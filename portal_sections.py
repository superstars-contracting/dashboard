"""#284 — the /api/portal/<code>/* section payloads: the portal shell's data, and the
first PRODUCTION consumers of the client_payload() registry.

FOUR sections tonight: progress, photos, documents, daily. Each handler:

  * is INDEPENDENTLY CURATED. A mirror suffix is never a passthrough of the internal
    endpoint — the handler reads the DB itself and every emitted field passes through
    client_registry.client_payload() against a REGISTERED dataset. An unregistered
    field does not leave the building (fail-closed at the serialiser).
  * hard-codes audience="client". Even an admin preview receives the CLIENT projection —
    the internal passthrough branch is unreachable from these routes by construction,
    and preview parity is a corollary rather than a promise.
  * re-derives EVERYTHING per request via require_portal_section(): the effective
    client (self, or the #270 admin preview target), their ONE bound project, the #284
    role x section MATRIX row, and the #269 grant. The <code> in the URL must equal the
    bound project — a client cannot address another project's payload by URL.
  * serves photo/document BYTES through the EXISTING id-gated Classic routes
    (/api/portal/photos/<id>/..., /api/portal/documents/<id>/file) — per-item
    visibility re-derived from the row on every fetch (#264). No new byte surface.

THE DAILY BREAKDOWN (operator-approved allowlist, decided for #284):
  date + work/no-work; weather; active drop/elevation labels; STRUCTURED activity
  categories (stage-template step names + started/completed enums); that-day
  cell status changes in client vocabulary (status_tone client labels); that-day
  client-shared photos. NEVER: worker identities, hours, rates, headcounts, SOV
  quantities, internal notes, or ANY free-text column — no_work_reason,
  no_work_note, scope_of_work, description, drop_stage_status.note, cell reason
  are not in any SELECT below (provenance, not vocabulary).

PII discipline (CLAUDE.md): ids/labels/dates/counts only. Dates are LOCAL. All SQL is
parameterized through the caller's db_layer connection — identical on SQLite and PG.
"""
from __future__ import annotations

import functools
import logging

from flask import g, jsonify, request

import client_grants
import client_registry as reg
import client_portal
import portal_matrix
import visibility
import dropplan_rollups as _rollups
from auth import _db


