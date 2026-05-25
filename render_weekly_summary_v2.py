"""Weekly Summary Report — live HTML renderer (Phase 4).

Per construction_builds_spec.json `weekly_summary_report`: this is an
AGGREGATION over the week's daily reports — NOT an independent data
entry. Every section is a roll-up (sum / latest / list / narrative /
max impact) of the live DB at render time, plus live RFI counts and a
reference to the Look-Ahead.

audience='owner' renders the high-level / progress-focused cut;
audience='internal' renders the full granular section set.

Location-grouped roll-up (per the spec's "by location_reference and
scope_category") stays partial until the DCR carries
location_reference (#122, deferred). For now the renderer surfaces
everything chronologically with the count rollups the spec asks for;
when DCR rows pick up location_unit / location_id, the grouping is a
one-line GROUP BY change.
"""
from __future__ import annotations
import html as _html
import sqlite3
from datetime import date, datetime, timedelta
from typing import Iterable

from typography import get_inlined_style_tag


def _esc(v) -> str:
    if v is None:
        return ""
    return _html.escape(str(v), quote=True)


def _fmt_mdy(iso: str) -> str:
    if not iso:
        return "—"
    try:
        d = datetime.strptime(str(iso)[:10], "%Y-%m-%d").date()
        return d.strftime("%m-%d-%Y")
    except (ValueError, TypeError):
        return str(iso)


WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _week_ending(week_ending_iso: str | None) -> date:
    """Resolve the week-ending Friday. If unset, use the most recent
    completed Mon-Fri week's Friday (mirrors payroll_hours.last_completed_week)."""
    if week_ending_iso:
        return date.fromisoformat(week_ending_iso)
    today = date.today()
    days_since_fri = (today.weekday() + 7 - 4) % 7
    if days_since_fri == 0:
        days_since_fri = 7  # today is Friday → use the prior week
    return today - timedelta(days=days_since_fri)


def _week_dates(friday: date) -> list[date]:
    """Mon..Sun for the week containing `friday` (a working-week Friday).
    7 days so weekend safety events / deliveries don't get dropped."""
    monday = friday - timedelta(days=4)
    return [monday + timedelta(days=i) for i in range(7)]


