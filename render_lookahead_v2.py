"""Two-Week Look-Ahead — live HTML renderer (Phase 3).

Reads from the live DB at render time (not from disk) and produces a
self-contained HTML report shaped per construction_builds_spec.json
'two_week_look_ahead': drop rows × day grid + activities from
drop_activities + constraints from /api/.../rfi-constraints +
deliveries + inspections.

Why a new module (not edits to the legacy render_lookahead_html.py):
the legacy renderer was designed for a workbook input from the prior
SC-2601 project; this one reads the canonical drop_plan / drop_activities
spine seeded for FR-BX-001 (and any future project) and renders without
a per-project rewrite.

P6 hook (deliberate, not implemented): drop_activities has no
planned_start_date / planned_finish_date yet — the day-grid cells for
the activity bars stay empty until a Primavera P6 import populates
those columns. The grid IS rendered (day headers, empty cells with
data-day attributes the JS hook can target later) so the operator
sees the framing now and bars layer in when dates arrive.
"""
from __future__ import annotations
import html as _html
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

from typography import get_inlined_style_tag

WEEKDAYS_SHORT = ["Mon", "Tue", "Wed", "Thu", "Fri"]


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


def _working_days_window(start: date, n_days: int) -> list[date]:
    """Return the first `n_days` working days (Mon-Fri) starting at or
    after `start`. n_days defaults to 10 (the 2-week window the spec
    describes). Weekends are skipped without touching the count.
    """
    out: list[date] = []
    cur = start
    # If start is a weekend, advance to next Monday
    while cur.weekday() >= 5:
        cur += timedelta(days=1)
    while len(out) < n_days:
        if cur.weekday() < 5:
            out.append(cur)
        cur += timedelta(days=1)
    return out


