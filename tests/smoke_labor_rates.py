"""
smoke_labor_rates.py — Labor Rates redesign (#220).

Approval-gated rate flow + Active/Inactive + history + PM scoped-queue gating +
~200 stress, against the running server. OPERATOR-LIVE SAFE: synthetic workers
are W-9xxx (real workers are W-1xxx/W-2xxx); cleanup is SCOPED to worker_id LIKE
'W-9%'. Comp-data discipline: FAKE rates only ($10/$12 etc.); the 14 REAL rates
are verified intact by a MATCH query (never printing a real value).

Covers: migration intact (14 real, all active, initial history, == worker_rates);
submit -> pending (current unchanged, pending KPI++); PM approve -> applies +
history; PM reject -> holds; Active/Inactive split + Reactivate (history kept);
role-stamped history (no names); gating (admin submit; PM only the queue, roster
403; super 403); stress 200 + scoped cleanup (zero residue, 14 real untouched).
"""
import os
import sqlite3
import sys
import time
from datetime import date
from pathlib import Path

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
sys.path.insert(0, str(SCRIPT_DIR))
from auth import hash_password  # noqa: E402

PM_EMAIL = "smk-pm-lrt@superstars.local"
SUPER_EMAIL = "smk-super-lrt@superstars.local"
PW = "smk-lrt-pw"
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    c = sqlite3.connect(str(DB_PATH), timeout=60.0)
    c.row_factory = sqlite3.Row
    return c


def make_user(email, role):
    conn = db()
    if not conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        conn.execute("INSERT INTO users (email,password_hash,role,full_name,is_active) VALUES (?,?,?,?,1)",
                     (email, hash_password(PW), role, "SMK " + role))
    else:
        conn.execute("UPDATE users SET role=?,password_hash=?,is_active=1 WHERE email=?",
                     (role, hash_password(PW), email))
    conn.commit(); conn.close()
    s = requests.Session()
    s.post(f"{BASE}/api/auth/login", json={"email": email, "password": PW}, timeout=10)
    return s


def add_worker(wid, trade, rate, eff="2026-01-05", status="active"):
    return requests.post(f"{BASE}/api/labor-rates/state", json={
        "worker_id": wid, "trade": trade, "rate": rate, "effective_date": eff, "status": status}, timeout=15)


def roster():
    return requests.get(f"{BASE}/api/labor-rates/roster", timeout=20).json()


def find(rost, section, wid):
    return next((w for w in rost["data"][section] if w["worker_id"] == wid), None)


