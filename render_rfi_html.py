import json
import sys
from datetime import datetime
from typography import get_inlined_style_tag

def render_rfi(json_path, output_html):
    with open(json_path, 'r') as f:
        data = json.load(f)

    status = data['status']
    priority = data['priority']
    
    status_colors = {
        'Draft': '#E8E4DD',
        'Submitted': '#E8E4DD',
        'Under Review': '#FFC107',
        'Response Received': '#4CAF50',
        'Closed': '#999',
        'Overdue': '#B11E2E'
    }
    
    priority_colors = {
        'Low': '#999',
        'Medium': '#76777E',
        'High': '#B11E2E',
        'Urgent': '#B11E2E'
    }

    status_color = status_colors.get(status, '#999')
    priority_color = priority_colors.get(priority, '#999')

    impacts_html = ''
    if data['question']['impacts']:
        impacts_html = '<div style="margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px;">'
        for impact in data['question']['impacts']:
            impacts_html += f'<span style="background: #E8E4DD; padding: 4px 8px; border-radius: 12px; font-size: 12px;">{impact}</span>'
        impacts_html += '</div>'

    dist_html = ''
    if data['distribution_list']:
        dist_html = '<div style="margin-top: 12px; display: flex; flex-wrap: wrap; gap: 6px;">'
        for dist in data['distribution_list']:
            dist_html += f'<span style="background: #B11E2E; color: white; padding: 4px 8px; border-radius: 3px; font-size: 12px;">{dist}</span>'
        dist_html += '</div>'

    attachments_html = ''
    if data['attachments']['photo_count'] > 0 or data['attachments']['reference_documents']:
        attachments_html = '<div style="margin-top: 16px;"><h4 style="font-family: \'Archivo\', -apple-system, BlinkMacSystemFont, \'Helvetica Neue\', Helvetica, Arial, sans-serif; font-size: 14px; margin-bottom: 8px;">Attachments</h4>'
        if data['attachments']['photo_count'] > 0:
            attachments_html += f'<p style="font-size: 12px; margin-bottom: 8px;"><strong>Photos:</strong> {data["attachments"]["photo_count"]} attached</p>'
        if data['attachments']['reference_documents']:
            attachments_html += '<p style="font-size: 12px;"><strong>References:</strong> ' + ', '.join(data['attachments']['reference_documents']) + '</p>'
        attachments_html += '</div>'

    response_html = ''
    if data['response']['received_date']:
        response_html = f'''
        <div style="margin-top: 24px; padding: 16px; background: #F5F5F5; border-left: 4px solid #4CAF50;">
            <h3 style="font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif; font-size: 16px; margin-bottom: 8px; color: #4CAF50;">Response</h3>
            <p style="font-size: 12px; margin-bottom: 8px;"><strong>Received:</strong> {data['response']['received_date']}</p>
            <p style="font-size: 13px; line-height: 1.6;">{data['response']['summary'] or 'Response received.'}</p>
        </div>
        '''

    days_overdue_text = ''
    if data['response']['days_overdue']:
        days_overdue_text = f" ({data['response']['days_overdue']} days overdue)"

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    {get_inlined_style_tag()}
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{data['rfi_id']} - Request for Information</title>
    <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600&family=Playfair+Display:wght@600;700&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: #FAF7F1;
            color: #14161C;
            line-height: 1.6;
        }}
        @media print {{
            body {{ background: white; }}
            .no-print {{ display: none; }}
        }}
        .letterhead {{
            background-color: #14161C;
            color: white;
            padding: 20px 24px;
            border-bottom: 2px solid #B11E2E;
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
        }}
        .letterhead-left {{
            flex: 1;
        }}
        .letterhead-brand {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-weight: 700;
            font-size: 24px;
            margin-bottom: 4px;
        }}
        .letterhead-star {{ color: #B11E2E; margin-right: 8px; }}
        .letterhead-address {{
            font-size: 11px;
            color: #ccc;
            letter-spacing: 0.05em;
        }}
        .letterhead-right {{
            text-align: right;
        }}
        .letterhead-title {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 18px;
            font-weight: 700;
            margin-bottom: 8px;
        }}
        .container {{
            max-width: 800px;
            margin: 0 auto;
            padding: 24px;
            background: white;
            border-radius: 2px;
        }}
        h1 {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 36px;
            font-weight: 700;
            margin: 24px 0 12px 0;
            color: #14161C;
        }}
        h2 {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 18px;
            font-weight: 700;
            margin-top: 24px;
            margin-bottom: 12px;
            padding-bottom: 8px;
            border-bottom: 2px solid #B11E2E;
            color: #14161C;
        }}
        h3 {{
            font-family: 'Archivo', -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Helvetica, Arial, sans-serif;
            font-size: 14px;
            font-weight: 700;
            margin-bottom: 8px;
        }}
        .eyebrow {{
            font-size: 10px;
            letter-spacing: 0.18em;
            text-transform: uppercase;
            color: #76777E;
            margin-bottom: 8px;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: 600;
            margin-right: 8px;
            margin-bottom: 8px;
        }}
        .status-badge {{
            background: {status_color};
            color: {{'white' if status_color == '#B11E2E' else '#14161C'}};
        }}
        .priority-badge {{
            background: {priority_color};
            color: white;
        }}
        .meta-grid {{
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 12px;
            margin-top: 12px;
        }}
        .meta-item {{
            padding: 8px;
            background: #F5F5F5;
            border-radius: 2px;
            font-size: 12px;
        }}
        .meta-label {{
            font-weight: 600;
            color: #76777E;
            margin-bottom: 4px;
        }}
        .meta-value {{
            font-size: 13px;
            color: #14161C;
        }}
        .section {{
            margin-top: 24px;
            padding: 16px;
            background: #FAFAFA;
            border: 1px solid #E8E4DD;
            border-radius: 2px;
        }}
        .question-box {{
            margin-top: 12px;
            padding: 12px;
            background: white;
            border-left: 4px solid #B11E2E;
            font-style: italic;
            font-size: 13px;
            line-height: 1.6;
        }}
        .two-col {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 12px;
            margin-top: 12px;
        }}
        p {{ margin-bottom: 8px; font-size: 13px; }}
        @media (max-width: 600px) {{
            .container {{ padding: 16px; }}
            .meta-grid {{ grid-template-columns: 1fr; }}
            .two-col {{ grid-template-columns: 1fr; }}
            .letterhead {{ flex-direction: column; }}
            .letterhead-right {{ text-align: left; margin-top: 12px; }}
        }}
    </style>
