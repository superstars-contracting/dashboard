#!/usr/bin/env python3
"""Idempotent migration for construction_agent_provenance (#198).

Creates the Construction Specialist Agent provenance audit table. Run
the DB snapshot BEFORE this (standing rule) — the caller is expected to
have copied superstars.db to data_room/db_backups/ first.

PII-safe: prints counts + the table's column names only, never row
contents.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_construction_agent_provenance.sql"


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
    cols = [r[1] for r in conn.execute(
        "PRAGMA table_info(construction_agent_provenance)").fetchall()]
    n = conn.execute(
        "SELECT COUNT(*) FROM construction_agent_provenance").fetchone()[0]
    conn.close()
    print(f"[cap-provenance] applied={applied} skipped={skipped} failed={failed}")
    print(f"[cap-provenance] columns: {cols}")
    print(f"[cap-provenance] rows currently in table: {n}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
