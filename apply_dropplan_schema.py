#!/usr/bin/env python3
"""Idempotent migration for the Drop Plan System — Batch A (#199).

Creates the eight §3 tables from schema_dropplan.sql. Snapshot the DB
BEFORE running (standing rule). PII-safe: prints table names + column
counts only, never row contents.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_dropplan.sql"

EXPECTED_TABLES = [
    "drops", "stage_templates", "stage_template_steps", "drop_stage_status",
    "sov_line_items", "quantity_entries", "expense_entries", "paint_phases",
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
    conn.execute("PRAGMA busy_timeout=60000;")
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()
    print(f"[dropplan-schema] applied={applied} skipped={skipped} failed={failed}")
    for t in EXPECTED_TABLES:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (t,)
        ).fetchone() is not None
        ncols = len(conn.execute(f"PRAGMA table_info({t})").fetchall()) if exists else 0
        print(f"  {t}: {'OK' if exists else 'MISSING'} ({ncols} cols)")
    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
