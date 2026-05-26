-- =====================================================================
-- Blank Forms Library — reusable safety / compliance templates
-- =====================================================================
-- A small, cross-project catalog of blank (template) forms the operator
-- prints fresh each day / each event. Examples: Daily Suspended Scaffold
-- Inspection, future Safety Plan, Orientation, Waste-Management, Rigging
-- C-hook Letters.
--
-- Files live under data_room/forms/. The row carries the displayed
-- title verbatim (preserves operator-specified casing + punctuation
-- like "BLANK- ...") and the URL-safe filename separately.
--
-- Schema is intentionally extensible — adding a new form is one INSERT.
-- UNIQUE(title) so the same template can't be added twice. Idempotent
-- migration via CREATE TABLE IF NOT EXISTS.
-- =====================================================================
CREATE TABLE IF NOT EXISTS blank_forms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL UNIQUE,
  filename TEXT NOT NULL,
  category TEXT,
  description TEXT,
  mime_type TEXT NOT NULL DEFAULT 'application/pdf',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_blank_forms_category ON blank_forms(category);
