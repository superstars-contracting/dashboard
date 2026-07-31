"""#287 GUARD — SSC_DATA_ROOT containment.

Boots its OWN waitress with SSC_DATA_ROOT pointed at a fresh SCRATCH root (the
gate's isolated SSC_DB_URL inherited), then proves:

  UPLOAD      a field-photo upload lands UNDER the scratch root, and its stored
              DB paths are RELATIVE (portable rows, #287+)
  RENDER      issuing a DCR writes html (+pdf attempt) UNDER the scratch root
  SERVE       the gated portal photo route serves the bytes back FROM the root;
              /project-files/ serves the render from the root
  WATCHDOG    NOTHING wrote outside the root during the probes: the repo-dir
              data trees' file inventory+mtimes snapshot is IDENTICAL before/
              after (the zero-leak assertion)

The UNSET-config proof is not here: it is the entire rest of the gate running
green with the variable unset — every pre-#287 suite untouched IS the
zero-change evidence.

Isolated backend REQUIRED. PII-safe: synthetic ids/counts only. 127.0.0.1 only.
"""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
import db_layer  # noqa: E402

PORT = int(os.environ.get("SMOKE_DATAROOT_PORT", "5261"))
BASE = f"http://127.0.0.1:{PORT}"
PC = "SMK287-A"
PASS, FAIL = [], []
IDS = {"users": [], "photos": []}

# repo-dir data trees the watchdog snapshots (out-of-root writes land here if
# the abstraction leaks)
WATCH_TREES = ("data_room", "worker_records")


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note and not cond else ""))
    return bool(cond)


def tree_snapshot():
    """{relpath: (size, mtime_ns)} over the repo-dir data trees. PII-safe: kept in
    memory, never printed (folder names under worker_records embed names)."""
    snap = {}
    for tree in WATCH_TREES:
        root = SCRIPT_DIR / tree
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p.is_file():
                st = p.stat()
                snap[str(p.relative_to(SCRIPT_DIR))] = (st.st_size, st.st_mtime_ns)
    return snap


def seed():
    conn = db_layer.connect()
    try:
        conn.execute("DELETE FROM projects WHERE project_code=?", (PC,))
        conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                     (PC, "Smoke 287 Root"))
        users = {}
        for key, role in (("admin", "admin"), ("cli", "client")):
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, full_name, is_active, status, "
                "must_reset_password, is_system) VALUES (?,?,?,?,1,'active',0,1)",
                (f"smk287-{key}@superstars.local", "x!unusable", role, f"SMK287 {key}"))
            users[key] = cur.lastrowid
            IDS["users"].append(cur.lastrowid)
        conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, "
                     "assigned_at) VALUES (?,?,?, '2026-07-29T00:00:00')",
                     (users["cli"], PC, users["admin"]))
        for s in ("photos", "daily"):
            conn.execute("INSERT INTO client_section_grant (user_id, project_code, section, "
                         "granted_by, granted_at) VALUES (?,?,?,?, '2026-07-29T00:00:00')",
                         (users["cli"], PC, s, users["admin"]))
        sessions = {}
        for key, uid in users.items():
            tok = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions (id, user_id, expires_at, user_agent) "
                         "VALUES (?,?, '2099-01-01T00:00:00', 'smk287')", (tok, uid))
            sessions[key] = tok
        conn.commit()
        return users, sessions
    finally:
        conn.close()


def cleanup():
    conn = db_layer.connect()
    try:
        if IDS["photos"]:
            ph = ",".join("?" * len(IDS["photos"]))
            conn.execute(f"DELETE FROM item_visibility WHERE item_type='photo' AND item_id IN ({ph})",
                         tuple(IDS["photos"]))
            conn.execute(f"DELETE FROM field_photos WHERE id IN ({ph})", tuple(IDS["photos"]))
        if IDS["users"]:
            ph = ",".join("?" * len(IDS["users"]))
            for t, c in (("client_section_grant", "user_id"), ("pm_project_assignment", "user_id"),
                         ("sessions", "user_id"), ("audit_log", "actor_user_id")):
                conn.execute(f"DELETE FROM {t} WHERE {c} IN ({ph})", tuple(IDS["users"]))
            conn.execute(f"DELETE FROM users WHERE id IN ({ph})", tuple(IDS["users"]))
        conn.execute("DELETE FROM report_index WHERE project_code=?", (PC,))
        conn.execute("DELETE FROM sign_in_log WHERE project_code=?", (PC,))
        conn.execute("DELETE FROM projects WHERE project_code=?", (PC,))
        conn.commit()
        print("  [cleanup] synthetic rows removed (scoped to SMK287 ids)")
    finally:
        conn.close()


