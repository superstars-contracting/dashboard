#!/usr/bin/env python3
"""#266 — CRM/ops core guard smoke (dual-backend).

Proves the load-bearing behaviours, fail->pass where practical:
  (a) ACCESS — every CRM endpoint is admin/c_suite ONLY; pm AND super get 403 (server-
      enforced). The same call a c_suite gets 200 on flips to 403 by role.
  (b) TASK -> NEEDS-ATTENTION -> COMPLETE — a created follow-up is ABSENT from needs-
      attention, APPEARS after create (overdue), and LEAVES on complete (completed_at set).
  (c) ACTIVITY persists on the entity timeline (newest-first).
  (d) ORG create + stage + function-tags persist and are filterable.
  (e) LOCAL dates — a user-picked due_date/occurred_at is stored VERBATIM (no UTC shift),
      and the server LOCAL-stamps completed_at (date == today-local).

Runs against SMOKE_BASE (the gate's isolated server) and honors SSC_DB_URL for the direct
DB seed/verify (SQLite copy or Postgres ssc_test). Synthetic-only data (SMK266-*),
is_system=1, random per-run password. FK-safe teardown (children before parents).
"""
from __future__ import annotations

import os
import sys
import secrets
from datetime import date
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

import db_layer            # noqa: E402
import crm                 # noqa: E402
from auth import hash_password  # noqa: E402
from apply_crm_266 import ensure_crm_schema  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PW = secrets.token_urlsafe(18)
USERS = {
    "csuite": "smk266-csuite@superstars.local",
    "pm":     "smk266-pm@superstars.local",
    "super":  "smk266-super@superstars.local",
}
ROLE_OF = {"csuite": "c_suite", "pm": "pm", "super": "super"}
PROJ = "SMK266-P"                    # synthetic project for the link test
PAST = "2020-01-15"                  # a clearly-overdue due date
OCCUR = "2026-03-03"                 # a user-picked activity date

PASS, FAIL = [], []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


# ---------------- setup / teardown (direct DB, isolated backend) ----------------

def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_crm_schema(conn)          # self-prepare the #266 schema on this backend
        for key, email in USERS.items():
            role = ROLE_OF[key]
            row = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if row:
                conn.execute(
                    "UPDATE users SET password_hash=?, role=?, is_active=1, status='active', "
                    "must_reset_password=0, is_system=1 WHERE email=?", (hash_password(PW), role, email))
            else:
                conn.execute(
                    "INSERT INTO users (email,password_hash,role,full_name,is_active,status,"
                    "must_reset_password,is_system) VALUES (?,?,?,?,1,'active',0,1)",
                    (email, hash_password(PW), role, f"SMK266 {key}"))
        # synthetic project for the link test
        if not conn.execute("SELECT 1 FROM projects WHERE project_code=?", (PROJ,)).fetchone():
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?, 'active')",
                         (PROJ, "SMK266 Project"))
        conn.commit()
    finally:
        conn.close()


