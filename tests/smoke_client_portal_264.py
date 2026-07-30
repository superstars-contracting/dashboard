"""#264 default-deny VISIBILITY ENGINE guard — #267 contains clients to /welcome. Dual-backend.

The most security-sensitive surface in the app. #267 hard-contains a `client` to the welcome
page (the portal is code-intact but NOT client-reachable yet), so this guard now verifies the
default-deny ENGINE via its predicate (the exact functions the portal endpoints call) + the
curated serializer directly, plus the client's containment:

  (a) DEFAULT-DENY ENGINE: a photo with no client share is NOT in the visible set; sharing it
      flips the predicate to visible; red-flag (take offline) flips it back. (literal fail->pass)
  (b) PER-RESOURCE ISOLATION (closes the #263 by-ID gap): visibility.photo_visible_to_client is
      True for a SHARED in-project photo but False for an UNSHARED one, a RED-FLAGGED one, and
      an OTHER-PROJECT photo (even one carrying a client share row).
  (c) #267 CONTAINMENT: the client's every PAGE (/, /portal, /projects/<code>, /admin/*) → 302
      redirect to /welcome; every DATA/API (portal, internal project, drop plan, expenses,
      company, admin, by-id) → 403. The portal is no longer a reachable client surface.
  (d) CURATED-ONLY serializer: client_portal._portal_photo emits ONLY curated keys — never
      cost / labor / rate / worker PII / *_path / internal fields (the payload guarantee for
      when the portal returns online per-section).
  READ-ONLY: the client cannot share, red-flag, or patch (403).
  PER-RESOURCE WRITE: a pm may share a photo on an ASSIGNED project but 403 on a project
      they aren't assigned to (the share endpoint re-derives the photo's project).

Isolation + hygiene (CLAUDE.md): runs against SMOKE_BASE (the gate's isolated server —
NEVER live). Self-ensures its schema. Synthetic is_system=1 users (smk264-*) + projects
(SMK264-*) + photos + their on-disk files under a synthetic project dir; scoped cleanup in
finally (children first — FK-safe on Postgres). PII-safe: asserts on status / counts /
booleans / curated keys — never a worker name, rate, PIN, or path value.
"""
from __future__ import annotations

import os
import secrets
import sys
import uuid
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))


import db_layer  # noqa: E402
import ssc_paths  # noqa: E402  # #287
from auth import hash_password, _now_iso  # noqa: E402
from apply_pm_assignment_263 import ensure_pm_assignment_schema  # noqa: E402
from apply_item_visibility_264 import ensure_item_visibility_schema  # noqa: E402
import visibility  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
_FP_BASE = ssc_paths.under_root("data_room", "field_photos")   # #287

PW = secrets.token_urlsafe(18)
USERS = {
    "admin":  "smk264-admin@superstars.local",
    "pm":     "smk264-pm@superstars.local",     # assigned to A
    "pm2":    "smk264-pm2@superstars.local",    # NOT assigned to A
    "client": "smk264-client@superstars.local", # scoped to A
}
ROLE_OF = {"admin": "admin", "pm": "pm", "pm2": "pm", "client": "client"}
PROJ_A = "SMK264-A"   # the client's project
PROJ_B = "SMK264-B"   # another project
PHOTOS = {}           # label -> photo_id
_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return cond


# ============= SETUP / TEARDOWN =============

_TINY_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"


def _make_photo(conn, project_code) -> int:
    """Insert a field_photos row + write tiny on-disk full/thumb files under the synthetic
    project dir (so the by-id serve has real bytes). Returns the photo id."""
    pdir = _FP_BASE / project_code / uuid.uuid4().hex
    pdir.mkdir(parents=True, exist_ok=True)
    full = pdir / "full.jpg"
    thumb = pdir / "thumb.jpg"
    full.write_bytes(_TINY_JPEG)
    thumb.write_bytes(_TINY_JPEG)
    cur = conn.execute(
        "INSERT INTO field_photos (project_code, uploaded_at, file_path, thumb_path, "
        "file_name, mime, caption, taken_at, worker_id, stage) "
        "VALUES (?, ?, ?, ?, 'syn.jpg', 'image/jpeg', 'Synthetic test photo', ?, 'W-9999', 'Survey')",
        (project_code, _now_iso(), str(full), str(thumb), "2026-06-01 09:00:00"))
    return cur.lastrowid


