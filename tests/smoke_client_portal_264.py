"""#264 — read-only CLIENT portal + default-deny visibility engine guard. Dual-backend.

The most security-sensitive surface in the app. Proves (fails on a pre-#264 server, where
the portal/visibility endpoints don't exist and nothing is default-deny):

  (a) DEFAULT-DENY: a photo with no client share is NOT in the client gallery; sharing it
      makes it appear; red-flag (take offline) removes it instantly. (literal fail->pass)
  (b) PER-RESOURCE ISOLATION (closes the #263 by-ID gap): the client gets 200 on a SHARED
      photo by id, but 404 on an UNSHARED one, a RED-FLAGGED one, an OTHER-PROJECT photo
      (even one carrying a client share row), and a nonexistent id — guessing ids gets
      nothing. The internal by-id endpoint (/api/field-photos/<id>/file) is 403 to a client.
  (c) The client is 403 on a representative set of INTERNAL endpoints + other projects
      (company console, internal project dashboard/API, drop plan, expenses, admin, the
      other project) — the default-deny gate.
  (d) CURATED-ONLY payload: the portal photos + project responses contain ONLY curated
      fields — never cost / labor / rate / worker PII / *_path / internal fields.
  READ-ONLY: the client cannot share, red-flag, patch, or otherwise write (403).
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
from auth import hash_password, _now_iso  # noqa: E402
from apply_pm_assignment_263 import ensure_pm_assignment_schema  # noqa: E402
from apply_item_visibility_264 import ensure_item_visibility_schema  # noqa: E402
import visibility  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
_FP_BASE = SCRIPT_DIR / "data_room" / "field_photos"

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


def run():
    admin = _login("admin"); pm = _login("pm"); pm2 = _login("pm2"); client = _login("client")
    if not ok("logins", all([admin, pm, pm2, client]), "could not log in synthetic users"):
        return

    pS, pU, pF, pO = PHOTOS["shared"], PHOTOS["unshared"], PHOTOS["flagged"], PHOTOS["other"]

    # ---- (a) default-deny gallery ----
    ids = _portal_photo_ids(client)
    ok("client_gallery_only_shared",
       ids is not None and pS in ids and pU not in ids and pF not in ids and pO not in ids,
       f"gallery must contain ONLY the shared in-project photo")

    # ---- (b) per-resource isolation (by-id) ----
    ok("byid_shared_200", _sc(client, "GET", f"/api/portal/photos/{pS}/file") == 200)
    ok("byid_unshared_404", _sc(client, "GET", f"/api/portal/photos/{pU}/file") == 404)
    ok("byid_flagged_404", _sc(client, "GET", f"/api/portal/photos/{pF}/file") == 404)
    ok("byid_other_project_404", _sc(client, "GET", f"/api/portal/photos/{pO}/file") == 404,
       "an other-project photo (even shared to client) is 404")
    ok("byid_nonexistent_404", _sc(client, "GET", "/api/portal/photos/99999999/file") == 404)
    ok("byid_thumb_shared_200", _sc(client, "GET", f"/api/portal/photos/{pS}/thumb") == 200)
    # the INTERNAL by-id endpoint is unreachable to a client (default-deny gate)
    ok("client_internal_byid_403", _sc(client, "GET", f"/api/field-photos/{pS}/file") == 403)

    # ---- (c) client 403 on internal endpoints + other projects ----
    internal = {
        "company_console": ("GET", "/"),
        "internal_project_dash": ("GET", f"/projects/{PROJ_A}"),
        "internal_project_photos": ("GET", f"/api/projects/{PROJ_A}/photos"),
        "other_project_photos": ("GET", f"/api/projects/{PROJ_B}/photos"),
        "dropplan_rollup": ("GET", f"/api/dropplan/projects/{PROJ_A}/rollup"),
        "expenses": ("GET", f"/api/projects/{PROJ_A}/expenses"),
        "company_summary": ("GET", "/api/company/summary"),
        "workforce": ("GET", "/api/workers/intake-summary"),
        "admin_users": ("GET", "/admin/users"),
        "admin_pm_assignments": ("GET", "/api/admin/pm-assignments"),
        "labor_rates": ("GET", "/api/labor-rates/workers"),
    }
    for name, (m, p) in internal.items():
        ok(f"client_403_{name}", _sc(client, m, p) == 403, f"{m} {p}")

    # ---- (d) curated-only payloads ----
    proj = client.get(f"{BASE}/api/portal/project", timeout=15).json()
    photos = client.get(f"{BASE}/api/portal/photos", timeout=15).json()
    hits = []
    _scan_forbidden(proj, hits, "project")
    _scan_forbidden(photos, hits, "photos")
    ok("payload_curated_only", not hits, f"forbidden keys in client payload: {hits}")
    # the one shared photo carries ONLY the curated keys
    plist = photos.get("data", {}).get("photos") or []
    if plist:
        keys = set(plist[0].keys())
        ok("photo_keys_minimal", keys <= {"id", "caption", "taken_at", "thumb_url", "file_url"},
           f"unexpected photo keys: {keys}")

    # ---- READ-ONLY: client cannot write ----
    ok("client_cannot_share", _sc(client, "POST", f"/api/field-photos/{pS}/share",
                                   json={"audience": "client", "on": False}) == 403)
    ok("client_cannot_redflag", _sc(client, "POST", f"/api/field-photos/{pS}/redflag",
                                     json={"on": True}) == 403)
    ok("client_cannot_patch_photo", _sc(client, "PATCH", f"/api/field-photos/{pS}",
                                        json={"caption": "x"}) == 403)

    # ---- (a) fail->pass: share an unshared photo -> appears; red-flag -> disappears ----
    ok("admin_share_unshared",
       admin.post(f"{BASE}/api/field-photos/{pU}/share", json={"audience": "client", "on": True},
                  timeout=15).status_code == 200)
    ids2 = _portal_photo_ids(client)
    ok("shared_now_appears", ids2 is not None and pU in ids2, "after share, photo appears in gallery")
    ok("shared_now_byid_200", _sc(client, "GET", f"/api/portal/photos/{pU}/file") == 200)
    ok("admin_redflag",
       admin.post(f"{BASE}/api/field-photos/{pU}/redflag", json={"on": True}, timeout=15).status_code == 200)
    ids3 = _portal_photo_ids(client)
    ok("redflag_removes_instantly", ids3 is not None and pU not in ids3, "red-flag pulls it offline")
    ok("redflag_byid_404", _sc(client, "GET", f"/api/portal/photos/{pU}/file") == 404)

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
