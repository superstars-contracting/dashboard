#!/usr/bin/env python3
"""Idempotent seed for the FR-BX-001 drop plan — Batch A (#199).

Seeds, per DROP_PLAN_SYSTEM_DESIGN.md §4 / §9 / §9a:
  * 35 drops  (North 1-12, West 13-16, South 17-32, East 33-35);
    active (scaffold_active) = 1,2,3,4,5,33; rest not_started;
    window_count left NULL (not fabricated).
  * the 890 stage template — 11 work steps; the 7-day cure gate is a
    flag on step 8 (per §4 it sits between steps 8 and 9), the structural
    sign-off gate is a flag on step 11 (it follows step 11).
  * drop_stage_status: 35 drops x 11 steps = 385 rows, all not_started
    (actual states are backfilled in Batch E, not invented here).
  * 11 provisional SOV line items, unit_rate NULL (rates arrive with the
    architect AIA/SOV upload — decision #2).
  * 4 paint phases (one per elevation), status not_ready.

Idempotent: INSERT OR IGNORE on natural keys; re-running does not
duplicate or overwrite. Dates are LOCAL (none seeded here are dates;
all date columns left NULL). PII-safe: no names anywhere.
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
PROJECT = "FR-BX-001"
TEMPLATE_NAME = "890 Structural Facade Sequence"

ACTIVE = {1, 2, 3, 4, 5, 33}


def elevation_for(seq: int) -> str:
    if 1 <= seq <= 12:
        return "North"
    if 13 <= seq <= 16:
        return "West"
    if 17 <= seq <= 32:
        return "South"
    return "East"  # 33-35


# (step_no, name, default_working_days, is_signoff_gate, is_cure_gate, note)
STEPS = [
    (1,  "Install scaffold", 2.0, 0, 0, "C-Hook electric on 890 (~2 d/drop)."),
    (2,  "Pressure wash", 1.5, 0, 0, "Remove paint + loose concrete."),
    (3,  "Remove windows & sills", 2.0, 0, 0, "Only loose/rotten; scales with window_count."),
    (4,  "Drill & install rebar", 1.0, 0, 0, '2" embed, 24" o.c., rust-inhibitor coated.'),
    (5,  "Pour new window sills", 1.5, 0, 0, "Level the surface."),
    (6,  "Demo rusted concrete", 4.0, 0, 0, "Sounding + remove all rusted facade concrete."),
    (7,  "Apply Sika Armatec + coat rebar", 2.0, 0, 0, "Bonding / anticorrosion."),
    (8,  "Board & patch", 3.0, 0, 0,
     "Sika patch into formed areas. The poured patch then cures while step 9 (block) "
     "proceeds; the 7-day cure gate is enforced before step 10 (strip forms)."),
    (9,  "Install block + horizontal rebar", 4.0, 0, 0,
     "Build up blocked openings. Proceeds during the patch cure."),
    (10, "Strip forms + quick parge", 1.0, 0, 1,
     "Remove boards; quick parge of front facade. 7-DAY CURE GATE PRECEDES this step "
     "(design section 4 clarification): the poured patch must cure ~7 days before forms "
     "strip — a calendar wait, NOT working days; blocking (step 9) runs during the cure."),
    (11, "Remove scaffold", 1.0, 1, 0,
     "Then relocate to next drop. STRUCTURAL SIGN-OFF GATE FOLLOWS this step: "
     "engineer/AOR sign-off ends the scaffold cycle; drop -> awaiting_paint."),
]

# (sov_code, description, unit) — all provisional, unit_rate NULL
SOV = [
    ("SOV-01", "Scaffold install & rental [provisional - pending architect SOV]", "LS"),
    ("SOV-02", "Pressure wash [provisional - pending architect SOV]", "SF"),
    ("SOV-03", "Window & sill removal [provisional - pending architect SOV]", "EA"),
    ("SOV-04", "Drill & rebar dowels [provisional - pending architect SOV]", "EA"),
    ("SOV-05", "Window sill pour [provisional - pending architect SOV]", "EA"),
    ("SOV-06", "Concrete demo [provisional - pending architect SOV]", "SF"),
    ("SOV-07", "Sika Armatec rebar coating [provisional - pending architect SOV]", "LF"),
    ("SOV-08", "Concrete patch - area x depth - PRIMARY cost driver [provisional - pending architect SOV]", "CF"),
    ("SOV-09", "Block install [provisional - pending architect SOV]", "SF"),
    ("SOV-10", "Parge [provisional - pending architect SOV]", "SF"),
    ("SOV-11", "Paint - elevation rope phase [provisional - pending architect SOV]", "SF"),
]

ELEVATIONS = ["North", "West", "South", "East"]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA busy_timeout=60000;")

    # 0. Verify project exists
    if conn.execute("SELECT 1 FROM projects WHERE project_code=?", (PROJECT,)).fetchone() is None:
        print(f"ERROR: project {PROJECT} not found in projects table", file=sys.stderr)
        conn.close()
        return 1

    # 1. drops (window_count NULL; lifecycle per ACTIVE set)
    for seq in range(1, 36):
        drop_id = f"{PROJECT}-DP{seq}"
        lifecycle = "scaffold_active" if seq in ACTIVE else "not_started"
        conn.execute(
            "INSERT OR IGNORE INTO drops(drop_id, project_code, elevation, sequence_no, "
            "window_count, lifecycle) VALUES (?,?,?,?,NULL,?)",
            (drop_id, PROJECT, elevation_for(seq), seq, lifecycle))

    # 2. stage template + steps
    conn.execute("INSERT OR IGNORE INTO stage_templates(project_code, name) VALUES (?,?)",
                 (PROJECT, TEMPLATE_NAME))
    template_id = conn.execute(
        "SELECT template_id FROM stage_templates WHERE project_code=? AND name=?",
        (PROJECT, TEMPLATE_NAME)).fetchone()[0]
    for step_no, name, days, signoff, cure, note in STEPS:
        conn.execute(
            "INSERT OR IGNORE INTO stage_template_steps(template_id, step_no, name, "
            "default_working_days, is_signoff_gate, is_cure_gate, note) VALUES (?,?,?,?,?,?,?)",
            (template_id, step_no, name, days, signoff, cure, note))

    # 3. drop_stage_status: 35 drops x 11 steps = 385 rows, not_started
    for seq in range(1, 36):
        drop_id = f"{PROJECT}-DP{seq}"
        for step_no, *_ in STEPS:
            conn.execute(
                "INSERT OR IGNORE INTO drop_stage_status(drop_id, step_no, status) "
                "VALUES (?,?, 'not_started')", (drop_id, step_no))

    # 4. provisional SOV (unit_rate NULL)
    for sov_code, desc, unit in SOV:
        conn.execute(
            "INSERT OR IGNORE INTO sov_line_items(project_code, sov_code, description, unit, unit_rate) "
            "VALUES (?,?,?,?,NULL)", (PROJECT, sov_code, desc, unit))

    # 5. paint phases (one per elevation, not_ready)
    for elev in ELEVATIONS:
        conn.execute(
            "INSERT OR IGNORE INTO paint_phases(project_code, elevation, building_wide, method, status) "
            "VALUES (?,?,0,'rope_access','not_ready')", (PROJECT, elev))

    conn.commit()

    # ---- Report counts (PII-safe) ----
    def q(sql, args=()):
        return conn.execute(sql, args).fetchone()[0]

    drops_total = q("SELECT COUNT(*) FROM drops WHERE project_code=?", (PROJECT,))
    by_elev = {e: q("SELECT COUNT(*) FROM drops WHERE project_code=? AND elevation=?", (PROJECT, e))
               for e in ELEVATIONS}
    active_n = q("SELECT COUNT(*) FROM drops WHERE project_code=? AND lifecycle='scaffold_active'", (PROJECT,))
    wc_null = q("SELECT COUNT(*) FROM drops WHERE project_code=? AND window_count IS NULL", (PROJECT,))
    steps_n = q("SELECT COUNT(*) FROM stage_template_steps WHERE template_id=?", (template_id,))
    cure_steps = q("SELECT GROUP_CONCAT(step_no) FROM stage_template_steps WHERE template_id=? AND is_cure_gate=1", (template_id,))
    signoff_steps = q("SELECT GROUP_CONCAT(step_no) FROM stage_template_steps WHERE template_id=? AND is_signoff_gate=1", (template_id,))
    days_sum = q("SELECT ROUND(SUM(default_working_days),2) FROM stage_template_steps WHERE template_id=?", (template_id,))
    dss_n = q("SELECT COUNT(*) FROM drop_stage_status ds JOIN drops d ON ds.drop_id=d.drop_id WHERE d.project_code=?", (PROJECT,))
    sov_n = q("SELECT COUNT(*) FROM sov_line_items WHERE project_code=?", (PROJECT,))
    sov_null = q("SELECT COUNT(*) FROM sov_line_items WHERE project_code=? AND unit_rate IS NULL", (PROJECT,))
    paint_n = q("SELECT COUNT(*) FROM paint_phases WHERE project_code=?", (PROJECT,))

    print("[dropplan-seed] FR-BX-001 seed complete.")
    print(f"  drops: {drops_total}")
    for e in ELEVATIONS:
        print(f"    {e}: {by_elev[e]}")
    print(f"    scaffold_active: {active_n}")
    print(f"    window_count NULL: {wc_null}")
    print(f"  template steps: {steps_n}  (cure-gate step: {cure_steps}; signoff-gate step: {signoff_steps}; sum working_days: {days_sum})")
    print(f"  drop_stage_status rows: {dss_n}")
    print(f"  SOV line items: {sov_n}  (unit_rate NULL: {sov_null})")
    print(f"  paint phases: {paint_n}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
