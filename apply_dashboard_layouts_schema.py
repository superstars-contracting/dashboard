#!/usr/bin/env python3
"""Idempotent migration for dashboard_layouts (#209).

Per-user, per-page widget layouts (drag/resize positions). Safe to re-run:
'already exists' / 'duplicate column' are counted as skipped (CLAUDE.md
idempotent-migration rule). Snapshot the DB before running (handled by the
batch); this script only adds a table + index, never touches existing rows.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_dashboard_layouts.sql"


def split_statements(sql_text):
    cleaned_lines = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[:line.index("--")]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    out, buf = [], []
    for ch in cleaned:
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
                print(f"ERROR: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()
    # report shape only (no rows)
    has = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='dashboard_layouts'"
    ).fetchone()
    conn.close()
    print(f"[dashboard_layouts] applied={applied} skipped={skipped} failed={failed} "
          f"table_present={bool(has)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
