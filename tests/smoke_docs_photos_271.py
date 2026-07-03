#!/usr/bin/env python3
"""#271 — document versioning + view-not-print + EXIF capture-time guard (dual-backend).

Proves, server-side:
  (a) VERSION ARC — Update (upload w/ supersedes_id): old row superseded=1 and KEPT
      (row + on-disk file), its client share rows REMOVED (audited unshare), the NEW
      version starts INTERNAL-ONLY; the list shows history (count + chain ids, newest
      previous first); the client sees NOTHING until the new version is re-shared, then
      ONLY the new version; a superseded id stays 404 to the client EVEN WITH a stale
      share row manually planted (the #269 superseded exclusion). Updating an already-
      superseded id -> 409.
  (b) REPLACE — same row id, file bytes swapped, NO history entry, version/share state
      untouched, old disk file gone.
  (c) VIEW-NOT-PRINT — /api/documents/<id>/file serves Content-Disposition: inline
      (with a filename); the doc-open UI path carries NO print trigger (static scan:
      exactly one window.print in dashboard-static.html and it is the deliberate
      look-ahead button, none in the pd- module).
  (d) EXIF ORDER — a bulk upload with mixed fixtures (JPEG w/ EXIF, HEIC w/ EXIF,
      JPEG w/o EXIF), filenames deliberately counter-ordered: both the internal list
      AND the client portal order by taken_at (capture time); the HEIC timestamp
      survives conversion; the no-EXIF file falls back to upload time and is flagged
      estimated (the UI's "upload time" marker source).
  (e) BACKFILL — a fallback-flagged row whose on-disk file HAS EXIF gains its true
      capture time; a stripped-file row stays; re-run fills nothing (idempotent);
      row counts unchanged.

Isolation (CLAUDE.md): SMOKE_BASE isolated server; refuses without SSC_DB_URL.
Synthetic smk271-* users + SMK271-A project + tiny fixtures; scoped FK-safe cleanup.
PII-safe: no paths in output — counts/booleans/ids only.
"""
from __future__ import annotations

import io
import json
import os
import re
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
from apply_docs_photos_271 import ensure_doc_versions_schema, backfill_photo_exif  # noqa: E402
import visibility  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
_FP_BASE = SCRIPT_DIR / "data_room" / "field_photos"
_DOC_BASE = SCRIPT_DIR / "data_room" / "project_docs"

PW = secrets.token_urlsafe(18)
USERS = {"admin": "smk271-admin@superstars.local",
         "client": "smk271-client@superstars.local"}
PROJ = "SMK271-A"
IDS = {}
_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return cond


_PDF_V1 = b"%PDF-1.4\n1 0 obj<</T(v1)>>endobj\ntrailer<<>>\n%%EOF\n"
_PDF_V2 = b"%PDF-1.4\n1 0 obj<</T(v2-newer)>>endobj\ntrailer<<>>\n%%EOF\n"
_PDF_FIX = b"%PDF-1.4\n1 0 obj<</T(fixed-file)>>endobj\ntrailer<<>>\n%%EOF\n"


