"""#277 — Walkthrough scheduling + the iPad walkthrough report (blueprint Build C,
§2 steps 4-5). Visits live on the ESTIMATE (pre-project), drive the #276 stage
machine (single truth, no parallel state), and merge with #274 inspection visits
into the COMPANY SCHEDULE.

STAGE SYNC (via estimating._apply_stage — the machine primitive):
  * create_visit          -> received -> walkthrough_scheduled (when applicable;
                             a revisit on a later stage just adds the row)
  * mark_visit_done       -> walkthrough_scheduled -> walkthrough_done
  * cancel_visit          -> back to received IF no other scheduled visit remains
  * estimate.walkthrough_date is DERIVED: MIN(scheduled) else MAX(done) else NULL
    — synced here after every visit mutation, never independently editable.

REPORTS/PHOTOS: the #235 pipeline (field_photos.process_image) — HEIC-safe,
orientation baked in, GPS/EXIF STRIPPED from stored bytes, capture time kept
(taken_at + estimated flag). Files under data_room/walkthroughs/<estimate_code>/;
paths NEVER in JSON; photos served ONLY by gated by-id routes that RE-DERIVE
photo -> report -> estimate per request (per-resource isolation).

ACCESS: everything the estimator works is 'estimating' (estimator/admin/c_suite);
the merged company schedule is 'estimates' (admin/c_suite — console calendar).
pm/super 403 by section; clients contained by their gate. No amounts anywhere on
report surfaces (financials omitted, not zeroed).

Dates LOCAL. All SQL parameterized via db_layer — identical on both backends.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import jsonify, request, send_file

import crm
import estimates
import estimating
import notifications
from auth import _db, current_user, requires_section

SCRIPT_DIR = Path(__file__).resolve().parent
_WT_BASE = SCRIPT_DIR / "data_room" / "walkthroughs"

VISIT_STATUSES = ("scheduled", "done", "cancelled")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _uid():
    return (current_user() or {}).get("id")


def _valid_date(s):
    s = (s or "").strip()
    datetime.strptime(s, "%Y-%m-%d")
    return s


def _initials(name) -> str:
    parts = [p for p in (name or "").replace("@", " ").split() if p]
    return ("".join(p[0] for p in parts[:2]) or "?").upper()


# ===================== visits + stage sync (shared with the smoke) =====================

def sync_walkthrough_date(conn, est_id) -> None:
    """estimate.walkthrough_date = MIN(scheduled visit) else MAX(done) else NULL.
    The ONLY writer of walkthrough_date since #277 (derived, never hand-edited)."""
    r = conn.execute(
        "SELECT MIN(CASE WHEN status='scheduled' THEN visit_date END) AS nxt, "
        "       MAX(CASE WHEN status='done' THEN visit_date END) AS last_done "
        "FROM walkthrough_visit WHERE estimate_id=?", (est_id,)).fetchone()
    conn.execute("UPDATE estimate SET walkthrough_date=?, updated_at=? WHERE id=?",
                 (r["nxt"] or r["last_done"], _now(), est_id))
    conn.commit()


