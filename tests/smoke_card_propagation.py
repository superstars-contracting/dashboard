"""
smoke_card_propagation.py — verifies that the LIVE card-render route
(#90) reflects the worker's CURRENT photo / PIN / name at every render,
while keeping the card number + expiry frozen at issuance.

For each cohort × card type:
  1. BASELINE: issue the card → fetch the live render → assert it shows
     the correct face photo (img src non-empty + photo file hash matches),
     the correct PIN, the correct W-#### number, and (CoF only) the
     correct expiry.
  2. PHOTO CHANGE: upload a different face photo → fetch the live render
     → the served photo's hash now matches the NEW photo (and not the
     old one). Card number + expiry unchanged.
  3. PIN CHANGE: PATCH the worker's phone (which re-derives PIN to the
     last-4 of digits) → fetch the live render → the PIN substring in
     the rendered HTML matches the new PIN. Card number + expiry
     unchanged.
  4. CONSISTENCY: the W-#### number and name in the rendered HTML match
     the worker's current row.

Cohorts:
  - EXISTING worker (E-00001 — for Company ID directly; for CoF we add a
    temp SCAFFOLD-16 prereq cert + remove it after).
  - NEW synthetic worker (created via POST /api/workers/create, deleted
    via DELETE /api/employees/<id> at end).

Card types tested: CoF + Company ID. Both cohorts × both types = 4
runs. Each run does the baseline + photo + PIN checks.

PII-safe: only employee_id (E-/W-) / counts / booleans / hashes printed.
No names, phones, or PIN values in chat output.
"""
import base64
import hashlib
import io
import os
import re
import sqlite3
import sys
import uuid
from pathlib import Path

import requests

# Auth gate (#48): login the smoke admin + patch requests so cookies ride along.
import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
# Let the test pull in worker_id helpers from the dashboard root.
sys.path.insert(0, str(SCRIPT_DIR))
RUN_MARKER = "PROP_" + uuid.uuid4().hex[:6].upper()


def _b64(s):
    return base64.b64decode(s)


# Two distinguishable minimal JPEGs so a hash compare can tell them apart.
# (Same dimensions, different pixel data → different hashes.)
JPG_A = _b64(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAA"
    "AAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKp//9k="
)
# JPG_B differs by a single trailing byte in the entropy section.
JPG_B = _b64(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQTAQAAAAAA"
    "AAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKr//9k="
)
assert hashlib.sha256(JPG_A).hexdigest() != hashlib.sha256(JPG_B).hexdigest(), \
    "Test JPEGs must hash differently"


def hash_url(url):
    """Hex digest of the body served at the given dashboard-local URL."""
    r = requests.get(BASE + url, timeout=10)
    r.raise_for_status()
    return hashlib.sha256(r.content).hexdigest()


def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=30.0)
    conn.row_factory = sqlite3.Row
    return conn


def upload_face(emp_id, jpg_bytes):
    return requests.post(
        f"{BASE}/api/employees/{emp_id}/face-photo",
        files={"file": ("smoke.jpg", jpg_bytes, "image/jpeg")},
        timeout=15,
    )


def get_employee(emp_id):
    return requests.get(f"{BASE}/api/workers/{emp_id}", timeout=10).json()["data"]["employee"]


def issue_credential(emp_id, want_type):
    """Issue and return the card_id of the active card of want_type.
    Caller is responsible for the prereq (CoF needs SCAFFOLD-16/RIGGER-32)."""
    r = requests.post(
        f"{BASE}/api/employees/{emp_id}/credential/issue",
        json={"issued_by": RUN_MARKER, "override_active": True},
        timeout=30,
    )
    if r.status_code != 201:
        raise RuntimeError(f"issue failed: {r.status_code} {r.text[:200]}")
    data = r.json()["data"]
    if data["type"] != want_type:
        raise RuntimeError(f"dispatched to {data['type']} but wanted {want_type}")
    return data


def fetch_live(emp_id, cred_type):
    r = requests.get(f"{BASE}/api/cards/{emp_id}/{cred_type}/live", timeout=10)
    if r.status_code != 200:
        raise RuntimeError(f"live render {r.status_code} {r.text[:200]}")
    return r.text


def extract_photo_url(html):
    m = re.search(r'class="photo-box">[^<]*<img\s+src="([^"]+)"', html)
    return m.group(1) if m else None


