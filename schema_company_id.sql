-- =====================================================================
-- Company ID credential — the sibling to CoF for workers who are not
-- CoF-eligible (no SCAFFOLD-16 and no RIGGER-32). Every worker gets
-- exactly one credential; this is the fallback.
--
-- card_id is the unique PK including a per-employee revision number
-- (e.g. SSC-CID-E-00001-1) so re-issuance creates a new row without
-- PK collisions. card_number_display drops the revision (SSC-CID-E-00001)
-- — that's what shows on the printed card and stays stable across
-- supersede events.
--
-- Perpetual lifecycle — no cert-derived expiry like CoF. Status flag
-- handles active / inactive / replaced. HR flips to 'inactive' on
-- termination; issuance flips prior 'active' to 'replaced' before
-- inserting the new active row.
-- =====================================================================

CREATE TABLE IF NOT EXISTS company_id_cards (
  card_id TEXT PRIMARY KEY,                    -- SSC-CID-{employee_id}-{revision}
  employee_id TEXT NOT NULL,
  issued_date DATE NOT NULL,
  issued_by TEXT NOT NULL,
  card_number_display TEXT,                    -- SSC-CID-{employee_id} (no revision)
  photo_snapshot_path TEXT,                    -- copy of face_image_path at issue time
  pdf_export_path TEXT,                        -- data_room/credentials/company_id/<emp_id>_v<rev>.pdf
  status TEXT DEFAULT 'active',                -- active | inactive | replaced
  notes TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_company_id_emp_status ON company_id_cards(employee_id, status);
CREATE INDEX IF NOT EXISTS idx_company_id_status ON company_id_cards(status);