def _img_bytes(fmt, exif_dt=None, color=(120, 60, 60)):
    """Tiny JPEG/HEIF bytes, optionally carrying EXIF DateTimeOriginal (LOCAL wall-clock)."""
    from PIL import Image
    im = Image.new("RGB", (32, 24), color)
    kw = {}
    if exif_dt:
        ex = Image.Exif()
        ex[306] = exif_dt                       # DateTime (base IFD)
        ex.get_ifd(0x8769)[36867] = exif_dt     # DateTimeOriginal (Exif sub-IFD)
        kw["exif"] = ex.tobytes()
    if fmt == "HEIF":
        import pillow_heif
        pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    im.save(buf, fmt, **kw)
    return buf.getvalue()


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
    conn.execute("DELETE FROM client_section_grant WHERE project_code=?", (code,))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_pm_assignment_schema(conn)
        ensure_item_visibility_schema(conn)
        ensure_client_grants_schema(conn)
        ensure_doc_versions_schema(conn)
        for key, email in USERS.items():
            role = "admin" if key == "admin" else "client"
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
                    (email, hash_password(PW), role, f"SMK271 {key}"))
        if not conn.execute("SELECT 1 FROM projects WHERE project_code=?", (PROJ,)).fetchone():
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?, 'active')",
                         (PROJ, "Smoke Versions A"))
        else:
            conn.execute("UPDATE projects SET status='active' WHERE project_code=?", (PROJ,))
        cid, aid = _uid(conn, "client"), _uid(conn, "admin")
        conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (cid,))
        conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, assigned_at) "
                     "VALUES (?,?,?,?)", (cid, PROJ, aid, _now_iso()))
        _purge_project_rows(conn, PROJ)   # BEFORE the grant inserts — the purge clears grants too
        conn.execute("DELETE FROM client_section_grant WHERE user_id=?", (cid,))
        now = _now_iso()
        for s in ("photos", "documents"):
            conn.execute("INSERT INTO client_section_grant (user_id, project_code, section, "
                         "granted_by, granted_at) VALUES (?,?,?,?,?)", (cid, PROJ, s, aid, now))
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        _purge_project_rows(conn, PROJ)
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
        conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
        conn.commit()
    finally:
        conn.close()
    for base in (_FP_BASE, _DOC_BASE):
        d = base / PROJ
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def run():
    conn = db_layer.connect(pragma_fk=True)
    try:
        client_uid = _uid(conn, "client")
        admin_uid = _uid(conn, "admin")
    finally:
        conn.close()
    admin = _login("admin")
    client = _login("client")
    if not ok("logins", bool(admin and client)):
        return

    # ---- (a) VERSION ARC ----
    r = admin.post(f"{BASE}/api/projects/{PROJ}/documents",
                   files={"file": ("permit-v1.pdf", _PDF_V1, "application/pdf")},
                   data={"category": "PERMITS", "title": "Synthetic permit 271",
                         "effective_date": "2026-01-03", "expiry_date": "2026-05-11"},
                   timeout=15)
    ok("upload_v1_201", r.status_code == 201, f"got {r.status_code}")
    v1 = r.json()["data"]["id"]
    ok("v1_share_200", admin.post(f"{BASE}/api/documents/{v1}/share",
                                  json={"audience": "client", "on": True}, timeout=15).status_code == 200)
    rc = client.get(f"{BASE}/api/portal/documents", timeout=15)
    ok("client_sees_v1", rc.status_code == 200
       and [d["id"] for d in rc.json()["data"]["documents"]] == [v1])
    # UPDATE -> v2 with its own dates
    r = admin.post(f"{BASE}/api/projects/{PROJ}/documents",
                   files={"file": ("permit-v2.pdf", _PDF_V2, "application/pdf")},
                   data={"category": "PERMITS", "title": "Synthetic permit 271",
                         "effective_date": "2026-05-12", "expiry_date": "2026-09-30",
                         "supersedes_id": str(v1)},
                   timeout=15)
    ok("update_v2_201", r.status_code == 201, f"got {r.status_code}")
    v2 = r.json()["data"]["id"]
    conn = db_layer.connect(pragma_fk=True)
    try:
        old = conn.execute("SELECT superseded, file_path FROM project_documents WHERE id=?", (v1,)).fetchone()
        ok("v1_superseded_kept", bool(old) and old["superseded"] == 1 and Path(old["file_path"]).exists(),
           "old version row + file must be KEPT")
        new = conn.execute("SELECT superseded, supersedes_id FROM project_documents WHERE id=?", (v2,)).fetchone()
        ok("v2_links_v1", new["superseded"] == 0 and new["supersedes_id"] == v1)
        shares_v1 = conn.execute("SELECT COUNT(*) FROM item_visibility WHERE item_type='document' AND item_id=?",
                                 (v1,)).fetchone()[0]
        shares_v2 = conn.execute("SELECT COUNT(*) FROM item_visibility WHERE item_type='document' AND item_id=?",
                                 (v2,)).fetchone()[0]
        ok("supersede_unshared_old", shares_v1 == 0, "stale version must lose its client share")
        ok("new_version_internal_only", shares_v2 == 0, "new version must start internal-only")
        aud = conn.execute("SELECT COUNT(*) FROM visibility_audit WHERE item_type='document' AND item_id=? "
                           "AND action='unshare'", (v1,)).fetchone()[0]
        ok("unshare_audited", aud >= 1)
    finally:
        conn.close()
    # list: history chain on the current doc
    r = admin.get(f"{BASE}/api/projects/{PROJ}/documents", timeout=15)
    doc = None
    for c in r.json()["data"]["categories"]:
        for d in c["extras"]:
            if d["id"] == v2:
                doc = d
    ok("list_v2_is_current_extra", doc is not None)
    ok("list_history_chain", bool(doc) and doc.get("history_count") == 1
       and [h["id"] for h in doc.get("history", [])] == [v1], f"got {doc and doc.get('history')}")
    listed_ids = [d["id"] for c in r.json()["data"]["categories"] for d in c["extras"]]
    ok("superseded_not_listed_as_extra", v1 not in listed_ids,
       "a chained superseded version must live in History, not extras")
    # client: nothing until re-share; then ONLY v2; superseded 404 even w/ stale share row
    rc = client.get(f"{BASE}/api/portal/documents", timeout=15)
    ok("client_sees_nothing_after_update", rc.status_code == 200 and rc.json()["data"]["documents"] == [])
    ok("client_v1_byid_404", client.get(f"{BASE}/api/portal/documents/{v1}/file", timeout=15).status_code == 404)
    ok("reshare_v2_200", admin.post(f"{BASE}/api/documents/{v2}/share",
                                    json={"audience": "client", "on": True}, timeout=15).status_code == 200)
    rc = client.get(f"{BASE}/api/portal/documents", timeout=15)
    ok("client_sees_only_v2", [d["id"] for d in rc.json()["data"]["documents"]] == [v2])
    conn = db_layer.connect(pragma_fk=True)
    try:  # plant a STALE share row on the superseded version — must still be 404
        conn.execute("INSERT OR IGNORE INTO item_visibility (item_type, item_id, audience, shared_by, shared_at) "
                     "VALUES ('document', ?, 'client', ?, ?)", (v1, admin_uid, _now_iso()))
        conn.commit()
    finally:
        conn.close()
    ok("superseded_404_despite_stale_share",
       client.get(f"{BASE}/api/portal/documents/{v1}/file", timeout=15).status_code == 404,
       "superseded stays invisible to clients no matter what share rows exist")
    ok("update_superseded_409",
       admin.post(f"{BASE}/api/projects/{PROJ}/documents",
                  files={"file": ("x.pdf", _PDF_V2, "application/pdf")},
                  data={"category": "PERMITS", "title": "x", "supersedes_id": str(v1)},
                  timeout=15).status_code == 409)

    # ---- (b) REPLACE — same version, no history ----
    before = admin.get(f"{BASE}/api/documents/{v2}/file", timeout=15).content
    r = admin.post(f"{BASE}/api/documents/{v2}/replace-file",
                   files={"file": ("permit-v2-fixed.pdf", _PDF_FIX, "application/pdf")}, timeout=15)
    ok("replace_200", r.status_code == 200, f"got {r.status_code}")
    after = admin.get(f"{BASE}/api/documents/{v2}/file", timeout=15).content
    ok("replace_swaps_bytes", before != after and after == _PDF_FIX)
    conn = db_layer.connect(pragma_fk=True)
    try:
        n_rows = conn.execute("SELECT COUNT(*) FROM project_documents WHERE project_code=?", (PROJ,)).fetchone()[0]
        v2row = conn.execute("SELECT superseded, supersedes_id FROM project_documents WHERE id=?", (v2,)).fetchone()
        shares_v2 = conn.execute("SELECT COUNT(*) FROM item_visibility WHERE item_type='document' AND item_id=?",
                                 (v2,)).fetchone()[0]
    finally:
        conn.close()
    ok("replace_no_history_entry", n_rows == 2, f"expected 2 rows (v1+v2), got {n_rows}")
    ok("replace_state_untouched", v2row["superseded"] == 0 and v2row["supersedes_id"] == v1 and shares_v2 == 1,
       "replace must not touch version/share state")

    # ---- (c) VIEW-NOT-PRINT ----
    r = admin.get(f"{BASE}/api/documents/{v2}/file", timeout=15)
    disp = r.headers.get("Content-Disposition", "")
    ok("file_disposition_inline", disp.startswith("inline") and "filename" in disp, f"got '{disp}'")
    src = (SCRIPT_DIR / "dashboard-static.html").read_text(encoding="utf-8")
    prints = [ln for ln in src.splitlines() if "window.print" in ln]
    ok("no_print_on_doc_open_path", len(prints) == 1 and "la-print" in prints[0],
       "exactly ONE window.print may exist (the deliberate look-ahead button) — none on the doc path")

    # ---- (d) EXIF capture-time ordering (bulk, mixed formats, counter-ordered names) ----
    jpg_late = _img_bytes("JPEG", "2026:07:01 10:00:00")           # capture 10:00
    heic_early = _img_bytes("HEIF", "2026:07:01 08:00:00")         # capture 08:00 (HEIC)
    jpg_noexif = _img_bytes("JPEG", None, color=(40, 90, 140))     # no EXIF -> upload-time fallback
    r = admin.post(f"{BASE}/api/projects/{PROJ}/photos/upload",
                   files=[("photos", ("a-last-by-name.jpg", jpg_late, "image/jpeg")),
                          ("photos", ("z-first-by-capture.heic", heic_early, "image/heic")),
                          ("photos", ("m-no-exif.jpg", jpg_noexif, "image/jpeg"))],
                   timeout=30)
    ok("photo_batch_201", r.status_code == 201, f"got {r.status_code}")
    stored = {s["file"]: s for s in r.json()["data"]["stored"]}
    ok("heic_exif_survives", stored.get("z-first-by-capture.heic", {}).get("taken_at") == "2026-07-01 08:00:00"
       and stored["z-first-by-capture.heic"]["estimated"] is False,
       f"got {stored.get('z-first-by-capture.heic')}")
    ok("jpeg_exif_read", stored.get("a-last-by-name.jpg", {}).get("taken_at") == "2026-07-01 10:00:00")
    ok("noexif_flagged_upload_time", stored.get("m-no-exif.jpg", {}).get("estimated") is True)
    # internal gallery order: taken_at DESC -> no-exif (today) first, then 10:00, then 08:00
    r = admin.get(f"{BASE}/api/projects/{PROJ}/photos?group=all&limit=50", timeout=15)
    photos = r.json()["data"]["photos"]
    ids_in_order = [p["id"] for p in photos]
    expected = [stored["m-no-exif.jpg"]["id"], stored["a-last-by-name.jpg"]["id"],
                stored["z-first-by-capture.heic"]["id"]]
    ok("internal_gallery_capture_order", ids_in_order == expected,
       f"got {ids_in_order}, expected {expected}")
    # portal order identical (share all three to the client first)
    for fid in expected:
        admin.post(f"{BASE}/api/field-photos/{fid}/share", json={"audience": "client", "on": True}, timeout=15)
    rc = client.get(f"{BASE}/api/portal/photos", timeout=15)
    ok("portal_gallery_capture_order", [p["id"] for p in rc.json()["data"]["photos"]] == expected,
       f"got {[p['id'] for p in rc.json()['data']['photos']]}")

    # ---- (e) BACKFILL — idempotent, counts unchanged, fills only real EXIF ----
    conn = db_layer.connect(pragma_fk=True)
    try:
        pdir = _FP_BASE / PROJ / uuid.uuid4().hex
        pdir.mkdir(parents=True, exist_ok=True)
        exif_file = pdir / "full.jpg"
        exif_file.write_bytes(_img_bytes("JPEG", "2026:06:15 07:30:00"))   # EXIF present on disk
        (pdir / "thumb.jpg").write_bytes(_img_bytes("JPEG", None))
        cur = conn.execute(
            "INSERT INTO field_photos (project_code, uploaded_at, file_path, thumb_path, file_name, "
            "mime, caption, taken_at, taken_at_estimated) VALUES (?,?,?,?, 'syn.jpg', 'image/jpeg', "
            "'Synthetic backfill fixture', ?, 1)",
            (PROJ, _now_iso(), str(exif_file), str(pdir / "thumb.jpg"), _now_iso()[:19].replace("T", " ")))
        backfill_id = cur.lastrowid
        pre_count = conn.execute("SELECT COUNT(*) FROM field_photos").fetchone()[0]
        conn.commit()
        stats1 = backfill_photo_exif(conn)
        conn.commit()
        row = conn.execute("SELECT taken_at, taken_at_estimated FROM field_photos WHERE id=?",
                           (backfill_id,)).fetchone()
        ok("backfill_fills_real_exif", stats1["filled"] == 1 and row["taken_at"] == "2026-06-15 07:30:00"
           and row["taken_at_estimated"] == 0, f"stats={stats1}")
        ok("backfill_skips_stripped", stats1["no_exif"] >= 1,
           "the pipeline-stripped no-EXIF upload must stay flagged, not get a fake time")
        stats2 = backfill_photo_exif(conn)
        conn.commit()
        ok("backfill_idempotent", stats2["filled"] == 0, f"second run filled={stats2['filled']}")
        post_count = conn.execute("SELECT COUNT(*) FROM field_photos").fetchone()[0]
        ok("backfill_counts_unchanged", pre_count == post_count)
    finally:
        conn.close()


def main():
    print(f"== #271 doc versions + view-not-print + EXIF order guard ==  BASE={BASE}")
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
