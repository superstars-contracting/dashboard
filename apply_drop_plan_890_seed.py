#!/usr/bin/env python3
"""Seed the FR-BX-001 (890 E 135th St) drop plan + per-drop activities.

Source of truth: drop_plan_890.md (the operator-authored layout). 34
drops across four elevations:
  - North (East 135th St):  Drops 1–12        (12 drops)
  - West (Walnut Ave):      Drops 13–16       (4 drops; #16 = garage bay)
  - South (rear yard):      Drops 17–31       (15 drops; incl. brick
                                                 smokestack faces +
                                                 rear wing)
  - East (Locust Ave):      Drops 32–34       (3 drops)

Per drop, the standard "game plan" is 6 steps + a sign-off gate after
Step 5; the scaffold relocates once the drop is signed off, then Step
6 (paint) follows. ~15 working days per drop excluding the scaffold
move (see drop_plan_890.md):

  1. Remove windows                          2 days
  2. Sounding & demo of front facade         2 days
  3. Install rebar w/ epoxy + level sills    2 days
  4. Facade patches                          4 days
  5. Concrete block install                  4 days  [GATE]
  6. Paint                                   1 day

What this script does:
  1. Applies schema_drop_activities.sql (idempotent — CREATE IF NOT
     EXISTS / CREATE INDEX IF NOT EXISTS via split_statements pattern).
  2. INSERT OR IGNORE 34 rows into drop_plan (one per DP-001..DP-034).
  3. INSERT OR IGNORE 6 rows per drop into drop_activities (204 rows
     total) — the standard sequence. Each drop starts with all steps
     status='pending'.

Re-run safe. Idempotent. Doesn't overwrite an existing drop or
activity row if codes match — preserves any operator edits.
"""
import sqlite3
import sys
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_drop_activities.sql"

PROJECT_CODE = "FR-BX-001"

# Elevation assignment per the source doc. Drop ranges are inclusive
# on both ends.
ELEVATIONS = [
    ("North (East 135th St)",  range(1,  13)),   # 12 drops
    ("West (Walnut Ave)",      range(13, 17)),   # 4 drops
    ("South (rear yard)",      range(17, 32)),   # 15 drops
    ("East (Locust Ave)",      range(32, 35)),   # 3 drops
]

# Per-drop notes for the few drops the source doc calls out individually.
# Everything else gets the standard project-level scope note.
DROP_NOTES = {
    16: "Garage bay (per drop_plan_890.md).",
    # Doc says South includes brick smokestack faces + rear wing —
    # without a per-drop breakdown the operator can tag specific
    # numbers later as work proceeds; flag the range so they know
    # to refine.
    17: "South elevation — includes brick smokestack faces + rear wing (per drop_plan_890.md). Refine per drop as work proceeds.",
}

# Standard scope_of_work text on every drop_plan row. The detailed
# step-by-step lives in drop_activities; this is the operator-facing
# summary that shows in the Drop Plan UI without joining.
STANDARD_SCOPE = (
    "Standard facade-restoration sequence (6 steps, ~15 working days). "
    "Details + status per step in drop_activities."
)

# (step_number, activity, estimated_days, gate_after_step)
# The sign-off + scaffold-relocation gate fires after Step 5 — once
# Step 5 is complete and the drop is signed off, scaffold relocates
# and Step 6 (paint) follows.
ACTIVITY_TEMPLATE = [
    (1, "Remove windows",                       2.0, 0),
    (2, "Sounding & demo of front facade",      2.0, 0),
    (3, "Install rebar w/ epoxy + level sills", 2.0, 0),
    (4, "Facade patches",                       4.0, 0),
    (5, "Concrete block install",               4.0, 1),  # GATE
    (6, "Paint",                                1.0, 0),
]


def split_statements(sql_text):
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


def drop_id_for(n):
    return f"DP-{n:03d}"


