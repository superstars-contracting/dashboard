"""#174 / #178 — Bundle all worker credentials into a single printable PDF.

Per worker:
  - W-0001..W-0012: CoF card (front + back) — the CoF IS their badge.
  - W-0013, W-0014: Company ID card (front + back).

Total: 14 cards × 2 sides.

Layout (#178 lamination-friendly redesign): Letter LANDSCAPE, 2×2 grid
(4 CR80 cards per page), exactly 2.00" of empty space between adjacent
cards both directions, ~1.125" margin on every page edge. The 2" gap
gives the operator clean scissor / lamination-pouch room around each
card.

  Math check (Letter landscape = 11" wide × 8.5" tall):
    horizontal: 2(3.375) card + 1(2.00) gap + 2(1.125) margin = 11.00 in
    vertical:   2(2.125) card + 1(2.00) gap + 2(1.125) margin =  8.50 in

Duplex via SHARED BACK tiling (no mirror, no rotation):
  - Page 1 / 3 / 5 / 7: 4 unique fronts (worker order: W-####).
  - Page 2 / 4 / 6: 4× IDENTICAL CoF back tile.
  - Page 8: 4× IDENTICAL Company ID back tile.
  The fact that each back-page tiles the SAME back design at all four
  slot positions means duplex alignment is irrelevant — long-edge,
  short-edge, or two-pass manual flip-and-reload, every front lands
  behind a correct, right-side-up back. The only print-dialog
  requirement is "Letter Landscape + two-sided" (any binding edge).
  Page 8 has 2 extra back tiles at the empty-front slot positions
  (W-0015, W-0016 don't exist yet); those become trim scrap, no harm.

Page count: 14 workers → 4 front-pages × 2 sides = 8 pages total.

Pipeline:
  1. For each worker, render their live card HTML (Jinja2 pipeline)
     to a 2-page PDF at the existing CR80 @page size.
  2. pypdfium2 renders each PDF page (front + back) to a PNG (300 DPI).
  3. Render ONE canonical CoF back PNG + ONE canonical Company ID back
     PNG. These are tiled 4× on the back pages.
  4. Assemble the Letter-landscape bundle HTML with all the PNGs
     base64-embedded in 2×2 grids, alternating front-page / back-page.
     Page 1 carries a tiny print-instructions footer (#187) telling
     the operator to pick long-edge flip; pages 2-8 are footer-free.
  5. Render the bundle HTML to PDF via headless Edge.
  6. Post-process the PDF catalog to set
     /ViewerPreferences << /Duplex /DuplexFlipLongEdge >>
     so modern print dialogs auto-select long-edge duplex (#187).
     Some dialogs ignore the hint; the page-1 footer is the backstop.

Output: data_room/credentials/batch_print/SuperstarsContracting-AllIDs-<YYYY-MM-DD>.pdf

Idempotent re-runs overwrite the same dated file.

PII discipline:
  - Logs W-#### + card_id + counts only — never names or face-photo paths.
  - The output PDF carries the same identifying content that any single
    printed badge carries; the operator hand-prints these for site use.
"""
import base64
import io
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

import jinja2
import pypdfium2 as pp
from PIL import Image

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import sqlite3  # noqa: E402

DB = SCRIPT_DIR / "superstars.db"
WORKER_RECORDS_DIR = SCRIPT_DIR / "worker_records"
BATCH_DIR = SCRIPT_DIR / "data_room" / "credentials" / "batch_print"
EDGE_PATHS = [
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
    Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
]

# Order: W-0001..W-0012 (CoF), then W-0013, W-0014 (Company ID).
WORKER_ORDER = [f"W-{i:04d}" for i in range(1, 15)]


def _fmt_mdy(d):
    if not d:
        return ""
    try:
        y, m, dd = d[:10].split("-")
        return f"{m}-{dd}-{y}"
    except Exception:
        return d or ""


