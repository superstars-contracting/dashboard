"""#195 — Replay #192's Kevin 5-21 sign_in_log insert after the
test_weekly_hours smoke landmine silently destroyed it.

This script restores the row that commit a575153 (#192) inserted:
  sign_in_log:
    date         = '2026-05-21'
    employee_id  = 'E-00003'  (worker_id W-0003)
    project_code = 'FR-BX-001'
    time_in      = '07:00'
    time_out     = '11:30'    (= 4.0 hours worked per
                                payroll_hours.compute_worked_hours)

Idempotent: if Kevin's 5-21 row already exists with the canonical
shape, the script is a no-op. Audit_log carries the replay reason
so future diffs distinguish the original #192 insert (audit id 86,
action='signin_operator_insert') from this replay.

PII discipline: W-#### + date + hours operational; never rate values
or worker names in the audit payload or script output.
"""
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from payroll_hours import compute_worked_hours  # noqa: E402

DB = SCRIPT_DIR / "superstars.db"
PROJECT = "FR-BX-001"
TARGET_DATE = "2026-05-21"
KEVIN_WID = "W-0003"
TIME_IN = "07:00"
TIME_OUT = "11:30"
ACTOR_ROLE = "admin"


def actor_user_id(conn):
    row = conn.execute(
        "SELECT id FROM users WHERE role IN ('admin','c_suite') "
        "AND email NOT LIKE 'smoke%' ORDER BY id ASC LIMIT 1"
    ).fetchone()
    if not row:
        row = conn.execute(
            "SELECT id FROM users WHERE role IN ('admin','c_suite') "
            "ORDER BY id ASC LIMIT 1"
        ).fetchone()
    return row[0] if row else None


def main() -> int:
    derived = compute_worked_hours(TIME_IN, TIME_OUT)
    assert derived == 4.0, f"expected 4.0h, got {derived}h — abort"
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        kevin = conn.execute(
            "SELECT employee_id FROM employees WHERE worker_id = ?",
            (KEVIN_WID,)
        ).fetchone()
        if not kevin:
            print(f"FATAL: {KEVIN_WID} not in employees")
            return 2
        kevin_emp_id = kevin["employee_id"]

        existing = conn.execute(
            "SELECT id, time_in, time_out FROM sign_in_log "
            "WHERE project_code = ? AND date = ? AND employee_id = ?",
            (PROJECT, TARGET_DATE, kevin_emp_id),
        ).fetchone()
        if existing and existing["time_in"] == TIME_IN and existing["time_out"] == TIME_OUT:
            print(f"  {KEVIN_WID} 5-21 row already at canonical shape "
                  f"(id={existing['id']}); no-op.")
            return 0
        if existing:
            # Same date+worker but different shape — UPDATE to canonical
            conn.execute(
                "UPDATE sign_in_log SET time_in = ?, time_out = ?, "
                "       updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (TIME_IN, TIME_OUT, existing["id"]),
            )
            print(f"  {KEVIN_WID} 5-21 row UPDATED to canonical shape "
                  f"(time_in={TIME_IN}, time_out={TIME_OUT}, hours=4.0)")
        else:
            conn.execute(
                "INSERT INTO sign_in_log "
                "(date, employee_id, project_code, time_in, time_out, "
                " created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (TARGET_DATE, kevin_emp_id, PROJECT, TIME_IN, TIME_OUT),
            )
            print(f"  {KEVIN_WID} 5-21 row INSERTED "
                  f"(time_in={TIME_IN}, time_out={TIME_OUT}, hours=4.0)")

        actor = actor_user_id(conn)
        conn.execute(
            "INSERT INTO audit_log "
            "(action, actor_user_id, actor_role, target_type, target_id, "
            " before_json, after_json, note, created_at) "
            "VALUES ('signin_operator_insert', ?, ?, 'worker', ?, ?, ?, ?, "
            "        CURRENT_TIMESTAMP)",
            (
                actor, ACTOR_ROLE, kevin_emp_id,
                json.dumps({"log_present": False}),
                json.dumps({
                    "log_present": True,
                    "hours": 4.0,
                    "source": "operator_correction_replay",
                    "date": TARGET_DATE,
                    "project_code": PROJECT,
                    "reason":
                        "replay_of_192_after_test_weekly_hours_landmine_deleted_it",
                }),
                "#195 — replay of #192 (commit a575153) after "
                "test_weekly_hours smoke landmine destroyed the row "
                "without audit. Source row is bit-identical to the "
                "original #192 INSERT.",
            )
        )
        conn.commit()
        # Verify
        rows = conn.execute(
            "SELECT s.id, e.worker_id, s.time_in, s.time_out "
            "FROM sign_in_log s JOIN employees e ON e.employee_id = s.employee_id "
            "WHERE s.project_code = ? AND s.date = ? "
            "ORDER BY CAST(SUBSTR(e.worker_id, 3) AS INTEGER)",
            (PROJECT, TARGET_DATE),
        ).fetchall()
        print()
        print(f"  Post-replay 5-21 rows: {len(rows)}")
        for r in rows:
            hrs = compute_worked_hours(r["time_in"], r["time_out"])
            print(f"    {r['worker_id']}  time_in={r['time_in']}  "
                  f"time_out={r['time_out']}  hours={hrs:.2f}")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"FATAL: {type(e).__name__}: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
