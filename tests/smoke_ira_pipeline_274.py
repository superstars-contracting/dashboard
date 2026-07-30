#!/usr/bin/env python3
"""#274 — IRA pipeline + calendar guard smoke (dual-backend).

Proves, end-to-end THROUGH the #273 pipeline (estimate -> approve -> convert -> job):
  (a) CONVERT HOOK + SELF-HEAL — converting an approved IRA estimate creates its
      ira_job; deleting the row and re-listing regenerates it (the call-back case can
      never find a missing job).
  (b) ARTIFACT LIFECYCLE — upload (contract/cd5/coi) -> the job's slot points at the
      doc, the waiting-on 'missing' flag clears, an 'ops' crm_activity row lands; the
      artifact is served ONLY by the gated by-id route (pm/super/client 403).
  (c) CD-5 TRANSITIONS — not_filed->approved jump 400; not_filed->filed->approved
      200s with the filed date persisting; approved->filed correction allowed.
  (d) COI EXPIRY (the #271 machinery) — past expiry -> 'expired' + the waiting-on
      sweep flags coi_expired; <=30d -> 'expiring'; >30d -> 'on_file' and the flag
      clears.
  (e) VISITS — multiple visits, SAME DAY, accepted and both returned (calendar +
      job detail); the call-back case (converted long ago, visits added now) is just
      more rows; a performed visit is IMMUTABLE except status (date/label edit 400);
      cancel keeps the row (never hard-deleted); chosen visit dates persist VERBATIM.
  (f) REPORT + PAYMENT persistence — chosen report_sent_date stored verbatim
      (date-chosen-persists), payment submit creates the tracked state (submit-
      creates-record), deposit date defaults LOCAL-today only when omitted.
  (g) ROLE GATES — pm AND super AND client 403 on EVERY /api/ira/* endpoint.
  (h) FORBIDDEN KEYS — no *_path key in any payload seen.

Isolation (CLAUDE.md): SMOKE_BASE isolated server; REFUSES without SSC_DB_URL.
Synthetic-only (SMK274-* / smk274-* / the IRA-QN series), is_system=1, random
per-run password, FK-safe scoped teardown (visits -> job -> docs(+disk) -> ira ->
estimate -> project -> activity -> org -> users). PII-safe output.
"""
from __future__ import annotations

import os
import shutil
import sys
import secrets
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR.parent))

import ssc_paths  # noqa: E402  # #287 — fixture paths honor SSC_DATA_ROOT

import db_layer            # noqa: E402
from auth import hash_password  # noqa: E402
from apply_ira_274 import ensure_ira_schema  # noqa: E402
import crm                 # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PW = secrets.token_urlsafe(18)
USERS = {
    "csuite": "smk274-csuite@superstars.local",
    "pm":     "smk274-pm@superstars.local",
    "super":  "smk274-super@superstars.local",
    "client": "smk274-client@superstars.local",
}
ROLE_OF = {"csuite": "c_suite", "pm": "pm", "super": "super", "client": "client"}
ORG_NAME = "SMK274 Client Org"
SERIES = ("IRA", "QN")                    # synthetic series for this smoke
REPORT_DATE = "2026-06-11"                # verbatim-persistence probes
_DOC_DIR = ssc_paths.under_root("data_room", "estimate_docs")   # #287
_PDF = b"%PDF-1.4\n1 0 obj<</T(smk274)>>endobj\ntrailer<<>>\n%%EOF\n"

PASS, FAIL = [], []
SEEN = []


def ok(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))


