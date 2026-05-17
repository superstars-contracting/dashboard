-- =====================================================================
-- Worker Intake — schema additions
-- Open-ended cert tracking + ID document storage per worker.
-- All scanned documents stored on local disk, paths recorded in DB.
-- =====================================================================

-- Add common employee fields if not already present (idempotent)
ALTER TABLE employees ADD COLUMN dob DATE;
ALTER TABLE employees ADD COLUMN phone TEXT;
ALTER TABLE employees ADD COLUMN email TEXT;
ALTER TABLE employees ADD COLUMN emergency_contact_name TEXT;
ALTER TABLE employees ADD COLUMN emergency_contact_phone TEXT;
ALTER TABLE employees ADD COLUMN emergency_contact_relation TEXT;
ALTER TABLE employees ADD COLUMN language TEXT;
ALTER TABLE employees ADD COLUMN hire_date DATE;
ALTER TABLE employees ADD COLUMN pin TEXT;
ALTER TABLE employees ADD COLUMN folder_path TEXT;
ALTER TABLE employees ADD COLUMN face_image_path TEXT;
ALTER TABLE employees ADD COLUMN intake_status TEXT DEFAULT 'pending';   -- pending, complete, needs_review

-- Track every scanned document per worker (DL, passport, SST, any cert card, etc.)
CREATE TABLE IF NOT EXISTS worker_documents (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL,
  doc_type TEXT NOT NULL,              -- 'id_front', 'id_back', 'sst_front', 'sst_back', 'cert_front', 'cert_back', 'other'
  doc_label TEXT,                      -- human label e.g. 'Driver License', 'NY State ID', 'SPRAT Level 1'
  file_path TEXT NOT NULL,
  original_filename TEXT,
  mime_type TEXT,
  file_size_bytes INTEGER,
  related_cert_id INTEGER,             -- if this scan is FOR a specific cert, FK to certifications.id
  uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
  FOREIGN KEY (related_cert_id) REFERENCES certifications(id)
);

CREATE INDEX IF NOT EXISTS idx_worker_docs_employee ON worker_documents(employee_id);
CREATE INDEX IF NOT EXISTS idx_worker_docs_cert ON worker_documents(related_cert_id);

-- Link each certification to its scan via scan_path (optional, faster than join)
ALTER TABLE certifications ADD COLUMN scan_path TEXT;
ALTER TABLE certifications ADD COLUMN card_number TEXT;
ALTER TABLE certifications ADD COLUMN issuing_body TEXT;
ALTER TABLE certifications ADD COLUMN notes TEXT;

-- Cert types: defensive add of CoF prerequisite flag (may already exist from CoF migration)
ALTER TABLE cert_types ADD COLUMN is_cof_prerequisite INTEGER DEFAULT 0;


-- =====================================================================
-- Pre-seed cert_types library — common NYC construction certs
-- INSERT OR IGNORE so re-runs don't error
-- =====================================================================

