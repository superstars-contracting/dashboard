#!/usr/bin/env python3
"""#278 — Project Cost widget + expense ledger guard smoke (dual-backend).

Proves, fail->pass where practical:
  (a) RATE-BOUNDARY MATH — a mid-history rate change splits a worker's spend AT THE
      BOUNDARY: 3 days x 8h x $40 + 2 days x 8h x $50 = $1,760.00 EXACTLY (Decimal,
      to the penny). FAIL->PASS PROOF: the naive today's-rate math (40h x $50 =
      $2,000.00) is asserted UNEQUAL — the engine provably resolves per-day.
  (b) UNRATED BUCKET — sign-ins before any effective_from land in the unrated
      bucket: EXCLUDED from every $, surfaced as chip data (hours/workers/earliest)
      — never a silent $0.
  (c) SUMS — trade split sums == labor total; expense sums by category; a VOIDED
      expense is excluded everywhere (and flagged in the list).
  (d) ROLE MATRIX — admin/c_suite get the cost payload; pm/super/estimator/client
      get 403 on EVERY /api/costs/* endpoint with NO cost keys in the body
      (omitted, never zeroed). Field-reachable surfaces (the APIs dashboard-static
      consumes) carry NO new cost keys.
  (e) LEDGER DISCIPLINE — create 201; void requires an audit note (400 without);
      double-void 409; voided rows stay listed, flagged.
  (f) MODAL — the #275 structural any-modal-field scanner passes company-dashboard
      WITH the new expense modal, and the pc-* fields are IN the scanned set.

Isolation: SMOKE_BASE isolated server; REFUSES without SSC_DB_URL. Synthetic-only
(SMK278-* / SMKP-278 / E-SMK278*), is_system=1, random per-run password, scoped
FK-safe teardown. PII/comp-safe output: synthetic dollars only, workers by
employee_id fixture ids.
"""
from __future__ import annotations

import os
import sys
import secrets
from datetime import date
from decimal import Decimal
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

import db_layer            # noqa: E402
from auth import hash_password  # noqa: E402
from apply_expenses_278 import ensure_expenses_schema  # noqa: E402
import project_costs       # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PW = secrets.token_urlsafe(18)
USERS = {
    "admin": "smk278-admin@superstars.local",
    "csuite": "smk278-csuite@superstars.local",
    "pm": "smk278-pm@superstars.local",
    "super": "smk278-super@superstars.local",
    "est": "smk278-est@superstars.local",
    "client": "smk278-client@superstars.local",
}
ROLE_OF = {"admin": "admin", "csuite": "c_suite", "pm": "pm", "super": "super",
           "est": "estimator", "client": "client"}