def find_edge():
    for p in EDGE_PATHS:
        if p.exists():
            return p
    raise RuntimeError("Microsoft Edge not found")


def fetch_card_context(emp_id):
    """Return (cred_type, template_name, ctx) for the worker's active
    credential, or None if none exists."""
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    try:
        emp = c.execute(
            "SELECT employee_id, name, trade, pin, face_image_path "
            "FROM employees WHERE employee_id = ?",
            (emp_id,),
        ).fetchone()
        if not emp:
            return None
        cof = c.execute(
            "SELECT card_id, card_number_display, issued_date, expires_date, "
            "       issued_by, rigger_name_snapshot, rigger_license_snapshot, "
            "       signature_path FROM cof_cards "
            "WHERE employee_id = ? AND status = 'issued' "
            "ORDER BY issued_date DESC LIMIT 1",
            (emp_id,),
        ).fetchone()
        if cof:
            card = dict(cof)
            cred_type = "cof"
            template_name = "cof_card_print.html"
            expires_str = card.get("expires_date") or ""
        else:
            cid = c.execute(
                "SELECT card_id, card_number_display, issued_date, issued_by "
                "FROM company_id_cards "
                "WHERE employee_id = ? AND status = 'active' "
                "ORDER BY issued_date DESC LIMIT 1",
                (emp_id,),
            ).fetchone()
            if not cid:
                return None
            card = dict(cid)
            cred_type = "company_id"
            template_name = "company_id_card_print.html"
            expires_str = ""
    finally:
        c.close()

    # Photos are embedded as data: URIs because headless Edge renders
    # without the operator's session cookie, and /worker-files/ is
    # auth-gated (returns 401 -> HTML login redirect). Do not "clean
    # up" to direct URLs without also injecting cookies or signed URLs
    # into the headless render context — every card would render with
    # a broken-image placeholder.
    #
    # PII discipline: the data: URI is base64 of the JPEG bytes — no
    # filesystem path, no name leaked anywhere in the rendered HTML or
    # in server logs. (Image bytes themselves are PII of course, but
    # they're the worker's own card photo, which is by design on every
    # printed CR80 going out the door.)
    photo_url = ""
    face_path = emp["face_image_path"]
    if face_path:
        fp = Path(face_path)
        if not fp.is_absolute():
            fp = SCRIPT_DIR / fp
        if fp.exists() and fp.stat().st_size > 0:
            mime = {
                ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png",  ".webp": "image/webp",
            }.get(fp.suffix.lower(), "image/jpeg")
            try:
                b64 = base64.b64encode(fp.read_bytes()).decode("ascii")
                photo_url = f"data:{mime};base64,{b64}"
            except Exception:
                photo_url = ""
    # Signature
    sig_url = ""
    sig_path = card.get("signature_path") if cred_type == "cof" else None
    if sig_path:
        sf = SCRIPT_DIR / sig_path.lstrip("/")
        if sf.exists():
            sig_url = "/files/" + sig_path

    cnd = card.get("card_number_display") or card.get("card_id") or ""
    ctx = {
        "NAME": emp["name"] or "",
        "EMPLOYEE_ID": emp_id,
        "CARD_NUMBER_DISPLAY": cnd,
        "ISSUED_DATE": _fmt_mdy(card.get("issued_date")),
        "ISSUED_BY": card.get("issued_by") or "",
        "EXPIRES_DATE": _fmt_mdy(expires_str),
        "TRADE": emp["trade"] or "",
        "PIN": emp["pin"] or "----",
        "PHOTO_URL_OR_BLANK": photo_url,
        "RIGGER_NAME": card.get("rigger_name_snapshot", "") or "" if cred_type == "cof" else "",
        "RIGGER_LICENSE": card.get("rigger_license_snapshot", "") or "" if cred_type == "cof" else "",
        "SIGNATURE_URL": sig_url,
    }
    return cred_type, template_name, ctx