def create_visit(conn, est_id, *, visit_date, attendee_user_id, site_poc_contact_id=None,
                 poc_note=None, actor_user_id=None) -> dict:
    """Schedule a walkthrough. attendee_user_id NOT NULL — someone from the company
    MUST attend (400 without). Advances received -> walkthrough_scheduled when the
    machine is at received; a later-stage estimate just gains a revisit row."""
    est = estimates.get_estimate(conn, est_id)
    if not est:
        raise LookupError("estimate not found")
    if est["status"] != "scoping":
        # the machine contract (#276, guard-enshrined): estimating activity — visits
        # included — happens while status='scoping'. An intake lead starts estimating
        # first (one click), THEN schedules; no stage/visit divergence possible.
        raise ValueError("walkthroughs are scheduled once estimating has started (status='scoping')")
    vd = _valid_date(visit_date)
    if not attendee_user_id:
        raise ValueError("attendee_user_id is required — someone must attend the walkthrough")
    u = conn.execute("SELECT id FROM users WHERE id=? AND is_active=1",
                     (attendee_user_id,)).fetchone()
    if not u:
        raise ValueError("attendee user not found or inactive")
    if site_poc_contact_id is not None and not crm.get_contact(conn, site_poc_contact_id):
        raise ValueError("site_poc_contact_id does not exist")
    conn.execute(
        "INSERT INTO walkthrough_visit (estimate_id, visit_date, attendee_user_id, "
        "site_poc_contact_id, poc_note, status, created_by, created_at, updated_at) "
        "VALUES (?,?,?,?,?, 'scheduled', ?,?,?)",
        (est_id, vd, attendee_user_id, site_poc_contact_id,
         (poc_note or "").strip() or None, actor_user_id, _now(), _now()))
    conn.commit()
    vid = conn.execute("SELECT MAX(id) AS m FROM walkthrough_visit").fetchone()["m"]
    if est["status"] == "scoping" and (est.get("est_stage") or "received") == "received":
        estimating._apply_stage(conn, est, "walkthrough_scheduled",
                                actor_user_id=actor_user_id)
    else:
        crm.add_activity(conn, entity_type="organization", entity_id=est["client_org_id"],
                         activity_type="system", author_user_id=actor_user_id,
                         function_tag="sales",
                         summary=f"Estimate {est['code']}: walkthrough scheduled {vd}")
    sync_walkthrough_date(conn, est_id)
    if attendee_user_id != actor_user_id:
        notifications.notify_user(
            conn, kind="walkthrough", user_id=attendee_user_id,
            subject=f"[SSC] Walkthrough {vd} — {est['code']}",
            estimate_code=est["code"],
            extra_line=f"{est.get('building_address') or ''}".strip())
    r = conn.execute("SELECT * FROM walkthrough_visit WHERE id=?", (vid,)).fetchone()
    return dict(r)


def mark_visit_done(conn, visit_id, *, actor_user_id=None, sync_stage=True) -> dict:
    v = conn.execute("SELECT * FROM walkthrough_visit WHERE id=?", (visit_id,)).fetchone()
    if not v:
        raise LookupError("visit not found")
    v = dict(v)
    if v["status"] != "scheduled":
        raise ValueError(f"only a scheduled visit can be marked done (is {v['status']})")
    conn.execute("UPDATE walkthrough_visit SET status='done', updated_at=? WHERE id=?",
                 (_now(), visit_id))
    conn.commit()
    est = estimates.get_estimate(conn, v["estimate_id"])
    if (sync_stage and est and est["status"] == "scoping"
            and est.get("est_stage") == "walkthrough_scheduled"):
        estimating._apply_stage(conn, est, "walkthrough_done", actor_user_id=actor_user_id)
    sync_walkthrough_date(conn, v["estimate_id"])
    r = conn.execute("SELECT * FROM walkthrough_visit WHERE id=?", (visit_id,)).fetchone()
    return dict(r)


def mark_next_scheduled_done(conn, est_id, *, actor_user_id=None, sync_stage=False) -> None:
    """Best-effort visit/stage convergence when the stage button 'Mark walkthrough
    done' is clicked directly (#276 path): the earliest scheduled visit follows."""
    r = conn.execute(
        "SELECT id FROM walkthrough_visit WHERE estimate_id=? AND status='scheduled' "
        "ORDER BY visit_date LIMIT 1", (est_id,)).fetchone()
    if r:
        mark_visit_done(conn, r["id"], actor_user_id=actor_user_id, sync_stage=sync_stage)
    else:
        sync_walkthrough_date(conn, est_id)


def cancel_visit(conn, visit_id, *, actor_user_id=None) -> dict:
    """Cancel a scheduled visit (history kept). If NO other scheduled visit remains
    and the machine sits at walkthrough_scheduled, the stage reverts to received —
    server-decided, so the queue card honestly says 'schedule a walkthrough'."""
    v = conn.execute("SELECT * FROM walkthrough_visit WHERE id=?", (visit_id,)).fetchone()
    if not v:
        raise LookupError("visit not found")
    v = dict(v)
    if v["status"] != "scheduled":
        raise ValueError(f"only a scheduled visit can be cancelled (is {v['status']})")
    conn.execute("UPDATE walkthrough_visit SET status='cancelled', updated_at=? WHERE id=?",
                 (_now(), visit_id))
    conn.commit()
    others = conn.execute(
        "SELECT COUNT(*) AS n FROM walkthrough_visit WHERE estimate_id=? AND status='scheduled'",
        (v["estimate_id"],)).fetchone()["n"]
    est = estimates.get_estimate(conn, v["estimate_id"])
    if (others == 0 and est and est["status"] == "scoping"
            and est.get("est_stage") == "walkthrough_scheduled"):
        estimating._apply_stage(conn, est, "received", actor_user_id=actor_user_id)
    sync_walkthrough_date(conn, v["estimate_id"])
    r = conn.execute("SELECT * FROM walkthrough_visit WHERE id=?", (visit_id,)).fetchone()
    return dict(r)


