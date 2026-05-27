#!/usr/bin/env python3
"""#173 — Issue Company ID badges for W-0013 and W-0014.

Both are non-field workers (Laborer trade, no CoF eligibility) — they
just need a Company ID badge. Per the handoff: do NOT touch CoF state
for these two; they should remain CoF-not-applicable.

Idempotent: if either worker already has an active Company ID, the
script skips them.

PII discipline: logs W-#### + trade + booleans only; never echoes
worker names or photo paths.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from worker_rates import log_audit  # noqa: E402
from company_id_issuer import issue_company_id  # noqa: E402

DB = SCRIPT_DIR / "superstars.db"
TARGETS = ["W-0013", "W-0014"]
ISSUER = "Arun Mal"


def actor_user_id():
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    try:
        row = c.execute(
            "SELECT id FROM users WHERE role IN ('admin','c_suite') "
            "AND email NOT LIKE 'smoke%' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            row = c.execute(
                "SELECT id FROM users WHERE role IN ('admin','c_suite') "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None
    finally:
        c.close()


def main():
    actor_id = actor_user_id()
    issued = 0
    skipped = 0
    for wid in TARGETS:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        try:
            emp = c.execute(
                "SELECT employee_id, trade, face_image_path "
                "FROM employees WHERE worker_id = ?",
                (wid,),
            ).fetchone()
        finally:
            c.close()
        if not emp:
            print(f"  {wid}: NOT FOUND — SKIPPED")
            skipped += 1
            continue
        emp_id = emp["employee_id"]
        if not emp["face_image_path"]:
            print(f"  {wid}: no face photo — SKIPPED (upload a photo first)")
            skipped += 1
            continue

        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        try:
            existing = c.execute(
                "SELECT card_id FROM company_id_cards "
                "WHERE employee_id = ? AND status = 'active' LIMIT 1",
                (emp_id,),
            ).fetchone()
        finally:
            c.close()
        if existing:
            print(f"  {wid}: already has active company_id={existing['card_id']} — SKIPPED")
            skipped += 1
            continue

        try:
            card = issue_company_id(emp_id, ISSUER)
        except Exception as e:
            print(f"  {wid}: ISSUE FAILED — {e}")
            skipped += 1
            continue

        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        try:
            log_audit(
                c,
                action="company_id_issue",
                actor_user_id=actor_id,
                actor_role="admin",
                target_type="company_id_card",
                target_id=card["card_id"],
                before=None,
                after={
                    "card_id": card["card_id"],
                    "card_number_display": card.get("card_number_display"),
                    "issued_date": card.get("issued_date"),
                },
                note=f"#173 issue company_id for {wid} (non-field worker, no CoF)",
            )
            c.commit()
        finally:
            c.close()
        issued += 1
        print(f"  {wid}: ISSUED  card_id={card['card_id']}  "
              f"display={card.get('card_number_display')}  "
              f"date={card.get('issued_date')}")

    print(f"\nissued: {issued}  skipped: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
