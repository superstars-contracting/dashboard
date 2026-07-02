#!/usr/bin/env python3
"""#269 — SELECTIVE CLIENT UN-GATING guard (dual-backend). Per-client, per-section,
DEFAULT-OFF grants on top of #264 per-item visibility + #267 welcome containment.

Proves the full fail->pass->fail arc, server-side:
  (a) ZERO GRANTS  = #267 containment intact: /welcome only; /portal -> 302 /welcome;
      every /api/portal/* (incl. the new documents/daily/schedule) -> 403.
  (b) GRANT ONE SECTION unlocks EXACTLY that section: after granting `progress`, /welcome
      forwards to /portal, /portal 200, context lists only ['progress'], the progress API
      is 200 — and photos/documents/daily/schedule APIs are STILL 403 (direct URL).
  (c) PER-ITEM DEFAULT-DENY inside a granted section: with `photos` granted the gallery
      lists ONLY the client-shared photo; unshared / red-flagged / cross-project by-ID
      -> 404. Same for `documents` (#269 extends the engine to item_type='document').
  (d) REVOKE removes it: revoking `progress` makes its API 403 again and drops it from
      context; revoking ALL sections restores the full welcome hard-stop.
  (e) ADMIN-ONLY grant surface: pm/client hitting the grant endpoints -> 403; bad
      section -> 400; granting to a non-client -> 400.
  (f) CURATED payloads: forbidden-keys scan on every portal payload (no *_path, worker,
      rate, crew, notes, uploader, project_code, ...).

Isolation + hygiene (CLAUDE.md): runs against SMOKE_BASE (the gate's isolated server —
NEVER live; refuses if SSC_DB_URL is unset). Self-ensures its schemas. Synthetic
is_system=1 users (smk269-*) + projects (SMK269-*) + photos/docs + on-disk files under
synthetic project dirs; scoped cleanup in finally (children first — FK-safe on Postgres).
PII-safe: asserts on status / counts / booleans / curated keys only.
"""
from __future__ import annotations

import os
import secrets
import shutil
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
from apply_client_grants_269 import ensure_client_grants_schema  # noqa: E402
import visibility  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
_FP_BASE = SCRIPT_DIR / "data_room" / "field_photos"
_DOC_BASE = SCRIPT_DIR / "data_room" / "project_docs"

PW = secrets.token_urlsafe(18)
USERS = {
    "admin":  "smk269-admin@superstars.local",
    "pm":     "smk269-pm@superstars.local",      # NOT assigned to A — grant-endpoint 403 probe
    "client": "smk269-client@superstars.local",  # scoped to A
}
ROLE_OF = {"admin": "admin", "pm": "pm", "client": "client"}
PROJ_A = "SMK269-A"
PROJ_B = "SMK269-B"
SECTIONS = ("progress", "photos", "documents", "daily", "schedule")
IDS = {}          # label -> id  (photos + documents)
_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return cond


# ============= SETUP / TEARDOWN =============

_TINY_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
_TINY_PDF = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _make_photo(conn, project_code) -> int:
    pdir = _FP_BASE / project_code / uuid.uuid4().hex
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "full.jpg").write_bytes(_TINY_JPEG)
    (pdir / "thumb.jpg").write_bytes(_TINY_JPEG)
    cur = conn.execute(
        "INSERT INTO field_photos (project_code, uploaded_at, file_path, thumb_path, "
        "file_name, mime, caption, taken_at, worker_id, stage) "
        "VALUES (?, ?, ?, ?, 'syn.jpg', 'image/jpeg', 'Synthetic test photo', ?, 'W-9999', 'Survey')",
        (project_code, _now_iso(), str(pdir / "full.jpg"), str(pdir / "thumb.jpg"),
         "2026-06-01 09:00:00"))
    return cur.lastrowid


def _make_doc(conn, project_code, title, superseded=0) -> int:
    pdir = _DOC_BASE / project_code
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / f"{uuid.uuid4().hex}.pdf"
    f.write_bytes(_TINY_PDF)
    cur = conn.execute(
        "INSERT INTO project_documents (project_code, category, title, doc_type, file_path, "
        "file_name, file_size, mime, effective_date, superseded, uploaded_at) "
        "VALUES (?, 'PERMITS', ?, 'PDF', ?, 'syn.pdf', ?, 'application/pdf', '2026-06-01', ?, ?)",
        (project_code, title, str(f), len(_TINY_PDF), superseded, _now_iso()))
    return cur.lastrowid


