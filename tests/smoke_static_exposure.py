"""
smoke_static_exposure.py — #248 static-serving exposure gate.

THE CONTRACT (allowlist by construction):
  PUBLIC (no auth):  /files/static/* vendored assets ONLY, plus the worker-app
                     PWA shell files (/worker-app-manifest.json, /worker-app-sw.js).
  GATED  (session):  /project-files/<rel> serves generated artifacts from
                     allowlisted data_room subtrees only; the authed root
                     catch-all serves only allowlisted artifact dirs/extensions.
  NEVER  (any auth): *.db / *.db-wal / *.db-shm, DB snapshots, *.py, *.md,
                     .env*, dotfiles, tests/, and any traversal escape —
                     unreachable by construction on every route.

Run BEFORE the #248 fix: MUST fail loudly (the /files/superstars.db probe
returning 200 is the catch-proof). Run AFTER: all green. Part of the gate.

Spawns its OWN isolated server on PORT (default 5151) — production 5050 is
untouched. Tree-kills it in finally (CLAUDE.md orphan rule). PII discipline:
prints status codes + byte counts only — never response bodies, never
filenames from PII-bearing trees.
"""
from __future__ import annotations

import http.client
import os
import sqlite3
import subprocess
import sys
import time
import uuid
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
VENV_PY = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"
PORT = int(os.environ.get("SMOKE_STATIC_PORT", "5151"))
BASE = f"http://127.0.0.1:{PORT}"
SRV_LOG = SCRIPT_DIR / "tests" / "_static_exposure_srv.log"

TEST_EMAIL = f"smoke-staticexp-{uuid.uuid4().hex[:8]}@example.test"
TEST_PASSWORD = "SmokeExp!" + uuid.uuid4().hex[:16]

sys.path.insert(0, str(SCRIPT_DIR))
from auth import hash_password  # noqa: E402

results: list[tuple[str, bool, str]] = []


def expect(label: str, ok: bool, detail: str = "") -> bool:
    results.append((label, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail and not ok else ""))
    return ok


# ---------- raw-path probe (requests/urllib normalize '..' client-side) ----------

def raw_get(path: str, cookie: str | None = None) -> tuple[int, int]:
    """GET with the path sent on the wire EXACTLY as given. Returns (status, body_len)."""
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    try:
        conn.putrequest("GET", path, skip_accept_encoding=True)
        conn.putheader("Host", f"127.0.0.1:{PORT}")
        conn.putheader("Accept", "*/*")
        if cookie:
            conn.putheader("Cookie", f"ssc_session={cookie}")
        conn.endheaders()
        r = conn.getresponse()
        body = r.read()
        return r.status, len(body)
    finally:
        conn.close()


# ---------- probe helpers ----------

def probe_not_servable(sess, label: str, path: str, raw: bool = False, cookie: str | None = None):
    """Assert the path does NOT serve content (any non-2xx is acceptable)."""
    if raw:
        status, blen = raw_get(path, cookie=cookie)
    else:
        r = sess.get(f"{BASE}{path}", allow_redirects=False, timeout=15)
        status, blen = r.status_code, len(r.content or b"")
    ok = not (200 <= status < 300)
    expect(label, ok, f"EXPOSED: {status}, {blen} bytes" if not ok else "")


def probe_serves(sess, label: str, path: str, min_bytes: int = 1):
    r = sess.get(f"{BASE}{path}", allow_redirects=False, timeout=15)
    ok = r.status_code == 200 and len(r.content or b"") >= min_bytes
    expect(label, ok, f"got {r.status_code}, {len(r.content or b'')} bytes")
    return r


# ---------- fixture discovery (runtime, so the smoke works before AND after the move) ----------

def newest_db_backup_rel() -> str:
    d = SCRIPT_DIR / "data_room" / "db_backups"
    if d.exists():
        cands = sorted(d.glob("*.db"))
        if cands:
            return cands[-1].relative_to(SCRIPT_DIR).as_posix()
    # Post-move state: dir empty/gone — probe the pattern path; non-200 by construction.
    return "data_room/db_backups/superstars-daily-2099-01-01.db"