def render_card_html_to_pdf(html_text, base_url, output_pdf):
    """Render a card HTML string to a 2-page CR80 PDF via headless
    Edge. The HTML carries `@page { size: 85.6mm 53.98mm; margin: 0 }`
    so each side is one page. Uses the base_url as a hint so /files/
    and /worker-files/ URLs resolve via the running server."""
    profile = tempfile.mkdtemp(prefix="cred_print_")
    edge = find_edge()
    # Write the HTML to a temp file; convert /worker-files/ + /files/
    # URLs to fully-qualified http://127.0.0.1:5050/... so the headless
    # Edge sandbox can fetch them (it can't talk to / by default).
    full_html = html_text.replace(
        'src="/worker-files/', f'src="{base_url}/worker-files/'
    ).replace(
        'src="/files/', f'src="{base_url}/files/'
    )
    tmp_html = Path(profile) / "card.html"
    tmp_html.write_text(full_html, encoding="utf-8")
    try:
        cmd = [
            str(edge),
            "--headless=old",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=5000",
            f"--print-to-pdf={output_pdf}",
            tmp_html.as_uri(),
        ]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=45)
        if r.returncode != 0:
            return False
        # Edge sometimes flushes the file just after exit.
        for _ in range(20):
            if Path(output_pdf).exists() and Path(output_pdf).stat().st_size > 0:
                return True
            time.sleep(0.1)
        return False
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def pdf_page_to_png(pdf_path, page_index, dpi=300, max_px=1600):
    """Render a single PDF page to a PIL Image."""
    doc = pp.PdfDocument(str(pdf_path))
    try:
        page = doc[page_index]
        w, h = page.get_size()
        scale = dpi / 72.0
        bitmap = page.render(scale=scale)
        pil = bitmap.to_pil()
        # Cap at max_px on the long edge for embed-size sanity.
        if max(pil.size) > max_px:
            r = max_px / max(pil.size)
            pil = pil.resize((int(pil.size[0] * r), int(pil.size[1] * r)),
                             Image.LANCZOS)
        return pil
    finally:
        doc.close()


def png_to_data_url(img):
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


