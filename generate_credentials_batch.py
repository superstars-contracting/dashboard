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

import hashlib
import json
import jinja2
import logging
import os
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

# #246 — the bundle pool is the CANONICAL active roster (v_active_workers),
# in numeric W-#### order, derived at gather time. The previous hardcoded
# W-0001..W-0014 list was doubly stale: it MISSED workers onboarded after
# W-0014 and still PRINTED retired (labor-inactive) workers. Deactivated
# workers keep their issued credential rows (history) — they just stop
# appearing in fresh bundles; reactivation restores them.

# #189 — cache file convention. Naming is `SuperstarsContracting-AllIDs-
# <fingerprint>.pdf` where <fingerprint> is the SHA256/16 of the
# worker+rigger input set. The endpoint downloads under the friendly
# filename (SuperstarsContracting-AllIDs-<YYYY-MM-DD>.pdf) via the
# anchor's `download` attribute, so the operator never sees the
# fingerprint suffix.
CACHE_PREFIX = "SuperstarsContracting-AllIDs-"
CACHE_KEEP_LAST_N = 3

# #190 — bundle output-format version, included in the cache
# fingerprint so a code change that affects the rendered PDF
# invalidates every cached file the moment the new code lands.
#
# **Protocol:** bump this constant in the SAME commit as any change
# that affects the bundle PDF's output — new layout, new content, new
# metadata, new viewer preferences, new card-template structure, new
# render-time guard that could shift pixels, etc. Bumping moves the
# fingerprint forward by exactly the version bytes, which guarantees
# every existing cached file misses on the next click and is
# regenerated from current code. The operator's first click after
# deploy is a ~5s cache_miss; subsequent clicks hit the new file.
#
# History (also serves as a changelog of bundle-output-affecting commits):
#   v1 (initial #174)  — Letter portrait, 8-up grid, mirrored backs
#   v2 (#178)          — Letter landscape, 2x2 grid, 2.00" lamination spacing,
#                        shared-back tiling
#   v3 (#187)          — added /Duplex /DuplexFlipLongEdge viewer pref +
#                        page-1 "Print 2-sided · Flip on long edge" footer
#   v4 (#188)          — render-time PIN auto-generation guard (could
#                        affect rendered card content via self-heal)
#   v5 (#189)          — single-Edge consolidation of the per-card stage
#                        (verified content-identical, but bump for safety
#                        in case Chromium ever changes its pagination)
#   v6 (#190)          — current — fingerprint now includes THIS version,
#                        so pre-#190 cached PDFs (which lacked the v1..v5
#                        output changes' downstream effects in their
#                        fingerprint) get invalidated and replaced with
#                        a fresh render that has every fix from v1..v5
#                        baked in.
BUNDLE_FORMAT_VERSION = "v6"


def compute_bundle_fingerprint(workers_summary, global_state):
    """SHA256(worker rows + photo mtimes + rigger info + format version)
    → 16-hex digest.

    Inputs that AFFECT the rendered bundle are hashed; anything else
    (e.g., today's calendar date if no worker data changed) is NOT,
    so two clicks on the same day with no DB change land on a cache HIT.

    workers_summary: list of dicts with keys worker_id, pin, name,
        trade, photo_mtime (float or None), cof_card_id, cof_expiry,
        company_id_card_id, rigger_name_snapshot, rigger_license_snapshot,
        signature_path_mtime.
    global_state: dict with keys like template_mtime (so a template
        edit invalidates the cache automatically). BUNDLE_FORMAT_VERSION
        is folded in here so a code change that affects the rendered
        PDF (without touching worker data or template mtimes) still
        invalidates the cache — see #190 and the BUNDLE_FORMAT_VERSION
        constant docstring above.

    The hash uses sort-stable JSON to be byte-stable across Python
    runs. The 16-hex digest is enough collision resistance for cache
    keying — ~10^19 possible fingerprints vs realistic ~10s of distinct
    bundle states per operator-week.
    """
    sorted_items = sorted(workers_summary, key=lambda w: w["worker_id"])
    # Make a copy with format_version added so we never mutate the
    # caller's global_state dict.
    global_state_with_version = dict(global_state or {})
    global_state_with_version["format_version"] = BUNDLE_FORMAT_VERSION
    blob = json.dumps(
        {"workers": sorted_items, "global": global_state_with_version},
        sort_keys=True,
        default=str,  # date/Path → str fallback
    ).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _photo_mtime(face_image_path):
    """File mtime in epoch-seconds, or None if missing/unset."""
    if not face_image_path:
        return None
    fp = Path(face_image_path)
    if not fp.is_absolute():
        fp = SCRIPT_DIR / fp
    if not fp.exists():
        return None
    return fp.stat().st_mtime