def newest_artifact_rel() -> str | None:
    """A real generated artifact under an allowlisted data_room subtree."""
    for sub, pat in (("reports", "**/*.html"), ("forms", "*.pdf"),
                     ("toolbox_talks", "*.pdf"), ("signage", "*.pdf"),
                     ("credentials", "**/*.html")):
        d = SCRIPT_DIR / "data_room" / sub
        if d.exists():
            cands = sorted(p for p in d.glob(pat) if p.is_file())
            if cands:
                return cands[-1].relative_to(SCRIPT_DIR).as_posix()
    return None


def root_artifact_name() -> str | None:
    for pat in ("DCR-*.html", "WPS-*.html", "LA-*.html", "RFI-*.html",
                "rfi_submission_form.html"):
        cands = sorted(SCRIPT_DIR.glob(pat))
        if cands:
            return cands[-1].name
    return None


def a_real_font_rel() -> str | None:
    d = SCRIPT_DIR / "static" / "fonts"
    if d.exists():
        for ext in ("*.woff2", "*.woff", "*.ttf"):
            cands = sorted(d.rglob(ext))
            if cands:
                return cands[-1].relative_to(SCRIPT_DIR).as_posix()
    return None


# ---------- server lifecycle ----------

def kill_port_listeners(port: int) -> None:
    """CLAUDE.md orphan rule: tree-kill anything already listening on the port."""
    ps = (
        f"$c = Get-NetTCPConnection -LocalPort {port} -State Listen -ErrorAction SilentlyContinue; "
        "foreach ($conn in $c) { cmd /c \"taskkill /F /T /PID $($conn.OwningProcess)\" }"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30)


def start_server() -> subprocess.Popen:
    env = {**os.environ, "PORT": str(PORT)}
    logf = open(SRV_LOG, "w", encoding="utf-8")
    proc = subprocess.Popen(
        [str(VENV_PY), "server.py"], cwd=str(SCRIPT_DIR),
        stdout=logf, stderr=subprocess.STDOUT, env=env,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE}/api/health", timeout=2)
            if r.status_code == 200:
                return proc
        except requests.exceptions.ConnectionError:
            pass
        if proc.poll() is not None:
            raise RuntimeError(f"server exited rc={proc.returncode} — see {SRV_LOG.name}")
        time.sleep(0.5)
    raise RuntimeError("server did not come up in 40s")


def stop_server(proc: subprocess.Popen | None) -> None:
    if proc is None:
        return
    subprocess.run(["cmd", "/c", f"taskkill /F /T /PID {proc.pid}"],
                   capture_output=True, timeout=30)


# ---------- smoke user ----------

def seed_user() -> int:
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA foreign_keys=ON;")
    conn.execute(
        "INSERT INTO users (email, password_hash, role, full_name, is_active) "
        "VALUES (?, ?, 'admin', ?, 1)",
        (TEST_EMAIL, hash_password(TEST_PASSWORD), "Smoke Static Exposure"),
    )
    conn.commit()
    uid = conn.execute("SELECT id FROM users WHERE email = ?", (TEST_EMAIL,)).fetchone()[0]
    conn.close()
    return uid


def cleanup_user(uid: int) -> None:
    try:
        conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
        conn.execute("DELETE FROM sessions WHERE user_id = ?", (uid,))
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"warning: user cleanup failed — {e}", file=sys.stderr)


# ---------- main ----------

