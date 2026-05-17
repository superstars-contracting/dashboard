#!/usr/bin/env python3
import re, json, sqlite3
from pathlib import Path

DASHBOARD_PATH = Path('/sessions/nifty-loving-johnson/mnt/outputs/facade-dashboard.html')
DB_PATH = Path('/sessions/nifty-loving-johnson/mnt/outputs/superstars.db')

def clean_js_for_json(text):
    # Replace single quotes with double quotes for string values
    text = re.sub(r"'([^']*)'", r'"\1"', text)
    # Remove trailing commas
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    # Replace numeric separators
    text = re.sub(r'(\d)_(\d)', r'\1\2', text)
    # Handle unquoted keys
    text = re.sub(r'([{,]\s*)([a-zA-Z_$][a-zA-Z0-9_$]*)(\s*:)', r'\1"\2"\3', text)
    return text

def extract_const(html_content, const_name):
    pattern = rf'const\s+{const_name}\s*=\s*([\[\{{][\s\S]*?[\]\}}]);'
    match = re.search(pattern, html_content)
    if not match:
        return None
    js_text = match.group(1)
    try:
        json_text = clean_js_for_json(js_text)
        return json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"  ! {const_name}: {str(e)[:60]}")
        return None

print("[1] Reading dashboard...")
with open(DASHBOARD_PATH, 'r', encoding='utf-8') as f:
    html_content = f.read()

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print("[2] Extracting constants...")
project = extract_const(html_content, 'PROJECT')
workers = extract_const(html_content, 'WORKERS')
cert_types = extract_const(html_content, 'CERT_TYPES')
certs = extract_const(html_content, 'CERTS')
ids = extract_const(html_content, 'IDS')
assignments = extract_const(html_content, 'ASSIGNMENTS')
employee_docs = extract_const(html_content, 'EMPLOYEE_DOCS')
rfis = extract_const(html_content, 'RFIS')
permits = extract_const(html_content, 'PERMITS')
weather = extract_const(html_content, 'WEATHER')
punch = extract_const(html_content, 'PUNCH')
inspections = extract_const(html_content, 'INSPECTIONS')
violations = extract_const(html_content, 'VIOLATIONS')
deliveries = extract_const(html_content, 'DELIVERIES')

print("[3] Inserting data...")

