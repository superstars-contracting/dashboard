"""Render a weekly payroll timesheet to self-contained HTML.

Pairs with pdf_export.py for the headless-Edge printable export. Layout:
  - SSC letterhead
  - Week range
  - Worker x day grid with totals
  - Generated-on timestamp

Self-contained: inline CSS, no external assets, no fonts.googleapis. The
@page CSS targets Letter portrait with sensible margins; the @media print
block keeps it print-ready.
"""
from datetime import datetime

BRAND_RED = "#B11E2E"
CREAM = "#FAF7F1"


def _esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _fmt_date_long(iso):
    """'2026-05-11' -> 'Mon May 11'"""
    d = datetime.strptime(iso, "%Y-%m-%d").date()
    return d.strftime("%a %b %d")


def _fmt_hours(h):
    if h is None or h == 0:
        return ""
    return f"{h:.2f}"


def render_timesheet_html(grid, generated_at=None):
    """Render the grid dict (output of payroll_hours.build_week_grid)
    to a printable HTML string."""
    generated_at = generated_at or datetime.now().isoformat(timespec="seconds")
    week_start_long = _fmt_date_long(grid["week_start"])
    week_end_long = _fmt_date_long(grid["week_end"])

    day_headers = "".join(
        f'<th class="day-col"><div class="dow">{_esc(_fmt_date_long(d).split()[0])}</div>'
        f'<div class="dom">{_esc(_fmt_date_long(d).split(maxsplit=1)[1])}</div></th>'
        for d in grid["dates"]
    )

    body_rows = []
    for w in grid["workers"]:
        cells = []
        for day in w["days"]:
            if day["has_entry"]:
                hours_str = _fmt_hours(day["hours"])
                times = f'{_esc(day["time_in"] or "")}–{_esc(day["time_out"] or "")}'
                multi = ' <span class="multi-tag">×' + str(day.get("row_count", 1)) + '</span>' \
                        if day.get("row_count", 1) > 1 else ''
                cells.append(
                    f'<td class="day-cell"><div class="hours">{hours_str}</div>'
                    f'<div class="times">{times}{multi}</div></td>'
                )
            else:
                cells.append('<td class="day-cell blank">—</td>')
        body_rows.append(
            f"<tr>"
            f'<td class="emp-id">{_esc(w.get("worker_id") or w["employee_id"])}</td>'
            f'<td class="emp-name">{_esc(w["name"])}</td>'
            f'<td class="emp-trade">{_esc(w["trade"] or "")}</td>'
            + "".join(cells)
            + f'<td class="weekly-total">{_fmt_hours(w["weekly_total"])}</td>'
            + "</tr>"
        )

    totals_cells = "".join(
        f'<td class="day-total">{_fmt_hours(t)}</td>' for t in grid["totals_by_day"]
    )

    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Weekly Hours — {_esc(grid["week_start"])} to {_esc(grid["week_end"])}</title>
  <style>
    @page {{ size: Letter landscape; margin: 0.5in 0.4in; }}
    :root {{ color-scheme: light; }}
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{ font-family: 'DM Sans', -apple-system, sans-serif; background: {CREAM}; padding: 24px 28px; color: #14161C; }}
    @media print {{ body {{ background: white; padding: 0; }} .content {{ box-shadow: none; padding: 16px; }} }}
    .header {{ background: #1a1a1a; color: {CREAM}; padding: 14px 28px; text-align: center; font-size: 22px; font-weight: bold; margin-bottom: 18px; }}
    .header-star {{ color: {BRAND_RED}; }}
    .content {{ background: white; padding: 22px 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }}
    .section-header {{ font-size: 14px; font-weight: bold; color: {BRAND_RED}; margin-bottom: 8px; border-bottom: 2px solid {BRAND_RED}; padding-bottom: 5px; text-transform: uppercase; letter-spacing: 0.06em; }}
    .week-range {{ font-size: 18px; font-weight: 600; margin: 12px 0 14px 0; color: #14161C; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
    th {{ background: {BRAND_RED}; color: white; padding: 6px 5px; font-weight: 600; border: 1px solid {BRAND_RED}; }}
    th.day-col {{ text-align: center; }}
    .dow {{ font-size: 10px; font-weight: 600; text-transform: uppercase; opacity: 0.85; }}
    .dom {{ font-size: 11px; }}
    td {{ border: 1px solid #ddd; padding: 5px 6px; vertical-align: middle; }}
    .emp-id {{ font-family: 'Courier New', monospace; font-size: 10px; color: #555; }}
    .emp-name {{ font-weight: 600; }}
    .emp-trade {{ color: #76777E; font-size: 10px; }}
    .day-cell {{ text-align: center; min-width: 70px; }}
    .day-cell.blank {{ color: #c4c4c4; }}
    .hours {{ font-weight: 700; font-size: 12px; }}
    .times {{ font-size: 9px; color: #76777E; margin-top: 2px; }}
    .multi-tag {{ background: #eee; padding: 0 4px; border-radius: 3px; font-size: 8px; }}
    .weekly-total {{ text-align: center; font-weight: 700; background: #fef5f6; font-size: 12px; }}
    tr.totals td {{ font-weight: 700; background: #f1eee8; }}
    .day-total {{ text-align: center; }}
    .grand-total {{ background: {BRAND_RED}; color: white; text-align: center; }}
    .footer {{ margin-top: 16px; font-size: 10px; color: #76777E; text-align: right; }}
  </style>
</head>
<body>
  <div class="header"><span class="header-star">★</span> Superstars Contracting Inc.</div>
  <div class="content">
    <div class="section-header">Weekly Hours Log — Payroll</div>
    <div class="week-range">{_esc(week_start_long)} – {_esc(week_end_long)}, {_esc(grid["week_start"][:4])}</div>
    <table>
      <thead>
        <tr><th>Worker ID</th><th>Name</th><th>Trade</th>{day_headers}<th>Weekly Total</th></tr>
      </thead>
      <tbody>
        {"".join(body_rows)}
        <tr class="totals">
          <td colspan="3" style="text-align:right;">DAILY TOTALS</td>
          {totals_cells}
          <td class="grand-total">{_fmt_hours(grid["grand_total"])}</td>
        </tr>
      </tbody>
    </table>
    <div class="footer">Generated {_esc(generated_at)} · Hours = max(0, (time_out − time_in) − 30 min lunch)</div>
  </div>
</body>
</html>"""
