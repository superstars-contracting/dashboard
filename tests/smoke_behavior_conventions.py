"""smoke_behavior_conventions.py — behavioral guard (#253).

Stops the recurring FIELD-BUG classes at the root by FAILING the build if a key
modal/surface regresses one of them. These are the exact classes behind #253:

  (a) DATE-CHOSEN-PERSISTS: a user-chosen date field must be read from the picker
      (SSCDatePicker.getISO) on submit — never silently saving today() instead of
      the picked date.  [#253 labor-rate effective date; drop-stage start date;
      expense date]
  (b) SUBMIT-CREATES-RECORD: a primary "submit for approval" must fire on the
      WHOLE change, not a partial slice — the labor-rate submit must fire on a
      RATE *or* EFFECTIVE-DATE change, else a date-only edit is silently dropped
      while still toasting "Submitted".  [#253 submit-to-PM]
  (c) CANCEL-RESETS-FORM: a modal's Cancel/close must reset the form (incl. the
      SSCDatePicker dataset.iso, not just .value) so reopening is a clean slate.
      [#253 onboarding cancel]
  + RENDER: the drop-stage date chip must use a chip-SPECIFIC empty class, not the
      generic .dp-empty (whose 28px padding ballooned every undated chip and
      cascaded the stepper).  [#253 stage-date render]

The static surface checks parse the SERVED HTML/JS of each surface (same approach
as smoke_design_conventions.py) and assert the fixed pattern is present; a
self-test proves every matcher FAILS on the broken pattern and PASSES on the
fixed one.

PLUS one CROSS-VIEW BEHAVIORAL check (#254): an APPROVED labor-rate change —
including a DATE-ONLY backdate — must be reflected in the canonical worker_rates
the tracker/payroll grid resolves (get_rate_effective_on). It drives the real
write-flow on a SYNTHETIC worker (add rate -> submit backdate -> approve) and
asserts the tracker resolves the approved rate for the backdated week. On the
PRE-#254 server (the approve->worker_rates bridge silently skipped backdates)
this FAILS; on the fixed server it PASSES. Synthetic-only, scoped cleanup, real
data untouched; comp-data discipline — prints booleans only, never a rate value.
"""
import os
import re
import sqlite3
import sys
from datetime import date, timedelta

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
DB_PATH = _smoke_auth.DB_PATH
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return bool(cond)


def fetch(path):
    r = requests.get(BASE + path, timeout=15)
    r.raise_for_status()
    return r.text


# ---- The recurring-class matchers. Each returns True when the FIXED pattern is
# ---- present. Kept as named functions so the self-test can prove each one
# ---- discriminates broken-vs-fixed on sample strings. ----------------------

def m_date_read(html, field_token):
    """(a) the submit reads the chosen date via SSCDatePicker.getISO(<field>),
    not a hardcoded today()."""
    return re.search(r"getISO\(" + re.escape(field_token) + r"\)", html) is not None


def m_submit_on_rate_or_date(html):
    """(b) the labor-rate edit submit fires on rate OR effective-date change."""
    return re.search(r"rateChanged\s*\|\|\s*dateChanged", html) is not None


def m_cancel_resets(html):
    """(c) the intake modal resets the form (clearing dataset.iso via setISO('')),
    and Cancel/close/open all call it (>=3 call sites)."""
    has_reset = re.search(r"function\s+resetIntakeForm\s*\(", html) is not None
    clears_iso = re.search(r"setISO\(\s*e\s*,\s*''\s*\)", html) is not None
    call_sites = len(re.findall(r"resetIntakeForm\(\)", html))
    return has_reset and clears_iso and call_sites >= 3


def m_stage_chip_specific_empty(html):
    """(RENDER) the drop-stage chip uses the chip-specific empty class, not the
    bare generic .dp-empty (the 28px-padding collision)."""
    uses_specific = "dp-datechip-empty" in html
    # the broken render added a bare ' dp-empty' to the datechip class string
    broken = re.search(r"dp-datechip'\s*\+\s*\(iso\?''\s*:\s*' dp-empty'\)", html) is not None
    return uses_specific and not broken