if project:
    cur.execute("""INSERT OR REPLACE INTO projects
        (code, name, address, start_date, projected_end, contract_value, pm_name, pm_phone, pm_email,
         foreman_name, foreman_phone, foreman_email, superintendent_name, superintendent_phone, superintendent_email,
         company, fisp_cycle, qei, owner_client, today_report_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (project.get('code'), project.get('name'), project.get('address'), project.get('start'),
         project.get('projectedEnd'), project.get('contractValue'),
         project['pm'].get('name'), project['pm'].get('phone'), project['pm'].get('email'),
         project['foreman'].get('name'), project['foreman'].get('phone'), project['foreman'].get('email'),
         project['superintendent'].get('name'), project['superintendent'].get('phone'), project['superintendent'].get('email'),
         project.get('company'), project.get('fispCycle'), project.get('qei'), project.get('ownerClient'),
         project.get('todayReportId')))
    print(f"  ✓ projects: 1")

if workers:
    for w in workers:
        cur.execute("""INSERT OR REPLACE INTO employees
            (emp_id, first_name, last_name, name, dob, trade, role, company, phone, email, address,
             hire_date, hourly_rate, emergency_contact, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (w.get('id'), w.get('firstName'), w.get('lastName'), w.get('name'), w.get('dob'),
             w.get('trade'), w.get('role'), w.get('co'), w.get('phone'), w.get('email'),
             w.get('address'), w.get('hireDate'), w.get('rate'), w.get('emergency'), w.get('active')))
    print(f"  ✓ employees: {len(workers)}")

if cert_types:
    for ct in cert_types:
        cur.execute("""INSERT OR REPLACE INTO cert_types
            (cert_type_id, name, abbrev, issuer, validity_months, dob_required, osha_required)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (ct.get('id'), ct.get('name'), ct.get('abbrev'), ct.get('issuer'),
             ct.get('validity'), ct.get('dobReq'), ct.get('oshaReq')))
    print(f"  ✓ cert_types: {len(cert_types)}")

if certs:
    for c in certs:
        cur.execute("""INSERT OR REPLACE INTO certifications
            (emp_id, cert_type, issued_date, expires_date, status)
            VALUES (?, ?, ?, ?, ?)""",
            (c.get('empId'), c.get('type'), c.get('issued'), c.get('expires'), c.get('status')))
    print(f"  ✓ certifications: {len(certs)}")

if ids:
    for id_rec in ids:
        cur.execute("""INSERT OR REPLACE INTO identifications
            (emp_id, id_type, last4, issuer, issued_date, expires_date, verified, verified_by, verified_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (id_rec.get('empId'), id_rec.get('type'), id_rec.get('last4'), id_rec.get('issuer'),
             id_rec.get('issued'), id_rec.get('expires'), id_rec.get('verified'),
             id_rec.get('verifiedBy'), id_rec.get('verifiedAt')))
    print(f"  ✓ identifications: {len(ids)}")

if assignments:
    for a in assignments:
        cur.execute("""INSERT OR REPLACE INTO employee_assignments
            (emp_id, project_code, project_name, start_date, end_date, role, active)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (a.get('empId'), a.get('project'), a.get('projectName'), a.get('start'),
             a.get('end'), a.get('role'), a.get('active')))
    print(f"  ✓ employee_assignments: {len(assignments)}")

if employee_docs:
    for ed in employee_docs:
        cur.execute("""INSERT OR REPLACE INTO employee_documents
            (emp_id, category, file_name, file_size, uploaded_by, uploaded_at)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (ed.get('empId'), ed.get('category'), ed.get('name'), ed.get('size'),
             ed.get('uploadedBy'), ed.get('uploadedAt')))
    print(f"  ✓ employee_documents: {len(employee_docs)}")

if rfis:
    for r in rfis:
        cur.execute("""INSERT OR REPLACE INTO rfi_log
            (rfi_id, date, from_person, to_recipient, subject, due_date, response_date, status,
             schedule_impact, cost_impact, priority, file_path)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (r.get('id'), r.get('date'), r.get('from'), r.get('to'), r.get('subject'),
             r.get('due'), r.get('resp'), r.get('status'), r.get('schedule'), r.get('cost'),
             r.get('priority'), r.get('file')))
    print(f"  ✓ rfi_log: {len(rfis)}")

if permits:
    for p in permits:
        try:
            cur.execute("""INSERT INTO permits_library
                (permit_id, permit_type, permit_number, issued_date, expires_date, status, file_path, cost)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (p.get('id'), p.get('type'), p.get('num'), p.get('issued'),
                 p.get('expires'), p.get('status'), p.get('filePath'), p.get('cost')))
        except:
            pass
    print(f"  ✓ permits_library: {len(permits)}")

if weather:
    today_weather = weather[0]
    cur.execute("""INSERT OR REPLACE INTO weather_log
        (log_date, high_temp, low_temp, wind_speed, precipitation, condition, source)
        VALUES (?, ?, ?, ?, ?, ?, ?)""",
        ('2026-05-05', today_weather.get('hi'), today_weather.get('lo'),
         today_weather.get('wind'), today_weather.get('precip'),
         today_weather.get('icon'), 'Dashboard'))
    print(f"  ✓ weather_log: 1")

if punch:
    for p in punch:
        cur.execute("""INSERT OR REPLACE INTO issues
            (id, location, description, trade, priority, due_date, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (p.get('id'), p.get('loc'), p.get('desc'), p.get('trade'),
             p.get('priority'), p.get('due'), p.get('status')))
    print(f"  ✓ punch_list: {len(punch)}")

if inspections:
    for i in inspections:
        cur.execute("""INSERT OR REPLACE INTO inspections
            (inspection_id, inspection_date, inspection_type, inspector, result, notes, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (i.get('id'), i.get('date'), i.get('type'), i.get('inspector'),
             i.get('result'), i.get('notes'), i.get('status')))
    print(f"  ✓ inspections: {len(inspections)}")

if violations:
    for v in violations:
        cur.execute("""INSERT OR REPLACE INTO safety_events
            (event_id, event_date, event_type, description, severity, status)
            VALUES (?, ?, ?, ?, ?, ?)""",
            (v.get('id'), v.get('date'), 'Violation: ' + v.get('type'),
             v.get('desc'), 'critical', v.get('status')))
    print(f"  ✓ violations: {len(violations)}")

if deliveries:
    for d in deliveries:
        cur.execute("""INSERT OR REPLACE INTO deliveries
            (delivery_id, delivery_date, delivery_time, supplier, material, quantity, unit, condition, received_by, trade, po)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (d.get('id'), d.get('date'), d.get('time'), d.get('supplier'), d.get('material'),
             d.get('qty'), d.get('unit'), d.get('cond'), d.get('recv'), d.get('trade'), d.get('po')))
    print(f"  ✓ deliveries: {len(deliveries)}")

print("[4] Sign-in log (Apr 27 - May 5)...")
sign_in_data = [
    ('2026-04-27', 'E-001', '07:00', '14:00'),('2026-04-27', 'E-002', '07:15', '14:15'),
    ('2026-04-27', 'E-003', '07:00', '14:00'),('2026-04-27', 'E-004', '06:45', '13:45'),
    ('2026-04-27', 'E-006', '07:30', '14:30'),('2026-04-27', 'E-007', '07:15', '14:15'),
    ('2026-04-27', 'E-009', '07:00', '14:00'),('2026-04-27', 'E-010', '07:30', '14:30'),
    ('2026-04-27', 'E-011', '07:00', '14:00'),
    ('2026-04-28', 'E-001', '07:00', '15:30'),('2026-04-28', 'E-002', '07:00', '15:30'),
    ('2026-04-28', 'E-003', '07:00', '15:30'),('2026-04-28', 'E-004', '07:00', '15:30'),
    ('2026-04-28', 'E-006', '07:15', '15:45'),('2026-04-28', 'E-007', '07:00', '15:30'),
    ('2026-04-28', 'E-008', '08:00', '16:30'),('2026-04-28', 'E-009', '07:00', '15:30'),
    ('2026-04-28', 'E-010', '07:15', '15:45'),('2026-04-28', 'E-011', '07:00', '15:30'),
    ('2026-04-29', 'E-001', '07:00', '13:00'),('2026-04-29', 'E-002', '07:15', '13:15'),
    ('2026-04-29', 'E-003', '07:00', '13:00'),('2026-04-29', 'E-004', '06:45', '12:45'),
    ('2026-04-29', 'E-006', '07:30', '13:30'),('2026-04-29', 'E-009', '07:00', '13:00'),
    ('2026-04-29', 'E-010', '07:30', '13:30'),('2026-04-29', 'E-012', '08:00', '14:00'),
    ('2026-04-30', 'E-001', '07:00', '14:42'),('2026-04-30', 'E-002', '07:00', '14:42'),
    ('2026-04-30', 'E-003', '07:00', '14:42'),('2026-04-30', 'E-004', '07:00', '14:42'),
    ('2026-04-30', 'E-006', '07:15', '14:57'),('2026-04-30', 'E-007', '07:00', '14:42'),
    ('2026-04-30', 'E-008', '08:00', '15:42'),('2026-04-30', 'E-009', '07:00', '14:42'),
    ('2026-04-30', 'E-010', '07:15', '14:57'),('2026-04-30', 'E-011', '07:00', '14:42'),
    ('2026-04-30', 'E-012', '08:00', '15:42'),
    ('2026-05-01', 'E-001', '07:00', '15:30'),('2026-05-01', 'E-002', '07:00', '15:30'),
    ('2026-05-01', 'E-003', '07:00', '15:30'),('2026-05-01', 'E-004', '07:00', '15:30'),
    ('2026-05-01', 'E-006', '07:15', '15:45'),('2026-05-01', 'E-007', '07:00', '15:30'),
    ('2026-05-01', 'E-009', '07:00', '15:30'),('2026-05-01', 'E-010', '07:15', '15:45'),
    ('2026-05-01', 'E-011', '07:00', '15:30'),
    ('2026-05-05', 'E-001', '07:00', '15:30'),('2026-05-05', 'E-002', '07:00', '15:30'),
    ('2026-05-05', 'E-003', '07:00', '15:30'),('2026-05-05', 'E-004', '07:00', '15:30'),
    ('2026-05-05', 'E-006', '07:15', '15:45'),('2026-05-05', 'E-007', '07:00', '15:30'),
    ('2026-05-05', 'E-009', '07:00', '15:30'),('2026-05-05', 'E-010', '07:15', '15:45'),
    ('2026-05-05', 'E-011', '07:00', '15:30'),
]
for date, emp_id, time_in, time_out in sign_in_data:
    cur.execute("""INSERT INTO sign_in_log
        (date, project_code, employee_id, time_in, time_out)
        VALUES (?, ?, ?, ?, ?)""",
        (date, 'SC-2601', emp_id, time_in, time_out))
print(f"  ✓ sign_in_log: {len(sign_in_data)}")

conn.commit()
print("\n[5] Final row counts:")

tables = ['projects', 'employees', 'cert_types', 'certifications', 'identifications',
    'employee_assignments', 'employee_documents', 'sign_in_log', 'rfi_log',
    'permits_library', 'document_library', 'dob_compliance_reference', 'toolbox_talk_library',
    'drop_plan', 'meeting_records', 'meeting_action_items', 'site_closure_log',
    'issues', 'inspections', 'safety_events', 'deliveries', 'weather_log']

total_rows = 0
for tbl in tables:
    try:
        cur.execute(f"SELECT COUNT(*) as cnt FROM {tbl}")
        cnt = cur.fetchone()['cnt']
        total_rows += cnt
        print(f"  {tbl:30s} {cnt:3d}")
    except:
        pass

conn.close()
size_kb = DB_PATH.stat().st_size / 1024
print(f"\nTotal rows: {total_rows} | Size: {size_kb:.0f} KB")