def visit_public(conn, v) -> dict:
    v = dict(v)
    u = conn.execute("SELECT COALESCE(display_name, full_name, email) AS nm FROM users WHERE id=?",
                     (v["attendee_user_id"],)).fetchone()
    nm = u["nm"] if u else None    # sqlite3.Row has no .get — index it
    poc = None
    if v.get("site_poc_contact_id"):
        c = crm.get_contact(conn, v["site_poc_contact_id"])
        poc = (c or {}).get("full_name")
    return {"id": v["id"], "estimate_id": v["estimate_id"], "visit_date": v["visit_date"],
            "attendee_user_id": v["attendee_user_id"],
            "attendee_name": nm, "attendee_initials": _initials(nm),
            "site_poc": poc, "poc_note": v.get("poc_note"), "status": v["status"],
            "created_at": v["created_at"]}


# ===================== reports + photos (#235 pipeline reuse) =====================

def _wt_write(est_code, res):
    """Write display+thumb bytes under data_room/walkthroughs/<code>/<uuid>/ —
    the same containment pattern as field photos. Returns (file_path, thumb_path)."""
    base = _WT_BASE.resolve()
    pdir = _WT_BASE / est_code / uuid.uuid4().hex
    if not pdir.resolve().is_relative_to(base):
        raise ValueError("invalid path")
    pdir.mkdir(parents=True, exist_ok=True)
    fpath = pdir / ("full" + res["ext"])
    tpath = pdir / ("thumb" + res["ext"])
    fpath.write_bytes(res["display_bytes"])
    tpath.write_bytes(res["thumb_bytes"])
    return str(fpath), str(tpath)


def create_report(conn, est_id, *, note, files, captions=None, visit_id=None,
                  actor_user_id=None) -> dict:
    """One walkthrough report: N photos (each through field_photos.process_image —
    GPS stripped, capture time kept) + one notes field. Returns the public report."""
    import field_photos as fp
    est = estimates.get_estimate(conn, est_id)
    if not est:
        raise LookupError("estimate not found")
    if visit_id is not None:
        v = conn.execute("SELECT estimate_id FROM walkthrough_visit WHERE id=?",
                         (visit_id,)).fetchone()
        if not v or v["estimate_id"] != est_id:
            raise ValueError("visit_id does not belong to this estimate")
    note = (note or "").strip() or None
    files = [f for f in (files or []) if f and getattr(f, "filename", None)]
    if not note and not files:
        raise ValueError("a report needs at least a note or one photo")
    captions = captions or []
    now = _now()
    conn.execute(
        "INSERT INTO walkthrough_report (estimate_id, visit_id, note, created_by, created_at) "
        "VALUES (?,?,?,?,?)", (est_id, visit_id, note, actor_user_id, now))
    conn.commit()
    rid = conn.execute("SELECT MAX(id) AS m FROM walkthrough_report").fetchone()["m"]
    stored, skipped = [], []
    for i, fs in enumerate(files):
        name = Path(fs.filename or "photo").name
        try:
            res = fp.process_image(fs.read(), fs.filename,
                                   fallback_dt_iso=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except fp.SkipImage as se:
            skipped.append({"file": name, "reason": str(se)})
            continue
        fpath, tpath = _wt_write(est["code"], res)
        cap = (captions[i] if i < len(captions) else "") or None
        conn.execute(
            "INSERT INTO walkthrough_photo (report_id, file_path, thumb_path, file_name, "
            "file_size, mime, width, height, caption, taken_at, taken_at_estimated, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (rid, fpath, tpath, res["file_name"], len(res["display_bytes"]), res["mime"],
             res["width"], res["height"], (cap or "").strip() or None,
             res["taken_at"], 1 if res["taken_at_estimated"] else 0, now))
        stored.append(name)
    conn.commit()
    crm.add_activity(conn, entity_type="organization", entity_id=est["client_org_id"],
                     activity_type="system", author_user_id=actor_user_id, function_tag="sales",
                     summary=f"Estimate {est['code']}: walkthrough report filed "
                             f"({len(stored)} photo{'s' if len(stored) != 1 else ''})")
    return {**report_public(conn, rid), "skipped": skipped}