PROJ = "SMKP-278"
EMP_A, EMP_B = "E-SMK278A", "E-SMK278B"

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_expenses_schema(conn)
        for key, email in USERS.items():
            role = ROLE_OF[key]
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET password_hash=?, role=?, is_active=1, status='active', "
                    "must_reset_password=0, is_system=1 WHERE email=?", (hash_password(PW), role, email))
            else:
                conn.execute(
                    "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                    "must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                    (email, hash_password(PW), role, f"SMK278 {key}"))
        conn.execute("INSERT OR IGNORE INTO projects (project_code, name, status) "
                     "VALUES (?, 'SMK278 Cost Fixture', 'active')", (PROJ,))
        for eid, nm in ((EMP_A, "SMK A"), (EMP_B, "SMK B")):
            if not conn.execute("SELECT 1 FROM employees WHERE employee_id=?", (eid,)).fetchone():
                conn.execute("INSERT INTO employees (employee_id, name) VALUES (?,?)", (eid, nm))
        conn.execute("INSERT OR REPLACE INTO labor_worker_state (worker_id, employee_id, trade, status) "
                     "VALUES ('W-9278', ?, 'Mechanic', 'active')", (EMP_A,))
        conn.execute("INSERT OR REPLACE INTO labor_worker_state (worker_id, employee_id, trade, status) "
                     "VALUES ('W-9279', ?, 'Laborer', 'active')", (EMP_B,))
        # MID-PERIOD RATE CHANGE: $40 through 6/30 inclusive, $50 from 7/1 (open)
        conn.execute("DELETE FROM worker_rates WHERE employee_id IN (?,?)", (EMP_A, EMP_B))
        conn.execute("INSERT INTO worker_rates (employee_id, hourly_rate, effective_from, effective_to) "
                     "VALUES (?, 40.0, '2026-06-01', '2026-06-30')", (EMP_A,))
        conn.execute("INSERT INTO worker_rates (employee_id, hourly_rate, effective_from, effective_to) "
                     "VALUES (?, 50.0, '2026-07-01', NULL)", (EMP_A,))
        conn.execute("DELETE FROM sign_in_log WHERE project_code=?", (PROJ,))
        for d in ("2026-06-24", "2026-06-25", "2026-06-26", "2026-07-01", "2026-07-02"):
            conn.execute("INSERT INTO sign_in_log (date, employee_id, project_code, time_in, time_out) "
                         "VALUES (?,?,?, '07:00', '15:30')", (d, EMP_A, PROJ))
        # unrated: EMP_B works one 8h day with NO rate rows at all
        conn.execute("INSERT INTO sign_in_log (date, employee_id, project_code, time_in, time_out) "
                     "VALUES ('2026-07-02', ?, ?, '07:00', '15:30')", (EMP_B, PROJ))
        conn.execute("DELETE FROM project_expense WHERE project_code=?", (PROJ,))
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        conn.execute("DELETE FROM project_expense WHERE project_code=?", (PROJ,))
        conn.execute("DELETE FROM sign_in_log WHERE project_code=?", (PROJ,))
        conn.execute("DELETE FROM worker_rates WHERE employee_id IN (?,?)", (EMP_A, EMP_B))
        conn.execute("DELETE FROM labor_worker_state WHERE worker_id IN ('W-9278','W-9279')")
        for eid in (EMP_A, EMP_B):
            conn.execute("DELETE FROM employees WHERE employee_id=?", (eid,))
        conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM users WHERE id=?", (u[0],))
        conn.commit()
    finally:
        conn.close()


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _walk_keys(obj, out):
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.add(str(k))
            _walk_keys(v, out)
    elif isinstance(obj, list):
        for v in obj:
            _walk_keys(v, out)


COST_KEYS = {"labor_cost_per_hr", "materials_share_pct", "last_full_week_total",
             "spent_to_date", "by_trade", "hourly_rate"}


