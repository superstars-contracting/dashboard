#!/usr/bin/env python3
"""#270 — document bulk share + access presets + read-only "Preview as client" guard
(dual-backend). Builds on the #269 grant fixtures pattern.

Proves, server-side:
  (a) PREVIEW PARITY — for every portal endpoint, an admin's ?preview_client=<id>
      response `data` is byte-for-byte identical to the target client's own `data`
      (json sort_keys compare); by-ID photo/doc FILE bytes identical too. The preview
      block rides OUTSIDE `data` (context), so parity is honest.
  (b) PREVIEW NEVER EXCEEDS the target's grants — a non-granted section's API is 403
      for the admin preview exactly as for the client; per-item default-deny holds in
      preview (unshared/flagged by-ID -> 404).
  (c) PREVIEW ROLE GATES — pm + super with the param -> 403; a CLIENT sending the param
      (naming another client) is served SELF (param ignored); admin without the param,
      or naming a pm / an inactive client -> 403.
  (d) PREVIEW AUDITED — every /portal?preview_client page open writes an audit_log row
      (action=client_portal_preview, actor + target ids).
  (e) PRESETS — replace-set semantics (standard over full -> exactly standard's
      sections), idempotent, minimal -> progress only, unknown preset 400, non-client
      target 400, pm caller 403.
  (f) BULK SHARE — one atomic call flips document_states for ALL ids (on and off);
      per-resource: a pm with no assignment -> 403 whole-call, NO partial write; a
      nonexistent id -> 404 whole-call; a red-flagged id in an `on` selection -> 409
      whole-call, NO partial write.

Isolation + hygiene (CLAUDE.md): SMOKE_BASE isolated server; refuses without SSC_DB_URL.
Synthetic is_system=1 users (smk270-*) + projects (SMK270-*) + tiny on-disk files under
synthetic project dirs; scoped FK-safe cleanup in finally. PII-safe: asserts on status /
counts / booleans / key-shape only.
"""
from __future__ import annotations

import json
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
    "admin":   "smk270-admin@superstars.local",
    "pm":      "smk270-pm@superstars.local",      # NO assignments — per-resource 403 probe
    "super":   "smk270-super@superstars.local",
    "client":  "smk270-client@superstars.local",  # scoped to A
    "client2": "smk270-client2@superstars.local", # scoped to B (param-ignored probe)
}
ROLE_OF = {"admin": "admin", "pm": "pm", "super": "super", "client": "client", "client2": "client"}
PROJ_A = "SMK270-A"
PROJ_B = "SMK270-B"
SECTIONS = ("progress", "photos", "documents", "daily", "schedule")
SECTION_API = {
    "progress": "/api/portal/project",
    "photos": "/api/portal/photos",
    "documents": "/api/portal/documents",
    "daily": "/api/portal/daily",
    "schedule": "/api/portal/schedule",
}
IDS = {}
_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return cond


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
        "VALUES (?, ?, ?, ?, 'syn.jpg', 'image/jpeg', 'Synthetic 270 photo', ?, 'W-9999', 'Survey')",
        (project_code, _now_iso(), str(pdir / "full.jpg"), str(pdir / "thumb.jpg"),
         "2026-06-15 09:00:00"))
    return cur.lastrowid


def _make_doc(conn, project_code, title) -> int:
    pdir = _DOC_BASE / project_code
    pdir.mkdir(parents=True, exist_ok=True)
    f = pdir / f"{uuid.uuid4().hex}.pdf"
    f.write_bytes(_TINY_PDF)
    cur = conn.execute(
        "INSERT INTO project_documents (project_code, category, title, doc_type, file_path, "
        "file_name, file_size, mime, effective_date, superseded, uploaded_at) "
        "VALUES (?, 'PERMITS', ?, 'PDF', ?, 'syn.pdf', ?, 'application/pdf', '2026-06-01', 0, ?)",
        (project_code, title, str(f), len(_TINY_PDF), _now_iso()))
    return cur.lastrowid


def _uid(conn, key):
    return conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()[0]


