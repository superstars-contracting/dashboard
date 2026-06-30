#!/usr/bin/env python3
"""Site Closure HTML Renderer."""
import argparse, json, sys
from pathlib import Path
from typing import Any, Dict, List
from typography import get_inlined_style_tag
import brand  # #265 — canonical logo

class ClosureHTMLRenderer:
    BRAND_RED = "#B11E2E"
    INK = "#14161C"
    CREAM = "#FAF7F1"
    WHITE = "#FFFFFF"
    MUTE = "#94908D"
    GREEN = "#22C55E"

    def __init__(self, closure_data: Dict[str, Any]):
        self.data = closure_data

    def render(self) -> str:
        parts = [
            self._head(),
            self._header(),
            self._closure_stats(),
            self._project_info(),
            self._checklist_section(),
            self._equipment_section(),
            self._notes_section(),
            self._signoff(),
            '</body></html>'
        ]
        return ''.join(parts)

    def _head(self) -> str:
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    {get_inlined_style_tag()}
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Site Closure Record</title>
    <style>
        :root {{ color-scheme: light; }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: {self.CREAM}; padding: 40px 20px; color: {self.INK}; }}
        .page {{ max-width: 900px; margin: 0 auto; background: {self.WHITE}; box-shadow: 0 2px 12px rgba(0,0,0,0.08); }}
        .letterhead {{ background: {self.INK}; color: {self.WHITE}; padding: 24px 40px; display: flex; align-items: center; justify-content: space-between; border-bottom: 4px solid {self.BRAND_RED}; }}
        .letterhead-left {{ display: flex; align-items: center; gap: 12px; }}
        .star {{ font-size: 28px; color: {self.BRAND_RED}; }}
        .brand-name {{ font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 20px; font-weight: bold; color: {self.WHITE}; }}
        .letterhead-right {{ text-align: right; }}
        .doc-title {{ font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 18px; font-weight: 600; color: {self.INK}; margin-bottom: 4px; }}
        .doc-id {{ font-size: 12px; color: {self.MUTE}; text-transform: uppercase; letter-spacing: 0.5px; }}
        .content {{ padding: 40px; }}
        .stats-row {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 24px; margin-bottom: 36px; padding-bottom: 24px; border-bottom: 1px solid #e5e2dd; }}
        .stat-item {{ text-align: center; }}
        .stat-value {{ font-size: 28px; font-weight: bold; color: {self.INK}; margin-bottom: 4px; }}
        .stat-label {{ font-size: 12px; color: {self.MUTE}; text-transform: uppercase; letter-spacing: 0.5px; }}
        .stat-badge {{ display: inline-block; margin-top: 6px; padding: 4px 12px; border-radius: 12px; background: {self.CREAM}; font-size: 11px; font-weight: 600; }}
        .stat-badge.green {{ background: {self.GREEN}; color: {self.WHITE}; }}
        .project-info {{ display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 36px; padding-bottom: 24px; border-bottom: 1px solid #e5e2dd; }}
        .info-field {{ }}
        .info-label {{ font-size: 10px; color: {self.MUTE}; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; margin-bottom: 6px; }}
        .info-value {{ font-size: 13px; color: {self.INK}; line-height: 1.4; }}
        .checklist-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 32px; margin-bottom: 36px; }}
        .section {{ }}
        .section-title {{ display: flex; align-items: center; gap: 8px; font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 14px; font-weight: 600; color: {self.INK}; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 2px solid {self.BRAND_RED}; }}
        .rule-mark {{ width: 4px; height: 4px; background: {self.BRAND_RED}; border-radius: 2px; }}
        .section-warning {{ background: #FEF3C7; padding: 4px 8px; border-radius: 4px; font-size: 10px; color: #92400E; font-weight: 600; margin-left: auto; }}
        .checklist-item {{ display: flex; align-items: flex-start; gap: 10px; margin-bottom: 10px; font-size: 12px; }}
        .item-icon {{ width: 18px; height: 18px; border-radius: 3px; display: flex; align-items: center; justify-content: center; font-weight: bold; flex-shrink: 0; }}
        .icon-complete {{ background: {self.GREEN}; color: {self.WHITE}; }}
        .icon-incomplete {{ background: #EF4444; color: {self.WHITE}; }}
        .icon-na {{ background: #D1D5DB; color: {self.WHITE}; }}
        .item-label {{ color: {self.INK}; }}
        .na-badge {{ display: inline-block; margin-left: 8px; padding: 2px 6px; background: {self.MUTE}; color: {self.WHITE}; border-radius: 3px; font-size: 10px; font-weight: 600; }}
        .equipment-section {{ margin-bottom: 36px; padding-bottom: 24px; border-bottom: 1px solid #e5e2dd; }}
        .section-header {{ font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 14px; font-weight: 600; color: {self.INK}; margin-bottom: 12px; }}
        .equipment-text {{ font-size: 12px; color: {self.INK}; line-height: 1.6; white-space: pre-wrap; }}
        .notes-section {{ margin-bottom: 36px; padding-bottom: 24px; border-bottom: 1px solid #e5e2dd; }}
        .notes-text {{ font-size: 12px; color: {self.INK}; line-height: 1.6; white-space: pre-wrap; font-style: italic; color: {self.MUTE}; }}
        .notes-text.filled {{ font-style: normal; color: {self.INK}; }}
        .signoff {{ margin-top: 36px; }}
        .signoff-label {{ font-size: 10px; color: {self.MUTE}; text-transform: uppercase; letter-spacing: 0.5px; font-weight: 600; margin-bottom: 8px; }}
        .signoff-value {{ font-size: 13px; color: {self.INK}; margin-bottom: 20px; }}
        .timestamp-display {{ font-size: 14px; font-weight: bold; color: {self.INK}; margin-bottom: 16px; }}
        .footer-note {{ font-size: 11px; color: {self.MUTE}; text-align: center; padding-top: 20px; border-top: 1px solid #e5e2dd; font-style: italic; }}
    </style>
</head>
<body>
<div class="page">
"""

    def _header(self) -> str:
        closure = self.data.get('closure', {})
        return f"""<div class="letterhead">
    <div class="letterhead-left">
        <div class="star">{brand.star_svg(px=28)}</div>
        <div class="brand-name">SUPERSTARS CONTRACTING</div>
    </div>
    <div class="letterhead-right">
        <div class="doc-title">Site Closure Record</div>
        <div class="doc-id">{self.data.get('closure_id')} · {closure.get('date')}</div>
    </div>
</div>
<div class="content">
"""

    def _closure_stats(self) -> str:
        closure = self.data.get('closure', {})
        summary = self.data.get('checklist', {}).get('summary', {})
        total = summary.get('total_items', 0)
        completed = summary.get('completed_items', 0)
        na = summary.get('na_items', 0)
        completion = summary.get('completion_pct', 0)

        status_badge = f'<span class="stat-badge green">✓ Closure Complete</span>' if completion == 100 else '<span class="stat-badge">Incomplete</span>'
        na_note = f' ({na} N/A)' if na > 0 else ''

        return f"""<div class="stats-row">
    <div class="stat-item">
        <div class="stat-value">{closure.get('date', '')}</div>
        <div class="stat-label">{closure.get('day_of_week', '')}</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{closure.get('time_of_close', '')}</div>
        <div class="stat-label">Time of Close</div>
    </div>
    <div class="stat-item">
        <div class="stat-value">{completed}</div>
        <div class="stat-label">of {total} items{na_note}</div>
        {status_badge}
    </div>
</div>
"""

    def _project_info(self) -> str:
        project = self.data.get('project', {})
        closure = self.data.get('closure', {})
        foreman = closure.get('foreman', {})

        return f"""<div class="project-info">
    <div class="info-field">
        <div class="info-label">Project Name</div>
        <div class="info-value">{project.get('name', '')}</div>
    </div>
    <div class="info-field">
        <div class="info-label">Project Address</div>
        <div class="info-value">{project.get('address', '')}</div>
    </div>
    <div class="info-field">
        <div class="info-label">Site Type</div>
        <div class="info-value">{project.get('site_type', '')}</div>
    </div>
    <div class="info-field">
        <div class="info-label">Foreman</div>
        <div class="info-value">{foreman.get('name', '')} · {foreman.get('trade', '')}</div>
    </div>
    <div class="info-field" style="grid-column: 1;">
        <div class="info-label">Weather at Close</div>
        <div class="info-value">{closure.get('weather_at_close', '')}</div>
    </div>
</div>
"""

    def _checklist_section(self) -> str:
        sections = self.data.get('checklist', {}).get('sections', [])
        html = '<div class="checklist-grid">'

        col = 0
        for section in sections:
            if col == 2:
                html += '</div><div class="checklist-grid">'
                col = 0

            has_incomplete = any(item['status'] == 'incomplete' for item in section.get('items', []))
            warning_badge = '<span class="section-warning">⚠ Incomplete</span>' if has_incomplete else ''

            html += f"""<div class="section">
    <div class="section-title">
        <span class="rule-mark"></span>
        {section.get('name', '')}
        {warning_badge}
    </div>
"""

            for item in section.get('items', []):
                status = item.get('status', 'na')
                if status == 'completed':
                    icon_html = '<span class="item-icon icon-complete">✓</span>'
                elif status == 'incomplete':
                    icon_html = '<span class="item-icon icon-incomplete">✗</span>'
                else:
                    icon_html = '<span class="item-icon icon-na">◯</span>'

                na_badge = '<span class="na-badge">N/A</span>' if status == 'na' else ''
                html += f"""    <div class="checklist-item">
        {icon_html}
        <span class="item-label">{item.get('label', '')}{na_badge}</span>
    </div>
"""

            html += '</div>'
            col += 1

        html += '</div>'
        return html

    def _equipment_section(self) -> str:
        closure = self.data.get('closure', {})
        equipment = closure.get('equipment_left_overnight', 'None')

        return f"""<div class="equipment-section">
    <div class="section-header">Equipment Left Overnight</div>
    <div class="equipment-text">{equipment}</div>
</div>
"""

    def _notes_section(self) -> str:
        notes = self.data.get('notes', '')
        notes_html = notes if notes else 'No additional notes.'
        note_class = 'filled' if notes else ''

        return f"""<div class="notes-section">
    <div class="section-header">Notes & Comments</div>
    <div class="notes-text {note_class}">{notes_html}</div>
</div>
"""

    def _signoff(self) -> str:
        closure = self.data.get('closure', {})
        foreman = closure.get('foreman', {})
        timestamp = self.data.get('signed_timestamp', '')

        return f"""<div class="signoff">
    <div class="signoff-label">Signed By</div>
    <div class="signoff-value">{foreman.get('name', '')}</div>
    <div class="timestamp-display">{timestamp}</div>
    <div class="footer-note">Archived for project records. Not distributed.</div>
</div>
"""

def main():
    parser = argparse.ArgumentParser(description='Render Site Closure HTML')
    parser.add_argument('json_path', help='Input JSON file')
    parser.add_argument('output_html', help='Output HTML file')

    args = parser.parse_args()

    with open(args.json_path, 'r') as f:
        data = json.load(f)

    renderer = ClosureHTMLRenderer(data)
    html = renderer.render()

    Path(args.output_html).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_html, 'w') as f:
        f.write(html)

    print(f"Rendered: {args.output_html}")

if __name__ == '__main__':
    main()
