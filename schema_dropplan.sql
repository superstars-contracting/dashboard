-- =====================================================================
-- Drop Plan System — Batch A schema (#199)
-- =====================================================================
-- Implements the §3 data model of DROP_PLAN_SYSTEM_DESIGN.md (v0.3).
-- Eight NEW tables. Does NOT touch the SUPERSEDED sample tables
-- (drop_plan, drop_activities) — those remain from the old drop_plan_890
-- sample and are out of scope here.
--
-- Conventions:
--  * All operator-facing DATE columns are TEXT, stored as LOCAL
--    'YYYY-MM-DD' (Python date.today() is local) — never UTC
--    (CLAUDE.md dates rule, #74/#77). created_at/updated_at are system
--    insertion markers (repo convention: CURRENT_TIMESTAMP).
--  * quantity_entries + expense_entries are APPEND-ONLY ledgers — totals
--    are computed as SUM(entries); a stored total is never overwritten.
--  * unit_rate stays NULL until the architect AIA/SOV upload (decision #2).
--  * volume_cf is a GENERATED column (area_sf * depth_in / 12) so the
--    patch-volume math is single-source and cannot drift.
--  * Costs/expenses are internal-only; role-gating is enforced at the
--    endpoint layer (Batch B), not here.
--
-- Re-run safe: CREATE TABLE/INDEX IF NOT EXISTS via the split_statements
-- migration pattern.
-- =====================================================================

-- 3.1 drops — one row per drop per project
CREATE TABLE IF NOT EXISTS drops (
  drop_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  elevation TEXT,
  sequence_no INTEGER NOT NULL,
  window_count INTEGER,
  lifecycle TEXT NOT NULL DEFAULT 'not_started'
    CHECK (lifecycle IN ('not_started','scaffold_active','awaiting_paint','closed')),
  structural_signoff_at TEXT,
  closed_at TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);
CREATE INDEX IF NOT EXISTS idx_drops_project   ON drops(project_code, sequence_no);
CREATE INDEX IF NOT EXISTS idx_drops_elevation ON drops(project_code, elevation);

-- 3.2 stage_templates + stage_template_steps (per project)
CREATE TABLE IF NOT EXISTS stage_templates (
  template_id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  name TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(project_code, name),
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE TABLE IF NOT EXISTS stage_template_steps (
  template_id INTEGER NOT NULL,
  step_no INTEGER NOT NULL,
  name TEXT NOT NULL,
  default_working_days REAL,
  is_signoff_gate INTEGER NOT NULL DEFAULT 0,
  is_cure_gate INTEGER NOT NULL DEFAULT 0,
  note TEXT,
  PRIMARY KEY (template_id, step_no),
  FOREIGN KEY (template_id) REFERENCES stage_templates(template_id)
);

-- 3.3 drop_stage_status (per drop x step)
CREATE TABLE IF NOT EXISTS drop_stage_status (
  drop_id TEXT NOT NULL,
  step_no INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'not_started'
    CHECK (status IN ('not_started','in_progress','complete','n_a')),
  started_on TEXT,
  completed_on TEXT,
  working_days_actual REAL,
  note TEXT,
  PRIMARY KEY (drop_id, step_no),
  FOREIGN KEY (drop_id) REFERENCES drops(drop_id)
);

-- 3.4 sov_line_items (per project — AIA Schedule-of-Values spine)
CREATE TABLE IF NOT EXISTS sov_line_items (
  sov_id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  sov_code TEXT NOT NULL,
  description TEXT,
  unit TEXT,
  unit_rate REAL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(project_code, sov_code),
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- 3.5 quantity_entries (APPEND-ONLY; volume_cf generated)
CREATE TABLE IF NOT EXISTS quantity_entries (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
  drop_id TEXT NOT NULL,
  sov_line_item INTEGER NOT NULL,
  step_no INTEGER,
  quantity REAL,
  unit TEXT,
  area_sf REAL,
  depth_in REAL,
  volume_cf REAL GENERATED ALWAYS AS
    (CASE WHEN area_sf IS NOT NULL AND depth_in IS NOT NULL
          THEN area_sf * depth_in / 12.0 ELSE NULL END) VIRTUAL,
  logged_on TEXT NOT NULL,
  logged_by TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  note TEXT,
  FOREIGN KEY (drop_id) REFERENCES drops(drop_id),
  FOREIGN KEY (sov_line_item) REFERENCES sov_line_items(sov_id)
);
CREATE INDEX IF NOT EXISTS idx_qty_drop ON quantity_entries(drop_id, sov_line_item);
CREATE INDEX IF NOT EXISTS idx_qty_logged ON quantity_entries(logged_on);

-- 3.6 expense_entries (APPEND-ONLY; INTERNAL-ONLY money)
CREATE TABLE IF NOT EXISTS expense_entries (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  drop_id TEXT,
  category TEXT CHECK (category IN ('material','labor','equipment','other')),
  amount REAL,
  vendor TEXT,
  logged_on TEXT NOT NULL,
  logged_by TEXT,
  source TEXT NOT NULL DEFAULT 'manual' CHECK (source IN ('manual','expensify')),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  note TEXT,
  FOREIGN KEY (project_code) REFERENCES projects(project_code),
  FOREIGN KEY (drop_id) REFERENCES drops(drop_id)
);
CREATE INDEX IF NOT EXISTS idx_expense_project ON expense_entries(project_code);
CREATE INDEX IF NOT EXISTS idx_expense_drop    ON expense_entries(drop_id);

-- 3.8 paint_phases (elevation-level rope-access paint phase)
CREATE TABLE IF NOT EXISTS paint_phases (
  phase_id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  elevation TEXT,
  building_wide INTEGER NOT NULL DEFAULT 0,
  method TEXT NOT NULL DEFAULT 'rope_access',
  status TEXT NOT NULL DEFAULT 'not_ready'
    CHECK (status IN ('not_ready','ready','in_progress','complete')),
  started_on TEXT,
  completed_on TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(project_code, elevation),
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);
