"""UI v2 toggle — resolution + v2 page resolution with silent v1 fallback (#279, phase 0).

THE ONE PLACE the interface version is decided, and the ONE PLACE a page filename
becomes a path on disk. Every UI route goes through `serve_ui()`.

-------------------------------------------------------------------------------
ARCHITECTURE NOTE — why this is not `render_ui(template, **ctx)`
-------------------------------------------------------------------------------
The v2 build brief specifies a Jinja shape: `render_template(f"v2/{template}")`
with a `TemplateNotFound` fallback. This application has NO Jinja templates and
makes ZERO `render_template` calls — every UI surface is a standalone static HTML
file served with `send_file`/`Response`, and all data arrives over `/api/*` JSON.

So the same contract is implemented against the real architecture:

    render_template(f"v2/{name}")  ->  templates/v2/<name>        (if it exists)
    render_template(name)          ->  <dashboard root>/<name>    (v1, ALWAYS)
    TemplateNotFound               ->  Path.exists() is False

Everything the brief depends on is preserved:
  * v1 files are NEVER touched or read differently — same bytes, same headers.
  * A page with no v2 twin silently serves v1, so partial migration always ships.
  * "Context dicts stay identical" is free here: there are no context dicts. A v2
    twin consumes exactly the same /api/* endpoints its v1 original does.
  * Deleting templates/v2/ restores the old UI completely, by construction.

-------------------------------------------------------------------------------
RESOLUTION ORDER (highest priority first)
-------------------------------------------------------------------------------
  1. SSC_UI_FORCE_V1=1   env kill switch -> everyone gets v1, nothing else is read
  2. ?ui=1 | ?ui=2       per-request override, THIS REQUEST ONLY (never persisted)
  3. users.ui_version    INTEGER NOT NULL DEFAULT 1
  4. default             1

The kill switch is read PER REQUEST, not cached at import: flipping it is rollback
layer 2, and an operator who sets it expects the next request to obey after the
documented waitress restart — not to depend on which module imported first.

DEFAULT-SAFE BY CONSTRUCTION: anything that is not exactly 2 resolves to 1. An
unmigrated database, a NULL, a junk value, an anonymous request, or a DB error all
degrade to the classic UI rather than 500ing a page.
"""
from __future__ import annotations

import os
from pathlib import Path

from flask import g, request

SCRIPT_DIR = Path(__file__).resolve().parent

# v1 lives at the dashboard root (untouched, forever). v2 twins live here.
V1_ROOT = SCRIPT_DIR
V2_ROOT = SCRIPT_DIR / "templates" / "v2"

FORCE_V1_ENV = "SSC_UI_FORCE_V1"


# ============= 1. the kill switch =============

def force_v1() -> bool:
    """Rollback layer 2: SSC_UI_FORCE_V1=1 -> everyone gets v1, ignore everything below.
    Truthy spellings are accepted so an operator typing `true` under pressure is not
    silently ignored."""
    return (os.environ.get(FORCE_V1_ENV) or "").strip().lower() in ("1", "true", "yes", "on")


# ============= 3. the stored per-user preference =============

_COLUMN_READY: bool | None = None   # None = not probed yet; cached once True


