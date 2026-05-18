from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
import logging
import json
import uuid

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
COMPANY_DASHBOARD_PATH = SCRIPT_DIR / "company-dashboard.html"
DASHBOARD_PATH = SCRIPT_DIR / "dashboard-static.html"

app = Flask(__name__, static_folder=str(SCRIPT_DIR), static_url_path='/files')
CORS(app, resources={r"/api/*": {"origins": "*"}})

# Browser-preview blueprint: /preview/* URLs for HTML-first design iteration.
# WeasyPrint stays in render_pdf.py for production export only.
from preview_routes import preview_bp
app.register_blueprint(preview_bp)

# Security: max upload size (20 MB per file). Anything larger is rejected at the WSGI layer.
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024

# Whitelist of allowed file types for worker document uploads
ALLOWED_DOC_MIME_TYPES = {
    'image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp',
    'image/heic', 'image/heif',           # iPhone defaults
    'application/pdf',
}
ALLOWED_DOC_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif', '.pdf'}


# ============= DASHBOARD ROUTES =============

@app.route('/')
def index():
    """Company Overview Console — top-level entry point."""
    if COMPANY_DASHBOARD_PATH.exists():
        return send_file(str(COMPANY_DASHBOARD_PATH))
    # Fallback to project dashboard if company console not yet generated
    return send_file(str(DASHBOARD_PATH))


@app.route('/projects/<project_code>')
def project_dashboard(project_code):
    """Project-specific dashboard. Project context passed via URL → JS reads it from location.pathname."""
    return send_file(str(DASHBOARD_PATH))


@app.route('/dashboard')
def legacy_dashboard():
    """Legacy redirect — old URLs land on the project dashboard for the default project."""
    return send_file(str(DASHBOARD_PATH))


