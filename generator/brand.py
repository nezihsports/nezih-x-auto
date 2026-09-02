# generator/brand.py
"""Nezihbet marka sabitleri ve font cozumu.

Fontlar hem Windows'ta (yerel test) hem Ubuntu'da (GitHub Actions) bulunmali.
Bu yuzden aday listesi sirayla denenir; hicbiri yoksa PIL varsayilanina duser
(o durumda Turkce karakterler bozulabilir, bu yuzden repoya assets/fonts/
altina bir DejaVuSans koymak en garantisi).
"""
from pathlib import Path

from PIL import ImageFont

# Color-Codes.jpg'den
GOLD = "#d7bf8e"
NAVY_DARK = "#0d1526"
NAVY_MID = "#222c41"
WHITE = "#ffffff"
MUTED = "#9aa6bd"

_ROOT = Path(__file__).resolve().parent.parent

_BOLD = [
    _ROOT / "assets/fonts/DejaVuSans-Bold.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    Path("C:/Windows/Fonts/ArialNova-Bold.ttf"),
    Path("C:/Windows/Fonts/arialbd.ttf"),
]
_REGULAR = [
    _ROOT / "assets/fonts/DejaVuSans.ttf",
    Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    Path("C:/Windows/Fonts/ArialNova.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
]


def font(size: int, bold: bool = True):
    for p in (_BOLD if bold else _REGULAR):
        try:
            if p.exists():
                return ImageFont.truetype(str(p), size)
        except Exception:
            continue
    return ImageFont.load_default()


def resolve_logo(spec: str | None) -> Path | None:
    """
    Kanal basina logo secimi.

      "none"  (varsayilan) -> logo YOK. Marka logosunda "bet" gectigi icin
                              spor/sosyal hesaplarda spam filtresi riski var;
                              bu yuzden varsayilan kapali.
      "brand"              -> assets/logo.png
      "<yol>"              -> repoya gore veya mutlak bir dosya yolu

    Logo istemeyip yine de bir iz birakmak isteyen kanallar config'te
    watermark_text kullanabilir (bkz. card._paste_mark).
    """
    if not spec or spec == "none":
        return None
    p = (_ROOT / "assets" / "logo.png") if spec == "brand" else Path(spec)
    if not p.is_absolute():
        p = _ROOT / p
    return p if p.exists() else None
