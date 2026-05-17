import json
import sys
from datetime import datetime

def render_html(talk):
    category_colors = {
        'Fall Protection': '#B11E2E',
        'Scaffold': '#14161C',
        'Site Conditions': '#FF9500',
        'PPE': '#FFA500',
        'Hot Work / Fire Prevention': '#E74C3C',
        'Hazard Comm': '#3498DB',
        'Material Handling': '#9B59B6',
        'Equipment': '#2ECC71',
        'Emergency / General': '#E67E22'
    }
    
    badge_color = category_colors.get(talk['category'], '#666')
    today = datetime.now().strftime('%B %d, %Y')
    
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{talk['title']} - Toolbox Talk</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700&family=DM+Sans:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'DM Sans', sans-serif; line-height: 1.5; color: #14161C; background: #FAF7F1; }}
        @page {{ size: letter portrait; margin: 0.5in; }}
        @media print {{
            body {{ background: white; }}
            .page {{ page-break-after: always; }}
        }}
        .page {{ max-width: 8.5in; margin: 0 auto; background: white; padding: 0.5in; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .letterhead {{ display: flex; justify-content: space-between; align-items: center; background: #14161C; color: white; padding: 0.5in; margin: -0.5in -0.5in 0.75in -0.5in; font-size: 11px; }}
        .letterhead-left {{ font-weight: 600; font-size: 13px; letter-spacing: 1px; }}
        .letterhead-right {{ text-align: right; font-size: 10px; }}
        .header {{ margin-bottom: 1in; }}
        .category-badge {{ display: inline-block; background: {badge_color}; color: white; padding: 0.25in 0.4in; font-size: 9px; font-weight: 600; letter-spacing: 1px; margin-bottom: 0.2in; border-radius: 3px; }}
        .title {{ font-family: 'Playfair Display', serif; font-size: 26px; font-weight: 700; color: #14161C; margin-bottom: 0.3in; line-height: 1.2; }}
        .refs {{ font-size: 10px; color: #666; margin-bottom: 0.4in; }}
        .project-info {{ font-size: 10px; color: #666; }}
        .callout {{ background: #FFF8F0; border-left: 4px solid #B11E2E; padding: 0.4in; margin: 0.5in 0; border-radius: 3px; }}
        .callout-title {{ font-weight: 600; font-size: 9px; letter-spacing: 1px; color: #B11E2E; margin-bottom: 0.15in; }}
        .callout-text {{ font-style: italic; font-size: 11px; line-height: 1.6; }}
        h3 {{ font-family: 'Playfair Display', serif; font-size: 14px; font-weight: 700; margin: 0.4in 0 0.2in 0; color: #14161C; }}
        .practices {{ counter-reset: practice; }}
        .practice {{ display: flex; margin-bottom: 0.2in; font-size: 11px; }}
        .practice-num {{ display: inline-flex; align-items: center; justify-content: center; width: 24px; height: 24px; background: #B11E2E; color: white; border-radius: 50%; font-weight: 600; font-size: 11px; margin-right: 0.3in; flex-shrink: 0; }}
        .practice-text {{ flex: 1; }}
        .ppe-list {{ display: flex; flex-wrap: wrap; gap: 0.2in; margin-bottom: 0.4in; }}
        .ppe-chip {{ background: #E8E4DD; padding: 0.15in 0.3in; border-radius: 20px; font-size: 10px; font-weight: 500; white-space: nowrap; }}
        .questions {{ font-size: 11px; }}
        .question {{ margin-bottom: 0.15in; padding-left: 0.2in; }}
        .question::before {{ content: "•"; color: #B11E2E; font-weight: bold; margin-right: 0.2in; }}
        .inspections {{ font-size: 10px; background: #F5F5F5; padding: 0.3in; border-radius: 3px; margin-bottom: 0.5in; }}
        .signin {{ margin-top: 0.75in; }}
        .signin-title {{ font-weight: 600; font-size: 11px; letter-spacing: 1px; margin-bottom: 0.2in; }}
        table {{ width: 100%; border-collapse: collapse; font-size: 10px; }}
        table th {{ background: #14161C; color: white; padding: 0.15in; text-align: left; font-weight: 600; letter-spacing: 0.5px; }}
        table td {{ border: 1px solid #E8E4DD; padding: 0.15in; }}
        table td:first-child {{ width: 25px; text-align: center; }}
        table td:nth-child(2) {{ width: 35%; }}
        table td:nth-child(3) {{ width: 35%; }}
        table td:nth-child(4) {{ width: 25px; }}
        .footer {{ font-size: 9px; color: #999; margin-top: 0.5in; border-top: 1px solid #E8E4DD; padding-top: 0.3in; text-align: center; line-height: 1.4; }}
    </style>
</head>
<body>
    <div class="page">
        <div class="letterhead">
            <div class="letterhead-left">SUPERSTARS CONTRACTING · TOOLBOX TALK</div>
            <div class="letterhead-right">
                {talk['talk_id']} · {talk['scheduled_for']}<br/>Duration: {talk['duration_estimated']} min
            </div>
        </div>
        
        <div class="header">
            <div class="category-badge">{talk['category'].upper()}</div>
            <div class="title">{talk['title']}</div>
            <div class="refs">
                <strong>DOB:</strong> {talk['dob_reference']} · <strong>OSHA:</strong> {talk['osha_reference']}
            </div>
            <div class="project-info">
                <strong>{talk['project']['name']}</strong><br/>
                Scheduled: {talk['scheduled_for']} · Conducted by: {talk['conducted_by_planned']}
            </div>
        </div>
        
        <div class="callout">
            <div class="callout-title">WHY THIS MATTERS</div>
            <div class="callout-text">{talk['hazards_summary']}</div>
        </div>
        
        <h3>Key Safety Practices</h3>
        <div class="practices">
            {''.join(f'<div class="practice"><div class="practice-num">{i}</div><div class="practice-text">{p}</div></div>' for i, p in enumerate(talk['key_practices'], 1))}
        </div>
        
        <h3>Required PPE</h3>
        <div class="ppe-list">
            {''.join(f'<div class="ppe-chip">{p}</div>' for p in talk['required_ppe'])}
        </div>
        
        <h3>Discussion Questions</h3>
        <div class="questions">
            {''.join(f'<div class="question">{q}</div>' for q in talk['discussion_questions'])}
        </div>
        
        <div class="inspections">
            <strong>Required Inspections:</strong><br/>{talk['required_inspections']}
        </div>
        
        <div class="signin">
            <div class="signin-title">SIGN-IN</div>
            <table>
                <thead><tr><th>#</th><th>Name (Printed)</th><th>Signature</th><th>Time</th></tr></thead>
                <tbody>
                    {''.join(f'<tr><td>{i}</td><td></td><td></td><td></td></tr>' for i in range(1, 13))}
                </tbody>
            </table>
        </div>
        
        <div class="footer">
            Generated {today} · Superstars Contracting Safety Dept · Code references current as of 2026<br/>
            <em>Foreman keeps signed copy for project records.</em>
        </div>
    </div>
</body>
</html>"""
    
    return html

if __name__ == '__main__':
    with open(sys.argv[1]) as f:
        talk = json.load(f)
    html = render_html(talk)
    with open(sys.argv[2], 'w') as f:
        f.write(html)
    print(f"Rendered {sys.argv[2]}")
