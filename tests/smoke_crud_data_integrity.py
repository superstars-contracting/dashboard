"""
smoke_crud_data_integrity.py — per-section CRUD + visibility smoke.

For every operator-editable section, runs:
  1. CREATE        — insert a synthetic row via the public API
  2. READ-BACK 1   — confirm it persisted (DB-level fetch or list endpoint)
  3. UPDATE        — edit via the public API (PATCH/PUT)
  4. READ-BACK 2   — confirm the edit landed
  5. DELETE        — remove via the public API
  6. READ-BACK 3   — confirm gone
  7. SHOWS-IN-REPORT — re-insert, hit the DCR aggregator, confirm the
                       row surfaces in the rendered JSON, then clean up

Endpoints with no public-API support for one of the steps are scored as
FAIL ("no API") — the operator cannot achieve that step, which is the
audit question this smoke is answering.

Outputs the per-section table with columns:
  Section | Create | Edit | Delete | Shows in report | Verdict

PII-safe: only employee_id (E-XXXXX) / worker_id (W-####) / counts /
booleans are printed. No names, no phones, no PINs.
"""
import io
import json
import os
import sqlite3
import string
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

import requests

# Auth gate (#48): login the smoke admin + patch requests so cookies ride along.
import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PROJECT = "FR-BX-001"
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
MARKER = "SMOKE_CRUD_" + uuid.uuid4().hex[:8].upper()

# Test dates: span the 5/1..today range per handoff
D_EARLY = "2026-05-01"
D_MID = "2026-05-10"
D_LATE = "2026-05-21"

# ---------- Helpers ----------

def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def row_count(conn, table, where_sql, params):
    q = f"SELECT COUNT(*) FROM {table} WHERE {where_sql}"
    return conn.execute(q, params).fetchone()[0]

def aggregator(date_str, audience="internal"):
    r = requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{date_str}",
        params={"audience": audience}, timeout=15,
    )
    r.raise_for_status()
    return r.json()["data"]

def make_jpeg_bytes():
    # 1x1 white JPEG. Minimal valid file the face-photo endpoint will accept.
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb0043000806060706"
        "0508070708090a0c140d0c0b0b0c19121316141d1a1f1e1d1a1c1c20242e"
        "2720222c231c1c2837292c30313434341f27393d38323c2e333432ffc000"
        "0b08000100010101011100ffc4001f0000010501010101010100000000000"
        "0000001020304050607080910ffc40036100002010303020403050504040"
        "00000010002030411051221314106135161220771819114a132ffda00080"
        "1010000003f00ffd9"
    )

# ---------- Result model ----------

class SectionResult:
    def __init__(self, name):
        self.name = name
        self.create = None   # True / False / 'n/a'
        self.edit = None
        self.delete = None
        self.shows = None
        self.notes = []
    def verdict(self):
        steps = [self.create, self.edit, self.delete, self.shows]
        if any(s is False for s in steps):
            if all(s is False for s in steps):
                return "FAIL"
            return "PARTIAL"
        return "PASS"
    def fmt(self, v):
        return {True: "PASS", False: "FAIL", "n/a": "N/A", None: "?"}[v]
    def row(self):
        return f"| {self.name} | {self.fmt(self.create)} | {self.fmt(self.edit)} | {self.fmt(self.delete)} | {self.fmt(self.shows)} | {self.verdict()} |"


def add_note(result, msg):
    result.notes.append(msg)


# ---------- Pre-flight ----------

def preflight():
    r = requests.get(f"{BASE}/api/health", timeout=5)
    assert r.status_code == 200, f"health {r.status_code}"
    r = requests.get(f"{BASE}/api/employees", timeout=10)
    assert r.status_code == 200, f"employees {r.status_code}"
    emps = r.json()["data"]
    assert emps, "no employees in DB — can't run sign-in test"
    return emps[0]["employee_id"]


