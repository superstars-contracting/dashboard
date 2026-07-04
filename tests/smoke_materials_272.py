#!/usr/bin/env python3
"""#272a — Materials & Deliveries guard (dual-backend).

Proves, server-side:
  (a) UNIT-CONVERSION INTEGRITY — a pallet entry stores BOTH what was typed
      (qty_entered/unit_entered) and the converted base qty (qty_base = qty × pack);
      on-hand is only ever base units; a bogus unit -> 400.
  (b) ON-HAND ARITHMETIC — SUM over delivery/pickup/return/writeoff signs correctly;
      the TRANSFER endpoint writes an ATOMIC out/in pair (source down, destination up,
      auto-created destination material when absent — definition copied, unpinned).
  (c) WEEKLY COUNT — count_adjust reconciles ledger->reality: drift reported per item,
      on-hand corrected, a zero-delta item writes NO txn.
  (d) EXPECTED -> RECEIVED in one step — a delivery txn lands pre-filled, the row
      closes, on_hand rises, next_expected clears, last_delivery updates.
  (e) SUMMARY FIELDS — last_delivery {date,qty,vendor} + next_expected {date,status,
      vendor} come back exactly right (the two fields the operator asked to SEE).
  (f) ROLE GATES — an UNASSIGNED pm gets 403 on EVERY endpoint (path-scoped via the
      central hook, by-id via per-resource checks); a zero-grant client is contained
      (403 via the #267/#269 gate).
  (g) CURATED PAYLOADS — forbidden-keys scan on every payload: no *_path, no cost/
      price/rate keys (financials live in the expense module, not here).
  (h) CATALOG RULE — copy-from clones DEFINITIONS faithfully (fields equal, collisions
      skipped, transactions NOT copied); a material with ledger history cannot be
      hard-deleted (409 -> deactivate), a deactivated material leaves the default list
      but stays queryable with ?all=1 and refuses new txns.
  (i) SLIP — multipart upload stores the slip; bytes come back ONLY through the gated
      by-id route; payloads carry has_slip/slip_url, never a path.

Synthetic-only (SMK272-* materials/projects, smk272-* users — the CATALOG RULE means
nothing here resembles production data). Isolated via SSC_DB_URL; FK-safe cleanup.
"""
from __future__ import annotations

import os
import secrets
import shutil
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
from auth import hash_password, _now_iso  # noqa: E402
from apply_pm_assignment_263 import ensure_pm_assignment_schema  # noqa: E402
from apply_client_grants_269 import ensure_client_grants_schema  # noqa: E402
from apply_materials_272 import ensure_materials_schema  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
_SLIP_BASE = SCRIPT_DIR / "data_room" / "material_slips"

PW = secrets.token_urlsafe(18)
USERS = {"admin": "smk272-admin@superstars.local",
         "pm": "smk272-pm@superstars.local",       # NO assignments — 403 probes
         "client": "smk272-client@superstars.local"}
ROLE_OF = {"admin": "admin", "pm": "pm", "client": "client"}
PROJ_A, PROJ_B = "SMK272-A", "SMK272-B"
_TINY_PDF = b"%PDF-1.4\n1 0 obj<</T(slip)>>endobj\ntrailer<<>>\n%%EOF\n"
_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return cond


def _uid(conn, key):
    return conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()[0]