def _load_data(conn: sqlite3.Connection, project_code: str,
               week_dates: list[date]) -> dict:
    conn.row_factory = sqlite3.Row
    start_iso = week_dates[0].isoformat()
    end_iso = week_dates[-1].isoformat()

    project = dict(conn.execute(
        "SELECT * FROM projects WHERE project_code = ?", (project_code,)
    ).fetchone() or {})

    # DCRs issued in the week (gives a paper-trail count + display IDs)
    dcrs = [dict(r) for r in conn.execute(
        "SELECT DISTINCT dcr_sequence, report_date, status, MIN(created_at) AS created_at "
        "FROM report_index WHERE project_code = ? AND report_type = 'DCR' "
        "AND report_date BETWEEN ? AND ? "
        "GROUP BY dcr_sequence, report_date, status "
        "ORDER BY report_date",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # Sign-ins → headcount + hours per day. compute_worked_hours is
    # the canonical calc; replicate the same shape payroll_hours uses.
    from payroll_hours import compute_worked_hours
    sign_rows = conn.execute(
        "SELECT date, employee_id, time_in, time_out FROM sign_in_log "
        "WHERE project_code = ? AND date BETWEEN ? AND ?",
        (project_code, start_iso, end_iso),
    ).fetchall()
    per_day: dict[str, dict] = {d.isoformat(): {"headcount": 0, "hours": 0.0, "workers": set()} for d in week_dates}
    for r in sign_rows:
        day_iso = r["date"]
        if day_iso not in per_day:
            continue
        cell = per_day[day_iso]
        cell["workers"].add(r["employee_id"])
        cell["headcount"] = len(cell["workers"])
        cell["hours"] += compute_worked_hours(r["time_in"], r["time_out"])

    # work_log
    work = [dict(r) for r in conn.execute(
        "SELECT date, trade_area, location_elevation, description, scope_of_work "
        "FROM work_log WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # equipment
    equipment = [dict(r) for r in conn.execute(
        "SELECT date, equipment_type, owner, hours_used, issues, status "
        "FROM equipment_log WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # safety_events + toolbox
    safety = [dict(r) for r in conn.execute(
        "SELECT date, event_type, severity, person, description "
        "FROM safety_events WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]
    toolbox = [dict(r) for r in conn.execute(
        "SELECT date, talk_id, facilitator, attendees, duration_minutes "
        "FROM toolbox_talk_records WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # inspections
    inspections = [dict(r) for r in conn.execute(
        "SELECT date, type, agency, inspector_name AS inspector, result, scope, notes "
        "FROM inspections WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # issues — schema uses `category` (not severity) + `time_lost_hrs` + `action`
    issues = [dict(r) for r in conn.execute(
        "SELECT date, due_date, description, status, owner, category, "
        "       time_lost_hrs, action "
        "FROM issues WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # weather — schema uses am/pm temp + am/pm conditions + wind
    weather = [dict(r) for r in conn.execute(
        "SELECT date, am_conditions, pm_conditions, am_temp_f, pm_temp_f, "
        "       conditions, wind "
        "FROM weather_log WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # deliveries
    deliveries = [dict(r) for r in conn.execute(
        "SELECT date, material, qty, unit, supplier, notes "
        "FROM deliveries WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # visitors — schema uses `name` (not visitor_name)
    visitors = [dict(r) for r in conn.execute(
        "SELECT date, name AS visitor_name, company, purpose, time_in, time_out "
        "FROM visitors WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    # photos count + sample
    photo_count = conn.execute(
        "SELECT COUNT(*) FROM photos WHERE project_code = ? AND date BETWEEN ? AND ?",
        (project_code, start_iso, end_iso),
    ).fetchone()[0]

    # ---- LIVE RFI counts — linkage_rules.rfi_to_reports --------------
    # Open / Overdue derivation matches the Phase-2 logic: status not in
    # ('Closed','Void') AND no date_response_received. Overdue = past
    # date_response_required, Open otherwise.
    today_iso = date.today().isoformat()
    rfi_rows = conn.execute(
        "SELECT rfi_number, subject_title, sent_to, date_submitted, "
        "       date_response_required, date_response_received, status, "
        "       location_id, schedule_impact_flag, cost_impact_flag "
        "FROM rfi_log WHERE project_code = ?",
        (project_code,)
    ).fetchall()
    rfi_open: list[dict] = []
    rfi_overdue: list[dict] = []
    rfi_schedule_impact: list[dict] = []
    rfi_cost_impact: list[dict] = []
    for r in rfi_rows:
        status_raw = (r["status"] or "").strip()
        received = r["date_response_received"]
        if status_raw in ("Closed", "Void"):
            continue
        if received:
            continue
        due = r["date_response_required"]
        d = dict(r)
        if due and due < today_iso:
            d["status_derived"] = "Overdue"
            rfi_overdue.append(d)
        else:
            d["status_derived"] = "Open"
            rfi_open.append(d)
        if r["schedule_impact_flag"]:
            rfi_schedule_impact.append(d)
        if r["cost_impact_flag"]:
            rfi_cost_impact.append(d)

    return {
        "project": project,
        "dcrs": dcrs,
        "per_day": per_day,
        "work": work,
        "equipment": equipment,
        "safety": safety,
        "toolbox": toolbox,
        "inspections": inspections,
        "issues": issues,
        "weather": weather,
        "deliveries": deliveries,
        "visitors": visitors,
        "photo_count": photo_count,
        "rfi_open": rfi_open,
        "rfi_overdue": rfi_overdue,
        "rfi_schedule_impact": rfi_schedule_impact,
        "rfi_cost_impact": rfi_cost_impact,
    }


def _section(num: int, title: str, body_html: str, note: str = "") -> str:
    note_html = f'<div class="sec-note">{_esc(note)}</div>' if note else ""
    return (f'<section class="sec"><h2><span class="n">{num}</span>{_esc(title)}</h2>'
            f'{note_html}<div class="sec-body">{body_html}</div></section>')


def _empty(msg: str) -> str:
    return f'<p class="empty">{_esc(msg)}</p>'


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return _empty("None recorded this week.")
    head = "".join(f"<th>{_esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
        for row in rows
    )
    return f'<table class="ltable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


def _progress_summary(data: dict, week_dates: list[date]) -> str:
    """Section 2 — Progress Summary. Concatenated narratives from work_log
    grouped by date (per spec). The spec asks for grouping by
    location_reference + scope_category too — partial until DCR
    location_reference (#122)."""
    if not data["work"]:
        return _empty("No work_log entries this week — nothing to roll up.")
    by_day: dict[str, list[dict]] = {}
    for w in data["work"]:
        by_day.setdefault(w["date"], []).append(w)
    out = []
    for dstr in sorted(by_day):
        items = by_day[dstr]
        bullets = "".join(
            f"<li><b>{_esc(w.get('trade_area') or '—')}</b> · {_esc(w.get('location_elevation') or '—')} — "
            f"{_esc(w.get('description') or w.get('scope_of_work') or '')}</li>"
            for w in items
        )
        out.append(f"<div class='day-block'><div class='day-block-h'>{_esc(_fmt_mdy(dstr))} "
                   f"<span class='muted'>· {len(items)} entries</span></div>"
                   f"<ul class='day-block-list'>{bullets}</ul></div>")
    return "".join(out)


def _manpower(data: dict, week_dates: list[date]) -> str:
    """Section 4 — Manpower & Equipment. Headcount per day + equipment list."""
    pd = data["per_day"]
    days_html = []
    for d in week_dates:
        key = d.isoformat()
        cell = pd.get(key, {"headcount": 0, "hours": 0.0})
        days_html.append(
            f'<td class="num"><b>{cell["headcount"]}</b>'
            f'<div class="muted small">{cell["hours"]:.1f}h</div></td>'
        )
    headers = "".join(f"<th>{_esc(WEEKDAYS_SHORT[d.weekday()])}<br>{d.strftime('%m-%d')}</th>" for d in week_dates)
    grid = (
        '<table class="ltable"><thead><tr><th>Day</th>' + headers + '</tr></thead>'
        '<tbody><tr><td><b>Headcount</b><div class="muted small">hours</div></td>'
        + "".join(days_html) + '</tr></tbody></table>'
    )
    equip_rows = [
        [_esc(_fmt_mdy(e["date"])), _esc(e.get("equipment_type") or "—"),
         _esc(e.get("owner") or "—"), _esc(e.get("hours_used") or "—"),
         _esc(e.get("status") or "—")]
        for e in data["equipment"]
    ]
    equip_table = _table(["Date", "Item delivered", "Delivered by", "Qty/Hrs", "Status"], equip_rows)
    return grid + '<h3 class="sub-h">Equipment Delivered to Site</h3>' + equip_table


def _safety(data: dict) -> str:
    events = data["safety"]
    talks = data["toolbox"]
    summary = (
        f'<p><b>{len(events)}</b> safety event(s) · '
        f'<b>{len(talks)}</b> toolbox talk(s)'
        + (' · <b class="ok">Zero-incident week.</b>' if not events else '')
        + '</p>'
    )
    ev_rows = [
        [_esc(_fmt_mdy(e["date"])), _esc(e.get("event_type") or "—"),
         _esc(e.get("severity") or "—"), _esc(e.get("person") or "—"),
         _esc(e.get("description") or "")]
        for e in events
    ]
    tb_rows = [
        [_esc(_fmt_mdy(t["date"])), _esc(t.get("talk_id") or "—"),
         _esc(t.get("facilitator") or "—"), _esc(t.get("duration_minutes") or "—")]
        for t in talks
    ]
    return (summary
            + '<h3 class="sub-h">Events</h3>'
            + _table(["Date", "Type", "Severity", "Person", "Description"], ev_rows)
            + '<h3 class="sub-h">Toolbox Talks</h3>'
            + _table(["Date", "Talk", "Facilitator", "Duration (min)"], tb_rows))


def _quality(data: dict) -> str:
    rows = [
        [_esc(_fmt_mdy(i["date"])), _esc(i.get("type") or "—"),
         _esc(i.get("agency") or "—"), _esc(i.get("inspector") or "—"),
         _esc(i.get("result") or "—"), _esc(i.get("notes") or "")]
        for i in data["inspections"]
    ]
    return _table(["Date", "Type", "Agency", "Inspector", "Result", "Notes"], rows)


def _issues_section(data: dict) -> str:
    rows = [
        [_esc(_fmt_mdy(i["date"])), _esc(i.get("description") or "—"),
         _esc(i.get("category") or "—"), _esc(i.get("status") or "—"),
         _esc(i.get("owner") or "—"), _esc(_fmt_mdy(i.get("due_date")))]
        for i in data["issues"]
    ]
    issues_table = _table(
        ["Date", "Description", "Category", "Status", "Owner", "Due"], rows
    )
    # rfi_to_reports linkage: pull open / overdue RFIs into this section too.
    open_count = len(data["rfi_open"])
    over_count = len(data["rfi_overdue"])
    rfi_summary = (
        f'<p style="margin-top:8px;"><b>Live RFI snapshot:</b> '
        f'<b>{open_count}</b> open · <b class="{"bad" if over_count else "muted"}">'
        f'{over_count} overdue</b> · <b>{len(data["rfi_schedule_impact"])}</b> with schedule impact · '
        f'<b>{len(data["rfi_cost_impact"])}</b> with cost impact</p>'
    )
    return issues_table + rfi_summary


def _weather_section(data: dict) -> str:
    rows = []
    for w in data["weather"]:
        conds = (w.get("am_conditions") or "") + (
            (" / " + w.get("pm_conditions")) if w.get("pm_conditions") else ""
        )
        if not conds:
            conds = w.get("conditions") or "—"
        rows.append([
            _esc(_fmt_mdy(w["date"])),
            _esc(conds),
            f'{w.get("am_temp_f") if w.get("am_temp_f") is not None else "—"} / '
            f'{w.get("pm_temp_f") if w.get("pm_temp_f") is not None else "—"}',
            _esc(w.get("wind") or "—"),
        ])
    return _table(["Date", "Conditions (AM / PM)", "AM/PM °F", "Wind"], rows)


def _materials_section(data: dict) -> str:
    rows = [
        [_esc(_fmt_mdy(d["date"])), _esc(d.get("material") or "—"),
         _esc(f"{d['qty']} {d.get('unit') or ''}".strip() if d.get('qty') is not None else "—"),
         _esc(d.get("supplier") or "—"), _esc(d.get("notes") or "")]
        for d in data["deliveries"]
    ]
    return _table(["Date", "Material", "Qty", "Supplier", "Notes"], rows)


def _rfi_section(data: dict) -> str:
    """Section 10 — Change Orders & RFIs. Live from rfi_log per
    linkage_rules.rfi_to_reports."""
    overdue_rows = [
        [_esc(r["rfi_number"]), _esc(r["subject_title"]), _esc(r["sent_to"] or "—"),
         _esc(_fmt_mdy(r["date_response_required"])), _esc(r.get("location_id") or "—"),
         '<span class="status-pill status-overdue">OVERDUE</span>']
        for r in data["rfi_overdue"]
    ]
    open_rows = [
        [_esc(r["rfi_number"]), _esc(r["subject_title"]), _esc(r["sent_to"] or "—"),
         _esc(_fmt_mdy(r["date_response_required"])), _esc(r.get("location_id") or "—"),
         '<span class="status-pill status-open">OPEN</span>']
        for r in data["rfi_open"]
    ]
    summary_table = (
        '<table class="ltable"><thead><tr>'
        '<th>Bucket</th><th class="num">Count</th>'
        '</tr></thead><tbody>'
        f'<tr><td>Open</td><td class="num"><b>{len(data["rfi_open"])}</b></td></tr>'
        f'<tr><td>Overdue</td><td class="num"><b class="{"bad" if data["rfi_overdue"] else ""}">{len(data["rfi_overdue"])}</b></td></tr>'
        f'<tr><td>Schedule-impact (open / overdue)</td><td class="num"><b>{len(data["rfi_schedule_impact"])}</b></td></tr>'
        f'<tr><td>Cost-impact (open / overdue)</td><td class="num"><b>{len(data["rfi_cost_impact"])}</b></td></tr>'
        '</tbody></table>'
    )
    detail = ""
    if overdue_rows or open_rows:
        detail = (
            '<h3 class="sub-h">Current Open / Overdue RFIs</h3>'
            + _table(["RFI #", "Subject", "Sent to", "Needed by", "Location", "Status"],
                     overdue_rows + open_rows)
        )
    return summary_table + detail


def _photos_section(data: dict) -> str:
    n = data["photo_count"]
    if n == 0:
        return _empty("No photos attached this week.")
    return f'<p><b>{n}</b> photo(s) attached to DCRs this week. Per-photo grid in the daily PDFs.</p>'


def _actions(data: dict) -> str:
    """Section 13 — Action Items / Next Steps. Carry forward open issues +
    upcoming RFI deadlines as actions."""
    items = []
    for i in data["issues"]:
        if (i.get("status") or "").lower() not in ("closed", "resolved", "complete"):
            items.append([
                _esc(i.get("description") or "—"),
                _esc(i.get("owner") or "—"),
                _esc(_fmt_mdy(i.get("due_date"))),
                _esc(f"From {_fmt_mdy(i['date'])}"),
            ])
    for r in data["rfi_overdue"]:
        items.append([
            f"Resolve RFI {_esc(r['rfi_number'])} — {_esc(r['subject_title'])}",
            _esc(r["sent_to"] or "—"),
            _esc(_fmt_mdy(r["date_response_required"])),
            'OVERDUE',
        ])
    return _table(["Action", "Owner", "Due", "Source"], items)


def render_weekly_summary_html(conn: sqlite3.Connection, project_code: str,
                               week_ending_iso: str | None = None,
                               audience: str = "internal") -> str:
    """Render the live Weekly Summary for `project_code`.

    audience='owner'    — high-level: summary banner + progress + safety +
                          inspections + RFI/CO + actions. Drops the
                          per-day operational tables and the cost-notes
                          stub.
    audience='internal' — full 13-section set.
    """
    audience = audience if audience in ("internal", "owner") else "internal"
    friday = _week_ending(week_ending_iso)
    week_dates = _week_dates(friday)
    week_start = week_dates[0]
    data = _load_data(conn, project_code, week_dates)
    project = data["project"]
    project_name = project.get("name") or project_code
    project_addr = project.get("address") or ""
    generated = datetime.now().strftime("%m-%d-%Y %H:%M")

    # ---- Build sections (numbering per spec) -------------------------
    sections: list[str] = []

    sections.append(_section(1, "Project Identification",
        f'<div class="kv">'
        f'  <div><span class="k">Project</span><span class="v">{_esc(project_name)}</span></div>'
        f'  <div><span class="k">Project ID</span><span class="v">{_esc(project_code)}</span></div>'
        f'  <div><span class="k">Type</span><span class="v">{_esc(project.get("project_type") or "—")}</span></div>'
        f'  <div><span class="k">Address</span><span class="v">{_esc(project_addr)}</span></div>'
        f'  <div><span class="k">Week ending</span><span class="v">{_esc(_fmt_mdy(friday.isoformat()))}</span></div>'
        f'  <div><span class="k">Window</span><span class="v">{_esc(_fmt_mdy(week_start.isoformat()))} – {_esc(_fmt_mdy(friday.isoformat()))}</span></div>'
        f'  <div><span class="k">DCRs issued</span><span class="v">{len(data["dcrs"])}</span></div>'
        f'  <div><span class="k">Audience</span><span class="v">{_esc(audience)}</span></div>'
        f'</div>'))

    sections.append(_section(2, "Progress Summary",
        _progress_summary(data, week_dates),
        "Concatenated daily work_log narratives. Location-grouped roll-up partial until DCR carries location_reference (#122)."))

    sections.append(_section(3, "Schedule Status",
        f'<p>Reference the <b>Two-Week Look-Ahead</b> for upcoming activities + open constraints. '
        f'Live at <code>/api/projects/{_esc(project_code)}/lookahead/render</code>.</p>'
        f'<p class="muted">Master schedule comparison waits for the Primavera P6 import; the Look-Ahead grid is rendered with day-cell hooks ready for those dates.</p>'))

    if audience == "internal":
        sections.append(_section(4, "Manpower & Equipment", _manpower(data, week_dates)))

    sections.append(_section(5, "Safety", _safety(data)))
    sections.append(_section(6, "Quality & Inspections", _quality(data)))
    sections.append(_section(7, "Issues, Delays & Risks", _issues_section(data),
        "Live RFI snapshot pulled per linkage_rules.rfi_to_reports."))

    if audience == "internal":
        sections.append(_section(8, "Weather", _weather_section(data)))
        sections.append(_section(9, "Materials & Deliveries", _materials_section(data)))

    sections.append(_section(10, "Change Orders & RFIs", _rfi_section(data),
        "Live from rfi_log — open/overdue counts driven by status + date_response_required."))

    if audience == "internal":
        sections.append(_section(11, "Photos", _photos_section(data)))
        sections.append(_section(12, "Cost Notes",
            '<p class="muted">Optional per spec — surfaced from the company console Labor Rate Tracker once real rates land (deferred to auth/governance phase).</p>'))

    sections.append(_section(13, "Action Items / Next Steps", _actions(data)))

    fonts = get_inlined_style_tag()
    style = """
      :root {
        --red: #B11E2E; --red-dark: #8B1623;
        --ink: #14161C; --ink-soft: #4A4A4A;
        --cream: #FAF7F1; --line: #E8E4DD; --line-soft: #F1EEE8;
        --muted: #76777E; --green: #2F7C57; --amber: #B68838;
      }
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { background: #fff; color: var(--ink); font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; font-size: 12px; line-height: 1.45; padding: 18px 24px; }
      .hdr { display: flex; justify-content: space-between; align-items: flex-end; padding-bottom: 10px; border-bottom: 3px solid var(--red); margin-bottom: 16px; }
      .hdr h1 { font-family: 'Archivo', -apple-system, sans-serif; font-size: 22px; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase; }
      .hdr .sub { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }
      .hdr .meta { text-align: right; font-size: 11px; color: var(--ink-soft); }
      .hdr .meta .doctype { font-weight: 700; color: var(--red); text-transform: uppercase; letter-spacing: 1px; font-size: 10px; }
      .audience-pill { display: inline-block; padding: 2px 10px; border-radius: 99px; font-size: 9px; font-weight: 800; letter-spacing: 1px; text-transform: uppercase; background: var(--ink); color: white; }
      .sec { margin-bottom: 14px; page-break-inside: avoid; }
      .sec h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--red); border-bottom: 2px solid var(--red); padding-bottom: 4px; margin-bottom: 8px; display: flex; align-items: center; gap: 8px; }
      .sec h2 .n { display: inline-block; background: var(--red); color: white; font-size: 10px; padding: 2px 7px; border-radius: 3px; font-weight: 800; }
      .sec-note { font-size: 10px; color: var(--muted); margin-bottom: 6px; font-style: italic; }
      .sub-h { font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--ink-soft); margin: 10px 0 4px; font-weight: 700; }
      .ltable { width: 100%; border-collapse: collapse; font-size: 11px; }
      .ltable th { background: var(--cream); text-align: left; padding: 6px 8px; border-bottom: 2px solid var(--red); font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--ink-soft); font-weight: 700; }
      .ltable td { padding: 5px 8px; border-bottom: 1px solid var(--line-soft); vertical-align: top; }
      .ltable td.num, .ltable th.num { text-align: right; font-variant-numeric: tabular-nums; }
      .empty { color: var(--muted); font-style: italic; padding: 8px 4px; font-size: 11px; }
      .kv { display: grid; grid-template-columns: 1fr 1fr; gap: 6px 16px; }
      .kv > div { display: flex; justify-content: space-between; padding: 4px 6px; border-bottom: 1px dotted var(--line); }
      .kv .k { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; font-weight: 700; align-self: center; }
      .kv .v { font-weight: 600; }
      .day-block { padding: 8px 10px; background: var(--line-soft); border-left: 3px solid var(--red); margin-bottom: 6px; border-radius: 0 4px 4px 0; }
      .day-block-h { font-size: 11px; font-weight: 700; color: var(--red); margin-bottom: 4px; }
      .day-block-list { list-style: none; padding-left: 0; }
      .day-block-list li { font-size: 11px; padding: 2px 0; }
      .muted { color: var(--muted); font-weight: 400; }
      .small { font-size: 9px; }
      .bad  { color: var(--red); }
      .ok   { color: var(--green); }
      .status-pill { display: inline-block; padding: 1px 7px; border-radius: 99px; font-size: 9px; font-weight: 700; letter-spacing: 0.5px; }
      .status-overdue { background: #F8D7D9; color: var(--red); }
      .status-open    { background: #FFE6D6; color: #8B4A1B; }
      .foot { margin-top: 18px; padding-top: 10px; border-top: 1px solid var(--line); font-size: 9px; color: var(--muted); text-align: center; }
      @media print { body { padding: 12px 14px; } .sec { page-break-inside: avoid; } }
    """

    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8">
<title>Weekly Summary — {_esc(project_code)} — week ending {_esc(friday.isoformat())}</title>
{fonts}
<style>{style}</style>
</head><body>
<div class="hdr">
  <div>
    <h1>{_esc(project_name)}</h1>
    <div class="sub">{_esc(project_addr)} · {_esc(project_code)}</div>
  </div>
  <div class="meta">
    <div class="doctype">Weekly Summary Report</div>
    <div>Week ending <b>{_esc(_fmt_mdy(friday.isoformat()))}</b> · {_esc(_fmt_mdy(week_start.isoformat()))} – {_esc(_fmt_mdy(friday.isoformat()))}</div>
    <div style="margin-top:3px;">Generated {_esc(generated)} · <span class="audience-pill">{_esc(audience)}</span></div>
  </div>
</div>
{''.join(sections)}
<div class="foot">
  Superstars Contracting Inc. · {_esc(project_code)} · Weekly Summary ({_esc(audience)}) · Generated {_esc(generated)}
</div>
</body></html>"""