INSERT OR IGNORE INTO cert_types (cert_type_id, name, description, validity_months, is_cof_prerequisite) VALUES
  -- NYC-required Site Safety Training
  ('SST-WORKER',     'SST Worker Card (40-hr)',          'NYC Local Law 196 site safety training, worker level',                     60, 0),
  ('SST-SUPER',      'SST Supervisor Card (62-hr)',      'NYC Local Law 196 site safety training, supervisor level',                 60, 0),
  ('SST-TRAINEE',    'SST Temporary Trainee Card',       'NYC Local Law 196 partial training card (10 or 30 hr)',                     6, 0),

  -- OSHA federal training
  ('OSHA-10',        'OSHA 10-hour Construction',        '10-hr OSHA Outreach for construction',                                     60, 0),
  ('OSHA-30',        'OSHA 30-hour Construction',        '30-hr OSHA Outreach for construction',                                     60, 0),

  -- Scaffold-specific (16-hr Suspended is the CoF hard prereq)
  ('SCAFFOLD-16',    '16-hr Suspended Scaffold User',    'NYC 16-hr Suspended (swing stage) scaffold user',                          48, 1),
  ('SCAFFOLD-32',    '32-hr Suspended Scaffold User',    'Older 32-hour Suspended Scaffold User course',                             48, 1),
  ('SCAFFOLD-4',     '4-hr Supported Scaffold User',     'NYC 4-hr supported scaffold user',                                         48, 0),
  ('SCAFFOLD-USER',  'General Scaffold User',            'Generic scaffold user training',                                           48, 0),
  ('SCAFFOLD-ERECT', 'Scaffold Erector / Dismantler',    'Scaffold erection and dismantling training',                               48, 0),

  -- Rigging
  ('RIGGER-32',      '32-hr Rigger',                     '32-hr rigger training',                                                    48, 0),
  ('SPECIAL-RIGGER', 'NYC Special Rigger License',       'NYC DOB Special Rigger license (held by master rigger)',                  NULL, 0),
  ('SIGN-HANGER',    'NYC Sign Hanger License',          'NYC DOB Sign Hanger license',                                             NULL, 0),
  ('MASTER-RIGGER',  'NYC Master Rigger License',        'NYC DOB Master Rigger license',                                           NULL, 0),

  -- Rope access (SPRAT / IRATA)
  ('SPRAT-L1',       'SPRAT Level 1 Rope Access',        'Society of Professional Rope Access Technicians, Level 1',                 36, 0),
  ('SPRAT-L2',       'SPRAT Level 2 Rope Access',        'SPRAT Lead Technician',                                                    36, 0),
  ('SPRAT-L3',       'SPRAT Level 3 Rope Access',        'SPRAT Supervisor',                                                         36, 0),
  ('IRATA-L1',       'IRATA Level 1 Rope Access',        'Industrial Rope Access Trade Association Level 1',                         36, 0),
  ('IRATA-L2',       'IRATA Level 2 Rope Access',        'IRATA Level 2',                                                            36, 0),
  ('IRATA-L3',       'IRATA Level 3 Rope Access',        'IRATA Level 3',                                                            36, 0),

  -- Fall protection / heights
  ('FALL-PROT',      'Fall Protection',                  'Fall arrest, harness & lanyard training',                                  24, 0),
  ('FALL-COMP',      'Competent Person Fall Protection', 'OSHA Competent Person, Fall Protection',                                   24, 0),
  ('AERIAL-LIFT',    'Aerial Lift / Boom',               'Aerial / boom / scissor lift operator',                                    36, 0),

  -- Confined space
  ('CONFINED-ENTRY', 'Confined Space Entry',             'OSHA confined space entry training',                                       24, 0),
  ('CONFINED-COMP',  'Confined Space Competent Person',  'OSHA Competent Person for permit-required confined space',                 24, 0),

  -- Hoisting
  ('HMO',            'NYC Hoist Machine Operator',       'NYC DOB Hoisting Machine Operator',                                       NULL, 0),
  ('CRANE-NCCCO',    'NCCCO Crane Operator',             'National Commission for the Certification of Crane Operators',             60, 0),
  ('SIGNAL-PERSON',  'Crane Signal Person',              'OSHA qualified signal person',                                             60, 0),
  ('RIGGER-OSHA',    'OSHA Qualified Rigger',            'OSHA 1926.1404 qualified rigger',                                          60, 0),

  -- Welding / cutting
  ('AWS-WELDER',     'AWS Certified Welder',             'American Welding Society certification',                                   24, 0),
  ('NYC-WELDER',     'NYC DOB Welder License',           'NYC Department of Buildings welder license',                              NULL, 0),

  -- Asbestos / lead / silica
  ('ASBESTOS-HANDLER','Asbestos Handler',                'NY State asbestos handler license',                                        12, 0),
  ('ASBESTOS-SUPER',  'Asbestos Supervisor',             'NY State asbestos supervisor license',                                     12, 0),
  ('LEAD-WORKER',    'Lead Worker (RRP)',                'EPA Lead Renovator / Lead-safe work practices',                            60, 0),
  ('SILICA-COMP',    'Silica Competent Person',          'OSHA respirable crystalline silica competent person',                      24, 0),

  -- Medical / safety response
  ('FIRST-AID',      'First Aid',                        'Red Cross / AHA first aid certification',                                  24, 0),
  ('CPR',            'CPR / AED',                        'CPR + AED certification',                                                  24, 0),
  ('FIRST-AID-CPR',  'First Aid + CPR/AED Combo',        'Combined First Aid + CPR + AED',                                           24, 0),

  -- Fire safety (NYC)
  ('FIRE-S95',       'NYC Fire Guard (S-95)',            'NYC FDNY S-95 Fire Guard for construction sites',                          36, 0),
  ('FIRE-S56',       'NYC Indoor Place of Assembly',     'FDNY S-56',                                                                36, 0),
  ('FIRE-WATCH',     'NYC Hot Work Fire Watch',          'Generic hot work fire watch training',                                     24, 0),

  -- Equipment / specialty
  ('FORKLIFT',       'Forklift / Powered Industrial Truck','OSHA powered industrial truck operator',                                 36, 0),
  ('HAZWOPER-40',    'HAZWOPER 40-hr',                   'OSHA Hazardous Waste Operations & Emergency Response, 40-hour',           12, 0),
  ('HAZWOPER-24',    'HAZWOPER 24-hr',                   'HAZWOPER 24-hour',                                                         12, 0),
  ('HAZWOPER-REF',   'HAZWOPER 8-hr Refresher',          'HAZWOPER annual refresher',                                                12, 0),

  -- Drug screening / medical clearance (track date, not card)
  ('DRUG-SCREEN',    'Drug Screening',                   'Pre-employment or periodic drug screen',                                   12, 0),
  ('MEDICAL-PHYSICAL','Annual Physical / Medical Clearance','Annual medical clearance for job duties',                               12, 0);
