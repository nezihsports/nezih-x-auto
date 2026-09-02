# generator/plan.py
"""
Zamanlama mantigi.

Buffer UCRETSIZ planinda sinir "ayda 10 post" DEGIL, "kanal basina ayni anda
10 BEKLEYEN post". Bir post yayinlandigi anda slot bosalir. Yani aylik bir
kota bolusturmuyoruz; kuyrugu surekli dolu tutuyoruz:

    her turda -> bekleyen post sayisi < queue_target ise, aradaki farki
                 gelecekteki bos slotlara yerlestir.

posts_per_day slotlari config'te saat olarak verilir (Turkiye saati). Iki post
arasinda en az min_gap_hours birakilir; hicbir post simdiden min_lead_minutes
once konumlandirilmaz (gorselin Pages'e yayilmasi icin pay).
"""
from datetime import datetime, timedelta, timezone, time as dtime

# Turkiye 2016'dan beri yil boyu UTC+3, yaz saati uygulamasi yok.
# Sabit offset kullanmak zoneinfo/tzdata bagimliligini ortadan kaldiriyor.
TR = timezone(timedelta(hours=3))


def now_tr() -> datetime:
    return datetime.now(TR)


def parse_slots(slots: list[str]) -> list[tuple[int, int]]:
    out = []
    for s in slots or []:
        hh, _, mm = str(s).partition(":")
        out.append((int(hh), int(mm or 0)))
    return sorted(out) or [(10, 0)]


def to_utc_iso(dt: datetime) -> str:
    """Buffer dueAt formati: 2026-09-05T17:00:00.000Z"""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(TR)


def next_slots(count: int, pending_due: list[datetime], slots: list[tuple[int, int]],
               min_gap_hours: float = 6, min_lead_minutes: int = 90,
               now: datetime | None = None) -> list[datetime]:
    """
    Bekleyen postlardan SONRA gelen, birbirinden min_gap_hours ayri `count`
    adet uygun zaman dondurur.
    """
    now = now or now_tr()
    gap = timedelta(hours=min_gap_hours)
    cursor = now + timedelta(minutes=min_lead_minutes)

    future = [d for d in pending_due if d > now]
    if future:
        cursor = max(cursor, max(future) + gap)

    out: list[datetime] = []
    day = cursor.date()
    guard = 0
    while len(out) < count and guard < 400:
        guard += 1
        for hh, mm in slots:
            cand = datetime.combine(day, dtime(hh, mm), tzinfo=TR)
            if cand < cursor:
                continue
            if out and (cand - out[-1]) < gap:
                continue
            out.append(cand)
            if len(out) >= count:
                break
        day += timedelta(days=1)
    return out


def build_text(item: dict, ch: dict) -> str:
    """X icin metin. Buffer uzerinden gittigi icin link maliyeti YOK - link acik."""
    limit = int(ch.get("max_chars", 275))
    tail_parts = []
    if ch.get("hashtags"):
        tail_parts.append(str(ch["hashtags"]).strip())
    if ch.get("signature"):
        tail_parts.append(str(ch["signature"]).strip())
    if ch.get("include_link", True) and item.get("link"):
        tail_parts.append(item["link"])
    tail = "\n\n".join(p for p in tail_parts if p)

    # X her URL'yi t.co olarak 23 karakter sayar.
    tail_cost = 0
    if tail:
        tail_cost = 2 + sum(23 if p.startswith("http") else len(p) for p in tail_parts) \
                      + 2 * (len(tail_parts) - 1)

    budget = limit - tail_cost
    title = (item.get("title") or "").strip()
    summary = (item.get("summary") or "").strip()

    body = title
    if summary and ch.get("include_summary", True):
        room = budget - len(title) - 2
        if room >= 40:
            s = summary if len(summary) <= room else summary[:room - 1].rsplit(" ", 1)[0] + "…"
            body = f"{title}\n\n{s}"
    if len(body) > budget:
        body = body[:max(1, budget - 1)].rsplit(" ", 1)[0] + "…"

    return (body + ("\n\n" + tail if tail else "")).strip()