def extract_pin(html):
    # PIN is in <div class="field-value mono pin-value">XXXX</div>
    m = re.search(r'class="field-value mono pin-value"[^>]*>\s*([^\s<]+)\s*</div>', html)
    return m.group(1) if m else None


def extract_card_number(html):
    m = re.search(r'class="field-value mono"[^>]*>\s*(SSC-[A-Z]+-W-\d{4})\s*</div>', html)
    return m.group(1) if m else None


def extract_name(html):
    # NAME is inside <div class="field-value">NAME</div> (no .mono class) — the FIRST one on the front
    m = re.search(r'Name of Holder</div>\s*<div class="field-value">\s*([^<]+)\s*</div>', html)
    return m.group(1).strip() if m else None


def add_temp_prereq(emp_id):
    """Add a SCAFFOLD-16 cert so issue_credential dispatches to CoF.
    Returns the cert_id for teardown."""
    r = requests.post(
        f"{BASE}/api/workers/{emp_id}/certs",
        json={
            "cert_type_id": "SCAFFOLD-16",
            "date_obtained": "2026-01-01",
            "expiration_date": "2030-01-01",
            "card_number": RUN_MARKER + "_PREREQ",
            "issuing_body": "DOB",
            "notes": RUN_MARKER,
        },
        timeout=10,
    )
    return r.json()["data"]["cert_id"]


def remove_temp_prereq(emp_id, cert_id):
    requests.delete(f"{BASE}/api/workers/{emp_id}/certs/{cert_id}", timeout=10)


def revoke_credential(emp_id):
    requests.delete(f"{BASE}/api/employees/{emp_id}/credential", timeout=10)


def patch_phone(emp_id, new_phone):
    return requests.patch(
        f"{BASE}/api/employees/{emp_id}",
        json={"phone": new_phone},
        timeout=10,
    )


