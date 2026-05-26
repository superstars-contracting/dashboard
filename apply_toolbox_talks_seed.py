#!/usr/bin/env python3
"""Apply toolbox_talks schema + seed all defined Ch 33 talks.

Reads toolbox_talks_data.TALKS as the source of truth. Each talk has
an EN and an ES HTML in toolbox_talks_source/; the seed renders the
two PDFs (via headless Edge) if missing, then INSERT OR IGNOREs the
row keyed on topic_number.

Idempotent — re-runs are no-ops when content is unchanged.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_toolbox_talks.sql"
TALKS_DIR = SCRIPT_DIR / "data_room" / "toolbox_talks"     # /files/ serves these
SOURCES_DIR = SCRIPT_DIR / "toolbox_talks_source"          # tracked HTML

from toolbox_talks_data import TALKS  # noqa: E402


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

    # ---- Render + Seed ----
    TALKS_DIR.mkdir(parents=True, exist_ok=True)
    inserted = ignored = missing = rendered = 0
    for t in TALKS:
        slug = t["slug"]
        topic_number = t["topic_number"]
        for lang in ("en", "es"):
            src = SOURCES_DIR / f"{slug}_{lang}.html"
            tgt = TALKS_DIR / f"{slug}_{lang}.pdf"
            if not tgt.exists():
                if not src.exists():
                    print(f"[toolbox] WARN: source missing for {slug}_{lang}; skipping render")
                    missing += 1
                    continue
                try:
                    from pdf_export import render_html_to_pdf
                    r = render_html_to_pdf(src.resolve(), tgt.resolve())
                    if not r.get("ok"):
                        print(f"[toolbox] WARN: render failed for {slug}_{lang}: {r.get('error')}")
                        missing += 1
                        continue
                    rendered += 1
                    print(f"[toolbox] rendered {slug}_{lang}.pdf ({r.get('size')} bytes)")
                except Exception as e:
                    print(f"[toolbox] WARN: render exception for {slug}_{lang}: {e}")
                    missing += 1
                    continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO toolbox_talks "
            "(topic_number, category, title_en, title_es, ch33_ref, "
            " filename_en, filename_es, est_minutes, description) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                topic_number,
                t.get("category"),
                t["title_en"],
                t["title_es"],
                t.get("ch33_ref"),
                f"{slug}_en.pdf",
                f"{slug}_es.pdf",
                t.get("est_minutes", 15),
                t.get("description", ""),
            ),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            ignored += 1
    conn.commit()

    total = conn.execute("SELECT COUNT(*) FROM toolbox_talks").fetchone()[0]
    print(f"[toolbox] schema: applied={applied} skipped={skipped} failed={failed}")
    print(
        f"[toolbox] seed: inserted={inserted} ignored={ignored} "
        f"missing={missing} rendered={rendered} (total in DB: {total})"
    )
    for r in conn.execute(
        "SELECT topic_number, category, title_en, ch33_ref, filename_en, filename_es "
        "FROM toolbox_talks ORDER BY topic_number"
    ):
        print(
            f"  #{r[0]:>2}  [{r[1] or '—':9}]  {r[2]}  ({r[3]})  -> {r[4]} / {r[5]}"
        )
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
