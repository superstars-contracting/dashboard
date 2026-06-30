"""#265 — the ONE canonical Superstars Contracting logo lockup. Single source of truth.

The brand mark, everywhere (app headers + every generated report), is ONE lockup:
a SOLID, FILLED, faceted brand-red star (the Office Console treatment) + the
"Superstars Contracting" wordmark + an optional section subtitle.

NEVER the hollow / outline star (the "rinky dink" variant) — that geometry is banned and
guarded against (smoke_design_conventions). The star is IDENTICAL on every surface; only
the wordmark TEXT colour adapts to the section background:
  * LIGHT / white sections -> ink wordmark   (lockup_html(dark=False))
  * DARK / black sections   -> white wordmark (lockup_html(dark=True))

This module is imported by the report renderers (render_*.py) so a future logo change
touches ONE place. The HTML app pages inline the SAME `STAR_SVG` markup (kept identical;
the guard enforces it). The canonical star geometry below is copied verbatim from the
Office Console (company-dashboard.html) — the operator's reference.
"""
from __future__ import annotations

# Brand tokens
BRAND_RED = "#B11E2E"
INK = "#14161C"
MUTE = "#76777E"
CREAM = "#FAF7F1"

# The canonical faceted star INNER markup (defs + facet polygons + cream inner star).
# viewBox is 0 0 100 100. The two red gradients (topRL/topRD) give the solid star its
# faceted depth; the final cream polygon is the inner star. DO NOT replace with an
# outline/hollow star.
_STAR_DEFS_AND_POLYS = (
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

# A distinctive substring of the canonical star, used by the design guard to confirm the
# real lockup is present (geometry is stable regardless of size/class).
CANONICAL_SIGNATURE = '38.78,34.55'


def star_svg(px=None, cls: str = "ssc-logo-mark") -> str:
    """The canonical filled star as a standalone <svg>. Pass `px` to set width/height
    attributes (standalone reports); pass px=None to let CSS size it via `cls` (app page
    headers, matching the Office Console). Identical geometry everywhere it's inlined."""
    size = f' width="{px}" height="{px}"' if px else ""
    return (
        f'<svg class="{cls}"{size} viewBox="0 0 100 100" '
        f'xmlns="http://www.w3.org/2000/svg" aria-hidden="true">{_STAR_DEFS_AND_POLYS}</svg>'
    )


def lockup_css(dark: bool = False) -> str:
    """Inline CSS for the lockup — for STANDALONE report HTML (which doesn't load
    widgets.css). App pages use the shared .ssc-logo rules in static/css/widgets.css."""
    name_color = "#ffffff" if dark else INK
    sub_color = "rgba(255,255,255,.72)" if dark else MUTE
    return (
        ".ssc-logo{display:inline-flex;align-items:center;gap:11px;}"
        ".ssc-logo-mark{flex:none;display:block;}"
        ".ssc-logo-text{line-height:1.12;}"
        ".ssc-logo-name{font-family:'Archivo','Helvetica Neue',Helvetica,Arial,sans-serif;"
        f"font-size:17px;font-weight:700;letter-spacing:.5px;text-transform:uppercase;color:{name_color};}}"
        ".ssc-logo-sub{font-size:10px;font-weight:600;letter-spacing:1px;text-transform:uppercase;"
        f"color:{sub_color};margin-top:2px;}}"
    )


def lockup_html(subtitle: str = "", dark: bool = False, px: int = 42,
                name: str = "Superstars Contracting") -> str:
    """The full canonical lockup: filled star + wordmark (+ optional subtitle). Use
    dark=True on dark/black header backgrounds (white wordmark). The report renderers
    call this; they also embed lockup_css(dark) once in their <style>."""
    cls = "ssc-logo ssc-logo--dark" if dark else "ssc-logo"
    sub = f'<div class="ssc-logo-sub">{subtitle}</div>' if subtitle else ""
    return (
        f'<div class="{cls}">{star_svg(px)}'
        f'<div class="ssc-logo-text"><div class="ssc-logo-name">{name}</div>{sub}</div></div>'
    )
