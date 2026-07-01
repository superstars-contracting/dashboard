"""#264 CLIENT portal + the client DEFAULT-DENY gate — #267 contains clients to /welcome.

The most security-sensitive surface in the app. Posture:

  * DEFAULT-DENY GATE. #267 — for now a `client` has NO access grants, so `_client_gate`
    HARD-CONTAINS them to the welcome/pending page + auth: EVERY other page redirects to
    /welcome and every API returns 403 by construction (company dashboard, portal, crm,
    internal project endpoints, field-photos, drop plan, admin, by-ID fetches — none
    reachable). The #264 portal below stays code-intact but is NOT client-reachable yet;
    per-section un-gating returns when the access-grant system is built. The remaining
    portal design notes describe that future-reachable surface:
  * PROJECT-SCOPED. A client is assigned to exactly ONE project (pm_project_assignment,
    generalized from #263). They see only that project, and only while it is active.
  * PER-RESOURCE ISOLATION (closes the #263 by-ID gap). Every by-ID fetch re-derives
    ownership from the row: a photo serves ONLY if it BELONGS to the client's project AND
    is shared to the `client` audience AND is not red-flagged (visibility.py). Guessing an
    id from another project or an unshared photo yields 404 — never the bytes.
  * CURATED-ONLY PAYLOAD. The portal serializes id / caption / date / gated URLs only —
    never cost, labor, worker PII, file paths, uploader, or any internal field (CLAUDE.md).
  * READ-ONLY. The portal exposes no write endpoint.

Production stays on SQLite; all SQL routes through the caller's db_layer connection so it
runs identically on Postgres. Dates are LOCAL.
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Response, jsonify, redirect, request, send_file

from auth import _db, current_user, requires_role
import visibility
import dropplan_rollups as _rollups

SCRIPT_DIR = Path(__file__).resolve().parent
PORTAL_PAGE = SCRIPT_DIR / "client_portal.html"
WELCOME_PAGE = SCRIPT_DIR / "welcome.html"   # #267 — the client hard-stop
_FP_BASE = SCRIPT_DIR / "data_room" / "field_photos"

# ============= CLIENT DEFAULT-DENY GATE — #267: contain to /welcome =============
# For now a `client` has NO access grants, so they are HARD-CONTAINED to the welcome/pending
# page + auth. The ONLY paths a client may reach: /welcome, the forced-reset page, the auth
# API, the two public no-data pings, and the vendored static assets the welcome page loads.
# Every other PAGE -> redirect to /welcome; every API -> 403 — server-side, so no portal,
# internal, admin, drop-plan, crm, or by-ID surface is reachable even by direct URL.
# (The #264 portal endpoints below stay REGISTERED — code-intact — but are NOT client-
# reachable yet; per-section un-gating returns when the access-grant system is built.)
_CLIENT_ALLOW_PREFIXES = ("/api/auth/", "/files/static/")
_CLIENT_ALLOW_EXACT = {"/welcome", "/set-password", "/api/health", "/api/today"}


def _client_allowed(path: str) -> bool:
    if path in _CLIENT_ALLOW_EXACT:
        return True
    return any(path.startswith(p) for p in _CLIENT_ALLOW_PREFIXES)


def _client_gate():
    """Registered AFTER the auth gate (g.auth_user set). A `client` is hard-contained to the
    welcome page + auth (#267): default-deny everything else — every PAGE redirects to
    /welcome, every API returns 403 — server-side, so no portal/internal/by-ID resource is
    reachable even by direct URL. Grants (per-section un-gating) are a later build."""
    user = current_user()
    if not user or user.get("role") != "client":
        return None  # non-clients handled by their own gates
    if _client_allowed(request.path):
        return None
    logging.info(f"client_portal: contain block path={request.path}")
    if request.path.startswith("/api/"):
        return jsonify({"error": "forbidden"}), 403
    return redirect("/welcome")


# ============= CLIENT PROJECT SCOPE =============

def client_project_code(user_id, conn):
    """The ONE active project a client is assigned to (pm_project_assignment, generalized).
    None if unassigned or the project is closed (closed drops off the client view, #263)."""
    row = conn.execute(
        "SELECT a.project_code FROM pm_project_assignment a "
        "JOIN projects p ON p.project_code = a.project_code "
        "WHERE a.user_id = ? AND (p.status = 'active' OR p.status IS NULL) "
        "ORDER BY a.project_code LIMIT 1",
        (user_id,)).fetchone()
    return row[0] if row else None


# ============= CURATED SERIALIZERS (no PII / paths / internal fields) =============

def _portal_photo(r) -> dict:
    """The ONLY photo fields a client receives. No worker_id / stage / file_name / size /
    mime / uploader / project_code / *_path — just what's needed to show the image."""
    return {
        "id": r["id"],
        "caption": r["caption"],
        "taken_at": (r["taken_at"] or "")[:10] or None,   # date only (LOCAL), no time
        "thumb_url": f"/api/portal/photos/{r['id']}/thumb",
        "file_url": f"/api/portal/photos/{r['id']}/file",
    }


def _progress_label(pct: float) -> str:
    if pct <= 0:
        return "Getting started"
    if pct >= 100:
        return "Complete"
    if pct < 35:
        return "Underway"
    if pct < 80:
        return "In progress"
    return "Nearing completion"


# ============= WELCOME / PENDING HARD-STOP (#267) =============

def _welcome_page():
    """The client welcome/pending page — the contained dead-end. Served to any authenticated
    user (the auth gate enforces login; the client gate routes clients here). No-store."""
    if not WELCOME_PAGE.exists():
        return ("welcome page missing", 500)
    resp = send_file(str(WELCOME_PAGE))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


# ============= PORTAL ENDPOINTS (client-only, read-only) =============

@requires_role("client")
def _portal_page():
    if not PORTAL_PAGE.exists():
        return ("client portal page missing", 500)
    resp = send_file(str(PORTAL_PAGE))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@requires_role("client")
def _portal_project():
    """Curated project header + high-level progress + a curated progress summary. NO money,
    NO drop internals — overall % only (project_rollup with include_cost=False)."""
    user = current_user()
    conn = _db()
    try:
        code = client_project_code(user["id"], conn)
        if not code:
            return jsonify({"data": {"project": None}})
        p = conn.execute(
            "SELECT project_code, name, address, city_zip, status FROM projects WHERE project_code = ?",
            (code,)).fetchone()
        if not p:
            return jsonify({"data": {"project": None}})
        roll = _rollups.project_rollup(conn, code, include_cost=False)  # include_cost=False => NO $ fields
        pct = roll.get("overall_progress_pct", 0.0) or 0.0
        vis_ids = visibility.client_visible_photo_ids(conn, code)
        last_activity = None
        if vis_ids:
            row = conn.execute(
                f"SELECT MAX(substr(taken_at,1,10)) FROM field_photos "
                f"WHERE id IN ({','.join(['?']*len(vis_ids))})", vis_ids).fetchone()
            last_activity = row[0] if row else None
        label = _progress_label(pct)
        summary = (f"Your project is {label.lower()} — about {pct:.0f}% complete."
                   + (f" {len(vis_ids)} photo{'s' if len(vis_ids) != 1 else ''} shared with you."
                      if vis_ids else " New photos will appear here as we share them."))
        return jsonify({"data": {
            "project": {
                "code": p["project_code"], "name": p["name"] or p["project_code"],
                "address": ", ".join(x for x in (p["address"], p["city_zip"]) if x) or None,
                "status": (p["status"] or "active"),
            },
            "progress": {"pct": round(pct, 0), "label": label},
            "summary": {"text": summary, "last_activity": last_activity,
                        "photos_shared": len(vis_ids)},
            # v1: financials intentionally omitted — a clean spot for a future curated note.
        }})
    finally:
        conn.close()


@requires_role("client")
def _portal_photos():
    """The client gallery — ONLY photos shared to the client audience for the client's
    project, never red-flagged. Default-deny: an unshared photo is simply absent."""
    user = current_user()
    conn = _db()
    try:
        code = client_project_code(user["id"], conn)
        if not code:
            return jsonify({"data": {"photos": []}})
        ids = visibility.client_visible_photo_ids(conn, code)
        if not ids:
            return jsonify({"data": {"photos": []}})
        rows = conn.execute(
            f"SELECT id, caption, taken_at FROM field_photos WHERE id IN ({','.join(['?']*len(ids))}) "
            f"ORDER BY taken_at DESC, id DESC", ids).fetchall()
        resp = jsonify({"data": {"photos": [_portal_photo(r) for r in rows]}})
        resp.headers["Cache-Control"] = "no-store"
        return resp
    finally:
        conn.close()


def _portal_serve(photo_id, col):
    """Serve photo bytes to a client BY ID — only after re-deriving ownership + visibility
    from the row (per-resource isolation). Any other-project / unshared / flagged / unknown
    id -> 404 (never reveals existence). `col` is 'file_path' or 'thumb_path'."""
    user = current_user()
    conn = _db()
    try:
        code = client_project_code(user["id"], conn)
        if not code or not visibility.photo_visible_to_client(conn, photo_id, code):
            return jsonify({"error": "not found"}), 404
        r = conn.execute(
            f"SELECT {col} AS p, mime FROM field_photos WHERE id = ?", (photo_id,)).fetchone()
    finally:
        conn.close()
    if not r or not r["p"]:
        return jsonify({"error": "not found"}), 404
    p = Path(r["p"])
    try:
        if not p.resolve().is_relative_to(_FP_BASE.resolve()) or not p.exists():
            return jsonify({"error": "not found"}), 404
    except (OSError, ValueError):
        return jsonify({"error": "not found"}), 404
    return send_file(str(p), mimetype=(r["mime"] or "image/jpeg"), conditional=True)


@requires_role("client")
def _portal_photo_thumb(photo_id):
    return _portal_serve(photo_id, "thumb_path")


@requires_role("client")
def _portal_photo_file(photo_id):
    return _portal_serve(photo_id, "file_path")


def register(app) -> None:
    """Wire the client default-deny gate + the read-only portal page/API. Call AFTER
    apply_auth_gate (and the other gates) so g.auth_user is set; the gate then enforces
    default-deny for the client role, and every portal endpoint is requires_role('client')
    + project-scoped + per-resource visibility-checked."""
    app.before_request(_client_gate)
    app.add_url_rule("/welcome", "client_welcome_page", _welcome_page, methods=["GET"])  # #267 hard-stop
    app.add_url_rule("/portal", "client_portal_page", _portal_page, methods=["GET"])
    app.add_url_rule("/api/portal/project", "client_portal_project", _portal_project, methods=["GET"])
    app.add_url_rule("/api/portal/photos", "client_portal_photos", _portal_photos, methods=["GET"])
    app.add_url_rule("/api/portal/photos/<int:photo_id>/thumb", "client_portal_thumb",
                     _portal_photo_thumb, methods=["GET"])
    app.add_url_rule("/api/portal/photos/<int:photo_id>/file", "client_portal_file",
                     _portal_photo_file, methods=["GET"])
