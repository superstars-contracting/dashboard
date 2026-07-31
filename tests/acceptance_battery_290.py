"""#290 (Cloud M4) — the acceptance battery. Runs FROM THE WORKSTATION against
the cloud service URL and reports pass/fail per probe.

Usage (from the dashboard dir):

  # Phase PRE — right after first boot, before any data lands. Connectivity,
  # auth gate, static assets, timezone. No DB access, no writes anywhere.
  venv\\Scripts\\python.exe tests\\acceptance_battery_290.py https://<service>.onrender.com

  # Phase FULL — after the DB rehearsal (and media transfer, for the media
  # probes). Adds synthetic-login, PDF-via-chromium, portal containment,
  # photo + DCR render probes. Requires SSC_DB_URL in THIS terminal set to
  # the Render Postgres EXTERNAL connection string (operator sets it from
  # 1Password — never in a committed file):
  #   $env:SSC_DB_URL = "<external postgres URL from 1Password>"
  venv\\Scripts\\python.exe tests\\acceptance_battery_290.py https://<service>.onrender.com --phase full

Synthetic fixtures only: the full phase seeds is_system=1 users
(m4battery-*@superstars.local) with per-run random passwords directly into the
CLOUD database, and deletes them (plus their grants/assignments/sessions) in a
finally block. It refuses to run against anything but a Postgres SSC_DB_URL —
the workstation's live SQLite can never be touched by this script. No real
credentials are used or asked for, ever. Output is PII-safe: statuses, counts,
ids, byte sizes — never names, paths, or real emails.
"""
from __future__ import annotations

import argparse
import io
import os
import re
import secrets
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

EASTERN = ZoneInfo("America/New_York")
ADMIN_EMAIL = "m4battery-admin@superstars.local"
CLIENT_EMAIL = "m4battery-client@superstars.local"
PW = secrets.token_urlsafe(18)          # per-run, in-process only, never logged

RESULTS: list[tuple[str, str, str]] = []   # (probe, PASS/FAIL/SKIP, detail)


def record(name: str, ok: bool | None, detail: str = "") -> None:
    status = "SKIP" if ok is None else ("PASS" if ok else "FAIL")
    RESULTS.append((name, status, detail))
    print(f"  {status:4}  {name}" + (f"  [{detail}]" if detail else ""))


def probe(name):
    """Decorator: run the probe, record an exception as FAIL, never abort the
    battery mid-run."""
    def wrap(fn):
        def run(*a, **kw):
            try:
                fn(*a, **kw)
            except Exception as e:
                record(name, False, f"{e.__class__.__name__}: {str(e)[:120]}")
        return run
    return wrap


# ============= PRE-PHASE PROBES (no DB, no writes) =============

def p_health(base):
    r = requests.get(f"{base}/api/health", timeout=20)
    d = (r.json().get("data") or {}) if r.status_code == 200 else {}
    record("health-200", r.status_code == 200 and d.get("status") == "ok",
           f"status={r.status_code}")


def p_login_page(base):
    r = requests.get(f"{base}/login", timeout=20)
    ok = (r.status_code == 200 and "text/html" in (r.headers.get("Content-Type") or "")
          and "password" in r.text.lower() and "superstars" in r.text.lower())
    record("login-page-renders", ok, f"status={r.status_code} bytes={len(r.content)}")


def p_auth_gate(base):
    r = requests.get(f"{base}/api/projects", timeout=20)
    record("auth-gate-api-401", r.status_code == 401,
           f"status={r.status_code}")
    r2 = requests.get(f"{base}/", timeout=20, allow_redirects=False)
    record("auth-gate-html-302-login",
           r2.status_code in (301, 302) and "/login" in (r2.headers.get("Location") or ""),
           f"status={r2.status_code}")


