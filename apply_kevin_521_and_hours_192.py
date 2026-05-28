"""#192 — Kevin 5-21 insert + 5-21 hours correction, atomic transaction.

Operator clarifications from #191:
  - Kevin W-0003 WAS present on 2026-05-21; foreman omitted him from the
    DCR roster. Insert the missing sign_in_log row.
  - 5-21 hours: Robert W-0001 = 6.5h worked; all other field workers
    present = 4h worked.

Schema reminder (the handoff's SQL used phantom columns; this script
uses the real schema): sign_in_log columns are
  (id, date, employee_id, project_code, time_in, time_out,
   created_at, updated_at).
Hours WORKED = payroll_hours.compute_worked_hours(time_in, time_out)
            = (time_out - time_in) - 30min lunch
so:
  4.0h  -> time_in='07:00', time_out='11:30'  (4.5h gross - 0.5h lunch)
  6.5h  -> time_in='07:00', time_out='14:00'  (7.0h gross - 0.5h lunch)
  8.0h  -> time_in='07:00', time_out='15:30'  (8.5h gross - 0.5h lunch)

All operations run in a single transaction so a mid-script failure
rolls back cleanly. Audit log carries PII-safe payloads — hours yes
(operational), rates NEVER.
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
ROBERT_WID = "W-0001"
KEVIN_WID = "W-0003"
COUNT_MIN = 8
COUNT_MAX = 14
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
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        # ----- Phase 1: Kevin insert -----
        actor = actor_user_id(conn)
        kevin_emp = conn.execute(
            "SELECT employee_id FROM employees WHERE worker_id = ?",
            (KEVIN_WID,)
        ).fetchone()
        if not kevin_emp:
            print(f"FATAL: {KEVIN_WID} not found in employees")
            return 2
        kevin_emp_id = kevin_emp["employee_id"]

        already = conn.execute(
            "SELECT id FROM sign_in_log WHERE project_code = ? "
            "AND date = ? AND employee_id = ?",
            (PROJECT, TARGET_DATE, kevin_emp_id),
        ).fetchone()
        if already:
            print(f"  {KEVIN_WID} sign-in row already exists on {TARGET_DATE} "
                  f"(id={already['id']}); skipping insert.")
        else:
            # 4h shift: 07:00 -> 11:30. Verify the math.
            time_in, time_out = "07:00", "11:30"
            derived = compute_worked_hours(time_in, time_out)
            assert derived == 4.0, f"expected 4.0h, got {derived}h — abort"
            conn.execute(
                "INSERT INTO sign_in_log "
                "(date, employee_id, project_code, time_in, time_out, "
                " created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (TARGET_DATE, kevin_emp_id, PROJECT, time_in, time_out),
            )
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
                        "source": "operator_correction",
                        "date": TARGET_DATE,
                        "project_code": PROJECT,
                        "reason": "kevin_was_present_dcr_missed_him",
                    }),
                    "#192 — operator confirmed worker was present; DCR omitted",
                )
            )
            print(f"  {KEVIN_WID} inserted on {TARGET_DATE} "
                  f"(time_in={time_in}, time_out={time_out}, hours=4.0)")

        # ----- Phase 2: count gate -----
        rows = conn.execute(
            "SELECT s.employee_id, e.worker_id, s.time_in, s.time_out "
            "FROM sign_in_log s JOIN employees e ON e.employee_id = s.employee_id "
            "WHERE s.project_code = ? AND s.date = ? "
            "ORDER BY CAST(SUBSTR(e.worker_id, 3) AS INTEGER)",
            (PROJECT, TARGET_DATE),
        ).fetchall()
        n = len(rows)
        print()
        print(f"  Workers on {TARGET_DATE} after insert: {n}")
        for r in rows:
            current = compute_worked_hours(r["time_in"], r["time_out"])
            print(f"    {r['worker_id']}  time_in={r['time_in']}  "
                  f"time_out={r['time_out']}  hours_now={current:.2f}")
        if n < COUNT_MIN or n > COUNT_MAX:
            print(f"\nPAUSE — count {n} outside [{COUNT_MIN}, {COUNT_MAX}].")
            print("Rolling back; operator must review before proceeding.")
            conn.rollback()
            return 3

        # ----- Phase 3: apply hours -----
        # Robert 6.5h -> 07:00..14:00
        # Everyone else 4h -> 07:00..11:30
        ROBERT_OUT = "14:00"
        OTHERS_OUT = "11:30"
        updated = 0
        for r in rows:
            wid = r["worker_id"]
            emp_id = r["employee_id"]
            before_hours = compute_worked_hours(r["time_in"], r["time_out"])
            if wid == ROBERT_WID:
                new_in, new_out = "07:00", ROBERT_OUT
            else:
                new_in, new_out = "07:00", OTHERS_OUT
            new_hours = compute_worked_hours(new_in, new_out)
            if before_hours == new_hours and r["time_in"] == new_in and r["time_out"] == new_out:
                continue
            conn.execute(
                "UPDATE sign_in_log SET time_in = ?, time_out = ?, "
                "       updated_at = CURRENT_TIMESTAMP "
                "WHERE project_code = ? AND date = ? AND employee_id = ?",
                (new_in, new_out, PROJECT, TARGET_DATE, emp_id),
            )
            conn.execute(
                "INSERT INTO audit_log "
                "(action, actor_user_id, actor_role, target_type, target_id, "
                " before_json, after_json, note, created_at) "
                "VALUES ('hours_correction', ?, ?, 'worker', ?, ?, ?, ?, "
                "        CURRENT_TIMESTAMP)",
                (
                    actor, ACTOR_ROLE, emp_id,
                    json.dumps({"hours": before_hours,
                                "date": TARGET_DATE, "project_code": PROJECT}),
                    json.dumps({"hours": new_hours,
                                "date": TARGET_DATE, "project_code": PROJECT}),
                    f"#192 — 5-21 hours correction (operator spec: "
                    f"Robert 6.5h, others 4h)",
                )
            )
            updated += 1
            print(f"    {wid}: {before_hours:.2f}h -> {new_hours:.2f}h")

        # ----- Phase 4: mark the DCR stale so the operator sees it needs reissue -----
        conn.execute(
            "UPDATE report_index SET stale = 1, stale_marked_at = CURRENT_TIMESTAMP "
            "WHERE project_code = ? AND report_date = ? "
            "AND report_type = 'DCR' AND status = 'issued'",
            (PROJECT, TARGET_DATE),
        )

        conn.commit()
        print(f"\n  COMMITTED — {n} rows on {TARGET_DATE}, "
              f"updates applied={updated}; DCR marked stale for reissue.")
        return 0
    except Exception as e:
        conn.rollback()
        print(f"FATAL: {type(e).__name__}: {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