def _make_jpeg() -> bytes:
    """A small valid JPEG, generated with the same Pillow the app uses."""
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (64, 48), (177, 30, 46)).save(buf, format="JPEG")
    return buf.getvalue()


_JPEG = _make_jpeg()


def run(scratch: Path, sessions, users):
    AD = requests.Session(); AD.cookies.set("ssc_session", sessions["admin"])
    CL = requests.Session(); CL.cookies.set("ssc_session", sessions["cli"])
    R = dict(allow_redirects=False, timeout=30)

    print("\n-- watchdog baseline over the repo-dir data trees --")
    before = tree_snapshot()
    print(f"  (snapshot: {len(before)} files watched — counts only)")

    print("\n-- UPLOAD lands under the scratch root, stored RELATIVE --")
    r = AD.post(f"{BASE}/api/projects/{PC}/photos/upload",
                files={"photos": ("smk287.jpg", _JPEG, "image/jpeg")}, timeout=30)
    ok("upload_2xx", r.status_code in (200, 201), f"{r.status_code} {r.text[:120]}")
    conn = db_layer.connect()
    try:
        row = conn.execute(
            "SELECT id, file_path, thumb_path FROM field_photos WHERE project_code=? "
            "ORDER BY id DESC LIMIT 1", (PC,)).fetchone()
        if row:
            IDS["photos"].append(row["id"])
            conn.execute("INSERT INTO item_visibility (item_type, item_id, audience, shared_by, "
                         "shared_at) VALUES ('photo', ?, 'client', ?, '2026-07-29T12:00:00')",
                         (row["id"], users["admin"]))
            conn.commit()
    finally:
        conn.close()
    ok("upload_row_exists", row is not None)
    stored_rel = row and not str(row["file_path"]).startswith(("C:", "/", "\\\\"))
    ok("stored_paths_relative", bool(stored_rel),
       "new rows must store portable relative paths")
    on_disk = row and (scratch / str(row["file_path"])).exists() \
        and (scratch / str(row["thumb_path"])).exists()
    ok("upload_bytes_under_root", bool(on_disk))

    print("\n-- gated photo serve reads FROM the root --")
    r = CL.get(f"{BASE}/api/portal/photos/{row['id']}/file", **R)
    ok("portal_photo_serve_200", r.status_code == 200, f"{r.status_code}")
    disk = (scratch / str(row["file_path"])).read_bytes() if on_disk else b""
    ok("portal_photo_bytes_from_root", r.status_code == 200 and r.content == disk,
       f"served={len(r.content)}B disk={len(disk)}B")

    print("\n-- DCR render writes under the root; /project-files serves it --")
    conn = db_layer.connect()
    try:
        conn.execute("INSERT INTO sign_in_log (date, employee_id, project_code, time_in, time_out) "
                     "SELECT '2026-07-29', employee_id, ?, '07:00', '15:30' "
                     "FROM employees LIMIT 1", (PC,))
        conn.commit()
    finally:
        conn.close()
    r = AD.post(f"{BASE}/api/projects/{PC}/daily/2026-07-29/issue",
                json={"audience": "internal", "roster_skip": True}, timeout=120)
    ok("dcr_issue_2xx", r.status_code in (200, 201), f"{r.status_code} {r.text[:150]}")
    seq = ((r.json().get("data") or {}).get("sequence") or r.json().get("sequence")) \
        if r.status_code in (200, 201) else None
    render = None
    if seq is not None:
        render = scratch / "data_room" / "reports" / "dcr" / PC / f"{int(seq):03d}" / "internal.html"
    ok("dcr_render_under_root", bool(render and render.exists()),
       str(render.relative_to(scratch)) if render else "no seq")
    repo_render = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PC
    ok("dcr_render_not_in_repo_tree", not repo_render.exists())
    if render and render.exists():
        rel = f"data_room/reports/dcr/{PC}/{int(seq):03d}/internal.html"
        r = AD.get(f"{BASE}/project-files/{rel}", **R)
        ok("project_files_serves_from_root", r.status_code == 200
           and r.content == render.read_bytes(), f"{r.status_code}")

    print("\n-- WATCHDOG: nothing wrote outside the root --")
    after = tree_snapshot()
    added = set(after) - set(before)
    removed = set(before) - set(after)
    changed = {k for k in (set(before) & set(after)) if before[k] != after[k]}
    ok("watchdog_no_out_of_root_writes",
       not added and not removed and not changed,
       f"added={len(added)} removed={len(removed)} changed={len(changed)} (names withheld)")


