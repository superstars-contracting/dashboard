#!/usr/bin/env python3
"""DCR HTML Renderer — handles both internal and client audiences."""
import argparse, json, sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

class DCRHTMLRenderer:
    BRAND_RED = "#B11E2E"
    CREAM = "#FAF7F1"

    def __init__(self, dcr_data: Dict[str, Any]):
        self.dcr = dcr_data
        self.audience = dcr_data.get('audience', 'internal')

    def render(self) -> str:
        if self.audience == 'client':
            return self.render_client()
        else:
            return self.render_internal()

    def render_internal(self) -> str:
        """Render internal DCR with full detail."""
        p = self.dcr['project']
        report_number = self.dcr.get('display_id') or self.dcr.get('report_id') or '—'
        html_parts = [self._head("Daily Construction Report"), self._header(), """
        <section class="content">
            <div class="section-header">1. PROJECT INFORMATION</div>
            <div class="project-grid">
                <div class="project-field"><label>Report Number</label><p>{}</p></div>
                <div class="project-field"><label>Code</label><p>{}</p></div>
                <div class="project-field"><label>Name</label><p>{}</p></div>
                <div class="project-field"><label>Address</label><p>{}</p></div>
                <div class="project-field"><label>Date</label><p>{} ({})</p></div>
                <div class="project-field"><label>Superintendent</label><p>{}</p></div>
                <div class="project-field"><label>PM</label><p>{}</p></div>
            </div>""".format(report_number, p.get('code'), p.get('name'), p.get('address'), p.get('date'), p.get('day_of_week'), p.get('superintendent'), p.get('project_manager')), self._labor_internal(), self._work_section(), self._materials_section(), self._equipment_section(), self._safety_section_internal(), self._issues_section_internal(), self._inspections_section(), self._visitors_section_internal(), self._photos_section(), self._signoff_section(), """
        </section>
        </body></html>"""]
        return ''.join(html_parts)

    def render_client(self) -> str:
        """Render client-facing DCR with redacted sensitive data."""
        p = self.dcr['project']
        report_number = self.dcr.get('display_id') or self.dcr.get('report_id') or '—'
        html_parts = [self._head("Daily Progress Report"), self._header(), """
        <section class="content">
            <div class="section-header">1. PROJECT INFORMATION</div>
            <div class="project-grid">
                <div class="project-field"><label>Report Number</label><p>{}</p></div>
                <div class="project-field"><label>Code</label><p>{}</p></div>
                <div class="project-field"><label>Name</label><p>{}</p></div>
                <div class="project-field"><label>Address</label><p>{}</p></div>
                <div class="project-field"><label>Date</label><p>{}</p></div>
            </div>""".format(report_number, p.get('code'), p.get('name'), p.get('address'), p.get('date')), self._labor_client(), self._work_section(), self._materials_section(), self._equipment_section(), self._safety_section_client(), self._issues_section_client(), self._inspections_section(), self._visitors_section_client(), self._photos_section(), self._signoff_section_client(), """
        </section>
        </body></html>"""]
        return ''.join(html_parts)

    def _head(self, title: str) -> str:
        return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        :root {{ color-scheme: light; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'DM Sans', -apple-system, sans-serif; background: {self.CREAM}; padding: 40px 20px; }}
        .header {{ background: #1a1a1a; color: {self.CREAM}; padding: 20px 40px; text-align: center; font-size: 28px; font-weight: bold; margin-bottom: 30px; }}
        .header-star {{ color: {self.BRAND_RED}; }}
        .content {{ max-width: 900px; margin: 0 auto; background: white; padding: 40px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .section-header {{ font-size: 16px; font-weight: bold; color: {self.BRAND_RED}; margin-top: 20px; margin-bottom: 12px; border-bottom: 2px solid {self.BRAND_RED}; padding-bottom: 8px; }}
        .project-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px; }}
        .project-field {{ }}
        .project-field label {{ display: block; font-weight: bold; color: {self.BRAND_RED}; font-size: 12px; margin-bottom: 4px; }}
        .project-field p {{ color: #333; }}
        table {{ width: 100%; border-collapse: collapse; margin-bottom: 15px; }}
        th {{ background: {self.BRAND_RED}; color: white; padding: 10px; text-align: left; font-weight: bold; }}
        td {{ border-bottom: 1px solid #eee; padding: 10px; }}
        tr:hover {{ background: {self.CREAM}; }}
        .footer {{ margin-top: 40px; font-size: 12px; color: #666; border-top: 1px solid #ddd; padding-top: 20px; }}
    </style>
</head>
<body>"""

    def _header(self) -> str:
        return f'<div class="header"><span class="header-star">★</span> Superstar Contracting</div>'

    def _labor_internal(self) -> str:
        labor = self.dcr.get('labor', {})
        rows = labor.get('rows', [])
        if not rows:
            return "<div class='section-header'>2. LABOR TRACKING</div><p>No sign-in data.</p>"
        html = "<div class='section-header'>2. LABOR TRACKING</div><table><tr><th>Employee</th><th>Trade</th><th>Time In</th><th>Time Out</th><th>Hours</th><th>Area</th></tr>"
        for row in rows:
            html += f"<tr><td>{row.get('name')}</td><td>{row.get('trade')}</td><td>{row.get('time_in')}</td><td>{row.get('time_out')}</td><td>{row.get('hours')}</td><td>{row.get('area', '')}</td></tr>"
        html += f"</table><p><strong>Headcount:</strong> {labor.get('headcount')} | <strong>Total Hours:</strong> {labor.get('total_hours')}</p>"
        return html

    def _labor_client(self) -> str:
        labor = self.dcr.get('labor', {})
        summary = labor.get('summary', {})
        by_trade = summary.get('by_trade', [])
        if not by_trade:
            return "<div class='section-header'>2. LABOR SUMMARY</div><p>No labor data available.</p>"
        html = "<div class='section-header'>2. LABOR SUMMARY</div><table><tr><th>Trade</th><th>Count</th><th>Hours</th></tr>"
        for item in by_trade:
            html += f"<tr><td>{item.get('trade')}</td><td>{item.get('count')}</td><td>{item.get('hours'):.2f}</td></tr>"
        site_open = summary.get('site_open')
        site_closed = summary.get('site_closed')
        html += f"</table><p><strong>Site Open:</strong> {site_open} | <strong>Site Closed:</strong> {site_closed}</p>"
        html += f"<p><strong>Headcount:</strong> {labor.get('headcount')} | <strong>Total Hours:</strong> {labor.get('total_hours')}</p>"
        return html

    def _work_section(self) -> str:
        work = self.dcr.get('work_performed', [])
        if not work:
            return "<div class='section-header'>3. WORK PERFORMED</div><p>No work logged.</p>"
        html = "<div class='section-header'>3. WORK PERFORMED</div><table><tr><th>Trade / Area</th><th>Location</th><th>Description</th></tr>"
        for w in work:
            html += f"<tr><td>{w.get('trade_area')}</td><td>{w.get('location_elevation')}</td><td>{w.get('description')}</td></tr>"
        html += "</table>"
        return html

    def _materials_section(self) -> str:
        mat = self.dcr.get('materials_deliveries', [])
        if not mat:
            return "<div class='section-header'>4. MATERIALS & DELIVERIES</div><p>No materials logged.</p>"
        html = "<div class='section-header'>4. MATERIALS & DELIVERIES</div><table><tr><th>Time</th><th>Material</th><th>Qty</th><th>Supplier</th></tr>"
        for m in mat:
            html += f"<tr><td>{m.get('time')}</td><td>{m.get('material')}</td><td>{m.get('qty')} {m.get('unit')}</td><td>{m.get('supplier')}</td></tr>"
        html += "</table>"
        return html

    def _equipment_section(self) -> str:
        equip = self.dcr.get('equipment', [])
        if not equip:
            return "<div class='section-header'>5. EQUIPMENT ON SITE</div><p>No equipment logged.</p>"
        html = "<div class='section-header'>5. EQUIPMENT ON SITE</div><table><tr><th>Equipment</th><th>Owner</th><th>Hours Used</th><th>Issues</th></tr>"
        for e in equip:
            html += f"<tr><td>{e.get('equipment')}</td><td>{e.get('owner')}</td><td>{e.get('hours_used')}</td><td>{e.get('issues', '')}</td></tr>"
        html += "</table>"
        return html

    def _safety_section_internal(self) -> str:
        safety = self.dcr.get('safety', {})
        talk = safety.get('toolbox_talk')
        events = safety.get('events', [])
        html = "<div class='section-header'>6. SAFETY</div>"
        if talk:
            html += f"<p><strong>Toolbox Talk:</strong> {talk.get('topic')} (conducted by {talk.get('conducted_by')})</p>"
        else:
            html += "<p><strong>Toolbox Talk:</strong> Not conducted</p>"
        if events:
            html += "<table><tr><th>Type</th><th>Time</th><th>Person</th><th>Description</th></tr>"
            for ev in events:
                html += f"<tr><td>{ev.get('type')}</td><td>{ev.get('time')}</td><td>{ev.get('person')}</td><td>{ev.get('description')}</td></tr>"
            html += "</table>"
        else:
            html += "<p>No safety events reported.</p>"
        return html

    def _safety_section_client(self) -> str:
        safety = self.dcr.get('safety', {})
        talk = safety.get('toolbox_talk')
        events = safety.get('events', [])
        html = "<div class='section-header'>6. SAFETY</div>"
        if talk:
            html += f"<p><strong>Toolbox Talk Conducted:</strong> Yes — Topic: {talk.get('topic')}</p>"
        else:
            html += "<p><strong>Toolbox Talk Conducted:</strong> No</p>"
        if events:
            html += f"<p><strong>Incidents:</strong> {len(events)} — under review by site supervisor</p>"
        else:
            html += "<p><strong>Incidents:</strong> 0</p>"
        return html

    def _issues_section_internal(self) -> str:
        issues = self.dcr.get('issues_delays', [])
        if not issues:
            return "<div class='section-header'>7. ISSUES / DELAYS</div><p>No issues logged.</p>"
        html = "<div class='section-header'>7. ISSUES / DELAYS</div><table><tr><th>Category</th><th>Description</th><th>Time Lost</th><th>Owner</th></tr>"
        for i in issues:
            html += f"<tr><td>{i.get('category')}</td><td>{i.get('description')}</td><td>{i.get('time_lost_hrs')} hrs</td><td>{i.get('owner')}</td></tr>"
        html += "</table>"
        return html

    def _issues_section_client(self) -> str:
        issues = self.dcr.get('issues_delays', [])
        if not issues:
            return "<div class='section-header'>7. ISSUES / DELAYS</div><p>No issues reported.</p>"
        html = "<div class='section-header'>7. ISSUES / DELAYS</div><table><tr><th>Category</th><th>Status</th></tr>"
        for i in issues:
            html += f"<tr><td>{i.get('category')}</td><td>{i.get('summary', 'Under review')}</td></tr>"
        html += "</table>"
        return html

    def _inspections_section(self) -> str:
        insp = self.dcr.get('inspections', [])
        if not insp:
            return "<div class='section-header'>8. INSPECTIONS</div><p>No inspections scheduled.</p>"
        html = "<div class='section-header'>8. INSPECTIONS</div><table><tr><th>Type</th><th>Inspector</th><th>Area</th><th>Result</th></tr>"
        for i in insp:
            html += f"<tr><td>{i.get('type')}</td><td>{i.get('inspector')}</td><td>{i.get('area')}</td><td>{i.get('result')}</td></tr>"
        html += "</table>"
        return html

    def _visitors_section_internal(self) -> str:
        visitors = self.dcr.get('visitors', [])
        if not visitors:
            return "<div class='section-header'>9. VISITORS</div><p>No visitors recorded.</p>"
        html = "<div class='section-header'>9. VISITORS</div><table><tr><th>Name</th><th>Company</th><th>Role</th><th>Time In</th><th>Time Out</th><th>Purpose</th></tr>"
        for v in visitors:
            html += f"<tr><td>{v.get('name') or '—'}</td><td>{v.get('company') or '—'}</td><td>{v.get('role') or '—'}</td><td>{v.get('time_in') or '—'}</td><td>{v.get('time_out') or '—'}</td><td>{v.get('purpose') or '—'}</td></tr>"
        html += "</table>"
        return html

    def _visitors_section_client(self) -> str:
        visitors = self.dcr.get('visitors') or {}
        if not isinstance(visitors, dict):
            visitors = {}
        by_role = visitors.get('count_by_role', [])
        total = visitors.get('total_visits', 0)
        if not by_role and not total:
            return "<div class='section-header'>9. VISITORS</div><p>No visitors recorded.</p>"
        html = "<div class='section-header'>9. VISITORS</div><table><tr><th>Role</th><th>Visits</th></tr>"
        for item in by_role:
            html += f"<tr><td>{item.get('role')}</td><td>{item.get('count')}</td></tr>"
        html += f"</table><p><strong>Total visits:</strong> {total}</p>"
        return html

    def _photos_section(self) -> str:
        photos = self.dcr.get('photos', [])
        if not photos:
            return "<div class='section-header'>10. PHOTOS</div><p>No photos available.</p>"
        html = "<div class='section-header'>10. PHOTOS</div>"
        for p in photos[:6]:
            html += f"<p><strong>{p.get('location')}</strong><br>{p.get('description')}</p>"
        html += "</div>"
        return html

    def _signoff_section(self) -> str:
        signoff = self.dcr.get('signoff', {})
        return f"""<div class='section-header'>11. SIGN-OFF</div>
        <p><strong>Superintendent:</strong> {signoff.get('superintendent_name')} ___________________</p>
        <p><strong>Project Manager:</strong> {signoff.get('pm_name')} ___________________</p>
        <div class='footer'>Report generated {signoff.get('time_signed')}</div>"""

    def _signoff_section_client(self) -> str:
        signoff = self.dcr.get('signoff', {})
        return f"""<div class='section-header'>11. SIGN-OFF</div>
        <p><strong>Project Superintendent:</strong> {signoff.get('superintendent_name')}</p>
        <p><strong>Project Manager:</strong> {signoff.get('pm_name')}</p>
        <div class='footer'>This report is provided to the building owner / managing agent. For full project records, contact your project manager.</div>"""

def main():
    parser = argparse.ArgumentParser(description='Render DCR JSON to HTML')
    parser.add_argument('input_json', help='Input DCR JSON file')
    parser.add_argument('output_html', help='Output HTML file')
    args = parser.parse_args()
    try:
        with open(args.input_json, 'r', encoding='utf-8') as f:
            dcr = json.load(f)
        renderer = DCRHTMLRenderer(dcr)
        html = renderer.render()
        with open(args.output_html, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"HTML rendered: {args.output_html}", file=sys.stderr)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