def m_stage_complete_control(html):
    """(#256) the Drop Plan stage row exposes a backdatable COMPLETE control and an
    UN-COMPLETE toggle, and the completion date rides a SSCDatePicker input. Pre-#256
    the row had only a start-date chip + N/A toggle, so a stage could never be marked
    complete — and since % counts only completed stages, the number could never move
    (and stayed wrong after a hard refresh). The affordance to set the COMPLETION
    signal must exist, be reversible, and use the date picker (backdatable)."""
    has_complete = "data-complete=" in html
    has_uncomplete = "data-uncomplete=" in html
    has_completion_datepicker = "dp-cdatechip" in html  # SSCDatePicker-wired completion date
    return has_complete and has_uncomplete and has_completion_datepicker


# ---- (#254) cross-view BEHAVIORAL check: approved rate -> tracker resolution --

_PROP_EID, _PROP_WID = "E-99254", "W-9954"


def _prop_teardown():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    try:
        for tbl in ("labor_rate_change", "labor_worker_state"):
            conn.execute(f"DELETE FROM {tbl} WHERE worker_id=?", (_PROP_WID,))
        conn.execute("DELETE FROM worker_rates WHERE employee_id=?", (_PROP_EID,))
        conn.execute("DELETE FROM project_assignments WHERE employee_id=?", (_PROP_EID,))
        conn.execute("DELETE FROM audit_log WHERE target_id IN (?,?)", (_PROP_EID, _PROP_WID))
        conn.execute("DELETE FROM employees WHERE employee_id=? OR worker_id=?", (_PROP_EID, _PROP_WID))
        conn.commit()
    finally:
        conn.close()


def behavioral_propagation_check():
    """Synthetic write-flow: add rate -> submit a DATE-ONLY backdate -> approve,
    then assert the canonical worker_rates the tracker resolves
    (get_rate_effective_on) reflects the approved rate for the backdated week.
    Returns (ok_bool, note). Fake $1.00 rate (comp discipline); booleans only."""
    from worker_rates import get_rate_effective_on
    _prop_teardown()
    # synthetic active worker + active project assignment (eligible to add a rate)
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    try:
        conn.execute("INSERT INTO employees (employee_id, worker_id, name, trade, intake_status) "
                     "VALUES (?,?,?,?, 'active')",
                     (_PROP_EID, _PROP_WID, "ZZ SMOKE Propagation", "Mechanic"))
        proj = conn.execute("SELECT project_code FROM projects WHERE status='active' OR status IS NULL LIMIT 1").fetchone()
        if proj:
            conn.execute("INSERT INTO project_assignments (employee_id, project_code, status) VALUES (?,?, 'active')",
                         (_PROP_EID, proj[0]))
        conn.commit()
    finally:
        conn.close()
    try:
        today = date.today()
        this_mon = today - timedelta(days=today.weekday())
        last_mon = this_mon - timedelta(days=7)
        # 1) initial rate effective THIS week's Monday
        r1 = requests.post(f"{BASE}/api/labor-rates/state",
                           json={"worker_id": _PROP_WID, "trade": "Mechanic", "rate": 1.00,
                                 "effective_date": this_mon.isoformat(), "status": "active"}, timeout=15)
        if r1.status_code not in (200, 201):
            return False, f"add-rate failed ({r1.status_code})"
        # 2) DATE-ONLY BACKDATE to LAST week's Monday (same rate) -> pending
        r2 = requests.post(f"{BASE}/api/labor-rates/changes",
                           json={"worker_id": _PROP_WID, "new_rate": 1.00,
                                 "effective_date": last_mon.isoformat()}, timeout=15)
        if r2.status_code not in (200, 201):
            return False, f"submit failed ({r2.status_code})"
        cid = (r2.json().get("data") or {}).get("change_id")
        if not cid:
            return False, "no change_id"
        # 3) approve -> the bridge must land the backdate in worker_rates
        r3 = requests.post(f"{BASE}/api/labor-rates/changes/{cid}/approve", json={}, timeout=15)
        if r3.status_code != 200:
            return False, f"approve failed ({r3.status_code})"
        # 4) cross-view: does the canonical source the tracker resolves now reflect
        #    the approved rate for the BACKDATED week? (boolean; never the value)
        rconn = sqlite3.connect(str(DB_PATH), timeout=60)
        rconn.row_factory = sqlite3.Row
        try:
            resolved = get_rate_effective_on(rconn, _PROP_EID, last_mon.isoformat())
        finally:
            rconn.close()
        if resolved is not None:
            return True, "tracker resolves the approved backdated rate (propagated)"
        return False, "tracker still 'Rate not set' for the backdated week (approve->worker_rates bridge skipped)"
    finally:
        _prop_teardown()


