# generator/main.py
"""
Orkestrasyon. GitHub Actions her turda `python -m generator.main run` cagirir.

AKIS (iki fazli - kasitli):
  FAZ A  yeni icerik icin gorsel uret -> docs/img/ altina yaz.
         Actions bunlari commit'ler, GitHub Pages yayinlar.
  FAZ B  docs/img/'deki gorselin adresi GERCEKTEN 200 donuyorsa postu
         Buffer'a planla.

Neden iki faz: Buffer'in medya yukleme ucu yok; gorselin herkese acik bir
HTTPS adresinde durmasini ve post yayinlanana kadar orada kalmasini istiyor.
Gorseli ayni turda commit'leyip ayni anda Buffer'a bildirirsek adres henuz
yayinda olmayabilir. Bu yuzden planlama, adres canli dogrulanana kadar bir
sonraki tura ertelenir.

Komutlar:
  probe   Buffer semasini okur (kanal/organizasyon sorgusunun adini bulmak icin)
  plan    hicbir sey gondermez; ne zaman ne planlanacagini yazar (DRY-RUN)
  run     gercek is
"""
import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx
import yaml

from .brand import resolve_logo
from .buffer_client import BufferClient, BufferError
from .card import render_news_card, render_text_card, fetch_image, asset_name
from .plan import build_text, next_slots, now_tr, parse_iso, parse_slots, to_utc_iso
from .sources import fetch_og_image, from_pool, from_rss

ROOT = Path(__file__).resolve().parent.parent
IMG_DIR = ROOT / "docs" / "img"
STATE_PATH = ROOT / "state.json"

log = logging.getLogger("main")


def load_config() -> dict:
    with open(ROOT / "config.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_state() -> dict:
    if STATE_PATH.exists():
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {"channels": {}}


def save_state(state: dict):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)


def _bucket(state, name):
    ch = state.setdefault("channels", {}).setdefault(name, {})
    ch.setdefault("seen", [])
    ch.setdefault("rendered", [])    # gorsel uretildi, adres canli olmayi bekliyor
    ch.setdefault("scheduled", [])   # Buffer'a verildi
    return ch


async def url_is_live(client: httpx.AsyncClient, url: str) -> bool:
    """Buffer gorseli cekebilecek mi? Tam olarak onu test ediyoruz."""
    try:
        r = await client.get(url, timeout=20, follow_redirects=True)
        return r.status_code == 200 and r.headers.get("content-type", "").startswith("image/")
    except Exception:
        return False


async def gather_items(client, ch: dict) -> list[dict]:
    src = (ch.get("source") or "pool").lower()
    if src == "rss":
        return await from_rss(client, ch.get("rss_url", ""))
    return from_pool(ch.get("pool", []))


async def render_one(client, item: dict, ch: dict) -> str:
    """Gorseli uretir, docs/img altindaki dosya adini doner."""
    template = (ch.get("template") or "news").lower()
    label = item.get("label") or ch.get("default_label", "")
    name = asset_name(item["key"], ch["name"])
    out = IMG_DIR / name

    if out.exists():
        return name

    # Logo varsayilan olarak KAPALI: marka adinda "bet" gectigi icin spor/sosyal
    # hesaplarda X'in spam filtrelerini tetikleme riski var. Kanal bazinda
    # config'ten "brand" veya bir dosya yolu ile acilabilir.
    mark = dict(logo_file=resolve_logo(ch.get("logo", "none")),
                watermark_text=ch.get("watermark_text", ""))

    if template == "text":
        render_text_card(item["title"], item.get("summary", ""), out, label=label, **mark)
        return name

    image_url = item.get("image")
    if not image_url and item.get("link") and ch.get("fetch_og_image", True):
        image_url = await fetch_og_image(client, item["link"])
    bg = await fetch_image(client, image_url) if image_url else None
    render_news_card(item["title"], item.get("summary", ""), out,
                     bg=bg, label=label or "Spor", **mark)
    return name


