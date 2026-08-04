"""#292 guard — ssc_memo: write-invalidated memoization, proven not promised.

The doctrine (HANDOFF, verbatim): "Expensive reads are memoized via ssc_memo
with write-invalidation. TTL freshness-guessing is banned. Every memoized
payload ships with a planted-write invalidation guard: each invalidating
write type must provably change the served payload, and a stale serve is a
red gate."

Proves, against the shared gate server + the layer directly:
  1. PLANTED WRITES, per invalidating type on the cost widget:
       sign-in write      -> widget total MOVES (choke-point bump)
       rate change        -> planted hours RE-PRICE (domain bump via set_rate)
       expense create     -> total MOVES up;  expense void -> MOVES back
     A missing bump = the served payload doesn't move = RED. This is the
     stale-serve gate.
  2. SECURITY BOUNDARY (two-role probe): with the cache WARM from an admin
     request, a pm request still 403s (gating lives ABOVE the cache) and a
     c_suite request serves the per-request-shaped payload.
  3. SINGLE-FLIGHT: 8 threads memoizing one cold scope produce EXACTLY ONE
     compute (stats prove it) — pool-parallel parts can't stampede.
  4. Mutation-safety: shaping a served result never poisons the cache
     (serves are deep copies).

Synthetic fixtures only (SMK292M- ids), cleaned in finally. PII-safe output:
booleans/deltas-moved, never rate or dollar values.
"""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
import db_layer  # noqa: E402
import ssc_memo  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5434")
PROJECT = "FR-BX-001"
EID, WID = "E-99292", "W-9292"

PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note and not cond else ""))
    return bool(cond)


def seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        conn.execute("DELETE FROM sign_in_log WHERE employee_id=?", (EID,))
        conn.execute("DELETE FROM worker_rates WHERE employee_id=?", (EID,))
        conn.execute("DELETE FROM labor_worker_state WHERE worker_id=?", (WID,))
        conn.execute("DELETE FROM employees WHERE employee_id=?", (EID,))
        now = "2026-08-04T00:00:00"   # dual-backend: never datetime('now') in SQL
        conn.execute(
            "INSERT INTO employees (employee_id, name, trade, created_at, updated_at) "
            "VALUES (?, 'SMK292M Memo', 'Laborer', ?, ?)", (EID, now, now))
        conn.execute(
            "INSERT INTO labor_worker_state (worker_id, employee_id, trade, current_rate, "
            "status, effective_date, created_at, updated_at) "
            "VALUES (?,?, 'Laborer', 10.0, 'active', '2026-01-01', '2026-01-01', '2026-01-01')",
            (WID, EID))
        conn.execute(
            "INSERT INTO worker_rates (employee_id, hourly_rate, effective_from, "
            "effective_to, notes) VALUES (?, 10.0, '2026-01-01', NULL, 'smk292m seed')",
            (EID,))
        conn.commit()
    finally:
        conn.close()


def cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        for sql in ("DELETE FROM sign_in_log WHERE employee_id=?",
                    "DELETE FROM worker_rates WHERE employee_id=?",
                    "DELETE FROM project_expense WHERE vendor='SMK292M'",
                    "DELETE FROM audit_log WHERE target_id=?"):
            try:
                conn.execute(sql, (EID,) if "?" in sql else ())
                conn.commit()
            except Exception:
                try:
                    conn.rollback()
                except Exception:
                    pass
        conn.execute("DELETE FROM labor_worker_state WHERE worker_id=?", (WID,))
        conn.execute("DELETE FROM employees WHERE employee_id=?", (EID,))
        conn.commit()
    finally:
        conn.close()


def widget(sess):
    """Returns (status, SELECTED payload) — the endpoint nests one project's
    payload under data.selected (the first guard run compared a nonexistent
    top-level 'total' and every probe passed/failed vacuously on None)."""
    r = sess.get(f"{BASE}/api/costs/widget?project={PROJECT}", timeout=30)
    if r.status_code != 200:
        return r.status_code, None
    d = r.json().get("data") or {}
    return 200, (d.get("selected") or {})