# ---- (#255) look-ahead persistence: drag / add / remove survive a reload ------

_LA_PROJ = "ZZ-SMOKE-LA"


def _la_teardown():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    try:
        conn.execute("DELETE FROM lookahead_activity WHERE project_code=?", (_LA_PROJ,))
        conn.commit()
    finally:
        conn.close()


def _la_all(win):
    return list(win.get("general", [])) + [a for g in win.get("groups", []) for a in g.get("activities", [])]


def behavioral_lookahead_check():
    """The Two-Week Look-Ahead is the editable master-schedule source of truth, so
    an ADDED activity must persist, a DRAGGED activity's LOCAL planned dates must
    survive a reload (and lock it source='manual'), and a REMOVED one must be
    gone. Drives add -> drag(PATCH) -> remove(DELETE) on a synthetic project and
    asserts each round-trips through a fresh GET. Returns (ok_bool, note)."""
    _la_teardown()
    base = f"{BASE}/api/projects/{_LA_PROJ}/lookahead"
    try:
        r = requests.post(base + "/activities", json={
            "name": "ZZ smoke activity", "activity_type": "work",
            "planned_start": "2026-06-15", "planned_finish": "2026-06-16"}, timeout=15)
        if r.status_code not in (200, 201):
            return False, f"add failed ({r.status_code})"
        aid = (r.json().get("data") or {}).get("id")
        if not aid:
            return False, "add returned no id"
        win = requests.get(base + "?start=2026-06-15", timeout=15).json()["data"]
        if not any(a["id"] == aid for a in _la_all(win)):
            return False, "added activity did not persist"
        # drag: PATCH new LOCAL planned dates -> must persist + lock manual
        p = requests.patch(f"{BASE}/api/lookahead/activities/{aid}",
                           json={"planned_start": "2026-06-18", "planned_finish": "2026-06-19"}, timeout=15)
        if p.status_code != 200:
            return False, f"drag PATCH failed ({p.status_code})"
        win2 = requests.get(base + "?start=2026-06-15", timeout=15).json()["data"]
        a = next((x for x in _la_all(win2) if x["id"] == aid), None)
        if not (a and a["planned_start"] == "2026-06-18" and a["planned_finish"] == "2026-06-19"
                and a["source"] == "manual"):
            return False, "dragged planned dates did not persist (or did not lock manual)"
        # remove: DELETE -> must be gone
        requests.delete(f"{BASE}/api/lookahead/activities/{aid}", timeout=15)
        win3 = requests.get(base + "?start=2026-06-15", timeout=15).json()["data"]
        if any(x["id"] == aid for x in _la_all(win3)):
            return False, "removed activity still present"
        return True, "add + drag (persisted LOCAL dates, locked manual) + remove all round-trip"
    finally:
        _la_teardown()


# ---- (#256) stage completion -> per-drop & overall % derived live, single-source --
# The recurring class here is the #255 family (divergent / stale % source). The
# fix: % is DERIVED on read from the canonical stage-status (drop_stage_status),
# and COMPLETING a stage is the only signal that moves it. This drives the real
# write-flow on a SYNTHETIC project+drop so the live FR-BX-001 data is untouched.

_SC_PROJ = "ZZ-SMOKE-256"
_SC_DROP = "ZZ-SMK-256-DP1"
_SC_STEPS = 5


