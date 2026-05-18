-- =====================================================================
-- Visitors table for site-visit tracking. Powers the DCR visitors
-- section (operator-entered, surfaced in the rendered DCR HTML).
--
-- One row per visit. CREATE TABLE IF NOT EXISTS keeps the migration
-- idempotent; apply_visitors_schema.py mirrors the D0 split_statements
-- pattern so re-runs catch already-exists errors as skipped.
-- =====================================================================

CREATE TABLE IF NOT EXISTS visitors (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE NOT NULL,
  project_code TEXT NOT NULL,
  name TEXT,
  company TEXT,
  role TEXT,
  time_in TEXT,
  time_out TEXT,
  purpose TEXT,
  accompanied_by TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_visitors_proj_date ON visitors(project_code, date);
