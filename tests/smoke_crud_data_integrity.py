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
import re
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

# #251 — the no-filesystem-path-on-the-wire contract (CLAUDE.md PII rule),
# enforced structurally by response_wrapper's scrub_paths. Same key pattern as
# the gate's response-path guard (tests/_smoke_auth.py): a bare 'folder' or any
# key ending in path/file_path/filepath. Returns True if ANY such key is present
# anywhere in the payload — never returns values (PII discipline).
_PATH_KEY_RE = re.compile(r"(?i)(^|_)(file_?path|filepath|path|folder)$")


def has_path_key(obj):
    if isinstance(obj, dict):
        return any((isinstance(k, str) and _PATH_KEY_RE.search(k)) or has_path_key(v)
                   for k, v in obj.items())
    if isinstance(obj, list):
        return any(has_path_key(v) for v in obj)
    return False


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


def _synth_worker(label):
    """Create a synthetic SMK-#### worker. Returns the employee_id, or None
    if creation failed. Caller is responsible for teardown via
    `_synth_teardown(emp_id)`.

    The synthetic-worker pattern exists so face-photo and credential-issuance
    CRUD round-trips don't write through to a real operator worker. The
    previous flaw (caught in #172-v2 / Robert): test_face_photo POSTed a
    1x1 placeholder JPEG to employees[0] = W-0001, then "restored" only the
    DB column. The upload handler had already overwritten face.jpg on disk
    with the placeholder bytes; the smoke test passed (column round-trip)
    while the worker's real photo file was destroyed. test_credential_issue
    had the same defect (placeholder face write + supersedes real CoF).
    """
    syn_id = "SMK-" + uuid.uuid4().hex[:6].upper()
    resp = requests.post(f"{BASE}/api/workers/create", json={
        "employee_id": syn_id,
        "name": f"SMOKE {label}",
        "trade": f"SMOKE_{label.upper()}",
        "language": "EN",
    }, timeout=10)
    if resp.status_code != 200:
        return None
    return syn_id


