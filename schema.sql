-- SuperStars Construction Management Database Schema
-- Generated for Phase 2A: SQLite migration
-- Conventions:
--   - Snake_case table names and columns
--   - All datetime values in ISO 8601 format (YYYY-MM-DD or YYYY-MM-DD HH:MM:SS)
--   - Boolean fields use TEXT with CHECK constraint (Y/N/N-A) where workbook has them
--   - All tables include created_at and updated_at for provenance tracking
--   - Foreign keys declared inline with REFERENCES
--   - Indexes added for common query patterns and foreign key lookups

-- Core: Projects
CREATE TABLE projects (
  project_code TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  address TEXT,
  city_zip TEXT,
  superintendent TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Core: Employees
CREATE TABLE employees (
  employee_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  trade TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily Operations: Sign In Log
CREATE TABLE sign_in_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE NOT NULL,
  employee_id TEXT NOT NULL,
  project_code TEXT NOT NULL,
  time_in TEXT,
  time_out TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX idx_sign_in_log_date_project ON sign_in_log(date, project_code);
CREATE INDEX idx_sign_in_log_employee ON sign_in_log(employee_id);

-- Daily Operations: Weather Log
CREATE TABLE weather_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE NOT NULL,
  project_code TEXT NOT NULL,
  am_temp_f REAL,
  pm_temp_f REAL,
  conditions TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Daily Operations: Settings
CREATE TABLE settings (
  setting_name TEXT PRIMARY KEY,
  value TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Daily Operations: Report Index
CREATE TABLE report_index (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  report_date DATE NOT NULL,
  project_code TEXT NOT NULL,
  report_type TEXT,
  status TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Daily Operations: Work Log
CREATE TABLE work_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE NOT NULL,
  project_code TEXT NOT NULL,
  scope_of_work TEXT,
  trades_working TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Daily Operations: Deliveries
CREATE TABLE deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE,
  project_code TEXT,
  description TEXT,
  delivered_by TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Daily Operations: Equipment Log
CREATE TABLE equipment_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE,
  project_code TEXT,
  equipment_type TEXT,
  status TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Safety: Toolbox Talk Records
CREATE TABLE toolbox_talk_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE,
  project_code TEXT,
  talk_id TEXT,
  facilitator TEXT,
  attendees TEXT,
  duration_minutes INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Safety: Safety Events
CREATE TABLE safety_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE NOT NULL,
  project_code TEXT,
  event_type TEXT,
  severity TEXT,
  description TEXT,
  reported_by TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Quality: Issues Log
CREATE TABLE issues (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE,
  project_code TEXT,
  description TEXT,
  owner TEXT,
  status TEXT,
  due_date DATE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Quality: Inspections
CREATE TABLE inspections (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE,
  project_code TEXT,
  inspector_name TEXT,
  scope TEXT,
  result TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Documentation: Photos
CREATE TABLE photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date DATE,
  project_code TEXT,
  file_path TEXT,
  description TEXT,
  uploaded_by TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Certifications: Certification Types
CREATE TABLE cert_types (
  cert_type_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  validity_months INTEGER,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Certifications: Employee Certifications
CREATE TABLE certifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL,
  cert_type_id TEXT NOT NULL,
  date_obtained DATE,
  expiration_date DATE,
  status TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
  FOREIGN KEY (cert_type_id) REFERENCES cert_types(cert_type_id)
);

CREATE INDEX idx_certifications_employee ON certifications(employee_id);
CREATE INDEX idx_certifications_status ON certifications(status);
CREATE INDEX idx_certifications_expiration ON certifications(expiration_date);

-- Identification: Identifications
CREATE TABLE identifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL,
  id_type TEXT,
  id_number TEXT,
  issued_date DATE,
  expiration_date DATE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);

-- Employee Management: Employee Documents
CREATE TABLE employee_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL,
  document_type TEXT,
  file_path TEXT,
  uploaded_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);

-- Employee Management: Employee Assignments
CREATE TABLE employee_assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL,
  project_code TEXT NOT NULL,
  assignment_start_date DATE,
  assignment_end_date DATE,
  role TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX idx_employee_assignments_project ON employee_assignments(project_code);
CREATE INDEX idx_employee_assignments_employee ON employee_assignments(employee_id);

-- Planning: Lookahead Schedule
CREATE TABLE lookahead_schedule (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  start_date DATE,
  end_date DATE,
  scope_of_work TEXT,
  trades_required TEXT,
  materials_required TEXT,
  equipment_required TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX idx_lookahead_dates ON lookahead_schedule(start_date, end_date);

-- Library: Permits Library
CREATE TABLE permits_library (
  permit_id TEXT PRIMARY KEY,
  project_code TEXT,
  permit_type TEXT,
  permit_number TEXT,
  issuing_agency TEXT,
  issued_date DATE,
  expiration_date DATE,
  status TEXT,
  renewal_required TEXT CHECK (renewal_required IN ('Y', 'N')),
  renewal_submitted_date DATE,
  renewal_approved_date DATE,
  cost REAL,
  file_path TEXT,
  notes TEXT,
  last_reviewed DATE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX idx_permits_status ON permits_library(status);
CREATE INDEX idx_permits_expiration ON permits_library(expiration_date);

-- Library: Document Library
CREATE TABLE document_library (
  doc_id TEXT PRIMARY KEY,
  project_code TEXT,
  type TEXT,
  title TEXT,
  version TEXT,
  discipline TEXT,
  file_path TEXT,
  file_size_kb INTEGER,
  uploaded_at TIMESTAMP,
  uploaded_by TEXT,
  status TEXT,
  linked_records TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Library: DOB Compliance Reference
CREATE TABLE dob_compliance_reference (
  code_id TEXT PRIMARY KEY,
  code_title TEXT,
  source TEXT,
  document_type TEXT,
  applies_to TEXT,
  file_path TEXT,
  loaded_at TIMESTAMP,
  last_updated_by_dob TIMESTAMP,
  project_codes TEXT,
  status TEXT,
  compliance_rules_count INTEGER,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Library: Toolbox Talk Library
CREATE TABLE toolbox_talk_library (
  talk_id TEXT PRIMARY KEY,
  title TEXT,
  category TEXT,
  dob_reference TEXT,
  osha_reference TEXT,
  duration_min INTEGER,
  required_for TEXT,
  frequency_recommendation TEXT,
  hazards_summary TEXT,
  key_practices TEXT,
  required_ppe TEXT,
  discussion_questions TEXT,
  required_inspections TEXT,
  related_certifications TEXT,
  last_updated DATE,
  author TEXT,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Drop Planning: Drop Plan
CREATE TABLE drop_plan (
  drop_id TEXT PRIMARY KEY,
  project_code TEXT NOT NULL,
  elevation TEXT,
  bay_range TEXT,
  floor_range TEXT,
  scope_of_work TEXT,
  trades_required TEXT,
  estimated_duration_days INTEGER,
  planned_start_date DATE,
  planned_end_date DATE,
  actual_start_date DATE,
  actual_end_date DATE,
  crew_size INTEGER,
  crew_assigned TEXT,
  equipment_required TEXT,
  materials_required TEXT,
  drawing_references TEXT,
  status TEXT,
  sign_off_required_from TEXT,
  sign_off_status TEXT,
  sign_off_foreman TEXT,
  sign_off_superintendent TEXT,
  sign_off_qei TEXT,
  sign_off_owner_rep TEXT,
  photos_required TEXT CHECK (photos_required IN ('Y', 'N', 'N/A')),
  photos_captured TEXT CHECK (photos_captured IN ('Y', 'N', 'N/A')),
  linked_punch_items TEXT,
  notes TEXT,
  predecessor_drops TEXT,
  successor_drops TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX idx_drop_plan_project ON drop_plan(project_code);
CREATE INDEX idx_drop_plan_status ON drop_plan(status);

-- Meetings: Meeting Schedule
CREATE TABLE meeting_schedule (
  schedule_id TEXT PRIMARY KEY,
  project_code TEXT,
  meeting_type TEXT,
  recurrence TEXT,
  day_of_week TEXT,
  time TEXT,
  default_location TEXT,
  default_distribution_list TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

-- Meetings: Meeting Records
CREATE TABLE meeting_records (
  meeting_id TEXT PRIMARY KEY,
  project_code TEXT,
  schedule_id TEXT,
  meeting_type TEXT,
  date DATE,
  time_start TIME,
  time_end TIME,
  location TEXT,
  prepared_by TEXT,
  attendees TEXT,
  transcript_source TEXT,
  summary TEXT,
  decisions TEXT,
  distribution_list TEXT,
  status TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code),
  FOREIGN KEY (schedule_id) REFERENCES meeting_schedule(schedule_id)
);

-- Meetings: Meeting Action Items
CREATE TABLE meeting_action_items (
  action_id TEXT PRIMARY KEY,
  meeting_id TEXT NOT NULL,
  description TEXT,
  owner TEXT,
  owner_email TEXT,
  due_date DATE,
  status TEXT,
  completion_date DATE,
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (meeting_id) REFERENCES meeting_records(meeting_id)
);

CREATE INDEX idx_action_items_meeting ON meeting_action_items(meeting_id);
CREATE INDEX idx_action_items_status ON meeting_action_items(status);
CREATE INDEX idx_action_items_owner ON meeting_action_items(owner);

-- RFI & Punch: RFI Log
CREATE TABLE rfi_log (
  rfi_number TEXT PRIMARY KEY,
  project_code TEXT,
  date_submitted DATE,
  submitted_by TEXT,
  discipline TEXT,
  description TEXT,
  status TEXT,
  due_date DATE,
  response_date DATE,
  response TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX idx_rfi_log_status ON rfi_log(status);
CREATE INDEX idx_rfi_log_project ON rfi_log(project_code);

-- Site Operations: Site Closure Log
CREATE TABLE site_closure_log (
  closure_id TEXT PRIMARY KEY,
  date DATE NOT NULL,
  project_code TEXT NOT NULL,
  foreman_id TEXT,
  foreman_name TEXT,
  time_of_close TIME,
  weather_at_close TEXT,
  equipment_left_overnight TEXT,
  personnel_all_signed_out TEXT CHECK (personnel_all_signed_out IN ('Y', 'N', 'N/A')),
  personnel_visitors_escorted TEXT CHECK (personnel_visitors_escorted IN ('Y', 'N', 'N/A')),
  personnel_no_remaining TEXT CHECK (personnel_no_remaining IN ('Y', 'N', 'N/A')),
  equipment_tools_secured TEXT CHECK (equipment_tools_secured IN ('Y', 'N', 'N/A')),
  equipment_scaffold_locked TEXT CHECK (equipment_scaffold_locked IN ('Y', 'N', 'N/A')),
  equipment_compressors_secured TEXT CHECK (equipment_compressors_secured IN ('Y', 'N', 'N/A')),
  equipment_mast_climbers_locked TEXT CHECK (equipment_mast_climbers_locked IN ('Y', 'N', 'N/A')),
  fire_watch_completed TEXT CHECK (fire_watch_completed IN ('Y', 'N', 'N/A')),
  fire_heat_sources_cool TEXT CHECK (fire_heat_sources_cool IN ('Y', 'N', 'N/A')),
  fire_extinguishers_ready TEXT CHECK (fire_extinguishers_ready IN ('Y', 'N', 'N/A')),
  dust_collection_sealed TEXT CHECK (dust_collection_sealed IN ('Y', 'N', 'N/A')),
  dust_storage_sealed TEXT CHECK (dust_storage_sealed IN ('Y', 'N', 'N/A')),
  dust_tarps_secure TEXT CHECK (dust_tarps_secure IN ('Y', 'N', 'N/A')),
  water_penetrations_covered TEXT CHECK (water_penetrations_covered IN ('Y', 'N', 'N/A')),
  water_window_protection TEXT CHECK (water_window_protection IN ('Y', 'N', 'N/A')),
  security_access_locked TEXT CHECK (security_access_locked IN ('Y', 'N', 'N/A')),
  security_fence_secured TEXT CHECK (security_fence_secured IN ('Y', 'N', 'N/A')),
  security_sidewalk_clear TEXT CHECK (security_sidewalk_clear IN ('Y', 'N', 'N/A')),
  building_doors_locked TEXT CHECK (building_doors_locked IN ('Y', 'N', 'N/A')),
  building_roof_locked TEXT CHECK (building_roof_locked IN ('Y', 'N', 'N/A')),
  climate_hvac_undisturbed TEXT CHECK (climate_hvac_undisturbed IN ('Y', 'N', 'N/A')),
  climate_storage_sealed TEXT CHECK (climate_storage_sealed IN ('Y', 'N', 'N/A')),
  doc_daily_report TEXT CHECK (doc_daily_report IN ('Y', 'N', 'N/A')),
  doc_photos_taken TEXT CHECK (doc_photos_taken IN ('Y', 'N', 'N/A')),
  notes TEXT,
  signed_timestamp TIMESTAMP,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code)
);

CREATE INDEX idx_closure_log_date ON site_closure_log(date, project_code);