def report_public(conn, report_id) -> dict:
    r = conn.execute(
        "SELECT wr.*, COALESCE(u.display_name, u.full_name, u.email) AS by_name "
        "FROM walkthrough_report wr LEFT JOIN users u ON u.id = wr.created_by "
        "WHERE wr.id=?", (report_id,)).fetchone()
    if not r:
        return {}
    photos = [{"id": p["id"], "caption": p["caption"], "taken_at": p["taken_at"],
               "taken_at_estimated": bool(p["taken_at_estimated"]),
               "width": p["width"], "height": p["height"], "file_name": p["file_name"],
               "file_url": f"/api/walkthroughs/photos/{p['id']}/file",
               "thumb_url": f"/api/walkthroughs/photos/{p['id']}/thumb"}
              for p in conn.execute(
                  "SELECT * FROM walkthrough_photo WHERE report_id=? ORDER BY taken_at, id",
                  (report_id,)).fetchall()]
    return {"id": r["id"], "estimate_id": r["estimate_id"], "visit_id": r["visit_id"],
            "note": r["note"], "created_by_name": r["by_name"], "created_at": r["created_at"],
            "photos": photos, "photo_count": len(photos)}


def list_reports(conn, est_id) -> list:
    ids = [r["id"] for r in conn.execute(
        "SELECT id FROM walkthrough_report WHERE estimate_id=? ORDER BY created_at DESC, id DESC",
        (est_id,)).fetchall()]
    return [report_public(conn, i) for i in ids]


# ===================== the company schedule (merged calendar) =====================

def company_schedule(conn, month=None):
    """The console month grid: ira_visit (kind 'inspection') + walkthrough_visit
    (kind 'walkthrough') merged, + the next-14-days list (both kinds) + the #274
    waiting-on digest (unchanged source of truth in ira.py)."""
    import ira
    month = (month or "").strip() or date.today().isoformat()[:7]
    first = date.fromisoformat(month + "-01")
    last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    today = date.today()
    horizon = (today + timedelta(days=14)).isoformat()

    def _wt_rows(lo, hi, only_scheduled):
        sql = ("SELECT v.*, e.code AS est_code, e.building_address, o.name AS org_name, "
               "COALESCE(u.display_name, u.full_name, u.email) AS attendee_name "
               "FROM walkthrough_visit v JOIN estimate e ON e.id = v.estimate_id "
               "JOIN crm_organization o ON o.id = e.client_org_id "
               "LEFT JOIN users u ON u.id = v.attendee_user_id "
               "WHERE v.visit_date >= ? AND v.visit_date <= ? ")
        if only_scheduled:
            sql += "AND v.status='scheduled' "
        sql += "ORDER BY v.visit_date, v.id"
        return [dict(r) for r in conn.execute(sql, (lo, hi)).fetchall()]

    def _wt_event(v):
        return {"kind": "walkthrough", "id": v["id"], "date": v["visit_date"],
                "code": v["est_code"], "estimate_id": v["estimate_id"],
                "label": v.get("building_address") or v.get("org_name"),
                "attendee_initials": _initials(v.get("attendee_name")),
                "attendee_name": v.get("attendee_name"), "status": v["status"]}

    def _ira_event(v):
        return {"kind": "inspection", "id": v["id"], "date": v["visit_date"],
                "code": v["project_code"], "estimate_id": None,
                "label": v.get("building_address") or v.get("org_name") or v.get("label"),
                "attendee_initials": None, "attendee_name": None, "status": v["status"]}

    ira_month = [dict(r) for r in conn.execute(
        "SELECT v.*, e.building_address, o.name AS org_name FROM ira_visit v "
        "JOIN ira_job j ON j.project_code = v.project_code "
        "JOIN estimate e ON e.id = j.estimate_id "
        "JOIN crm_organization o ON o.id = e.client_org_id "
        "WHERE v.visit_date >= ? AND v.visit_date <= ? ORDER BY v.visit_date, v.id",
        (first.isoformat(), last.isoformat())).fetchall()]
    ira_up = [dict(r) for r in conn.execute(
        "SELECT v.*, e.building_address, o.name AS org_name FROM ira_visit v "
        "JOIN ira_job j ON j.project_code = v.project_code "
        "JOIN estimate e ON e.id = j.estimate_id "
        "JOIN crm_organization o ON o.id = e.client_org_id "
        "WHERE v.status='scheduled' AND v.visit_date >= ? AND v.visit_date <= ? "
        "ORDER BY v.visit_date, v.id", (today.isoformat(), horizon)).fetchall()]

    events = ([_wt_event(v) for v in _wt_rows(first.isoformat(), last.isoformat(), False)]
              + [_ira_event(v) for v in ira_month])
    events.sort(key=lambda e: (e["date"], e["kind"], e["id"]))
    upcoming = ([_wt_event(v) for v in _wt_rows(today.isoformat(), horizon, True)]
                + [_ira_event(v) for v in ira_up])
    upcoming.sort(key=lambda e: (e["date"], e["kind"], e["id"]))

    waiting = []
    for j in ira._jobs_with_estimate(conn):
        jp = ira.job_public(conn, dict(j), org_name=j["org_name"],
                            building_address=j["building_address"],
                            today_iso=today.isoformat())
        if jp["missing"] and jp["next_visit"]:
            waiting.append({"project_code": jp["project_code"], "org_name": jp["org_name"],
                            "next_visit_date": jp["next_visit"]["visit_date"],
                            "missing": jp["missing"]})
    waiting.sort(key=lambda w: w["next_visit_date"])
    return {"month": month, "first": first.isoformat(), "last": last.isoformat(),
            "events": events, "upcoming": upcoming, "waiting_on": waiting}


