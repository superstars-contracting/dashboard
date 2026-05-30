"""#206 — Reset FR-BX-001 drop-plan OPERATIONAL state to a clean slate.

The operator will re-activate and backfill every drop on-site, so this clears
the operational drop data back to its initial state WITHOUT touching the
structure. It is the deliberate, auditable, snapshot-guarded version of that
reset (run once; safe to re-run — it is idempotent).

KEEPS (never touched): the 35 `drops` rows themselves, `stage_templates` /
`stage_template_steps`, `sov_line_items`, and the schema.

RESETS (FR-BX-001 only):
  * drop_stage_status : every row -> status='not_started'; started_on,
                        completed_on, working_days_actual -> NULL
                        (covers any 'complete'/'in_progress'/'n_a' too).
  * quantity_entries  : DELETE all rows for FR-BX-001 drops (every patch).
  * drops             : lifecycle='not_started'; structural_signoff_at,
                        closed_at -> NULL.
  * paint_phases      : status='not_ready'; started_on, completed_on -> NULL.
  * expense_entries   : DELETE all FR-BX-001 rows (if any).
  * audit_log         : ONE PII-safe bulk row (role + counts; no names).

Safety (per CLAUDE.md snapshot rule + Build-a-Layer Playbook non-negotiables):
  1. Snapshots superstars.db FIRST, before any write, to
     data_room/db_backups/superstars-pre-dropplan-reset-<localstamp>.db,
     and aborts if the snapshot is missing/empty.
  2. All mutations run in a single transaction (BEGIN IMMEDIATE) — a failure
     rolls the whole reset back, leaving the DB untouched.
  3. Scoped to project_code='FR-BX-001' only. Synthetic SMK-* rows are not
     special-cased: they are not present in normal operation, and any present
     would be reset/deleted just like real ones (acceptable for a clean slate).

PII discipline: prints counts only — never worker names, rates, or PINs.
LOCAL timestamps (datetime.now()), never UTC.

Run:
  python reset_dropplan.py
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB = SCRIPT_DIR / "superstars.db"
BACKUPS = SCRIPT_DIR / "data_room" / "db_backups"
PROJECT = "FR-BX-001"

# rows of this project's drops — the scope for the child tables
DROPS_SUBQ = "SELECT drop_id FROM drops WHERE project_code=?"


def counts(conn: sqlite3.Connection) -> dict:
    """PII-safe operational-state counts for the project (counts only)."""
    one = lambda sql, p=(PROJECT,): conn.execute(sql, p).fetchone()[0]
    return {
        "drops_total": one("SELECT COUNT(*) FROM drops WHERE project_code=?"),
        "drops_active": one("SELECT COUNT(*) FROM drops WHERE project_code=? "
                            "AND lifecycle!='not_started'"),
        "drops_signoff_or_closed": one(
            "SELECT COUNT(*) FROM drops WHERE project_code=? AND "
            "(structural_signoff_at IS NOT NULL OR closed_at IS NOT NULL)"),
        "stage_rows_total": one(
            f"SELECT COUNT(*) FROM drop_stage_status WHERE drop_id IN ({DROPS_SUBQ})"),
        "stage_rows_not_notstarted": one(
            f"SELECT COUNT(*) FROM drop_stage_status WHERE drop_id IN ({DROPS_SUBQ}) "
            "AND status!='not_started'"),
        "stage_rows_with_dates": one(
            f"SELECT COUNT(*) FROM drop_stage_status WHERE drop_id IN ({DROPS_SUBQ}) "
            "AND (started_on IS NOT NULL OR completed_on IS NOT NULL)"),
        "stage_rows_with_wda": one(
            f"SELECT COUNT(*) FROM drop_stage_status WHERE drop_id IN ({DROPS_SUBQ}) "
            "AND working_days_actual IS NOT NULL"),
        "quantity_entries": one(
            f"SELECT COUNT(*) FROM quantity_entries WHERE drop_id IN ({DROPS_SUBQ})"),
        "expense_entries": one("SELECT COUNT(*) FROM expense_entries WHERE project_code=?"),
        "paint_total": one("SELECT COUNT(*) FROM paint_phases WHERE project_code=?"),
        "paint_not_ready": one("SELECT COUNT(*) FROM paint_phases WHERE project_code=? "
                               "AND status='not_ready'"),
        "paint_with_dates": one(
            "SELECT COUNT(*) FROM paint_phases WHERE project_code=? AND "
            "(started_on IS NOT NULL OR completed_on IS NOT NULL)"),
    }


def snapshot() -> Path:
    """Copy the live DB to the backups dir BEFORE any write. Abort on failure."""
    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")  # LOCAL time, never UTC
    dest = BACKUPS / f"superstars-pre-dropplan-reset-{stamp}.db"
    shutil.copy2(DB, dest)
    if not dest.exists() or dest.stat().st_size == 0:
        print(f"ABORT: snapshot failed or empty at {dest}")
        sys.exit(1)
    print(f"  snapshot: {dest.name} ({dest.stat().st_size} bytes)")
    return dest


def main() -> int:
    if not DB.exists():
        print(f"ABORT: {DB} not found")
        return 1

    print(f"#206 reset — project {PROJECT}")
    snap = snapshot()

    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA busy_timeout=60000;")
    try:
        before = counts(conn)
        print("  BEFORE:", json.dumps(before))

        conn.execute("BEGIN IMMEDIATE;")
        # 1. stage status -> clean (status + all date/actual fields)
        conn.execute(
            f"UPDATE drop_stage_status SET status='not_started', started_on=NULL, "
            f"completed_on=NULL, working_days_actual=NULL WHERE drop_id IN ({DROPS_SUBQ})",
            (PROJECT,))
        # 2. patches -> gone
        conn.execute(
            f"DELETE FROM quantity_entries WHERE drop_id IN ({DROPS_SUBQ})", (PROJECT,))
        # 3. expenses -> gone (likely none)
        conn.execute("DELETE FROM expense_entries WHERE project_code=?", (PROJECT,))
        # 4. drops -> not_started; signoff/closed cleared; stamp the change time
        conn.execute(
            "UPDATE drops SET lifecycle='not_started', structural_signoff_at=NULL, "
            "closed_at=NULL, updated_at=CURRENT_TIMESTAMP WHERE project_code=?", (PROJECT,))
        # 5. paint -> not_ready; dates cleared
        conn.execute(
            "UPDATE paint_phases SET status='not_ready', started_on=NULL, "
            "completed_on=NULL WHERE project_code=?", (PROJECT,))

        after = counts(conn)
        # 6. one PII-safe audit row (role + counts; no names, no auth session)
        audit_after = {"project": PROJECT, "before": before, "after": after,
                       "snapshot": snap.name}
        conn.execute(
            "INSERT INTO audit_log (action, actor_user_id, actor_role, target_type, "
            "target_id, before_json, after_json, note, created_at) "
            "VALUES (?,?,?,?,?,?,?,?, CURRENT_TIMESTAMP)",
            ("dropplan_reset", None, "admin", "project", PROJECT,
             json.dumps(before), json.dumps(audit_after),
             "bulk reset of FR-BX-001 drop operational state for on-site backfill (#206); "
             "structure (drops/templates/SOV/schema) preserved"))
        conn.commit()

        print("  AFTER: ", json.dumps(after))
        ok = (after["drops_active"] == 0
              and after["stage_rows_not_notstarted"] == 0
              and after["stage_rows_with_dates"] == 0
              and after["stage_rows_with_wda"] == 0
              and after["quantity_entries"] == 0
              and after["expense_entries"] == 0
              and after["drops_signoff_or_closed"] == 0
              and after["paint_total"] == after["paint_not_ready"]
              and after["paint_with_dates"] == 0
              and after["drops_total"] == before["drops_total"])  # 35 preserved
        print("  RESULT:", "PASS — clean slate, 35 drops preserved" if ok else "FAIL")
        return 0 if ok else 1
    except Exception as e:
        conn.rollback()
        print(f"  ROLLBACK — {e}")
        return 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
