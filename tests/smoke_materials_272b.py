#!/usr/bin/env python3
"""#272b — derived consumption / burn / reorder guard (dual-backend).

FIXTURE HAND MATH (asserted exactly — REAL division parity across backends):
  map: yield 0.5 CF/bag, waste 10%, lead 2d, safety default 4d
  entries: 7 work days in the trailing 14, 4 CF each (2ft × 2ft × 1ft) = 28 CF
  consumed   = 28 ÷ 0.5 × 1.10        = 61.6 bags
  burn/day   = 61.6 ÷ 14              = 4.4
  per-workday= 61.6 ÷ 7               = 8.8
  look-ahead : 7 scheduled days in the next 14 -> forward = 8.8 × 7/14 = 4.4
  on-hand 44 -> days_left = 44 ÷ 4.4  = 10.0
  order_by   = today + 10 − (2 + 4)   = today + 4  -> amber 'order_by'
  writeoff 40 -> on-hand 4 -> days_left 0.9 -> order_by = today − 6 -> 'order_now'

Also proves: window boundary (an entry dated exactly today−14 is OUTSIDE the
(today−14, today] window; today included); UNMAPPED materials carry NO derived keys
(honest absence, never zeros); manual_rate = flat per-workday; lead/safety edits move
order_by exactly; the weekly-count drift HINT (expected-vs-actual + suggested waste)
NEVER touches the map row; role gates (pm-unassigned 403 on map PUT/DELETE; the
company alerts widget endpoint is admin/c_suite-only and lists the fixture alert);
forbidden-keys scan on the enriched payloads. Synthetic SMK272B-* only; isolated DB.
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
from auth import hash_password, _now_iso  # noqa: E402
from apply_pm_assignment_263 import ensure_pm_assignment_schema  # noqa: E402
from apply_materials_272 import ensure_materials_schema  # noqa: E402
from apply_material_consumption_272b import ensure_consumption_schema  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PW = secrets.token_urlsafe(18)
USERS = {"admin": "smk272b-admin@superstars.local",
         "pm": "smk272b-pm@superstars.local"}      # NO assignments — 403 probes
PROJ = "SMK272B-A"
DROP = "SMK272B-D1"
_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return cond


def _uid(conn, key):
    return conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()[0]


def _purge(conn):
    conn.execute("DELETE FROM quantity_entries WHERE drop_id=?", (DROP,))
    conn.execute("DELETE FROM lookahead_activity WHERE project_code=?", (PROJ,))
    conn.execute("DELETE FROM drops WHERE project_code=?", (PROJ,))
    conn.execute("DELETE FROM sov_line_items WHERE project_code=?", (PROJ,))
    for r in conn.execute("SELECT id FROM material WHERE project_code=?", (PROJ,)).fetchall():
        conn.execute("DELETE FROM material_consumption_map WHERE material_id=?", (r[0],))
    conn.execute("DELETE FROM material_txn WHERE project_code=?", (PROJ,))
    conn.execute("DELETE FROM expected_delivery WHERE project_code=?", (PROJ,))
    conn.execute("DELETE FROM material WHERE project_code=?", (PROJ,))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_pm_assignment_schema(conn)
        ensure_materials_schema(conn)
        ensure_consumption_schema(conn)
        for key, email in USERS.items():
            role = "admin" if key == "admin" else "pm"
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute("UPDATE users SET password_hash=?, role=?, is_active=1, "
                             "status='active', must_reset_password=0, is_system=1 WHERE email=?",
                             (hash_password(PW), role, email))
            else:
                conn.execute("INSERT INTO users (email,password_hash,role,full_name,is_active,"
                             "status,must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                             (email, hash_password(PW), role, f"SMK272B {key}"))
        if not conn.execute("SELECT 1 FROM projects WHERE project_code=?", (PROJ,)).fetchone():
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                         (PROJ, "Smoke Consumption A"))
        conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (_uid(conn, "pm"),))
        _purge(conn)
        # drop-plan parents for quantity_entries (FKs are ON in gate copies)
        conn.execute("INSERT INTO drops (drop_id, project_code, sequence_no) VALUES (?,?,1)",
                     (DROP, PROJ))
        conn.execute("INSERT INTO sov_line_items (project_code, sov_code, description) "
                     "VALUES (?, 'SMK272B-01', 'Synthetic concrete repair')", (PROJ,))
        sov_id = conn.execute("SELECT sov_id FROM sov_line_items WHERE project_code=? AND sov_code=?",
                              (PROJ, "SMK272B-01")).fetchone()[0]
        today = date.today()
        # 7 entries, 4 CF each (2ft x 2ft x 1ft), on days today-1 .. today-7  => 28 CF
        for i in range(1, 8):
            conn.execute(
                "INSERT INTO quantity_entries (drop_id, sov_line_item, length, width, depth, "
                "logged_on) VALUES (?,?,?,?,?,?)",
                (DROP, sov_id, 2.0, 2.0, 1.0, (today - timedelta(days=i)).isoformat()))
        # boundary probes: exactly today-14 (must be EXCLUDED), today (must be INCLUDED,
        # added later inside run() so the base math stays 28 CF)
        conn.execute(
            "INSERT INTO quantity_entries (drop_id, sov_line_item, length, width, depth, logged_on) "
            "VALUES (?,?,?,?,?,?)", (DROP, sov_id, 10.0, 10.0, 10.0,
                                     (today - timedelta(days=14)).isoformat()))
        # look-ahead: ONE activity spanning 7 days of the next 14
        conn.execute(
            "INSERT INTO lookahead_activity (project_code, name, activity_type, planned_start, "
            "planned_finish, source) VALUES (?, 'Synthetic patch run', 'work', ?, ?, 'manual')",
            (PROJ, (today + timedelta(days=1)).isoformat(), (today + timedelta(days=7)).isoformat()))
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        _purge(conn)
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                uid = u[0]
                conn.execute("DELETE FROM pm_project_assignment WHERE user_id=? OR assigned_by=?", (uid, uid))
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM role_change_audit WHERE user_id=? OR changed_by=?", (uid, uid))
                conn.execute("DELETE FROM audit_log WHERE actor_user_id=?", (uid,))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
        conn.commit()
    finally:
        conn.close()


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _sc(sess, method, path, **kw):
    return sess.request(method, f"{BASE}{path}", timeout=15, **kw).status_code


_FORBIDDEN_KEYS = {"slip_path", "file_path", "path", "cost", "price", "unit_cost",
                   "total_cost", "spend", "rate", "amount", "pin", "phone", "ssn"}


def _scan(obj, hits, where=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _FORBIDDEN_KEYS:
                hits.append(f"{where}.{k}")
            _scan(v, hits, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:80]):
            _scan(v, hits, f"{where}[{i}]")


def run():
    admin = _login("admin"); pm = _login("pm")
    if not ok("logins", bool(admin and pm)):
        return
    A = f"/api/projects/{PROJ}"
    today = date.today()

    # materials: mapped / unmapped / manual-rate
    m1 = admin.post(f"{BASE}{A}/materials", json={
        "name": "SMK272B repair mortar", "base_unit": "bag", "purchase_unit": "pallet",
        "pack_qty": 56, "pinned": True, "lead_time_days": 2}, timeout=15).json()["data"]["id"]
    m2 = admin.post(f"{BASE}{A}/materials", json={
        "name": "SMK272B unmapped sealant", "base_unit": "sausage"}, timeout=15).json()["data"]["id"]
    m3 = admin.post(f"{BASE}{A}/materials", json={
        "name": "SMK272B flat consumable", "base_unit": "EA"}, timeout=15).json()["data"]["id"]

    # ---- map m1: yield 0.5 CF/bag, waste 10% (safety default 4) ----
    r = admin.put(f"{BASE}/api/materials/{m1}/consumption-map", json={
        "driver": "volume_cf", "yield_per_unit": 0.5, "waste_pct": 10}, timeout=15)
    ok("map_put_200", r.status_code == 200, f"got {r.status_code}")
    ok("map_safety_defaults_4", r.json()["data"]["map"]["safety_days"] == 4)
    ok("map_bad_driver_400", admin.put(f"{BASE}/api/materials/{m1}/consumption-map",
       json={"driver": "moon_phase", "yield_per_unit": 1}, timeout=15).status_code == 400)

    # on-hand 44 bags
    admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "delivery", "qty": 44, "unit": "bag",
        "txn_date": today.isoformat()}, timeout=15)

    def fetch_m(mid):
        mats = admin.get(f"{BASE}{A}/materials", timeout=15).json()["data"]["materials"]
        return next(x for x in mats if x["id"] == mid)

    # ---- (a) the hand math, exactly ----
    payload = admin.get(f"{BASE}{A}/materials", timeout=15).json()["data"]
    ok("window_28cf_7days", payload["quantity_window"]["volume_cf"] == 28.0
       and payload["quantity_window"]["workdays"] == 7,
       f"got {payload['quantity_window']} (the day-14 boundary entry must be EXCLUDED)")
    ok("sched_days_7", payload["sched_days_next14"] == 7, f"got {payload['sched_days_next14']}")
    s1 = next(x for x in payload["materials"] if x["id"] == m1)
    ok("consumed_61_6", s1["consumed_14d"] == 61.6, f"got {s1.get('consumed_14d')}")
    ok("burn_4_4", s1["burn_day"] == 4.4, f"got {s1.get('burn_day')}")
    ok("forward_4_4", s1["forward_day"] == 4.4, f"got {s1.get('forward_day')}")
    ok("days_left_10", s1["days_left"] == 10.0, f"got {s1.get('days_left')}")
    ok("order_by_today_plus_4", s1["order_by_date"] == (today + timedelta(days=4)).isoformat(),
       f"got {s1.get('order_by_date')} (10 − (2 lead + 4 safety))")
    ok("status_amber", s1["stock_status"] == "order_by", f"got {s1.get('stock_status')}")

    # ---- window boundary: a TODAY entry lands inside ----
    conn = db_layer.connect(pragma_fk=True)
    try:
        sov_id = conn.execute("SELECT sov_id FROM sov_line_items WHERE project_code=?",
                              (PROJ,)).fetchone()[0]
        conn.execute("INSERT INTO quantity_entries (drop_id, sov_line_item, length, width, depth, "
                     "logged_on) VALUES (?,?,2.0,2.0,1.0,?)", (DROP, sov_id, today.isoformat()))
        conn.commit()
    finally:
        conn.close()
    s1 = fetch_m(m1)
    ok("today_entry_included", s1["consumed_14d"] == round(32 / 0.5 * 1.1, 2),
       f"got {s1['consumed_14d']} (32 CF now)")

    # ---- (c) unmapped = honest absence ----
    s2 = fetch_m(m2)
    ok("unmapped_no_fields", all(k not in s2 for k in
       ("map", "burn_day", "days_left", "order_by_date", "stock_status", "consumed_14d")),
       f"leaked keys: {[k for k in ('map','burn_day','days_left','order_by_date','stock_status') if k in s2]}")

    # ---- manual_rate driver: flat per-workday ----
    admin.put(f"{BASE}/api/materials/{m3}/consumption-map", json={
        "driver": "manual_rate", "yield_per_unit": 5, "waste_pct": 0}, timeout=15)
    s3 = fetch_m(m3)
    ok("manual_flat_burn", s3["burn_day"] == 5.0 and s3["map"]["driver"] == "manual_rate",
       f"got {s3.get('burn_day')}")

    # ---- order-now flip: write off 40 -> on-hand 4 ----
    admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "writeoff", "qty": 40, "unit": "bag",
        "txn_date": today.isoformat()}, timeout=15)
    s1 = fetch_m(m1)
    ok("order_now_flip", s1["stock_status"] == "order_now" and s1["on_hand"] == 4,
       f"got {s1['stock_status']} at on_hand {s1['on_hand']}")

    # ---- lead/safety move order_by exactly: zero them -> stocked again ----
    admin.put(f"{BASE}/api/materials/{m1}/consumption-map", json={
        "driver": "volume_cf", "yield_per_unit": 0.5, "waste_pct": 10, "safety_days": 0},
        timeout=15)
    admin.patch(f"{BASE}/api/materials/{m1}", json={"lead_time_days": 0}, timeout=15)
    admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "delivery", "qty": 96, "unit": "bag",
        "txn_date": today.isoformat()}, timeout=15)   # on-hand 100
    s1 = fetch_m(m1)
    rate = max(round(70.4 / 14, 2), round((70.4 / 8) * (7 / 14.0), 2))  # 32 CF now: 70.4 consumed, 8 workdays
    expect_days = round(100 / rate, 1)
    ok("order_by_no_lead_safety",
       s1["days_left"] == expect_days
       and s1["order_by_date"] == (today + timedelta(days=int(expect_days))).isoformat()
       and s1["stock_status"] == "stocked",
       f"got {s1['days_left']}/{s1['order_by_date']}/{s1['stock_status']} want {expect_days}")

    # ---- (e) drift hint: actual 10% over expected; map NEVER touched ----
    # expected over (no prior count -> trailing 14d) = 70.4; actual = before − counted
    s1 = fetch_m(m1)
    before = s1["on_hand"]   # 100
    counted = round(before - 70.4 * 1.1, 2)   # actual_used = 77.44 => over = +10%
    r = admin.post(f"{BASE}{A}/material-count", json={
        "counts": {str(m1): counted}}, timeout=15)
    ok("count_200", r.status_code == 200)
    item = next(x for x in r.json()["data"]["results"] if x["material_id"] == m1)
    uc = item.get("usage_check") or {}
    ok("hint_expected_actual", uc.get("expected_used") == 70.4 and uc.get("actual_used") == 77.44,
       f"got {uc}")
    ok("hint_over_10pct", uc.get("over_pct") == 10, f"got {uc.get('over_pct')}")
    ok("hint_text", "10% over" in (uc.get("hint") or "") and "10%→21%" in (uc.get("hint") or ""),
       f"got {uc.get('hint')!r}")
    conn = db_layer.connect(pragma_fk=True)
    try:
        w = conn.execute("SELECT waste_pct FROM material_consumption_map WHERE material_id=?",
                         (m1,)).fetchone()[0]
    finally:
        conn.close()
    ok("hint_never_touches_map", w == 10.0, f"map waste_pct changed to {w}")

    # ---- (g) forbidden keys on the enriched payload ----
    hits = []
    _scan(admin.get(f"{BASE}{A}/materials", timeout=15).json(), hits, "materials")
    ok("curated_enriched_payload", not hits, f"forbidden keys: {hits}")

    # ---- (f) role gates ----
    ok("pm_map_put_403", _sc(pm, "PUT", f"/api/materials/{m1}/consumption-map",
       json={"driver": "volume_cf", "yield_per_unit": 1}) == 403)
    ok("pm_map_delete_403", _sc(pm, "DELETE", f"/api/materials/{m1}/consumption-map") == 403)
    ok("widget_pm_403", _sc(pm, "GET", "/api/company/material-alerts") == 403,
       "the console widget endpoint is admin/c_suite-only")
    r = admin.get(f"{BASE}/api/company/material-alerts", timeout=15)
    ok("widget_admin_200", r.status_code == 200)
    names = [a["name"] for a in r.json()["data"]["alerts"]]
    # after the count reconcile on-hand ≈ 22.56 -> days_left ≈ 22.56/5.03 ≈ 4.5 -> order window
    ok("widget_lists_fixture", "SMK272B repair mortar" in names, f"got {names}")
    hits = []
    _scan(r.json(), hits, "alerts")
    ok("curated_widget_payload", not hits, f"forbidden keys: {hits}")

    # ---- unmap -> honest absence returns ----
    ok("map_delete_200", _sc(admin, "DELETE", f"/api/materials/{m1}/consumption-map") == 200)
    s1 = fetch_m(m1)
    ok("unmapped_after_delete", "map" not in s1 and "burn_day" not in s1)


def main():
    print(f"== #272b consumption/burn/reorder guard ==  BASE={BASE}")
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    backend = "postgres" if db_layer.is_postgres() else "sqlite"
    print(f"   backend={backend}  SSC_DB_URL={'(set)' if db_url else '(unset=LIVE — refuse)'}")
    if not db_url and os.environ.get("ALLOW_LIVE") != "1":
        print("   REFUSING: SSC_DB_URL unset (would seed LIVE). Set an isolated backend.")
        return 2
    _seed()
    try:
        run()
    finally:
        _cleanup()
    n = len(_failures)
    print(f"\n== {'ALL PASS' if n == 0 else str(n) + ' FAILED: ' + ', '.join(_failures)} ==")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
