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
PM-gated deactivate (#221, same queue, both types); role-stamped history (no
names); worker-card + photo hover (#221, gated: admin any, PM only its queue
items, super 403, no *_path leak — FAKE 'SMK ' names only); gating (admin submit;
PM only the queue, roster 403; super 403); stress 200 + scoped cleanup (zero
residue incl. synthetic employees + test photo dirs; 14 real untouched).
"""
import os
import shutil
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

# #241 — real-row baselines captured at start; cleanup asserts they are
# UNCHANGED instead of hardcoding the 2026-06 migration count (14). The
# operator adds real workers between smoke runs — asserting a frozen count
# made the suite fail on live data drift (W-0016 was the instance).
REAL_STATE_BASELINE = None
REAL_WR_BASELINE = None


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


def mk_emp(wid, eid, name, trade, photo=False):
    """Synthetic employees row (FAKE 'SMK ...' name) so the worker-card endpoint
    has an identity to return. If photo, drop a tiny synthetic face.jpg under a
    SYNTHETIC worker_records dir (no real name). Returns nothing PII."""
    fip = None
    if photo:
        d = SCRIPT_DIR / "worker_records" / f"{eid}_SMK-TEST"
        d.mkdir(parents=True, exist_ok=True)
        fp = d / "face.jpg"
        try:
            from PIL import Image
            Image.new("RGB", (6, 6), (90, 110, 140)).save(str(fp), "JPEG")
        except Exception:
            fp.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF synthetic-test\xff\xd9")
        fip = str(fp.resolve())
    conn = db()
    conn.execute("DELETE FROM employees WHERE worker_id=?", (wid,))
    conn.execute("INSERT INTO employees (employee_id, worker_id, name, trade, face_image_path) "
                 "VALUES (?,?,?,?,?)", (eid, wid, name, trade, fip))
    conn.commit(); conn.close()


def roster():
    return requests.get(f"{BASE}/api/labor-rates/roster", timeout=20).json()


def find(rost, section, wid):
    return next((w for w in rost["data"][section] if w["worker_id"] == wid), None)


def main():
    global REAL_STATE_BASELINE, REAL_WR_BASELINE
    print("== #220 Labor Rates smoke ==")

    # ---- 1) REAL ROWS intact (no real values printed; baseline = live count) ----
    conn = db()
    state_n = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id NOT LIKE 'W-9%'").fetchone()[0]
    active_n = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id NOT LIKE 'W-9%' AND status='active'").fetchone()[0]
    valid_status_n = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id NOT LIKE 'W-9%' AND status IN ('active','inactive')").fetchone()[0]
    init_n = conn.execute("SELECT COUNT(*) FROM labor_rate_change WHERE is_initial=1 AND worker_id NOT LIKE 'W-9%'").fetchone()[0]
    mism = conn.execute("""SELECT COUNT(*) FROM labor_worker_state s JOIN employees e ON e.worker_id=s.worker_id
        JOIN worker_rates wr ON wr.employee_id=e.employee_id AND wr.effective_to IS NULL
        WHERE s.worker_id NOT LIKE 'W-9%' AND ABS(s.current_rate - wr.hourly_rate) > 0.005""").fetchone()[0]
    canon_n = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id <> UPPER(worker_id)").fetchone()[0]
    REAL_STATE_BASELINE = state_n
    REAL_WR_BASELINE = conn.execute(
        "SELECT COUNT(*) FROM worker_rates WHERE effective_to IS NULL AND employee_id NOT LIKE 'E-99%'").fetchone()[0]
    conn.close()
    ok("real_state_on_file", state_n >= 1, f"{state_n} real workers (live baseline, not a frozen count)")
    ok("ids_all_canonical_uppercase", canon_n == 0, "#241 — no lowercase worker ids")
    # The active/inactive split is OPERATOR-controlled — real ops deactivate workers via the
    # live dashboard (PM-gated deactivate, #221). Assert every real worker has a valid status
    # (accounting sums to 14), NOT that all 14 are active, so the suite tolerates that drift.
    ok("migration_status_accounted", valid_status_n == state_n, f"{active_n} active / {state_n - active_n} inactive (operator-controlled)")
    ok("migration_initial_history", init_n == state_n)
    ok("migration_rates_match_worker_rates", mism == 0, "state.current_rate == worker_rates (no values shown)")

    # ---- 2) SUBMIT -> pending (current unchanged, KPI++) ----
    # #241 — add-worker now REQUIRES the worker to exist in employees (the
    # free-typed-id hole is closed), so every synthetic gets an employees row.
    mk_emp("W-9001", "E-99001", "SMK Lrt One", "Laborer")
    mk_emp("W-9002", "E-99002", "SMK Lrt Two", "Mechanic")
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

    # ---- 5) Reactivate (instant admin) + direct set_status->inactive BLOCKED (#221) ----
    dr0 = requests.post(f"{BASE}/api/labor-rates/deactivate", json={"worker_id": "W-9001"}, timeout=15)
    pm.post(f"{BASE}/api/labor-rates/changes/{dr0.json()['data']['change_id']}/approve", timeout=15)
    rost3 = roster()
    ok("deactivate_moves_to_inactive", find(rost3, "inactive", "W-9001") is not None and find(rost3, "active", "W-9001") is None)
    ok("set_status_inactive_blocked",
       requests.post(f"{BASE}/api/labor-rates/state/W-9001/status", json={"status": "inactive"}, timeout=10).status_code == 400)
    requests.post(f"{BASE}/api/labor-rates/state/W-9001/status", json={"status": "active"}, timeout=15)
    rost4 = roster()
    hist2 = requests.get(f"{BASE}/api/labor-rates/history/W-9001", timeout=15).json()["data"]
    ok("reactivate_same_id_history_kept", find(rost4, "active", "W-9001") is not None and len(hist2) >= 2)

    # ---- 6) DEACTIVATE flow (#221) — PM-gated, same queue ----
    mk_emp("W-9003", "E-99003", "SMK Lrt Three", "Rope Access")
    mk_emp("W-9004", "E-99004", "SMK Lrt Four", "Superintendent")
    add_worker("W-9003", "Rope Access", 30.00)
    add_worker("W-9004", "Superintendent", 70.00)
    dr = requests.post(f"{BASE}/api/labor-rates/deactivate", json={"worker_id": "W-9003"}, timeout=15)
    ok("deactivate_submit_201", dr.status_code == 201 and dr.json()["data"]["change_type"] == "deactivate", f"HTTP {dr.status_code}")
    dcid = dr.json()["data"]["change_id"]
    rd = roster(); w3 = find(rd, "active", "W-9003")
    ok("deactivate_stays_active_pending", w3 is not None and w3["has_pending"] and w3.get("pending_type") == "deactivate")
    ok("deactivate_pending_kpi", rd["kpis"]["pending"] >= 1)
    pq = pm.get(f"{BASE}/api/labor-rates/pending", timeout=10).json()["data"]
    ok("queue_shows_deactivate_type", any(p["id"] == dcid and p["change_type"] == "deactivate" for p in pq))
    # also have a rate pending in the queue (W-9002 from earlier was rejected; submit a fresh one)
    requests.post(f"{BASE}/api/labor-rates/changes", json={"worker_id": "W-9004", "new_rate": 72.0, "effective_date": "2026-06-01"}, timeout=15)
    pq2 = pm.get(f"{BASE}/api/labor-rates/pending", timeout=10).json()["data"]
    ok("queue_mixed_types", any(p["change_type"] == "deactivate" for p in pq2) and any(p["change_type"] == "rate" for p in pq2))
    ap = pm.post(f"{BASE}/api/labor-rates/changes/{dcid}/approve", timeout=15)
    ok("deactivate_approve_200", ap.status_code == 200)
    rd2 = roster()
    ok("deactivate_approve_moves_inactive", find(rd2, "inactive", "W-9003") is not None and find(rd2, "active", "W-9003") is None)
    hd = requests.get(f"{BASE}/api/labor-rates/history/W-9003", timeout=15).json()["data"]
    dh = [h for h in hd if h["change_type"] == "deactivate" and h["status"] == "approved"]
    ok("deactivate_history_entry", len(dh) >= 1 and dh[0]["decided_by_role"] == "pm")
    # second deactivate -> PM reject -> stays active (W-9004 has a pending rate; submit deactivate supersedes it)
    dr2 = requests.post(f"{BASE}/api/labor-rates/deactivate", json={"worker_id": "W-9004"}, timeout=15)
    dcid2 = dr2.json()["data"]["change_id"]
    pm.post(f"{BASE}/api/labor-rates/changes/{dcid2}/reject", json={"note": "keep"}, timeout=15)
    ok("deactivate_reject_stays_active", find(roster(), "active", "W-9004") is not None)
    # admin-only: PM cannot submit a deactivate (403)
    ok("pm_deactivate_403", pm.post(f"{BASE}/api/labor-rates/deactivate", json={"worker_id": "W-9004"}, timeout=10).status_code == 403)

    # ---- 7b) WORKER-CARD + PHOTO hover (#221) — gated identity, FAKE names only ----
    # W-9501: has a synthetic photo + a PENDING change (so a PM may see it).
    # W-9502: no photo + NO pending (so a PM must NOT see it).
    mk_emp("W-9501", "E-99501", "SMK Test Alpha", "Rope Access", photo=True)
    mk_emp("W-9502", "E-99502", "SMK Test Bravo", "Mechanic", photo=False)
    add_worker("W-9501", "Rope Access", 40.00)
    add_worker("W-9502", "Mechanic", 41.00)
    requests.post(f"{BASE}/api/labor-rates/changes", json={"worker_id": "W-9501", "new_rate": 42.0, "effective_date": "2026-06-01"}, timeout=15)
    # admin: card for ANY worker; name+trade present; NO *_path leak
    ca = requests.get(f"{BASE}/api/labor-rates/worker-card/W-9501", timeout=10)
    cj = ca.json().get("data", {}) if ca.status_code == 200 else {}
    ok("card_admin_200", ca.status_code == 200 and cj.get("display_name") == "SMK Test Alpha" and cj.get("trade") == "Rope Access", f"HTTP {ca.status_code}")
    ok("card_has_photo_true", cj.get("has_photo") is True)
    ok("card_no_path_leak", not any("path" in k.lower() for k in cj.keys()) and "worker_records" not in ca.text.lower())
    cb = requests.get(f"{BASE}/api/labor-rates/worker-card/W-9502", timeout=10).json().get("data", {})
    ok("card_no_photo_initials", cb.get("display_name") == "SMK Test Bravo" and cb.get("has_photo") is False)
    # admin photo route serves the synthetic image (no-store); a worker with no photo -> 404
    pa = requests.get(f"{BASE}/api/labor-rates/worker-photo/W-9501", timeout=10)
    ok("photo_admin_serves", pa.status_code == 200 and pa.headers.get("Content-Type", "").startswith("image/") and "no-store" in pa.headers.get("Cache-Control", ""), f"HTTP {pa.status_code}")
    ok("photo_no_file_404", requests.get(f"{BASE}/api/labor-rates/worker-photo/W-9502", timeout=10).status_code == 404)
    # PM: card/photo ONLY for a worker with a pending queue item; 403 otherwise
    ok("card_pm_with_pending_200", pm.get(f"{BASE}/api/labor-rates/worker-card/W-9501", timeout=10).status_code == 200)
    ok("card_pm_no_pending_403", pm.get(f"{BASE}/api/labor-rates/worker-card/W-9502", timeout=10).status_code == 403)
    ok("photo_pm_with_pending_200", pm.get(f"{BASE}/api/labor-rates/worker-photo/W-9501", timeout=10).status_code == 200)
    ok("photo_pm_no_pending_403", pm.get(f"{BASE}/api/labor-rates/worker-photo/W-9502", timeout=10).status_code == 403)
    # super/other: 403 on both card + photo
    ok("card_super_403", sup.get(f"{BASE}/api/labor-rates/worker-card/W-9501", timeout=10).status_code == 403)
    ok("photo_super_403", sup.get(f"{BASE}/api/labor-rates/worker-photo/W-9501", timeout=10).status_code == 403)

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
        # #241 — every state row needs a real employees row now; eid mirrors
        # the wid digits (W-9100 -> E-99100), inside the E-99% cleanup band.
        mk_emp(wid, f"E-9{wid[2:]}", f"SMK Stress {i}", trades[i % 4])
        rr = add_worker(wid, trades[i % 4], 10.0 + (i % 30), eff="2026-01-05",
                        status=("inactive" if i % 7 == 0 else "active"))
        if rr.status_code == 201:
            n += 1
            if i % 3 == 0:  # ~1/3 get a pending rate change
                requests.post(f"{BASE}/api/labor-rates/changes", json={
                    "worker_id": wid, "new_rate": 15.0 + (i % 20), "effective_date": "2026-06-01"}, timeout=15)
            elif i % 5 == 0 and i % 7 != 0:  # some active workers get a pending deactivate
                requests.post(f"{BASE}/api/labor-rates/deactivate", json={"worker_id": wid}, timeout=15)
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
    # synthetic employees created for the worker-card test (FAKE 'SMK ' names, E-99% eids) only
    conn.execute("DELETE FROM employees WHERE worker_id LIKE 'W-9%' AND (name LIKE 'SMK %' OR employee_id LIKE 'E-99%')")
    # those synthetic employees bridged a rate into worker_rates + an audit_log row — purge both (E-99% only)
    conn.execute("DELETE FROM worker_rates WHERE employee_id LIKE 'E-99%'")
    conn.execute("DELETE FROM audit_log WHERE target_id LIKE 'E-99%'")
    conn.execute("DELETE FROM users WHERE email IN (?,?)", (PM_EMAIL, SUPER_EMAIL))
    conn.commit()
    res_state = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id LIKE 'W-9%'").fetchone()[0]
    res_chg = conn.execute("SELECT COUNT(*) FROM labor_rate_change WHERE worker_id LIKE 'W-9%'").fetchone()[0]
    res_emp = conn.execute("SELECT COUNT(*) FROM employees WHERE worker_id LIKE 'W-9%'").fetchone()[0]
    res_wr9 = conn.execute("SELECT COUNT(*) FROM worker_rates WHERE employee_id LIKE 'E-99%'").fetchone()[0]
    real_state = conn.execute("SELECT COUNT(*) FROM labor_worker_state").fetchone()[0]
    real_wr = conn.execute("SELECT COUNT(*) FROM worker_rates WHERE effective_to IS NULL AND employee_id NOT LIKE 'E-99%'").fetchone()[0]
    conn.close()
    # synthetic worker_records dirs (E-99..._SMK-TEST) — never touch real worker folders
    dirs = 0
    for d in (SCRIPT_DIR / "worker_records").glob("E-99*_SMK-TEST"):
        shutil.rmtree(d, ignore_errors=True); dirs += 1
    print(f"    purged {chg} change rows + synthetic emps; removed {dirs} test photo dir(s); residue state={res_state} change={res_chg} emp={res_emp} wr={res_wr9}")
    ok("cleanup_zero_residue", res_state == 0 and res_chg == 0 and res_emp == 0 and res_wr9 == 0)
    ok("cleanup_real_rows_untouched",
       real_state == REAL_STATE_BASELINE and real_wr == REAL_WR_BASELINE,
       f"state {real_state} == baseline {REAL_STATE_BASELINE} · active worker_rates {real_wr} == baseline {REAL_WR_BASELINE}")


if __name__ == "__main__":
    sys.exit(main())
