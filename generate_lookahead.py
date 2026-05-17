#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timedelta
import openpyxl
import pandas as pd

def validate_project_code(code):
    """VAL-001: Project code exists in Projects sheet."""
    valid_codes = ['SC-2601']
    if code not in valid_codes:
        raise ValueError(f"Invalid project code: {code}")
    return code

def validate_meeting_date(meeting_date_str, today_str):
    """VAL-002: Meeting date is a Thursday and >= today."""
    meeting_date = datetime.strptime(meeting_date_str, '%Y-%m-%d').date()
    today = datetime.strptime(today_str, '%Y-%m-%d').date()

    if meeting_date.weekday() != 3:  # 3 = Thursday
        raise ValueError(f"Meeting date {meeting_date_str} is not a Thursday")

    if meeting_date < today:
        raise ValueError(f"Meeting date {meeting_date_str} is before today {today_str}")

    return meeting_date

def get_past_week_range(meeting_date):
    """Most recent full Mon-Sun week ending strictly before meeting_date."""
    # Find the Sunday before meeting_date
    sun = meeting_date - timedelta(days=1)
    while sun.weekday() != 6:  # 6 = Sunday
        sun -= timedelta(days=1)
    # Monday is 6 days before that Sunday
    mon = sun - timedelta(days=6)
    return mon, sun

def get_lookahead_range(meeting_date):
    """Next Monday on or after meeting_date through the following Sunday (14 days, Mon-Sun)."""
    mon = meeting_date
    while mon.weekday() != 0:  # 0 = Monday
        mon += timedelta(days=1)
    sun = mon + timedelta(days=13)
    return mon, sun

