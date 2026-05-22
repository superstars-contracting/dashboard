#!/usr/bin/env python3
"""Idempotent migration for Reports Phase 1 shared spine.

Applies schema_project_type.sql:
- projects.project_type TEXT NOT NULL DEFAULT 'generic'
  CHECK IN (facade, garage, interiors, ira, generic)
- rfi_log.location_unit / location_id / scope_category /
  schedule_impact_flag / cost_impact_flag
- idx_rfi_log_project_status, idx_rfi_log_location

Then backfills FR-BX-001 to project_type='facade' per the handoff (890 E
135th is a facade restoration project). Other pre-existing projects keep
the 'generic' default — the operator (or a future migration) reclassifies
them deliberately.

PII-safe: only project_codes / column counts / migration counters printed.

Read alongside:
- construction_builds_spec.json (source of truth for project_types)
- project_type_config.py (Python single-source mirror)
- REPORTS_PHASE1_SHARED_SPINE.md (Phase 2-4 consumer guide)
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_project_type.sql"

# 890 E 135th / FR-BX-001 is the live facade restoration project. Other
# pre-existing project_codes (if any) stay 'generic' so the operator
# reclassifies them deliberately.
PROJECT_TYPE_BACKFILL = {
    'FR-BX-001': 'facade',
}


def split_statements(sql_text):
    """Drop comments + split on ';'. Same pattern as apply_riggers_schema."""
    cleaned = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[:line.index("--")]
        cleaned.append(line)
    text = "\n".join(cleaned)
    out, buf = [], []
    for ch in text:
        buf.append(ch)
        if ch == ";":
            s = "".join(buf).strip()
            if s and s != ";":
                out.append(s)
            buf = []
    return out


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    # ---- 1. SCHEMA ----
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:140]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()

    # ---- 2. BACKFILL ----
    backfilled = []
    for project_code, ptype in PROJECT_TYPE_BACKFILL.items():
        row = conn.execute(
            "SELECT project_type FROM projects WHERE project_code = ?",
            (project_code,)
        ).fetchone()
        if not row:
            print(f"[backfill] {project_code} not found — skipping")
            continue
        current = row[0]
        if current == ptype:
            print(f"[backfill] {project_code} already = '{ptype}' — skipping")
            continue
        conn.execute(
            "UPDATE projects SET project_type = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE project_code = ?",
            (ptype, project_code)
        )
        backfilled.append((project_code, current, ptype))
    conn.commit()

    # ---- 3. REPORT ----
    print(f"[schema]   applied={applied} skipped={skipped} failed={failed}")
    if backfilled:
        for code, before, after in backfilled:
            print(f"[backfill] {code}: project_type {before!r} -> {after!r}")
    # Verify final state (PII-safe — project_code + project_type only)
    rows = conn.execute(
        "SELECT project_code, project_type FROM projects ORDER BY project_code"
    ).fetchall()
    print(f"[verify]   {len(rows)} project(s):")
    for r in rows:
        print(f"           - {r[0]} project_type={r[1]!r}")
    # Confirm rfi_log columns landed
    rfi_cols = [r[1] for r in conn.execute("PRAGMA table_info(rfi_log)").fetchall()]
    expected_new = ['location_unit', 'location_id', 'scope_category',
                    'schedule_impact_flag', 'cost_impact_flag']
    missing = [c for c in expected_new if c not in rfi_cols]
    if missing:
        print(f"[verify]   WARNING: rfi_log missing columns: {missing}")
        failed += 1
    else:
        print(f"[verify]   rfi_log has all 5 new spine columns")

    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