def p_static(base):
    ok_all, detail = True, []
    for rel in ("css/widgets.css", "js/dash_layout.js"):
        r = requests.get(f"{base}/files/static/{rel}", timeout=20)
        good = r.status_code == 200 and len(r.content) > 500
        ok_all = ok_all and good
        detail.append(f"{rel.split('/')[-1]}:{r.status_code}/{len(r.content)}b")
    record("static-assets", ok_all, " ".join(detail))


def p_worker_app_shell(base):
    # /worker-app.html is the real worker entry point (the bare /worker-app is
    # auth-exempted defensively but has never had a route — 404 on the
    # workstation too; verified against live 2026-07-30).
    r = requests.get(f"{base}/worker-app.html", timeout=20)
    record("worker-app-public-shell", r.status_code == 200 and len(r.content) > 1000,
           f"status={r.status_code} bytes={len(r.content)}")


def p_timezone(base):
    got = expected = None
    for _ in range(2):                      # midnight-safe double-read
        before = datetime.now(EASTERN).date().isoformat()
        r = requests.get(f"{base}/api/today", timeout=20)
        got = (r.json().get("data") or {}).get("date") if r.status_code == 200 else None
        after = datetime.now(EASTERN).date().isoformat()
        if before == after:
            expected = before
            break
    record("timezone-eastern-today", got is not None and got == expected,
           f"server={got} eastern={expected}")


# ============= FULL-PHASE HELPERS (cloud DB via SSC_DB_URL) =============

def cloud_db():
    import db_layer
    if not db_layer.is_postgres():
        raise RuntimeError(
            "SSC_DB_URL is not a Postgres URL — the full phase runs ONLY against "
            "the cloud database (set the Render EXTERNAL connection string in "
            "this terminal from 1Password).")
    return db_layer.connect()


def seed_fixtures(project_code):
    from auth import hash_password
    conn = cloud_db()
    try:
        ids = {}
        for email, role in ((ADMIN_EMAIL, "admin"), (CLIENT_EMAIL, "client")):
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET password_hash=?, role=?, is_active=1, status='active', "
                    "must_reset_password=0, is_system=1 WHERE email=?",
                    (hash_password(PW), role, email))
                ids[role] = row[0]
            else:
                conn.execute(
                    "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                    "must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                    (email, hash_password(PW), role, f"M4 Battery {role}"))
                ids[role] = conn.execute("SELECT id FROM users WHERE email=?",
                                         (email,)).fetchone()[0]
        # client binds to the project via assignment; grants start at ZERO
        conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (ids["client"],))
        conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, "
                     "assigned_at) VALUES (?,?,?,?)",
                     (ids["client"], project_code, ids["admin"],
                      datetime.now().isoformat(timespec="seconds")))
        conn.execute("DELETE FROM client_section_grant WHERE user_id=?", (ids["client"],))
        conn.commit()
        return ids
    finally:
        conn.close()


def cleanup_fixtures():
    try:
        conn = cloud_db()
    except Exception:
        return
    try:
        for email in (ADMIN_EMAIL, CLIENT_EMAIL):
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if not row:
                continue
            uid = row[0]
            for sql in ("DELETE FROM client_section_grant WHERE user_id=?",
                        "DELETE FROM pm_project_assignment WHERE user_id=?",
                        "DELETE FROM sessions WHERE user_id=?",
                        "DELETE FROM users WHERE id=?"):
                try:
                    conn.execute(sql, (uid,))
                except Exception:
                    pass
        conn.commit()
        print("  [fixtures cleaned]")
    finally:
        conn.close()


def login(base, email):
    s = requests.Session()
    r = s.post(f"{base}/api/auth/login", json={"email": email, "password": PW}, timeout=20)
    if r.status_code != 200 or not s.cookies.get("ssc_session"):
        raise RuntimeError(f"synthetic login failed status={r.status_code}")
    return s, r


# ============= FULL-PHASE PROBES =============