def _uid(conn, key):
    return conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()[0]


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_pm_assignment_schema(conn)
        ensure_item_visibility_schema(conn)
        for key, email in USERS.items():
            role = ROLE_OF[key]
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET password_hash=?, role=?, is_active=1, status='active', "
                    "must_reset_password=0, is_system=1 WHERE email=?",
                    (hash_password(PW), role, email))
            else:
                conn.execute(
                    "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                    "must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                    (email, hash_password(PW), role, f"SMK264 {key}"))
        for code in (PROJ_A, PROJ_B):
            row = conn.execute("SELECT project_code FROM projects WHERE project_code=?", (code,)).fetchone()
            if row:
                conn.execute("UPDATE projects SET status='active' WHERE project_code=?", (code,))
            else:
                conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                             (code, f"Smoke Project {code[-1]}"))
        # assignments: client -> A, pm -> A (pm2 unassigned)
        cid, pmid = _uid(conn, "client"), _uid(conn, "pm")
        for uid in (cid, pmid, _uid(conn, "pm2")):
            conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (uid,))
        admin_id = _uid(conn, "admin")
        for uid in (cid, pmid):
            conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, assigned_at) "
                         "VALUES (?, ?, ?, ?)", (uid, PROJ_A, admin_id, _now_iso()))
        # photos: clean any prior synthetic photos for our projects first
        for code in (PROJ_A, PROJ_B):
            for r in conn.execute("SELECT id FROM field_photos WHERE project_code=?", (code,)).fetchall():
                pid = r[0]
                for t in ("item_visibility", "item_redflag", "visibility_audit"):
                    conn.execute(f"DELETE FROM {t} WHERE item_type='photo' AND item_id=?", (pid,))
            conn.execute("DELETE FROM field_photos WHERE project_code=?", (code,))
        PHOTOS["shared"] = _make_photo(conn, PROJ_A)
        PHOTOS["unshared"] = _make_photo(conn, PROJ_A)
        PHOTOS["flagged"] = _make_photo(conn, PROJ_A)
        PHOTOS["other"] = _make_photo(conn, PROJ_B)
        conn.commit()
        # visibility: shared -> client; flagged -> share then redflag; other -> client (cross-project)
        visibility.share(conn, "photo", PHOTOS["shared"], "client", admin_id)
        visibility.share(conn, "photo", PHOTOS["flagged"], "client", admin_id)
        visibility.redflag(conn, "photo", PHOTOS["flagged"], admin_id)
        visibility.share(conn, "photo", PHOTOS["other"], "client", admin_id)  # still cross-project => invisible
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        for code in (PROJ_A, PROJ_B):
            for r in conn.execute("SELECT id FROM field_photos WHERE project_code=?", (code,)).fetchall():
                pid = r[0]
                for t in ("item_visibility", "item_redflag", "visibility_audit"):
                    conn.execute(f"DELETE FROM {t} WHERE item_type='photo' AND item_id=?", (pid,))
            conn.execute("DELETE FROM field_photos WHERE project_code=?", (code,))
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                uid = u[0]
                conn.execute("DELETE FROM pm_project_assignment WHERE user_id=? OR assigned_by=?", (uid, uid))
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM role_change_audit WHERE user_id=? OR changed_by=?", (uid, uid))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
        for code in (PROJ_A, PROJ_B):
            conn.execute("DELETE FROM projects WHERE project_code=?", (code,))
        conn.commit()
    finally:
        conn.close()
    # remove the synthetic on-disk photo dirs
    import shutil
    for code in (PROJ_A, PROJ_B):
        d = _FP_BASE / code
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _sc(sess, method, path, **kw):
    return sess.request(method, f"{BASE}{path}", timeout=15, **kw).status_code


def _portal_photo_ids(sess):
    r = sess.get(f"{BASE}/api/portal/photos", timeout=15)
    if r.status_code != 200:
        return None
    return {p["id"] for p in (r.json().get("data", {}).get("photos") or [])}


# ============= CHECKS =============

_FORBIDDEN_KEYS = {"file_path", "thumb_path", "path", "folder", "worker_id", "stage",
                   "uploaded_by_uid", "file_name", "file_size", "mime", "project_code",
                   "cost", "total_spend", "total_expenses", "rate", "labor", "pin",
                   "phone", "dob", "ssn"}


