"""Dashboard auth foundation (#48) — hashing, sessions, gating.

Scope: dashboard users only (operator + future C-suite/PM/super). Worker-app
PIN sign-in is unaffected; this module does not touch employees.pin or
/api/worker/* routes.

Public surface used by server.py:
  - apply_auth_gate(app)         — registers before_request hook + login routes
  - requires_role(*roles)        — per-route decorator for role gating
  - current_user()               — accessor for the request-scoped user dict

Session model: server-side. Cookie holds an opaque random id; the row in
`sessions` is the truth. Logout / password change / admin revoke = DELETE
the row. 12-hour sliding window.

PII discipline (per CLAUDE.md):
  - Never log password_hash, plaintext passwords, or full session ids.
  - Session ids in logs are redacted to last-6 prefix.
  - Login failure responses do not distinguish "no such email" from
    "wrong password" — both return the same 401.
"""
from __future__ import annotations

import functools
import logging
import secrets
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import bcrypt
from flask import g, jsonify, make_response, redirect, request, send_file

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
LOGIN_PAGE_PATH = SCRIPT_DIR / "login.html"

COOKIE_NAME = "ssc_session"
SESSION_TTL = timedelta(hours=12)  # sliding — refreshed on each authed request

# Paths that bypass auth entirely. Order: prefix match (startswith) for
# wildcard buckets; exact match for single paths.
#
# #248 — the /files/ exemption narrowed to /files/static/ (vendored shell
# assets only; the old whole-project mount let anyone download the DB and
# source). /preview/ LOST its exemption: it serves rendered project
# documents (internal DCRs etc.), so it now requires a session like every
# other operator surface. Generated artifacts are served by the gated
# /project-files/ route, which is intentionally NOT exempt.
_PUBLIC_PREFIXES = (
    "/api/auth/",         # login, logout, me — see below for /me caveat
    "/api/worker/",       # worker-app PIN flow — unchanged
    "/files/static/",     # vendored shell assets ONLY (css/js/fonts/vendor)
)
_PUBLIC_EXACT = {
    "/login",
    "/api/health",
    "/api/today",         # date-only, no PII, used by client shells on load
    "/worker-app",
    "/worker-app.html",
    "/api/worker-sign-in",
    "/worker-app-manifest.json",  # PWA shell (#248) — code/config, no data
    "/worker-app-sw.js",          # PWA shell (#248)
}


# ============= PASSWORD HASHING =============

def hash_password(plaintext: str) -> str:
    """bcrypt hash with per-call random salt. Returns the 60-char $2b$ string."""
    if not isinstance(plaintext, str) or not plaintext:
        raise ValueError("password must be a non-empty string")
    return bcrypt.hashpw(plaintext.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plaintext: str, hashed: str) -> bool:
    """Constant-time compare against a stored bcrypt hash. False on any error."""
    if not plaintext or not hashed:
        return False
    try:
        return bcrypt.checkpw(plaintext.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        return False


# ============= DB HELPER (local — avoids import cycle with server.py) =============

def _db():
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _redact_sid(sid: Optional[str]) -> str:
    """Session id appearing in logs/errors — last 6 chars only, no leak of the full token."""
    if not sid:
        return "—"
    return f"…{sid[-6:]}"


# ============= USERS =============

def get_user_by_email(email: str) -> Optional[dict]:
    if not email:
        return None
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash, role, full_name, employee_id_link, "
            "       is_active, created_at, last_login_at "
            "FROM users WHERE LOWER(email) = LOWER(?)",
            (email.strip(),),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[dict]:
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, email, role, full_name, employee_id_link, is_active, "
            "       created_at, last_login_at "
            "FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def touch_last_login(user_id: int) -> None:
    conn = _db()
    try:
        conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_now_iso(), user_id))
        conn.commit()
    finally:
        conn.close()


# ============= SESSIONS =============