def main() -> int:
    print("== #292 guard: ssc_memo write-invalidation ==")
    import _smoke_auth
    _smoke_auth.setup()
    admin = requests

    seed()
    try:
        yday = (date.today() - timedelta(days=1)).isoformat()

        # ---- 1. planted writes move the served payload ----
        sc, base0 = widget(admin)
        ok("widget_200_baseline", sc == 200, f"{sc}")
        t0 = (base0 or {}).get("total")

        # warm serve sanity: identical second read
        sc, warm = widget(admin)
        ok("warm_serve_identical", sc == 200 and warm.get("total") == t0)

        # (a) SIGN-IN write via the real API -> total must MOVE
        r = admin.post(f"{BASE}/api/sign-ins", json={
            "date": yday, "employee_id": EID, "project_code": PROJECT,
            "time_in": "07:00", "time_out": "15:30"}, timeout=20)
        ok("planted_signin_201", r.status_code == 201, f"{r.status_code}")
        sc, after_si = widget(admin)
        ok("signin_write_moves_payload", sc == 200 and after_si.get("total") != t0,
           "STALE SERVE — sign-in bump missing")
        t1 = after_si.get("total")

        # (b) RATE change via the real API -> planted hours re-price, total MOVES
        r = admin.post(f"{BASE}/api/labor-rates/workers/{EID}", json={
            "hourly_rate": 20.0, "effective_from": yday,
            "notes": "smk292m reprice"}, timeout=20)
        ok("planted_rate_change_2xx", r.status_code in (200, 201), f"{r.status_code}")
        sc, after_rate = widget(admin)
        ok("rate_write_moves_payload", sc == 200 and after_rate.get("total") != t1,
           "STALE SERVE — rate bump missing")
        t2 = after_rate.get("total")

        # (c) EXPENSE create -> MOVES up; void -> MOVES back
        r = admin.post(f"{BASE}/api/costs/{PROJECT}/expenses", json={
            "expense_date": yday, "vendor": "SMK292M", "category": "materials",
            "amount": 123.45}, timeout=20)
        ok("planted_expense_201", r.status_code == 201, f"{r.status_code}")
        exp_id = (r.json().get("data") or {}).get("id") if r.status_code == 201 else None
        sc, after_exp = widget(admin)
        ok("expense_create_moves_payload", sc == 200 and after_exp.get("total") != t2,
           "STALE SERVE — expense bump missing")
        r = admin.post(f"{BASE}/api/costs/expenses/{exp_id}/void",
                       json={"note": "smk292m guard void"}, timeout=20)
        ok("planted_void_200", r.status_code == 200, f"{r.status_code}")
        sc, after_void = widget(admin)
        ok("expense_void_moves_payload_back", sc == 200 and after_void.get("total") == t2,
           "void did not restore the pre-expense total")

        # ---- 2. two-role probe: gating + curation live ABOVE the cache ----
        import secrets
        from auth import hash_password
        pw = secrets.token_urlsafe(14)
        conn = db_layer.connect(pragma_fk=True)
        uids = {}
        try:
            for role in ("pm", "c_suite"):
                email = f"smk292m-{role}@superstars.local"
                row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
                if row:
                    conn.execute("UPDATE users SET password_hash=?, role=?, is_active=1, "
                                 "status='active', must_reset_password=0, is_system=1 "
                                 "WHERE id=?", (hash_password(pw), role, row[0]))
                    uids[role] = row[0]
                else:
                    conn.execute("INSERT INTO users (email,password_hash,role,full_name,"
                                 "is_active,status,must_reset_password,is_system) "
                                 "VALUES (?,?,?,?,1,'active',0,1)",
                                 (email, hash_password(pw), role, f"SMK292M {role}"))
                    uids[role] = conn.execute("SELECT id FROM users WHERE email=?",
                                              (email,)).fetchone()[0]
            conn.commit()
        finally:
            conn.close()
        try:
            widget(admin)                       # cache is WARM now
            pm = requests.Session()
            pm.post(f"{BASE}/api/auth/login",
                    json={"email": "smk292m-pm@superstars.local", "password": pw}, timeout=15)
            r = pm.get(f"{BASE}/api/costs/widget?project={PROJECT}", timeout=15)
            ok("warm_cache_pm_still_403", r.status_code == 403, f"{r.status_code}")
            cs = requests.Session()
            cs.post(f"{BASE}/api/auth/login",
                    json={"email": "smk292m-c_suite@superstars.local", "password": pw},
                    timeout=15)
            sc2, cs_payload = widget(cs)
            ok("c_suite_served_shaped_per_request", sc2 == 200
               and cs_payload.get("total") == after_void.get("total"))
        finally:
            conn = db_layer.connect(pragma_fk=True)
            try:
                for role, uid in uids.items():
                    for sql in ("DELETE FROM sessions WHERE user_id=?",
                                "DELETE FROM login_audit WHERE user_id=?",
                                "DELETE FROM users WHERE id=?"):
                        try:
                            conn.execute(sql, (uid,))
                            conn.commit()
                        except Exception:
                            conn.rollback()
            finally:
                conn.close()

        # ---- 3. single-flight: one compute for 8 concurrent callers ----
        ssc_memo.reset()
        calls = {"n": 0}

        def slow_compute():
            calls["n"] += 1
            time.sleep(0.15)
            return {"v": calls["n"]}

        results = []
        threads = [threading.Thread(
            target=lambda: results.append(ssc_memo.memoize(("sf_probe", "x"), slow_compute)))
            for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        st = ssc_memo.stats("sf_probe", "x")
        ok("single_flight_one_compute", calls["n"] == 1 and st["computes"] == 1
           and st["serves"] == 7, f"computes={calls['n']} stats={st}")

        # ---- 4. mutation-safety: shaping a serve never poisons the cache ----
        first = ssc_memo.memoize(("mut_probe",), lambda: {"keep": 1, "shape": [1, 2]})
        first.pop("keep")
        first["shape"].append(99)
        second = ssc_memo.memoize(("mut_probe",), lambda: {"never": "recomputed"})
        ok("serves_are_deep_copies", second.get("keep") == 1 and second["shape"] == [1, 2])

        print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        return 0 if not FAIL else 1
    finally:
        cleanup()


if __name__ == "__main__":
    sys.exit(main())