def upcoming_walkthroughs(conn, days=14) -> list:
    """The /estimating workspace list — the estimator's schedule without console
    access: scheduled walkthroughs in the next `days`, attendee + address."""
    today = date.today()
    rows = conn.execute(
        "SELECT v.*, e.code AS est_code, e.building_address, o.name AS org_name, "
        "COALESCE(u.display_name, u.full_name, u.email) AS attendee_name "
        "FROM walkthrough_visit v JOIN estimate e ON e.id = v.estimate_id "
        "JOIN crm_organization o ON o.id = e.client_org_id "
        "LEFT JOIN users u ON u.id = v.attendee_user_id "
        "WHERE v.status='scheduled' AND v.visit_date >= ? AND v.visit_date <= ? "
        "ORDER BY v.visit_date, v.id",
        (today.isoformat(), (today + timedelta(days=days)).isoformat())).fetchall()
    return [{"id": v["id"], "visit_date": v["visit_date"], "code": v["est_code"],
             "estimate_id": v["estimate_id"], "building_address": v["building_address"],
             "org_name": v["org_name"], "attendee_name": v["attendee_name"],
             "attendee_initials": _initials(v["attendee_name"])}
            for v in rows]


# ===================== endpoints =====================

@requires_section('estimating')
def _api_visits(est_id):
    conn = _db()
    try:
        if not estimates.get_estimate(conn, est_id):
            return jsonify({"error": "not found"}), 404
        vs = [visit_public(conn, dict(v)) for v in conn.execute(
            "SELECT * FROM walkthrough_visit WHERE estimate_id=? ORDER BY visit_date DESC, id DESC",
            (est_id,)).fetchall()]
        return jsonify({"data": vs})
    finally:
        conn.close()


