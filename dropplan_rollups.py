"""Drop Plan roll-up computation layer — Batch B (#200).

Pure functions over a sqlite3 connection (row_factory=Row). No stored
duplication: every total is computed from the ledgers (the single source
of truth), per DROP_PLAN_SYSTEM_DESIGN.md §3.7 / §5.

Money discipline (§6, #158 omit-not-zero):
  * drop_cost / project spend return the sentinel string "pending_rates"
    whenever a contributing SOV line has a NULL unit_rate — NEVER $0 for
    unpriced work. Real rates load later from the architect AIA/SOV.
  * The assembling helpers (drop_detail, project_rollup) take an
    `include_cost` flag. When False they OMIT cost/rate/expense KEYS
    ENTIRELY (not zeroed) so a pm/super response simply has no dollar
    fields — the omit is enforced here, not just at the endpoint.

PII-safe: no names; logged_by is surfaced verbatim as a W-####/id token.
"""
from __future__ import annotations

import sqlite3
from typing import Optional, Union

PENDING_RATES = "pending_rates"

# working-days variance tolerance (days) for the on_track band
_VARIANCE_TOL = 0.5


def _rows(conn: sqlite3.Connection, sql: str, args=()):
    return conn.execute(sql, args).fetchall()


def get_template_id(conn: sqlite3.Connection, project_code: str) -> Optional[int]:
    r = conn.execute(
        "SELECT template_id FROM stage_templates WHERE project_code=? ORDER BY template_id LIMIT 1",
        (project_code,)).fetchone()
    return r["template_id"] if r else None


# ---------------- progress ----------------

def drop_progress(conn: sqlite3.Connection, drop_id: str) -> dict:
    """% = complete steps / applicable (non-N/A) steps (§5)."""
    rows = _rows(conn, "SELECT status FROM drop_stage_status WHERE drop_id=?", (drop_id,))
    applicable = [r for r in rows if r["status"] != "n_a"]
    complete = [r for r in applicable if r["status"] == "complete"]
    pct = round(len(complete) / len(applicable) * 100, 1) if applicable else 0.0
    return {
        "complete_steps": len(complete),
        "applicable_steps": len(applicable),
        "total_steps": len(rows),
        "na_steps": len(rows) - len(applicable),
        "pct": pct,
    }


def current_stage(conn: sqlite3.Connection, drop_id: str) -> Optional[dict]:
    """The drop's current step: first in_progress, else first not_started
    (N/A and complete are skipped). None when every applicable step is done."""
    rows = _rows(
        conn,
        "SELECT ds.step_no, ds.status, st.name "
        "FROM drop_stage_status ds "
        "JOIN drops d ON d.drop_id=ds.drop_id "
        "JOIN stage_templates t ON t.project_code=d.project_code "
        "JOIN stage_template_steps st ON st.template_id=t.template_id AND st.step_no=ds.step_no "
        "WHERE ds.drop_id=? ORDER BY ds.step_no", (drop_id,))
    for want in ("in_progress", "not_started"):
        for r in rows:
            if r["status"] == want:
                return {"step_no": r["step_no"], "name": r["name"], "status": r["status"]}
    return None


# ---------------- quantities ----------------

def drop_quantity_totals(conn: sqlite3.Connection, drop_id: str) -> list:
    """SUM(quantity) and SUM(volume_cf) per SOV line for this drop."""
    rows = _rows(
        conn,
        "SELECT s.sov_id, s.sov_code, s.unit, "
        "       ROUND(SUM(q.quantity), 4) AS qty_total, "
        "       ROUND(SUM(q.volume_cf), 4) AS volume_total, "
        "       COUNT(*) AS entry_count "
        "FROM quantity_entries q JOIN sov_line_items s ON s.sov_id=q.sov_line_item "
        "WHERE q.drop_id=? GROUP BY s.sov_id ORDER BY s.sov_code", (drop_id,))
    return [dict(r) for r in rows]


# ---------------- working days / variance ----------------

def drop_working_days(conn: sqlite3.Connection, drop_id: str) -> dict:
    """Planned (template) vs actual (logged) working days + variance/status.

    planned_total = sum default_working_days over applicable (non-N/A) steps.
    Variance is computed over the steps that HAVE an actual logged, so we
    compare like-for-like: planned_to_date - actual_to_date (positive=ahead).
    """
    rows = _rows(
        conn,
        "SELECT ds.status, ds.working_days_actual, st.default_working_days "
        "FROM drop_stage_status ds "
        "JOIN drops d ON d.drop_id=ds.drop_id "
        "JOIN stage_templates t ON t.project_code=d.project_code "
        "JOIN stage_template_steps st ON st.template_id=t.template_id AND st.step_no=ds.step_no "
        "WHERE ds.drop_id=?", (drop_id,))
    applicable = [r for r in rows if r["status"] != "n_a"]
    planned_total = round(sum((r["default_working_days"] or 0) for r in applicable), 2)
    with_actual = [r for r in applicable if r["working_days_actual"] is not None]
    actual_to_date = round(sum(r["working_days_actual"] for r in with_actual), 2)
    planned_to_date = round(sum((r["default_working_days"] or 0) for r in with_actual), 2)
    if not with_actual:
        status = "no_actuals"
        variance = 0.0
    else:
        variance = round(planned_to_date - actual_to_date, 2)
        if variance > _VARIANCE_TOL:
            status = "ahead"
        elif variance < -_VARIANCE_TOL:
            status = "behind"
        else:
            status = "on_track"
    return {
        "planned_total_days": planned_total,
        "planned_to_date_days": planned_to_date,
        "actual_to_date_days": actual_to_date,
        "variance_days": variance,
        "status": status,
    }


