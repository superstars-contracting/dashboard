"""
smoke_worker_lifecycle.py — #241 worker ↔ labor-rates ↔ daily-report lifecycle.

Permanent regression net for the operator-reported integration bugs:
  S1/S6  lowercase free-typed worker id ('w-0016') stored -> payroll rate
         never resolved ("Rate not set") and the row rendered lowercase.
  S2     daily-report worker selector ordered alphabetically by name.
  S3     Labor-Rates deactivate/reactivate not propagating to the
         daily-report selector.
  S4     rate entry accepted a free-typed worker id.

Lifecycle covered (synthetic W-99xx / E-999xx band, against the running
server at SMOKE_BASE):
  create employee -> visible in daily-report selector (no rate needed)
  -> malformed worker-id POSTs REJECTED (shape + unknown worker)
  -> lowercase-but-valid id NORMALIZED to uppercase on write (never stored
     lowercase; employee link + worker_rates bridge both land)
  -> appears in selector at the correct NUMERIC position
  -> rate resolves on the payroll view (no rate_not_set)
  -> deactivate (PM-approval flow) -> EXCLUDED from selector, history kept
  -> reactivate -> back in selector, same id + same rate.

Cleanup is scoped to the exact synthetic ids only — never a blanket DELETE.
PII-safe: prints only W-####/E-##### ids, counts, and booleans. Fake rate
($1.00) only; no real rate values are read or printed.
"""
import os
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PROJECT = "FR-BX-001"
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"

WID = "W-9941"          # outside the stress band (W-9100..W-9299), inside W-9% cleanup band
EID = "E-99941"
WID_UNKNOWN = "W-9942"  # valid shape, deliberately never created
FAKE_RATE = 1.00

PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    c = sqlite3.connect(str(DB_PATH), timeout=60.0)
    c.row_factory = sqlite3.Row
    return c


def selector_ids():
    """The daily-report worker selector's source list, in API order."""
    r = requests.get(f"{BASE}/api/projects/{PROJECT}/workers", timeout=20)
    r.raise_for_status()
    return [w["worker_id"] for w in r.json()["data"]]


def numerically_sorted(ids):
    nums = [int(str(w)[2:]) for w in ids if w]
    return nums == sorted(nums)


def add_rate(worker_id):
    return requests.post(f"{BASE}/api/labor-rates/state", json={
        "worker_id": worker_id, "trade": "Laborer", "rate": FAKE_RATE,
        "effective_date": date.today().isoformat(), "status": "active"}, timeout=15)


def _purge_synthetic(conn):
    """Delete THIS smoke's synthetic rows — scoped to the exact ids only."""
    conn.execute("DELETE FROM labor_rate_change WHERE worker_id=?", (WID,))
    conn.execute("DELETE FROM labor_worker_state WHERE worker_id=?", (WID,))
    conn.execute("DELETE FROM worker_rates WHERE employee_id=?", (EID,))
    conn.execute("DELETE FROM audit_log WHERE target_id IN (?,?)", (EID, WID))
    conn.execute("DELETE FROM project_assignments WHERE employee_id=?", (EID,))
    conn.execute("DELETE FROM employees WHERE employee_id=? OR worker_id=?", (EID, WID))
    conn.commit()


def main():
    print("== #241 worker lifecycle smoke ==")
    conn = db()
    # pre-flight: a prior crashed run may have stranded rows in OUR exact
    # synthetic ids — purge them (scoped; ids are synthetic by construction).
    stale = conn.execute("SELECT COUNT(*) FROM employees WHERE worker_id IN (?,?)", (WID, WID_UNKNOWN)).fetchone()[0]
    if stale:
        print(f"  [note] purging stale residue from a prior crashed run ({stale} employees row(s), scoped to {WID})")
        _purge_synthetic(conn)
    # real-row baselines (asserted unchanged after cleanup)
    base_state = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id NOT LIKE 'W-9%'").fetchone()[0]
    base_emp = conn.execute("SELECT COUNT(*) FROM employees WHERE worker_id NOT LIKE 'W-9%' OR worker_id IS NULL").fetchone()[0]
    try:
        return _run(conn, base_state, base_emp)
    finally:
        # cleanup ALWAYS runs — a mid-run crash must never strand synthetic rows
        try:
            _purge_synthetic(conn)
        finally:
            conn.close()


