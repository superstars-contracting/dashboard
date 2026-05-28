"""#188 — Backfill missing PINs for active workers in one atomic transaction.

Symptom: three workers (created before WF-3 / #126 landed the auto-PIN
derivation on onboarding) had NULL `employees.pin`, so their cards
render `----` in the PIN field.

This script:
  1. Snapshots the affected worker set (PII-safe — only W-#### + state).
  2. For each worker, calls `worker_pin.assign_pin_for_worker()` which
     derives last-4-phone (or random fallback if that collides),
     UPDATEs the row, and writes an `audit_log` row with PII-safe
     before/after payloads.
  3. Wraps the whole batch in a single transaction so a mid-run failure
     leaves nothing half-written. (The audit_log rows roll back with
     the UPDATEs if the transaction aborts.)

Idempotent: re-running this against an already-PIN'd worker set is a
no-op — `assign_pin_for_worker` short-circuits when a valid PIN exists.

Run:
    python apply_pin_backfill_188.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from worker_pin import assign_pin_for_worker, is_valid_pin  # noqa: E402

DB = SCRIPT_DIR / "superstars.db"
ACTOR_ROLE = "admin"


def actor_user_id(conn: sqlite3.Connection):
    """Best-effort: pick the lowest-numbered non-smoke admin/c_suite
    user for the audit_log actor field. None is acceptable — the row
    still gets written."""
    row = conn.execute(
        "SELECT id FROM users WHERE role IN ('admin','c_suite') "
        "AND email NOT LIKE 'smoke%' "
        "ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if row:
        return row[0]
    row = conn.execute(
        "SELECT id FROM users WHERE role IN ('admin','c_suite') "
        "ORDER BY id ASC LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def main() -> int:
    print("#188 — PIN backfill for active workers with NULL/empty/invalid PINs")
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        # Discover affected workers. Active = archived_at IS NULL.
        affected = conn.execute(
            """SELECT employee_id, worker_id, pin
                 FROM employees
                WHERE archived_at IS NULL
                ORDER BY CAST(SUBSTR(worker_id, 3) AS INTEGER)"""
        ).fetchall()
        targets = [
            r for r in affected
            if not is_valid_pin(r["pin"])
        ]
        print(f"  active workers: {len(affected)}   needing backfill: {len(targets)}")
        for r in targets:
            # PII-safe: only W-#### + the categorical state of pin
            if r["pin"] is None:
                state = "NULL"
            elif r["pin"] == "":
                state = "EMPTY"
            else:
                state = f"WRONG_LEN_{len(r['pin'])}"
            print(f"    {r['worker_id']}: pin_state={state}")

        if not targets:
            print("  no workers need PIN backfill — exiting clean")
            return 0

        actor = actor_user_id(conn)
        # Atomic batch: BEGIN -> per-worker UPDATE+audit -> COMMIT.
        # sqlite3 auto-opens an implicit txn on the first write; we
        # explicitly defer commit until all workers succeed.
        results = []
        for r in targets:
            new_pin = assign_pin_for_worker(
                conn,
                r["employee_id"],
                actor_user_id=actor,
                actor_role=ACTOR_ROLE,
                source="pin_backfill",
            )
            results.append((r["worker_id"], new_pin is not None,
                            is_valid_pin(new_pin)))
        # All-or-nothing: if any worker failed, rollback the whole batch.
        if not all(ok and valid for (_, ok, valid) in results):
            print("  one or more assignments returned invalid — rolling back")
            conn.rollback()
            for w, ok, valid in results:
                print(f"    {w}: assigned={ok}  pin_valid={valid}")
            return 2

        conn.commit()
        print(f"\n  committed {len(results)} PIN backfills:")
        for w, ok, valid in results:
            # PII-safe: report SUCCESS booleans, NEVER the PIN value.
            print(f"    {w}: pin_present_after=True")

        # Post-state verify — re-query and confirm zero remaining.
        remaining = conn.execute(
            """SELECT COUNT(*) FROM employees
                WHERE archived_at IS NULL
                  AND (pin IS NULL OR pin = '' OR length(pin) != 4
                       OR pin NOT GLOB '[0-9][0-9][0-9][0-9]')"""
        ).fetchone()[0]
        print(f"\n  post-backfill: workers with invalid pin = {remaining}")
        return 0 if remaining == 0 else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