def _seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        ensure_ira_schema(conn)
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
                    (email, hash_password(PW), role, f"SMK274 {key}"))
        conn.commit()
        if not conn.execute("SELECT 1 FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone():
            crm.create_org(conn, name=ORG_NAME, relationship_type="client")
        return conn.execute("SELECT id FROM crm_organization WHERE name=?", (ORG_NAME,)).fetchone()[0]
    finally:
        conn.close()


def _cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        t, b = SERIES
        codes = []
        for r in conn.execute("SELECT id, code FROM estimate WHERE est_type=? AND borough=?",
                              (t, b)).fetchall():
            codes.append(r[1])
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
                conn.execute("DELETE FROM login_audit WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM sessions WHERE user_id=?", (u[0],))
                conn.execute("DELETE FROM users WHERE id=?", (u[0],))
        conn.commit()
        for c in codes:
            shutil.rmtree(_DOC_DIR / c, ignore_errors=True)
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
        print("REFUSING TO RUN: SSC_DB_URL is unset — this smoke seeds users/jobs and "
              "must never touch the live superstars.db.")
        return 2
    print(f"#274 IRA pipeline guard — BASE={BASE}  backend={'postgres' if db_layer.is_postgres() else 'sqlite'}")
    _cleanup()
    org_id = _seed()
    today = date.today()
    try:
        cs, pm, su, cl = _login("csuite"), _login("pm"), _login("super"), _login("client")
        ok("logins", all([cs, pm, su]))
        if not cs:
            print("cannot proceed without c_suite session"); return 1

        # ---------- (g) role gates on every /api/ira/* endpoint ----------
        GATED = [
            ("GET", "/api/ira/jobs"), ("GET", "/api/ira/jobs/X"), ("PUT", "/api/ira/jobs/X"),
            ("POST", "/api/ira/jobs/X/artifact"), ("POST", "/api/ira/jobs/X/visits"),
            ("PUT", "/api/ira/visits/1"), ("GET", "/api/ira/calendar"),
        ]
        for role, sess in (("pm", pm), ("super", su), ("client", cl)):
            if not sess:
                continue
            for m, p in GATED:
                st, _ = _sc(sess, m, p, json={} if m in ("POST", "PUT") else None)
                ok(f"{role}_403 {m} {p}", st == 403)

        # ---------- (a) the full #273 -> #274 path: create -> approve -> convert -> job ----------
        st, body = _sc(cs, "POST", "/api/estimates",
                       json={"est_type": "IRA", "borough": "QN", "client_org_id": org_id,
                             "building_address": "SMK274 41-20 Queens Blvd"})
        est = (body or {}).get("data", {}) or {}
        est_id, code = est.get("id"), est.get("code")
        ok("estimate_created", st == 200 and code == "IRA-QN-001")
        for s_, extra in (("scoping", {}), ("submitted", {}),
                          ("approved", {"final_amount": 22000, "qb_estimate_ref": "QB-274"})):
            st, _ = _sc(cs, "POST", f"/api/estimates/{est_id}/status", json={"status": s_, **extra})
        st, body = _sc(cs, "POST", f"/api/estimates/{est_id}/convert")
        ok("converted", st == 200 and ((body or {}).get("data", {}) or {}).get("project_code") == code)
        st, body = _sc(cs, "GET", "/api/ira/jobs")
        jobs = ((body or {}).get("data", {}) or {}).get("jobs", [])
        job = next((j for j in jobs if j["project_code"] == code), None)
        ok("convert_hook_created_job", job is not None)
        ok("job_starts_not_filed_all_missing",
           job and job["cd5_status"] == "not_filed"
           and set(job["missing"]) >= {"contract", "cd5", "coi"})
        # self-heal: drop the row, list regenerates it
        conn = db_layer.connect()
        try:
            conn.execute("DELETE FROM ira_job WHERE project_code=?", (code,))
            conn.commit()
        finally:
            conn.close()
        st, body = _sc(cs, "GET", "/api/ira/jobs")
        jobs = ((body or {}).get("data", {}) or {}).get("jobs", [])
        ok("self_heal_regenerates_job", any(j["project_code"] == code for j in jobs))

        # ---------- (c) CD-5 transitions ----------
        st, _ = _sc(cs, "PUT", f"/api/ira/jobs/{code}", json={"cd5_status": "approved"})
        ok("cd5_jump_400", st == 400)
        st, body = _sc(cs, "PUT", f"/api/ira/jobs/{code}",
                       json={"cd5_status": "filed", "cd5_filed_date": "2026-06-01"})
        d = (body or {}).get("data", {}) or {}
        ok("cd5_filed_200_date_verbatim", st == 200 and d.get("cd5_status") == "filed"
           and d.get("cd5_filed_date") == "2026-06-01")
        st, body = _sc(cs, "PUT", f"/api/ira/jobs/{code}", json={"cd5_status": "approved"})
        d = (body or {}).get("data", {}) or {}
        ok("cd5_approved_200_keeps_date", st == 200 and d.get("cd5_status") == "approved"
           and d.get("cd5_filed_date") == "2026-06-01")
        st, body = _sc(cs, "PUT", f"/api/ira/jobs/{code}", json={"cd5_status": "filed"})
        ok("cd5_correction_back_200", st == 200)
        st, _ = _sc(cs, "PUT", f"/api/ira/jobs/{code}", json={"cd5_status": "approved"})
        ok("cd5_reapproved_200", st == 200)

        # ---------- (b) artifact lifecycle: upload -> slot -> flag clears -> activity ----------
        conn = db_layer.connect()
        try:
            act_before = conn.execute(
                "SELECT COUNT(*) FROM crm_activity WHERE entity_type='organization' AND entity_id=? "
                "AND function_tag='ops'", (org_id,)).fetchone()[0]
        finally:
            conn.close()
        st, body = _sc(cs, "POST", f"/api/ira/jobs/{code}/artifact",
                       files={"file": ("smk274-contract.pdf", _PDF, "application/pdf")},
                       data={"kind": "contract"})
        d = (body or {}).get("data", {}) or {}
        ok("contract_upload_200_slot_set", st == 200 and d.get("contract_doc") is not None)
        ok("contract_flag_cleared", "contract" not in (d.get("missing") or []))
        conn = db_layer.connect()
        try:
            act_after = conn.execute(
                "SELECT COUNT(*) FROM crm_activity WHERE entity_type='organization' AND entity_id=? "
                "AND function_tag='ops'", (org_id,)).fetchone()[0]
        finally:
            conn.close()
        ok("artifact_wrote_ops_activity", act_after > act_before)
        doc_url = (d.get("contract_doc") or {}).get("file_url")
        r = cs.get(f"{BASE}{doc_url}", timeout=10)
        ok("artifact_served_inline_by_id", r.status_code == 200
           and "inline" in (r.headers.get("Content-Disposition") or "").lower())
        for role, sess in (("pm", pm), ("super", su), ("client", cl)):
            if sess:
                ok(f"artifact_file_{role}_403", sess.get(f"{BASE}{doc_url}", timeout=10).status_code == 403)
        st, _ = _sc(cs, "POST", f"/api/ira/jobs/{code}/artifact",
                    files={"file": ("x.pdf", _PDF, "application/pdf")}, data={"kind": "nope"})
        ok("artifact_bad_kind_400", st == 400)

        # ---------- (d) COI expiry — the #271 pill + the waiting-on sweep ----------
        # a visit must be scheduled for the job to appear in waiting_on at all
        vis_day = (today + timedelta(days=5)).isoformat()
        st, _ = _sc(cs, "POST", f"/api/ira/jobs/{code}/visits",
                    json={"visit_date": vis_day, "label": "SMK274 crew A"})
        ok("visit_created", st == 200)
        past = (today - timedelta(days=10)).isoformat()
        st, body = _sc(cs, "POST", f"/api/ira/jobs/{code}/artifact",
                       files={"file": ("smk274-coi-old.pdf", _PDF, "application/pdf")},
                       data={"kind": "coi", "expiry_date": past})
        d = (body or {}).get("data", {}) or {}
        ok("coi_expired_pill", st == 200 and d.get("coi_expiry_status") == "expired")
        st, body = _sc(cs, "GET", "/api/ira/calendar")
        wait = ((body or {}).get("data", {}) or {}).get("waiting_on", [])
        w = next((x for x in wait if x["project_code"] == code), None)
        ok("waiting_on_flags_coi_expired", w is not None and "coi_expired" in (w.get("missing") or []))
        soon = (today + timedelta(days=12)).isoformat()
        st, body = _sc(cs, "POST", f"/api/ira/jobs/{code}/artifact",
                       files={"file": ("smk274-coi-soon.pdf", _PDF, "application/pdf")},
                       data={"kind": "coi", "expiry_date": soon})
        ok("coi_expiring_pill", ((body or {}).get("data", {}) or {}).get("coi_expiry_status") == "expiring")
        good = (today + timedelta(days=200)).isoformat()
        st, body = _sc(cs, "POST", f"/api/ira/jobs/{code}/artifact",
                       files={"file": ("smk274-coi-new.pdf", _PDF, "application/pdf")},
                       data={"kind": "coi", "expiry_date": good})
        d = (body or {}).get("data", {}) or {}
        ok("coi_on_file_pill", d.get("coi_expiry_status") == "on_file")
        st, body = _sc(cs, "GET", "/api/ira/calendar")
        wait = ((body or {}).get("data", {}) or {}).get("waiting_on", [])
        w = next((x for x in wait if x["project_code"] == code), None)
        ok("waiting_on_coi_clears", not w or ("coi" not in w["missing"] and "coi_expired" not in w["missing"]))

        # ---------- (e) visits: same-day stacking, call-back, immutability, cancel ----------
        st, _ = _sc(cs, "POST", f"/api/ira/jobs/{code}/visits",
                    json={"visit_date": vis_day, "label": "SMK274 sub B"})
        ok("same_day_second_visit_accepted", st == 200)
        month = vis_day[:7]
        st, body = _sc(cs, "GET", f"/api/ira/calendar?month={month}")
        cal = (body or {}).get("data", {}) or {}
        same_day = [v for v in cal.get("visits", []) if v["visit_date"] == vis_day and v["project_code"] == code]
        ok("same_day_both_rendered", len(same_day) == 2)
        # call-back: another visit far out, after conversion long done
        later = (today + timedelta(days=45)).isoformat()
        st, body = _sc(cs, "POST", f"/api/ira/jobs/{code}/visits",
                       json={"visit_date": later, "label": "SMK274 call-back", "status": "scheduled"})
        ok("callback_visit_added_later", st == 200
           and ((body or {}).get("data", {}) or {}).get("visit_date") == later)
        # performed immutability (backfilled performed visit)
        st, body = _sc(cs, "POST", f"/api/ira/jobs/{code}/visits",
                       json={"visit_date": (today - timedelta(days=3)).isoformat(),
                             "label": "SMK274 done day", "status": "performed"})
        pv = ((body or {}).get("data", {}) or {}).get("id")
        ok("performed_backfill_created", st == 200 and bool(pv))
        st, _ = _sc(cs, "PUT", f"/api/ira/visits/{pv}", json={"visit_date": today.isoformat()})
        ok("performed_date_edit_400", st == 400)
        st, _ = _sc(cs, "PUT", f"/api/ira/visits/{pv}", json={"label": "renamed"})
        ok("performed_label_edit_400", st == 400)
        st, body = _sc(cs, "PUT", f"/api/ira/visits/{pv}", json={"status": "scheduled"})
        ok("performed_status_change_200", st == 200
           and ((body or {}).get("data", {}) or {}).get("status") == "scheduled")
        # cancel keeps the row — never hard-deleted
        conn = db_layer.connect()
        try:
            n_before = conn.execute("SELECT COUNT(*) FROM ira_visit WHERE project_code=?", (code,)).fetchone()[0]
        finally:
            conn.close()
        st, body = _sc(cs, "PUT", f"/api/ira/visits/{pv}", json={"status": "cancelled"})
        conn = db_layer.connect()
        try:
            n_after = conn.execute("SELECT COUNT(*) FROM ira_visit WHERE project_code=?", (code,)).fetchone()[0]
        finally:
            conn.close()
        ok("cancel_keeps_row", st == 200 and n_before == n_after
           and ((body or {}).get("data", {}) or {}).get("status") == "cancelled")

        # ---------- (f) report + payment persistence ----------
        st, body = _sc(cs, "PUT", f"/api/ira/jobs/{code}",
                       json={"report_sent_date": REPORT_DATE})
        ok("report_date_verbatim", st == 200
           and ((body or {}).get("data", {}) or {}).get("report_sent_date") == REPORT_DATE)
        st, body = _sc(cs, "PUT", f"/api/ira/jobs/{code}",
                       json={"deposit_received": True, "balance_status": "paid",
                             "qb_invoice_ref": "QB-INV-274"})
        d = (body or {}).get("data", {}) or {}
        ok("payment_submit_creates_state", st == 200 and d.get("deposit_received") is True
           and d.get("balance_status") == "paid" and d.get("qb_invoice_ref") == "QB-INV-274")
        ok("deposit_date_defaults_local_today", d.get("deposit_date") == today.isoformat())
        chosen_dep = (today - timedelta(days=2)).isoformat()
        st, body = _sc(cs, "PUT", f"/api/ira/jobs/{code}",
                       json={"deposit_received": True, "deposit_date": chosen_dep})
        ok("deposit_date_chosen_persists",
           ((body or {}).get("data", {}) or {}).get("deposit_date") == chosen_dep)
        st, body = _sc(cs, "GET", f"/api/ira/jobs/{code}")
        jd = ((body or {}).get("data", {}) or {}).get("job", {})
        ok("job_detail_roundtrip", jd.get("report_sent_date") == REPORT_DATE
           and jd.get("balance_status") == "paid")
        ok("job_detail_documents_listed",
           len(((body or {}).get("data", {}) or {}).get("documents", [])) >= 4)

        # ---------- (h) forbidden keys ----------
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