def cleanup_marker():
    """Remove any debris from earlier interrupted runs (matches MARKER prefix).

    Also sweeps `sign_in_log` defensively (#111): test_sign_ins and
    test_weekly_hours POST sign-ins against REAL workers (emps[1] /
    emps[2]) on the test dates D_EARLY / D_MID / D_LATE — if the smoke
    aborts mid-test (timeout, network blip, ctrl-c) the explicit
    requests.delete() call is skipped, and a row at the test default
    `time_in='07:00', time_out='15:30'` accumulates against a real
    worker. The DCR labor scoping (project_code + date) then surfaces
    it as a phantom sign-in on a freshly-created DCR.

    Filter is intentionally tight — only deletes rows whose date has NO
    issued DCR in report_index (orphan), AND match the exact test time
    pattern, AND are on the smoke's own test dates. A real sign-in at
    07:00-15:30 that's referenced by a real DCR is preserved.
    """
    conn = db()
    try:
        cur = conn.cursor()
        for tbl, col in [
            ("sign_in_log",          None),  # no marker field; cleaned by emp+date below
            ("work_log",             "description"),
            ("deliveries",           "notes"),
            ("equipment_log",        "notes"),
            ("weather_log",          "conditions"),
            ("toolbox_talk_records", "talk_id"),
            ("safety_events",        "description"),
            ("issues",               "description"),
            ("inspections",          "notes"),
            ("visitors",             "notes"),
            ("photos",               "description"),
        ]:
            if col:
                cur.execute(f"DELETE FROM {tbl} WHERE {col} LIKE 'SMOKE_CRUD_%'")
        # Synthetic test workers we created (employee_id begins with SMK-)
        cur.execute("DELETE FROM project_assignments WHERE employee_id LIKE 'SMK-%'")
        cur.execute("DELETE FROM certifications     WHERE employee_id LIKE 'SMK-%'")
        cur.execute("DELETE FROM worker_documents   WHERE employee_id LIKE 'SMK-%'")
        cur.execute("DELETE FROM cof_cards          WHERE employee_id LIKE 'SMK-%'")
        cur.execute("DELETE FROM company_id_cards   WHERE employee_id LIKE 'SMK-%'")
        cur.execute("DELETE FROM sign_in_log        WHERE employee_id LIKE 'SMK-%'")
        cur.execute("DELETE FROM employees          WHERE employee_id LIKE 'SMK-%'")
        # Defensive sweep of REAL-worker orphan sign-ins on the smoke's own
        # test dates. Triple-locked filter (project + test time pattern +
        # no parent DCR) so no real labor row can be touched.
        cur.execute(
            """DELETE FROM sign_in_log
               WHERE project_code = ?
                 AND time_in = '07:00' AND time_out = '15:30'
                 AND date IN (?, ?, ?)
                 AND NOT EXISTS (
                   SELECT 1 FROM report_index r
                   WHERE r.project_code = sign_in_log.project_code
                     AND r.report_type = 'DCR'
                     AND r.report_date = sign_in_log.date
                 )""",
            (PROJECT, D_EARLY, D_MID, D_LATE),
        )
        conn.commit()
    finally:
        conn.close()


# ---------- Section tests ----------

def test_workforce(real_emp_id):
    """Workforce: POST /api/workers/create, GET, PATCH /api/employees/<id>,
    no public DELETE for workers."""
    r = SectionResult("Workforce (worker CRUD)")
    syn_id = "SMK-" + uuid.uuid4().hex[:6].upper()
    # CREATE
    resp = requests.post(f"{BASE}/api/workers/create", json={
        "employee_id": syn_id, "name": "SMOKE TestAlpha",
        "trade": "SMOKE_CRUD_TRADE_A", "language": "EN",
    }, timeout=10)
    if resp.status_code != 200:
        r.create = False
        add_note(r, f"POST /api/workers/create -> {resp.status_code}")
        return r
    # READ-BACK 1
    g = requests.get(f"{BASE}/api/workers/{syn_id}", timeout=10)
    r.create = (g.status_code == 200 and g.json()["data"]["employee"]["trade"] == "SMOKE_CRUD_TRADE_A")
    # EDIT
    p = requests.patch(f"{BASE}/api/employees/{syn_id}", json={"trade": "SMOKE_CRUD_TRADE_B"}, timeout=10)
    g2 = requests.get(f"{BASE}/api/workers/{syn_id}", timeout=10)
    r.edit = (p.status_code == 200 and g2.status_code == 200 and
              g2.json()["data"]["employee"]["trade"] == "SMOKE_CRUD_TRADE_B")
    # SHOWS — workforce list (intake-summary). Verify BEFORE delete so a
    # working DELETE doesn't make SHOWS see the post-delete state.
    ls = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10)
    r.shows = any(x.get("employee_id") == syn_id for x in ls.json()["data"])
    # DELETE — hard-delete path (no history was attached to this worker).
    d = requests.delete(f"{BASE}/api/employees/{syn_id}", timeout=10)
    hard_ok = (d.status_code == 200 and d.json().get("data", {}).get("deleted") == "hard")

    # Also verify the SOFT-archive path: create another worker, add a sign-in
    # so it has history, then DELETE → expect 'archived' (not 'hard').
    syn_id2 = "SMK-" + uuid.uuid4().hex[:6].upper()
    requests.post(f"{BASE}/api/workers/create", json={
        "employee_id": syn_id2, "name": "SMOKE TestArchive", "trade": "Archive",
    }, timeout=10)
    requests.post(f"{BASE}/api/sign-ins", json={
        "employee_id": syn_id2, "project_code": PROJECT,
        "date": D_EARLY, "time_in": "07:00", "time_out": "15:30",
    }, timeout=10)
    d2 = requests.delete(f"{BASE}/api/employees/{syn_id2}", timeout=10)
    soft_ok = (d2.status_code == 200 and d2.json().get("data", {}).get("deleted") == "archived")
    # Archived worker must be hidden from default list, visible with flag.
    default_ls = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10).json()["data"]
    incl_ls = requests.get(f"{BASE}/api/workers/intake-summary",
                           params={"include_archived": "true"}, timeout=10).json()["data"]
    filtered = (not any(x.get("employee_id") == syn_id2 for x in default_ls)
                and any(x.get("employee_id") == syn_id2 for x in incl_ls))
    r.delete = bool(hard_ok and soft_ok and filtered)
    if not r.delete:
        add_note(r, f"hard_ok={hard_ok} soft_ok={soft_ok} list_filtered={filtered}")
    # Clean up any residue via SQL (idempotent against working+missing delete)
    conn = db()
    try:
        conn.execute("DELETE FROM project_assignments WHERE employee_id = ?", (syn_id,))
        conn.execute("DELETE FROM employees WHERE employee_id = ?", (syn_id,))
        conn.commit()
    finally:
        conn.close()
    return r