def _column_ready(conn) -> bool:
    """True when users.ui_version exists — a CATALOG probe (sqlite_master /
    information_schema), never a query against the column itself. On Postgres a failed
    statement aborts the surrounding transaction, so probing by try/except a SELECT is
    not an option (the #269 lesson). An UNMIGRATED database degrades to v1 for everyone
    instead of 500ing every page."""
    global _COLUMN_READY
    if _COLUMN_READY:
        return True
    import db_layer
    if db_layer.is_postgres():
        found = bool(conn.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name='users' AND column_name='ui_version'").fetchone())
    else:
        found = any(r[1] == "ui_version"
                    for r in conn.execute("PRAGMA table_info(users)").fetchall())
    if found:
        _COLUMN_READY = True
    return found


def stored_version(user_id) -> int:
    """users.ui_version for `user_id`, or 1 for anything unresolvable."""
    if not user_id:
        return 1
    import db_layer
    conn = None
    try:
        conn = db_layer.connect()
        if not _column_ready(conn):
            return 1
        row = conn.execute("SELECT ui_version FROM users WHERE id = ?", (user_id,)).fetchone()
        return 2 if (row is not None and row["ui_version"] == 2) else 1
    except Exception:
        # Never let the toggle take a page down — the classic UI is always the safe answer.
        return 1
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def set_stored_version(user_id, version: int) -> int:
    """Persist users.ui_version. Returns the value actually stored (1 unless 2 was asked
    for). Raises RuntimeError if the column is missing — a caller writing the preference
    wants to know it did not stick, unlike a reader, which degrades silently."""
    v = 2 if version == 2 else 1
    import db_layer
    conn = db_layer.connect()
    try:
        if not _column_ready(conn):
            raise RuntimeError("users.ui_version is missing — run apply_ui_version_279.py")
        conn.execute("UPDATE users SET ui_version = ? WHERE id = ?", (v, user_id))
        conn.commit()
        return v
    finally:
        conn.close()


# ============= the resolver =============

def resolve() -> int:
    """Apply the four-step order and return 1 or 2. Cached on `g` per request."""
    if force_v1():
        return 1
    # 2. per-request override — this request only, never written to the users row.
    try:
        raw = (request.args.get("ui") or "").strip()
    except RuntimeError:      # outside a request context
        raw = ""
    if raw == "2":
        return 2
    if raw == "1":
        return 1
    # 3. the stored preference.
    try:
        from auth import current_user
        user = current_user() or {}
    except Exception:
        user = {}
    return stored_version(user.get("id"))


def current() -> int:
    """The resolved version for this request, computed once and cached on `g`.

    Deliberately lazy: API routes never call this, so the extra users lookup lands only
    on the handful of routes that actually serve a page."""
    v = getattr(g, "ui_version", None)
    if v in (1, 2):
        return v
    v = resolve()
    g.ui_version = v
    return v


def apply(app) -> None:
    """Set g.ui_version eagerly on page (non-/api/) requests so any downstream code can
    read `g.ui_version` directly, as the brief specifies. MUST be registered AFTER
    auth.apply_auth_gate so current_user() is populated; an unauthenticated request is
    short-circuited by the auth gate before this hook ever runs."""
    @app.before_request
    def _set_ui_version():          # noqa: ANN202 — flask hook
        if not request.path.startswith("/api/"):
            current()
        return None


# ============= v2 page resolution (the render_ui equivalent) =============

def v2_page(page_name: str) -> Path | None:
    """The v2 twin of `page_name` if one exists on disk, else None.

    Refuses anything that is not a plain filename: a page name reaching a directory
    outside templates/v2 would turn every UI route into a file-disclosure primitive."""
    if not page_name or "/" in page_name or "\\" in page_name or page_name.startswith("."):
        return None
    candidate = V2_ROOT / page_name
    try:
        resolved = candidate.resolve()
        if not resolved.is_relative_to(V2_ROOT.resolve()):
            return None
    except OSError:
        return None
    return resolved if resolved.is_file() else None


def resolve_page(v1_path) -> Path:
    """THE substitution point. Given the v1 page path a route already serves, return the
    path to serve: the v2 twin when this request resolves to v2 AND the twin exists,
    otherwise the v1 path, byte-for-byte unchanged.

    Not migrated yet is not an error — it is the design (rollback layer 3 is literally
    'delete one file in templates/v2/')."""
    v1_path = Path(v1_path)
    if current() != 2:
        return v1_path
    return v2_page(v1_path.name) or v1_path


def serve_ui(v1_path, serve_fn):
    """Serve `v1_path`'s effective page through `serve_fn`, which owns the response
    (headers, no-store, mimetype). The version decision lives here; the response
    contract stays exactly where each route already had it."""
    return serve_fn(resolve_page(v1_path))


def is_v2_active(v1_path) -> bool:
    """True when this request is actually being served a v2 twin of `v1_path` — i.e. the
    'You're on the new interface' affordance belongs on the page. False whenever the page
    fell back to v1, so the affordance never appears on a classic page."""
    return current() == 2 and v2_page(Path(v1_path).name) is not None


# ============= THE SWITCH =============
# Interface — Classic / New. A user sets their own; an admin sets it for anyone.
#
# The control lives on its OWN page (/settings/interface) rather than inside an
# existing screen, because non-negotiable #1 is that no v1 file is ever modified —
# and the phase-0 gate is that every existing page is byte-identical. A brand-new
# additive page breaks neither. Rollback layer 1 ("flip users.ui_version to 1") has
# to be something the operator can actually do from a browser on day one, and this
# is that surface.

SETTINGS_PAGE = SCRIPT_DIR / "ui_settings.html"


def _json_error(msg, code):
    from flask import jsonify
    return jsonify({"error": msg}), code


def _read_version_request():
    """The requested version from a JSON body, or None if absent/invalid."""
    data = request.get_json(silent=True) or {}
    raw = data.get("ui_version")
    if isinstance(raw, str) and raw.strip() in ("1", "2"):
        raw = int(raw.strip())
    return raw if raw in (1, 2) else None


def _api_get_version():
    """GET /api/ui/version — what this user has stored, and what is actually in force."""
    from flask import jsonify
    from auth import current_user
    user = current_user() or {}
    stored = stored_version(user.get("id"))
    return jsonify({"data": {
        "ui_version": stored,
        "effective": current(),
        "forced_v1": force_v1(),          # the kill switch is up — the UI says why
    }})


def _api_set_version():
    """POST /api/ui/version {ui_version:1|2} — a user switching their OWN interface.
    Deliberately NOT role-gated beyond being signed in: 'Switch back' has to work for
    every role, and choosing your own interface grants no access to anything."""
    from flask import jsonify
    from auth import current_user
    user = current_user() or {}
    if not user.get("id"):
        return _json_error("auth required", 401)
    want = _read_version_request()
    if want is None:
        return _json_error("ui_version must be 1 or 2", 400)
    try:
        stored = set_stored_version(user["id"], want)
    except RuntimeError as e:
        return _json_error(str(e), 503)
    import logging
    logging.info(f"ui_version: user_id={user['id']} -> v{stored}")   # PII rule: id, not email
    return jsonify({"data": {"ui_version": stored, "effective": current(), "forced_v1": force_v1()}})


def _api_admin_set_version(user_id):
    """POST /api/admin/ui/version/<user_id> {ui_version:1|2} — admin sets it for anyone.
    Admin-only and audited: changing what another person sees is an administrative act,
    even though it grants no data access."""
    from flask import jsonify
    from auth import current_user, _now_iso
    import db_layer
    actor = current_user() or {}
    want = _read_version_request()
    if want is None:
        return _json_error("ui_version must be 1 or 2", 400)
    conn = db_layer.connect()
    try:
        target = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()
        if target is None:
            return _json_error("no such user", 404)
    finally:
        conn.close()
    try:
        stored = set_stored_version(user_id, want)
    except RuntimeError as e:
        return _json_error(str(e), 503)
    conn = db_layer.connect()
    try:
        conn.execute(
            "INSERT INTO audit_log (action, actor_user_id, actor_role, target_type, "
            "target_id, note, created_at) VALUES (?,?,?,?,?,?,?)",
            ("ui_version_set", actor.get("id"), actor.get("role"), "user",
             str(user_id), f"interface set to v{stored}", _now_iso()))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"data": {"user_id": user_id, "ui_version": stored}})


def _settings_page():
    """GET /settings/interface — the Classic / New control. Additive page; itself
    served through resolve_page so it can get a v2 twin later like anything else."""
    from flask import send_file
    if not SETTINGS_PAGE.exists():
        return _json_error("interface settings page not found", 404)
    resp = send_file(str(resolve_page(SETTINGS_PAGE)))
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


def register(app) -> None:
    """Wire the switch. MUST follow apply_auth_gate — every route here is behind the
    blanket login gate, and the admin route is additionally role-gated server-side."""
    from auth import requires_role
    app.add_url_rule("/settings/interface", "ui_settings_page", _settings_page, methods=["GET"])
    app.add_url_rule("/api/ui/version", "ui_version_get", _api_get_version, methods=["GET"])
    app.add_url_rule("/api/ui/version", "ui_version_set", _api_set_version, methods=["POST"])
    app.add_url_rule("/api/admin/ui/version/<int:user_id>", "ui_version_admin_set",
                     requires_role('admin')(_api_admin_set_version), methods=["POST"])
