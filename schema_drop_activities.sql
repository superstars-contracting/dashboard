-- =====================================================================
-- drop_activities — per-drop step template
-- =====================================================================
-- Each drop in `drop_plan` has a standard work sequence (the "game plan")
-- that the operator tracks step-by-step as crews execute. This table
-- stores those activity rows: 6 steps per drop, with Step 5 marked as
-- the sign-off + scaffold-relocation gate.
--
-- Why separate from drop_plan: drop_plan is one row per work location;
-- drop_activities is the time-ordered checklist of WHAT happens at that
-- location. Separating lets the Two-Week Look-Ahead query "which
-- activities are scheduled in the next 10–15 days?" without parsing
-- JSON inside scope_of_work, and lets photo attachment / status updates
-- target individual steps (per the source doc note: "Photos attach per
-- drop as steps are worked").
--
-- gate_after_step: 1 on Step 5 (concrete block install) — when that
-- step completes, the operator triggers the drop sign-off; once signed
-- off, the scaffold relocates to the next drop and Step 6 (paint)
-- follows. Modeling the gate as a flag on the step (not a separate row)
-- preserves the 6-step / ~15-day math the operator already uses.
--
-- Re-run-safe: the table is CREATE IF NOT EXISTS and the seed uses
-- INSERT OR IGNORE on the UNIQUE(drop_id, step_number).
-- =====================================================================

CREATE TABLE IF NOT EXISTS drop_activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drop_id TEXT NOT NULL,
  step_number INTEGER NOT NULL,
  activity TEXT NOT NULL,
  estimated_days REAL NOT NULL,
  gate_after_step INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'pending',
  actual_start_date DATE,
  actual_end_date DATE,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(drop_id, step_number),
  FOREIGN KEY (drop_id) REFERENCES drop_plan(drop_id)
);

CREATE INDEX IF NOT EXISTS idx_drop_activities_drop   ON drop_activities(drop_id);
CREATE INDEX IF NOT EXISTS idx_drop_activities_status ON drop_activities(status);
CREATE INDEX IF NOT EXISTS idx_drop_activities_gate   ON drop_activities(gate_after_step) WHERE gate_after_step = 1;
