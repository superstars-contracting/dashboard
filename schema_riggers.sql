-- =====================================================================
-- Multi-rigger support for CoF issuance.
-- Each project has 1+ riggers assigned. When PM issues a CoF, they pick
-- which rigger signs. That rigger's name + license # auto-fill on the
-- back of the generated card.
-- =====================================================================

CREATE TABLE IF NOT EXISTS project_riggers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  rigger_name TEXT NOT NULL,                  -- e.g. "Arun Mal"
  license_number TEXT NOT NULL,               -- e.g. "7652"
  rigger_type TEXT DEFAULT 'Special Rigger',  -- Special Rigger / Master Rigger / Sign Hanger
  signature_path TEXT,                        -- path to scanned signature image
  is_active INTEGER DEFAULT 1,
  is_default INTEGER DEFAULT 0,               -- one default rigger per project for quick-issue
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX IF NOT EXISTS idx_proj_riggers_project ON project_riggers(project_code);
CREATE INDEX IF NOT EXISTS idx_proj_riggers_active ON project_riggers(is_active);

-- Track which rigger signed each card (for audit)
ALTER TABLE cof_cards ADD COLUMN rigger_id INTEGER REFERENCES project_riggers(id);
ALTER TABLE cof_cards ADD COLUMN rigger_name_snapshot TEXT;     -- name as it appeared on the card
ALTER TABLE cof_cards ADD COLUMN rigger_license_snapshot TEXT;  -- license # as it appeared on the card

-- Seed: two sample riggers for SC-2601 so the system has something to test against.
-- Update these (or replace via the dashboard) with the real names + license #s.
INSERT OR IGNORE INTO project_riggers
  (project_code, rigger_name, license_number, rigger_type, is_default, notes)
VALUES
  ('SC-2601', 'Amit Mal', '7652', 'Special Rigger', 1, 'Primary rigger on Mott Haven Restoration'),
  ('SC-2601', 'Arun Mal', '8341', 'Special Rigger', 0, 'Secondary rigger / back-up signer');