def _purge(conn):
    for code in (PROJ_A, PROJ_B):
        conn.execute("DELETE FROM material_txn WHERE project_code=?", (code,))
        conn.execute("DELETE FROM expected_delivery WHERE project_code=?", (code,))
        conn.execute("DELETE FROM material WHERE project_code=?", (code,))
        conn.execute("DELETE FROM client_section_grant WHERE project_code=?", (code,))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_pm_assignment_schema(conn)
        ensure_client_grants_schema(conn)
        ensure_materials_schema(conn)
        for key, email in USERS.items():
            role = ROLE_OF[key]
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute("UPDATE users SET password_hash=?, role=?, is_active=1, "
                             "status='active', must_reset_password=0, is_system=1 WHERE email=?",
                             (hash_password(PW), role, email))
            else:
                conn.execute("INSERT INTO users (email,password_hash,role,full_name,is_active,"
                             "status,must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                             (email, hash_password(PW), role, f"SMK272 {key}"))
        for code in (PROJ_A, PROJ_B):
            if not conn.execute("SELECT 1 FROM projects WHERE project_code=?", (code,)).fetchone():
                conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                             (code, f"Smoke Materials {code[-1]}"))
            else:
                conn.execute("UPDATE projects SET status='active' WHERE project_code=?", (code,))
        for k in ("pm", "client"):
            conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (_uid(conn, k),))
        _purge(conn)
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
                conn.execute("DELETE FROM client_section_grant WHERE user_id=? OR granted_by=?", (uid, uid))
                conn.execute("DELETE FROM pm_project_assignment WHERE user_id=? OR assigned_by=?", (uid, uid))
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM role_change_audit WHERE user_id=? OR changed_by=?", (uid, uid))
                conn.execute("DELETE FROM audit_log WHERE actor_user_id=?", (uid,))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
        for code in (PROJ_A, PROJ_B):
            conn.execute("DELETE FROM projects WHERE project_code=?", (code,))
        conn.commit()
    finally:
        conn.close()
    for code in (PROJ_A, PROJ_B):
        d = _SLIP_BASE / code
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _sc(sess, method, path, **kw):
    return sess.request(method, f"{BASE}{path}", timeout=15, **kw).status_code


