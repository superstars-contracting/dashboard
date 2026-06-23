"""#195d — Structural meta-smoke: catch smoke tests that pollute
production data.

The Kevin-on-5-21 / `test_weekly_hours` regression was a textbook
instance of a class of bug: a smoke section assumes it can mutate a
"test" row, but the "test" row identifier (employee_id index, project
code, date) was reused on real operator data. The mutation happens
inside the smoke, no audit row is written, and the row is silently
corrupted on every smoke run.

The #175 audit was supposed to close this. It missed `test_weekly_hours`
(which uses `emps[2]` + `D_LATE='2026-05-21'`). #195 reopens #175 to
fix that specific instance. THIS meta-smoke is the structural
prevention so the next missed instance surfaces immediately.

Strategy:
  1. Snapshot every "real-data" table that the smoke could touch,
     filtered to rows whose identifiers do NOT carry a synthetic
     prefix (SMK-, SMOKE-, SYN-).
  2. Run the full CRUD smoke suite as a subprocess (so we don't have
     to in-line all 20+ tests here; the subprocess inherits the same
     auth + DB).
  3. Snapshot again.
  4. Diff: anything that changed in the non-synthetic slice is a
     production-data corruption. Report which rows changed, where
     possible name the smoke section by cross-referencing the
     audit_log additions in the same window.

PII discipline: snapshot output is row counts + identifier prefixes +
diff cardinalities. Worker names + rate values + PIN values are
NEVER serialized to the report or to a snapshot file.

Run:
  python tests/smoke_no_production_data_corruption.py
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import sqlite3  # noqa: E402
import db_layer  # noqa: E402  # #260 — snapshot whatever SSC_DB_URL targets (isolated copy or PG test db)

DB = SCRIPT_DIR / "superstars.db"
# #241 — the standard gate runs BOTH suites inside the snapshot window:
# the per-section CRUD smoke and the worker-lifecycle smoke. Any suite
# added here inherits the anti-pollution diff for free.
SMOKE_SCRIPTS = [
    SCRIPT_DIR / "tests" / "smoke_crud_data_integrity.py",
    SCRIPT_DIR / "tests" / "smoke_worker_lifecycle.py",
]
VENV_PY = SCRIPT_DIR / "venv" / "Scripts" / "python.exe"

# Identifier prefixes that indicate a row is synthetic (smoke-owned)
# and therefore expected to appear/disappear during a smoke run.
# #241 — the repo-wide synthetic id band (W-9xxx workers / E-99xxx
# employees, per the standing test-data rules) is part of the filter:
# real worker ids are sequentially allocated (W-00xx at today's scale),
# so a W-9/E-99 id can only be smoke-owned. Without these, a smoke
# purging its own stale residue false-flags as production pollution.
SYNTHETIC_PREFIXES = ("SMK-", "SMOKE-", "SYN-", "SMK_", "W-9", "E-99")

# Tables to snapshot. Each entry is:
#   (table, identifying_columns, optional_value_columns_for_change_detection)
# identifying_columns combine to form the row's primary identity. If
# any identifying column is synthetic-prefixed, the row is treated as
# expected smoke residue.
TABLES_TO_SNAPSHOT: list[Tuple[str, list[str], list[str]]] = [
    ("sign_in_log", ["employee_id", "project_code", "date"], ["time_in", "time_out"]),
    ("employees", ["employee_id"], ["worker_id", "name", "trade"]),
    # worker_rates: hourly_rate IS PII (comp data per CLAUDE.md). Detect
    # row presence + identity only — value is never serialized here.
    ("worker_rates", ["employee_id", "effective_from"], ["effective_to"]),
    ("certifications", ["employee_id", "cert_type_id", "card_number"], ["expiration_date"]),
    ("report_index", ["report_id", "project_code", "report_date"], ["status", "stale", "no_work"]),
    # audit_log: every smoke writes some rows; we expect non-empty diff.
    # We track that EVERY new audit_log row is either against a
    # synthetic target_id, OR is from a known-public action that is
    # operator-attributable (e.g., from the apply scripts that run
    # outside the smoke run). Inside the smoke window, anything against
    # a NON-synthetic target is suspicious.
    ("audit_log", ["id"], ["action", "target_id"]),
    # cof_cards, company_id_cards: smoke issues credentials but the
    # #175 audit moved that to synthetic workers. Track to confirm.
    ("cof_cards", ["card_id"], ["employee_id", "status"]),
    ("company_id_cards", ["card_id"], ["employee_id", "status"]),
    ("project_assignments", ["employee_id", "project_code"], ["status"]),
    # construction_agent_provenance (#198): the Construction Specialist
    # Agent's audit trail. This table legitimately GROWS during normal
    # operator use (one row per substantive Q&A) — that growth is NOT
    # corruption. It is snapshotted here as a backstop, not because the
    # CRUD smoke writes to it (it does not): the construction-agent path
    # is exercised only by tests/smoke_construction_agent.py, never by
    # smoke_crud_data_integrity.py (the subprocess this meta-smoke runs).
    # So within a meta-smoke run the before/after slices are identical
    # and this table reports "clean" — no false failure. The value of
    # snapshotting it: if any FUTURE smoke ever writes a NON-synthetic
    # provenance row during the CRUD run, it surfaces immediately.
    # Identity = interaction_id (TEXT) so SMK-/SYN-prefixed test rows are
    # auto-filtered as expected smoke residue. value_cols are status-only
    # (never question_text / answer_summary, which stay un-serialized).
    ("construction_agent_provenance", ["interaction_id"],
     ["operator_disposition", "corpus_version"]),
    # Drop Plan tables (#199 Batch A). Same backstop logic as the
    # provenance table above: the CRUD smoke subprocess never touches any
    # drop-plan table, so within a meta-smoke run before==after and each
    # reports "clean" — no false failure. They're snapshotted so that if a
    # FUTURE smoke writes a NON-synthetic drop-plan row during the CRUD
    # run, it surfaces immediately. Identity columns lead with a TEXT
    # natural key (drop_id / sov_code / elevation / template name) so the
    # drop-plan smoke's SMK--prefixed rows are auto-filtered as expected
    # residue. Money lives in expense_entries.amount — NOT serialized here
    # (value_cols stay status/category only, mirroring worker_rates).
    ("drops", ["drop_id"], ["lifecycle", "sequence_no", "elevation"]),
    ("stage_templates", ["project_code", "name"], []),
    ("stage_template_steps", ["template_id", "step_no"], ["name"]),
    ("drop_stage_status", ["drop_id", "step_no"], ["status", "started_on", "completed_on"]),
    ("sov_line_items", ["project_code", "sov_code"], ["unit"]),
    ("quantity_entries", ["entry_id", "drop_id"], ["quantity", "logged_on"]),
    ("expense_entries", ["entry_id", "drop_id"], ["category", "logged_on"]),
    ("paint_phases", ["phase_id", "project_code", "elevation"], ["status"]),
    # dashboard_layouts (#209): per-user widget drag/resize positions. Same
    # backstop logic as the drop-plan tables — the CRUD smoke subprocess never
    # writes layouts, so within a meta-smoke run before==after and this reports
    # "clean". Identity = (user_id, page_key); value_cols=[] (presence only) so
    # benign updated_at churn never false-flags. layout_json holds widget ids +
    # positions ONLY (no PII), so it is not serialized here. Surfaces immediately
    # if any FUTURE smoke writes a layout row for a real user during the CRUD run.
    ("dashboard_layouts", ["user_id", "page_key"], []),
    # Expense / Spend module (#218 Batch A). Same backstop logic as the
    # drop-plan tables: the CRUD smoke subprocess never writes any expense
    # table, so within a meta-smoke run before==after and each reports
    # "clean" — no false failure. They're snapshotted so that if a FUTURE
    # smoke writes a NON-synthetic expense row during the CRUD run, it
    # surfaces immediately. Identity leads with vendor/doc_number (which the
    # expense smoke prefixes SMK-) so synthetic rows auto-filter as expected
    # residue. value_cols are status/category/class ONLY — money (total,
    # unit_price, extended_price) and receipt_image_path are NEVER serialized
    # here (cost-data + path discipline, mirroring worker_rates).
    ("expenses", ["vendor", "doc_number", "project_code"], ["status", "category"]),
    ("expense_line_items", ["expense_id", "sort_order"], ["product_class"]),
    ("expense_class_alias", ["vendor", "item_key"], ["product_class"]),
    # Labor Rates redesign (#220). COMP DATA — value_cols are status/trade ONLY;
    # the rate values (current_rate / new_rate / old_rate) are NEVER serialized
    # here, mirroring worker_rates above. Backstop logic: the CRUD smoke never
    # writes these, so within a meta run before==after -> clean. Surfaces if a
    # FUTURE smoke leaves a NON-synthetic labor-rate row during the CRUD run.
    ("labor_worker_state", ["worker_id"], ["status", "trade"]),
    ("labor_rate_change", ["id"], ["status", "worker_id"]),
    # Project Documents (#229 Batch A). Same backstop logic as the drop-plan tables:
    # the CRUD smoke subprocess never writes these, so within a meta run before==after
    # -> each reports "clean". Snapshotted so a FUTURE smoke leaving a NON-synthetic row
    # surfaces. Identity leads with project_code (the doc smoke prefixes SMK-) so
    # synthetic rows auto-filter as expected residue. value_cols are category ONLY —
    # file_path / title / file_name are NEVER serialized here (path + PII discipline,
    # mirroring receipt_image_path / worker_rates above).
    ("project_documents", ["project_code", "id"], ["category"]),
    # document_requirements: a STATIC seeded reference table (like cert_types) — the CRUD
    # smoke never touches it, so before==after -> clean. Identity = the natural key.
    ("document_requirements", ["category", "requirement_key"], ["sort_order"]),
    # Field Photos (#235 Phase 1). Same backstop logic as the drop-plan tables:
    # the CRUD smoke subprocess never writes field_photos, so within a meta run
    # before==after -> clean. Snapshotted so a FUTURE smoke leaving a NON-synthetic
    # photo row during the CRUD run surfaces. Identity leads with project_code (the
    # field-photos smoke prefixes SMK-FOTO) so synthetic rows auto-filter as expected
    # residue. value_cols are drop_id/stage ONLY — file_path / thumb_path / file_name /
    # caption are NEVER serialized here (path + PII discipline, mirroring the docs +
    # receipt_image_path rules above).
    ("field_photos", ["project_code", "id"], ["drop_id", "stage"]),
]


def _is_synthetic(value) -> bool:
    """True iff `value` carries a recognized synthetic prefix."""
    if value is None:
        return False
    s = str(value)
    return any(s.startswith(p) for p in SYNTHETIC_PREFIXES)


def snapshot_table(
    conn: sqlite3.Connection,
    table: str,
    id_cols: list[str],
    value_cols: list[str],
) -> Dict[Tuple, str]:
    """Return {identity_tuple: value_hash} for every row in `table`.

    The hash is over the value-columns only (sorted by name, stable
    JSON). PII discipline: value_cols here are explicit, narrow lists
    that NEVER include worker names, phone numbers, photo paths, or
    rate amounts — they're identity/status fields used to detect
    "row changed" without serializing the sensitive content.
    """
    sql_cols = ",".join([*id_cols, *value_cols])
    rows = conn.execute(f"SELECT {sql_cols} FROM {table}").fetchall()
    out: Dict[Tuple, str] = {}
    for r in rows:
        identity = tuple(r[i] for i in range(len(id_cols)))
        vals = tuple(r[i] for i in range(len(id_cols), len(id_cols) + len(value_cols)))
        h = hashlib.sha256(
            json.dumps(vals, default=str, sort_keys=True).encode("utf-8")
        ).hexdigest()[:16]
        out[identity] = h
    return out


def snapshot_all() -> Dict[str, Dict[Tuple, str]]:
    """Snapshot every monitored table. Returns {table: {id: hash}}."""
    conn = db_layer.connect()
    try:
        return {
            t: snapshot_table(conn, t, id_cols, val_cols)
            for (t, id_cols, val_cols) in TABLES_TO_SNAPSHOT
        }
    finally:
        conn.close()


def diff_snapshots(before: dict, after: dict) -> dict:
    """Per-table diff. Returns {table: {added, removed, changed}}.

    Each value is a list of identity tuples filtered to NON-synthetic
    rows. Synthetic rows (SMK-/SMOKE-/SYN- prefixed) are excluded
    because their churn is expected during smoke runs.
    """
    out: dict = {}
    for table in before.keys():
        b = before[table]
        a = after[table]
        added_keys = set(a) - set(b)
        removed_keys = set(b) - set(a)
        changed_keys = {k for k in (set(b) & set(a)) if b[k] != a[k]}

        def _nonsynth(keys):
            res = []
            for k in keys:
                if not any(_is_synthetic(part) for part in k):
                    res.append(k)
            return res

        out[table] = {
            "added": _nonsynth(added_keys),
            "removed": _nonsynth(removed_keys),
            "changed": _nonsynth(changed_keys),
        }
    return out


def is_diff_clean(diff: dict) -> bool:
    """True iff every table's non-synthetic diff is empty.

    audit_log changes against operator-attributable actions ARE
    expected (smoke section setup occasionally inserts an audit row
    for a real worker via an API path). Filter those out: an
    audit_log addition is considered clean if the new row's
    target_id is synthetic.
    """
    for table, parts in diff.items():
        for kind in ("added", "removed", "changed"):
            if parts.get(kind):
                return False
    return True


def format_diff_report(diff: dict) -> str:
    """Human-readable diff summary. Identifier tuples are printed
    verbatim — they're internal IDs (employee_id, project_code,
    report_date), not PII."""
    lines = []
    for table, parts in diff.items():
        added = parts["added"]
        removed = parts["removed"]
        changed = parts["changed"]
        if added or removed or changed:
            lines.append(
                f"  [{table}]  added={len(added)}  removed={len(removed)}  changed={len(changed)}"
            )
            for k in added[:10]:
                lines.append(f"    + added: {k}")
            for k in removed[:10]:
                lines.append(f"    - removed: {k}")
            for k in changed[:10]:
                lines.append(f"    ~ changed: {k}")
            if (len(added) + len(removed) + len(changed)) > 30:
                lines.append("    ... (truncated)")
        else:
            lines.append(f"  [{table}]  clean")
    return "\n".join(lines)


def main() -> int:
    print("#195d — Meta-smoke: snapshot real-data tables, run the "
          "full CRUD smoke, diff for non-synthetic pollution.\n")

    # 0a. #247 — self-test the path-guard DETECTOR every run (so a silently
    # broken scanner can't pass the gate green). Catch-positive + no false
    # positive on the legit '*_url' shape.
    import _smoke_auth as _sa
    _catch = []
    _sa._scan_json_for_paths(
        {"folder_path": "x", "data": [{"scan_path": "y"}], "html_url": "/api/c/live",
         "nested": {"folder": "z"}}, "SELFTEST", _catch)
    _caught_keys = {h.split("key '")[1].rstrip("'") for h in _catch if "key '" in h}
    assert _caught_keys == {"folder_path", "data[0].scan_path", "nested.folder"}, \
        f"path-guard self-test FAILED — caught {_caught_keys}"
    print("  path-guard self-test: detector catches path keys, ignores *_url — OK")

    # 0. #247 — arm the response *_path guard for every suite in the gate.
    # _smoke_auth (imported by each subprocess) hooks the patched session and
    # appends any path-pattern key / path-like value it sees in ANY JSON
    # response to this file; step 5 fails the gate on hits.
    guard_file = SCRIPT_DIR / "tests" / "_path_guard_hits.txt"
    try:
        guard_file.unlink()
    except OSError:
        pass
    os.environ["PATH_GUARD_HITS"] = str(guard_file)

    # 1. Before snapshot
    t0 = time.time()
    before = snapshot_all()
    print(f"  before snapshot: "
          f"{sum(len(v) for v in before.values())} rows across "
          f"{len(before)} tables  ({time.time() - t0:.2f}s)")

    # 2. Run every gated smoke suite as a subprocess (CRUD + lifecycle).
    for script in SMOKE_SCRIPTS:
        t1 = time.time()
        proc = subprocess.run(
            [str(VENV_PY), str(script)],
            capture_output=True, text=True, timeout=600,
            cwd=str(SCRIPT_DIR),
        )
        print(f"  {script.name} returncode={proc.returncode}  "
              f"({time.time() - t1:.1f}s)")
        if proc.returncode != 0:
            # Surface the smoke's own failure first; pollution check is
            # secondary if the suite outright failed.
            print(f"  {script.name} FAILED — last 20 stdout lines:")
            for line in (proc.stdout or "").splitlines()[-20:]:
                print(f"    {line}")
            print("  stderr (last 10):")
            for line in (proc.stderr or "").splitlines()[-10:]:
                print(f"    {line}")
            return 1

    # 3. After snapshot
    after = snapshot_all()
    print(f"  after snapshot:  "
          f"{sum(len(v) for v in after.values())} rows across "
          f"{len(after)} tables")

    # 4. Diff
    diff = diff_snapshots(before, after)
    clean = is_diff_clean(diff)
    print("\n  Non-synthetic-row diff (anything here is a smoke "
          "polluting production data):")
    print(format_diff_report(diff))

    # 5. #247 — response *_path guard verdict. Independent of the row diff:
    # a path field crossing the wire fails the gate even with clean data.
    path_hits = []
    if guard_file.exists():
        path_hits = sorted(set(
            ln for ln in guard_file.read_text(encoding="utf-8").splitlines() if ln.strip()))
    if path_hits:
        print(f"\n  PATH-GUARD FAIL — {len(path_hits)} *_path leak(s) crossed the wire:")
        for h in path_hits:
            print(f"    {h}")
        return 3
    print("  path-guard: zero path keys/values in any captured JSON response")

    print(f"\n  TOTAL: {time.time() - t0:.1f}s")
    if clean:
        print("\n  PASS — every smoke section left zero non-synthetic "
              "rows added/removed/changed.")
        return 0
    else:
        print("\n  FAIL — at least one non-synthetic row was "
              "touched. Surface to operator IMMEDIATELY — likely "
              "candidate is a smoke that targets a real worker / "
              "real date / real project; see #175 audit pattern.")
        return 2


if __name__ == "__main__":
    sys.exit(main())