@requires_section('estimating')
def _api_visit_create(est_id):
    d = request.get_json(silent=True) or {}
    conn = _db()
    try:
        v = create_visit(conn, est_id, visit_date=d.get("visit_date"),
                         attendee_user_id=d.get("attendee_user_id"),
                         site_poc_contact_id=d.get("site_poc_contact_id"),
                         poc_note=d.get("poc_note"), actor_user_id=_uid())
        return jsonify({"data": visit_public(conn, v)})
    except LookupError:
        return jsonify({"error": "not found"}), 404
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@requires_section('estimating')
def _api_visit_done(visit_id):
    conn = _db()
    try:
        v = mark_visit_done(conn, visit_id, actor_user_id=_uid())
        return jsonify({"data": visit_public(conn, v)})
    except LookupError:
        return jsonify({"error": "not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@requires_section('estimating')
def _api_visit_cancel(visit_id):
    conn = _db()
    try:
        v = cancel_visit(conn, visit_id, actor_user_id=_uid())
        return jsonify({"data": visit_public(conn, v)})
    except LookupError:
        return jsonify({"error": "not found"}), 404
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@requires_section('estimating')
def _api_attendees():
    """Assignable attendees for the schedule modal (real active internal staff who
    can hold the section: estimator + admin/c_suite)."""
    conn = _db()
    try:
        rows = [{"id": r["id"], "name": r["nm"]} for r in conn.execute(
            "SELECT id, COALESCE(display_name, full_name, email) AS nm FROM users "
            "WHERE role IN ('estimator','c_suite','admin') AND status='active' AND is_active=1 "
            "AND COALESCE(is_system,0)=0 ORDER BY LOWER(nm)").fetchall()]
        return jsonify({"data": rows})
    finally:
        conn.close()


@requires_section('estimating')
def _api_report_create(est_id):
    files = request.files.getlist("photos") or request.files.getlist("files")
    captions = request.form.getlist("captions")
    conn = _db()
    try:
        rep = create_report(conn, est_id, note=request.form.get("note"),
                            files=files, captions=captions,
                            visit_id=(int(request.form["visit_id"])
                                      if (request.form.get("visit_id") or "").strip() else None),
                            actor_user_id=_uid())
        return jsonify({"data": rep}), 201
    except LookupError:
        return jsonify({"error": "not found"}), 404
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@requires_section('estimating')
def _api_reports(est_id):
    conn = _db()
    try:
        if not estimates.get_estimate(conn, est_id):
            return jsonify({"error": "not found"}), 404
        return jsonify({"data": list_reports(conn, est_id)})
    finally:
        conn.close()


def _serve_photo(photo_id, col):
    """Per-resource isolation: RE-DERIVE photo -> report -> estimate on every fetch;
    a photo id that doesn't resolve through a real estimate is a 404, whatever the
    caller's role. Inline, no-store, path-contained under data_room/walkthroughs/."""
    conn = _db()
    try:
        row = conn.execute(
            "SELECT p.file_path, p.thumb_path, p.mime, p.file_name, wr.estimate_id "
            "FROM walkthrough_photo p JOIN walkthrough_report wr ON wr.id = p.report_id "
            "WHERE p.id=?", (photo_id,)).fetchone()
        if not row or not estimates.get_estimate(conn, row["estimate_id"]):
            return jsonify({"error": "not found"}), 404
        p = Path(row[col])
        if not (p.resolve().is_relative_to(_WT_BASE.resolve()) and p.exists()):
            return jsonify({"error": "file missing"}), 404
        resp = send_file(str(p), mimetype=row["mime"] or "image/jpeg",
                         as_attachment=False, download_name=row["file_name"] or f"photo-{photo_id}")
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        return resp
    finally:
        conn.close()


@requires_section('estimating')
def _api_photo_file(photo_id):
    return _serve_photo(photo_id, "file_path")


@requires_section('estimating')
def _api_photo_thumb(photo_id):
    return _serve_photo(photo_id, "thumb_path")


@requires_section('estimates')
def _api_company_schedule():
    conn = _db()
    try:
        month = (request.args.get("month") or "").strip() or None
        try:
            payload = company_schedule(conn, month)
        except ValueError:
            return jsonify({"error": "month must be YYYY-MM"}), 400
        return jsonify({"data": payload})
    finally:
        conn.close()


def register(app) -> None:
    """Wire the walkthrough surfaces. Estimator-reachable = 'estimating'; the merged
    company schedule = 'estimates' (console). Call after the auth gates."""
    app.add_url_rule("/api/estimating/<int:est_id>/walkthroughs", "wt_visits", _api_visits, methods=["GET"])
    app.add_url_rule("/api/estimating/<int:est_id>/walkthroughs", "wt_visit_create", _api_visit_create, methods=["POST"])
    app.add_url_rule("/api/walkthroughs/visits/<int:visit_id>/done", "wt_visit_done", _api_visit_done, methods=["POST"])
    app.add_url_rule("/api/walkthroughs/visits/<int:visit_id>/cancel", "wt_visit_cancel", _api_visit_cancel, methods=["POST"])
    app.add_url_rule("/api/estimating/attendees", "wt_attendees", _api_attendees, methods=["GET"])
    app.add_url_rule("/api/estimating/<int:est_id>/walkthrough-report", "wt_report_create", _api_report_create, methods=["POST"])
    app.add_url_rule("/api/estimating/<int:est_id>/walkthrough-reports", "wt_reports", _api_reports, methods=["GET"])
    app.add_url_rule("/api/walkthroughs/photos/<int:photo_id>/file", "wt_photo_file", _api_photo_file, methods=["GET"])
    app.add_url_rule("/api/walkthroughs/photos/<int:photo_id>/thumb", "wt_photo_thumb", _api_photo_thumb, methods=["GET"])
    app.add_url_rule("/api/company/schedule", "wt_company_schedule", _api_company_schedule, methods=["GET"])