</head>
<body>
    <div class="letterhead">
        <div class="letterhead-left">
            <div class="letterhead-brand"><span class="letterhead-star">★</span>SUPERSTARS</div>
            <div class="letterhead-address">890 EAST 135TH STREET, BRONX, NY 10454</div>
        </div>
        <div class="letterhead-right">
            <div class="letterhead-title">Request for Information</div>
            <div style="font-size: 12px; color: #ccc;">{data['rfi_id']} • {data['details']['date_submitted']}</div>
            <div style="margin-top: 8px;"><span class="badge status-badge">{status}</span></div>
        </div>
    </div>

    <div class="container">
        <h1>{data['rfi_id']}</h1>
        <p style="font-size: 16px; margin-bottom: 12px;">{data['details']['title']}</p>
        
        <div>
            <span class="badge status-badge">{status}</span>
            <span class="badge priority-badge">{priority}</span>
        </div>

        <div class="meta-grid">
            <div class="meta-item">
                <div class="meta-label">Project</div>
                <div class="meta-value">{data['project']['code']}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Date Submitted</div>
                <div class="meta-value">{data['details']['date_submitted']}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Response Due</div>
                <div class="meta-value">{data['response']['due_date'] or 'N/A'}{days_overdue_text}</div>
            </div>
            <div class="meta-item">
                <div class="meta-label">Status</div>
                <div class="meta-value">{status}</div>
            </div>
        </div>

        <h2>Submitter</h2>
        <div class="two-col">
            <div>
                <p><strong>Name:</strong> {data['submitter']['name']}</p>
                <p><strong>Company:</strong> {data['submitter']['company_trade']}</p>
            </div>
            <div>
                <p><strong>Phone:</strong> {data['submitter']['phone'] or 'N/A'}</p>
                <p><strong>Email:</strong> {data['submitter']['email'] or 'N/A'}</p>
            </div>
        </div>

        <h2>Details</h2>
        <div class="section">
            <div style="margin-bottom: 8px;">
                <div class="eyebrow">Description</div>
                <p>{data['details']['description']}</p>
            </div>
            <div style="margin-top: 12px;">
                <span class="badge" style="background: #E8E4DD; color: #14161C;">{data['details']['category']}</span>
                <span class="eyebrow" style="display: inline-block; margin-left: 8px;">Location: {data['details']['location']}</span>
            </div>
        </div>

        <h2>Question</h2>
        <div class="question-box">
            {data['question']['primary']}
        </div>
        {impacts_html}

        <h2>Distribution</h2>
        {dist_html if dist_html else '<p style="color: #76777E;">No distribution list.</p>'}

        {response_html}

        {attachments_html}

        <div style="margin-top: 32px; padding-top: 16px; border-top: 1px solid #E8E4DD; font-size: 11px; color: #76777E;">
            <p>Generated: {data['metadata']['generated_at']}</p>
        </div>
    </div>
</body>
</html>
'''

    with open(output_html, 'w') as f:
        f.write(html)

    print(f"Rendered {output_html}")

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print("Usage: render_rfi_html.py <json_path> <output_html>")
        sys.exit(1)
    
    render_rfi(sys.argv[1], sys.argv[2])