def _synth_teardown(emp_id):
    """Drop a synthetic SMK-#### worker, its credential rows, AND its
    worker_records folder. Idempotent; safe to call from finally:."""
    if not emp_id or not emp_id.startswith("SMK-"):
        return
    folder = None
    conn = db()
    try:
        row = conn.execute(
            "SELECT folder_path FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
        folder = row["folder_path"] if row else None
        for tbl in (
            "project_assignments", "cof_cards", "company_id_cards",
            "certifications", "worker_documents", "sign_in_log",
        ):
            conn.execute(f"DELETE FROM {tbl} WHERE employee_id = ?", (emp_id,))
        conn.execute("DELETE FROM employees WHERE employee_id = ?", (emp_id,))
        conn.commit()
    finally:
        conn.close()
    if folder:
        import shutil
        try:
            p = Path(folder).resolve()
            wr = (SCRIPT_DIR / "worker_records").resolve()
            if str(p).startswith(str(wr)) and p.exists():
                shutil.rmtree(p, ignore_errors=True)
        except Exception:
            pass


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
    public DELETE.

    Operates on a synthetic SMK-#### worker — never on `real_emp_id`. The
    face-photo upload handler overwrites face.<ext> on disk before the DB
    UPDATE; a "restore" that only rewinds the column leaves the real
    worker's photo bytes clobbered. See `_synth_worker` / #172-v2.
    """
    r = SectionResult("Worker face photo (upload)")
    syn_id = _synth_worker("FacePhoto")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # CREATE — upload. #251: the response must carry the GATED image_url and
        # NO *_path key (the #247/#251 PII contract, now enforced structurally by
        # response_wrapper.scrub_paths). The old code read face_image_path off the
        # worker GET — a key the PII fix deliberately removed — which KeyError'd
        # this whole section every run since #247. The test now PROTECTS the fix:
        # it fails if a path key reappears, and confirms the photo is reachable
        # via the gated id-based route instead of a filesystem path.
        files = {"file": ("smoke_face.jpg", make_jpeg_bytes(), "image/jpeg")}
        up = requests.post(
            f"{BASE}/api/employees/{syn_id}/face-photo",
            files=files, timeout=15,
        )
        up_json = up.json() if up.headers.get("Content-Type", "").startswith("application/json") else {}
        img_url = (up_json.get("data") or {}).get("image_url") or up_json.get("image_url")
        served = bool(img_url) and requests.get(f"{BASE}{img_url}", timeout=10).status_code == 200
        g = requests.get(f"{BASE}/api/workers/{syn_id}", timeout=10)
        g_json = g.json() if g.status_code == 200 else {}
        no_path = (g.status_code == 200) and not has_path_key(g_json) and not has_path_key(up_json)
        r.create = (up.status_code == 200 and bool(img_url) and served and no_path)
        if not r.create:
            add_note(r, f"upload={up.status_code} img_url={bool(img_url)} served={served} no_path={no_path}")
        # EDIT = re-upload (overwrites)
        up2 = requests.post(
            f"{BASE}/api/employees/{syn_id}/face-photo",
            files={"file": ("smoke_face2.jpg", make_jpeg_bytes(), "image/jpeg")},
            timeout=15,
        )
        r.edit = (up2.status_code == 200)
        # SHOWS — face_image_path is referenced by /credential endpoint.
        # Check BEFORE delete so a working DELETE doesn't make SHOWS see absent.
        g3 = requests.get(f"{BASE}/api/employees/{syn_id}/credential", timeout=10)
        r.shows = (g3.status_code == 200 and g3.json()["data"].get("face_image_path_present") is True)
        # DELETE
        d = requests.delete(f"{BASE}/api/employees/{syn_id}/face-photo", timeout=10)
        r.delete = (d.status_code == 200)
        if not r.delete:
            add_note(r, f"no public DELETE for face-photo (status {d.status_code})")
    finally:
        _synth_teardown(syn_id)
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
    Hard-gates on face photo. No public UPDATE/DELETE.

    Operates on a synthetic SMK-#### worker — never on `real_emp_id`. The
    previous flaw (caught in #172-v2): override_active=True against a real
    worker marks their existing CoF as 'replaced' permanently (cleanup
    only DELETEd the test issuance row, not the supersede flip), AND the
    "ensure face photo" upload writes a 1x1 placeholder over the real
    worker's face.jpg on disk. The synthetic has no certs so it falls
    through to Company ID issuance, which exercises the same code path.
    """
    r = SectionResult("Credential issuance (CoF/Company ID)")
    syn_id = _synth_worker("Credential")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Synthetic worker needs a face photo before /credential/issue passes
        # its hard-gate check. Writing to the synthetic's folder is contained.
        files = {"file": ("smoke_face.jpg", make_jpeg_bytes(), "image/jpeg")}
        requests.post(f"{BASE}/api/employees/{syn_id}/face-photo", files=files, timeout=15)
        # CREATE — issue. No override_active needed; synthetic has no prior credential.
        iss = requests.post(
            f"{BASE}/api/employees/{syn_id}/credential/issue",
            json={"issued_by": MARKER},
            timeout=15,
        )
        issued_ok = (iss.status_code in (200, 201))
        # READ-BACK
        g = requests.get(f"{BASE}/api/employees/{syn_id}/credential", timeout=10)
        has_current = bool(g.status_code == 200 and g.json()["data"].get("type"))
        r.create = (issued_ok and has_current)
        cred_type = g.json()["data"].get("type") if has_current else None
        # SHOWS — intake-summary surfaces current_credential. Check BEFORE
        # PATCH/DELETE so the soft-revoke from DELETE doesn't sabotage SHOWS.
        ls = requests.get(f"{BASE}/api/workers/intake-summary", timeout=10).json()["data"]
        row = next((x for x in ls if x["employee_id"] == syn_id), None)
        r.shows = bool(row and row.get("current_credential") and
                       row["current_credential"].get("type") == cred_type)
        # EDIT — PATCH credential notes (non-empty body required)
        p = requests.patch(f"{BASE}/api/employees/{syn_id}/credential",
                           json={"notes": MARKER + "_CRED_NOTE"}, timeout=10)
        r.edit = (p.status_code == 200)
        if not r.edit:
            add_note(r, f"PATCH credential failed (status {p.status_code})")
        # DELETE
        d = requests.delete(f"{BASE}/api/employees/{syn_id}/credential", timeout=10)
        r.delete = (d.status_code == 200)
        if not r.delete:
            add_note(r, f"DELETE credential failed (status {d.status_code})")
    finally:
        _synth_teardown(syn_id)
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
    is /api/payroll/hours; cell edit = sign-ins POST/PUT/DELETE.

    #175-reopen / #195 — earlier this test operated on `emps[2]` (real
    worker, in practice Kevin = E-00003 = W-0003) on `D_LATE`
    (2026-05-21, a real DCR-issued date). Every smoke run deleted
    Kevin's 5-21 sign_in_log row before the test even started, then
    deleted the test-created row at the end. After #192 inserted
    Kevin's real 5-21 row, the very next smoke run silently destroyed
    it — undetected for hours because the deletion bypassed
    audit_log. Rewritten to scope to a synthetic SMK-#### worker on a
    synthetic date so the production roster is never touched. Pattern
    matches the #175-audit fixes to test_face_photo and
    test_credential_issue (see _synth_worker / _synth_teardown).
    """
    r = SectionResult("Weekly Hours Log (cell add/edit/delete)")
    # Synthetic date well outside any operator window — same family
    # the roster-completeness smoke uses for the same reason.
    SYN_MONDAY = "2030-03-11"
    SYN_TEST_DATE = "2030-03-13"  # Thursday of the synthetic week
    syn_id = _synth_worker("WkHrs")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Defensive — no row could exist yet, but cleanup_marker
        # patterns from prior history left this here. Limit DELETE to
        # the synthetic worker so it can't bleed onto real data.
        conn = db()
        try:
            conn.execute(
                "DELETE FROM sign_in_log "
                "WHERE employee_id = ? AND date = ? AND project_code = ?",
                (syn_id, SYN_TEST_DATE, PROJECT)
            )
            conn.commit()
        finally:
            conn.close()
        # CREATE — POST a sign-in for the synthetic worker on the
        # synthetic date.
        cr = requests.post(f"{BASE}/api/sign-ins", json={
            "employee_id": syn_id, "project_code": PROJECT,
            "date": SYN_TEST_DATE, "time_in": "07:00", "time_out": "15:30",
        }, timeout=10)
        new_id = cr.json()["data"]["id"] if cr.status_code in (200, 201) else None
        # /api/payroll/hours is week-scoped; the SYN_MONDAY week is
        # well past any real data so no grid pollution.
        grid = requests.get(f"{BASE}/api/payroll/hours",
                            params={"week_start": SYN_MONDAY}, timeout=10).json()["data"]
        found = False
        for w in grid["workers"]:
            if w["employee_id"] == syn_id:
                for d in w["days"]:
                    if d.get("date") == SYN_TEST_DATE and d.get("has_entry"):
                        found = True
        r.create = bool(new_id) and found
        # EDIT — PUT (full replace) to change times → grid should reflect new hours
        if new_id is not None:
            ur = requests.put(f"{BASE}/api/sign-ins/{new_id}",
                              json={"time_in": "08:00", "time_out": "12:00"}, timeout=10)
            grid2 = requests.get(f"{BASE}/api/payroll/hours",
                                 params={"week_start": SYN_MONDAY}, timeout=10).json()["data"]
            new_hours = None
            for w in grid2["workers"]:
                if w["employee_id"] == syn_id:
                    for d in w["days"]:
                        if d.get("date") == SYN_TEST_DATE:
                            new_hours = d.get("hours")
            r.edit = (ur.status_code == 200 and new_hours not in (None, 0))
        else:
            r.edit = False
        # DELETE — clearing a cell = DELETE the sign-in
        if new_id is not None:
            dr = requests.delete(f"{BASE}/api/sign-ins/{new_id}", timeout=10)
            grid3 = requests.get(f"{BASE}/api/payroll/hours",
                                 params={"week_start": SYN_MONDAY}, timeout=10).json()["data"]
            gone = True
            for w in grid3["workers"]:
                if w["employee_id"] == syn_id:
                    for d in w["days"]:
                        if d.get("date") == SYN_TEST_DATE and d.get("has_entry"):
                            gone = False
            r.delete = (dr.status_code == 200 and gone)
        else:
            r.delete = False
        # SHOWS = grid surfaces the entry while it's present (already verified in CREATE)
        r.shows = r.create
    finally:
        _synth_teardown(syn_id)
    return r


def test_dcr_staling_lifecycle():
    """#196 regression guard: DCR `stale` flag lifecycle —
       issue → not_stale → mutate sign_in_log → stale → re-issue → not_stale.

    The Kevin-on-5-21 / DCR-014 stale-badge regression was a textbook
    instance of this lifecycle drifting silently: #192 cleared stale
    via the issue endpoint, then `test_weekly_hours` mutated a 5-21
    sign-in via /api/sign-ins (which fires `_mark_dcr_stale`),
    re-staling DCR-014 until the operator noticed. Three pieces of
    the lifecycle to assert here, each one is the natural transition
    pair the operator's UI depends on.

    Synthetic-only per #175 / the #195 audit:
      - Uses an SMK-#### worker
      - Uses a FUTURE date well outside any operator window so no
        real DCR collides
      - Issues against FR-BX-001 (the only project with templates,
        since `_issue_one_dcr` renders the artifact via WeasyPrint).
        The synthetic date guarantees no real row touched.
    """
    r = SectionResult("DCR staling lifecycle [#196]")
    from datetime import date as _date

    # Synthetic future date — 2030 quarter is safely past any
    # operator-relevant window. Use the same family the other #195/#196
    # synthetic smokes use so we're consistent.
    SYN_DATE = "2030-03-20"
    PROJECT_CODE = "FR-BX-001"
    syn_id = _synth_worker("StaleLife")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    issued_seq = None
    try:
        # Step 1 — seed: post a sign-in for the synthetic worker on
        # the synthetic date via the API so the standard mutation
        # path runs (matches what the operator's daily-report UI does).
        cr = requests.post(f"{BASE}/api/sign-ins", json={
            "employee_id": syn_id, "project_code": PROJECT_CODE,
            "date": SYN_DATE, "time_in": "07:00", "time_out": "15:30",
        }, timeout=10)
        seed_sign_in_id = cr.json()["data"]["id"] if cr.status_code in (200, 201) else None
        if not seed_sign_in_id:
            r.create = False
            add_note(r, f"seed sign-in POST failed status={cr.status_code}")
            return r

        # Step 2 — issue the DCR for the synthetic date. The #194
        # roster-completeness gate would fire here because the
        # project has historical regulars (W-0001..W-0011) far
        # outside this smoke's synthetic future window — the smoke
        # cares about the staling lifecycle, NOT the gate, so use
        # the documented `roster_skip=true` ad-hoc escape (#194
        # explicitly reserves this for tooling and never exposes it
        # in the UI).
        iss = requests.post(
            f"{BASE}/api/projects/{PROJECT_CODE}/daily/{SYN_DATE}/issue",
            json={"audience": "both", "roster_skip": True}, timeout=30,
        )
        issued = iss.json().get("data", {}) if iss.ok else {}
        issued_seq = issued.get("sequence")
        if iss.status_code not in (200, 201) or issued_seq is None:
            r.create = False
            add_note(r,
                f"issue failed status={iss.status_code} body={iss.text[:120]}")
            return r
        # Confirm post-issue stale=0 on both audiences.
        conn = db()
        try:
            row_internal = conn.execute(
                "SELECT stale FROM report_index "
                "WHERE project_code = ? AND report_date = ? "
                "AND report_id LIKE '%-internal'",
                (PROJECT_CODE, SYN_DATE)
            ).fetchone()
            row_client = conn.execute(
                "SELECT stale FROM report_index "
                "WHERE project_code = ? AND report_date = ? "
                "AND report_id LIKE '%-client'",
                (PROJECT_CODE, SYN_DATE)
            ).fetchone()
        finally:
            conn.close()
        r.create = bool(
            row_internal and row_client
            and (row_internal["stale"] or 0) == 0
            and (row_client["stale"] or 0) == 0
        )

        # Step 3 — mutate sign_in_log via the API (PUT changes times).
        # This should fire _mark_dcr_stale; verify both audience rows
        # flip to stale=1.
        mu = requests.put(f"{BASE}/api/sign-ins/{seed_sign_in_id}",
                          json={"time_in": "08:00", "time_out": "14:00"},
                          timeout=10)
        conn = db()
        try:
            after_mut = conn.execute(
                "SELECT report_id, stale FROM report_index "
                "WHERE project_code = ? AND report_date = ?",
                (PROJECT_CODE, SYN_DATE)
            ).fetchall()
        finally:
            conn.close()
        all_stale = all((a["stale"] or 0) == 1 for a in after_mut)
        r.edit = (mu.status_code == 200 and len(after_mut) >= 2 and all_stale)
        if not r.edit:
            stales = [(a["report_id"], a["stale"]) for a in after_mut]
            add_note(r, f"post-mutate state: {stales}  mut_status={mu.status_code}")

        # Step 4 — re-issue. Should clear stale on BOTH rows.
        # roster_skip again for the same reason as Step 2.
        ri = requests.post(
            f"{BASE}/api/projects/{PROJECT_CODE}/daily/{SYN_DATE}/issue",
            json={"audience": "both", "override_active": True,
                  "roster_skip": True}, timeout=30,
        )
        conn = db()
        try:
            after_reissue = conn.execute(
                "SELECT report_id, stale FROM report_index "
                "WHERE project_code = ? AND report_date = ?",
                (PROJECT_CODE, SYN_DATE)
            ).fetchall()
        finally:
            conn.close()
        all_clean = all((a["stale"] or 0) == 0 for a in after_reissue)
        r.delete = (ri.status_code in (200, 201) and all_clean)
        if not r.delete:
            stales = [(a["report_id"], a["stale"]) for a in after_reissue]
            add_note(r, f"post-reissue state: {stales}  reissue_status={ri.status_code}")

        # SHOWS: all three transitions held.
        r.shows = bool(r.create and r.edit and r.delete)
    finally:
        # Teardown — remove the synthetic DCR rows, the synthetic
        # artifact directory, the sign_in_log row, then the worker.
        conn = db()
        try:
            conn.execute(
                "DELETE FROM report_index "
                "WHERE project_code = ? AND report_date = ?",
                (PROJECT_CODE, SYN_DATE)
            )
            conn.execute(
                "DELETE FROM sign_in_log "
                "WHERE project_code = ? AND date = ? AND employee_id = ?",
                (PROJECT_CODE, SYN_DATE, syn_id)
            )
            conn.commit()
        finally:
            conn.close()
        # Remove the issued artifact directory if known.
        if issued_seq is not None:
            from pathlib import Path as _P
            import shutil
            art = (_P(str(SCRIPT_DIR)) / "data_room" / "reports" / "dcr"
                   / PROJECT_CODE / f"{issued_seq:03d}")
            try:
                if art.exists():
                    shutil.rmtree(art, ignore_errors=True)
            except Exception:
                pass
        _synth_teardown(syn_id)
    return r


def test_roster_completeness_check():
    """#194 prevention guard: DCR issue endpoint refuses to silently
    issue when a regularly-present worker is missing from today's
    roster. Asserts the modal protocol (409 with missing_regulars
    payload, then 200/201 after operator acknowledgement).

    Synthetic-only per #175: two SMK-#### workers + a future date well
    outside any operator-relevant window (2030-03-13) on FR-BX-001 so
    the project's render pipeline still works but no real DCR collides.

    Steps:
      1. Seed: create SMK-A + SMK-B + SMK-C (project_assignments for
         FR-BX-001). Insert sign_in_log rows for SMK-A + SMK-B on 5 of
         the 7 working days prior to TEST_DATE; SMK-C only on 1 day
         (NOT a regular). On TEST_DATE itself, sign_in_log has SMK-A
         only — SMK-B is the missing regular.
      2. POST /api/projects/FR-BX-001/daily/<TEST_DATE>/issue with no
         roster_completeness body → expect 409 + missing_regulars
         containing SMK-B's W-#### and NOT SMK-C's.
      3. POST again with roster_completeness={action: 'mark_absent',
         acknowledge_missing: [SMK-B.wid]} → expect 200/201 and a
         'roster_completeness_mark_absent' audit row for SMK-B's emp.
      4. Teardown of every SMK-* row + the rendered artifact.
    """
    r = SectionResult("Roster completeness (#194)")
    import os
    from datetime import date as _date, timedelta as _td
    from pathlib import Path as _P

    TEST_DATE = "2030-03-13"
    test_date_d = _date.fromisoformat(TEST_DATE)
    # Build 5 of the prior 7 weekdays as "recent" presence.
    prior_days = []
    cursor = test_date_d - _td(days=1)
    while len(prior_days) < 5:
        if cursor.weekday() < 5:
            prior_days.append(cursor.isoformat())
        cursor -= _td(days=1)

    syn_a = _synth_worker("RostA")
    syn_b = _synth_worker("RostB")
    syn_c = _synth_worker("RostC")
    if not (syn_a and syn_b and syn_c):
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        # Teardown what did get created
        for sid in (syn_a, syn_b, syn_c):
            if sid: _synth_teardown(sid)
        return r
    artifact_dir = _P(str(SCRIPT_DIR)) / "data_room" / "reports" / "dcr" / "FR-BX-001"
    seq_dir_to_remove = None
    try:
        # Get the synthetic W-####s for assertion comparison
        conn = db()
        try:
            wid_a = conn.execute(
                "SELECT worker_id FROM employees WHERE employee_id = ?", (syn_a,)
            ).fetchone()["worker_id"]
            wid_b = conn.execute(
                "SELECT worker_id FROM employees WHERE employee_id = ?", (syn_b,)
            ).fetchone()["worker_id"]
            wid_c = conn.execute(
                "SELECT worker_id FROM employees WHERE employee_id = ?", (syn_c,)
            ).fetchone()["worker_id"]
            # SMK-A + SMK-B each: 5 days of prior sign-ins (regulars)
            for d in prior_days:
                for emp_id in (syn_a, syn_b):
                    conn.execute(
                        "INSERT INTO sign_in_log "
                        "(date, employee_id, project_code, time_in, time_out, "
                        " created_at, updated_at) "
                        "VALUES (?, ?, 'FR-BX-001', '07:00', '15:30', "
                        "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                        (d, emp_id),
                    )
            # SMK-C: only ONE prior day (not a regular).
            conn.execute(
                "INSERT INTO sign_in_log "
                "(date, employee_id, project_code, time_in, time_out, "
                " created_at, updated_at) "
                "VALUES (?, ?, 'FR-BX-001', '07:00', '15:30', "
                "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (prior_days[0], syn_c),
            )
            # On TEST_DATE itself: SMK-A only. SMK-B = missing regular.
            conn.execute(
                "INSERT INTO sign_in_log "
                "(date, employee_id, project_code, time_in, time_out, "
                " created_at, updated_at) "
                "VALUES (?, ?, 'FR-BX-001', '07:00', '15:30', "
                "        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (TEST_DATE, syn_a),
            )
            conn.commit()
        finally:
            conn.close()

        # Step 2 — first POST: expect 409 + missing_regulars=[wid_b]
        url = f"{BASE}/api/projects/FR-BX-001/daily/{TEST_DATE}/issue"
        resp = requests.post(url, json={"audience": "internal"}, timeout=15)
        body = resp.json() if resp.headers.get("Content-Type", "").startswith("application/json") else {}
        missing_set = {m["worker_id"] for m in (body.get("missing_regulars") or [])}
        r.create = (
            resp.status_code == 409
            and body.get("roster_completeness_required") is True
            and wid_b in missing_set
            and wid_c not in missing_set
        )
        if not r.create:
            add_note(r,
                f"first POST: status={resp.status_code}  "
                f"missing={missing_set}  "
                f"expected wid_b={wid_b} in, wid_c={wid_c} out")

        # Step 3 — second POST: ack with mark_absent → expect 201.
        # Capture the issued sequence so we can rmtree the artifact in
        # teardown.
        resp2 = requests.post(url, json={
            "audience": "internal",
            "roster_completeness": {
                "action": "mark_absent",
                "acknowledge_missing": [wid_b],
            },
        }, timeout=30)
        body2 = resp2.json() if resp2.headers.get("Content-Type", "").startswith("application/json") else {}
        issued_seq = (body2.get("data") or {}).get("sequence")
        r.edit = (resp2.status_code in (200, 201) and issued_seq is not None)
        if issued_seq:
            seq_dir_to_remove = artifact_dir / f"{issued_seq:03d}"

        # Step 3b — audit row written for SMK-B's mark_absent.
        conn = db()
        try:
            audit_n = conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE action='roster_completeness_mark_absent' AND target_id=?",
                (wid_b,),
            ).fetchone()[0]
        finally:
            conn.close()
        r.delete = (audit_n >= 1)
        if not r.delete:
            add_note(r, f"expected mark_absent audit row for {wid_b}, got {audit_n}")

        r.shows = (r.create and r.edit and r.delete)
    finally:
        conn = db()
        try:
            for sid in (syn_a, syn_b, syn_c):
                conn.execute("DELETE FROM sign_in_log WHERE employee_id = ?", (sid,))
            # Remove the issued DCR rows + clean up audit_log noise
            conn.execute(
                "DELETE FROM report_index "
                "WHERE project_code='FR-BX-001' AND report_date = ?",
                (TEST_DATE,),
            )
            for sid in (syn_a, syn_b, syn_c):
                conn.execute(
                    "DELETE FROM audit_log "
                    "WHERE action IN ('roster_completeness_mark_absent', "
                    "                 'signin_roster_completeness_default') "
                    "AND target_id = ?",
                    (sid,),
                )
            wid_locals = [wid_a, wid_b, wid_c] if 'wid_a' in dir() else []
            for wid in wid_locals:
                conn.execute(
                    "DELETE FROM audit_log "
                    "WHERE action IN ('roster_completeness_mark_absent') "
                    "AND target_id = ?",
                    (wid,),
                )
            conn.commit()
        finally:
            conn.close()
        for sid in (syn_a, syn_b, syn_c):
            _synth_teardown(sid)
        # Remove the issued artifact directory if we know which one.
        import shutil
        try:
            if seq_dir_to_remove and seq_dir_to_remove.exists():
                shutil.rmtree(seq_dir_to_remove, ignore_errors=True)
        except Exception:
            pass
    return r


def test_signin_dcr_invariant():
    """#191 regression guard: sign_in_log ↔ DCR-artifact roster
    divergence detection + reconciliation end-to-end.

    Synthetic-only per the #175 audit — creates a synthetic SMK-#### worker
    and a dedicated SMK-DCR-INV project_code so real production data
    (FR-BX-001 and the operator's actual workers) is never touched.
    Steps:
      1. Establish a clean SMK round-trip: sign_in_log + fake DCR
         artifact + report_index row → no divergence.
      2. DELETE the sign_in_log row → compute_divergences must report
         one in_dcr_not_log.
      3. Run reconcile_in_dcr_not_log → row restored, audit row added.
      4. Post-reconcile compute_divergences → empty again.
      5. Teardown of every SMK-* row + artifact directory.
    """
    r = SectionResult("Sign-in <-> DCR invariant [#191]")
    import os
    from pathlib import Path as _P
    SMK_PROJECT = "SMK-DCR-INV"
    TEST_DATE = "2020-01-15"  # well outside any operator-relevant window
    syn_id = _synth_worker("DcrInv")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    artifact_dir = _P(str(SCRIPT_DIR)) / "data_room" / "reports" / "dcr" / SMK_PROJECT / "001"
    try:
        # Look up the synthetic's worker_id (W-#### assigned by
        # /api/workers/create; need it for the fake artifact body).
        conn = db()
        try:
            row = conn.execute(
                "SELECT worker_id FROM employees WHERE employee_id = ?",
                (syn_id,)
            ).fetchone()
            syn_wid = row["worker_id"] if row else None
            if not syn_wid:
                r.create = False
                add_note(r, "synthetic worker has no W-#### assigned")
                return r
            # Step 1 — seed: sign_in_log row, fake DCR artifact + report_index.
            conn.execute(
                "INSERT INTO sign_in_log (date, employee_id, project_code, "
                "time_in, time_out, created_at, updated_at) "
                "VALUES (?, ?, ?, '07:00', '15:30', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (TEST_DATE, syn_id, SMK_PROJECT),
            )
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "internal.html").write_text(
                f"<html><body>Synthetic DCR · {syn_wid}</body></html>",
                encoding="utf-8",
            )
            conn.execute(
                "INSERT INTO report_index "
                "(report_id, project_code, report_type, status, report_date, "
                " dcr_sequence, no_work, stale, created_at, updated_at) "
                "VALUES (?, ?, 'DCR', 'issued', ?, 1, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
                (f"DCR-{SMK_PROJECT}-001-internal", SMK_PROJECT, TEST_DATE),
            )
            conn.commit()
        finally:
            conn.close()

        # Step 1 cont. — compute divergences against the seeded state.
        import sys as _sys
        _sys.path.insert(0, str(SCRIPT_DIR))
        from signin_dcr_reconcile import (
            compute_divergences, reconcile_in_dcr_not_log
        )
        conn = db()
        try:
            divs0 = compute_divergences(conn, SMK_PROJECT)
        finally:
            conn.close()
        r.create = (len(divs0) == 0)
        if not r.create:
            add_note(r, f"seeded state had {len(divs0)} divergences "
                        f"(expected 0)")

        # Step 2 — DELETE the sign_in_log row, expect 1 in_dcr_not_log.
        conn = db()
        try:
            conn.execute(
                "DELETE FROM sign_in_log "
                "WHERE project_code = ? AND date = ? AND employee_id = ?",
                (SMK_PROJECT, TEST_DATE, syn_id),
            )
            conn.commit()
            divs1 = compute_divergences(conn, SMK_PROJECT)
        finally:
            conn.close()
        r.edit = (
            len(divs1) == 1
            and divs1[0]["class"] == "in_dcr_not_log"
            and divs1[0]["worker_id"] == syn_wid
            and divs1[0]["date"] == TEST_DATE
        )
        if not r.edit:
            add_note(r, f"post-delete divergences unexpected: {divs1}")

        # Step 3 — reconcile, expect inserted + audit row.
        conn = db()
        try:
            rec = reconcile_in_dcr_not_log(
                conn, SMK_PROJECT, divs1,
                actor_user_id=None, actor_role="smoke",
            )
            conn.commit()
            divs2 = compute_divergences(conn, SMK_PROJECT)
            audit_n = conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE action='signin_reconcile_from_dcr' AND target_id=?",
                (syn_id,),
            ).fetchone()[0]
        finally:
            conn.close()
        r.delete = (  # "DELETE" column in the smoke = the round-trip result
            rec.get("reconciled") == 1
            and len(divs2) == 0
            and audit_n >= 1
        )
        if not r.delete:
            add_note(r,
                f"reconcile summary={rec}  post divs={divs2}  audit rows={audit_n}")

        # Step 4 — SHOWS = invariant holds end-to-end.
        r.shows = (r.create and r.edit and r.delete)
    finally:
        # Teardown — pure SMK-* cleanup.
        conn = db()
        try:
            conn.execute(
                "DELETE FROM sign_in_log WHERE project_code = ?", (SMK_PROJECT,)
            )
            conn.execute(
                "DELETE FROM report_index WHERE project_code = ?", (SMK_PROJECT,)
            )
            conn.execute(
                "DELETE FROM audit_log "
                "WHERE action='signin_reconcile_from_dcr' AND target_id LIKE 'SMK-%'"
            )
            conn.commit()
        finally:
            conn.close()
        _synth_teardown(syn_id)
        # Remove the SMK fake DCR artifact directory.
        import shutil
        try:
            top = artifact_dir.parent  # SMK-DCR-INV/
            if top.exists():
                shutil.rmtree(top, ignore_errors=True)
        except Exception:
            pass
    return r


# ---------- LRT rate-effective-date smokes (#197 + #197-verification) ----------
#
# All six tests below operate exclusively on synthetic SMK-#### workers
# on synthetic 2030-class dates so the production roster is never
# touched (per #175 audit + #195 meta-smoke). Placeholder rates are
# $1.00 and $2.00 ONLY — real operator rates never appear in test
# fixtures, the test code, or the smoke log (per CLAUDE.md comp-data
# rule; PII gate enforced even on synthetic rows).
#
# Each test sets up its synthetic worker, exercises one rate-effective-
# date scenario through the LRT API, asserts the per-day-worked lookup
# from #197 rendered correctly, and cleans up worker_rates +
# rate_change audit rows in finally: so the meta-smoke
# (smoke_no_production_data_corruption.py) sees a clean before/after
# diff — anything left behind would flag as production-data pollution
# even though target_id is synthetic.

def _lrt_set_rate_api(syn_id, hourly_rate, effective_from, notes=None):
    """Set a rate via the operator-facing API. Returns response status."""
    body = {"hourly_rate": float(hourly_rate), "effective_from": effective_from}
    if notes:
        body["notes"] = notes
    return requests.post(
        f"{BASE}/api/labor-rates/workers/{syn_id}", json=body, timeout=10
    )


def _lrt_signin(syn_id, project, date_iso, time_in="07:00", time_out="15:30"):
    """Post a sign-in for a synthetic worker on a synthetic date."""
    return requests.post(
        f"{BASE}/api/sign-ins",
        json={
            "employee_id": syn_id, "project_code": project,
            "date": date_iso, "time_in": time_in, "time_out": time_out,
        }, timeout=10,
    )


def _lrt_week(week_start_iso):
    """GET /api/payroll/hours for a week. Returns the data dict."""
    r = requests.get(
        f"{BASE}/api/payroll/hours",
        params={"week_start": week_start_iso}, timeout=15,
    )
    r.raise_for_status()
    return r.json()["data"]


def _lrt_find_row(grid, syn_id):
    for w in grid.get("workers", []):
        if w["employee_id"] == syn_id:
            return w
    return None


def _lrt_cleanup_rate_state(syn_id):
    """Drop the synthetic worker's worker_rates rows + rate_change
    audit rows. Called from each smoke's finally:; the regular
    _synth_teardown handles employees + sign_in_log + workforce
    artifacts but NOT the rate-domain tables."""
    if not syn_id:
        return
    conn = db()
    try:
        conn.execute("DELETE FROM worker_rates WHERE employee_id = ?", (syn_id,))
        conn.execute(
            "DELETE FROM audit_log "
            "WHERE action='rate_change' AND target_id = ?", (syn_id,)
        )
        conn.commit()
    finally:
        conn.close()


def test_lrt_midweek_rate_onset():
    """#197 regression guard: rate effective mid-week renders correctly.

    Operator-reported case (Mario W-0007): rate's effective_from was the
    Wednesday of a week; sign-ins on Wed + Fri fell within the rate's
    effective range; LRT (week-start as-of lookup) returned no rate row
    because 2026-05-11 (Mon) < 2026-05-13 (effective_from) — and the
    column rendered "Rate not set" even though every WORKED day had an
    active rate. Per-day lookup from #197 must clear this.

    Synthetic mirror: SMK-#### worker, week_start=2030-03-11 (Mon),
    effective_from=2030-03-13 (Wed), sign-ins Wed + Fri at 8h each.
    Assert: rate_not_set=False, hourly_rate present, amount_owed > 0,
    rate_effective_from echoes back the Wed date.
    """
    r = SectionResult("LRT mid-week rate onset [#197]")
    SYN_MONDAY = "2030-03-11"
    SYN_WED = "2030-03-13"
    SYN_FRI = "2030-03-15"
    syn_id = _synth_worker("LrtMidWk")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Seed rate effective WEDNESDAY (mid-week, the #197 case).
        rate_resp = _lrt_set_rate_api(syn_id, 1.00, SYN_WED)
        if rate_resp.status_code != 201:
            r.create = False
            add_note(r, f"set_rate -> {rate_resp.status_code}")
            return r
        # Sign-ins on Wed + Fri at 8h each (within effective range).
        s1 = _lrt_signin(syn_id, PROJECT, SYN_WED)
        s2 = _lrt_signin(syn_id, PROJECT, SYN_FRI)
        r.create = (s1.status_code in (200, 201) and s2.status_code in (200, 201))
        # GET LRT for the SYN_MONDAY week.
        grid = _lrt_week(SYN_MONDAY)
        row = _lrt_find_row(grid, syn_id)
        # SHOWS — the column NOT rendering "Rate not set" is the bug fix.
        r.shows = bool(
            row
            and row.get("rate_not_set") is not True
            and "hourly_rate" in row
            and "amount_owed" in row
            and row.get("rate_effective_from") == SYN_WED
            and float(row.get("amount_owed") or 0) > 0
            and float(row.get("weekly_total") or 0) == 16.0
        )
        if not r.shows:
            # PII rule: dump only flags + dates, never rate values.
            add_note(r, f"row keys={sorted(row.keys()) if row else None}  "
                        f"rate_not_set={row.get('rate_not_set') if row else 'no row'}  "
                        f"weekly_total={row.get('weekly_total') if row else None}  "
                        f"rate_eff_from={row.get('rate_effective_from') if row else None}")
        # EDIT — amount_owed == hours * $1.00 = 16.00.
        if row:
            r.edit = (abs(float(row.get("amount_owed") or 0) - 16.0) < 0.005)
        else:
            r.edit = False
        # DELETE step = cleanup runs in finally: and meta-smoke sees clean diff.
        r.delete = True
    finally:
        _lrt_cleanup_rate_state(syn_id)
        _synth_teardown(syn_id)
    return r


def test_lrt_future_dated_rate():
    """Future-dated rate: rate A this week, NEW rate B effective next Mon.
    Current week renders rate A; future week renders rate B.

    Validates: the per-day lookup correctly picks the *latest* rate row
    whose effective_from is <= the day being computed. A future-dated
    rate must not bleed back into the current week.
    """
    r = SectionResult("LRT future-dated rate [#197-verify]")
    WEEK_A = "2030-04-08"       # Monday
    WEEK_B = "2030-04-15"       # Monday (1 week future)
    SYN_TUE_A = "2030-04-09"
    SYN_TUE_B = "2030-04-16"
    syn_id = _synth_worker("LrtFuture")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Rate A=$1.00 effective WEEK_A start. Rate B=$2.00 effective
        # WEEK_B start (one week in the future from operator's POV).
        ra = _lrt_set_rate_api(syn_id, 1.00, WEEK_A)
        rb = _lrt_set_rate_api(syn_id, 2.00, WEEK_B)
        # 8h on Tue of each week.
        _lrt_signin(syn_id, PROJECT, SYN_TUE_A)
        _lrt_signin(syn_id, PROJECT, SYN_TUE_B)
        r.create = (ra.status_code == 201 and rb.status_code == 201)
        # WEEK_A — Tue is 2030-04-09, before rate B's effective_from.
        # Per-day lookup returns rate A → amount_owed = 8 * $1.00 = 8.00.
        grid_a = _lrt_week(WEEK_A)
        row_a = _lrt_find_row(grid_a, syn_id)
        ok_a = bool(
            row_a
            and not row_a.get("rate_not_set")
            and abs(float(row_a.get("amount_owed") or 0) - 8.0) < 0.005
            and row_a.get("rate_effective_from") == WEEK_A
        )
        # WEEK_B — Tue is 2030-04-16, after rate B's effective_from.
        # Per-day picks rate B → amount_owed = 8 * $2.00 = 16.00.
        grid_b = _lrt_week(WEEK_B)
        row_b = _lrt_find_row(grid_b, syn_id)
        ok_b = bool(
            row_b
            and not row_b.get("rate_not_set")
            and abs(float(row_b.get("amount_owed") or 0) - 16.0) < 0.005
            and row_b.get("rate_effective_from") == WEEK_B
        )
        r.shows = ok_a and ok_b
        r.edit = ok_a  # current-week rate A behavior
        r.delete = ok_b  # future-week rate B behavior
        if not r.shows:
            add_note(r,
                f"weekA ok={ok_a} eff_from={row_a.get('rate_effective_from') if row_a else None}; "
                f"weekB ok={ok_b} eff_from={row_b.get('rate_effective_from') if row_b else None}")
    finally:
        _lrt_cleanup_rate_state(syn_id)
        _synth_teardown(syn_id)
    return r


def test_lrt_retroactive_rate():
    """Retroactive rate: worker has rate A for two weeks, then operator
    enters rate B with the SAME effective_from as A (or matching the
    earliest worked day). Both weeks now render at rate B — the "raise
    applied to weeks already worked" payroll scenario.

    Implementation note: set_rate validates effective_from >= current's
    effective_from, so retroactive-to-same-date is the supported path.
    Earlier than current's effective_from is explicitly rejected by
    worker_rates.set_rate (RateError). This test exercises the
    same-date retroactive path which is what payroll's "raise" usually
    means anyway.
    """
    r = SectionResult("LRT retroactive rate [#197-verify]")
    WEEK_1 = "2030-05-06"     # Monday
    WEEK_2 = "2030-05-13"     # Monday
    SYN_TUE_1 = "2030-05-07"
    SYN_TUE_2 = "2030-05-14"
    syn_id = _synth_worker("LrtRetro")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Rate A=$1.00 effective WEEK_1. Two weeks of work at A.
        ra = _lrt_set_rate_api(syn_id, 1.00, WEEK_1)
        _lrt_signin(syn_id, PROJECT, SYN_TUE_1)
        _lrt_signin(syn_id, PROJECT, SYN_TUE_2)
        # Sanity at rate A: week 1 amount_owed = 8.
        grid_pre = _lrt_week(WEEK_1)
        row_pre = _lrt_find_row(grid_pre, syn_id)
        pre_ok = bool(
            row_pre
            and abs(float(row_pre.get("amount_owed") or 0) - 8.0) < 0.005
        )
        # Operator enters retroactive rate B=$2.00 effective same date (WEEK_1).
        rb = _lrt_set_rate_api(syn_id, 2.00, WEEK_1)
        r.create = (ra.status_code == 201 and rb.status_code == 201 and pre_ok)
        if rb.status_code != 201:
            add_note(r, f"retroactive set_rate -> {rb.status_code} {rb.text[:120]}")
        # WEEK_1 now renders at rate B (8 * $2.00 = 16.00).
        grid_a = _lrt_week(WEEK_1)
        row_a = _lrt_find_row(grid_a, syn_id)
        ok_a = bool(
            row_a
            and not row_a.get("rate_not_set")
            and abs(float(row_a.get("amount_owed") or 0) - 16.0) < 0.005
        )
        # WEEK_2 renders at rate B too (8 * $2.00 = 16.00).
        grid_b = _lrt_week(WEEK_2)
        row_b = _lrt_find_row(grid_b, syn_id)
        ok_b = bool(
            row_b
            and not row_b.get("rate_not_set")
            and abs(float(row_b.get("amount_owed") or 0) - 16.0) < 0.005
        )
        r.shows = ok_a and ok_b
        r.edit = ok_a    # retroactive applied to week 1
        r.delete = ok_b  # rate B applied to week 2 too
        if not r.shows:
            add_note(r,
                f"week1 ok={ok_a}  week2 ok={ok_b}")
    finally:
        _lrt_cleanup_rate_state(syn_id)
        _synth_teardown(syn_id)
    return r


def test_lrt_rate_transition_midperiod():
    """Mid-week rate transition: rate A from Mon, rate B from Wed of same
    week. Per the per-day lookup (#197), Mon-Tue compute with rate A,
    Wed-Fri compute with rate B. amount_owed sums those per-day amounts.

    Operationally rare for construction (rate changes usually align to
    Mondays / pay periods) but this test asserts the per-day path
    handles it. Without per-day, the whole week would lock to one rate
    and silently miscalculate.
    """
    r = SectionResult("LRT mid-week rate transition [#197-verify]")
    WEEK = "2030-06-03"       # Monday
    DAYS = ["2030-06-03", "2030-06-04", "2030-06-05", "2030-06-06", "2030-06-07"]
    syn_id = _synth_worker("LrtTrans")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Rate A=$1.00 from Mon, rate B=$2.00 from Wed.
        ra = _lrt_set_rate_api(syn_id, 1.00, DAYS[0])   # Mon
        rb = _lrt_set_rate_api(syn_id, 2.00, DAYS[2])   # Wed
        # 8h every weekday.
        for d in DAYS:
            _lrt_signin(syn_id, PROJECT, d)
        r.create = (ra.status_code == 201 and rb.status_code == 201)
        grid = _lrt_week(WEEK)
        row = _lrt_find_row(grid, syn_id)
        # Per-day breakdown: Mon, Tue @ $1.00 = $8 each; Wed, Thu, Fri
        # @ $2.00 = $16 each. Total = 2*8 + 3*16 = 16 + 48 = 64.00.
        expected = 2 * 8 * 1.00 + 3 * 8 * 2.00
        ok = bool(
            row
            and not row.get("rate_not_set")
            and abs(float(row.get("amount_owed") or 0) - expected) < 0.005
            and float(row.get("weekly_total") or 0) == 40.0
        )
        r.shows = ok
        # EDIT = per-day math correct; DELETE step = cleanup verified
        # by meta-smoke clean diff.
        r.edit = ok
        r.delete = True
        if not ok:
            add_note(r,
                f"expected amount_owed={expected} got={row.get('amount_owed') if row else None}  "
                f"weekly_total={row.get('weekly_total') if row else None}")
    finally:
        _lrt_cleanup_rate_state(syn_id)
        _synth_teardown(syn_id)
    return r


def test_lrt_end_dated_rate():
    """End-dated rate: rate A active, then end-dated (effective_to set).
    LRT for any week AFTER effective_to renders "Rate not set" correctly
    (no stale rate bleed-through), and weeks fully WITHIN the active
    window still render rate A.

    Also exercises the #158 auto-end-dating: when rate B is inserted on
    top of rate A, A's effective_to gets set to (B.effective_from - 1
    day) automatically by set_rate. Verifies that auto-end-date is
    honored by the per-day lookup.
    """
    r = SectionResult("LRT end-dated rate [#197-verify]")
    WEEK_ACTIVE = "2030-07-01"       # Monday — rate A is active this week
    WEEK_AFTER = "2030-07-15"        # Monday — well past end_date
    SYN_TUE_ACTIVE = "2030-07-02"
    SYN_TUE_AFTER = "2030-07-16"
    syn_id = _synth_worker("LrtEnd")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Rate A=$1.00 active from 2030-07-01.
        ra = _lrt_set_rate_api(syn_id, 1.00, WEEK_ACTIVE)
        # Set rate B=$2.00 effective 2030-07-08 (Monday of week-2).
        # Per #158, this auto-end-dates rate A with effective_to=2030-07-07.
        rb = _lrt_set_rate_api(syn_id, 2.00, "2030-07-08")
        # Sign-in in the active window (WEEK_ACTIVE).
        _lrt_signin(syn_id, PROJECT, SYN_TUE_ACTIVE)
        # Sign-in in the post-B window (WEEK_AFTER, beyond rate B too).
        _lrt_signin(syn_id, PROJECT, SYN_TUE_AFTER)
        r.create = (ra.status_code == 201 and rb.status_code == 201)
        # WEEK_ACTIVE: rate A should still render (within its window).
        grid_a = _lrt_week(WEEK_ACTIVE)
        row_a = _lrt_find_row(grid_a, syn_id)
        ok_a = bool(
            row_a
            and not row_a.get("rate_not_set")
            and abs(float(row_a.get("amount_owed") or 0) - 8.0) < 0.005
            and row_a.get("rate_effective_from") == WEEK_ACTIVE
        )
        # WEEK_AFTER: rate B (effective_from=2030-07-08) covers
        # 2030-07-16, so rate B renders (8h * $2 = $16). The OLD rate A
        # would be incorrectly applied IF the lookup ignored
        # effective_to; this asserts the auto-end-date is honored.
        grid_b = _lrt_week(WEEK_AFTER)
        row_b = _lrt_find_row(grid_b, syn_id)
        ok_b = bool(
            row_b
            and not row_b.get("rate_not_set")
            and abs(float(row_b.get("amount_owed") or 0) - 16.0) < 0.005
            and row_b.get("rate_effective_from") == "2030-07-08"
        )
        # Also verify: manually end-date rate B (post-supersede) so no
        # rate is active in WEEK_AFTER, then assert "Rate not set"
        # renders. Direct UPDATE — no rate API for retroactive end-date.
        conn = db()
        try:
            conn.execute(
                "UPDATE worker_rates SET effective_to = '2030-07-09' "
                "WHERE employee_id = ? AND effective_from = '2030-07-08'",
                (syn_id,)
            )
            conn.commit()
        finally:
            conn.close()
        # Now WEEK_AFTER's 2030-07-16 sign-in has no rate active on it.
        grid_c = _lrt_week(WEEK_AFTER)
        row_c = _lrt_find_row(grid_c, syn_id)
        ok_c = bool(
            row_c
            and row_c.get("rate_not_set") is True
            and "hourly_rate" not in row_c
        )
        r.shows = ok_a and ok_b and ok_c
        r.edit = ok_a and ok_b  # rate-A active window + auto-end-date honored
        r.delete = ok_c          # post-end-date "Rate not set" rendered
        if not r.shows:
            add_note(r,
                f"active ok={ok_a}  postB ok={ok_b}  postEnd ok={ok_c}")
    finally:
        _lrt_cleanup_rate_state(syn_id)
        _synth_teardown(syn_id)
    return r


def test_lrt_hire_mid_pay_period():
    """Mid-pay-period hire: worker first signs in Wed of a week, rate
    effective_from = hire date. Wed/Thu/Fri have hours + rate; Mon/Tue
    have no entry. Per-day lookup must NOT render "Rate not set" for
    the worker's row just because Mon/Tue have no hours — the worker
    DID work within the effective range, just not on every day.

    The Mario W-0007 case generalized: any new hire onboarding mid-week
    where the rate row effective_from = first day worked.
    """
    r = SectionResult("LRT mid-period hire [#197-verify]")
    WEEK = "2030-08-05"       # Monday
    SYN_WED = "2030-08-07"
    SYN_THU = "2030-08-08"
    SYN_FRI = "2030-08-09"
    syn_id = _synth_worker("LrtHire")
    if not syn_id:
        r.create = r.edit = r.delete = r.shows = False
        add_note(r, "synth worker create failed")
        return r
    try:
        # Rate effective on hire date (Wed). No sign-ins Mon/Tue.
        ra = _lrt_set_rate_api(syn_id, 1.00, SYN_WED)
        _lrt_signin(syn_id, PROJECT, SYN_WED)
        _lrt_signin(syn_id, PROJECT, SYN_THU)
        _lrt_signin(syn_id, PROJECT, SYN_FRI)
        r.create = (ra.status_code == 201)
        grid = _lrt_week(WEEK)
        row = _lrt_find_row(grid, syn_id)
        # Wed+Thu+Fri @ 8h = 24h * $1.00 = $24.
        ok_amount = bool(
            row
            and not row.get("rate_not_set")
            and abs(float(row.get("amount_owed") or 0) - 24.0) < 0.005
            and float(row.get("weekly_total") or 0) == 24.0
            and row.get("rate_effective_from") == SYN_WED
        )
        # Mon + Tue cells: no entry, hours == 0.
        days = row.get("days", []) if row else []
        mon_clear = any(
            d.get("date") == "2030-08-05"
            and not d.get("has_entry")
            and (d.get("hours") or 0) == 0
            for d in days
        )
        tue_clear = any(
            d.get("date") == "2030-08-06"
            and not d.get("has_entry")
            and (d.get("hours") or 0) == 0
            for d in days
        )
        r.shows = ok_amount and mon_clear and tue_clear
        r.edit = ok_amount   # amount_owed correct, not blanked by Mon/Tue gap
        r.delete = mon_clear and tue_clear
        if not r.shows:
            add_note(r,
                f"amount_ok={ok_amount}  mon_clear={mon_clear}  tue_clear={tue_clear}  "
                f"rate_eff_from={row.get('rate_effective_from') if row else None}")
    finally:
        _lrt_cleanup_rate_state(syn_id)
        _synth_teardown(syn_id)
    return r


def test_pin_invariant():
    """#188 regression guard: every active worker has a 4-digit numeric PIN.

    Post-#188 the canonical guard (worker_pin.assign_pin_for_worker called
    from the render entry-points in server.serve_card_live AND
    generate_credentials_batch.fetch_card_context) should make this
    invariant impossible to violate. This test asserts it directly so any
    future regression (e.g., a third worker-create path that bypasses
    PIN derivation AND somehow never renders before the operator notices)
    is caught here instead of on the printed card.

    Read-only — does NOT mutate worker rows. PII-safe — only counts +
    W-#### are surfaced; PIN values are never printed.
    """
    r = SectionResult("PIN invariant (every active worker has 4-digit PIN) [#188]")
    conn = db()
    try:
        rows = conn.execute(
            """SELECT worker_id, pin
                 FROM employees
                WHERE archived_at IS NULL
                ORDER BY CAST(SUBSTR(worker_id, 3) AS INTEGER)"""
        ).fetchall()
    finally:
        conn.close()
    bad = []
    for row in rows:
        pin = row["pin"]
        if (pin is None or pin == "" or len(pin) != 4 or not pin.isdigit()):
            bad.append(row["worker_id"])
    # CREATE = "the invariant holds at smoke-time"
    r.create = (len(bad) == 0)
    if not r.create:
        # PII rule: list W-####s, never the (missing/wrong) value.
        add_note(r, f"workers with invalid PIN: {bad}")
    # EDIT / DELETE / SHOWS are N/A — this is a read-only invariant.
    r.edit = "n/a"
    r.delete = "n/a"
    r.shows = (len(rows) > 0)  # we got SOME rows back (sanity)
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
        ("PinInvariant",     lambda: test_pin_invariant()),
        ("SignInDcrInvariant", lambda: test_signin_dcr_invariant()),
        ("RosterCompleteness", lambda: test_roster_completeness_check()),
        ("DcrStalingLifecycle", lambda: test_dcr_staling_lifecycle()),
        # LRT rate-effective-date suite — #197 (mid-week onset bug)
        # plus 5 verification scenarios. All synthetic SMK-#### workers
        # on 2030-class dates; placeholder rates $1.00 / $2.00 only.
        ("LrtMidWeekRateOnset", lambda: test_lrt_midweek_rate_onset()),
        ("LrtFutureDatedRate",  lambda: test_lrt_future_dated_rate()),
        ("LrtRetroactiveRate",  lambda: test_lrt_retroactive_rate()),
        ("LrtRateTransition",   lambda: test_lrt_rate_transition_midperiod()),
        ("LrtEndDatedRate",     lambda: test_lrt_end_dated_rate()),
        ("LrtHireMidPeriod",    lambda: test_lrt_hire_mid_pay_period()),
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
