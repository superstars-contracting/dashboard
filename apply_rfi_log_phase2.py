#!/usr/bin/env python3
"""Idempotent migration for Reports Phase 2 — RFI Log full field set.

Applies schema_rfi_log_phase2.sql:
- 9 new columns on rfi_log (subject_title, sent_to, date_response_required,
  date_response_received, question_description, response_answer,
  drawing_spec_reference, impact_magnitude_note, related_documents)
- backfill of new names from legacy column values (idempotent)
- idx_rfi_log_register for the management register's default scan

PII-safe: only column counts / migration counters printed.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_rfi_log_phase2.sql"


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
    conn.execute("PRAGMA busy_timeout=60000;")

    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:140]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()

    cols = [r[1] for r in conn.execute("PRAGMA table_info(rfi_log)").fetchall()]
    expected_new = ['subject_title', 'sent_to', 'date_response_required',
                    'date_response_received', 'question_description',
                    'response_answer', 'drawing_spec_reference',
                    'impact_magnitude_note', 'related_documents']
    missing = [c for c in expected_new if c not in cols]
    print(f"[schema] applied={applied} skipped={skipped} failed={failed}")
    if missing:
        print(f"[verify] WARNING: rfi_log missing columns: {missing}")
        failed += 1
    else:
        print(f"[verify] rfi_log has all 9 new spec columns")
    print(f"[verify] rfi_log total columns: {len(cols)}")
    n = conn.execute("SELECT COUNT(*) FROM rfi_log").fetchone()[0]
    print(f"[verify] rfi_log row count: {n}")
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
