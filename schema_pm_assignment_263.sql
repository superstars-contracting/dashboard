-- =====================================================================
-- #263 — PM project-scoping: project-membership assignment + project status
--
-- Two INDEPENDENT axes (see access.py / CLAUDE.md):
--   * ROLE       decides which SECTIONS a user can reach (#262 access map).
--   * ASSIGNMENT decides which PROJECTS a `pm` can reach (this table).
--
-- pm_project_assignment links a `pm` user to the project(s) an admin/c_suite has
-- assigned them. A pm may have MANY projects; UNIQUE(user_id, project_code) keeps a
-- single row per (pm, project). assigned_at is a LOCAL ISO string (never UTC, per
-- CLAUDE.md dates rule) written by the app at insert time — no SQL default, so the
-- one statement is valid on BOTH backends.
--
-- NOTE: distinct from `project_assignments` (worker->project roster). This table is
-- USER->project membership for access scoping only.
--
-- Canonical SQLite DDL (reference). The migration runner (apply_pm_assignment_263.py)
-- emits the backend-correct PRIMARY KEY clause for Postgres (IDENTITY) at apply time.
-- =====================================================================

CREATE TABLE IF NOT EXISTS pm_project_assignment (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id       INTEGER NOT NULL,
  project_code  TEXT    NOT NULL,
  assigned_by   INTEGER,
  assigned_at   TEXT,
  UNIQUE (user_id, project_code)
);

CREATE INDEX IF NOT EXISTS idx_pmpa_user    ON pm_project_assignment(user_id);
CREATE INDEX IF NOT EXISTS idx_pmpa_project ON pm_project_assignment(project_code);

-- Project lifecycle status (active | closed). Already present on live projects
-- (DEFAULT 'active'); guard-added here for fresh deploys. admin/c_suite may set
-- 'closed' — a closed project drops off assigned PMs' active-projects view.
-- (Added idempotently by the runner; this line documents the column.)
-- ALTER TABLE projects ADD COLUMN status TEXT DEFAULT 'active';
