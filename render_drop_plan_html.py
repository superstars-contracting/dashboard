#!/usr/bin/env python3
import json
import sys
from datetime import datetime
from typography import get_inlined_style_tag

def render_html(json_path, output_path):
    with open(json_path) as f:
        data = json.load(f)
    
    status_colors = {
        'Active': '#FFA500',
        'Planned': '#9CA3AF',
        'Pending Sign-Off': '#FFA500',
        'Signed Off': '#10B981',
        'Work Complete': '#10B981',
        'Mobilizing': '#3B82F6',
        'Demobilized': '#6B7280',
    }
    
    status_color = status_colors.get(data['status'], '#9CA3AF')
    
    crew_html = ''
    if data['crew_members']:
        crew_html = ''.join([
            f"<div style='padding: 8px 0; border-bottom: 1px solid #E5E7EB;'>"
            f"<div style='font-weight: 600; font-size: 13px;'>{m['name']}</div>"
            f"<div style='font-size: 12px; color: #666;'>{m['trade']}</div>"
            f"</div>"
            for m in data['crew_members']
        ])
    else:
        crew_html = "<div style='color: #999; font-style: italic;'>TBD</div>"
    
    drawings_html = ''
    if data['drawing_references']:
        drawings_html = ''.join([
            f"<div style='padding: 8px 0; border-bottom: 1px solid #E5E7EB;'>"
            f"<div style='font-weight: 600; font-size: 13px;'>{d['id']}</div>"
            f"<div style='font-size: 12px; color: #666;'>{d['title']}</div>"
            f"<div style='font-size: 11px; color: #999;'>v{d['version']}</div>"
            f"</div>"
            for d in data['drawing_references']
        ])
    
    sign_off_rows = ''
    for role in data['sign_off_required']:
        received = role in data['sign_off_progress']['received']
        bg_color = '#ECFDF5' if received else '#FFFBEB'
        date_val = data['sign_off_dates'].get(role.lower().replace(' ', '_'), '')
        date_str = date_val if date_val else 'Pending'
        
        sign_off_rows += f"""
        <tr style='background-color: {bg_color};'>
            <td style='padding: 10px; border-bottom: 1px solid #E5E7EB; font-weight: 600;'>{role}</td>
            <td style='padding: 10px; border-bottom: 1px solid #E5E7EB;'>{date_str if received else '-'}</td>
            <td style='padding: 10px; border-bottom: 1px solid #E5E7EB;'>
                <span style='display: inline-block; width: 8px; height: 8px; border-radius: 50%; background-color: {"#10B981" if received else "#FCA5A5"};'></span>
            </td>
        </tr>
        """
    
    photo_pct = int((data['photos_captured'] / data['photos_required']) * 100) if data['photos_required'] else 0
    
    pred_html = ''
    if data['predecessor_drops']:
        pred_html = ', '.join(data['predecessor_drops'])
    else:
        pred_html = 'None'
    
    succ_html = ''
    if data['successor_drops']:
        succ_html = ', '.join(data['successor_drops'])
    else:
        succ_html = 'None'
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    {get_inlined_style_tag()}
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Drop Plan {data['drop_id']}</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background: #FAF7F1; color: #14161C; line-height: 1.6; }}
        @page {{ margin: 0.5in; size: letter portrait; }}
        @media print {{
            body {{ background: white; }}
            .no-print {{ display: none; }}
        }}
        .container {{ max-width: 8.5in; margin: 0 auto; background: white; padding: 0.5in; }}
        .letterhead {{ display: flex; justify-content: space-between; align-items: flex-start; border-bottom: 3px solid #B11E2E; padding-bottom: 0.3in; margin-bottom: 0.3in; }}
        .letterhead-left {{ flex: 1; }}
        .letterhead-star {{ font-size: 24px; }}
        .company-name {{ font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 16px; font-weight: 700; color: #B11E2E; margin-top: 4px; }}
        .company-addr {{ font-size: 9px; color: #666; margin-top: 4px; line-height: 1.3; }}
        .letterhead-right {{ text-align: right; }}
        .doc-title {{ font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 24px; color: #B11E2E; }}
        .doc-subtitle {{ font-size: 13px; color: #666; margin-top: 4px; }}
        .status-badge {{ display: inline-block; padding: 4px 12px; border-radius: 3px; font-size: 11px; font-weight: 600; margin-top: 6px; background-color: {status_color}; color: white; }}
        h2 {{ font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 20px; margin-top: 0.2in; margin-bottom: 0.15in; padding-bottom: 0.1in; border-bottom: 2px solid #E5E7EB; }}
        h3 {{ font-size: 13px; font-weight: 600; color: #B11E2E; margin-top: 0.15in; margin-bottom: 0.08in; text-transform: uppercase; letter-spacing: 1px; }}
        .meta-strip {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 0.15in; margin-bottom: 0.2in; }}
        .meta-box {{ background: #F3F4F6; padding: 0.12in; border-left: 3px solid #B11E2E; }}
        .meta-label {{ font-size: 9px; color: #666; text-transform: uppercase; font-weight: 600; }}
        .meta-value {{ font-size: 14px; font-weight: 600; color: #14161C; margin-top: 3px; }}
        .scope-box {{ background: #FAF7F1; padding: 0.15in; border-left: 4px solid #B11E2E; margin-bottom: 0.15in; font-style: italic; font-size: 12px; line-height: 1.5; }}
        .grid-3 {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 0.15in; margin-bottom: 0.2in; }}
        .card {{ background: #F9FAFB; padding: 0.12in; border: 1px solid #E5E7EB; }}
        .card-title {{ font-size: 10px; font-weight: 600; color: #B11E2E; text-transform: uppercase; margin-bottom: 6px; }}
        .card-item {{ font-size: 11px; margin: 4px 0; line-height: 1.4; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 11px; margin-bottom: 0.15in; }}
        th {{ background: #F3F4F6; padding: 8px; text-align: left; font-weight: 600; border-bottom: 2px solid #E5E7EB; }}
        td {{ padding: 8px; border-bottom: 1px solid #E5E7EB; }}
        .photo-bar {{ background: #E5E7EB; height: 8px; border-radius: 2px; overflow: hidden; }}
        .photo-fill {{ background: #10B981; height: 100%; width: {photo_pct}%; }}
        .signature-line {{ border-top: 1px solid #14161C; height: 0.4in; }}
        .sig-block {{ display: inline-block; width: 1.5in; margin-right: 0.3in; font-size: 10px; }}
        .sig-name {{ margin-top: 4px; font-weight: 600; }}
        .sig-date {{ margin-top: 2px; color: #666; }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Letterhead -->
        <div class="letterhead">
            <div class="letterhead-left">
                <div class="letterhead-star">★</div>
                <div class="company-name">SUPERSTARS CONTRACTING</div>
                <div class="company-addr">
                    890 East 135th Street<br>
                    Bronx, NY 10454
                </div>
            </div>
            <div class="letterhead-right">
                <div class="doc-title">Drop Plan</div>
                <div class="doc-subtitle">{data['drop_id']} · {data['project_code']}</div>
                <div class="status-badge">{data['status']}</div>
            </div>
        </div>

        <!-- Drop Header -->
        <div style="margin-bottom: 0.25in;">
            <div style="font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 32px; font-weight: 700; color: #14161C;">{data['drop_id']}</div>
            <div style="font-size: 13px; color: #666; margin-top: 4px;">{data['elevation']} Elevation · Bay {data['bay_range']} · Floors {data['floor_range']}</div>
        </div>

        <!-- Meta Strip -->
        <div class="meta-strip">
            <div class="meta-box">
                <div class="meta-label">Planned Start</div>
                <div class="meta-value">{data['planned_start'] or 'TBD'}</div>
            </div>
            <div class="meta-box">
                <div class="meta-label">Planned End</div>
                <div class="meta-value">{data['planned_end'] or 'TBD'}</div>
            </div>
            <div class="meta-box">
                <div class="meta-label">Crew Size</div>
                <div class="meta-value">{data['crew_size']} people</div>
            </div>
            <div class="meta-box">
                <div class="meta-label">Days Remaining</div>
                <div class="meta-value">{data['days_remaining'] if data['days_remaining'] is not None else '-'}</div>
            </div>
        </div>

        <!-- Scope -->
        <h2>Scope of Work</h2>
        <div class="scope-box">{data['scope_of_work']}</div>

        <!-- Trades, Equipment, Materials -->
        <h2>Resources</h2>
        <div class="grid-3">
            <div class="card">
                <div class="card-title">Trades Required</div>
                {"".join([f"<div class='card-item'>• {t}</div>" for t in data['trades_required']])}
            </div>
            <div class="card">
                <div class="card-title">Equipment</div>
                {"".join([f"<div class='card-item'>• {e}</div>" for e in data['equipment_required']])}
            </div>
            <div class="card">
                <div class="card-title">Materials</div>
                {"".join([f"<div class='card-item'>• {m}</div>" for m in data['materials_required']])}
            </div>
        </div>

        <!-- Crew -->
        <h2>Crew Assignment</h2>
        {crew_html}

        <!-- Drawing References -->
        <h2>Drawing References</h2>
        {drawings_html if drawings_html else '<div style="color: #999; font-style: italic;">None</div>'}

        <!-- Sign-Off Workflow -->
        <h2>Sign-Off Status</h2>
        <table>
            <tr>
                <th>Role</th>
                <th>Signed</th>
                <th>Status</th>
            </tr>
            {sign_off_rows}
        </table>

        <!-- Photos -->
        <h2>Photo Documentation</h2>
        <div style="margin-bottom: 0.1in;">
            <div style="font-size: 12px; font-weight: 600; margin-bottom: 4px;">Photos Captured: {data['photos_captured']} of {data['photos_required']}</div>
            <div class="photo-bar">
                <div class="photo-fill"></div>
            </div>
        </div>
        <div style="font-size: 10px; color: #666; line-height: 1.5;">
            Expected categories: Before photos · Mid-progress · After completion · Detail shots · Certifications
        </div>

        <!-- Sequencing -->
        <h2>Drop Sequencing</h2>
        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.15in; font-size: 11px;">
            <div style="background: #F9FAFB; padding: 0.1in; border: 1px solid #E5E7EB;">
                <div style="font-weight: 600; color: #B11E2E; margin-bottom: 4px;">Predecessor Drops</div>
                <div>{pred_html}</div>
            </div>
            <div style="background: #F9FAFB; padding: 0.1in; border: 1px solid #E5E7EB;">
                <div style="font-weight: 600; color: #B11E2E; margin-bottom: 4px;">Successor Drops</div>
                <div>{succ_html}</div>
            </div>
        </div>

        <!-- Notes -->
        {"" if not data['notes'] else f'''
        <h2>Notes</h2>
        <div style="font-size: 11px; line-height: 1.6; background: #FFFBEB; padding: 0.1in; border-left: 3px solid #FCA5A5;">
            {data['notes']}
        </div>
        '''}

        <!-- Signature Block -->
        <div style="margin-top: 0.3in; page-break-inside: avoid;">
            <h2>Authorization</h2>
            <div style="display: flex; justify-content: space-between; font-size: 10px;">
                <div class="sig-block">
                    <div class="signature-line"></div>
                    <div class="sig-name">Foreman</div>
                    <div class="sig-date">{data['sign_off_dates'].get('foreman', '')}</div>
                </div>
                <div class="sig-block">
                    <div class="signature-line"></div>
                    <div class="sig-name">Superintendent</div>
                    <div class="sig-date">{data['sign_off_dates'].get('superintendent', '')}</div>
                </div>
                <div class="sig-block">
                    <div class="signature-line"></div>
                    <div class="sig-name">QEI</div>
                    <div class="sig-date">{data['sign_off_dates'].get('qei', '')}</div>
                </div>
                <div class="sig-block">
                    <div class="signature-line"></div>
                    <div class="sig-name">Owner Rep</div>
                    <div class="sig-date">{data['sign_off_dates'].get('owner_rep', '')}</div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
"""
    
    with open(output_path, 'w') as f:
        f.write(html)
    
    print(f"Rendered {output_path}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: render_drop_plan_html.py <json_path> <output_html_path>")
        sys.exit(1)
    render_html(sys.argv[1], sys.argv[2])
