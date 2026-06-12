#!/usr/bin/env python3
"""DCR HTML Renderer — black/red/white SSC brand layout.

Design source: daily_report_mockup.html in the Documents/Claude/Projects
folder. Wired to the aggregator output (dcr_aggregator.aggregate_dcr).

Self-contained inline CSS — no external assets, no fonts.googleapis. The
headless-Edge PDF pipeline (pdf_export.render_html_to_pdf) renders this
HTML deterministically.

Print/PDF pagination contract:
  - On screen: one continuous flowing document, no visible page seams.
  - In print: @page Letter @ 0.4in margins; sections never split across a
    page (break-inside:avoid) and section titles never strand at the
    bottom of a page (break-after:avoid).
The SAME @media print rules govern browser Ctrl+P AND the headless-Edge
auto-PDF on finalize — they consume the same HTML.
"""
import argparse
import html as _html
import json
import sys
from datetime import datetime
from typing import Any, Dict, List
from typography import get_inlined_style_tag

# Placeholder star — inlined as a Python constant so the DCR HTML is fully
# self-contained (the PDF render doesn't depend on a file path). Swap this
# block when the official brand logo arrives.
# Source: Superstars Logo Kit/svg/superstars-star.svg.
SUPERSTARS_STAR_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1000" '
    'width="40" height="40" aria-label="Superstars Contracting" role="img">'
    '<polygon points="500.0,40.0 608.2,351.1 579.8,390.2 500.0,155.0" fill="#e23d3f"/>'
    '<polygon points="500.0,155.0 579.8,390.2 551.4,429.3 500.0,270.0" fill="#99151d"/>'
    '<polygon points="608.2,351.1 937.5,357.9 828.1,393.4 579.8,390.2" fill="#6d0d14"/>'
    '<polygon points="579.8,390.2 828.1,393.4 718.7,428.9 551.4,429.3" fill="#99151d"/>'
    '<polygon points="937.5,357.9 675.0,556.9 629.1,541.9 828.1,393.4" fill="#5d0b11"/>'
    '<polygon points="828.1,393.4 629.1,541.9 583.1,527.0 718.7,428.9" fill="#99151d"/>'
    '<polygon points="675.0,556.9 770.4,872.1 702.8,779.1 629.1,541.9" fill="#5d0b11"/>'
    '<polygon points="629.1,541.9 702.8,779.1 635.2,686.1 583.1,527.0" fill="#99151d"/>'
    '<polygon points="770.4,872.1 500.0,684.0 500.0,635.7 702.8,779.1" fill="#5d0b11"/>'
    '<polygon points="702.8,779.1 500.0,635.7 500.0,587.4 635.2,686.1" fill="#99151d"/>'
    '<polygon points="500.0,684.0 229.6,872.1 297.2,779.1 500.0,635.7" fill="#5d0b11"/>'
    '<polygon points="500.0,635.7 297.2,779.1 364.8,686.1 500.0,587.4" fill="#99151d"/>'
    '<polygon points="229.6,872.1 325.0,556.9 370.9,541.9 297.2,779.1" fill="#92131c"/>'
    '<polygon points="297.2,779.1 370.9,541.9 416.9,527.0 364.8,686.1" fill="#99151d"/>'
    '<polygon points="325.0,556.9 62.5,357.9 171.9,393.4 370.9,541.9" fill="#ed4b49"/>'
    '<polygon points="370.9,541.9 171.9,393.4 281.3,428.9 416.9,527.0" fill="#99151d"/>'
    '<polygon points="62.5,357.9 391.8,351.1 420.2,390.2 171.9,393.4" fill="#ee4c4a"/>'
    '<polygon points="171.9,393.4 420.2,390.2 448.6,429.3 281.3,428.9" fill="#99151d"/>'
    '<polygon points="391.8,351.1 500.0,40.0 500.0,155.0 420.2,390.2" fill="#ee4c4a"/>'
    '<polygon points="420.2,390.2 500.0,155.0 500.0,270.0 448.6,429.3" fill="#99151d"/>'
    '<polygon points="500.0,40.0 608.2,351.1 937.5,357.9 675.0,556.9 770.4,872.1 500.0,684.0 229.6,872.1 325.0,556.9 62.5,357.9 391.8,351.1" '
    'fill="none" stroke="#280408" stroke-width="4.1" stroke-linejoin="round"/>'
    '<polygon points="500.0,270.0 551.4,429.3 718.7,428.9 583.1,527.0 635.2,686.1 500.0,587.4 364.8,686.1 416.9,527.0 281.3,428.9 448.6,429.3" '
    'fill="none" stroke="#280408" stroke-width="4.1" stroke-linejoin="round"/>'
    '</svg>'
)

# Day-of-week + long form date helper. Aggregator already returns project.date
# and project.day_of_week separately; we use both for the header line.
WEEKDAYS_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June',
               'July', 'August', 'September', 'October', 'November', 'December']


def _esc(v) -> str:
    if v is None:
        return ''
    return _html.escape(str(v), quote=True)


def _fmt_long_date(iso: str) -> str:
    """'2026-05-04' -> 'Monday, May 4, 2026'. Falls back to raw on bad input."""
    if not iso:
        return ''
    try:
        d = datetime.strptime(iso, '%Y-%m-%d').date()
        return f"{WEEKDAYS_LONG[d.weekday()]}, {MONTHS_LONG[d.month-1]} {d.day}, {d.year}"
    except (ValueError, TypeError):
        return str(iso)


def _fmt_short_date(iso: str) -> str:
    """'2026-05-04' -> 'Mon · 05-04-2026'. MM-DD-YYYY is the operator's
    preferred read form (per the display-format rule); the leading day-of-week
    abbreviation stays for the at-a-glance "what day was that?" check on
    rendered DCRs. Falls back to raw on bad input."""
    if not iso:
        return '—'
    try:
        d = datetime.strptime(iso, '%Y-%m-%d').date()
        wkd = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d.weekday()]
        return f"{wkd} · {d.strftime('%m-%d-%Y')}"
    except (ValueError, TypeError):
        return str(iso)


