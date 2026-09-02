# generator/card.py
"""
Otomatik gorsel uretimi (1200x675, X icin 16:9).

Iki sablon:
  render_news_card : arkaplanda haber gorseli + karartma + baslik seridi
  render_text_card : duz markali gradient kart (haber gorseli olmayan icerikler)

Ciktilar docs/img/ altina JPEG olarak yazilir; GitHub Pages bunlari
https://<kullanici>.github.io/<repo>/img/<ad>.jpg olarak yayinlar ve Buffer
tam olarak boyle herkese acik bir HTTPS URL bekler.
"""
import hashlib
import io
import logging
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFilter

from .brand import GOLD, NAVY_DARK, NAVY_MID, WHITE, MUTED, font

log = logging.getLogger("card")

W, H = 1200, 675
PAD = 64


def _hex(c: str):
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))


def _wrap(draw, text, fnt, max_w):
    """Kelime bazli sarma; tek kelime satira sigmiyorsa harf bazinda kirar."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= max_w:
            cur = trial
            continue
        if cur:
            lines.append(cur)
        if draw.textlength(w, font=fnt) <= max_w:
            cur = w
        else:
            piece = ""
            for ch in w:
                if draw.textlength(piece + ch, font=fnt) <= max_w:
                    piece += ch
                else:
                    lines.append(piece)
                    piece = ch
            cur = piece
    if cur:
        lines.append(cur)
    return lines


def _gradient(w, h, top, bottom):
    base = Image.new("RGB", (1, h))
    d = ImageDraw.Draw(base)
    t, b = _hex(top), _hex(bottom)
    for y in range(h):
        f = y / max(1, h - 1)
        d.point((0, y), fill=tuple(int(t[i] + (b[i] - t[i]) * f) for i in range(3)))
    return base.resize((w, h))


def _cover(img: Image.Image, w: int, h: int) -> Image.Image:
    """Orani bozmadan kirparak w x h'ye oturtur (CSS object-fit: cover)."""
    src_r, dst_r = img.width / img.height, w / h
    if src_r > dst_r:
        nw = int(img.height * dst_r)
        img = img.crop(((img.width - nw) // 2, 0, (img.width + nw) // 2, img.height))
    else:
        nh = int(img.width / dst_r)
        img = img.crop((0, (img.height - nh) // 2, img.width, (img.height + nh) // 2))
    return img.resize((w, h), Image.LANCZOS)


def _paste_mark(img: Image.Image, logo_file=None, watermark_text: str = "",
                height_ratio: float = 0.085, margin: int = 40):
    """
    Sag ustteki isaret. Once logo dosyasi, yoksa duz metin, o da yoksa hicbir sey.
    Marka logosu varsayilan olarak KAPALI - bkz. brand.resolve_logo.
    """
    if logo_file:
        try:
            logo = Image.open(logo_file).convert("RGBA")
            th = int(H * height_ratio)
            tw = int(logo.width * th / logo.height)
            logo = logo.resize((tw, th), Image.LANCZOS)
            img.paste(logo, (W - tw - margin, margin), logo)
            return
        except Exception as e:
            log.debug(f"logo eklenemedi ({logo_file}): {e}")

    if watermark_text:
        draw = ImageDraw.Draw(img)
        f = font(30, bold=True)
        tw = draw.textlength(watermark_text, font=f)
        draw.text((W - tw - margin, margin + 6), watermark_text, font=f, fill=_hex(GOLD))


def _badge(draw, x, y, text):
    f = font(24, bold=True)
    tw = draw.textlength(text, font=f)
    draw.rounded_rectangle([x, y, x + tw + 36, y + 46], radius=23, fill=_hex(GOLD))
    draw.text((x + 18, y + 9), text, font=f, fill=_hex(NAVY_DARK))
    return y + 46


def _finish(img: Image.Image, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.convert("RGB").save(out_path, "JPEG", quality=88, optimize=True)
    return out_path


def asset_name(seed: str, prefix: str = "card") -> str:
    """Icerikten deterministik dosya adi - ayni haber iki kez uretilse ayni ad."""
    return f"{prefix}-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:12]}.jpg"


async def fetch_image(client: httpx.AsyncClient, url: str):
    try:
        # follow_redirects sart: haber CDN'leri gorseli neredeyse her zaman
        # 301/302 ile baska bir adrese yonlendiriyor.
        r = await client.get(url, timeout=20, follow_redirects=True,
                             headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        return Image.open(io.BytesIO(r.content)).convert("RGB")
    except Exception as e:
        log.debug(f"arkaplan gorseli indirilemedi ({url}): {e}")
        return None


def render_news_card(title: str, subtitle: str, out_path: Path,
                     bg: Image.Image | None = None, label: str = "SPOR",
                     logo_file=None, watermark_text: str = "") -> Path:
    if bg is not None:
        img = _cover(bg, W, H).filter(ImageFilter.GaussianBlur(1.5))
        # Alt yariyi karart ki yazi her gorselde okunur kalsin
        shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shade)
        for y in range(H):
            f = max(0.0, (y / H - 0.18) / 0.82)
            sd.line([(0, y), (W, y)], fill=(5, 10, 20, int(245 * (f ** 1.3))))
        img = Image.alpha_composite(img.convert("RGBA"), shade).convert("RGB")
    else:
        img = _gradient(W, H, NAVY_MID, NAVY_DARK)

    draw = ImageDraw.Draw(img)
    draw.rectangle([0, H - 8, W, H], fill=_hex(GOLD))

    tf = font(52, bold=True)
    lines = _wrap(draw, title.strip(), tf, W - 2 * PAD)[:3]
    sf = font(28, bold=False)
    sub_lines = _wrap(draw, subtitle.strip(), sf, W - 2 * PAD)[:2] if subtitle else []

    block_h = len(lines) * 64 + (len(sub_lines) * 38 + 16 if sub_lines else 0)
    y = H - PAD - 8 - block_h

    _badge(draw, PAD, y - 74, label.upper())

    for ln in lines:
        draw.text((PAD + 2, y + 2), ln, font=tf, fill=(0, 0, 0))
        draw.text((PAD, y), ln, font=tf, fill=_hex(WHITE))
        y += 64
    if sub_lines:
        y += 16
        for ln in sub_lines:
            draw.text((PAD, y), ln, font=sf, fill=_hex(GOLD))
            y += 38

    _paste_mark(img, logo_file, watermark_text)
    return _finish(img, out_path)


def render_text_card(title: str, body: str, out_path: Path, label: str = "",
                     logo_file=None, watermark_text: str = "") -> Path:
    img = _gradient(W, H, NAVY_MID, NAVY_DARK)
    draw = ImageDraw.Draw(img)

    # Kose aksani
    draw.rectangle([0, 0, 10, H], fill=_hex(GOLD))
    draw.rectangle([0, H - 8, W, H], fill=_hex(GOLD))

    tf = font(58, bold=True)
    bf = font(30, bold=False)
    max_w = W - 2 * PAD - 40
    t_lines = _wrap(draw, title.strip(), tf, max_w)[:3]
    b_lines = _wrap(draw, body.strip(), bf, max_w)[:4] if body else []

    # Blogu dikeyde ortala; aksi halde kisa metinlerde alt yari bombos kaliyor.
    block_h = (76 if label else 0) + len(t_lines) * 72 + (18 + len(b_lines) * 42 if b_lines else 0)
    y = max(PAD, (H - block_h) // 2)

    if label:
        y = _badge(draw, PAD + 20, y, label.upper()) + 30
    for ln in t_lines:
        draw.text((PAD + 20, y), ln, font=tf, fill=_hex(WHITE))
        y += 72
    if b_lines:
        y += 18
        for ln in b_lines:
            draw.text((PAD + 20, y), ln, font=bf, fill=_hex(MUTED))
            y += 42

    _paste_mark(img, logo_file, watermark_text)
    return _finish(img, out_path)
