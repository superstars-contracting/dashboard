#!/usr/bin/env python3
"""#277 — Walkthrough scheduling + iPad report guard smoke (dual-backend).

Proves, fail->pass where practical:
  (a) VISIT CRUD — attendee NOT NULL (400 without); date validation; multiple
      visits per estimate; history never deleted (cancel keeps the row).
  (b) STAGE SYNC ARCS (the #276 machine stays the single truth): schedule ->
      walkthrough_scheduled; visit-done -> walkthrough_done; cancel-with-no-other-
      scheduled -> back to received; the TWO-VISIT case (cancel one of two keeps
      the stage; cancelling the last reverts).
  (c) walkthrough_date DERIVATION — MIN(scheduled) else MAX(done) else NULL at
      every step; the field never drifts from the visits (and the #276 stage
      endpoint's schedule path lands in the same derivation).
  (d) CALENDAR MERGE — /api/company/schedule carries BOTH kinds on the right
      days (walkthrough + inspection), same-day stacking intact; the #274
      /api/ira/calendar endpoint is untouched (its own suite stays green).
  (e) REPORT/PHOTO — multipart upload (JPEG + HEIC, BOTH with GPS EXIF planted)
      -> gated by-id serves (inline); STORED BYTES read back and asserted
      GPS-FREE (no GPSInfo IFD, no tag 34853); the HEIC capture time SURVIVES
      into taken_at (estimated=0); captions kept.
  (f) PER-RESOURCE ISOLATION — pm AND super AND client 403 on every walkthrough
      endpoint incl. photo/thumb; unknown ids 404; estimator reaches only the
      'estimating' surfaces (company schedule 403).
  (g) FORBIDDEN KEYS — no *_path key in any payload seen.

Isolation: SMOKE_BASE isolated server; REFUSES without SSC_DB_URL. Synthetic-only
SMK277-* users / the WT-QN series (FR/IR at borough QN), is_system=1, random
per-run password, FK-safe scoped teardown incl. on-disk photo dirs. PII-safe.
"""
from __future__ import annotations

import io
import os
import shutil
import sys
import secrets
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

import db_layer            # noqa: E402
from auth import hash_password  # noqa: E402
from apply_walkthroughs_277 import ensure_walkthroughs_schema  # noqa: E402
import crm                 # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PW = secrets.token_urlsafe(18)
USERS = {
    "csuite": "smk277-csuite@superstars.local",
    "est":    "smk277-wt-est@superstars.local",
    "pm":     "smk277-wt-pm@superstars.local",
    "super":  "smk277-wt-super@superstars.local",
    "client": "smk277-wt-client@superstars.local",
}
ROLE_OF = {"csuite": "c_suite", "est": "estimator", "pm": "pm", "super": "super", "client": "client"}
ORG_NAME = "SMK277 WT Org"
SERIES = (("FR", "QN"), ("IR", "QN"))
TODAY = date.today()
_WT_DIR = SCRIPT_DIR.parent / "data_room" / "walkthroughs"