async def process_channel(client, conf, state, ch: dict, bc: BufferClient | None, dry: bool):
    name = ch["name"]
    b = _bucket(state, name)
    base = conf.get("pages_base_url", "").rstrip("/")
    queue_target = int(ch.get("queue_target", 8))
    slots = parse_slots(ch.get("slots", ["10:00", "19:00"]))
    now = now_tr()

    # Yayinlanmis olanlari kuyruktan dus (dueAt gecmisse Buffer atmistir).
    still_pending = []
    for s in b["scheduled"]:
        if parse_iso(s["due_at"]) > now:
            still_pending.append(s)
        else:
            b["seen"].append(s["key"])
    b["scheduled"] = still_pending
    # seen sinirsiz buyumesin; sirayi koruyarak tekrarlari at ve son 2000'i tut.
    b["seen"] = list(dict.fromkeys(b["seen"]))[-2000:]
    pending_due = [parse_iso(s["due_at"]) for s in still_pending]

    known = set(b["seen"]) | {r["key"] for r in b["rendered"]} | {s["key"] for s in still_pending}

    # ---- FAZ A: yeni icerik icin gorsel uret ----
    items = await gather_items(client, ch)
    fresh = [i for i in items if i["key"] not in known]
    # Kuyrukta yer kadar + bir tur pay kadar uret; fazlasi bosuna repo sisirir.
    render_budget = max(0, queue_target - len(still_pending) - len(b["rendered"]))
    for item in fresh[:render_budget]:
        try:
            asset = await render_one(client, item, ch)
            b["rendered"].append({
                "key": item["key"], "asset": asset,
                "text": build_text(item, ch),
            })
            log.info(f"[{name}] gorsel uretildi: {asset}  <- {item['title'][:60]}")
        except Exception as e:
            log.warning(f"[{name}] gorsel uretilemedi ({item['title'][:40]}): {e}")

    if not b["rendered"]:
        log.info(f"[{name}] planlanacak yeni icerik yok (bekleyen: {len(still_pending)}).")
        return

    # ---- FAZ B: adresi canli olanlari Buffer'a planla ----
    free = queue_target - len(still_pending)
    if free <= 0:
        log.info(f"[{name}] kuyruk dolu ({len(still_pending)}/{queue_target}), planlama yok.")
        return

    ready, waiting = [], []
    for r in b["rendered"]:
        url = f"{base}/img/{r['asset']}"
        if dry or await url_is_live(client, url):
            ready.append((r, url))
        else:
            waiting.append(r)
    if waiting:
        log.info(f"[{name}] {len(waiting)} gorsel henuz Pages'te yayinda degil, "
                 f"bir sonraki tura birakildi.")

    ready = ready[:free]
    times = next_slots(len(ready), pending_due, slots,
                       min_gap_hours=float(ch.get("min_gap_hours", 6)),
                       min_lead_minutes=int(ch.get("min_lead_minutes", 90)), now=now)

    done_keys = set()
    for (r, url), when in zip(ready, times):
        if dry:
            log.info(f"[{name}] DRY-RUN {when:%d.%m %H:%M} TR | {url}\n{r['text']}\n---")
            done_keys.add(r["key"])
            continue
        try:
            pid = await bc.create_post(client, channel_id=ch["buffer_channel_id"],
                                       text=r["text"], due_at_iso=to_utc_iso(when),
                                       image_url=url)
            b["scheduled"].append({"key": r["key"], "post_id": pid,
                                   "due_at": when.isoformat(), "asset": r["asset"]})
            done_keys.add(r["key"])
            log.info(f"[{name}] planlandi {when:%d.%m %H:%M} TR (post={pid})")
        except BufferError as e:
            log.error(f"[{name}] Buffer reddetti: {e}")
            break

    b["rendered"] = [r for r in b["rendered"] if r["key"] not in done_keys]


async def run(dry: bool):
    conf = load_config()
    state = load_state()
    IMG_DIR.mkdir(parents=True, exist_ok=True)

    bc = None
    if not dry:
        bc = BufferClient(os.environ.get("BUFFER_API_KEY", ""))

    async with httpx.AsyncClient() as client:
        for ch in conf.get("channels", []):
            if not ch.get("enabled", True):
                continue
            if not dry and not ch.get("buffer_channel_id"):
                log.warning(f"[{ch['name']}] buffer_channel_id yok, atlandi.")
                continue
            try:
                await process_channel(client, conf, state, ch, bc, dry)
            except Exception as e:
                log.exception(f"[{ch['name']}] tur hatasi: {e}")

    if dry:
        log.info("DRY-RUN: state.json'a dokunulmadi (gorseller docs/img altina yazildi).")
        return
    save_state(state)
    log.info("state.json guncellendi.")


async def probe():
    bc = BufferClient(os.environ.get("BUFFER_API_KEY", ""))
    async with httpx.AsyncClient() as client:
        data = await bc.probe(client)
    schema = data.get("__schema", {})
    print("\n=== Query alanlari (kanal/organizasyon sorgusunu burada arayin) ===")
    for f in (schema.get("queryType") or {}).get("fields", []):
        print(f"  {f['name']:28s} {(f.get('description') or '')[:70]}")
    print("\n=== Mutation alanlari ===")
    for f in (schema.get("mutationType") or {}).get("fields", []):
        print(f"  {f['name']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["run", "plan", "probe"])
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    if args.command == "probe":
        asyncio.run(probe())
    else:
        asyncio.run(run(dry=(args.command == "plan")))


if __name__ == "__main__":
    main()