def _sc_teardown():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000;")
        conn.execute("DELETE FROM audit_log WHERE action LIKE 'dropplan_%' AND target_id LIKE ?", (_SC_DROP + "#%",))
        conn.execute("DELETE FROM drop_stage_status WHERE drop_id=?", (_SC_DROP,))
        conn.execute("DELETE FROM drops WHERE drop_id=?", (_SC_DROP,))
        conn.execute("DELETE FROM stage_template_steps WHERE template_id IN "
                     "(SELECT template_id FROM stage_templates WHERE project_code=?)", (_SC_PROJ,))
        conn.execute("DELETE FROM stage_templates WHERE project_code=?", (_SC_PROJ,))
        conn.execute("DELETE FROM projects WHERE project_code=?", (_SC_PROJ,))
        conn.commit()
    finally:
        conn.close()


def _sc_setup():
    conn = sqlite3.connect(str(DB_PATH), timeout=60)
    try:
        conn.execute("PRAGMA busy_timeout=60000;")
        conn.execute("INSERT INTO projects(project_code,name) VALUES(?, 'ZZ Smoke 256 Progress')", (_SC_PROJ,))
        conn.execute("INSERT INTO stage_templates(project_code,name) VALUES(?, 'ZZ Smoke 256 template')", (_SC_PROJ,))
        tid = conn.execute("SELECT template_id FROM stage_templates WHERE project_code=?", (_SC_PROJ,)).fetchone()[0]
        for n in range(1, _SC_STEPS + 1):
            conn.execute("INSERT INTO stage_template_steps(template_id,step_no,name,default_working_days) "
                         "VALUES(?,?,?,2)", (tid, n, f"Stage {n}"))
        conn.execute("INSERT INTO drops(drop_id,project_code,elevation,sequence_no,lifecycle) "
                     "VALUES(?,?, 'North', 1, 'scaffold_active')", (_SC_DROP, _SC_PROJ))
        for n in range(1, _SC_STEPS + 1):
            conn.execute("INSERT INTO drop_stage_status(drop_id,step_no,status) VALUES(?,?, 'not_started')", (_SC_DROP, n))
        conn.commit()
    finally:
        conn.close()


def _sc_drop_pct():
    """The value the Drop-Plan card AND the Drop-Report read: drop_detail.progress.pct."""
    r = requests.get(f"{BASE}/api/dropplan/drops/{_SC_DROP}", timeout=15)
    return (r.json().get("data") or {}).get("progress", {}).get("pct")


def _sc_overall_pct():
    """The value the progress WIDGET / hero read: project_rollup.overall_progress_pct."""
    r = requests.get(f"{BASE}/api/dropplan/projects/{_SC_PROJ}/rollup", timeout=15)
    return (r.json().get("data") or {}).get("overall_progress_pct")


