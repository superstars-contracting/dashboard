"""Smoke-test auth shim — call `_smoke_auth.setup()` to attach a logged-in
session cookie to every subsequent `requests.get/post/...` and
`urllib.request.urlopen(...)` call in the process.

Why this exists: the dashboard auth gate (#48) rejects unauthenticated
requests to `/api/*`. Existing smoke tests written before the gate use the
module-level `requests.get(...)` form (or raw urllib), not session objects
— patching every call site by hand would be 9+ files × dozens of calls of
churn. This shim does it in one place:

  1. Ensure a `smoke@superstars.local` admin user exists (idempotent, with
     a fixed password the shim knows).
  2. POST /api/auth/login to grab a session cookie.
  3. Rebind `requests.get/post/put/patch/delete` to the authenticated
     session's methods so the cookie rides along on every call.
  4. Install a urllib opener that attaches the cookie to every urlopen call.

Usage:
  - Smokes that hit an already-running server (smoke_crud_data_integrity,
    smoke_card_propagation, stress_*): call setup() right after import.
  - Smokes that launch their own server (smoke_dcr_volume,
    smoke_dcr_backdated_30day, smoke_weekly_hours): call setup() AFTER
    waiting for their server to come up, BEFORE the first HTTP call.

setup() is idempotent — safe to call multiple times. It retries the login
briefly so a small startup race against the test server doesn't false-fail.
"""
from __future__ import annotations

import os
import sqlite3
import sys
import time
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")

SMOKE_EMAIL = "smoke@superstars.local"
SMOKE_NAME = "Smoke Test Admin"
SMOKE_PASSWORD = "smoke-suite-password-please-do-not-reuse"

sys.path.insert(0, str(SCRIPT_DIR))
from auth import hash_password  # noqa: E402

_setup_done = False
_session: requests.Session | None = None

# ---- #247: response *_path guard ------------------------------------------
# When PATH_GUARD_HITS is set (the meta-smoke sets it for the whole gate),
# EVERY JSON response that flows through the patched session is scanned for
# KEY NAMES matching the filesystem-path pattern: a bare 'folder', or any key
# ending in 'path' / 'file_path' / 'filepath'. CLAUDE.md §2: files cross the
# wire via gated id-based routes ONLY — never a path. Tuned to KEYS so legit
# '*_url' fields (gated routes) don't false-positive. Hits are appended to the
# file; the meta-smoke fails the gate on any hit.
import re as _re
from urllib.parse import urlparse as _urlparse

_PATH_KEY_RE = _re.compile(r"(?i)(^|_)(file_?path|filepath|path|folder)$")


def _scan_json_for_paths(obj, route, hits, keypath=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            kp = f"{keypath}.{k}" if keypath else str(k)
            if isinstance(k, str) and _PATH_KEY_RE.search(k):
                hits.append(f"{route} :: key '{kp}'")
            _scan_json_for_paths(v, route, hits, kp)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:80]):
            _scan_json_for_paths(v, route, hits, f"{keypath}[{i}]")


def _install_path_guard(session: requests.Session) -> None:
    hits_file = os.environ.get("PATH_GUARD_HITS")
    if not hits_file:
        return

    def _hook(r, *args, **kwargs):
        try:
            if "application/json" not in (r.headers.get("Content-Type") or ""):
                return r
            if len(r.content or b"") > 2_000_000:
                return r
            data = r.json()
        except Exception:
            return r
        hits = []
        route = f"{r.request.method} {_urlparse(r.url).path}"
        _scan_json_for_paths(data, route, hits)
        if hits:
            with open(hits_file, "a", encoding="utf-8") as fh:
                for h in sorted(set(hits)):
                    fh.write(h + "\n")
        return r

    session.hooks.setdefault("response", []).append(_hook)


def _ensure_user() -> None:
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA foreign_keys=ON;")
    row = conn.execute("SELECT id FROM users WHERE email = ?", (SMOKE_EMAIL,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO users (email, password_hash, role, full_name, is_active) "
            "VALUES (?, ?, 'admin', ?, 1)",
            (SMOKE_EMAIL, hash_password(SMOKE_PASSWORD), SMOKE_NAME),
        )
    else:
        # Repair the row so the shim's known credential always works regardless
        # of what previous runs (or a future admin) did to it.
        conn.execute(
            "UPDATE users SET password_hash = ?, is_active = 1, role = 'admin', full_name = ? "
            "WHERE email = ?",
            (hash_password(SMOKE_PASSWORD), SMOKE_NAME, SMOKE_EMAIL),
        )
    conn.commit()
    conn.close()


def _login_with_retries(retries: int, delay: float) -> requests.Session:
    last_err: Exception | None = None
    for _ in range(max(1, retries)):
        try:
            s = requests.Session()
            r = s.post(
                f"{BASE}/api/auth/login",
                json={"email": SMOKE_EMAIL, "password": SMOKE_PASSWORD},
                timeout=10,
            )
            if r.status_code == 200 and s.cookies.get("ssc_session"):
                return s
            last_err = RuntimeError(f"login status={r.status_code}")
        except requests.exceptions.ConnectionError as e:
            last_err = e
        time.sleep(delay)
    raise RuntimeError(
        f"_smoke_auth: login failed against {BASE} — {last_err}. "
        "Is the server running with the auth gate?"
    )


def _patch_requests(session: requests.Session) -> None:
    requests.get = session.get
    requests.post = session.post
    requests.put = session.put
    requests.patch = session.patch
    requests.delete = session.delete
    requests.head = session.head
    requests.options = session.options
    requests.request = session.request


def _patch_urllib(session_cookie: str) -> None:
    import http.cookiejar
    import urllib.parse
    import urllib.request

    jar = http.cookiejar.CookieJar()
    host = urllib.parse.urlparse(BASE).hostname or "127.0.0.1"
    cookie = http.cookiejar.Cookie(
        version=0, name="ssc_session", value=session_cookie,
        port=None, port_specified=False,
        domain=host, domain_specified=True, domain_initial_dot=False,
        path="/", path_specified=True,
        secure=False, expires=None,
        discard=False, comment=None, comment_url=None,
        rest={}, rfc2109=False,
    )
    jar.set_cookie(cookie)
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    urllib.request.install_opener(opener)


def setup(retries: int = 10, retry_delay: float = 0.5) -> None:
    """Idempotent: seed the smoke admin user, login, patch requests+urllib."""
    global _setup_done, _session
    if _setup_done:
        return
    _ensure_user()
    _session = _login_with_retries(retries, retry_delay)
    _install_path_guard(_session)   # #247 — scan every JSON response for paths
    _patch_requests(_session)
    _patch_urllib(_session.cookies.get("ssc_session"))
    _setup_done = True
