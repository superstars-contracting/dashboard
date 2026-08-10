"""#294 GUARD — field photo reassignment history + edit tracking + DCR amend flag.

What it proves:
  HISTORY     single AND multi-select batch reassignment move the photo(s) and
              write one history row per photo (from -> to, actor, optional
              reason, timing-since-upload) in the SAME act; a no-op assign
              writes nothing; the tray flow (unassigned -> drop) is logged but
              never counts as a correction (no marker, no analytics).
  MARKER      the gallery payload carries reassigned/reassign_count for
              corrected photos only; /api/field-photos/<id>/history serves the
              trail to editors.
  SCOPE       a selection spanning two projects is refused (400); a target
              drop from another project is refused (400) — a photo moves
              between drops of ITS project, never to another project.
  DCR FLAG    a correction whose photo's taken-at day has an ISSUED DCR is
              ALLOWED but flags report_index.photo_amended (+at), returns the
              amendment in the assign response, writes an audit_log row, and
              the archive listing (/api/projects/<code>/reports) carries the
              visible marker.
  SELF-SERVE  pm can reassign (200) — correcting a mistake is a ~10-second
              act; client 403; anonymous 401. Pattern view / alerts /
              threshold are admin+c_suite ONLY (pm 403, client 403, anon 401).
  ALERTS      quiet under the threshold; a planted >N/user/7d spike fires with
              the right timing bucket + reading; ANY whole-batch correction
              fires its own alert; the threshold is SETTABLE via the API and
              raising it silences the spike.
  BUCKETS     planted lags classify minutes / hours / days exactly.
  PII         alert payloads carry uid / W-#### in 'who' — never a name.

Runs against the shared gate server (SMOKE_BASE). Isolated backend REQUIRED —
the suite seeds users/projects/photos and refuses to run without SSC_DB_URL.
PII-safe: synthetic identities; ids/counts/booleans only.
"""
from __future__ import annotations

import os
import secrets
import sys
from datetime import datetime, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PA, PB = "SMK294-A", "SMK294-B"
PASS, FAIL = [], []
IDS = {"users": []}


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note and not cond else ""))
    return bool(cond)


def now_s(**delta):
    return (datetime.now() - timedelta(**delta)).strftime("%Y-%m-%d %H:%M:%S")


def seed():
    conn = db_layer.connect()
    try:
        for code in (PA, PB):
            conn.execute("DELETE FROM projects WHERE project_code=?", (code,))
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?, 'active')",
                         (code, f"Smoke 294 {code[-1]}"))
            conn.execute("DELETE FROM drops WHERE project_code=?", (code,))
            for i in (7, 8):
                conn.execute("INSERT INTO drops (drop_id, project_code, sequence_no, elevation) "
                             "VALUES (?,?,?, 'N')", (f"{code}-DP{i}", code, i))
        users = {}
        for key, role in (("adm", "c_suite"), ("pma", "pm"), ("cl", "client")):
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, full_name, is_active, status, "
                "must_reset_password, is_system) VALUES (?,?,?,?,1,'active',0,1)",
                (f"smk294-{key}@superstars.local", "x!unusable", role, f"SMK294 {key}"))
            users[key] = cur.lastrowid
            IDS["users"].append(cur.lastrowid)
        for key in ("pma", "cl"):
            conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, "
                         "assigned_at) VALUES (?,?,?,?)",
                         (users[key], PA, users["adm"], now_s()))
        sessions = {}
        for key, uid in users.items():
            tok = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions (id, user_id, expires_at, user_agent) "
                         "VALUES (?,?, '2099-01-01T00:00:00', 'smk294')", (tok, uid))
            sessions[key] = tok
        conn.commit()
        return users, sessions
    finally:
        conn.close()


