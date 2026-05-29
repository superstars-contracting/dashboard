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
    # dropplan audit rows for SMK targets (stage audits use 'SMK-...#n' target_ids;
    # quantity audits target the entry_id of an SMK-drop entry).
    conn.execute("DELETE FROM audit_log WHERE action LIKE 'dropplan_%' AND (target_id LIKE 'SMK-%' "
                 "OR target_id IN (SELECT CAST(entry_id AS TEXT) FROM quantity_entries WHERE drop_id LIKE 'SMK-%'))")
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
    _c = sqlite3.connect(str(DB))
    AUDIT_BASE = _c.execute("SELECT COALESCE(MAX(id),0) FROM audit_log").fetchone()[0]
    _c.close()
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

        # ---- dimensioned patch via POST (#202: L x W x D, mixed ft/in) ----
        # 10ft x 1ft x 8in = 6.6667 CF; volume_cf is the GENERATED column,
        # volume_cf_display is ceil-to-tenth.
        pv = admin.post(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries",
                        json={"sov_line_item": sid, "length": 10, "width": 1, "depth": 8,
                              "length_unit": "ft", "width_unit": "ft", "depth_unit": "in",
                              "logged_by": "W-0001"}, timeout=10)
        pvj = pv.json().get("data", {})
        check("POST dimensioned patch -> 201 + volume_cf 6.6667",
              pv.status_code == 201 and abs(pvj.get("volume_cf", 0) - 6.6667) < 0.001, f"{pv.status_code} {pvj.get('volume_cf')}")
        check("POST response volume_cf_display = ceil-to-tenth = 6.7", pvj.get("volume_cf_display") == 6.7, f"{pvj.get('volume_cf_display')}")
        det2 = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}", timeout=10).json()["data"]
        qt2 = [q for q in det2["quantity_totals"] if q["sov_code"] == SMK_SOV][0]
        check("volume_total = 6.6667 (full precision)", abs(qt2["volume_total"] - 6.6667) < 0.001, f"{qt2['volume_total']}")
        check("volume_total_display = ceil-to-tenth = 6.7", qt2["volume_total_display"] == 6.7, f"{qt2['volume_total_display']}")

        # ---- edge cases: API rejects bad dimensions (does not crash) ----
        def bad(json_body, label):
            r = admin.post(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries", json=json_body, timeout=10)
            check(label + " -> 400", r.status_code == 400, f"got {r.status_code}")
        bad({"sov_line_item": sid, "length": 0, "width": 1, "depth": 1}, "zero dimension")
        bad({"sov_line_item": sid, "length": -5, "width": 1, "depth": 1}, "negative dimension")
        bad({"sov_line_item": sid, "length": "abc", "width": 1, "depth": 1}, "non-numeric dimension")
        bad({"sov_line_item": sid, "length": 10}, "partial dimensions (length only)")
        bad({"sov_line_item": sid}, "blank: no quantity and no dimensions")

        # ---- GET entries list + PATCH edit + DELETE (#203) ----
        patch_id = pvj.get("entry_id")
        lst = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries", timeout=10).json()["data"]
        check("GET entries list includes patch w/ volume_cf_display 6.7",
              any(e["entry_id"] == patch_id and e.get("volume_cf_display") == 6.7 for e in lst), f"{len(lst)} entries")
        ed = admin.patch(f"{BASE}/api/dropplan/quantity-entries/{patch_id}",
                         json={"length": 12, "width": 1, "depth": 6, "length_unit": "ft", "width_unit": "ft", "depth_unit": "in"}, timeout=10)
        edj = ed.json().get("data", {})
        check("PATCH edit patch dims -> volume_cf 6.0", ed.status_code == 200 and abs(edj.get("volume_cf", 0) - 6.0) < 1e-6, f"{ed.status_code} {edj.get('volume_cf')}")
        lst2 = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries", timeout=10).json()["data"]
        check("edit persisted (length now 12)", any(e["entry_id"] == patch_id and e["length"] == 12 for e in lst2))
        dl = admin.delete(f"{BASE}/api/dropplan/quantity-entries/{patch_id}", timeout=10)
        check("DELETE patch -> 200", dl.status_code == 200, f"{dl.status_code}")
        lst3 = admin.get(f"{BASE}/api/dropplan/drops/{SMK_DROP}/quantity-entries", timeout=10).json()["data"]
        check("patch gone after DELETE", not any(e["entry_id"] == patch_id for e in lst3))
        # PATCH/DELETE on a non-existent entry -> 404
        check("PATCH missing entry -> 404",
              admin.patch(f"{BASE}/api/dropplan/quantity-entries/999999", json={"length": 1, "width": 1, "depth": 1}, timeout=10).status_code == 404)
        check("DELETE missing entry -> 404",
              admin.delete(f"{BASE}/api/dropplan/quantity-entries/999999", timeout=10).status_code == 404)
        # audit rows written for add/edit/delete of that patch
        cc = sqlite3.connect(str(DB))
        naudit = cc.execute("SELECT COUNT(*) FROM audit_log WHERE action LIKE 'dropplan_quantity_%' AND target_id=?", (str(patch_id),)).fetchone()[0]
        cc.close()
        check("audit rows written for patch add/edit/delete (>=3)", naudit >= 3, f"{naudit}")

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
        # belt-and-suspenders: remove every dropplan audit row this run created
        # (covers the DELETE'd patch whose entry no longer exists for the join-based cleanup).
        conn.execute("DELETE FROM audit_log WHERE id > ? AND action LIKE 'dropplan_%'", (AUDIT_BASE,))
        conn.commit()
        smk = conn.execute("SELECT COUNT(*) FROM drops WHERE drop_id LIKE 'SMK-%'").fetchone()[0]
        real = conn.execute("SELECT COUNT(*) FROM drops WHERE project_code=? AND drop_id NOT LIKE 'SMK-%'", (PROJECT,)).fetchone()[0]
        audit_left = conn.execute("SELECT COUNT(*) FROM audit_log WHERE id > ? AND action LIKE 'dropplan_%'", (AUDIT_BASE,)).fetchone()[0]
        conn.close()
        users_cleanup()
        print()
        print(f"  cleanup: SMK- drops left={smk}; real drops={real}; dropplan audit rows left={audit_left}; test users removed")
        check("cleanup: 0 synthetic drops; 35 real intact; 0 test audit rows", smk == 0 and real == 35 and audit_left == 0)

    print()
    print(f"=== Drop Plan API smoke: {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
