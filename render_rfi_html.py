#!/usr/bin/env python3
"""RFI HTML Renderer — DCR design language for the formal RFI doc sent
to the architect / EOR / owner's rep (Reports Phase 2E).

Mirrors render_dcr_html.py's letterhead, section style, color palette,
and print/PDF pagination contract — same black/red/white SSC look,
same Archivo/Inter fonts, same break-inside:avoid section rules. The
two renderers SHARE the SUPERSTARS_STAR_SVG (imported from
render_dcr_html) so a future brand-logo swap touches one place.

Input shape: a row from rfi_log enriched with status_derived /
turnaround_days (the _rfi_row_to_dict helper in server.py produces it)
plus a `project` dict from the projects table. The /api/rfis/<n>/render
route in server.py composes both and calls render_rfi_html().

Print contract — identical to the DCR:
  - On screen: one continuous flowing document.
  - In print: @page Letter @ 0.4in margins, sections never split,
    headings never strand, .signoff pairs paginate atomically.

Supersedes the legacy script that rendered RFIs from a JSON file with
a different shape (priority / distribution_list / impacts). Phase 2C
forms write to the new spec field set; nothing reads the old JSON path.
"""
import html as _html
from datetime import datetime
from typing import Any, Dict

from render_dcr_html import SUPERSTARS_STAR_SVG
from typography import get_inlined_style_tag

WEEKDAYS_LONG = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
MONTHS_LONG   = ['January', 'February', 'March', 'April', 'May', 'June',
                 'July', 'August', 'September', 'October', 'November', 'December']


def _esc(v) -> str:
    if v is None:
        return ''
    return _html.escape(str(v), quote=True)


def _fmt_short(iso: str) -> str:
    if not iso:
        return '—'
    try:
        d = datetime.strptime(iso, '%Y-%m-%d').date()
        wkd = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'][d.weekday()]
        return f"{wkd} · {d.strftime('%m/%d/%Y')}"
    except (ValueError, TypeError):
        return str(iso)


def _fmt_long(iso: str) -> str:
    if not iso:
        return '—'
    try:
        d = datetime.strptime(iso, '%Y-%m-%d').date()
        return f"{MONTHS_LONG[d.month-1]} {d.day}, {d.year}"
    except (ValueError, TypeError):
        return str(iso)


def _status_badge_html(status: str) -> str:
    palette = {
        'Overdue':  ('#be1e2d', '#fff'),
        'Open':     ('#a8530a', '#fff'),
        'Answered': ('#1f7a4d', '#fff'),
        'Closed':   ('#6f6f6f', '#fff'),
        'Void':     ('#6f6f6f', '#fff'),
    }
    bg, fg = palette.get(status, palette['Open'])
    return (f'<span style="display:inline-block;background:{bg};color:{fg};'
            f'font-size:9px;font-weight:700;letter-spacing:.6px;'
            f'text-transform:uppercase;padding:3px 9px;border-radius:99px;">'
            f'{_esc(status)}</span>')


