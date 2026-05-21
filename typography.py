"""Single source of truth for the dashboard's typography (Archivo + Inter).

Web pages use the static CSS via:
    <link rel="stylesheet" href="/files/static/fonts/typography.css">

Generated documents (DCRs, cards, weekly summaries, lookaheads — anything
piped through headless Edge to PDF, or archived/emailed as standalone
HTML) inline the base64-embedded version via get_inlined_style_tag().
That keeps the rendered output self-contained: no network fetch, no
relative font-path dependency, no risk of the PDF falling back to Times
because the woff2 wasn't reachable.

Both fonts are variable woff2 (one file per family, full 100..900 weight
axis). Latin subset only — covers EN/ES dashboard surfaces.
"""
import base64
from functools import lru_cache
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
FONTS_DIR = SCRIPT_DIR / "static" / "fonts"

INTER_STACK = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif"
ARCHIVO_STACK = "'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif"


@lru_cache(maxsize=1)
def _archivo_b64():
    return base64.b64encode((FONTS_DIR / "Archivo-latin.woff2").read_bytes()).decode("ascii")


@lru_cache(maxsize=1)
def _inter_b64():
    return base64.b64encode((FONTS_DIR / "Inter-latin.woff2").read_bytes()).decode("ascii")


@lru_cache(maxsize=1)
def get_inlined_css():
    """Return the full @font-face block (base64-embedded woff2) + base
    typography rules, as a CSS string. Suitable for placing inside a
    <style> tag in a self-contained rendered document."""
    return (
        "@font-face {\n"
        "  font-family: 'Archivo';\n"
        "  font-style: normal;\n"
        "  font-weight: 100 900;\n"
        "  font-display: swap;\n"
        f"  src: url(data:font/woff2;base64,{_archivo_b64()}) format('woff2');\n"
        "}\n"
        "@font-face {\n"
        "  font-family: 'Inter';\n"
        "  font-style: normal;\n"
        "  font-weight: 100 900;\n"
        "  font-display: swap;\n"
        f"  src: url(data:font/woff2;base64,{_inter_b64()}) format('woff2');\n"
        "}\n"
        "html, body {\n"
        f"  font-family: {INTER_STACK};\n"
        "}\n"
        "h1, h2, h3, h4, h5, h6,\n"
        ".archivo, .title, .heading {\n"
        f"  font-family: {ARCHIVO_STACK};\n"
        "  letter-spacing: -0.01em;\n"
        "}\n"
    )


def get_inlined_style_tag():
    """Wrap get_inlined_css() in a <style> tag for direct injection into
    a rendered HTML document's <head>."""
    return f"<style>\n{get_inlined_css()}</style>"
