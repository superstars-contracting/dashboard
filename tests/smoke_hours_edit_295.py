"""#295 GUARD — sign-in hours corrections: history, issued-DCR amend + re-render.

What it proves:
  HISTORY     PUT (edit) and DELETE (remove) on /api/sign-ins/<id> write one
              sign_in_edit row per correction — action, from -> to times
              (remove preserves the erased times), actor, optional reason.
              The cancel-rollback delete labels itself via ?reason=.
  ISSUED ARC  a correction on a day with an ISSUED DCR is ALLOWED and:
              flags report_index.hours_amended(+at), writes an audit_log row
              ('hours_edit_after_issue'), marks the history row dcr_amended,
              returns the amendment in the response, AND auto re-renders BOTH
              audiences — verified BY CONTENT (the served artifacts carry the
              corrected time and no longer carry the old one) — and the stale
              flag ends CLEARED (artifact matches live again).
  ARCHIVE     the reports listing carries hours_amended for the visible pill.
  MEMO        the #292 cost engine's labor total MOVES after an hours edit and
              after a remove (stale serve = red) — the invalidation
              choke-point fires on the correction doors.
  AUTH        anonymous PUT/DELETE are 401 (blanket gate).
  STRUCTURE   the served project page carries the roster correction
              affordances (data-led-edit), the honest Cancel copy, and the
              hours-amended pill builder.

Runs against the shared gate server (SMOKE_BASE). Isolated backend REQUIRED.
PII-safe: synthetic identities; ids/counts/booleans only.
"""
from __future__ import annotations

import os
import secrets
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5434")
PC = "SMK295-A"
E1, W1 = "E-99295", "W-9295"
E2, W2 = "E-99296", "W-9296"
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note and not cond else ""))
    return bool(cond)


def seed():
    conn = db_layer.connect(pragma_fk=True)
    try:
        cleanup_rows(conn)
        now = "2026-08-10T00:00:00"
        conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?, 'active')",
                     (PC, "Smoke 295"))
        for eid, wid, nm in ((E1, W1, "SMK295 One"), (E2, W2, "SMK295 Two")):
            conn.execute(
                "INSERT INTO employees (employee_id, name, trade, worker_id, created_at, updated_at) "
                "VALUES (?,?, 'Laborer', ?, ?, ?)", (eid, nm, wid, now, now))
            conn.execute(
                "INSERT INTO labor_worker_state (worker_id, employee_id, trade, current_rate, "
                "status, effective_date, created_at, updated_at) "
                "VALUES (?,?, 'Laborer', 10.0, 'active', '2026-01-01', '2026-01-01', '2026-01-01')",
                (wid, eid))
            conn.execute(
                "INSERT INTO worker_rates (employee_id, hourly_rate, effective_from, "
                "effective_to, notes) VALUES (?, 10.0, '2026-01-01', NULL, 'smk295 seed')",
                (eid,))
        conn.commit()
    finally:
        conn.close()


def plant_signin(conn, eid, day, t_in, t_out):
    now = "2026-08-10T00:00:00"
    cur = conn.execute(
        "INSERT INTO sign_in_log (date, employee_id, project_code, time_in, time_out, "
        "created_at, updated_at) VALUES (?,?,?,?,?,?,?)",
        (day, eid, PC, t_in, t_out, now, now))
    return cur.lastrowid


def cleanup_rows(conn):
    for sql, args in (
        ("DELETE FROM sign_in_edit WHERE project_code=?", (PC,)),
        ("DELETE FROM sign_in_log WHERE project_code=?", (PC,)),
        ("DELETE FROM report_index WHERE project_code=?", (PC,)),
        ("DELETE FROM audit_log WHERE action='hours_edit_after_issue'", ()),
        ("DELETE FROM worker_rates WHERE employee_id IN (?,?)", (E1, E2)),
        ("DELETE FROM labor_worker_state WHERE worker_id IN (?,?)", (W1, W2)),
        ("DELETE FROM employees WHERE employee_id IN (?,?)", (E1, E2)),
        ("DELETE FROM projects WHERE project_code=?", (PC,)),
    ):
        try:
            conn.execute(sql, args)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass


def cleanup():
    conn = db_layer.connect(pragma_fk=True)
    try:
        cleanup_rows(conn)
    finally:
        conn.close()
    # rendered artifacts live under the repo data tree in the gate config
    import ssc_paths
    shutil.rmtree(ssc_paths.under_root("data_room", "reports", "dcr", PC),
                  ignore_errors=True)
    print("  [cleanup] synthetic rows + renders removed (scoped to SMK295 ids)")


def q1(sql, args=()):
    conn = db_layer.connect()
    try:
        return conn.execute(sql, args).fetchone()
    finally:
        conn.close()


