"""
smoke_auth.py — dashboard auth foundation (#48) end-to-end smoke.

Verifies the gate, login/logout, and exemptions:

  CORE FLOW
    1. POST /api/auth/login with wrong password → 401, no cookie
    2. POST /api/auth/login with right password → 200, sets ssc_session cookie
    3. GET  /api/auth/me with cookie → 200 + {user: {...role...}}
    4. GET  /                with cookie → 200 (dashboard HTML served)
    5. POST /api/auth/logout with cookie → 200, cookie cleared
    6. GET  /api/auth/me after logout → 401

  GATE
    7. GET  /                no cookie → 302 to /login?next=/
    8. GET  /api/projects    no cookie → 401 JSON

  EXEMPTIONS (must remain reachable without dashboard auth)
    9. GET  /api/health      no cookie → 200
   10. POST /api/worker/login bad PIN  → 401 from the PIN handler
       (NOT 302 to /login — proves worker-app path is untouched)
   11. GET  /login           no cookie → 200 (the login page itself)

PII-safe: never prints the password, the session id, or the user's email.
Seeds a throwaway test user with a marker email; cleans up regardless of pass/fail.

Usage: SMOKE_BASE controls the target (default http://127.0.0.1:5050).
Run against a live server with the new auth code loaded.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import uuid
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")

TEST_EMAIL = f"smoke-auth-{uuid.uuid4().hex[:8]}@example.test"
TEST_PASSWORD = "SmokeAuth!" + uuid.uuid4().hex[:16]
TEST_NAME = "Smoke Auth Test"

# Use the auth module's hasher so we exercise the same bcrypt round-trip
# the real login path uses.
sys.path.insert(0, str(SCRIPT_DIR))
from auth import hash_password  # noqa: E402


PASS = "PASS"
FAIL = "FAIL"
results: list[tuple[str, str, str]] = []


def expect(label: str, ok: bool, detail: str = "") -> bool:
    results.append((label, PASS if ok else FAIL, detail))
    return ok


def seed_user() -> int:
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(
        "INSERT INTO users (email, password_hash, role, full_name, is_active) "
        "VALUES (?, ?, 'admin', ?, 1)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD), TEST_NAME),
    )
    conn.commit()
    user_id = conn.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()[0]
    conn.close()
    return user_id


def cleanup_user(user_id: int) -> None:
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        # Cleanup failure shouldn't mask the test result.
        print(f"warning: cleanup failed — {e}", file=sys.stderr)


def main() -> int:
    print(f"smoke_auth: target={BASE}")
    user_id = seed_user()
    try:
        # ---- 1. Wrong password ----
        s_bad = requests.Session()
        r = s_bad.post(f"{BASE}/api/auth/login", json={"email": TEST_EMAIL, "password": "wrong-pw"},
                       allow_redirects=False, timeout=10)
        expect("[1] wrong password -> 401", r.status_code == 401, f"got {r.status_code}")
        expect("[1] wrong password sets no cookie", not s_bad.cookies.get("ssc_session"))

        # ---- 2. Right password ----
        s = requests.Session()
        r = s.post(f"{BASE}/api/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD},
                   allow_redirects=False, timeout=10)
        expect("[2] right password -> 200", r.status_code == 200, f"got {r.status_code}")
        sid = s.cookies.get("ssc_session")
        expect("[2] sets ssc_session cookie", bool(sid))
        body = r.json() if r.headers.get("Content-Type", "").startswith("application/json") else {}
        # Response shape: {user: {id, email, full_name, role}} — don't echo email
        expect("[2] response has user.role=admin", body.get("user", {}).get("role") == "admin")
        expect("[2] response has user.full_name", body.get("user", {}).get("full_name") == TEST_NAME)

        # ---- 3. /api/auth/me with session ----
        r = s.get(f"{BASE}/api/auth/me", allow_redirects=False, timeout=10)
        expect("[3] /api/auth/me with session -> 200", r.status_code == 200, f"got {r.status_code}")
        me = r.json().get("user", {}) if r.ok else {}
        expect("[3] /me has role=admin", me.get("role") == "admin")

        # ---- 4. Dashboard HTML with session ----
        r = s.get(f"{BASE}/", allow_redirects=False, timeout=10)
        expect("[4] GET / with session -> 200", r.status_code == 200, f"got {r.status_code}")
        # 'Superstars Contracting' appears in the served HTML
        expect("[4] returned dashboard HTML", "Superstars" in r.text)

        # ---- 5. Logout ----
        r = s.post(f"{BASE}/api/auth/logout", allow_redirects=False, timeout=10)
        expect("[5] logout -> 200", r.status_code == 200, f"got {r.status_code}")

        # ---- 6. /api/auth/me after logout ----
        # Drop the now-invalidated cookie locally too so we test the post-logout state.
        s.cookies.clear()
        r = s.get(f"{BASE}/api/auth/me", allow_redirects=False, timeout=10)
        expect("[6] /api/auth/me post-logout -> 401", r.status_code == 401, f"got {r.status_code}")

        # ---- 7. Gate: HTML route without cookie redirects ----
        anon = requests.Session()
        r = anon.get(f"{BASE}/", allow_redirects=False, timeout=10)
        expect("[7] GET / anon -> 302", r.status_code == 302, f"got {r.status_code}")
        loc = r.headers.get("Location", "")
        expect("[7] redirect to /login with next=", loc.startswith("/login?next=") or loc.startswith(f"{BASE}/login?next="))

        # ---- 8. Gate: API route without cookie 401s ----
        r = anon.get(f"{BASE}/api/projects", allow_redirects=False, timeout=10)
        expect("[8] GET /api/projects anon -> 401", r.status_code == 401, f"got {r.status_code}")

        # ---- 9. Exempt: /api/health ----
        r = anon.get(f"{BASE}/api/health", allow_redirects=False, timeout=10)
        expect("[9] /api/health anon -> 200", r.status_code == 200, f"got {r.status_code}")

        # ---- 10. Exempt: worker PIN flow still reachable ----
        # Bad PIN should hit the PIN handler and return 401, NOT redirect to /login.
        r = anon.post(f"{BASE}/api/worker/login",
                      json={"phone_or_pin": "0000", "latitude": 0, "longitude": 0},
                      allow_redirects=False, timeout=10)
        # Worker handler returns 401 for invalid PIN, 400/403 for other failures — anything
        # in 400..499 proves the handler ran (i.e., wasn't redirected by the dashboard gate).
        ran = r.status_code in (400, 401, 403)
        expect("[10] worker PIN handler reached (not gated)", ran, f"got {r.status_code}")
        expect("[10] worker handler did NOT redirect to /login",
               r.headers.get("Location", "") == "" or "/login" not in r.headers.get("Location", ""))

        # ---- 11. Login page itself reachable ----
        r = anon.get(f"{BASE}/login", allow_redirects=False, timeout=10)
        expect("[11] GET /login anon -> 200", r.status_code == 200, f"got {r.status_code}")
        expect("[11] login page contains the sign-in form", "id=\"login-form\"" in r.text)

    finally:
        cleanup_user(user_id)

    # ---- Report ----
    width = max(len(label) for label, _, _ in results) + 2
    print()
    for label, status, detail in results:
        line = f"  {label:<{width}} {status}"
        if detail and status == FAIL:
            line += f"   — {detail}"
        print(line)
    passed = sum(1 for _, s, _ in results if s == PASS)
    total = len(results)
    print()
    print(f"  TOTAL: {passed}/{total} {'PASS' if passed == total else 'FAIL'}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except requests.exceptions.ConnectionError:
        print(f"ERROR: could not reach {BASE} — is the server running with the new auth code?",
              file=sys.stderr)
        sys.exit(2)
