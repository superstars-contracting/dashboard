"""Reconcile canonical worker_rates to the approved labor_worker_state (#254).

Why: before #254 the approval->worker_rates bridge silently skipped backdated /
date-only changes (set_rate rejected the backdate, the approve handler swallowed
it), so some workers' approved rate never reached the canonical worker_rates the
tracker/payroll grid reads — they rendered "Rate not set". #254 fixes the bridge
going forward; this reconciles the EXISTING gap.

Scope (safety): reflects ONLY already-approved values from labor_worker_state —
invents no rates, changes no approvals. Idempotent: only touches a worker whose
current worker_rates row doesn't already match the approved (rate, effective_date).

PII / comp-data discipline (CLAUDE.md): prints COUNTS only — never a rate value
or a name. Snapshot the DB before running with --apply (the operator/agent does
this out of band).

Usage:
  python reconcile_worker_rates.py            # DRY-RUN (reports, writes nothing)
  python reconcile_worker_rates.py --apply    # write the reconciliation
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from worker_rates import bridge_approved_rate, get_current_rate  # noqa: E402

DB = ROOT / "superstars.db"
APPLY = "--apply" in sys.argv


def main():
    conn = sqlite3.connect(str(DB), timeout=60)
    conn.row_factory = sqlite3.Row
    states = conn.execute(
        "SELECT worker_id, employee_id, current_rate, effective_date "
        "FROM labor_worker_state "
        "WHERE status='active' AND current_rate IS NOT NULL "
        "  AND employee_id IS NOT NULL AND effective_date IS NOT NULL "
        "  AND effective_date <> ''"
    ).fetchall()

    already_ok = 0
    to_fix = []
    for s in states:
        eid = s["employee_id"]
        cur = get_current_rate(conn, eid)
        matches = (cur is not None
                   and abs(float(cur["hourly_rate"]) - float(s["current_rate"])) < 0.005
                   and (cur["effective_from"] or "") == (s["effective_date"] or ""))
        if matches:
            already_ok += 1
        else:
            to_fix.append(s)

    reconciled = 0
    if APPLY:
        for s in to_fix:
            bridge_approved_rate(
                conn, employee_id=s["employee_id"],
                hourly_rate=float(s["current_rate"]),
                effective_from=s["effective_date"],
                notes="#254 reconcile to approved labor_worker_state",
                actor_user_id=None, actor_role="system",
            )
            conn.commit()
            reconciled += 1

    mode = "APPLIED" if APPLY else "DRY-RUN (no writes)"
    print(f"reconcile {mode}: total_active_rated={len(states)} "
          f"already_ok={already_ok} needing_reconcile={len(to_fix)} reconciled={reconciled}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
