"""#294 — field photo reassignment history + edit tracking + admin alerts.

THE POSTURE (operator-approved): correcting a mislabeled photo is SELF-SERVICE
for anyone who can edit field photos — a ~10-second act, or people stop
correcting and the photo record rots. Oversight comes from VISIBILITY, not
gatekeeping: every transition is amendment-not-erasure (a history row, never a
silent overwrite), and the aggregate edit-rate feeds the operator as feedback
about the SOFTWARE, not just the person.

THE SHAPE INSIGHT (why timing rides every row): corrections within MINUTES of
upload mean the upload UI makes drop-selection too easy to get wrong;
corrections DAYS later mean field labeling habits; one person accounting for
nearly all of them means training. The alert carries those buckets, never a
bare count.

WHAT COUNTS AS A CORRECTION: a transition whose from_drop is NOT NULL.
Assigning from the Unassigned sort tray (NULL -> drop) is the INTENDED
workflow — it is logged for the paper trail but excluded from the
struggling-with-the-software analytics, or the sort tray itself would read as
a mistake factory.

DCR HONESTY: a correction whose photo's taken-at day already has an ISSUED DCR
is allowed (operator-confirmed) but flags that report_index row
photo_amended=1, writes an audit_log row, and marks the history row — the
paper trail stays honest without blocking the fix.

PII: server logs and alert payloads carry uid / W-#### only — never names.
The pattern view (admin/c_suite-only) resolves display names the same way
every other console admin surface does; nothing here is comp data.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from flask import jsonify, request

import db_layer
from auth import current_user, requires_role

# The self-service editor set — server.py's field-photo routes alias this, so
# the two can never drift.
FP_EDIT_ROLES = ("admin", "c_suite", "pm", "super")
ADMIN_ROLES = ("admin", "c_suite")

THRESHOLD_KEY = "fp_reassign_alert_threshold"
THRESHOLD_DEFAULT = 5

# Timing buckets (seconds since upload). <=15 min reads as "caught it
# immediately — the UI let the wrong drop through"; > 48 h reads as "the
# labeling habit surfaced later"; between is ordinary workflow lag.
BUCKET_MINUTES = 15 * 60
BUCKET_HOURS = 48 * 3600

_TIME_FMTS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M")


def _db():
    return db_layer.connect()


def _now_dt():
    return datetime.now()


def _now():
    return _now_dt().strftime("%Y-%m-%d %H:%M:%S")   # LOCAL, never UTC


def _parse_dt(s):
    for fmt in _TIME_FMTS:
        try:
            return datetime.strptime(str(s)[:19], fmt)
        except (ValueError, TypeError):
            continue
    return None


def bucket_of(seconds) -> str | None:
    """PURE: seconds-since-upload -> the shape bucket."""
    if seconds is None:
        return None
    if seconds <= BUCKET_MINUTES:
        return "minutes"
    if seconds <= BUCKET_HOURS:
        return "hours"
    return "days"


BUCKET_READINGS = {
    "minutes": ("corrected within minutes of upload — the upload UI may make "
                "drop selection too easy to get wrong"),
    "hours": "corrected within the working day or two — ordinary workflow lag",
    "days": "corrected days after upload — field labeling habits worth a look",
}


def get_threshold(conn) -> int:
    row = conn.execute("SELECT value FROM app_settings WHERE key=?",
                       (THRESHOLD_KEY,)).fetchone()
    try:
        n = int(str(row["value"]).strip()) if row else THRESHOLD_DEFAULT
        return n if n > 0 else THRESHOLD_DEFAULT
    except (TypeError, ValueError):
        return THRESHOLD_DEFAULT


# ============================================================================
# RECORDING — called inside the assign endpoint's transaction
# ============================================================================

def record_reassignments(conn, actor_uid, photo_rows, new_drop_id, reason=None):
    """Write history rows for every photo whose drop actually CHANGES, detect
    whole-batch corrections, and flag issued DCRs whose day is amended.

    photo_rows: field_photos rows (id, project_code, drop_id, uploaded_at,
    uploaded_by_uid, taken_at) BEFORE the caller's UPDATE. Caller owns the
    transaction — everything here rides the same commit as the move itself, so
    the trail can never diverge from the assignment.

    Returns {changed, corrections, whole_batch_batches, dcr_amended:[{...}]}.
    """
    now = _now()
    now_dt = _now_dt()
    changed = [r for r in photo_rows if (r["drop_id"] or None) != (new_drop_id or None)]
    corrections = [r for r in changed if r["drop_id"]]

    # whole-batch detection: a correction set that covers the ENTIRE upload
    # group (same uploader, same upload stamp — one POST) of size > 1.
    by_batch = {}
    for r in corrections:
        key = f"{r['uploaded_by_uid'] or 0}|{r['uploaded_at'] or ''}"
        by_batch.setdefault(key, []).append(r)
    whole_batches = set()
    for key, rows in by_batch.items():
        uid, up_at = rows[0]["uploaded_by_uid"], rows[0]["uploaded_at"]
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM field_photos WHERE project_code=? AND "
            "uploaded_at=? AND (uploaded_by_uid=? OR (uploaded_by_uid IS NULL AND ? IS NULL))",
            (rows[0]["project_code"], up_at, uid, uid)).fetchone()["n"]
        if total > 1 and len(rows) == total:
            whole_batches.add(key)

    # issued-DCR days being amended (corrections only)
    dcr_amended = []
    amended_days = set()
    days = sorted({str(r["taken_at"])[:10] for r in corrections if r["taken_at"]})
    if days:
        marks = ",".join("?" for _ in days)
        code = corrections[0]["project_code"]
        # UPPER(): live rows carry report_type='DCR'; test fixtures have used
        # 'dcr'. A case-exact match here silently never flags a real report —
        # caught in the #294 browser pass, kept case-insensitive forever.
        issued = conn.execute(
            f"SELECT id, report_id, report_date, dcr_sequence FROM report_index "
            f"WHERE project_code=? AND UPPER(report_type)='DCR' AND status='issued' "
            f"AND dcr_sequence IS NOT NULL AND report_date IN ({marks})",
            (code, *days)).fetchall()
        # actor role from the DB, not the request context — this function must
        # stay callable transaction-side with no Flask context (tests, CLI).
        arow = conn.execute("SELECT role FROM users WHERE id=?",
                            (actor_uid,)).fetchone() if actor_uid else None
        actor_role = arow["role"] if arow else None
        for d in issued:
            amended_days.add(d["report_date"])
            n_photos = sum(1 for r in corrections
                           if str(r["taken_at"])[:10] == d["report_date"])
            conn.execute(
                "UPDATE report_index SET photo_amended=1, "
                "photo_amended_at=COALESCE(photo_amended_at, ?) WHERE id=?",
                (now, d["id"]))
            conn.execute(
                "INSERT INTO audit_log (action, actor_user_id, actor_role, target_type, "
                "target_id, before_json, after_json, note, created_at) "
                "VALUES ('fp_reassign_after_issue', ?,?,?,?,?,?,?,?)",
                (actor_uid, actor_role, "report_index", str(d["id"]),
                 json.dumps({"photo_ids": [r["id"] for r in corrections
                                           if str(r["taken_at"])[:10] == d["report_date"]],
                             "from_drops": sorted({r["drop_id"] for r in corrections
                                                   if str(r["taken_at"])[:10] == d["report_date"]})}),
                 json.dumps({"to_drop": new_drop_id}),
                 f"{n_photos} photo(s) drop-reassigned after issue on {d['report_date']}",
                 now))
            dcr_amended.append({"report_index_id": d["id"], "report_date": d["report_date"],
                                "dcr_sequence": d["dcr_sequence"], "photos": n_photos})

    for r in changed:
        up_dt = _parse_dt(r["uploaded_at"])
        lag = int((now_dt - up_dt).total_seconds()) if up_dt else None
        if lag is not None and lag < 0:
            lag = 0
        key = f"{r['uploaded_by_uid'] or 0}|{r['uploaded_at'] or ''}"
        is_corr = bool(r["drop_id"])
        conn.execute(
            "INSERT INTO field_photo_reassign (photo_id, project_code, from_drop_id, "
            "to_drop_id, actor_uid, reason, batch_key, seconds_since_upload, whole_batch, "
            "dcr_amended, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (r["id"], r["project_code"], r["drop_id"] or None, new_drop_id or None,
             actor_uid, (reason or None), key, lag,
             1 if (is_corr and key in whole_batches) else 0,
             1 if (is_corr and r["taken_at"] and str(r["taken_at"])[:10] in amended_days) else 0,
             now))

    if changed:
        # uid + counts only — never names (CLAUDE.md PII rule for logs)
        logging.info(
            f"fp-reassign: uid={actor_uid} moved={len(changed)} corrections={len(corrections)} "
            f"whole_batches={len(whole_batches)} dcr_amended={len(dcr_amended)} "
            f"to={new_drop_id or 'unassigned'}")
    return {"changed": len(changed), "corrections": len(corrections),
            "whole_batch_batches": len(whole_batches), "dcr_amended": dcr_amended}


def reassign_states(conn, photo_ids):
    """{photo_id: correction_count} for one page of the gallery — one query,
    the visibility.photo_states shape. Corrections only: a tray assignment
    must not paint the 'reassigned' marker."""
    ids = [int(i) for i in photo_ids if i is not None]
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = conn.execute(
        f"SELECT photo_id, COUNT(*) AS n FROM field_photo_reassign "
        f"WHERE photo_id IN ({marks}) AND from_drop_id IS NOT NULL GROUP BY photo_id",
        tuple(ids)).fetchall()
    return {r["photo_id"]: r["n"] for r in rows}


# ============================================================================
# READS — history, patterns, alerts
# ============================================================================

def _drop_labels(conn, project_code):
    out = {}
    for r in conn.execute("SELECT drop_id, sequence_no, elevation FROM drops "
                          "WHERE project_code=?", (project_code,)):
        out[r["drop_id"]] = f"DP-{r['sequence_no']} · {r['elevation'] or '—'}"
    return out


def _actor_display(conn, uids):
    """{uid: {display, worker_id}} — display name for the internal surface,
    W-#### where linked (what alert TEXT uses; alert text never carries names)."""
    uids = [u for u in set(uids) if u]
    if not uids:
        return {}
    marks = ",".join("?" for _ in uids)
    rows = conn.execute(
        f"SELECT u.id, u.display_name, u.full_name, e.worker_id "
        f"FROM users u LEFT JOIN employees e ON e.employee_id = u.employee_id_link "
        f"WHERE u.id IN ({marks})", tuple(uids)).fetchall()
    return {r["id"]: {"display": r["display_name"] or r["full_name"] or f"uid {r['id']}",
                      "worker_id": r["worker_id"]}
            for r in rows}


