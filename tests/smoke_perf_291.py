"""#291 guard — the bootstrap aggregates are MIRRORS, never doors.

Proves, against the shared gate server:
  1. PARITY (admin): every key the console + project bootstraps return is
     deep-equal to the payload of the individual endpoint it mirrors, same
     request args. An aggregate that drifts from its endpoints goes red.
  2. ADMITS NOTHING NEW (pm): the project bootstrap's key set for a pm is a
     subset of the endpoints that pm can fetch individually (200s); the
     console bootstrap refuses a pm outright (company-only page, #263).
  3. CONTAINMENT (client): both aggregates 403 for a client session — the
     client gate fires before any aggregate code runs.
  4. THUMB CACHING (#291.3): /api/field-photos/<id>/thumb + /file carry
     exactly 'private, max-age=31536000, immutable' (private = Cloudflare's
     shared cache must never hold an auth-gated photo; browser-only), and
     the routes still 401 anonymously — headers never weakened auth.
  5. NO PATH KEYS: aggregate payloads contain no filesystem-path-shaped keys
     (CLAUDE.md files-cross-by-id rule), recursively.
  6. LAZY GRID (source-level): the field-photos + DCR photo tiles carry
     loading="lazy" in dashboard-static.html.

Isolated backend required (SSC_DB_URL); PII-safe output.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
import uuid
from datetime import date
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))
import db_layer  # noqa: E402
import ssc_paths  # noqa: E402
from auth import hash_password  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5434")
PROJECT = "FR-BX-001"
PW = secrets.token_urlsafe(16)
EMAILS = {"pm": "smk291-pm@superstars.local", "client": "smk291-client@superstars.local"}

PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note and not cond else ""))
    return bool(cond)


def seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ids = {}
        for key, email in EMAILS.items():
            role = "pm" if key == "pm" else "client"
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute("UPDATE users SET password_hash=?, role=?, is_active=1, "
                             "status='active', must_reset_password=0, is_system=1 WHERE id=?",
                             (hash_password(PW), role, row[0]))
                ids[key] = row[0]
            else:
                conn.execute("INSERT INTO users (email,password_hash,role,full_name,is_active,"
                             "status,must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                             (email, hash_password(PW), role, f"SMK291 {key}"))
                ids[key] = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()[0]
            conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (ids[key],))
            conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, "
                         "assigned_at) VALUES (?,?,?,?)", (ids[key], PROJECT, ids[key],
                                                           "2026-08-02T00:00:00"))
        # a synthetic photo row + real bytes under the ACTIVE data root
        pdir = ssc_paths.under_root("data_room", "field_photos", PROJECT, "smk291-" + uuid.uuid4().hex[:8])
        pdir.mkdir(parents=True, exist_ok=True)
        full, thumb = pdir / "full.jpg", pdir / "thumb.jpg"
        jpg = b"\xff\xd8\xff\xe0" + b"\x00" * 400 + b"\xff\xd9"
        full.write_bytes(jpg)
        thumb.write_bytes(jpg)
        cur = conn.execute(
            "INSERT INTO field_photos (project_code, uploaded_at, file_path, thumb_path, mime) "
            "VALUES (?,?,?,?,?)",
            (PROJECT, "2026-08-02T00:00:00", ssc_paths.store_rel(full),
             ssc_paths.store_rel(thumb), "image/jpeg"))
        pid = cur.lastrowid or conn.execute(
            "SELECT MAX(id) FROM field_photos WHERE project_code=?", (PROJECT,)).fetchone()[0]
        conn.commit()
        ids["photo"] = pid
        ids["pdir"] = pdir
        return ids
    finally:
        conn.close()


def cleanup(ids):
    conn = db_layer.connect(pragma_fk=True)
    try:
        if ids.get("photo"):
            conn.execute("DELETE FROM field_photos WHERE id=?", (ids["photo"],))
        for key in EMAILS:
            uid = ids.get(key)
            if not uid:
                continue
            for sql in ("DELETE FROM client_section_grant WHERE user_id=?",
                        "DELETE FROM pm_project_assignment WHERE user_id=?",
                        "DELETE FROM sessions WHERE user_id=?",
                        "DELETE FROM login_audit WHERE user_id=?",
                        "DELETE FROM users WHERE id=?"):
                try:
                    conn.execute(sql, (uid,))
                    conn.commit()
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
        conn.commit()
    finally:
        conn.close()
    try:
        import shutil
        shutil.rmtree(ids.get("pdir"), ignore_errors=True)
    except Exception:
        pass


def login(email, pw):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": email, "password": pw}, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"login {email.split('@')[0]} -> {r.status_code}")
    return s


PATH_KEY_RE = re.compile(r"(?i)(^|_)(file_?path|filepath|path|folder)$")


def path_keys(obj, hits, kp=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and PATH_KEY_RE.search(k):
                hits.append(f"{kp}.{k}")
            path_keys(v, hits, f"{kp}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            path_keys(v, hits, f"{kp}[{i}]")


def main() -> int:
    print("== #291 guard: bootstrap aggregates + thumb caching ==")
    import _smoke_auth
    _smoke_auth.setup()
    admin = requests  # patched session

    ids = seed()
    try:
        t = date.today().isoformat()
        CONSOLE_PARTS = {
            "summary": "/api/company/summary",
            "projects": "/api/projects",
            "compliance": "/api/compliance/summary",
            "activity": "/api/activity/recent?limit=12",
            "material_alerts": "/api/company/material-alerts",
            "rollup": f"/api/dropplan/projects/{PROJECT}/rollup",
            "drops": f"/api/dropplan/projects/{PROJECT}/drops",
            "on_site": f"/api/projects/{PROJECT}/on-site?date={t}",
        }
        PROJ_PARTS = {
            "rollup": f"/api/dropplan/projects/{PROJECT}/rollup",
            "drops": f"/api/dropplan/projects/{PROJECT}/drops",
            "on_site": f"/api/projects/{PROJECT}/on-site?date={t}",
            "workers": f"/api/projects/{PROJECT}/workers",
        }

        # ---- 1. PARITY (admin) ----
        for name, agg_url, parts in (
            ("console", f"/api/console/bootstrap?project={PROJECT}&date={t}&limit=12", CONSOLE_PARTS),
            ("project", f"/api/projects/{PROJECT}/bootstrap?date={t}", PROJ_PARTS),
        ):
            r = admin.get(f"{BASE}{agg_url}", timeout=30)
            ok(f"{name}_bootstrap_200", r.status_code == 200, f"{r.status_code}")
            agg = (r.json().get("data") or {}) if r.status_code == 200 else {}
            ok(f"{name}_bootstrap_has_all_parts", set(parts) <= set(agg.keys()),
               f"missing {set(parts) - set(agg.keys())}")
            for k, url in parts.items():
                ri = admin.get(f"{BASE}{url}", timeout=30)
                ind = (ri.json() or {}).get("data") if ri.status_code == 200 else None
                same = (k in agg) and (agg[k] == ind)
                ok(f"{name}_parity_{k}", same,
                   f"individual={ri.status_code}")
            hits = []
            path_keys(agg, hits)
            ok(f"{name}_no_path_keys", not hits, str(hits[:4]))

        # ---- 2. pm: subset discipline + console refusal ----
        pm = login(EMAILS["pm"], PW)
        r = pm.get(f"{BASE}/api/console/bootstrap", timeout=15)
        ok("console_bootstrap_pm_403", r.status_code == 403, f"{r.status_code}")
        r = pm.get(f"{BASE}/api/projects/{PROJECT}/bootstrap?date={t}", timeout=30)
        ok("project_bootstrap_pm_200", r.status_code == 200, f"{r.status_code}")
        pm_agg = (r.json().get("data") or {}) if r.status_code == 200 else {}
        allowed = set()
        for k, url in PROJ_PARTS.items():
            if pm.get(f"{BASE}{url}", timeout=30).status_code == 200:
                allowed.add(k)
        ok("project_bootstrap_pm_subset", set(pm_agg.keys()) <= allowed,
           f"agg={sorted(pm_agg)} allowed={sorted(allowed)}")

        # ---- 3. client containment ----
        cl = login(EMAILS["client"], PW)
        for url in (f"/api/console/bootstrap", f"/api/projects/{PROJECT}/bootstrap"):
            r = cl.get(f"{BASE}{url}", timeout=15)
            ok(f"client_403_{url.split('/')[2]}", r.status_code == 403, f"{r.status_code}")

        # ---- 4. thumb/file cache headers + auth intact ----
        WANT = "private, max-age=31536000, immutable"
        for col in ("thumb", "file"):
            r = admin.get(f"{BASE}/api/field-photos/{ids['photo']}/{col}", timeout=15)
            ok(f"photo_{col}_200", r.status_code == 200, f"{r.status_code}")
            ok(f"photo_{col}_cache_control", r.headers.get("Cache-Control") == WANT,
               f"got {r.headers.get('Cache-Control')!r}")
        anon = requests.Session()
        r = anon.get(f"{BASE}/api/field-photos/{ids['photo']}/thumb", timeout=15)
        ok("photo_thumb_anon_401", r.status_code == 401, f"{r.status_code}")

        # ---- 5. lazy grid (source-level) ----
        src = (SCRIPT_DIR / "dashboard-static.html").read_text(encoding="utf-8", errors="replace")
        fp_lazy = src.count("<img loading=\"lazy\"") + src.count("'<img loading=\"lazy\"")
        ok("grid_imgs_lazy", "thumb_url" in src and
           re.search(r"""<img loading="lazy"[^>]*'\s*\+\s*esc\(p\.thumb_url\)""", src) is not None)
        ok("dcr_tile_lazy", 'loading="lazy" decoding="async" src=\'' in src.replace('" + ', "' + ")
           or "loading=\"lazy\" decoding=\"async\"" in src)

        print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        return 0 if not FAIL else 1
    finally:
        cleanup(ids)


if __name__ == "__main__":
    sys.exit(main())
