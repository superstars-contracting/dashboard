#!/usr/bin/env python3
"""
Generates 5 sample workers with realistic NYC construction cert combinations.
Calls the local Flask API at http://localhost:5050 — server must be running.

Run:    python create_sample_workers.py
Reset:  python create_sample_workers.py --reset
"""

import sys
import json
import time
from urllib import request as urlreq
from urllib.error import HTTPError, URLError

API = "http://localhost:5050"

SAMPLE_WORKERS = [
    {
        "name": "Jose Vargas",
        "trade": "Scaffold Rigger",
        "dob": "1985-04-12",
        "phone": "917-555-0101",
        "email": None,
        "emergency_contact_name": "Maria Vargas",
        "emergency_contact_phone": "917-555-0901",
        "emergency_contact_relation": "Spouse",
        "language": "es",
        "hire_date": "2024-03-15",
        "pin": "4218",
        "certs": [
            {"cert_type_id": "SST-WORKER",    "name": "SST Worker Card (40-hr)",         "card": "12345678", "issued": "2024-01-15", "expires": "2029-01-15"},
            {"cert_type_id": "OSHA-30",       "name": "OSHA 30-hour Construction",       "card": "OSHA-7741210",   "issued": "2023-08-22", "expires": "2028-08-22"},
            {"cert_type_id": "SCAFFOLD-16",   "name": "16-hr Suspended Scaffold User",   "card": "SC-2024-0098",   "issued": "2024-02-10", "expires": "2028-02-10"},
            {"cert_type_id": "FALL-PROT",     "name": "Fall Protection",                 "card": "FP-2024-117",    "issued": "2024-04-05", "expires": "2026-04-05"},
        ],
    },
    {
        "name": "Miguel Hernandez",
        "trade": "Mason / Pointer",
        "dob": "1979-11-03",
        "phone": "917-555-0102",
        "emergency_contact_name": "Lucia Hernandez",
        "emergency_contact_phone": "718-555-0902",
        "emergency_contact_relation": "Sister",
        "language": "es",
        "hire_date": "2023-09-01",
        "pin": "8842",
        "certs": [
            {"cert_type_id": "SST-WORKER",    "name": "SST Worker Card (40-hr)",         "card": "23456789", "issued": "2023-05-20", "expires": "2028-05-20"},
            {"cert_type_id": "OSHA-30",       "name": "OSHA 30-hour Construction",       "card": "OSHA-6629115",   "issued": "2022-11-08", "expires": "2027-11-08"},
            {"cert_type_id": "SILICA-COMP",   "name": "Silica Competent Person",         "card": "SIL-2024-211",   "issued": "2024-03-12", "expires": "2026-03-12"},
        ],
    },
    {
        "name": "Carlos Rodriguez",
        "trade": "Foreman",
        "dob": "1972-06-25",
        "phone": "917-555-0103",
        "email": "crodriguez@superstars.example",
        "emergency_contact_name": "Ana Rodriguez",
        "emergency_contact_phone": "917-555-0903",
        "emergency_contact_relation": "Wife",
        "language": "en",
        "hire_date": "2018-04-02",
        "pin": "1972",
        "certs": [
            {"cert_type_id": "SST-SUPER",     "name": "SST Supervisor Card (62-hr)",     "card": "34567890", "issued": "2023-02-14", "expires": "2028-02-14"},
            {"cert_type_id": "OSHA-30",       "name": "OSHA 30-hour Construction",       "card": "OSHA-3324488",   "issued": "2021-10-30", "expires": "2026-10-30"},
            {"cert_type_id": "SCAFFOLD-16",   "name": "16-hr Suspended Scaffold User",   "card": "SC-2023-0144",   "issued": "2023-06-18", "expires": "2027-06-18"},
            {"cert_type_id": "RIGGER-32",     "name": "32-hr Rigger",                    "card": "RG-2023-0099",   "issued": "2023-07-22", "expires": "2027-07-22"},
            {"cert_type_id": "SPECIAL-RIGGER","name": "NYC Special Rigger License",      "card": "SR-7652",        "issued": "2020-01-15", "expires": None},
            {"cert_type_id": "FIRE-S95",      "name": "NYC Fire Guard (S-95)",           "card": "S95-2023-882",   "issued": "2023-09-10", "expires": "2026-09-10"},
            {"cert_type_id": "FIRST-AID-CPR", "name": "First Aid + CPR/AED Combo",       "card": "FA-2024-441",    "issued": "2024-05-01", "expires": "2026-05-01"},
        ],
    },
    {
        "name": "Pedro Castillo",
        "trade": "Laborer",
        "dob": "1990-02-18",
        "phone": "646-555-0104",
        "emergency_contact_name": "Rosa Castillo",
        "emergency_contact_phone": "646-555-0904",
        "emergency_contact_relation": "Mother",
        "language": "es",
        "hire_date": "2025-01-08",
        "pin": "6610",
        "certs": [
            # NOTE: deliberately missing SCAFFOLD-16 to test "ineligible for CoF" logic
            {"cert_type_id": "SST-TRAINEE",   "name": "SST Temporary Trainee Card",      "card": "TRAIN-12384", "issued": "2025-01-05", "expires": "2025-07-05"},  # near expiry
            {"cert_type_id": "OSHA-10",       "name": "OSHA 10-hour Construction",       "card": "OSHA-9981200",   "issued": "2024-12-15", "expires": "2029-12-15"},
        ],
    },
    {
        "name": "Anton Kowalski",
        "trade": "Rope Access Technician",
        "dob": "1988-09-07",
        "phone": "212-555-0105",
        "email": "akowalski@superstars.example",
        "emergency_contact_name": "Magda Kowalski",
        "emergency_contact_phone": "212-555-0905",
        "emergency_contact_relation": "Brother",
        "language": "pl",
        "hire_date": "2022-06-15",
        "pin": "8807",
        "certs": [
            {"cert_type_id": "SST-WORKER",    "name": "SST Worker Card (40-hr)",         "card": "45678901", "issued": "2022-04-10", "expires": "2027-04-10"},
            {"cert_type_id": "OSHA-30",       "name": "OSHA 30-hour Construction",       "card": "OSHA-5512204",   "issued": "2022-03-20", "expires": "2027-03-20"},
            {"cert_type_id": "SPRAT-L2",      "name": "SPRAT Level 2 Rope Access",       "card": "SPRAT-L2-3344",  "issued": "2024-01-22", "expires": "2027-01-22"},
            {"cert_type_id": "FALL-PROT",     "name": "Fall Protection",                 "card": "FP-2024-118",    "issued": "2024-04-05", "expires": "2025-06-15"},  # expiring SOON for test
            {"cert_type_id": "SCAFFOLD-16",   "name": "16-hr Suspended Scaffold User",   "card": "SC-2024-0125",   "issued": "2024-05-30", "expires": "2028-05-30"},
        ],
    },
]


