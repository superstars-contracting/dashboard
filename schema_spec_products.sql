-- =====================================================================
-- Specifications database — manufacturer-agnostic catalog
-- =====================================================================
-- spec_products  — the spec catalog itself. Seeded with Sika; schema is
--                  extensible to any manufacturer (default "Sika" for
--                  the first seed batch). Each row links to the
--                  official manufacturer-published TDS via spec_url +
--                  an optional locally-uploaded datasheet_pdf_path.
-- project_document_specs — link table that attaches a spec to a
--                  project's Project Documents. UNIQUE pair so the
--                  same spec can't be attached twice to one project.
--
-- Re-run safe: CREATE TABLE IF NOT EXISTS / CREATE INDEX IF NOT EXISTS
-- via the split_statements pattern used by the rest of the migrations.
-- =====================================================================

CREATE TABLE IF NOT EXISTS spec_products (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  manufacturer TEXT NOT NULL DEFAULT 'Sika',
  category TEXT NOT NULL,
  product_line TEXT,
  product_name TEXT NOT NULL,
  product_code TEXT,
  description TEXT,
  spec_url TEXT,
  datasheet_pdf_path TEXT,
  tags TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(manufacturer, product_name)
);

CREATE INDEX IF NOT EXISTS idx_spec_products_mfr      ON spec_products(manufacturer);
CREATE INDEX IF NOT EXISTS idx_spec_products_category ON spec_products(manufacturer, category);
CREATE INDEX IF NOT EXISTS idx_spec_products_line     ON spec_products(manufacturer, product_line);

CREATE TABLE IF NOT EXISTS project_document_specs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  spec_product_id INTEGER NOT NULL,
  added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  added_by TEXT,
  notes TEXT,
  UNIQUE(project_code, spec_product_id),
  FOREIGN KEY (project_code) REFERENCES projects(project_code),
  FOREIGN KEY (spec_product_id) REFERENCES spec_products(id)
);

CREATE INDEX IF NOT EXISTS idx_pds_project ON project_document_specs(project_code);
CREATE INDEX IF NOT EXISTS idx_pds_spec    ON project_document_specs(spec_product_id);