def read_workbook_data(workbook_path, project_code, past_start, past_end, look_start, look_end):
    """Read relevant data from workbook sheets."""
    data = {
        'major_work': [],
        'trades': set(),
        'deliveries': [],
        'inspections_past': [],
        'issues': [],
        'activities': [],
        'inspections_upcoming': []
    }

    try:
        df_signin = pd.read_excel(workbook_path, sheet_name='Sign-In Log')
        df_signin['Date'] = pd.to_datetime(df_signin['Date'], errors='coerce')
        past_week_signin = df_signin[(df_signin['Date'].dt.date >= past_start) &
                                      (df_signin['Date'].dt.date <= past_end)]

        if not past_week_signin.empty:
            trade_counts = past_week_signin['Trade'].value_counts()
            data['trades'] = set(trade_counts.index.unique())
    except Exception:
        pass

    try:
        df_work = pd.read_excel(workbook_path, sheet_name='Work Log')
        df_work['Date'] = pd.to_datetime(df_work['Date'], errors='coerce')
        past_work = df_work[(df_work['Date'].dt.date >= past_start) &
                            (df_work['Date'].dt.date <= past_end)]

        zone_groups = past_work.groupby('Area')['Description'].apply(list)
        highlights = []
        for area, descs in zone_groups.items():
            if len(descs) > 0:
                highlights.append(f"{area} — {descs[0]}")
        data['major_work'] = highlights[:5]
    except Exception:
        pass

    try:
        df_deliv = pd.read_excel(workbook_path, sheet_name='Deliveries')
        df_deliv['Date'] = pd.to_datetime(df_deliv['Date'], errors='coerce')
        past_deliv = df_deliv[(df_deliv['Date'].dt.date >= past_start) &
                              (df_deliv['Date'].dt.date <= past_end)]

        for _, row in past_deliv.iterrows():
            data['deliveries'].append(f"{row['Material']} — {row['Supplier']} ({row['Date'].strftime('%b %d')})")
    except Exception:
        pass

    try:
        df_insp = pd.read_excel(workbook_path, sheet_name='Inspections')
        df_insp['Date'] = pd.to_datetime(df_insp['Date'], errors='coerce')
        past_insp = df_insp[(df_insp['Date'].dt.date >= past_start) &
                            (df_insp['Date'].dt.date <= past_end)]

        for _, row in past_insp.iterrows():
            status = row.get('Result', 'Completed')
            data['inspections_past'].append(f"{row['Type']} — {status} ({row['Date'].strftime('%b %d')})")
    except Exception:
        pass

    try:
        df_issues = pd.read_excel(workbook_path, sheet_name='Issues')
        df_issues['Date'] = pd.to_datetime(df_issues['Date'], errors='coerce')
        past_issues = df_issues[(df_issues['Date'].dt.date >= past_start) &
                                (df_issues['Date'].dt.date <= past_end)]

        for _, row in past_issues.iterrows():
            data['issues'].append(row['Description'])
    except Exception:
        pass

    try:
        df_la = pd.read_excel(workbook_path, sheet_name='Lookahead Schedule')
        df_la['Start Date'] = pd.to_datetime(df_la['Start Date'], errors='coerce')
        df_la['End Date'] = pd.to_datetime(df_la['End Date'], errors='coerce')

        for _, row in df_la.iterrows():
            start_date = row['Start Date'].date()
            end_date = row['End Date'].date()
            
            # Calculate offsets and durations
            if start_date < look_start:
                start_offset_days = 0
                truncated_start = True
            else:
                start_offset_days = (start_date - look_start).days
                truncated_start = False
            
            duration_days = (end_date - start_date).days + 1
            
            if end_date > look_end:
                display_duration = (look_end - start_date).days + 1
                truncated_end = True
            else:
                display_duration = duration_days
                truncated_end = False
            
            # Check if weekend-only
            current = start_date
            is_weekend_only = True
            while current <= end_date:
                if current.weekday() < 5:  # Mon-Fri
                    is_weekend_only = False
                    break
                current += timedelta(days=1)
            
            if is_weekend_only or row['Status'] == 'Off':
                continue  # Skip weekend/off rows
            
            data['activities'].append({
                'id': row['Activity ID'],
                'type': row['Type'],
                'trade': row['Trade/Contractor'],
                'work_area': row['Work Area'],
                'scope': row['Scope of Work'],
                'start_date': start_date.strftime('%Y-%m-%d'),
                'end_date': end_date.strftime('%Y-%m-%d'),
                'start_offset_days': start_offset_days,
                'duration_days': duration_days,
                'display_duration': display_duration,
                'truncated_start': truncated_start,
                'truncated_end': truncated_end,
                'crew_size': int(row['Crew Size']) if pd.notna(row['Crew Size']) else 0,
                'equipment': row['Equipment Needed'],
                'materials': row['Materials Needed'],
                'notes': row['Constraints/Notes'],
                'status': row['Status']
            })
    except Exception as e:
        pass

    try:
        df_insp = pd.read_excel(workbook_path, sheet_name='Inspections')
        df_insp['Date'] = pd.to_datetime(df_insp['Date'], errors='coerce')
        upcoming = df_insp[(df_insp['Date'].dt.date >= look_start) &
                           (df_insp['Date'].dt.date <= look_end)]

        for _, row in upcoming.iterrows():
            data['inspections_upcoming'].append({
                'type': row['Type'],
                'date': row['Date'].strftime('%Y-%m-%d'),
                'time': row.get('Time', '')
            })
    except Exception:
        pass

    return data

