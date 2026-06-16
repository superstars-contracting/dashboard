"""Worker rate domain logic — pay rates with effective dates + audit.

This module is COMPENSATION-DATA-BEARING. Standing rules:

  - NEVER log rate values to server.log or any disk-side log file.
  - NEVER include rate values in agent reports / screenshots / chats.
  - Audit log entries in the DB ARE allowed to carry before/after JSON
    (the audit table lives behind the auth gate + on the encrypted
    workstation drive), but the writer must never echo that JSON to
    stdout/stderr.
  - Smoke tests use fake rates ($1.00, $2.00 etc.) — never real ones.

Surface restriction (CLAUDE.md "Compensation / payroll data governance"):
  - Rates appear ONLY on the company console (and its API responses).
  - The project dashboard, worker app, rendered DCRs, and any
    field-reachable surface MUST NOT receive rate values.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Optional


# ============= AUDIT LOG =============

def log_audit(
    conn: sqlite3.Connection,
    *,
    action: str,
    actor_user_id: Optional[int],
    actor_role: Optional[str],
    target_type: Optional[str],
    target_id: Optional[str],
    before: Optional[dict] = None,
    after: Optional[dict] = None,
    note: Optional[str] = None,
) -> int:
    """Append an audit_log row. Returns the new row id.

    PII rule: the JSON blobs may carry rate values — that's fine,
    audit_log lives in the gated DB. This function MUST NOT print
    the JSON to any log destination.
    """
    cur = conn.execute(
        "INSERT INTO audit_log "
        "(action, actor_user_id, actor_role, target_type, target_id, "
        " before_json, after_json, note) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            action,
            actor_user_id,
            actor_role,
            target_type,
            target_id,
            json.dumps(before) if before is not None else None,
            json.dumps(after) if after is not None else None,
            note,
        ),
    )
    return cur.lastrowid


# ============= RATE LOOKUPS =============

def get_current_rate(conn: sqlite3.Connection, employee_id: str) -> Optional[dict]:
    """Currently-active rate for a worker, or None if no rate set."""
    row = conn.execute(
        "SELECT id, employee_id, hourly_rate, effective_from, effective_to, "
        "       notes, created_by, created_at "
        "FROM worker_rates "
        "WHERE employee_id = ? AND effective_to IS NULL "
        "ORDER BY effective_from DESC LIMIT 1",
        (employee_id,),
    ).fetchone()
    if not row:
        return None
    return dict(row)


def get_rate_effective_on(
    conn: sqlite3.Connection, employee_id: str, on_date: str
) -> Optional[dict]:
    """Rate that was effective for this worker on the given ISO date.

    Convention (documented per the handoff): if a mid-week change
    happens, the LRT looks up the rate effective on the WEEK'S START
    DATE (Monday). The handoff explicitly accepts this construction-
    standard simplification — the alternative (splitting weeks at the
    raise date) requires per-day rate lookups and double the rows on
    payroll. Operator-side: schedule rate changes on a Monday.
    """
    row = conn.execute(
        "SELECT id, employee_id, hourly_rate, effective_from, effective_to, "
        "       notes, created_by, created_at "
        "FROM worker_rates "
        "WHERE employee_id = ? "
        "  AND effective_from <= ? "
        "  AND (effective_to IS NULL OR effective_to >= ?) "
        "ORDER BY effective_from DESC LIMIT 1",
        (employee_id, on_date, on_date),
    ).fetchone()
    return dict(row) if row else None


def get_rate_history(conn: sqlite3.Connection, employee_id: str) -> list[dict]:
    """All rate rows for a worker, newest first."""
    rows = conn.execute(
        "SELECT wr.id, wr.employee_id, wr.hourly_rate, wr.effective_from, "
        "       wr.effective_to, wr.notes, wr.created_by, wr.created_at, "
        "       u.full_name AS created_by_name, u.email AS created_by_email "
        "FROM worker_rates wr "
        "LEFT JOIN users u ON u.id = wr.created_by "
        "WHERE wr.employee_id = ? "
        "ORDER BY wr.effective_from DESC, wr.id DESC",
        (employee_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ============= MUTATIONS =============

class RateError(ValueError):
    """Operator-facing rate validation failure."""


def set_rate(
    conn: sqlite3.Connection,
    *,
    employee_id: str,
    hourly_rate: float,
    effective_from: str,
    notes: Optional[str],
    actor_user_id: int,
    actor_role: str,
) -> dict:
    """Atomically end-date the current active rate and insert the new one.

    Validation:
      - hourly_rate > 0
      - effective_from is a valid ISO date
      - effective_from must be >= current active rate's effective_from
        (cannot back-date BEFORE the row it would supersede)

    Audit:
      - One audit_log row with action='rate_change', before = old current
        row (or None if none), after = new row.

    Returns the newly inserted row as a dict.
    """
    # Validate hourly_rate
    try:
        rate_val = float(hourly_rate)
    except (TypeError, ValueError):
        raise RateError("hourly_rate must be a number")
    if rate_val <= 0:
        raise RateError("hourly_rate must be positive")
    # Validate date
    try:
        eff_from = datetime.strptime(effective_from, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise RateError("effective_from must be YYYY-MM-DD")
    # Validate worker exists
    emp_row = conn.execute(
        "SELECT employee_id FROM employees WHERE employee_id = ?", (employee_id,)
    ).fetchone()
    if not emp_row:
        raise RateError(f"unknown employee_id {employee_id}")

    # Get current active rate (if any)
    current = get_current_rate(conn, employee_id)

    # If there's already an active rate, ensure new effective_from
    # doesn't predate the existing active's effective_from.
    if current:
        existing_from = datetime.strptime(current["effective_from"], "%Y-%m-%d").date()
        if eff_from < existing_from:
            raise RateError(
                "effective_from cannot precede the current active rate's effective_from"
            )

    # Atomic: end-date the old + insert the new in one transaction.
    # If new effective_from == existing effective_from, the existing row
    # gets effective_to = effective_from - 1 day = a 1-day-old row that
    # never overlapped — equivalent to "supersede on the same day."
    try:
        conn.execute("BEGIN")
        if current:
            end_date = (eff_from - timedelta(days=1)).isoformat()
            conn.execute(
                "UPDATE worker_rates SET effective_to = ? WHERE id = ?",
                (end_date, current["id"]),
            )
        cur = conn.execute(
            "INSERT INTO worker_rates "
            "(employee_id, hourly_rate, effective_from, effective_to, "
            " notes, created_by) "
            "VALUES (?, ?, ?, NULL, ?, ?)",
            (employee_id, rate_val, effective_from, notes, actor_user_id),
        )
        new_id = cur.lastrowid

        # Audit: before/after JSON. Allowed in DB; NOT echoed to disk logs.
        log_audit(
            conn,
            action="rate_change",
            actor_user_id=actor_user_id,
            actor_role=actor_role,
            target_type="worker",
            target_id=employee_id,
            before=(
                {
                    "id": current["id"],
                    "hourly_rate": current["hourly_rate"],
                    "effective_from": current["effective_from"],
                    "effective_to_before": current["effective_to"],
                }
                if current
                else None
            ),
            after={
                "id": new_id,
                "hourly_rate": rate_val,
                "effective_from": effective_from,
                "notes": notes,
            },
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    # Re-fetch the new row for the caller
    new_row = conn.execute(
        "SELECT id, employee_id, hourly_rate, effective_from, effective_to, "
        "       notes, created_by, created_at "
        "FROM worker_rates WHERE id = ?",
        (new_id,),
    ).fetchone()
    return dict(new_row)


# ============= APPROVAL BRIDGE (labor_worker_state -> canonical worker_rates) =

def bridge_approved_rate(
    conn: sqlite3.Connection,
    *,
    employee_id: str,
    hourly_rate: float,
    effective_from: str,
    notes: Optional[str],
    actor_user_id: Optional[int],
    actor_role: Optional[str],
) -> int:
    """Reflect an APPROVED labor-rate change into the canonical worker_rates so
    EVERY rate-reading surface (the tracker / payroll grid, which resolve via
    get_rate_effective_on) sees the approved value.

    Unlike set_rate() — the operator-facing add path, which deliberately REJECTS
    back-dating before the current active rate — this is the approval bridge and
    must ALWAYS land the approved value for ALL change types: a rate change, a
    DATE-ONLY change, or a BACKDATE. That gap (set_rate raised on a backdate and
    the approve handler swallowed it) is the #254 bug — an approved backdate never
    reached worker_rates, so the tracker showed 'Rate not set'.

    Effective-dated, single-current model (labor_worker_state holds ONE current
    approved rate): the approved row becomes the current rate from effective_from
    onward. Rows at/after effective_from are superseded by this approval and are
    dropped; the row immediately BEFORE it is end-dated at effective_from-1 so
    earlier weeks keep their historical rate; the approved row is inserted as the
    new current (effective_to NULL). Runs in the CALLER's transaction (no commit),
    so the approval + bridge commit atomically. Returns the new worker_rates id.
    """
    rate_val = float(hourly_rate)
    if rate_val <= 0:
        raise RateError("hourly_rate must be positive")
    try:
        eff = datetime.strptime(effective_from, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        raise RateError("effective_from must be YYYY-MM-DD")

    before = get_current_rate(conn, employee_id)  # for the audit before-image

    # Supersede anything on/after the approved effective date (single-current).
    conn.execute(
        "DELETE FROM worker_rates WHERE employee_id = ? AND effective_from >= ?",
        (employee_id, effective_from),
    )
    # End-date the most recent remaining (strictly-earlier) row so it stops the
    # day before the approved rate begins — earlier weeks keep their old rate.
    prev = conn.execute(
        "SELECT id FROM worker_rates WHERE employee_id = ? AND effective_from < ? "
        "ORDER BY effective_from DESC LIMIT 1", (employee_id, effective_from),
    ).fetchone()
    if prev:
        end_date = (eff - timedelta(days=1)).isoformat()
        conn.execute("UPDATE worker_rates SET effective_to = ? WHERE id = ?",
                     (end_date, prev["id"]))
    cur = conn.execute(
        "INSERT INTO worker_rates "
        "(employee_id, hourly_rate, effective_from, effective_to, notes, created_by) "
        "VALUES (?, ?, ?, NULL, ?, ?)",
        (employee_id, rate_val, effective_from, notes, actor_user_id),
    )
    new_id = cur.lastrowid
    log_audit(
        conn, action="rate_change", actor_user_id=actor_user_id, actor_role=actor_role,
        target_type="worker", target_id=employee_id,
        before=({"hourly_rate": before["hourly_rate"],
                 "effective_from": before["effective_from"]} if before else None),
        after={"id": new_id, "hourly_rate": rate_val, "effective_from": effective_from},
        note=notes or "PM-approved rate change (bridge)",
    )
    return new_id


# ============= ROLE-GATE HELPER (for response shaping) =============

def role_can_see_rates(role: Optional[str]) -> bool:
    """True iff the role is allowed to see compensation values.

    Per the handoff: only 'admin' and 'c_suite'. For anyone else, the
    server must OMIT rate / amount_owed fields entirely from API
    responses (not zero them, not stub them) so sniffed traffic
    reveals nothing about pay.
    """
    return role in ("admin", "c_suite")
