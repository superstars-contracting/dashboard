#!/usr/bin/env python3
"""Apply blank_forms schema + seed the first form (Daily Suspended
Scaffold Checklist). Idempotent.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
import ssc_paths  # #287
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_blank_forms.sql"
FORMS_DIR = ssc_paths.under_root("data_room", "forms")   # #287   # serve location (gitignored)
SOURCES_DIR = SCRIPT_DIR / "forms_source"        # tracked source HTML

# (title, filename, source_html, category, description)
# Title preserves operator-specified casing + punctuation verbatim
# (note the "BLANK-" prefix + space — that's how it should display).
# source_html is the tracked path under forms_source/; if the PDF isn't
# present in FORMS_DIR, the seed re-renders it via pdf_export so a
# fresh checkout boots up with the catalog intact.
SEED = [
    (
        "BLANK- Daily Suspended Scaffold Checklist",
        "blank_daily_suspended_scaffold_checklist.pdf",
        "blank_daily_suspended_scaffold_checklist.html",
        "Safety",
        "Pre-shift safety inspection for suspended (swing-stage) scaffold operations. "
        "NYC DOB / OSHA. Print fresh each shift; competent person signs.",
    ),
]


def split_statements(sql_text):
    cleaned = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[:line.index("--")]
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
    # If the PDF isn't on disk, render it from the tracked source HTML
    # so a fresh checkout boots with the catalog intact. Skips the row
    # only if both the PDF AND the source HTML are missing.
    FORMS_DIR.mkdir(parents=True, exist_ok=True)
    inserted = ignored = missing = rendered = 0
    for title, filename, source_html, category, description in SEED:
        target = FORMS_DIR / filename
        if not target.exists():
            src = SOURCES_DIR / source_html
            if not src.exists():
                print(f"[blank-forms] WARN: PDF + source HTML both missing for {title!r}; skipping")
                missing += 1
                continue
            try:
                from pdf_export import render_html_to_pdf
                r = render_html_to_pdf(src.resolve(), target.resolve())
                if not r.get("ok"):
                    print(f"[blank-forms] WARN: render failed for {title!r}: {r.get('error')}")
                    missing += 1
                    continue
                rendered += 1
                print(f"[blank-forms] rendered {filename} ({r.get('size')} bytes) from forms_source/")
            except Exception as e:
                print(f"[blank-forms] WARN: render exception for {title!r}: {e}")
                missing += 1
                continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO blank_forms (title, filename, category, description) "
            "VALUES (?, ?, ?, ?)",
            (title, filename, category, description),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            ignored += 1
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM blank_forms").fetchone()[0]
    print(f"[blank-forms] schema: applied={applied} skipped={skipped} failed={failed}")
    print(f"[blank-forms] seed: inserted={inserted} ignored={ignored} missing={missing} rendered_from_source={rendered} (total in DB: {total})")
    for r in conn.execute("SELECT id, title, filename, category FROM blank_forms ORDER BY title"):
        print(f"  {r[0]}  {r[1]}  ({r[3]})  -> {r[2]}")
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