def create_session(user_id: int, user_agent: Optional[str]) -> str:
    """Insert a sessions row, return the opaque id (caller sets it as cookie)."""
    sid = secrets.token_urlsafe(32)
    expires = (datetime.now() + SESSION_TTL).isoformat(timespec="seconds")
    # Trim UA to a reasonable length — not used for auth, just forensic breadcrumb.
    ua = (user_agent or "")[:255]
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO sessions (id, user_id, expires_at, user_agent) VALUES (?, ?, ?, ?)",
            (sid, user_id, expires, ua),
        )
        conn.commit()
    finally:
        conn.close()
    return sid


def lookup_session(sid: str) -> Optional[dict]:
    """Resolve a session id to the active user row. Refreshes sliding TTL on hit.

    Returns None for missing, expired, or inactive-user sessions. Expired
    rows are deleted opportunistically (no separate sweeper needed for the
    single-operator workload).
    """
    if not sid:
        return None
    conn = _db()
    try:
        row = conn.execute(
            "SELECT s.id, s.user_id, s.expires_at, "
            "       u.email, u.role, u.full_name, u.employee_id_link, u.is_active "
            "FROM sessions s JOIN users u ON u.id = s.user_id "
            "WHERE s.id = ?",
            (sid,),
        ).fetchone()
        if not row:
            return None
        # Expiry check — string compare on ISO-8601 with seconds precision is total-order safe.
        if row["expires_at"] < _now_iso():
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            conn.commit()
            return None
        if not row["is_active"]:
            # Deactivated user — kill the session so re-auth is forced.
            conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            conn.commit()
            return None
        # Sliding refresh: push expires_at forward, update last_used_at.
        new_expires = (datetime.now() + SESSION_TTL).isoformat(timespec="seconds")
        conn.execute(
            "UPDATE sessions SET expires_at = ?, last_used_at = ? WHERE id = ?",
            (new_expires, _now_iso(), sid),
        )
        conn.commit()
        return {
            "id": row["user_id"],
            "email": row["email"],
            "role": row["role"],
            "full_name": row["full_name"],
            "employee_id_link": row["employee_id_link"],
        }
    finally:
        conn.close()


def destroy_session(sid: str) -> None:
    if not sid:
        return
    conn = _db()
    try:
        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
        conn.commit()
    finally:
        conn.close()


def destroy_all_user_sessions(user_id: int) -> None:
    """Invalidate every session for a user (e.g. on password change). Reserved for future use."""
    conn = _db()
    try:
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


# ============= COOKIE HELPERS =============

def _request_is_https() -> bool:
    """True if the client-facing connection is HTTPS.

    Direct HTTPS sets request.is_secure. Under Tailscale serve the local
    Flask sees HTTP from the loopback; Tailscale's reverse proxy sets
    X-Forwarded-Proto=https. Either signal counts.
    """
    if request.is_secure:
        return True
    return (request.headers.get("X-Forwarded-Proto", "").lower() == "https")


def _set_session_cookie(response, sid: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        sid,
        max_age=int(SESSION_TTL.total_seconds()),
        httponly=True,
        secure=_request_is_https(),
        samesite="Lax",
        path="/",
    )


def _clear_session_cookie(response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        "",
        max_age=0,
        httponly=True,
        secure=_request_is_https(),
        samesite="Lax",
        path="/",
    )


# ============= CURRENT USER =============

def current_user() -> Optional[dict]:
    """Request-scoped user dict, populated by the before_request gate. None if unauthed."""
    return getattr(g, "auth_user", None)


# ============= GATE =============

