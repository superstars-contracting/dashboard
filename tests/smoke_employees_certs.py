"""
smoke_employees_certs.py — Employees & Certifications crafted card view (#223).

Verifies the crew-compliance endpoint (readiness hero + per-worker compliance
COMPUTED from cert expiry, LOCAL dates, NO *_path) and the gated face-photo
route, against the running server. OPERATOR-LIVE SAFE: a synthetic project
SMK-EC-SMOKE + synthetic workers (E-996xx / W-96xx) with FAKE names + synthetic
certs + one synthetic headshot; cleanup is SCOPED to those ids + the synthetic
worker_records photo dir. PII: never prints real names/photos/paths — synthetic
fake data only.

Covers: hero counts + pct computed correctly (ready/expiring/expired); per-worker
compliance status; certs carry NO scan_path and NO *_path anywhere in the JSON;
has_photo boolean; face-photo route serves the synthetic image (gated, no-store)
/ 404 when none / 401 unauthenticated; crew-compliance 401 unauthenticated;
~80-worker scale + timing; scoped cleanup -> zero residue.
"""
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

import _smoke_auth  # noqa: E402
import db_layer  # noqa: E402  # #260 — route DB access through the env-driven layer (SSC_DB_URL)
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
PROJ = "SMK-EC-SMOKE"
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    c = db_layer.connect()
    c.row_factory = sqlite3.Row
    return c


def crew():
    return requests.get(f"{BASE}/api/projects/{PROJ}/crew-compliance", timeout=20).json()


def find(ws, wid):
    return next((w for w in ws if w["worker_id"] == wid), None)


def seed():
    """Synthetic project + 4 controlled workers (FAKE names) + 1 synthetic photo."""
    conn = db()
    conn.execute("INSERT OR IGNORE INTO projects (project_code,name,status) VALUES (?,?,?)",
                 (PROJ, "SMK EC Smoke", "active"))
    d = SCRIPT_DIR / "worker_records" / "E-99601_SMK-EC"
    d.mkdir(parents=True, exist_ok=True)
    fp = d / "face.jpg"
    try:
        from PIL import Image
        Image.new("RGB", (40, 40), (70, 110, 160)).save(str(fp), "JPEG")
    except Exception:
        fp.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF synthetic-test\xff\xd9")
    for ctid, name in [("SMK-ECT-Valid", "SMK Valid"), ("SMK-ECT-Exp30", "SMK SST Super"),
                       ("SMK-ECT-Expired", "SMK Expired"), ("SMK-ECT-Extra", "SMK OSHA 30")]:
        conn.execute("INSERT OR IGNORE INTO cert_types (cert_type_id,name) VALUES (?,?)", (ctid, name))
    t = date.today()

    def emp(eid, wid, name, trade, photo=None):
        conn.execute("DELETE FROM employees WHERE employee_id=?", (eid,))
        conn.execute("INSERT INTO employees (employee_id,worker_id,name,trade,face_image_path,intake_status) "
                     "VALUES (?,?,?,?,?,?)", (eid, wid, name, trade, photo, "complete"))
        conn.execute("DELETE FROM project_assignments WHERE employee_id=?", (eid,))
        conn.execute("INSERT INTO project_assignments (employee_id,project_code,status) VALUES (?,?,?)",
                     (eid, PROJ, "active"))
        conn.execute("DELETE FROM certifications WHERE employee_id=?", (eid,))

    def cert(eid, ctid, exp):
        conn.execute("INSERT INTO certifications (employee_id,cert_type_id,date_obtained,expiration_date,status) "
                     "VALUES (?,?,?,?,?)", (eid, ctid, (t - timedelta(days=200)).isoformat(), exp, "active"))

    emp("E-99601", "W-9601", "SMK Ready Photo", "Mechanic", str(fp.resolve()))
    cert("E-99601", "SMK-ECT-Valid", (t + timedelta(days=180)).isoformat())
    emp("E-99602", "W-9602", "SMK Expiring Soon", "Rope Access")
    cert("E-99602", "SMK-ECT-Exp30", (t + timedelta(days=10)).isoformat())
    cert("E-99602", "SMK-ECT-Extra", (t + timedelta(days=365)).isoformat())
    emp("E-99603", "W-9603", "SMK Expired Cert", "Laborer")
    cert("E-99603", "SMK-ECT-Expired", (t - timedelta(days=5)).isoformat())
    emp("E-99604", "W-9604", "SMK No Certs", "Superintendent")  # no certs -> ready
    conn.commit()
    conn.close()


def _scale(n):
    conn = db()
    conn.execute("INSERT OR IGNORE INTO cert_types (cert_type_id,name) VALUES ('SMK-ECT-Valid','SMK Valid')")
    t = date.today()
    for i in range(n):
        eid = f"E-996{500 + i}"
        wid = f"W-96{500 + i}"
        conn.execute("DELETE FROM employees WHERE employee_id=?", (eid,))
        conn.execute("INSERT INTO employees (employee_id,worker_id,name,trade,intake_status) "
                     "VALUES (?,?,?,?,?)", (eid, wid, f"SMK Scale {i}", "Laborer", "complete"))
        conn.execute("DELETE FROM project_assignments WHERE employee_id=?", (eid,))
        conn.execute("INSERT INTO project_assignments (employee_id,project_code,status) VALUES (?,?,?)",
                     (eid, PROJ, "active"))
        conn.execute("INSERT INTO certifications (employee_id,cert_type_id,date_obtained,expiration_date,status) "
                     "VALUES (?,?,?,?,?)", (eid, "SMK-ECT-Valid", t.isoformat(),
                                            (t + timedelta(days=200)).isoformat(), "active"))
    conn.commit()
    conn.close()
    t0 = time.perf_counter()
    body = crew()
    ms = (time.perf_counter() - t0) * 1000
    ok("scale_endpoint", body["data"]["hero"]["total"] >= n and ms < 3000,
       f"{body['data']['hero']['total']} workers in {ms:.0f}ms")