def post_json(path, payload):
    req = urlreq.Request(
        API + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlreq.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        # Read the actual error body — server returns JSON with details
        body = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body)
            return {"error": f"HTTP {e.code} — {parsed.get('error', body[:200])}"}
        except Exception:
            return {"error": f"HTTP {e.code} — {body[:200]}"}
    except URLError as e:
        return {"error": f"network: {e.reason}"}


def delete_url(path):
    req = urlreq.Request(API + path, method="DELETE")
    try:
        with urlreq.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def get_json(path):
    with urlreq.urlopen(API + path, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def reset_all_sample_workers():
    """Delete the sample workers we created (by name match) and their data."""
    print("Resetting sample workers (by name match)...")
    try:
        existing = get_json("/api/workers/intake-summary").get("data", [])
    except Exception as e:
        print(f"Could not reach server: {e}")
        return
    sample_names = {w["name"] for w in SAMPLE_WORKERS}
    removed = 0
    for emp in existing:
        if emp.get("name") in sample_names:
            # Delete via direct DB call would be cleaner, but we don't have a DELETE worker endpoint yet.
            # For now we just blank their data. To do a full delete, use the reset_sample_workers.py companion.
            print(f"  Would delete: {emp['name']} ({emp['employee_id']}) — manual DB delete needed")
            removed += 1
    print(f"Found {removed} sample workers in system. Use SQLite to drop them manually:")
    print(f"  python -c \"import sqlite3;c=sqlite3.connect('superstars.db');"
          f"c.execute('DELETE FROM certifications WHERE employee_id IN "
          f"(SELECT employee_id FROM employees WHERE name IN ({','.join(['?']*len(sample_names))}))', "
          f"{list(sample_names)});c.commit()\"")


def main():
    if "--reset" in sys.argv:
        reset_all_sample_workers()
        return 0

    print("\n=== CREATING SAMPLE WORKERS ===\n")
    print(f"Hitting API: {API}")
    print("Make sure the Flask server is running (run_server.bat).\n")

    try:
        # Probe health
        get_json("/api/health")
    except Exception as e:
        print(f"ERROR: server not reachable at {API}. Is the server running?")
        print(f"  ({e})")
        return 1

    # --- Pre-flight schema check ---
    print("--- Pre-flight schema check ---")
    import sqlite3
    from pathlib import Path
    DB = Path(__file__).resolve().parent / "superstars.db"
    if not DB.exists():
        print(f"  ✗ Database not found at {DB}")
        return 1
    conn = sqlite3.connect(str(DB))
    issues = []
    # Check employees columns
    cols = [r[1] for r in conn.execute("PRAGMA table_info(employees)").fetchall()]
    needed = ['dob', 'phone', 'email', 'emergency_contact_name', 'emergency_contact_phone',
              'emergency_contact_relation', 'language', 'hire_date', 'pin', 'folder_path']
    missing_emp = [c for c in needed if c not in cols]
    if missing_emp:
        issues.append(f"employees table missing columns: {', '.join(missing_emp)} — run apply_worker_intake_schema.py")
    # Check certifications columns
    cols = [r[1] for r in conn.execute("PRAGMA table_info(certifications)").fetchall()]
    if 'card_number' not in cols:
        issues.append("certifications table missing card_number column — run apply_worker_intake_schema.py")
    # Check worker_documents exists
    try:
        conn.execute("SELECT 1 FROM worker_documents LIMIT 1")
    except sqlite3.OperationalError:
        issues.append("worker_documents table missing — run apply_worker_intake_schema.py")
    # Check project_assignments exists
    try:
        conn.execute("SELECT 1 FROM project_assignments LIMIT 1")
    except sqlite3.OperationalError:
        issues.append("project_assignments table missing — run apply_assignments_schema.py")
    # Check cert_types is populated
    n = conn.execute("SELECT COUNT(*) FROM cert_types").fetchone()[0]
    if n < 10:
        issues.append(f"cert_types has only {n} entries — run apply_worker_intake_schema.py to seed the library")
    conn.close()

    if issues:
        print("\n  Found schema problems — fix these first:")
        for i in issues:
            print(f"    ✗ {i}")
        print("\n  After fixing, RESTART the server, then re-run this script.")
        return 1
    print("  ✓ All schema checks passed.\n")

    for w in SAMPLE_WORKERS:
        try:
            payload = {k: w[k] for k in w if k != "certs"}
            resp = post_json("/api/workers/create", payload)
            if "error" in resp:
                print(f"  ✗ {w['name']}: {resp['error']}")
                continue
            employee_id = resp["data"]["employee_id"]
            folder = resp["data"]["folder_path"]
            print(f"  ✓ {w['name']:<24} → {employee_id}  folder: {folder.split('worker_records')[-1]}")

            # Add certs
            for c in w["certs"]:
                cert_payload = {
                    "cert_type_id": c["cert_type_id"],
                    "cert_type_name": c["name"],
                    "card_number": c["card"],
                    "date_obtained": c["issued"],
                    "expiration_date": c["expires"],
                }
                cresp = post_json(f"/api/workers/{employee_id}/certs", cert_payload)
                if "error" in cresp:
                    print(f"      ✗ cert {c['cert_type_id']}: {cresp['error']}")
                else:
                    exp = c["expires"] or "no expiry"
                    print(f"      ✓ {c['cert_type_id']:<18} card {c['card']:<22} expires {exp}")
            time.sleep(0.2)
        except Exception as e:
            print(f"  ✗ {w['name']}: {e}")

    print("\n=== DONE ===")
    print("Open http://localhost:5050/ to see the Company Console with your sample workforce.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
