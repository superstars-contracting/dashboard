-- =====================================================================
-- NYC Compliance Watch — schema additions
-- Tables for caching public DOB / OpenData pulls.
-- =====================================================================

-- Augment projects table with NYC identifiers (only added once)
ALTER TABLE projects ADD COLUMN bin TEXT;
ALTER TABLE projects ADD COLUMN bbl TEXT;
ALTER TABLE projects ADD COLUMN borough TEXT;
ALTER TABLE projects ADD COLUMN house_number TEXT;
ALTER TABLE projects ADD COLUMN street_name TEXT;
ALTER TABLE projects ADD COLUMN zip_code TEXT;

-- Permits issued (DOB Permit Issuance, Socrata: ipu4-2q9a)
CREATE TABLE IF NOT EXISTS dob_permits (
  permit_id TEXT PRIMARY KEY,             -- job_filing_number + work_permit
  project_code TEXT,
  bin TEXT,
  job_filing_number TEXT,
  work_permit TEXT,
  permit_type TEXT,
  permit_subtype TEXT,
  filing_status TEXT,
  issuance_date DATE,
  expiration_date DATE,
  filing_date DATE,
  work_type TEXT,
  permittee_name TEXT,
  permittee_business_name TEXT,
  permittee_license_number TEXT,
  raw_json TEXT,                          -- full record for forensics
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX IF NOT EXISTS idx_dob_permits_project ON dob_permits(project_code);
CREATE INDEX IF NOT EXISTS idx_dob_permits_expiration ON dob_permits(expiration_date);

-- Violations (DOB Violations + ECB Violations, Socrata: 6bgk-3dad / 3dad-nc3d)
CREATE TABLE IF NOT EXISTS dob_violations (
  violation_id TEXT PRIMARY KEY,          -- isn_dob_bis_viol or ecb_violation_number
  project_code TEXT,
  bin TEXT,
  source TEXT,                            -- 'DOB' or 'ECB'
  violation_number TEXT,
  violation_type TEXT,
  violation_category TEXT,
  issue_date DATE,
  hearing_date DATE,
  status TEXT,                            -- ACTIVE, DISPOSED, RESOLVED, etc.
  description TEXT,
  penalty_imposed REAL,
  penalty_paid REAL,
  raw_json TEXT,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX IF NOT EXISTS idx_dob_violations_project ON dob_violations(project_code);
CREATE INDEX IF NOT EXISTS idx_dob_violations_status ON dob_violations(status);

-- Complaints (DOB Complaints Received, Socrata: eabe-havv)
CREATE TABLE IF NOT EXISTS dob_complaints (
  complaint_id TEXT PRIMARY KEY,          -- complaint_number
  project_code TEXT,
  bin TEXT,
  complaint_number TEXT,
  complaint_category TEXT,
  status TEXT,                            -- ACTIVE, CLOSED
  date_entered DATE,
  disposition_date DATE,
  disposition_code TEXT,
  inspection_date DATE,
  raw_json TEXT,
  fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX IF NOT EXISTS idx_dob_complaints_project ON dob_complaints(project_code);
CREATE INDEX IF NOT EXISTS idx_dob_complaints_status ON dob_complaints(status);

-- Pulse log: every time we hit Socrata, log it
CREATE TABLE IF NOT EXISTS dob_pulse_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  project_code TEXT,
  dataset TEXT,                           -- permits, violations, complaints
  bin_queried TEXT,
  records_returned INTEGER,
  status_code INTEGER,
  duration_ms INTEGER,
  error_message TEXT
);

CREATE INDEX IF NOT EXISTS idx_dob_pulse_runs_run_at ON dob_pulse_runs(run_at);
