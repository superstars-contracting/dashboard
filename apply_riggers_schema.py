#!/usr/bin/env python3
"""Idempotent migration for project_riggers table + cof_cards.rigger_id."""
import sqlite3, sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_riggers.sql"


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
    riggers = conn.execute("SELECT project_code, rigger_name, license_number, is_default FROM project_riggers").fetchall()
    conn.close()
    print(f"[riggers] applied={applied} skipped={skipped} failed={failed}")
    print(f"[riggers] {len(riggers)} rigger(s) in project_riggers:")
    for r in riggers:
        default = " (DEFAULT)" if r[3] else ""
        print(f"           • {r[0]} | {r[1]} — License #{r[2]}{default}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