def _no_store(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ============= THE GATE — matrix + grant + project binding, per request =============

def require_portal_section(section: str):
    """403 unless: the request resolves to an effective CLIENT (self, or a validated
    admin/c_suite preview target — client_portal._resolve_portal_client), AND the URL's
    project_code equals that client's one bound project, AND `section` is inside the
    role's MATRIX row (#284), AND the client holds the #269 grant. Layered on top of the
    client/architect containment gates, which have already run for the session role."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(project_code, *args, **kwargs):
            conn = _db()
            try:
                target, is_preview, err = client_portal._resolve_portal_client(conn)
                if err:
                    return err
                role = target.get("role")          # 'client' by construction today
                if not portal_matrix.allowed(role, section):
                    logging.info(f"portal_sections: matrix deny role={role} "
                                 f"section={section} path={request.path}")
                    return jsonify({"error": "forbidden"}), 403
                code = client_portal.client_project_code(target["id"], conn)
                if not code or code != project_code:
                    logging.info(f"portal_sections: project-binding deny "
                                 f"target={target.get('id')} path={request.path}")
                    return jsonify({"error": "forbidden"}), 403
                if not client_grants.has_grant(conn, target["id"], code, section):
                    logging.info(f"portal_sections: grant deny section={section} "
                                 f"target={target.get('id')} preview={is_preview}")
                    return jsonify({"error": "forbidden"}), 403
            finally:
                conn.close()
            g.portal_client_id = target["id"]
            g.portal_is_preview = is_preview
            g.client_project_code = code
            return fn(*args, **kwargs)
        return wrapper
    return decorator


# ============= SECTION: progress =============

# WMO weather code -> the shared icon vocabulary (the internal widget's w-* symbol
# names). A structured map over an enum — no free text involved.
_WMO_ICON = {}
for _codes, _name in (((0, 1), "sun"), ((2,), "pcloud"), ((3, 45, 48), "cloud"),
                      (tuple(range(51, 68)) + tuple(range(80, 83)), "rain"),
                      (tuple(range(71, 78)) + (85, 86), "snow"),
                      (tuple(range(95, 100)), "storm")):
    for _c in _codes:
        _WMO_ICON[_c] = _name


def _drop_status(lifecycle, pct):
    """The internal Project Health three-bucket derivation, mirrored: structured
    inputs (lifecycle enum + derived pct) only."""
    if lifecycle == "not_started":
        return "not_started"
    if pct >= 100 or lifecycle in ("closed",):
        return "complete"
    return "active"


def _progress_boards(conn, code):
    """The client-safe Project Health boards: active-drop cards, drops-by-status
    counts, progress-by-elevation bars. Sources are drops (enum/label columns),
    drop_stage_status (via rollups) and stage_template_steps.name (structured
    template vocabulary). No note/description column is selected anywhere."""
    drops = conn.execute(
        "SELECT drop_id, sequence_no, elevation, lifecycle FROM drops "
        "WHERE project_code=? ORDER BY sequence_no", (code,)).fetchall()
    active, counts, by_elev = [], {"active": 0, "complete": 0, "not_started": 0}, {}
    for d in drops:
        p = _rollups.drop_progress(conn, d["drop_id"])
        pct = p.get("pct", 0.0) or 0.0
        status = _drop_status(d["lifecycle"], pct)
        counts[status] += 1
        if d["elevation"]:
            by_elev.setdefault(d["elevation"], []).append(pct)
        if status == "active":
            stage = _rollups.current_stage(conn, d["drop_id"])
            step = (f"Step {stage['step_no']} · {stage['name']}" if stage
                    else "All steps complete")
            active.append(reg.client_payload("health.active_drop", {
                "label": f"DP-{d['sequence_no']}",
                "elevation": d["elevation"],
                "pct": round(pct, 0),
                "step": step,
            }))
    status_counts = reg.client_payload("health.status_count", [
        {"status": "active", "label": "Active", "tone": "blue",
         "count": counts["active"]},
        {"status": "complete", "label": "Complete", "tone": "green",
         "count": counts["complete"]},
        {"status": "not_started", "label": "Not started", "tone": "neutral",
         "count": counts["not_started"]},
    ])
    elevation_progress = reg.client_payload("health.elevation_progress", [
        {"elevation": e, "pct": round(sum(v) / len(v), 0)}
        for e, v in sorted(by_elev.items())])
    return active, status_counts, elevation_progress


def _progress_weather():
    """Today's conditions + the 5-day strip, from the same Open-Meteo helper the
    internal widget uses (public data), every row through health.weather. On a
    provider failure the card is simply absent — never an error page."""
    try:
        from server import fetch_open_meteo_weather
        w = fetch_open_meteo_weather(40.8083, -73.9162)
    except Exception:
        return None, []
    now = reg.client_payload("health.weather", {
        "date": w.get("date"),
        "temp_f": w.get("temp_now"),
        "condition": w.get("condition_label"),
        "icon": _WMO_ICON.get(w.get("condition_code"), "cloud"),
        "precip_pct": w.get("precip_prob_today"),
        "wind_mph": w.get("wind_mph"),
    })
    days = reg.client_payload("health.weather", [{
        "date": f.get("date"),
        "temp_f": f.get("temp_max"),
        "condition": None,
        "icon": _WMO_ICON.get(f.get("code"), "cloud"),
        "precip_pct": f.get("precip_prob"),
        "wind_mph": None,
    } for f in (w.get("forecast") or [])])
    return now, days


@require_portal_section("progress")
def _sec_progress():
    """The client-safe Project Health mirror (#285): overall ring + generated summary
    (as before), plus active-drop cards, drops-by-status counts, progress-by-elevation
    bars, and the weather card. Every field through the registry; include_cost=False
    means no $ field exists to begin with."""
    code = g.client_project_code
    conn = _db()
    try:
        roll = _rollups.project_rollup(conn, code, include_cost=False)
        pct = roll.get("overall_progress_pct", 0.0) or 0.0
        label = client_portal._progress_label(pct)
        text = f"Your project is {label.lower()} — about {pct:.0f}% complete."
        last_activity = None
        photos_shared = None
        if client_grants.has_grant(conn, g.portal_client_id, code, "photos"):
            vis_ids = visibility.client_visible_photo_ids(conn, code)
            photos_shared = len(vis_ids)
            if vis_ids:
                row = conn.execute(
                    f"SELECT MAX(substr(taken_at,1,10)) FROM field_photos "
                    f"WHERE id IN ({','.join(['?'] * len(vis_ids))})", vis_ids).fetchone()
                last_activity = row[0] if row else None
                text += f" {photos_shared} photo{'s' if photos_shared != 1 else ''} shared with you."
        progress = reg.client_payload("health.progress",
                                      {"pct": round(pct, 0), "label": label})
        summary = {"text": text, "last_activity": last_activity}
        if photos_shared is not None:
            summary["photos_shared"] = photos_shared
        summary = reg.client_payload("portal.progress_summary", summary)
        active, status_counts, elevation_progress = _progress_boards(conn, code)
    finally:
        conn.close()
    weather_now, weather_days = _progress_weather()   # network call AFTER the db closes
    return _no_store(jsonify({"data": {
        "progress": progress, "summary": summary,
        "active_drops": active, "status_counts": status_counts,
        "elevation_progress": elevation_progress,
        "weather": weather_now, "weather_days": weather_days,
    }}))


# ============= SECTION: photos =============

@require_portal_section("photos")
def _sec_photos():
    """Item-shared photos ONLY (visibility.py is the source of truth for WHICH; the
    registry curates the SHAPE). #285 — the internal Field Photos mirror: each photo
    carries its drop label + elevation (structured joins, generated labels), the
    caption column is NOT SELECTED (operator decision: drop · elevation · date only),
    and a stat strip rides alongside. Byte URLs stay on the Classic id-gated routes."""
    code = g.client_project_code
    conn = _db()
    try:
        ids = visibility.client_visible_photo_ids(conn, code)
        if not ids:
            stats = reg.client_payload("portal.photos_stats", {
                "shared_count": 0, "drops_covered": 0, "latest_date": None})
            return _no_store(jsonify({"data": {"photos": [], "stats": stats}}))
        rows = conn.execute(
            f"SELECT fp.id, fp.taken_at, d.sequence_no, d.elevation "
            f"FROM field_photos fp LEFT JOIN drops d ON d.drop_id = fp.drop_id "
            f"WHERE fp.id IN ({','.join(['?'] * len(ids))}) "
            f"ORDER BY fp.taken_at DESC, fp.id DESC", ids).fetchall()
        photos = reg.client_payload("portal.photo", [{
            "id": r["id"],
            "drop_label": (f"DP-{r['sequence_no']}" if r["sequence_no"] is not None
                           else "Unassigned"),
            "elevation": r["elevation"],
            "taken_at": (r["taken_at"] or "")[:10] or None,   # date only, LOCAL
            "thumb_url": f"/api/portal/photos/{r['id']}/thumb",
            "file_url": f"/api/portal/photos/{r['id']}/file",
        } for r in rows])
        drops_covered = len({p["drop_label"] for p in photos
                             if p.get("drop_label") and p["drop_label"] != "Unassigned"})
        latest = max((p["taken_at"] for p in photos if p.get("taken_at")), default=None)
        stats = reg.client_payload("portal.photos_stats", {
            "shared_count": len(photos), "drops_covered": drops_covered,
            "latest_date": latest})
        return _no_store(jsonify({"data": {"photos": photos, "stats": stats}}))
    finally:
        conn.close()


# ============= SECTION: documents =============

@require_portal_section("documents")
def _sec_documents():
    """Item-shared documents ONLY — same engine, same posture as photos."""
    code = g.client_project_code
    conn = _db()
    try:
        ids = visibility.client_visible_document_ids(conn, code)
        if not ids:
            return _no_store(jsonify({"data": {"documents": []}}))
        rows = conn.execute(
            f"SELECT id, title, category, doc_type, effective_date FROM project_documents "
            f"WHERE id IN ({','.join(['?'] * len(ids))}) ORDER BY uploaded_at DESC, id DESC",
            ids).fetchall()
        docs = reg.client_payload("portal.document", [{
            "id": r["id"], "title": r["title"], "category": r["category"],
            "doc_type": r["doc_type"], "effective_date": r["effective_date"],
            "file_url": f"/api/portal/documents/{r['id']}/file",
        } for r in rows])
        return _no_store(jsonify({"data": {"documents": docs}}))
    finally:
        conn.close()


# ============= SECTION: daily — the client DCR breakdown =============

_DAY_LIMIT = 30


def _daily_days(conn, code):
    """Issued report days, newest first. no_work_reason / no_work_note are NOT selected."""
    return conn.execute(
        "SELECT report_date AS date, MAX(COALESCE(no_work,0)) AS no_work "
        "FROM report_index WHERE project_code=? AND status='issued' "
        "GROUP BY report_date ORDER BY report_date DESC LIMIT ?",
        (code, _DAY_LIMIT)).fetchall()


def _daily_weather(conn, code, dates):
    """{date: registered-weather} — temps + condition/wind strings the operator approved."""
    if not dates:
        return {}
    rows = conn.execute(
        f"SELECT date, am_temp_f, pm_temp_f, am_conditions, pm_conditions, wind "
        f"FROM weather_log WHERE project_code=? AND date IN ({','.join(['?'] * len(dates))})",
        [code, *dates]).fetchall()
    return {r["date"]: reg.client_payload("portal.daily_weather", {
        "am_temp_f": r["am_temp_f"], "pm_temp_f": r["pm_temp_f"],
        "am_conditions": r["am_conditions"], "pm_conditions": r["pm_conditions"],
        "wind": r["wind"],
    }) for r in rows}


def _daily_stage_activity(conn, code, dates):
    """{date: (drops, activities)} from drop_stage_status started_on/completed_on.
    STRUCTURED vocabulary only: the drop label (sequence + elevation) and the stage-
    template step NAME + a started/completed enum. ds.note is never selected."""
    if not dates:
        return {}
    ph = ",".join(["?"] * len(dates))
    rows = conn.execute(
        f"SELECT d.sequence_no, d.elevation, st.name AS category, "
        f"       ds.started_on, ds.completed_on "
        f"FROM drop_stage_status ds "
        f"JOIN drops d ON d.drop_id = ds.drop_id "
        f"JOIN stage_templates t ON t.project_code = d.project_code "
        f"JOIN stage_template_steps st ON st.template_id = t.template_id "
        f"                            AND st.step_no = ds.step_no "
        f"WHERE d.project_code=? AND (ds.started_on IN ({ph}) OR ds.completed_on IN ({ph}))",
        [code, *dates, *dates]).fetchall()
    out = {}
    for r in rows:
        # #285 — schedule-drop vocabulary is DP-{n} everywhere on the portal
        # (photos groups, progress cards, these chips). Drawing-cell status
        # changes keep their own surface's "Drop {idx}" naming.
        label = f"DP-{r['sequence_no']}"
        elev = r["elevation"]
        for col, verb in (("started_on", "started"), ("completed_on", "completed")):
            day = r[col]
            if day in set(dates):
                drops, acts = out.setdefault(day, ({}, []))
                drops.setdefault(label, {"label": label, "elevation": elev})
                acts.append({"category": r["category"], "status": verb})
    return out


def _daily_cell_changes(conn, code, dates):
    """{date: [registered change]} from the append-only elevation_cell_event log, in
    CLIENT vocabulary (status_tone client_label). reason / actor_uid never selected."""
    if not dates:
        return {}
    tones = {r["key"][len("elevation."):]: (r["client_label"] or r["label"])
             for r in conn.execute(
                 "SELECT key, label, client_label FROM status_tone "
                 "WHERE module='elevation' AND client_visible=1").fetchall()}
    ph = ",".join(["?"] * len(dates))
    rows = conn.execute(
        f"SELECT substr(ev.created_at,1,10) AS day, ed.idx AS drop_idx, "
        f"       c.level_name, ev.from_status, ev.to_status "
        f"FROM elevation_cell_event ev "
        f"JOIN elevation_cell c ON c.id = ev.cell_id "
        f"JOIN elevation_drop ed ON ed.id = c.drop_id "
        f"JOIN elevation e ON e.id = ed.elevation_id "
        f"WHERE e.project_code=? AND substr(ev.created_at,1,10) IN ({ph}) "
        f"ORDER BY ev.created_at", [code, *dates]).fetchall()
    out = {}
    for r in rows:
        frm, to = tones.get(r["from_status"]), tones.get(r["to_status"])
        if to is None:
            continue          # a non-client-visible status never ships, even renamed
        out.setdefault(r["day"], []).append(reg.client_payload("portal.daily_change", {
            "drop_label": f"Drop {r['drop_idx']}",
            "level": r["level_name"],
            "from_label": frm, "to_label": to,
        }))
    return out


def _daily_photos(conn, code, dates):
    """{date: [registered photo ref]} — that-day CLIENT-SHARED photos only. ids + byte
    URLs; caption deliberately absent here (free-text stays out of the daily payload)."""
    ids = visibility.client_visible_photo_ids(conn, code)
    if not ids:
        return {}
    rows = conn.execute(
        f"SELECT id, substr(taken_at,1,10) AS day FROM field_photos "
        f"WHERE id IN ({','.join(['?'] * len(ids))}) ORDER BY taken_at, id", ids).fetchall()
    want = set(dates)
    out = {}
    for r in rows:
        if r["day"] in want:
            out.setdefault(r["day"], []).append(reg.client_payload("portal.daily_photo", {
                "id": r["id"],
                "thumb_url": f"/api/portal/photos/{r['id']}/thumb",
                "file_url": f"/api/portal/photos/{r['id']}/file",
            }))
    return out


@require_portal_section("daily")
def _sec_daily():
    """The client daily timeline: one entry per ISSUED report day, each carrying ONLY
    the operator-approved breakdown. Every field goes through the registry; the day
    label is generated vocabulary, never a stored string."""
    code = g.client_project_code
    conn = _db()
    try:
        day_rows = _daily_days(conn, code)
        dates = [r["date"] for r in day_rows]
        weather = _daily_weather(conn, code, dates)
        stage = _daily_stage_activity(conn, code, dates)
        changes = _daily_cell_changes(conn, code, dates)
        photos = _daily_photos(conn, code, dates)
        days = []
        for r in day_rows:
            d = r["date"]
            no_work = bool(r["no_work"])
            day = reg.client_payload("portal.daily_day", {
                "date": d, "no_work": no_work,
                "label": "No work performed" if no_work
                         else "Crew on site — work performed",
            })
            drops_map, acts = stage.get(d, ({}, []))
            day["weather"] = weather.get(d)
            day["active_drops"] = reg.client_payload(
                "portal.daily_drop", list(drops_map.values()))
            day["activities"] = reg.client_payload("portal.daily_activity", acts)
            day["status_changes"] = changes.get(d, [])
            day["photos"] = photos.get(d, [])
            days.append(day)
        return _no_store(jsonify({"data": {"days": days}}))
    finally:
        conn.close()


def register(app) -> None:
    """Wire the four section payloads. Call AFTER client_portal.register (the client
    gate must already be routing /api/portal/* for the session role)."""
    app.add_url_rule("/api/portal/<project_code>/progress", "portal_sec_progress",
                     _sec_progress, methods=["GET"])
    app.add_url_rule("/api/portal/<project_code>/photos", "portal_sec_photos",
                     _sec_photos, methods=["GET"])
    app.add_url_rule("/api/portal/<project_code>/documents", "portal_sec_documents",
                     _sec_documents, methods=["GET"])
    app.add_url_rule("/api/portal/<project_code>/daily", "portal_sec_daily",
                     _sec_daily, methods=["GET"])
