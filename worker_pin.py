"""Canonical worker-PIN helpers (#188).

The PIN derivation rule — last 4 digits of the worker's phone — was
inlined in three places by the WF-3 / #126 commit (`server.py` POST
/api/workers/create and PATCH /api/employees, plus `import_workers.py`).
This module factors the derivation + persistence + collision-handling
into a single canonical implementation so that:

  - The #188 backfill script (one-shot, fills NULL PINs that pre-date
    WF-3) uses the same logic as the live onboarding paths.
  - The render-time PIN self-heal guard in the card-render endpoints
    (Option A from the #188 handoff) also uses the same logic, so any
    future worker-create path that bypasses PIN derivation gets
    auto-repaired on first render — cards never print `----`.

PII discipline (CLAUDE.md PII rule):
  - This module NEVER logs the PIN value itself. server.log gets
    `pin_assigned=True` / actor / employee_id only.
  - The audit_log row written by `assign_pin_for_worker` uses
    `{pin_present: false}` / `{pin_present: true}` before/after JSON,
    not the value.
  - Callers should NEVER pass the returned PIN to print() outside of
    the card render itself (the card PDF is the intended PIN surface).

The existing onboarding paths in server.py keep their inline pattern
unchanged — refactoring them is out of scope for #188 and risks UX
drift on the onboarding form. New consumers should call this module.
"""
from __future__ import annotations

import json
import logging
import random
import re
import sqlite3
from typing import Optional


PIN_LENGTH = 4
_PIN_RE = re.compile(r"^[0-9]{4}$")


def is_valid_pin(value: Optional[str]) -> bool:
    """True iff `value` is a 4-character all-digits string."""
    return bool(value) and bool(_PIN_RE.fullmatch(value))


def derive_pin_from_phone(phone: Optional[str]) -> Optional[str]:
    """Last 4 digits of the worker's phone. Returns None if the phone
    is empty or has fewer than 4 digits. Matches the WF-3 / #126 rule
    used by /api/workers/create and PATCH /api/employees.

    Non-digit characters (dashes, spaces, parens, + country code prefix)
    are stripped before slicing — so '(555) 123-4567' yields '4567'.
    """
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) < PIN_LENGTH:
        return None
    return digits[-PIN_LENGTH:]


def pin_in_use(conn: sqlite3.Connection,
               pin: str,
               *,
               exclude_employee_id: Optional[str] = None) -> bool:
    """True iff some OTHER employee already has this PIN (active OR
    archived — collisions matter across both because the worker-app
    PIN-keypad lookup keys on the value alone)."""
    if not is_valid_pin(pin):
        return False
    if exclude_employee_id is None:
        row = conn.execute(
            "SELECT 1 FROM employees WHERE pin = ? LIMIT 1", (pin,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT 1 FROM employees WHERE pin = ? AND employee_id != ? LIMIT 1",
            (pin, exclude_employee_id),
        ).fetchone()
    return row is not None


def _next_random_pin(conn: sqlite3.Connection,
                     exclude_employee_id: Optional[str]) -> Optional[str]:
    """Last-resort: pick a random unused 4-digit PIN. Used only when
    the phone-last-4 derivation collides (the #133 tracked case) or
    when the worker has no phone on file (orphan record).

    Returns None if the universe is genuinely saturated (impossible at
    the operator's current scale — 14 active workers vs 10,000 slots —
    but the explicit return keeps the caller honest).
    """
    # Walk a randomized order through the 0000..9999 space, return the
    # first slot not in use. Cap at 10,000 (the full universe) so the
    # loop terminates even if every slot is taken.
    candidates = list(range(10_000))
    random.shuffle(candidates)
    for n in candidates:
        candidate = f"{n:04d}"
        if not pin_in_use(conn, candidate, exclude_employee_id=exclude_employee_id):
            return candidate
    return None


def assign_pin_for_worker(conn: sqlite3.Connection,
                          employee_id: str,
                          *,
                          actor_user_id: Optional[int] = None,
                          actor_role: Optional[str] = "system",
                          source: str = "pin_backfill") -> Optional[str]:
    """Derive + persist + audit-log a PIN for one worker, atomically.

    Tries phone-last-4 first; on collision (#133), falls back to a
    random unused 4-digit PIN. UPDATEs `employees.pin` and writes an
    `audit_log` row with payload `{pin_present: false}` -> `{pin_present: true}`
    (NEVER the value).

    `source` is logged as the audit `action` value so the operator can
    later distinguish backfill writes from render-time self-heal writes:
      - `pin_backfill` — invoked from apply_pin_backfill_188.py
      - `pin_render_heal` — invoked from the render entry-point guard

    Returns the assigned PIN string on success, or None if the worker
    doesn't exist / cannot be PIN'd (e.g., DB is saturated, which is
    not currently reachable).
    """
    row = conn.execute(
        "SELECT employee_id, phone, pin FROM employees WHERE employee_id = ?",
        (employee_id,)
    ).fetchone()
    if not row:
        return None
    # Schema-agnostic row access (sqlite3.Row OR tuple).
    try:
        existing_phone = row["phone"]
        existing_pin = row["pin"]
    except (TypeError, IndexError):
        existing_phone, existing_pin = row[1], row[2]

    # No-op if a valid PIN already exists.
    if is_valid_pin(existing_pin):
        return existing_pin

    # Try phone-last-4 first.
    candidate = derive_pin_from_phone(existing_phone)
    if candidate and pin_in_use(conn, candidate, exclude_employee_id=employee_id):
        # #133 collision case — escalate to random fallback rather than
        # erroring (we're inside a self-heal flow; cannot fail-loud).
        candidate = None
    if not candidate:
        candidate = _next_random_pin(conn, exclude_employee_id=employee_id)
    if not candidate:
        logging.error(
            "worker_pin.assign_pin_for_worker: PIN universe exhausted "
            f"employee_id={employee_id} (impossible at current scale)"
        )
        return None

    conn.execute(
        "UPDATE employees SET pin = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE employee_id = ?",
        (candidate, employee_id)
    )
    # Audit log — PII-safe payload. The before/after carry presence
    # booleans, NOT the value, per CLAUDE.md PII rule.
    before_json = json.dumps({"pin_present": False})
    after_json = json.dumps({"pin_present": True})
    note = f"#188 / {source} — auto-assigned via canonical worker_pin helper"
    conn.execute(
        """INSERT INTO audit_log (action, actor_user_id, actor_role,
                                  target_type, target_id,
                                  before_json, after_json, note, created_at)
           VALUES (?, ?, ?, 'worker', ?, ?, ?, ?, CURRENT_TIMESTAMP)""",
        (source, actor_user_id, actor_role, employee_id,
         before_json, after_json, note)
    )
    logging.info(
        f"worker_pin: pin_assigned=True employee_id={employee_id} "
        f"source={source} actor_user_id={actor_user_id} actor_role={actor_role}"
    )
    return candidate
