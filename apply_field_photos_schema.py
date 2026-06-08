"""#235 — apply schema_field_photos.sql (field_photos table + indexes).

Idempotent (safe to re-run): CREATE TABLE / INDEX IF NOT EXISTS via the
split_statements pattern (per the CLAUDE.md migration rule). No seed rows —
field_photos starts empty and fills as the operator uploads.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB = SCRIPT_DIR / "superstars.db"
SQL = SCRIPT_DIR / "schema_field_photos.sql"


def split_statements(sql_text: str):
    out, cur = [], []
    for line in sql_text.splitlines():
        s = line.strip()
        if s.startswith("--") or not s:
            continue
        cur.append(line)
        if s.endswith(";"):
            out.append("\n".join(cur))
            cur = []
    if cur:
        out.append("\n".join(cur))
    return out


def main() -> int:
    if not DB.exists():
        print(f"ABORT: {DB} not found")
        return 1
    conn = sqlite3.connect(str(DB))
    conn.execute("PRAGMA busy_timeout=60000;")
    applied = skipped = 0
    for stmt in split_statements(SQL.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            if "already exists" in str(e) or "duplicate column" in str(e):
                skipped += 1
            else:
                conn.close()
                raise
    conn.commit()
    cols = [r[1] for r in conn.execute("PRAGMA table_info(field_photos)")]
    conn.close()
    print(f"schema: {applied} applied, {skipped} skipped | field_photos columns: {len(cols)}")
    print("columns:", cols)
    return 0


if __name__ == "__main__":
    sys.exit(main())
