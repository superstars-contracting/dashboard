#!/usr/bin/env python3
"""Idempotent migration for the Expense / Spend module (#218):
expenses + expense_line_items + expense_class_alias (+ indexes).
Safe to re-run — CREATE ... IF NOT EXISTS, and duplicate/exists errors are
counted as skipped (per CLAUDE.md migration rule)."""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_expenses.sql"


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
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
        "('expenses','expense_line_items','expense_class_alias')").fetchall()}
    conn.close()
    print(f"[expenses] applied={applied} skipped={skipped} failed={failed}")
    print(f"[expenses] tables present: {sorted(tables)}")
    ok = failed == 0 and tables == {'expenses', 'expense_line_items', 'expense_class_alias'}
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