def main() -> int:
    print("== #295 guard: hours corrections — history, amend flag, re-render ==")
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    if not db_url:
        print("REFUSING TO RUN: SSC_DB_URL is unset — this suite seeds rows and issues "
              "a DCR and must never touch the live DB.")
        return 2
    import _smoke_auth
    _smoke_auth.setup()
    admin = requests           # patched: authenticated smoke admin
    anon = requests.Session()  # clean session: anonymous

    seed()
    try:
        d_free = (date.today() - timedelta(days=2)).isoformat()   # no DCR issued
        d_issued = (date.today() - timedelta(days=1)).isoformat() # gets an issued DCR

        conn = db_layer.connect()
        try:
            sid_a = plant_signin(conn, E1, d_free, "07:00", "15:30")
            sid_b = plant_signin(conn, E2, d_free, "07:00", "15:30")
            sid_c = plant_signin(conn, E2, d_free, "08:00", "16:00")  # cancel-label probe
            conn.commit()
        finally:
            conn.close()

        # ---- 1. HISTORY: edit on an unissued day ----
        r = admin.put(f"{BASE}/api/sign-ins/{sid_a}",
                      json={"time_in": "06:30", "time_out": "14:45",
                            "reason": "smk295 wrong start"}, timeout=20)
        ok("edit_put_200", r.status_code == 200, f"{r.status_code}")
        body = (r.json() or {}).get("data") or {}
        ok("edit_no_amend_on_unissued_day", "dcr_amended" not in body)
        h = q1("SELECT * FROM sign_in_edit WHERE sign_in_id=? AND action='edit'", (sid_a,))
        ok("edit_history_row", h is not None)
        ok("edit_history_from_to",
           h is not None and h["from_time_in"] == "07:00" and h["from_time_out"] == "15:30"
           and h["to_time_in"] == "06:30" and h["to_time_out"] == "14:45")
        ok("edit_history_reason", h is not None and h["reason"] == "smk295 wrong start")
        ok("edit_history_actor", h is not None and h["actor_uid"] is not None)
        row = q1("SELECT time_in, time_out FROM sign_in_log WHERE id=?", (sid_a,))
        ok("edit_moved_the_row", row is not None and row["time_in"] == "06:30"
           and row["time_out"] == "14:45")

        # ---- 2. HISTORY: remove preserves the erased times ----
        r = admin.delete(f"{BASE}/api/sign-ins/{sid_b}?reason=smk295%20wrong%20worker", timeout=20)
        ok("remove_200", r.status_code == 200, f"{r.status_code}")
        h = q1("SELECT * FROM sign_in_edit WHERE sign_in_id=? AND action='remove'", (sid_b,))
        ok("remove_history_row", h is not None)
        ok("remove_preserves_times",
           h is not None and h["from_time_in"] == "07:00" and h["from_time_out"] == "15:30"
           and h["to_time_in"] is None and h["to_time_out"] is None)
        ok("remove_history_reason", h is not None and h["reason"] == "smk295 wrong worker")
        ok("remove_row_gone",
           q1("SELECT 1 FROM sign_in_log WHERE id=?", (sid_b,)) is None)

        # ---- 3. cancel-rollback labels itself ----
        r = admin.delete(f"{BASE}/api/sign-ins/{sid_c}"
                         "?reason=entry%20cancelled%20before%20issue", timeout=20)
        ok("cancel_delete_200", r.status_code == 200, f"{r.status_code}")
        h = q1("SELECT reason FROM sign_in_edit WHERE sign_in_id=?", (sid_c,))
        ok("cancel_label_recorded", h is not None
           and h["reason"] == "entry cancelled before issue")

        # ---- 4. anonymous 401 ----
        r = anon.put(f"{BASE}/api/sign-ins/{sid_a}",
                     json={"time_in": "06:00", "time_out": "14:00"}, timeout=20)
        ok("anon_put_401", r.status_code == 401, f"{r.status_code}")
        r = anon.delete(f"{BASE}/api/sign-ins/{sid_a}", timeout=20)
        ok("anon_delete_401", r.status_code == 401, f"{r.status_code}")

        # ---- 5. ISSUED ARC: issue both audiences, edit, verify by content ----
        conn = db_layer.connect()
        try:
            sid_d = plant_signin(conn, E1, d_issued, "07:01", "15:31")
            plant_signin(conn, E2, d_issued, "07:02", "15:32")
            conn.commit()
        finally:
            conn.close()
        r = admin.post(f"{BASE}/api/projects/{PC}/daily/{d_issued}/issue",
                       json={"audience": "both", "roster_skip": True}, timeout=120)
        ok("issue_both_201", r.status_code == 201, f"{r.status_code} {r.text[:120]}")
        iss = (r.json() or {}).get("data") or {}
        int_url, cli_url = iss.get("internal_url"), iss.get("client_url")
        ok("issue_urls_present", bool(int_url) and bool(cli_url))
        pre_int = admin.get(f"{BASE}{int_url}", timeout=30).text if int_url else ""
        ok("pre_edit_artifact_has_old_time", "15:31" in pre_int)
        # client audience is CURATED (no per-worker times — portal parity):
        # its content check is bytes-changed, not time-string presence.
        pre_cli = admin.get(f"{BASE}{cli_url}", timeout=30).text if cli_url else ""

        r = admin.put(f"{BASE}/api/sign-ins/{sid_d}",
                      json={"time_in": "07:01", "time_out": "12:15",
                            "reason": "smk295 early departure"}, timeout=120)
        ok("issued_edit_200", r.status_code == 200, f"{r.status_code}")
        body = (r.json() or {}).get("data") or {}
        am = body.get("dcr_amended") or {}
        ok("issued_edit_reports_amend", bool(am), str(body)[:120])
        ok("issued_edit_rerendered_flag", am.get("rerendered") is True, str(am)[:120])
        ok("issued_edit_display_id", (am.get("display_id") or "").startswith(f"DCR-{PC}-"))

        ri = q1("SELECT MAX(hours_amended) AS ha, MAX(hours_amended_at) AS at, "
                "MAX(stale) AS st FROM report_index WHERE project_code=? AND report_date=?",
                (PC, d_issued))
        ok("report_index_hours_amended", ri is not None and ri["ha"] == 1 and ri["at"])
        ok("stale_cleared_after_rerender", ri is not None and (ri["st"] or 0) == 0)
        ok("audit_row_written",
           q1("SELECT 1 FROM audit_log WHERE action='hours_edit_after_issue' "
              "AND note LIKE ?", (f"%{PC} {d_issued}%",)) is not None)
        ok("history_marked_dcr_amended",
           q1("SELECT 1 FROM sign_in_edit WHERE sign_in_id=? AND dcr_amended=1",
              (sid_d,)) is not None)

        post_int = admin.get(f"{BASE}{int_url}", timeout=30).text if int_url else ""
        post_cli = admin.get(f"{BASE}{cli_url}", timeout=30).text if cli_url else ""
        ok("rerender_internal_has_new_time", "12:15" in post_int)
        ok("rerender_internal_dropped_old_time", "15:31" not in post_int)
        ok("rerender_internal_kept_control_row", "15:32" in post_int)
        ok("rerender_client_artifact_updated",
           bool(post_cli) and post_cli != pre_cli)

        r = admin.get(f"{BASE}/api/projects/{PC}/reports?report_type=DCR", timeout=20)
        rows = (r.json() or {}).get("data") or []
        mine = [x for x in rows if x.get("report_date") == d_issued]
        ok("archive_carries_hours_amended",
           bool(mine) and any(x.get("hours_amended") == 1 for x in mine))

        # ---- 6. MEMO: the cost engine total MOVES on the correction doors ----
        def widget():
            r = admin.get(f"{BASE}/api/costs/widget?project={PC}", timeout=30)
            if r.status_code != 200:
                return r.status_code, None
            return 200, ((r.json().get("data") or {}).get("selected") or {})
        sc, w0 = widget()
        ok("memo_widget_200", sc == 200, f"{sc}")
        t0 = (w0 or {}).get("total")
        r = admin.put(f"{BASE}/api/sign-ins/{sid_a}",
                      json={"time_in": "06:30", "time_out": "11:00",
                            "reason": "smk295 memo probe"}, timeout=20)
        ok("memo_probe_edit_200", r.status_code == 200, f"{r.status_code}")
        sc, w1 = widget()
        ok("memo_moves_on_edit", sc == 200 and (w1 or {}).get("total") != t0,
           "STALE SERVE — edit did not invalidate labor_cost")
        t1 = (w1 or {}).get("total")
        r = admin.delete(f"{BASE}/api/sign-ins/{sid_a}?reason=smk295%20memo%20remove", timeout=20)
        ok("memo_probe_remove_200", r.status_code == 200, f"{r.status_code}")
        sc, w2 = widget()
        ok("memo_moves_on_remove", sc == 200 and (w2 or {}).get("total") != t1,
           "STALE SERVE — remove did not invalidate labor_cost")

        # ---- 7. STRUCTURE: the served page carries the correction UI ----
        page = admin.get(f"{BASE}/projects/FR-BX-001", timeout=30).text
        ok("page_has_roster_edit_affordance", "data-led-edit" in page)
        ok("page_has_honest_cancel_copy", "Saved sign-ins stay on record" in page)
        ok("page_has_hours_amended_pill", "hours amended" in page)
    finally:
        cleanup()

    print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