def elevation_for(n):
    for label, rng in ELEVATIONS:
        if n in rng:
            return label
    return None  # shouldn't happen for 1..34


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # ---- 1) Apply the schema migration (idempotent) -------------------
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate column" in msg:
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    if failed:
        conn.rollback()
        conn.close()
        return 1

    # Confirm the project exists (FK target).
    project_ok = conn.execute(
        "SELECT 1 FROM projects WHERE project_code = ?", (PROJECT_CODE,)
    ).fetchone()
    if not project_ok:
        print(f"ERROR: project {PROJECT_CODE!r} not found in projects table", file=sys.stderr)
        conn.close()
        return 1

    # Total estimated days per drop (sum of activity days) — surface in
    # drop_plan.estimated_duration_days so the existing column carries
    # the same number the activity template implies.
    est_total = int(round(sum(a[2] for a in ACTIVITY_TEMPLATE)))

    # ---- 2) Insert 34 drop_plan rows (INSERT OR IGNORE) --------------
    drop_inserted = drop_ignored = 0
    for n in range(1, 35):
        did = drop_id_for(n)
        elev = elevation_for(n)
        notes = DROP_NOTES.get(n)
        cur = conn.execute(
            "INSERT OR IGNORE INTO drop_plan "
            "  (drop_id, project_code, elevation, scope_of_work, "
            "   estimated_duration_days, status, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (did, PROJECT_CODE, elev, STANDARD_SCOPE,
             est_total, 'pending', notes),
        )
        if cur.rowcount == 1:
            drop_inserted += 1
        else:
            drop_ignored += 1

    # ---- 3) Insert 6 activities per drop (INSERT OR IGNORE) ----------
    act_inserted = act_ignored = 0
    for n in range(1, 35):
        did = drop_id_for(n)
        for step, activity, days, gate in ACTIVITY_TEMPLATE:
            cur = conn.execute(
                "INSERT OR IGNORE INTO drop_activities "
                "  (drop_id, step_number, activity, estimated_days, "
                "   gate_after_step, status) "
                "VALUES (?, ?, ?, ?, ?, 'pending')",
                (did, step, activity, days, gate),
            )
            if cur.rowcount == 1:
                act_inserted += 1
            else:
                act_ignored += 1
    conn.commit()

    # ---- 4) Report ----------------------------------------------------
    by_elev = Counter()
    for r in conn.execute(
        "SELECT elevation, COUNT(*) FROM drop_plan "
        "WHERE project_code = ? GROUP BY elevation", (PROJECT_CODE,)
    ):
        by_elev[r[0]] = r[1]
    total_drops = conn.execute(
        "SELECT COUNT(*) FROM drop_plan WHERE project_code = ?", (PROJECT_CODE,)
    ).fetchone()[0]
    total_acts = conn.execute(
        "SELECT COUNT(*) FROM drop_activities da "
        "JOIN drop_plan dp ON dp.drop_id = da.drop_id "
        "WHERE dp.project_code = ?", (PROJECT_CODE,)
    ).fetchone()[0]
    gates = conn.execute(
        "SELECT COUNT(*) FROM drop_activities da "
        "JOIN drop_plan dp ON dp.drop_id = da.drop_id "
        "WHERE dp.project_code = ? AND da.gate_after_step = 1",
        (PROJECT_CODE,)
    ).fetchone()[0]

    print(f"[drop-plan] schema migration: applied={applied} skipped={skipped} failed={failed}")
    print(f"[drop-plan] drop_plan rows: inserted={drop_inserted} ignored={drop_ignored} (total {total_drops})")
    print(f"[drop-plan] drop_activities rows: inserted={act_inserted} ignored={act_ignored} (total {total_acts})")
    print(f"[drop-plan] sign-off gates: {gates} (one per drop, on Step 5)")
    print(f"[drop-plan] estimated days per drop: {est_total}")
    print(f"[drop-plan] by elevation:")
    for elev, n in sorted(by_elev.items()):
        print(f"             • {elev}: {n}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
