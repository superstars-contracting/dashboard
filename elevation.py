"""#280 — North Elevation drop plan: endpoints, audiences, and the external payload.

SECURITY MODEL — this ships to outside parties, so read this before editing anything.

TWO AUDIENCES, NOT THREE. Per the operator's correction to the earlier mockup:
  * INTERNAL  admin / c_suite / pm / super / estimator
      Everything, plus paint mode (the only roles that may change a status).
  * EXTERNAL  architect / client — ONE view, IDENTICAL for both.
      Same drawing, same DROP n labels, same grids, same dimension strings, same
      statuses INCLUDING rework (a field condition, not an internal metric), and the
      same `reason` text. They differ only in WRITE rights, never in what they see:
      architect may comment / raise RFIs / request meetings; client is read-only.

WHAT NEVER LEAVES THE BUILDING (asserted in tests/smoke_elevation_280.py):
  * elevation_cell.internal_note — never selected into an external payload, at all.
  * SLA / performance metrics, estimate stages, cost, rates, margin — none of these
    exist in this module's queries, by construction.

THE TWO-FIELD REASON SPLIT IS THIS BUILD'S SECURITY MECHANISM. The phase-2 client
registry + client_payload() serialiser do not exist yet, so "external" and "internal"
are separate COLUMNS rather than a filtering rule applied to one column:
    reason         EXTERNAL by construction — shown to architect and client
    internal_note  INTERNAL by construction — excluded by not being selected
The operating rule for whoever is typing: the reason is what you would say to the
architect's face. Anything else goes in the internal note.

DEBT, RECORDED DELIBERATELY (#280 -> phase 2): every external endpoint here builds its
payload from a HAND-CURATED NARROW SELECT naming each column. No SELECT *, no model
dump. When phase 2 lands the client-field registry and client_payload(), these
endpoints get routed through it and the hand-curation is deleted. Until then the narrow
SELECT is the guarantee, and the smoke asserts it holds.

PROJECT SCOPING: an architect is scoped to ASSIGNED PROJECTS ONLY, reusing the existing
#263 pm_project_assignment grant — never a parallel mechanism, and never "all projects".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from flask import Response, g, jsonify, request, send_file

import access
import db_layer
import pm_scoping
from auth import current_user

SCRIPT_DIR = Path(__file__).resolve().parent
# THE DRAWING MARKUP PAGE. Named and routed separately from the existing /dropplan
# (#201/#256), which is the per-drop LIFECYCLE schedule and stays exactly as it is.
# This page is the interactive elevation with per-drop, per-floor work status.
MARKUP_PAGE = SCRIPT_DIR / "templates" / "v2" / "drawing-markup.html"

# ---- audiences -------------------------------------------------------------
INTERNAL_ROLES = frozenset({"admin", "c_suite", "pm", "super", "estimator"})
EXTERNAL_ROLES = frozenset({"architect", "client"})
# Roles that may CHANGE a drop status. Deliberately narrower than "internal can see":
# painting the elevation is an SSC act.
PAINT_ROLES = INTERNAL_ROLES
# Roles that may write collaboration objects (comments, RFIs, meeting requests).
# The client is READ-ONLY by design and is absent here.
COLLAB_WRITE_ROLES = INTERNAL_ROLES | {"architect"}

STATUS_KEYS = ("not_started", "in_progress", "on_hold", "rework", "complete")
REASON_REQUIRED = frozenset({"on_hold", "rework"})
MAX_REASON = 500
MAX_COMMENT = 2000


def _db():
    return db_layer.connect()


def _now():
    return datetime.now().isoformat(timespec="seconds")   # LOCAL, never UTC


def _err(msg, code):
    return jsonify({"error": msg}), code


# ============================================================================
# ACCESS — one place. Every endpoint below calls _require_project().
# ============================================================================

def _role():
    return (current_user() or {}).get("role")


def _uid():
    return (current_user() or {}).get("id")


def is_internal(role=None) -> bool:
    return (role or _role()) in INTERNAL_ROLES


def audience(role=None) -> str:
    """'internal' or 'external'. Anything unrecognised is EXTERNAL — default-deny:
    a role added later is treated as an outsider until someone says otherwise."""
    return "internal" if is_internal(role) else "external"


def accessible_codes(conn, user) -> set:
    """The project codes this user may open. Default-deny: an unknown role gets none.

    admin / c_suite      every project (the company axis, #263)
    pm/super/estimator   assigned projects (#263 pm_project_assignment)
    architect            ASSIGNED PROJECTS ONLY — never all. An architect on
                         890 E 135th must not see any other job.
    client               the single project their portal is bound to (#264/#269)
    """
    role = (user or {}).get("role")
    uid = (user or {}).get("id")
    if role in access.COMPANY_ROLES:
        return {r[0] for r in conn.execute("SELECT project_code FROM projects").fetchall()}
    if role in ("pm", "super", "estimator", "architect"):
        return pm_scoping.assigned_codes(uid, conn)
    if role == "client":
        import client_portal
        code = client_portal.client_project_code(uid, conn)
        return {code} if code else set()
    return set()


def _require_project(conn, code):
    """None when allowed, else a 403 response. Server-side, every time, no exceptions."""
    user = current_user()
    if not user or not code:
        return _err("forbidden", 403)
    if code not in accessible_codes(conn, user):
        logging.info(f"elevation: scope block role={user.get('role')} "
                     f"uid={user.get('id')} code={code}")
        return _err("forbidden", 403)
    return None


# ============================================================================
# READ — GET /api/elevation/<id>
# ============================================================================

def _drop_rows(conn, elev_id):
    """NARROW SELECT — named columns only. internal_note is absent from the external
    branch by CONSTRUCTION: it is not in the column list."""
    return conn.execute(
        "SELECT id, idx, grid_from, grid_to, x0, x1, width_ft, area_sf, note "
        "FROM elevation_drop WHERE elevation_id=? ORDER BY idx", (elev_id,)).fetchall()


def _cells_external(conn, elev_id):
    """External cell payload. internal_note IS NOT SELECTED — not fetched, not dropped
    later. `reason` IS included: it is external by construction."""
    return conn.execute(
        "SELECT c.id, c.drop_id, c.level_id, c.level_name, c.status_key, c.reason, "
        "       c.updated_at "
        "FROM elevation_cell c JOIN elevation_drop d ON d.id = c.drop_id "
        "WHERE d.elevation_id = ? ORDER BY d.idx, c.level_id", (elev_id,)).fetchall()


def _cells_internal(conn, elev_id):
    return conn.execute(
        "SELECT c.id, c.drop_id, c.level_id, c.level_name, c.status_key, c.reason, "
        "       c.internal_note, c.updated_by_uid, c.updated_at "
        "FROM elevation_cell c JOIN elevation_drop d ON d.id = c.drop_id "
        "WHERE d.elevation_id = ? ORDER BY d.idx, c.level_id", (elev_id,)).fetchall()


def status_vocabulary(conn, aud="internal"):
    """The five tones, from status_tone — never hard-coded in a template or a payload
    (non-negotiable #7: status colour comes from the status table only).

    Keyed by the token that audience's payload actually carries: the internal key for
    internal viewers, `client_key` for external ones. The renderer then looks up whatever
    token it was given without knowing which audience it is serving."""
    rows = conn.execute(
        "SELECT key, label, tone, severity_rank, client_key, client_label, client_visible, "
        "       sort_order FROM status_tone WHERE module='elevation' ORDER BY sort_order"
    ).fetchall()
    out = {}
    for r in rows:
        short = r["key"].split(".", 1)[1]
        if aud == "internal":
            out[short] = {"key": short, "label": r["label"], "tone": r["tone"],
                          "severity": r["severity_rank"],
                          "reason_required": short in REASON_REQUIRED}
        elif r["client_visible"]:
            ck = r["client_key"] or short
            out[ck] = {"key": ck, "label": r["client_label"] or r["label"],
                       "tone": r["tone"], "severity": r["severity_rank"],
                       "reason_required": False}
    return out


def _status_meta(conn):
    """short key -> {client_key, severity}. One query, used by the derivation below."""
    rows = conn.execute(
        "SELECT key, client_key, severity_rank FROM status_tone WHERE module='elevation'"
    ).fetchall()
    return {r["key"].split(".", 1)[1]: {"client_key": r["client_key"], "sev": r["severity_rank"]}
            for r in rows}


def derive_drop_status(cell_statuses, meta) -> str:
    """A drop's work status, DERIVED from its five cells. NEVER STORED, NEVER ENTERED.

    The two models sit at different grains and must not be allowed to drift:
      `drops` (#201/#256)  per-drop LIFECYCLE — scaffold_active means "is the rig up",
                           not "is the work done". Untouched by this build.
      elevation_cell       per-drop-per-FLOOR work status. The old model cannot express
                           this grain.
    So any drop-level WORK status shown anywhere is computed here from the cells. There
    is no column to enter it into, which prevents divergence by construction rather than
    by remembering.

    Alert statuses win by severity_rank (from status_tone — the ordering is data, not a
    switch here). Progress statuses fall through to explicit rules, because "half the
    floors are complete" is a progress question that severity cannot answer:
      any rework   -> rework      (highest severity; a failure anywhere fails the drop)
      any on_hold  -> on_hold
      all complete -> complete
      any movement -> in_progress (some complete, or some in progress)
      otherwise    -> not_started
    """
    if not cell_statuses:
        return "not_started"
    present = set(cell_statuses)
    alerts = [s for s in present if meta.get(s, {}).get("sev", 0) >= 60]
    if alerts:
        return max(alerts, key=lambda s: meta.get(s, {}).get("sev", 0))
    if present == {"complete"}:
        return "complete"
    if present & {"in_progress", "complete"}:
        return "in_progress"
    return "not_started"


def _api_get_elevation(elev_id):
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, project_code, face, name, source_sheet, sheet_date, dob_job, "
            "       scale_note, geometry_json FROM elevation WHERE id=?", (elev_id,)).fetchone()
        if row is None:
            return _err("not found", 404)
        blocked = _require_project(conn, row["project_code"])
        if blocked:
            return blocked

        aud = audience()
        meta = _status_meta(conn)
        drops = [{"id": d["id"], "idx": d["idx"], "grid_from": d["grid_from"],
                  "grid_to": d["grid_to"], "x0": d["x0"], "x1": d["x1"],
                  "width_ft": d["width_ft"], "area_sf": d["area_sf"], "note": d["note"]}
                 for d in _drop_rows(conn, elev_id)]

        # `status` carries the token for THIS audience: the internal key internally,
        # client_key externally. The internal key never ships to an external payload,
        # even where the two spell the same word today.
        def _tok(sk):
            return sk if aud == "internal" else (meta.get(sk, {}).get("client_key") or sk)

        if aud == "internal":
            cells = [{"id": c["id"], "drop_id": c["drop_id"], "level_id": c["level_id"],
                      "level_name": c["level_name"], "status": c["status_key"],
                      "reason": c["reason"], "internal_note": c["internal_note"],
                      "updated_at": c["updated_at"]}
                     for c in _cells_internal(conn, elev_id)]
        else:
            cells = [{"id": c["id"], "drop_id": c["drop_id"], "level_id": c["level_id"],
                      "level_name": c["level_name"], "status": _tok(c["status_key"]),
                      "reason": c["reason"], "updated_at": c["updated_at"]}
                     for c in _cells_external(conn, elev_id)]

        # Drop roll-up: DERIVED from the cells, never stored. Computed off the raw
        # internal keys, then translated for the audience.
        raw = {}
        for c in _cells_external(conn, elev_id):
            raw.setdefault(c["drop_id"], []).append(c["status_key"])
        for d in drops:
            d["derived_status"] = _tok(derive_drop_status(raw.get(d["id"], []), meta))

        try:
            geom = json.loads(row["geometry_json"] or "{}")
        except ValueError:
            geom = {}

        return jsonify({"data": {
            "id": row["id"],
            "project_code": row["project_code"],
            "face": row["face"],
            "name": row["name"],
            "source_sheet": row["source_sheet"],
            "sheet_date": row["sheet_date"],
            "dob_job": row["dob_job"],
            "scale_note": row["scale_note"],
            "geometry": geom,
            "drops": drops,
            "cells": cells,
            "statuses": status_vocabulary(conn, aud),
            "audience": aud,
            "can_paint": _role() in PAINT_ROLES,
            "can_collaborate": _role() in COLLAB_WRITE_ROLES,
        }})
    finally:
        conn.close()


# ============================================================================
# WRITE — every change appends a cell_event. History is never overwritten.
# ============================================================================

def _validate_status(status_key, reason):
    if status_key not in STATUS_KEYS:
        return f"status must be one of: {', '.join(STATUS_KEYS)}"
    if status_key in REASON_REQUIRED and not (reason or "").strip():
        return f"a reason is required for '{status_key}'"
    if reason and len(reason) > MAX_REASON:
        return f"reason must be {MAX_REASON} characters or fewer"
    return None


def _cell_project(conn, cell_id):
    row = conn.execute(
        "SELECT e.project_code AS code, c.status_key AS status FROM elevation_cell c "
        "JOIN elevation_drop d ON d.id = c.drop_id "
        "JOIN elevation e ON e.id = d.elevation_id WHERE c.id=?", (cell_id,)).fetchone()
    return row


def _apply_cell(conn, cell_id, from_status, status_key, reason, internal_note, uid):
    """Update one cell + append its event. Caller owns the transaction."""
    if internal_note is None:
        conn.execute(
            "UPDATE elevation_cell SET status_key=?, reason=?, updated_by_uid=?, updated_at=? "
            "WHERE id=?", (status_key, (reason or None), uid, _now(), cell_id))
    else:
        conn.execute(
            "UPDATE elevation_cell SET status_key=?, reason=?, internal_note=?, "
            "updated_by_uid=?, updated_at=? WHERE id=?",
            (status_key, (reason or None), (internal_note or None), uid, _now(), cell_id))
    conn.execute(
        "INSERT INTO elevation_cell_event (cell_id, from_status, to_status, reason, "
        "actor_uid, created_at) VALUES (?,?,?,?,?,?)",
        (cell_id, from_status, status_key, (reason or None), uid, _now()))


def _api_post_cell():
    """POST /api/elevation/cell — {cell_id, status_key, reason?, internal_note?}"""
    if _role() not in PAINT_ROLES:
        return _err("forbidden", 403)
    data = request.get_json(silent=True) or {}
    cell_id = data.get("cell_id")
    status_key = (data.get("status_key") or "").strip()
    reason = (data.get("reason") or "").strip() or None
    internal_note = data.get("internal_note")
    if internal_note is not None:
        internal_note = (str(internal_note).strip() or None)
    if not cell_id:
        return _err("cell_id is required", 400)
    bad = _validate_status(status_key, reason)
    if bad:
        return _err(bad, 400)

    conn = _db()
    try:
        row = _cell_project(conn, cell_id)
        if row is None:
            return _err("not found", 404)
        blocked = _require_project(conn, row["code"])
        if blocked:
            return blocked
        _apply_cell(conn, cell_id, row["status"], status_key, reason, internal_note, _uid())
        conn.commit()
        return jsonify({"data": {"cell_id": cell_id, "status_key": status_key,
                                 "reason": reason}})
    finally:
        conn.close()


def _api_post_drop():
    """POST /api/elevation/drop — {drop_id, status_key, reason?, internal_note?}
    Paints every level of one drop. Still one cell_event PER CELL — a bulk action must
    not collapse into a single audit row, or the trail stops matching the cells."""
    if _role() not in PAINT_ROLES:
        return _err("forbidden", 403)
    data = request.get_json(silent=True) or {}
    drop_id = data.get("drop_id")
    status_key = (data.get("status_key") or "").strip()
    reason = (data.get("reason") or "").strip() or None
    internal_note = data.get("internal_note")
    if internal_note is not None:
        internal_note = (str(internal_note).strip() or None)
    if not drop_id:
        return _err("drop_id is required", 400)
    bad = _validate_status(status_key, reason)
    if bad:
        return _err(bad, 400)

    conn = _db()
    try:
        row = conn.execute(
            "SELECT e.project_code AS code FROM elevation_drop d "
            "JOIN elevation e ON e.id = d.elevation_id WHERE d.id=?", (drop_id,)).fetchone()
        if row is None:
            return _err("not found", 404)
        blocked = _require_project(conn, row["code"])
        if blocked:
            return blocked
        cells = conn.execute(
            "SELECT id, status_key FROM elevation_cell WHERE drop_id=? ORDER BY level_id",
            (drop_id,)).fetchall()
        for c in cells:
            _apply_cell(conn, c["id"], c["status_key"], status_key, reason,
                        internal_note, _uid())
        conn.commit()
        return jsonify({"data": {"drop_id": drop_id, "status_key": status_key,
                                 "cells_updated": len(cells)}})
    finally:
        conn.close()


def _api_cell_history(cell_id):
    """GET /api/elevation/cell/<id>/history — the append-only trail for one cell.
    Actor is rendered through the same W-#### / real-name rule as comments."""
    conn = _db()
    try:
        row = _cell_project(conn, cell_id)
        if row is None:
            return _err("not found", 404)
        blocked = _require_project(conn, row["code"])
        if blocked:
            return blocked
        rows = conn.execute(
            "SELECT from_status, to_status, reason, actor_uid, created_at "
            "FROM elevation_cell_event WHERE cell_id=? ORDER BY id", (cell_id,)).fetchall()
        internal = is_internal()
        return jsonify({"data": [
            {"from_status": r["from_status"], "to_status": r["to_status"],
             "reason": r["reason"], "at": r["created_at"],
             "actor": display_actor(conn, r["actor_uid"], internal)}
            for r in rows]})
    finally:
        conn.close()


# ============================================================================
# ACTOR DISPLAY — SSC staff are W-#### to outsiders; outsiders are named
# ============================================================================

_ACTOR_CACHE_KEY = "_elev_actor_cache"


def display_actor(conn, uid, internal_viewer: bool) -> dict:
    """How a person is named to THIS viewer.

    Internal viewer  -> real display name for everyone.
    External viewer  -> SSC STAFF render as their W-#### worker id (never a name);
                        outside parties (architect / client / vendor) show real names,
                        because an architect signing a comment anonymously is useless
                        to the owner.

    An SSC user with no linked worker record has no W-####; they render as "SSC" — a
    role-level attribution, never a name, and never a fabricated id.
    """
    if not uid:
        return {"label": "—", "kind": "unknown"}
    cache = g.setdefault(_ACTOR_CACHE_KEY, {}) if g else {}
    ck = (uid, internal_viewer)
    if ck in cache:
        return cache[ck]
    row = conn.execute(
        "SELECT u.display_name, u.full_name, u.role, u.employee_id_link "
        "FROM users u WHERE u.id=?", (uid,)).fetchone()
    if row is None:
        out = {"label": "—", "kind": "unknown"}
    else:
        name = row["display_name"] or row["full_name"] or "—"
        role = row["role"]
        if internal_viewer or role in EXTERNAL_ROLES or role == "vendor":
            out = {"label": name, "kind": "person", "role": role}
        else:
            wid = None
            if row["employee_id_link"]:
                w = conn.execute(
                    "SELECT worker_id FROM employees WHERE employee_id=?",
                    (row["employee_id_link"],)).fetchone()
                wid = w["worker_id"] if w else None
            out = ({"label": wid, "kind": "worker_id"} if wid
                   else {"label": "SSC", "kind": "org"})
    cache[ck] = out
    return out


# ============================================================================
# PAGE
# ============================================================================

def _markup_page(elev_id=None):
    """GET /drawing-markup  ·  GET /drawing-markup/<elev_id> — the standalone v2 page.

    Served DIRECTLY from templates/v2/, not through ui_version.resolve_page(): this page
    has no v1 original to fall back to, so twin-resolution has nothing to resolve. It is
    the first surface built to the v2 system, shipped standalone — the #279 toggle is
    untouched by it, and its byte-identity gate is unaffected because this route did not
    exist when that gate was measured."""
    role = _role()
    if role not in (INTERNAL_ROLES | EXTERNAL_ROLES):
        return _err("forbidden", 403)
    if not MARKUP_PAGE.exists():
        return _err("drawing markup page not found", 404)
    resp = send_file(str(MARKUP_PAGE))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def _api_my_elevations():
    """GET /api/elevations — the elevations this user may open. The page uses it to find
    its default; it is also the check that an architect sees ONLY assigned projects."""
    conn = _db()
    try:
        user = current_user()
        codes = accessible_codes(conn, user)
        if not codes:
            return jsonify({"data": []})
        marks = ",".join("?" for _ in codes)
        rows = conn.execute(
            f"SELECT e.id, e.project_code, e.face, e.name, p.name AS project_name "
            f"FROM elevation e LEFT JOIN projects p ON p.project_code = e.project_code "
            f"WHERE e.project_code IN ({marks}) ORDER BY e.project_code, e.face",
            tuple(codes)).fetchall()
        return jsonify({"data": [
            {"id": r["id"], "project_code": r["project_code"], "face": r["face"],
             "name": r["name"], "project_name": r["project_name"]} for r in rows]})
    finally:
        conn.close()


# ============================================================================
# ARCHITECT CONTAINMENT — the gate that makes this safe to hand outside
# ============================================================================
#
# `architect` was already in the users role CHECK, defined-not-onboarded, so nothing had
# ever contained it. pm_scoping.pm_can_access_project already returns False for architect
# on any path CARRYING a project code — but that only covers project-scoped paths. Every
# internal endpoint WITHOUT a project code in its path (and without its own role gate)
# was reachable. A `client` is contained by client_portal._client_gate; there was no
# equivalent for an architect, and one role short of containment is the whole hole.
#
# ALLOWLIST, not denylist. A route added tomorrow is closed to architects until somebody
# deliberately opens it — the same default-deny posture as #264/#267/#269.

_ARCH_ALLOW_EXACT = {
    "/drawing-markup",
    "/api/elevations",
    "/set-password",
    "/api/health",
    "/api/today",
    "/api/ui/version",        # #279 — every role may choose its own interface
}
_ARCH_ALLOW_PREFIXES = (
    "/drawing-markup/",
    "/api/elevation/",
    "/api/comments",          # step 4
    "/api/rfi",               # step 5
    "/api/meeting-request",   # step 6 (route exists only once step 6 ships)
    "/api/auth/",
    "/files/static/",
)


def _architect_allowed(path: str) -> bool:
    return path in _ARCH_ALLOW_EXACT or any(path.startswith(p) for p in _ARCH_ALLOW_PREFIXES)


def _architect_gate():
    """Contain `architect` to the drawing-markup surface. Registered AFTER the auth gate
    (g.auth_user set) and after the client gate. Server-side; hiding nav is not access
    control. Per-PROJECT scoping is enforced separately in _require_project — this gate
    decides which ROUTES exist for an architect at all, not which projects."""
    user = current_user()
    if not user or user.get("role") != "architect":
        return None
    path = request.path
    if _architect_allowed(path):
        return None
    logging.info(f"elevation: architect contain block path={path} uid={user.get('id')}")
    if path.startswith("/api/"):
        return _err("forbidden", 403)
    from flask import redirect
    return redirect("/drawing-markup")


def register(app) -> None:
    """MUST follow apply_auth_gate (current_user populated) and the #263 scoping hook."""
    app.before_request(_architect_gate)
    app.add_url_rule("/drawing-markup", "drawing_markup_page", _markup_page, methods=["GET"])
    app.add_url_rule("/drawing-markup/<int:elev_id>", "drawing_markup_page_id",
                     _markup_page, methods=["GET"])
    app.add_url_rule("/api/elevations", "elevation_list", _api_my_elevations, methods=["GET"])
    app.add_url_rule("/api/elevation/<int:elev_id>", "elevation_get",
                     _api_get_elevation, methods=["GET"])
    app.add_url_rule("/api/elevation/cell", "elevation_cell_post",
                     _api_post_cell, methods=["POST"])
    app.add_url_rule("/api/elevation/drop", "elevation_drop_post",
                     _api_post_drop, methods=["POST"])
    app.add_url_rule("/api/elevation/cell/<int:cell_id>/history", "elevation_cell_history",
                     _api_cell_history, methods=["GET"])
