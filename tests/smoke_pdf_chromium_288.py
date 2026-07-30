"""#288 GUARD — the chromium PDF engine (Cloud M2).

Proves, with NO server and synthetic data only:
  ENGINE      SSC_PDF_ENGINE unset -> 'edge' (the Windows default, in code);
              'chromium' resolves a real browser on this machine.
  DCR         both audiences render via chromium from a SYNTHETIC day
              aggregated through the REAL pipeline (dcr_aggregator ->
              DCRHTMLRenderer) on the isolated DB — valid PDFs, >=1 page.
  FORM        a repo-tracked blank-form source renders — valid PDF, 1 page.
  CREDENTIAL  a synthetic CR80-geometry card fixture (@page 85.6x53.98mm,
              two sides) renders — valid PDF, exactly 2 pages (the geometry
              is the credential-specific risk).
  PLANT       SSC_CHROMIUM_PATH -> a nonexistent binary raises a CLEAN
              PDFExportError naming the path, fast (<5s), with NO pdf file
              created — never a hang, never a zero-byte PDF served.

The edge-default proof for everything else is the Rest of the gate running
with the var unset — no suite here re-tests edge.

Isolated backend REQUIRED (seeds a synthetic project/day). PII-safe:
synthetic ids/counts only. No server, no network.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
import pdf_export  # noqa: E402

PC = "SMK288-A"
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note and not cond else ""))
    return bool(cond)


def pdf_pages(p: Path):
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(p)).pages)
    except Exception:
        return -1


CRED_FIXTURE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
@page { size: 85.6mm 53.98mm; margin: 0; }
body { margin: 0; font-family: sans-serif; }
.side { width: 85.6mm; height: 53.98mm; page-break-after: always;
        background: #fff; border: 1mm solid #B11E2E; box-sizing: border-box;
        padding: 4mm; }
.side:last-child { page-break-after: auto; }
</style></head><body>
<div class="side"><b>SMK288 SYNTHETIC CREDENTIAL</b><br>W-9999 — FRONT</div>
<div class="side">BACK — issued by the #288 smoke, not a real card</div>
</body></html>"""


def seed():
    conn = db_layer.connect()
    try:
        conn.execute("DELETE FROM projects WHERE project_code=?", (PC,))
        conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                     (PC, "Smoke 288 PDF"))
        conn.execute("INSERT INTO sign_in_log (date, employee_id, project_code, time_in, "
                     "time_out) SELECT '2026-07-30', employee_id, ?, '07:00', '15:30' "
                     "FROM employees LIMIT 1", (PC,))
        conn.execute("INSERT INTO weather_log (date, project_code, am_temp_f, pm_temp_f, "
                     "am_conditions, pm_conditions, wind) VALUES ('2026-07-30', ?, 70.0, "
                     "82.0, 'Sunny', 'Sunny', '5 mph')", (PC,))
        conn.commit()
    finally:
        conn.close()


def cleanup():
    conn = db_layer.connect()
    try:
        for t in ("sign_in_log", "weather_log", "report_index", "projects"):
            conn.execute(f"DELETE FROM {t} WHERE project_code=?", (PC,))
        conn.commit()
        print("  [cleanup] synthetic rows removed (scoped to SMK288)")
    finally:
        conn.close()


def main():
    print("== #288 guard: chromium PDF engine ==")
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    print(f"   backend={'postgres' if db_layer.is_postgres() else 'sqlite'}  "
          f"SSC_DB_URL={'(set)' if db_url else '(unset)'}")
    if not db_url and os.environ.get("ALLOW_LIVE") != "1":
        print("REFUSING TO RUN: SSC_DB_URL is unset — this suite seeds rows and must "
              "never touch the live DB.")
        return 2

    # engine defaulting is code-level truth, asserted with the var explicitly absent
    saved_engine = os.environ.pop("SSC_PDF_ENGINE", None)
    saved_chromium = os.environ.pop("SSC_CHROMIUM_PATH", None)
    out = Path(tempfile.mkdtemp(prefix="smk288_"))
    try:
        ok("engine_default_is_edge", pdf_export.active_engine() == "edge")
        try:
            _, browser = pdf_export.find_browser_executable("chromium")
            ok("chromium_browser_resolves", browser.exists(), str(browser))
        except pdf_export.PDFExportError as e:
            ok("chromium_browser_resolves", False, str(e)[:80])
            return 1

        seed()
        try:
            from dcr_aggregator import aggregate_dcr
            from render_dcr_html import DCRHTMLRenderer
            for audience in ("internal", "client"):
                dcr = aggregate_dcr(PC, "2026-07-30", audience)
                dcr["report_id"] = f"DCR-{PC}-999-{audience}"
                dcr["display_id"] = f"DCR-{PC}-999"
                dcr["dcr_sequence"] = 999
                html = out / f"dcr_{audience}.html"
                html.write_text(DCRHTMLRenderer(dcr).render(), encoding="utf-8")
                pdf = out / f"dcr_{audience}.pdf"
                r = pdf_export.render_html_to_pdf(html, pdf, engine="chromium")
                ok(f"dcr_{audience}_chromium_ok", bool(r.get("ok")),
                   (r.get("error") or "")[:90])
                ok(f"dcr_{audience}_valid_pages", r.get("ok") and pdf_pages(pdf) >= 1
                   and pdf.stat().st_size > 10_000,
                   f"pages={pdf_pages(pdf)} size={pdf.stat().st_size if pdf.exists() else 0}")
        finally:
            cleanup()

        form_src = SCRIPT_DIR / "forms_source" / "blank_daily_suspended_scaffold_checklist.html"
        pdf = out / "form.pdf"
        r = pdf_export.render_html_to_pdf(form_src, pdf, engine="chromium")
        ok("form_chromium_ok", bool(r.get("ok")), (r.get("error") or "")[:90])
        ok("form_one_page", r.get("ok") and pdf_pages(pdf) == 1, f"pages={pdf_pages(pdf)}")

        cred_html = out / "cred.html"
        cred_html.write_text(CRED_FIXTURE, encoding="utf-8")
        pdf = out / "cred.pdf"
        r = pdf_export.render_html_to_pdf(cred_html, pdf, engine="chromium")
        ok("credential_chromium_ok", bool(r.get("ok")), (r.get("error") or "")[:90])
        ok("credential_cr80_two_pages", r.get("ok") and pdf_pages(pdf) == 2,
           f"pages={pdf_pages(pdf)}")

        # ---- PLANT: nonexistent binary -> clean, fast, actionable, no artifact ----
        os.environ["SSC_CHROMIUM_PATH"] = str(out / "no_such_browser.exe")
        plant_pdf = out / "plant.pdf"
        t0 = time.time()
        try:
            pdf_export.render_html_to_pdf(cred_html, plant_pdf, engine="chromium")
            ok("plant_bad_binary_raises", False, "no exception raised")
        except pdf_export.PDFExportError as e:
            ok("plant_bad_binary_raises", "SSC_CHROMIUM_PATH" in str(e)
               and "no_such_browser" in str(e), str(e)[:90])
        finally:
            os.environ.pop("SSC_CHROMIUM_PATH", None)
        ok("plant_fails_fast", (time.time() - t0) < 5.0, f"{time.time() - t0:.1f}s")
        ok("plant_no_pdf_artifact", not plant_pdf.exists())
    finally:
        if saved_engine is not None:
            os.environ["SSC_PDF_ENGINE"] = saved_engine
        if saved_chromium is not None:
            os.environ["SSC_CHROMIUM_PATH"] = saved_chromium
        shutil.rmtree(out, ignore_errors=True)

    print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
