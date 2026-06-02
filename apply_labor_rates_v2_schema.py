#!/usr/bin/env python3
"""Idempotent migration for the Labor Rates redesign (#220).

Creates labor_worker_state + labor_rate_change, then SEEDS each existing worker
(who has a current rate in worker_rates) with:
  - a labor_worker_state row (current_rate = their current worker_rates rate,
    status='active', trade from employees), and
  - one 'initial' labor_rate_change row (status='approved') = the start of their
    rate history.

worker_rates is READ ONLY here — the canonical effective-dated rates the
check-cutting sheet reads are never modified, so the real rates stay intact.
Idempotent: re-running skips workers already in labor_worker_state. Comp-data
discipline: this script never prints a rate value (counts only)."""
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_labor_rates_v2.sql"


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
        print("ERROR: superstars.db not found", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:90]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()

    # ---- data seed: one state row + one initial approved change per worker ----
    now = datetime.now().isoformat(timespec="seconds")
    # Current rate per worker = the worker_rates row with effective_to IS NULL,
    # latest effective_from. Join employees for worker_id + trade.
    rows = conn.execute(
        """
        SELECT e.employee_id, e.worker_id, e.trade,
               wr.hourly_rate, wr.effective_from
        FROM employees e
        JOIN worker_rates wr ON wr.employee_id = e.employee_id
        WHERE wr.effective_to IS NULL
          AND e.worker_id IS NOT NULL
          AND wr.effective_from = (
              SELECT MAX(w2.effective_from) FROM worker_rates w2
              WHERE w2.employee_id = e.employee_id AND w2.effective_to IS NULL
          )
        """
    ).fetchall()

    seeded = already = 0
    for r in rows:
        wid = r["worker_id"]
        exists = conn.execute(
            "SELECT 1 FROM labor_worker_state WHERE worker_id = ?", (wid,)
        ).fetchone()
        if exists:
            already += 1
            continue
        conn.execute(
            "INSERT INTO labor_worker_state (worker_id, employee_id, trade, current_rate, "
            "status, effective_date, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (wid, r["employee_id"], r["trade"], float(r["hourly_rate"]), "active",
             r["effective_from"], now, now),
        )
        conn.execute(
            "INSERT INTO labor_rate_change (worker_id, employee_id, old_rate, new_rate, "
            "effective_date, status, is_initial, submitted_by_role, submitted_at, "
            "decided_by_role, decided_at, note) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (wid, r["employee_id"], None, float(r["hourly_rate"]), r["effective_from"],
             "approved", 1, "system", now, "system", now, "initial rate (migrated)"),
        )
        seeded += 1
    conn.commit()

    state_n = conn.execute("SELECT COUNT(*) FROM labor_worker_state").fetchone()[0]
    init_n = conn.execute(
        "SELECT COUNT(*) FROM labor_rate_change WHERE is_initial = 1").fetchone()[0]
    active_n = conn.execute(
        "SELECT COUNT(*) FROM labor_worker_state WHERE status='active'").fetchone()[0]
    conn.close()

    print(f"[labor-rates v2] schema applied={applied} skipped={skipped} failed={failed}")
    print(f"[labor-rates v2] seeded={seeded} already={already} | "
          f"state rows={state_n} (active={active_n}) | initial history rows={init_n}")
    ok = failed == 0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
