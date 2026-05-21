#!/usr/bin/env python3
import json
import sys
from datetime import datetime
from typography import get_inlined_style_tag

def render_lookahead_html(json_path, output_path):
    with open(json_path, 'r') as f:
        data = json.load(f)

    prepared_by = data['sign_off']['prepared_by']['name']
    prepared_role = data['sign_off']['prepared_by']['role']
    reviewed_by = data['sign_off']['reviewed_by']['name']
    reviewed_role = data['sign_off']['reviewed_by']['role']
    signoff_date = data['sign_off']['date']
    gen_time = datetime.now().strftime('%Y-%m-%d %H:%M')

    html = build_html(data, prepared_by, prepared_role, reviewed_by, reviewed_role, signoff_date, gen_time)

    with open(output_path, 'w') as f:
        f.write(html)

def build_html(data, prepared_by, prepared_role, reviewed_by, reviewed_role, signoff_date, gen_time):

    head_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    {get_inlined_style_tag()}
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>2-Week Look Ahead — {data['project']['code']}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}

        :root {{
            --dark-ink: #14161C;
            --brand-red: #B11E2E;
            --cream-bg: #FAF7F1;
            --white: #FFFFFF;
            --hairline: #E8E4DD;
            --mute: #76777E;
            --text: #3C3935;
            --gold: #B89968;
            --weekend-cream: #F4EFE3;
            --subtle-cream: #F8F4E8;
        }}

        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background: var(--cream-bg);
            color: var(--text);
            line-height: 1.5;
        }}

        .page {{
            background: var(--white);
            max-width: 11in;
            margin: 0.5in auto;
            padding: 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}

        .letterhead {{
            background: var(--dark-ink);
            color: var(--white);
            padding: 0.5in;
            display: grid;
            grid-template-columns: 1fr 2fr;
            gap: 1in;
            align-items: center;
            border-bottom: 2px solid var(--brand-red);
        }}

        .letterhead-left {{
            font-size: 10px;
            line-height: 1.4;
            opacity: 0.9;
        }}

        .letterhead-brand {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 28px;
            font-weight: 700;
            letter-spacing: -1px;
            margin-bottom: 0.2in;
        }}

        .letterhead-address {{
            font-size: 9px;
            opacity: 0.85;
        }}

        .letterhead-right {{
            text-align: right;
        }}

        .letterhead-title {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 24px;
            font-weight: 600;
            margin-bottom: 0.1in;
            color: var(--white);
        }}

        .letterhead-meta {{
            font-size: 10px;
            opacity: 0.9;
            margin-bottom: 0.1in;
            line-height: 1.3;
        }}

        .letterhead-period {{
            font-size: 9px;
            opacity: 0.8;
        }}

        .section {{
            padding: 0.4in 0.5in;
            border-bottom: 1px solid var(--hairline);
        }}

        .section:last-child {{
            border-bottom: none;
        }}

        .section-title {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 16px;
            font-weight: 600;
            color: var(--text);
            margin-bottom: 0.2in;
            padding-top: 0.2in;
            position: relative;
            padding-left: 0;
        }}

        .section-title::before {{
            content: '';
            position: absolute;
            top: -0.15in;
            left: 0;
            width: 32px;
            height: 2px;
            background: var(--brand-red);
        }}

        .section-header {{
            display: flex;
            align-items: center;
            margin-bottom: 0.15in;
        }}

        .section-rule {{
            width: 32px;
            height: 2px;
            background: var(--brand-red);
            margin-right: 0.2in;
            display: block;
            flex-shrink: 0;
        }}

        .eyebrow {{
            font-size: 8px;
            font-weight: 600;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: var(--mute);
            margin-bottom: 0.15in;
            display: block;
        }}

        .project-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.3in;
            font-size: 10px;
        }}

        .project-field {{
            display: flex;
            flex-direction: column;
        }}

        .project-label {{
            font-weight: 600;
            color: var(--mute);
            font-size: 9px;
            text-transform: uppercase;
            letter-spacing: 0.12em;
            margin-bottom: 0.05in;
        }}

        .project-value {{
            font-weight: 500;
            color: var(--text);
        }}

        .summary-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 0.25in;
            font-size: 10px;
        }}

        .summary-card {{
            background: var(--cream-bg);
            padding: 0.2in;
            border-radius: 2px;
            border-left: 2px solid var(--brand-red);
        }}

        .summary-card .eyebrow {{
            margin-bottom: 0.1in;
        }}

        .summary-list {{
            list-style: none;
            font-size: 9px;
            line-height: 1.3;
        }}

        .summary-list li {{
            margin-bottom: 0.08in;
            padding-left: 0.15in;
            position: relative;
        }}

        .summary-list li::before {{
            content: '•';
            position: absolute;
            left: 0;
        }}

        .trade-chips {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.1in;
            margin-top: 0.08in;
        }}

        .trade-chip {{
            background: var(--dark-ink);
            color: var(--white);
            padding: 0.05in 0.1in;
            border-radius: 2px;
            font-size: 8px;
            font-weight: 600;
        }}

        /* GANTT TABLE */
        .gantt-wrap {{
            position: relative;
            width: 968px;
            margin: 24px auto;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
        }}

        .week-divider {{
            position: absolute;
            left: 604px;
            top: 0;
            bottom: 0;
            width: 2px;
            background: var(--brand-red);
            z-index: 1;
            pointer-events: none;
        }}

        table.gantt {{
            table-layout: fixed;
            width: 968px;
            border-collapse: separate;
            border-spacing: 0;
            font-size: 11px;
        }}

        table.gantt col.label-col {{ width: 240px; }}
        table.gantt col.day-col {{ width: 52px; }}

        table.gantt th.week-label {{
            height: 32px;
            text-align: center;
            font-size: 10px;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: var(--mute);
            font-weight: 600;
            border-bottom: 1px solid var(--hairline);
            padding: 0;
        }}

        table.gantt tr.week-row th:nth-child(2) {{
            border-right: 1px solid var(--hairline);
        }}

        table.gantt tr.day-row th {{
            height: 64px;
            padding: 8px 0;
            text-align: center;
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 22px;
            font-weight: 600;
            color: var(--dark-ink);
            background: var(--white);
            border-bottom: 1.5px solid var(--dark-ink);
            border-right: 1px solid var(--hairline);
        }}

        table.gantt tr.day-row th:first-child {{
            border-bottom: 1.5px solid var(--dark-ink);
            border-right: none;
        }}

        table.gantt tr.day-row th .dow {{
            display: block;
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            font-size: 9px;
            font-weight: 600;
            letter-spacing: 0.16em;
            color: var(--mute);
            text-transform: uppercase;
            margin-bottom: 4px;
        }}

        table.gantt tr.day-row th.weekend {{
            background: var(--weekend-cream);
        }}

        table.gantt tr.day-row th.weekend,
        table.gantt tr.day-row th.weekend .dow {{
            color: var(--mute);
        }}

        table.gantt tr.day-row th:nth-child(8) {{
            border-right: 1px solid var(--hairline);
        }}

        table.gantt tr.activity-row {{
            height: 48px;
        }}

        table.gantt tr.activity-row td {{
            padding: 0;
            border-bottom: 1px solid var(--hairline);
            vertical-align: middle;
        }}

        table.gantt tr.activity-row:last-child td {{
            border-bottom: none;
        }}

        table.gantt td.label {{
            padding: 8px 14px;
            border-right: 1px solid var(--hairline);
            position: relative;
        }}

        table.gantt td.label .trade {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 13px;
            font-weight: 600;
            color: var(--dark-ink);
            line-height: 1.2;
        }}

        table.gantt td.label .work-area {{
            font-size: 11px;
            color: var(--mute);
            margin-top: 1px;
            line-height: 1.2;
        }}

        table.gantt td.label .type-badge {{
            position: absolute;
            top: 8px;
            right: 8px;
            font-size: 9px;
            letter-spacing: 0.12em;
            text-transform: uppercase;
            font-weight: 600;
            padding: 2px 6px;
            border-radius: 2px;
            color: var(--mute);
            background: var(--weekend-cream);
        }}

        table.gantt td.label .type-work    {{ color: var(--dark-ink); background: #EFEAD8; }}
        table.gantt td.label .type-inspect {{ color: var(--brand-red); background: #F5E0E2; }}
        table.gantt td.label .type-deliver {{ color: #7A6334; background: #F1EAD9; }}

        table.gantt td.day-cell {{
            border-right: 1px solid var(--hairline);
        }}

        table.gantt td.day-cell.weekend {{
            background: var(--subtle-cream);
        }}

        table.gantt tr.activity-row td:nth-child(8) {{
            border-right: 1px solid var(--hairline);
        }}

        table.gantt td.bar {{
            padding: 0;
            border-right: 1px solid var(--hairline);
            position: relative;
        }}

        table.gantt td.bar .bar-inner {{
            position: absolute;
            top: 6px;
            left: 2px;
            right: 2px;
            bottom: 6px;
            border-radius: 4px;
            display: flex;
            align-items: center;
            padding: 0 10px;
            font-size: 11px;
            font-weight: 600;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            z-index: 2;
            color: var(--white);
        }}

        table.gantt td.bar.bar-work     .bar-inner {{ background: var(--dark-ink); }}
        table.gantt td.bar.bar-inspect  .bar-inner {{ background: var(--brand-red); }}
        table.gantt td.bar.bar-deliver  .bar-inner {{ background: var(--gold); }}
        table.gantt td.bar.bar-mile     .bar-inner {{ background: rgba(20,22,28,0.06); border: 1.5px dashed var(--dark-ink); color: var(--dark-ink); }}
        table.gantt td.bar.bar-planned   .bar-inner {{ opacity: 0.78; }}
        table.gantt td.bar.bar-confirmed .bar-inner {{ opacity: 1.0; }}

        /* Legend */
        .gantt-legend {{
            margin-top: 16px;
            margin-bottom: 12px;
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 16px;
            font-size: 11px;
            font-weight: 500;
        }}

        .gantt-legend-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .gantt-legend-swatch {{
            display: inline-block;
            width: 10px;
            height: 10px;
            border-radius: 2px;
        }}

        .gantt-legend-swatch.work {{
            background: var(--dark-ink);
        }}

        .gantt-legend-swatch.inspection {{
            background: var(--brand-red);
        }}

        .gantt-legend-swatch.delivery {{
            background: var(--gold);
        }}

        .gantt-legend-swatch.milestone {{
            border: 1.5px dashed var(--dark-ink);
            background: var(--white);
        }}

        .gantt-legend-swatch.weekend {{
            background: var(--subtle-cream);
            border: 1px solid var(--dark-ink);
        }}

        /* Key items */
        .key-items-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr 1fr;
            gap: 0.2in;
            font-size: 9px;
        }}

        .key-item-card {{
            background: var(--cream-bg);
            padding: 0.15in;
            border-left: 2px solid var(--brand-red);
            border-radius: 2px;
        }}

        .key-item-card .eyebrow {{
            margin-bottom: 0.1in;
        }}

        .key-item-list {{
            list-style: none;
            font-size: 8px;
            line-height: 1.2;
        }}

        .key-item-list li {{
            margin-bottom: 0.05in;
            padding-left: 0.12in;
            position: relative;
        }}

        .key-item-list li::before {{
            content: '•';
            position: absolute;
            left: 0;
        }}

        /* Sign-off */
        .signoff {{
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 0.5in;
            margin-top: 0.2in;
        }}

        .signoff-cell {{
            display: flex;
            flex-direction: column;
        }}

        .signoff-label {{
            font-weight: 600;
            color: var(--mute);
            font-size: 8px;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 0.1in;
        }}

        .signoff-name {{
            font-weight: 600;
            margin-bottom: 0.3in;
            min-height: 0.5in;
        }}

        .signoff-line {{
            border-top: 1px solid var(--text);
            margin-top: 0.1in;
            padding-top: 0.05in;
            font-size: 8px;
        }}

        /* Footer */
        .footer {{
            padding: 0.2in 0.5in;
            border-top: 1px solid var(--hairline);
            font-size: 8px;
            color: var(--mute);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .footer-left {{ flex: 1; line-height: 1.3; }}
        .footer-right {{ text-align: right; }}

        @page {{
            size: letter portrait;
            margin: 0.5in;
        }}

        @page landscape {{
            size: letter landscape;
            margin: 0.4in;
        }}

        @media print {{
            body {{ margin: 0; padding: 0; background: #FFFFFF; }}
            .page {{ margin: 0; padding: 0; max-width: 100%; box-shadow: none; }}
            .container {{ box-shadow: none; padding: 0; max-width: none; }}

            /* The Gantt section gets its own landscape page */
            .gantt-page {{
                page: landscape;
                page-break-before: always;
                page-break-after: always;
                margin: 0;
            }}

            /* All other sections force portrait */
            .portrait-page {{ page: auto; }}
        }}
    </style>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet">
</head>
<body>
"""

    body_html = f"""    <div class="page">
        <div class="letterhead">
            <div class="letterhead-left">
                <div class="letterhead-brand">SUPERSTARS</div>
                <div class="letterhead-address">Superstars Contracting, Inc.<br>{data['project']['address']}</div>
            </div>
            <div class="letterhead-right">
                <div class="letterhead-title">2-Week Look Ahead</div>
                <div class="letterhead-meta">
                    Meeting · {data['project']['meeting_day']}, {data['project']['meeting_date']}<br>
                    {data['report_id']}
                </div>
                <div class="letterhead-period">Reporting period: {data['two_week_lookahead']['period']}</div>
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">Project</h2>
            <div class="project-grid">
                <div class="project-field">
                    <div class="project-label">Project Name</div>
                    <div class="project-value">{data['project']['name']}</div>
                </div>
                <div class="project-field">
                    <div class="project-label">Project Address</div>
                    <div class="project-value">{data['project']['address']}</div>
                </div>
                <div class="project-field">
                    <div class="project-label">Prepared By</div>
                    <div class="project-value">{data['project']['prepared_by']}</div>
                </div>
                <div class="project-field">
                    <div class="project-label">Meeting Date</div>
                    <div class="project-value">{data['project']['meeting_date']}</div>
                </div>
            </div>
        </div>

        <div class="section">
            <span class="eyebrow">Week of {data['weekly_summary_previous_week']['period']}</span>
            <h2 class="section-title">Previous Week Summary</h2>
            <div class="summary-grid">
                <div class="summary-card">
                    <span class="eyebrow">Major Work Completed</span>
                    <ul class="summary-list">
                        {build_list_items(data['weekly_summary_previous_week']['major_work_completed'][:3])}
                    </ul>
                </div>
                <div class="summary-card">
                    <span class="eyebrow">Trades On Site</span>
                    <div class="trade-chips">
                        {build_trade_chips(data['weekly_summary_previous_week']['trades_on_site'][:4])}
                    </div>
                </div>
                <div class="summary-card">
                    <span class="eyebrow">Key Deliveries</span>
                    <ul class="summary-list">
                        {build_list_items(data['weekly_summary_previous_week']['key_deliveries'])}
                    </ul>
                </div>
                <div class="summary-card">
                    <span class="eyebrow">Inspections Completed</span>
                    <ul class="summary-list">
                        {build_list_items(data['weekly_summary_previous_week']['inspections_completed'])}
                    </ul>
                </div>
                <div class="summary-card">
                    <span class="eyebrow">Issues Encountered</span>
                    <ul class="summary-list">
                        {build_list_items(data['weekly_summary_previous_week']['issues_encountered'][:2])}
                    </ul>
                </div>
                <div class="summary-card">
                    <span class="eyebrow">Schedule Impact</span>
                    <div style="font-size: 8px; font-style: italic; margin-top: 0.1in;">{data['weekly_summary_previous_week']['delays']}</div>
                </div>
            </div>
        </div>

        <section class="gantt-page">
            <div class="section-header">
                <span class="section-rule"></span>
                <span class="eyebrow">SCHEDULE · {data['two_week_lookahead']['period'].upper()}</span>
            </div>
            <h2 class="section-title">2-Week Look Ahead</h2>
            <div class="gantt-wrap">
                <div class="week-divider"></div>
"""

    # Build Gantt table
    day_cols = data['two_week_lookahead']['day_columns']
    weeks = data['two_week_lookahead'].get('weeks', [])

    body_html += """                <table class="gantt">
                    <colgroup>
                        <col class="label-col"/>
"""
    for _ in range(14):
        body_html += """                        <col class="day-col"/>
"""
    body_html += """                    </colgroup>
                    <thead>
                        <tr class="week-row">
                            <th></th>
"""
    if weeks:
        body_html += f"""                            <th colspan="7" class="week-label">WEEK 1 · {weeks[0]['label_text'].upper()}</th>
                            <th colspan="7" class="week-label">WEEK 2 · {weeks[1]['label_text'].upper()}</th>
"""
    body_html += """                        </tr>
                        <tr class="day-row">
                            <th></th>
"""
    for day in day_cols:
        weekend_class = ' weekend' if day['is_weekend'] else ''
        day_letter = day['day_name'][0]
        body_html += f"""                            <th class="day-cell{weekend_class}"><span class="dow">{day_letter}</span>{day['day_num']}</th>
"""
    body_html += """                        </tr>
                    </thead>
                    <tbody>
"""

    # Activity rows
    for activity in data['two_week_lookahead']['activities']:
        type_lower = activity['type'].lower()
        status_class = activity['status'].lower()

        badge_map = {'Work': 'work', 'Inspection': 'inspect', 'Delivery': 'deliver', 'Milestone': 'mile'}
        badge_class = badge_map.get(activity['type'], 'work')

        body_html += f"""                        <tr class="activity-row">
                            <td class="label">
                                <div class="trade">{activity['trade']}</div>
                                <div class="work-area">{activity['work_area']}</div>
                                <span class="type-badge type-{badge_class}">{activity['type']}</span>
                            </td>
"""

        # Build day cells
        col_idx = 0
        while col_idx < 14:
            if col_idx == activity['start_offset_days']:
                bar_class = f"bar-{type_lower} bar-{status_class}"
                body_html += f"""                            <td colspan="{activity['display_duration']}" class="bar {bar_class}">
                                <div class="bar-inner">{activity['scope']}</div>
                            </td>
"""
                col_idx += activity['display_duration']
            else:
                weekend_class = ' weekend' if day_cols[col_idx]['is_weekend'] else ''
                body_html += f"""                            <td class="day-cell weekday{weekend_class}"></td>
"""
                col_idx += 1

        body_html += """                        </tr>
"""

    body_html += """                    </tbody>
                </table>
            </div>
            <div class="gantt-legend">
                <div class="gantt-legend-item">
                    <span class="gantt-legend-swatch work"></span>
                    <span>Work</span>
                </div>
                <div class="gantt-legend-item">
                    <span class="gantt-legend-swatch inspection"></span>
                    <span>Inspection</span>
                </div>
                <div class="gantt-legend-item">
                    <span class="gantt-legend-swatch delivery"></span>
                    <span>Delivery</span>
                </div>
                <div class="gantt-legend-item">
                    <span class="gantt-legend-swatch milestone"></span>
                    <span>Milestone</span>
                </div>
                <div class="gantt-legend-item">
                    <span class="gantt-legend-swatch weekend"></span>
                    <span>Weekend</span>
                </div>
            </div>
        </section>

        <div class="section">
            <h2 class="section-title">Key Upcoming Items</h2>
            <div class="key-items-grid">
                <div class="key-item-card">
                    <span class="eyebrow">Upcoming Inspections</span>
                    <ul class="key-item-list">
"""

    for insp in data['key_upcoming_items']['upcoming_inspections']:
        body_html += f"                        <li>{insp['type']} — {insp['agency']} ({insp['date']})</li>\n"

    body_html += """                    </ul>
                </div>
                <div class="key-item-card">
                    <span class="eyebrow">Critical Milestones</span>
                    <ul class="key-item-list">
"""

    for milestone in data['key_upcoming_items']['critical_milestones']:
        body_html += f"                        <li>{milestone}</li>\n"

    body_html += """                    </ul>
                </div>
                <div class="key-item-card">
                    <span class="eyebrow">Important Deliveries</span>
                    <ul class="key-item-list">
"""

    for delivery in data['key_upcoming_items']['important_deliveries']:
        body_html += f"                        <li>{delivery}</li>\n"

    body_html += f"""                    </ul>
                </div>
            </div>
        </div>

        <div class="section">
            <h2 class="section-title">Sign-Off</h2>
            <div class="signoff">
                <div class="signoff-cell">
                    <span class="signoff-label">Prepared By</span>
                    <div class="signoff-name">{prepared_by}</div>
                    <div class="signoff-line">{prepared_role}</div>
                </div>
                <div class="signoff-cell">
                    <span class="signoff-label">Reviewed By</span>
                    <div class="signoff-name">{reviewed_by}</div>
                    <div class="signoff-line">{reviewed_role}</div>
                </div>
                <div class="signoff-cell">
                    <span class="signoff-label">Date</span>
                    <div class="signoff-name">{signoff_date}</div>
                </div>
            </div>
        </div>

        <div class="footer">
            <div class="footer-left">
                Prepared at the Thursday weekly planning meeting. Distributed to PM, Superintendent, Foreman, and Owner's Rep.
            </div>
            <div class="footer-right">
                Generated {gen_time}
            </div>
        </div>
    </div>
</body>
</html>
"""

    return head_html + body_html

def build_list_items(items):
    return ''.join(f'<li>{item}</li>' for item in items)

def build_trade_chips(trades):
    return ''.join(f'<span class="trade-chip">{t}</span>' for t in trades)

if __name__ == '__main__':
    if len(sys.argv) != 3:
        print("Usage: render_lookahead_html.py <json_path> <output_path>")
        sys.exit(1)

    render_lookahead_html(sys.argv[1], sys.argv[2])
    print(f"✓ Rendered {sys.argv[2]}")
