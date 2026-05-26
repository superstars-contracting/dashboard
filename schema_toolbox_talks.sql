-- =====================================================================
-- Toolbox Talks Library (Ch 33) — DOB-sourced safety talks (EN + ES)
-- =====================================================================
-- 19 toolbox talks sourced from NYC DOB Building Code Chapter 33
-- ("Safeguards During Construction or Demolition" — amended by Local
-- Law 77 of 2023), tailored to SSC's work (facade restoration,
-- suspended scaffolds, demolition). Each talk has BOTH an English
-- AND a Spanish printable, rendered to PDF and posted on site.
--
-- Files live under data_room/toolbox_talks/. Same library pattern as
-- blank_forms (#157) and signage_templates (#160). UNIQUE(topic_number)
-- so the same talk can't be added twice. Idempotent migration via
-- CREATE TABLE IF NOT EXISTS.
-- =====================================================================
CREATE TABLE IF NOT EXISTS toolbox_talks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  topic_number INTEGER NOT NULL UNIQUE,
  category TEXT,                          -- Site / Fall / Scaffold / Demo / General
  title_en TEXT NOT NULL,
  title_es TEXT NOT NULL,
  ch33_ref TEXT,                          -- e.g. "§3301.12" / "§3314 + OSHA"
  filename_en TEXT NOT NULL,
  filename_es TEXT NOT NULL,
  est_minutes INTEGER NOT NULL DEFAULT 15,
  description TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_toolbox_talks_category ON toolbox_talks(category);
CREATE INDEX IF NOT EXISTS idx_toolbox_talks_topic   ON toolbox_talks(topic_number);
