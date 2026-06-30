"""#265 — central BRANDING config (single source of truth). White-label / rebrand ready.

ALL brand identity lives HERE + in the swappable asset files under `static/brand/`:

  * LOGO ASSET SLOTS — `static/brand/mark.svg` (+ `logo-light.svg` / `logo-dark.svg`).
    Replace the FILE (same path) to rebrand the whole app + every report with NO code
    change. App pages reference it via `mark_img()` (an `<img>`, served + cached);
    standalone reports inline it via `star_svg()` (read from the file → self-contained PDF).
  * BRAND COLOUR TOKENS — the `BRAND` dict is the single source for the `:root` design
    tokens (and report letterhead colours). Update here for a colourway change → it
    propagates site-wide via `tokens_css()` / the `:root` block.
  * COMPANY NAME / wordmark — `COMPANY_NAME`.

A future admin "Branding" settings surface (upload a logo + set colours) plugs into this
config with no rework: it writes the asset file and the token values.

LAYOUT SAFETY: the logo always renders in a FIXED-SPACE, aspect-ratio-safe container —
the SVG carries `preserveAspectRatio`, and the `.ssc-logo-mark` / brand-mark CSS uses
`object-fit:contain` + a reserved height/max-width — so a swapped logo of ANY dimensions
scales to fit WITHOUT distortion and WITHOUT shifting surrounding layout.
"""
from __future__ import annotations

import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
BRAND_DIR = SCRIPT_DIR / "static" / "brand"

COMPANY_NAME = "Superstars Contracting"

# ── Brand colour tokens — the SINGLE source for :root (widgets.css) + report letterheads.
BRAND = {
    "red": "#B11E2E", "red_deep": "#8B1623",
    "accent": "#4364dc", "accent_ink": "#3a5fd0",
    "ink": "#14161C", "mute": "#76777E", "cream": "#FAF7F1",
}
# back-compat aliases used by some renderers
BRAND_RED = BRAND["red"]
INK = BRAND["ink"]
MUTE = BRAND["mute"]
CREAM = BRAND["cream"]

# ── Logo asset slots. Swap the FILE to rebrand. URL = served path; mark_path() = on disk.
_SLOTS = {"mark": "mark.svg", "light": "logo-light.svg", "dark": "logo-dark.svg"}

# A distinctive substring of the canonical star, used by the design guard to confirm the
# real mark asset is present (geometry is stable regardless of size/colourway).
CANONICAL_SIGNATURE = "38.78,34.55"

# Fallback canonical star inner markup — used only if the asset file is missing, so the app
# never renders logo-less. The asset file static/brand/mark.svg is the real swap point.
_FALLBACK_STAR_INNER = (
    '<defs>'
    '<linearGradient id="topRL" x1="0%" y1="0%" x2="70%" y2="100%">'
    '<stop offset="0%" stop-color="#E0394E"/><stop offset="100%" stop-color="#A01829"/></linearGradient>'
    '<linearGradient id="topRD" x1="100%" y1="0%" x2="30%" y2="100%">'
    '<stop offset="0%" stop-color="#831321"/><stop offset="100%" stop-color="#4A0A12"/></linearGradient>'
    '</defs>'
    '<polygon fill="url(#topRL)" points="50,50 38.78,34.55 50,0"/>'
    '<polygon fill="url(#topRD)" points="50,50 50,0 61.22,34.55"/>'
    '<polygon fill="url(#topRL)" points="50,50 61.22,34.55 97.55,34.55"/>'
    '<polygon fill="url(#topRD)" points="50,50 97.55,34.55 68.16,55.91"/>'
    '<polygon fill="url(#topRL)" points="50,50 68.16,55.91 79.39,90.45"/>'
    '<polygon fill="url(#topRD)" points="50,50 79.39,90.45 50,69.1"/>'
    '<polygon fill="url(#topRL)" points="50,50 50,69.1 20.61,90.45"/>'
    '<polygon fill="url(#topRD)" points="50,50 20.61,90.45 31.84,55.91"/>'
    '<polygon fill="url(#topRL)" points="50,50 31.84,55.91 2.45,34.55"/>'
    '<polygon fill="url(#topRD)" points="50,50 2.45,34.55 38.78,34.55"/>'
    '<polygon fill="#FAF7F1" points="50,30 55.61,44.27 70.39,44.27 58.39,53.46 63,67.73 '
    '50,59.05 37,67.73 41.61,53.46 29.61,44.27 44.39,44.27"/>'
)


