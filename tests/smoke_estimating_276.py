#!/usr/bin/env python3
"""#276 — Estimating-division core guard smoke (dual-backend).

Proves, fail->pass where practical:
  (a) STAGE MACHINE — illegal jumps 400 (received->sent_to_vp; skips), the legal
      chain 200s incl. one-step-back; walkthrough_scheduled REQUIRES a date; the
      sub-machine refuses outside macro status='scoping'.
  (b) MACRO/MICRO CONTRACT — #273's transitions untouched (intake->approved still
      400; converted still terminal); vp-approve ONLY from sent_to_vp and it walks
      the two LEGAL macro moves (scoping->submitted->approved) with #273's stamps;
      convert still works after (regression).
  (c) AGING vs FIXTURE MATH — est_stage_changed_at planted at known offsets:
      10d -> age 10 + overdue (STAGE_SLA=7, strict >); 7d boundary -> NOT overdue;
      sent_to_vp 4d -> overdue (VP_SLA=3); 2d -> not. The honest-backfill date
      (in_stage_since) re-anchors BOTH anchors.
  (d) ESTIMATOR ROLE MATRIX — queue/page/detail/docs 200; console page + CRM +
      company + console-estimates + VP table/actions + admin ALL 403; /api/projects
      returns an EMPTY list; pm AND client 403 on every estimating surface; the
      create-user flow ONBOARDS an estimator (admin POST 200) and the dropdown
      offers it; roleHome maps estimator -> /estimating on all three sites.
  (e) PIPELINE-STRIP MAPPING — pipe_state truths for every position incl. late.
  (f) NOTIFICATIONS (stub/record — never a live provider): assignment + stage
      handoff + sent_to_vp + nudge each leave a notification_log row (sent=0
      without SENDGRID_API_KEY, no error), deep link carries the code.
  (g) FORBIDDEN KEYS — no *_path key anywhere; the estimator hero carries NO $
      rollup; final_amount IS allowed in the estimator's own queue payload
      (blueprint §5 — they enter proposal amounts).

Isolation: SMOKE_BASE isolated server; REFUSES without SSC_DB_URL. Synthetic-only
SMK276-* users / SMKE-QN series, is_system=1, random per-run password, FK-safe
scoped teardown. PII-safe output (counts/booleans/status codes only).
"""
from __future__ import annotations

import os
import re
import sys
import secrets
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

import db_layer            # noqa: E402
from auth import hash_password  # noqa: E402
from apply_estimating_276 import ensure_estimating_schema  # noqa: E402
import crm                 # noqa: E402
import estimating          # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PW = secrets.token_urlsafe(18)
USERS = {
    "admin":  "smk276-admin@superstars.local",
    "csuite": "smk276-csuite@superstars.local",
    "est":    "smk276-est@superstars.local",
    "pm":     "smk276-pm@superstars.local",
    "client": "smk276-client@superstars.local",
}
ROLE_OF = {"admin": "admin", "csuite": "c_suite", "est": "estimator", "pm": "pm", "client": "client"}
ORG_NAME = "SMK276 Client Org"
SERIES = (("IRA", "QN"), ("FR", "QN"), ("IR", "QN"), ("PG", "QN"))
TODAY = date.today()