def _scan_forbidden(obj, hits, where=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _FORBIDDEN_KEYS:
                hits.append(f"{where}.{k}")
            _scan_forbidden(v, hits, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            _scan_forbidden(v, hits, f"{where}[{i}]")


def _visible(conn, code):
    return set(visibility.client_visible_photo_ids(conn, code))


def run():
    admin = _login("admin"); pm = _login("pm"); pm2 = _login("pm2"); client = _login("client")
    if not ok("logins", all([admin, pm, pm2, client]), "could not log in synthetic users"):
        return

    pS, pU, pF, pO = PHOTOS["shared"], PHOTOS["unshared"], PHOTOS["flagged"], PHOTOS["other"]

    # ---- (a)+(b) DEFAULT-DENY ENGINE + PER-RESOURCE ISOLATION, via the predicate (#267 —
    #      the portal is not client-reachable, so verify the exact engine the portal calls) ----
    conn = db_layer.connect(pragma_fk=True)
    try:
        vis = _visible(conn, PROJ_A)
        ok("engine_visible_only_shared",
           pS in vis and pU not in vis and pF not in vis and pO not in vis,
           "the client-visible set must be ONLY the shared in-project photo")
        ok("engine_shared_visible", visibility.photo_visible_to_client(conn, pS, PROJ_A) is True)
        ok("engine_unshared_hidden", not visibility.photo_visible_to_client(conn, pU, PROJ_A))
        ok("engine_flagged_hidden", not visibility.photo_visible_to_client(conn, pF, PROJ_A))
        ok("engine_other_project_hidden", not visibility.photo_visible_to_client(conn, pO, PROJ_A),
           "an other-project photo (even shared to client) is not visible in the client's project")
    finally:
        conn.close()

    # ---- (c) #267 CONTAINMENT: every client PAGE -> 302 /welcome; every API -> 403 ----
    def _page_to_welcome(path):
        r = client.get(f"{BASE}{path}", timeout=15, allow_redirects=False)
        return (r.status_code in (301, 302, 303, 307, 308)
                and r.headers.get("Location", "").rstrip("/").endswith("/welcome"))
    ok("client_portal_not_reachable", _page_to_welcome("/portal"),
       "the #264 portal now bounces the client to /welcome")
    ok("client_company_console_to_welcome", _page_to_welcome("/"))
    ok("client_project_dash_to_welcome", _page_to_welcome(f"/projects/{PROJ_A}"))
    ok("client_admin_users_to_welcome", _page_to_welcome("/admin/users"))
    apis = {
        "portal_photos": "/api/portal/photos",
        "portal_photo_byid": f"/api/portal/photos/{pS}/file",
        "internal_project_photos": f"/api/projects/{PROJ_A}/photos",
        "other_project_photos": f"/api/projects/{PROJ_B}/photos",
        "dropplan_rollup": f"/api/dropplan/projects/{PROJ_A}/rollup",
        "expenses": f"/api/projects/{PROJ_A}/expenses",
        "company_summary": "/api/company/summary",
        "admin_pm_assignments": "/api/admin/pm-assignments",
        "internal_byid": f"/api/field-photos/{pS}/file",
    }
    for name, p in apis.items():
        ok(f"client_api_403_{name}", _sc(client, "GET", p) == 403, f"GET {p}")

    # ---- (d) CURATED-ONLY serializer (tested directly; the portal payload guarantee) ----
    import client_portal
    conn = db_layer.connect(pragma_fk=True)
    try:
        row = conn.execute("SELECT * FROM field_photos WHERE id=?", (pS,)).fetchone()
        curated = client_portal._portal_photo(row)
    finally:
        conn.close()
    hits = []
    _scan_forbidden(curated, hits, "photo")
    ok("curated_serializer_no_pii", not hits, f"forbidden keys in curated photo: {hits}")
    ok("curated_serializer_minimal_keys",
       set(curated.keys()) <= {"id", "caption", "taken_at", "thumb_url", "file_url"},
       f"unexpected curated keys: {set(curated.keys())}")

    # ---- READ-ONLY: client cannot write (403 via the containment gate) ----
    ok("client_cannot_share", _sc(client, "POST", f"/api/field-photos/{pS}/share",
                                   json={"audience": "client", "on": False}) == 403)
    ok("client_cannot_redflag", _sc(client, "POST", f"/api/field-photos/{pS}/redflag",
                                     json={"on": True}) == 403)
    ok("client_cannot_patch_photo", _sc(client, "PATCH", f"/api/field-photos/{pS}",
                                        json={"caption": "x"}) == 403)

    # ---- (a) fail->pass: share flips the engine predicate to visible; red-flag flips it back ----
    ok("admin_share_unshared",
       admin.post(f"{BASE}/api/field-photos/{pU}/share", json={"audience": "client", "on": True},
                  timeout=15).status_code == 200)
    conn = db_layer.connect(pragma_fk=True)
    try:
        ok("shared_now_visible", visibility.photo_visible_to_client(conn, pU, PROJ_A) is True,
           "after share, the engine reports the photo visible to the client")
    finally:
        conn.close()
    ok("admin_redflag",
       admin.post(f"{BASE}/api/field-photos/{pU}/redflag", json={"on": True}, timeout=15).status_code == 200)
    conn = db_layer.connect(pragma_fk=True)
    try:
        ok("redflag_removes_instantly", not visibility.photo_visible_to_client(conn, pU, PROJ_A),
           "red-flag pulls it offline (engine predicate)")
    finally:
        conn.close()

    # ---- per-resource WRITE: pm assigned can share; pm NOT assigned -> 403 ----
    ok("pm_assigned_can_share",
       pm.post(f"{BASE}/api/field-photos/{pS}/share", json={"audience": "client", "on": True},
               timeout=15).status_code == 200)
    ok("pm_unassigned_cannot_share",
       pm2.post(f"{BASE}/api/field-photos/{pS}/share", json={"audience": "client", "on": True},
                timeout=15).status_code == 403,
       "a pm not assigned to the photo's project is 403 (per-resource write check)")

    # ---- visibility audit recorded ----
    conn = db_layer.connect(pragma_fk=True)
    try:
        n = conn.execute("SELECT COUNT(*) FROM visibility_audit WHERE item_id IN (?,?,?)",
                         (pS, pU, pF)).fetchone()[0]
    finally:
        conn.close()
    ok("visibility_audited", n >= 4, f"share/redflag actions audited (rows={n})")


def main():
    print(f"== #264 client portal + visibility guard ==  BASE={BASE}")
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
