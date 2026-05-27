"""Smoke test for Labor Rates (#158).

Exercises:
  - 401 when unauthenticated
  - 403 for pm / super
  - Insert (admin) -> current rate appears
  - Insert again with future effective_from -> prior row end-dated
  - get_rate_effective_on returns OLD rate before transition, NEW after
  - /api/payroll/hours omits hourly_rate / amount_owed for pm role
  - /api/payroll/hours INCLUDES them for admin role when a worker has a rate
  - Audit log row present after each insert

PII discipline:
  - Fake placeholder rates only ($1.00, $2.00, $3.00).
  - Never echo any rate value to stdout. Counts + booleans + status codes only.
  - The two test rate rows are cleaned up at the end.

Assumes the live server on 127.0.0.1:5050 is up. Uses _smoke_auth to log
in as the smoke admin. Adds a temp pm user for the role-gate checks and
removes it at the end.
"""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR / "tests"))

import requests  # noqa: E402

import _smoke_auth  # noqa: E402  (also seeds + logs in the smoke admin)
_smoke_auth.setup()  # idempotent — installs admin cookie on module-level requests

from auth import hash_password  # noqa: E402

DB_PATH = SCRIPT_DIR / "superstars.db"
BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")

PM_EMAIL = "smoke-pm@superstars.local"
PM_PASSWORD = "smoke-pm-password-please-do-not-reuse"

# Fake placeholder rates ONLY. Never use real numbers in this file.
FAKE_RATE_A = 1.00
FAKE_RATE_B = 2.00


_passed = 0
_failed = 0


def expect(label: str, ok: bool, detail: str = "") -> None:
    global _passed, _failed
    mark = "PASS" if ok else "FAIL"
    if ok:
        _passed += 1
    else:
        _failed += 1
    suffix = f"  ({detail})" if detail else ""
    print(f"  [{mark:4}] {label}{suffix}")


