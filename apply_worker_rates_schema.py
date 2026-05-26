#!/usr/bin/env python3
"""Apply the worker_rates + audit_log schema (#158). Idempotent.

Snapshot before run — caller takes the snapshot, this script does not
(per CLAUDE.md operational-discipline rule, the human / orchestrator
takes pre-migration snapshots so the recovery point is deliberate).
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_worker_rates.sql"


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
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                skipped += 1
            else:
                # Truncate stmt — never echo any rate-bearing data here.
                print(f"ERROR on: {stmt[:80]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()
    n_rates = conn.execute("SELECT COUNT(*) FROM worker_rates").fetchone()[0]
    n_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    print(f"[rates] schema: applied={applied} skipped={skipped} failed={failed}")
    # Counts only — never rate values.
    print(f"[rates] worker_rates rows: {n_rates}  audit_log rows: {n_audit}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
