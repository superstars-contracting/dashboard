-- #229 Project Documents — Batch A. Per-project compliance document checklist +
-- uploads (single + bulk). NO AI vision yet (Batch B).
--
-- PII / path discipline (per CLAUDE.md): file_path lives on-disk ONLY and is
-- NEVER serialized to JSON — the gated route GET /api/documents/<id>/file serves
-- the bytes. Files are stored under data_room/project_docs/<project>/<uuid>.<ext>.
-- Dates are LOCAL (YYYY-MM-DD), never UTC.
--
-- STATUS is COMPUTED at read time (not stored authoritatively):
--   on_file   — uploaded, valid (no expiry, or expiry > 30 days out)
--   expiring  — expiry within 30 days (LOCAL)
--   expired   — past expiry (LOCAL)
--   missing   — a required checklist item with no (non-superseded) doc
--   superseded— an old version flagged superseded=1

CREATE TABLE IF NOT EXISTS project_documents (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code     TEXT NOT NULL,                 -- FK projects.project_code
  category         TEXT NOT NULL,                 -- PERMITS|DRAWINGS|CONTRACTS|INSPECTIONS|SAFETY|CLOSEOUT
  requirement_key  TEXT,                          -- which required item it fulfills (NULL = extra/other)
  title            TEXT NOT NULL,
  doc_type         TEXT,                          -- PDF|JPG|PNG|HEIC|XLSX (display label)
  file_path        TEXT NOT NULL,                 -- on-disk path — NEVER in JSON
  file_name        TEXT,                          -- original filename (display)
  file_size        INTEGER,
  mime             TEXT,
  effective_date   TEXT,                          -- LOCAL YYYY-MM-DD
  expiry_date      TEXT,                          -- nullable LOCAL YYYY-MM-DD (drives expiring/expired)
  version          TEXT,                          -- nullable (drawing rev, etc.)
  notes            TEXT,                          -- nullable
  superseded       INTEGER NOT NULL DEFAULT 0,    -- 1 = old version flagged
  uploaded_by_uid  INTEGER,                       -- users.id (PII-safe token; no names)
  uploaded_at      TEXT NOT NULL                  -- LOCAL ISO timestamp
);
CREATE INDEX IF NOT EXISTS idx_projdocs_project ON project_documents(project_code, category);
CREATE INDEX IF NOT EXISTS idx_projdocs_req ON project_documents(project_code, requirement_key);
CREATE INDEX IF NOT EXISTS idx_projdocs_expiry ON project_documents(expiry_date);

-- The required-docs checklist per category (GLOBAL; seeded from the taxonomy;
-- admin-editable later). Drives the "missing" flags + the readiness rollup.
CREATE TABLE IF NOT EXISTS document_requirements (
  id               INTEGER PRIMARY KEY AUTOINCREMENT,
  category         TEXT NOT NULL,
  requirement_key  TEXT NOT NULL,
  label            TEXT NOT NULL,
  sort_order       INTEGER NOT NULL DEFAULT 0,
  UNIQUE(category, requirement_key)
);