def _uid(conn, key):
    return conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()[0]


def _purge_project_rows(conn, code):
    """Scoped, synthetic-only cleanup for one SMK269 project code (children first)."""
    for r in conn.execute("SELECT id FROM field_photos WHERE project_code=?", (code,)).fetchall():
        for t in ("item_visibility", "item_redflag", "visibility_audit"):
            conn.execute(f"DELETE FROM {t} WHERE item_type='photo' AND item_id=?", (r[0],))
    conn.execute("DELETE FROM field_photos WHERE project_code=?", (code,))
    for r in conn.execute("SELECT id FROM project_documents WHERE project_code=?", (code,)).fetchall():
        for t in ("item_visibility", "item_redflag", "visibility_audit"):
            conn.execute(f"DELETE FROM {t} WHERE item_type='document' AND item_id=?", (r[0],))
    conn.execute("DELETE FROM project_documents WHERE project_code=?", (code,))
    conn.execute("DELETE FROM report_index WHERE project_code=?", (code,))
    conn.execute("DELETE FROM lookahead_activity WHERE project_code=?", (code,))
    conn.execute("DELETE FROM client_section_grant WHERE project_code=?", (code,))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_pm_assignment_schema(conn)
        ensure_item_visibility_schema(conn)
        ensure_client_grants_schema(conn)
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
                    (email, hash_password(PW), role, f"SMK269 {key}"))
        for code in (PROJ_A, PROJ_B):
            row = conn.execute("SELECT project_code FROM projects WHERE project_code=?", (code,)).fetchone()
            if row:
                conn.execute("UPDATE projects SET status='active' WHERE project_code=?", (code,))
            else:
                conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                             (code, f"Smoke Grants {code[-1]}"))
        cid, admin_id = _uid(conn, "client"), _uid(conn, "admin")
        for uid in (cid, _uid(conn, "pm")):
            conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (uid,))
        conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, assigned_at) "
                     "VALUES (?, ?, ?, ?)", (cid, PROJ_A, admin_id, _now_iso()))
        conn.execute("DELETE FROM client_section_grant WHERE user_id=?", (cid,))   # DEFAULT OFF
        for code in (PROJ_A, PROJ_B):
            _purge_project_rows(conn, code)
        # photos: A shared / A unshared / A flagged / B shared(cross-project probe)
        IDS["ph_shared"] = _make_photo(conn, PROJ_A)
        IDS["ph_unshared"] = _make_photo(conn, PROJ_A)
        IDS["ph_flagged"] = _make_photo(conn, PROJ_A)
        IDS["ph_other"] = _make_photo(conn, PROJ_B)
        # documents: A shared / A unshared / A shared-but-superseded / B shared(cross-project)
        IDS["doc_shared"] = _make_doc(conn, PROJ_A, "Synthetic shared permit")
        IDS["doc_unshared"] = _make_doc(conn, PROJ_A, "Synthetic internal permit")
        IDS["doc_superseded"] = _make_doc(conn, PROJ_A, "Synthetic superseded permit", superseded=1)
        IDS["doc_other"] = _make_doc(conn, PROJ_B, "Synthetic other-project permit")
        # daily: two issued report days (one no-work)
        conn.execute("INSERT INTO report_index (report_date, project_code, report_type, status, "
                     "created_at, no_work) VALUES ('2026-06-29', ?, 'DCR', 'issued', ?, 0)",
                     (PROJ_A, _now_iso()))
        conn.execute("INSERT INTO report_index (report_date, project_code, report_type, status, "
                     "created_at, no_work) VALUES ('2026-06-30', ?, 'DCR', 'issued', ?, 1)",
                     (PROJ_A, _now_iso()))
        # schedule: one activity in the visible window
        conn.execute("INSERT INTO lookahead_activity (project_code, name, activity_type, "
                     "planned_start, planned_finish, source) "
                     "VALUES (?, 'Synthetic parge coat', 'stage', '2026-07-02', '2026-07-06', 'manual')",
                     (PROJ_A,))
        conn.commit()
        visibility.share(conn, "photo", IDS["ph_shared"], "client", admin_id)
        visibility.share(conn, "photo", IDS["ph_flagged"], "client", admin_id)
        visibility.redflag(conn, "photo", IDS["ph_flagged"], admin_id)
        visibility.share(conn, "photo", IDS["ph_other"], "client", admin_id)
        visibility.share(conn, "document", IDS["doc_shared"], "client", admin_id)
        visibility.share(conn, "document", IDS["doc_superseded"], "client", admin_id)  # superseded => still invisible
        visibility.share(conn, "document", IDS["doc_other"], "client", admin_id)  # cross-project => invisible
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        for code in (PROJ_A, PROJ_B):
            _purge_project_rows(conn, code)
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
    for base in (_FP_BASE, _DOC_BASE):
        for code in (PROJ_A, PROJ_B):
            d = base / code
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _sc(sess, method, path, **kw):
    return sess.request(method, f"{BASE}{path}", timeout=15, **kw).status_code