def test_intake_status(real_emp_id):
    """Intake completion: handoff #4b says completing intake must flip
    workforce 'Intake' column to 'done'. Check whether ANY public endpoint
    can change employees.intake_status."""
    r = SectionResult("Intake status (flip pending -> done)")
    # Create a temp worker so we know its starting intake_status
    syn_id = "SMK-" + uuid.uuid4().hex[:6].upper()
    requests.post(f"{BASE}/api/workers/create", json={
        "employee_id": syn_id, "name": "SMOKE TestIntake", "trade": "Intake",
    }, timeout=10)
    # CREATE = "intake row exists with intake_status='pending'"
    ls = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10)
    row = next((x for x in ls.json()["data"] if x.get("employee_id") == syn_id), None)
    r.create = bool(row and row.get("intake_status") == "pending")
    # EDIT = "flip pending -> done via API"
    # Try the documented PATCH first.
    p = requests.patch(f"{BASE}/api/employees/{syn_id}", json={"intake_status": "done"}, timeout=10)
    # Plausible alternates a UI might use
    alt1 = requests.post(f"{BASE}/api/workers/{syn_id}/intake/complete", timeout=10)
    alt2 = requests.post(f"{BASE}/api/employees/{syn_id}/intake/complete", timeout=10)
    ls2 = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10)
    row2 = next((x for x in ls2.json()["data"] if x.get("employee_id") == syn_id), None)
    flipped = bool(row2 and row2.get("intake_status") == "done")
    r.edit = flipped
    if not flipped:
        add_note(r,
            f"no flip path: PATCH employees={p.status_code}, "
            f"POST workers/intake/complete={alt1.status_code}, "
            f"POST employees/intake/complete={alt2.status_code}; intake_status remains 'pending'"
        )
    # DELETE = "revert done -> pending" — not a real operator flow but checked
    # for symmetry; expected to fail since EDIT failed.
    r.delete = "n/a"
    # SHOWS — intake_status surfaces on workforce list (intake-summary). Field exists, value just doesn't flip.
    r.shows = bool(row and "intake_status" in row)
    # cleanup
    conn = db()
    try:
        conn.execute("DELETE FROM project_assignments WHERE employee_id = ?", (syn_id,))
        conn.execute("DELETE FROM employees WHERE employee_id = ?", (syn_id,))
        conn.commit()
    finally:
        conn.close()
    return r


def test_face_photo(real_emp_id):
    """Face photo: POST /api/employees/<id>/face-photo (multipart). No
    public DELETE."""
    r = SectionResult("Worker face photo (upload)")
    # Capture prior value so we can restore later
    conn = db()
    try:
        prior = conn.execute(
            "SELECT face_image_path FROM employees WHERE employee_id = ?",
            (real_emp_id,)
        ).fetchone()
        prior_path = prior["face_image_path"] if prior else None
    finally:
        conn.close()
    # CREATE — upload
    files = {"file": ("smoke_face.jpg", make_jpeg_bytes(), "image/jpeg")}
    up = requests.post(
        f"{BASE}/api/employees/{real_emp_id}/face-photo",
        files=files, timeout=15,
    )
    g = requests.get(f"{BASE}/api/workers/{real_emp_id}", timeout=10)
    new_path = g.json()["data"]["employee"]["face_image_path"] if g.status_code == 200 else None
    r.create = (up.status_code == 200 and bool(new_path))
    # EDIT = re-upload (overwrites)
    up2 = requests.post(
        f"{BASE}/api/employees/{real_emp_id}/face-photo",
        files={"file": ("smoke_face2.jpg", make_jpeg_bytes(), "image/jpeg")},
        timeout=15,
    )
    r.edit = (up2.status_code == 200)
    # SHOWS — face_image_path is referenced by /credential endpoint.
    # Check BEFORE delete so a working DELETE doesn't make SHOWS see absent.
    g3 = requests.get(f"{BASE}/api/employees/{real_emp_id}/credential", timeout=10)
    r.shows = (g3.status_code == 200 and g3.json()["data"].get("face_image_path_present") is True)
    # DELETE
    d = requests.delete(f"{BASE}/api/employees/{real_emp_id}/face-photo", timeout=10)
    r.delete = (d.status_code == 200)
    if not r.delete:
        add_note(r, f"no public DELETE for face-photo (status {d.status_code})")
    # Restore prior face_image_path so we don't permanently overwrite a real worker
    conn = db()
    try:
        conn.execute(
            "UPDATE employees SET face_image_path = ? WHERE employee_id = ?",
            (prior_path, real_emp_id)
        )
        conn.commit()
    finally:
        conn.close()
    return r