def plant_photo(conn, code, drop, uploaded_at, uid, name="p.jpg", taken_at=None):
    cur = conn.execute(
        "INSERT INTO field_photos (project_code, drop_id, taken_at, taken_at_estimated, "
        "uploaded_at, uploaded_by_uid, file_name, file_path, thumb_path) "
        "VALUES (?,?,?,0,?,?,?, 'data_room/field_photos/x/full.jpg', "
        "'data_room/field_photos/x/thumb.jpg')",
        (code, drop, taken_at or uploaded_at, uploaded_at, uid, name))
    return cur.lastrowid


def cleanup():
    conn = db_layer.connect()
    try:
        for sql, args in [
            ("DELETE FROM field_photo_reassign WHERE project_code IN (?,?)", (PA, PB)),
            ("DELETE FROM field_photos WHERE project_code IN (?,?)", (PA, PB)),
            ("DELETE FROM report_index WHERE project_code IN (?,?)", (PA, PB)),
            ("DELETE FROM drops WHERE project_code IN (?,?)", (PA, PB)),
            ("DELETE FROM audit_log WHERE action='fp_reassign_after_issue' AND "
             "target_id IN (SELECT CAST(id AS TEXT) FROM report_index "
             "WHERE project_code IN (?,?))", (PA, PB)),
        ]:
            try:
                conn.execute(sql, args)
            except Exception as e:
                print(f"    [cleanup] {e}")
        # audit rows referencing already-deleted report rows: sweep by actor
        uids = IDS["users"]
        if uids:
            ph = ",".join("?" * len(uids))
            try:
                conn.execute(f"DELETE FROM audit_log WHERE action='fp_reassign_after_issue' "
                             f"AND actor_user_id IN ({ph})", tuple(uids))
            except Exception:
                pass
            for t, c in (("client_section_grant", "user_id"), ("pm_project_assignment", "user_id"),
                         ("sessions", "user_id"), ("login_audit", "user_id"),
                         ("audit_log", "actor_user_id"), ("role_change_audit", "user_id")):
                try:
                    conn.execute(f"DELETE FROM {t} WHERE {c} IN ({ph})", tuple(uids))
                except Exception as e:
                    print(f"    [cleanup] {t}: {e}")
            conn.execute(f"DELETE FROM users WHERE id IN ({ph})", tuple(uids))
        conn.execute("DELETE FROM projects WHERE project_code IN (?,?)", (PA, PB))
        # restore the default threshold in case a run died mid-flight
        conn.execute("UPDATE app_settings SET value='5' WHERE key='fp_reassign_alert_threshold'")
        conn.commit()
        print("  [cleanup] synthetic rows removed (scoped to SMK294 ids)")
    finally:
        conn.close()


def S(sessions, key):
    s = requests.Session()
    s.cookies.set("ssc_session", sessions[key])
    return s