def _fmt_mdy(iso: str) -> str:
    """'2026-05-04' (or 'YYYY-MM-DDTHH:MM:SS') -> '05-04-2026'. Date-only
    MM-DD-YYYY display formatter — the single source of truth on the
    Python side, mirroring SSCDatePicker.fmtMDY on the client. The
    "Issued at" header path drops the time per the display rule; the
    full datetime stays stored on the report for audit."""
    if not iso:
        return ''
    s = str(iso)[:10]
    try:
        d = datetime.strptime(s, '%Y-%m-%d').date()
        return d.strftime('%m-%d-%Y')
    except (ValueError, TypeError):
        return str(iso)


def _fmt_weather(weather: Dict[str, Any]) -> str:
    """Compact weather string for the project-info cell. Tolerates both
    shapes the aggregator returns:
      - {am: {temp_f, conditions}, pm: {temp_f, conditions}, wind, source}
      - {am: <number>, pm: <number>, wind, source}  (live fallback older path)
    Source='unavailable' degrades silently to '—'.
    """
    if not weather or weather.get('source') == 'unavailable':
        return '—'

    def _temp(block):
        if block is None: return None
        if isinstance(block, dict): return block.get('temp_f')
        return block  # plain number / string

    def _cond(block):
        if isinstance(block, dict): return block.get('conditions')
        return None

    am = _temp(weather.get('am'))
    pm = _temp(weather.get('pm'))
    cond = _cond(weather.get('am')) or _cond(weather.get('pm')) or weather.get('conditions')
    wind = weather.get('wind')

    bits = []
    if cond:
        bits.append(str(cond))
    try:
        if am is not None and pm is not None:
            bits.append(f"AM {round(float(am))}° · PM {round(float(pm))}°")
        elif am is not None:
            bits.append(f"{round(float(am))}°F")
        elif pm is not None:
            bits.append(f"{round(float(pm))}°F")
    except (TypeError, ValueError):
        pass  # bad number data — skip the temp portion
    if wind:
        bits.append(f"Wind {wind}")
    return ' · '.join(bits) if bits else '—'


