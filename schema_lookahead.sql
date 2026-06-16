-- =====================================================================
-- lookahead_activity — the editable Two-Week Look-Ahead schedule (#255)
-- =====================================================================
-- One row per planned activity in a project's rolling look-ahead. This is
-- the SINGLE editable surface the super drags/edits/adds/removes; it is
-- AUTO-DRAFTED from the Drop Plan (drops + drop_stage_status +
-- stage_template_steps) and then adjusted by hand. The same planned-date
-- data later feeds the master-schedule view — single source of truth.
--
-- Why a new table (not extending drop_activities): drop_activities is the
-- canonical per-drop 6-step TEMPLATE (drop_id NOT NULL, UNIQUE(drop_id,
-- step_number), FK to the old sample drop_plan) with real seeded rows.
-- The look-ahead needs PLANNED dates, a draggable source=auto|manual flag,
-- a NULLABLE drop_id (custom project-wide rows like "rain-day cleaning"),
-- and milestone types — distinct concerns. Mixing them would force a risky
-- column-rebuild and conflate the template with the projected schedule.
--
-- Conventions (per CLAUDE.md dates rule): planned_start / planned_finish
-- are TEXT, stored as LOCAL 'YYYY-MM-DD' — never UTC. A milestone
-- (delivery / inspection) has planned_finish == planned_start.
--
-- source: 'auto' rows are (re)projected from the Drop Plan on Refresh.
-- The moment a super drags or edits one, it flips to 'manual' and is
-- LOCKED — a re-draft never overwrites a manual row, and custom rows are
-- always manual. So Refresh re-projects only the untouched auto rows.
--
-- Re-run safe: CREATE TABLE / INDEX IF NOT EXISTS.
-- =====================================================================

CREATE TABLE IF NOT EXISTS lookahead_activity (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  drop_id TEXT,                              -- NULLABLE: custom / project-wide rows
  name TEXT NOT NULL,
  activity_type TEXT NOT NULL DEFAULT 'work'
    CHECK (activity_type IN ('stage','work','delivery','inspection')),
  planned_start TEXT NOT NULL,               -- LOCAL YYYY-MM-DD
  planned_finish TEXT NOT NULL,              -- LOCAL YYYY-MM-DD (== start for a milestone)
  crew TEXT,
  source TEXT NOT NULL DEFAULT 'manual'
    CHECK (source IN ('auto','manual')),
  source_step INTEGER,                       -- stage_template step_no an auto row drafted from
  notes TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX IF NOT EXISTS idx_lookahead_project ON lookahead_activity(project_code, planned_start);
CREATE INDEX IF NOT EXISTS idx_lookahead_drop    ON lookahead_activity(drop_id);
CREATE INDEX IF NOT EXISTS idx_lookahead_source  ON lookahead_activity(project_code, source);