def p_synthetic_login(base, admin_ref):
    s, r = login(base, ADMIN_EMAIL)
    setck = r.headers.get("Set-Cookie") or ""
    record("synthetic-admin-login", True, "cookie ok")
    record("session-cookie-secure-flag", "Secure" in setck,
           "Set-Cookie carries Secure behind the TLS edge")
    me = s.get(f"{base}/api/auth/me", timeout=20)
    d = (me.json().get("user") or {}) if me.status_code == 200 else {}
    record("auth-me-admin", me.status_code == 200 and d.get("role") == "admin",
           f"status={me.status_code}")
    admin_ref["s"] = s


def p_authed_api(base, admin):
    r = admin.get(f"{base}/api/projects", timeout=30)
    ok = r.status_code == 200
    n = None
    if ok:
        d = r.json()
        arr = d.get("data") if isinstance(d, dict) else d
        n = len(arr) if isinstance(arr, list) else "obj"
    record("authed-api-projects", ok, f"status={r.status_code} projects={n}")


def p_pdf_chromium(base, admin):
    t = time.time()
    r = admin.get(f"{base}/api/payroll/hours.pdf", timeout=180)
    dt = time.time() - t
    ok = r.status_code == 200 and r.content[:5] == b"%PDF-"
    pages = 0
    if ok:
        try:
            from pypdf import PdfReader
            pages = len(PdfReader(io.BytesIO(r.content)).pages)
        except Exception:
            pages = -1
    record("pdf-export-chromium", ok and pages >= 1,
           f"status={r.status_code} bytes={len(r.content)} pages={pages} {dt:.1f}s")


def p_portal_containment(base, project, ids, client_ref):
    # unauthenticated portal -> login redirect
    r = requests.get(f"{base}/portal/{project}", timeout=20, allow_redirects=False)
    record("portal-anon-302-login",
           r.status_code in (301, 302) and "/login" in (r.headers.get("Location") or ""),
           f"status={r.status_code}")

    cs, _ = login(base, CLIENT_EMAIL)
    client_ref["s"] = cs

    # ZERO grants -> the #267 hard-stop: page contained on /welcome, APIs 403
    r = cs.get(f"{base}/portal/{project}", timeout=20, allow_redirects=False)
    record("zero-grant-portal-302-welcome",
           r.status_code in (301, 302) and "/welcome" in (r.headers.get("Location") or ""),
           f"status={r.status_code}")
    r = cs.get(f"{base}/api/portal/{project}/progress", timeout=20)
    record("zero-grant-api-403", r.status_code == 403, f"status={r.status_code}")

    # client NEVER reaches internal APIs (grants or not)
    r = cs.get(f"{base}/api/projects", timeout=20)
    record("client-internal-api-403", r.status_code == 403, f"status={r.status_code}")


def p_portal_granted(base, project, ids, admin, client):
    for section in ("progress", "daily"):
        g = admin.post(f"{base}/api/admin/client-grants",
                       json={"user_id": ids["client"], "section": section, "on": True},
                       timeout=20)
        if g.status_code not in (200, 201):
            record(f"grant-{section}", False, f"status={g.status_code}")
            return
    record("grant-progress+daily", True)

    r = client.get(f"{base}/portal/{project}", timeout=20)
    record("granted-portal-shell-200", r.status_code == 200 and len(r.content) > 5000,
           f"status={r.status_code} bytes={len(r.content)}")
    r = client.get(f"{base}/api/portal/{project}/progress", timeout=30)
    record("granted-progress-api-200", r.status_code == 200, f"status={r.status_code}")
    # ungranted section stays closed
    r = client.get(f"{base}/api/portal/{project}/photos", timeout=20)
    record("ungranted-photos-api-403", r.status_code == 403, f"status={r.status_code}")


