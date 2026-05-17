#!/usr/bin/env python3
import json
import argparse
import subprocess
import pandas as pd
from datetime import datetime
from pathlib import Path

def generate_email_draft(meeting_id, recipient_name, recipient_email, summary, actions_for_recipient):
    body = f"""<html><body style='font-family: sans-serif; font-size: 13px; color: #333;'>
<p>Hi {recipient_name},</p>

<p>Please see the attached meeting minutes from {meeting_id}.</p>

<p><strong>Summary excerpt:</strong><br/>
{summary[:200]}{'...' if len(summary) > 200 else ''}</p>

{f'''<p><strong>Your Action Items:</strong><br/>
<table style='border-collapse: collapse; width: 100%; margin: 10px 0;'>
<tr style='background: #f5f5f5;'><th style='border: 1px solid #ddd; padding: 8px; text-align: left;'>ID</th><th style='border: 1px solid #ddd; padding: 8px; text-align: left;'>Description</th><th style='border: 1px solid #ddd; padding: 8px; text-align: left;'>Due</th></tr>
{chr(10).join([f"<tr><td style='border: 1px solid #ddd; padding: 8px;'>{a['id']}</td><td style='border: 1px solid #ddd; padding: 8px;'>{a['description']}</td><td style='border: 1px solid #ddd; padding: 8px;'>{a['due_date']}</td></tr>" for a in actions_for_recipient])}
</table></p>''' if actions_for_recipient else ''}

<p><strong>Full minutes:</strong> See attachment or contact PM.</p>

<p>Best,<br/>Superstars Contracting</p>
</body></html>"""
    return body

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--meeting_id', default=None)
    parser.add_argument('--all-recent', action='store_true')
    parser.add_argument('--actions_dir', required=True)
    parser.add_argument('--today', default=None)
    args = parser.parse_args()

    today = datetime.fromisoformat(args.today) if args.today else datetime.now()
    actions_dir = Path(args.actions_dir)
    actions_dir.mkdir(parents=True, exist_ok=True)

    mr_df = pd.read_excel(args.workbook, sheet_name='Meeting Records')

    meetings_to_process = []
    if args.meeting_id:
        meetings_to_process = [args.meeting_id]
    elif args.all_recent:
        recent = mr_df[mr_df['Status'] == 'Draft'].copy()
        recent['Date'] = pd.to_datetime(recent['Date'])
        recent = recent[recent['Date'] >= (today - pd.Timedelta(days=7))]
        meetings_to_process = recent['Meeting ID'].tolist()

    log = {
        'run_time': datetime.now().isoformat(),
        'meetings_processed': [],
        'errors': []
    }

    for meeting_id in meetings_to_process:
        try:
            meeting = mr_df[mr_df['Meeting ID'] == meeting_id].iloc[0]

            # Generate JSON
            json_path = actions_dir / f"{meeting_id}.json"
            cmd = [
                'python3',
                '/sessions/nifty-loving-johnson/mnt/outputs/generate_meeting_minutes.py',
                '--workbook', args.workbook,
                '--meeting_id', meeting_id,
                '--today', args.today or today.isoformat(),
                '--output_json', str(json_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)

            # Generate HTML
            html_path = actions_dir / f"{meeting_id}.html"
            cmd = [
                'python3',
                '/sessions/nifty-loving-johnson/mnt/outputs/render_meeting_minutes_html.py',
                str(json_path),
                str(html_path)
            ]
            subprocess.run(cmd, check=True, capture_output=True)

            # Load JSON for email generation
            with open(json_path) as f:
                data = json.load(f)

            # Generate email drafts
            email_drafts_dir = actions_dir / 'email_drafts'
            email_drafts_dir.mkdir(exist_ok=True)

            for recipient in data['distribution_list']:
                name = recipient['name']
                email = recipient['email']

                # Find action items for this recipient
                actions_for_recipient = [a for a in data['action_items'] if a['owner'] == name]

                body = generate_email_draft(meeting_id, name, email, data['summary'], actions_for_recipient)

                slug = name.lower().replace(' ', '-').replace('.', '')
                email_file = email_drafts_dir / f"{meeting_id}-to-{slug}.html"
                with open(email_file, 'w') as f:
                    f.write(f"""<html><head><title>Email Draft</title></head><body>
<p><strong>To:</strong> {email}</p>
<p><strong>Subject:</strong> Meeting Minutes — {data['meeting']['type']} · {data['meeting']['date']} · {meeting_id}</p>
<hr/>
{body}
</body></html>""")

            log['meetings_processed'].append({
                'meeting_id': meeting_id,
                'status': 'success',
                'json': str(json_path),
                'html': str(html_path),
                'email_drafts': len(data['distribution_list'])
            })

        except Exception as e:
            log['errors'].append({'meeting_id': meeting_id, 'error': str(e)})

    # Write log
    log_path = actions_dir / 'meeting_workflow_log.json'
    with open(log_path, 'w') as f:
        json.dump(log, f, indent=2)

    print(f"✓ Workflow complete. Log: {log_path}")
    print(f"  Meetings: {len(log['meetings_processed'])}")
    print(f"  Errors: {len(log['errors'])}")

if __name__ == '__main__':
    main()
