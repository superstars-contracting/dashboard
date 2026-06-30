#!/usr/bin/env python3
"""
Renders Weekly Progress Summary JSON to HTML using DCR letterhead protocol.
"""

import json
import sys
from datetime import datetime
from typography import get_inlined_style_tag
import brand  # #265 — canonical logo

def render_html(json_path, output_path):
    with open(json_path) as f:
        data = json.load(f)
    
    audience = data.get('audience', 'internal')
    is_internal = audience == 'internal'
    
    # Build HTML with proper escaping
    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    {get_inlined_style_tag()}
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Weekly Progress Summary - {data['project']['code']}</title>
    <style>
        :root {{
            --ink: #14161C;
            --red: #B11E2E;
            --cream: #FAF7F1;
            --white: #FFFFFF;
            --border: #E8E4DD;
            --mute: #8B8B8B;
        }}
        
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: var(--cream);
            color: var(--ink);
            line-height: 1.5;
        }}
        
        .page {{
            max-width: 8.5in;
            height: 11in;
            margin: 0.5in auto;
            background: var(--white);
            box-shadow: 0 0 8px rgba(0,0,0,0.1);
            padding: 0.5in;
            page-break-after: always;
            position: relative;
        }}
        
        .page::before {{
            content: "★";
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            font-size: 20rem;
            opacity: 0.08;
            color: var(--red);
            z-index: 0;
            pointer-events: none;
        }}
        
        .content {{ position: relative; z-index: 1; }}
        
        .letterhead {{
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 1rem;
            padding-bottom: 1rem;
            border-bottom: 2px solid var(--red);
            margin-bottom: 1rem;
        }}
        
        .letterhead-left {{
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }}
        
        .star-logo {{ font-size: 2rem; }}
        
        .letterhead-text h1 {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--ink);
            line-height: 1.1;
        }}
        
        .letterhead-text p {{
            font-size: 0.75rem;
            color: var(--mute);
            margin-top: 0.25rem;
        }}
        
        .letterhead-right {{
            text-align: right;
            border-left: 2px solid var(--border);
            padding-left: 1rem;
        }}
        
        .letterhead-right h2 {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 1.3rem;
            font-weight: 600;
            color: var(--red);
            margin-bottom: 0.5rem;
        }}
        
        .letterhead-right p {{
            font-size: 0.8rem;
            color: var(--mute);
            line-height: 1.4;
        }}
        
        .section {{
            margin-bottom: 1.5rem;
            page-break-inside: avoid;
        }}
        
        .section-title {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--ink);
            padding-top: 0.5rem;
            margin-bottom: 0.8rem;
            position: relative;
            padding-left: 0.5rem;
        }}
        
        .section-title::before {{
            content: "";
            position: absolute;
            top: 0;
            left: 0;
            width: 32px;
            height: 2px;
            background: var(--red);
        }}
        
        .eyebrow {{
            font-size: 0.65rem;
            font-weight: 700;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: var(--mute);
            margin-bottom: 0.3rem;
        }}
        
        .exec-summary {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 1.5rem;
            align-items: start;
        }}
        
        .hero-number {{
            text-align: center;
            padding: 2rem 1rem;
            background: linear-gradient(135deg, var(--red) 0%, #8B0A1A 100%);
            color: white;
            border-radius: 4px;
        }}
        
        .hero-number .number {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 3rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }}
        
        .hero-number .label {{
            font-size: 0.85rem;
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }}
        
        .highlights ul {{
            list-style: none;
        }}
        
        .highlights li {{
            padding: 0.5rem 0;
            padding-left: 1.5rem;
            position: relative;
            font-size: 0.9rem;
        }}
        
        .highlights li::before {{
            content: "•";
            position: absolute;
            left: 0;
            color: var(--red);
        }}
        
        .badge {{
            display: inline-block;
            padding: 0.3rem 0.6rem;
            border-radius: 3px;
            font-size: 0.75rem;
            font-weight: 600;
            text-transform: uppercase;
            margin-right: 0.5rem;
        }}
        
        .badge.success {{ background: #D4EDDA; color: #155724; }}
        .badge.warning {{ background: #FFF3CD; color: #856404; }}
        .badge.info {{ background: #D1ECF1; color: #0C5460; }}
        
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 0.85rem;
            margin-top: 0.8rem;
        }}
        
        thead {{
            background: var(--cream);
            border-bottom: 1px solid var(--border);
        }}
        
        th {{
            text-align: left;
            padding: 0.6rem;
            font-weight: 600;
            color: var(--ink);
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
        }}
        
        td {{
            padding: 0.6rem;
            border-bottom: 1px solid var(--border);
        }}
        
        .trade-row {{
            display: grid;
            grid-template-columns: 150px 1fr 80px;
            gap: 1rem;
            padding: 0.5rem 0;
            border-bottom: 1px solid var(--border);
            align-items: center;
        }}
        
        .trade-bar {{
            background: var(--cream);
            height: 20px;
            border-radius: 2px;
            overflow: hidden;
        }}
        
        .trade-fill {{
            height: 100%;
            background: var(--red);
        }}
        
        .trade-hours {{ font-family: "Courier New", monospace; text-align: right; }}
        
        .stat-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
            gap: 1rem;
            margin-top: 0.8rem;
        }}
        
        .stat-card {{
            background: var(--cream);
            border: 1px solid var(--border);
            padding: 1rem;
            border-radius: 4px;
            text-align: center;
        }}
        
        .stat-card .value {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 1.8rem;
            font-weight: 700;
            color: var(--red);
            margin: 0.5rem 0;
        }}
        
        .stat-card .label {{
            font-size: 0.75rem;
            color: var(--mute);
            text-transform: uppercase;
            letter-spacing: 0.1em;
        }}
        
        .redaction-notice {{
            background: var(--cream);
            border-left: 3px solid var(--red);
            padding: 0.8rem;
            margin-top: 1rem;
            font-size: 0.8rem;
            font-style: italic;
            color: var(--mute);
        }}
        
        .signoff {{
            border-top: 2px solid var(--border);
            margin-top: 2rem;
            padding-top: 1rem;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 3rem;
        }}
        
        .signature-block {{
            text-align: center;
        }}
        
        .signature-line {{
            border-bottom: 1px solid var(--ink);
            height: 60px;
            margin-bottom: 0.3rem;
        }}
        
        .signature-name {{
            font-weight: 600;
            font-size: 0.85rem;
            margin-top: 0.3rem;
        }}
        
        .signature-title {{
            font-size: 0.75rem;
            color: var(--mute);
            margin-top: 0.2rem;
        }}
        
        @media print {{
            body {{ background: white; }}
            .page {{ margin: 0; box-shadow: none; }}
        }}
    </style>
</head>
<body>
    <div class="page">
        <div class="content">
            <div class="letterhead">
                <div class="letterhead-left">
                    <div class="star-logo">{brand.star_svg(px=34)}</div>
                    <div class="letterhead-text">
                        <h1>SUPERSTARS</h1>
                        <p>Contracting & Restoration</p>
                        <p>Bronx, NY 10454</p>
                    </div>
                </div>
                <div class="letterhead-right">
                    <h2>{"Weekly Progress Report" if not is_internal else "Weekly Construction Report"}</h2>
                    <p><strong>Week ending</strong> {data['period']['week_ending']}</p>
                    <p><strong>Report</strong> {data['report_id']}</p>
                </div>
            </div>
            
            <div class="section">
                <div class="eyebrow">Project Information</div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; font-size: 0.9rem;">
                    <div>
                        <strong>Project Code:</strong> {data['project']['code']}<br>
                        <strong>Location:</strong> {data['project']['address']}<br>
                        <strong>Owner:</strong> {data['project']['owner']}
                    </div>
                    <div>
                        <strong>PM:</strong> {data['project']['pm']}<br>
                        <strong>GC:</strong> {data['project']['gc']}<br>
                        <strong>Status:</strong> {data['project']['status']}
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h3 class="section-title">Executive Summary</h3>
                <div class="exec-summary">
                    <div class="hero-number">
                        <div class="number">{data['executive_summary']['overall_pct_complete']}%</div>
                        <div class="label">Overall Complete</div>
                    </div>
                    <div>
                        <div style="margin-bottom: 0.8rem;">
                            <strong style="font-size: 0.9rem;">Schedule Status:</strong>
                            <div style="margin-top: 0.3rem;">
                                <span class="badge {"success" if "On track" in data['executive_summary']['schedule_status'] else "warning"}">
                                    {data['executive_summary']['schedule_status']}
                                </span>
                            </div>
                        </div>
                        <div style="margin-bottom: 0.8rem;">
                            <strong style="font-size: 0.9rem;">Budget Status:</strong>
                            <div style="margin-top: 0.3rem;">
                                <span class="badge success">{data['executive_summary']['budget_status']}</span>
                            </div>
                        </div>
                        <div>
                            <strong style="font-size: 0.9rem; display: block; margin-bottom: 0.5rem;">Key Highlights</strong>
                            <div class="highlights">
                                <ul>
'''

    for highlight in data['executive_summary']['key_highlights']:
        html += f'                                    <li>{highlight}</li>\n'
    
    html += f'''                                </ul>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="section">
                <h3 class="section-title">Schedule Progress</h3>
                <div class="eyebrow">Phase Status</div>
                <table>
                    <thead>
                        <tr>
                            <th>Phase</th>
                            <th>Planned %</th>
                            <th>Actual %</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
'''
    
    for phase in data['schedule_progress']['phases']:
        html += f'''                        <tr>
                            <td>{phase['name']}</td>
                            <td style="text-align: right; font-family: 'Courier New', monospace;">{phase['planned_pct']}%</td>
                            <td style="text-align: right; font-family: 'Courier New', monospace;">{phase['actual_pct']}%</td>
                            <td><span class="badge info">{phase['status']}</span></td>
                        </tr>
'''
    
    html += f'''                    </tbody>
                </table>
            </div>
            
            <div class="section">
                <h3 class="section-title">Labor & Site Activity</h3>
                <div class="eyebrow">Headcount & Hours by Day</div>
                <table>
                    <thead>
                        <tr>
                            <th>Date</th>
                            <th>Headcount</th>
                            <th>Hours</th>
                        </tr>
                    </thead>
                    <tbody>
'''
    
    for day in data['labor_summary']['by_day']:
        short_day = day['day'][:3]
        html += f'''                        <tr>
                            <td>{day['date']} ({short_day})</td>
                            <td style="text-align: right;">{day['headcount']}</td>
                            <td style="text-align: right; font-family: 'Courier New', monospace;">{day['hours']}</td>
                        </tr>
'''
    
    html += f'''                    </tbody>
                </table>
                
                <div class="eyebrow" style="margin-top: 1.5rem;">Trade Breakdown</div>
'''
    
    for trade_data in data['labor_summary']['by_trade']:
        pct = trade_data['pct_of_total']
        html += f'''                <div class="trade-row">
                    <div>{trade_data['trade']}</div>
                    <div class="trade-bar"><div class="trade-fill" style="width: {pct}%;"></div></div>
                    <div class="trade-hours">{trade_data['hours']} hrs</div>
                </div>
'''
    
    if not is_internal:
        html += '''                <div class="redaction-notice">
                    Worker names and individual hours not shown in client portal.
                </div>
'''
    
    html += f'''            </div>
            
            <div class="section">
                <h3 class="section-title">Work Performed This Week</h3>
'''
    
    if data['work_performed']:
        html += '''                <table>
                    <thead>
                        <tr>
                            <th>Date</th>
                            <th>Zone</th>
                            <th>Description</th>
                        </tr>
                    </thead>
                    <tbody>
'''
        for work in data['work_performed']:
            html += f'''                        <tr>
                            <td>{work['date']}</td>
                            <td>{work['zone']}</td>
                            <td>{work['description']}</td>
                        </tr>
'''
        html += '''                    </tbody>
                </table>
'''
    
    html += f'''            </div>
            
            <div class="section">
                <h3 class="section-title">Safety & Compliance</h3>
                <div class="stat-cards">
                    <div class="stat-card">
                        <div class="label">Incidents</div>
                        <div class="value">{data['safety_compliance']['incidents_this_week']}</div>
                    </div>
                    <div class="stat-card">
                        <div class="label">Near Misses</div>
                        <div class="value">{data['safety_compliance']['near_misses_this_week']}</div>
                    </div>
                    <div class="stat-card">
                        <div class="label">Weather Holds</div>
                        <div class="value">{data['safety_compliance']['weather_hold_days']}</div>
                    </div>
                </div>
                <div style="margin-top: 1rem; font-size: 0.9rem;">
                    <strong>Compliance Status:</strong> {data['safety_compliance']['compliance_status']}
                </div>
'''
    
    if is_internal:
        html += f'''                <div style="margin-top: 0.5rem; font-size: 0.9rem;">
                    <strong>Cert Alert:</strong> {data['safety_compliance']['expiring_certs_alert']}
                </div>
'''
    
    html += f'''            </div>
            
            <div class="section">
                <h3 class="section-title">Lookahead — Next Week</h3>
                <div class="highlights">
                    <ul>
'''
    
    for activity in data['lookahead_next_week']['planned_activities']:
        html += f'                        <li>{activity}</li>\n'
    
    html += f'''                    </ul>
                </div>
            </div>
            
            <div class="signoff">
                <div class="signature-block">
                    <div class="signature-line"></div>
                    <div class="signature-name">{data['prepared_by']['name']}</div>
                    <div class="signature-title">{data['prepared_by']['role']}</div>
                </div>
                <div class="signature-block">
                    <div style="text-align: center; color: var(--mute); font-size: 0.8rem;">
                        <p><strong>Report Date:</strong> {data['prepared_by']['date']}</p>
                    </div>
                </div>
            </div>
        </div>
    </div>
</body>
</html>
'''
    
    with open(output_path, 'w') as f:
        f.write(html)
    
    print(f"✓ Rendered {output_path}")

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: render_weekly_summary_html.py <json_path> <html_output_path>")
        sys.exit(1)
    
    render_html(sys.argv[1], sys.argv[2])