def _redirects_to(sess, path, target):
    r = sess.get(f"{BASE}{path}", timeout=15, allow_redirects=False)
    return (r.status_code in (301, 302, 303, 307, 308)
            and r.headers.get("Location", "").rstrip("/").endswith(target))


def _grant(admin, user_id, section, on=True):
    return admin.post(f"{BASE}/api/admin/client-grants",
                      json={"user_id": user_id, "section": section, "on": on},
                      timeout=15)


# curated-payload scan — no PII / path / internal keys ever reach a client
_FORBIDDEN_KEYS = {"file_path", "thumb_path", "path", "folder", "worker_id", "stage",
                   "uploaded_by_uid", "file_name", "file_size", "mime", "project_code",
                   "cost", "total_spend", "rate", "labor", "pin", "phone", "dob", "ssn",
                   "crew", "notes", "requirement_key", "source_step", "report_id"}


def _scan_forbidden(obj, hits, where=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and k.lower() in _FORBIDDEN_KEYS:
                hits.append(f"{where}.{k}")
            _scan_forbidden(v, hits, f"{where}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            _scan_forbidden(v, hits, f"{where}[{i}]")


SECTION_API = {
    "progress": "/api/portal/project",
    "photos": "/api/portal/photos",
    "documents": "/api/portal/documents",
    "daily": "/api/portal/daily",
    "schedule": "/api/portal/schedule",
}


def run():
    conn = db_layer.connect(pragma_fk=True)
    try:
        client_uid = _uid(conn, "client")
    finally:
        conn.close()
    admin = _login("admin"); pm = _login("pm"); client = _login("client")
    if not ok("logins", all([admin, pm, client]), "could not log in synthetic users"):
        return

    # ---- (a) ZERO GRANTS: full #267 containment ----
    ok("nogrant_welcome_200", _sc(client, "GET", "/welcome") == 200)
    ok("nogrant_portal_to_welcome", _redirects_to(client, "/portal", "/welcome"))
    ok("nogrant_root_to_welcome", _redirects_to(client, "/", "/welcome"))
    for s, api in SECTION_API.items():
        ok(f"nogrant_api_403_{s}", _sc(client, "GET", api) == 403, f"GET {api}")
    ok("nogrant_context_403", _sc(client, "GET", "/api/portal/context") == 403)
    ok("nogrant_byid_photo_403", _sc(client, "GET", f"/api/portal/photos/{IDS['ph_shared']}/file") == 403)
    ok("nogrant_byid_doc_403", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_shared']}/file") == 403)

    # ---- (e) admin-only grant surface ----
    ok("grant_admin_only_pm_403", _grant(pm, client_uid, "progress").status_code == 403)
    ok("grant_admin_only_client_403", _grant(client, client_uid, "progress").status_code == 403)
    ok("grant_list_client_403", _sc(client, "GET", "/api/admin/client-grants") == 403)
    ok("grant_bad_section_400", _grant(admin, client_uid, "financials").status_code == 400)
    conn = db_layer.connect(pragma_fk=True)
    try:
        pm_uid = _uid(conn, "pm")
    finally:
        conn.close()
    ok("grant_non_client_400", _grant(admin, pm_uid, "progress").status_code == 400)

    # ---- (b) GRANT `progress` -> exactly that section unlocks ----
    ok("grant_progress_200", _grant(admin, client_uid, "progress").status_code == 200)
    ok("granted_welcome_forwards_to_portal", _redirects_to(client, "/welcome", "/portal"))
    ok("granted_portal_200", _sc(client, "GET", "/portal") == 200)
    r = client.get(f"{BASE}/api/portal/context", timeout=15)
    ok("granted_context_200", r.status_code == 200)
    secs = (r.json().get("data", {}).get("sections") if r.status_code == 200 else None) or []
    ok("granted_context_only_progress", secs == ["progress"], f"sections={secs}")
    hits = []
    _scan_forbidden(r.json() if r.status_code == 200 else {}, hits, "context")
    ok("context_payload_curated", not hits, f"forbidden keys: {hits}")
    r = client.get(f"{BASE}/api/portal/project", timeout=15)
    ok("granted_progress_api_200", r.status_code == 200)
    hits = []
    _scan_forbidden(r.json() if r.status_code == 200 else {}, hits, "progress")
    ok("progress_payload_curated", not hits, f"forbidden keys: {hits}")
    for s in ("photos", "documents", "daily", "schedule"):
        ok(f"ungranted_still_403_{s}", _sc(client, "GET", SECTION_API[s]) == 403,
           "granting one section must not open another")
    # still contained outside the portal
    ok("granted_admin_page_to_portal", _redirects_to(client, "/admin/users", "/portal"))
    ok("granted_internal_api_403",
       _sc(client, "GET", f"/api/projects/{PROJ_A}/photos") == 403)

    # ---- (c) photos: per-item default-deny inside the granted section ----
    ok("grant_photos_200", _grant(admin, client_uid, "photos").status_code == 200)
    r = client.get(f"{BASE}/api/portal/photos", timeout=15)
    ok("photos_api_200", r.status_code == 200)
    ids = {p["id"] for p in (r.json().get("data", {}).get("photos") or [])} if r.status_code == 200 else set()
    ok("photos_only_shared_listed",
       ids == {IDS["ph_shared"]},
       f"expected only the shared photo, got {len(ids)} ids")
    hits = []
    _scan_forbidden(r.json() if r.status_code == 200 else {}, hits, "photos")
    ok("photos_payload_curated", not hits, f"forbidden keys: {hits}")
    ok("photo_shared_byid_200", _sc(client, "GET", f"/api/portal/photos/{IDS['ph_shared']}/file") == 200)
    ok("photo_unshared_byid_404", _sc(client, "GET", f"/api/portal/photos/{IDS['ph_unshared']}/file") == 404)
    ok("photo_flagged_byid_404", _sc(client, "GET", f"/api/portal/photos/{IDS['ph_flagged']}/file") == 404)
    ok("photo_other_project_byid_404", _sc(client, "GET", f"/api/portal/photos/{IDS['ph_other']}/file") == 404)

    # ---- (c) documents: the engine extended to item_type='document' ----
    ok("grant_documents_200", _grant(admin, client_uid, "documents").status_code == 200)
    r = client.get(f"{BASE}/api/portal/documents", timeout=15)
    ok("docs_api_200", r.status_code == 200)
    payload = r.json() if r.status_code == 200 else {}
    dids = {d["id"] for d in (payload.get("data", {}).get("documents") or [])}
    ok("docs_only_shared_listed", dids == {IDS["doc_shared"]},
       f"expected only the shared doc, got {len(dids)} ids")
    hits = []
    _scan_forbidden(payload, hits, "docs")
    ok("docs_payload_curated", not hits, f"forbidden keys: {hits}")
    ok("doc_shared_byid_200", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_shared']}/file") == 200)
    ok("doc_unshared_byid_404", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_unshared']}/file") == 404)
    ok("doc_superseded_byid_404", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_superseded']}/file") == 404,
       "a superseded doc stays invisible even while a share row lingers")
    ok("doc_other_project_byid_404", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_other']}/file") == 404)
    # red-flag a shared doc -> instantly offline (engine parity with photos)
    ok("doc_redflag_200",
       admin.post(f"{BASE}/api/documents/{IDS['doc_shared']}/redflag", json={"on": True},
                  timeout=15).status_code == 200)
    ok("doc_flagged_byid_404", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_shared']}/file") == 404)
    ok("doc_unflag_200",
       admin.post(f"{BASE}/api/documents/{IDS['doc_shared']}/redflag", json={"on": False},
                  timeout=15).status_code == 200)
    ok("doc_unflag_does_not_reshare", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_shared']}/file") == 404,
       "unflag must NOT silently re-share (re-share is deliberate)")
    ok("doc_reshare_200",
       admin.post(f"{BASE}/api/documents/{IDS['doc_shared']}/share",
                  json={"audience": "client", "on": True}, timeout=15).status_code == 200)
    ok("doc_reshared_byid_200", _sc(client, "GET", f"/api/portal/documents/{IDS['doc_shared']}/file") == 200)

    # ---- daily + schedule (curated) ----
    ok("grant_daily_200", _grant(admin, client_uid, "daily").status_code == 200)
    r = client.get(f"{BASE}/api/portal/daily", timeout=15)
    ok("daily_api_200", r.status_code == 200)
    days = (r.json().get("data", {}).get("days") or []) if r.status_code == 200 else []
    ok("daily_two_days", len(days) == 2, f"got {len(days)}")
    hits = []
    _scan_forbidden(r.json() if r.status_code == 200 else {}, hits, "daily")
    ok("daily_payload_curated", not hits, f"forbidden keys: {hits}")

    ok("grant_schedule_200", _grant(admin, client_uid, "schedule").status_code == 200)
    r = client.get(f"{BASE}/api/portal/schedule", timeout=15)
    ok("schedule_api_200", r.status_code == 200)
    acts = (r.json().get("data", {}).get("activities") or []) if r.status_code == 200 else []
    ok("schedule_has_activity", len(acts) >= 1, f"got {len(acts)}")
    hits = []
    _scan_forbidden(r.json() if r.status_code == 200 else {}, hits, "schedule")
    ok("schedule_payload_curated", not hits, f"forbidden keys: {hits}")

    r = client.get(f"{BASE}/api/portal/context", timeout=15)
    secs = (r.json().get("data", {}).get("sections") if r.status_code == 200 else None) or []
    ok("context_all_five", secs == list(SECTIONS), f"sections={secs}")

    # ---- (d) REVOKE progress -> 403 again + gone from context ----
    ok("revoke_progress_200", _grant(admin, client_uid, "progress", on=False).status_code == 200)
    ok("revoked_progress_api_403", _sc(client, "GET", "/api/portal/project") == 403,
       "a revoked section's endpoint must 403 immediately")
    r = client.get(f"{BASE}/api/portal/context", timeout=15)
    secs = (r.json().get("data", {}).get("sections") if r.status_code == 200 else None) or []
    ok("revoked_progress_gone_from_context", "progress" not in secs and len(secs) == 4,
       f"sections={secs}")
    ok("revoked_portal_still_200", _sc(client, "GET", "/portal") == 200)

    # ---- (d) REVOKE ALL -> the welcome hard-stop returns ----
    for s in ("photos", "documents", "daily", "schedule"):
        _grant(admin, client_uid, s, on=False)
    ok("allrevoked_portal_to_welcome", _redirects_to(client, "/portal", "/welcome"))
    ok("allrevoked_welcome_200", _sc(client, "GET", "/welcome") == 200)
    for s, api in SECTION_API.items():
        ok(f"allrevoked_api_403_{s}", _sc(client, "GET", api) == 403)

    # ---- admin list endpoint shape ----
    r = admin.get(f"{BASE}/api/admin/client-grants?user_id={client_uid}", timeout=15)
    ok("grant_list_200", r.status_code == 200)
    if r.status_code == 200:
        cl = (r.json().get("data", {}).get("clients") or [{}])[0]
        ok("grant_list_empty_after_revoke", cl.get("sections") == [] and cl.get("project_code") == PROJ_A,
           f"got {cl}")


def main():
    print(f"== #269 selective client un-gating guard ==  BASE={BASE}")
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
