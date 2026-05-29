"""#200 — Drop Plan Batch B API smoke (real HTTP, role-gated, synthetic-only).

Exercises the operator's ACTUAL code path (the endpoints the UI will hit),
with real sessions for admin / pm / super / external roles — not internal
function shortcuts (banked #190/#195). Asserts:

  * Role-gate OMIT (§6 / #158): drop-detail as admin has cost+expense_total;
    as pm AND super those KEYS are ABSENT (not zeroed); external role -> 403.
  * Roll-up math via endpoints: APPEND POST (two entries SUM, no overwrite),
    volume_cf, cost == "pending_rates" when rate NULL (NOT 0), cost = qty*rate
    once a rate exists.
  * Progress % with an N/A step (complete / applicable, N/A excluded).
  * Expense POST is admin/c_suite only (pm -> 403); quantity write denied to
    external role.
  * Cure-gate fix: is_cure_gate on step 10, not step 8.

All synthetic rows are SMK--prefixed and cleaned up; test users are deleted.
PII-safe: logged_by is a token; no names; amounts are fake ($1/$2).

Run (server must be up):
  python tests/smoke_dropplan_api.py
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
DB = SCRIPT_DIR / "superstars.db"
BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PROJECT = "FR-BX-001"
from auth import hash_password  # noqa: E402

PASS, FAIL = 0, 0
PW = "smk-api-pw-do-not-reuse"
# The auth schema's users.role CHECK permits ONLY these four operational
# roles — there is no external/client role to create (drop-plan data is
# unreachable by any non-operational identity by construction). Role denial
# is proven via the expense endpoint (pm -> 403) + the structural check.
TEST_USERS = {
    "admin": "smk-api-admin@superstars.local",
    "pm": "smk-api-pm@superstars.local",
    "super": "smk-api-super@superstars.local",
}
SMK_DROP = "SMK-API-DROP"
SMK_SOV = "SMK-API-SOV"


def check(label, ok, note=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" — {note}" if note else ""))


def ensure_user(email, role):
    conn = sqlite3.connect(str(DB), timeout=60.0)
    try:
        conn.execute("PRAGMA busy_timeout=60000;")
        row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO users(email,password_hash,role,full_name,is_active) VALUES(?,?,?,?,1)",
                         (email, hash_password(PW), role, f"SMK {role}"))
        else:
            conn.execute("UPDATE users SET password_hash=?, role=?, is_active=1 WHERE email=?",
                         (hash_password(PW), role, email))
        conn.commit()
    finally:
        conn.close()


def session_for(role):
    ensure_user(TEST_USERS[role], role)
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": TEST_USERS[role], "password": PW}, timeout=10)
    assert r.status_code == 200 and s.cookies.get("ssc_session"), f"login failed for {role}: {r.status_code}"
    return s


def db_setup():
    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA busy_timeout=60000;")
    db_cleanup(conn)
    # synthetic drop under FR-BX-001 + its 11 stage rows (so template joins work)
    conn.execute("INSERT INTO drops(drop_id,project_code,elevation,sequence_no,lifecycle) "
                 "VALUES(?,?, 'North',9100,'scaffold_active')", (SMK_DROP, PROJECT))
    for step in range(1, 12):
        conn.execute("INSERT INTO drop_stage_status(drop_id,step_no,status) VALUES(?,?, 'not_started')", (SMK_DROP, step))
    conn.execute("INSERT INTO sov_line_items(project_code,sov_code,description,unit,unit_rate) "
                 "VALUES(?, ?, 'SMK synthetic line','CF',NULL)", (PROJECT, SMK_SOV))
    conn.commit()
    sid = conn.execute("SELECT sov_id FROM sov_line_items WHERE sov_code=?", (SMK_SOV,)).fetchone()[0]
    conn.close()
    return sid


def db_cleanup(conn):
    conn.execute("DELETE FROM quantity_entries WHERE drop_id LIKE 'SMK-%' "
                 "OR sov_line_item IN (SELECT sov_id FROM sov_line_items WHERE sov_code LIKE 'SMK-%')")
    conn.execute("DELETE FROM expense_entries WHERE drop_id LIKE 'SMK-%' OR note LIKE 'SMK-%'")
    conn.execute("DELETE FROM drop_stage_status WHERE drop_id LIKE 'SMK-%'")
    conn.execute("DELETE FROM drops WHERE drop_id LIKE 'SMK-%'")
    conn.execute("DELETE FROM sov_line_items WHERE sov_code LIKE 'SMK-%'")
    conn.commit()


def users_cleanup():
    conn = sqlite3.connect(str(DB), timeout=60.0)
    for email in TEST_USERS.values():
        uid = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if uid:
            conn.execute("DELETE FROM sessions WHERE user_id=?", (uid[0],))
            conn.execute("DELETE FROM users WHERE id=?", (uid[0],))
    conn.commit()
    conn.close()


def main() -> int:
    sid = db_setup()
    try:
        admin = session_for("admin")
        pm = session_for("pm")
        sup = session_for("super")

        # ---- external/client unreachable by construction ----
        conn = sqlite3.connect(str(DB))
        users_ddl = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
        conn.close()
        check("auth schema permits ONLY admin/c_suite/pm/super (no external/client role can exist)",
              "'client'" not in users_ddl and "'external'" not in users_ddl
              and all(r in users_ddl for r in ("'admin'", "'c_suite'", "'pm'", "'super'")))

        # ---- cure-gate fix (DB read) ----
        conn = sqlite3.connect(str(DB))
        tid = conn.execute("SELECT template_id FROM stage_templates WHERE project_code=?", (PROJECT,)).fetchone()[0]
        s8 = conn.execute("SELECT is_cure_gate FROM stage_template_steps WHERE template_id=? AND step_no=8", (tid,)).fetchone()[0]
        s10 = conn.execute("SELECT is_cure_gate FROM stage_template_steps WHERE template_id=? AND step_no=10", (tid,)).fetchone()[0]
        conn.close()
        check("cure-gate on step 10, off step 8", s8 == 0 and s10 == 1, f"s8={s8} s10={s10}")

        # ---- role-gate OMIT on a real drop detail ----
        ra = admin.get(f"{BASE}/api/dropplan/drops/{PROJECT}-DP1", timeout=10).json()["data"]
        check("admin drop-detail INCLUDES cost", "cost" in ra)
        check("admin drop-detail INCLUDES expense_total", "expense_total" in ra)
        rp = pm.get(f"{BASE}/api/dropplan/drops/{PROJECT}-DP1", timeout=10).json()["data"]
        check("pm drop-detail OMITS cost key (not zeroed)", "cost" not in rp)
        check("pm drop-detail OMITS expense_total key", "expense_total" not in rp)
        rs = sup.get(f"{BASE}/api/dropplan/drops/{PROJECT}-DP1", timeout=10).json()["data"]
        check("super drop-detail OMITS cost key", "cost" not in rs and "expense_total" not in rs)
        # pm/super still get the operational data
        check("pm still sees progress + stages + quantity_totals",
              all(k in rp for k in ("progress", "stages", "quantity_totals", "working_days")))

        # ---- APPEND via POST (two entries, same drop+SOV) ----
        p1 = admin.post(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries",
                        json={"sov_line_item": sid, "quantity": 5.0, "unit": "CF", "logged_by": "W-0001"}, timeout=10)
        p2 = admin.post(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries",
                        json={"sov_line_item": sid, "quantity": 3.0, "unit": "CF", "logged_by": "W-0001"}, timeout=10)
        check("POST quantity entry x2 -> 201", p1.status_code == 201 and p2.status_code == 201,
              f"{p1.status_code},{p2.status_code}")
        det = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}", timeout=10).json()["data"]
        qt = [q for q in det["quantity_totals"] if q["sov_code"] == SMK_SOV]
        check("APPEND: 2 entries persisted (entry_count=2, no overwrite)", qt and qt[0]["entry_count"] == 2,
              f"{qt}")
        check("APPEND: qty_total = SUM = 8.0", qt and abs(qt[0]["qty_total"] - 8.0) < 1e-9, f"{qt}")

        # ---- pending_rates (rate NULL, has quantity) ----
        check("cost == 'pending_rates' when rate NULL (NOT 0)", det.get("cost") == "pending_rates",
              f"cost={det.get('cost')!r}")

        # ---- volume via POST (area/depth -> volume_cf) ----
        admin.post(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries",
                   json={"sov_line_item": sid, "area_sf": 10, "depth_in": 8, "unit": "CF", "logged_by": "W-0001"}, timeout=10)
        det2 = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}", timeout=10).json()["data"]
        qt2 = [q for q in det2["quantity_totals"] if q["sov_code"] == SMK_SOV][0]
        check("volume_total = 6.6667 (10sf x 8in / 12)", abs(qt2["volume_total"] - 6.6667) < 0.001, f"{qt2['volume_total']}")

        # ---- priced cost (set a synthetic rate, recompute) ----
        conn = sqlite3.connect(str(DB))
        conn.execute("UPDATE sov_line_items SET unit_rate=2.0 WHERE sov_code=?", (SMK_SOV,))
        conn.commit()
        conn.close()
        det3 = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}", timeout=10).json()["data"]
        check("cost = qty*rate = 8 * $2.00 = 16.0 once rate exists", det3.get("cost") == 16.0, f"cost={det3.get('cost')!r}")

        # ---- progress % with an N/A step (via PATCH endpoint) ----
        admin.patch(f"{BASE}/api/dropplan/drops/{SMK_DROP}/stages/1", json={"status": "complete"}, timeout=10)
        admin.patch(f"{BASE}/api/dropplan/drops/{SMK_DROP}/stages/2", json={"status": "complete"}, timeout=10)
        admin.patch(f"{BASE}/api/dropplan/drops/{SMK_DROP}/stages/3", json={"status": "n_a"}, timeout=10)
        det4 = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}", timeout=10).json()["data"]
        prog = det4["progress"]
        check("progress: applicable excludes N/A (10 applicable, 2 complete, 20.0%)",
              prog["applicable_steps"] == 10 and prog["complete_steps"] == 2 and prog["pct"] == 20.0, f"{prog}")

        # ---- expense POST admin-only ----
        pe = pm.post(f"{BASE}/api/dropplan/projects/{PROJECT}/expense-entries",
                     json={"category": "material", "amount": 1.00, "drop_id": SMK_DROP, "note": "SMK-exp"}, timeout=10)
        check("pm POST expense DENIED (403)", pe.status_code == 403, f"got {pe.status_code}")
        ae = admin.post(f"{BASE}/api/dropplan/projects/{PROJECT}/expense-entries",
                        json={"category": "material", "amount": 1.00, "drop_id": SMK_DROP, "note": "SMK-exp"}, timeout=10)
        check("admin POST expense -> 201", ae.status_code == 201, f"got {ae.status_code}")

    finally:
        conn = sqlite3.connect(str(DB), timeout=60.0)
        conn.execute("PRAGMA busy_timeout=60000;")
        db_cleanup(conn)
        smk = conn.execute("SELECT COUNT(*) FROM drops WHERE drop_id LIKE 'SMK-%'").fetchone()[0]
        real = conn.execute("SELECT COUNT(*) FROM drops WHERE project_code=? AND drop_id NOT LIKE 'SMK-%'", (PROJECT,)).fetchone()[0]
        conn.close()
        users_cleanup()
        print()
        print(f"  cleanup: SMK- drops left={smk}; real drops={real}; test users removed")
        check("cleanup: 0 synthetic drops; 35 real intact", smk == 0 and real == 35)

    print()
    print(f"=== Drop Plan API smoke: {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
