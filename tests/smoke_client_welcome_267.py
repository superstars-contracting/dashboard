#!/usr/bin/env python3
"""#267 — client welcome/pending hard-stop containment guard (dual-backend).

Proves a `client` with NO access grants is fully contained, server-side:
  * ALLOWED (fail->pass contrast): /welcome (200, serves the branded lockup), the auth API
    (/api/auth/me 200), the public pings (/api/health), and the vendored static assets the
    welcome page loads (/files/static/brand/mark.svg 200).
  * EVERY OTHER PAGE -> 302 redirect to /welcome (/, /portal, /projects/<code>, /admin/*).
    The #264 portal is code-intact but NOT client-reachable — /portal now bounces to /welcome
    (the fail->pass: what was a 200 client surface is now contained).
  * EVERY DATA/API -> 403 (portal, crm, projects, company, admin).

Runs against SMOKE_BASE (the gate's isolated server); honors SSC_DB_URL for the direct DB
seed/verify. Synthetic-only client (SMK267-*, is_system=1, random per-run pw, must_reset=0,
NO pm_project_assignment). FK-safe teardown.
"""
from __future__ import annotations

import os
import sys
import secrets
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

import db_layer                     # noqa: E402
from auth import hash_password      # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PW = secrets.token_urlsafe(18)
CLIENT = "smk267-client@superstars.local"
PROJ = "SMK267-P"     # a project code for the /projects/<code> containment probe (need not exist)

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        row = conn.execute("SELECT id FROM users WHERE email=?", (CLIENT,)).fetchone()
        if row:
            conn.execute(
                "UPDATE users SET password_hash=?, role='client', is_active=1, status='active', "
                "must_reset_password=0, is_system=1, full_name='SMK267 Client' WHERE email=?",
                (hash_password(PW), CLIENT))
            uid = row[0]
        else:
            conn.execute(
                "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                "must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                (CLIENT, hash_password(PW), "client", "SMK267 Client"))
            uid = conn.execute("SELECT id FROM users WHERE email=?", (CLIENT,)).fetchone()[0]
        # NO grants: ensure no project assignment
        conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        r = conn.execute("SELECT id FROM users WHERE email=?", (CLIENT,)).fetchone()
        if r:
            uid = r[0]
            conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM login_audit WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM role_change_audit WHERE user_id=? OR changed_by=?", (uid, uid))
            conn.execute("DELETE FROM audit_log WHERE actor_user_id=?", (uid,))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
            conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


def _login():
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": CLIENT, "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def main():
    print(f"#267 client welcome hard-stop — BASE={BASE}  "
          f"backend={'postgres' if db_layer.is_postgres() else 'sqlite'}")
    _cleanup()
    _seed()
    try:
        s = _login()
        ok("client_login", s is not None)
        if not s:
            return 1

        # ---- ALLOWED: welcome + auth + static ----
        r = s.get(f"{BASE}/welcome", timeout=10)
        ok("welcome_200", r.status_code == 200)
        body = r.text if r.status_code == 200 else ""
        ok("welcome_serves_brand_lockup",
           ("brand/mark.svg" in body) and ("Triton" in body) and ("Welcome aboard" in body),
           "welcome page must render the canonical star + Superstars Triton wordmark")
        ok("auth_me_allowed_200", s.get(f"{BASE}/api/auth/me", timeout=10).status_code == 200)
        ok("health_allowed_200", s.get(f"{BASE}/api/health", timeout=10).status_code == 200)
        ok("static_mark_allowed_200",
           s.get(f"{BASE}/files/static/brand/mark.svg", timeout=10).status_code == 200)

        # ---- EVERY OTHER PAGE -> 302 redirect to /welcome ----
        PAGES = ["/", "/portal", f"/projects/{PROJ}", "/admin/users", "/admin/projects", "/projects"]
        for p in PAGES:
            r = s.get(f"{BASE}{p}", timeout=10, allow_redirects=False)
            loc = r.headers.get("Location", "")
            ok(f"page_redirects_to_welcome {p}",
               r.status_code in (301, 302, 303, 307, 308) and loc.rstrip("/").endswith("/welcome"),
               f"got {r.status_code} Location={loc!r}")

        # ---- fail->pass: the #264 portal is NO LONGER a reachable client surface ----
        r = s.get(f"{BASE}/portal", timeout=10, allow_redirects=False)
        ok("portal_no_longer_client_reachable",
           r.status_code != 200 and r.headers.get("Location", "").rstrip("/").endswith("/welcome"))

        # ---- EVERY DATA/API -> 403 ----
        APIS = ["/api/portal/project", "/api/portal/photos", "/api/crm/organizations",
                "/api/crm/needs-attention", "/api/projects", "/api/company/summary",
                "/api/admin/users", f"/api/projects/{PROJ}/on-site"]
        for a in APIS:
            ok(f"api_403 {a}", s.get(f"{BASE}{a}", timeout=10).status_code == 403)

        print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        if FAIL:
            print("FAILURES: " + ", ".join(FAIL))
        print("OVERALL:", "PASS" if not FAIL else "FAIL")
        return 0 if not FAIL else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