_FORBIDDEN_KEYS = {"slip_path", "file_path", "thumb_path", "path", "cost", "price",
                   "unit_cost", "total_cost", "spend", "rate", "amount", "extended_price",
                   "pin", "phone", "ssn", "dob"}


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
    admin = _login("admin"); pm = _login("pm"); client = _login("client")
    if not ok("logins", all([admin, pm, client])):
        return
    A = f"/api/projects/{PROJ_A}"

    # ---- catalog starts EMPTY (the CATALOG RULE) ----
    r = admin.get(f"{BASE}{A}/materials", timeout=15)
    ok("catalog_empty_200", r.status_code == 200 and r.json()["data"]["materials"] == [])
    ok("units_are_taxonomy_enum", "pallet" in r.json()["data"]["units"]
       and "sausage" in r.json()["data"]["units"])

    # ---- create materials (distinct pack sizes; one pinned) ----
    def mk(name, base, purch, pack, pinned, lead=None, vendor=None):
        return admin.post(f"{BASE}{A}/materials", json={
            "name": name, "base_unit": base, "purchase_unit": purch, "pack_qty": pack,
            "pinned": pinned, "lead_time_days": lead, "default_vendor": vendor,
            "category": "SMK272"}, timeout=15)
    r1 = mk("SMK272 repair mortar", "bag", "pallet", 56, True, 2, "SMK272 Vendor Co")
    r2 = mk("SMK272 sealant", "sausage", "case", 20, False)
    r3 = mk("SMK272 block", "PC", None, 1, False)
    ok("create_201", all(x.status_code == 201 for x in (r1, r2, r3)),
       f"got {[x.status_code for x in (r1, r2, r3)]}")
    m1, m2, m3 = (x.json()["data"]["id"] for x in (r1, r2, r3))
    ok("create_dup_409", mk("SMK272 repair mortar", "bag", None, 1, False).status_code == 409)
    ok("create_bad_unit_400", admin.post(f"{BASE}{A}/materials", json={
        "name": "SMK272 bad", "base_unit": "zorkmid"}, timeout=15).status_code == 400)

    # ---- (a) conversion integrity: 1 pallet -> 56 bags, both stored ----
    r = admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "delivery", "qty": 1, "unit": "pallet",
        "vendor": "SMK272 Vendor Co", "txn_date": "2026-07-01"}, timeout=15)
    ok("delivery_201", r.status_code == 201, f"got {r.status_code}")
    t = r.json()["data"]["txn"]
    ok("conversion_both_stored", t["qty_base"] == 56 and t["qty_entered"] == 1
       and t["unit_entered"] == "pallet", f"got {t['qty_base']}/{t['qty_entered']}/{t['unit_entered']}")
    ok("on_hand_base_units", r.json()["data"]["on_hand"] == 56)
    ok("txn_bad_unit_400", admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "delivery", "qty": 1, "unit": "case"},
        timeout=15).status_code == 400)
    ok("txn_transfer_type_rejected", admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "transfer_out", "qty": 1, "unit": "bag"},
        timeout=15).status_code == 400)

    # ---- (b) arithmetic: pickup +, return -, writeoff - ----
    admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "pickup", "qty": 10, "unit": "bag",
        "txn_date": "2026-07-02", "vendor": "SMK272 Counter Pickup"}, timeout=15)
    admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "return", "qty": 4, "unit": "bag",
        "txn_date": "2026-07-02"}, timeout=15)
    r = admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m1, "txn_type": "writeoff", "qty": 2, "unit": "bag",
        "txn_date": "2026-07-02"}, timeout=15)
    ok("arithmetic_signs", r.json()["data"]["on_hand"] == 60, f"got {r.json()['data']['on_hand']} (want 56+10-4-2=60)")

    # ---- (b) ATOMIC transfer to B (auto-creates the material there, unpinned) ----
    r = admin.post(f"{BASE}{A}/material-transfers", json={
        "material_id": m1, "to_project_code": PROJ_B, "qty": 12, "unit": "bag",
        "txn_date": "2026-07-03"}, timeout=15)
    ok("transfer_201", r.status_code == 201, f"got {r.status_code}")
    ok("transfer_source_down", r.json()["data"]["on_hand"] == 48)
    rb = admin.get(f"{BASE}/api/projects/{PROJ_B}/materials", timeout=15).json()["data"]["materials"]
    bmat = next((x for x in rb if x["name"] == "SMK272 repair mortar"), None)
    ok("transfer_dest_up_autocreated", bmat is not None and bmat["on_hand"] == 12
       and bmat["pinned"] is False and bmat["pack_qty"] == 56,
       f"got {bmat}")
    conn = db_layer.connect(pragma_fk=True)
    try:
        pair = conn.execute(
            "SELECT txn_type, qty_base FROM material_txn WHERE txn_type LIKE 'transfer%' "
            "AND project_code IN (?,?) ORDER BY id DESC LIMIT 2", (PROJ_A, PROJ_B)).fetchall()
    finally:
        conn.close()
    ok("transfer_atomic_pair", sorted([(p[0], p[1]) for p in pair]) ==
       [("transfer_in", 12.0), ("transfer_out", -12.0)], f"got {pair}")

    # ---- (d)+(e) expected delivery -> summary -> receive in one step ----
    r = admin.post(f"{BASE}{A}/expected-deliveries", json={
        "material_id": m1, "vendor": "SMK272 Vendor Co", "qty": 2, "unit": "pallet",
        "expected_date": "2026-07-10", "description": "SMK272 restock"}, timeout=15)
    ok("expected_201", r.status_code == 201, f"got {r.status_code}")
    exp_id = r.json()["data"]["id"]
    ok("expected_source_manual", r.json()["data"]["source"] == "manual")
    r = admin.patch(f"{BASE}/api/expected-deliveries/{exp_id}", json={"status": "confirmed"}, timeout=15)
    ok("expected_status_walk", r.status_code == 200 and r.json()["data"]["status"] == "confirmed")
    ok("expected_bad_status_400", admin.patch(f"{BASE}/api/expected-deliveries/{exp_id}",
       json={"status": "teleported"}, timeout=15).status_code == 400)
    summ = admin.get(f"{BASE}{A}/materials", timeout=15).json()["data"]["materials"]
    s1 = next(x for x in summ if x["id"] == m1)
    ok("summary_last_delivery", s1["last_delivery"] is not None
       and s1["last_delivery"]["date"] == "2026-07-02"
       and s1["last_delivery"]["vendor"] == "SMK272 Counter Pickup",
       f"got {s1['last_delivery']}")
    ok("summary_next_expected", s1["next_expected"] == {
        "date": "2026-07-10", "status": "confirmed", "vendor": "SMK272 Vendor Co"},
       f"got {s1['next_expected']}")
    r = admin.post(f"{BASE}/api/expected-deliveries/{exp_id}/receive",
                   json={"txn_date": "2026-07-04"}, timeout=15)
    ok("receive_201", r.status_code == 201, f"got {r.status_code}")
    ok("receive_on_hand_up", r.json()["data"]["on_hand"] == 48 + 112,
       f"got {r.json()['data']['on_hand']} (2 pallets = 112 bags)")
    s1 = next(x for x in admin.get(f"{BASE}{A}/materials", timeout=15)
              .json()["data"]["materials"] if x["id"] == m1)
    ok("receive_clears_next_expected", s1["next_expected"] is None, f"got {s1['next_expected']}")
    ok("receive_updates_last_delivery", s1["last_delivery"]["date"] == "2026-07-04"
       and s1["last_delivery"]["qty"] == 112, f"got {s1['last_delivery']}")
    ok("receive_twice_409", admin.post(f"{BASE}/api/expected-deliveries/{exp_id}/receive",
                                       json={}, timeout=15).status_code == 409)

    # ---- (c) weekly count: drift written, zero-delta writes nothing ----
    conn = db_layer.connect(pragma_fk=True)
    try:
        pre_n = conn.execute("SELECT COUNT(*) FROM material_txn WHERE material_id=?", (m2,)).fetchone()[0]
    finally:
        conn.close()
    r = admin.post(f"{BASE}{A}/material-count", json={
        "counts": {str(m1): 157, str(m2): 0}, "txn_date": "2026-07-04"}, timeout=15)
    ok("count_200", r.status_code == 200, f"got {r.status_code}")
    res = {x["material_id"]: x for x in r.json()["data"]["results"]}
    ok("count_drift_reported", res[m1]["drift"] == -3 and res[m1]["before"] == 160
       and res[m1]["counted"] == 157, f"got {res.get(m1)}")
    ok("count_zero_delta_no_txn", res[m2]["drift"] == 0)
    conn = db_layer.connect(pragma_fk=True)
    try:
        post_n = conn.execute("SELECT COUNT(*) FROM material_txn WHERE material_id=?", (m2,)).fetchone()[0]
    finally:
        conn.close()
    ok("count_zero_delta_writes_nothing", post_n == pre_n)
    s1 = next(x for x in admin.get(f"{BASE}{A}/materials", timeout=15)
              .json()["data"]["materials"] if x["id"] == m1)
    ok("count_corrects_on_hand", s1["on_hand"] == 157, f"got {s1['on_hand']}")

    # ---- (i) slip upload + gated serve ----
    r = admin.post(f"{BASE}{A}/material-txns",
                   data={"material_id": str(m2), "txn_type": "delivery", "qty": "1",
                         "unit": "case", "txn_date": "2026-07-04"},
                   files={"slip": ("slip.pdf", _TINY_PDF, "application/pdf")}, timeout=15)
    ok("slip_txn_201", r.status_code == 201, f"got {r.status_code}")
    t = r.json()["data"]["txn"]
    ok("slip_url_not_path", t["has_slip"] is True and t["slip_url"]
       and "slip_path" not in t, f"got {t.get('slip_url')}")
    ok("slip_served_200", _sc(admin, "GET", t["slip_url"]) == 200)
    ok("slip_pm_unassigned_403", _sc(pm, "GET", t["slip_url"]) == 403)

    # ---- (g) curated payloads ----
    for path in (f"{A}/materials", f"{A}/material-txns", f"{A}/expected-deliveries"):
        hits = []
        _scan(admin.get(f"{BASE}{path}", timeout=15).json(), hits, path)
        ok(f"curated_{path.rsplit('/',1)[-1]}", not hits, f"forbidden keys: {hits}")

    # ---- (h) catalog copy fidelity + deactivate-not-delete ----
    r = admin.post(f"{BASE}/api/projects/{PROJ_B}/materials/copy-from",
                   json={"source_project_code": PROJ_A}, timeout=15)
    ok("copy_200", r.status_code == 200, f"got {r.status_code}")
    d = r.json()["data"]
    ok("copy_skips_collisions", d["copied"] == 2 and d["skipped"] == 1
       and d["skipped_names"] == ["SMK272 repair mortar"], f"got {d}")
    rb = admin.get(f"{BASE}/api/projects/{PROJ_B}/materials", timeout=15).json()["data"]["materials"]
    b2 = next((x for x in rb if x["name"] == "SMK272 sealant"), None)
    ok("copy_fidelity", b2 is not None and b2["base_unit"] == "sausage"
       and b2["purchase_unit"] == "case" and b2["pack_qty"] == 20 and b2["on_hand"] == 0,
       f"got {b2}")
    ok("copy_no_txns", all(x["on_hand"] == 0 for x in rb if x["name"] != "SMK272 repair mortar"))
    ok("delete_with_history_409", _sc(admin, "DELETE", f"/api/materials/{m1}") == 409)
    r = admin.patch(f"{BASE}/api/materials/{m3}", json={"active": False}, timeout=15)
    ok("deactivate_200", r.status_code == 200 and r.json()["data"]["active"] is False)
    mats_default = admin.get(f"{BASE}{A}/materials", timeout=15).json()["data"]["materials"]
    mats_all = admin.get(f"{BASE}{A}/materials?all=1", timeout=15).json()["data"]["materials"]
    ok("deactivated_hidden_default", all(x["id"] != m3 for x in mats_default))
    ok("deactivated_visible_all", any(x["id"] == m3 for x in mats_all))
    ok("deactivated_refuses_txn", admin.post(f"{BASE}{A}/material-txns", json={
        "material_id": m3, "txn_type": "delivery", "qty": 1, "unit": "PC"},
        timeout=15).status_code == 409)
    b3 = next((x for x in rb if x["name"] == "SMK272 block"), None)
    ok("copy_before_deactivate_included", b3 is not None)

    # ---- (f) role gates: pm UNASSIGNED -> 403 everywhere; client contained ----
    pm_probes = [
        ("GET", f"{A}/materials", {}),
        ("POST", f"{A}/materials", {"json": {"name": "SMK272 pm", "base_unit": "bag"}}),
        ("PATCH", f"/api/materials/{m1}", {"json": {"pinned": True}}),
        ("DELETE", f"/api/materials/{m2}", {}),
        ("POST", f"{A}/materials/copy-from", {"json": {"source_project_code": PROJ_B}}),
        ("POST", f"{A}/material-txns", {"json": {"material_id": m1, "qty": 1, "unit": "bag"}}),
        ("GET", f"{A}/material-txns", {}),
        ("POST", f"{A}/material-transfers", {"json": {"material_id": m1, "to_project_code": PROJ_B,
                                                      "qty": 1, "unit": "bag"}}),
        ("GET", f"{A}/expected-deliveries", {}),
        ("POST", f"{A}/expected-deliveries", {"json": {"expected_date": "2026-07-20"}}),
        ("PATCH", f"/api/expected-deliveries/{exp_id}", {"json": {"status": "arriving"}}),
        ("POST", f"/api/expected-deliveries/{exp_id}/receive", {"json": {}}),
        ("POST", f"{A}/material-count", {"json": {"counts": {str(m1): 1}}}),
    ]
    ok("pm_unassigned_403_everywhere",
       all(_sc(pm, mth, p, **kw) == 403 for mth, p, kw in pm_probes),
       f"statuses: {[(p, _sc(pm, mth, p, **kw)) for mth, p, kw in pm_probes]}")
    ok("client_contained_403", _sc(client, "GET", f"{A}/materials") == 403
       and _sc(client, "POST", f"{A}/material-txns", json={}) == 403)

    # pm ASSIGNED flips access (fail->pass inside the run)
    conn = db_layer.connect(pragma_fk=True)
    try:
        conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, assigned_at) "
                     "VALUES (?,?,?,?)", (_uid(conn, "pm"), PROJ_A, _uid(conn, "admin"), _now_iso()))
        conn.commit()
    finally:
        conn.close()
    ok("pm_assigned_200", _sc(pm, "GET", f"{A}/materials") == 200,
       "assignment must flip the same URL 403 -> 200")
    ok("pm_assigned_transfer_needs_both_403",
       _sc(pm, "POST", f"{A}/material-transfers", json={
           "material_id": m1, "to_project_code": PROJ_B, "qty": 1, "unit": "bag"}) == 403,
       "transfer requires access to BOTH projects — pm is not assigned to B")


def main():
    print(f"== #272a materials guard ==  BASE={BASE}")
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