def mark_url(dark: bool = False, slot: str = None) -> str:
    """Served URL of the logo asset for the given context (dark → the dark slot)."""
    return f"/files/static/brand/{_SLOTS[slot or ('dark' if dark else 'mark')]}"


def mark_path(dark: bool = False, slot: str = None) -> Path:
    return BRAND_DIR / _SLOTS[slot or ('dark' if dark else 'mark')]


def _mark_inner(dark: bool = False) -> str:
    """The inner SVG (defs + polygons) of the mark asset, read FRESH from the file so a swap
    of static/brand/*.svg propagates to inline (report) usages immediately. Falls back to the
    canonical constant only if the file is missing/unreadable."""
    try:
        svg = mark_path(dark).read_text(encoding="utf-8")
        m = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.DOTALL)
        inner = (m.group(1) if m else svg).strip()
        # drop a standalone <title> (decor only) so inline use stays clean
        inner = re.sub(r"<title>.*?</title>", "", inner, flags=re.DOTALL).strip()
        return inner or _FALLBACK_STAR_INNER
    except OSError:
        return _FALLBACK_STAR_INNER


def star_svg(px=None, cls: str = "ssc-logo-mark", dark: bool = False) -> str:
    """The mark as an INLINE <svg> (reads static/brand/mark.svg) — for STANDALONE reports
    (self-contained PDF, no server dependency). `px` sets width/height; px=None lets CSS size
    it via `cls`. preserveAspectRatio keeps it undistorted at any box size."""
    size = f' width="{px}" height="{px}"' if px else ""
    return (f'<svg class="{cls}"{size} viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet" '
            f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{_mark_inner(dark)}</svg>')


def mark_img(px=None, cls: str = "ssc-logo-mark", dark: bool = False, alt: str = None) -> str:
    """The mark as an <img> referencing the swappable asset FILE — for APP PAGES (served).
    Swap the file → swaps everywhere, no code change. The .ssc-logo-mark CSS adds
    object-fit:contain so a logo of any aspect ratio scales to fit without distortion."""
    size = f' width="{px}" height="{px}"' if px else ""
    return f'<img class="{cls}"{size} src="{mark_url(dark)}" alt="{alt or COMPANY_NAME}">'


def tokens_css() -> str:
    """The :root brand-token block — the SINGLE source for the colourway. Inlined into
    widgets.css (app) and available to report letterheads."""
    b = BRAND
    return (":root{"
            f"--brand-red:{b['red']};--brand-red-deep:{b['red_deep']};"
            f"--accent:{b['accent']};--accent-ink:{b['accent_ink']};"
            f"--ink:{b['ink']};--mute:{b['mute']};--cream:{b['cream']};}}")


def lockup_css(dark: bool = False) -> str:
    """Inline CSS for the lockup — for STANDALONE report HTML. Aspect-safe (object-fit:contain
    + reserved height) so a swapped logo never distorts or shifts the letterhead."""
    name_color = "#ffffff" if dark else BRAND["ink"]
    sub_color = "rgba(255,255,255,.72)" if dark else BRAND["mute"]
    return (
        ".ssc-logo{display:inline-flex;align-items:center;gap:11px;}"
        ".ssc-logo-mark{flex:none;display:block;height:36px;width:auto;max-width:180px;object-fit:contain;}"
        ".ssc-logo-text{line-height:1.12;}"
        ".ssc-logo-name{font-family:'Archivo','Helvetica Neue',Helvetica,Arial,sans-serif;"
        f"font-size:17px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:{name_color};}}"
        ".ssc-logo-sub{font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;"
        f"color:{sub_color};margin-top:2px;}}"
    )


def lockup_html(subtitle: str = "", dark: bool = False, px: int = 40,
                name: str = None, inline: bool = True) -> str:
    """Full canonical lockup: mark + wordmark (+ optional subtitle). `inline=True` embeds the
    SVG (reports, self-contained); `inline=False` uses an <img> to the asset file (served
    pages). The report renderers call this with inline=True + embed lockup_css(dark)."""
    cls = "ssc-logo ssc-logo--dark" if dark else "ssc-logo"
    mark = star_svg(px=px, dark=dark) if inline else mark_img(px=px, dark=dark)
    sub = f'<div class="ssc-logo-sub">{subtitle}</div>' if subtitle else ""
    return (f'<div class="{cls}">{mark}'
            f'<div class="ssc-logo-text"><div class="ssc-logo-name">{name or COMPANY_NAME}</div>{sub}</div></div>')