def behavioral_stage_completion_check():
    """#256 — completing a stage is the signal that moves %. On a SYNTHETIC
    project+drop (5 stages):
      * a BACKDATED START date -> stage in_progress, % unchanged (per the model);
      * mark COMPLETE with a PAST date -> per-drop % +1/total AND overall % move,
        and the recomputed values come back IN the PATCH response (no extra fetch);
      * completion date is stored as the chosen PAST date, never silently today;
      * (b) the value is identical across the drop-plan card, the drop-report, the
        widget endpoints AND the canonical helper (single-source — fails on divergence);
      * (c) it persists across a reload; un-complete reverts it (and clears completed_on).
    Returns (ok_bool, note). Scoped teardown; real data untouched; numbers only."""
    import dropplan_rollups as R
    _sc_teardown()
    _sc_setup()
    try:
        today = date.today()
        last_week = (today - timedelta(days=7)).isoformat()
        per = round(100.0 / _SC_STEPS, 1)  # 20.0

        if _sc_drop_pct() != 0.0 or _sc_overall_pct() != 0.0:
            return False, "baseline % not 0"

        # (1) BACKDATED START -> in_progress, % unchanged, response carries recomputed %
        r = requests.patch(f"{BASE}/api/dropplan/drops/{_SC_DROP}/stages/1",
                           json={"started_on": last_week}, timeout=15)
        if r.status_code != 200:
            return False, f"start PATCH failed ({r.status_code})"
        j = r.json().get("data") or {}
        if j.get("status") != "in_progress":
            return False, "start date did not set status in_progress (the recompute-signal gap)"
        if "drop_pct" not in j or "overall_pct" not in j:
            return False, "PATCH response missing recomputed drop_pct/overall_pct"
        if j.get("drop_pct") != 0.0 or j.get("overall_pct") != 0.0:
            return False, "start date moved % (should stay 0 until a stage is complete)"

        # (2) COMPLETE with a PAST date -> +1/total per-drop & overall; date is the PAST date
        r = requests.patch(f"{BASE}/api/dropplan/drops/{_SC_DROP}/stages/1",
                           json={"status": "complete", "completed_on": last_week}, timeout=15)
        if r.status_code != 200:
            return False, f"complete PATCH failed ({r.status_code})"
        j = r.json().get("data") or {}
        if j.get("status") != "complete":
            return False, "complete did not set status complete"
        if j.get("completed_on") == today.isoformat() or j.get("completed_on") != last_week:
            return False, f"completion date not the chosen PAST date (got {j.get('completed_on')!r})"
        if j.get("drop_pct") != per or j.get("overall_pct") != per:
            return False, f"% did not rise to {per} on complete (drop={j.get('drop_pct')} overall={j.get('overall_pct')})"

        # (3) SINGLE SOURCE — card, report, widget endpoints + helper all agree
        hconn = sqlite3.connect(str(DB_PATH), timeout=60)
        hconn.row_factory = sqlite3.Row
        try:
            helper_drop = R.drop_progress(hconn, _SC_DROP)["pct"]
            helper_overall = R.project_rollup(hconn, _SC_PROJ, include_cost=False)["overall_progress_pct"]
        finally:
            hconn.close()
        vals = [_sc_drop_pct(), _sc_overall_pct(), helper_drop, helper_overall, per]
        if len(set(vals)) != 1:
            return False, f"surfaces diverge (not single-source): {vals}"

        # (4) PERSISTS across a reload (re-read the canonical source + the chosen date)
        if _sc_drop_pct() != per or _sc_overall_pct() != per:
            return False, "completed % did not persist across reload"
        det = requests.get(f"{BASE}/api/dropplan/drops/{_SC_DROP}", timeout=15).json().get("data") or {}
        st1 = next((s for s in det.get("stages", []) if s["step_no"] == 1), {})
        if st1.get("completed_on") != last_week:
            return False, "completion date did not persist as the past date across reload"

        # (5) UN-COMPLETE -> reverts %, clears completed_on, persists
        r = requests.patch(f"{BASE}/api/dropplan/drops/{_SC_DROP}/stages/1",
                           json={"status": "in_progress"}, timeout=15)
        j = r.json().get("data") or {}
        if j.get("drop_pct") != 0.0 or j.get("overall_pct") != 0.0:
            return False, "un-complete did not revert %"
        if j.get("completed_on") is not None:
            return False, "un-complete did not clear completed_on"
        if _sc_drop_pct() != 0.0 or _sc_overall_pct() != 0.0:
            return False, "reverted % did not persist across reload"

        return True, (f"complete +{per} per-drop & overall (single-source across card/report/widget/helper), "
                      "PAST date stored, persists across reload, un-complete reverts")
    finally:
        _sc_teardown()


