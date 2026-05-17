-- =====================================================================
-- Certificate of Fitness — schema additions
-- =====================================================================

-- Employees: add photo for cards
ALTER TABLE employees ADD COLUMN photo_path TEXT;

-- Cert types: flag which certs are HARD prerequisites for issuing a CoF
ALTER TABLE cert_types ADD COLUMN is_cof_prerequisite INTEGER DEFAULT 0;

-- CoF cards: one row per issuance
CREATE TABLE IF NOT EXISTS cof_cards (
  card_id TEXT PRIMARY KEY,                 -- SSC-XXXXX
  employee_id TEXT NOT NULL,
  issued_date DATE NOT NULL,
  expires_date DATE NOT NULL,
  issued_by TEXT NOT NULL,                  -- name of issuer at time of signing
  issuer_license TEXT,                      -- e.g., "NYC DOB Special Rigger #7652"
  signature_path TEXT,                      -- path to signature image used at issuance
  photo_snapshot_path TEXT,                 -- snapshot of employee photo at issuance
  pdf_export_path TEXT,                     -- where the print-ready PDF was saved
  status TEXT DEFAULT 'issued',             -- issued, revoked, replaced, expired
  basis_certs_json TEXT,                    -- snapshot of which certs + expiries drove the expiration
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id)
);

CREATE INDEX IF NOT EXISTS idx_cof_cards_employee ON cof_cards(employee_id);
CREATE INDEX IF NOT EXISTS idx_cof_cards_status ON cof_cards(status);
CREATE INDEX IF NOT EXISTS idx_cof_cards_expires ON cof_cards(expires_date);

-- App settings (single-row key/value store) — for the issuer's stored signature
CREATE TABLE IF NOT EXISTS app_settings (
  key TEXT PRIMARY KEY,
  value TEXT,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Pre-seed default issuer (you can change later via dashboard)
INSERT OR IGNORE INTO app_settings (key, value) VALUES
  ('issuer_name', 'ARUN MAL'),
  ('issuer_license', 'NYC DOB Special Rigger #7652'),
  ('issuer_signature_path', '');

-- Mark the 16-hour Suspended Scaffold User cert as the CoF prerequisite.
-- Matches by name pattern so it works regardless of cert_type_id naming convention.
UPDATE cert_types
SET is_cof_prerequisite = 1
WHERE LOWER(name) LIKE '%16%hour%suspend%scaffold%'
   OR LOWER(name) LIKE '%suspended scaffold user%'
   OR LOWER(name) LIKE '%16 hr suspended%'
   OR LOWER(cert_type_id) LIKE '%susp%scaffold%';