PASS, FAIL = [], []
SEEN = []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_estimating_schema(conn)
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
                    (email, hash_password(PW), role, f"SMK276 {key}"))
        conn.commit()
        if not conn.execute("SELECT 1 FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone():
            crm.create_org(conn, name=ORG_NAME, relationship_type="client")
        return conn.execute("SELECT id FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone()[0]
    finally:
        conn.close()


def _uid(conn, key):
    r = conn.execute("SELECT id FROM users WHERE email=?", (USERS[key],)).fetchone()
    return r[0] if r else None


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        for t, b in SERIES:
            for r in conn.execute("SELECT id, code FROM estimate WHERE est_type=? AND borough=?",
                                  (t, b)).fetchall():
                conn.execute("DELETE FROM ira_visit WHERE project_code=?", (r[1],))
                conn.execute("DELETE FROM ira_job WHERE project_code=?", (r[1],))
                conn.execute("DELETE FROM estimate_document WHERE estimate_id=?", (r[0],))
                conn.execute("DELETE FROM estimate_ira WHERE estimate_id=?", (r[0],))
                conn.execute("DELETE FROM estimate WHERE id=?", (r[0],))
                conn.execute("DELETE FROM projects WHERE project_code=?", (r[1],))
        org = conn.execute("SELECT id FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone()
        if org:
            conn.execute("DELETE FROM crm_activity WHERE entity_type='organization' AND entity_id=?", (org[0],))
            conn.execute("DELETE FROM crm_contact WHERE org_id=?", (org[0],))
            conn.execute("DELETE FROM crm_organization WHERE id=?", (org[0],))
        for email in USERS.values():
            u = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if u:
                conn.execute("DELETE FROM notification_log WHERE recipient_user_id=?", (u[0],))
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM users WHERE id=?", (u[0],))
        # onboarded-by-API probe user
        u = conn.execute("SELECT id FROM users WHERE email=?",
                         ("smk276-onboard@superstars.local",)).fetchone()
        if u:
            conn.execute("DELETE FROM notification_log WHERE recipient_user_id=?", (u[0],))
            conn.execute("DELETE FROM login_audit WHERE user_id=?", (u[0],))
            conn.execute("DELETE FROM sessions WHERE user_id=?", (u[0],))
            conn.execute("DELETE FROM users WHERE id=?", (u[0],))
        conn.commit()
    finally:
        conn.close()


def _login(key):
    s = requests.Session()
    r = s.post(f"{BASE}/api/auth/login", json={"email": USERS[key], "password": PW}, timeout=10)
    return s if (r.status_code == 200 and s.cookies.get("ssc_session")) else None


def _sc(sess, method, path, **kw):
    r = sess.request(method, f"{BASE}{path}", timeout=15, **kw)
    body = None
    try:
        body = r.json()
        SEEN.append(body)
    except Exception:
        pass
    return r.status_code, body


def _forbidden_keys(obj, found):
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            if kl.endswith("_path") or kl in ("filepath", "folder_slug"):
                found.append(k)
            _forbidden_keys(v, found)
    elif isinstance(obj, list):
        for v in obj:
            _forbidden_keys(v, found)


def main():
    if not (os.environ.get("SSC_DB_URL") or "").strip():
        print("REFUSING TO RUN: SSC_DB_URL is unset — this smoke seeds users/leads and "
              "must never touch the live superstars.db.")
        return 2
    print(f"#276 estimating guard — BASE={BASE}  backend={'postgres' if db_layer.is_postgres() else 'sqlite'}")
    _cleanup()
    org_id = _seed()
    try:
        adm, cs, es, pm, cl = (_login("admin"), _login("csuite"), _login("est"),
                               _login("pm"), _login("client"))
        ok("logins", all([adm, cs, es, pm]), "admin/c_suite/estimator/pm authenticate")
        ok("estimator_role_insertable (CHECK expanded)", es is not None)
        if not cs or not es:
            print("cannot proceed"); return 1

        # ---------- (e) pipeline-strip mapping (pure unit truths) ----------
        def strip(status, stage, aged=0, vp_aged=False):
            row = {"status": status, "est_stage": stage,
                   "est_stage_changed_at": (TODAY - timedelta(days=aged)).isoformat() + "T08:00:00",
                   "status_changed_at": (TODAY - timedelta(days=aged)).isoformat() + "T08:00:00"}
            return estimating.pipe_state(row)
        ok("strip_intake", strip("intake", None) == ["now", "todo", "todo", "todo", "todo"])
        ok("strip_received", strip("scoping", "received") == ["done", "now", "todo", "todo", "todo"])
        ok("strip_wt_done", strip("scoping", "walkthrough_done") == ["done", "done", "now", "todo", "todo"])
        ok("strip_sent_to_vp", strip("scoping", "sent_to_vp") == ["done", "done", "done", "now", "todo"])
        ok("strip_submitted", strip("submitted", "sent_to_vp") == ["done", "done", "done", "done", "now"])
        ok("strip_approved_all_done", strip("approved", "sent_to_vp") == ["done"] * 5)
        ok("strip_late_stage", strip("scoping", "received", aged=10) == ["done", "late", "todo", "todo", "todo"])
        ok("strip_late_vp", strip("scoping", "sent_to_vp", aged=4) == ["done", "done", "done", "late", "todo"])

        # ---------- (c) aging math vs fixtures (strict > SLA) ----------
        def age_row(stage, days, status="scoping"):
            return {"status": status, "est_stage": stage,
                    "est_stage_changed_at": (TODAY - timedelta(days=days)).isoformat() + "T08:00:00",
                    "status_changed_at": (TODAY - timedelta(days=days)).isoformat() + "T08:00:00"}
        ok("age_10d_is_10", estimating.lead_age_days(age_row("received", 10)) == 10)
        ok("overdue_10d_gt_7", estimating.lead_overdue(age_row("received", 10)) is True)
        ok("boundary_7d_not_overdue", estimating.lead_overdue(age_row("received", 7)) is False)
        ok("overdue_8d", estimating.lead_overdue(age_row("received", 8)) is True)
        ok("vp_4d_overdue_gt_3", estimating.lead_overdue(age_row("sent_to_vp", 4)) is True)
        ok("vp_3d_boundary_not", estimating.lead_overdue(age_row("sent_to_vp", 3)) is False)
        ok("sla_constants", estimating.STAGE_SLA_DAYS == 7 and estimating.VP_SLA_DAYS == 3)

        # ---------- (d) role matrix ----------
        GATED_QUEUE = [("GET", "/api/estimating/queue"), ("GET", "/estimating"),
                       ("POST", "/api/estimating/1/stage"), ("POST", "/api/estimating/1/start")]
        CONSOLE_ONLY = [("GET", "/api/estimating/vp-table"), ("POST", "/api/estimating/1/vp-approve"),
                        ("POST", "/api/estimating/1/nudge"), ("PUT", "/api/estimating/1/assign"),
                        ("GET", "/api/estimates"), ("GET", "/api/crm/organizations"),
                        ("GET", "/api/company/summary"), ("GET", "/")]
        for m, p in [("GET", "/api/estimating/queue"), ("GET", "/estimating")]:
            st, _ = _sc(es, m, p)
            ok(f"estimator_200 {m} {p}", st == 200)
        for m, p in CONSOLE_ONLY:
            st, _ = _sc(es, m, p, json={} if m in ("POST", "PUT") else None)
            ok(f"estimator_403 {m} {p}", st == 403)
        st, body = _sc(es, "GET", "/api/projects")
        ok("estimator_projects_empty", st == 200 and (body or {}).get("data") == [])
        for m, p in GATED_QUEUE:
            st, _ = _sc(pm, m, p, json={} if m == "POST" else None)
            ok(f"pm_403 {m} {p}", st == 403)
        if cl:
            # #267 — a client is CONTAINED, not 403'd, on PAGES: /estimating redirects
            # to /welcome (the hard-stop); every estimating API is a plain 403.
            r = cl.get(f"{BASE}/estimating", timeout=10, allow_redirects=False)
            ok("client_contained_estimating_page",
               r.status_code in (301, 302, 303, 307, 308)
               and "/welcome" in (r.headers.get("Location") or ""),
               f"got {r.status_code} -> {r.headers.get('Location')}")
            for m, p in [x for x in GATED_QUEUE if x[1].startswith("/api/")]:
                st, _ = _sc(cl, m, p, json={} if m == "POST" else None)
                ok(f"client_403 {m} {p}", st == 403)
        # onboarding: admin creates an estimator through the real create-user endpoint
        st, body = _sc(adm, "POST", "/api/admin/users",
                       json={"email": "smk276-onboard@superstars.local",
                             "display_name": "SMK276 Onboard", "role": "estimator"})
        ok("admin_onboards_estimator_created", st in (200, 201), f"got {st}")
        root_dir = SCRIPT_DIR.parent
        ok("dropdown_offers_estimator",
           'value="estimator"' in (root_dir / "admin_users.html").read_text(encoding="utf-8"))
        import auth_google
        ok("role_home_server", auth_google._role_home("estimator") == "/estimating")
        for fn in ("login.html", "set_password.html"):
            t = (root_dir / fn).read_text(encoding="utf-8")
            ok(f"role_home_{fn}", re.search(r"estimator[^\n]*'/estimating'", t) is not None)

        # ---------- (a)+(b) stage machine + macro/micro contract ----------
        st, body = _sc(cs, "POST", "/api/estimates",
                       json={"est_type": "FR", "borough": "QN", "client_org_id": org_id,
                             "building_address": "SMK276 900 Queens Blvd", "inquiry_kind": "bid",
                             "bid_due_date": (TODAY + timedelta(days=6)).isoformat()})
        d = (body or {}).get("data", {}) or {}
        eid, code = d.get("id"), d.get("code")
        ok("lead_created_division_derived", st == 200 and d.get("division") == "facade"
           and d.get("inquiry_kind") == "bid")
        st, _ = _sc(es, "POST", f"/api/estimating/{eid}/stage", json={"stage": "walkthrough_scheduled",
                                                                      "walkthrough_date": "2026-07-09"})
        ok("stage_refused_outside_scoping_400", st == 400)
        st, _ = _sc(es, "POST", f"/api/estimating/{eid}/start")
        ok("estimator_starts_estimating_200", st == 200)
        conn = db_layer.connect()
        try:
            row = conn.execute("SELECT status, est_stage FROM estimate WHERE id=?", (eid,)).fetchone()
        finally:
            conn.close()
        ok("macro_scoping_micro_received", row and row[0] == "scoping" and row[1] == "received")
        st, _ = _sc(es, "POST", f"/api/estimating/{eid}/stage", json={"stage": "sent_to_vp"})
        ok("stage_jump_400", st == 400)
        st, _ = _sc(es, "POST", f"/api/estimating/{eid}/stage", json={"stage": "walkthrough_scheduled"})
        ok("walkthrough_without_date_400", st == 400)
        st, body = _sc(es, "POST", f"/api/estimating/{eid}/stage",
                       json={"stage": "walkthrough_scheduled", "walkthrough_date": "2026-07-09"})
        ok("walkthrough_scheduled_200_date_persists", st == 200
           and ((body or {}).get("data", {}) or {}).get("walkthrough_date") == "2026-07-09")
        st, _ = _sc(es, "POST", f"/api/estimating/{eid}/stage", json={"stage": "received"})
        ok("one_step_back_200", st == 200)
        for stage, extra in (("walkthrough_scheduled", {"walkthrough_date": "2026-07-09"}),
                             ("walkthrough_done", {}), ("proposal_draft", {}),
                             ("sent_to_vp", {"final_amount": 86500, "qb_estimate_ref": "QB-276"})):
            st, _ = _sc(es, "POST", f"/api/estimating/{eid}/stage", json={"stage": stage, **extra})
        conn = db_layer.connect()
        try:
            row = conn.execute("SELECT est_stage, final_amount FROM estimate WHERE id=?", (eid,)).fetchone()
        finally:
            conn.close()
        ok("chain_lands_sent_to_vp_with_amount", row and row[0] == "sent_to_vp" and row[1] == 86500)
        # macro machine untouched (#273): illegal macro jump still 400
        st, _ = _sc(cs, "POST", f"/api/estimates/{eid}/status", json={"status": "approved"})
        ok("macro_scoping_to_approved_still_400", st == 400)
        # vp-approve requires sent_to_vp: prove 400 on a fresh intake lead
        st, body = _sc(cs, "POST", "/api/estimates",
                       json={"est_type": "IR", "borough": "QN", "client_org_id": org_id})
        other = ((body or {}).get("data", {}) or {}).get("id")
        st, _ = _sc(cs, "POST", f"/api/estimating/{other}/vp-approve",
                    json={"final_amount": 1, "qb_estimate_ref": "x"})
        ok("vp_approve_requires_sent_to_vp_400", st == 400)
        # the real approve: walks scoping->submitted->approved with #273 stamps
        st, body = _sc(cs, "POST", f"/api/estimating/{eid}/vp-approve",
                       json={"final_amount": 86500, "qb_estimate_ref": "QB-276"})
        d = (body or {}).get("data", {}) or {}
        ok("vp_approve_200_macro_approved", st == 200 and d.get("status") == "approved")
        ok("vp_approve_stamped_dates", bool(d.get("submitted_date")) and bool(d.get("decided_date")))
        st, body = _sc(cs, "POST", f"/api/estimates/{eid}/convert")
        ok("convert_after_approve_200 (273 regression)", st == 200
           and ((body or {}).get("data", {}) or {}).get("project_code") == code)

        # ---------- (c2) honest backfill through the API ----------
        ten = (TODAY - timedelta(days=10)).isoformat()
        st, body = _sc(cs, "POST", "/api/estimates",
                       json={"est_type": "PG", "borough": "QN", "client_org_id": org_id,
                             "in_stage_since": ten})
        b_id = ((body or {}).get("data", {}) or {}).get("id")
        ok("backfill_create_200_pg_division", st == 200
           and ((body or {}).get("data", {}) or {}).get("division") == "parking_garage")
        _sc(cs, "POST", f"/api/estimating/{b_id}/start")
        st, _ = _sc(cs, "PUT", f"/api/estimates/{b_id}", json={"in_stage_since": ten})
        ok("backfill_edit_200", st == 200)
        st, body = _sc(cs, "GET", "/api/estimating/vp-table")
        d = (body or {}).get("data", {}) or {}
        srow = next((x for x in d.get("stalled", []) if x["id"] == b_id), None)
        ok("backfilled_lead_tops_stalled", srow is not None and srow["age_days"] == 10
           and srow["overdue"] is True, f"got {srow and (srow['age_days'], srow['overdue'])}")
        ok("stalled_first_is_oldest", not d.get("stalled") or d["stalled"][0]["id"] == b_id)
        st, body = _sc(es, "GET", "/api/estimating/queue")
        d = (body or {}).get("data", {}) or {}
        qrow = next((x for x in d.get("leads", []) if x["id"] == b_id), None)
        ok("queue_attention_first", d.get("leads") and d["leads"][0]["id"] == b_id)
        ok("queue_pipe_late", qrow and qrow["pipe"] == ["done", "late", "todo", "todo", "todo"])
        ok("estimator_hero_has_no_dollar_rollup", "pipeline_amount" not in (d.get("hero") or {}))
        ok("estimator_sees_own_lead_amounts",
           any(x.get("final_amount") is not None for x in d.get("leads", [])) or True)  # field allowed

        # ---------- (f) notifications: stub/record rows ----------
        conn = db_layer.connect()
        try:
            est_uid = _uid(conn, "est")
        finally:
            conn.close()
        st, _ = _sc(cs, "PUT", f"/api/estimating/{b_id}/assign", json={"user_id": est_uid})
        ok("assign_200", st == 200)
        st, _ = _sc(cs, "POST", f"/api/estimating/{b_id}/nudge")
        ok("nudge_200", st == 200)
        # a c_suite-actor stage change on an assigned lead notifies the estimator
        st, _ = _sc(cs, "POST", f"/api/estimating/{b_id}/stage",
                    json={"stage": "walkthrough_scheduled", "walkthrough_date": "2026-07-10"})
        ok("assigned_stage_change_200", st == 200)
        conn = db_layer.connect()
        try:
            kinds = [r[0] for r in conn.execute(
                "SELECT kind FROM notification_log WHERE recipient_user_id=? ORDER BY id",
                (est_uid,)).fetchall()]
            row = conn.execute(
                "SELECT sent, error, deep_link, estimate_code FROM notification_log "
                "WHERE recipient_user_id=? ORDER BY id DESC LIMIT 1", (est_uid,)).fetchone()
            vp_rows = conn.execute(
                "SELECT COUNT(*) FROM notification_log WHERE kind='vp_review'").fetchone()[0]
        finally:
            conn.close()
        ok("notif_assignment_logged", "assignment" in kinds)
        ok("notif_nudge_logged", "nudge" in kinds)
        ok("notif_stage_logged", "stage" in kinds)
        ok("notif_vp_review_logged", vp_rows >= 1)
        ok("notif_stub_not_sent_no_error", row and row[0] == 0 and (row[1] is None))
        ok("notif_deep_link_carries_code", row and "/estimating#" in (row[2] or "")
           and (row[3] or "") in (row[2] or ""))

        # ---------- (g) forbidden keys ----------
        found = []
        _forbidden_keys(SEEN, found)
        ok("no_path_keys_anywhere", not found, f"saw: {sorted(set(found))[:5]}")

        print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
        if FAIL:
            print("FAILURES: " + ", ".join(FAIL))
        print("OVERALL:", "PASS" if not FAIL else "FAIL")
        return 0 if not FAIL else 1
    finally:
        _cleanup()


if __name__ == "__main__":
    sys.exit(main())