class DCRHTMLRenderer:
    def __init__(self, dcr_data: Dict[str, Any]):
        self.dcr = dcr_data
        self.audience = dcr_data.get('audience', 'internal')

    def render(self) -> str:
        # Both audiences use the same shell + section ordering — only the
        # labor + safety + issues + visitors bodies differ (redaction).
        body_parts = [
            self._head(),
            self._header_band(),
            '<div class="wrap">',
            self._section_project_info(),
            self._section_labor(),
            self._section_work(),
            '<div class="two">',
            self._section_materials(),
            self._section_equipment(),
            '</div>',
            '<div class="two">',
            self._section_safety(),
            self._section_issues(),
            '</div>',
            '<div class="two">',
            self._section_inspections(),
            self._section_visitors(),
            '</div>',
            self._section_photos(),
            self._section_signoff(),
            '</div>',  # /wrap
            self._footer(),
            self._lightbox_block(),
            self._fit_one_page_script(),
            '</body></html>',
        ]
        return ''.join(body_parts)

    # Compatibility shims for any caller that imported the per-audience methods.
    def render_internal(self) -> str:
        self.audience = 'internal'
        return self.render()

    def render_client(self) -> str:
        self.audience = 'client'
        return self.render()

    # ---------- Shell ----------

    def _head(self) -> str:
        # Print contract is enforced by @media print: every .sec is
        # break-inside:avoid + page-break-inside:avoid; every section
        # heading is break-after:avoid so it never strands. .two becomes a
        # 1-column stack in print so the side-by-side blocks don't get
        # split in half across a page boundary.
        title = ("Daily Construction Report" if self.audience == 'internal'
                 else "Daily Progress Report")
        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
    {get_inlined_style_tag()}
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>{_esc(title)}</title>
<style>
  :root {{
    --ink:#1c1c1c; --ink-soft:#3d3d3d;
    --black:#15161a; --red:#be1e2d; --red-dark:#8f1622;
    --line:#d9d9d9; --line-soft:#ededed; --zebra:#f7f7f8;
    --muted:#6f6f6f; --ok:#1f7a4d;
    --cream:#f7f3ea; --paper:#ffffff;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin:0; padding:0; background:var(--cream); }}
  body {{
    font-family:"Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    color:var(--ink); font-size:12px; line-height:1.42;
    -webkit-print-color-adjust:exact; print-color-adjust:exact;
  }}
  /* max-width (not fixed width) so the page shrinks on narrow viewports
     rather than overflowing horizontally and clipping the right edge. */
  .page {{ width:8.5in; max-width:100%; min-height:11in; margin:18px auto; background:var(--paper); box-shadow:0 6px 24px rgba(0,0,0,.22); }}

  /* ---------- Letterhead ----------
     box-sizing:border-box keeps the 0.55in padding INSIDE the .page width,
     not added on top of it (which would push content past the right edge
     in print after the @page margin is applied). min-width:0 on the flex
     children lets the docmeta block shrink rather than overflowing its
     column when the page area is constrained. */
  .head {{ background:var(--black); color:#fff; display:flex; justify-content:space-between; align-items:center; gap:16px; padding:14px 0.55in; box-sizing:border-box; }}
  .brand {{ display:flex; align-items:center; gap:14px; min-width:0; flex-shrink:1; }}
  .brand .logo svg {{ display:block; }}
  .brand .name h1 {{ margin:0; font-size:20px; font-weight:800; letter-spacing:.3px; }}
  .brand .name .sub {{ margin:2px 0 0; font-size:9.5px; color:#c7c7cc; letter-spacing:1.6px; text-transform:uppercase; }}
  .docmeta {{ text-align:right; min-width:0; flex-shrink:0; }}
  .docmeta .doctype {{ font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:1.2px; white-space:nowrap; }}
  .docmeta .rid {{ font-size:10.5px; color:#c7c7cc; margin-top:3px; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .redbar {{ height:4px; background:var(--red); }}

  .wrap {{ padding:0.4in 0.55in 0.5in; }}

  /* ---------- Project info grid ---------- */
  .info {{ display:grid; grid-template-columns:repeat(4,1fr); border:1px solid var(--line); border-radius:5px; overflow:hidden; margin-bottom:14px; }}
  .info .cell {{ padding:7px 10px; border-right:1px solid var(--line-soft); border-bottom:1px solid var(--line-soft); }}
  .info .cell:nth-child(4n) {{ border-right:none; }}
  .info .k {{ font-size:8.5px; text-transform:uppercase; letter-spacing:.8px; color:var(--red); font-weight:700; }}
  .info .v {{ font-size:12px; font-weight:600; margin-top:2px; word-break:break-word; }}
  .info .wide {{ grid-column: span 2; }}

  /* ---------- Section ---------- */
  .sec {{ margin-bottom:12px; }}
  .sec > h2 {{ display:flex; justify-content:space-between; align-items:center; font-size:11px; text-transform:uppercase; letter-spacing:.9px; color:#fff; background:var(--black); margin:0; padding:6px 10px; border-bottom:3px solid var(--red); border-radius:3px 3px 0 0; }}
  .sec > h2 .n {{ color:var(--red); font-weight:800; margin-right:7px; }}
  .sec > h2 .meta {{ font-size:9.5px; color:#c7c7cc; letter-spacing:.5px; text-transform:none; font-weight:500; }}
  .sec .body {{ border:1px solid var(--line); border-top:none; border-radius:0 0 3px 3px; }}
  .sec .pad {{ padding:8px 10px; }}
  .sec .empty {{ padding:8px 10px; color:var(--muted); font-style:italic; }}

  /* ---------- Tables ---------- */
  table {{ width:100%; border-collapse:collapse; font-size:11px; }}
  thead th {{ background:var(--zebra); text-align:left; font-size:8.5px; text-transform:uppercase; letter-spacing:.6px; color:var(--ink-soft); padding:5px 8px; border-bottom:2px solid var(--red); }}
  tbody td {{ padding:5px 8px; border-bottom:1px solid var(--line-soft); vertical-align:top; }}
  tbody tr:nth-child(even) {{ background:var(--zebra); }}
  td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  td.wid {{ font-weight:700; font-variant-numeric:tabular-nums; color:var(--red-dark); white-space:nowrap; }}
  tfoot td {{ padding:6px 8px; font-weight:700; border-top:2px solid var(--black); background:#fbfbfc; }}

  /* ---------- Work performed rows ---------- */
  .work-row {{ display:flex; gap:10px; padding:7px 10px; border-bottom:1px solid var(--line-soft); }}
  .work-row:last-child {{ border-bottom:none; }}
  .work-loc {{ flex:0 0 140px; font-weight:700; font-size:10.5px; color:var(--red-dark); }}
  .work-desc {{ flex:1; }}
  .work-trade {{ font-size:9.5px; color:var(--muted); margin-top:2px; }}

  /* ---------- Photos ---------- */
  .photos {{ display:grid; grid-template-columns:repeat(3,1fr); gap:8px; padding:10px; }}
  .photo {{ border:1px solid var(--line); border-radius:4px; overflow:hidden; }}
  .photo .ph {{ height:120px; background:repeating-linear-gradient(45deg,#f0f0f0,#f0f0f0 10px,#e7e7e7 10px,#e7e7e7 20px); display:flex; align-items:center; justify-content:center; color:var(--muted); font-size:10px; }}
  .photo img {{ display:block; width:100%; height:140px; object-fit:cover; }}
  .photo .cap {{ padding:5px 7px; font-size:9.5px; color:var(--ink-soft); border-top:1px solid var(--line-soft); }}
  .photo .cap b {{ color:var(--red-dark); }}

  .two {{ display:grid; grid-template-columns:1fr 1fr; gap:12px; }}
  .badge {{ display:inline-block; font-size:8.5px; font-weight:700; color:var(--ok); border:1px solid var(--ok); border-radius:10px; padding:1px 7px; text-transform:uppercase; letter-spacing:.5px; }}
  .badge.warn {{ color:#a8530a; border-color:#a8530a; }}
  .badge.bad  {{ color:var(--red-dark); border-color:var(--red-dark); }}

  .signoff {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; margin-top:6px; }}
  .sigbox {{ border-top:1.5px solid var(--black); padding-top:5px; }}
  .sigbox .role {{ font-size:8.5px; text-transform:uppercase; letter-spacing:.8px; color:var(--red); font-weight:700; }}
  .sigbox .nm {{ font-size:11px; font-weight:600; margin-top:14px; min-height:14px; }}
  .sigbox .d {{ font-size:10px; color:var(--muted); margin-top:4px; }}

  .foot {{ margin:16px 0.55in 0; border-top:2px solid var(--red); padding:7px 0 18px; display:flex; justify-content:space-between; font-size:8.5px; color:var(--muted); }}

  .warnbar {{ background:#fff3cd; border:1px solid #d4a90a; color:#5a4500; padding:6px 10px; border-radius:4px; font-size:10.5px; margin-bottom:10px; }}

  /* =========================================================
     PRINT / PDF — same rules drive browser Ctrl+P and the
     headless-Edge auto-PDF. On screen the report flows as one
     continuous document; in print, sections paginate cleanly.
     ========================================================= */
  @media print {{
    @page {{ size: Letter portrait; margin: 0.4in; }}
    html, body {{ background:#fff; }}
    /* In print, .page fills the printable area (Letter minus @page margin
       = ~7.7in). max-width:none drops the 100% cap that the screen rule
       imposes; width:auto + box-sizing:border-box ensures the .page
       container itself has zero width-overflow risk. */
    .page {{ box-shadow:none; margin:0; width:auto; max-width:none; min-height:auto; box-sizing:border-box; }}
    /* Header/body/foot horizontal insets match the screen layout (0.55in)
       so the PDF reads like the on-screen "boxed" report — framed inset
       from the page edge, not edge-to-edge. Earlier override was zeroing
       these and made the print look sparse + run to the paper edge. The
       @page margin (0.4in) is OUTSIDE these insets, so the total gutter
       from the physical paper edge to content is 0.4 + 0.55 = 0.95in
       — comfortable and matches a typical printed report. */
    .head {{ padding:14px 0.55in; box-sizing:border-box; }}
    .wrap {{ padding:0.25in 0.55in 0; }}
    /* .foot's horizontal margin: 0.55in carries through from the screen
       rule — no print override needed. */
    /* Section pagination: keep title with body; never split mid-section. */
    .sec        {{ break-inside:avoid; page-break-inside:avoid; }}
    .sec > h2   {{ break-after:avoid;  page-break-after:avoid; }}
    .sec .body  {{ break-before:avoid; page-break-before:avoid; }}
    /* Side-by-side blocks (.two) stay two-column in print so the report
       looks identical to the screen layout — same tight, boxed pairing
       for Materials/Equipment, Safety/Issues, Inspections/Visitors. The
       break-inside:avoid on the wrapper moves the WHOLE paired row to
       the next page if it doesn't fit, rather than slicing it mid-column.
       Each child .sec also has break-inside:avoid (rule above) as a
       second-line defense in case a single half is genuinely too tall. */
    .two        {{ break-inside:avoid; page-break-inside:avoid; }}
    /* Table rows shouldn't split; repeat <thead> if a table wraps to next page. */
    thead       {{ display:table-header-group; }}
    tfoot       {{ display:table-footer-group; }}
    tr          {{ break-inside:avoid; page-break-inside:avoid; }}
    /* Photos grid: each tile keeps together. */
    .photo      {{ break-inside:avoid; page-break-inside:avoid; }}
  }}
</style>
</head><body>
<div class="page">"""

    def _header_band(self) -> str:
        display_id = self.dcr.get('display_id') or self.dcr.get('report_id') or '—'
        proj = self.dcr.get('project') or {}
        doctype = ("Daily Construction Report" if self.audience == 'internal'
                   else "Daily Progress Report")
        # No-Work Day banner — prominent below the header band when set.
        # Renders for both audiences. Optional note appears in smaller
        # weight after the reason so the rendered report carries the
        # operator's free-text context (e.g. "site closed by GC").
        nw_html = ''
        if self.dcr.get('no_work'):
            reason = (self.dcr.get('no_work_reason') or 'OTHER').upper()
            note = self.dcr.get('no_work_note') or ''
            note_html = (f' <span style="font-weight:400;color:#444;">· {_esc(note)}</span>'
                         if note else '')
            nw_html = (
                f'<div class="nowork-band" style="background:#FFE8D6;border-left:6px solid var(--red);'
                f'padding:10px 16px;margin-top:4px;font-size:14px;font-weight:800;color:#7A2E1B;'
                f'letter-spacing:0.05em;text-transform:uppercase;">'
                f'⛔ NO WORK — {_esc(reason)}{note_html}</div>'
            )
        return f"""<div class="head">
  <div class="brand">
    <!-- SWAP HERE when official brand logo arrives.  See SUPERSTARS_STAR_SVG
         constant at top of render_dcr_html.py. -->
    <div class="logo">{SUPERSTARS_STAR_SVG}</div>
    <div class="name">
      <h1>Superstars Contracting Inc.</h1>
      <div class="sub">Facade Restoration · New York City</div>
    </div>
  </div>
  <div class="docmeta">
    <div class="doctype">{_esc(doctype)}</div>
    <div class="rid">{_esc(display_id)}</div>
    <div class="rid">{_esc(_fmt_mdy(proj.get('date')))}</div>
  </div>
</div>
<div class="redbar"></div>
{nw_html}"""

    def _footer(self) -> str:
        proj = self.dcr.get('project') or {}
        warnings = ((self.dcr.get('metadata') or {}).get('warnings') or [])
        warn_html = ''
        if warnings and self.audience == 'internal':
            # Internal report surfaces the aggregator warnings inline at the
            # bottom so the operator sees them when reviewing the PDF.
            items = ''.join(f"<li>{_esc(w)}</li>" for w in warnings)
            warn_html = (f'<div class="wrap" style="padding-top:0;padding-bottom:0;">'
                         f'<div class="warnbar"><strong>Aggregator notes:</strong>'
                         f'<ul style="margin:4px 0 0 16px;padding:0;">{items}</ul></div></div>')
        code = _esc(proj.get('code') or '')
        return f"""{warn_html}<div class="foot">
  <div><span style="color:var(--red);">★</span> Superstars Contracting Inc. · Facade Restoration · New York City</div>
  <div>Project {code} · Generated {_esc(datetime.now().strftime('%m-%d-%Y %H:%M'))}</div>
</div></div>"""

    # ---------- 1. Project Information ----------

    def _section_project_info(self) -> str:
        p = self.dcr.get('project') or {}
        display_id = self.dcr.get('display_id') or self.dcr.get('report_id') or '—'
        weather_str = _fmt_weather(self.dcr.get('weather'))
        cells = []

        def cell(k, v, wide=False):
            cls = "cell wide" if wide else "cell"
            cells.append(f'<div class="{cls}"><div class="k">{_esc(k)}</div><div class="v">{_esc(v) or "—"}</div></div>')

        cell("Report Number", display_id)
        cell("Code", p.get('code'))
        cell("Date", _fmt_short_date(p.get('date')))
        cell("Weather", weather_str)
        cell("Project", p.get('name'), wide=True)
        cell("Address", p.get('address'), wide=True)
        cell("Client", p.get('owner_client') or '—')
        cell("Superintendent", p.get('superintendent') or '—')
        cell("Project Manager", p.get('project_manager') or '—')
        cell("Status", (p.get('status') or '—').title())
        return f"""<div class="sec">
  <h2><span><span class="n">1</span>Project Information</span></h2>
  <div class="body"><div class="info" style="border:none;border-radius:0;margin:0;">
    {''.join(cells)}
  </div></div>
</div>"""

    # ---------- 2. Labor Tracking ----------

    def _section_labor(self) -> str:
        labor = self.dcr.get('labor') or {}
        if self.audience == 'client':
            return self._section_labor_client(labor)
        rows = labor.get('rows') or []
        headcount = labor.get('headcount') or 0
        total_hours = labor.get('total_hours')
        meta = f'{headcount} {"worker" if headcount == 1 else "workers"}'
        if total_hours not in (None, ''):
            meta += f' · {total_hours} hrs worked'
        if not rows:
            return self._sec_empty(2, "Labor Tracking", meta, "No sign-in data for this date.")
        tr = []
        for i, r in enumerate(rows, 1):
            wid = r.get('worker_id') or '—'
            tr.append(
                f"<tr><td>{i}</td>"
                f'<td class="wid">{_esc(wid)}</td>'
                f'<td>{_esc(r.get("name") or "—")}</td>'
                f'<td>{_esc(r.get("trade") or "—")}</td>'
                f'<td class="num">{_esc(r.get("time_in") or "—")}</td>'
                f'<td class="num">{_esc(r.get("time_out") or "—")}</td>'
                f'<td class="num">{_esc(r.get("hours") if r.get("hours") is not None else "—")}</td></tr>'
            )
        tfoot_total = _esc(total_hours if total_hours is not None else '—')
        tfoot_workers = f'{headcount} on site'
        return f"""<div class="sec">
  <h2><span><span class="n">2</span>Labor Tracking</span><span class="meta">{_esc(meta)}</span></h2>
  <div class="body">
    <table>
      <thead><tr>
        <th style="width:16px">#</th><th style="width:62px">Worker ID</th>
        <th>Name</th><th>Trade</th>
        <th class="num">In</th><th class="num">Out</th><th class="num">Hrs</th>
      </tr></thead>
      <tbody>{''.join(tr)}</tbody>
      <tfoot><tr><td colspan="6">Total — {_esc(tfoot_workers)}</td><td class="num">{tfoot_total}</td></tr></tfoot>
    </table>
  </div>
</div>"""

    def _section_labor_client(self, labor: Dict[str, Any]) -> str:
        summary = labor.get('summary') or {}
        by_trade = summary.get('by_trade') or []
        headcount = labor.get('headcount') or 0
        total_hours = labor.get('total_hours')
        meta = f'{headcount} {"worker" if headcount == 1 else "workers"}'
        if total_hours not in (None, ''):
            meta += f' · {total_hours} hrs'
        if not by_trade:
            return self._sec_empty(2, "Labor Summary", meta, "No labor data available.")
        tr = []
        for item in by_trade:
            tr.append(
                f'<tr><td>{_esc(item.get("trade") or "—")}</td>'
                f'<td class="num">{_esc(item.get("count") or 0)}</td>'
                f'<td class="num">{_esc(item.get("hours") or 0)}</td></tr>'
            )
        return f"""<div class="sec">
  <h2><span><span class="n">2</span>Labor Summary</span><span class="meta">{_esc(meta)}</span></h2>
  <div class="body">
    <table>
      <thead><tr><th>Trade</th><th class="num">Count</th><th class="num">Hours</th></tr></thead>
      <tbody>{''.join(tr)}</tbody>
    </table>
  </div>
</div>"""

    # ---------- 3. Work Performed ----------

    def _section_work(self) -> str:
        work = self.dcr.get('work_performed') or []
        if not work:
            return self._sec_empty(3, "Work Performed", "", "No work logged.")
        rows = []
        for w in work:
            loc = w.get('location_elevation') or w.get('trade_area') or '—'
            trade = w.get('trade_area') or ''
            desc = w.get('description') or '—'
            trade_html = (f'<div class="work-trade">{_esc(trade)}</div>'
                          if trade and trade != loc else '')
            rows.append(
                f'<div class="work-row">'
                f'<div class="work-loc">{_esc(loc)}{trade_html}</div>'
                f'<div class="work-desc">{_esc(desc)}</div>'
                f'</div>'
            )
        return f"""<div class="sec">
  <h2><span><span class="n">3</span>Work Performed</span></h2>
  <div class="body">{''.join(rows)}</div>
</div>"""

    # ---------- 4. Materials & Deliveries ----------

    def _section_materials(self) -> str:
        mat = self.dcr.get('materials_deliveries') or []
        if not mat:
            return self._sec_empty(4, "Materials & Deliveries", "", "None.")
        tr = []
        for m in mat:
            qty = m.get('qty')
            unit = m.get('unit') or ''
            qty_str = f"{qty} {unit}".strip() if qty is not None else '—'
            tr.append(
                f'<tr><td>{_esc(m.get("material") or "—")}</td>'
                f'<td class="num">{_esc(qty_str)}</td>'
                f'<td>{_esc(m.get("supplier") or "—")}</td></tr>'
            )
        return f"""<div class="sec">
  <h2><span><span class="n">4</span>Materials &amp; Deliveries</span></h2>
  <div class="body"><table>
    <thead><tr><th>Item</th><th class="num">Qty</th><th>Supplier</th></tr></thead>
    <tbody>{''.join(tr)}</tbody>
  </table></div>
</div>"""

    # ---------- 5. Equipment Delivered to Site ----------

    def _section_equipment(self) -> str:
        equip = self.dcr.get('equipment') or []
        if not equip:
            return self._sec_empty(5, "Equipment Delivered to Site", "", "None.")
        tr = []
        for e in equip:
            label = e.get('equipment_type') or e.get('equipment') or '—'
            status = e.get('status') or ''
            extra = f' <span style="color:var(--muted);font-size:10px;">({_esc(status)})</span>' if status else ''
            tr.append(
                f'<tr><td>{_esc(label)}{extra}</td>'
                f'<td class="num">{_esc(e.get("hours_used") or "—")}</td></tr>'
            )
        return f"""<div class="sec">
  <h2><span><span class="n">5</span>Equipment Delivered to Site</span></h2>
  <div class="body"><table>
    <thead><tr><th>Item</th><th class="num">Qty/Hrs</th></tr></thead>
    <tbody>{''.join(tr)}</tbody>
  </table></div>
</div>"""

    # ---------- 6. Safety ----------

    def _section_safety(self) -> str:
        safety = self.dcr.get('safety') or {}
        talk = safety.get('toolbox_talk')
        events = safety.get('events') or []
        badge = '<span class="badge">No incidents</span>' if not events else f'<span class="badge bad">{len(events)} event(s)</span>'
        talk_line = ''
        if talk:
            topic = talk.get('topic') or '—'
            by = talk.get('conducted_by') or talk.get('facilitator')
            talk_line = f'<p style="margin:6px 0 4px"><strong>Toolbox talk:</strong> {_esc(topic)}'
            if by:
                talk_line += f' <span style="color:var(--muted);">({_esc(by)})</span>'
            talk_line += '</p>'
        else:
            talk_line = '<p style="margin:6px 0 4px"><strong>Toolbox talk:</strong> Not conducted.</p>'
        events_line = ''
        if events:
            items = []
            for ev in events:
                if self.audience == 'client':
                    items.append(f'<li>{_esc(ev.get("type") or "Incident")} — under review</li>')
                else:
                    when = ev.get('time') or ''
                    who = ev.get('person') or ''
                    desc = ev.get('description') or ''
                    items.append(
                        f'<li><strong>{_esc(ev.get("type") or "Incident")}</strong>'
                        + (f' · {_esc(when)}' if when else '')
                        + (f' · {_esc(who)}' if who else '')
                        + (f' — {_esc(desc)}' if desc else '')
                        + '</li>'
                    )
            events_line = '<ul style="margin:4px 0 0 16px;padding:0;">' + ''.join(items) + '</ul>'
        else:
            events_line = '<p style="margin:0"><strong>Events:</strong> None reported.</p>'
        return f"""<div class="sec">
  <h2><span><span class="n">6</span>Safety</span></h2>
  <div class="body pad">
    <p style="margin:0 0 6px">{badge}</p>
    {talk_line}
    {events_line}
  </div>
</div>"""

    # ---------- 7. Issues / Delays ----------

    def _section_issues(self) -> str:
        issues = self.dcr.get('issues_delays') or []
        if not issues:
            return self._sec_empty(7, "Issues / Delays", "", "None. Work proceeded on schedule.")
        tr = []
        for i in issues:
            if self.audience == 'client':
                tr.append(
                    f'<tr><td>{_esc(i.get("category") or "—")}</td>'
                    f'<td>{_esc(i.get("summary") or i.get("status") or "Under review")}</td></tr>'
                )
            else:
                tr.append(
                    f'<tr><td>{_esc(i.get("category") or "—")}</td>'
                    f'<td>{_esc(i.get("description") or "—")}</td>'
                    f'<td class="num">{_esc(i.get("time_lost_hrs") if i.get("time_lost_hrs") is not None else "—")}</td>'
                    f'<td>{_esc(i.get("owner") or "—")}</td></tr>'
                )
        if self.audience == 'client':
            head = '<thead><tr><th>Category</th><th>Status</th></tr></thead>'
        else:
            head = '<thead><tr><th>Category</th><th>Description</th><th class="num">Hrs Lost</th><th>Owner</th></tr></thead>'
        return f"""<div class="sec">
  <h2><span><span class="n">7</span>Issues / Delays</span></h2>
  <div class="body"><table>{head}<tbody>{''.join(tr)}</tbody></table></div>
</div>"""

    # ---------- 8. Inspections ----------

    def _section_inspections(self) -> str:
        insp = self.dcr.get('inspections') or []
        if not insp:
            return self._sec_empty(8, "Inspections", "", "None.")
        tr = []
        for i in insp:
            tr.append(
                f'<tr><td>{_esc(i.get("type") or i.get("scope") or "—")}</td>'
                f'<td>{_esc(i.get("agency") or i.get("inspector_name") or i.get("inspector") or "—")}</td>'
                f'<td class="num">{_esc(i.get("result") or "—")}</td></tr>'
            )
        return f"""<div class="sec">
  <h2><span><span class="n">8</span>Inspections</span></h2>
  <div class="body"><table>
    <thead><tr><th>Type</th><th>Agency / Inspector</th><th class="num">Result</th></tr></thead>
    <tbody>{''.join(tr)}</tbody>
  </table></div>
</div>"""

    # ---------- 9. Visitors ----------

    def _section_visitors(self) -> str:
        visitors = self.dcr.get('visitors')
        if self.audience == 'client':
            return self._section_visitors_client(visitors)
        # internal: list view
        rows = visitors if isinstance(visitors, list) else []
        if not rows:
            return self._sec_empty(9, "Visitors", "", "None.")
        tr = []
        for v in rows:
            tr.append(
                f'<tr><td>{_esc(v.get("name") or "—")}</td>'
                f'<td>{_esc(v.get("company") or v.get("org") or "—")}</td>'
                f'<td class="num">{_esc(v.get("time_in") or "—")}</td></tr>'
            )
        return f"""<div class="sec">
  <h2><span><span class="n">9</span>Visitors</span></h2>
  <div class="body"><table>
    <thead><tr><th>Name</th><th>Org</th><th class="num">Time</th></tr></thead>
    <tbody>{''.join(tr)}</tbody>
  </table></div>
</div>"""

    def _section_visitors_client(self, visitors) -> str:
        v = visitors if isinstance(visitors, dict) else {}
        by_role = v.get('count_by_role') or []
        total = v.get('total_visits') or 0
        if not by_role and not total:
            return self._sec_empty(9, "Visitors", "", "None.")
        tr = ''.join(
            f'<tr><td>{_esc(item.get("role") or "—")}</td>'
            f'<td class="num">{_esc(item.get("count") or 0)}</td></tr>'
            for item in by_role
        )
        meta = f'{total} visit(s)'
        return f"""<div class="sec">
  <h2><span><span class="n">9</span>Visitors</span><span class="meta">{_esc(meta)}</span></h2>
  <div class="body"><table>
    <thead><tr><th>Role</th><th class="num">Visits</th></tr></thead>
    <tbody>{tr}</tbody>
  </table></div>
</div>"""

    # ---------- 10. Photos ----------

    def _section_photos(self) -> str:
        photos = self.dcr.get('photos') or []
        if not photos:
            return self._sec_empty(10, "Photos", "", "None attached.")
        tiles = []
        for p in photos[:12]:  # cap at 12 — keeps PDF page count sane
            # photos.url is the gated /project-files/ URL (#248); the
            # file_path fallback mirrors that scheme for legacy rows.
            url = p.get('url') or (('/project-files/' + p.get('file_path')) if p.get('file_path') else None)
            cap = []
            loc = p.get('location')
            desc = p.get('description')
            if loc: cap.append(f'<b>{_esc(loc)}</b>')
            if desc: cap.append(_esc(desc))
            cap_html = ' — '.join(cap) if cap else '&nbsp;'
            if url:
                # DCR-3: each photo's <img> carries data-zoom-src so the
                # rendered/issued DCR's inline lightbox script (injected
                # in _head's @media print fence) opens it full-screen on
                # click. data-zoom-src is ignored by the print stylesheet
                # so paginated PDFs are unchanged.
                tiles.append(
                    f'<div class="photo"><img src="{_esc(url)}" '
                    f'data-zoom-src="{_esc(url)}" alt="{_esc(loc or "site photo")}">'
                    f'<div class="cap">{cap_html}</div></div>'
                )
            else:
                tiles.append(f'<div class="photo"><div class="ph">[ Site photo ]</div><div class="cap">{cap_html}</div></div>')
        meta = f'{len(photos)} attached'
        return f"""<div class="sec">
  <h2><span><span class="n">10</span>Photos</span><span class="meta">{_esc(meta)}</span></h2>
  <div class="body"><div class="photos">{''.join(tiles)}</div></div>
</div>"""

    # ---------- 11. Sign-Off ----------

    def _section_signoff(self) -> str:
        s = self.dcr.get('signoff') or {}
        p = self.dcr.get('project') or {}
        super_name = s.get('superintendent_name') or p.get('superintendent') or ''
        pm_name = s.get('pm_name') or p.get('project_manager') or ''
        date_text = _fmt_short_date(p.get('date'))
        if self.audience == 'client':
            footer_note = ('<p style="margin:8px 0 0;font-size:10px;color:var(--muted);">'
                           'This report is provided to the building owner / managing agent.'
                           '</p>')
        else:
            footer_note = ''
        return f"""<div class="sec">
  <h2><span><span class="n">11</span>Sign-Off</span></h2>
  <div class="body pad">
    <div class="signoff">
      <div class="sigbox"><div class="role">Prepared by — Superintendent</div><div class="nm">{_esc(super_name)}</div><div class="d">Date: {_esc(date_text)}</div></div>
      <div class="sigbox"><div class="role">Reviewed by — Project Manager</div><div class="nm">{_esc(pm_name)}</div><div class="d">Date: ____________</div></div>
    </div>
    {footer_note}
  </div>
</div>"""

    # ---------- helpers ----------

    def _lightbox_block(self) -> str:
        """Inline image lightbox for the rendered/issued DCR (DCR-3).

        Each photo's <img> in _section_photos carries a `data-zoom-src`
        attribute; clicking opens the image full-screen. Esc or click on
        the overlay dismisses. Self-contained — no external script, no
        coupling to the dashboard's lightbox.

        Print-safe: the overlay starts at display:none and the @media
        print stylesheet keeps it that way, so PDF generation is
        untouched. cursor:zoom-in on the photo <img> is screen-only
        (print stylesheet resets cursor).
        """
        return """
<div id="dcr-img-lightbox" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:9000;align-items:center;justify-content:center;cursor:zoom-out;">
  <img id="dcr-img-lightbox-content" src="" alt="" style="max-width:92vw;max-height:92vh;object-fit:contain;box-shadow:0 8px 40px rgba(0,0,0,0.5);">
</div>
<style>
  .photo img { cursor:zoom-in; }
  @media print { #dcr-img-lightbox { display:none !important; } .photo img { cursor:default; } }
</style>
<script>
(function(){
  var lb  = document.getElementById('dcr-img-lightbox');
  var img = document.getElementById('dcr-img-lightbox-content');
  if (!lb || !img) return;
  function open(src) { if (!src) return; img.src = src; lb.style.display = 'flex'; }
  function close() { lb.style.display = 'none'; img.src = ''; }
  lb.addEventListener('click', close);
  document.addEventListener('keydown', function(e) { if (e.key === 'Escape' && lb.style.display !== 'none') close(); });
  document.addEventListener('click', function(e) {
    var t = e.target;
    if (!t || !t.closest) return;
    var z = t.closest('[data-zoom-src]');
    if (z) { e.preventDefault(); e.stopPropagation(); open(z.getAttribute('data-zoom-src')); }
  });
})();
</script>
"""

    def _fit_one_page_script(self) -> str:
        """Print-time JS: if the report is JUST barely over one page (≤1.25×),
        squeeze the .page wrapper down so it fits on a single page. If it's
        a genuinely long report (>1.25×), do nothing — don't crush.

        Implementation note (why `zoom`, not `transform: scale`):
        Chromium's print engine paginates based on the LAYOUT box. CSS
        `transform: scale()` only affects the paint, not the layout — so
        a transform-shrunk report still emits an unscaled page 2 because
        the layout flow math used the pre-scale height. CSS `zoom` (a
        Chromium/IE-legacy property) DOES affect layout. Edge headless
        and Ctrl+P from Edge/Chrome both honor it; that's our primary
        target. transform: scale is kept as a paint fallback for browsers
        without `zoom` (Firefox, Safari) — those rarely produce the
        finalize PDF in this workflow anyway.

        Runs on:
          - browser Ctrl+P: window.beforeprint event
          - headless Edge --print-to-pdf: print media kicks in only at
            capture time, so matchMedia('print') is false while JS runs.
            We instead listen to `beforeprint` (Chromium DOES fire it
            for --print-to-pdf) and also try on window 'load' as a safety
            net (the --virtual-time-budget=5000 in pdf_export.py covers it).
        Reverts on afterprint so the screen view stays at 1:1.

        Threshold + page-height constants are exposed at the top of the IIFE
        so the operator can tune in render_dcr_html.py without spelunking.
        """
        return """
<script>
(function() {
  // ----- tunables -----
  // Reports up to SHRINK_LIMIT × one page get squeezed onto one page;
  // beyond that, normal pagination. 1.25 = a 1-and-a-bit page report
  // (footer/sign-off spills) snaps to one page without crushing a real
  // 2-page report. Tweak if needed.
  var SHRINK_LIMIT = 1.25;
  // Letter portrait (11in) minus @page top+bottom margins (0.4in each)
  // = 10.2in printable. Browsers use 96 CSS px per inch in print.
  var PAGE_HEIGHT_PX = (11 - 0.4 - 0.4) * 96;  // 979.2
  // Small safety so a borderline case doesn't fall one pixel over a page break.
  var SAFETY = 0.98;
  var ROOT_SEL = '.page';

  function reset(root) {
    if (!root) return;
    root.style.zoom = '';
    root.style.transform = '';
    root.style.transformOrigin = '';
  }

  function fitIfClose() {
    var root = document.querySelector(ROOT_SEL);
    if (!root) return;
    reset(root);                                // measure unscaled
    var contentH = root.scrollHeight;
    if (contentH <= PAGE_HEIGHT_PX) return;     // already fits
    var ratio = contentH / PAGE_HEIGHT_PX;
    if (ratio > SHRINK_LIMIT) return;           // genuinely long — let it paginate
    var scale = (PAGE_HEIGHT_PX / contentH) * SAFETY;
    // Primary: `zoom` (Chromium) — affects layout flow + pagination.
    root.style.zoom = scale;
    // Fallback for non-Chromium (paint-only): transform:scale. If both
    // apply in Chromium, zoom wins; transform is a no-op there because
    // zoom already shrank the layout box.
    root.style.transform = 'scale(' + scale + ')';
    root.style.transformOrigin = 'top center';
  }

  // Browser Ctrl+P: scale on beforeprint, restore on afterprint.
  // Chromium headless --print-to-pdf ALSO fires beforeprint before the
  // capture, so this single listener handles both paths.
  window.addEventListener('beforeprint', fitIfClose);
  window.addEventListener('afterprint', function() {
    reset(document.querySelector(ROOT_SEL));
  });

  // Safety net for Edge headless in case beforeprint timing differs:
  // also try at window 'load' under print media. matchMedia('print')
  // typically reads false during the JS run window of --print-to-pdf
  // (print media only activates at capture), so this is mostly a no-op
  // — but harmless if true.
  window.addEventListener('load', function() {
    if (window.matchMedia && window.matchMedia('print').matches) {
      fitIfClose();
    }
  });
})();
</script>"""

    def _sec_empty(self, n: int, title: str, meta: str, empty_text: str) -> str:
        meta_html = f'<span class="meta">{_esc(meta)}</span>' if meta else '<span></span>'
        return f"""<div class="sec">
  <h2><span><span class="n">{n}</span>{_esc(title)}</span>{meta_html}</h2>
  <div class="body"><div class="empty">{_esc(empty_text)}</div></div>
</div>"""


def main():
    parser = argparse.ArgumentParser(description='Render DCR JSON to HTML')
    parser.add_argument('input_json', help='Input DCR JSON file')
    parser.add_argument('output_html', help='Output HTML file')
    args = parser.parse_args()
    try:
        with open(args.input_json, 'r', encoding='utf-8') as f:
            dcr = json.load(f)
        renderer = DCRHTMLRenderer(dcr)
        html_out = renderer.render()
        with open(args.output_html, 'w', encoding='utf-8') as f:
            f.write(html_out)
        print(f"HTML rendered: {args.output_html}", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
