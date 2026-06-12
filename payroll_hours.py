"""Weekly hours-worked computation, source-of-truth = sign_in_log.

Single helper for hours WORKED (labor actually performed) used by both
the DCR labor section and the weekly Hours Log so the two views can
never drift apart. Lunch is ALWAYS subtracted — every day gets a
30-minute deduction regardless of shift length (per
HANDOFF_WEEKLY_HOURS_LOG).

Naming note (intentional): we say "worked," not "paid." Whether
those hours ultimately get paid is a downstream manual decision
(an early-leave for "personal" may be unpaid; "sent home — weather"
may be paid). The number is the same; the framing avoids implying
the system makes pay-or-not calls.

Forward note (task #64, NOT this commit): time_in / time_out are the
BILLABLE in/out times. When the live PIN model lands, attendance
timestamps will be added on a separate column so payroll keeps
reading from these billable fields without redefinition.
"""
from datetime import date, datetime, timedelta


DEFAULT_LUNCH_MINUTES = 30
STANDARD_TIME_IN = "07:00"
STANDARD_TIME_OUT = "15:30"


def last_completed_week(today=None):
    """Return (monday, friday) of the most recent Mon-Fri week that is
    fully past relative to `today`. If today is Friday or earlier in the
    same Mon-Fri week, returns the previous week. Payroll runs one week
    in arrears, so this is what the weekly view defaults to.

    Examples (today -> result):
      Wed May 20, 2026 -> (May 11, May 15)  # this week not yet done
      Fri May 22, 2026 -> (May 11, May 15)  # today is Friday — still this-week-in-progress
      Sat May 23, 2026 -> (May 18, May 22)
      Mon May 25, 2026 -> (May 18, May 22)
    """
    today = today or date.today()
    # weekday(): Mon=0, Tue=1, ..., Fri=4, Sat=5, Sun=6
    days_since_fri = (today.weekday() + 7 - 4) % 7
    if days_since_fri == 0:
        # today IS a Friday — the current Mon-Fri week is not yet "completed"
        days_since_fri = 7
    last_fri = today - timedelta(days=days_since_fri)
    last_mon = last_fri - timedelta(days=4)
    return last_mon, last_fri


def week_dates(monday):
    """Return the 5 weekday dates Mon..Fri starting from `monday`."""
    return [monday + timedelta(days=i) for i in range(5)]


def _parse_hhmm(s):
    """Parse 'HH:MM' (or 'HH:MM:SS') to (hour, minute). Returns None on bad input."""
    if not s:
        return None
    try:
        parts = str(s).split(':')
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return None


def compute_worked_hours(time_in, time_out, lunch_minutes=DEFAULT_LUNCH_MINUTES):
    """Return hours WORKED as a float rounded to 2 decimals.

    Formula:  max(0, (time_out - time_in) - lunch_minutes), in hours.

    "Worked" not "paid": this is labor actually performed. Whether the
    hours get paid is a separate, manual downstream decision (early-leave
    for "personal" might be unpaid; "sent home — weather" might be paid).
    The number is identical to the prior compute_paid_hours; only the
    framing changed so the system isn't implying pay-or-not policy.

    Reused by the weekly Hours grid AND the DCR aggregator so the two
    surfaces never disagree. Returns 0.0 if either time is missing or
    malformed — the caller decides whether to render that as blank or
    explicit zero.

    Overnight shifts (out < in) are NOT supported — return 0.0 for those.
    Facade work doesn't span midnight; if someone genuinely needs to
    log overnight, payroll catches it manually rather than letting the
    formula guess.
    """
    pin = _parse_hhmm(time_in)
    pout = _parse_hhmm(time_out)
    if pin is None or pout is None:
        return 0.0
    h_in, m_in = pin
    h_out, m_out = pout
    raw_minutes = (h_out * 60 + m_out) - (h_in * 60 + m_in)
    if raw_minutes <= 0:
        return 0.0
    paid_minutes = max(0, raw_minutes - lunch_minutes)
    return round(paid_minutes / 60.0, 2)


