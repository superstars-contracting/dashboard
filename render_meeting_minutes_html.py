#!/usr/bin/env python3
import json
import sys
from datetime import datetime

def render_html(data):
    attendees_html = '\n'.join([
        f"<div class='attendee'>{a['name']} · {a['role']}" + 
        (f" — {a['company']}" if a['company'] else "") + "</div>"
        for a in data['attendees']
    ])

    decisions_html = '\n'.join([
        f"<li>{d}</li>"
        for d in data['decisions']
    ])

    def status_badge_class(status):
        classes = {
            'Completed': 'badge-completed',
            'In Progress': 'badge-in-progress',
            'Open': 'badge-open',
            'Overdue': 'badge-overdue',
            'Cancelled': 'badge-cancelled'
        }
        return classes.get(status, 'badge-open')

    actions_html = '\n'.join([
        f"""<tr>
            <td>{a['id']}</td>
            <td>{a['description']}</td>
            <td>{a['owner']}</td>
            <td>{a['due_date']}</td>
            <td><span class='status-badge {status_badge_class(a['status'])}'>{a['status']}</span></td>
        </tr>"""
        for a in data['action_items']
    ])

    distribution_html = '\n'.join([
        f"<div class='dist-item'>{d['name']} ({d['email']})</div>"
        for d in data['distribution_list']
    ])

    next_mtg = f"<div class='next-mtg'><strong>Next: {data['next_meeting'].get('type', '')} · {data['next_meeting'].get('date', '')} · {data['next_meeting'].get('time', '')} · {data['next_meeting'].get('location', '')}</strong></div>" if data['next_meeting'].get('type') else ""

    topics_html = ""
    if data.get('topics_discussed'):
        topics_html = '\n'.join([
            f"""<div class='topic'>
                <h4>{t.get('topic', '')}</h4>
                <p class='topic-meta'>{t.get('duration_minutes', 0)} min</p>
                <p>{t.get('summary', '')}</p>
            </div>"""
            for t in data['topics_discussed']
        ])
        topics_html = f"<div class='topics-section'><h3>Topics Discussed</h3>{topics_html}</div>"

    summary_block = f"""<div class='summary-block'>
        <p><em>{data['summary']}</em></p>
    </div>""" if data['summary'] else ""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Meeting Minutes - {data['meeting_id']}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        :root {{
            --brand-red: #B11E2E;
            --ink: #14161C;
            --cream: #FAF7F1;
            --text-light: #666;
        }}
        body {{
            font-family: 'DM Sans', sans-serif;
            font-size: 13px;
            line-height: 1.6;
            color: var(--ink);
            background: white;
            padding: 40px;
            max-width: 8.5in;
            margin: 0 auto;
        }}
        @media print {{
            body {{ padding: 20px; }}
        }}
        .letterhead {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--ink);
            padding-bottom: 20px;
            margin-bottom: 30px;
        }}
        .letterhead-left {{
            font-size: 14px;
            font-weight: bold;
            color: var(--ink);
        }}
        .letterhead-left .star {{ color: var(--brand-red); font-size: 18px; }}
        .letterhead-right {{
            text-align: right;
            font-size: 14px;
        }}
        .letterhead-right .title {{ font-family: 'Playfair Display', serif; font-size: 18px; font-weight: bold; color: var(--ink); }}
        .letterhead-right .meta {{ font-size: 12px; color: var(--text-light); margin-top: 4px; }}
        section {{
            margin-bottom: 28px;
        }}
        h2 {{
            font-family: 'Playfair Display', serif;
            font-size: 16px;
            font-weight: normal;
            color: var(--ink);
            margin-bottom: 12px;
            border-bottom: 1px solid #eee;
            padding-bottom: 8px;
        }}
        h3 {{
            font-family: 'Playfair Display', serif;
            font-size: 14px;
            font-weight: normal;
            color: var(--ink);
            margin-bottom: 12px;
            margin-top: 16px;
        }}
        h4 {{
            font-size: 12px;
            font-weight: bold;
            color: var(--ink);
            margin-top: 12px;
            margin-bottom: 6px;
        }}
        p {{ margin-bottom: 10px; line-height: 1.7; }}
        .summary-block {{
            background: rgba(255,247,241,0.5);
            border-left: 3px solid var(--brand-red);
            padding: 12px 16px;
            margin: 12px 0;
            font-style: italic;
            color: var(--ink);
        }}
        .meeting-info {{
            background: var(--cream);
            padding: 14px;
            margin-bottom: 20px;
            border-radius: 2px;
            font-size: 12px;
        }}
        .meeting-info p {{
            margin-bottom: 6px;
        }}
        .attendee {{
            padding: 4px 0;
            font-size: 12px;
        }}
        ul {{
            margin-left: 20px;
            margin-bottom: 12px;
        }}
        li {{
            margin-bottom: 6px;
            list-style: none;
            position: relative;
            padding-left: 16px;
        }}
        li:before {{
            content: '•';
            color: var(--brand-red);
            position: absolute;
            left: 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 12px 0;
            font-size: 11px;
        }}
        th {{
            background: var(--ink);
            color: white;
            padding: 8px;
            text-align: left;
            font-weight: bold;
            border: 1px solid var(--ink);
        }}
        td {{
            padding: 8px;
            border: 1px solid #ddd;
        }}
        tr:nth-child(even) {{
            background: var(--cream);
        }}
        .status-badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 2px;
            font-size: 10px;
            font-weight: bold;
        }}
        .badge-completed {{
            background: #d4edda;
            color: #155724;
        }}
        .badge-in-progress {{
            background: #fff3cd;
            color: #856404;
        }}
        .badge-open {{
            background: #e2e3e5;
            color: #383d41;
        }}
        .badge-overdue {{
            background: #f8d7da;
            color: #721c24;
        }}
        .badge-cancelled {{
            background: #ddd;
            color: #666;
            text-decoration: line-through;
        }}
        .next-mtg {{
            background: var(--cream);
            padding: 12px;
            border-left: 3px solid var(--brand-red);
            margin: 14px 0;
            font-size: 12px;
        }}
        .dist-item {{
            padding: 4px 0;
            font-size: 11px;
        }}
        .footer {{
            border-top: 1px solid #ccc;
            padding-top: 12px;
            margin-top: 30px;
            font-size: 10px;
            color: var(--text-light);
            text-align: center;
        }}
        .topic-meta {{
            font-size: 10px;
            color: var(--text-light);
            margin-bottom: 4px;
        }}
        .topics-section {{
            margin: 14px 0;
        }}
    </style>
