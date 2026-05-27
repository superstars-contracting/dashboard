#!/usr/bin/env python3
"""#170 — Register the Special Rigger for FR-BX-001.

Replaces the placeholder rigger row (rigger_name='TBD - Replace before
live use', license_number='TBD') seeded by apply_riggers_schema.py with
the actual licensed Special Rigger:

    Arun Mal · NYC DOB Special Rigger License #7652

Idempotent: if Arun Mal is already registered as the active default
rigger for FR-BX-001, this is a no-op. Re-runs are safe.

Schema requirements (already in place via apply_riggers_schema.py):
  - project_riggers carries rigger_name, license_number, rigger_type,
    is_active, is_default, signature_path
  - No UNIQUE constraint on project_code, so multiple riggers per
    project are allowed (a co-Special or Master Rigger can be added
    later without altering schema).

PII / governance:
  - License #7652 is a public NYC DOB record — fine to log.
  - The script logs counts + the new active rigger summary only.

Consumed by:
  - cof_issuer.py — get_default_rigger_for_project() returns this row
    at issuance time; the rigger_name / license_number are snapshotted
    into cof_cards.rigger_name_snapshot / rigger_license_snapshot.
  - /api/cards/<emp_id>/cof/live — renders the snapshot fields into
    cof_card_print.html's RIGGER_NAME / RIGGER_LICENSE placeholders.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"

PROJECT_CODE = "FR-BX-001"
RIGGER_NAME = "Arun Mal"
LICENSE_NUMBER = "7652"
RIGGER_TYPE = "Special Rigger"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")

    # Already done?
    existing = conn.execute(
        "SELECT id FROM project_riggers "
        "WHERE project_code = ? AND rigger_name = ? "
        "  AND license_number = ? AND is_active = 1 AND is_default = 1",
        (PROJECT_CODE, RIGGER_NAME, LICENSE_NUMBER),
    ).fetchone()
    if existing:
        print(f"[rigger] Arun Mal #7652 already the active default for {PROJECT_CODE} (id={existing['id']}); no-op")
        conn.close()
        return 0

    # Update the default placeholder row, or insert if none.
    default = conn.execute(
        "SELECT id FROM project_riggers "
        "WHERE project_code = ? AND is_default = 1 "
        "ORDER BY id ASC LIMIT 1",
        (PROJECT_CODE,),
    ).fetchone()
    if default:
        conn.execute(
            "UPDATE project_riggers SET "
            "  rigger_name=?, license_number=?, rigger_type=?, "
            "  is_active=1, is_default=1, "
            "  updated_at=CURRENT_TIMESTAMP "
            "WHERE id = ?",
            (RIGGER_NAME, LICENSE_NUMBER, RIGGER_TYPE, default["id"]),
        )
        print(f"[rigger] updated default row id={default['id']} -> {RIGGER_NAME} #{LICENSE_NUMBER}")
        keep_id = default["id"]
    else:
        cur = conn.execute(
            "INSERT INTO project_riggers "
            "(project_code, rigger_name, license_number, rigger_type, "
            " is_active, is_default) "
            "VALUES (?, ?, ?, ?, 1, 1)",
            (PROJECT_CODE, RIGGER_NAME, LICENSE_NUMBER, RIGGER_TYPE),
        )
        keep_id = cur.lastrowid
        print(f"[rigger] inserted new default row id={keep_id} -> {RIGGER_NAME} #{LICENSE_NUMBER}")

    # Drop any leftover "TBD" placeholder rows on this project.
    cur = conn.execute(
        "DELETE FROM project_riggers "
        "WHERE project_code = ? "
        "  AND (rigger_name LIKE 'TBD%' OR license_number LIKE 'TBD%') "
        "  AND id != ?",
        (PROJECT_CODE, keep_id),
    )
    if cur.rowcount:
        print(f"[rigger] dropped {cur.rowcount} stale TBD placeholder row(s)")

    conn.commit()
    n = conn.execute(
        "SELECT COUNT(*) FROM project_riggers WHERE project_code = ? AND is_active = 1",
        (PROJECT_CODE,),
    ).fetchone()[0]
    print(f"[rigger] active riggers for {PROJECT_CODE}: {n}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