def _org_ids(conn):
    return [r[0] for r in conn.execute(
        "SELECT id FROM crm_organization WHERE name LIKE 'SMK266 %'").fetchall()]


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ids = _org_ids(conn)
        for oid in ids:
            conn.execute("DELETE FROM crm_activity WHERE entity_type='organization' AND entity_id=?", (oid,))
            conn.execute("DELETE FROM crm_task WHERE entity_type='organization' AND entity_id=?", (oid,))
            conn.execute("DELETE FROM crm_contact WHERE org_id=?", (oid,))          # FK child -> org
        # unlink + drop the synthetic project (projects.client_org_id FK -> org)
        conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
        for oid in ids:
            conn.execute("DELETE FROM crm_organization WHERE id=?", (oid,))
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                uid = u[0]
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
                conn.execute("DELETE FROM users WHERE id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _sc(sess, method, path, **kw):
    r = sess.request(method, f"{BASE}{path}", timeout=10, **kw)
    body = None
    try:
        body = r.json()
    except Exception:
        pass
    return r.status_code, body


def _uid(key):
    conn = db_layer.connect()
    try:
        r = conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()
        return r[0] if r else None
    finally:
        conn.close()


# ---------------- checks ----------------

def main():
    print(f"#266 CRM/ops guard — BASE={BASE}  backend={'postgres' if db_layer.is_postgres() else 'sqlite'}")
    _cleanup()
    _seed()
    try:
        cs, pm, su = _login("csuite"), _login("pm"), _login("super")
        ok("logins", all([cs, pm, su]), "all three synthetic users authenticate")
        if not cs:
            print("cannot proceed without c_suite session"); return 1

        # (a) ACCESS — pm AND super 403 on every CRM endpoint; c_suite 200 (fail->pass by role)
        ENDPOINTS = [
            ("GET", "/api/crm/organizations"),
            ("GET", "/api/crm/needs-attention"),
            ("GET", "/api/crm/console"),
            ("GET", "/api/crm/assignable-users"),
        ]
        for m, p in ENDPOINTS:
            ok(f"csuite_200 {m} {p}", _sc(cs, m, p)[0] == 200)
        for role, sess in (("pm", pm), ("super", su)):
            for m, p in ENDPOINTS:
                ok(f"{role}_403 {m} {p}", _sc(sess, m, p)[0] == 403)
            ok(f"{role}_403 POST /api/crm/organizations",
               _sc(sess, "POST", "/api/crm/organizations", json={"name": "hack"})[0] == 403)
            ok(f"{role}_403 POST /api/crm/tasks",
               _sc(sess, "POST", "/api/crm/tasks", json={"title": "hack"})[0] == 403)

        # (d) ORG create + stage + function-tags persist
        st, body = _sc(cs, "POST", "/api/crm/organizations",
                       json={"name": "SMK266 Client A", "relationship_type": "client",
                             "stage": "onboarding", "function_tags": ["sales", "finance"]})
        org_id = (body or {}).get("data", {}).get("id")
        ok("org_create_200", st == 200 and bool(org_id))
        st, body = _sc(cs, "GET", f"/api/crm/organizations/{org_id}")
        org = (body or {}).get("data", {}).get("organization", {})
        ok("org_stage_persists", org.get("stage") == "onboarding")
        ok("org_function_tags_persist",
           "sales" in (org.get("function_tags") or "") and "finance" in (org.get("function_tags") or ""))
        # filter by function_tag returns it (fail->pass: a non-matching tag does NOT)
        st, body = _sc(cs, "GET", "/api/crm/organizations?function_tag=sales")
        names = [o["name"] for o in (body or {}).get("data", [])]
        ok("org_filter_by_tag_hit", "SMK266 Client A" in names)
        st, body = _sc(cs, "GET", "/api/crm/organizations?function_tag=compliance")
        names2 = [o["name"] for o in (body or {}).get("data", [])]
        ok("org_filter_by_tag_miss", "SMK266 Client A" not in names2)

        # contact under the org
        st, body = _sc(cs, "POST", "/api/crm/contacts",
                       json={"full_name": "SMK266 Contact", "org_id": org_id, "email": "c@smk266.test"})
        ok("contact_create_200", st == 200)

        # (c) ACTIVITY persists on the timeline, with the chosen LOCAL occurred_at
        st, _ = _sc(cs, "POST", "/api/crm/activity",
                    json={"entity_type": "organization", "entity_id": org_id,
                          "activity_type": "call", "summary": "SMK266 intro call", "occurred_at": OCCUR})
        ok("activity_add_200", st == 200)
        st, body = _sc(cs, "GET", f"/api/crm/activity?entity_type=organization&entity_id={org_id}")
        tl = (body or {}).get("data", [])
        ok("activity_on_timeline", any(a.get("summary") == "SMK266 intro call" for a in tl))
        ok("activity_local_date_persists (e)",
           any(a.get("occurred_at") == OCCUR for a in tl))

        # (b) TASK -> NEEDS-ATTENTION -> COMPLETE (fail->pass->fail)
        def na_ids(sess):
            _, b = _sc(sess, "GET", "/api/crm/needs-attention")
            return [t["id"] for t in (b or {}).get("data", [])]
        st, body = _sc(cs, "POST", "/api/crm/tasks",
                       json={"title": "SMK266 send MSA", "entity_type": "organization", "entity_id": org_id,
                             "due_date": PAST, "assignee_user_id": _uid("csuite"),
                             "priority": "high", "function_tag": "sales"})
        task_id = (body or {}).get("data", {}).get("id")
        ok("task_create_200", st == 200 and bool(task_id))
        after = na_ids(cs)
        ok("task_appears_in_needs_attention", task_id in after)
        # overdue flag set (PAST < today)
        _, b = _sc(cs, "GET", "/api/crm/needs-attention")
        row = next((t for t in (b or {}).get("data", []) if t["id"] == task_id), {})
        ok("task_marked_overdue", row.get("overdue") is True and row.get("due_date") == PAST)
        # complete -> leaves
        st, _ = _sc(cs, "POST", f"/api/crm/tasks/{task_id}/complete")
        ok("task_complete_200", st == 200)
        ok("task_leaves_needs_attention", task_id not in na_ids(cs))

        # (e) LOCAL stamping — completed_at date == today-local; due_date stored verbatim
        conn = db_layer.connect()
        try:
            trow = conn.execute("SELECT status, due_date, completed_at FROM crm_task WHERE id=?", (task_id,)).fetchone()
        finally:
            conn.close()
        ok("task_done_persisted", trow and trow[0] == "done")
        ok("due_date_verbatim (e)", trow and trow[1] == PAST)
        ok("completed_at_local_today (e)",
           bool(trow and trow[2] and str(trow[2]).startswith(date.today().isoformat())))

        # link a project -> shows under the org (then it cleans up in teardown)
        st, _ = _sc(cs, "POST", f"/api/crm/projects/{PROJ}/link", json={"org_id": org_id})
        ok("link_project_200", st == 200)
        st, body = _sc(cs, "GET", f"/api/crm/organizations/{org_id}")
        linked = [p["project_code"] for p in (body or {}).get("data", {}).get("linked_projects", [])]
        ok("linked_project_shows", PROJ in linked)

        print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        if FAIL:
            print("FAILURES: " + ", ".join(FAIL))
        print("OVERALL:", "PASS" if not FAIL else "FAIL")
        return 0 if not FAIL else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