@requires_role(*FP_EDIT_ROLES)
def _api_photo_history(photo_id):
    """GET /api/field-photos/<id>/history — the amendment trail for one photo,
    oldest first. Internal editors only (same set that can move photos)."""
    conn = _db()
    try:
        p = conn.execute("SELECT id, project_code FROM field_photos WHERE id=?",
                         (photo_id,)).fetchone()
        if p is None:
            return jsonify({"error": "not found"}), 404
        rows = conn.execute(
            "SELECT from_drop_id, to_drop_id, actor_uid, reason, seconds_since_upload, "
            "whole_batch, dcr_amended, created_at FROM field_photo_reassign "
            "WHERE photo_id=? ORDER BY id", (photo_id,)).fetchall()
        labels = _drop_labels(conn, p["project_code"])
        actors = _actor_display(conn, [r["actor_uid"] for r in rows])
        out = []
        for r in rows:
            a = actors.get(r["actor_uid"], {})
            out.append({
                "from_drop_id": r["from_drop_id"],
                "from_label": labels.get(r["from_drop_id"]) if r["from_drop_id"] else None,
                "to_drop_id": r["to_drop_id"],
                "to_label": labels.get(r["to_drop_id"]) if r["to_drop_id"] else None,
                "actor": a.get("display") or (f"uid {r['actor_uid']}" if r["actor_uid"] else "—"),
                "reason": r["reason"],
                "at": r["created_at"],
                "seconds_since_upload": r["seconds_since_upload"],
                "bucket": bucket_of(r["seconds_since_upload"]),
                "whole_batch": bool(r["whole_batch"]),
                "dcr_amended": bool(r["dcr_amended"]),
                "correction": bool(r["from_drop_id"]),
            })
        return jsonify({"data": out})
    finally:
        conn.close()


