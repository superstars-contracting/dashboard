-- =====================================================================
-- Signage Templates Library — crystal-clear full-page printable site signs
-- =====================================================================
-- 10 standard construction-site signs (ANSI Z535 + DOB) recreated as
-- self-contained HTML, rendered to PDF that fills a Letter page when
-- printed. Operator prints, posts on site. Examples: DANGER Hard Hat
-- Area, NOTICE All PPE Required, NO SMOKING, Restricted Area /
-- Construction Work in Progress.
--
-- Files live under data_room/signage/. Same library pattern as
-- blank_forms (#157). UNIQUE(title) so the same sign can't be added
-- twice. Idempotent migration via CREATE TABLE IF NOT EXISTS.
-- =====================================================================
CREATE TABLE IF NOT EXISTS signage_templates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  code TEXT,                              -- short identifier (e.g. SAFE-001)
  title TEXT NOT NULL UNIQUE,
  filename TEXT NOT NULL,
  category TEXT,                          -- Safety / PPE / DOB / Site
  orientation TEXT DEFAULT 'portrait',    -- 'portrait' or 'landscape'
  description TEXT,
  mime_type TEXT NOT NULL DEFAULT 'application/pdf',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_signage_templates_category ON signage_templates(category);
