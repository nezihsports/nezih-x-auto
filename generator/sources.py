# generator/sources.py
"""
Icerik kaynaklari.

  rss  : bir RSS 2.0 / Atom beslemesinden yeni haberler (nezihsport icin)
  pool : config'teki sabit icerik havuzundan sirayla (nezihsosyal / nezihbet
         gibi haber beslemesi olmayan hesaplar icin)

Her kaynak ayni sekli dondurur:
    {"key": tekil kimlik, "title": ..., "summary": ..., "image": url|None,
     "label": rozet metni}
"key" tekrari onlemek icin state.json'da saklanir.
"""
import hashlib
import logging
import re
import xml.etree.ElementTree as ET

import httpx

log = logging.getLogger("sources")

_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"
_IMG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.I)
_OG_RE = re.compile(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', re.I)
_OG_RE_ALT = re.compile(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', re.I)


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


def _key(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:16]


def _rss2(item):
    title = _clean(item.findtext("title") or "")
    link = (item.findtext("link") or "").strip()
    guid = (item.findtext("guid") or link).strip()
    summary = _clean(item.findtext("description") or "")
    category = _clean(item.findtext("category") or "")

    image = None
    for finder in (f"{_MEDIA}content", f"{_MEDIA}thumbnail", "enclosure"):
        el = item.find(finder)
        if el is not None and el.get("url"):
            image = el.get("url")
            break
    if not image:
        ce = item.find(f"{_CONTENT}encoded")
        if ce is not None and ce.text:
            m = _IMG_RE.search(ce.text)
            if m:
                image = m.group(1)

    if not title:
        return None
    return {"key": _key(guid or title), "title": title, "summary": summary,
            "image": image, "label": category or "Spor", "link": link}


def _atom(entry):
    te = entry.find(f"{_ATOM}title")
    title = _clean(te.text if te is not None else "")
    link = ""
    for le in entry.findall(f"{_ATOM}link"):
        if le.get("href"):
            link = le.get("href")
            break
    ie = entry.find(f"{_ATOM}id")
    guid = (ie.text or link).strip() if ie is not None and ie.text else link
    se = entry.find(f"{_ATOM}summary")
    summary = _clean(se.text if se is not None else "")
    ce = entry.find(f"{_ATOM}category")
    category = ce.get("term", "") if ce is not None else ""

    image = None
    co = entry.find(f"{_ATOM}content")
    if co is not None and co.text:
        m = _IMG_RE.search(co.text)
        if m:
            image = m.group(1)

    if not title:
        return None
    return {"key": _key(guid or title), "title": title, "summary": summary,
            "image": image, "label": category or "Spor", "link": link}


async def fetch_og_image(client: httpx.AsyncClient, url: str):
    try:
        r = await client.get(url, timeout=20, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        m = _OG_RE.search(r.text) or _OG_RE_ALT.search(r.text)
        return m.group(1) if m else None
    except Exception as e:
        log.debug(f"og:image alinamadi ({url}): {e}")
        return None


async def from_rss(client: httpx.AsyncClient, url: str) -> list[dict]:
    try:
        r = await client.get(url, timeout=25, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:
        log.warning(f"RSS okunamadi ({url}): {e}")
        return []

    tag = root.tag.split("}")[-1]
    out = []
    if tag == "rss":
        ch = root.find("channel")
        for it in (ch.findall("item") if ch is not None else []):
            p = _rss2(it)
            if p:
                out.append(p)
    elif tag == "feed":
        for e in root.findall(f"{_ATOM}entry"):
            p = _atom(e)
            if p:
                out.append(p)
    else:
        log.warning(f"RSS taninmayan kok etiket <{tag}>: {url}")
    return out


def from_pool(entries: list) -> list[dict]:
    """config.yaml'daki sabit havuz. Her giris: {title, summary?, label?}"""
    out = []
    for e in entries or []:
        if isinstance(e, str):
            e = {"title": e}
        title = (e.get("title") or "").strip()
        if not title:
            continue
        out.append({
            "key": _key("pool", title),
            "title": title,
            "summary": (e.get("summary") or "").strip(),
            "image": e.get("image"),
            "label": e.get("label", ""),
            "link": "",
        })
    return out