# ---------------------------------------------------------------------
# Bundle HTML template — #178 lamination-friendly layout.
#
# Letter LANDSCAPE (11" × 8.5"). 2×2 grid of CR80 cards per page.
# Exactly 2.00" gap between adjacent cards in BOTH directions, with
# ~1.125" page margins. The 2" gap is the operator's lamination /
# scissor margin — every card has at least 1" of clear border on all
# four sides after the sheet is printed.
#
# Math (in inches):
#   horizontal: 2(3.375 card) + 1(2.00 gap) + 2(1.125 margin) = 11.00
#   vertical:   2(2.125 card) + 1(2.00 gap) + 2(1.125 margin) =  8.50
#
# Slots within a page (row-major):
#   [0] = top-left   [1] = top-right
#   [2] = bottom-left [3] = bottom-right
#
# Duplex strategy: each back-page tiles ONE back design at all four
# slot positions (shared-back, no mirroring). See module docstring.
# A `.slot.empty` is invisible — empty slots on the last front-page
# correspond to the same positions on the back-page, which still get
# the back tile printed (trim-off scrap, harmless).
#
# The page CSS gives no .page-label rendering room: when the operator
# prints to paper, a visible label would land on the printed sheet
# and confuse the lamination/cut step. The orientation guidance
# stays in the dialog/Downloads filename instead.
# ---------------------------------------------------------------------
BUNDLE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Superstars Contracting — All Worker Credentials — Batch Print</title>
<style>
  @page { size: 11in 8.5in; margin: 0; }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: #fff; font-family: "Inter", sans-serif; }
  .page {
    width: 11in;
    height: 8.5in;
    page-break-after: always;
    page-break-inside: avoid;
    overflow: hidden;
    position: relative;
  }
  .page:last-child { page-break-after: auto; }
  /* 2×2 grid. The 2.00in column-gap + row-gap is the lamination /
     scissor margin between adjacent cards. Tracks are CR80-sized.
     justify-content / align-content center the whole grid against
     the page so the outer margin distributes evenly to all four
     edges (math above lands at 1.125in per side). */
  .grid {
    width: 100%;
    height: 100%;
    display: grid;
    grid-template-columns: 3.375in 3.375in;
    grid-template-rows: 2.125in 2.125in;
    column-gap: 2.00in;
    row-gap: 2.00in;
    justify-content: center;
    align-content: center;
  }
  .slot {
    width: 3.375in;
    height: 2.125in;
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .slot.empty { /* invisible — see comment in module docstring */ }
  .slot img { width: 100%; height: 100%; object-fit: contain; display: block; }

  /* Page-1-only print-instructions footer (#187).
     Backstop for the PDF /ViewerPreferences /Duplex hint — some print
     dialogs ignore the catalog hint and default to whatever the driver
     remembered last. The footer lives in the bottom-margin band (the
     page has 1.125in of clear space below the bottom row of cards), so
     it never overlaps card content. Restricted to page 1 so it
     doesn't reprint behind every card; the operator only needs to
     read it once. */
  .print-instructions {
    position: absolute;
    left: 0; right: 0;
    bottom: 0.25in;
    text-align: center;
    font-size: 8pt;
    color: #999;
    font-weight: 400;
    font-variant-numeric: normal;
  }
</style>
</head>
<body>
{% for page in pages %}
  <div class="page">
    <div class="grid">
      {% for slot in page.slots %}
        {% if slot %}
          <div class="slot"><img src="{{ slot }}" alt=""></div>
        {% else %}
          <div class="slot empty"></div>
        {% endif %}
      {% endfor %}
    </div>
    {% if loop.first %}
      <div class="print-instructions">Print 2-sided · Flip on long edge</div>
    {% endif %}
  </div>
{% endfor %}
</body>
</html>
"""


def build_bundle(fronts_by_type, shared_backs, output_pdf, base_url):
    """Build the lamination-friendly 2x2 landscape bundle PDF (#178).

    Args:
      fronts_by_type: list of (W-####, cred_type, front_img) in worker
        order. cred_type is 'cof' or 'company_id'; used only to choose
        which shared back to tile on the next page.
      shared_backs: dict {'cof': cof_back_data_url, 'company_id': cid_back_data_url}
        — each value is rendered ONCE and reused on every back-page
        slot, so duplex alignment is automatic regardless of which
        duplex mode the operator selects.
      output_pdf: target PDF path (str/Path).
      base_url: unused now that photos are inlined as data: URIs, but
        kept in the signature so the caller doesn't have to change.

    Pages emitted, in order:
      P1 fronts (1..4)    P2 backs (4× tile of cred_type for P1)
      P3 fronts (5..8)    P4 backs (4× tile)
      P5 fronts (9..12)   P6 backs (4× tile)
      P7 fronts (13..14)  P8 backs (4× tile — empty front slots still
                                    get a back tile; trim scrap)

    A page boundary is also a credential-type boundary: a single
    front-page is always all CoF OR all Company ID, never mixed,
    because the back tile only fits ONE credential type. With the
    current operator roster (CoF for W-0001..W-0012, Company ID for
    W-0013..W-0014) this falls out naturally: pages 1/3/5 are pure
    CoF; page 7 is pure Company ID. Code asserts this invariant.
    """
    PER_PAGE = 4  # 2 cols × 2 rows
    pages = []
    n = len(fronts_by_type)
    n_chunks = (n + PER_PAGE - 1) // PER_PAGE
    for chunk_idx in range(n_chunks):
        chunk = fronts_by_type[chunk_idx * PER_PAGE:(chunk_idx + 1) * PER_PAGE]
        # Pad with None so every page has exactly PER_PAGE slots.
        while len(chunk) < PER_PAGE:
            chunk.append(None)
        # Determine the credential type for this sheet — every entry in
        # the chunk must agree (the WORKER_ORDER keeps CoFs together
        # before Company IDs, so this is true in practice).
        chunk_types = {e[1] for e in chunk if e is not None}
        if len(chunk_types) > 1:
            raise RuntimeError(
                f"Mixed cred types on sheet {chunk_idx+1}: {chunk_types}. "
                f"Worker ordering must group like-types together so the "
                f"shared-back tile is unambiguous."
            )
        cred_type = next(iter(chunk_types)) if chunk_types else 'cof'
        front_slots = [(e[2] if e is not None else None) for e in chunk]
        pages.append({"slots": front_slots})
        # Back-page: tile the shared back for this cred type at ALL
        # four positions, including positions whose front slot was
        # empty. Those extra back tiles become trim scrap when the
        # operator cuts the sheet, which is fine.
        back_tile = shared_backs.get(cred_type)
        if not back_tile:
            raise RuntimeError(f"No shared back rendered for cred_type={cred_type!r}")
        pages.append({"slots": [back_tile] * PER_PAGE})

    env = jinja2.Environment(autoescape=False)
    bundle_html = env.from_string(BUNDLE_TEMPLATE).render(pages=pages)
    # Render bundle HTML to PDF via headless Edge.
    profile = tempfile.mkdtemp(prefix="bundle_")
    edge = find_edge()
    tmp_html = Path(profile) / "bundle.html"
    tmp_html.write_text(bundle_html, encoding="utf-8")
    try:
        cmd = [
            str(edge),
            "--headless=old",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=8000",
            f"--print-to-pdf={output_pdf}",
            tmp_html.as_uri(),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        for _ in range(40):
            if Path(output_pdf).exists() and Path(output_pdf).stat().st_size > 0:
                break
            time.sleep(0.2)
        else:
            return False
        # Bake the long-edge duplex hint into the PDF catalog (#187).
        # Most modern print dialogs (Adobe Reader, Edge, Chrome) honor
        # this and auto-select Flip-on-Long-Edge, which keeps the
        # shared-back tile right-side-up. The page-1 footer in the
        # bundle template is the backstop for dialogs that ignore the
        # hint.
        _bake_long_edge_duplex_hint(output_pdf)
        return True
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def _bake_long_edge_duplex_hint(pdf_path):
    """Set /ViewerPreferences << /Duplex /DuplexFlipLongEdge >> in the
    PDF catalog. Pure post-process: doesn't touch page content. Errors
    are logged + swallowed — a hint failure should never block the
    download (the page-1 footer still tells the operator which flip
    to pick).
    """
    try:
        from pypdf import PdfReader, PdfWriter
        reader = PdfReader(str(pdf_path))
        writer = PdfWriter(clone_from=reader)
        # The .duplex setter creates the ViewerPreferences dict if
        # absent, otherwise patches in the /Duplex entry.
        writer.viewer_preferences.duplex = "/DuplexFlipLongEdge"
        # Write to a sibling temp file first, then atomic-replace —
        # avoids leaving a half-written PDF if the write is interrupted.
        tmp_out = Path(str(pdf_path) + ".duplex.tmp")
        with tmp_out.open("wb") as f:
            writer.write(f)
        tmp_out.replace(pdf_path)
    except Exception as e:
        # PDF was already written successfully; this is best-effort.
        print(f"  WARN: duplex-hint post-process failed: {type(e).__name__}: {e}",
              file=sys.stderr)


def main(base_url="http://127.0.0.1:5050"):
    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    # Operator-facing filename (#178) — clean when it lands in the
    # operator's Downloads folder vs the prior all_credentials_*.
    output = BATCH_DIR / f"SuperstarsContracting-AllIDs-{today}.pdf"

    # 1. Render each worker's card to a 2-page PDF + convert front to PNG.
    #    Back is NOT extracted per-worker — see step 2.
    fronts = []          # list of (W-####, cred_type, front_data_url)
    back_sample_html = {}  # cred_type -> HTML to render once for the
                           # shared-back tile
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(SCRIPT_DIR)),
        autoescape=True,
    )
    workdir = Path(tempfile.mkdtemp(prefix="cred_bundle_"))
    try:
        for wid in WORKER_ORDER:
            c = sqlite3.connect(str(DB))
            c.row_factory = sqlite3.Row
            try:
                emp = c.execute(
                    "SELECT employee_id FROM employees WHERE worker_id = ?",
                    (wid,),
                ).fetchone()
            finally:
                c.close()
            if not emp:
                print(f"  {wid}: not found — SKIPPED")
                continue
            emp_id = emp["employee_id"]
            ctx_pkg = fetch_card_context(emp_id)
            if not ctx_pkg:
                print(f"  {wid}: no active credential — SKIPPED")
                continue
            cred_type, template_name, ctx = ctx_pkg
            html = env.get_template(template_name).render(**ctx)
            # First worker of each cred_type donates their HTML as the
            # source of the shared back tile (the back attestation block
            # is rigger-only fields + a date; per-worker variation
            # there is intentional behavior the operator decided to
            # collapse in the batch print — see module docstring's
            # SHARED BACK discussion).
            if cred_type not in back_sample_html:
                back_sample_html[cred_type] = html
            card_pdf = workdir / f"{wid}.pdf"
            ok = render_card_html_to_pdf(html, base_url, card_pdf)
            if not ok:
                print(f"  {wid}: PDF render failed — SKIPPED")
                continue
            try:
                front_img = pdf_page_to_png(card_pdf, 0)
            except Exception as ex:
                print(f"  {wid}: front page-extract failed — {ex}")
                continue
            front_data = png_to_data_url(front_img)
            fronts.append((wid, cred_type, front_data))
            print(f"  {wid}: {cred_type:11}  front_size={front_img.size}")

        if not fronts:
            print("\n  BUNDLE: no workers prepared")
            return 1

        # 2. Render the shared-back tile ONCE per cred_type encountered.
        #    Uses the first worker of that type's already-rendered HTML
        #    (page 2 of the per-worker PDF). The back template only
        #    surfaces rigger fields + ISSUED_DATE — values that are
        #    cohort-consistent for this batch — so any sample yields
        #    the same visual back tile within rounding.
        shared_backs = {}
        for cred_type, html in back_sample_html.items():
            sample_pdf = workdir / f"_shared_back_{cred_type}.pdf"
            if not render_card_html_to_pdf(html, base_url, sample_pdf):
                print(f"  SHARED BACK ({cred_type}): render failed")
                return 1
            try:
                doc = pp.PdfDocument(str(sample_pdf))
                n_pages = len(doc)
                doc.close()
            except Exception as ex:
                print(f"  SHARED BACK ({cred_type}): page-count failed — {ex}")
                return 1
            if n_pages < 2:
                print(f"  SHARED BACK ({cred_type}): expected >=2 pages, got {n_pages}")
                return 1
            back_img = pdf_page_to_png(sample_pdf, 1)
            shared_backs[cred_type] = png_to_data_url(back_img)
            print(f"  shared back ({cred_type}): back_size={back_img.size}")

        print(f"\n  workers prepared: {len(fronts)}   cred_types: {sorted(shared_backs.keys())}")
        ok = build_bundle(fronts, shared_backs, output, base_url)
        if not ok:
            print(f"\n  BUNDLE RENDER FAILED")
            return 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # Verify pages
    doc = pp.PdfDocument(str(output))
    n = len(doc)
    doc.close()
    print(f"\n  bundle written: {output} ({output.stat().st_size:,} bytes, {n} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