def build_week_grid(conn, monday):
    """Build the weekly hours grid for the given Monday.

    Returns dict:
      {
        "week_start": "YYYY-MM-DD" (monday),
        "week_end":   "YYYY-MM-DD" (friday),
        "dates":      ["YYYY-MM-DD"] * 5 (Mon..Fri),
        "workers": [
          {"employee_id": "E-00001", "name": "...", "trade": "...",
           "days": [{"date": "...", "sign_in_id": int|None,
                     "time_in": "HH:MM"|None, "time_out": "HH:MM"|None,
                     "hours": float, "project_code": "FR-BX-001"|None}, ...],
           "weekly_total": float}, ...
        ],
        "totals_by_day": [float, float, float, float, float],
        "grand_total": float,
      }

    Worker pool: employees with at least one ACTIVE project_assignment.
    Sums hours across all projects for a given (worker, date) — payroll
    doesn't care which project a worker was on, just the total.
    """
    dates = week_dates(monday)
    date_strs = [d.isoformat() for d in dates]

    workers = conn.execute(
        """SELECT DISTINCT e.employee_id, e.worker_id, e.name, e.trade
           FROM employees e
           JOIN project_assignments pa ON pa.employee_id = e.employee_id
           WHERE pa.status = 'active'
           ORDER BY CAST(SUBSTR(e.worker_id, 3) AS INTEGER)"""
    ).fetchall()

    # One query for the whole week — index on (date, project_code) covers this.
    placeholders = ",".join("?" * len(date_strs))
    rows = conn.execute(
        f"""SELECT id, employee_id, date, time_in, time_out, project_code
            FROM sign_in_log
            WHERE date IN ({placeholders})
            ORDER BY employee_id, date, id""",
        date_strs,
    ).fetchall()

    # Bucket by (employee_id, date) — multiple project rows on same day get summed.
    by_emp_day = {}
    for r in rows:
        key = (r["employee_id"], r["date"])
        by_emp_day.setdefault(key, []).append(r)

    grid_workers = []
    totals_by_day = [0.0] * 5
    grand_total = 0.0

    for w in workers:
        eid = w["employee_id"]
        days = []
        weekly_total = 0.0
        for i, dstr in enumerate(date_strs):
            day_rows = by_emp_day.get((eid, dstr), [])
            if not day_rows:
                day = {"date": dstr, "sign_in_id": None, "time_in": None,
                       "time_out": None, "hours": 0.0, "project_code": None,
                       "has_entry": False}
            else:
                # Sum hours across all projects for this (worker, date)
                day_hours = 0.0
                for r in day_rows:
                    day_hours += compute_worked_hours(r["time_in"], r["time_out"])
                # Primary row is the one most recently created (last id); show
                # its times in the cell. Operator edits this primary row.
                primary = day_rows[-1]
                day = {
                    "date": dstr,
                    "sign_in_id": primary["id"],
                    "time_in": primary["time_in"],
                    "time_out": primary["time_out"],
                    "hours": round(day_hours, 2),
                    "project_code": primary["project_code"],
                    "has_entry": True,
                    "row_count": len(day_rows),  # >1 means multi-project day
                }
                weekly_total += day_hours
                totals_by_day[i] += day_hours
            days.append(day)
        grid_workers.append({
            "employee_id": eid,
            "worker_id": w["worker_id"],
            "name": w["name"],
            "trade": w["trade"],
            "days": days,
            "weekly_total": round(weekly_total, 2),
        })
        grand_total += weekly_total

    # No-Work Day designation per date — surfaced so consumers (Labor
    # Rate Tracker, Weekly Summary) can render "NO WORK — REASON" in
    # that day's column instead of a blank zero. Pulled from
    # report_index.no_work; date keys match `dates` exactly.
    no_work_by_date: dict[str, dict] = {}
    placeholders2 = ",".join("?" * len(date_strs))
    for r in conn.execute(
        f"SELECT DISTINCT report_date, no_work_reason, no_work_note "
        f"FROM report_index "
        f"WHERE report_type='DCR' AND no_work=1 AND report_date IN ({placeholders2})",
        date_strs,
    ).fetchall():
        no_work_by_date[r["report_date"]] = {
            "reason": r["no_work_reason"],
            "note": r["no_work_note"],
        }

    return {
        "week_start": date_strs[0],
        "week_end": date_strs[-1],
        "dates": date_strs,
        "workers": grid_workers,
        "totals_by_day": [round(t, 2) for t in totals_by_day],
        "grand_total": round(grand_total, 2),
        "no_work_by_date": no_work_by_date,
    }
