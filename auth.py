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

import db_layer  # #259 — env-driven SQLite/Postgres layer (SQLite default)

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
LOGIN_PAGE_PATH = SCRIPT_DIR / "login.html"

COOKIE_NAME = "ssc_session"
SESSION_TTL = timedelta(hours=12)  # sliding — refreshed on each authed request

# Multi-user phase 1 (#257). Security basics built now even on Tailscale so the
# later public-exposure phase is ready (admin 2FA + public TLS/WAF are NEXT phase
# — TODO, not built here). Nothing here exposes the app publicly.
MIN_PASSWORD_LEN = 12
LOGIN_MAX_FAILS = 5                          # per-account, within the window
LOGIN_FAIL_WINDOW = timedelta(minutes=15)
SET_PASSWORD_PAGE_PATH = SCRIPT_DIR / "set_password.html"
# A must_reset_password user may reach ONLY these paths (plus the public /api/auth/*)
# until they set a real password — NO data loads behind the forced-reset screen.
_RESET_ALLOWED_EXACT = {"/set-password", "/login"}

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
    "/api/auth/",         # login, logout, me, sso/config — see below for /me caveat
    "/api/worker/",       # worker-app PIN flow — unchanged
    "/files/static/",     # vendored shell assets ONLY (css/js/fonts/vendor)
    "/auth/google/",      # #261 — Google OIDC login/callback must be reachable while
                          # logged OUT (that IS the login). When SSO is disabled (no
                          # GOOGLE_OAUTH_* env) the handlers themselves return 404.
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
    # #259 — env-driven (SSC_DB_URL). SQLite default returns the SAME native sqlite3
    # connection as before (Row, WAL, busy_timeout, foreign_keys=ON); a postgres URL
    # returns the psycopg-backed wrapper (Postgres enforces FKs natively).
    return db_layer.connect(pragma_fk=True)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _redact_sid(sid: Optional[str]) -> str:
    """Session id appearing in logs/errors — last 6 chars only, no leak of the full token."""
    if not sid:
        return "—"
    return f"…{sid[-6:]}"


# ============= AUDIT + SECURITY HELPERS (#257) =============

def _client_ip() -> Optional[str]:
    """Best-effort client IP for the audit trail. Behind Tailscale serve the real
    client rides in X-Forwarded-For; fall back to remote_addr. (IP is allowed in
    the audit per CLAUDE.md — it is not name/path PII.)"""
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        return xff.split(",")[0].strip()[:64] or None
    return (request.remote_addr or "")[:64] or None


def _login_audit(user_id: Optional[int], event: str, ip: Optional[str],
                 method: Optional[str] = None) -> None:
    """Append a login_audit row (LOCAL timestamp). NEVER records the password, the
    hash, or which non-existent email was tried (user_id is NULL when unknown).
    `method` distinguishes the login path — 'google' for SSO (#261), NULL for the
    email/password path. Auth must never fail because the audit write failed (any
    backend error — incl. a not-yet-migrated method column — is swallowed)."""
    conn = _db()
    try:
        conn.execute(
            "INSERT INTO login_audit (user_id, event, at, ip, method) VALUES (?, ?, ?, ?, ?)",
            (user_id, event, _now_iso(), ip, method),
        )
        conn.commit()
    except Exception:
        pass  # audit table/column not migrated yet — do not block auth (SQLite or PG)
    finally:
        conn.close()


def _recent_login_fails(user_id: int) -> int:
    """login_fail count for this account within the lockout window."""
    since = (datetime.now() - LOGIN_FAIL_WINDOW).isoformat(timespec="seconds")
    conn = _db()
    try:
        row = conn.execute(
            "SELECT COUNT(1) FROM login_audit WHERE user_id = ? AND event = 'login_fail' AND at >= ?",
            (user_id, since),
        ).fetchone()
        return row[0] if row else 0
    except Exception:   # not-yet-migrated table, or any backend error — fail open (no lockout)
        return 0
    finally:
        conn.close()


def password_strength_error(pw: str) -> Optional[str]:
    """Return an error string if the password is too weak, else None. Reasonable
    rule: >= MIN_PASSWORD_LEN chars with at least one letter and one digit."""
    if not isinstance(pw, str) or len(pw) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if not any(c.isalpha() for c in pw):
        return "Password must include at least one letter."
    if not any(c.isdigit() for c in pw):
        return "Password must include at least one number."
    return None


# ============= USERS =============

