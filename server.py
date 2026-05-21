from flask import Flask, jsonify, request, send_from_directory, send_file
from flask_cors import CORS
import sqlite3
from pathlib import Path
from datetime import datetime, date, timedelta
import logging
import json
import uuid

# Vision-based cert extraction (requires ANTHROPIC_API_KEY in env — launch
# the server via `op run --env-file=".env.template" -- python server.py`).
from cert_extractor import extract_cert_from_image, load_cert_types_from_db

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

# Per CLAUDE.md PII rule: PINs are derived from phone last-4, so plaintext
# phones and PINs in server.log violate the same PII discipline as pasting
# them into chats. Redact at the logging boundary so the file accumulates
# only safe data.
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
    """Create a sign-in row. Two supported callers:
    - worker-app live flow (via /api/worker-sign-in, not this route): time_in
      only, time_out set later by sign-out
    - DCR form's backdated manual labor entry: passes BOTH time_in + time_out
      with an arbitrary date (the operator entering a past day's roster)

    Validates: employee + project exist, time_out >= time_in when both present,
    and rejects duplicates for the same (employee_id, date, project_code) with
    409 — silent duplicates double-count hours in the DCR labor aggregator, so
    the caller must explicitly delete the existing row before re-adding.
    """
    try:
        data = request.get_json() or {}
        employee_id = data.get('employee_id')
        project_code = data.get('project_code')
        date_str = data.get('date', date.today().isoformat())
        time_in = data.get('time_in')
        time_out = data.get('time_out')  # optional — backdated entry supplies both

        if not employee_id or not project_code or not date_str or not time_in:
            return jsonify({"error": "employee_id, project_code, date, time_in are required"}), 400
        # HH:MM string compare is correct for same-day shifts (the DCR labor
        # path doesn't model overnight). Reject inverted ranges explicitly so
        # they don't silently render as negative hours later.
        if time_out and time_out < time_in:
            return jsonify({"error": f"time_out ({time_out}) is before time_in ({time_in})"}), 400

        conn = db()
        if not validate_employee_exists(conn, employee_id):
            conn.close()
            return jsonify({"error": "Employee not found"}), 400
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400

        existing = conn.execute(
            "SELECT id, time_in, time_out FROM sign_in_log "
            "WHERE employee_id = ? AND date = ? AND project_code = ?",
            (employee_id, date_str, project_code)
        ).fetchone()
        if existing:
            conn.close()
            return jsonify({
                "error": "Sign-in already exists for this worker on this date",
                "existing_id": existing["id"],
                "existing_time_in": existing["time_in"],
                "existing_time_out": existing["time_out"],
            }), 409

        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO sign_in_log (date, employee_id, project_code, time_in, time_out, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date_str, employee_id, project_code, time_in, time_out, now, now)
        )
        conn.commit()
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