def _is_public_path(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    for prefix in _PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    return False


def _wants_json(path: str) -> bool:
    """JSON-style endpoints get a 401; HTML routes get a redirect to /login.

    Non-HTML resource fetches (worker-photo image, file downloads under
    /worker-files/) ALSO get 401 instead of a redirect. The 302 -> /login
    HTML response is fatal when a <img src=/worker-files/...> hits it
    while the cookie isn't set yet — the browser caches the redirected
    HTML against the image URL, then renders that URL as a broken image
    on every subsequent page load even after a fresh login. See #172
    (Robert A. photo loop bug). 401 keeps the browser cache clean.
    """
    if path.startswith("/api/"):
        return True
    if path.startswith("/worker-files/"):
        return True
    if path.startswith("/project-files/"):  # gated artifacts (#248) — same #172 rule
        return True
    accept = request.headers.get("Accept", "")
    return "application/json" in accept and "text/html" not in accept


def _before_request_gate():
    # OPTIONS preflight — let CORS handle it without auth.
    if request.method == "OPTIONS":
        return None
    path = request.path
    if _is_public_path(path):
        return None
    sid = request.cookies.get(COOKIE_NAME)
    user = lookup_session(sid) if sid else None
    if not user:
        if _wants_json(path):
            return jsonify({"error": "auth required"}), 401
        # HTML route — redirect to /login with ?next= so we can bounce back post-login.
        # next is intentionally restricted to same-origin paths only (validated on login).
        return redirect(f"/login?next={path}")
    g.auth_user = user
    return None


def _login_page():
    if LOGIN_PAGE_PATH.exists():
        return send_file(str(LOGIN_PAGE_PATH))
    return ("login page missing", 500)


def _api_login():
    """POST /api/auth/login → {email, password} → sets session cookie."""
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    user = get_user_by_email(email)
    # Uniform failure response — never disclose whether email exists.
    if not user or not user.get("is_active") or not verify_password(password, user["password_hash"]):
        logging.info("auth: login failed")  # PII rule: do NOT log the email
        return jsonify({"error": "invalid credentials"}), 401
    sid = create_session(user["id"], request.headers.get("User-Agent"))
    touch_last_login(user["id"])
    logging.info(f"auth: login ok role={user['role']} sid={_redact_sid(sid)}")
    response = make_response(jsonify({
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
        }
    }))
    _set_session_cookie(response, sid)
    return response


def _api_logout():
    sid = request.cookies.get(COOKIE_NAME)
    destroy_session(sid)
    logging.info(f"auth: logout sid={_redact_sid(sid)}")
    response = make_response(jsonify({"ok": True}))
    _clear_session_cookie(response)
    return response


def _api_me():
    """GET /api/auth/me — returns the current user or 401. Used by the client shell to
    render the header name/role + decide which controls to show."""
    sid = request.cookies.get(COOKIE_NAME)
    user = lookup_session(sid) if sid else None
    if not user:
        return jsonify({"user": None}), 401
    return jsonify({"user": {
        "id": user["id"],
        "email": user["email"],
        "full_name": user["full_name"],
        "role": user["role"],
    }})


def apply_auth_gate(app) -> None:
    """Wire the before_request gate + the /login page + the /api/auth/* routes onto `app`."""
    app.before_request(_before_request_gate)
    app.add_url_rule("/login", "auth_login_page", _login_page, methods=["GET"])
    app.add_url_rule("/api/auth/login", "auth_api_login", _api_login, methods=["POST"])
    app.add_url_rule("/api/auth/logout", "auth_api_logout", _api_logout, methods=["POST"])
    app.add_url_rule("/api/auth/me", "auth_api_me", _api_me, methods=["GET"])


# ============= ROLE DECORATOR =============

def requires_role(*allowed_roles: str):
    """Per-route role gate. Use on top of the blanket before_request login gate
    for routes that need more than just "logged in" — Labor Rates + LRT rate
    columns will use @requires_role('admin', 'c_suite') when #158 lands.

    Returns 403 JSON on wrong role; the blanket gate has already enforced
    that the request is authenticated before this decorator runs.
    """
    allowed: set = set(allowed_roles)

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user()
            if not user:
                # before_request should have caught this — defense in depth.
                return jsonify({"error": "auth required"}), 401
            if user.get("role") not in allowed:
                logging.info(
                    f"auth: role denied role={user.get('role')} "
                    f"path={request.path} required={sorted(allowed)}"
                )
                return jsonify({"error": "forbidden"}), 403
            return fn(*args, **kwargs)
        return wrapper
    return decorator