def get_user_by_email(email: str) -> Optional[dict]:
    if not email:
        return None
    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash, role, full_name, display_name, employee_id_link, "
            "       is_active, status, must_reset_password, created_at, last_login_at "
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
            "       u.email, u.role, u.full_name, u.display_name, u.employee_id_link, "
            "       u.is_active, u.status, u.must_reset_password "
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
        # Status is re-read from the users row on EVERY request (the session stores
        # only user_id) — so a deactivation / role change takes effect on the user's
        # very next request. A non-active user's session is destroyed so re-auth is forced.
        if row["status"] != "active" or not row["is_active"]:
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
            "display_name": row["display_name"] or row["full_name"],
            "employee_id_link": row["employee_id_link"],
            "status": row["status"],
            "must_reset_password": bool(row["must_reset_password"]),
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
    # Forced first-login reset (#257): a must_reset_password user can reach ONLY the
    # set-password screen + the public /api/auth/* endpoints. NO data loads behind it
    # — server-side, so it holds even if the client UI is bypassed.
    if user.get("must_reset_password") and path not in _RESET_ALLOWED_EXACT:
        if _wants_json(path):
            return jsonify({"error": "password reset required", "must_reset": True}), 403
        return redirect("/set-password")
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
    ip = _client_ip()
    user = get_user_by_email(email)
    # Silent per-account lockout: after N fails in the window, refuse even a correct
    # password — same generic 401, so it never discloses that the account exists.
    if user and _recent_login_fails(user["id"]) >= LOGIN_MAX_FAILS:
        _login_audit(user["id"], "login_fail", ip)
        logging.info("auth: login refused (rate-limited)")
        return jsonify({"error": "invalid credentials"}), 401
    active = bool(user) and user.get("status") == "active" and bool(user.get("is_active"))
    # Uniform failure response — never disclose whether the email exists or is disabled.
    if not user or not active or not verify_password(password, user["password_hash"]):
        if user:
            _login_audit(user["id"], "login_fail", ip)
        logging.info("auth: login failed")  # PII rule: do NOT log the email
        return jsonify({"error": "invalid credentials"}), 401
    sid = create_session(user["id"], request.headers.get("User-Agent"))
    touch_last_login(user["id"])
    _login_audit(user["id"], "login_success", ip)
    logging.info(f"auth: login ok role={user['role']} sid={_redact_sid(sid)}")
    response = make_response(jsonify({
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "display_name": user.get("display_name") or user["full_name"],
            "role": user["role"],
            "must_reset_password": bool(user.get("must_reset_password")),
        }
    }))
    _set_session_cookie(response, sid)
    return response


def _api_logout():
    sid = request.cookies.get(COOKIE_NAME)
    user = lookup_session(sid) if sid else None
    if user:
        _login_audit(user["id"], "logout", _client_ip())
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
        "display_name": user.get("display_name") or user["full_name"],
        "role": user["role"],
        "status": user.get("status"),
        "must_reset_password": bool(user.get("must_reset_password")),
    }})


def _set_password_page():
    """The forced first-login 'set your password' screen. Reached only by an
    authenticated user (the before_request gate redirects must_reset users here)."""
    if SET_PASSWORD_PAGE_PATH.exists():
        resp = send_file(str(SET_PASSWORD_PAGE_PATH))
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        return resp
    return ("set-password page missing", 500)


def _api_set_password():
    """POST /api/auth/set-password — {new_password}. The user must be authenticated
    (logged in with their temp password). Validates strength, updates the bcrypt
    hash, clears must_reset_password, audits password_set. Session stays valid so
    the client can route straight to the role home. NEVER logs the password."""
    sid = request.cookies.get(COOKIE_NAME)
    user = lookup_session(sid) if sid else None
    if not user:
        return jsonify({"error": "auth required"}), 401
    data = request.get_json(silent=True) or {}
    new_pw = data.get("new_password") or ""
    err = password_strength_error(new_pw)
    if err:
        return jsonify({"error": err}), 400
    conn = _db()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ?, must_reset_password = 0 WHERE id = ?",
            (hash_password(new_pw), user["id"]),
        )
        conn.commit()
    finally:
        conn.close()
    _login_audit(user["id"], "password_set", _client_ip())
    logging.info(f"auth: password_set user_id={user['id']}")  # PII rule: never the password
    return jsonify({"ok": True, "role": user["role"]})


def apply_auth_gate(app) -> None:
    """Wire the before_request gate + the /login page + the /api/auth/* routes onto `app`."""
    app.before_request(_before_request_gate)
    app.add_url_rule("/login", "auth_login_page", _login_page, methods=["GET"])
    app.add_url_rule("/set-password", "auth_set_password_page", _set_password_page, methods=["GET"])
    app.add_url_rule("/api/auth/login", "auth_api_login", _api_login, methods=["POST"])
    app.add_url_rule("/api/auth/logout", "auth_api_logout", _api_logout, methods=["POST"])
    app.add_url_rule("/api/auth/me", "auth_api_me", _api_me, methods=["GET"])
    app.add_url_rule("/api/auth/set-password", "auth_api_set_password", _api_set_password, methods=["POST"])


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