class RFIHTMLRenderer:
    """Render a single RFI as the SSC-branded formal document."""

    def __init__(self, rfi: Dict[str, Any], project: Dict[str, Any]):
        self.rfi = rfi
        self.project = project or {}

    def render(self) -> str:
        body_parts = [
            self._head(),
            self._header_band(),
            '<div class="wrap">',
            self._section_project_info(),
            self._section_subject_and_question(),
            self._section_location_and_scope(),
            self._section_impact(),
            self._section_response(),
            self._section_signoff(),
            '</div>',  # /wrap
            self._footer(),
            '</body></html>',
        ]
        return ''.join(body_parts)

    # ---------- Shell ----------

    def _head(self) -> str:
        return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
    {get_inlined_style_tag()}
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Request for Information</title>
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
  .page {{ width:8.5in; max-width:100%; min-height:11in; margin:18px auto; background:var(--paper); box-shadow:0 6px 24px rgba(0,0,0,.22); }}

  /* ---------- Letterhead (mirrors DCR) ---------- */
  .head {{ background:var(--black); color:#fff; display:flex; justify-content:space-between; align-items:center; gap:16px; padding:14px 0.55in; box-sizing:border-box; }}
  .brand {{ display:flex; align-items:center; gap:14px; min-width:0; flex-shrink:1; }}
  .brand .logo svg {{ display:block; }}
  .brand .name h1 {{ margin:0; font-size:20px; font-weight:800; letter-spacing:.3px; font-family:"Archivo", "Inter", sans-serif; }}
  .brand .name .sub {{ margin:2px 0 0; font-size:9.5px; color:#c7c7cc; letter-spacing:1.6px; text-transform:uppercase; }}
  .docmeta {{ text-align:right; min-width:0; flex-shrink:0; }}
  .docmeta .doctype {{ font-size:12px; font-weight:800; text-transform:uppercase; letter-spacing:1.2px; white-space:nowrap; font-family:"Archivo", "Inter", sans-serif; }}
  .docmeta .rid {{ font-size:10.5px; color:#c7c7cc; margin-top:3px; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .redbar {{ height:4px; background:var(--red); }}

  .wrap {{ padding:0.4in 0.55in 0.5in; }}

  /* ---------- Project info grid (mirrors DCR) ---------- */
  .info {{ display:grid; grid-template-columns:repeat(4,1fr); border:1px solid var(--line); border-radius:5px; overflow:hidden; margin-bottom:14px; }}
  .info .cell {{ padding:7px 10px; border-right:1px solid var(--line-soft); border-bottom:1px solid var(--line-soft); }}
  .info .cell:nth-child(4n) {{ border-right:none; }}
  .info .k {{ font-size:8.5px; text-transform:uppercase; letter-spacing:.8px; color:var(--red); font-weight:700; }}
  .info .v {{ font-size:12px; font-weight:600; margin-top:2px; word-break:break-word; }}
  .info .wide {{ grid-column: span 2; }}

  /* ---------- Section (mirrors DCR) ---------- */
  .sec {{ margin-bottom:12px; }}
  .sec > h2 {{ display:flex; justify-content:space-between; align-items:center; font-size:11px; text-transform:uppercase; letter-spacing:.9px; color:#fff; background:var(--black); margin:0; padding:6px 10px; border-bottom:3px solid var(--red); border-radius:3px 3px 0 0; font-family:"Archivo", "Inter", sans-serif; }}
  .sec > h2 .n {{ color:var(--red); font-weight:800; margin-right:7px; }}
  .sec > h2 .meta {{ font-size:9.5px; color:#c7c7cc; letter-spacing:.5px; text-transform:none; font-weight:500; }}
  .sec .body {{ border:1px solid var(--line); border-top:none; border-radius:0 0 3px 3px; }}
  .sec .pad {{ padding:8px 10px; }}
  .sec .empty {{ padding:8px 10px; color:var(--muted); font-style:italic; }}

  /* ---------- RFI-specific: question / answer stack ---------- */
  .qa-row {{ padding:10px 12px; border-bottom:1px solid var(--line-soft); }}
  .qa-row:last-child {{ border-bottom:none; }}
  .qa-label {{ font-size:8.5px; font-weight:700; text-transform:uppercase; letter-spacing:.8px; color:var(--red); margin-bottom:4px; }}
  .qa-value {{ font-size:12px; color:var(--ink); white-space:pre-wrap; }}
  .qa-value.empty {{ color:var(--muted); font-style:italic; }}

  /* ---------- Impact flags strip ---------- */
  .flagstrip {{ display:flex; gap:8px; padding:10px 12px; flex-wrap:wrap; }}
  .flagpill {{ display:inline-flex; align-items:center; gap:6px; font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:.6px; padding:4px 10px; border-radius:99px; border:1px solid var(--line); color:var(--muted); }}
  .flagpill.on {{ background:#fbe9eb; color:var(--red-dark); border-color:var(--red-dark); }}
  .flagpill .dot {{ width:8px; height:8px; border-radius:50%; background:var(--muted); }}
  .flagpill.on .dot {{ background:var(--red-dark); }}

  /* ---------- Sign-off blocks (mirrors DCR) ---------- */
  .signoff {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; padding:14px 12px; }}
  .sigbox {{ border-top:1.5px solid var(--black); padding-top:5px; }}
  .sigbox .role {{ font-size:8.5px; text-transform:uppercase; letter-spacing:.8px; color:var(--red); font-weight:700; }}
  .sigbox .nm {{ font-size:11px; font-weight:600; margin-top:14px; min-height:14px; }}
  .sigbox .d {{ font-size:10px; color:var(--muted); margin-top:4px; }}

  .foot {{ margin:16px 0.55in 0; border-top:2px solid var(--red); padding:7px 0 18px; display:flex; justify-content:space-between; font-size:8.5px; color:var(--muted); }}

  /* =========================================================
     PRINT / PDF — mirrors the DCR rules
     ========================================================= */
  @media print {{
    @page {{ size: Letter portrait; margin: 0.4in; }}
    html, body {{ background:#fff; }}
    .page {{ box-shadow:none; margin:0; width:auto; max-width:none; min-height:auto; box-sizing:border-box; }}
    .head {{ padding:14px 0.55in; box-sizing:border-box; }}
    .wrap {{ padding:0.25in 0.55in 0; }}
    .sec        {{ break-inside:avoid; page-break-inside:avoid; }}
    .sec > h2   {{ break-after:avoid;  page-break-after:avoid; }}
    .sec .body  {{ break-before:avoid; page-break-before:avoid; }}
    .qa-row     {{ break-inside:avoid; page-break-inside:avoid; }}
    .signoff    {{ break-inside:avoid; page-break-inside:avoid; }}
  }}
</style>
</head><body>
<div class="page">"""

    def _header_band(self) -> str:
        rfi_num = self.rfi.get('rfi_number') or '—'
        date_sub = self.rfi.get('date_submitted')
        return f"""<div class="head">
  <div class="brand">
    <div class="logo">{SUPERSTARS_STAR_SVG}</div>
    <div class="name">
      <h1>Superstars Contracting Inc.</h1>
      <div class="sub">Facade Restoration · New York City</div>
    </div>
  </div>
  <div class="docmeta">
    <div class="doctype">Request for Information</div>
    <div class="rid">{_esc(rfi_num)}</div>
    <div class="rid">{_esc(_fmt_long(date_sub))}</div>
  </div>
</div>
<div class="redbar"></div>"""

    def _footer(self) -> str:
        code = _esc(self.project.get('project_code') or '')
        return f"""<div class="foot">
  <div><span style="color:var(--red);">★</span> Superstars Contracting Inc. · Facade Restoration · New York City</div>
  <div>Project {code} · Generated {_esc(datetime.now().strftime('%Y-%m-%d %H:%M'))}</div>
</div></div>"""

    # ---------- Section 1 — Project + RFI identification ----------

    def _section_project_info(self) -> str:
        p = self.project
        r = self.rfi
        status = r.get('status_derived') or 'Open'
        # Build cells; the status cell renders the badge inline so the
        # operator sees the same visual signal as in the dashboard register.
        status_cell = (
            f'<div class="cell"><div class="k">Status</div>'
            f'<div class="v">{_status_badge_html(status)}</div></div>'
        )

        def cell(k, v, wide=False):
            cls = "cell wide" if wide else "cell"
            return (f'<div class="{cls}"><div class="k">{_esc(k)}</div>'
                    f'<div class="v">{_esc(v) or "—"}</div></div>')

        cells = [
            cell("RFI Number",            r.get('rfi_number')),
            status_cell,
            cell("Date Submitted",        _fmt_short(r.get('date_submitted'))),
            cell("Response Required By",  _fmt_short(r.get('date_response_required'))),
            cell("Project",               p.get('name'), wide=True),
            cell("Address",               p.get('address'), wide=True),
            cell("Client",                p.get('client') or '—'),
            cell("Superintendent",        p.get('superintendent') or '—'),
            cell("Submitted By",          r.get('submitted_by')),
            cell("Sent To",               r.get('sent_to')),
        ]
        return f"""<div class="sec">
  <h2><span><span class="n">1</span>Project &amp; RFI Information</span></h2>
  <div class="body"><div class="info" style="border:none;border-radius:0;margin:0;">
    {''.join(cells)}
  </div></div>
</div>"""

    # ---------- Section 2 — Subject + question + drawing/spec ref ----------

    def _section_subject_and_question(self) -> str:
        r = self.rfi

        def qa(label, value, empty_label="Not specified"):
            v = (value or '').strip() if isinstance(value, str) else value
            if not v:
                return (f'<div class="qa-row"><div class="qa-label">{_esc(label)}</div>'
                        f'<div class="qa-value empty">{_esc(empty_label)}</div></div>')
            return (f'<div class="qa-row"><div class="qa-label">{_esc(label)}</div>'
                    f'<div class="qa-value">{_esc(v)}</div></div>')

        return f"""<div class="sec">
  <h2><span><span class="n">2</span>Subject &amp; Question</span></h2>
  <div class="body">
    {qa("Subject", r.get("subject_title"))}
    {qa("Question", r.get("question_description"))}
    {qa("Drawing / Spec Reference", r.get("drawing_spec_reference"), empty_label="—")}
    {qa("Related Documents", r.get("related_documents"), empty_label="—")}
  </div>
</div>"""

    # ---------- Section 3 — Location + scope (the spine) ----------

    def _section_location_and_scope(self) -> str:
        r = self.rfi
        loc_unit = r.get('location_unit') or '—'
        loc_id   = r.get('location_id') or '—'
        scope    = r.get('scope_category') or '—'
        return f"""<div class="sec">
  <h2><span><span class="n">3</span>Location &amp; Scope</span></h2>
  <div class="body"><div class="info" style="border:none;border-radius:0;margin:0;">
    <div class="cell"><div class="k">Location Unit</div><div class="v">{_esc(loc_unit)}</div></div>
    <div class="cell wide"><div class="k">Location ID</div><div class="v">{_esc(loc_id)}</div></div>
    <div class="cell"><div class="k">Scope Category</div><div class="v">{_esc(scope)}</div></div>
  </div></div>
</div>"""

    # ---------- Section 4 — Impact flags + magnitude note ----------

    def _section_impact(self) -> str:
        r = self.rfi
        sched_on = 'on' if r.get('schedule_impact_flag') else ''
        cost_on  = 'on' if r.get('cost_impact_flag') else ''
        note = (r.get('impact_magnitude_note') or '').strip()
        note_html = (
            f'<div class="qa-row"><div class="qa-label">Impact Magnitude Note</div>'
            f'<div class="qa-value">{_esc(note)}</div></div>'
            if note else
            f'<div class="qa-row"><div class="qa-label">Impact Magnitude Note</div>'
            f'<div class="qa-value empty">—</div></div>'
        )
        return f"""<div class="sec">
  <h2><span><span class="n">4</span>Impact</span></h2>
  <div class="body">
    <div class="flagstrip">
      <span class="flagpill {sched_on}"><span class="dot"></span>Schedule Impact</span>
      <span class="flagpill {cost_on}"><span class="dot"></span>Cost Impact</span>
    </div>
    {note_html}
  </div>
</div>"""

    # ---------- Section 5 — Response (Answered/Overdue/Pending state) ----------

    def _section_response(self) -> str:
        r = self.rfi
        rcv = r.get('date_response_received')
        ans = (r.get('response_answer') or '').strip()
        turnaround = r.get('turnaround_days')
        meta = ''
        if rcv:
            ta = f' · turnaround {turnaround}d' if isinstance(turnaround, int) else ''
            meta = f'<span class="meta">Received {_esc(_fmt_short(rcv))}{_esc(ta)}</span>'
        body = (
            f'<div class="qa-row"><div class="qa-label">Response</div>'
            f'<div class="qa-value">{_esc(ans)}</div></div>'
            if ans else
            f'<div class="qa-row"><div class="qa-label">Response</div>'
            f'<div class="qa-value empty">Pending — awaiting reply</div></div>'
        )
        return f"""<div class="sec">
  <h2><span><span class="n">5</span>Response</span>{meta}</h2>
  <div class="body">{body}</div>
</div>"""

    # ---------- Section 6 — Sign-off blocks ----------

    def _section_signoff(self) -> str:
        r = self.rfi
        submitter = r.get('submitted_by') or ''
        sent_to   = r.get('sent_to') or ''
        date_sub  = _fmt_short(r.get('date_submitted'))
        date_rcv  = _fmt_short(r.get('date_response_received'))
        responder_name = _esc(sent_to) if r.get('response_answer') else '&nbsp;'
        return f"""<div class="sec">
  <h2><span><span class="n">6</span>Sign-off</span></h2>
  <div class="body">
    <div class="signoff">
      <div class="sigbox">
        <div class="role">Submitted By</div>
        <div class="nm">{_esc(submitter)}</div>
        <div class="d">Date: {_esc(date_sub)}</div>
      </div>
      <div class="sigbox">
        <div class="role">Responded By ({_esc(sent_to) or '—'})</div>
        <div class="nm">{responder_name}</div>
        <div class="d">Date: {_esc(date_rcv)}</div>
      </div>
    </div>
  </div>
</div>"""


def render_rfi_html(rfi: Dict[str, Any], project: Dict[str, Any]) -> str:
    """Module-level convenience — server.py imports this."""
    return RFIHTMLRenderer(rfi, project).render()