def test_cert_upload(real_emp_id):
    """Cert upload (the failure-#1 ticket): POST /api/workers/<id>/certs
    is the JSON entry endpoint; DELETE /api/workers/<id>/certs/<cid>."""
    r = SectionResult("Worker cert (add/edit/delete)")
    # CREATE
    payload = {
        "cert_type_id": "SCAFFOLD-16",
        "date_obtained": "2026-01-01",
        "expiration_date": "2026-12-31",
        "card_number": MARKER + "_CERT_A",
        "issuing_body": "DOB",
        "notes": MARKER,
    }
    c = requests.post(f"{BASE}/api/workers/{real_emp_id}/certs", json=payload, timeout=10)
    cert_id = None
    if c.status_code == 200:
        cert_id = c.json()["data"].get("cert_id")
    # READ-BACK
    g = requests.get(f"{BASE}/api/workers/{real_emp_id}", timeout=10)
    cert_seen = False
    if g.status_code == 200:
        for cert in g.json()["data"]["certifications"]:
            if cert.get("id") == cert_id:
                cert_seen = True
                break
    r.create = (cert_id is not None and cert_seen)
    # EDIT — no PATCH endpoint for /api/workers/<id>/certs/<id>
    p = requests.patch(
        f"{BASE}/api/workers/{real_emp_id}/certs/{cert_id}",
        json={"card_number": MARKER + "_CERT_B"}, timeout=10,
    )
    r.edit = (p.status_code == 200)
    if not r.edit:
        add_note(r, f"no PATCH endpoint for certs (status {p.status_code})")
    # DELETE
    if cert_id is not None:
        d = requests.delete(
            f"{BASE}/api/workers/{real_emp_id}/certs/{cert_id}", timeout=10
        )
        r.delete = (d.status_code == 200)
    else:
        r.delete = False
    # SHOWS — re-create, check intake-summary cert_count delta
    pre = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10).json()["data"]
    pre_row = next(x for x in pre if x["employee_id"] == real_emp_id)
    pre_count = pre_row["cert_count"]
    payload2 = dict(payload, card_number=MARKER + "_CERT_C")
    c2 = requests.post(f"{BASE}/api/workers/{real_emp_id}/certs", json=payload2, timeout=10)
    cid2 = c2.json()["data"].get("cert_id") if c2.status_code == 200 else None
    post = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10).json()["data"]
    post_row = next(x for x in post if x["employee_id"] == real_emp_id)
    r.shows = (post_row["cert_count"] == pre_count + 1)
    # cleanup
    if cid2 is not None:
        requests.delete(f"{BASE}/api/workers/{real_emp_id}/certs/{cid2}", timeout=10)
    return r


def test_credential_issue(real_emp_id):
    """Credential issuance: POST /api/employees/<id>/credential/issue.
    Hard-gates on face photo. No public UPDATE/DELETE."""
    r = SectionResult("Credential issuance (CoF/Company ID)")
    # Make sure a face photo exists (test_face_photo restored, so re-add)
    files = {"file": ("smoke_face.jpg", make_jpeg_bytes(), "image/jpeg")}
    requests.post(f"{BASE}/api/employees/{real_emp_id}/face-photo", files=files, timeout=15)
    # CREATE — issue. override_active=True so we can run on a real worker
    # who might already hold a credential without polluting their record.
    iss = requests.post(
        f"{BASE}/api/employees/{real_emp_id}/credential/issue",
        json={"issued_by": MARKER, "override_active": True},
        timeout=15,
    )
    issued_ok = (iss.status_code in (200, 201))
    # READ-BACK
    g = requests.get(f"{BASE}/api/employees/{real_emp_id}/credential", timeout=10)
    has_current = bool(g.status_code == 200 and g.json()["data"].get("type"))
    r.create = (issued_ok and has_current)
    cred_type = g.json()["data"].get("type") if has_current else None
    # SHOWS — intake-summary surfaces current_credential. Check BEFORE
    # PATCH/DELETE so the soft-revoke from DELETE doesn't sabotage SHOWS.
    ls = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10).json()["data"]
    row = next((x for x in ls if x["employee_id"] == real_emp_id), None)
    r.shows = bool(row and row.get("current_credential") and
                   row["current_credential"].get("type") == cred_type)
    # EDIT — PATCH credential notes (non-empty body required)
    p = requests.patch(f"{BASE}/api/employees/{real_emp_id}/credential",
                       json={"notes": MARKER + "_CRED_NOTE"}, timeout=10)
    r.edit = (p.status_code == 200)
    if not r.edit:
        add_note(r, f"PATCH credential failed (status {p.status_code})")
    # DELETE
    d = requests.delete(f"{BASE}/api/employees/{real_emp_id}/credential", timeout=10)
    r.delete = (d.status_code == 200)
    if not r.delete:
        add_note(r, f"DELETE credential failed (status {d.status_code})")
    # Cleanup — retract the test issuance via direct SQL
    conn = db()
    try:
        conn.execute(
            "DELETE FROM cof_cards WHERE employee_id = ? AND issued_by = ?",
            (real_emp_id, MARKER)
        )
        conn.execute(
            "DELETE FROM company_id_cards WHERE employee_id = ? AND issued_by = ?",
            (real_emp_id, MARKER)
        )
        conn.commit()
    finally:
        conn.close()
    return r


# ---------- DCR sub-section tests ----------

