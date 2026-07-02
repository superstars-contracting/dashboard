-- =====================================================================
-- #269 — SELECTIVE CLIENT UN-GATING: per-client, per-section, DEFAULT-OFF grants.
--
-- The "gated day 1, unlock over time" mechanism (North Star §6/§8). Extends the
-- #264 visibility engine + the #267 welcome containment with a SECOND default-deny
-- layer, ABOVE per-item visibility:
--
--   SECTION grant (this table)      — may the client see the section AT ALL.
--                                     Presence of a row = unlocked. NO row = locked.
--                                     A client with ZERO rows stays hard-contained
--                                     on /welcome (#267 behavior unchanged).
--   ITEM visibility (#264)          — within photos/documents, WHICH items.
--                                     Still default-deny, shared one item at a time.
--
-- section: progress | photos | documents | daily | schedule  (enforced in code —
-- client_grants.SECTIONS — not by a CHECK, so a future section is an additive code
-- change on both backends, no ALTER).
--
-- granted_at is a LOCAL ISO string written by the app (never UTC, CLAUDE.md).
-- NO FK constraints (matches the #264 engine tables: dual-backend simple; integrity
-- enforced in code — target must be an active `client` user + a real project).
--
-- Canonical SQLite DDL (reference). apply_client_grants_269.py emits the
-- backend-correct PRIMARY KEY (Postgres IDENTITY) at apply time.
-- =====================================================================

CREATE TABLE IF NOT EXISTS client_section_grant (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       INTEGER NOT NULL,
  project_code  TEXT    NOT NULL,
  section       TEXT    NOT NULL,   -- progress | photos | documents | daily | schedule
  granted_by    INTEGER,
  granted_at    TEXT,
  UNIQUE (user_id, project_code, section)
);
CREATE INDEX IF NOT EXISTS idx_csg_user    ON client_section_grant(user_id, project_code);
CREATE INDEX IF NOT EXISTS idx_csg_project ON client_section_grant(project_code, section);