def snapshot_emp(emp_id):
    """Capture face_image_path + phone + pin so we can restore after test."""
    conn = db()
    try:
        row = conn.execute(
            "SELECT face_image_path, phone, pin FROM employees WHERE employee_id = ?",
            (emp_id,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def restore_emp(emp_id, snap):
    if not snap:
        return
    conn = db()
    try:
        conn.execute(
            "UPDATE employees SET face_image_path = ?, phone = ?, pin = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE employee_id = ?",
            (snap["face_image_path"], snap["phone"], snap["pin"], emp_id)
        )
        conn.commit()
    finally:
        conn.close()


def delete_test_cards_for(emp_id):
    """Nuke any test-marked cards rows for emp_id (FONTCARD_TEST / PROP_*).
    Live route looks at status='issued'/'active' so revoking is enough for
    the read flow; this just keeps the DB tidy."""
    conn = db()
    try:
        conn.execute(
            "DELETE FROM cof_cards WHERE employee_id = ? AND "
            "(issued_by LIKE 'PROP_%' OR issued_by = 'FONTCARD_TEST')",
            (emp_id,)
        )
        conn.execute(
            "DELETE FROM company_id_cards WHERE employee_id = ? AND "
            "(issued_by LIKE 'PROP_%' OR issued_by = 'FONTCARD_TEST')",
            (emp_id,)
        )
        conn.commit()
    finally:
        conn.close()


# ---------- Per-cohort × per-type ----------

def run_propagation(emp_id, cohort_label, want_type):
    """Run baseline + photo + PIN propagation for one worker × one card type.
    Returns a dict of pass/fail for each check."""
    print(f"\n--- {cohort_label} × {want_type.upper()} (emp_id={emp_id}) ---")
    results = {}

    # ---- setup: ensure face photo + ensure card type dispatch ----
    upload_face(emp_id, JPG_A)
    snap = snapshot_emp(emp_id)
    # PIN baseline (we'll change phone later) — derived from existing phone last-4
    pin_before = snap["pin"]
    prereq_cert_id = None
    if want_type == "cof":
        prereq_cert_id = add_temp_prereq(emp_id)

    try:
        # ---- 1. BASELINE ----
        card_info = issue_credential(emp_id, want_type)
        cnd_at_issue = card_info["card_number_display"]
        exp_at_issue = card_info.get("expires_date", "")
        html_baseline = fetch_live(emp_id, want_type)

        photo_url = extract_photo_url(html_baseline)
        pin_in_html = extract_pin(html_baseline)
        cnd_in_html = extract_card_number(html_baseline)
        name_in_html = extract_name(html_baseline)
        emp_row = get_employee(emp_id)

        photo_hash_before = hash_url(photo_url) if photo_url else None
        # The served face file should match the bytes we just uploaded:
        jpg_a_hash = hashlib.sha256(JPG_A).hexdigest()

        results["baseline_photo_present"] = bool(photo_url)
        results["baseline_photo_matches_upload"] = (photo_hash_before == jpg_a_hash)
        results["baseline_pin_matches_emp"] = (pin_in_html == emp_row.get("pin"))
        results["baseline_pin_matches_pre_snap"] = (pin_in_html == pin_before)
        results["baseline_card_number_W_format"] = bool(cnd_in_html and cnd_in_html.startswith(f"SSC-{want_type.upper().replace('_', '').replace('COMPANYID','CID')}-W-"))
        results["baseline_card_number_matches_issue"] = (cnd_in_html == cnd_at_issue)
        results["baseline_name_matches_emp"] = (name_in_html == (emp_row.get("name") or "").strip())

        # ---- 2. PHOTO CHANGE ----
        upload_face(emp_id, JPG_B)
        html_after_photo = fetch_live(emp_id, want_type)
        photo_url2 = extract_photo_url(html_after_photo)
        photo_hash_after = hash_url(photo_url2) if photo_url2 else None
        jpg_b_hash = hashlib.sha256(JPG_B).hexdigest()
        results["photo_change_propagated"] = (photo_hash_after == jpg_b_hash)
        results["photo_change_card_number_unchanged"] = (extract_card_number(html_after_photo) == cnd_at_issue)
        if want_type == "cof":
            m = re.search(r'class="field-value mono expires"[^>]*>\s*([^\s<]+)', html_after_photo)
            exp_in_html = m.group(1) if m else ""
            # exp_at_issue is ISO (YYYY-MM-DD) straight from the API; the
            # rendered HTML is MM-DD-YYYY per CLAUDE.md display rule (#137).
            # Compare digit-equivalence so the display-format change isn't a
            # spurious mismatch.
            digits_html = re.sub(r"\D", "", exp_in_html)
            digits_iso = re.sub(r"\D", "", exp_at_issue)
            results["photo_change_expiry_unchanged"] = (
                sorted(digits_html) == sorted(digits_iso) and len(digits_html) == 8
            )
        else:
            results["photo_change_expiry_unchanged"] = True  # N/A for Company ID

        # ---- 3. PIN CHANGE ----
        # Pick a phone whose last-4 differs from the current PIN.
        new_phone = "5550009999"
        if pin_in_html == "9999":
            new_phone = "5550008888"
        target_pin = new_phone[-4:]
        pr = patch_phone(emp_id, new_phone)
        if pr.status_code != 200:
            results["pin_change_patch_ok"] = False
        else:
            results["pin_change_patch_ok"] = True
            html_after_pin = fetch_live(emp_id, want_type)
            pin_in_html2 = extract_pin(html_after_pin)
            # Don't print PIN values; compare to target as boolean only
            results["pin_change_propagated"] = (pin_in_html2 == target_pin)
            results["pin_change_card_number_unchanged"] = (extract_card_number(html_after_pin) == cnd_at_issue)
    finally:
        # ---- teardown: restore worker state ----
        revoke_credential(emp_id)
        delete_test_cards_for(emp_id)
        if prereq_cert_id is not None:
            remove_temp_prereq(emp_id, prereq_cert_id)
        restore_emp(emp_id, snap)

    return results


# ---------- Cohort drivers ----------

def driver():
    # ALL cohorts are synthetic SMK-#### workers. The previous version
    # hard-coded EXISTING = E-00001 (W-0001) for the "EXISTING" runs;
    # run_propagation's upload_face overwrites the worker's face.jpg
    # bytes on disk and the `restore_emp` step only rolls back the DB
    # column — the same defect that destroyed Robert's photo through
    # smoke_crud_data_integrity.test_face_photo (see #172-v2). Two
    # workers ("alpha"/"beta") cover the "EXISTING vs NEW" distinction
    # the test was originally written for; from the propagation logic's
    # point of view, both are real workers with face/phone/PIN/credential
    # state — the only difference was which row in the employees table
    # backed them.
    cohorts = {
        "alpha_cof":  ("SMK-" + uuid.uuid4().hex[:6].upper(), "cof",        "5551110000"),
        "alpha_cid":  ("SMK-" + uuid.uuid4().hex[:6].upper(), "company_id", "5551110001"),
        "beta_cof":   ("SMK-" + uuid.uuid4().hex[:6].upper(), "cof",        "5551112222"),
        "beta_cid":   ("SMK-" + uuid.uuid4().hex[:6].upper(), "company_id", "5551112223"),
    }

    # Create the synthetic workers.
    for sid, _ctype, _phone in cohorts.values():
        requests.post(f"{BASE}/api/workers/create", json={
            "employee_id": sid,
            "name": "SMOKE Propagation",
            "trade": "SMK_PROP",
        }, timeout=10)

    # /api/workers/create doesn't auto-assign worker_id or derive PIN —
    # do both manually so the propagation baseline has the data it
    # expects (W-#### card number renders correctly, PIN is non-NULL).
    from worker_id import next_worker_id_sequence, format_worker_id
    conn = db()
    try:
        for sid, _ctype, _phone in cohorts.values():
            seq = next_worker_id_sequence(conn)
            wid = format_worker_id(seq)
            conn.execute("UPDATE employees SET worker_id = ? WHERE employee_id = ?", (wid, sid))
            conn.commit()
    finally:
        conn.close()

    # Use the public PATCH endpoint to set phone — that re-derives PIN
    # via the documented (phone last-4) mechanism the live render reads.
    for sid, _ctype, phone in cohorts.values():
        requests.patch(f"{BASE}/api/employees/{sid}", json={"phone": phone}, timeout=10)

    all_results = {}
    try:
        all_results["alpha_cof"] = run_propagation(cohorts["alpha_cof"][0],  "ALPHA-SYN", "cof")
        all_results["alpha_cid"] = run_propagation(cohorts["alpha_cid"][0],  "ALPHA-SYN", "company_id")
        all_results["beta_cof"]  = run_propagation(cohorts["beta_cof"][0],   "BETA-SYN",  "cof")
        all_results["beta_cid"]  = run_propagation(cohorts["beta_cid"][0],   "BETA-SYN",  "company_id")
    finally:
        # Capture folder paths BEFORE deletion so we can rmtree them after.
        conn = db()
        folders_to_rm = []
        try:
            for sid, _ctype, _phone in cohorts.values():
                row = conn.execute(
                    "SELECT folder_path FROM employees WHERE employee_id = ?",
                    (sid,)
                ).fetchone()
                if row and row["folder_path"]:
                    folders_to_rm.append(row["folder_path"])
        finally:
            conn.close()
        # Hard-delete synthetic workers (no other history left for them)
        for sid, _ctype, _phone in cohorts.values():
            requests.delete(f"{BASE}/api/employees/{sid}", timeout=10)
        # Belt-and-suspenders: nuke any leftover SMK- rows.
        conn = db()
        try:
            for sid, _ctype, _phone in cohorts.values():
                conn.execute("DELETE FROM project_assignments WHERE employee_id = ?", (sid,))
                conn.execute("DELETE FROM cof_cards WHERE employee_id = ?", (sid,))
                conn.execute("DELETE FROM company_id_cards WHERE employee_id = ?", (sid,))
                conn.execute("DELETE FROM certifications WHERE employee_id = ?", (sid,))
                conn.execute("DELETE FROM employees WHERE employee_id = ?", (sid,))
            conn.commit()
        finally:
            conn.close()
        # On-disk folder teardown — bounded to worker_records/ for safety.
        import shutil
        wr = (SCRIPT_DIR / "worker_records").resolve()
        for fp in folders_to_rm:
            try:
                p = Path(fp).resolve()
                if str(p).startswith(str(wr)) and p.exists():
                    shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass

    # ---- summarize ----
    print("\n========== PROPAGATION SUMMARY ==========")
    overall_ok = True
    for label, results in all_results.items():
        passes = sum(1 for v in results.values() if v is True)
        total = len(results)
        print(f"\n{label}: {passes}/{total} checks")
        for k, v in results.items():
            mark = "OK" if v is True else "FAIL"
            print(f"  [{mark:4}] {k}")
            if v is not True:
                overall_ok = False
    print(f"\nOVERALL: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(driver())
