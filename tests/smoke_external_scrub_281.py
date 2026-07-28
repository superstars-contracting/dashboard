"""#281 HARD GATE — the shell must be clean before any external role sees it.

Four scrub items, asserted rather than eyeballed. Each one is a thing that was ACTUALLY
in the served HTML, not a hypothetical:

  1. No link to an *-internal.* document anywhere in the shell. The Project Health action
     row carried /WPS-FR-BX-001-2026-05-01-INTERNAL.html on a button an external role
     would see. Both that and the lookahead link pointed at files that do not exist for
     this project, so they were dead — the danger was that generating them would silently
     turn an externally-visible button into a live internal-document link.
  2. No build stamps. Five of them carried internal changelog prose in the DOM
     ("build #271 · Project Documents · versioning (Update keeps History…)").
  3. No hard-coded project identity. "890 E 135th St", "FR-BX-001" and the client org
     name were baked into three headers, binding one file to one job and one client.
     They are filled per request from the URL now, so the SERVED page still shows them —
     the assertion is on the FILE, plus a served-page check that the fill actually works.
  4. The expenses view + its nav group are inside SECTION:financial, so they are ABSENT
     from the DOM for non-financial roles rather than CSS-hidden.

Runs against SMOKE_BASE with an isolated backend, like every other suite.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
from auth import hash_password  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SHELL = SCRIPT_DIR / "dashboard-static.html"
PW = secrets.token_urlsafe(18)
USERS = {"admin": "smk281-admin@superstars.local", "pm": "smk281-pm@superstars.local"}
PROJ = "SMK281-A"
_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return bool(cond)


# ============= 1-4 asserted against the FILE (no server needed) =============

def file_checks():
    html = SHELL.read_text(encoding="utf-8", errors="replace")
    markup = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    markup = re.sub(r"<style\b.*?</style>", "", markup, flags=re.S | re.I)

    print("\n-- 1. no internal-document links --")
    internal_links = re.findall(r'(?:href|data-link)="([^"]*-internal\.[a-z]+)"', html, re.I)
    ok("no_internal_doc_links", not internal_links, str(internal_links))
    ok("wps_button_gone", "WPS-FR-BX-001" not in html)
    ok("lookahead_button_gone", "LA-FR-BX-001" not in html)

    print("\n-- 2. no build stamps --")
    stamps = re.findall(r'id="([a-z]{2,3}-build-stamp)"', html)
    ok("no_build_stamp_elements", not stamps, str(stamps))
    ok("no_build_changelog_prose", not re.search(r"build #\d+\s*·", markup),
       "internal changelog text still in markup")

    print("\n-- 3. project identity is not baked into the file --")
    ok("no_hardcoded_project_code", "FR-BX-001" not in markup,
       str(re.findall(r"FR-BX-001", markup)[:3]))
    ok("no_hardcoded_project_name", "890 E 135th" not in markup)
    ok("no_hardcoded_client_org", "Compass Point" not in markup)
    ok("identity_placeholders_present",
       markup.count("data-project-title") >= 1 and markup.count("data-project-line") >= 2,
       "the headers must still have somewhere to render into")

    print("\n-- 4. expenses is SECTION:financial --")
    blocks = re.findall(r"<!--\s*SECTION:financial:start\s*-->(.*?)<!--\s*SECTION:financial:end\s*-->",
                        html, re.S)
    ok("financial_blocks_present", len(blocks) >= 3, f"{len(blocks)} blocks")
    joined = "\n".join(blocks)
    ok("expenses_view_inside_financial", '<section class="view" data-view="expenses"' in joined)
    ok("expenses_nav_inside_financial", 'data-view="expenses"><svg' in joined
       or 'data-view="expenses"' in joined)
    ok("product_usage_inside_financial", 'data-view="product-usage"' in joined,
       "its only entry point is the expenses group — it must not be left orphaned in the DOM")


# ============= served-page checks =============

def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        row = conn.execute("SELECT project_code FROM projects WHERE project_code=?",
                           (PROJ,)).fetchone()
        if row:
            conn.execute("UPDATE projects SET status='active', name=? WHERE project_code=?",
                         ("Smoke 281 Project", PROJ))
        else:
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                         (PROJ, "Smoke 281 Project"))
        for key, email in USERS.items():
            role = "admin" if key == "admin" else "pm"
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                conn.execute("UPDATE users SET password_hash=?, role=?, is_active=1, "
                             "status='active', must_reset_password=0, is_system=1 WHERE email=?",
                             (hash_password(PW), role, email))
                uid = u[0]
            else:
                cur = conn.execute(
                    "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                    "must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                    (email, hash_password(PW), role, f"SMK281 {key}"))
                uid = cur.lastrowid
            conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (uid,))
            if role == "pm":
                conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, "
                             "assigned_by, assigned_at) VALUES (?,?,?,?)",
                             (uid, PROJ, 1, "2026-07-27T00:00:00"))
        conn.commit()
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                uid = u[0]
                for t, c in (("login_audit", "user_id"), ("role_change_audit", "user_id"),
                             ("sessions", "user_id"), ("audit_log", "actor_user_id"),
                             ("dashboard_layouts", "user_id"), ("worker_rates", "created_by")):
                    try:
                        conn.execute(f"DELETE FROM {t} WHERE {c}=?", (uid,))
                    except Exception:
                        pass
                conn.execute("DELETE FROM pm_project_assignment WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.execute("DELETE FROM pm_project_assignment WHERE project_code=?", (PROJ,))
        conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
        conn.commit()
    finally:
        conn.close()


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if r.status_code == 200 else None


def served_checks():
    admin, pm = _login("admin"), _login("pm")
    if not ok("login_admin", admin is not None) or not ok("login_pm", pm is not None):
        return

    print("\n-- 3b. identity is FILLED server-side, per project --")
    page = admin.get(f"{BASE}/projects/{PROJ}", timeout=25).text
    ok("served_page_shows_this_project", "Smoke 281 Project" in page and PROJ in page,
       "the header must be filled from the URL, not blank")
    ok("served_page_not_other_project", "890 E 135th" not in page,
       "a different project's name must never appear")

    print("\n-- 4b. financial block is ABSENT from the DOM for a non-financial role --")
    pm_page = pm.get(f"{BASE}/projects/{PROJ}", timeout=25).text
    ok("pm_has_no_expenses_view", 'data-view="expenses"' not in pm_page,
       "expenses must be stripped, not hidden")
    ok("pm_has_no_product_usage", 'data-view="product-usage"' not in pm_page)
    ok("admin_still_has_expenses", 'data-view="expenses"' in page,
       "the financial role must NOT be over-stripped")

    print("\n-- 1b/2b. served page carries no internal artefacts for anyone --")
    for who, body in (("admin", page), ("pm", pm_page)):
        ok(f"{who}_no_internal_link", not re.search(r'"[^"]*-internal\.[a-z]+"', body))
        ok(f"{who}_no_build_changelog", not re.search(r"build #\d+\s*·", body))


def main():
    print(f"== #281 external-scrub hard gate ==  BASE={BASE}")
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    print(f"   backend={'postgres' if db_layer.is_postgres() else 'sqlite'}  "
          f"SSC_DB_URL={'(set)' if db_url else '(unset=LIVE — refuse)'}")
    file_checks()
    if not db_url and os.environ.get("ALLOW_LIVE") != "1":
        print("\n   SKIPPING served checks: SSC_DB_URL unset (would seed LIVE).")
    else:
        _seed()
        try:
            served_checks()
        finally:
            _cleanup()
    n = len(_failures)
    print(f"\n== {'ALL PASS' if n == 0 else str(n) + ' FAILED: ' + ', '.join(_failures)} ==")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