def cleanup():
    conn = db()
    conn.execute("DELETE FROM certifications WHERE employee_id LIKE 'E-996%'")
    conn.execute("DELETE FROM project_assignments WHERE project_code=? OR employee_id LIKE 'E-996%'", (PROJ,))
    conn.execute("DELETE FROM employees WHERE employee_id LIKE 'E-996%' AND (name LIKE 'SMK %' OR worker_id LIKE 'W-96%')")
    conn.execute("DELETE FROM cert_types WHERE cert_type_id LIKE 'SMK-ECT-%'")
    conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
    conn.commit()
    res_e = conn.execute("SELECT COUNT(*) FROM employees WHERE employee_id LIKE 'E-996%'").fetchone()[0]
    res_a = conn.execute("SELECT COUNT(*) FROM project_assignments WHERE project_code=?", (PROJ,)).fetchone()[0]
    res_c = conn.execute("SELECT COUNT(*) FROM certifications WHERE employee_id LIKE 'E-996%'").fetchone()[0]
    conn.close()
    pd = SCRIPT_DIR / "worker_records" / "E-99601_SMK-EC"
    if pd.exists():
        shutil.rmtree(pd, ignore_errors=True)
    return res_e, res_a, res_c


def main():
    print("== #223 Employees & Certifications smoke ==")
    conn = db()
    base_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    base_cert = conn.execute("SELECT COUNT(*) FROM certifications").fetchone()[0]
    conn.close()

    seed()

    # ---- 1) crew-compliance: hero + per-worker compliance (computed from expiry) ----
    r = requests.get(f"{BASE}/api/projects/{PROJ}/crew-compliance", timeout=20)
    ok("crew_200", r.status_code == 200, f"HTTP {r.status_code}")
    ok("crew_no_store", "no-store" in r.headers.get("Cache-Control", ""))
    body = r.json()
    txt = r.text
    hero = body["data"]["hero"]
    ws = body["data"]["workers"]
    ok("hero_total_4", hero["total"] == 4, f"{hero}")
    ok("hero_ready_2", hero["ready"] == 2)          # W-9601 + W-9604 (no certs)
    ok("hero_expiring_1", hero["expiring"] == 1)
    ok("hero_expired_1", hero["expired"] == 1)
    ok("hero_pct_50", hero["pct_ready"] == 50)
    w1 = find(ws, "W-9601")
    ok("worker_ready_photo", bool(w1) and w1["compliance"] == "ready" and w1["has_photo"] is True)
    w2 = find(ws, "W-9602")
    ok("worker_expiring", bool(w2) and w2["compliance"] == "expiring" and w2["cert_expiring"] == 1)
    w3 = find(ws, "W-9603")
    ok("worker_expired", bool(w3) and w3["compliance"] == "expired" and w3["cert_expired"] == 1)
    w4 = find(ws, "W-9604")
    ok("worker_nocerts_ready", bool(w4) and w4["compliance"] == "ready" and w4["cert_total"] == 0)

    # ---- 2) PII: NO *_path anywhere (certs carry no scan_path) ----
    cert_keys = set()
    for w in ws:
        for c in w["certs"]:
            cert_keys |= set(c.keys())
    ok("certs_no_path_key", not any("path" in k.lower() for k in cert_keys), str(sorted(cert_keys)))
    worker_keys = set()
    for w in ws:
        worker_keys |= set(w.keys())
    ok("worker_no_path_key", not any("path" in k.lower() for k in worker_keys), str(sorted(worker_keys)))
    ok("no_path_substring", "worker_records" not in txt.lower() and "face_image" not in txt.lower())

    # ---- 3) face-photo route: gated, no-store, 404, 401 ----
    pa = requests.get(f"{BASE}/api/employees/E-99601/face-photo", timeout=10)
    ok("photo_serves", pa.status_code == 200 and pa.headers.get("Content-Type", "").startswith("image/")
       and "no-store" in pa.headers.get("Cache-Control", ""), f"HTTP {pa.status_code}")
    ok("photo_404_no_photo", requests.get(f"{BASE}/api/employees/E-99602/face-photo", timeout=10).status_code == 404)
    ok("photo_401_unauth", requests.Session().get(f"{BASE}/api/employees/E-99601/face-photo", timeout=10).status_code == 401)
    ok("crew_401_unauth", requests.Session().get(f"{BASE}/api/projects/{PROJ}/crew-compliance", timeout=10).status_code == 401)

    # ---- 4) scale (~80 synthetic workers) ----
    _scale(80)

    # ---- cleanup (scoped to synthetic ids) ----
    res_e, res_a, res_c = cleanup()
    conn = db()
    now_emp = conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0]
    now_cert = conn.execute("SELECT COUNT(*) FROM certifications").fetchone()[0]
    conn.close()
    ok("cleanup_zero_residue", res_e == 0 and res_a == 0 and res_c == 0,
       f"emp={res_e} assign={res_a} cert={res_c}")
    # scoped deletes only ever target E-996%/SMK rows; report real-count delta (operator-live tolerant)
    print(f"    real employees {base_emp}->{now_emp}, certs {base_cert}->{now_cert} "
          f"(delta, if any, = concurrent operator activity — not this test)")

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