def _pattern_rows(conn, since_iso):
    """Per-user correction aggregates since a date. Corrections only."""
    rows = conn.execute(
        "SELECT actor_uid, COUNT(*) AS n, "
        "SUM(CASE WHEN seconds_since_upload IS NOT NULL AND seconds_since_upload <= ? "
        "    THEN 1 ELSE 0 END) AS n_minutes, "
        "SUM(CASE WHEN seconds_since_upload > ? AND seconds_since_upload <= ? "
        "    THEN 1 ELSE 0 END) AS n_hours, "
        "SUM(CASE WHEN seconds_since_upload > ? THEN 1 ELSE 0 END) AS n_days, "
        "SUM(whole_batch) AS n_whole_batch, "
        "SUM(dcr_amended) AS n_dcr_amended, "
        "MIN(created_at) AS first_at, MAX(created_at) AS last_at "
        "FROM field_photo_reassign "
        "WHERE from_drop_id IS NOT NULL AND created_at >= ? "
        "GROUP BY actor_uid ORDER BY n DESC",
        (BUCKET_MINUTES, BUCKET_MINUTES, BUCKET_HOURS, BUCKET_HOURS, since_iso)).fetchall()
    return rows


@requires_role(*ADMIN_ROLES)
def _api_edit_patterns():
    """GET /api/admin/photo-edit-patterns?days=30 — the per-user pattern view:
    who corrects, how often, HOW SOON after upload (the shape), whole-batch
    and after-issue counts. admin/c_suite only."""
    try:
        days = max(1, min(int(request.args.get("days", 30)), 365))
    except (TypeError, ValueError):
        days = 30
    since = (_now_dt() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = _db()
    try:
        rows = _pattern_rows(conn, since)
        actors = _actor_display(conn, [r["actor_uid"] for r in rows])
        total = sum(r["n"] for r in rows)
        out = []
        for r in rows:
            a = actors.get(r["actor_uid"], {})
            out.append({
                "actor_uid": r["actor_uid"],
                "actor": a.get("display") or (f"uid {r['actor_uid']}" if r["actor_uid"] else "—"),
                "worker_id": a.get("worker_id"),
                "corrections": r["n"],
                "share": round(r["n"] / total, 2) if total else 0,
                "buckets": {"minutes": r["n_minutes"] or 0, "hours": r["n_hours"] or 0,
                            "days": r["n_days"] or 0},
                "whole_batch": r["n_whole_batch"] or 0,
                "dcr_amended": r["n_dcr_amended"] or 0,
                "first_at": r["first_at"], "last_at": r["last_at"],
            })
        return jsonify({"data": {
            "days": days, "total_corrections": total, "users": out,
            "threshold": get_threshold(conn),
            "buckets_legend": BUCKET_READINGS,
        }})
    finally:
        conn.close()


def build_alerts(conn):
    """The console-banner payload: alerts past the settable threshold over a
    ROLLING 7 DAYS, plus any whole-batch correction in the window. Each alert
    carries the dominant SHAPE bucket reading, never a bare count. uid/W-####
    only — the banner is admin/c_suite but the text stays name-free."""
    threshold = get_threshold(conn)
    since = (_now_dt() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    rows = _pattern_rows(conn, since)
    total = sum(r["n"] for r in rows)
    actors = _actor_display(conn, [r["actor_uid"] for r in rows])
    alerts = []
    for r in rows:
        if r["n"] <= threshold:
            continue
        buckets = {"minutes": r["n_minutes"] or 0, "hours": r["n_hours"] or 0,
                   "days": r["n_days"] or 0}
        dom = max(buckets, key=lambda k: buckets[k])
        a = actors.get(r["actor_uid"], {})
        who = a.get("worker_id") or f"uid {r['actor_uid']}"
        share = (r["n"] / total) if total else 0
        reading = BUCKET_READINGS[dom]
        if share >= 0.8 and len(rows) > 1:
            reading += "; one person accounts for nearly all of them — training"
        alerts.append({
            "kind": "user_over_threshold",
            "actor_uid": r["actor_uid"], "who": who,
            "count": r["n"], "threshold": threshold,
            "buckets": buckets, "dominant_bucket": dom,
            "share": round(share, 2),
            "reading": reading,
        })
    wb = conn.execute(
        "SELECT actor_uid, batch_key, COUNT(*) AS n, MAX(created_at) AS at, "
        "MAX(seconds_since_upload) AS lag FROM field_photo_reassign "
        "WHERE whole_batch=1 AND from_drop_id IS NOT NULL AND created_at >= ? "
        "GROUP BY actor_uid, batch_key ORDER BY at DESC LIMIT 10", (since,)).fetchall()
    wb_actors = _actor_display(conn, [r["actor_uid"] for r in wb])
    for r in wb:
        a = wb_actors.get(r["actor_uid"], {})
        who = a.get("worker_id") or f"uid {r['actor_uid']}"
        dom = bucket_of(r["lag"]) or "hours"
        alerts.append({
            "kind": "whole_batch",
            "actor_uid": r["actor_uid"], "who": who,
            "count": r["n"], "at": r["at"],
            "dominant_bucket": dom,
            "reading": (f"an entire upload of {r['n']} photos was re-dropped — "
                        + BUCKET_READINGS[dom]),
        })
    return {"alerts": alerts, "threshold": threshold, "window_days": 7,
            "total_corrections_7d": total}


@requires_role(*ADMIN_ROLES)
def _api_edit_alerts():
    """GET /api/admin/photo-edit-alerts — the console banner feed."""
    conn = _db()
    try:
        return jsonify({"data": build_alerts(conn)})
    finally:
        conn.close()


@requires_role(*ADMIN_ROLES)
def _api_set_threshold():
    """POST /api/admin/photo-edit-alerts/threshold {threshold} — settable,
    never hardcoded. Positive integers only."""
    body = request.get_json(silent=True) or {}
    try:
        n = int(body.get("threshold"))
    except (TypeError, ValueError):
        return jsonify({"error": "threshold must be a positive integer"}), 400
    if not (1 <= n <= 1000):
        return jsonify({"error": "threshold must be between 1 and 1000"}), 400
    conn = _db()
    try:
        now = _now()
        cur = conn.execute("UPDATE app_settings SET value=?, updated_at=? WHERE key=?",
                           (str(n), now, THRESHOLD_KEY))
        if cur.rowcount == 0:
            conn.execute("INSERT INTO app_settings (key, value, updated_at) VALUES (?,?,?)",
                         (THRESHOLD_KEY, str(n), now))
        conn.commit()
        uid = (current_user() or {}).get("id")
        logging.info(f"fp-reassign: threshold set to {n} by uid={uid}")
        return jsonify({"data": {"threshold": n}})
    finally:
        conn.close()


def register(app) -> None:
    """MUST follow apply_auth_gate (requires_role reads the session user)."""
    app.add_url_rule("/api/field-photos/<int:photo_id>/history", "fp_history",
                     _api_photo_history, methods=["GET"])
    app.add_url_rule("/api/admin/photo-edit-patterns", "fp_edit_patterns",
                     _api_edit_patterns, methods=["GET"])
    app.add_url_rule("/api/admin/photo-edit-alerts", "fp_edit_alerts",
                     _api_edit_alerts, methods=["GET"])
    app.add_url_rule("/api/admin/photo-edit-alerts/threshold", "fp_edit_threshold",
                     _api_set_threshold, methods=["POST"])