def run():
    users, sessions = seed()
    R = dict(timeout=30)
    ADM, PM, CL = S(sessions, "adm"), S(sessions, "pma"), S(sessions, "cl")

    conn = db_layer.connect()
    try:
        up_recent = now_s(minutes=5)
        day = up_recent[:10]
        # a 3-photo upload batch on DP7 (the mislabeled-batch origin case)
        batch = [plant_photo(conn, PA, f"{PA}-DP7", up_recent, users["pma"], f"b{i}.jpg")
                 for i in range(3)]
        # a lone photo on DP7, uploaded days ago
        lone = plant_photo(conn, PA, f"{PA}-DP7", now_s(days=3), users["pma"], "lone.jpg")
        # an unassigned tray photo — its OWN upload stamp: sharing the batch's
        # (uploader, uploaded_at) would make the upload group 4 photos and
        # correctly defeat whole-batch detection on the 3-photo move.
        tray = plant_photo(conn, PA, None, now_s(minutes=4), users["pma"], "tray.jpg")
        # project-B photo + an issued DCR on project A's day
        bphoto = plant_photo(conn, PB, f"{PB}-DP7", up_recent, users["adm"], "b.jpg")
        conn.execute("INSERT INTO report_index (report_date, project_code, report_type, status, "
                     "report_id, dcr_sequence, no_work) VALUES (?,?, 'DCR', 'issued', ?, 901, 0)",
                     (day, PA, f"DCR-{PA}-901-internal"))
        conn.commit()
    finally:
        conn.close()

    print("\n-- single reassign: history + move + reason --")
    r = PM.post(f"{BASE}/api/field-photos/assign",
                json={"photo_ids": [lone], "drop_id": f"{PA}-DP8", "reason": "wrong drop"}, **R)
    ok("single_reassign_200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    d = (r.json() or {}).get("data") or {}
    ok("single_counts", d.get("changed") == 1 and d.get("corrections") == 1, str(d))
    conn = db_layer.connect()
    try:
        row = conn.execute("SELECT drop_id FROM field_photos WHERE id=?", (lone,)).fetchone()
        ok("single_photo_moved", row["drop_id"] == f"{PA}-DP8")
        h = conn.execute("SELECT * FROM field_photo_reassign WHERE photo_id=?", (lone,)).fetchall()
        ok("single_history_row", len(h) == 1 and h[0]["from_drop_id"] == f"{PA}-DP7"
           and h[0]["to_drop_id"] == f"{PA}-DP8" and h[0]["reason"] == "wrong drop"
           and h[0]["actor_uid"] == users["pma"])
        ok("single_lag_days_bucket", h[0]["seconds_since_upload"] > 2 * 86400)
    finally:
        conn.close()

    print("\n-- no-op writes nothing --")
    r = PM.post(f"{BASE}/api/field-photos/assign",
                json={"photo_ids": [lone], "drop_id": f"{PA}-DP8"}, **R)
    ok("noop_200", r.status_code == 200)
    ok("noop_no_change", (r.json().get("data") or {}).get("changed") == 0)

    print("\n-- batch reassign: the whole mislabeled upload, DCR day flagged --")
    r = PM.post(f"{BASE}/api/field-photos/assign",
                json={"photo_ids": batch, "drop_id": f"{PA}-DP8",
                      "reason": "batch labeled Drop 7, belongs to Drop 8"}, **R)
    ok("batch_reassign_200", r.status_code == 200, f"{r.status_code} {r.text[:150]}")
    d = (r.json() or {}).get("data") or {}
    ok("batch_counts", d.get("changed") == 3 and d.get("corrections") == 3, str(d))
    ok("batch_whole_batch_true", d.get("whole_batch") is True)
    ok("batch_dcr_amended_returned", len(d.get("dcr_amended") or []) == 1
       and d["dcr_amended"][0]["photos"] == 3, str(d.get("dcr_amended")))
    conn = db_layer.connect()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM field_photo_reassign WHERE photo_id IN "
                         f"({','.join('?' * 3)})", batch).fetchone()["n"]
        ok("batch_history_rows", n == 3, str(n))
        ri = conn.execute("SELECT photo_amended, photo_amended_at FROM report_index "
                          "WHERE project_code=? AND report_date=?", (PA, day)).fetchone()
        ok("dcr_flag_set", ri and ri["photo_amended"] == 1 and ri["photo_amended_at"])
        au = conn.execute("SELECT COUNT(*) AS n FROM audit_log WHERE "
                          "action='fp_reassign_after_issue' AND actor_user_id=?",
                          (users["pma"],)).fetchone()["n"]
        ok("dcr_audit_row", au == 1, str(au))
    finally:
        conn.close()
    r = ADM.get(f"{BASE}/api/projects/{PA}/reports?report_type=DCR", **R)
    rows = (r.json() or {}).get("data") or []
    arch = next((x for x in rows if x.get("report_date") == day), None)
    ok("archive_carries_marker", arch is not None and arch.get("photo_amended") == 1,
       str({k: arch.get(k) for k in ("report_date", "photo_amended")} if arch else None))

    print("\n-- markers + history endpoint; tray assign is not a correction --")
    r = PM.get(f"{BASE}/api/projects/{PA}/photos?group=all&limit=100", **R)
    photos = ((r.json() or {}).get("data") or {}).get("photos") or []
    by_id = {p["id"]: p for p in photos}
    ok("marker_on_corrected", all(by_id.get(p, {}).get("reassigned") for p in batch + [lone]))
    r = PM.post(f"{BASE}/api/field-photos/assign",
                json={"photo_ids": [tray], "drop_id": f"{PA}-DP7"}, **R)
    ok("tray_assign_200", r.status_code == 200 and
       (r.json().get("data") or {}).get("corrections") == 0)
    r = PM.get(f"{BASE}/api/projects/{PA}/photos?group=all&limit=100", **R)
    photos = ((r.json() or {}).get("data") or {}).get("photos") or []
    by_id = {p["id"]: p for p in photos}
    ok("tray_no_marker", by_id.get(tray, {}).get("reassigned") is False, str(by_id.get(tray)))
    r = PM.get(f"{BASE}/api/field-photos/{lone}/history", **R)
    hist = (r.json() or {}).get("data") or []
    ok("history_endpoint_editor", r.status_code == 200 and len(hist) == 1
       and hist[0]["bucket"] == "days" and hist[0]["correction"] is True)
    r = CL.get(f"{BASE}/api/field-photos/{lone}/history", **R)
    ok("history_client_403", r.status_code == 403, str(r.status_code))
    r = requests.get(f"{BASE}/api/field-photos/{lone}/history", timeout=20)
    ok("history_anon_401", r.status_code == 401, str(r.status_code))

    print("\n-- same-project guard --")
    r = PM.post(f"{BASE}/api/field-photos/assign",
                json={"photo_ids": [lone, bphoto], "drop_id": f"{PA}-DP8"}, **R)
    ok("cross_project_selection_400", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
    r = PM.post(f"{BASE}/api/field-photos/assign",
                json={"photo_ids": [lone], "drop_id": f"{PB}-DP8"}, **R)
    ok("cross_project_drop_400", r.status_code == 400, f"{r.status_code} {r.text[:120]}")
    conn = db_layer.connect()
    try:
        row = conn.execute("SELECT drop_id, project_code FROM field_photos WHERE id=?",
                           (lone,)).fetchone()
        ok("photo_unmoved_after_refusals", row["drop_id"] == f"{PA}-DP8"
           and row["project_code"] == PA)
    finally:
        conn.close()

    print("\n-- self-service permission --")
    r = CL.post(f"{BASE}/api/field-photos/assign",
                json={"photo_ids": [lone], "drop_id": f"{PA}-DP7"}, **R)
    ok("client_assign_403", r.status_code == 403, str(r.status_code))
    r = requests.post(f"{BASE}/api/field-photos/assign",
                      json={"photo_ids": [lone], "drop_id": f"{PA}-DP7"}, timeout=20)
    ok("anon_assign_401", r.status_code == 401, str(r.status_code))

    print("\n-- pattern view + alerts: admin-only, buckets, planted spike --")
    for name, sess, want in (("patterns_pm_403", PM, 403), ("patterns_client_403", CL, 403)):
        rr = sess.get(f"{BASE}/api/admin/photo-edit-patterns", **R)
        ok(name, rr.status_code == want, str(rr.status_code))
    ok("patterns_anon_401",
       requests.get(f"{BASE}/api/admin/photo-edit-patterns", timeout=20).status_code == 401)
    for name, sess, want in (("alerts_pm_403", PM, 403), ("alerts_client_403", CL, 403)):
        rr = sess.get(f"{BASE}/api/admin/photo-edit-alerts", **R)
        ok(name, rr.status_code == want, str(rr.status_code))
    r = ADM.get(f"{BASE}/api/admin/photo-edit-patterns?days=30", **R)
    pat = (r.json() or {}).get("data") or {}
    me = next((u for u in pat.get("users") or [] if u["actor_uid"] == users["pma"]), None)
    ok("patterns_row_present", me is not None and me["corrections"] == 4, str(me))
    ok("patterns_buckets", me is not None and me["buckets"]["minutes"] == 3
       and me["buckets"]["days"] == 1, str(me and me["buckets"]))
    ok("patterns_whole_batch_count", me is not None and me["whole_batch"] == 3)

    # ROBUSTNESS: the alerts feed is GLOBAL — a gate snapshot taken after real
    # corrections exist on live will carry other users' rows. Every assertion
    # below is scoped to THIS suite's uids, never to the whole feed.
    mine = set(users.values())
    r = ADM.get(f"{BASE}/api/admin/photo-edit-alerts", **R)
    al = (r.json() or {}).get("data") or {}
    my_alerts = [a for a in al.get("alerts") or [] if a.get("actor_uid") in mine]
    ok("alert_whole_batch_fires", any(a["kind"] == "whole_batch" for a in my_alerts),
       str([a["kind"] for a in my_alerts]))
    ok("alert_quiet_under_threshold",
       not any(a["kind"] == "user_over_threshold" for a in my_alerts),
       f"threshold={al.get('threshold')} mine={[a['kind'] for a in my_alerts]}")
    ok("alert_who_not_name", all("SMK294" not in str(a.get("who")) for a in al.get("alerts") or []))

    # plant a >threshold spike (6 corrections, minutes-lag) directly in the log
    conn = db_layer.connect()
    try:
        for i in range(6):
            conn.execute(
                "INSERT INTO field_photo_reassign (photo_id, project_code, from_drop_id, "
                "to_drop_id, actor_uid, batch_key, seconds_since_upload, whole_batch, "
                "dcr_amended, created_at) VALUES (?,?,?,?,?,?,?,0,0,?)",
                (900000 + i, PA, f"{PA}-DP7", f"{PA}-DP8", users["adm"],
                 f"{users['adm']}|spike{i}", 120, now_s(hours=i)))
        conn.commit()
    finally:
        conn.close()
    r = ADM.get(f"{BASE}/api/admin/photo-edit-alerts", **R)
    al = (r.json() or {}).get("data") or {}
    over = [a for a in al.get("alerts") or []
            if a["kind"] == "user_over_threshold" and a.get("actor_uid") == users["adm"]]
    ok("alert_spike_fires", len(over) == 1 and over[0]["count"] == 6, str(over))
    ok("alert_spike_bucket_minutes", bool(over) and over[0]["dominant_bucket"] == "minutes"
       and "upload UI" in over[0]["reading"], str(over and over[0]["reading"]))

    print("\n-- threshold is settable (and silences the spike) --")
    r = PM.post(f"{BASE}/api/admin/photo-edit-alerts/threshold", json={"threshold": 50}, **R)
    ok("threshold_pm_403", r.status_code == 403, str(r.status_code))
    r = ADM.post(f"{BASE}/api/admin/photo-edit-alerts/threshold", json={"threshold": 0}, **R)
    ok("threshold_rejects_zero", r.status_code == 400, str(r.status_code))
    r = ADM.post(f"{BASE}/api/admin/photo-edit-alerts/threshold", json={"threshold": 50}, **R)
    ok("threshold_set_200", r.status_code == 200 and r.json()["data"]["threshold"] == 50)
    r = ADM.get(f"{BASE}/api/admin/photo-edit-alerts", **R)
    silenced = [a for a in ((r.json() or {}).get("data") or {}).get("alerts") or []
                if a["kind"] == "user_over_threshold" and a.get("actor_uid") in mine]
    ok("threshold_raised_silences_spike", not silenced, str(silenced))
    r = ADM.post(f"{BASE}/api/admin/photo-edit-alerts/threshold", json={"threshold": 5}, **R)
    ok("threshold_restored", r.status_code == 200)


def main() -> int:
    if not (os.environ.get("SSC_DB_URL") or "").strip():
        print("REFUSING TO RUN: SSC_DB_URL is unset (this suite seeds users/projects/photos).")
        return 2
    print(f"#294 smoke_photo_reassign: target={BASE}")
    try:
        run()
    finally:
        cleanup()
        print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        for f in FAIL:
            print(f"  FAILED: {f}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())