def _run(conn, base_state, base_emp):
    # ---- 1) CREATE — synthetic employee + active assignment ----
    conn.execute("INSERT INTO employees (employee_id, worker_id, name, trade, intake_status) "
                 "VALUES (?,?,?,?,?)", (EID, WID, "SMK Lifecycle", "Laborer", "complete"))
    conn.execute("DELETE FROM project_assignments WHERE employee_id=?", (EID,))
    conn.execute("INSERT INTO project_assignments (employee_id, project_code, status) VALUES (?,?,?)",
                 (EID, PROJECT, "active"))
    conn.commit()

    # ---- 2) SELECTOR — present (no rate on file yet) + numeric order ----
    ids = selector_ids()
    ok("selector_includes_new_worker_pre_rate", WID in ids, "workers without a labor file stay selectable")
    ok("selector_numeric_order", numerically_sorted(ids), " > ".join(ids[:4]) + " ...")
    ok("selector_position_correct", ids.index(WID) == len(ids) - 1 if WID in ids else False,
       f"{WID} sorts last of {len(ids)}")

    # ---- 2b) RATE-ENTRY SELECTOR source — eligible until a rate is on file ----
    el = requests.get(f"{BASE}/api/labor-rates/eligible-workers", timeout=15).json()["data"]
    ok("eligible_includes_new_worker", any(w["worker_id"] == WID for w in el))

    # ---- 3) RATE ENTRY — malformed REJECTED; lowercase NORMALIZED ----
    r = add_rate("w-99411")   # shape-invalid (5 digits) + lowercase
    ok("malformed_shape_rejected_400", r.status_code == 400, f"HTTP {r.status_code}")
    r = add_rate("W9941")     # missing dash
    ok("malformed_nodash_rejected_400", r.status_code == 400, f"HTTP {r.status_code}")
    r = add_rate(WID_UNKNOWN)  # valid shape, not in employees
    ok("unknown_worker_rejected_400", r.status_code == 400, f"HTTP {r.status_code}")
    r = add_rate(WID.lower())  # 'w-9941' — valid after normalization
    ok("lowercase_valid_accepted_201", r.status_code == 201, f"HTTP {r.status_code}")
    st = conn.execute("SELECT worker_id, employee_id FROM labor_worker_state WHERE worker_id=?", (WID,)).fetchone()
    low = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id=?", (WID.lower(),)).fetchone()[0]
    ok("stored_uppercase_only", st is not None and low == 0)
    ok("employee_link_backfilled", st is not None and st["employee_id"] == EID)
    wr = conn.execute("SELECT COUNT(*) FROM worker_rates WHERE employee_id=? AND effective_to IS NULL", (EID,)).fetchone()[0]
    ok("worker_rates_bridge_ran", wr == 1, "canonical rate row exists")
    el2 = requests.get(f"{BASE}/api/labor-rates/eligible-workers", timeout=15).json()["data"]
    ok("eligible_excludes_rated_worker", not any(w["worker_id"] == WID for w in el2))

    # ---- 4) PAYROLL — rate resolves on the weekly view ----
    monday = (date.today() - timedelta(days=date.today().weekday())).isoformat()
    g = requests.get(f"{BASE}/api/payroll/hours", params={"week_start": monday}, timeout=20)
    grid = g.json().get("data", {})
    me = next((w for w in grid.get("workers", []) if w.get("worker_id") == WID), None)
    ok("payroll_worker_in_grid", me is not None)
    ok("payroll_rate_resolves", bool(me) and not me.get("rate_not_set") and me.get("hourly_rate") is not None,
       "no 'Rate not set'")
    gids = [w.get("worker_id") for w in grid.get("workers", []) if w.get("worker_id")]
    ok("payroll_grid_numeric_order", numerically_sorted(gids))

    # ---- 5) Normalization on the CHANGE endpoint too ----
    rc = requests.post(f"{BASE}/api/labor-rates/changes", json={
        "worker_id": WID.lower(), "new_rate": 2.00,
        "effective_date": date.today().isoformat()}, timeout=15)
    ok("change_lowercase_normalized_201", rc.status_code == 201, f"HTTP {rc.status_code}")
    cid = (rc.json().get("data") or {}).get("change_id")
    if cid:
        requests.post(f"{BASE}/api/labor-rates/changes/{cid}/reject", json={"note": "smoke"}, timeout=15)

    # ---- 6) DEACTIVATE (PM-approval flow) -> excluded; history intact ----
    dr = requests.post(f"{BASE}/api/labor-rates/deactivate", json={"worker_id": WID}, timeout=15)
    ok("deactivate_submit_201", dr.status_code == 201, f"HTTP {dr.status_code}")
    dcid = dr.json()["data"]["change_id"]
    ap = requests.post(f"{BASE}/api/labor-rates/changes/{dcid}/approve", timeout=15)
    ok("deactivate_approve_200", ap.status_code == 200, f"HTTP {ap.status_code}")
    ids2 = selector_ids()
    ok("selector_excludes_deactivated", WID not in ids2, "instant — no copies, live filter")
    hist = requests.get(f"{BASE}/api/labor-rates/history/{WID}", timeout=15).json()["data"]
    ok("history_intact_after_deactivate", len(hist) >= 2, f"{len(hist)} rows")

    # ---- 6b) #246 — propagation across EVERY surface class ----
    g2 = requests.get(f"{BASE}/api/payroll/hours", params={"week_start": monday}, timeout=20).json()["data"]
    ok("lrt_excludes_deactivated", not any(w.get("worker_id") == WID for w in g2.get("workers", [])))
    cc = requests.get(f"{BASE}/api/projects/{PROJECT}/crew-compliance", timeout=20).json()["data"]
    ccw = cc.get("workers") if isinstance(cc, dict) else cc
    ok("crew_compliance_excludes_deactivated",
       not any(w.get("worker_id") == WID for w in (ccw or [])))
    inv = requests.get(f"{BASE}/api/workers/intake-summary", timeout=20).json()["data"]
    mine = next((w for w in inv if w.get("worker_id") == WID), None)
    ok("workforce_keeps_worker_with_inactive_status",
       bool(mine) and mine.get("labor_status") == "inactive")
    # PIN sign-in gate — a retired worker's PIN must not create new hours.
    # Only safe to exercise when the synthetic PIN collides with no one.
    pin_taken = conn.execute(
        "SELECT COUNT(*) FROM employees WHERE pin='9941' AND employee_id != ?", (EID,)).fetchone()[0]
    if not pin_taken:
        conn.execute("UPDATE employees SET pin='9941' WHERE employee_id=?", (EID,))
        conn.commit()
        rs = requests.post(f"{BASE}/api/worker/login",
                           json={"phone_or_pin": "9941", "latitude": 0, "longitude": 0}, timeout=15)
        ok("pin_signin_blocked_when_inactive", rs.status_code == 403, f"HTTP {rs.status_code}")
    else:
        print("  [note] PIN gate check skipped — synthetic PIN would collide with a real worker")

    # ---- 7) REACTIVATE -> back, same id + same rate ----
    ra = requests.post(f"{BASE}/api/labor-rates/state/{WID}/status", json={"status": "active"}, timeout=15)
    ok("reactivate_200", ra.status_code == 200, f"HTTP {ra.status_code}")
    ids3 = selector_ids()
    ok("selector_includes_reactivated", WID in ids3)
    st2 = conn.execute("SELECT current_rate FROM labor_worker_state WHERE worker_id=?", (WID,)).fetchone()
    ok("rate_survives_lifecycle", st2 is not None and abs(float(st2["current_rate"]) - FAKE_RATE) < 0.005)
    # #246 — restoration propagates everywhere too
    cc2 = requests.get(f"{BASE}/api/projects/{PROJECT}/crew-compliance", timeout=20).json()["data"]
    ccw2 = cc2.get("workers") if isinstance(cc2, dict) else cc2
    ok("crew_compliance_restores_reactivated",
       any(w.get("worker_id") == WID for w in (ccw2 or [])))
    inv2 = requests.get(f"{BASE}/api/workers/intake-summary", timeout=20).json()["data"]
    mine2 = next((w for w in inv2 if w.get("worker_id") == WID), None)
    ok("workforce_active_after_reactivate",
       bool(mine2) and mine2.get("labor_status") == "active")

    # ---- CLEANUP — scoped to the exact synthetic ids only ----
    _purge_synthetic(conn)
    residue = sum(conn.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} IN (?,?)", (WID, EID)).fetchone()[0]
                  for t, c in (("employees", "employee_id"), ("labor_worker_state", "worker_id"),
                               ("labor_rate_change", "worker_id"), ("worker_rates", "employee_id"),
                               ("project_assignments", "employee_id")))
    end_state = conn.execute("SELECT COUNT(*) FROM labor_worker_state WHERE worker_id NOT LIKE 'W-9%'").fetchone()[0]
    end_emp = conn.execute("SELECT COUNT(*) FROM employees WHERE worker_id NOT LIKE 'W-9%' OR worker_id IS NULL").fetchone()[0]
    ok("cleanup_zero_residue", residue == 0, f"residue={residue}")
    ok("cleanup_real_rows_untouched", end_state == base_state and end_emp == base_emp,
       f"state {end_state}=={base_state} · employees {end_emp}=={base_emp}")

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