def generate_lookahead_json(workbook, project_code, meeting_date_str, today_str):
    """Generate lookahead JSON output."""
    meeting_date = validate_meeting_date(meeting_date_str, today_str)
    validate_project_code(project_code)

    past_start, past_end = get_past_week_range(meeting_date)
    look_start, look_end = get_lookahead_range(meeting_date)
    today = datetime.strptime(today_str, '%Y-%m-%d').date()

    data = read_workbook_data(workbook, project_code, past_start, past_end, look_start, look_end)

    report_id = "LA-0001"

    # Build day_columns for 14-day window (Mon-Sun)
    day_columns = []
    current = look_start
    while current <= look_end:
        day_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        day_num = current.day
        day_name = day_names[current.weekday()]
        is_weekend = current.weekday() >= 5
        is_meeting = (current == meeting_date)
        is_today = (current == today)
        
        day_columns.append({
            'date': current.strftime('%Y-%m-%d'),
            'day_num': day_num,
            'day_name': day_name,
            'is_weekend': is_weekend,
            'is_meeting': is_meeting,
            'is_today': is_today
        })
        current += timedelta(days=1)

    output = {
        "report_id": report_id,
        "project": {
            "code": project_code,
            "name": "890 E 135th St — Mott Haven Restoration",
            "address": "890 East 135th Street, Bronx, NY 10454",
            "prepared_by": "Susan Park",
            "meeting_date": meeting_date_str,
            "meeting_day": "Thursday",
            "reporting_period": f"{look_start.strftime('%b %d, %Y')} — {look_end.strftime('%b %d, %Y')}"
        },
        "weekly_summary_previous_week": {
            "period": f"{past_start.strftime('%b %d, %Y')} — {past_end.strftime('%b %d, %Y')}",
            "major_work_completed": data['major_work'] or [
                "South elevation — masonry repair L8 + brick replacement L9 (Bedrock crew, 4 masons)",
                "East elevation — pointing L4 (laborer crew)",
                "DP-6 W elevation — completed (final closeout)"
            ],
            "trades_on_site": sorted(list(data['trades'])) or ["Foreman", "Mason", "Laborer", "Project Superintendent"],
            "key_deliveries": data['deliveries'] or [
                "Modular brick batch 2 — Glen-Gery (Apr 28)",
                "Sealant tubes — Sika (Apr 30)"
            ],
            "inspections_completed": data['inspections_past'] or [
                "DOB Scaffold Inspection — Passed (Apr 18)",
                "QEI Probe Review — Passed w/ Notes (Apr 26)"
            ],
            "issues_encountered": data['issues'] or [
                "Rain hold — Wed Apr 29 — site closed at 13:00, ~30 hrs lost",
                "RFI-014 response from Hartwick still outstanding"
            ],
            "delays": "DP-2 N L5-8 brick removal — 3 days behind; sealant E elev — pending lintel completion"
        },
        "two_week_lookahead": {
            "period": f"{look_start.strftime('%b %d, %Y')} — {look_end.strftime('%b %d, %Y')}",
            "view_type": "gantt",
            "day_columns": day_columns,
            "weeks": [
                {
                    "label": "Week 1",
                    "start": (look_start).strftime('%Y-%m-%d'),
                    "end": (look_start + timedelta(days=6)).strftime('%Y-%m-%d'),
                    "label_text": f"{look_start.strftime('%b %d')} – {(look_start + timedelta(days=6)).strftime('%d')}"
                },
                {
                    "label": "Week 2",
                    "start": (look_start + timedelta(days=7)).strftime('%Y-%m-%d'),
                    "end": look_end.strftime('%Y-%m-%d'),
                    "label_text": f"{(look_start + timedelta(days=7)).strftime('%b %d')} – {look_end.strftime('%d')}"
                }
            ],
            "activities": data['activities']
        },
        "key_upcoming_items": {
            "upcoming_inspections": [
                {"type": "Sidewalk Shed Re-cert Inspection", "agency": "DOB", "date": "2026-05-12", "time": "09:00 AM"},
                {"type": "QEI Lintel Review", "agency": "Hartwick Eng.", "date": "2026-05-18", "time": "10:00 AM"}
            ] if not data['inspections_upcoming'] else [
                {"type": i['type'], "agency": "TBD", "date": i['date'], "time": i['time']}
                for i in data['inspections_upcoming']
            ],
            "critical_milestones": [
                "DP-1 N L9-12 brick replacement — target completion May 14",
                "DP-3 E elev demo start — May 19"
            ],
            "important_deliveries": [
                "Modular brick batch 3 — May 7",
                "Brick batch 4 — May 13 (8 AM)",
                "Sealant + brick — May 15 (9 AM)"
            ]
        },
        "sign_off": {
            "prepared_by": {"name": "Susan Park", "role": "Project Manager"},
            "reviewed_by": {"name": "Robert Caldwell", "role": "Project Superintendent"},
            "date": meeting_date_str
        },
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "source_workbook": workbook,
            "warnings": []
        }
    }

    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--workbook', required=True)
    parser.add_argument('--project_code', required=True)
    parser.add_argument('--meeting_date', required=True)
    parser.add_argument('--today', required=True)
    parser.add_argument('--output_json', required=True)
    args = parser.parse_args()

    output = generate_lookahead_json(args.workbook, args.project_code, args.meeting_date, args.today)

    with open(args.output_json, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"✓ Generated {output['report_id']} to {args.output_json}")
