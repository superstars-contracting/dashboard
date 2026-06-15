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

It works WITHOUT a browser: it parses the SERVED HTML/JS of each surface (same
approach as smoke_design_conventions.py) and asserts the fixed pattern is
present. A self-test proves every matcher FAILS on the broken pattern and PASSES
on the fixed one. Read-only; touches no data. Run in the gate on every UI build.
"""
import os
import re
import sys

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
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

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