def main() -> int:
    print(f"smoke_static_exposure: target={BASE} (isolated instance)")
    kill_port_listeners(PORT)
    proc = None
    uid = None
    try:
        proc = start_server()
        uid = seed_user()

        anon = requests.Session()
        authed = requests.Session()
        r = authed.post(f"{BASE}/api/auth/login",
                        json={"email": TEST_EMAIL, "password": TEST_PASSWORD}, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"smoke login failed: {r.status_code}")
        sid = authed.cookies.get("ssc_session")

        backup_rel = newest_db_backup_rel()
        artifact_rel = newest_artifact_rel()
        root_art = root_artifact_name()
        font_rel = a_real_font_rel()

        # ===== 1. NEVER SERVABLE — anonymous ==================================
        print("\n-- anonymous probes that must NOT serve --")
        probe_not_servable(anon, "[anon] /files/superstars.db", "/files/superstars.db")
        probe_not_servable(anon, "[anon] /files/superstars.db-wal", "/files/superstars.db-wal")
        probe_not_servable(anon, "[anon] /files/superstars.db-shm", "/files/superstars.db-shm")
        probe_not_servable(anon, "[anon] /files/<db snapshot>", f"/files/{backup_rel}")
        probe_not_servable(anon, "[anon] /files/server.py", "/files/server.py")
        probe_not_servable(anon, "[anon] /files/auth.py", "/files/auth.py")
        probe_not_servable(anon, "[anon] /files/CLAUDE.md", "/files/CLAUDE.md")
        probe_not_servable(anon, "[anon] /files/.env", "/files/.env")
        probe_not_servable(anon, "[anon] /files/.env.template", "/files/.env.template")
        probe_not_servable(anon, "[anon] /files/.gitignore", "/files/.gitignore")
        probe_not_servable(anon, "[anon] /files/tests/smoke_auth.py", "/files/tests/smoke_auth.py")
        probe_not_servable(anon, "[anon] /files/workers_import_template.csv",
                           "/files/workers_import_template.csv")
        # Traversal — raw paths, client-side normalization bypassed.
        probe_not_servable(anon, "[anon] RAW /files/../superstars.db",
                           "/files/../superstars.db", raw=True)
        probe_not_servable(anon, "[anon] RAW /files/..%2fsuperstars.db",
                           "/files/..%2fsuperstars.db", raw=True)
        probe_not_servable(anon, "[anon] RAW /files/..%5csuperstars.db",
                           "/files/..%5csuperstars.db", raw=True)
        probe_not_servable(anon, "[anon] RAW /files/static/../server.py",
                           "/files/static/../server.py", raw=True)
        probe_not_servable(anon, "[anon] RAW /files/static/..%2f..%2fsuperstars.db",
                           "/files/static/..%2f..%2fsuperstars.db", raw=True)
        # Artifact roots require auth.
        if artifact_rel:
            r = anon.get(f"{BASE}/project-files/{artifact_rel}", allow_redirects=False, timeout=15)
            expect("[anon] /project-files/<artifact> -> 401 (not 2xx, not redirect-cached)",
                   r.status_code == 401, f"got {r.status_code}")
        probe_not_servable(anon, "[anon] /preview/ (design surface now gated)", "/preview/")
        probe_not_servable(anon, "[anon] /superstars.db (root catch-all)", "/superstars.db")
        probe_not_servable(anon, "[anon] /server.py (root catch-all)", "/server.py")

        # ===== 2. PUBLIC vendored assets — must serve =========================
        print("\n-- anonymous probes that MUST serve (vendored assets + PWA shell) --")
        rr = probe_serves(anon, "[anon] /files/static/css/widgets.css",
                          "/files/static/css/widgets.css", min_bytes=100)
        if rr.status_code == 200:
            expect("[anon] widgets.css looks like CSS", "{" in rr.text[:4000])
        probe_serves(anon, "[anon] /files/static/js/datepicker.js",
                     "/files/static/js/datepicker.js", min_bytes=100)
        probe_serves(anon, "[anon] /files/static/js/auth_menu.js",
                     "/files/static/js/auth_menu.js", min_bytes=50)
        probe_serves(anon, "[anon] /files/static/fonts/typography.css",
                     "/files/static/fonts/typography.css", min_bytes=50)
        probe_serves(anon, "[anon] /files/static/vendor/gridstack.min.css",
                     "/files/static/vendor/gridstack.min.css", min_bytes=100)
        if font_rel:
            probe_serves(anon, "[anon] real font binary under /files/static/fonts/",
                         f"/files/{font_rel}", min_bytes=1000)
        probe_serves(anon, "[anon] /worker-app-manifest.json (PWA shell)",
                     "/worker-app-manifest.json", min_bytes=50)
        probe_serves(anon, "[anon] /worker-app-sw.js (PWA shell)",
                     "/worker-app-sw.js", min_bytes=50)

        # ===== 3. Gated artifacts — authed must serve ==========================
        print("\n-- authed probes that MUST serve (gated artifacts) --")
        if artifact_rel:
            probe_serves(authed, "[authed] /project-files/<artifact>",
                         f"/project-files/{artifact_rel}", min_bytes=100)
        else:
            expect("[authed] /project-files/<artifact> (no artifact on disk — skipped)", True)
        if root_art:
            probe_serves(authed, "[authed] /<root legacy artifact> via catch-all",
                         f"/{root_art}", min_bytes=100)
        else:
            expect("[authed] root legacy artifact (none on disk — skipped)", True)

        # ===== 4. NEVER SERVABLE — even authed =================================
        print("\n-- authed probes that must NOT serve (never-servable set) --")
        probe_not_servable(authed, "[authed] /superstars.db", "/superstars.db")
        probe_not_servable(authed, "[authed] /superstars.db-wal", "/superstars.db-wal")
        probe_not_servable(authed, "[authed] /server.py", "/server.py")
        probe_not_servable(authed, "[authed] /CLAUDE.md", "/CLAUDE.md")
        probe_not_servable(authed, "[authed] /.env.template", "/.env.template")
        probe_not_servable(authed, "[authed] /tests/smoke_auth.py", "/tests/smoke_auth.py")
        probe_not_servable(authed, "[authed] /workers_import_template.csv",
                           "/workers_import_template.csv")
        probe_not_servable(authed, "[authed] /<db snapshot> via catch-all", f"/{backup_rel}")
        probe_not_servable(authed, "[authed] /files/superstars.db", "/files/superstars.db")
        probe_not_servable(authed, "[authed] /files/server.py", "/files/server.py")
        probe_not_servable(authed, "[authed] /project-files/server.py",
                           "/project-files/server.py")
        probe_not_servable(authed, "[authed] /project-files/superstars.db",
                           "/project-files/superstars.db")
        probe_not_servable(authed, "[authed] /project-files/<db snapshot>",
                           f"/project-files/{backup_rel}")
        today_log = f"data_room/server_logs/server-{time.strftime('%Y-%m-%d')}.log"
        probe_not_servable(authed, "[authed] /project-files/<server log>",
                           f"/project-files/{today_log}")
        probe_not_servable(authed, "[authed] RAW /project-files/data_room/../superstars.db",
                           "/project-files/data_room/../superstars.db", raw=True, cookie=sid)
        probe_not_servable(authed, "[authed] RAW /project-files/..%2fsuperstars.db",
                           "/project-files/..%2fsuperstars.db", raw=True, cookie=sid)
        probe_not_servable(authed, "[authed] RAW /worker-files/../server.py",
                           "/worker-files/../server.py", raw=True, cookie=sid)
        probe_not_servable(authed, "[authed] RAW /<catch-all traversal> ..%2f..%2fwindows%2fwin.ini",
                           "/..%2f..%2f..%2fwindows%2fwin.ini", raw=True, cookie=sid)

    finally:
        if uid is not None:
            cleanup_user(uid)
        stop_server(proc)
        kill_port_listeners(PORT)

    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"\n  TOTAL: {passed}/{total} {'PASS' if passed == total else 'FAIL'}")
    if passed != total:
        print("  EXPOSURE GATE FAILED — see FAIL lines above.")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
