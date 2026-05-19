#!/usr/bin/env python3
"""One-shot link of the imported roster to project FR-BX-001 (890 E 135th St).

NOTE: This script is historical. Project assignments are now seeded during
the rebuild flow. Re-running is safe (INSERT OR IGNORE-style), but typically a no-op.

cleanup_all_sample_workers.py wiped project_assignments along with everything
else dependent on employees; import_workers.py inserts into employees only.
This script bridges that gap by inserting an active assignment row for every
existing employee against FR-BX-001 so the project dashboard's roster loads.

DRY-RUN by default; pass --execute to actually INSERT. Idempotent: any row
where (project_code, employee_id) already has an active assignment is skipped
silently.

  python assign_workers_to_sc2601.py             # dry-run
  python assign_workers_to_sc2601.py --execute   # actually insert
"""

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
PROJECT_CODE = "FR-BX-001"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true",
                        help="Actually INSERT. Default is dry-run.")
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    # Mirror the server-side INSERT shape at server.py:1102-1107: project_code,
    # employee_id, role_on_project=trade, start_date=today, status='active'.
    today = date.today().isoformat()

    employees = list(conn.execute(
        "SELECT employee_id, name, trade FROM employees "
        "ORDER BY CAST(SUBSTR(employee_id, 3) AS INTEGER)"
    ))
    if not employees:
        print("No rows in employees — nothing to assign.")
        conn.close()
        return 0

    existing_pairs = {
        (r["project_code"], r["employee_id"])
        for r in conn.execute(
            "SELECT project_code, employee_id FROM project_assignments "
            "WHERE project_code = ? AND status = 'active'",
            (PROJECT_CODE,)
        )
    }

    to_insert = []
    skipped = []
    for e in employees:
        if (PROJECT_CODE, e["employee_id"]) in existing_pairs:
            skipped.append(e["employee_id"])
        else:
            to_insert.append(e)

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"[{mode}] Link roster to project {PROJECT_CODE}")
    print()
    if skipped:
        print(f"Already linked (skipped): {len(skipped)}")
        for eid in skipped:
            print(f"  - {eid}")
        print()

    if not to_insert:
        print("Nothing new to insert. Exiting.")
        conn.close()
        return 0

    print(f"Would insert {len(to_insert)} new assignment row(s) (start_date={today}):")
    print()
    print(f"  {'employee_id':<10}  {'initial':<8}  {'role_on_project':<28}  {'status':<8}")
    print(f"  {'-'*10}  {'-'*8}  {'-'*28}  {'-'*8}")
    for e in to_insert:
        initial = (e["name"][:1] + ".") if e["name"] else ""
        role = (e["trade"] or "-")[:28]
        print(f"  {e['employee_id']:<10}  {initial:<8}  {role:<28}  active")

    if not args.execute:
        print()
        print("Dry-run only. Re-run with --execute to insert.")
        conn.close()
        return 0

    print()
    print("Inserting...")
    try:
        for e in to_insert:
            conn.execute(
                """INSERT INTO project_assignments
                   (project_code, employee_id, role_on_project, start_date, status)
                   VALUES (?, ?, ?, ?, 'active')""",
                (PROJECT_CODE, e["employee_id"], e["trade"], today)
            )
        conn.commit()
    except sqlite3.Error as ex:
        conn.rollback()
        print(f"ERROR: SQL failure, rolled back: {ex}", file=sys.stderr)
        conn.close()
        return 1

    total = conn.execute(
        "SELECT COUNT(*) FROM project_assignments WHERE project_code = ? AND status = 'active'",
        (PROJECT_CODE,)
    ).fetchone()[0]
    conn.close()
    print()
    print(f"Inserted {len(to_insert)} row(s).")
    print(f"Active assignments for {PROJECT_CODE}: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
