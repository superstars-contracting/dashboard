#!/usr/bin/env python3
"""Generate signage HTML wrappers from source PDFs (#168).

For each sign with a source PDF in signage_source/:
  1. Render source PDF page 1 to a high-DPI PNG (300 DPI).
  2. (Restricted Area only) crop the top-left quadrant of the 4-up sheet.
  3. Base64-embed the PNG into a self-contained Letter-landscape HTML
     wrapper (full-bleed, no margins, no added typography).
  4. Save the wrapper at signage_templates_source/<slug>.html.

The wrapper renders to PDF via the existing headless-Edge pipeline
(apply_signage_templates_seed.py). Output: data_room/signage/<slug>.pdf
which IS the source sign, normalized to Letter landscape.

Dress Code (no source PDF) is built separately in the file
dress_code_ppe_*.html — see Path-B per HANDOFF_SIGNS_USE_SOURCE_PDFS.

This module is idempotent: re-running with unchanged sources produces
identical wrapper HTMLs.
"""
import base64
import io
from pathlib import Path

import pypdfium2 as pp
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
SOURCES = SCRIPT_DIR / "signage_source"
WRAPPERS = SCRIPT_DIR / "signage_templates_source"

# (source_filename, output_slug, optional crop spec)
# crop spec: None = no crop; "top-left-quadrant" = take the upper-left
# quarter of the page (for the 4-up U-1012-01 sticker sheet).
EMBEDS = [
    ("hard-hat-area-danger-sign.pdf",                 "danger_hard_hat_area",               None),
    ("WARN0034__86149.pdf",                           "warning_men_working_above",          None),
    ("construction-in-progress-caution-sign.pdf",     "caution_construction_in_progress",   None),
    ("all-ppe-required-notice-sign-s-9775.pdf",       "notice_all_ppe_required",            None),
    ("keep-work-area-clean-notice-sign.pdf",          "notice_keep_work_area_clean",        None),
    ("landscape-no-smoking-sign.pdf",                 "no_smoking",                         None),
    ("en.U-1012-01.4UpSignLabel.Restricted_Construction.WorkInProgress.1908-01.pdf",
                                                      "restricted_area_construction",       "top-left-quadrant"),
    ("G2547.pdf",                                     "dob_g2547",                          None),
    ("G2729.pdf",                                     "dob_g2729",                          None),
    ("G2729BI.pdf",                                   "dob_g2729_bilingual",                None),
]


def render_source_to_png(src_pdf: Path, dpi: int = 300) -> Image.Image:
    """Render the first page of a source PDF to a PIL Image at the given DPI."""
    doc = pp.PdfDocument(str(src_pdf))
    try:
        page = doc[0]
        bitmap = page.render(scale=dpi / 72.0)
        return bitmap.to_pil()
    finally:
        doc.close()


def crop_top_left_quadrant(img: Image.Image) -> Image.Image:
    """Return the top-left quadrant of an image."""
    w, h = img.size
    return img.crop((0, 0, w // 2, h // 2))


def png_to_data_url(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


WRAPPER_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
  @page {{ size: Letter landscape; margin: 0; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; width: 11in; height: 8.5in; background: #fff; }}
  body {{ display: flex; align-items: center; justify-content: center; }}
  img {{
    display: block;
    max-width: 11in;
    max-height: 8.5in;
    width: auto;
    height: auto;
    object-fit: contain;
  }}
</style>
</head>
<body>
<img src="{data_url}" alt="{title}">
</body>
</html>
"""


def main():
    if not SOURCES.exists():
        print(f"ERROR: signage_source dir not found at {SOURCES}")
        return 1
    WRAPPERS.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    for src_name, slug, crop in EMBEDS:
        src = SOURCES / src_name
        if not src.exists():
            print(f"  MISSING source: {src_name}  (skipped)")
            skipped += 1
            continue
        img = render_source_to_png(src, dpi=300)
        if crop == "top-left-quadrant":
            img = crop_top_left_quadrant(img)
        # Resize huge source PDFs down to a sane embed size (3300px max on
        # the long edge = 300 DPI at Letter landscape). Anything beyond
        # that is wasted bytes — the page only prints at 11x8.5 inches.
        MAX_PX = 3300
        if max(img.size) > MAX_PX:
            scale = MAX_PX / max(img.size)
            new_size = (int(img.size[0] * scale), int(img.size[1] * scale))
            img = img.resize(new_size, Image.LANCZOS)
        data_url = png_to_data_url(img)
        html = WRAPPER_TEMPLATE.format(title=slug.replace("_", " ").title(),
                                       data_url=data_url)
        out = WRAPPERS / f"{slug}.html"
        out.write_text(html, encoding="utf-8")
        written += 1
        print(f"  wrapped  {src_name:60} -> {slug}.html  (img {img.size[0]}x{img.size[1]}, html {out.stat().st_size//1024}KB)")
    print(f"\n[signage-gen] wrappers written: {written}  missing sources: {skipped}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