def main():
    print("== #220 Labor Rates smoke ==")

    # ---- 1) MIGRATION intact (no real values printed) ----
    conn = db()
    state_n = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id NOT LIKE 'W-9%'").fetchone()[0]
    active_n = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id NOT LIKE 'W-9%' AND status='active'").fetchone()[0]
    init_n = conn.execute("SELECT COUNT(*) FROM labor_rate_change WHERE is_initial=1 AND worker_id NOT LIKE 'W-9%'").fetchone()[0]
    mism = conn.execute("""SELECT COUNT(*) FROM labor_worker_state s JOIN employees e ON e.worker_id=s.worker_id
        JOIN worker_rates wr ON wr.employee_id=e.employee_id AND wr.effective_to IS NULL
        WHERE s.worker_id NOT LIKE 'W-9%' AND ABS(s.current_rate - wr.hourly_rate) > 0.005""").fetchone()[0]
    conn.close()
    ok("migration_14_state", state_n == 14, f"{state_n}")
    ok("migration_all_active", active_n == 14)
    ok("migration_initial_history", init_n == 14)
    ok("migration_rates_match_worker_rates", mism == 0, "state.current_rate == worker_rates (no values shown)")

    # ---- 2) SUBMIT -> pending (current unchanged, KPI++) ----
    add_worker("W-9001", "Laborer", 10.00)
    add_worker("W-9002", "Mechanic", 20.00)
    before = roster()
    pend_before = before["kpis"]["pending"]
    r = requests.post(f"{BASE}/api/labor-rates/changes", json={
        "worker_id": "W-9001", "new_rate": 12.00, "effective_date": "2026-06-01"}, timeout=15)
    ok("submit_201", r.status_code == 201, f"HTTP {r.status_code}")
    change_id = r.json()["data"]["change_id"]
    after = roster()
    w1 = find(after, "active", "W-9001")
    ok("submit_pending_flag", w1 and w1["has_pending"] and w1.get("pending_new_rate") == 12.00)
    ok("submit_current_unchanged", w1 and w1["current_rate"] == 10.00, f"current={w1['current_rate'] if w1 else None}")
    ok("submit_pending_kpi_incr", after["kpis"]["pending"] == pend_before + 1)

    # ---- 7a) GATING: PM session ----
    pm = make_user(PM_EMAIL, "pm")
    sup = make_user(SUPER_EMAIL, "super")
    pm_pending = pm.get(f"{BASE}/api/labor-rates/pending", timeout=15)
    ok("pm_sees_pending_queue", pm_pending.status_code == 200 and any(p["id"] == change_id for p in pm_pending.json()["data"]))
    ok("pm_roster_403", pm.get(f"{BASE}/api/labor-rates/roster", timeout=10).status_code == 403)
    ok("pm_history_403", pm.get(f"{BASE}/api/labor-rates/history/W-9001", timeout=10).status_code == 403)
    ok("pm_submit_403", pm.post(f"{BASE}/api/labor-rates/changes", json={"worker_id": "W-9001", "new_rate": 99, "effective_date": "2026-06-01"}, timeout=10).status_code == 403)
    ok("super_pending_403", sup.get(f"{BASE}/api/labor-rates/pending", timeout=10).status_code == 403)
    ok("super_roster_403", sup.get(f"{BASE}/api/labor-rates/roster", timeout=10).status_code == 403)

    # ---- 3) PM APPROVES -> applies + history; pending clears ----
    ap = pm.post(f"{BASE}/api/labor-rates/changes/{change_id}/approve", timeout=15)
    ok("pm_approve_200", ap.status_code == 200, f"HTTP {ap.status_code}")
    after2 = roster()
    w1b = find(after2, "active", "W-9001")
    ok("approve_applies_rate", w1b and w1b["current_rate"] == 12.00 and not w1b["has_pending"], f"current={w1b['current_rate'] if w1b else None}")
    ok("approve_effective_applied", w1b and w1b["effective_date"] == "2026-06-01")
    hist = requests.get(f"{BASE}/api/labor-rates/history/W-9001", timeout=15).json()["data"]
    appr = [h for h in hist if h["status"] == "approved" and not h["is_initial"]]
    ok("approve_history_entry", len(appr) >= 1 and appr[0]["new_rate"] == 12.00 and appr[0]["decided_by_role"] == "pm")
    ok("history_role_stamped_no_names", all("name" not in h for h in hist) and any(h["submitted_by_role"] for h in hist))

    # ---- 4) PM REJECTS -> current unchanged ----
    r2 = requests.post(f"{BASE}/api/labor-rates/changes", json={"worker_id": "W-9002", "new_rate": 25.00, "effective_date": "2026-06-01"}, timeout=15)
    cid2 = r2.json()["data"]["change_id"]
    rj = pm.post(f"{BASE}/api/labor-rates/changes/{cid2}/reject", json={"note": "too high"}, timeout=15)
    ok("pm_reject_200", rj.status_code == 200)
    w2 = find(roster(), "active", "W-9002")
    ok("reject_current_unchanged", w2 and w2["current_rate"] == 20.00 and not w2["has_pending"])

    # ---- 5) ACTIVE/INACTIVE split + Reactivate (history kept) ----
    requests.post(f"{BASE}/api/labor-rates/state/W-9001/status", json={"status": "inactive"}, timeout=15)
    rost3 = roster()
    ok("inactive_moves_section", find(rost3, "inactive", "W-9001") is not None and find(rost3, "active", "W-9001") is None)
    requests.post(f"{BASE}/api/labor-rates/state/W-9001/status", json={"status": "active"}, timeout=15)
    rost4 = roster()
    hist2 = requests.get(f"{BASE}/api/labor-rates/history/W-9001", timeout=15).json()["data"]
    ok("reactivate_same_id_history_kept", find(rost4, "active", "W-9001") is not None and len(hist2) >= 2)

    # ---- 8) STRESS ~200 synthetic + changes ----
    _stress()

    # ---- cleanup (scoped to W-9%) ----
    _cleanup()

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


