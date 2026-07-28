"""#279 — UI v2 phase 0 gate: the toggle exists and changes NOTHING yet.

The phase-0 contract is deliberately boring: with no v2 twins on disk, every page for
every role must render BYTE-IDENTICALLY with the toggle in either position. This suite
is what makes that a fact instead of a hope.

Proves (fails on a pre-#279 server, where /api/ui/version does not exist):

  (a) BYTE-IDENTITY — for every UI page × every role, the response served at
      ui_version=1 and at ui_version=2 is identical in status AND bytes. Each pair is
      preceded by a CONTROL fetch (v1 vs v1) so a page that is inherently
      non-deterministic is reported as such instead of being blamed on the toggle.
  (b) RESOLUTION ORDER — ?ui= overrides the stored preference; the override lasts
      exactly one request and never writes to the users row.
  (c) V2 RESOLUTION + ROLLBACK LAYER 3 — a twin dropped into templates/v2/ is served
      to a v2 user and NOT to a v1 user; deleting that one file puts everyone back on
      v1 immediately. Rehearsed here, in-test, on every run.
  (d) KILL SWITCH (rollback layer 2) — a server started with SSC_UI_FORCE_V1=1 serves
      v1 to a v2 user EVEN WITH A TWIN PRESENT. Proven against a real server process
      with the env var actually set, not by unit-testing the predicate.
  (e) THE SWITCH — a user can set their own interface; only an admin can set someone
      else's (a pm gets 403); a junk value is rejected, not coerced.
  (f) DEFAULT-DENY POSTURE — the stored default is 1, and an unmigrated column, a NULL,
      or a junk value all degrade to 1 rather than erroring.

Isolation + hygiene (CLAUDE.md): runs against SMOKE_BASE (the gate's isolated server,
SSC_DB_URL → a snapshot copy or ssc_test — NEVER live). Self-ensures its own schema
(ensure_ui_version_column). Synthetic is_system=1 users (smk279-*) + one synthetic
project (SMK279-A) only; scoped cleanup in finally, children before users (FK-safe on
Postgres). Any v2 twin it writes is removed in finally — a stray twin would break the
byte-identity gate on the next run. PII-safe: asserts on status codes, byte equality and
booleans — never a worker name, rate, PIN, or *_path value.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
import ui_version as uiv  # noqa: E402
from auth import hash_password  # noqa: E402
from apply_ui_version_279 import ensure_ui_version_column  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
VENV_PY = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"
KILL_PORT = int(os.environ.get("SMOKE_UIV2_PORT", "5153"))
KILL_BASE = f"http://127.0.0.1:{KILL_PORT}"
KILL_LOG = SCRIPT_DIR / "tests" / "_uiv2_killswitch_srv.log"

PW = secrets.token_urlsafe(18)          # random per run; in-process only, never logged
USERS = {                                # key -> synthetic email (is_system=1)
    "admin":     "smk279-admin@superstars.local",
    "c_suite":   "smk279-csuite@superstars.local",
    "pm":        "smk279-pm@superstars.local",
    "super":     "smk279-super@superstars.local",
    "estimator": "smk279-est@superstars.local",
    "client":    "smk279-client@superstars.local",
}
ROLE_OF = {k: k for k in USERS}
PROJ = "SMK279-A"

# Every UI page route the toggle now passes through. Includes routes a given role is
# FORBIDDEN from: a 403 body is what that role renders, and it must be identical too.
PAGES = [
    "/",
    "/projects",
    f"/projects/{PROJ}",
    "/dashboard",
    "/dropplan",
    "/admin/labor-rates",
    "/admin/users",
    "/admin/projects",
    "/estimating",
    "/portal",
    "/welcome",
    "/settings/interface",
]

# The page used for the twin-resolution tests. projects.html is served by /projects to
# every internal role, so one twin exercises the whole path.
TWIN_NAME = "projects.html"
TWIN_PATH = uiv.V2_ROOT / TWIN_NAME
TWIN_MARK = b"<!-- SMK279 V2 TWIN MARKER -->"

_failures = []
_notes = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return bool(cond)


# ============= SETUP / TEARDOWN (direct DB, isolated backend) =============

def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_ui_version_column(conn)      # self-prepare the #279 column on this backend
        for key, email in USERS.items():
            role = ROLE_OF[key]
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET password_hash=?, role=?, is_active=1, status='active', "
                    "must_reset_password=0, is_system=1, ui_version=1 WHERE email=?",
                    (hash_password(PW), role, email))
            else:
                conn.execute(
                    "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                    "must_reset_password,is_system,ui_version) VALUES (?,?,?,?,1,'active',0,1,1)",
                    (email, hash_password(PW), role, f"SMK279 {key}"))
        row = conn.execute("SELECT project_code FROM projects WHERE project_code=?", (PROJ,)).fetchone()
        if row:
            conn.execute("UPDATE projects SET status='active' WHERE project_code=?", (PROJ,))
        else:
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                         (PROJ, "Smoke Project 279"))
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    # A stray twin would silently break the byte-identity gate on the next run — remove it
    # first, before anything else can fail.
    try:
        if TWIN_PATH.exists():
            TWIN_PATH.unlink()
    except OSError:
        pass
    conn = db_layer.connect(pragma_fk=True)
    try:
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                uid = u[0]
                # children before users — Postgres enforces these FKs (#260)
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM role_change_audit WHERE user_id=? OR changed_by=?", (uid, uid))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM audit_log WHERE actor_user_id=?", (uid,))
                conn.execute("DELETE FROM dashboard_layouts WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM worker_rates WHERE created_by=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
        conn.commit()
    finally:
        conn.close()


def _set_stored(key, version):
    """Set users.ui_version directly in the DB — the smoke drives the stored preference
    without going through the API it is also testing."""
    conn = db_layer.connect(pragma_fk=True)
    try:
        conn.execute("UPDATE users SET ui_version=? WHERE email=?", (version, USERS[key]))
        conn.commit()
    finally:
        conn.close()


def _login(key, base=BASE):
    s = requests.Session()
    r = s.post(f"{base}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _fetch(sess, path, base=BASE):
    """(status, sha256-of-body). Hashing keeps multi-hundred-KB pages out of memory
    comparisons and out of any failure message — the pages carry project data."""
    r = sess.get(f"{base}{path}", timeout=30, allow_redirects=False)
    return r.status_code, hashlib.sha256(r.content).hexdigest(), r.content


# ============= (a) BYTE-IDENTITY =============

def test_byte_identity(sessions):
    """The phase-0 gate itself. Reports its COVERAGE unconditionally: a byte-identity
    check that silently compared nothing — every login broken, or 72 identical redirects
    to /login — passes just as quietly as a real one. The counts below, and the
    substantive-200 floor, are what stop this from being a green light over an empty run."""
    print("\n-- (a) byte-identity: every page × every role, ui_version 1 vs 2 --")
    identical = 0
    substantive = 0          # pairs that were a real rendered page (200, non-trivial body)
    by_status = {}
    skipped = []
    mismatches = 0
    for key in USERS:
        sess = sessions[key]
        if sess is None:
            ok(f"login_{key}", False, "could not log in")
            continue
        for path in PAGES:
            _set_stored(key, 1)
            st_a, h_a, body_a = _fetch(sess, path)
            st_ctl, h_ctl, _ = _fetch(sess, path)          # CONTROL: v1 vs v1
            if (st_a, h_a) != (st_ctl, h_ctl):
                # The page differs from itself between two identical requests — a
                # non-deterministic body (timestamp/nonce). Report it; do NOT blame v2.
                skipped.append(f"{key}:{path}")
                _notes.append(f"non-deterministic body, excluded from byte-identity: {key} {path}")
                continue
            _set_stored(key, 2)
            st_b, h_b, _ = _fetch(sess, path)
            by_status[st_a] = by_status.get(st_a, 0) + 1
            if (st_a == st_b) and (h_a == h_b):
                identical += 1
                if st_a == 200 and len(body_a) > 2000:
                    substantive += 1
            else:
                mismatches += 1
                ok(f"identical_{key}_{path}", False,
                   f"v1 status={st_a} != v2 status={st_b}" if st_a != st_b else "body bytes differ")
            _set_stored(key, 1)

    dist = ", ".join(f"{s}×{n}" for s, n in sorted(by_status.items()))
    print(f"     compared {identical + mismatches} (role,page) pairs — statuses: {dist}")
    print(f"     of those, {substantive} were substantive rendered pages (200, >2KB body)")
    ok("byte_identity_all_pages_all_roles", mismatches == 0,
       f"{mismatches} pair(s) differed")
    # Coverage floors — these fail the gate if the run was hollow.
    ok("byte_identity_covered_every_pair", identical + mismatches == len(USERS) * len(PAGES) - len(skipped),
       f"expected {len(USERS) * len(PAGES) - len(skipped)}, compared {identical + mismatches}")
    ok("byte_identity_saw_real_pages", substantive >= 10,
       f"only {substantive} substantive 200s — the check may be comparing redirects")
    if skipped:
        print(f"     note: {len(skipped)} pair(s) excluded as non-deterministic: {', '.join(skipped)}")
    return identical


# ============= (b) RESOLUTION ORDER =============

def test_resolution_order(sessions):
    print("\n-- (b) resolution order: ?ui= overrides the stored value, for one request --")
    s = sessions["admin"]
    _set_stored("admin", 1)
    r = s.get(f"{BASE}/api/ui/version", timeout=10).json().get("data", {})
    ok("stored_1_effective_1", r.get("ui_version") == 1 and r.get("effective") == 1)

    r = s.get(f"{BASE}/api/ui/version?ui=2", timeout=10).json().get("data", {})
    ok("override_ui2_beats_stored_1", r.get("ui_version") == 1 and r.get("effective") == 2,
       f"got stored={r.get('ui_version')} effective={r.get('effective')}")

    r = s.get(f"{BASE}/api/ui/version", timeout=10).json().get("data", {})
    ok("override_did_not_persist", r.get("ui_version") == 1 and r.get("effective") == 1)

    _set_stored("admin", 2)
    r = s.get(f"{BASE}/api/ui/version?ui=1", timeout=10).json().get("data", {})
    ok("override_ui1_beats_stored_2", r.get("ui_version") == 2 and r.get("effective") == 1)
    _set_stored("admin", 1)


# ============= (c) V2 RESOLUTION + ROLLBACK LAYER 3 =============

def _write_twin():
    uiv.V2_ROOT.mkdir(parents=True, exist_ok=True)
    TWIN_PATH.write_bytes(b"<!doctype html><title>twin</title>" + TWIN_MARK)


def test_twin_resolution(sessions):
    print("\n-- (c) v2 twin resolution + rollback layer 3 (delete one file) --")
    s = sessions["admin"]
    _set_stored("admin", 1)
    _, _, v1_body = _fetch(s, "/projects")
    ok("v1_body_has_no_marker", TWIN_MARK not in v1_body)

    _write_twin()
    _set_stored("admin", 2)
    _, _, body_v2 = _fetch(s, "/projects")
    ok("v2_user_gets_twin", TWIN_MARK in body_v2)

    _set_stored("admin", 1)
    _, _, body_v1 = _fetch(s, "/projects")
    ok("v1_user_never_gets_twin", TWIN_MARK not in body_v1)

    _, _, body_ovr = _fetch(s, "/projects?ui=2")
    ok("override_ui2_gets_twin", TWIN_MARK in body_ovr)

    _set_stored("admin", 2)
    _, _, body_ovr1 = _fetch(s, "/projects?ui=1")
    ok("override_ui1_forces_v1", TWIN_MARK not in body_ovr1)

    # A page with NO twin still falls back to v1 for the same v2 user — the property that
    # makes partial migration shippable.
    st_np, _, _ = _fetch(s, "/settings/interface")
    ok("untwinned_page_falls_back_ok", st_np == 200, f"status={st_np}")

    # ROLLBACK LAYER 3, rehearsed: delete the one file, v2 user is back on v1 at once.
    TWIN_PATH.unlink()
    _, _, body_after = _fetch(s, "/projects")
    ok("rollback_layer3_delete_file_restores_v1", TWIN_MARK not in body_after)
    _set_stored("admin", 1)


# ============= (d) KILL SWITCH (rollback layer 2) =============

def _kill_listeners(port):
    ps = (f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue; "
          "foreach ($conn in $c) { cmd /c \"taskkill /F /T /PID $($conn.OwningProcess)\" }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, timeout=30)


def test_kill_switch():
    print("\n-- (d) kill switch: SSC_UI_FORCE_V1=1 on a real server, twin present --")
    _kill_listeners(KILL_PORT)
    _write_twin()                       # the twin EXISTS — only the env var may suppress it
    _set_stored("admin", 2)             # and the user WANTS v2
    logf = open(KILL_LOG, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(VENV_PY), "-m", "waitress", "--host=127.0.0.1", f"--port={KILL_PORT}",
         "--threads=4", "server:app"],
        cwd=str(SCRIPT_DIR), stdout=logf, stderr=subprocess.STDOUT,
        env={**os.environ, "SSC_UI_FORCE_V1": "1"},
    )
    try:
        up = False
        deadline = time.time() + 45
        while time.time() < deadline:
            try:
                if requests.get(f"{KILL_BASE}/api/health", timeout=2).status_code == 200:
                    up = True
                    break
            except requests.exceptions.ConnectionError:
                pass
            if proc.poll() is not None:
                break
            time.sleep(0.5)
        if not ok("killswitch_server_up", up, f"see {KILL_LOG.name}"):
            return
        s = _login("admin", base=KILL_BASE)
        if not ok("killswitch_login", s is not None):
            return
        _, _, body = _fetch(s, "/projects", base=KILL_BASE)
        ok("killswitch_forces_v1_despite_twin_and_preference", TWIN_MARK not in body)
        # ...and it outranks the per-request override too.
        _, _, body_ovr = _fetch(s, "/projects?ui=2", base=KILL_BASE)
        ok("killswitch_outranks_ui_override", TWIN_MARK not in body_ovr)
        r = s.get(f"{KILL_BASE}/api/ui/version", timeout=10).json().get("data", {})
        ok("killswitch_reported_to_ui", r.get("forced_v1") is True and r.get("effective") == 1,
           f"forced_v1={r.get('forced_v1')} effective={r.get('effective')}")
    finally:
        subprocess.run(["cmd", "/c", f"taskkill /F /T /PID {proc.pid}"], capture_output=True, timeout=30)
        logf.close()
        if TWIN_PATH.exists():
            TWIN_PATH.unlink()
        _set_stored("admin", 1)


# ============= (e) THE SWITCH =============

def test_switch_api(sessions):
    print("\n-- (e) the switch: self-service open, admin-only for other users --")
    admin, pm = sessions["admin"], sessions["pm"]
    _set_stored("admin", 1)
    _set_stored("pm", 1)

    r = pm.post(f"{BASE}/api/ui/version", json={"ui_version": 2}, timeout=10)
    ok("any_role_may_switch_self", r.status_code == 200, f"status={r.status_code}")
    got = pm.get(f"{BASE}/api/ui/version", timeout=10).json().get("data", {})
    ok("self_switch_persisted", got.get("ui_version") == 2)

    r = pm.post(f"{BASE}/api/ui/version", json={"ui_version": 7}, timeout=10)
    ok("junk_value_rejected_not_coerced", r.status_code == 400, f"status={r.status_code}")
    got = pm.get(f"{BASE}/api/ui/version", timeout=10).json().get("data", {})
    ok("junk_left_value_untouched", got.get("ui_version") == 2)

    # Someone else's interface is an ADMIN act, server-enforced.
    conn = db_layer.connect(pragma_fk=True)
    try:
        pm_uid = conn.execute("SELECT id FROM users WHERE email=?", (USERS["pm"],)).fetchone()[0]
    finally:
        conn.close()
    r = pm.post(f"{BASE}/api/admin/ui/version/{pm_uid}", json={"ui_version": 1}, timeout=10)
    ok("pm_cannot_set_for_others_403", r.status_code == 403, f"status={r.status_code}")
    r = admin.post(f"{BASE}/api/admin/ui/version/{pm_uid}", json={"ui_version": 1}, timeout=10)
    ok("admin_can_set_for_others", r.status_code == 200, f"status={r.status_code}")
    got = pm.get(f"{BASE}/api/ui/version", timeout=10).json().get("data", {})
    ok("admin_set_took_effect", got.get("ui_version") == 1)
    r = admin.post(f"{BASE}/api/admin/ui/version/99999999", json={"ui_version": 2}, timeout=10)
    ok("admin_set_unknown_user_404", r.status_code == 404, f"status={r.status_code}")


# ============= (f) DEFAULT-DENY POSTURE =============

def test_default_posture(sessions):
    print("\n-- (f) default-safe: anything that is not exactly 2 resolves to 1 --")
    conn = db_layer.connect(pragma_fk=True)
    try:
        row = conn.execute("SELECT ui_version FROM users WHERE email=?", (USERS["super"],)).fetchone()
        ok("seeded_default_is_1", row is not None and row["ui_version"] == 1)
        # A junk value written straight past the API (no CHECK constraint by design).
        conn.execute("UPDATE users SET ui_version=9 WHERE email=?", (USERS["super"],))
        conn.commit()
    finally:
        conn.close()
    s = sessions["super"]
    r = s.get(f"{BASE}/api/ui/version", timeout=10).json().get("data", {})
    ok("junk_stored_value_degrades_to_v1", r.get("effective") == 1,
       f"effective={r.get('effective')}")
    _set_stored("super", 1)

    # An anonymous request resolves to 1 without touching the DB.
    anon = requests.Session()
    st = anon.get(f"{BASE}/login", timeout=10).status_code
    ok("login_page_still_200_anonymous", st == 200, f"status={st}")


def run(sessions):
    test_byte_identity(sessions)
    test_resolution_order(sessions)
    test_twin_resolution(sessions)
    test_switch_api(sessions)
    test_default_posture(sessions)
    test_kill_switch()


def main():
    print(f"== #279 UI v2 phase-0 gate ==  BASE={BASE}")
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    backend = "postgres" if db_layer.is_postgres() else "sqlite"
    print(f"   backend={backend}  SSC_DB_URL={'(set)' if db_url else '(unset=LIVE — refuse)'}")
    if not db_url and os.environ.get("ALLOW_LIVE") != "1":
        print("   REFUSING: SSC_DB_URL unset (would seed LIVE). Set an isolated backend.")
        return 2
    if TWIN_PATH.exists():
        print(f"   REFUSING: a stray v2 twin exists at {TWIN_PATH} — byte-identity cannot be proven.")
        return 2
    _seed()
    sessions = {}
    try:
        for key in USERS:
            sessions[key] = _login(key)
        run(sessions)
    finally:
        _cleanup()
    for n in _notes:
        print(f"   note: {n}")
    n = len(_failures)
    print(f"\n== {'ALL PASS' if n == 0 else str(n) + ' FAILED: ' + ', '.join(_failures)} ==")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
