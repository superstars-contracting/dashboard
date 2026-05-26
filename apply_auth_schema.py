#!/usr/bin/env python3
"""Idempotent migration for dashboard auth foundation (#48).

Creates users + sessions tables. Re-running is safe — duplicate-table /
duplicate-column errors are counted as skipped.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_auth.sql"


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
    conn.execute("PRAGMA foreign_keys=ON;")
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
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()
    user_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    session_count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    conn.close()
    print(f"[auth] applied={applied} skipped={skipped} failed={failed}")
    print(f"[auth] users table: {user_count} row(s)")
    print(f"[auth] sessions table: {session_count} row(s)")
    if user_count == 0:
        print("[auth] no users yet — run `python bootstrap_admin.py` to seed the first admin")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