def p_dcr_render(base, project, client):
    conn = cloud_db()
    try:
        row = conn.execute(
            "SELECT MAX(dcr_sequence) FROM report_index WHERE project_code=? "
            "AND report_type='DCR' AND status='issued'", (project,)).fetchone()
    finally:
        conn.close()
    seq = row[0] if row else None
    if not seq:
        record("dcr-client-render", None, "no issued DCRs in cloud DB yet")
        return
    r = client.get(f"{base}/api/portal/{project}/daily/{seq}/view", timeout=60)
    ok = (r.status_code == 200 and "DCR" in r.text and len(r.content) > 10_000)
    record("dcr-client-render", ok,
           f"seq={seq} status={r.status_code} bytes={len(r.content)}")


def p_photo_serves(base, project, admin):
    conn = cloud_db()
    try:
        rows = conn.execute(
            "SELECT id FROM field_photos WHERE project_code=? ORDER BY id DESC LIMIT 5",
            (project,)).fetchall()
    finally:
        conn.close()
    if not rows:
        record("photo-serves-from-disk", None, "no field_photos rows in cloud DB yet")
        return
    def looks_like_image(b: bytes) -> bool:
        return (b[:2] == b"\xff\xd8"            # JPEG
                or b[:4] == b"\x89PNG"[:4]      # PNG
                or b[:4] == b"RIFF"             # WEBP
                or b[4:8] == b"ftyp")           # HEIC/HEIF container
    for row in rows:
        pid = row[0]
        r = admin.get(f"{base}/api/field-photos/{pid}/file", timeout=30)
        if r.status_code == 200 and len(r.content) > 1000 and looks_like_image(r.content[:8]):
            record("photo-serves-from-disk", True,
                   f"id={pid} bytes={len(r.content)}")
            return
    record("photo-serves-from-disk", False,
           f"none of newest {len(rows)} photo ids served bytes (media tree on disk?)")


# ============= MAIN =============

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("base", help="https://<service>.onrender.com")
    ap.add_argument("--phase", choices=("pre", "full"), default="pre")
    ap.add_argument("--project", default="FR-BX-001")
    args = ap.parse_args()
    base = args.base.rstrip("/")
    if not base.startswith("https://"):
        print("refusing: base URL must be https")
        return 2

    print(f"=== M4 acceptance battery — {args.phase.upper()} phase against "
          f"{urlparse(base).hostname} ===")

    probe("health-200")(p_health)(base)
    probe("login-page-renders")(p_login_page)(base)
    probe("auth-gate")(p_auth_gate)(base)
    probe("static-assets")(p_static)(base)
    probe("worker-app-public-shell")(p_worker_app_shell)(base)
    probe("timezone-eastern-today")(p_timezone)(base)

    if args.phase == "full":
        ids = None
        admin_ref, client_ref = {}, {}
        try:
            ids = seed_fixtures(args.project)
            print(f"  [fixtures seeded: admin id={ids['admin']} client id={ids['client']}]")
            probe("synthetic-admin-login")(p_synthetic_login)(base, admin_ref)
            admin = admin_ref.get("s")
            if admin is None:
                record("full-phase", False, "no admin session — remaining probes skipped")
            else:
                probe("authed-api-projects")(p_authed_api)(base, admin)
                probe("pdf-export-chromium")(p_pdf_chromium)(base, admin)
                probe("portal-containment")(p_portal_containment)(base, args.project,
                                                                  ids, client_ref)
                client = client_ref.get("s")
                if client is not None:
                    probe("portal-granted")(p_portal_granted)(base, args.project, ids,
                                                              admin, client)
                    probe("dcr-client-render")(p_dcr_render)(base, args.project, client)
                probe("photo-serves-from-disk")(p_photo_serves)(base, args.project, admin)
        finally:
            cleanup_fixtures()

    print("\n=== battery summary ===")
    npass = nfail = nskip = 0
    for name, status, detail in RESULTS:
        print(f"  {status:4}  {name:34} {detail}")
        npass += status == "PASS"
        nfail += status == "FAIL"
        nskip += status == "SKIP"
    print(f"=== {npass} pass / {nfail} fail / {nskip} skip ===")
    return 0 if nfail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
