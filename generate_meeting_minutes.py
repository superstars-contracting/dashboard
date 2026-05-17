#!/usr/bin/env python3
import json
import argparse
import pandas as pd
import re
from datetime import datetime
from pathlib import Path

STAKEHOLDER_EMAILS = {
    'Susan Park': 'susan.park@superstars.nyc',
    'Robert Caldwell': 'robert.caldwell@superstars.nyc',
    'John Doe': 'john.doe@superstars.nyc',
    'J. Hellman': 'jhellman@acmerealty.com',
    'S. Hartwick': 'hartwick@hartwickeng.com',
    'L. Park': 'lpark@parkdesigns.com',
    'Tony Russo': 'tony@bedrockny.com',
    'Lucy Bertrand': 'lucy@aquasealny.com',
    'Mike Donato': 'mike@verticalaccess.us',
    'Sara Whitfield': 'sara@crowncoat.us',
}

PROJECT_INFO = {
    'SC-2601': {
        'name': '890 E 135th St — Mott Haven Restoration',
        'address': '890 East 135th Street, Bronx, NY 10454'
    }
}


ROLE_EXPANSION = {
    'PM': 'Project Manager',
    'Super': 'Project Superintendent',
    'Foreman': 'Foreman'
}

def parse_semicolon_list(text):
    if not text:
        return []
    return [item.strip() for item in str(text).split(';')]

def parse_attendees(attendees_str):
    """Parse attendees with format: 'Name (Role)' or 'Name (Role – Company)'"""
    if not attendees_str:
        return []
    
    items = [item.strip() for item in str(attendees_str).split(';')]
    result = []
    
    for item in items:
        if not item:
            continue
        
        # Match: "Name (Role – Company)" or "Name (Role)"
        match = re.match(r'^(.+?)\s*\((.+)\)$', item)
        if match:
            name = match.group(1).strip()
            parenthesized = match.group(2).strip()
            
            # Check if contains em-dash or en-dash
            if ' – ' in parenthesized or ' — ' in parenthesized:
                sep = ' – ' if ' – ' in parenthesized else ' — '
                role, company = parenthesized.split(sep, 1)
                role = role.strip()
                company = company.strip()
            else:
                role = parenthesized
                company = ''
                # Check if it's an internal employee role
                if role in ROLE_EXPANSION:
                    company = 'Superstars Contracting'
            
            result.append({
                'name': name,
                'role': role,
                'company': company
            })
        else:
            # No parentheses
            result.append({
                'name': item,
                'role': '',
                'company': ''
            })
    
    return result


def get_email(name):
    return STAKEHOLDER_EMAILS.get(name, f"unknown@superstars.nyc")

def calculate_duration(start_time, end_time):
    if not start_time or not end_time:
        return 0
    try:
        fmt = '%H:%M'
        start = datetime.strptime(str(start_time), fmt)
        end = datetime.strptime(str(end_time), fmt)
        return int((end - start).total_seconds() / 60)
    except:
        return 0

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--meeting_id', required=True)
    parser.add_argument('--ai_transcript', default=None)
    parser.add_argument('--today', default=None)
    parser.add_argument('--output_json', required=True)
    args = parser.parse_args()

    today = datetime.fromisoformat(args.today) if args.today else datetime.now()

    # Read workbook
    mr_df = pd.read_excel(args.workbook, sheet_name='Meeting Records')
    meeting = mr_df[mr_df['Meeting ID'] == args.meeting_id]

    if meeting.empty:
        print(f"VAL-001: Meeting {args.meeting_id} not found")
        exit(1)

    meeting = meeting.iloc[0]

    # Get action items
    try:
        mai_df = pd.read_excel(args.workbook, sheet_name='Meeting Action Items')
        actions = mai_df[mai_df['Meeting ID'] == args.meeting_id].to_dict('records')

        # Update status to Overdue if needed
        for action in actions:
            if pd.notna(action.get('Due Date')) and action.get('Status') not in ('Completed', 'Cancelled'):
                due_date = pd.Timestamp(action['Due Date']).to_pydatetime()
                if due_date < today:
                    action['Status'] = 'Overdue'
    except:
        actions = []

    # Parse AI transcript if provided
    ai_data = {}
    if args.ai_transcript:
        try:
            with open(args.ai_transcript) as f:
                ai_data = json.load(f)
        except:
            ai_data = {}

    # Get day of week
    try:
        date_obj = pd.Timestamp(meeting['Date']).to_pydatetime()
        day_of_week = date_obj.strftime('%A')
    except:
        day_of_week = ''

    # Get project info
    proj = PROJECT_INFO.get(meeting['Project Code'], {'name': '', 'address': ''})

    # Parse attendees
    attendees = parse_attendees(meeting.get('Attendees', ''))

    # Parse decisions
    decisions = parse_semicolon_list(meeting.get('Decisions', ''))

    # Parse distribution list
    dist_names = parse_semicolon_list(meeting.get('Distribution List', ''))
    distribution = [{'name': name, 'email': get_email(name)} for name in dist_names]

    # Get next meeting (same schedule, next week)
    sch_df = pd.read_excel(args.workbook, sheet_name='Meeting Schedule')
    schedule = sch_df[sch_df['Schedule ID'] == meeting['Schedule ID']]
    next_meeting = {}
    if not schedule.empty:
        sch = schedule.iloc[0]
        next_meeting = {
            'type': sch['Meeting Type'],
            'date': '',
            'time': sch['Time'],
            'location': sch['Default Location']
        }

    output = {
        'meeting_id': args.meeting_id,
        'project': {
            'code': meeting['Project Code'],
            'name': proj['name'],
            'address': proj['address']
        },
        'meeting': {
            'type': meeting['Meeting Type'],
            'date': str(meeting['Date'])[:10],
            'day_of_week': day_of_week,
            'time_start': str(meeting['Time Start']),
            'time_end': str(meeting['Time End']),
            'duration_minutes': calculate_duration(meeting['Time Start'], meeting['Time End']),
            'location': meeting['Location'],
            'prepared_by': meeting['Prepared By']
        },
        'attendees': attendees,
        'transcript_source': meeting.get('Transcript Source', ''),
        'summary': meeting.get('Summary', ''),
        'topics_discussed': ai_data.get('topics_discussed', []),
        'decisions': decisions,
        'action_items': [
            {
                'id': a.get('Action ID'),
                'description': a.get('Description'),
                'owner': a.get('Owner'),
                'owner_email': a.get('Owner Email'),
                'due_date': str(a.get('Due Date'))[:10] if pd.notna(a.get('Due Date')) else '',
                'status': a.get('Status'),
                'completion_date': str(a.get('Completion Date'))[:10] if pd.notna(a.get('Completion Date')) else '',
                'notes': a.get('Notes', '')
            }
            for a in actions
        ],
        'next_meeting': next_meeting,
        'distribution_list': distribution,
        'status': meeting.get('Status', ''),
        'metadata': {
            'generated_at': datetime.now().isoformat(),
            'source_workbook': args.workbook,
            'ai_transcript_used': bool(args.ai_transcript),
            'warnings': []
        }
    }

    Path(args.output_json).parent.mkdir(parents=True, exist_ok=True)
    with open(args.output_json, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"✓ Generated {args.output_json}")

if __name__ == '__main__':
    main()