def main():
    if not (os.environ.get("SSC_DB_URL") or "").strip():
        print("REFUSING TO RUN: SSC_DB_URL is unset — this smoke seeds workers/rates and "
              "must never touch the live superstars.db.")
        return 2
    print(f"#278 cost-widget guard — BASE={BASE}  backend={'postgres' if db_layer.is_postgres() else 'sqlite'}")
    _cleanup()
    _seed()
    try:
        # ---------- (a)+(b)+(c) the engine, penny-exact (module-level, gate DB) ----------
        conn = db_layer.connect()
        try:
            lab = project_costs.labor_breakdown(conn, PROJ)
            ok("rate_boundary_penny_exact", lab["total"] == Decimal("1760.00"),
               f"got {lab['total']}")
            ok("naive_todays_rate_would_be_wrong (fail->pass proof)",
               lab["total"] != Decimal("2000.00"))
            ok("hours_exact", lab["hours"] == Decimal("40.0"))
            ok("trade_split_sums_to_total",
               sum(b["amount"] for b in lab["by_trade"].values()) == lab["total"])
            ok("unrated_excluded_and_surfaced",
               lab["unrated"] is not None and lab["unrated"]["hours"] == Decimal("8.0")
               and lab["unrated"]["workers"] == 1 and lab["unrated"]["earliest"] == "2026-07-02")
            # weekly hand-math: wk of 6/22 = 3d x 8 x 40 = 960; wk of 6/29 = 2d x 8 x 50 = 800
            ok("weekly_buckets_hand_math",
               lab["weekly"].get("2026-06-22") == Decimal("960.00")
               and lab["weekly"].get("2026-06-29") == Decimal("800.00"),
               f"got {sorted(lab['weekly'].items())}")
        finally:
            conn.close()

        adm, cs, pm, su, es, cl = (_login("admin"), _login("csuite"), _login("pm"),
                                   _login("super"), _login("est"), _login("client"))
        ok("logins", all([adm, cs, pm, su, es]))
        if not cs:
            print("cannot proceed"); return 1

        # ---------- (e) ledger discipline over HTTP ----------
        r = cs.post(f"{BASE}/api/costs/{PROJ}/expenses", json={
            "expense_date": "2026-07-02", "vendor": "SMK Vendor",
            "category": "materials", "amount": 250.50}, timeout=10)
        ok("expense_create_201", r.status_code == 201, f"got {r.status_code}")
        r = cs.post(f"{BASE}/api/costs/{PROJ}/expenses", json={
            "expense_date": "2026-07-02", "category": "equipment", "amount": 100.0}, timeout=10)
        eq_id = (r.json().get("data") or {}).get("id")
        ok("expense_create_2nd_201", r.status_code == 201 and bool(eq_id))
        r = cs.post(f"{BASE}/api/costs/{PROJ}/expenses", json={
            "expense_date": "2026-07-02", "category": "nope", "amount": 5}, timeout=10)
        ok("bad_category_400", r.status_code == 400)
        r = cs.post(f"{BASE}/api/costs/expenses/{eq_id}/void", json={}, timeout=10)
        ok("void_without_note_400", r.status_code == 400)
        r = cs.post(f"{BASE}/api/costs/expenses/{eq_id}/void", json={"note": "SMK278 dup"}, timeout=10)
        ok("void_with_note_200", r.status_code == 200)
        r = cs.post(f"{BASE}/api/costs/expenses/{eq_id}/void", json={"note": "again"}, timeout=10)
        ok("double_void_409", r.status_code == 409)
        r = cs.get(f"{BASE}/api/costs/{PROJ}/expenses", timeout=10)
        rows = r.json().get("data") or []
        ok("list_flags_voided", any(x["voided"] and x["id"] == eq_id for x in rows)
           and any(not x["voided"] for x in rows))

        # ---------- (c2) widget payload sums (voided excluded) ----------
        r = cs.get(f"{BASE}/api/costs/widget?project={PROJ}", timeout=15)
        ok("widget_200_csuite", r.status_code == 200)
        p = (r.json().get("data") or {}).get("selected") or {}
        ok("widget_total_penny", p.get("total") == 2010.50, f"got {p.get('total')}")
        ok("widget_expenses_exclude_voided", p.get("expenses", {}).get("total") == 250.50)
        ok("widget_cost_per_hr", p.get("labor_cost_per_hr") == 44.00)
        ok("widget_unrated_chip", (p.get("unrated") or {}).get("hours") == 8.0)
        ok("widget_trade_split", any(t["trade"] == "Mechanic" and t["amount"] == 1760.00
                                     for t in p.get("labor", {}).get("by_trade", [])))
        r = adm.get(f"{BASE}/api/costs/widget?project={PROJ}", timeout=15)
        ok("widget_200_admin", r.status_code == 200)

        # ---------- (d) role matrix: omitted, never zeroed ----------
        for role, sess in (("pm", pm), ("super", su), ("estimator", es), ("client", cl)):
            if not sess:
                continue
            for m, path in (("GET", "/api/costs/widget"),
                            ("GET", f"/api/costs/{PROJ}/expenses"),
                            ("POST", f"/api/costs/{PROJ}/expenses"),
                            ("POST", f"/api/costs/expenses/{eq_id}/void")):
                rr = sess.request(m, f"{BASE}{path}", timeout=10,
                                  **({"json": {}} if m == "POST" else {}))
                keys = set()
                try:
                    _walk_keys(rr.json(), keys)
                except Exception:
                    pass
                ok(f"{role}_403 {m} {path}", rr.status_code == 403)
                ok(f"{role}_no_cost_keys {m} {path}", not (keys & COST_KEYS),
                   f"leaked: {keys & COST_KEYS}")
        # field-reachable surfaces (what dashboard-static consumes) carry no new keys
        for path in (f"/api/projects/{PROJ}/materials", "/api/projects",
                     f"/api/dropplan/projects/{PROJ}/rollups"):
            rr = su.get(f"{BASE}{path}", timeout=10)
            keys = set()
            try:
                _walk_keys(rr.json(), keys)
            except Exception:
                pass
            ok(f"field_surface_no_cost_keys {path}", not (keys & COST_KEYS),
               f"leaked: {keys & COST_KEYS}")

        # ---------- (g2) WIDGET UPDATES AS DATA ARRIVES (operator-requested):
        # add an expense over HTTP + one more worked day in the DB -> the widget
        # payload moves by EXACTLY the hand-computed delta. ----------
        r = cs.post(f"{BASE}/api/costs/{PROJ}/expenses", json={
            "expense_date": "2026-07-03", "vendor": "SMK Vendor 2",
            "category": "materials", "amount": 89.50}, timeout=10)
        ok("delta_expense_201", r.status_code == 201)
        conn = db_layer.connect()
        try:
            conn.execute("INSERT INTO sign_in_log (date, employee_id, project_code, time_in, time_out) "
                         "VALUES ('2026-07-03', ?, ?, '07:00', '15:30')", (EMP_A, PROJ))
            conn.commit()
        finally:
            conn.close()
        r = cs.get(f"{BASE}/api/costs/widget?project={PROJ}", timeout=15)
        p2 = (r.json().get("data") or {}).get("selected") or {}
        # deltas: +8h x $50 = $400 labor; +$89.50 materials -> 2010.50+489.50 = 2500.00
        ok("delta_total_moves_exactly", p2.get("total") == 2500.00, f"got {p2.get('total')}")
        ok("delta_labor_moves", p2.get("labor", {}).get("total") == 2160.00,
           f"got {p2.get('labor', {}).get('total')}")
        ok("delta_hours_move", p2.get("labor", {}).get("hours_worked") == 48.0)
        ok("delta_expenses_move", p2.get("expenses", {}).get("total") == 340.00)

        # ---------- (h2) LAYOUT ROUND-TRIP (the live #278 regression): saving a
        # layout containing post-#210 widget ids must KEEP them (the old
        # enumerated allowlist silently stripped material-alerts/project-costs);
        # charset-unsafe ids are still dropped (injection safety preserved). ----------
        LAYOUT = [
            {"id": "active-project", "x": 0, "y": 0, "w": 5, "h": 3},
            {"id": "project-costs", "x": 5, "y": 0, "w": 7, "h": 4},
            {"id": "material-alerts", "x": 0, "y": 3, "w": 5, "h": 3},
            {"id": "<script>alert(1)</script>", "x": 0, "y": 9, "w": 4, "h": 2},
            {"id": "UPPER_case_bad", "x": 0, "y": 9, "w": 4, "h": 2},
        ]
        r = cs.put(f"{BASE}/api/dashboard/layout",
                   json={"page_key": "company_console", "layout": LAYOUT}, timeout=10)
        ok("layout_put_200", r.status_code == 200)
        r = cs.get(f"{BASE}/api/dashboard/layout?page_key=company_console", timeout=10)
        saved = ((r.json().get("data") or {}).get("layout") or [])
        ids = {n["id"] for n in saved}
        ok("layout_keeps_new_widget_ids", {"project-costs", "material-alerts"} <= ids,
           f"saved ids: {sorted(ids)}")
        ok("layout_drops_unsafe_ids", not any("<" in i or i != i.lower() for i in ids),
           f"saved ids: {sorted(ids)}")
        pc_saved = next((n for n in saved if n["id"] == "project-costs"), {})
        ok("layout_position_roundtrip", pc_saved.get("x") == 5 and pc_saved.get("w") == 7)
        cs.delete(f"{BASE}/api/dashboard/layout?page_key=company_console", timeout=10)

        # ---------- (f) the #275 structural guard passes WITH the expense modal ----------
        sys.path.insert(0, str(SCRIPT_DIR))
        import smoke_design_conventions as sdc
        page = (SCRIPT_DIR.parent / "company-dashboard.html").read_text(encoding="utf-8",
                                                                        errors="replace")
        css = (SCRIPT_DIR.parent / "static" / "css" / "widgets.css").read_text(encoding="utf-8")
        fields, bad = sdc.page_modal_field_violations(page, css)
        ids = {f["id"] for f in fields if f["id"]}
        ok("pc_modal_fields_scanned", {"pc-f-date", "pc-f-amount", "pc-f-category",
                                       "pc-f-vendor", "pc-f-note", "pc-void-note"} <= ids,
           f"missing: { {'pc-f-date','pc-f-amount','pc-f-category','pc-f-vendor','pc-f-note','pc-void-note'} - ids }")
        ok("pc_modal_all_boxed", not bad, f"BOXLESS: {bad}")

        print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        if FAIL:
            print("FAILURES: " + ", ".join(FAIL))
        print("OVERALL:", "PASS" if not FAIL else "FAIL")
        return 0 if not FAIL else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