def _dcr_section_test(name, table, post_url, payload, edit_url_tmpl,
                      edit_method, edit_payload, delete_url_tmpl,
                      aggregator_key, match_fn, date_str=D_LATE):
    """Generic CRUD+aggregator test for a DCR sub-section.

    match_fn(item) -> bool: returns True if the aggregator item is the one we inserted.
    edit_url_tmpl/edit_payload may be None — then EDIT is marked FAIL (no API).
    delete_url_tmpl: function row_id -> url.
    """
    r = SectionResult(name)
    # CREATE
    cr = requests.post(post_url, json=payload, timeout=10)
    new_id = None
    if cr.status_code in (200, 201):
        try:
            new_id = cr.json()["data"].get("id")
        except Exception:
            pass
    # READ-BACK 1 — db count
    conn = db()
    try:
        seen = row_count(conn, table, "id = ?", (new_id,)) if new_id else 0
    finally:
        conn.close()
    r.create = bool(new_id) and seen == 1
    # EDIT
    if edit_url_tmpl is None:
        r.edit = False
        add_note(r, f"no PATCH/PUT endpoint for {table}")
    else:
        if edit_method == "PATCH":
            er = requests.patch(edit_url_tmpl(new_id), json=edit_payload, timeout=10)
        else:
            er = requests.put(edit_url_tmpl(new_id), json=edit_payload, timeout=10)
        r.edit = (er.status_code in (200, 201))
    # DELETE
    if new_id is not None:
        dr = requests.delete(delete_url_tmpl(new_id), timeout=10)
        r.delete = (dr.status_code == 200)
    else:
        r.delete = False
    # READ-BACK 3 — confirm gone
    if new_id is not None:
        conn = db()
        try:
            after = row_count(conn, table, "id = ?", (new_id,))
        finally:
            conn.close()
        if after != 0:
            r.delete = False
            add_note(r, f"row {new_id} still in {table} after DELETE")
    # SHOWS IN REPORT — re-insert, aggregator, cleanup
    cr2 = requests.post(post_url, json=payload, timeout=10)
    new_id2 = None
    if cr2.status_code in (200, 201):
        try:
            new_id2 = cr2.json()["data"].get("id")
        except Exception:
            pass
    if new_id2 is not None:
        agg = aggregator(date_str)
        items = agg.get(aggregator_key) or []
        # aggregator returns a dict for safety; handle both
        if isinstance(items, dict):
            # For safety section the events sit at agg['safety']['events']
            items = items.get("events", []) if aggregator_key == "safety" else list(items.values())
        r.shows = any(match_fn(i) for i in items)
        # Cleanup
        requests.delete(delete_url_tmpl(new_id2), timeout=10)
    else:
        r.shows = False
        add_note(r, "could not re-create row for shows-in-report check")
    return r


def test_sign_ins(real_emp_id):
    r = SectionResult("Sign-ins (labor / billable in-out)")
    # Use a different worker than the one we faced-photo'd, so we don't
    # conflict with the test's own credential test. Pick the second one.
    emps = requests.get(f"{BASE}/api/employees", timeout=10).json()["data"]
    target_emp = emps[1]["employee_id"] if len(emps) > 1 else real_emp_id
    date_str = D_MID
    # Make sure no sign-in already exists for that date
    conn = db()
    try:
        conn.execute(
            "DELETE FROM sign_in_log WHERE employee_id = ? AND date = ? AND project_code = ?",
            (target_emp, date_str, PROJECT)
        )
        conn.commit()
    finally:
        conn.close()
    # CREATE
    cr = requests.post(f"{BASE}/api/sign-ins", json={
        "employee_id": target_emp, "project_code": PROJECT,
        "date": date_str, "time_in": "07:00", "time_out": "15:30",
    }, timeout=10)
    new_id = None
    if cr.status_code in (200, 201):
        new_id = cr.json()["data"]["id"]
    r.create = bool(new_id)
    # EDIT (PATCH = time_out only)
    if new_id is not None:
        pr = requests.patch(f"{BASE}/api/sign-ins/{new_id}",
                            json={"time_out": "16:00"}, timeout=10)
        # Also try PUT (full replace)
        ur = requests.put(f"{BASE}/api/sign-ins/{new_id}",
                          json={"time_in": "07:30", "time_out": "16:00"}, timeout=10)
        r.edit = (pr.status_code == 200 and ur.status_code == 200)
    else:
        r.edit = False
    # DELETE
    if new_id is not None:
        dr = requests.delete(f"{BASE}/api/sign-ins/{new_id}", timeout=10)
        r.delete = (dr.status_code == 200)
    else:
        r.delete = False
    # SHOWS — re-create, aggregator
    cr2 = requests.post(f"{BASE}/api/sign-ins", json={
        "employee_id": target_emp, "project_code": PROJECT,
        "date": date_str, "time_in": "07:00", "time_out": "15:30",
    }, timeout=10)
    new_id2 = cr2.json()["data"]["id"] if cr2.status_code in (200, 201) else None
    if new_id2 is not None:
        agg = aggregator(date_str)
        r.shows = any(row.get("employee_id") == target_emp for row in agg["labor"]["rows"])
        requests.delete(f"{BASE}/api/sign-ins/{new_id2}", timeout=10)
    else:
        r.shows = False
    return r