def _ensure_pm_user() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA foreign_keys=ON;")
    row = conn.execute("SELECT id FROM users WHERE email = ?", (PM_EMAIL,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (email, password_hash, role, full_name, is_active) "
            "VALUES (?, ?, 'pm', ?, 1)",
            (PM_EMAIL, hash_password(PM_PASSWORD), "Smoke PM"),
        )
    else:
        conn.execute(
            "UPDATE users SET password_hash=?, role='pm', is_active=1, full_name='Smoke PM' "
            "WHERE email=?",
            (hash_password(PM_PASSWORD), PM_EMAIL),
        )
    conn.commit()
    conn.close()


def _remove_pm_user() -> None:
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("DELETE FROM users WHERE email = ?", (PM_EMAIL,))
    conn.commit()
    conn.close()


def _pm_session() -> requests.Session:
    s = requests.Session()
    s.post(
        f"{BASE}/api/auth/login",
        json={"email": PM_EMAIL, "password": PM_PASSWORD},
        timeout=15,
    )
    return s


def _anon_session() -> requests.Session:
    return requests.Session()


def _pick_test_worker() -> str:
    """Create a synthetic SMK-#### worker dedicated to rate testing.

    Previous version picked the LOWEST-numbered active employee (always
    E-00001 = W-0001) and the cleanup wiped ALL worker_rates + audit_log
    rate_change rows for that worker — silently destroying the operator's
    legitimate rate row + audit history on every run. Comp data is
    company-confidential per CLAUDE.md and losing one row is non-trivial.
    Synthetic isolation is the only safe approach. (Pattern matches the
    #172-v2 fix to smoke_crud_data_integrity.test_face_photo.)
    """
    import uuid
    syn_id = "SMK-" + uuid.uuid4().hex[:6].upper()
    conn = sqlite3.connect(str(DB_PATH))
    try:
        conn.execute(
            "INSERT INTO employees (employee_id, name, trade, intake_status, language) "
            "VALUES (?, 'SMOKE Rates', 'SMK_RATES', 'pending', 'EN')",
            (syn_id,)
        )
        conn.execute(
            "INSERT INTO project_assignments (employee_id, project_code, status) "
            "VALUES (?, 'FR-BX-001', 'active')",
            (syn_id,)
        )
        conn.commit()
    finally:
        conn.close()
    return syn_id


def _cleanup_rate_rows(employee_id: str) -> int:
    """Remove rate rows + audit entries we inserted, AND drop the synthetic
    worker (employees + project_assignments rows). Idempotent — safe to
    call from a final block even when no rows were inserted.
    """
    conn = sqlite3.connect(str(DB_PATH))
    n_rates_before = conn.execute(
        "SELECT COUNT(*) FROM worker_rates WHERE employee_id=?", (employee_id,)
    ).fetchone()[0]
    conn.execute("DELETE FROM worker_rates WHERE employee_id=?", (employee_id,))
    conn.execute(
        "DELETE FROM audit_log WHERE action='rate_change' AND target_id=?",
        (employee_id,),
    )
    # Synthetic worker teardown. Guard prefix-only so a future caller that
    # passes a real E-##### never wipes employees rows here.
    if employee_id.startswith("SMK-"):
        conn.execute("DELETE FROM project_assignments WHERE employee_id=?", (employee_id,))
        conn.execute("DELETE FROM employees WHERE employee_id=?", (employee_id,))
    conn.commit()
    conn.close()
    return n_rates_before


def main() -> int:
    print("=== smoke_rates ===")

    # The _smoke_auth shim has already logged in the smoke admin via the
    # module-level requests; we use `requests` (admin) + a fresh session
    # (pm) for the role-gate checks.
    # _pick_test_worker() creates a fresh SMK-#### each run; no defensive
    # cleanup needed at start (the prior version called _cleanup_rate_rows
    # here, but that now deletes the synthetic itself — breaks the test).
    test_emp = _pick_test_worker()

    # ---- 1. unauthenticated -> 401 on the admin endpoints
    print("\n-- unauthenticated 401 --")
    anon = _anon_session()
    r = anon.get(f"{BASE}/api/labor-rates/workers", timeout=15)
    expect("anon GET /api/labor-rates/workers == 401", r.status_code == 401,
           f"got {r.status_code}")
    r = anon.post(
        f"{BASE}/api/labor-rates/workers/{test_emp}",
        json={"hourly_rate": FAKE_RATE_A, "effective_from": "2026-01-01"},
        timeout=15,
    )
    expect("anon POST /api/labor-rates/workers/<id> == 401", r.status_code == 401,
           f"got {r.status_code}")

    # ---- 2. wrong role -> 403
    print("\n-- pm role 403 --")
    _ensure_pm_user()
    pm = _pm_session()
    r = pm.get(f"{BASE}/api/labor-rates/workers", timeout=15)
    expect("pm GET /api/labor-rates/workers == 403", r.status_code == 403,
           f"got {r.status_code}")
    r = pm.post(
        f"{BASE}/api/labor-rates/workers/{test_emp}",
        json={"hourly_rate": FAKE_RATE_A, "effective_from": "2026-01-01"},
        timeout=15,
    )
    expect("pm POST /api/labor-rates/workers/<id> == 403", r.status_code == 403,
           f"got {r.status_code}")

    # /api/payroll/hours: pm gets the grid but WITHOUT hourly_rate/amount_owed
    r = pm.get(f"{BASE}/api/payroll/hours", timeout=20)
    expect("pm GET /api/payroll/hours == 200", r.status_code == 200,
           f"got {r.status_code}")
    if r.status_code == 200:
        grid = r.json().get("data", {})
        expect("pm grid rates_visible == False", grid.get("rates_visible") is False)
        expect("pm grid has NO grand_amount_owed", "grand_amount_owed" not in grid)
        any_with_rate = any("hourly_rate" in w for w in grid.get("workers", []))
        any_with_amount = any("amount_owed" in w for w in grid.get("workers", []))
        expect("pm: no worker has hourly_rate key", not any_with_rate)
        expect("pm: no worker has amount_owed key", not any_with_amount)

    # ---- 3. admin: insert + lookup + transition
    print("\n-- admin insert + transition --")
    # Use module-level requests (smoke_auth shim made these authenticated).
    r = requests.get(f"{BASE}/api/labor-rates/workers", timeout=15)
    expect("admin GET /api/labor-rates/workers == 200", r.status_code == 200,
           f"got {r.status_code}")

    # Insert rate A effective 2026-01-01
    r = requests.post(
        f"{BASE}/api/labor-rates/workers/{test_emp}",
        json={"hourly_rate": FAKE_RATE_A, "effective_from": "2026-01-01",
              "notes": "smoke test rate A"},
        timeout=15,
    )
    expect("admin POST rate A == 201", r.status_code == 201, f"got {r.status_code}")

    # Insert rate B effective 2026-06-01 (later) — should end-date rate A
    r = requests.post(
        f"{BASE}/api/labor-rates/workers/{test_emp}",
        json={"hourly_rate": FAKE_RATE_B, "effective_from": "2026-06-01",
              "notes": "smoke test rate B"},
        timeout=15,
    )
    expect("admin POST rate B == 201", r.status_code == 201, f"got {r.status_code}")

    # Inspect DB directly (counts + structure, NEVER print rate values)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT id, effective_from, effective_to FROM worker_rates "
        "WHERE employee_id=? ORDER BY effective_from",
        (test_emp,),
    ).fetchall()
    expect("worker_rates has exactly 2 rows for the test worker", len(rows) == 2)
    if len(rows) == 2:
        expect("earlier row effective_to is set (end-dated)",
               rows[0]["effective_to"] is not None)
        expect("earlier row end-date == 2026-05-31",
               rows[0]["effective_to"] == "2026-05-31")
        expect("later row effective_to is NULL (active)",
               rows[1]["effective_to"] is None)
        expect("later row effective_from == 2026-06-01",
               rows[1]["effective_from"] == "2026-06-01")

    # Audit log entries: exactly 2 rate_change rows for this worker
    audit_rows = conn.execute(
        "SELECT id, before_json, after_json FROM audit_log "
        "WHERE action='rate_change' AND target_id=? ORDER BY id",
        (test_emp,),
    ).fetchall()
    expect("audit_log has 2 rate_change rows for this worker", len(audit_rows) == 2)
    if len(audit_rows) == 2:
        expect("first audit row before_json is NULL (no prior rate)",
               audit_rows[0]["before_json"] is None)
        expect("first audit row after_json is non-null",
               audit_rows[0]["after_json"] is not None)
        expect("second audit row before_json is non-null (prior rate captured)",
               audit_rows[1]["before_json"] is not None)
    conn.close()

    # Lookup before transition: should return rate A
    from worker_rates import get_rate_effective_on  # noqa: E402
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    rate_pre = get_rate_effective_on(conn, test_emp, "2026-03-15")
    rate_post = get_rate_effective_on(conn, test_emp, "2026-09-15")
    expect("rate effective 2026-03-15 has effective_from == 2026-01-01",
           rate_pre is not None and rate_pre.get("effective_from") == "2026-01-01")
    expect("rate effective 2026-09-15 has effective_from == 2026-06-01",
           rate_post is not None and rate_post.get("effective_from") == "2026-06-01")
    # Booleans only on hourly_rate values
    expect("pre rate hourly_rate is the smaller of A/B (no value printed)",
           rate_pre is not None and rate_pre["hourly_rate"] < rate_post["hourly_rate"])
    conn.close()

    # ---- 4. admin LRT response includes hourly_rate for the test worker
    print("\n-- admin LRT response --")
    r = requests.get(f"{BASE}/api/payroll/hours?week_start=2026-06-01", timeout=20)
    if r.status_code == 200:
        grid = r.json().get("data", {})
        expect("admin grid rates_visible == True", grid.get("rates_visible") is True)
        expect("admin grid has grand_amount_owed key",
               "grand_amount_owed" in grid)
        # The test worker should carry hourly_rate (or rate_not_set=False).
        match = next((w for w in grid.get("workers", [])
                      if w.get("employee_id") == test_emp), None)
        expect("admin: test worker carried in /payroll/hours", match is not None)
        if match:
            expect("test worker hourly_rate present", "hourly_rate" in match)
            expect("test worker amount_owed present", "amount_owed" in match)

    # ---- 5. validation
    print("\n-- validation --")
    r = requests.post(
        f"{BASE}/api/labor-rates/workers/{test_emp}",
        json={"hourly_rate": -1, "effective_from": "2027-01-01"},
        timeout=15,
    )
    expect("negative rate rejected (400)", r.status_code == 400, f"got {r.status_code}")
    r = requests.post(
        f"{BASE}/api/labor-rates/workers/{test_emp}",
        json={"hourly_rate": FAKE_RATE_A, "effective_from": "not-a-date"},
        timeout=15,
    )
    expect("bad date rejected (400)", r.status_code == 400, f"got {r.status_code}")
    r = requests.post(
        f"{BASE}/api/labor-rates/workers/E-99999",
        json={"hourly_rate": FAKE_RATE_A, "effective_from": "2027-01-01"},
        timeout=15,
    )
    expect("unknown employee rejected (400)", r.status_code == 400, f"got {r.status_code}")

    # ---- Cleanup
    print("\n-- cleanup --")
    n = _cleanup_rate_rows(test_emp)
    expect("cleanup removed the 2 test rate rows", n == 2)
    _remove_pm_user()
    print("  pm test user removed")

    print(f"\n=== summary: {_passed} pass, {_failed} fail ===")
    return 0 if _failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