def check_cross_flavor_resolution():
    """#290 — resolve_data_path must parse stored WINDOWS-absolute rows on a
    POSIX host (the cloud). PosixPath('C:\\Users\\...') is neither absolute nor
    splittable on backslashes, so pre-#287 rows never re-anchored and every
    photo 404'd on Render. The parsing helper is pure (PureWindowsPath works on
    any OS), so the cross-flavor math is provable right here on Windows."""
    import ssc_paths

    win_row = r"C:\Users\SSC-Admin\Superstars\dashboard\data_room\field_photos\PC\ab12\full.jpg"
    parts, is_abs = ssc_paths._stored_parts(win_row)
    ok("290 windows row parses absolute", is_abs is True)
    ok("290 windows row splits on backslashes",
       "data_room" in parts and parts[-1] == "full.jpg")

    # a MISSING windows-absolute row re-anchors under the active root at its
    # data anchor — the exact cloud scenario (simulated via a scratch root)
    saved = os.environ.get("SSC_DATA_ROOT")
    os.environ["SSC_DATA_ROOT"] = str(Path(tempfile.gettempdir()) / "smk290_flavor_root")
    try:
        missing = r"C:\no\such\host\data_room\field_photos\PC\cd34\full.jpg"
        got = ssc_paths.resolve_data_path(missing)
        want = ssc_paths.under_root("data_room", "field_photos", "PC", "cd34", "full.jpg")
        ok("290 missing windows row re-anchors under the root", got == want,
           f"got {got}")
        rel = ssc_paths.resolve_data_path("data_room/field_photos/PC/ef56/full.jpg")
        ok("290 relative row anchors under the root",
           rel == ssc_paths.under_root("data_room", "field_photos", "PC", "ef56", "full.jpg"))
        ok("290 store_rel anchors a foreign windows row",
           ssc_paths.store_rel(missing) == "data_room/field_photos/PC/cd34/full.jpg")
    finally:
        if saved is None:
            os.environ.pop("SSC_DATA_ROOT", None)
        else:
            os.environ["SSC_DATA_ROOT"] = saved

    # no-anchor absolute rows still pass through untouched (caller containment
    # decides) — on the row's NATIVE flavor the exact old behavior
    ok("290 anchorless windows row passes through",
       str(ssc_paths.resolve_data_path(r"C:\Windows\notepad.exe")) ==
       str(Path(r"C:\Windows\notepad.exe")))


def main():
    print(f"== #287 guard: SSC_DATA_ROOT containment ==  port={PORT}")
    check_cross_flavor_resolution()
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    print(f"   backend={'postgres' if db_layer.is_postgres() else 'sqlite'}  "
          f"SSC_DB_URL={'(set)' if db_url else '(unset)'}")
    if not db_url and os.environ.get("ALLOW_LIVE") != "1":
        print("REFUSING TO RUN: SSC_DB_URL is unset — this suite seeds rows and issues "
              "a DCR and must never touch the live DB.")
        return 2
    scratch = Path(tempfile.mkdtemp(prefix="ssc_root_287_"))
    env = {**os.environ, "SSC_DATA_ROOT": str(scratch)}
    logf = open(SCRIPT_DIR / "tests" / "_287_srv.log", "w", encoding="utf-8")
    srv = subprocess.Popen(
        [str(SCRIPT_DIR / "venv" / "Scripts" / "python.exe"), "-m", "waitress",
         f"--host=127.0.0.1", f"--port={PORT}", "--threads=6", "server:app"],
        cwd=str(SCRIPT_DIR), stdout=logf, stderr=subprocess.STDOUT, env=env)
    try:
        deadline = time.time() + 45
        up = False
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{BASE}/api/health", timeout=2) as r:
                    if r.status == 200:
                        up = True
                        break
            except Exception:
                time.sleep(0.5)
        if not up:
            print("rooted test server did not come up; see tests/_287_srv.log")
            return 2
        users, sessions = seed()
        try:
            run(scratch, sessions, users)
        finally:
            cleanup()
    finally:
        subprocess.run(["cmd", "/c", f"taskkill /F /T /PID {srv.pid}"], capture_output=True)
        logf.close()
        shutil.rmtree(scratch, ignore_errors=True)
    print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