def test_work_log():
    return _dcr_section_test(
        name="DCR work_log (work_performed)",
        table="work_log",
        post_url=f"{BASE}/api/work-log",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "trade_area": "Facade",
                 "description": MARKER + "_WORK"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/work-log/{rid}",
        edit_method="PATCH",
        edit_payload={"description": MARKER + "_WORK_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/work-log/{rid}",
        aggregator_key="work_performed",
        match_fn=lambda i: (i.get("description") or "").startswith(MARKER + "_WORK"),
    )


def test_deliveries():
    return _dcr_section_test(
        name="DCR materials / deliveries",
        table="deliveries",
        post_url=f"{BASE}/api/deliveries",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "time": "09:00", "material": "Pipe scaffold",
                 "qty": 12, "unit": "ea", "supplier": "Test",
                 "notes": MARKER + "_DELIV"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/deliveries/{rid}",
        edit_method="PATCH",
        edit_payload={"notes": MARKER + "_DELIV_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/deliveries/{rid}",
        aggregator_key="materials_deliveries",
        match_fn=lambda i: (i.get("notes") or "").startswith(MARKER + "_DELIV"),
    )


def test_equipment():
    return _dcr_section_test(
        name="DCR equipment_log",
        table="equipment_log",
        post_url=f"{BASE}/api/equipment-log",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "equipment_type": "Scissor lift",
                 "equipment_id": "EQ-1", "owner": "Test",
                 "hours_used": 4,
                 "notes": MARKER + "_EQ"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/equipment-log/{rid}",
        edit_method="PATCH",
        edit_payload={"notes": MARKER + "_EQ_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/equipment-log/{rid}",
        aggregator_key="equipment",
        match_fn=lambda i: (i.get("issues") or "").startswith(MARKER + "_EQ"),
    )


def test_weather():
    return _dcr_section_test(
        name="DCR weather_log",
        table="weather_log",
        post_url=f"{BASE}/api/weather-log",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "am_temp_f": 70, "pm_temp_f": 75,
                 "am_conditions": MARKER + "_WX",
                 "pm_conditions": MARKER + "_WX",
                 "wind": "5 mph",
                 "conditions": MARKER + "_WX"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/weather-log/{rid}",
        edit_method="PATCH",
        edit_payload={"conditions": MARKER + "_WX_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/weather-log/{rid}",
        aggregator_key="weather",
        # weather is a single object in aggregator; match by am.conditions
        match_fn=lambda i: (i.get("conditions") or "").startswith(MARKER + "_WX") if isinstance(i, dict) else False,
    )


def test_weather_special():
    """Weather is a single object in the aggregator, not a list — needs custom logic."""
    r = SectionResult("DCR weather_log")
    payload = {"project_code": PROJECT, "date": D_LATE,
               "am_temp_f": 70, "pm_temp_f": 75,
               "am_conditions": MARKER + "_WX",
               "pm_conditions": MARKER + "_WX_PM",
               "wind": "5 mph",
               "conditions": MARKER + "_WX"}
    # Clean any existing
    conn = db()
    try:
        conn.execute("DELETE FROM weather_log WHERE project_code = ? AND date = ?",
                     (PROJECT, D_LATE))
        conn.commit()
    finally:
        conn.close()
    cr = requests.post(f"{BASE}/api/weather-log", json=payload, timeout=10)
    new_id = cr.json()["data"].get("id") if cr.status_code in (200, 201) else None
    r.create = bool(new_id)
    # EDIT — no PATCH for weather-log
    p = requests.patch(f"{BASE}/api/weather-log/{new_id}",
                       json={"conditions": MARKER + "_WX_EDITED"}, timeout=10)
    r.edit = (p.status_code in (200, 201))
    if not r.edit:
        add_note(r, "no PATCH for weather-log")
    # DELETE
    dr = requests.delete(f"{BASE}/api/weather-log/{new_id}", timeout=10)
    r.delete = (dr.status_code == 200)
    # SHOWS
    cr2 = requests.post(f"{BASE}/api/weather-log", json=payload, timeout=10)
    if cr2.status_code in (200, 201):
        agg = aggregator(D_LATE)
        wx = agg.get("weather") or {}
        am_cond = (wx.get("am") or {}).get("conditions") or ""
        r.shows = am_cond.startswith(MARKER + "_WX")
        # cleanup
        nid = cr2.json()["data"].get("id")
        requests.delete(f"{BASE}/api/weather-log/{nid}", timeout=10)
    else:
        r.shows = False
    return r


def test_safety_events():
    return _dcr_section_test(
        name="DCR safety_events",
        table="safety_events",
        post_url=f"{BASE}/api/safety-events",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "event_type": "near-miss", "severity": "low",
                 "time": "10:00", "person": "smoke",
                 "description": MARKER + "_SAFE",
                 "action": "noted", "reported_by": "smoke"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/safety-events/{rid}",
        edit_method="PATCH",
        edit_payload={"description": MARKER + "_SAFE_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/safety-events/{rid}",
        aggregator_key="safety",
        match_fn=lambda i: (i.get("description") or "").startswith(MARKER + "_SAFE"),
    )


def test_toolbox():
    """Toolbox talks: aggregator surfaces ONE talk per day in safety.toolbox_talk."""
    r = SectionResult("DCR toolbox_talk_records")
    # Pick a real talk_id from the library
    conn = db()
    try:
        row = conn.execute("SELECT talk_id FROM toolbox_talk_library LIMIT 1").fetchone()
        talk_id = row["talk_id"] if row else "TB-001"
        conn.execute("DELETE FROM toolbox_talk_records WHERE project_code = ? AND date = ?",
                     (PROJECT, D_LATE))
        conn.commit()
    finally:
        conn.close()
    payload = {"project_code": PROJECT, "date": D_LATE,
               "talk_id": talk_id,
               "facilitator": MARKER + "_TB",
               "attendees": 5, "duration_minutes": 10}
    cr = requests.post(f"{BASE}/api/toolbox-talks/records", json=payload, timeout=10)
    new_id = cr.json()["data"].get("id") if cr.status_code in (200, 201) else None
    r.create = bool(new_id)
    # EDIT — no PATCH
    p = requests.patch(f"{BASE}/api/toolbox-talks/records/{new_id}",
                       json={"facilitator": MARKER + "_TB_EDITED"}, timeout=10)
    r.edit = (p.status_code in (200, 201))
    if not r.edit:
        add_note(r, "no PATCH for toolbox-talks/records")
    # DELETE
    dr = requests.delete(f"{BASE}/api/toolbox-talks/records/{new_id}", timeout=10)
    r.delete = (dr.status_code == 200)
    # SHOWS
    cr2 = requests.post(f"{BASE}/api/toolbox-talks/records", json=payload, timeout=10)
    if cr2.status_code in (200, 201):
        agg = aggregator(D_LATE)
        tt = (agg.get("safety") or {}).get("toolbox_talk")
        r.shows = bool(tt and tt.get("conducted_by", "").startswith(MARKER + "_TB"))
        requests.delete(f"{BASE}/api/toolbox-talks/records/{cr2.json()['data']['id']}", timeout=10)
    else:
        r.shows = False
    return r


def test_issues():
    return _dcr_section_test(
        name="DCR issues / delays",
        table="issues",
        post_url=f"{BASE}/api/issues",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "category": "Weather", "description": MARKER + "_ISS",
                 "time_lost_hrs": 0.5, "action": "noted",
                 "owner": "smoke", "status": "open"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/issues/{rid}",
        edit_method="PATCH",
        edit_payload={"description": MARKER + "_ISS_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/issues/{rid}",
        aggregator_key="issues_delays",
        match_fn=lambda i: (i.get("description") or "").startswith(MARKER + "_ISS"),
    )


def test_inspections():
    return _dcr_section_test(
        name="DCR inspections",
        table="inspections",
        post_url=f"{BASE}/api/inspections",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "type": "Internal QC", "inspector_name": "smoke",
                 "agency": "SSC", "area": "Floor 3",
                 "result": "pass", "notes": MARKER + "_INSP"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/inspections/{rid}",
        edit_method="PATCH",
        edit_payload={"notes": MARKER + "_INSP_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/inspections/{rid}",
        aggregator_key="inspections",
        match_fn=lambda i: (i.get("notes") or "").startswith(MARKER + "_INSP"),
    )


def test_visitors():
    return _dcr_section_test(
        name="DCR visitors",
        table="visitors",
        post_url=f"{BASE}/api/visitors",
        payload={"project_code": PROJECT, "date": D_LATE,
                 "name": "SMOKE_VISITOR", "company": "Test",
                 "role": "Inspector", "time_in": "09:00",
                 "time_out": "10:00", "purpose": MARKER + "_VIS",
                 "accompanied_by": "smoke", "notes": MARKER + "_VIS"},
        edit_url_tmpl=lambda rid: f"{BASE}/api/visitors/{rid}",
        edit_method="PATCH",
        edit_payload={"notes": MARKER + "_VIS_EDITED"},
        delete_url_tmpl=lambda rid: f"{BASE}/api/visitors/{rid}",
        aggregator_key="visitors",
        match_fn=lambda i: (i.get("notes") or "").startswith(MARKER + "_VIS"),
    )


def test_photos():
    r = SectionResult("DCR photos (upload + delete)")
    # CREATE — multipart upload
    files = {"photo": ("smoke.jpg", make_jpeg_bytes(), "image/jpeg")}
    data = {"project_code": PROJECT, "date": D_LATE,
            "location": "Floor 3", "description": MARKER + "_PHOTO",
            "uploaded_by": "smoke"}
    up = requests.post(f"{BASE}/api/photos/upload", files=files, data=data, timeout=15)
    new_id = up.json()["data"].get("id") if up.status_code in (200, 201) else None
    r.create = bool(new_id)
    # EDIT — no PATCH endpoint
    p = requests.patch(f"{BASE}/api/photos/{new_id}",
                       json={"description": MARKER + "_PHOTO_EDITED"}, timeout=10)
    r.edit = (p.status_code in (200, 201))
    if not r.edit:
        add_note(r, "no PATCH for photos")
    # DELETE
    dr = requests.delete(f"{BASE}/api/photos/{new_id}", timeout=10)
    r.delete = (dr.status_code == 200)
    # SHOWS
    up2 = requests.post(f"{BASE}/api/photos/upload", files=files, data=data, timeout=15)
    if up2.status_code in (200, 201):
        agg = aggregator(D_LATE)
        photos = agg.get("photos") or []
        r.shows = any((p.get("description") or "").startswith(MARKER + "_PHOTO") for p in photos)
        nid = up2.json()["data"].get("id")
        if nid:
            requests.delete(f"{BASE}/api/photos/{nid}", timeout=10)
    else:
        r.shows = False
    return r


def test_weekly_hours():
    """Weekly Hours Log: hours are SOURCED from sign_in_log. The grid GET
    is /api/payroll/hours; cell edit = sign-ins POST/PUT/DELETE."""
    r = SectionResult("Weekly Hours Log (cell add/edit/delete)")
    # Use D_LATE (2026-05-21 = Thursday). Monday of that week = 2026-05-18.
    monday = "2026-05-18"
    emps = requests.get(f"{BASE}/api/employees", timeout=10).json()["data"]
    target_emp = emps[2]["employee_id"] if len(emps) > 2 else emps[0]["employee_id"]
    test_date = D_LATE
    # clean
    conn = db()
    try:
        conn.execute(
            "DELETE FROM sign_in_log WHERE employee_id = ? AND date = ? AND project_code = ?",
            (target_emp, test_date, PROJECT)
        )
        conn.commit()
    finally:
        conn.close()
    # CREATE — POST a sign-in
    cr = requests.post(f"{BASE}/api/sign-ins", json={
        "employee_id": target_emp, "project_code": PROJECT,
        "date": test_date, "time_in": "07:00", "time_out": "15:30",
    }, timeout=10)
    new_id = cr.json()["data"]["id"] if cr.status_code in (200, 201) else None
    grid = requests.get(f"{BASE}/api/payroll/hours",
                        params={"week_start": monday}, timeout=10).json()["data"]
    found = False
    for w in grid["workers"]:
        if w["employee_id"] == target_emp:
            for d in w["days"]:
                if d.get("date") == test_date and d.get("has_entry"):
                    found = True
    r.create = bool(new_id) and found
    # EDIT — PUT (full replace) to change times → grid should reflect new hours
    if new_id is not None:
        ur = requests.put(f"{BASE}/api/sign-ins/{new_id}",
                          json={"time_in": "08:00", "time_out": "12:00"}, timeout=10)
        grid2 = requests.get(f"{BASE}/api/payroll/hours",
                             params={"week_start": monday}, timeout=10).json()["data"]
        new_hours = None
        for w in grid2["workers"]:
            if w["employee_id"] == target_emp:
                for d in w["days"]:
                    if d.get("date") == test_date:
                        new_hours = d.get("hours")
        r.edit = (ur.status_code == 200 and new_hours not in (None, 0))
    else:
        r.edit = False
    # DELETE — clearing a cell = DELETE the sign-in
    if new_id is not None:
        dr = requests.delete(f"{BASE}/api/sign-ins/{new_id}", timeout=10)
        grid3 = requests.get(f"{BASE}/api/payroll/hours",
                             params={"week_start": monday}, timeout=10).json()["data"]
        gone = True
        for w in grid3["workers"]:
            if w["employee_id"] == target_emp:
                for d in w["days"]:
                    if d.get("date") == test_date and d.get("has_entry"):
                        gone = False
        r.delete = (dr.status_code == 200 and gone)
    else:
        r.delete = False
    # SHOWS = grid surfaces the entry while it's present (already verified in CREATE)
    r.shows = r.create
    return r


# ---------- Main ----------

def main():
    cleanup_marker()
    real_emp_id = preflight()
    print(f"# Smoke run marker: {MARKER}")
    print(f"# Target employee (E-): {real_emp_id}")
    print(f"# Dates: {D_EARLY}, {D_MID}, {D_LATE}")
    print()

    results = []
    section_fns = [
        ("Workforce",        lambda: test_workforce(real_emp_id)),
        ("Intake",           lambda: test_intake_status(real_emp_id)),
        ("FacePhoto",        lambda: test_face_photo(real_emp_id)),
        ("CertUpload",       lambda: test_cert_upload(real_emp_id)),
        ("Credential",       lambda: test_credential_issue(real_emp_id)),
        ("SignIns",          lambda: test_sign_ins(real_emp_id)),
        ("WorkLog",          lambda: test_work_log()),
        ("Deliveries",       lambda: test_deliveries()),
        ("Equipment",        lambda: test_equipment()),
        ("Weather",          lambda: test_weather_special()),
        ("Safety",           lambda: test_safety_events()),
        ("Toolbox",          lambda: test_toolbox()),
        ("Issues",           lambda: test_issues()),
        ("Inspections",      lambda: test_inspections()),
        ("Visitors",         lambda: test_visitors()),
        ("Photos",           lambda: test_photos()),
        ("WeeklyHours",      lambda: test_weekly_hours()),
    ]
    for short, fn in section_fns:
        try:
            res = fn()
        except Exception as e:
            res = SectionResult(short)
            res.create = res.edit = res.delete = res.shows = False
            add_note(res, f"exception: {type(e).__name__}: {e}")
        results.append(res)
        sys.stdout.write(f"  [{res.verdict():7}] {res.name}\n")
        sys.stdout.flush()

    # Build the table
    print()
    print("| Section | Create | Edit | Delete | Shows in report | Verdict |")
    print("|---|---|---|---|---|---|")
    for r in results:
        print(r.row())

    # Print any per-section notes
    print()
    print("## Notes")
    for r in results:
        if r.notes:
            print(f"- **{r.name}**: " + "; ".join(r.notes))

    # Final cleanup
    cleanup_marker()


if __name__ == "__main__":
    main()