PASS, FAIL = [], []
SEEN = []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def _img_bytes(fmt, exif_dt=None, gps=True):
    """Tiny JPEG/HEIF with EXIF DateTimeOriginal + a PLANTED GPS IFD — the strip
    proof needs GPS present on the way IN."""
    from PIL import Image
    im = Image.new("RGB", (48, 36), (110, 55, 55))
    ex = Image.Exif()
    if exif_dt:
        ex[306] = exif_dt
        ex.get_ifd(0x8769)[36867] = exif_dt
    if gps:
        g = ex.get_ifd(0x8825)
        g[1] = 'N'; g[2] = (40.0, 44.0, 30.0); g[3] = 'W'; g[4] = (73.0, 59.0, 10.0)
    if fmt == "HEIF":
        import pillow_heif
        pillow_heif.register_heif_opener()
    buf = io.BytesIO()
    im.save(buf, fmt, exif=ex.tobytes())
    return buf.getvalue()


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_walkthroughs_schema(conn)
        for key, email in USERS.items():
            role = ROLE_OF[key]
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET password_hash=?, role=?, is_active=1, status='active', "
                    "must_reset_password=0, is_system=1 WHERE email=?", (hash_password(PW), role, email))
            else:
                conn.execute(
                    "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                    "must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                    (email, hash_password(PW), role, f"SMK277 {key}"))
        conn.commit()
        if not conn.execute("SELECT 1 FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone():
            crm.create_org(conn, name=ORG_NAME, relationship_type="client")
        return conn.execute("SELECT id FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone()[0]
    finally:
        conn.close()


def _uid(conn, key):
    r = conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()
    return r[0] if r else None


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        # FIRST: the planted merge-test project — its ira_job row references the
        # IR-QN estimate, so it must go before the estimate loop (FK order).
        conn.execute("DELETE FROM ira_visit WHERE project_code='IR-QN-777'")
        conn.execute("DELETE FROM ira_job WHERE project_code='IR-QN-777'")
        conn.execute("DELETE FROM projects WHERE project_code='IR-QN-777'")
        codes = []
        for t, b in SERIES:
            for r in conn.execute("SELECT id, code FROM estimate WHERE est_type=? AND borough=?",
                                  (t, b)).fetchall():
                codes.append(r[1])
                for rep in conn.execute("SELECT id FROM walkthrough_report WHERE estimate_id=?",
                                        (r[0],)).fetchall():
                    conn.execute("DELETE FROM walkthrough_photo WHERE report_id=?", (rep[0],))
                    conn.execute("DELETE FROM walkthrough_report WHERE id=?", (rep[0],))
                conn.execute("DELETE FROM walkthrough_visit WHERE estimate_id=?", (r[0],))
                conn.execute("DELETE FROM ira_visit WHERE project_code=?", (r[1],))
                conn.execute("DELETE FROM ira_job WHERE project_code=?", (r[1],))
                conn.execute("DELETE FROM estimate_document WHERE estimate_id=?", (r[0],))
                conn.execute("DELETE FROM estimate_ira WHERE estimate_id=?", (r[0],))
                conn.execute("DELETE FROM estimate WHERE id=?", (r[0],))
                conn.execute("DELETE FROM projects WHERE project_code=?", (r[1],))
        org = conn.execute("SELECT id FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone()
        if org:
            conn.execute("DELETE FROM crm_activity WHERE entity_type='organization' AND entity_id=?", (org[0],))
            conn.execute("DELETE FROM crm_contact WHERE org_id=?", (org[0],))
            conn.execute("DELETE FROM crm_organization WHERE id=?", (org[0],))
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                conn.execute("DELETE FROM notification_log WHERE recipient_user_id=?", (u[0],))
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM users WHERE id=?", (u[0],))
        conn.commit()
        for c in codes:
            shutil.rmtree(_WT_DIR / c, ignore_errors=True)
    finally:
        conn.close()


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _sc(sess, method, path, **kw):
    r = sess.request(method, f"{BASE}{path}", timeout=20, **kw)
    body = None
    try:
        body = r.json()
        SEEN.append(body)
    except Exception:
        pass
    return r.status_code, body


def _forbidden_keys(obj, found):
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl.endswith("_path") or kl in ("filepath", "folder_slug"):
                found.append(k)
            _forbidden_keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _forbidden_keys(v, found)


def _wt_date(conn, est_id):
    return conn.execute("SELECT walkthrough_date, est_stage FROM estimate WHERE id=?",
                        (est_id,)).fetchone()


def main():
    if not (os.environ.get("SSC_DB_URL") or "").strip():
        print("REFUSING TO RUN: SSC_DB_URL is unset.")
        return 2
    print(f"#277 walkthroughs guard — BASE={BASE}  backend={'postgres' if db_layer.is_postgres() else 'sqlite'}")
    _cleanup()
    org_id = _seed()
    try:
        cs, es, pm, su, cl = (_login("csuite"), _login("est"), _login("pm"),
                              _login("super"), _login("client"))
        ok("logins", all([cs, es, pm, su]))
        if not cs or not es:
            print("cannot proceed"); return 1
        conn0 = db_layer.connect()
        att = _uid(conn0, "est")
        conn0.close()

        # lead A (FR-QN) at scoping/received
        st, body = _sc(cs, "POST", "/api/estimates",
                       json={"est_type": "FR", "borough": "QN", "client_org_id": org_id,
                             "building_address": "SMK277 77 Walk Way"})
        a_id = (body or {}).get("data", {}).get("id")
        _sc(es, "POST", f"/api/estimating/{a_id}/start")

        # ---------- (a) attendee NOT NULL + validation ----------
        st, _ = _sc(es, "POST", f"/api/estimating/{a_id}/walkthroughs",
                    json={"visit_date": (TODAY + timedelta(days=2)).isoformat()})
        ok("attendee_required_400", st == 400)
        st, _ = _sc(es, "POST", f"/api/estimating/{a_id}/walkthroughs",
                    json={"visit_date": "not-a-date", "attendee_user_id": att})
        ok("bad_date_400", st == 400)

        # ---------- (b)+(c) schedule -> scheduled + derivation ----------
        d2 = (TODAY + timedelta(days=2)).isoformat()
        d5 = (TODAY + timedelta(days=5)).isoformat()
        st, body = _sc(es, "POST", f"/api/estimating/{a_id}/walkthroughs",
                       json={"visit_date": d5, "attendee_user_id": att})
        v1 = ((body or {}).get("data", {}) or {}).get("id")
        ok("schedule_200", st == 200 and bool(v1))
        conn = db_layer.connect()
        row = _wt_date(conn, a_id); conn.close()
        ok("stage_scheduled", row and row[1] == "walkthrough_scheduled")
        ok("derived_is_min_scheduled", row and row[0] == d5)
        # revisit EARLIER -> derivation follows MIN
        st, body = _sc(es, "POST", f"/api/estimating/{a_id}/walkthroughs",
                       json={"visit_date": d2, "attendee_user_id": att})
        v2 = ((body or {}).get("data", {}) or {}).get("id")
        ok("revisit_200_two_visits", st == 200 and bool(v2))
        conn = db_layer.connect()
        row = _wt_date(conn, a_id); conn.close()
        ok("derived_follows_min", row and row[0] == d2)
        # TWO-VISIT cancel case: cancel one -> stage stays; cancel last -> reverts
        st, _ = _sc(es, "POST", f"/api/walkthroughs/visits/{v2}/cancel")
        conn = db_layer.connect()
        row = _wt_date(conn, a_id)
        nvis = conn.execute("SELECT COUNT(*) FROM walkthrough_visit WHERE estimate_id=?",
                            (a_id,)).fetchone()[0]
        conn.close()
        ok("cancel_one_of_two_stage_stays", st == 200 and row[1] == "walkthrough_scheduled")
        ok("cancel_history_kept", nvis == 2)
        ok("derived_back_to_remaining", row[0] == d5)
        st, _ = _sc(es, "POST", f"/api/walkthroughs/visits/{v1}/cancel")
        conn = db_layer.connect()
        row = _wt_date(conn, a_id); conn.close()
        ok("cancel_last_reverts_stage", st == 200 and row[1] == "received")
        ok("derived_null_when_none", row[0] is None)
        # re-schedule then DONE -> walkthrough_done + derived = done date
        st, body = _sc(es, "POST", f"/api/estimating/{a_id}/walkthroughs",
                       json={"visit_date": d2, "attendee_user_id": att})
        v3 = ((body or {}).get("data", {}) or {}).get("id")
        st, _ = _sc(es, "POST", f"/api/walkthroughs/visits/{v3}/done")
        conn = db_layer.connect()
        row = _wt_date(conn, a_id); conn.close()
        ok("visit_done_stage_done", st == 200 and row[1] == "walkthrough_done")
        ok("derived_max_done", row[0] == d2)
        # the #276 stage endpoint path lands in the SAME machinery (delegation)
        st, body = _sc(cs, "POST", "/api/estimates",
                       json={"est_type": "IR", "borough": "QN", "client_org_id": org_id})
        b_id = (body or {}).get("data", {}).get("id")
        _sc(es, "POST", f"/api/estimating/{b_id}/start")
        st, _ = _sc(es, "POST", f"/api/estimating/{b_id}/stage",
                    json={"stage": "walkthrough_scheduled", "walkthrough_date": d5})
        conn = db_layer.connect()
        nv = conn.execute("SELECT COUNT(*) FROM walkthrough_visit WHERE estimate_id=?",
                          (b_id,)).fetchone()[0]
        row = _wt_date(conn, b_id); conn.close()
        ok("stage_endpoint_creates_visit", st == 200 and nv == 1)
        ok("stage_endpoint_same_derivation", row and row[0] == d5 and row[1] == "walkthrough_scheduled")

        # ---------- (d) calendar merge (walkthrough + inspection, correct days) ----------
        conn = db_layer.connect()
        try:
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES ('IR-QN-777','smk277 wt','active')")
            conn.execute("INSERT INTO ira_job (project_code, estimate_id, cd5_status, deposit_received, balance_status) "
                         "VALUES ('IR-QN-777', ?, 'not_filed', 0, 'open')", (b_id,))
            conn.execute("INSERT INTO ira_visit (project_code, visit_date, label, status, created_at) "
                         "VALUES ('IR-QN-777', ?, 'smk277 crew', 'scheduled', ?)", (d5, d5))
            conn.commit()
        finally:
            conn.close()
        st, body = _sc(cs, "GET", f"/api/company/schedule?month={d5[:7]}")
        evs = ((body or {}).get("data", {}) or {}).get("events", [])
        kinds_on_d5 = sorted(e["kind"] for e in evs if e["date"] == d5)
        ok("schedule_merges_both_kinds", st == 200 and "inspection" in kinds_on_d5
           and "walkthrough" in kinds_on_d5, f"d5 kinds: {kinds_on_d5}")
        wt_ev = next((e for e in evs if e["kind"] == "walkthrough" and e["date"] == d5), {})
        ok("walkthrough_event_has_initials", bool(wt_ev.get("attendee_initials")))
        st, _ = _sc(cs, "GET", "/api/ira/calendar")
        ok("ira_calendar_untouched_200", st == 200)

        # ---------- (d2) AMENDMENT: visit_time + calendar-app event shape ----------
        st, _ = _sc(es, "POST", f"/api/estimating/{a_id}/walkthroughs",
                    json={"visit_date": d5, "visit_time": "25:99", "attendee_user_id": att})
        ok("bad_time_400", st == 400)
        st, body = _sc(es, "POST", f"/api/estimating/{a_id}/walkthroughs",
                       json={"visit_date": d5, "visit_time": "14:30", "attendee_user_id": att})
        tv = ((body or {}).get("data", {}) or {})
        ok("timed_visit_200_time_verbatim", st == 200 and tv.get("visit_time") == "14:30")
        st, body = _sc(cs, "GET", f"/api/company/schedule?month={d5[:7]}")
        evs = ((body or {}).get("data", {}) or {}).get("events", [])
        on_d5 = [(e["kind"], e["time"]) for e in evs if e["date"] == d5]
        ok("allday_null_time_kept", (("walkthrough", None) in on_d5) and (("inspection", None) in on_d5))
        ok("timed_event_carries_time", ("walkthrough", "14:30") in on_d5)
        # within a day: ALL-DAY first, then timed (calendar convention)
        ok("within_day_allday_first",
           on_d5[-1] == ("walkthrough", "14:30") and all(t is None for _, t in on_d5[:-1]),
           f"d5 order: {on_d5}")
        # CALENDAR-APP SHAPE: date/time/title/location/attendee — the future
        # per-person ICS feed serializes these 1:1 (DTSTART, SUMMARY, LOCATION,
        # ATTENDEE) with no rework.
        timed = next(e for e in evs if e["date"] == d5 and e["time"] == "14:30")
        ok("event_ics_shape_keys",
           all(k in timed for k in ("date", "time", "title", "location",
                                    "attendee_name", "attendee_initials", "kind", "status")))
        ok("event_title_is_summary", "Walkthrough" in timed["title"] and "FR-QN" in timed["title"])
        ok("event_location_is_address", timed.get("location") == "SMK277 77 Walk Way")
        # the estimator's upcoming list carries the time too
        st, body = _sc(es, "GET", "/api/estimating/queue")
        ups = ((body or {}).get("data", {}) or {}).get("walkthroughs_upcoming", [])
        ok("upcoming_list_carries_time",
           any(u.get("visit_time") == "14:30" for u in ups))

        # ---------- (e) report upload: GPS-strip + HEIC taken_at ----------
        heic = _img_bytes("HEIF", exif_dt="2026:07:05 10:15:00", gps=True)
        jpg = _img_bytes("JPEG", exif_dt="2026:07:05 09:00:00", gps=True)
        from PIL import Image as _Im
        ok("fixture_heic_carries_gps",
           len(_Im.open(io.BytesIO(heic)).getexif().get_ifd(0x8825)) > 0)
        st, body = _sc(es, "POST", f"/api/estimating/{a_id}/walkthrough-report",
                       files=[("photos", ("smk277-a.heic", heic, "image/heic")),
                              ("photos", ("smk277-b.jpg", jpg, "image/jpeg"))],
                       data={"note": "SMK277 roof notes", "captions": ["north", "setback"]})
        rep = (body or {}).get("data", {}) or {}
        ok("report_created_201", st == 201 and rep.get("photo_count") == 2, f"{st} {rep.get('skipped')}")
        taken = sorted(p["taken_at"] for p in rep.get("photos", []))
        ok("heic_taken_at_survives", "2026-07-05 10:15:00" in taken and "2026-07-05 09:00:00" in taken,
           f"got {taken}")
        ok("taken_at_not_estimated", all(not p["taken_at_estimated"] for p in rep.get("photos", [])))
        ok("captions_kept", sorted((p.get("caption") or "") for p in rep.get("photos", [])) == ["north", "setback"])
        # STORED BYTES are GPS-free (the #235 pipeline strip, proven on disk)
        conn = db_layer.connect()
        paths = [r[0] for r in conn.execute(
            "SELECT p.file_path FROM walkthrough_photo p JOIN walkthrough_report wr ON wr.id=p.report_id "
            "WHERE wr.estimate_id=?", (a_id,)).fetchall()]
        conn.close()
        gps_free = all(len(_Im.open(p).getexif().get_ifd(0x8825)) == 0
                       and 34853 not in _Im.open(p).getexif() for p in paths)
        ok("stored_bytes_gps_free", bool(paths) and gps_free, f"{len(paths)} file(s) checked")
        # gated serves: estimator 200 inline; roles 403; unknown 404
        pid = rep["photos"][0]["id"]
        r = es.get(f"{BASE}/api/walkthroughs/photos/{pid}/file", timeout=10)
        ok("photo_serves_inline_200", r.status_code == 200
           and "inline" in (r.headers.get("Content-Disposition") or "").lower())
        r = es.get(f"{BASE}/api/walkthroughs/photos/{pid}/thumb", timeout=10)
        ok("thumb_serves_200", r.status_code == 200)
        st, body = _sc(es, "GET", f"/api/estimating/{a_id}/walkthrough-reports")
        ok("reports_render_payload", st == 200 and (body or {}).get("data", [{}])[0].get("photo_count") == 2)
        st, _ = _sc(es, "POST", f"/api/estimating/{a_id}/walkthrough-report",
                    data={"note": ""})
        ok("empty_report_400", st == 400)

        # ---------- (f) per-resource isolation + role matrix ----------
        PROBES = [("GET", f"/api/estimating/{a_id}/walkthroughs"),
                  ("POST", f"/api/estimating/{a_id}/walkthroughs"),
                  ("POST", f"/api/walkthroughs/visits/{v3}/done"),
                  ("GET", f"/api/estimating/{a_id}/walkthrough-reports"),
                  ("GET", f"/api/walkthroughs/photos/{pid}/file"),
                  ("GET", f"/api/walkthroughs/photos/{pid}/thumb"),
                  ("GET", "/api/company/schedule")]
        for role, sess in (("pm", pm), ("super", su), ("client", cl)):
            if not sess:
                continue
            for m, p in PROBES:
                stx, _ = _sc(sess, m, p, json={} if m == "POST" else None)
                ok(f"{role}_403 {m} {p.split('/api/')[1][:34]}", stx == 403)
        st, _ = _sc(es, "GET", "/api/walkthroughs/photos/999999/file")
        ok("unknown_photo_404", st == 404)
        st, _ = _sc(es, "GET", "/api/company/schedule")
        ok("estimator_schedule_403 (console-only)", st == 403)

        # ---------- (g) forbidden keys ----------
        found = []
        _forbidden_keys(SEEN, found)
        ok("no_path_keys_anywhere", not found, f"saw: {sorted(set(found))[:5]}")

        print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        if FAIL:
            print("FAILURES: " + ", ".join(FAIL))
        print("OVERALL:", "PASS" if not FAIL else "FAIL")
        return 0 if not FAIL else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
