-- =====================================================================
-- Project Assignments — links org-level workers to specific projects.
-- One worker can be assigned to multiple projects over time.
-- =====================================================================

CREATE TABLE IF NOT EXISTS project_assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  employee_id TEXT NOT NULL,
  role_on_project TEXT,
  start_date DATE,
  end_date DATE,
  status TEXT DEFAULT 'active',  -- active, off-rolled, transferred, completed
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code),
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);

CREATE INDEX IF NOT EXISTS idx_proj_assign_project ON project_assignments(project_code);
CREATE INDEX IF NOT EXISTS idx_proj_assign_employee ON project_assignments(employee_id);
CREATE INDEX IF NOT EXISTS idx_proj_assign_status ON project_assignments(status);

-- Add a status field on projects so the Company Console can show active vs. completed
ALTER TABLE projects ADD COLUMN status TEXT DEFAULT 'active';
ALTER TABLE projects ADD COLUMN client TEXT;
ALTER TABLE projects ADD COLUMN start_date DATE;
ALTER TABLE projects ADD COLUMN target_completion DATE;