# Logging setup
logging.basicConfig(
    filename=str(SCRIPT_DIR / "server.log"),
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def db():
    # 60s timeout + WAL mode = server reads coexist with batch writers (e.g. nyc_compliance).
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    return conn

def rows_to_dicts(rows):
    return [dict(row) for row in rows]

def response_wrapper(data, count=None):
    """Wrap response with metadata"""
    return jsonify({
        "data": data,
        "meta": {
            "count": count if count is not None else len(data) if isinstance(data, list) else 1,
            "generated_at": datetime.now().isoformat()
        }
    })

# CLAUDE.md rule #2: PINs are derived from phone last-4, so plaintext phones
# and PINs in server.log violate the same PII discipline as pasting them into
# chats. Redact at the logging boundary so the file accumulates only safe data.
_PIN_BEARING_FIELDS = {'phone_or_pin', 'pin', 'phone', 'emergency_contact_phone'}

def _redact_pii(body):
    if not isinstance(body, dict):
        return body
    return {k: ('XXXX' if (k in _PIN_BEARING_FIELDS and v) else v) for k, v in body.items()}

@app.before_request
def log_request():
    body = request.get_json(silent=True) if request.is_json else request.data
    logging.info(f"{request.method} {request.path} | body: {_redact_pii(body)}")

@app.after_request
def log_response(response):
    logging.info(f"Response: {response.status_code}")
    return response

# ============= DASHBOARD META =============

@app.route('/api/health', methods=['GET'])
def health():
    return response_wrapper({
        "status": "ok",
        "db": "superstars.db",
        "timestamp": datetime.now().isoformat()
    })

@app.route('/api/today', methods=['GET'])
def today():
    return response_wrapper({
        "date": date.today().isoformat()
    })

# ============= WRITE HELPERS =============

def get_next_rfi_number(conn, project_code):
    """Auto-generate next RFI number (e.g., RFI-004)"""
    row = conn.execute(
        "SELECT rfi_number FROM rfi_log WHERE project_code = ? ORDER BY rfi_number DESC LIMIT 1",
        (project_code,)
    ).fetchone()
    if not row:
        return "RFI-001"
    last_num = int(row['rfi_number'].split('-')[1])
    return f"RFI-{str(last_num + 1).zfill(3)}"

def validate_employee_exists(conn, employee_id):
    """Validate employee exists"""
    row = conn.execute("SELECT 1 FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
    return row is not None

def validate_project_exists(conn, project_code):
    """Validate project exists"""
    row = conn.execute("SELECT 1 FROM projects WHERE project_code = ?", (project_code,)).fetchone()
    return row is not None

# ============= SIGN-IN LOG ENDPOINTS =============

@app.route('/api/sign-ins', methods=['POST'])
def create_sign_in():
    """Create new sign-in record"""
    try:
        data = request.get_json()
        employee_id = data.get('employee_id')
        project_code = data.get('project_code')
        date_str = data.get('date', date.today().isoformat())
        time_in = data.get('time_in')
        
        conn = db()
        
        # Validate FKs
        if not validate_employee_exists(conn, employee_id):
            conn.close()
            return jsonify({"error": "Employee not found"}), 400
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        
        # Insert
        conn.execute(
            "INSERT INTO sign_in_log (date, employee_id, project_code, time_in, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (date_str, employee_id, project_code, time_in, datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()
        
        # Fetch created record
        new_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
        row = conn.execute("SELECT * FROM sign_in_log WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/sign-ins: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/sign-ins/<int:sign_in_id>', methods=['PATCH'])
def update_sign_in(sign_in_id):
    """Update sign-out time"""
    try:
        data = request.get_json()
        time_out = data.get('time_out')
        
        conn = db()
        conn.execute(
            "UPDATE sign_in_log SET time_out = ?, updated_at = ? WHERE id = ?",
            (time_out, datetime.now().isoformat(), sign_in_id)
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM sign_in_log WHERE id = ?", (sign_in_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============= RFI ENDPOINTS =============

@app.route('/api/rfis', methods=['POST'])
def create_rfi():
    """Create new RFI"""
    try:
        data = request.get_json()
        project_code = data.get('project_code')
        
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        
        # Generate RFI number
        rfi_number = get_next_rfi_number(conn, project_code)
        
        # Calculate due date based on priority
        priority = data.get('priority', 'Standard')
        due_days = {'Urgent': 2, 'High': 5, 'Standard': 10}.get(priority, 10)
        due_date = (date.today() + timedelta(days=due_days)).isoformat()
        
        # Insert
        conn.execute(
            "INSERT INTO rfi_log (rfi_number, project_code, date_submitted, submitted_by, discipline, "
            "description, status, due_date, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'Open', ?, ?, ?)",
            (rfi_number, project_code, date.today().isoformat(), data.get('submitted_by'),
             data.get('discipline'), data.get('description'), due_date,
             datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM rfi_log WHERE rfi_number = ?", (rfi_number,)).fetchone()
        result = dict(row) if row else {"rfi_number": rfi_number}
        conn.close()
        
        return response_wrapper(result), 201
    except Exception as e:
        logging.error(f"POST /api/rfis: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/rfis/<rfi_id>', methods=['PATCH'])
def update_rfi(rfi_id):
    """Update RFI status/response"""
    try:
        data = request.get_json()
        updates = []
        params = []
        
        for key in ['status', 'response', 'response_date']:
            if key in data:
                updates.append(f"{key} = ?")
                params.append(data[key])
        
        updates.append("updated_at = ?")
        params.append(datetime.now().isoformat())
        params.append(rfi_id)
        
        conn = db()
        conn.execute(f"UPDATE rfi_log SET {', '.join(updates)} WHERE rfi_number = ?", params)
        conn.commit()
        
        row = conn.execute("SELECT * FROM rfi_log WHERE rfi_number = ?", (rfi_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row) if row else {}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============= SITE CLOSURE ENDPOINTS =============

@app.route('/api/site-closures', methods=['POST'])
def create_site_closure():
    """Create new site closure record"""
    try:
        data = request.get_json()
        project_code = data.get('project_code')
        
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        
        closure_id = f"SC-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        # Build checklist values
        checklist = data.get('checklist', {})
        cols = ['closure_id', 'date', 'project_code', 'foreman_id', 'time_of_close', 'weather_at_close',
                'equipment_left_overnight', 'created_at', 'updated_at']
        vals = [closure_id, data.get('date'), project_code, data.get('foreman_id'),
                data.get('time_of_close'), data.get('weather_at_close'),
                data.get('equipment_left_overnight'), datetime.now().isoformat(), datetime.now().isoformat()]
        
        # Add checklist items
        checklist_keys = [
            'personnel_all_signed_out', 'personnel_visitors_escorted', 'personnel_no_remaining',
            'equipment_tools_secured', 'equipment_scaffold_locked', 'equipment_compressors_secured',
            'equipment_mast_climbers_locked', 'fire_watch_completed', 'fire_heat_sources_cool',
            'fire_extinguishers_ready', 'dust_collection_sealed', 'dust_storage_sealed',
            'dust_tarps_secure', 'water_penetrations_covered', 'water_window_protection',
            'security_access_locked', 'security_fence_secured', 'security_sidewalk_clear',
            'building_doors_locked', 'building_roof_locked', 'climate_hvac_undisturbed',
            'climate_storage_sealed', 'doc_daily_report', 'doc_photos_taken'
        ]
        
        for key in checklist_keys:
            cols.append(key)
            vals.append(checklist.get(key, 'N'))
        
        placeholders = ', '.join(['?' for _ in vals])
        conn.execute(
            f"INSERT INTO site_closure_log ({', '.join(cols)}) VALUES ({placeholders})",
            vals
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM site_closure_log WHERE closure_id = ?", (closure_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row) if row else {"closure_id": closure_id}), 201
    except Exception as e:
        logging.error(f"POST /api/site-closures: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/site-closures/<closure_id>/checklist', methods=['PATCH'])
def update_closure_checklist(closure_id):
    """Update single checklist item"""
    try:
        data = request.get_json()
        item = data.get('item')
        value = data.get('value')
        
        conn = db()
        conn.execute(
            f"UPDATE site_closure_log SET {item} = ?, updated_at = ? WHERE closure_id = ?",
            (value, datetime.now().isoformat(), closure_id)
        )
        conn.commit()
        conn.close()
        
        return response_wrapper({"item": item, "value": value}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============= DROP PLAN ENDPOINTS =============

@app.route('/api/drops/<drop_id>/status', methods=['PATCH'])
def update_drop_status(drop_id):
    """Update drop plan status"""
    try:
        data = request.get_json()
        status = data.get('status')
        
        conn = db()
        conn.execute(
            "UPDATE drop_plan SET status = ?, updated_at = ? WHERE drop_id = ?",
            (status, datetime.now().isoformat(), drop_id)
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM drop_plan WHERE drop_id = ?", (drop_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row) if row else {}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============= ACTION ITEM ENDPOINTS =============

@app.route('/api/action-items/<int:action_id>/status', methods=['PATCH'])
def update_action_item_status(action_id):
    """Update action item status"""
    try:
        data = request.get_json()
        status = data.get('status')
        completion_date = data.get('completion_date')
        
        conn = db()
        conn.execute(
            "UPDATE meeting_action_items SET status = ?, completion_date = ?, updated_at = ? WHERE id = ?",
            (status, completion_date, datetime.now().isoformat(), action_id)
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM meeting_action_items WHERE id = ?", (action_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row) if row else {}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============= EMPLOYEE ENDPOINTS =============

@app.route('/api/employees', methods=['POST'])
def create_employee():
    """Create new employee"""
    try:
        data = request.get_json()
        employee_id = data.get('employee_id') or str(uuid.uuid4())[:8]
        name = data.get('name')
        trade = data.get('trade')
        
        conn = db()
        conn.execute(
            "INSERT INTO employees (employee_id, name, trade, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (employee_id, name, trade, datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()
        
        row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row) if row else {"employee_id": employee_id}), 201
    except Exception as e:
        logging.error(f"POST /api/employees: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/employees/<emp_id>', methods=['PATCH'])
def update_employee(emp_id):
    """Update employee"""
    try:
        data = request.get_json()
        updates = []
        params = []
        
        for key in ['name', 'trade']:
            if key in data:
                updates.append(f"{key} = ?")
                params.append(data[key])
        
        if updates:
            updates.append("updated_at = ?")
            params.append(datetime.now().isoformat())
            params.append(emp_id)
            
            conn = db()
            conn.execute(f"UPDATE employees SET {', '.join(updates)} WHERE employee_id = ?", params)
            conn.commit()
            
            row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (emp_id,)).fetchone()
            conn.close()
            
            return response_wrapper(dict(row) if row else {}), 200
        
        return jsonify({"error": "No fields to update"}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============= CERTIFICATION ENDPOINTS =============

@app.route('/api/certifications', methods=['POST'])
def create_certification():
    """Create new certification"""
    try:
        data = request.get_json()
        employee_id = data.get('employee_id')
        cert_type_id = data.get('cert_type_id')
        
        conn = db()
        if not validate_employee_exists(conn, employee_id):
            conn.close()
            return jsonify({"error": "Employee not found"}), 400
        
        conn.execute(
            "INSERT INTO certifications (employee_id, cert_type_id, expiration_date, file_path, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (employee_id, cert_type_id, data.get('expiration_date'), data.get('file_path'),
             datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()
        
        new_id = conn.execute("SELECT last_insert_rowid() as id").fetchone()['id']
        row = conn.execute("SELECT * FROM certifications WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row) if row else {}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ============= EXISTING READ ENDPOINTS (abbreviated) =============

@app.route('/api/projects', methods=['GET'])
def get_projects():
    conn = db()
    rows = conn.execute("SELECT * FROM projects").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/projects/<code>', methods=['GET'])
def get_project(code):
    conn = db()
    row = conn.execute("SELECT * FROM projects WHERE project_code = ?", (code,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Project not found"}), 404
    conn.close()
    return response_wrapper(dict(row))

@app.route('/api/employees', methods=['GET'])
def get_employees():
    conn = db()
    rows = conn.execute("SELECT * FROM employees").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/employees/<emp_id>', methods=['GET'])
def get_employee(emp_id):
    conn = db()
    emp_row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (emp_id,)).fetchone()
    if not emp_row:
        conn.close()
        return jsonify({"error": "Employee not found"}), 404
    
    employee = dict(emp_row)
    cert_rows = conn.execute(
        "SELECT c.*, ct.name as cert_name FROM certifications c LEFT JOIN cert_types ct ON c.cert_type_id = ct.cert_type_id WHERE c.employee_id = ?",
        (emp_id,)
    ).fetchall()
    employee['certifications'] = rows_to_dicts(cert_rows)
    conn.close()
    return response_wrapper(employee)

@app.route('/api/certifications', methods=['GET'])
def get_certifications():
    conn = db()
    rows = conn.execute(
        "SELECT c.*, ct.name as cert_name FROM certifications c LEFT JOIN cert_types ct ON c.cert_type_id = ct.cert_type_id ORDER BY c.expiration_date"
    ).fetchall()
    conn.close()
    certs = rows_to_dicts(rows)
    today = date.today().isoformat()
    for cert in certs:
        if cert.get('expiration_date'):
            cert['computed_status'] = 'Expired' if cert['expiration_date'] < today else 'Expiring Soon' if cert['expiration_date'] <= today else 'Active'
    return response_wrapper(certs, len(certs))

@app.route('/api/sign-ins', methods=['GET'])
def get_sign_ins():
    conn = db()
    rows = conn.execute(
        "SELECT s.*, e.name FROM sign_in_log s LEFT JOIN employees e ON s.employee_id = e.employee_id ORDER BY s.date DESC"
    ).fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/rfis', methods=['GET'])
def get_rfis():
    conn = db()
    rows = conn.execute("SELECT * FROM rfi_log ORDER BY date_submitted DESC").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/rfis/<rfi_id>', methods=['GET'])
def get_rfi(rfi_id):
    conn = db()
    row = conn.execute("SELECT * FROM rfi_log WHERE rfi_number = ?", (rfi_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "RFI not found"}), 404
    return response_wrapper(dict(row))

@app.route('/api/drops', methods=['GET'])
def get_drops():
    conn = db()
    rows = conn.execute("SELECT * FROM drop_plan ORDER BY planned_start_date").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/drops/<drop_id>', methods=['GET'])
def get_drop(drop_id):
    conn = db()
    row = conn.execute("SELECT * FROM drop_plan WHERE drop_id = ?", (drop_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Drop not found"}), 404
    return response_wrapper(dict(row))

@app.route('/api/site-closures', methods=['GET'])
def get_site_closures():
    conn = db()
    rows = conn.execute("SELECT * FROM site_closure_log ORDER BY date DESC").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/site-closures/<closure_id>', methods=['GET'])
def get_site_closure(closure_id):
    conn = db()
    row = conn.execute("SELECT * FROM site_closure_log WHERE closure_id = ?", (closure_id,)).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "Closure not found"}), 404
    return response_wrapper(dict(row))

@app.route('/api/permits', methods=['GET'])
def get_permits():
    conn = db()
    rows = conn.execute("SELECT * FROM permits_library ORDER BY expiration_date").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/documents', methods=['GET'])
def get_documents():
    conn = db()
    rows = conn.execute("SELECT * FROM document_library ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/toolbox-talks', methods=['GET'])
def get_toolbox_talks():
    conn = db()
    rows = conn.execute("SELECT * FROM toolbox_talk_library ORDER BY title").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/meetings', methods=['GET'])
def get_meetings():
    conn = db()
    rows = conn.execute("SELECT * FROM meeting_records ORDER BY date DESC").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/meetings/<meeting_id>', methods=['GET'])
def get_meeting(meeting_id):
    conn = db()
    row = conn.execute("SELECT * FROM meeting_records WHERE meeting_id = ?", (meeting_id,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "Meeting not found"}), 404
    meeting = dict(row)
    action_rows = conn.execute("SELECT * FROM meeting_action_items WHERE meeting_id = ?", (meeting_id,)).fetchall()
    meeting['action_items'] = rows_to_dicts(action_rows)
    conn.close()
    return response_wrapper(meeting)

@app.route('/api/action-items', methods=['GET'])
def get_action_items():
    conn = db()
    rows = conn.execute("SELECT * FROM meeting_action_items ORDER BY due_date").fetchall()
    conn.close()
    return response_wrapper(rows_to_dicts(rows), len(rows))

@app.route('/api/drops/<drop_id>/sign-off', methods=['POST'])
def sign_off_drop(drop_id):
    """Record drop plan sign-off"""
    try:
        data = request.get_json()
        role = data.get('role')  # 'Foreman', 'Super', 'QEI'
        signed_by_employee_id = data.get('signed_by_employee_id')
        sign_off_date = data.get('date', date.today().isoformat())
        
        conn = db()
        
        # Update drop_plan sign_off_status
        conn.execute(
            "UPDATE drop_plan SET sign_off_status = 'Complete', updated_at = ? WHERE drop_id = ?",
            (datetime.now().isoformat(), drop_id)
        )
        
        # Insert sign-off record (if table exists) or just log it
        try:
            conn.execute(
                "INSERT INTO drop_plan_sign_offs (drop_id, role, signed_by_employee_id, date, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (drop_id, role, signed_by_employee_id, sign_off_date, datetime.now().isoformat())
            )
        except:
            pass  # Table may not exist yet
        
        conn.commit()
        row = conn.execute("SELECT * FROM drop_plan WHERE drop_id = ?", (drop_id,)).fetchone()
        conn.close()
        
        return response_wrapper(dict(row)), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ============= WORKER APP ENDPOINTS =============

@app.route('/api/worker/login', methods=['POST'])
def worker_login():
    """Worker sign-in: PIN + geofence validation.

    DB-backed lookup replaces the hardcoded sample-data dict that previously
    gated auth — that dict was migration scaffolding from before real workers
    were imported. PINs now resolve against employees.pin, derived at import
    time from the worker's phone last-4 (see import_workers.py)."""
    try:
        data = request.get_json(silent=True) or {}
        pin = (data.get('phone_or_pin') or '').strip()
        latitude = float(data.get('latitude', 0))
        longitude = float(data.get('longitude', 0))

        if len(pin) != 4 or not pin.isdigit():
            return jsonify({"error": "Invalid PIN"}), 401

        conn = db()
        rows = conn.execute(
            "SELECT employee_id, name FROM employees "
            "WHERE pin = ? AND pin IS NOT NULL AND pin != ''",
            (pin,)
        ).fetchall()

        if len(rows) == 0:
            conn.close()
            return jsonify({"error": "Invalid PIN"}), 401
        if len(rows) > 1:
            # import_workers.py blocks PIN collisions pre-flight, so this branch
            # is defensive — never auth on ambiguity, log for investigation.
            app.logger.error(
                f"PIN collision in employees: {len(rows)} matches for given PIN"
            )
            conn.close()
            return jsonify({"error": "Authentication failed"}), 500
        emp = dict(rows[0])

        # TESTING AFFORDANCE — remove post-Monday cleanup. The bypass_geofence
        # flag is intentionally trusted from the client because we have no
        # separate test environment. Tracked for removal in task #11.
        bypass_geofence = bool(data.get('bypass_geofence'))
        if bypass_geofence:
            app.logger.warning(
                f"Geofence bypassed via testing flag for employee_id={emp['employee_id']}"
            )
        else:
            # Validate geofence (Bronx project: 40.8083, -73.9162)
            PROJECT_LAT, PROJECT_LNG = 40.8083, -73.9162
            R = 6371000  # Earth radius meters
            dLat = (latitude - PROJECT_LAT) * 3.14159 / 180
            dLng = (longitude - PROJECT_LNG) * 3.14159 / 180
            a = (dLat/2)**2 + (dLng/2)**2
            distance = R * 2 * (a**0.5)

            # Production geofence per project lat/lng accuracy. Previously relaxed
            # to 100 miles for cross-borough testing.
            if distance > 200:
                conn.close()
                return jsonify({"error": "Not on site", "distance": round(distance)}), 403

        cert_rows = conn.execute(
            "SELECT c.*, ct.name as cert_name FROM certifications c "
            "LEFT JOIN cert_types ct ON c.cert_type_id = ct.cert_type_id "
            "WHERE c.employee_id = ? ORDER BY c.expiration_date",
            (emp['employee_id'],)
        ).fetchall()
        conn.close()

        certs = rows_to_dicts(cert_rows)
        today = date.today().isoformat()

        # Test-day workers have no certs imported yet — once Phase D lands, the
        # existing expiration gate enforces real eligibility. A separate task
        # tracks refactoring the gate to CoF-prereq-only semantics.
        if certs:
            expired = [c for c in certs if c.get('expiration_date', '') < today]
            if expired:
                return jsonify({
                    "error": "Certification expired",
                    "cert": expired[0].get('cert_name')
                }), 403

        return response_wrapper({
            "employee_id": emp['employee_id'],
            "name": emp['name'],
            "session_token": f"TOKEN-{uuid.uuid4().hex[:12]}",
            "project_code": "SC-2601",
            "certifications": certs
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/worker/session/start', methods=['POST'])
def worker_session_start():
    """Record shift start in sign_in_log.

    Mirrors the column set used by POST /api/sign-ins so the schema-mismatch
    INSERT (latitude/longitude/start_time columns that don't exist) no longer
    silently breaks the worker-app sign-in flow."""
    try:
        data = request.get_json(silent=True) or {}
        employee_id = data.get('employee_id')
        project_code = data.get('project_code') or 'SC-2601'
        now_iso = datetime.now().isoformat()
        today = date.today().isoformat()

        conn = db()
        cursor = conn.execute(
            "INSERT INTO sign_in_log (date, employee_id, project_code, time_in, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (today, employee_id, project_code, now_iso, now_iso, now_iso)
        )
        sign_in_log_id = cursor.lastrowid
        conn.commit()
        conn.close()

        return response_wrapper({
            "sign_in_log_id": sign_in_log_id,
            "employee_id": employee_id,
            "project_code": project_code,
            "time_in": now_iso
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/worker/session/end', methods=['POST'])
def worker_session_end():
    """Record shift end by closing the most recent open sign_in_log row for
    this employee today.

    The schema has no session_id column, so we identify the row via
    (employee_id, today's date, time_out IS NULL) and close the most recent."""
    try:
        data = request.get_json(silent=True) or {}
        employee_id = data.get('employee_id')
        if not employee_id:
            return jsonify({"error": "employee_id required"}), 400
        now_iso = datetime.now().isoformat()
        # SQLite DATE('now') is UTC; worker_session_start stores Python's local
        # date.today(). Mismatch means a session opened locally before midnight
        # UTC can't be found by DATE('now') — pass the local date explicitly.
        today = date.today().isoformat()

        conn = db()
        row = conn.execute(
            "SELECT id FROM sign_in_log "
            "WHERE employee_id = ? AND date = ? AND time_out IS NULL "
            "ORDER BY id DESC LIMIT 1",
            (employee_id, today)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "No open session found for today"}), 404

        sign_in_log_id = row['id']
        conn.execute(
            "UPDATE sign_in_log SET time_out = ?, updated_at = ? WHERE id = ?",
            (now_iso, now_iso, sign_in_log_id)
        )
        conn.commit()
        conn.close()

        return response_wrapper({
            "sign_in_log_id": sign_in_log_id,
            "employee_id": employee_id,
            "time_out": now_iso
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/worker/session/<session_id>', methods=['GET'])
def get_worker_session(session_id):
    """Get active session info"""
    try:
        conn = db()
        row = conn.execute(
            "SELECT * FROM sign_in_log WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        conn.close()
        
        if not row:
            return jsonify({"error": "Session not found"}), 404
        
        return response_wrapper(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/api/photos/upload', methods=['POST'])
def upload_photo():
    """Upload worker photo"""
    try:
        session_id = request.form.get('session_id')
        zone = request.form.get('zone', 'Unknown')
        scope = request.form.get('scope', 'other')
        
        if 'photo' not in request.files:
            return jsonify({"error": "No photo file"}), 400
        
        photo_file = request.files['photo']
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        photo_id = f"PHOTO-{uuid.uuid4().hex[:8]}"
        
        # Save to data_room/photos/SC-2601/{date}/{zone}/
        today = date.today().isoformat()
        photo_dir = SCRIPT_DIR / "data_room" / "photos" / "SC-2601" / today / zone
        photo_dir.mkdir(parents=True, exist_ok=True)
        
        filename = f"{session_id}_{timestamp}.jpg"
        filepath = photo_dir / filename
        photo_file.save(str(filepath))
        
        # Log metadata
        conn = db()
        try:
            conn.execute(
                "INSERT INTO photos (photo_id, session_id, zone, scope, filepath, latitude, longitude, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (photo_id, session_id, zone, scope, str(filepath), 
                 request.form.get('latitude', 0), request.form.get('longitude', 0),
                 datetime.now().isoformat())
            )
            conn.commit()
        except:
            pass  # Table may not exist yet
        conn.close()
        
        return response_wrapper({
            "photo_id": photo_id,
            "filepath": str(filepath),
            "zone": zone,
            "scope": scope
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/photos', methods=['GET'])
def get_photos():
    """Get photos for a date/project"""
    try:
        date_filter = request.args.get('date', date.today().isoformat())
        project_code = request.args.get('project', 'SC-2601')
        
        conn = db()
        rows = conn.execute(
            "SELECT * FROM photos WHERE DATE(created_at) = ? ORDER BY created_at DESC",
            (date_filter,)
        ).fetchall()
        conn.close()
        
        return response_wrapper(rows_to_dicts(rows) if rows else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 400
# ============= PROJECTS (Company Console) =============

@app.route('/api/projects', methods=['GET'])
def api_projects_list():
    """All projects + counts for the Company Console grid."""
    try:
        conn = db()
        rows = conn.execute(
            "SELECT * FROM projects ORDER BY status, name"
        ).fetchall()
        out = []
        for r in rows:
            project_code = r["project_code"]
            assigned_count = conn.execute(
                "SELECT COUNT(*) FROM project_assignments WHERE project_code = ? AND status = 'active'",
                (project_code,)
            ).fetchone()[0]
            out.append({**dict(r), "assigned_workers": assigned_count})
        conn.close()
        return response_wrapper(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/projects/<project_code>/workers', methods=['GET'])
def api_project_workers(project_code):
    """Workers ASSIGNED to a specific project (the filtered roster for the project dashboard)."""
    try:
        conn = db()
        rows = conn.execute(
            """SELECT e.*, pa.role_on_project, pa.start_date AS assignment_start, pa.status AS assignment_status
               FROM employees e
               JOIN project_assignments pa ON pa.employee_id = e.employee_id
               WHERE pa.project_code = ? AND pa.status = 'active'
               ORDER BY e.name""",
            (project_code,)
        ).fetchall()

        today = datetime.utcnow().date().isoformat()
        d30 = (datetime.utcnow() + timedelta(days=30)).date().isoformat()
        out = []
        for e in rows:
            doc_count = conn.execute(
                "SELECT COUNT(*) FROM worker_documents WHERE employee_id = ?", (e["employee_id"],)
            ).fetchone()[0]
            certs = conn.execute(
                "SELECT cert_type_id, expiration_date, status FROM certifications WHERE employee_id = ?",
                (e["employee_id"],)
            ).fetchall()
            cert_count = len(certs)
            expiring_30 = sum(1 for c in certs if c["expiration_date"] and today <= c["expiration_date"] <= d30)
            expired = sum(1 for c in certs if c["expiration_date"] and c["expiration_date"] < today)
            out.append({**dict(e), "doc_count": doc_count, "cert_count": cert_count,
                        "certs_expiring_30d": expiring_30, "certs_expired": expired})
        conn.close()
        return response_wrapper(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/projects/<project_code>/assign', methods=['POST'])
def api_project_assign(project_code):
    """Assign an existing worker to a project. Body: {employee_id, role_on_project}."""
    try:
        data = request.get_json(silent=True) or {}
        employee_id = data.get("employee_id")
        if not employee_id:
            return jsonify({"error": "employee_id required"}), 400
        conn = db()
        # Skip if already assigned and active
        existing = conn.execute(
            "SELECT id FROM project_assignments WHERE project_code = ? AND employee_id = ? AND status = 'active'",
            (project_code, employee_id)
        ).fetchone()
        if existing:
            conn.close()
            return response_wrapper({"assignment_id": existing["id"], "already_assigned": True})
        cur = conn.execute(
            """INSERT INTO project_assignments
               (project_code, employee_id, role_on_project, start_date, status)
               VALUES (?, ?, ?, DATE('now'), 'active')""",
            (project_code, employee_id, data.get("role_on_project"))
        )
        aid = cur.lastrowid
        conn.commit()
        conn.close()
        return response_wrapper({"assignment_id": aid})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/company/summary', methods=['GET'])
def api_company_summary():
    """Roll-up metrics for the Company Overview top-of-page banner."""
    try:
        conn = db()
        total_workers = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
        active_projects = conn.execute(
            "SELECT COUNT(*) FROM projects WHERE status = 'active' OR status IS NULL"
        ).fetchone()[0]
        all_projects = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]

        today = datetime.utcnow().date().isoformat()
        d30 = (datetime.utcnow() + timedelta(days=30)).date().isoformat()
        certs = conn.execute(
            "SELECT expiration_date, status FROM certifications"
        ).fetchall()
        valid = expiring_30 = expired = 0
        for c in certs:
            if c["status"] and c["status"].lower() in ("revoked", "expired", "void"):
                continue
            exp = c["expiration_date"]
            if not exp:
                valid += 1
            elif exp < today:
                expired += 1
            elif exp <= d30:
                expiring_30 += 1
                valid += 1   # still valid but flagged
            else:
                valid += 1
        conn.close()
        return response_wrapper({
            "total_workers": total_workers,
            "active_projects": active_projects,
            "all_projects": all_projects,
            "certs": {"valid": valid, "expiring_30d": expiring_30, "expired": expired,
                      "total": valid + expired}
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============= WORKER INTAKE =============

import re
import shutil

WORKER_RECORDS_DIR = SCRIPT_DIR / "worker_records"
WORKER_RECORDS_DIR.mkdir(exist_ok=True)


def slugify_name(name):
    """Convert worker name to safe folder name. 'José Vargas' -> 'Jose_Vargas'."""
    if not name:
        return "unknown"
    # Normalize accented chars to ASCII
    import unicodedata
    normalized = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode('ascii')
    # Replace whitespace runs with underscore, strip non-safe chars
    cleaned = re.sub(r'[^A-Za-z0-9 _-]', '', normalized)
    return re.sub(r'\s+', '_', cleaned).strip('_') or "unknown"


def next_employee_id():
    """Generate next E-XXXXX employee ID. Uses NUMERIC max (not lexicographic)
    so mixed-width existing IDs (E-001, E-012, E-00013) all sort correctly."""
    conn = db()
    # Cast the numeric suffix to INTEGER for proper max calculation
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(employee_id, 3) AS INTEGER)) AS max_n "
        "FROM employees WHERE employee_id LIKE 'E-%'"
    ).fetchone()
    conn.close()
    max_n = (row["max_n"] if row and row["max_n"] is not None else 0)
    return f"E-{max_n+1:05d}"


@app.route('/api/workers/create', methods=['POST'])
def api_worker_create():
    """Create a new worker record + worker folder. Returns the new employee_id + folder path."""
    try:
        data = request.get_json(silent=True) or {}
        name = (data.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name is required"}), 400

        employee_id = data.get("employee_id") or next_employee_id()
        folder_slug = slugify_name(name)
        folder = WORKER_RECORDS_DIR / f"{employee_id}_{folder_slug}"
        (folder / "id").mkdir(parents=True, exist_ok=True)
        (folder / "certs").mkdir(parents=True, exist_ok=True)

        conn = db()
        # Try INSERT — fails silently if employee_id already exists
        cursor = conn.execute(
            """INSERT OR IGNORE INTO employees
               (employee_id, name, trade, dob, phone, email,
                emergency_contact_name, emergency_contact_phone, emergency_contact_relation,
                language, hire_date, pin, folder_path, intake_status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                employee_id, name, data.get("trade"),
                data.get("dob"), data.get("phone"), data.get("email"),
                data.get("emergency_contact_name"), data.get("emergency_contact_phone"),
                data.get("emergency_contact_relation"),
                data.get("language"), data.get("hire_date"), data.get("pin"),
                str(folder), "pending"
            )
        )
        # Only UPDATE if the INSERT didn't fire (i.e., the row already existed AND caller
        # explicitly passed this employee_id). New auto-generated IDs should never collide,
        # so this branch is only for caller-supplied IDs.
        if cursor.rowcount == 0 and data.get("employee_id"):
            conn.execute(
                """UPDATE employees SET name=COALESCE(?, name), trade=COALESCE(?, trade),
                      dob=COALESCE(?, dob), phone=COALESCE(?, phone), email=COALESCE(?, email),
                      emergency_contact_name=COALESCE(?, emergency_contact_name),
                      emergency_contact_phone=COALESCE(?, emergency_contact_phone),
                      emergency_contact_relation=COALESCE(?, emergency_contact_relation),
                      language=COALESCE(?, language), hire_date=COALESCE(?, hire_date),
                      pin=COALESCE(?, pin), folder_path=?, updated_at=CURRENT_TIMESTAMP
                   WHERE employee_id=?""",
                (
                    name, data.get("trade"), data.get("dob"), data.get("phone"),
                    data.get("email"), data.get("emergency_contact_name"),
                    data.get("emergency_contact_phone"), data.get("emergency_contact_relation"),
                    data.get("language"), data.get("hire_date"), data.get("pin"),
                    str(folder), employee_id
                )
            )
        # Auto-assign to projects specified, OR default to all active projects
        project_codes = data.get("project_codes") or []
        if not project_codes:
            # Default: assign to all currently-active projects (typically just one today)
            actives = conn.execute(
                "SELECT project_code FROM projects WHERE status = 'active' OR status IS NULL"
            ).fetchall()
            project_codes = [r["project_code"] for r in actives]

        for pcode in project_codes:
            existing = conn.execute(
                "SELECT id FROM project_assignments WHERE project_code = ? AND employee_id = ? AND status = 'active'",
                (pcode, employee_id)
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO project_assignments
                       (project_code, employee_id, role_on_project, start_date, status)
                       VALUES (?, ?, ?, DATE('now'), 'active')""",
                    (pcode, employee_id, data.get("trade"))
                )

        conn.commit()
        conn.close()
        return response_wrapper({
            "employee_id": employee_id,
            "name": name,
            "folder_path": str(folder),
            "folder_slug": folder_slug,
            "assigned_to": project_codes,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/workers/<employee_id>', methods=['GET'])
def api_worker_get(employee_id):
    """Return full worker record + all documents + all certs."""
    try:
        conn = db()
        emp = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?", (employee_id,)
        ).fetchone()
        if not emp:
            conn.close()
            return jsonify({"error": "not found"}), 404

        docs = conn.execute(
            "SELECT * FROM worker_documents WHERE employee_id = ? ORDER BY uploaded_at DESC",
            (employee_id,)
        ).fetchall()
        certs = conn.execute(
            """SELECT c.*, ct.name AS cert_name, ct.description AS cert_description,
                      ct.is_cof_prerequisite
               FROM certifications c
               JOIN cert_types ct ON ct.cert_type_id = c.cert_type_id
               WHERE c.employee_id = ?
               ORDER BY c.expiration_date ASC""",
            (employee_id,)
        ).fetchall()
        conn.close()

        return response_wrapper({
            "employee": dict(emp),
            "documents": [dict(d) for d in docs],
            "certifications": [dict(c) for c in certs],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/workers/<employee_id>/upload', methods=['POST'])
def api_worker_upload(employee_id):
    """Upload a scan to a worker's folder.
    Multipart form fields: file=<binary>, doc_type=<string>, doc_label=<string>, related_cert_id=<int|null>.

    Security controls applied:
      1. MIME type must be in ALLOWED_DOC_MIME_TYPES whitelist
      2. File extension must be in ALLOWED_DOC_EXTENSIONS whitelist
      3. File size capped at 20MB (config'd above)
      4. Server-generated UUID filename; original_filename stored separately
      5. doc_type validated against fixed enum (no folder path injection)
      6. Path traversal proof: final path must resolve inside WORKER_RECORDS_DIR
    """
    try:
        if 'file' not in request.files:
            return jsonify({"error": "no file in request"}), 400
        f = request.files['file']
        if not f.filename:
            return jsonify({"error": "empty filename"}), 400

        # ----- SECURITY: MIME + extension whitelist -----
        if f.mimetype not in ALLOWED_DOC_MIME_TYPES:
            return jsonify({"error": f"file type {f.mimetype} not allowed. Allowed: images + PDF"}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_DOC_EXTENSIONS:
            return jsonify({"error": f"file extension {ext} not allowed"}), 400

        # ----- SECURITY: doc_type enum validation -----
        ALLOWED_DOC_TYPES = {
            'id_front', 'id_back', 'passport', 'idnyc',
            'sst_front', 'sst_back',
            'cert_front', 'cert_back', 'cert_combined',
            'other'
        }
        doc_type = request.form.get("doc_type", "other")
        if doc_type not in ALLOWED_DOC_TYPES:
            return jsonify({"error": f"invalid doc_type {doc_type}"}), 400

        conn = db()
        emp = conn.execute(
            "SELECT employee_id, name, folder_path FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
        if not emp:
            conn.close()
            return jsonify({"error": "employee not found"}), 404

        folder_path = emp["folder_path"]
        if not folder_path:
            folder_slug = slugify_name(emp["name"])
            folder_path = str(WORKER_RECORDS_DIR / f"{employee_id}_{folder_slug}")
            conn.execute(
                "UPDATE employees SET folder_path = ? WHERE employee_id = ?",
                (folder_path, employee_id)
            )

        # ----- SECURITY: path traversal proof -----
        folder = Path(folder_path).resolve()
        if not str(folder).startswith(str(WORKER_RECORDS_DIR.resolve())):
            conn.close()
            return jsonify({"error": "invalid folder path"}), 400

        doc_label = request.form.get("doc_label", "")[:200]      # cap to prevent excessive sizes
        related_cert_id = request.form.get("related_cert_id")
        if related_cert_id:
            try:
                related_cert_id = int(related_cert_id)
            except ValueError:
                related_cert_id = None
        else:
            related_cert_id = None

        # Choose subfolder (no user input affects the path beyond enum)
        if doc_type in ("id_front", "id_back", "passport", "idnyc"):
            subfolder = folder / "id"
        else:
            subfolder = folder / "certs"
        subfolder.mkdir(parents=True, exist_ok=True)

        # ----- SECURITY: UUID filename (no user input in path) -----
        from datetime import datetime as dt
        stamp = dt.utcnow().strftime("%Y%m%d-%H%M%S")
        target_filename = f"{doc_type}_{stamp}_{uuid.uuid4().hex[:8]}{ext}"
        target_path = (subfolder / target_filename).resolve()

        # Final path-traversal check after resolve()
        if not str(target_path).startswith(str(WORKER_RECORDS_DIR.resolve())):
            conn.close()
            return jsonify({"error": "path traversal blocked"}), 400

        f.save(str(target_path))
        size = target_path.stat().st_size

        # Record in DB. Original filename is what the user uploaded; for audit only — never re-used as a path.
        cur = conn.execute(
            """INSERT INTO worker_documents
               (employee_id, doc_type, doc_label, file_path, original_filename,
                mime_type, file_size_bytes, related_cert_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (employee_id, doc_type, doc_label, str(target_path), f.filename[:255],
             f.mimetype, size, related_cert_id)
        )
        doc_id = cur.lastrowid
        conn.commit()
        conn.close()

        return response_wrapper({
            "doc_id": doc_id,
            "file_path": str(target_path),
            "size_bytes": size,
            "doc_type": doc_type,
            "doc_label": doc_label,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/workers/<employee_id>/documents/<int:doc_id>', methods=['DELETE'])
def api_worker_delete_document(employee_id, doc_id):
    """Delete a worker document. Removes the file from disk AND the DB row.
    Path is validated to ensure deletion can't escape the worker_records dir."""
    try:
        conn = db()
        row = conn.execute(
            "SELECT file_path FROM worker_documents WHERE id = ? AND employee_id = ?",
            (doc_id, employee_id)
        ).fetchone()
        if not row:
            conn.close()
            return jsonify({"error": "not found"}), 404

        # Security: only delete files inside worker_records dir
        try:
            target = Path(row["file_path"]).resolve()
            if not str(target).startswith(str(WORKER_RECORDS_DIR.resolve())):
                conn.close()
                return jsonify({"error": "invalid file path"}), 400
            if target.exists():
                target.unlink()
        except Exception as e:
            logging.warning(f"Could not delete file: {e}")

        conn.execute("DELETE FROM worker_documents WHERE id = ?", (doc_id,))
        conn.commit()
        conn.close()
        return response_wrapper({"deleted": doc_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/workers/<employee_id>/certs/<int:cert_id>', methods=['DELETE'])
def api_worker_delete_cert(employee_id, cert_id):
    """Delete a single certification entry from a worker."""
    try:
        conn = db()
        conn.execute(
            "DELETE FROM certifications WHERE id = ? AND employee_id = ?",
            (cert_id, employee_id)
        )
        conn.commit()
        conn.close()
        return response_wrapper({"deleted": cert_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/workers/<employee_id>/certs', methods=['POST'])
def api_worker_add_cert(employee_id):
    """Add a certification to a worker.
    Body: {cert_type_id, date_obtained, expiration_date, card_number, issuing_body, notes, status}
    Returns the new cert row including its id."""
    try:
        data = request.get_json(silent=True) or {}
        cert_type_id = data.get("cert_type_id")
        if not cert_type_id:
            return jsonify({"error": "cert_type_id is required"}), 400

        conn = db()
        # Make sure cert type exists; if not, create it on the fly (free-text new cert)
        ct = conn.execute(
            "SELECT cert_type_id FROM cert_types WHERE cert_type_id = ?",
            (cert_type_id,)
        ).fetchone()
        if not ct:
            new_name = data.get("cert_type_name", cert_type_id)
            conn.execute(
                "INSERT INTO cert_types (cert_type_id, name, description, validity_months) VALUES (?, ?, ?, ?)",
                (cert_type_id, new_name, data.get("cert_type_description"), data.get("validity_months"))
            )

        cur = conn.execute(
            """INSERT INTO certifications
               (employee_id, cert_type_id, date_obtained, expiration_date, status,
                card_number, issuing_body, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                employee_id, cert_type_id,
                data.get("date_obtained"), data.get("expiration_date"),
                data.get("status", "active"), data.get("card_number"),
                data.get("issuing_body"), data.get("notes")
            )
        )
        cert_id = cur.lastrowid
        conn.commit()
        conn.close()

        return response_wrapper({"cert_id": cert_id, "cert_type_id": cert_type_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/cert-types', methods=['GET'])
def api_cert_types():
    """List all cert types for autocomplete."""
    try:
        conn = db()
        rows = conn.execute(
            "SELECT cert_type_id, name, description, validity_months, is_cof_prerequisite "
            "FROM cert_types ORDER BY name"
        ).fetchall()
        conn.close()
        return response_wrapper(rows_to_dicts(rows))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/workers/intake-summary', methods=['GET'])
def api_workers_intake_summary():
    """List of all workers with intake status + cert health + doc count."""
    try:
        conn = db()
        emps = conn.execute(
            "SELECT employee_id, name, trade, phone, language, intake_status, folder_path FROM employees ORDER BY name"
        ).fetchall()

        today = datetime.utcnow().date().isoformat()
        out = []
        for e in emps:
            doc_count = conn.execute(
                "SELECT COUNT(*) FROM worker_documents WHERE employee_id = ?", (e["employee_id"],)
            ).fetchone()[0]
            certs = conn.execute(
                """SELECT cert_type_id, expiration_date, status FROM certifications
                   WHERE employee_id = ?""", (e["employee_id"],)
            ).fetchall()
            cert_count = len(certs)
            expiring_30 = sum(
                1 for c in certs if c["expiration_date"] and c["expiration_date"] <= str(
                    (datetime.utcnow() + timedelta(days=30)).date()
                ) and c["expiration_date"] >= today
            )
            expired = sum(
                1 for c in certs if c["expiration_date"] and c["expiration_date"] < today
            )
            out.append({
                **dict(e),
                "doc_count": doc_count,
                "cert_count": cert_count,
                "certs_expiring_30d": expiring_30,
                "certs_expired": expired,
            })
        conn.close()
        return response_wrapper(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/worker-files/<path:filepath>', methods=['GET'])
def serve_worker_file(filepath):
    """Serve scanned documents back to the dashboard (image preview etc.)."""
    try:
        # Only allow paths inside worker_records dir for safety
        target = (WORKER_RECORDS_DIR / filepath).resolve()
        if not str(target).startswith(str(WORKER_RECORDS_DIR.resolve())):
            return jsonify({"error": "invalid path"}), 403
        if not target.exists() or not target.is_file():
            return jsonify({"error": "not found"}), 404
        return send_file(str(target))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============= WEATHER (Open-Meteo, no API key) =============

@app.route('/api/weather', methods=['GET'])
def api_weather():
    """Live current + today's hi/lo for the active project, from Open-Meteo.
    Project coords default to the Bronx (Mott Haven) site.
    Returns: temp_now, temp_max, temp_min, wind_mph, wind_dir, condition_code, condition_label."""
    import urllib.request, urllib.parse
    try:
        lat = float(request.args.get("lat", 40.8083))
        lng = float(request.args.get("lng", -73.9162))
        params = {
            "latitude": lat, "longitude": lng,
            "current": "temperature_2m,wind_speed_10m,wind_direction_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,weather_code",
            "temperature_unit": "fahrenheit",
            "wind_speed_unit": "mph",
            "timezone": "America/New_York",
            "forecast_days": 1,
        }
        url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(params)
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        cur = data.get("current", {}) or {}
        daily = data.get("daily", {}) or {}
        out = {
            "temp_now": cur.get("temperature_2m"),
            "wind_mph": cur.get("wind_speed_10m"),
            "wind_dir_deg": cur.get("wind_direction_10m"),
            "condition_code": cur.get("weather_code"),
            "temp_max": (daily.get("temperature_2m_max") or [None])[0],
            "temp_min": (daily.get("temperature_2m_min") or [None])[0],
            "fetched_at": datetime.utcnow().isoformat() + "Z",
        }
        # Compass direction
        deg = out.get("wind_dir_deg")
        if deg is not None:
            compass = ["N","NE","E","SE","S","SW","W","NW","N"]
            out["wind_dir"] = compass[int((deg + 22.5) // 45)]

        # Plain-language condition (WMO weather codes)
        code = out.get("condition_code")
        labels = {
            0: "Clear", 1: "Mostly clear", 2: "Partly cloudy", 3: "Overcast",
            45: "Fog", 48: "Freezing fog",
            51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
            56: "Freezing drizzle", 57: "Freezing drizzle",
            61: "Light rain", 63: "Rain", 65: "Heavy rain",
            66: "Freezing rain", 67: "Freezing rain",
            71: "Light snow", 73: "Snow", 75: "Heavy snow",
            77: "Snow grains",
            80: "Rain showers", 81: "Rain showers", 82: "Heavy showers",
            85: "Snow showers", 86: "Snow showers",
            95: "Thunderstorm", 96: "Thunderstorm w/ hail", 99: "Severe thunderstorm",
        }
        out["condition_label"] = labels.get(code, "—")
        return response_wrapper(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============= NYC COMPLIANCE WATCH =============

@app.route('/api/compliance/summary', methods=['GET'])
def api_compliance_summary():
    """Returns red/yellow/green status per project across permits, violations, complaints."""
    from datetime import datetime, timedelta
    try:
        conn = db()
        projects = conn.execute(
            "SELECT project_code, name, bin, address FROM projects"
        ).fetchall()

        today = datetime.utcnow().date()
        d30 = today + timedelta(days=30)
        d90_ago = today - timedelta(days=90)
        d30_ago = today - timedelta(days=30)

        out = []
        for p in projects:
            code = p["project_code"]
            # Permits status
            permits_open = conn.execute(
                "SELECT COUNT(*) FROM dob_permits WHERE project_code = ? AND filing_status NOT IN ('Issued','REVOKED','SUPERCEDED','EXPIRED') OR (expiration_date IS NOT NULL AND expiration_date >= ?)",
                (code, str(today))
            ).fetchone()[0]
            permits_expiring_30 = conn.execute(
                "SELECT COUNT(*) FROM dob_permits WHERE project_code = ? AND expiration_date IS NOT NULL AND expiration_date BETWEEN ? AND ?",
                (code, str(today), str(d30))
            ).fetchone()[0]
            # Violations status
            v_active = conn.execute(
                "SELECT COUNT(*) FROM dob_violations WHERE project_code = ? AND (status IS NULL OR status NOT IN ('RESOLVED','DISPOSED','DISMISSED','CLOSED'))",
                (code,)
            ).fetchone()[0]
            v_recent = conn.execute(
                "SELECT COUNT(*) FROM dob_violations WHERE project_code = ? AND issue_date >= ?",
                (code, str(d90_ago))
            ).fetchone()[0]
            # Complaints status
            c_active = conn.execute(
                "SELECT COUNT(*) FROM dob_complaints WHERE project_code = ? AND (status IS NULL OR status NOT IN ('CLOSED','RESOLVED'))",
                (code,)
            ).fetchone()[0]
            c_recent = conn.execute(
                "SELECT COUNT(*) FROM dob_complaints WHERE project_code = ? AND date_entered >= ?",
                (code, str(d30_ago))
            ).fetchone()[0]

            # Overall light: red if any active violation OR expired permit; yellow if expiring 30d or recent complaint; green otherwise
            light = "green"
            if v_active > 0:
                light = "red"
            elif permits_expiring_30 > 0 or c_recent > 0:
                light = "yellow"

            # Last refresh
            last_run = conn.execute(
                "SELECT MAX(run_at) AS last FROM dob_pulse_runs WHERE project_code = ?", (code,)
            ).fetchone()
            last_refresh = last_run["last"] if last_run and last_run["last"] else None

            out.append({
                "project_code": code,
                "name": p["name"],
                "bin": p["bin"],
                "address": p["address"],
                "light": light,
                "permits": {"open": permits_open, "expiring_30d": permits_expiring_30},
                "violations": {"active": v_active, "issued_90d": v_recent},
                "complaints": {"active": c_active, "filed_30d": c_recent},
                "last_refresh": last_refresh,
            })
        conn.close()
        return response_wrapper(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/compliance/permits', methods=['GET'])
def api_compliance_permits():
    project_code = request.args.get("project_code")
    if not project_code:
        return jsonify({"error": "project_code required"}), 400
    try:
        conn = db()
        rows = conn.execute(
            """SELECT permit_id, work_permit, job_filing_number, permit_type, work_type,
                      filing_status, issuance_date, expiration_date, permittee_business_name
               FROM dob_permits WHERE project_code = ?
               ORDER BY filing_date DESC NULLS LAST, expiration_date DESC""",
            (project_code,)
        ).fetchall()
        conn.close()
        return response_wrapper(rows_to_dicts(rows) if rows else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/compliance/violations', methods=['GET'])
def api_compliance_violations():
    project_code = request.args.get("project_code")
    if not project_code:
        return jsonify({"error": "project_code required"}), 400
    try:
        conn = db()
        rows = conn.execute(
            """SELECT violation_id, source, violation_number, violation_type, violation_category,
                      issue_date, hearing_date, status, description, penalty_imposed, penalty_paid
               FROM dob_violations WHERE project_code = ?
               ORDER BY issue_date DESC""",
            (project_code,)
        ).fetchall()
        conn.close()
        return response_wrapper(rows_to_dicts(rows) if rows else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/compliance/complaints', methods=['GET'])
def api_compliance_complaints():
    project_code = request.args.get("project_code")
    if not project_code:
        return jsonify({"error": "project_code required"}), 400
    try:
        conn = db()
        rows = conn.execute(
            """SELECT complaint_id, complaint_number, complaint_category, status,
                      date_entered, disposition_date, disposition_code, inspection_date
               FROM dob_complaints WHERE project_code = ?
               ORDER BY date_entered DESC""",
            (project_code,)
        ).fetchall()
        conn.close()
        return response_wrapper(rows_to_dicts(rows) if rows else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/compliance/refresh', methods=['POST'])
def api_compliance_refresh():
    """Trigger a live pull from NYC OpenData. Body: {project_code: 'SC-2601'} or {} for all."""
    try:
        import nyc_compliance
        body = request.get_json(silent=True) or {}
        project_code = body.get("project_code")
        if project_code:
            result = nyc_compliance.refresh_project(project_code)
            return response_wrapper({"project": project_code, "result": result})
        else:
            results = nyc_compliance.refresh_all()
            return response_wrapper({"all": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/api/compliance/pulse', methods=['GET'])
def api_compliance_pulse():
    """Last N pulse runs for monitoring."""
    try:
        limit = int(request.args.get("limit", 30))
        conn = db()
        rows = conn.execute(
            """SELECT run_at, project_code, dataset, bin_queried, records_returned,
                      status_code, duration_ms, error_message
               FROM dob_pulse_runs ORDER BY run_at DESC LIMIT ?""",
            (limit,)
        ).fetchall()
        conn.close()
        return response_wrapper(rows_to_dicts(rows) if rows else [])
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============= STATIC SERVING =============


@app.route('/files/<path:filepath>', methods=['GET'])
def serve_files(filepath):
    try:
        return send_from_directory(str(SCRIPT_DIR), filepath)
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404


@app.route('/<path:filename>')
def static_files(filename):
    """Serve any other file in the outputs folder by name (e.g. /DCR-SC-2601-2026-05-05-internal.html, /drop_plans/DP-001.html)"""
    file_path = SCRIPT_DIR / filename
    if file_path.exists() and file_path.is_file():
        return send_file(str(file_path))
    return jsonify({"error": "File not found", "path": filename}), 404


@app.after_request
def add_no_cache_headers(response):
    """Force browsers (especially iPhone Safari) to always pull fresh HTML/JS.
    Without this, Safari aggressively caches PWA assets and edits never reach the device.
    """
    path = request.path or ''
    if path.endswith('.html') or path.endswith('.js') or path.endswith('-sw.js') or path == '/' or path.startswith('/worker-app'):
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate, max-age=0'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response
# ============= ERROR HANDLERS =============

@app.errorhandler(404)
def not_found(error):
    logging.error(f"404: {request.path}")
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logging.error(f"500: {str(error)}")
    return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    import sys
    print("\n" + "=" * 60, flush=True)
    print("  Server starting...", flush=True)
    print("  Try in browser: http://127.0.0.1:5050", flush=True)
    print("  Or:             http://localhost:5050", flush=True)
    print("=" * 60 + "\n", flush=True)
    sys.stdout.flush()
    # Loopback only per CLAUDE.md rule #6: workstation lives on a shared
    # coworking-space network — the dashboard must not be reachable from LAN.
    app.run(host='127.0.0.1', port=5050, debug=False, use_reloader=False, threaded=True)
