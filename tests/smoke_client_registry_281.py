"""#281 — the client field registry + client_payload(). Provenance, not vocabulary.

This is the guard the operator's amendment 2 asked for, tested as a unit before any
portal route depends on it. Three properties matter:

  1. DEFAULT-DENY. An unregistered field is not emitted, whatever it is called. This is
     the gate, and it is what protects against a column nobody has thought of yet.
  2. THE REGISTRY ITSELF IS GUARDED. A field that is internal by nature (*_reason,
     *_note, internal_*, *_uid, rate/cost/margin/pay, est_stage, *_path) cannot be
     registered client-safe — assert_registry_clean() fails at import and here.
  3. AN UNKNOWN DATASET RAISES. A typo must not degrade to "emit everything".

Pure unit test: no server, no database, no fixtures.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import client_registry as reg  # noqa: E402

_failures = []


def ok(name, cond, note=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"   — {note}" if note and not cond else ""))
    if not cond:
        _failures.append(name)
    return bool(cond)


def run():
    print("\n-- 1. default-deny: unregistered fields are dropped --")
    dirty = {
        "pct": 62.5, "label": "On track",
        # every one of these is the kind of thing that must not survive
        "internal_note": "client is slow paying",
        "hold_reason": "waiting on their funding call",
        "updated_by_uid": 41,
        "labour_cost": 18422.10,
        "margin_pct": 14.2,
        "est_stage": "sent_to_vp",
        "worker_id": "W-0042",
        "file_path": r"C:\worker_records\E-00001_Jane_Doe\face.jpg",
        "sla_breach_days": 6,
        # and one that matches NO internal name pattern but is still unregistered —
        # this is the case a name-based denylist would have missed entirely
        "hold_category": "budget",
    }
    out = reg.client_payload("health.progress", dirty)
    ok("only_registered_survive", set(out) == {"pct", "label"}, str(sorted(out)))
    ok("values_preserved", out["pct"] == 62.5 and out["label"] == "On track")
    for leak in ("internal_note", "hold_reason", "updated_by_uid", "labour_cost",
                 "margin_pct", "est_stage", "worker_id", "file_path", "sla_breach_days"):
        ok(f"dropped_{leak}", leak not in out)
    ok("dropped_unpatterned_internal_field", "hold_category" not in out,
       "a name-pattern denylist would have missed this one — the allowlist catches it")

    print("\n-- 2. the registry itself is guarded --")
    try:
        reg.assert_registry_clean()
        ok("live_registry_is_clean", True)
    except reg.RegistryError as e:
        ok("live_registry_is_clean", False, str(e))
    # self-test: the guard must actually fire
    saved = dict(reg.DATASETS)
    try:
        reg.DATASETS["_selftest"] = frozenset({"pct", "internal_note"})
        try:
            reg.assert_registry_clean()
            ok("guard_catches_internal_registration", False, "it did not raise")
        except reg.RegistryError:
            ok("guard_catches_internal_registration", True)
        reg.DATASETS["_selftest"] = frozenset({"pct", "hold_reason"})
        try:
            reg.assert_registry_clean()
            ok("guard_catches_reason_suffix", False, "it did not raise")
        except reg.RegistryError:
            ok("guard_catches_reason_suffix", True)
    finally:
        reg.DATASETS.clear()
        reg.DATASETS.update(saved)
    ok("registry_restored_after_selftest", "_selftest" not in reg.DATASETS)

    print("\n-- 3. an unknown dataset RAISES (never 'emit everything') --")
    try:
        reg.client_payload("health.typo", dirty)
        ok("unknown_dataset_raises", False, "it returned instead of raising")
    except reg.RegistryError:
        ok("unknown_dataset_raises", True)

    print("\n-- 4. shape is preserved; lists and None round-trip --")
    rows = [{"drop_id": 1, "label": "DROP 1", "elevation": "N", "pct": 20,
             "status": "in_progress", "internal_note": "x"},
            {"drop_id": 2, "label": "DROP 2", "elevation": "N", "pct": 0,
             "status": "not_started", "note": "y"}]
    out = reg.client_payload("health.active_drop", rows)
    ok("list_in_list_out", isinstance(out, list) and len(out) == 2)
    ok("list_rows_filtered", all("internal_note" not in r and "note" not in r for r in out))
    ok("none_round_trips", reg.client_payload("health.progress", None) is None)

    print("\n-- 5. internal audience passes through untouched --")
    out = reg.client_payload("health.progress", dirty, audience="internal")
    ok("internal_untouched", out is dirty,
       "the registry constrains what LEAVES the building, not what staff see")

    print("\n-- 6. audience derivation is default-deny --")
    for role in ("admin", "c_suite", "pm", "super", "estimator"):
        ok(f"{role}_is_internal", reg.audience_for(role) == "internal")
    for role in ("client", "architect", "vendor", "some_future_role", None):
        ok(f"{role}_is_external", reg.audience_for(role) == "client",
           "an unrecognised role must be treated as an outsider")

    print("\n-- 7. every registered dataset is non-empty and lowercase-keyed --")
    for name, fields in reg.DATASETS.items():
        ok(f"dataset_sane_{name}", bool(fields) and all(f == f.lower() for f in fields))


def main():
    print("== #281 client field registry + client_payload() ==")
    run()
    n = len(_failures)
    print(f"\n== {'ALL PASS' if n == 0 else str(n) + ' FAILED: ' + ', '.join(_failures)} ==")
    return 0 if n == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