def _stress():
    print("\n[stress] seeding ~200 synthetic workers + changes ...")
    trades = ["Mechanic", "Laborer", "Rope Access", "Superintendent"]
    t0 = time.perf_counter()
    n = 0
    for i in range(200):
        wid = f"W-9{i+100:03d}"
        rr = add_worker(wid, trades[i % 4], 10.0 + (i % 30), eff="2026-01-05",
                        status=("inactive" if i % 7 == 0 else "active"))
        if rr.status_code == 201:
            n += 1
            if i % 3 == 0:  # ~1/3 get a pending change
                requests.post(f"{BASE}/api/labor-rates/changes", json={
                    "worker_id": wid, "new_rate": 15.0 + (i % 20), "effective_date": "2026-06-01"}, timeout=15)
    seed_s = time.perf_counter() - t0
    ok("stress_seeded_200", n == 200, f"{n} in {seed_s:.1f}s")
    t = time.perf_counter()
    rost = roster()
    list_ms = (time.perf_counter() - t) * 1000
    ok("stress_roster_at_scale", rost["kpis"]["total"] >= 200 and list_ms < 3000,
       f"{rost['kpis']['total']} workers in {list_ms:.0f}ms")
    t = time.perf_counter()
    pq = requests.get(f"{BASE}/api/labor-rates/pending", timeout=20).json()
    pq_ms = (time.perf_counter() - t) * 1000
    ok("stress_pending_at_scale", len(pq["data"]) >= 50 and pq_ms < 3000, f"{len(pq['data'])} pending in {pq_ms:.0f}ms")
    h = requests.get(f"{BASE}/api/labor-rates/history/W-9100", timeout=15)
    ok("stress_history_ok", h.status_code == 200)


def _cleanup():
    print("\n[cleanup] scoped purge of W-9% synthetic ...")
    conn = db()
    chg = conn.execute("SELECT COUNT(*) FROM labor_rate_change WHERE worker_id LIKE 'W-9%'").fetchone()[0]
    conn.execute("DELETE FROM labor_rate_change WHERE worker_id LIKE 'W-9%'")
    conn.execute("DELETE FROM labor_worker_state WHERE worker_id LIKE 'W-9%'")
    conn.execute("DELETE FROM users WHERE email IN (?,?)", (PM_EMAIL, SUPER_EMAIL))
    conn.commit()
    res_state = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id LIKE 'W-9%'").fetchone()[0]
    res_chg = conn.execute("SELECT COUNT(*) FROM labor_rate_change WHERE worker_id LIKE 'W-9%'").fetchone()[0]
    real_state = conn.execute("SELECT COUNT(*) FROM labor_worker_state").fetchone()[0]
    real_wr = conn.execute("SELECT COUNT(*) FROM worker_rates WHERE effective_to IS NULL").fetchone()[0]
    conn.close()
    print(f"    purged {chg} change rows; residue state={res_state} change={res_chg}")
    ok("cleanup_zero_residue", res_state == 0 and res_chg == 0)
    ok("cleanup_14_real_untouched", real_state == 14 and real_wr == 14, f"state={real_state} worker_rates={real_wr}")


if __name__ == "__main__":
    sys.exit(main())
