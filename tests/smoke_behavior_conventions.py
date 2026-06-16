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

    # ---- (#254) cross-view propagation: approved rate reflected in the tracker -
    print("\n== cross-view behavioral (approved rate -> tracker resolution) ==")
    try:
        prop_ok, prop_note = behavioral_propagation_check()
    except Exception as e:
        prop_ok, prop_note = False, f"check errored: {type(e).__name__}: {e}"
    ok("approved_rate_propagates_to_tracker", prop_ok, prop_note)

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