def _file_mtime(path):
    """Generic mtime helper for cache fingerprinting; None if absent."""
    try:
        return Path(path).stat().st_mtime
    except FileNotFoundError:
        return None


def gather_bundle_inputs():
    """Snapshot the data that feeds the bundle render. Returns a tuple
    of (workers_summary, global_state) ready for fingerprinting.

    Pulls everything in ONE DB connection to avoid TOCTOU drift
    between fingerprint compute and cache miss regen.
    """
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    try:
        emp_rows = c.execute(
            """SELECT employee_id, worker_id, name, trade, pin, phone,
                      face_image_path
                 FROM v_active_workers
                ORDER BY CAST(SUBSTR(worker_id, 3) AS INTEGER)"""
        ).fetchall()

        workers_summary = []
        for row in (dict(r) for r in emp_rows):
            wid = row["worker_id"]
            eid = row["employee_id"]
            cof = c.execute(
                "SELECT card_id, issued_date, expires_date, "
                "       rigger_name_snapshot, rigger_license_snapshot, "
                "       signature_path "
                "FROM cof_cards WHERE employee_id = ? AND status = 'issued' "
                "ORDER BY issued_date DESC LIMIT 1",
                (eid,),
            ).fetchone()
            cid = c.execute(
                "SELECT card_id, issued_date "
                "FROM company_id_cards WHERE employee_id = ? AND status = 'active' "
                "ORDER BY issued_date DESC, created_at DESC LIMIT 1",
                (eid,),
            ).fetchone()
            cof_d = dict(cof) if cof else {}
            cid_d = dict(cid) if cid else {}
            sig_path = cof_d.get("signature_path") if cof_d else None
            workers_summary.append({
                "worker_id": wid,
                "employee_id": eid,
                # PII rule: hashing these is fine (one-way, not logged
                # outside the fingerprint); we never echo `name` / `pin`
                # / `phone` to chat or to server.log from this module.
                "name": row["name"] or "",
                "trade": row["trade"] or "",
                "pin": row["pin"] or "",
                "photo_mtime": _photo_mtime(row.get("face_image_path")),
                "cof_card_id": cof_d.get("card_id"),
                "cof_issued_date": cof_d.get("issued_date"),
                "cof_expires_date": cof_d.get("expires_date"),
                "cof_rigger_name": cof_d.get("rigger_name_snapshot"),
                "cof_rigger_license": cof_d.get("rigger_license_snapshot"),
                "cof_signature_mtime": _file_mtime(
                    SCRIPT_DIR / (sig_path or "")
                ) if sig_path else None,
                "company_id_card_id": cid_d.get("card_id"),
                "company_id_issued_date": cid_d.get("issued_date"),
            })

        # Global state: templates + bundle template's own source. If a
        # template edit changes the layout, the cache must invalidate.
        global_state = {
            "cof_template_mtime": _file_mtime(SCRIPT_DIR / "cof_card_print.html"),
            "cid_template_mtime": _file_mtime(SCRIPT_DIR / "company_id_card_print.html"),
            "generator_mtime": _file_mtime(__file__),
        }
        return workers_summary, global_state
    finally:
        c.close()


def cache_path_for(fingerprint):
    """Where the cached PDF for `fingerprint` lives on disk."""
    return BATCH_DIR / f"{CACHE_PREFIX}{fingerprint}.pdf"


