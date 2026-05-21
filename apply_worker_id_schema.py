#!/usr/bin/env python3
"""Idempotent migration: add employees.worker_id + backfill existing rows.

Safe to re-run. Re-running:
  - Skips ALTER TABLE if the column already exists (duplicate column error).
  - Skips CREATE UNIQUE INDEX if it already exists.
  - Backfill ONLY touches rows where worker_id IS NULL — already-assigned
    Worker IDs are never changed.

Backfill order is deterministic: ascending by the numeric portion of
employee_id (per CLAUDE.md schema rule — lexicographic would mis-order
E-00010 before E-00002). This ensures W-0001 maps to E-00001, etc.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_worker_id.sql"


def split_statements(sql_text):
    """Same pattern as apply_riggers_schema.py — strip line comments, split
    on semicolons, return non-empty statements."""
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
    if not SQL_PATH.exists():
        print(f"ERROR: schema_worker_id.sql not found at {SQL_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    # 1. Schema: idempotent ALTER + index
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
    print(f"[worker_id] schema: applied={applied} skipped={skipped} failed={failed}")

    if failed:
        conn.close()
        return 1

    # 2. Backfill: assign W-#### to NULL rows in deterministic order
    from worker_id import next_worker_id_sequence, format_worker_id

    unfilled = conn.execute(
        "SELECT employee_id FROM employees WHERE worker_id IS NULL "
        "ORDER BY CAST(SUBSTR(employee_id, 3) AS INTEGER)"
    ).fetchall()

    if not unfilled:
        # Count totals for the report — no PII printed
        n_total = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        n_with_id = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE worker_id IS NOT NULL"
        ).fetchone()[0]
        print(f"[worker_id] backfill: nothing to assign — {n_with_id}/{n_total} employees "
              f"already have a worker_id (idempotent re-run)")
        conn.close()
        return 0

    next_seq = next_worker_id_sequence(conn)
    assigned = 0
    for row in unfilled:
        emp_id = row[0]
        wid = format_worker_id(next_seq)
        try:
            conn.execute(
                "UPDATE employees SET worker_id = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE employee_id = ?",
                (wid, emp_id),
            )
            assigned += 1
            next_seq += 1
        except sqlite3.IntegrityError as e:
            # Unique index hit — shouldn't happen during backfill but
            # surface clearly if it does.
            print(f"ERROR: failed to assign {wid} to {emp_id}: {e}", file=sys.stderr)
            conn.rollback()
            conn.close()
            return 1
    conn.commit()

    # PII-safe report: counts + (employee_id -> worker_id) mapping only.
    # employee_id is not PII; worker_id is not PII.
    print(f"[worker_id] backfill: assigned {assigned} worker_id(s):")
    pairs = conn.execute(
        "SELECT employee_id, worker_id FROM employees "
        "WHERE worker_id IS NOT NULL "
        "ORDER BY CAST(SUBSTR(employee_id, 3) AS INTEGER)"
    ).fetchall()
    for p in pairs:
        print(f"           {p[0]}  ->  {p[1]}")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
