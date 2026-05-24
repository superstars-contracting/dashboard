#!/usr/bin/env python3
"""Add employees.cof_override and seed it for the current 11 workers.

Two-step migration:
  1. ALTER TABLE employees ADD COLUMN cof_override (idempotent — the
     standard duplicate-column suppression catches re-runs).
  2. UPDATE the existing roster (every worker currently in employees,
     archived rows excluded) to cof_override=1 — a one-shot admin
     override so they can be issued CoF cards before their real
     prerequisite certs have been entered.

Future onboards default to cof_override=0 — the operator must
explicitly flip the override per-worker if they want to issue a CoF
before real certs are entered. The override is reversible and
auditable (one SQL line to unset it per worker).

Idempotency: re-running this script doesn't change rows that already
have cof_override=1; the UPDATE matches the same set each time.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_cof_override.sql"


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

    # ---- 1) Schema migration (idempotent) -----------------------------
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
    if failed:
        conn.rollback()
        conn.close()
        return 1

    # ---- 2) Set cof_override=1 on the current roster -----------------
    # Scope: all NON-archived workers currently in employees. The
    # handoff calls this out as the 11 current workers (W-0001..W-0011);
    # archived rows stay at 0.
    cur = conn.execute(
        "UPDATE employees SET cof_override = 1 "
        "WHERE archived_at IS NULL AND cof_override = 0"
    )
    flipped = cur.rowcount
    conn.commit()

    overridden = conn.execute(
        "SELECT worker_id FROM employees "
        "WHERE cof_override = 1 AND archived_at IS NULL "
        "ORDER BY CAST(SUBSTR(employee_id, 3) AS INTEGER)"
    ).fetchall()
    total_active = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE archived_at IS NULL"
    ).fetchone()[0]
    conn.close()

    print(f"[cof-override] schema ALTERs: applied={applied} skipped={skipped} failed={failed}")
    print(f"[cof-override] rows flipped this run: {flipped}")
    print(f"[cof-override] active employees: {total_active}")
    print(f"[cof-override] override=1 on {len(overridden)} worker(s):")
    print(f"             {', '.join(r[0] for r in overridden if r[0])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
