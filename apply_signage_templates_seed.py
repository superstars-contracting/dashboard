#!/usr/bin/env python3
"""Apply signage_templates schema + seed the 10 standard site signs.

Idempotent: schema is CREATE TABLE IF NOT EXISTS, seed is INSERT OR
IGNORE on UNIQUE(title). Re-runs render any missing PDFs from the
tracked source HTMLs under signage_templates_source/ so a fresh
checkout boots up with the catalog intact (same pattern as
apply_blank_forms_seed).
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_signage_templates.sql"
SIGNS_DIR = SCRIPT_DIR / "data_room" / "signage"          # served via /files/
SOURCES_DIR = SCRIPT_DIR / "signage_templates_source"     # tracked HTML

# (code, title, filename, source_html, category, orientation, description)
SEED = [
    (
        "SAFE-001",
        "DANGER — Hard Hat Area",
        "danger_hard_hat_area.pdf",
        "danger_hard_hat_area.html",
        "Safety",
        "portrait",
        "ANSI Z535 danger sign. Post at every entry to a hard-hat-required zone.",
    ),
    (
        "SAFE-002",
        "WARNING — Men Working Above",
        "warning_men_working_above.pdf",
        "warning_men_working_above.html",
        "Safety",
        "portrait",
        "ANSI Z535 warning sign with upward arrow. Post below any overhead "
        "work zone (suspended scaffold drop, lift, hoist path).",
    ),
    (
        "SAFE-003",
        "CAUTION — Construction in Progress",
        "caution_construction_in_progress.pdf",
        "caution_construction_in_progress.html",
        "Safety",
        "portrait",
        "ANSI Z535 caution sign. General site-boundary marker.",
    ),
    (
        "SAFE-004",
        "CAUTION — Do Not Enter / Authorized Personnel Only",
        "caution_do_not_enter.pdf",
        "caution_do_not_enter.html",
        "Site",
        "portrait",
        "Caution sign with circle-slash hand pictogram. Post at restricted "
        "access points (drop zone, electrical, work platforms).",
    ),
    (
        "PPE-001",
        "NOTICE — All PPE Required Beyond This Point",
        "notice_all_ppe_required.pdf",
        "notice_all_ppe_required.html",
        "PPE",
        "portrait",
        "Notice sign with 6 PPE pictograms (hard hat, eye, hearing, hi-vis, "
        "gloves, boots). Post at PPE-mandatory entry points.",
    ),
    (
        "SITE-001",
        "NOTICE — Keep Work Area Clean",
        "notice_keep_work_area_clean.pdf",
        "notice_keep_work_area_clean.html",
        "Site",
        "portrait",
        "Housekeeping reminder. Post in shared work zones, debris staging, "
        "and at scaffold drops.",
    ),
    (
        "SAFE-005",
        "NO SMOKING",
        "no_smoking.pdf",
        "no_smoking.html",
        "Safety",
        "landscape",
        "No-smoking sign with red circle-slash cigarette pictogram. Landscape "
        "format. Required by NYC FDNY where flammables are stored.",
    ),
    (
        "DOB-001",
        "RESTRICTED AREA — Construction Work in Progress (U-1012-01)",
        "restricted_area_construction.pdf",
        "restricted_area_construction.html",
        "DOB",
        "portrait",
        "NYC DOB Restricted Construction / Work in Progress posting (U-1012-01). "
        "Post at site perimeter / restricted floors.",
    ),
    (
        "PPE-002",
        "Job Site Dress Code — PPE Required (English)",
        "dress_code_ppe_en.pdf",
        "dress_code_ppe_en.html",
        "PPE",
        "portrait",
        "Illustrated dress-code poster with labeled PPE callouts: hard hat, "
        "eye / hearing protection, respirator, hi-vis vest, gloves, long "
        "trousers, work shoes. English only.",
    ),
    (
        "PPE-003",
        "Job Site Dress Code — PPE Required (Bilingual EN/ES)",
        "dress_code_ppe_bilingual.pdf",
        "dress_code_ppe_bilingual.html",
        "PPE",
        "portrait",
        "Bilingual (English / Spanish) illustrated dress-code poster. Same "
        "PPE callouts as PPE-002 with Spanish translations under each label.",
    ),
]


def split_statements(sql_text):
    cleaned = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[: line.index("--")]
        cleaned.append(line)
    text = "\n".join(cleaned)
    out, buf = [], []
    for ch in text:
        buf.append(ch)
        if ch == ";":
            s = "".join(buf).strip()
            if s and s != ";":
                out.append(s)
            buf = []
    return out


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")

    # ---- Schema (idempotent) ----
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1

    # ---- Seed (INSERT OR IGNORE on UNIQUE(title)) ----
    SIGNS_DIR.mkdir(parents=True, exist_ok=True)
    inserted = ignored = missing = rendered = 0
    for code, title, filename, source_html, category, orientation, description in SEED:
        target = SIGNS_DIR / filename
        if not target.exists():
            src = SOURCES_DIR / source_html
            if not src.exists():
                print(f"[signage] WARN: PDF + source HTML both missing for {title!r}; skipping")
                missing += 1
                continue
            try:
                from pdf_export import render_html_to_pdf
                r = render_html_to_pdf(src.resolve(), target.resolve())
                if not r.get("ok"):
                    print(f"[signage] WARN: render failed for {title!r}: {r.get('error')}")
                    missing += 1
                    continue
                rendered += 1
                print(f"[signage] rendered {filename} ({r.get('size')} bytes) from signage_templates_source/")
            except Exception as e:
                print(f"[signage] WARN: render exception for {title!r}: {e}")
                missing += 1
                continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO signage_templates "
            "(code, title, filename, category, orientation, description) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (code, title, filename, category, orientation, description),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            ignored += 1
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM signage_templates").fetchone()[0]
    print(f"[signage] schema: applied={applied} skipped={skipped} failed={failed}")
    print(
        f"[signage] seed: inserted={inserted} ignored={ignored} "
        f"missing={missing} rendered_from_source={rendered} (total in DB: {total})"
    )
    for r in conn.execute(
        "SELECT id, code, title, category, orientation, filename "
        "FROM signage_templates ORDER BY category, code"
    ):
        print(f"  {r[0]:>2}  [{r[1] or '—':8}]  {r[2]}  ({r[3]} · {r[4]})  -> {r[5]}")
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