def cache_sidecar_for(fingerprint):
    """JSON metadata file next to the cached PDF (counts, gen ts)."""
    return BATCH_DIR / f"{CACHE_PREFIX}{fingerprint}.json"


def prune_cache(keep_last_n=CACHE_KEEP_LAST_N):
    """Keep the N most-recent fingerprinted cache PDFs; delete older.
    A `<fingerprint>.json` is removed alongside its `<fingerprint>.pdf`.
    Old dated files (legacy `*-YYYY-MM-DD.pdf` from before #189) are
    NOT touched — they're the operator's history. Errors are logged
    and swallowed; pruning is best-effort housekeeping."""
    try:
        pdfs = []
        for p in BATCH_DIR.glob(f"{CACHE_PREFIX}*.pdf"):
            stem = p.stem[len(CACHE_PREFIX):]
            # Fingerprints are 16 hex chars; anything else (e.g., a
            # date suffix or other format) is left alone.
            if len(stem) == 16 and all(ch in "0123456789abcdef" for ch in stem):
                pdfs.append(p)
        pdfs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for old in pdfs[keep_last_n:]:
            try:
                old.unlink()
                side = old.with_suffix(".json")
                if side.exists():
                    side.unlink()
            except OSError:
                pass
    except Exception as e:
        logging.warning(f"cache prune failed: {type(e).__name__}: {e}")


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

        # Render-time PIN self-heal (#188 Option A) — mirror of the
        # guard in server.serve_card_live. The bundle path is a
        # separate Python process from the live render, so the guard
        # has to run here too; the canonical helper makes the duplicate
        # cheap (one import + one call). Self-heals NULL/empty/invalid
        # PINs into a derived (phone last-4) or random unused PIN,
        # audit-logged with `pin_render_heal` action and PII-safe
        # before/after payloads.
        from worker_pin import assign_pin_for_worker, is_valid_pin
        if not is_valid_pin(emp["pin"]):
            new_pin = assign_pin_for_worker(
                c, emp_id,
                actor_user_id=None, actor_role="bundle_generator",
                source="pin_render_heal",
            )
            if new_pin:
                c.commit()
                emp = dict(emp)
                emp["pin"] = new_pin
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
    # Signature — vendored static/ assets stay on the public /files/static
    # mount; anything else is a gated artifact (#248).
    sig_url = ""
    sig_path = card.get("signature_path") if cred_type == "cof" else None
    if sig_path:
        sf = SCRIPT_DIR / sig_path.lstrip("/")
        if sf.exists():
            rel = sig_path.replace("\\", "/").lstrip("/")
            sig_url = ("/files/" + rel) if rel.startswith("static/") else ("/project-files/" + rel)

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
    # Write the HTML to a temp file; convert /worker-files/ + /files/ +
    # /project-files/ URLs to fully-qualified http://127.0.0.1:5050/... so
    # the headless Edge sandbox can fetch them (it can't talk to / by
    # default). NOTE (#248): only /files/static/* is fetchable without a
    # session — photos are inlined as data: URIs upstream precisely so the
    # cookie-less Edge never needs a gated URL; the gated rewrites are
    # belt-and-braces for any straggler (they 401 harmlessly).
    full_html = html_text.replace(
        'src="/worker-files/', f'src="{base_url}/worker-files/'
    ).replace(
        'src="/project-files/', f'src="{base_url}/project-files/'
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
    because the back tile only fits ONE credential type. #246 — the
    caller pre-sorts fronts by (cred_type, numeric W-####) so the
    grouping is guaranteed by construction, not roster coincidence.
    Code still asserts the invariant.
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
        # the chunk must agree (the caller's (cred_type, W-####) pre-sort
        # keeps CoFs together before Company IDs — #246).
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


def render_concat_cards_one_edge(card_htmls, base_url, output_pdf):
    """#189 — single-Edge consolidation of the per-card render stage.

    Takes 14 individually-rendered card HTMLs (cheap, Jinja-only — no
    Edge) and concatenates them into ONE wrapper HTML that Chromium
    renders in a single --print-to-pdf invocation. Saves ~13 Edge
    launches × ~800ms = ~10s on the cache-MISS path.

    Output PDF: 14 cards × 2 pages each = 28 pages. Caller extracts
    fronts at indices 0, 2, 4, ..., 26 and the shared-back samples at
    page 1 (first CoF) + first Company-ID back page.

    The two card templates (cof_card_print.html, company_id_card_print.html)
    share the same @page CR80 rule, so combining their styles into one
    <head> is safe; class names are scoped to each template's own
    selectors and don't collide.

    `.screen-only-note` (the on-screen "Ctrl+P to print" helper) is
    hidden explicitly here so it doesn't allocate a phantom 3rd page
    per card under Chromium's print pipeline.
    """
    import re as _re
    style_re = _re.compile(r"<style[^>]*>(.*?)</style>", _re.DOTALL | _re.IGNORECASE)
    body_re = _re.compile(r"<body[^>]*>(.*?)</body>", _re.DOTALL | _re.IGNORECASE)

    # Match the on-screen `Ctrl+P to print` helper (display:none in
    # print, but Chromium still allocates a page for it during the
    # layout pass that precedes the @media print evaluation — this
    # adds a phantom 1st blank page to the FIRST card in the concat).
    # Strip the div entirely from each body before splicing.
    screen_note_re = _re.compile(
        r"<div\s+class=[\"']screen-only-note[\"'][^>]*>.*?</div>",
        _re.DOTALL | _re.IGNORECASE,
    )

    styles_seen = []
    sections = []
    for html in card_htmls:
        # Photos already inlined as data: URIs by fetch_card_context;
        # /worker-files/ URL rewriting (kept here as belt-and-braces
        # for any non-photo asset path that does still need the
        # loopback prefix) is the same rewrite the per-card path uses.
        html = html.replace(
            'src="/worker-files/', f'src="{base_url}/worker-files/'
        ).replace(
            'src="/project-files/', f'src="{base_url}/project-files/'
        ).replace(
            'src="/files/', f'src="{base_url}/files/'
        )
        m_style = style_re.search(html)
        if m_style:
            s = m_style.group(1)
            if s not in styles_seen:
                styles_seen.append(s)
        m_body = body_re.search(html)
        body_content = m_body.group(1) if m_body else html
        # Drop the screen-only-note — see comment above.
        body_content = screen_note_re.sub("", body_content)
        sections.append(
            '<div class="ssc-card-doc">'
            + body_content
            + '</div>'
        )

    wrapper = (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="UTF-8">'
        f'<link rel="stylesheet" href="{base_url}/files/static/fonts/typography.css">'
        '<title>SSC bundle — concatenated cards</title>'
        '<style>'
        + "\n".join(styles_seen)
        + """
        /* #189 single-Edge bundle hardening. */
        body { margin: 0; padding: 0; background: #fff; }
        .ssc-card-doc { display: block; }
        /* Force a hard break AFTER every .sheet so Chromium emits
           exactly one page per sheet (= 2 pages per card). Without
           this, a trailing whitespace text node or @page interaction
           emits a phantom 3rd page per card (~28 -> 29-42 pages total
           depending on bookkeeping). Suppressing page-break-after on
           the very last sheet of the very last card stops the trailing
           blank-page that "always" would otherwise leave behind. */
        .ssc-card-doc > .sheet { page-break-after: always; }
        .ssc-card-doc:last-child > .sheet:last-of-type { page-break-after: auto; }
        /* The "Ctrl+P to print this credential" hint is screen-only;
           guarantee it doesn't allocate a print page here. */
        .screen-only-note { display: none !important; }
        @media print { .ssc-card-doc { -webkit-print-color-adjust: exact; print-color-adjust: exact; } }
        </style>
        </head><body>"""
        + "".join(sections)
        + '</body></html>'
    )

    profile = tempfile.mkdtemp(prefix="cred_concat_")
    edge = find_edge()
    tmp_html = Path(profile) / "concat.html"
    tmp_html.write_text(wrapper, encoding="utf-8")
    try:
        cmd = [
            str(edge),
            "--headless=old",
            "--disable-gpu",
            "--no-pdf-header-footer",
            f"--user-data-dir={profile}",
            "--virtual-time-budget=12000",
            f"--print-to-pdf={output_pdf}",
            tmp_html.as_uri(),
        ]
        subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        for _ in range(60):
            if Path(output_pdf).exists() and Path(output_pdf).stat().st_size > 0:
                return True
            time.sleep(0.2)
        return False
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


def main(base_url="http://127.0.0.1:5050", *, force_regenerate=False):
    """Render or serve the credentials bundle PDF.

    Returns a dict:
      {
        "status":      "cache_hit" | "cache_miss" | "no_workers",
        "output_path": Path,         # the PDF on disk
        "fingerprint": str,          # 16 hex chars
        "stage_t":     {stage: seconds, ...},
      }
    For backwards compat with the prior int-return signature, callers
    that test `if rc != 0` get a 0/1 via the convenience exit in
    `__main__`.

    Cache contract (#189): compute the input fingerprint, look up an
    existing PDF named `SuperstarsContracting-AllIDs-<fingerprint>.pdf`.
    On hit, serve it instantly (no Edge launches, no DB writes from the
    self-heal guard either — the guard already ran when the data was
    first cached). On miss, regenerate and save with the new fingerprint.
    """
    BATCH_DIR.mkdir(parents=True, exist_ok=True)

    # Profiling (#189) — wall-clock per stage. Logged at INFO so the
    # server.log carries the breakdown for every cache-MISS regen.
    stage_t = {}
    t_total = time.time()

    # Cache lookup. If the fingerprint of current inputs matches an
    # existing PDF, return it immediately. The fingerprint computation
    # itself is cheap (one DB query + a few stat()s + a hash) — orders
    # of magnitude faster than even the cheapest Edge launch.
    t_fp = time.time()
    try:
        workers_summary, global_state = gather_bundle_inputs()
    except Exception as e:
        # If gather fails, fall through to the no-cache regen path —
        # NEVER let the cache serve incorrect data.
        logging.warning(f"bundle: gather inputs failed, forcing regen: {e}")
        workers_summary, global_state = None, None

    fingerprint = None
    if workers_summary is not None:
        try:
            fingerprint = compute_bundle_fingerprint(workers_summary, global_state)
        except Exception as e:
            logging.warning(f"bundle: fingerprint failed, forcing regen: {e}")
            fingerprint = None
    stage_t["0_fingerprint"] = time.time() - t_fp

    if (fingerprint
            and not force_regenerate
            and cache_path_for(fingerprint).exists()
            and cache_path_for(fingerprint).stat().st_size > 0):
        cached = cache_path_for(fingerprint)
        stage_t["total"] = time.time() - t_total
        logging.info(
            f"bundle: cache HIT fingerprint={fingerprint} "
            f"({stage_t['total']*1000:.0f}ms)"
        )
        print(f"  cache HIT  fingerprint={fingerprint}  "
              f"served in {stage_t['total']*1000:.0f}ms")
        return {
            "status": "cache_hit",
            "output_path": cached,
            "fingerprint": fingerprint,
            "stage_t": stage_t,
        }

    # Cache MISS — proceed with full regeneration. The fingerprint
    # becomes the on-disk filename so subsequent identical inputs hit
    # the cache.
    output = (cache_path_for(fingerprint) if fingerprint
              else BATCH_DIR / f"{CACHE_PREFIX}{date.today().isoformat()}.pdf")
    print(f"  cache MISS  fingerprint={fingerprint or 'NA'}  regenerating...")

    # 1. Resolve worker contexts + render each card HTML via Jinja.
    #    No Edge launches here — just template rendering. The big
    #    per-card cost (#189) was 14 × Edge cold start; concat below
    #    folds them into one Edge call.
    fronts_meta = []     # list of (W-####, cred_type, jinja_html)
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(SCRIPT_DIR)),
        autoescape=True,
    )
    workdir = Path(tempfile.mkdtemp(prefix="cred_bundle_"))
    t_per_card = time.time()
    try:
        # #246 — same canonical pool as gather_bundle_inputs: the active
        # roster in numeric order (no hardcoded id list to go stale).
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        try:
            pool = c.execute(
                "SELECT worker_id, employee_id FROM v_active_workers "
                "ORDER BY CAST(SUBSTR(worker_id, 3) AS INTEGER)"
            ).fetchall()
        finally:
            c.close()
        for prow in pool:
            wid = prow["worker_id"]
            emp_id = prow["employee_id"]
            ctx_pkg = fetch_card_context(emp_id)
            if not ctx_pkg:
                print(f"  {wid}: no active credential — SKIPPED")
                continue
            cred_type, template_name, ctx = ctx_pkg
            html = env.get_template(template_name).render(**ctx)
            fronts_meta.append((wid, cred_type, html))
            print(f"  {wid}: {cred_type:11}  jinja=OK")

        # #246 — group like credential types (CoF sheets, then Company ID),
        # numeric W-#### within each group. Each 2x2 sheet must be a single
        # type (build_bundle raises on mixed sheets); the old hardcoded
        # ordering satisfied that only by roster coincidence.
        fronts_meta.sort(key=lambda f: (0 if f[1] == 'cof' else 1,
                                        int(f[0][2:]) if f[0][2:].isdigit() else 99999))

        if not fronts_meta:
            print("\n  BUNDLE: no workers prepared")
            return {"status": "no_workers", "output_path": None,
                    "fingerprint": fingerprint, "stage_t": stage_t}

        # SINGLE Edge invocation (#189 secondary opt): render all
        # cards' fronts+backs in one shot. Output is a 28-page CR80
        # PDF where pages 2k = card[k] front, 2k+1 = card[k] back.
        concat_pdf = workdir / "all_cards.pdf"
        ok = render_concat_cards_one_edge(
            [h for (_, _, h) in fronts_meta], base_url, concat_pdf
        )
        if not ok:
            print("\n  CONCAT RENDER FAILED")
            return {"status": "render_failed", "output_path": None,
                    "fingerprint": fingerprint, "stage_t": stage_t}

        # Extract per-card front PNGs + shared-back samples. In the
        # concat output each card occupies 2 pages (front, back), with
        # an OPTIONAL trailing phantom page at the very end emitted by
        # Chromium's print pipeline. We accept N×2 or N×2+1 pages and
        # index fronts at i*2, backs at i*2+1.
        PAGES_PER_CARD = 2
        try:
            concat_doc = pp.PdfDocument(str(concat_pdf))
            n_pages_concat = len(concat_doc)
            scale = 300 / 72.0  # match pdf_page_to_png's default DPI
            fronts = []
            first_cof_back_idx = None
            first_cid_back_idx = None
            expected_pages = len(fronts_meta) * PAGES_PER_CARD
            if n_pages_concat not in (expected_pages, expected_pages + 1):
                print(f"  CONCAT page count: got {n_pages_concat}, expected "
                      f"{expected_pages} or {expected_pages+1} "
                      f"(={len(fronts_meta)} × {PAGES_PER_CARD} pages/card "
                      f"+ optional trailing phantom); abort.")
                concat_doc.close()
                return {"status": "render_failed", "output_path": None,
                        "fingerprint": fingerprint, "stage_t": stage_t}
            for i, (wid, cred_type, _) in enumerate(fronts_meta):
                front_page_idx = i * PAGES_PER_CARD
                back_page_idx = front_page_idx + 1
                bitmap = concat_doc[front_page_idx].render(scale=scale)
                pil = bitmap.to_pil()
                # Match pdf_page_to_png's max_px=1600 long-edge cap.
                if max(pil.size) > 1600:
                    r = 1600 / max(pil.size)
                    pil = pil.resize((int(pil.size[0]*r), int(pil.size[1]*r)),
                                     Image.LANCZOS)
                fronts.append((wid, cred_type, png_to_data_url(pil)))
                if cred_type == "cof" and first_cof_back_idx is None:
                    first_cof_back_idx = back_page_idx
                if cred_type == "company_id" and first_cid_back_idx is None:
                    first_cid_back_idx = back_page_idx
            # Shared backs.
            shared_backs = {}
            for cred_type, page_idx in [
                ("cof", first_cof_back_idx),
                ("company_id", first_cid_back_idx),
            ]:
                if page_idx is None:
                    continue
                bitmap = concat_doc[page_idx].render(scale=scale)
                pil = bitmap.to_pil()
                if max(pil.size) > 1600:
                    r = 1600 / max(pil.size)
                    pil = pil.resize((int(pil.size[0]*r), int(pil.size[1]*r)),
                                     Image.LANCZOS)
                shared_backs[cred_type] = png_to_data_url(pil)
                print(f"  shared back ({cred_type}): back_size={pil.size}")
            concat_doc.close()
        except Exception as ex:
            print(f"  CONCAT page-extract failed — {ex}")
            return {"status": "render_failed", "output_path": None,
                    "fingerprint": fingerprint, "stage_t": stage_t}
        stage_t['1_per_card_render'] = time.time() - t_per_card

        print(f"\n  workers prepared: {len(fronts)}   cred_types: {sorted(shared_backs.keys())}")
        t_bundle = time.time()
        ok = build_bundle(fronts, shared_backs, output, base_url)
        stage_t['3_bundle_html_to_pdf'] = time.time() - t_bundle
        if not ok:
            print(f"\n  BUNDLE RENDER FAILED")
            return {"status": "render_failed", "output_path": None,
                    "fingerprint": fingerprint, "stage_t": stage_t}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    # Verify pages
    t_verify = time.time()
    doc = pp.PdfDocument(str(output))
    n = len(doc)
    doc.close()
    stage_t['4_pypdf_verify'] = time.time() - t_verify

    # Write sidecar metadata (counts + gen ts) next to the cache PDF
    # so the operator (or a future maintenance pass) can introspect
    # the cache without re-opening the PDF.
    if fingerprint:
        try:
            sidecar = cache_sidecar_for(fingerprint)
            with sidecar.open("w", encoding="utf-8") as f:
                json.dump({
                    "fingerprint": fingerprint,
                    "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "worker_count": len(fronts),
                    "page_count": n,
                    "size_bytes": output.stat().st_size,
                }, f, indent=2)
        except Exception as e:
            logging.warning(f"sidecar write failed: {e}")
        # Housekeeping: keep last N cache files.
        prune_cache()

    stage_t['total'] = time.time() - t_total
    print(f"\n  bundle written: {output} ({output.stat().st_size:,} bytes, {n} pages)")
    print("  timing (seconds):")
    for k in ['0_fingerprint', '1_per_card_render', '2_shared_backs',
              '3_bundle_html_to_pdf', '4_pypdf_verify', 'total']:
        v = stage_t.get(k)
        if v is not None:
            print(f"    {k:<24}  {v:6.2f}s")
    logging.info(
        f"bundle: cache MISS fingerprint={fingerprint} "
        f"generated in {stage_t['total']*1000:.0f}ms  "
        + "  ".join(f"{k}={v:.2f}s" for k, v in stage_t.items())
    )
    return {
        "status": "cache_miss",
        "output_path": output,
        "fingerprint": fingerprint,
        "stage_t": stage_t,
    }


if __name__ == "__main__":
    # CLI entry — translate the dict return into an exit code.
    result = main()
    if isinstance(result, dict):
        ok = result.get("status") in ("cache_hit", "cache_miss")
        sys.exit(0 if ok else 1)
    # Legacy int-return path (defensive).
    sys.exit(int(result or 0))