def _purge_project_rows(conn, code):
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
                    (email, hash_password(PW), role, f"SMK270 {key}"))
        for code in (PROJ_A, PROJ_B):
            row = conn.execute("SELECT project_code FROM projects WHERE project_code=?", (code,)).fetchone()
            if row:
                conn.execute("UPDATE projects SET status='active' WHERE project_code=?", (code,))
            else:
                conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                             (code, f"Smoke Preview {code[-1]}"))
        cid, cid2, admin_id = _uid(conn, "client"), _uid(conn, "client2"), _uid(conn, "admin")
        for k in ("client", "client2", "pm", "super"):
            conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (_uid(conn, k),))
        conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, assigned_at) "
                     "VALUES (?, ?, ?, ?)", (cid, PROJ_A, admin_id, _now_iso()))
        conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, assigned_at) "
                     "VALUES (?, ?, ?, ?)", (cid2, PROJ_B, admin_id, _now_iso()))
        for code in (PROJ_A, PROJ_B):
            _purge_project_rows(conn, code)
        conn.execute("DELETE FROM client_section_grant WHERE user_id IN (?,?)", (cid, cid2))
        # grants: client1 gets ALL BUT schedule (the not-granted parity probe);
        # client2 gets progress only (so honoring the param would visibly differ).
        now = _now_iso()
        for s in ("progress", "photos", "documents", "daily"):
            conn.execute("INSERT INTO client_section_grant (user_id, project_code, section, "
                         "granted_by, granted_at) VALUES (?,?,?,?,?)", (cid, PROJ_A, s, admin_id, now))
        conn.execute("INSERT INTO client_section_grant (user_id, project_code, section, granted_by, "
                     "granted_at) VALUES (?,?,?,?,?)", (cid2, PROJ_B, "progress", admin_id, now))
        # fixtures in A
        IDS["ph_shared"] = _make_photo(conn, PROJ_A)
        IDS["ph_unshared"] = _make_photo(conn, PROJ_A)
        IDS["doc_shared"] = _make_doc(conn, PROJ_A, "Synthetic shared permit 270")
        IDS["doc_bulk1"] = _make_doc(conn, PROJ_A, "Synthetic bulk doc one")
        IDS["doc_bulk2"] = _make_doc(conn, PROJ_A, "Synthetic bulk doc two")
        IDS["doc_flagged"] = _make_doc(conn, PROJ_A, "Synthetic flagged doc")
        conn.execute("INSERT INTO report_index (report_date, project_code, report_type, status, "
                     "created_at, no_work) VALUES ('2026-06-29', ?, 'DCR', 'issued', ?, 0)",
                     (PROJ_A, _now_iso()))
        conn.execute("INSERT INTO lookahead_activity (project_code, name, activity_type, "
                     "planned_start, planned_finish, source) "
                     "VALUES (?, 'Synthetic pointing pass', 'stage', '2026-07-03', '2026-07-08', 'manual')",
                     (PROJ_A,))
        conn.commit()
        visibility.share(conn, "photo", IDS["ph_shared"], "client", admin_id)
        visibility.share(conn, "document", IDS["doc_shared"], "client", admin_id)
        visibility.redflag(conn, "document", IDS["doc_flagged"], admin_id)
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


def _data_of(resp):
    try:
        return resp.json().get("data")
    except Exception:
        return None


def _canon(obj):
    return json.dumps(obj, sort_keys=True)


def _pv(path, cid):
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}preview_client={cid}"


def _doc_states(conn, ids):
    out = {}
    for i in ids:
        out[i] = visibility.state(conn, "document", i)
    return out