</head>
<body>
    <div class='letterhead'>
        <div class='letterhead-left'>
            <span class='star'>★</span> SUPERSTARS<br>
            <small>Contracting</small>
        </div>
        <div class='letterhead-right'>
            <div class='title'>Meeting Minutes</div>
            <div class='meta'>{data['meeting_id']} · {data['meeting']['date']}</div>
            <div class='meta' style='font-size: 11px;'>{data['meeting']['type']}</div>
        </div>
    </div>

    <section class='meeting-info'>
        <p><strong>{data['meeting']['type']} · {data['meeting_id']}</strong></p>
        <p>{data['meeting']['day_of_week']}, {data['meeting']['date']} · {data['meeting']['time_start']} – {data['meeting']['time_end']} ({data['meeting']['duration_minutes']} min)</p>
        <p><strong>Location:</strong> {data['meeting']['location']}</p>
        <p><strong>Prepared by:</strong> {data['meeting']['prepared_by']} · {data['meeting'].get('prepared_by_role', 'Project Manager')}</p>
        <p><strong>Source:</strong> {data['transcript_source']}</p>
    </section>

    <section>
        <h2>Attendees</h2>
        <p style='margin-bottom: 8px; font-size: 11px; color: var(--text-light);'>({len(data['attendees'])})</p>
        {attendees_html}
    </section>

    {summary_block}

    {topics_html}

    {'''<section>
        <h2>Decisions Made</h2>
        <ul>''' + decisions_html + '''</ul>
    </section>''' if data['decisions'] else ''}

    {'''<section>
        <h2>Action Items</h2>
        <table>
            <thead>
                <tr><th>#</th><th>Description</th><th>Owner</th><th>Due</th><th>Status</th></tr>
            </thead>
            <tbody>''' + actions_html + '''</tbody>
        </table>
    </section>''' if data['action_items'] else ''}

    {next_mtg}

    {'''<section>
        <h2>Distribution</h2>''' + distribution_html + '''
        <p style='margin-top: 10px; font-size: 11px; color: var(--text-light);'>Minutes distributed to all attendees and listed recipients.</p>
    </section>''' if data['distribution_list'] else ''}

    <div class='footer'>
        Generated by {data['transcript_source']} · {datetime.now().strftime('%Y-%m-%d %H:%M')} · Superstars Contracting
    </div>
</body>
</html>"""
    return html

def main():
    json_path = sys.argv[1]
    output_path = sys.argv[2]

    with open(json_path) as f:
        data = json.load(f)

    html = render_html(data)

    with open(output_path, 'w') as f:
        f.write(html)

    print(f"✓ Rendered {output_path}")

if __name__ == '__main__':
    main()