def main():
    # ---- self-test: prove the matchers discriminate broken vs fixed ----------
    print("== self-test (prove each matcher fails on the broken pattern) ==")
    ok("selftest_date_read",
       m_date_read("x=SSCDatePicker.getISO($('lr-f-date'));", "$('lr-f-date')")
       and not m_date_read("x=todayISO();", "$('lr-f-date')"))
    ok("selftest_submit_on_rate_or_date",
       m_submit_on_rate_or_date("if(rateChanged || dateChanged){post();}")
       and not m_submit_on_rate_or_date("if(Math.abs(rate-cur)>=0.005){post();}"))
    ok("selftest_cancel_resets",
       m_cancel_resets("function resetIntakeForm(){ SSCDatePicker.setISO(e, ''); } "
                       "resetIntakeForm() resetIntakeForm() resetIntakeForm()")
       and not m_cancel_resets("modal.classList.remove('active');"))
    ok("selftest_stage_chip_empty",
       m_stage_chip_specific_empty("class=\"dp-datechip'+(iso?'':' dp-datechip-empty')+'\"")
       and not m_stage_chip_specific_empty("class=\"dp-datechip'+(iso?'':' dp-empty')+'\""))
    ok("selftest_stage_complete_control",
       m_stage_complete_control("<button data-complete='1'></button><button data-uncomplete='1'></button>"
                                "<input class='dp-cdatechip' data-completestep='1'>")
       and not m_stage_complete_control("<input class='dp-datechip' data-datestep='1'>"
                                        "<button data-na='1'>N/A</button>"))

    # ---- live surfaces -------------------------------------------------------
    print("\n== surfaces ==")
    surfaces = {}
    for key, path in (("labor", "/admin/labor-rates"),
                      ("console", "/"),
                      ("project", "/dashboard")):
        try:
            surfaces[key] = fetch(path)
        except Exception as e:
            surfaces[key] = ""
            ok(f"fetch_{key}", False, f"{path} -> {e}")

    labor = surfaces.get("labor", "")
    console = surfaces.get("console", "")
    project = surfaces.get("project", "")

    # (a) date-chosen-persists across the date-submit surfaces
    ok("labor_effdate_read_from_picker", m_date_read(labor, "$('lr-f-date')"),
       "labor-rate effective date read via getISO (not today)")
    ok("dropstage_date_read_from_picker", m_date_read(project, "dc"),
       "drop-stage start date read via getISO")
    ok("expense_date_read_from_picker", m_date_read(project, "$('exp-f-date')"),
       "expense date read via getISO")

    # (b) submit-creates-record: labor-rate fires on rate OR date change
    ok("labor_submit_on_rate_or_date", m_submit_on_rate_or_date(labor),
       "edit submit fires on rate OR effective-date change (not rate-only)")

    # (c) cancel-resets-form: onboarding intake
    ok("onboarding_cancel_resets_form", m_cancel_resets(console),
       "intake Cancel/close/open reset the form incl. SSCDatePicker dataset.iso")

    # (render) drop-stage chip uses the chip-specific empty class
    ok("dropstage_chip_specific_empty_class", m_stage_chip_specific_empty(project),
       "stage date chip uses dp-datechip-empty (not the generic .dp-empty)")

    # (#256) the Drop Plan stage row has a backdatable Complete control + un-complete
    ok("dropstage_complete_control_present", m_stage_complete_control(project),
       "stage row exposes data-complete + data-uncomplete + SSCDatePicker completion date")

    # ---- (#254) cross-view propagation: approved rate reflected in the tracker -
    print("\n== cross-view behavioral (approved rate -> tracker resolution) ==")
    try:
        prop_ok, prop_note = behavioral_propagation_check()
    except Exception as e:
        prop_ok, prop_note = False, f"check errored: {type(e).__name__}: {e}"
    ok("approved_rate_propagates_to_tracker", prop_ok, prop_note)

    # ---- (#255) look-ahead: drag / add / remove persist across a reload -------
    print("\n== look-ahead persistence (drag / add / remove round-trip) ==")
    try:
        la_ok, la_note = behavioral_lookahead_check()
    except Exception as e:
        la_ok, la_note = False, f"check errored: {type(e).__name__}: {e}"
    ok("lookahead_drag_add_remove_persist", la_ok, la_note)

    # ---- (#256) stage completion -> per-drop & overall % derived live, single-source -
    print("\n== stage completion (per-drop & overall % derived live, single-source) ==")
    try:
        sc_ok, sc_note = behavioral_stage_completion_check()
    except Exception as e:
        sc_ok, sc_note = False, f"check errored: {type(e).__name__}: {e}"
    ok("stage_complete_moves_pct_single_source_persists", sc_ok, sc_note)

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