def run():
    conn = db_layer.connect(pragma_fk=True)
    try:
        client_uid = _uid(conn, "client")
        client2_uid = _uid(conn, "client2")
        pm_uid = _uid(conn, "pm")
        admin_uid = _uid(conn, "admin")
    finally:
        conn.close()
    admin = _login("admin"); pm = _login("pm"); sup = _login("super")
    client = _login("client"); client2 = _login("client2")
    if not ok("logins", all([admin, pm, sup, client, client2]), "could not log in synthetic users"):
        return

    # ---- (a) PREVIEW PARITY on every granted endpoint ----
    granted_now = ("progress", "photos", "documents", "daily")
    for s in granted_now:
        rc = client.get(f"{BASE}{SECTION_API[s]}", timeout=15)
        ra = admin.get(f"{BASE}{_pv(SECTION_API[s], client_uid)}", timeout=15)
        ok(f"parity_status_{s}", rc.status_code == 200 and ra.status_code == 200,
           f"client={rc.status_code} preview={ra.status_code}")
        ok(f"parity_data_{s}", _canon(_data_of(rc)) == _canon(_data_of(ra)),
           "preview data must equal the client's own data byte-for-byte")
    rc = client.get(f"{BASE}/api/portal/context", timeout=15)
    ra = admin.get(f"{BASE}{_pv('/api/portal/context', client_uid)}", timeout=15)
    ok("parity_context_data", rc.status_code == 200 and ra.status_code == 200
       and _canon(_data_of(rc)) == _canon(_data_of(ra)))
    pv_block = (ra.json() or {}).get("preview") or {}
    ok("context_preview_block_outside_data", pv_block.get("on") is True and bool(pv_block.get("client_name")),
       "preview metadata must ride OUTSIDE data")
    ok("context_no_preview_block_for_client", "preview" not in (rc.json() or {}),
       "a real client response must NEVER carry a preview block")
    # by-ID file bytes parity (shared photo + shared doc)
    fc = client.get(f"{BASE}/api/portal/photos/{IDS['ph_shared']}/file", timeout=15)
    fa = admin.get(f"{BASE}{_pv('/api/portal/photos/' + str(IDS['ph_shared']) + '/file', client_uid)}", timeout=15)
    ok("parity_photo_bytes", fc.status_code == 200 and fa.status_code == 200 and fc.content == fa.content)
    dc = client.get(f"{BASE}/api/portal/documents/{IDS['doc_shared']}/file", timeout=15)
    da = admin.get(f"{BASE}{_pv('/api/portal/documents/' + str(IDS['doc_shared']) + '/file', client_uid)}", timeout=15)
    ok("parity_doc_bytes", dc.status_code == 200 and da.status_code == 200 and dc.content == da.content)

    # ---- (b) preview never exceeds the target's grants + per-item deny in preview ----
    ok("preview_nongranted_403_schedule",
       _sc(admin, "GET", _pv(SECTION_API["schedule"], client_uid)) == 403,
       "schedule is NOT granted — the admin preview must 403 exactly like the client")
    ok("client_nongranted_403_schedule", _sc(client, "GET", SECTION_API["schedule"]) == 403)
    ok("preview_unshared_photo_404",
       _sc(admin, "GET", _pv(f"/api/portal/photos/{IDS['ph_unshared']}/file", client_uid)) == 404)
    ok("preview_unshared_doc_404",
       _sc(admin, "GET", _pv(f"/api/portal/documents/{IDS['doc_bulk1']}/file", client_uid)) == 404)
    ok("preview_flagged_doc_404",
       _sc(admin, "GET", _pv(f"/api/portal/documents/{IDS['doc_flagged']}/file", client_uid)) == 404)

    # ---- (c) preview role gates ----
    ok("pm_preview_403_context", _sc(pm, "GET", _pv("/api/portal/context", client_uid)) == 403)
    ok("pm_preview_403_section", _sc(pm, "GET", _pv(SECTION_API["progress"], client_uid)) == 403)
    ok("super_preview_403", _sc(sup, "GET", _pv("/api/portal/context", client_uid)) == 403)
    ok("admin_no_param_403", _sc(admin, "GET", "/api/portal/context") == 403)
    ok("admin_param_names_pm_403", _sc(admin, "GET", _pv("/api/portal/context", pm_uid)) == 403)
    ok("admin_param_garbage_403", _sc(admin, "GET", "/api/portal/context?preview_client=zzz") == 403)
    r_self = client.get(f"{BASE}/api/portal/context", timeout=15)
    r_spoof = client.get(f"{BASE}{_pv('/api/portal/context', client2_uid)}", timeout=15)
    ok("client_param_ignored_serves_self",
       r_spoof.status_code == 200 and _canon(_data_of(r_spoof)) == _canon(_data_of(r_self)),
       "a client naming another client must be served SELF")
    ok("client_param_no_banner", "preview" not in (r_spoof.json() or {}))

    # ---- (d) preview audited (a DB row per page open) ----
    conn = db_layer.connect(pragma_fk=True)
    try:
        n0 = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='client_portal_preview' "
                          "AND actor_user_id=? AND target_id=?", (admin_uid, str(client_uid))).fetchone()[0]
    finally:
        conn.close()
    ok("preview_page_200", _sc(admin, "GET", _pv("/portal", client_uid)) == 200)
    conn = db_layer.connect(pragma_fk=True)
    try:
        n1 = conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='client_portal_preview' "
                          "AND actor_user_id=? AND target_id=?", (admin_uid, str(client_uid))).fetchone()[0]
    finally:
        conn.close()
    ok("preview_open_audited", n1 == n0 + 1, f"expected one new audit row, got {n1 - n0}")
    ok("pm_preview_page_403", _sc(pm, "GET", _pv("/portal", client_uid)) == 403)

    # ---- (e) presets ----
    def _preset(sess, uid, name):
        return sess.post(f"{BASE}/api/admin/client-grants/preset",
                         json={"user_id": uid, "preset": name}, timeout=15)
    r = _preset(admin, client_uid, "full")
    # #281 — assert the preset delivers ITS OWN bundle, not that "full" is a synonym for
    # the whole catalog. PRESETS["full"] used to BE the SECTIONS tuple, so this passed by
    # identity; decoupling them (so a new grantable key is not silently bundled into Full)
    # made that equivalence false, and it was never the property worth asserting.
    from client_grants import PRESETS as _PRESETS
    ok("preset_full_200",
       r.status_code == 200 and (r.json()["data"]["sections"] == sorted(_PRESETS["full"])),
       f"got {r.status_code} sections={r.json().get('data', {}).get('sections')}")
    ok("preview_schedule_after_full_200",
       _sc(admin, "GET", _pv(SECTION_API["schedule"], client_uid)) == 200,
       "full preset must unlock schedule for the preview too")
    r = _preset(admin, client_uid, "standard")
    got = r.json()["data"]["sections"] if r.status_code == 200 else None
    ok("preset_standard_replaces", r.status_code == 200 and got == sorted(["progress", "photos", "daily"]),
       f"standard over full must yield EXACTLY standard's sections, got {got}")
    ok("preset_replace_locks_documents", _sc(client, "GET", SECTION_API["documents"]) == 403,
       "documents was granted before standard — replace-set must have removed it")
    r2 = _preset(admin, client_uid, "standard")
    ok("preset_idempotent", r2.status_code == 200
       and r2.json()["data"]["sections"] == sorted(["progress", "photos", "daily"]))
    r = _preset(admin, client_uid, "minimal")
    ok("preset_minimal", r.status_code == 200 and r.json()["data"]["sections"] == ["progress"])
    ok("preset_unknown_400", _preset(admin, client_uid, "everything").status_code == 400)
    ok("preset_nonclient_400", _preset(admin, pm_uid, "minimal").status_code == 400)
    ok("preset_pm_caller_403", _preset(pm, client_uid, "minimal").status_code == 403)
    # restore the (a)-phase grant shape for any later reads
    _preset(admin, client_uid, "full")

    # ---- (f) bulk share/unshare (atomic, per-resource, skip-none) ----
    b1, b2 = IDS["doc_bulk1"], IDS["doc_bulk2"]
    def _bulk(sess, ids, on):
        return sess.post(f"{BASE}/api/documents/share-bulk",
                         json={"ids": ids, "audience": "client", "on": on}, timeout=15)
    conn = db_layer.connect(pragma_fk=True)
    try:
        pre = _doc_states(conn, [b1, b2])
    finally:
        conn.close()
    ok("bulk_pre_unshared", not pre[b1]["shared_client"] and not pre[b2]["shared_client"])
    r = _bulk(admin, [b1, b2], True)
    ok("bulk_share_200", r.status_code == 200 and r.json()["data"]["count"] == 2, f"got {r.status_code}")
    conn = db_layer.connect(pragma_fk=True)
    try:
        st = _doc_states(conn, [b1, b2])
    finally:
        conn.close()
    ok("bulk_share_flips_both", st[b1]["shared_client"] and st[b2]["shared_client"])
    # pm with NO assignment -> 403 whole call, nothing changes
    r = _bulk(pm, [b1, b2], False)
    conn = db_layer.connect(pragma_fk=True)
    try:
        st2 = _doc_states(conn, [b1, b2])
    finally:
        conn.close()
    ok("bulk_pm_unassigned_403", r.status_code == 403)
    ok("bulk_pm_no_partial_write", st2[b1]["shared_client"] and st2[b2]["shared_client"],
       "a rejected bulk call must write NOTHING")
    ok("bulk_nonexistent_404", _bulk(admin, [b1, 99999999], False).status_code == 404)
    # flagged id in an `on` selection -> 409 whole-call, no partial
    r = _bulk(admin, [b2, IDS["doc_flagged"]], True)
    ok("bulk_flagged_409", r.status_code == 409)
    r = _bulk(admin, [b1, b2], False)
    ok("bulk_unshare_200", r.status_code == 200)
    conn = db_layer.connect(pragma_fk=True)
    try:
        st3 = _doc_states(conn, [b1, b2])
    finally:
        conn.close()
    ok("bulk_unshare_flips_both", not st3[b1]["shared_client"] and not st3[b2]["shared_client"])
    ok("bulk_client_403", _bulk(client, [b1], True).status_code == 403,
       "a client can never reach the internal bulk-share endpoint")


def main():
    print(f"== #270 preview + presets + bulk-share guard ==  BASE={BASE}")
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