# ---------------- cost (money — gate at caller) ----------------

def drop_cost(conn: sqlite3.Connection, drop_id: str) -> Union[float, str]:
    """Σ(quantity × unit_rate) per SOV line. Returns PENDING_RATES if ANY
    contributing line's unit_rate is NULL (never $0 for unpriced work).
    Returns 0.0 only when there are genuinely no quantity entries."""
    rows = _rows(
        conn,
        "SELECT s.unit_rate AS rate, SUM(q.quantity) AS qty "
        "FROM quantity_entries q JOIN sov_line_items s ON s.sov_id=q.sov_line_item "
        "WHERE q.drop_id=? GROUP BY s.sov_id", (drop_id,))
    if not rows:
        return 0.0
    if any(r["rate"] is None for r in rows):
        return PENDING_RATES
    return round(sum((r["qty"] or 0) * r["rate"] for r in rows), 2)


def drop_expense_total(conn: sqlite3.Connection, drop_id: str) -> float:
    r = conn.execute(
        "SELECT ROUND(SUM(amount), 2) FROM expense_entries WHERE drop_id=?", (drop_id,)).fetchone()
    return r[0] if r and r[0] is not None else 0.0


# ---------------- assemblers (omit-not-zero) ----------------

def drop_summary(conn: sqlite3.Connection, drop_id: str, include_cost: bool) -> Optional[dict]:
    """List-row summary for a drop. NEVER includes dollars (list view)."""
    d = conn.execute(
        "SELECT drop_id, project_code, elevation, sequence_no, window_count, lifecycle, "
        "structural_signoff_at, closed_at FROM drops WHERE drop_id=?", (drop_id,)).fetchone()
    if not d:
        return None
    out = dict(d)
    out["progress"] = drop_progress(conn, drop_id)
    out["current_stage"] = current_stage(conn, drop_id)
    out["working_days"] = drop_working_days(conn, drop_id)
    return out


def drop_detail(conn: sqlite3.Connection, drop_id: str, include_cost: bool) -> Optional[dict]:
    """Full drop detail. include_cost=False OMITS cost + expense keys entirely."""
    out = drop_summary(conn, drop_id, include_cost)
    if out is None:
        return None
    steps = _rows(
        conn,
        "SELECT ds.step_no, st.name, ds.status, ds.started_on, ds.completed_on, "
        "ds.working_days_actual, st.default_working_days, st.is_cure_gate, st.is_signoff_gate "
        "FROM drop_stage_status ds "
        "JOIN drops d ON d.drop_id=ds.drop_id "
        "JOIN stage_templates t ON t.project_code=d.project_code "
        "JOIN stage_template_steps st ON st.template_id=t.template_id AND st.step_no=ds.step_no "
        "WHERE ds.drop_id=? ORDER BY ds.step_no", (drop_id,))
    out["stages"] = [dict(s) for s in steps]
    out["quantity_totals"] = drop_quantity_totals(conn, drop_id)
    if include_cost:
        out["cost"] = drop_cost(conn, drop_id)        # float or "pending_rates"
        out["expense_total"] = drop_expense_total(conn, drop_id)
    # else: dollar keys intentionally ABSENT (omit-not-zero, §6 / #158)
    return out


def project_rollup(conn: sqlite3.Connection, project_code: str, include_cost: bool) -> dict:
    """Project-level roll-up. Quantities always; spend/expenses only when
    include_cost (keys omitted otherwise)."""
    drop_ids = [r["drop_id"] for r in _rows(
        conn, "SELECT drop_id FROM drops WHERE project_code=? ORDER BY sequence_no", (project_code,))]

    # aggregate progress = total complete / total applicable across drops
    comp = appl = 0
    for did in drop_ids:
        p = drop_progress(conn, did)
        comp += p["complete_steps"]
        appl += p["applicable_steps"]
    overall_pct = round(comp / appl * 100, 1) if appl else 0.0

    qty_by_sov = [dict(r) for r in _rows(
        conn,
        "SELECT s.sov_code, s.unit, ROUND(SUM(q.quantity),4) AS qty_total, "
        "ROUND(SUM(q.volume_cf),4) AS volume_total "
        "FROM quantity_entries q "
        "JOIN sov_line_items s ON s.sov_id=q.sov_line_item "
        "JOIN drops d ON d.drop_id=q.drop_id "
        "WHERE d.project_code=? GROUP BY s.sov_id ORDER BY s.sov_code", (project_code,))]

    out = {
        "project_code": project_code,
        "drop_count": len(drop_ids),
        "overall_progress_pct": overall_pct,
        "quantity_by_sov": qty_by_sov,
    }
    if include_cost:
        # project spend = sum of drop costs; pending_rates if ANY drop is pending
        costs = [drop_cost(conn, did) for did in drop_ids]
        if any(c == PENDING_RATES for c in costs):
            out["total_spend"] = PENDING_RATES
        else:
            out["total_spend"] = round(sum(c for c in costs), 2)
        exp = conn.execute(
            "SELECT ROUND(SUM(amount),2) FROM expense_entries WHERE project_code=?",
            (project_code,)).fetchone()[0]
        out["total_expenses"] = exp if exp is not None else 0.0
    return out
