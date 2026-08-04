"""#278 — Project Cost "Spent to Date" (C-Suite) + the project expense ledger.

COMP-DATA GOVERNANCE (CLAUDE.md, in full): everything here is company-console-only.
Every endpoint is @requires_role('admin','c_suite'); cost keys exist in payloads
ONLY for those roles — any other role gets 403 (omitted, never zeroed) and the
widget is hidden entirely client-side. Hours language is "worked", never "paid" —
this is the cost of labor performed.

LABOR ENGINE: for each sign_in_log row of the project,
  worked hours  = payroll_hours.compute_worked_hours (existing helper, 30-min lunch)
  x the rate    = worker_rates.rate_effective_on(employee_id, THE WORK DATE)
                  (the existing resolver: effective_from <= d <= effective_to,
                  NULL = open) — NOT today's rate; a mid-history raise splits a
                  worker's spend at the boundary to the penny.
  trade         = labor_worker_state.trade via the employee_id bridge.
All money is Decimal (cent-quantized per day-row, summed exactly).

UNRATED BUCKET (honest absence): hours whose work date has NO effective rate are
EXCLUDED from every dollar figure and surfaced as the coral attention chip
("N h unrated — M worker(s) missing an effective rate before <date>") — never a
silent $0.

EXPENSES: project_expense (apply_expenses_278) — date · vendor · category
(materials|equipment|other) · amount · note. VOID-NOT-DELETE: void stamps
who/when + a required audit note; voided rows are flagged in the list and
excluded from every sum. The materials module stays cost-free BY DESIGN.

WEEKS: buckets are Mon-Sun (ISO weeks), labeled by their FRIDAY (the workweek
end). "Last full week" = the most recent COMPLETE week before the current one;
its Friday is the subline's "through Fri MM/DD". The hero total is true
spent-to-DATE (includes the current partial week); the 8-bar series = 7 full
weeks + the current partial (dimmed client-side via `current: true`).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import payroll_hours
import worker_rates as wr
from auth import _db, current_user, requires_role

CATEGORIES = ("materials", "equipment", "other")
_CENT = Decimal("0.01")
_COST_ROLES = ("admin", "c_suite")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _uid():
    return (current_user() or {}).get("id")


def _D(v) -> Decimal:
    return Decimal(str(v))


def _cents(d: Decimal) -> Decimal:
    return d.quantize(_CENT, rounding=ROUND_HALF_UP)


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


# ===================== the labor engine (shared with the smoke) =====================

def labor_breakdown(conn, project_code, today=None) -> dict:
    """Decimal labor spend for one project: per-trade split, weekly buckets,
    and the unrated bucket. Exact math — the smoke asserts to the penny."""
    today = today or date.today()
    rows = conn.execute(
        "SELECT date, employee_id, time_in, time_out FROM sign_in_log "
        "WHERE project_code=? AND time_in IS NOT NULL AND time_out IS NOT NULL "
        "ORDER BY date", (project_code,)).fetchall()
    trade_of = {r["employee_id"]: (r["trade"] or "Unassigned") for r in conn.execute(
        "SELECT employee_id, trade FROM labor_worker_state WHERE employee_id IS NOT NULL"
    ).fetchall()}

    rate_cache = {}          # (emp, date_iso) -> Decimal | None

    def rate_for(emp, d_iso):
        key = (emp, d_iso)
        if key not in rate_cache:
            row = wr.get_rate_effective_on(conn, emp, d_iso)
            rate_cache[key] = _D(row["hourly_rate"]) if row else None
        return rate_cache[key]

    total = Decimal("0")
    total_hours = Decimal("0")
    by_trade = {}            # trade -> {"amount": D, "hours": D}
    weekly = {}              # monday_iso -> D (labor only; expenses merged later)
    workers = set()
    unrated_hours = Decimal("0")
    unrated_workers = set()
    unrated_earliest = None

    for r in rows:
        d_iso = str(r["date"])[:10]
        h = _D(payroll_hours.compute_worked_hours(r["time_in"], r["time_out"]))
        if h <= 0:
            continue
        emp = r["employee_id"]
        rate = rate_for(emp, d_iso)
        if rate is None:
            unrated_hours += h
            unrated_workers.add(emp)
            if unrated_earliest is None or d_iso < unrated_earliest:
                unrated_earliest = d_iso
            continue
        amt = _cents(h * rate)
        total += amt
        total_hours += h
        workers.add(emp)
        tr = trade_of.get(emp, "Unassigned")
        b = by_trade.setdefault(tr, {"amount": Decimal("0"), "hours": Decimal("0")})
        b["amount"] += amt
        b["hours"] += h
        wk = _monday(date.fromisoformat(d_iso)).isoformat()
        weekly[wk] = weekly.get(wk, Decimal("0")) + amt

    return {
        "total": total, "hours": total_hours, "workers": len(workers),
        "by_trade": by_trade, "weekly": weekly,
        "unrated": {"hours": unrated_hours, "workers": len(unrated_workers),
                    "earliest": unrated_earliest} if unrated_hours > 0 else None,
    }


def expense_sums(conn, project_code) -> dict:
    """Non-voided expense totals by category (Decimal) + weekly buckets."""
    rows = conn.execute(
        "SELECT expense_date, category, amount FROM project_expense "
        "WHERE project_code=? AND voided_at IS NULL", (project_code,)).fetchall()
    by_cat = {}
    weekly = {}
    total = Decimal("0")
    for r in rows:
        amt = _cents(_D(r["amount"]))
        total += amt
        by_cat[r["category"]] = by_cat.get(r["category"], Decimal("0")) + amt
        wk = _monday(date.fromisoformat(str(r["expense_date"])[:10])).isoformat()
        weekly[wk] = weekly.get(wk, Decimal("0")) + amt
    return {"total": total, "by_category": by_cat, "weekly": weekly, "count": len(rows)}


def widget_payload(conn, project_code, today=None) -> dict:
    """The full widget payload for ONE project (caller enforces the role gate)."""
    today = today or date.today()
    # #292 — the LABOR ENGINE (per-row worked-hours × day-effective rates) is
    # the expensive NEUTRAL compute; it memoizes via ssc_memo, invalidated by
    # sign-in writes / rate changes / expense writes (see the domain registry).
    # The date rides IN the key: a new day is a new key by construction, never
    # a TTL guess. Everything below — expense sums (cheap, live), shaping,
    # rounding, role-gated serving — stays per-request ABOVE the cache.
    import ssc_memo
    lab = ssc_memo.memoize(("labor_cost", project_code, today.isoformat()),
                           lambda: labor_breakdown(conn, project_code, today))
    exp = expense_sums(conn, project_code)
    total = lab["total"] + exp["total"]

    cur_monday = _monday(today)
    last_full_friday = cur_monday - timedelta(days=3)          # prev week's Friday
    # 8 bars: 7 full weeks + the current partial (dimmed)
    week_starts = [cur_monday - timedelta(weeks=k) for k in range(7, 0, -1)] + [cur_monday]
    weeks = []
    for ws in week_starts:
        iso = ws.isoformat()
        amt = lab["weekly"].get(iso, Decimal("0")) + exp["weekly"].get(iso, Decimal("0"))
        fri = ws + timedelta(days=4)
        weeks.append({"label": f"{fri.month}/{fri.day}", "amount": float(_cents(amt)),
                      "current": ws == cur_monday})
    last_full_iso = (cur_monday - timedelta(weeks=1)).isoformat()
    last_full_total = lab["weekly"].get(last_full_iso, Decimal("0")) \
        + exp["weekly"].get(last_full_iso, Decimal("0"))

    cost_per_hr = _cents(lab["total"] / lab["hours"]) if lab["hours"] > 0 else None
    mat_share = (_cents(exp["total"] / total * 100) if total > 0 and exp["total"] > 0
                 else None)

    return {
        "project_code": project_code,
        "total": float(_cents(total)),
        "labor": {
            "total": float(_cents(lab["total"])),
            "hours_worked": float(lab["hours"]),
            "workers": lab["workers"],
            "by_trade": [
                {"trade": t, "amount": float(_cents(b["amount"])), "hours": float(b["hours"])}
                for t, b in sorted(lab["by_trade"].items(), key=lambda kv: -kv[1]["amount"])
            ],
        },
        "expenses": {
            "total": float(_cents(exp["total"])),
            "by_category": {k: float(_cents(v)) for k, v in exp["by_category"].items()},
            "count": exp["count"],
            "has_any": exp["count"] > 0,
        },
        "through_friday": last_full_friday.isoformat(),
        "last_full_week_total": float(_cents(last_full_total)),
        "labor_cost_per_hr": (float(cost_per_hr) if cost_per_hr is not None else None),
        "materials_share_pct": (float(mat_share) if mat_share is not None else None),
        "weeks": weeks,
        "unrated": ({
            "hours": float(lab["unrated"]["hours"]),
            "workers": lab["unrated"]["workers"],
            "earliest": lab["unrated"]["earliest"],
        } if lab["unrated"] else None),
    }


def _candidate_projects(conn) -> list:
    """Active projects that have any sign-ins or expenses — the selector list."""
    rows = conn.execute(
        "SELECT p.project_code, p.name FROM projects p "
        "WHERE COALESCE(p.status,'active')='active' ORDER BY p.project_code").fetchall()
    out = []
    for p in rows:
        n_sign = conn.execute("SELECT COUNT(*) FROM sign_in_log WHERE project_code=?",
                              (p["project_code"],)).fetchone()[0]
        n_exp = conn.execute("SELECT COUNT(*) FROM project_expense WHERE project_code=? "
                             "AND voided_at IS NULL", (p["project_code"],)).fetchone()[0]
        if n_sign or n_exp:
            out.append({"project_code": p["project_code"], "name": p["name"]})
    return out


# ===================== endpoints (admin/c_suite ONLY — comp data) =====================

@requires_role(*_COST_ROLES)
def _api_widget():
    """GET /api/costs/widget[?project=CODE] — the selector list + one project's
    payload (default: highest spend). 403 for every other role — the widget is
    HIDDEN, its keys OMITTED, never zeroed."""
    conn = _db()
    try:
        cands = _candidate_projects(conn)
        if not cands:
            return jsonify({"data": {"projects": [], "selected": None}})
        want = (request.args.get("project") or "").strip() or None
        payloads = {c["project_code"]: widget_payload(conn, c["project_code"]) for c in cands}
        for c in cands:
            c["total"] = payloads[c["project_code"]]["total"]
        cands.sort(key=lambda c: -c["total"])
        sel = want if want in payloads else cands[0]["project_code"]
        return jsonify({"data": {"projects": cands, "selected": payloads[sel]}})
    finally:
        conn.close()


@requires_role(*_COST_ROLES)
def _api_expenses_list(project_code):
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            "SELECT id, project_code, expense_date, vendor, category, amount, note, "
            "voided_at, void_note, created_at FROM project_expense WHERE project_code=? "
            "ORDER BY expense_date DESC, id DESC", (project_code,)).fetchall()]
        for r in rows:
            r["voided"] = bool(r["voided_at"])
            r["amount"] = float(_cents(_D(r["amount"])))
        return jsonify({"data": rows})
    finally:
        conn.close()


@requires_role(*_COST_ROLES)
def _api_expense_create(project_code):
    d = request.get_json(silent=True) or {}
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM projects WHERE project_code=?",
                            (project_code,)).fetchone():
            return jsonify({"error": "project not found"}), 404
        ed = (d.get("expense_date") or "").strip()
        try:
            datetime.strptime(ed, "%Y-%m-%d")
        except (ValueError, TypeError):
            return jsonify({"error": "expense_date must be YYYY-MM-DD"}), 400
        cat = (d.get("category") or "").strip().lower()
        if cat not in CATEGORIES:
            return jsonify({"error": f"category must be one of {'/'.join(CATEGORIES)}"}), 400
        try:
            amt = _cents(_D(d.get("amount")))
        except Exception:
            return jsonify({"error": "amount must be a number"}), 400
        if amt <= 0:
            return jsonify({"error": "amount must be > 0"}), 400
        conn.execute(
            "INSERT INTO project_expense (project_code, expense_date, vendor, category, "
            "amount, note, entered_by_uid, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (project_code, ed, (d.get("vendor") or "").strip() or None, cat, float(amt),
             (d.get("note") or "").strip() or None, _uid(), _now()))
        conn.commit()
        # #292 — expenses live-compute above the cached labor engine today; the
        # bump is defense-in-depth for any future whole-widget caching.
        import ssc_memo
        ssc_memo.bump('labor_cost', project_code)
        rid = conn.execute("SELECT MAX(id) AS m FROM project_expense").fetchone()["m"]
        return jsonify({"data": {"id": rid, "amount": float(amt), "category": cat}}), 201
    finally:
        conn.close()


@requires_role(*_COST_ROLES)
def _api_expense_void(expense_id):
    """POST — void-not-delete. The row stays (flagged, excluded from sums); the
    void stamps who/when + a required audit note."""
    d = request.get_json(silent=True) or {}
    conn = _db()
    try:
        r = conn.execute("SELECT id, voided_at, project_code FROM project_expense WHERE id=?",
                         (expense_id,)).fetchone()
        if not r:
            return jsonify({"error": "not found"}), 404
        if r["voided_at"]:
            return jsonify({"error": "already voided"}), 409
        note = (d.get("note") or "").strip()
        if not note:
            return jsonify({"error": "a void needs an audit note (why)"}), 400
        conn.execute(
            "UPDATE project_expense SET voided_at=?, voided_by_uid=?, void_note=? WHERE id=?",
            (_now(), _uid(), note, expense_id))
        conn.commit()
        import ssc_memo
        ssc_memo.bump('labor_cost', r["project_code"])   # #292 — see create
        return jsonify({"data": {"id": expense_id, "voided": True}})
    finally:
        conn.close()


def register(app) -> None:
    """Wire the C-Suite cost surfaces (all admin/c_suite — comp-data governance)."""
    app.add_url_rule("/api/costs/widget", "costs_widget", _api_widget, methods=["GET"])
    app.add_url_rule("/api/costs/<project_code>/expenses", "costs_exp_list",
                     _api_expenses_list, methods=["GET"])
    app.add_url_rule("/api/costs/<project_code>/expenses", "costs_exp_create",
                     _api_expense_create, methods=["POST"])
    app.add_url_rule("/api/costs/expenses/<int:expense_id>/void", "costs_exp_void",
                     _api_expense_void, methods=["POST"])