@app.route('/api/sign-ins/<int:sign_in_id>', methods=['PUT'])
def replace_sign_in(sign_in_id):
    """Full replace of a sign_in_log row's billable times.

    Used by the Weekly Hours Log when the operator edits a cell that already
    has an entry. Distinct from PATCH (which only updates time_out) because
    the payroll grid lets the operator change BOTH time_in and time_out at
    once (e.g., late arrival + early departure on the same shift).

    Body: {time_in: "HH:MM", time_out: "HH:MM"}. Both required.
    Validates time_out >= time_in via the same HH:MM string compare used by
    POST. Returns the updated row, or 404 if the id doesn't exist."""
    try:
        data = request.get_json() or {}
        time_in = data.get('time_in')
        time_out = data.get('time_out')
        if not time_in or not time_out:
            return jsonify({"error": "time_in and time_out are required"}), 400
        if time_out < time_in:
            return jsonify({"error": f"time_out ({time_out}) is before time_in ({time_in})"}), 400

        conn = db()
        existing = conn.execute("SELECT id FROM sign_in_log WHERE id = ?", (sign_in_id,)).fetchone()
        if not existing:
            conn.close()
            return jsonify({"error": "sign_in_log row not found"}), 404
        conn.execute(
            "UPDATE sign_in_log SET time_in = ?, time_out = ?, updated_at = ? WHERE id = ?",
            (time_in, time_out, datetime.now().isoformat(), sign_in_id)
        )
        conn.commit()
        row = conn.execute("SELECT * FROM sign_in_log WHERE id = ?", (sign_in_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 200
    except Exception as e:
        logging.error(f"PUT /api/sign-ins/{sign_in_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/sign-ins/<int:sign_in_id>', methods=['DELETE'])
def delete_sign_in(sign_in_id):
    """Delete a sign_in_log row. Used by the Weekly Hours Log when the
    operator clears a cell (a worker who was incorrectly marked as
    present, or a row entered against the wrong worker/date).

    Returns 404 if the id doesn't exist so the caller can distinguish
    'already gone' from 'never existed' if needed."""
    try:
        conn = db()
        existing = conn.execute("SELECT id FROM sign_in_log WHERE id = ?", (sign_in_id,)).fetchone()
        if not existing:
            conn.close()
            return jsonify({"error": "sign_in_log row not found"}), 404
        conn.execute("DELETE FROM sign_in_log WHERE id = ?", (sign_in_id,))
        conn.commit()
        conn.close()
        return jsonify({"deleted": True, "id": sign_in_id}), 200
    except Exception as e:
        logging.error(f"DELETE /api/sign-ins/{sign_in_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============= PAYROLL: WEEKLY HOURS LOG =============

@app.route('/api/payroll/hours', methods=['GET'])
def api_payroll_hours():
    """Weekly Hours grid for payroll. Source of truth = sign_in_log.

    Query params:
      week_start (optional, ISO 'YYYY-MM-DD'): the Monday of the week. If
        omitted, defaults to the last completed Mon-Fri week relative to
        today (payroll runs one week in arrears).

    Returns the payroll_hours.build_week_grid dict: dates, workers (with
    per-day cells + weekly totals), totals_by_day, grand_total. Worker pool
    = employees with at least one active project_assignment.
    """
    from payroll_hours import last_completed_week, build_week_grid
    week_start = (request.args.get('week_start') or '').strip()
    try:
        if week_start:
            monday = datetime.strptime(week_start, '%Y-%m-%d').date()
            if monday.weekday() != 0:
                return jsonify({"error": "week_start must be a Monday"}), 400
        else:
            monday, _ = last_completed_week()
        conn = db()
        grid = build_week_grid(conn, monday)
        conn.close()
        return response_wrapper(grid), 200
    except Exception as e:
        logging.error(f"GET /api/payroll/hours: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/payroll/hours.csv', methods=['GET'])
def api_payroll_hours_csv():
    """CSV export of the weekly hours grid. One row per worker; columns:
    employee_id, name, trade, <Mon date>, <Tue>, <Wed>, <Thu>, <Fri>,
    weekly_total. A 'DAILY TOTAL' summary row follows the data rows.

    Hours are hours WORKED (lunch deducted) so the CSV matches what the
    operator hands to payroll. Pay-or-not is a downstream decision.
    """
    import csv
    import io
    from payroll_hours import last_completed_week, build_week_grid
    week_start = (request.args.get('week_start') or '').strip()
    try:
        if week_start:
            monday = datetime.strptime(week_start, '%Y-%m-%d').date()
            if monday.weekday() != 0:
                return jsonify({"error": "week_start must be a Monday"}), 400
        else:
            monday, _ = last_completed_week()
        conn = db()
        grid = build_week_grid(conn, monday)
        conn.close()

        buf = io.StringIO()
        w = csv.writer(buf)
        # Worker ID (W-####) first — the human-facing identifier that
        # payroll uses to match workers across systems. employee_id stays
        # so the internal key is in the export for traceback.
        w.writerow(["worker_id", "employee_id", "name", "trade",
                    *grid["dates"], "weekly_total"])
        for emp in grid["workers"]:
            w.writerow([
                emp.get("worker_id") or "",
                emp["employee_id"], emp["name"], emp["trade"] or "",
                *[(d["hours"] if d["has_entry"] else "") for d in emp["days"]],
                emp["weekly_total"],
            ])
        w.writerow(["", "", "DAILY TOTAL", "",
                    *grid["totals_by_day"], grid["grand_total"]])

        csv_bytes = buf.getvalue().encode("utf-8")
        filename = f"weekly-hours-{grid['week_start']}-to-{grid['week_end']}.csv"
        from flask import Response
        return Response(
            csv_bytes, status=200, mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        logging.error(f"GET /api/payroll/hours.csv: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/payroll/hours.pdf', methods=['GET'])
def api_payroll_hours_pdf():
    """PDF export of the weekly hours grid. Renders an HTML timesheet via
    render_timesheet_html and pipes through pdf_export (headless Edge),
    same pipeline as the DCR PDFs. Returns the PDF as an attachment.

    PDF render failures return 502 with the error so the UI can surface
    "PDF render failed — try CSV instead" rather than a blank download.
    """
    from payroll_hours import last_completed_week, build_week_grid
    from render_timesheet_html import render_timesheet_html
    from pdf_export import render_html_to_pdf, PDFExportError
    week_start = (request.args.get('week_start') or '').strip()
    try:
        if week_start:
            monday = datetime.strptime(week_start, '%Y-%m-%d').date()
            if monday.weekday() != 0:
                return jsonify({"error": "week_start must be a Monday"}), 400
        else:
            monday, _ = last_completed_week()
        conn = db()
        grid = build_week_grid(conn, monday)
        conn.close()

        html_str = render_timesheet_html(grid)

        # Use a stable temp filename pair under data_room so the file is
        # locatable for post-mortem if rendering fails. Overwritten each call.
        out_dir = SCRIPT_DIR / "data_room" / "reports" / "weekly_hours"
        out_dir.mkdir(parents=True, exist_ok=True)
        html_tmp = out_dir / f"week-{grid['week_start']}.html"
        pdf_tmp = out_dir / f"week-{grid['week_start']}.pdf"
        # Atomic write
        html_swap = out_dir / f"week-{grid['week_start']}.html.tmp"
        html_swap.write_text(html_str, encoding='utf-8')
        html_swap.replace(html_tmp)

        try:
            result = render_html_to_pdf(html_tmp, pdf_tmp)
        except PDFExportError as e:
            return jsonify({"error": f"PDF setup error: {e}"}), 502
        if not result.get("ok"):
            return jsonify({"error": result.get("error", "PDF render failed")}), 502

        filename = f"weekly-hours-{grid['week_start']}-to-{grid['week_end']}.pdf"
        return send_file(
            str(pdf_tmp), mimetype="application/pdf",
            as_attachment=True, download_name=filename,
        )
    except Exception as e:
        logging.error(f"GET /api/payroll/hours.pdf: {str(e)}")
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

# ============= DCR SITE ACTIVITY ENDPOINTS =============

def _parse_dcr_date(date_str):
    """Validate YYYY-MM-DD or return today's date if not supplied. Raises ValueError on bad format."""
    if not date_str:
        return date.today().isoformat()
    datetime.strptime(date_str, '%Y-%m-%d')
    return date_str


@app.route('/api/work-log', methods=['POST'])
def create_work_log():
    """Log work performed for a project on a given date."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO work_log (date, project_code, trade_area, location_elevation, "
            "description, scope_of_work, trades_working) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('trade_area'), data.get('location_elevation'),
             data.get('description'), data.get('scope_of_work'), data.get('trades_working'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM work_log WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/work-log: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/deliveries', methods=['POST'])
def create_delivery():
    """Log a material delivery."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO deliveries (date, project_code, time, material, qty, unit, "
            "supplier, notes, description, delivered_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('time'), data.get('material'),
             data.get('qty'), data.get('unit'), data.get('supplier'), data.get('notes'),
             data.get('description'), data.get('delivered_by'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM deliveries WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/deliveries: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/equipment-log', methods=['POST'])
def create_equipment_log():
    """Log equipment on site for a given day. Renderer uses `equipment` as display
    name; accepted as alias for the schema's equipment_type column."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        equipment_type = data.get('equipment_type') or data.get('equipment')
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO equipment_log (date, project_code, equipment_type, equipment_id, "
            "owner, hours_used, issues, status, notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, equipment_type, data.get('equipment_id'),
             data.get('owner'), data.get('hours_used'), data.get('issues'),
             data.get('status'), data.get('notes'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM equipment_log WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/equipment-log: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/weather-log', methods=['POST'])
def create_weather_log():
    """Log site weather for a given date. Operator-entered values override
    the live Open-Meteo fallback at DCR aggregation time."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO weather_log (date, project_code, am_temp_f, pm_temp_f, "
            "am_conditions, pm_conditions, wind, conditions) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('am_temp_f'), data.get('pm_temp_f'),
             data.get('am_conditions'), data.get('pm_conditions'),
             data.get('wind'), data.get('conditions'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM weather_log WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/weather-log: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============= DCR SAFETY + COMPLIANCE ENDPOINTS =============

@app.route('/api/toolbox-talks/records', methods=['POST'])
def create_toolbox_talk_record():
    """Log a toolbox-talk occurrence. `topic` is resolved from toolbox_talk_library
    via talk_id at render time, so a `topic` field in the body is accepted but not
    persisted. `conducted_by` is accepted as a synonym for `facilitator`."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        facilitator = data.get('facilitator') or data.get('conducted_by')
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO toolbox_talk_records (date, project_code, talk_id, "
            "facilitator, attendees, duration_minutes) VALUES (?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('talk_id'), facilitator,
             data.get('attendees'), data.get('duration_minutes'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM toolbox_talk_records WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/toolbox-talks/records: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/safety-events', methods=['POST'])
def create_safety_event():
    """Log a safety event (incident, near-miss, observation)."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO safety_events (date, project_code, event_type, severity, "
            "time, person, description, action, reported_by) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('event_type'), data.get('severity'),
             data.get('time'), data.get('person'), data.get('description'),
             data.get('action'), data.get('reported_by'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM safety_events WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/safety-events: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/issues', methods=['POST'])
def create_issue():
    """Log a project issue / delay."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        due_date = data.get('due_date')
        if due_date:
            try:
                datetime.strptime(due_date, '%Y-%m-%d')
            except ValueError:
                return jsonify({"error": "due_date must be YYYY-MM-DD"}), 400
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO issues (date, project_code, category, description, "
            "time_lost_hrs, action, owner, status, due_date) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('category'), data.get('description'),
             data.get('time_lost_hrs'), data.get('action'), data.get('owner'),
             data.get('status'), due_date)
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM issues WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/issues: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/inspections', methods=['POST'])
def create_inspection():
    """Log an inspection (DOB, 3rd party, internal QC)."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO inspections (date, project_code, type, inspector_name, "
            "agency, area, result, notes, scope) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('type'), data.get('inspector_name'),
             data.get('agency'), data.get('area'), data.get('result'),
             data.get('notes'), data.get('scope'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM inspections WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/inspections: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============= DCR VISITORS =============

@app.route('/api/visitors', methods=['POST'])
def create_visitor():
    """Log a site visitor. Powers the DCR visitors section."""
    try:
        data = request.get_json() or {}
        project_code = data.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(data.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.execute(
            "INSERT INTO visitors (date, project_code, name, company, role, "
            "time_in, time_out, purpose, accompanied_by, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (date_str, project_code, data.get('name'), data.get('company'),
             data.get('role'), data.get('time_in'), data.get('time_out'),
             data.get('purpose'), data.get('accompanied_by'), data.get('notes'))
        )
        conn.commit()
        new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
        row = conn.execute("SELECT * FROM visitors WHERE id = ?", (new_id,)).fetchone()
        conn.close()
        return response_wrapper(dict(row)), 201
    except Exception as e:
        logging.error(f"POST /api/visitors: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============= DELETE endpoints for DCR entry rows + reports =============

def _delete_entry_row(table, row_id):
    """Generic single-row delete by integer id. Parameterized SQL. Returns
    Flask response tuple. 404 if no row matched, 200 otherwise."""
    conn = db()
    try:
        existing = conn.execute(f"SELECT id FROM {table} WHERE id = ?", (row_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Not found"}), 404
        conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
        conn.commit()
        return jsonify({"deleted": True, "id": row_id, "table": table}), 200
    except Exception as e:
        logging.error(f"DELETE {table}/{row_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/work-log/<int:row_id>', methods=['DELETE'])
def delete_work_log(row_id):
    return _delete_entry_row('work_log', row_id)


@app.route('/api/deliveries/<int:row_id>', methods=['DELETE'])
def delete_delivery(row_id):
    return _delete_entry_row('deliveries', row_id)


@app.route('/api/equipment-log/<int:row_id>', methods=['DELETE'])
def delete_equipment_log(row_id):
    return _delete_entry_row('equipment_log', row_id)


@app.route('/api/weather-log/<int:row_id>', methods=['DELETE'])
def delete_weather_log(row_id):
    return _delete_entry_row('weather_log', row_id)


@app.route('/api/toolbox-talks/records/<int:row_id>', methods=['DELETE'])
def delete_toolbox_talk_record(row_id):
    return _delete_entry_row('toolbox_talk_records', row_id)


@app.route('/api/safety-events/<int:row_id>', methods=['DELETE'])
def delete_safety_event(row_id):
    return _delete_entry_row('safety_events', row_id)


@app.route('/api/issues/<int:row_id>', methods=['DELETE'])
def delete_issue(row_id):
    return _delete_entry_row('issues', row_id)


@app.route('/api/inspections/<int:row_id>', methods=['DELETE'])
def delete_inspection(row_id):
    return _delete_entry_row('inspections', row_id)


@app.route('/api/visitors/<int:row_id>', methods=['DELETE'])
def delete_visitor(row_id):
    return _delete_entry_row('visitors', row_id)


@app.route('/api/photos/<int:row_id>', methods=['DELETE'])
def delete_photo(row_id):
    """Delete photo row + file on disk. DB delete succeeds even if file
    delete fails (orphan file is better than orphan DB row)."""
    conn = db()
    try:
        row = conn.execute("SELECT file_path FROM photos WHERE id = ?", (row_id,)).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        file_path = row['file_path']
        conn.execute("DELETE FROM photos WHERE id = ?", (row_id,))
        conn.commit()
    except Exception as e:
        logging.error(f"DELETE /api/photos/{row_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    file_deleted = False
    file_error = None
    if file_path:
        try:
            p = Path(file_path)
            if not p.is_absolute():
                p = SCRIPT_DIR / p
            if p.exists():
                p.unlink()
                file_deleted = True
        except Exception as e:
            file_error = str(e)
            logging.warning(f"Photo file delete failed for id={row_id}: {file_error}")
    return jsonify({
        "deleted": True, "id": row_id, "file_deleted": file_deleted,
        "file_error": file_error,
    }), 200


# ============= PATCH endpoints for DCR entry rows =============

def _patch_dcr_row(table, row_id, allowed_fields, aliases=None):
    """Generic PATCH for a DCR sub-section row.

    Updates only the columns named in allowed_fields. Aliases is an optional
    {alias: real_column} map for POST-compat field aliases (e.g. 'equipment'
    → 'equipment_type' on equipment_log). 404 if no row matched; 400 if no
    updatable fields were supplied. `date` and `project_code` are NOT
    mutable here — re-creating a row is the operator path for moving it
    across days or projects (the semantics of every DCR sub-section are
    'this happened on this date for this project')."""
    data = request.get_json(silent=True) or {}
    updates = {}
    for k in allowed_fields:
        if k in data:
            updates[k] = data[k]
    if aliases:
        for alias, real in aliases.items():
            if alias in data and real not in updates:
                updates[real] = data[alias]
    if not updates:
        return jsonify({"error": "no updatable fields in payload"}), 400
    conn = db()
    try:
        existing = conn.execute(
            f"SELECT id FROM {table} WHERE id = ?", (row_id,)
        ).fetchone()
        if not existing:
            return jsonify({"error": "not found"}), 404
        set_clauses = [f"{k} = ?" for k in updates] + ["updated_at = CURRENT_TIMESTAMP"]
        params = list(updates.values()) + [row_id]
        conn.execute(
            f"UPDATE {table} SET {', '.join(set_clauses)} WHERE id = ?",
            params
        )
        conn.commit()
        row = conn.execute(f"SELECT * FROM {table} WHERE id = ?", (row_id,)).fetchone()
        return response_wrapper(dict(row)), 200
    except Exception as e:
        logging.error(f"PATCH /api/{table}/{row_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


@app.route('/api/work-log/<int:row_id>', methods=['PATCH'])
def patch_work_log(row_id):
    return _patch_dcr_row('work_log', row_id, {
        'trade_area', 'location_elevation', 'description',
        'scope_of_work', 'trades_working',
    })


@app.route('/api/deliveries/<int:row_id>', methods=['PATCH'])
def patch_delivery(row_id):
    return _patch_dcr_row('deliveries', row_id, {
        'time', 'material', 'qty', 'unit', 'supplier', 'notes',
        'description', 'delivered_by',
    })


@app.route('/api/equipment-log/<int:row_id>', methods=['PATCH'])
def patch_equipment_log(row_id):
    return _patch_dcr_row('equipment_log', row_id, {
        'equipment_type', 'equipment_id', 'owner', 'hours_used',
        'issues', 'status', 'notes',
    }, aliases={'equipment': 'equipment_type'})


@app.route('/api/weather-log/<int:row_id>', methods=['PATCH'])
def patch_weather_log(row_id):
    return _patch_dcr_row('weather_log', row_id, {
        'am_temp_f', 'pm_temp_f', 'am_conditions', 'pm_conditions',
        'wind', 'conditions',
    })


@app.route('/api/toolbox-talks/records/<int:row_id>', methods=['PATCH'])
def patch_toolbox_talk_record(row_id):
    return _patch_dcr_row('toolbox_talk_records', row_id, {
        'talk_id', 'facilitator', 'attendees', 'duration_minutes',
    }, aliases={'conducted_by': 'facilitator'})


@app.route('/api/safety-events/<int:row_id>', methods=['PATCH'])
def patch_safety_event(row_id):
    return _patch_dcr_row('safety_events', row_id, {
        'event_type', 'severity', 'time', 'person', 'description',
        'action', 'reported_by',
    })


@app.route('/api/issues/<int:row_id>', methods=['PATCH'])
def patch_issue(row_id):
    # Mirror POST due_date validation so PATCH can't sneak in a malformed value.
    data = request.get_json(silent=True) or {}
    if 'due_date' in data and data['due_date']:
        try:
            datetime.strptime(data['due_date'], '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": "due_date must be YYYY-MM-DD"}), 400
    return _patch_dcr_row('issues', row_id, {
        'category', 'description', 'time_lost_hrs', 'action',
        'owner', 'status', 'due_date',
    })


@app.route('/api/inspections/<int:row_id>', methods=['PATCH'])
def patch_inspection(row_id):
    return _patch_dcr_row('inspections', row_id, {
        'type', 'inspector_name', 'agency', 'area', 'result',
        'notes', 'scope',
    })


@app.route('/api/visitors/<int:row_id>', methods=['PATCH'])
def patch_visitor(row_id):
    return _patch_dcr_row('visitors', row_id, {
        'name', 'company', 'role', 'time_in', 'time_out',
        'purpose', 'accompanied_by', 'notes',
    })


@app.route('/api/photos/<int:row_id>', methods=['PATCH'])
def patch_photo(row_id):
    # Photo file metadata only — file_path / filename / url / date /
    # project_code are NOT mutable here. Re-uploading is the path for
    # changing the file itself.
    return _patch_dcr_row('photos', row_id, {
        'location', 'description', 'uploaded_by',
    })


@app.route('/api/projects/<project_code>/reports/by-sequence/<int:seq>', methods=['DELETE'])
def delete_report_by_sequence(project_code, seq):
    """Atomic DCR delete: removes BOTH internal and client report_index rows for
    (project_code, dcr_sequence=seq) plus both HTML files. Frontend Delete button
    uses this so the operator's 'Delete' action removes the entire report (the
    legacy per-report_id route is retained below for low-level use). 404 if no
    rows match. DB deletes are transactional; file deletes are best-effort."""
    conn = db()
    try:
        rows = conn.execute(
            "SELECT report_id FROM report_index "
            "WHERE project_code = ? AND dcr_sequence = ? AND report_type = 'DCR'",
            (project_code, seq)
        ).fetchall()
        if not rows:
            return jsonify({"error": "Not found"}), 404
        deleted_report_ids = [r['report_id'] for r in rows]
        conn.execute(
            "DELETE FROM report_index "
            "WHERE project_code = ? AND dcr_sequence = ? AND report_type = 'DCR'",
            (project_code, seq)
        )
        conn.commit()
    except Exception as e:
        logging.error(f"DELETE /api/projects/{project_code}/reports/by-sequence/{seq}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()

    files_deleted = []
    file_errors = {}
    seq_dir = SCRIPT_DIR / "data_room" / "reports" / "dcr" / project_code / f"{seq:03d}"
    for audience in ('internal', 'client'):
        out_file = seq_dir / f"{audience}.html"
        try:
            if out_file.exists():
                out_file.unlink()
                files_deleted.append(f"{audience}.html")
        except Exception as e:
            file_errors[f"{audience}.html"] = str(e)
            logging.warning(f"DCR HTML delete failed for {project_code} seq={seq} {audience}: {e}")
    # Best-effort rmdir the now-empty sequence directory so we don't leave a stub.
    try:
        if seq_dir.exists() and not any(seq_dir.iterdir()):
            seq_dir.rmdir()
    except Exception:
        pass

    return jsonify({
        "deleted": True,
        "project_code": project_code,
        "sequence": seq,
        "report_ids_deleted": deleted_report_ids,
        "files_deleted": files_deleted,
        "file_errors": file_errors or None,
    }), 200


@app.route('/api/projects/<project_code>/reports/<report_id>', methods=['DELETE'])
def delete_report(project_code, report_id):
    """Delete a single report_index row + its rendered HTML file (sequence-based
    path). One row per audience: deleting the internal variant leaves the client
    variant alone, and vice versa. DB delete succeeds even if file delete fails."""
    conn = db()
    try:
        row = conn.execute(
            "SELECT dcr_sequence FROM report_index WHERE project_code = ? AND report_id = ?",
            (project_code, report_id)
        ).fetchone()
        if not row:
            return jsonify({"error": "Not found"}), 404
        seq = row['dcr_sequence']
        conn.execute(
            "DELETE FROM report_index WHERE project_code = ? AND report_id = ?",
            (project_code, report_id)
        )
        conn.commit()
    except Exception as e:
        logging.error(f"DELETE /api/projects/{project_code}/reports/{report_id}: {str(e)}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    audience = None
    for suf in ('internal', 'client'):
        if report_id.endswith(f'-{suf}'):
            audience = suf
            break
    file_deleted = False
    file_error = None
    if seq is not None and audience:
        out_file = SCRIPT_DIR / "data_room" / "reports" / "dcr" / project_code / f"{seq:03d}" / f"{audience}.html"
        try:
            if out_file.exists():
                out_file.unlink()
                file_deleted = True
        except Exception as e:
            file_error = str(e)
            logging.warning(f"DCR HTML delete failed for {report_id}: {file_error}")
    return jsonify({
        "deleted": True, "report_id": report_id, "file_deleted": file_deleted,
        "file_error": file_error,
    }), 200


# ============= DCR AGGREGATOR =============

@app.route('/api/projects/<project_code>/daily/<report_date>', methods=['GET'])
def get_dcr_daily(project_code, report_date):
    """Return the full DCR JSON for (project_code, report_date) at the
    requested audience. ?audience=internal (default) or ?audience=client."""
    audience = request.args.get('audience', 'internal')
    if audience not in ('internal', 'client'):
        return jsonify({"error": "audience must be 'internal' or 'client'"}), 400
    try:
        datetime.strptime(report_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    conn = db()
    if not validate_project_exists(conn, project_code):
        conn.close()
        return jsonify({"error": "Project not found"}), 400
    conn.close()
    try:
        from dcr_aggregator import aggregate_dcr  # lazy to avoid circular import
        dcr = aggregate_dcr(project_code, report_date, audience)
        return response_wrapper(dcr)
    except (KeyError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        logging.error(f"GET /api/projects/{project_code}/daily/{report_date}: {str(e)}")
        return jsonify({"error": str(e)}), 500


def lookup_existing_dcr_sequence(conn, project_code, report_date):
    """If a DCR already exists for (project_code, report_date) at any audience,
    return its dcr_sequence. Otherwise return None. Used to preserve the seq
    number on re-issue (audiences for the same date share one seq)."""
    row = conn.execute(
        "SELECT dcr_sequence FROM report_index "
        "WHERE project_code = ? AND report_date = ? AND report_type = 'DCR' "
        "AND dcr_sequence IS NOT NULL LIMIT 1",
        (project_code, report_date)
    ).fetchone()
    return row['dcr_sequence'] if row else None


def next_dcr_sequence(conn, project_code):
    """Return the next DCR sequence number for a project — the smallest positive
    integer not currently in use. Gap-filling allocation so a deleted sequence
    becomes available again (matches operator mental model: 'delete and re-issue
    reuses the same number'). Per-project counter; tracks ISSUANCE order."""
    used = {row[0] for row in conn.execute(
        "SELECT DISTINCT dcr_sequence FROM report_index "
        "WHERE project_code = ? AND report_type = 'DCR' AND dcr_sequence IS NOT NULL",
        (project_code,)
    )}
    n = 1
    while n in used:
        n += 1
    return n


def _issue_one_dcr(conn, project_code, report_date, audience, seq):
    """Aggregate + render + write + upsert for one audience. Returns
    {report_id, audience, html_url, html_path, sequence}. Caller owns the
    connection + commit/close so 'both' can run as a single transaction; the
    caller also owns the html_path so it can roll back orphaned HTML files
    if the transaction fails after the file write. The seq is computed once
    by the caller and shared across audiences.

    HTML is written ATOMICALLY (.tmp then rename) so a concurrent fetch via
    /files/ during a re-issue can never catch a half-written file."""
    from dcr_aggregator import aggregate_dcr
    from render_dcr_html import DCRHTMLRenderer
    dcr = aggregate_dcr(project_code, report_date, audience)
    report_id = f"DCR-{project_code}-{seq:03d}-{audience}"
    display_id = f"DCR-{project_code}-{seq:03d}"
    dcr['report_id'] = report_id
    dcr['display_id'] = display_id
    dcr['dcr_sequence'] = seq
    html = DCRHTMLRenderer(dcr).render()
    out_dir = SCRIPT_DIR / "data_room" / "reports" / "dcr" / project_code / f"{seq:03d}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{audience}.html"
    tmp_file = out_dir / f"{audience}.html.tmp"
    tmp_file.write_text(html, encoding='utf-8')
    tmp_file.replace(out_file)  # atomic on POSIX and Windows
    rel = out_file.relative_to(SCRIPT_DIR).as_posix()
    html_url = f"/files/{rel}"

    # PDF render: internal audience only (the "full record" copy that gets
    # archived). Client audience stays HTML-only — it's the consumer-facing
    # progress report, not the official record. PDF failure does NOT fail
    # the issuance — HTML is the source of truth; the PDF can be regenerated
    # from it via pdf_export.py. Warnings surface in the response so the UI
    # can show "DCR issued, PDF render failed" instead of pretending it's OK.
    pdf_path = None
    pdf_url = None
    pdf_status = None
    drive_status = None  # Drive archive runs only if PDF render succeeded
    if audience == 'internal':
        from pdf_export import render_html_to_pdf, PDFExportError
        pdf_target = out_dir / f"{audience}.pdf"
        try:
            pdf_status = render_html_to_pdf(out_file, pdf_target)
        except PDFExportError as e:
            pdf_status = {"ok": False, "error": str(e)}
            logging.warning(f"DCR {report_id}: Edge not installed, PDF skipped: {e}")
        if pdf_status.get('ok'):
            pdf_path = pdf_target
            pdf_url = f"/files/{pdf_target.relative_to(SCRIPT_DIR).as_posix()}"
            # Drive archive — copy the local PDF into the project's synced
            # folder. Failure here is a WARN, never an error: local PDF is
            # always retained; Drive may simply not be configured/running.
            from drive_archive import archive_dcr_pdf
            drive_status = archive_dcr_pdf(
                pdf_target, project_code, report_date, seq, audience='internal'
            )
            if not drive_status.get('ok'):
                logging.warning(
                    f"DCR {report_id}: Drive archive {drive_status.get('status','unavailable')} "
                    f"— {drive_status.get('reason')}"
                )
        else:
            logging.warning(
                f"DCR {report_id}: PDF render failed — {pdf_status.get('error')}"
            )

    existing = conn.execute(
        "SELECT id FROM report_index WHERE project_code = ? AND report_type = ? AND report_id = ?",
        (project_code, 'DCR', report_id)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE report_index SET status = ?, report_date = ?, dcr_sequence = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            ('issued', report_date, seq, existing['id'])
        )
    else:
        conn.execute(
            "INSERT INTO report_index (report_date, project_code, report_type, report_id, status, dcr_sequence) VALUES (?, ?, ?, ?, ?, ?)",
            (report_date, project_code, 'DCR', report_id, 'issued', seq)
        )
    return {"report_id": report_id, "audience": audience, "html_url": html_url,
            "html_path": out_file, "display_id": display_id, "sequence": seq,
            "pdf_path": pdf_path, "pdf_url": pdf_url, "pdf_status": pdf_status,
            "drive_status": drive_status}


@app.route('/api/projects/<project_code>/daily/<report_date>/issue', methods=['POST'])
def issue_dcr(project_code, report_date):
    """Issue a DCR for (project_code, report_date) at the given audience.

    Body: {audience: 'internal'|'client'|'both' (default 'internal'),
           override_active: bool (default false)}

    audience='internal' or 'client' returns the legacy single-row shape
    ({report_id, display_id, audience, html_url, sequence, generated_at}).
    audience='both' runs both audiences inside a single transaction and
    returns {internal_url, client_url, internal_report_id, client_report_id,
    display_id, sequence, audience:'both', generated_at}.

    Sequence semantics: per-project counter, tracks ISSUANCE order.
    Both audiences for the same date share one sequence. Re-issuing a DCR
    for the same (project, date) preserves the existing sequence — pass
    override_active=true to opt into the re-issue (otherwise returns 409
    with the existing sequence). The DATE is preserved in the rendered
    HTML body, not in the report_id."""
    data = request.get_json() or {}
    audience = data.get('audience', 'internal')
    override_active = bool(data.get('override_active', False))
    if audience not in ('internal', 'client', 'both'):
        return jsonify({"error": "audience must be 'internal', 'client', or 'both'"}), 400
    try:
        datetime.strptime(report_date, '%Y-%m-%d')
    except ValueError:
        return jsonify({"error": "date must be YYYY-MM-DD"}), 400
    conn = db()
    if not validate_project_exists(conn, project_code):
        conn.close()
        return jsonify({"error": "Project not found"}), 400
    # Track HTML files written so we can roll them back if the transaction
    # fails. Otherwise a half-issued DCR leaves orphan HTML on disk that the
    # /files/ static route would happily serve.
    written_files = []
    try:
        existing_seq = lookup_existing_dcr_sequence(conn, project_code, report_date)
        if existing_seq is not None and not override_active:
            conn.close()
            display_id = f"DCR-{project_code}-{existing_seq:03d}"
            return jsonify({
                "error": f"DCR already exists for {project_code} on {report_date}",
                "existing_sequence": existing_seq,
                "existing_display_id": display_id,
                "hint": "Pass override_active=true to re-issue (sequence stays the same)",
            }), 409
        seq = existing_seq if existing_seq is not None else next_dcr_sequence(conn, project_code)
        display_id = f"DCR-{project_code}-{seq:03d}"
        generated_at = datetime.utcnow().isoformat() + 'Z'
        if audience == 'both':
            internal = _issue_one_dcr(conn, project_code, report_date, 'internal', seq)
            written_files.append(internal["html_path"])
            client = _issue_one_dcr(conn, project_code, report_date, 'client', seq)
            written_files.append(client["html_path"])
            conn.commit()
            conn.close()
            return response_wrapper({
                "audience": "both",
                "generated_at": generated_at,
                "internal_url": internal["html_url"],
                "client_url": client["html_url"],
                "internal_report_id": internal["report_id"],
                "client_report_id": client["report_id"],
                "display_id": display_id,
                "sequence": seq,
                # PDF render runs on internal only; surface its status so the
                # UI can show a "PDF render failed" warning even when HTML
                # issuance succeeded.
                "pdf_url": internal.get("pdf_url"),
                "pdf_status": internal.get("pdf_status"),
                "drive_status": internal.get("drive_status"),
            }), 201
        else:
            result = _issue_one_dcr(conn, project_code, report_date, audience, seq)
            written_files.append(result["html_path"])
            conn.commit()
            conn.close()
            return response_wrapper({
                "report_id": result["report_id"],
                "audience": result["audience"],
                "html_url": result["html_url"],
                "display_id": display_id,
                "sequence": seq,
                "generated_at": generated_at,
                "pdf_url": result.get("pdf_url"),
                "pdf_status": result.get("pdf_status"),
                "drive_status": result.get("drive_status"),
            }), 201
    except (KeyError, ValueError) as e:
        try: conn.rollback()
        except Exception: pass
        conn.close()
        for fp in written_files:
            try: fp.unlink(missing_ok=True)
            except Exception: pass
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        try: conn.rollback()
        except Exception: pass
        conn.close()
        # Orphan-HTML cleanup: any file we wrote before the DB transaction
        # rolled back becomes a ghost report otherwise.
        for fp in written_files:
            try: fp.unlink(missing_ok=True)
            except Exception: pass
        logging.error(
            f"POST /api/projects/{project_code}/daily/{report_date}/issue "
            f"(audience={audience}, override={override_active}): {str(e)}"
        )
        return jsonify({"error": str(e)}), 500


# ============= DCR REPORT ARCHIVE =============

def _display_id(report_id):
    """Strip the trailing -internal / -client suffix from a report_id for
    operator-facing display. Returns the input unchanged if no suffix
    matches. report_id stays in the response as the canonical DB key;
    display_id rides alongside for UI rendering."""
    if not report_id:
        return report_id
    for suffix in ('-internal', '-client'):
        if report_id.endswith(suffix):
            return report_id[:-len(suffix)]
    return report_id


@app.route('/api/projects/<project_code>/reports', methods=['GET'])
def list_reports(project_code):
    """List report_index rows for a project with optional filters.

    Query params:
      report_type (optional) — exact match, e.g. 'DCR'
      audience (optional)    — 'internal' or 'client'; applied via the
                               report_id suffix since report_index has
                               no audience column
      from_date (optional)   — inclusive YYYY-MM-DD
      to_date (optional)     — inclusive YYYY-MM-DD

    Returns {data: [{<row>, audience, html_url}, ...], meta: {count}}
    ordered by report_date DESC, id DESC. html_url is synthesized from
    the disk layout for issued DCR rows; NULL for rows where we can't
    derive a path."""
    # Default to internal-only so the operator-facing archive list shows
    # one row per (project, date). API consumers can pass audience=all to
    # get both audiences (back-compat for callers that relied on the
    # pre-default "no filter" behavior).
    audience = request.args.get('audience', 'internal')
    if audience not in ('internal', 'client', 'all'):
        return jsonify({"error": "audience must be 'internal', 'client', or 'all'"}), 400
    for k in ('from_date', 'to_date'):
        v = request.args.get(k)
        if v:
            try:
                datetime.strptime(v, '%Y-%m-%d')
            except ValueError:
                return jsonify({"error": f"{k} must be YYYY-MM-DD"}), 400
    conn = db()
    if not validate_project_exists(conn, project_code):
        conn.close()
        return jsonify({"error": "Project not found"}), 404
    where = ["project_code = ?"]
    params = [project_code]
    rt = request.args.get('report_type')
    if rt:
        where.append("report_type = ?")
        params.append(rt)
    if audience != 'all':
        where.append("report_id LIKE ?")
        params.append(f"%-{audience}")
    fd = request.args.get('from_date')
    if fd:
        where.append("report_date >= ?")
        params.append(fd)
    td = request.args.get('to_date')
    if td:
        where.append("report_date <= ?")
        params.append(td)
    sql = f"SELECT * FROM report_index WHERE {' AND '.join(where)} ORDER BY report_date DESC, id DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    out = []
    for r in rows:
        d = dict(r)
        rid = d.get('report_id') or ''
        if rid.endswith('-internal'):
            d['audience'] = 'internal'
        elif rid.endswith('-client'):
            d['audience'] = 'client'
        else:
            d['audience'] = None
        if d['audience'] and d.get('dcr_sequence') is not None and d.get('report_type') == 'DCR':
            d['html_url'] = f"/files/data_room/reports/dcr/{project_code}/{d['dcr_sequence']:03d}/{d['audience']}.html"
        else:
            d['html_url'] = None
        d['display_id'] = _display_id(rid)
        out.append(d)
    return response_wrapper(out, count=len(out))


@app.route('/api/projects/<project_code>/reports/latest', methods=['GET'])
def latest_report(project_code):
    """Return the most recent report_index row matching report_type +
    audience (plus optional on_date filter). 200 + {data: null} when
    no row found — per the design call, callers prefer a consistent
    envelope shape over a 404 branch."""
    report_type = request.args.get('report_type', 'DCR')
    audience = request.args.get('audience', 'internal')
    if audience not in ('internal', 'client'):
        return jsonify({"error": "audience must be 'internal' or 'client'"}), 400
    on_date = request.args.get('on_date')
    if on_date:
        try:
            datetime.strptime(on_date, '%Y-%m-%d')
        except ValueError:
            return jsonify({"error": "on_date must be YYYY-MM-DD"}), 400
    conn = db()
    if not validate_project_exists(conn, project_code):
        conn.close()
        return jsonify({"error": "Project not found"}), 404
    where = ["project_code = ?", "report_type = ?", "report_id LIKE ?"]
    params = [project_code, report_type, f"%-{audience}"]
    if on_date:
        where.append("report_date = ?")
        params.append(on_date)
    sql = f"SELECT * FROM report_index WHERE {' AND '.join(where)} ORDER BY report_date DESC, id DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    conn.close()
    if not row:
        return response_wrapper(None)
    d = dict(row)
    d['audience'] = audience
    if d.get('dcr_sequence') is not None and d.get('report_type') == 'DCR':
        d['html_url'] = f"/files/data_room/reports/dcr/{project_code}/{d['dcr_sequence']:03d}/{audience}.html"
    else:
        d['html_url'] = None
    d['display_id'] = _display_id(d.get('report_id'))
    try:
        rd = datetime.strptime(d['report_date'], '%Y-%m-%d').date()
        d['days_ago'] = (date.today() - rd).days
    except (ValueError, TypeError):
        d['days_ago'] = None
    return response_wrapper(d)


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
    """Create new employee. Allocates a fresh Worker ID (W-####) for the
    human-facing display label — bulk-import in import_workers.py uses the
    same allocator (worker_id.next_worker_id_sequence) so single-onboards
    and CSV imports never collide. employee_id is still the internal PK."""
    try:
        from worker_id import assign_worker_id
        data = request.get_json()
        employee_id = data.get('employee_id') or str(uuid.uuid4())[:8]
        name = data.get('name')
        trade = data.get('trade')

        conn = db()
        worker_id = assign_worker_id(conn)
        conn.execute(
            "INSERT INTO employees (employee_id, worker_id, name, trade, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (employee_id, worker_id, name, trade,
             datetime.now().isoformat(), datetime.now().isoformat())
        )
        conn.commit()

        row = conn.execute("SELECT * FROM employees WHERE employee_id = ?", (employee_id,)).fetchone()
        conn.close()

        return response_wrapper(dict(row) if row else {"employee_id": employee_id, "worker_id": worker_id}), 201
    except Exception as e:
        logging.error(f"POST /api/employees: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/employees/<emp_id>', methods=['PATCH'])
def update_employee(emp_id):
    """Edit an existing employee. Allowed fields: name, trade, dob, phone,
    email, emergency_contact_*, language, hire_date.

    Side-effects run inside a single DB transaction:
    - phone change re-derives PIN (last-4 of digits-only) and checks collision
      against every other row; conflict aborts with 409, no DB write.
    - name change renames worker_records/{emp_id}_{slug}/ on disk after the
      DB UPDATE but before commit; rename failure rolls the UPDATE back.

    Immutable post-import: employee_id, pin (mutated only via phone),
    folder_path (mutated only via name), intake_status, face_image_path,
    photo_path, created_at, updated_at."""
    import re
    EDITABLE = {'name', 'trade', 'dob', 'phone', 'email',
                'emergency_contact_name', 'emergency_contact_phone',
                'emergency_contact_relation', 'language', 'hire_date'}

    try:
        data = request.get_json(silent=True) or {}

        # ----- Pre-validation (no DB writes) -----
        if 'name' in data and not (data.get('name') or '').strip():
            return jsonify({"error": "name cannot be empty"}), 400
        if 'phone' in data and not (data.get('phone') or '').strip():
            return jsonify({"error": "phone cannot be empty"}), 400
        if 'language' in data and data['language'] and data['language'] not in ('EN', 'ES'):
            return jsonify({"error": "language must be 'EN' or 'ES'"}), 400
        for df in ('dob', 'hire_date'):
            if df in data and data[df]:
                try:
                    datetime.strptime(data[df], "%Y-%m-%d")
                except ValueError:
                    return jsonify({"error": f"{df} must be ISO YYYY-MM-DD"}), 400
        if 'phone' in data and data['phone']:
            if len(re.sub(r'\D', '', data['phone'])) < 4:
                return jsonify({"error": "phone must contain at least 4 digits"}), 400

        # ----- Build updates dict from editable fields only -----
        updates = {}
        for k in EDITABLE:
            if k in data:
                v = data[k]
                if isinstance(v, str):
                    v = v.strip()
                    updates[k] = v if v else None
                else:
                    updates[k] = v

        if not updates:
            return jsonify({"error": "No editable fields in payload"}), 400

        conn = db()
        current = conn.execute(
            "SELECT employee_id, folder_path FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
        if not current:
            conn.close()
            return jsonify({"error": "employee not found"}), 404

        # ----- Phone change → re-derive PIN + collision check -----
        pin_changed = False
        new_pin = None
        if 'phone' in updates and updates['phone']:
            phone_digits = re.sub(r'\D', '', updates['phone'])
            new_pin = phone_digits[-4:]
            collision = conn.execute(
                "SELECT employee_id FROM employees WHERE pin = ? AND employee_id != ?",
                (new_pin, emp_id)
            ).fetchone()
            if collision:
                conn.close()
                return jsonify({
                    "error": f"PIN collision with {collision['employee_id']} — choose a phone with different last-4"
                }), 409
            updates['phone'] = phone_digits
            updates['pin'] = new_pin
            pin_changed = True

        # ----- Name change → prepare folder rename (done after UPDATE so the
        #      DB rollback path is meaningful) -----
        rename_from = None
        rename_to = None
        if 'name' in updates and updates['name']:
            new_slug = slugify_name(updates['name'])
            new_folder = WORKER_RECORDS_DIR / f"{emp_id}_{new_slug}"
            current_folder_path = current['folder_path']
            if current_folder_path:
                current_folder = Path(current_folder_path)
                if current_folder.resolve() != new_folder.resolve():
                    if current_folder.exists():
                        rename_from = current_folder
                        rename_to = new_folder
                    updates['folder_path'] = str(new_folder)
            else:
                updates['folder_path'] = str(new_folder)

        # ----- UPDATE row -----
        set_clauses = [f"{k} = ?" for k in updates] + ["updated_at = CURRENT_TIMESTAMP"]
        params = list(updates.values()) + [emp_id]
        conn.execute(
            f"UPDATE employees SET {', '.join(set_clauses)} WHERE employee_id = ?",
            params
        )

        # ----- Folder side-effects (transaction still open) -----
        if rename_from is not None:
            try:
                rename_from.rename(rename_to)
            except OSError as e:
                conn.rollback()
                conn.close()
                return jsonify({"error": f"folder rename failed: {e}"}), 500
        elif 'folder_path' in updates:
            try:
                Path(updates['folder_path']).mkdir(parents=True, exist_ok=True)
            except OSError as e:
                conn.rollback()
                conn.close()
                return jsonify({"error": f"folder mkdir failed: {e}"}), 500

        conn.commit()

        row = conn.execute(
            "SELECT * FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
        conn.close()

        # CLAUDE.md PII discipline: pin is not volunteered in normal responses.
        # Only surfaced when this call caused the change so the operator can
        # share the new PIN with the worker once.
        result = dict(row) if row else {}
        result.pop('pin', None)
        if pin_changed:
            result['pin_changed'] = True
            result['new_pin'] = new_pin

        return response_wrapper(result), 200
    except Exception as e:
        app.logger.error(f"PATCH /api/employees/{emp_id} failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/employees/<emp_id>/intake/complete', methods=['POST'])
def complete_intake(emp_id):
    """Guarded forward transition: intake_status 'pending' → 'done'.

    intake_status is excluded from PATCH /api/employees' EDITABLE set so the
    field can't be flipped by a generic worker edit. This is the ONLY endpoint
    that moves a worker into intake-complete state. Forward-only — there is
    no reverse route. Idempotent: an already-done worker returns 200 with
    {already_done: true} so the operator's 'Complete Intake' button is safe
    to re-click without producing a 409.

    Intake completion is operator-driven (the operator decides when the work
    is done); the server doesn't gate on which artifacts are on file."""
    conn = None
    try:
        conn = db()
        emp = conn.execute(
            "SELECT employee_id, intake_status FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
        if not emp:
            return jsonify({"error": "employee not found"}), 404
        if emp["intake_status"] == "done":
            return response_wrapper({
                "employee_id": emp_id,
                "intake_status": "done",
                "already_done": True,
            }), 200
        conn.execute(
            "UPDATE employees SET intake_status = 'done', updated_at = CURRENT_TIMESTAMP "
            "WHERE employee_id = ?",
            (emp_id,)
        )
        conn.commit()
        return response_wrapper({
            "employee_id": emp_id,
            "intake_status": "done",
            "already_done": False,
        }), 200
    except Exception as e:
        logging.error(f"POST /api/employees/{emp_id}/intake/complete: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


def _worker_history_counts(conn, emp_id):
    """Count rows that prevent hard-delete (preserves accuracy of historical
    DCRs, Weekly Hours Log, and credential audit trail). Returns a dict
    keyed by table for the operator-facing diagnostic, plus a `total`."""
    counts = {}
    for tbl in ('sign_in_log', 'certifications', 'worker_documents',
                'cof_cards', 'company_id_cards'):
        n = conn.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE employee_id = ?", (emp_id,)
        ).fetchone()[0]
        counts[tbl] = n
    counts['total'] = sum(v for k, v in counts.items() if k != 'total')
    return counts


@app.route('/api/employees/<emp_id>', methods=['DELETE'])
def delete_employee(emp_id):
    """Delete a worker. Auto-dispatches between hard-delete and soft-archive
    based on whether the worker has any operational history:

      - NO history (sign_in_log, certifications, worker_documents, cof_cards,
        company_id_cards all empty for this employee) → hard-delete. Removes
        the employees row plus its project_assignments. Safe to wipe; nothing
        else references this worker.

      - HAS history → soft-archive: sets employees.archived_at = NOW. The
        sign-ins, certs, docs, and cards remain so historical DCRs and the
        Weekly Hours Log stay accurate. project_assignments stays so the
        archived worker can be re-activated later by clearing archived_at.

    Archived workers are filtered out of the workforce list, the project
    worker list, and the intake-summary list by default. Pass
    ?include_archived=true on those GETs to see them.

    Body: optional {reason}. 404 if worker doesn't exist; 409 if already
    archived. Hard-delete returns 200 with {deleted: 'hard'}; archive
    returns 200 with {deleted: 'archived'} + the history counts that
    forced the soft path."""
    conn = None
    try:
        data = request.get_json(silent=True) or {}
        reason = (data.get('reason') or '').strip() or None
        conn = db()
        emp = conn.execute(
            "SELECT employee_id, archived_at FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
        if not emp:
            return jsonify({"error": "employee not found"}), 404
        if emp["archived_at"]:
            return jsonify({"error": "employee already archived",
                            "archived_at": emp["archived_at"]}), 409
        counts = _worker_history_counts(conn, emp_id)
        if counts["total"] == 0:
            # Hard-delete: project_assignments first (no FK cascade configured),
            # then the employees row. Worker folder on disk is left in place —
            # it's the audit/intake artifact, and a re-onboard with the same
            # name would reuse it.
            conn.execute("DELETE FROM project_assignments WHERE employee_id = ?", (emp_id,))
            conn.execute("DELETE FROM employees WHERE employee_id = ?", (emp_id,))
            conn.commit()
            return response_wrapper({
                "employee_id": emp_id,
                "deleted": "hard",
                "history_counts": counts,
            }), 200
        else:
            # Soft-archive: mark archived_at + reason. History rows stay.
            conn.execute(
                "UPDATE employees SET archived_at = CURRENT_TIMESTAMP, "
                "archived_reason = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE employee_id = ?",
                (reason, emp_id)
            )
            conn.commit()
            row = conn.execute(
                "SELECT archived_at, archived_reason FROM employees WHERE employee_id = ?",
                (emp_id,)
            ).fetchone()
            return response_wrapper({
                "employee_id": emp_id,
                "deleted": "archived",
                "archived_at": row["archived_at"],
                "archived_reason": row["archived_reason"],
                "history_counts": counts,
            }), 200
    except Exception as e:
        logging.error(f"DELETE /api/employees/{emp_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


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
    """List employees. Archived workers (archived_at IS NOT NULL) are
    filtered out by default. Pass ?include_archived=true to include them
    (e.g., for restore flows or a 'recently archived' view)."""
    include_archived = (request.args.get('include_archived', '').lower()
                        in ('1', 'true', 'yes'))
    conn = db()
    if include_archived:
        rows = conn.execute("SELECT * FROM employees").fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM employees WHERE archived_at IS NULL"
        ).fetchall()
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
            "project_code": "FR-BX-001",
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
        project_code = data.get('project_code') or 'FR-BX-001'
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
    """Upload a site photo to disk + record metadata in the photos table.

    Disk layout: data_room/photos/<project_code>/<date>/<location>/<ts>_<uuid8>.<ext>
    On DB INSERT failure, the on-disk file is rolled back (deleted) so disk
    state and DB state never diverge. Replaces the prior contract (session_id,
    zone, scope, latitude, longitude) which had no live callers."""
    try:
        if 'photo' not in request.files:
            return jsonify({"error": "No photo file"}), 400
        project_code = request.form.get('project_code')
        if not project_code:
            return jsonify({"error": "project_code required"}), 400
        try:
            date_str = _parse_dcr_date(request.form.get('date'))
        except ValueError:
            return jsonify({"error": "date must be YYYY-MM-DD"}), 400

        conn = db()
        if not validate_project_exists(conn, project_code):
            conn.close()
            return jsonify({"error": "Project not found"}), 400
        conn.close()

        location = (request.form.get('location') or 'Unknown').strip() or 'Unknown'
        description = request.form.get('description')
        uploaded_by = request.form.get('uploaded_by')

        photo_file = request.files['photo']
        orig_name = photo_file.filename or ""
        ext = Path(orig_name).suffix.lower()
        if ext not in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.heif'}:
            ext = ".jpg"

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        photo_uuid = uuid.uuid4().hex[:8]
        filename = f"{timestamp}_{photo_uuid}{ext}"

        photos_base = (SCRIPT_DIR / "data_room" / "photos").resolve()
        photo_dir = SCRIPT_DIR / "data_room" / "photos" / project_code / date_str / location
        if not photo_dir.resolve().is_relative_to(photos_base):
            return jsonify({"error": "Invalid location path"}), 400
        photo_dir.mkdir(parents=True, exist_ok=True)

        file_path = photo_dir / filename
        photo_file.save(str(file_path))

        rel = file_path.relative_to(SCRIPT_DIR).as_posix()
        url = f"/files/{rel}"

        conn = db()
        try:
            conn.execute(
                "INSERT INTO photos (date, project_code, file_path, filename, url, "
                "location, description, uploaded_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (date_str, project_code, str(file_path), filename, url,
                 location, description, uploaded_by)
            )
            conn.commit()
            new_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()['id']
            row = conn.execute("SELECT * FROM photos WHERE id = ?", (new_id,)).fetchone()
            conn.close()
            return response_wrapper(dict(row)), 201
        except Exception as db_err:
            conn.close()
            try:
                file_path.unlink(missing_ok=True)
            except Exception:
                pass
            logging.error(f"POST /api/photos/upload DB insert failed, rolled back file {file_path}: {db_err}")
            return jsonify({"error": f"DB insert failed: {db_err}"}), 500
    except Exception as e:
        logging.error(f"POST /api/photos/upload: {str(e)}")
        return jsonify({"error": str(e)}), 500

@app.route('/api/photos', methods=['GET'])
def get_photos():
    """Get photos for a date/project"""
    try:
        date_filter = request.args.get('date', date.today().isoformat())
        project_code = request.args.get('project', 'FR-BX-001')
        
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
    """Workers ASSIGNED to a specific project (the filtered roster for the
    project dashboard). Archived workers are filtered out — pass
    ?include_archived=true to include them."""
    try:
        include_archived = (request.args.get('include_archived', '').lower()
                            in ('1', 'true', 'yes'))
        conn = db()
        archive_clause = '' if include_archived else ' AND e.archived_at IS NULL'
        rows = conn.execute(
            f"""SELECT e.*, pa.role_on_project, pa.start_date AS assignment_start, pa.status AS assignment_status
               FROM employees e
               JOIN project_assignments pa ON pa.employee_id = e.employee_id
               WHERE pa.project_code = ? AND pa.status = 'active'{archive_clause}
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


@app.route('/api/workers/<employee_id>/certs/<int:cert_id>', methods=['PATCH'])
def api_worker_patch_cert(employee_id, cert_id):
    """Edit fields on an existing certification row.

    Editable: cert_type_id, date_obtained, expiration_date, status,
    card_number, issuing_body, notes, scan_path. Mirrors the validation
    in POST/import (dates ISO YYYY-MM-DD, expiration_date >= date_obtained
    when both supplied). 404 if the cert id doesn't belong to the named
    employee — prevents cross-worker edits via guessed ids."""
    EDITABLE = {'cert_type_id', 'date_obtained', 'expiration_date', 'status',
                'card_number', 'issuing_body', 'notes', 'scan_path'}
    data = request.get_json(silent=True) or {}
    updates = {}
    for k in EDITABLE:
        if k in data:
            v = data[k]
            if isinstance(v, str):
                v = v.strip() or None
            updates[k] = v
    if not updates:
        return jsonify({"error": "no editable fields in payload"}), 400
    for df in ('date_obtained', 'expiration_date'):
        if df in updates and updates[df]:
            try:
                datetime.strptime(updates[df], '%Y-%m-%d')
            except ValueError:
                return jsonify({"error": f"{df} must be ISO YYYY-MM-DD"}), 400

    conn = db()
    try:
        existing = conn.execute(
            "SELECT id, date_obtained, expiration_date FROM certifications "
            "WHERE id = ? AND employee_id = ?",
            (cert_id, employee_id)
        ).fetchone()
        if not existing:
            return jsonify({"error": "certification not found"}), 404
        # Cross-field validation against the post-merge state, not just the
        # incoming payload — operator can update one half of the date pair.
        merged_do = updates.get('date_obtained', existing['date_obtained'])
        merged_exp = updates.get('expiration_date', existing['expiration_date'])
        if merged_do and merged_exp and merged_exp < merged_do:
            return jsonify({
                "error": f"expiration_date ({merged_exp}) is before date_obtained ({merged_do})"
            }), 400
        set_clauses = [f"{k} = ?" for k in updates] + ["updated_at = CURRENT_TIMESTAMP"]
        params = list(updates.values()) + [cert_id]
        conn.execute(
            f"UPDATE certifications SET {', '.join(set_clauses)} WHERE id = ?",
            params
        )
        conn.commit()
        row = conn.execute("SELECT * FROM certifications WHERE id = ?", (cert_id,)).fetchone()
        return response_wrapper(dict(row)), 200
    except Exception as e:
        logging.error(f"PATCH /api/workers/{employee_id}/certs/{cert_id}: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()


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


@app.route('/api/employees/<employee_id>/certifications/extract', methods=['POST'])
def api_certification_extract(employee_id):
    """Upload a cert card photo, save to the worker folder, run vision-based
    extraction, return structured cert data for operator review.

    Does NOT insert into certifications — the operator reviews the extracted
    fields and then POSTs to /api/employees/<id>/certifications to save.

    Multipart form fields: file=<image>.

    Returns {extracted, image_path, image_url}. image_url is what the
    operator's browser fetches to render the saved photo via /worker-files/.
    """
    import re as _re
    try:
        if 'file' not in request.files:
            return jsonify({"error": "no file in request"}), 400
        f = request.files['file']
        if not f.filename:
            return jsonify({"error": "empty filename"}), 400

        # Same whitelist used by api_worker_upload — images + PDF.
        if f.mimetype not in ALLOWED_DOC_MIME_TYPES:
            return jsonify({"error": f"file type {f.mimetype} not allowed"}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in ALLOWED_DOC_EXTENSIONS:
            return jsonify({"error": f"file extension {ext} not allowed"}), 400

        conn = db()
        emp = conn.execute(
            "SELECT employee_id, name, folder_path FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
        if not emp:
            conn.close()
            return jsonify({"error": "employee not found"}), 404

        # Back-fill folder_path if the row predates the standardized layout.
        folder_path = emp["folder_path"]
        if not folder_path:
            folder_slug = slugify_name(emp["name"])
            folder_path = str(WORKER_RECORDS_DIR / f"{employee_id}_{folder_slug}")
            conn.execute(
                "UPDATE employees SET folder_path = ? WHERE employee_id = ?",
                (folder_path, employee_id)
            )
            conn.commit()

        folder = Path(folder_path).resolve()
        if not str(folder).startswith(str(WORKER_RECORDS_DIR.resolve())):
            conn.close()
            return jsonify({"error": "invalid folder path"}), 400

        certs_dir = folder / "certs"
        certs_dir.mkdir(parents=True, exist_ok=True)

        # cert_N.<ext>. Pick N = max(existing) + 1 — never overwrite.
        existing_nums = []
        for p in certs_dir.iterdir():
            m = _re.match(r"^cert_(\d+)", p.name)
            if m:
                existing_nums.append(int(m.group(1)))
        next_n = (max(existing_nums) + 1) if existing_nums else 1
        target_path = (certs_dir / f"cert_{next_n}{ext}").resolve()
        if not str(target_path).startswith(str(WORKER_RECORDS_DIR.resolve())):
            conn.close()
            return jsonify({"error": "path traversal blocked"}), 400

        f.save(str(target_path))
        conn.close()

        # AI extraction is OPTIONAL — the server boots without
        # ANTHROPIC_API_KEY. When it's not configured (continuous-run Path A),
        # the cert-card photo is still saved to the worker folder and the
        # operator can fall back to manual cert entry. Return 503 with a clean
        # "feature disabled" signal so the UI can show "AI unavailable — use
        # manual entry" rather than treating it as an error.
        relative = target_path.relative_to(WORKER_RECORDS_DIR.resolve())
        image_url = "/worker-files/" + str(relative).replace("\\", "/")
        if not os.environ.get('ANTHROPIC_API_KEY'):
            return jsonify({
                "error": "AI extraction disabled — ANTHROPIC_API_KEY not configured",
                "ai_available": False,
                "image_path": str(target_path),
                "image_url": image_url,
                "note": "Image saved. Use manual entry to record cert data.",
            }), 503

        # Run extraction. If the API call fails, leave the image on disk so the
        # operator can retry or do manual entry — return 500 with the path.
        try:
            cert_types = load_cert_types_from_db(DB_PATH)
            extracted = extract_cert_from_image(target_path, cert_types)
        except (RuntimeError, FileNotFoundError) as e:
            app.logger.error(f"cert extraction failed for {target_path}: {e}")
            return jsonify({
                "error": f"extraction failed: {e}",
                "image_path": str(target_path),
                "note": "image saved on disk; operator can retry or use manual entry",
            }), 500

        return response_wrapper({
            "extracted": extracted,
            "image_path": str(target_path),
            "image_url": image_url,
        })
    except Exception as e:
        app.logger.error(f"POST /api/employees/{employee_id}/certifications/extract failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route('/api/employees/<employee_id>/certifications', methods=['POST'])
def api_certification_save(employee_id):
    """Save a confirmed certification row after operator review. Mirrors the
    validation rules in import_certifications.py and dedups on the same
    4-tuple (employee_id, cert_type_id, card_number, date_obtained).

    JSON body: cert_type_id (required), card_number, date_obtained,
    expiration_date, issuing_body, notes, scan_path.

    On dedup hit: 200 with {already_exists: True, row}. Otherwise 201 with
    {already_exists: False, cert_id, row}."""
    try:
        data = request.get_json(silent=True) or {}

        cert_type_id = (data.get("cert_type_id") or "").strip()
        card_number = (data.get("card_number") or "").strip() or None
        date_obtained = (data.get("date_obtained") or "").strip() or None
        expiration_date = (data.get("expiration_date") or "").strip() or None
        issuing_body = (data.get("issuing_body") or "").strip() or None
        notes = (data.get("notes") or "").strip() or None
        scan_path = (data.get("scan_path") or "").strip() or None

        if not cert_type_id:
            return jsonify({"error": "cert_type_id is required"}), 400
        for df, dval in (("date_obtained", date_obtained), ("expiration_date", expiration_date)):
            if dval:
                try:
                    datetime.strptime(dval, "%Y-%m-%d")
                except ValueError:
                    return jsonify({"error": f"{df} must be ISO YYYY-MM-DD"}), 400
        if date_obtained and expiration_date and expiration_date < date_obtained:
            return jsonify({
                "error": f"expiration_date ({expiration_date}) is before date_obtained ({date_obtained})"
            }), 400

        conn = db()

        emp = conn.execute(
            "SELECT employee_id FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
        if not emp:
            conn.close()
            return jsonify({"error": "employee not found"}), 404

        ct = conn.execute(
            "SELECT cert_type_id FROM cert_types WHERE cert_type_id = ?",
            (cert_type_id,)
        ).fetchone()
        if not ct:
            conn.close()
            return jsonify({
                "error": f"cert_type_id={cert_type_id!r} not in cert_types library"
            }), 400

        # 4-tuple dedup. IFNULL(...) so NULL == NULL behaves intuitively.
        existing = conn.execute(
            "SELECT id FROM certifications "
            "WHERE employee_id = ? AND cert_type_id = ? "
            "AND IFNULL(card_number, '') = IFNULL(?, '') "
            "AND IFNULL(date_obtained, '') = IFNULL(?, '')",
            (employee_id, cert_type_id, card_number, date_obtained)
        ).fetchone()
        if existing:
            row = conn.execute(
                "SELECT * FROM certifications WHERE id = ?", (existing["id"],)
            ).fetchone()
            conn.close()
            return response_wrapper({
                "cert_id": existing["id"],
                "already_exists": True,
                "row": dict(row),
            }), 200

        cur = conn.execute(
            """INSERT INTO certifications
               (employee_id, cert_type_id, card_number, date_obtained,
                expiration_date, issuing_body, notes, status, scan_path)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?)""",
            (employee_id, cert_type_id, card_number, date_obtained,
             expiration_date, issuing_body, notes, scan_path)
        )
        new_id = cur.lastrowid
        conn.commit()
        row = conn.execute(
            "SELECT * FROM certifications WHERE id = ?", (new_id,)
        ).fetchone()
        conn.close()

        return response_wrapper({
            "cert_id": new_id,
            "already_exists": False,
            "row": dict(row),
        }), 201
    except Exception as e:
        app.logger.error(f"POST /api/employees/{employee_id}/certifications failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/employees/<employee_id>/certifications', methods=['GET'])
def api_certifications_list(employee_id):
    """List one worker's certifications, joined with cert_types for the
    human-readable cert name and CoF-prereq flag. Adds a derived status field
    so the frontend can color-code at render time without re-computing.

    status_derived values:
      - 'valid'    — no expiration, or expires more than 30 days out
      - 'expiring' — expires within 30 days
      - 'expired'  — expiration date is in the past
      - 'unknown'  — no expiration_date AND no date_obtained
    """
    try:
        conn = db()
        emp = conn.execute(
            "SELECT employee_id FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
        if not emp:
            conn.close()
            return jsonify({"error": "employee not found"}), 404

        rows = conn.execute(
            """SELECT c.id AS cert_id, c.cert_type_id, ct.name AS cert_name,
                      ct.is_cof_prerequisite, c.card_number, c.date_obtained,
                      c.expiration_date, c.issuing_body, c.scan_path, c.status,
                      c.notes, c.created_at, c.updated_at
               FROM certifications c
               LEFT JOIN cert_types ct ON ct.cert_type_id = c.cert_type_id
               WHERE c.employee_id = ?
               ORDER BY
                 CASE WHEN c.expiration_date IS NULL THEN 1 ELSE 0 END,
                 c.expiration_date ASC,
                 c.id DESC""",
            (employee_id,)
        ).fetchall()
        conn.close()

        today = date.today()
        d30 = today + timedelta(days=30)
        today_iso = today.isoformat()
        d30_iso = d30.isoformat()

        out = []
        for r in rows:
            row = dict(r)
            exp = row.get("expiration_date")
            if not exp and not row.get("date_obtained"):
                row["status_derived"] = "unknown"
            elif not exp:
                row["status_derived"] = "valid"
            elif exp < today_iso:
                row["status_derived"] = "expired"
            elif exp <= d30_iso:
                row["status_derived"] = "expiring"
            else:
                row["status_derived"] = "valid"
            # Compact a browser-friendly URL for the scan, alongside the raw path.
            sp = row.get("scan_path")
            if sp:
                try:
                    rel = Path(sp).resolve().relative_to(WORKER_RECORDS_DIR.resolve())
                    row["scan_url"] = "/worker-files/" + str(rel).replace("\\", "/")
                except (ValueError, OSError):
                    row["scan_url"] = None
            else:
                row["scan_url"] = None
            out.append(row)

        return response_wrapper(out, count=len(out))
    except Exception as e:
        app.logger.error(f"GET /api/employees/{employee_id}/certifications failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/employees/<employee_id>/face-photo', methods=['POST'])
def api_employee_face_photo(employee_id):
    """Upload a face photo for the worker. Overwrites any existing face image
    (the worker has one current face — re-taking replaces). Updates
    employees.face_image_path."""
    try:
        if 'file' not in request.files:
            return jsonify({"error": "no file in request"}), 400
        f = request.files['file']
        if not f.filename:
            return jsonify({"error": "empty filename"}), 400

        # Face photos: images only — explicitly reject PDF even though it's
        # in the wider doc-upload whitelist.
        FACE_IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.heic', '.heif'}
        if f.mimetype not in ALLOWED_DOC_MIME_TYPES or f.mimetype == 'application/pdf':
            return jsonify({"error": f"face photo must be an image (got {f.mimetype})"}), 400
        ext = Path(f.filename).suffix.lower()
        if ext not in FACE_IMAGE_EXTS:
            return jsonify({"error": f"face photo extension {ext} not allowed"}), 400

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
            conn.commit()

        folder = Path(folder_path).resolve()
        if not str(folder).startswith(str(WORKER_RECORDS_DIR.resolve())):
            conn.close()
            return jsonify({"error": "invalid folder path"}), 400

        folder.mkdir(parents=True, exist_ok=True)

        # Remove any prior face.* so we don't leave a stale file when the
        # extension changes between uploads (face.jpg → face.heic etc.).
        for old in folder.glob("face.*"):
            try:
                old.unlink()
            except OSError as e:
                app.logger.warning(f"could not remove old face file {old}: {e}")

        target_path = (folder / f"face{ext}").resolve()
        if not str(target_path).startswith(str(WORKER_RECORDS_DIR.resolve())):
            conn.close()
            return jsonify({"error": "path traversal blocked"}), 400

        f.save(str(target_path))

        # iPhones default to HEIC; browsers can't render HEIC in <img>. Convert
        # to a sibling face.jpg so the profile thumbnail is always renderable.
        # The HEIC original is preserved as source-of-truth; face_image_path
        # points at the JPEG so the UI just works without conditional logic.
        displayable_path = target_path
        heic_conversion = None
        if ext in {'.heic', '.heif'}:
            try:
                from PIL import Image
                import pillow_heif
                pillow_heif.register_heif_opener()
                with Image.open(str(target_path)) as im:
                    if im.mode != 'RGB':
                        im = im.convert('RGB')
                    jpeg_path = (folder / "face.jpg").resolve()
                    im.save(str(jpeg_path), "JPEG", quality=85, optimize=True)
                displayable_path = jpeg_path
                heic_conversion = {"ok": True, "original": str(target_path),
                                   "jpeg": str(jpeg_path)}
            except Exception as e:
                app.logger.warning(
                    f"HEIC->JPEG conversion failed for {employee_id} "
                    f"({target_path.name}): {e}"
                )
                heic_conversion = {"ok": False, "error": str(e)}
                # Fall through: face_image_path still points at the HEIC. The
                # UI will fail to render it but the record + file are intact.

        conn.execute(
            "UPDATE employees SET face_image_path = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE employee_id = ?",
            (str(displayable_path), employee_id)
        )
        conn.commit()
        conn.close()

        relative = displayable_path.relative_to(WORKER_RECORDS_DIR.resolve())
        image_url = "/worker-files/" + str(relative).replace("\\", "/")

        return response_wrapper({
            "face_image_path": str(displayable_path),
            "image_url": image_url,
            "heic_conversion": heic_conversion,
        })
    except Exception as e:
        app.logger.error(f"POST /api/employees/{employee_id}/face-photo failed: {e}")
        return jsonify({"error": str(e)}), 400


@app.route('/api/employees/<employee_id>/face-photo', methods=['DELETE'])
def api_employee_face_photo_delete(employee_id):
    """Remove a worker's face photo. Clears employees.face_image_path and
    unlinks face.* files from disk. After deletion the worker can't be
    issued a new credential — POST /credential/issue hard-gates on
    face_image_path — until a new face photo is uploaded.

    404 if the worker doesn't exist. Idempotent — a worker who already has
    no face photo returns 200 with {already_absent: true}. DB is the source
    of truth; file unlink errors are logged but don't fail the response."""
    conn = None
    try:
        conn = db()
        emp = conn.execute(
            "SELECT employee_id, face_image_path, folder_path "
            "FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
        if not emp:
            return jsonify({"error": "employee not found"}), 404
        if not emp["face_image_path"]:
            return response_wrapper({
                "employee_id": employee_id,
                "face_image_path": None,
                "files_unlinked": 0,
                "already_absent": True,
            }), 200
        conn.execute(
            "UPDATE employees SET face_image_path = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE employee_id = ?",
            (employee_id,)
        )
        conn.commit()

        files_unlinked = 0
        folder = emp["folder_path"]
        if folder:
            try:
                fp = Path(folder).resolve()
                if str(fp).startswith(str(WORKER_RECORDS_DIR.resolve())):
                    for old in fp.glob("face.*"):
                        try:
                            old.unlink()
                            files_unlinked += 1
                        except OSError as e:
                            app.logger.warning(
                                f"face-photo unlink failed for {employee_id} {old}: {e}"
                            )
            except Exception as e:
                app.logger.warning(
                    f"face-photo dir cleanup failed for {employee_id}: {e}"
                )

        return response_wrapper({
            "employee_id": employee_id,
            "face_image_path": None,
            "files_unlinked": files_unlinked,
            "already_absent": False,
        }), 200
    except Exception as e:
        logging.error(f"DELETE /api/employees/{employee_id}/face-photo: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


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
    """List of all workers with intake status + cert health + doc count
    + credential eligibility + current_credential state. The two new
    fields let the workforce list render the Action button per row
    without follow-up round-trips.

    Archived workers are filtered out by default. Pass ?include_archived=true
    to include them."""
    try:
        include_archived = (request.args.get('include_archived', '').lower()
                            in ('1', 'true', 'yes'))
        # Lazy import — cof_issuer needs the DB open and we want server.py
        # startup to stay light.
        from cof_issuer import has_valid_prerequisite
        conn = db()
        if include_archived:
            emps = conn.execute(
                "SELECT employee_id, worker_id, name, trade, phone, language, intake_status, folder_path, archived_at "
                "FROM employees ORDER BY worker_id"
            ).fetchall()
        else:
            emps = conn.execute(
                "SELECT employee_id, worker_id, name, trade, phone, language, intake_status, folder_path "
                "FROM employees WHERE archived_at IS NULL ORDER BY worker_id"
            ).fetchall()

        today = datetime.utcnow().date().isoformat()
        out = []
        for e in emps:
            emp_id = e["employee_id"]
            doc_count = conn.execute(
                "SELECT COUNT(*) FROM worker_documents WHERE employee_id = ?", (emp_id,)
            ).fetchone()[0]
            certs = conn.execute(
                """SELECT cert_type_id, expiration_date, status FROM certifications
                   WHERE employee_id = ?""", (emp_id,)
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
            # Eligibility: SCAFFOLD-16 or RIGGER-32 currently valid → 'cof'; else 'company_id'.
            eligible, _ = has_valid_prerequisite(emp_id)
            eligibility = 'cof' if eligible else 'company_id'
            # Current credential — CoF (status='issued') takes precedence; fall back to Company ID (status='active').
            # html_url is derived from html_export_path so the workforce-list View button
            # has a direct link without a follow-up GET /credential round-trip.
            current_credential = None
            cof_row = conn.execute(
                """SELECT card_id, card_number_display, issued_date, expires_date, status, html_export_path FROM cof_cards
                   WHERE employee_id = ? AND status = 'issued'
                   ORDER BY issued_date DESC LIMIT 1""",
                (emp_id,)
            ).fetchone()
            if cof_row:
                cof_html = cof_row["html_export_path"]
                current_credential = {
                    "type": "cof",
                    "card_number_display": cof_row["card_number_display"] or cof_row["card_id"],
                    "issued_date": cof_row["issued_date"],
                    "expires_date": cof_row["expires_date"],
                    "status": cof_row["status"],
                    "html_url": ("/files/" + cof_html) if cof_html else None,
                }
            else:
                cid_row = conn.execute(
                    """SELECT card_id, card_number_display, issued_date, status, html_export_path FROM company_id_cards
                       WHERE employee_id = ? AND status = 'active'
                       ORDER BY issued_date DESC, created_at DESC LIMIT 1""",
                    (emp_id,)
                ).fetchone()
                if cid_row:
                    cid_html = cid_row["html_export_path"]
                    current_credential = {
                        "type": "company_id",
                        "card_number_display": cid_row["card_number_display"],
                        "issued_date": cid_row["issued_date"],
                        "status": cid_row["status"],
                        "html_url": ("/files/" + cid_html) if cid_html else None,
                    }
            out.append({
                **dict(e),
                "doc_count": doc_count,
                "cert_count": cert_count,
                "certs_expiring_30d": expiring_30,
                "certs_expired": expired,
                "eligibility": eligibility,
                "current_credential": current_credential,
            })
        conn.close()
        return response_wrapper(out)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


# ============= UNIFIED CREDENTIAL ENDPOINTS =============

@app.route('/api/employees/<emp_id>/credential', methods=['GET'])
def get_employee_credential(emp_id):
    """Return the worker's current credential state + eligibility +
    photo-readiness. Used by the workforce list (per-row context) and
    any per-worker detail view."""
    conn = None
    try:
        from cof_issuer import has_valid_prerequisite
        conn = db()
        emp = conn.execute(
            "SELECT employee_id, face_image_path FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
        if not emp:
            return jsonify({"error": "Employee not found"}), 404
        eligible, _ = has_valid_prerequisite(emp_id)
        eligibility = 'cof' if eligible else 'company_id'
        face_present = bool(emp["face_image_path"])

        current_type = card_number_display_v = issued_date_v = expires_v = status_v = html_export_path = None
        cof_row = conn.execute(
            """SELECT card_id, card_number_display, issued_date, expires_date, status, html_export_path
               FROM cof_cards WHERE employee_id = ? AND status = 'issued'
               ORDER BY issued_date DESC LIMIT 1""",
            (emp_id,)
        ).fetchone()
        if cof_row:
            current_type = 'cof'
            card_number_display_v = cof_row["card_number_display"] or cof_row["card_id"]
            issued_date_v = cof_row["issued_date"]
            expires_v = cof_row["expires_date"]
            status_v = cof_row["status"]
            html_export_path = cof_row["html_export_path"]
        else:
            cid_row = conn.execute(
                """SELECT card_id, card_number_display, issued_date, status, html_export_path
                   FROM company_id_cards WHERE employee_id = ? AND status = 'active'
                   ORDER BY issued_date DESC, created_at DESC LIMIT 1""",
                (emp_id,)
            ).fetchone()
            if cid_row:
                current_type = 'company_id'
                card_number_display_v = cid_row["card_number_display"]
                issued_date_v = cid_row["issued_date"]
                status_v = cid_row["status"]
                html_export_path = cid_row["html_export_path"]

        html_url = None
        if html_export_path:
            full = SCRIPT_DIR / html_export_path.lstrip("/")
            if full.exists():
                html_url = "/files/" + html_export_path

        payload = {
            "type": current_type,
            "card_number_display": card_number_display_v,
            "issued_date": issued_date_v,
            "status": status_v,
            "html_url": html_url,
            "eligibility": eligibility,
            "face_image_path_present": face_present,
        }
        if current_type == 'cof':
            payload["expires_date"] = expires_v
        return response_wrapper(payload)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


@app.route('/api/employees/<emp_id>/credential/issue', methods=['POST'])
def issue_employee_credential(emp_id):
    """Unified credential issuance — dispatches CoF vs Company ID based on
    eligibility. Hard-gates on face_image_path. 409 if there's already an
    active credential of the chosen type unless override_active=true.
    Renders the HTML template inline (Jinja2), saves to disk, updates
    html_export_path on the new row, returns the credential info with
    html_url. Operator opens the URL and uses browser print-to-PDF when
    a paper card is needed (per CLAUDE.md HTML-first rule)."""
    import jinja2
    conn = None
    try:
        data = request.get_json() or {}
        issued_by = data.get('issued_by')
        if not issued_by:
            return jsonify({"error": "issued_by required"}), 400
        override_active = bool(data.get('override_active', False))
        rigger_id = data.get('rigger_id')

        conn = db()
        emp = conn.execute(
            "SELECT employee_id, name, trade, pin, face_image_path FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
        if not emp:
            return jsonify({"error": "Employee not found"}), 404
        if not emp["face_image_path"]:
            return jsonify({"error": "Worker has no face photo on file. Take an ID photo before issuing a credential."}), 400

        from cof_issuer import has_valid_prerequisite, issue_cof, get_default_rigger_for_project
        from company_id_issuer import issue_company_id

        eligible, _ = has_valid_prerequisite(emp_id)
        cred_type = 'cof' if eligible else 'company_id'

        # Cross-type mutual exclusivity: a worker holds exactly one
        # credential at a time. Check for an active credential of EITHER
        # type. If any active credential exists (same or other type) and
        # override_active is false, return 409 with the current credential.
        existing_cof = conn.execute(
            "SELECT card_id, card_number_display, issued_date, expires_date, status FROM cof_cards "
            "WHERE employee_id = ? AND status = 'issued' LIMIT 1",
            (emp_id,)
        ).fetchone()
        existing_cid = conn.execute(
            "SELECT card_id, card_number_display, issued_date, status FROM company_id_cards "
            "WHERE employee_id = ? AND status = 'active' LIMIT 1",
            (emp_id,)
        ).fetchone()
        existing_any = existing_cof or existing_cid

        if existing_any and not override_active:
            if existing_cof:
                current_cred = {
                    "type": "cof",
                    "card_number_display": existing_cof["card_number_display"] or existing_cof["card_id"],
                    "issued_date": existing_cof["issued_date"],
                    "expires_date": existing_cof["expires_date"],
                    "status": existing_cof["status"],
                }
            else:
                current_cred = {
                    "type": "company_id",
                    "card_number_display": existing_cid["card_number_display"],
                    "issued_date": existing_cid["issued_date"],
                    "status": existing_cid["status"],
                }
            return jsonify({
                "error": f"Worker already has an active {current_cred['type']}",
                "current_credential": current_cred,
                "hint": "Pass override_active=true to supersede"
            }), 409

        # override_active=true → supersede CROSS-type rows before issuance.
        # Same-type supersede is handled inside the issuer modules
        # (cof_issuer.issue_cof / company_id_issuer.issue_company_id both
        # mark prior 'issued'/'active' rows as 'replaced' internally).
        if override_active:
            if cred_type == 'cof' and existing_cid:
                conn.execute(
                    "UPDATE company_id_cards SET status='replaced', updated_at=CURRENT_TIMESTAMP "
                    "WHERE employee_id=? AND status='active'",
                    (emp_id,)
                )
            elif cred_type == 'company_id' and existing_cof:
                conn.execute(
                    "UPDATE cof_cards SET status='replaced', updated_at=CURRENT_TIMESTAMP "
                    "WHERE employee_id=? AND status='issued'",
                    (emp_id,)
                )
            conn.commit()
        # Close the first conn before calling into the issuer modules —
        # they open their own conns and SQLite WAL prefers one writer at
        # a time. Reset conn=None so the outer finally doesn't double-close.
        conn.close()
        conn = None

        # Issue the card row
        try:
            if cred_type == 'cof':
                rigger_id_param = rigger_id
                if not rigger_id_param:
                    rigger = get_default_rigger_for_project('FR-BX-001')
                    rigger_id_param = rigger['id'] if rigger else None
                card = issue_cof(emp_id, rigger_id=rigger_id_param, project_code='FR-BX-001')
            else:
                card = issue_company_id(emp_id, issued_by)
        except Exception as ex:
            logging.error(f"POST .../credential/issue ({emp_id}) issuer-step: {ex}")
            return jsonify({"error": f"Issuance failed: {ex}"}), 500

        # Render HTML inline via Jinja2. WeasyPrint subprocess removed —
        # GTK runtime isn't installed on this workstation. Per CLAUDE.md
        # HTML-first rule the operator opens the html_url in a browser
        # and uses Ctrl+P / print-to-PDF when a paper card is needed.
        # pdf_export_path stays NULL on the row for future re-introduction
        # of an automated PDF renderer (WeasyPrint w/ GTK, or Playwright).
        if cred_type == 'cof':
            template_name = 'cof_card_print.html'
            subdir = 'cof'
            cnd = card.get('card_number_display') or card['card_id']
            expires_str = card.get('expires_date') or ''
        else:
            template_name = 'company_id_card_print.html'
            subdir = 'company_id'
            cnd = card['card_number_display']
            expires_str = ''
        # PHOTO_URL_OR_BLANK + SIGNATURE_URL: "/files/<rel>" if the file
        # exists, else empty string (the template's {% if %} fallback
        # handles the no-photo / no-signature case).
        photo_url = ''
        photo_snapshot = card.get('photo_snapshot_path')
        if photo_snapshot:
            photo_full = SCRIPT_DIR / photo_snapshot.lstrip('/')
            if photo_full.exists():
                photo_url = '/files/' + photo_snapshot
        signature_url = ''
        sig_path = card.get('signature_path')
        if sig_path:
            sig_full = SCRIPT_DIR / sig_path.lstrip('/')
            if sig_full.exists():
                signature_url = '/files/' + sig_path
        ctx = {
            'NAME': emp['name'] or '',
            'EMPLOYEE_ID': emp_id,
            'CARD_NUMBER_DISPLAY': cnd or '',
            'ISSUED_DATE': card.get('issued_date') or '',
            'ISSUED_BY': card.get('issued_by') or issued_by,
            'EXPIRES_DATE': expires_str,
            'TRADE': emp['trade'] or '',
            'PIN': emp['pin'] or '----',
            'PHOTO_URL_OR_BLANK': photo_url,
            'RIGGER_NAME': card.get('rigger_name_snapshot') or '',
            'RIGGER_LICENSE': card.get('rigger_license_snapshot') or '',
            'SIGNATURE_URL': signature_url,
        }
        env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(SCRIPT_DIR)),
            autoescape=True,
        )
        try:
            tpl = env.get_template(template_name)
            html_out = tpl.render(**ctx)
        except Exception as ex:
            logging.error(f"POST .../credential/issue ({emp_id}) jinja render failed: {ex}")
            return jsonify({"error": f"Template render failed: {ex}"}), 500
        html_dir = SCRIPT_DIR / "data_room" / "credentials" / subdir
        html_dir.mkdir(parents=True, exist_ok=True)
        html_file = html_dir / f"{emp_id}.html"
        html_file.write_text(html_out, encoding='utf-8')
        html_rel = html_file.relative_to(SCRIPT_DIR).as_posix()
        conn = db()
        if cred_type == 'cof':
            conn.execute(
                "UPDATE cof_cards SET html_export_path = ?, updated_at = CURRENT_TIMESTAMP WHERE card_id = ?",
                (html_rel, card['card_id'])
            )
        else:
            conn.execute(
                "UPDATE company_id_cards SET html_export_path = ?, updated_at = CURRENT_TIMESTAMP WHERE card_id = ?",
                (html_rel, card['card_id'])
            )
        conn.commit()
        conn.close()
        conn = None
        html_url = '/files/' + html_rel

        response_body = {
            "type": cred_type,
            "card_number_display": cnd,
            "card_id": card['card_id'],
            "issued_date": card['issued_date'],
            "status": card['status'],
            "html_url": html_url,
        }
        if cred_type == 'cof':
            response_body["expires_date"] = card.get('expires_date')
        return response_wrapper(response_body), 201
    except Exception as e:
        logging.error(f"POST .../credential/issue ({emp_id}): {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def _current_credential_row(conn, emp_id):
    """Locate the worker's current credential — same dispatch as GET
    /credential. Returns (table_name, dict-row) or (None, None). CoF
    (status='issued') takes precedence over Company ID (status='active')."""
    cof = conn.execute(
        "SELECT * FROM cof_cards WHERE employee_id = ? AND status = 'issued' "
        "ORDER BY issued_date DESC LIMIT 1",
        (emp_id,)
    ).fetchone()
    if cof:
        return ('cof_cards', dict(cof))
    cid = conn.execute(
        "SELECT * FROM company_id_cards WHERE employee_id = ? AND status = 'active' "
        "ORDER BY issued_date DESC, created_at DESC LIMIT 1",
        (emp_id,)
    ).fetchone()
    if cid:
        return ('company_id_cards', dict(cid))
    return (None, None)


@app.route('/api/employees/<emp_id>/credential', methods=['PATCH'])
def patch_employee_credential(emp_id):
    """Edit the worker's CURRENT credential (same dispatch as GET).

    Editable: notes, status (for both card types) + expires_date (CoF only).
    Immutable post-issue: card_id, card_number_display, issued_date,
    photo_snapshot_path, html_export_path, basis_certs_json, rigger_* —
    those are properties of the physical card and must not drift after
    print/handover.

    404 if there's no current credential to edit; 400 if expires_date is
    supplied for a Company ID (no such field on that card type)."""
    conn = None
    try:
        data = request.get_json(silent=True) or {}
        conn = db()
        table, card = _current_credential_row(conn, emp_id)
        if not card:
            return jsonify({"error": "no current credential to edit"}), 404
        EDITABLE = {'notes', 'status'}
        if table == 'cof_cards':
            EDITABLE = EDITABLE | {'expires_date'}
        elif 'expires_date' in data:
            return jsonify({"error": "company_id cards have no expires_date"}), 400
        updates = {}
        for k in EDITABLE:
            if k in data:
                updates[k] = data[k]
        if not updates:
            return jsonify({"error": "no editable fields in payload"}), 400
        if 'expires_date' in updates and updates['expires_date']:
            try:
                datetime.strptime(updates['expires_date'], '%Y-%m-%d')
            except ValueError:
                return jsonify({"error": "expires_date must be YYYY-MM-DD"}), 400
        set_clauses = [f"{k} = ?" for k in updates] + ["updated_at = CURRENT_TIMESTAMP"]
        params = list(updates.values()) + [card['card_id']]
        conn.execute(
            f"UPDATE {table} SET {', '.join(set_clauses)} WHERE card_id = ?",
            params
        )
        conn.commit()
        row = conn.execute(
            f"SELECT * FROM {table} WHERE card_id = ?", (card['card_id'],)
        ).fetchone()
        payload = {
            "type": 'cof' if table == 'cof_cards' else 'company_id',
            "card_id": row['card_id'],
            "card_number_display": row['card_number_display'],
            "status": row['status'],
            "notes": row['notes'],
        }
        if table == 'cof_cards':
            payload["expires_date"] = row['expires_date']
        return response_wrapper(payload), 200
    except Exception as e:
        logging.error(f"PATCH /api/employees/{emp_id}/credential: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


@app.route('/api/employees/<emp_id>/credential', methods=['DELETE'])
def delete_employee_credential(emp_id):
    """Soft-revoke: status='revoked' on the worker's current credential.
    The DB row is preserved (audit trail) and so are the rendered HTML/PDF
    files on disk. After revocation, GET /credential reports no current
    credential — the lookup only finds CoFs with status='issued' or
    Company IDs with status='active' — so the worker becomes credential-
    less and is eligible for re-issuance. 404 if no current credential."""
    conn = None
    try:
        conn = db()
        table, card = _current_credential_row(conn, emp_id)
        if not card:
            return jsonify({"error": "no current credential to revoke"}), 404
        conn.execute(
            f"UPDATE {table} SET status = 'revoked', updated_at = CURRENT_TIMESTAMP "
            f"WHERE card_id = ?",
            (card['card_id'],)
        )
        conn.commit()
        return jsonify({
            "revoked": True,
            "type": 'cof' if table == 'cof_cards' else 'company_id',
            "card_id": card['card_id'],
        }), 200
    except Exception as e:
        logging.error(f"DELETE /api/employees/{emp_id}/credential: {e}")
        return jsonify({"error": str(e)}), 500
    finally:
        if conn is not None:
            try: conn.close()
            except Exception: pass


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

_WMO_LABELS = {
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


def fetch_open_meteo_weather(lat, lng, date_str=None):
    """Fetch weather for a date (YYYY-MM-DD). For today/future, uses the
    forecast endpoint (with current + daily). For dates >5 days back, uses
    the archive endpoint. For 1-5 days back, uses forecast with date filter.
    Returns the same dict shape regardless of source so callers don't care
    which Open-Meteo endpoint was hit. Raises ValueError on bad date_str."""
    import urllib.request, urllib.parse

    target_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else date.today()
    today = date.today()
    days_back = (today - target_date).days
    is_archive = days_back > 5
    is_today = target_date == today

    endpoint = "https://archive-api.open-meteo.com/v1/archive" if is_archive \
        else "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": lat, "longitude": lng,
        "start_date": target_date.isoformat(),
        "end_date": target_date.isoformat(),
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m,weather_code",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "timezone": "America/New_York",
    }
    if is_today:
        params["current"] = "temperature_2m,wind_speed_10m,wind_direction_10m,weather_code"

    url = endpoint + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))

    cur = data.get("current", {}) or {}
    daily = data.get("daily", {}) or {}
    hourly = data.get("hourly", {}) or {}

    if is_today and cur:
        temp_now = cur.get("temperature_2m")
        wind_mph = cur.get("wind_speed_10m")
        wind_dir_deg = cur.get("wind_direction_10m")
        condition_code = cur.get("weather_code")
    else:
        # Past/future day: pick noon (or midpoint) as the representative reading.
        temps = hourly.get("temperature_2m", []) or []
        winds = hourly.get("wind_speed_10m", []) or []
        wdirs = hourly.get("wind_direction_10m", []) or []
        codes = hourly.get("weather_code", []) or []
        idx = 12 if len(temps) > 12 else (len(temps) // 2 if temps else 0)
        temp_now = temps[idx] if temps else None
        wind_mph = winds[idx] if winds else None
        wind_dir_deg = wdirs[idx] if wdirs else None
        condition_code = codes[idx] if codes else None

    out = {
        "temp_now": temp_now,
        "wind_mph": wind_mph,
        "wind_dir_deg": wind_dir_deg,
        "condition_code": condition_code,
        "temp_max": (daily.get("temperature_2m_max") or [None])[0],
        "temp_min": (daily.get("temperature_2m_min") or [None])[0],
        "fetched_at": datetime.utcnow().isoformat() + "Z",
        "date": target_date.isoformat(),
        "source": "open-meteo-archive" if is_archive else "open-meteo-forecast",
    }
    deg = out.get("wind_dir_deg")
    if deg is not None:
        compass = ["N","NE","E","SE","S","SW","W","NW","N"]
        out["wind_dir"] = compass[int((deg + 22.5) // 45)]
    out["condition_label"] = _WMO_LABELS.get(out.get("condition_code"), "—")
    return out


@app.route('/api/weather', methods=['GET'])
def api_weather():
    """Live weather for a project's coords + a given date. Default lat/lng
    is the 890 E 135th Street site (Bronx). ?date=YYYY-MM-DD selects the day —
    today by default; past dates >5 days back pull from Open-Meteo's archive
    endpoint. Same response shape regardless of which endpoint was hit."""
    try:
        lat = float(request.args.get("lat", 40.8083))
        lng = float(request.args.get("lng", -73.9162))
        date_str = request.args.get("date")
        if date_str:
            try:
                datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return jsonify({"error": "date must be YYYY-MM-DD"}), 400
        out = fetch_open_meteo_weather(lat, lng, date_str)
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
    """Trigger a live pull from NYC OpenData. Body: {project_code: 'FR-BX-001'} or {} for all."""
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
    """Serve any other file in the outputs folder by name (e.g. /DCR-FR-BX-001-2026-05-05-internal.html, /drop_plans/DP-001.html)"""
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
    # Loopback only per CLAUDE.md loopback policy: the workstation lives on a
    # shared coworking-space network — the dashboard must not be reachable from LAN.
    app.run(host='127.0.0.1', port=5050, debug=False, use_reloader=False, threaded=True)