def _load_data(conn: sqlite3.Connection, project_code: str,
               window_dates: list[date]):
    """Pull every piece the renderer needs in a single helper. Returns a
    dict with: project, drops, activities_by_drop, constraints_by_loc,
    deliveries, inspections.
    """
    conn.row_factory = sqlite3.Row
    project = dict(conn.execute(
        "SELECT * FROM projects WHERE project_code = ?", (project_code,)
    ).fetchone() or {})

    drops = [dict(r) for r in conn.execute(
        "SELECT drop_id, elevation, status, scope_of_work, "
        "       estimated_duration_days, planned_start_date, planned_end_date, "
        "       actual_start_date, actual_end_date, sign_off_status, notes "
        "FROM drop_plan WHERE project_code = ? "
        "ORDER BY CAST(SUBSTR(drop_id, 4) AS INTEGER)",
        (project_code,)
    ).fetchall()]

    drop_ids = [d["drop_id"] for d in drops]
    activities_by_drop: dict[str, list[dict]] = {did: [] for did in drop_ids}
    if drop_ids:
        placeholders = ",".join("?" * len(drop_ids))
        for r in conn.execute(
            f"SELECT * FROM drop_activities WHERE drop_id IN ({placeholders}) "
            f"ORDER BY drop_id, step_number",
            drop_ids,
        ).fetchall():
            activities_by_drop.setdefault(r["drop_id"], []).append(dict(r))

    # Constraints feed = open / overdue RFIs flagged as schedule-impacting.
    # Mirrors /api/projects/<code>/rfi-constraints output (Phase 2).
    today_iso = date.today().isoformat()
    constraints_by_loc: dict[str, list[dict]] = {}
    raw = conn.execute(
        "SELECT rfi_number, subject_title, sent_to, date_submitted, "
        "       date_response_required, date_response_received, status, "
        "       location_unit, location_id, scope_category, "
        "       schedule_impact_flag, cost_impact_flag "
        "FROM rfi_log WHERE project_code = ? AND schedule_impact_flag = 1",
        (project_code,)
    ).fetchall()
    for r in raw:
        # Open / Overdue derivation — Phase 2 logic, summarized inline so
        # this module stays decoupled from server.py helpers.
        status_raw = (r["status"] or "").strip()
        received = r["date_response_received"]
        if status_raw == "Closed":
            continue
        if status_raw == "Void":
            continue
        if received:
            # Got a response → not currently a constraint.
            continue
        due = r["date_response_required"]
        derived = "Overdue" if due and due < today_iso else "Open"
        loc_id = r["location_id"]
        if not loc_id:
            continue
        constraints_by_loc.setdefault(loc_id, []).append({
            "rfi_number":             r["rfi_number"],
            "subject_title":          r["subject_title"],
            "sent_to":                r["sent_to"],
            "date_response_required": due,
            "status_derived":         derived,
        })

    # Deliveries + inspections in the window — gives the operator the
    # gating ones (terra cotta arriving Tue, FISP inspection Fri, etc.)
    start_iso = window_dates[0].isoformat()
    end_iso = window_dates[-1].isoformat()
    deliveries = [dict(r) for r in conn.execute(
        "SELECT date, supplier, material, qty, unit, notes "
        "FROM deliveries WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]
    inspections = [dict(r) for r in conn.execute(
        "SELECT date, agency, inspector_name AS inspector, type, result, notes "
        "FROM inspections WHERE project_code = ? AND date BETWEEN ? AND ? "
        "ORDER BY date, id",
        (project_code, start_iso, end_iso),
    ).fetchall()]

    return {
        "project": project,
        "drops": drops,
        "activities_by_drop": activities_by_drop,
        "constraints_by_loc": constraints_by_loc,
        "deliveries": deliveries,
        "inspections": inspections,
    }


def _section(title: str, body_html: str, note: str = "") -> str:
    note_html = f'<div class="sec-note">{_esc(note)}</div>' if note else ""
    return (f'<section class="sec"><h2>{_esc(title)}</h2>{note_html}'
            f'<div class="sec-body">{body_html}</div></section>')


def _day_header(d: date) -> str:
    return (f'<th class="day-col"><div class="day-dow">{WEEKDAYS_SHORT[d.weekday()]}</div>'
            f'<div class="day-num">{d.strftime("%m-%d")}</div></th>')


def _render_drop_row(drop: dict, activities: list[dict],
                     constraints: list[dict], window_dates: list[date]) -> str:
    # Activity summary for the location cell — show step status counts so the
    # operator sees where this drop sits in the 6-step cycle.
    done = sum(1 for a in activities if a.get("status") == "complete")
    in_prog = sum(1 for a in activities if a.get("status") == "in_progress")
    total = len(activities)
    progress = f"{done}/{total}" if total else "—"
    # Show the next pending step as the "current scope" hint.
    next_step = next((a for a in activities if a.get("status") == "pending"), None)
    next_label = "—"
    if next_step:
        gate = " (GATE)" if next_step.get("gate_after_step") else ""
        next_label = f'Step {next_step["step_number"]}: {next_step["activity"]}{gate}'

    # Day grid cells — empty until Primavera dates load. Each cell carries
    # data-day so a future JS hook can paint bars without touching the
    # server renderer.
    day_cells = "".join(
        f'<td class="day-cell" data-day="{d.isoformat()}"></td>'
        for d in window_dates
    )

    constraint_count = len(constraints)
    cflag = ""
    if constraint_count:
        overdue = sum(1 for c in constraints if c.get("status_derived") == "Overdue")
        cls = "constraint-bad" if overdue else "constraint-warn"
        cflag = f'<span class="constraint-pill {cls}">{constraint_count}</span>'

    elev_short = (drop.get("elevation") or "").split(" ")[0]
    return (
        f'<tr data-drop="{_esc(drop["drop_id"])}">'
        f'  <td class="loc-cell">'
        f'    <div class="loc-id">{_esc(drop["drop_id"])}</div>'
        f'    <div class="loc-elev">{_esc(elev_short)}</div>'
        f'  </td>'
        f'  <td class="scope-cell">{_esc(next_label)}</td>'
        f'  <td class="prog-cell">{_esc(progress)}</td>'
        f'  <td class="status-cell"><span class="status-pill status-{_esc(drop.get("status") or "pending")}">{_esc((drop.get("status") or "pending").upper())}</span></td>'
        f'  {day_cells}'
        f'  <td class="constraints-cell">{cflag or "—"}</td>'
        f'</tr>'
    )


def _render_constraints_table(constraints_by_loc: dict[str, list[dict]]) -> str:
    rows = []
    for loc_id in sorted(constraints_by_loc.keys()):
        for c in constraints_by_loc[loc_id]:
            badge_cls = "status-overdue" if c["status_derived"] == "Overdue" else "status-open"
            rows.append(
                f'<tr>'
                f'<td>{_esc(loc_id)}</td>'
                f'<td><span class="status-pill {badge_cls}">{_esc(c["status_derived"])}</span></td>'
                f'<td>{_esc(c["rfi_number"])}</td>'
                f'<td>{_esc(c["subject_title"])}</td>'
                f'<td>{_esc(c["sent_to"] or "—")}</td>'
                f'<td>{_esc(_fmt_mdy(c["date_response_required"]))}</td>'
                f'</tr>'
            )
    if not rows:
        return '<p class="empty">No open schedule-impact RFIs against any drop in this window.</p>'
    return (
        '<table class="ltable"><thead><tr>'
        '<th>Drop</th><th>Status</th><th>RFI #</th><th>Subject</th>'
        '<th>Sent to</th><th>Needed by</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
    )


def _render_deliveries_table(deliveries: list[dict]) -> str:
    if not deliveries:
        return '<p class="empty">No deliveries scheduled in this window.</p>'
    rows = []
    for d in deliveries:
        qty = d.get("qty")
        unit = d.get("unit") or ""
        qty_str = f"{qty} {unit}".strip() if qty is not None else "—"
        rows.append(
            f'<tr>'
            f'<td>{_esc(_fmt_mdy(d.get("date")))}</td>'
            f'<td>{_esc(d.get("material") or "—")}</td>'
            f'<td>{_esc(qty_str)}</td>'
            f'<td>{_esc(d.get("supplier") or "—")}</td>'
            f'<td>{_esc(d.get("notes") or "")}</td>'
            f'</tr>'
        )
    return (
        '<table class="ltable"><thead><tr>'
        '<th>Date</th><th>Material</th><th>Qty</th><th>Supplier</th><th>Notes</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
    )


def _render_inspections_table(inspections: list[dict]) -> str:
    if not inspections:
        return '<p class="empty">No inspections scheduled in this window.</p>'
    rows = []
    for i in inspections:
        rows.append(
            f'<tr>'
            f'<td>{_esc(_fmt_mdy(i.get("date")))}</td>'
            f'<td>{_esc(i.get("type") or "—")}</td>'
            f'<td>{_esc(i.get("agency") or "—")}</td>'
            f'<td>{_esc(i.get("inspector") or "—")}</td>'
            f'<td>{_esc(i.get("result") or "—")}</td>'
            f'<td>{_esc(i.get("notes") or "")}</td>'
            f'</tr>'
        )
    return (
        '<table class="ltable"><thead><tr>'
        '<th>Date</th><th>Type</th><th>Agency</th><th>Inspector</th><th>Result</th><th>Notes</th>'
        '</tr></thead><tbody>' + "".join(rows) + '</tbody></table>'
    )


def render_lookahead_html(conn: sqlite3.Connection, project_code: str,
                          start_iso: str | None = None,
                          working_days: int = 10) -> str:
    """Render the live Two-Week Look-Ahead for `project_code` starting on
    `start_iso` (LOCAL today if omitted) covering `working_days` working
    days (default 10 = the 2-week window the spec describes).
    """
    if start_iso:
        start = date.fromisoformat(start_iso)
    else:
        start = date.today()
    window = _working_days_window(start, working_days)
    data = _load_data(conn, project_code, window)
    project = data["project"]
    drops = data["drops"]
    project_name = project.get("name") or project_code
    project_addr = project.get("address") or ""
    generated = datetime.now().strftime("%m-%d-%Y %H:%M")

    # Build drop rows
    drop_rows = "".join(
        _render_drop_row(
            drop=d,
            activities=data["activities_by_drop"].get(d["drop_id"], []),
            constraints=data["constraints_by_loc"].get(d["drop_id"], []),
            window_dates=window,
        )
        for d in drops
    )
    day_headers = "".join(_day_header(d) for d in window)

    grid_table = (
        '<table class="grid">'
        '<thead><tr>'
        '<th class="loc-col">Location</th>'
        '<th class="scope-col">Next scope</th>'
        '<th class="prog-col">Steps</th>'
        '<th class="status-col">Status</th>'
        f'{day_headers}'
        '<th class="constraints-col">Cons</th>'
        '</tr></thead>'
        f'<tbody>{drop_rows}</tbody></table>'
    )

    constraints_html = _render_constraints_table(data["constraints_by_loc"])
    deliveries_html = _render_deliveries_table(data["deliveries"])
    inspections_html = _render_inspections_table(data["inspections"])

    # Counts banner
    constraint_total = sum(len(v) for v in data["constraints_by_loc"].values())
    overdue_total = sum(
        1 for v in data["constraints_by_loc"].values()
        for c in v if c.get("status_derived") == "Overdue"
    )

    fonts = get_inlined_style_tag()
    # --- CSS (inline, self-contained, print-clean) ---
    style = """
      :root {
        --red: #B11E2E; --red-dark: #8B1623;
        --ink: #14161C; --ink-soft: #4A4A4A;
        --cream: #FAF7F1; --line: #E8E4DD; --line-soft: #F1EEE8;
        --muted: #76777E; --green: #2F7C57; --amber: #B68838;
      }
      * { box-sizing: border-box; margin: 0; padding: 0; }
      body { background: #fff; color: var(--ink); font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; -webkit-font-smoothing: antialiased; font-size: 12px; line-height: 1.4; padding: 18px 24px; }
      .hdr { display: flex; justify-content: space-between; align-items: flex-end; padding-bottom: 10px; border-bottom: 3px solid var(--red); margin-bottom: 16px; }
      .hdr h1 { font-family: 'Archivo', -apple-system, sans-serif; font-size: 22px; font-weight: 800; letter-spacing: 0.5px; text-transform: uppercase; }
      .hdr .sub { font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; margin-top: 4px; }
      .hdr .meta { text-align: right; font-size: 11px; color: var(--ink-soft); }
      .hdr .meta .doctype { font-weight: 700; color: var(--red); text-transform: uppercase; letter-spacing: 1px; font-size: 10px; }
      .banner { display: flex; gap: 12px; padding: 10px 14px; background: var(--cream); border: 1px solid var(--line); border-radius: 4px; margin-bottom: 14px; font-size: 11px; }
      .banner .b-item { padding-right: 16px; border-right: 1px solid var(--line); }
      .banner .b-item:last-child { border-right: none; }
      .banner b { color: var(--red-dark); }
      .sec { margin-bottom: 18px; page-break-inside: avoid; }
      .sec h2 { font-size: 12px; text-transform: uppercase; letter-spacing: 0.8px; color: var(--red); border-bottom: 2px solid var(--red); padding-bottom: 4px; margin-bottom: 8px; }
      .sec-note { font-size: 10px; color: var(--muted); margin-bottom: 8px; font-style: italic; }
      .grid { width: 100%; border-collapse: collapse; font-size: 10.5px; }
      .grid th { background: var(--cream); text-align: left; padding: 6px 6px; border-bottom: 2px solid var(--red); font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--ink-soft); font-weight: 700; }
      .grid td { padding: 5px 6px; border-bottom: 1px solid var(--line-soft); vertical-align: middle; }
      .grid tbody tr:nth-child(even) { background: #fbfaf6; }
      .loc-cell .loc-id { font-weight: 700; color: var(--red); font-variant-numeric: tabular-nums; }
      .loc-cell .loc-elev { font-size: 9px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.5px; }
      .scope-cell { font-size: 10.5px; color: var(--ink-soft); }
      .prog-cell { text-align: center; font-variant-numeric: tabular-nums; font-weight: 600; }
      .day-col { text-align: center; min-width: 38px; }
      .day-dow { font-size: 8.5px; color: var(--muted); }
      .day-num { font-size: 10px; font-weight: 700; color: var(--ink); font-variant-numeric: tabular-nums; }
      .day-cell { text-align: center; background: var(--line-soft); border: 1px dashed transparent; min-width: 38px; height: 24px; }
      .status-pill { display: inline-block; padding: 1px 7px; border-radius: 99px; font-size: 8.5px; font-weight: 700; letter-spacing: 0.5px; }
      .status-pending { background: #EEEDE9; color: var(--ink-soft); }
      .status-in_progress { background: #FFF4D6; color: #7A5E1E; }
      .status-complete { background: #DDF0E5; color: var(--green); }
      .status-open { background: #FFE6D6; color: #8B4A1B; }
      .status-overdue { background: #F8D7D9; color: var(--red); }
      .constraints-cell { text-align: center; }
      .constraint-pill { display: inline-block; padding: 1px 7px; border-radius: 99px; font-size: 9px; font-weight: 700; color: white; }
      .constraint-warn { background: var(--amber); }
      .constraint-bad { background: var(--red); }
      .ltable { width: 100%; border-collapse: collapse; font-size: 11px; }
      .ltable th { background: var(--cream); text-align: left; padding: 6px 8px; border-bottom: 2px solid var(--red); font-size: 9px; text-transform: uppercase; letter-spacing: 0.5px; color: var(--ink-soft); font-weight: 700; }
      .ltable td { padding: 5px 8px; border-bottom: 1px solid var(--line-soft); }
      .empty { color: var(--muted); font-style: italic; padding: 8px 4px; font-size: 11px; }
      .foot { margin-top: 18px; padding-top: 10px; border-top: 1px solid var(--line); font-size: 9px; color: var(--muted); text-align: center; }
      .p6-note { background: #FFF4D6; border: 1px solid #E8C76A; border-left: 4px solid var(--amber); color: #7A5E1E; font-size: 10.5px; padding: 8px 12px; border-radius: 4px; margin-bottom: 14px; }
      @media print { body { padding: 12px 14px; } .sec { page-break-inside: avoid; } }
    """

    return f"""<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8">
<title>Two-Week Look-Ahead — {_esc(project_code)} — {_esc(window[0].isoformat())} to {_esc(window[-1].isoformat())}</title>
{fonts}
<style>{style}</style>
</head><body>
<div class="hdr">
  <div>
    <h1>{_esc(project_name)}</h1>
    <div class="sub">{_esc(project_addr)} · {_esc(project_code)}</div>
  </div>
  <div class="meta">
    <div class="doctype">Two-Week Look-Ahead</div>
    <div>Window: {_esc(_fmt_mdy(window[0].isoformat()))} – {_esc(_fmt_mdy(window[-1].isoformat()))} ({len(window)} working days)</div>
    <div>Generated {_esc(generated)}</div>
  </div>
</div>

<div class="banner">
  <div class="b-item"><b>{len(drops)}</b> drops in plan</div>
  <div class="b-item"><b>{constraint_total}</b> open constraints
    {f'<span style="color:var(--red);"> ({overdue_total} overdue)</span>' if overdue_total else ''}
  </div>
  <div class="b-item"><b>{len(data["deliveries"])}</b> deliveries in window</div>
  <div class="b-item"><b>{len(data["inspections"])}</b> inspections in window</div>
</div>

<div class="p6-note">
  <b>Day-grid bars pending Primavera P6 import.</b> Activities + status + RFI
  constraints are live from the database; per-day scope bars layer in once
  drop_activities carries planned_start / planned_finish dates from the
  master schedule. The grid framing + data-day cell hooks are in place so the
  paint step is a JS-only addition.
</div>

{_section("Drop Plan — 2-Week Window", grid_table, "Rows = drops in walking order (N → W → S → E). Each drop's next pending step + cycle progress (steps complete / total). Constraint count joins via location_id from the RFI Log.")}

{_section("Constraints (open schedule-impact RFIs)", constraints_html, "Per linkage_rules.rfi_to_lookahead: any open or overdue RFI with schedule_impact_flag = 1 surfaces here, tied to the drop in its location_id.")}

{_section("Deliveries scheduled in window", deliveries_html)}

{_section("Inspections scheduled in window", inspections_html)}

<div class="foot">
  Superstars Contracting Inc. · {_esc(project_code)} · Two-Week Look-Ahead · Generated {_esc(generated)}
</div>
</body></html>"""
