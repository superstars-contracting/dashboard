-- =====================================================================
-- Multi-user accounts & roles — Phase 1 (#257)
-- =====================================================================
-- EXTENDS the #48 auth foundation (users + sessions). The users TABLE itself
-- is rebuilt in apply_auth_roles_257.py (SQLite can't ALTER a CHECK constraint
-- in place) to:
--   * expand the role CHECK to the full catalog:
--       admin, c_suite, pm, super, client, architect, vendor
--     (only admin/c_suite/pm are ONBOARDED this phase; super + the external
--      three are DEFINED, not enabled — no request-access intake here.)
--   * add columns: display_name, status (active|pending|disabled),
--     must_reset_password, created_by, deactivated_at.
--   * keep is_active + full_name (existing code reads them; status mirrors
--     is_active, display_name backfills from full_name).
-- Project-membership / scoping is intentionally DEFERRED (single project,
-- internal GLOBAL roles this phase) — the seam is left, not built.
--
-- This file holds only the ADDITIVE audit tables (CREATE IF NOT EXISTS, so it
-- is safe to re-run). All operator-written timestamps are LOCAL (the app
-- passes datetime.now(); CLAUDE.md dates rule — never UTC). `ip` in the login
-- audit is allowed (not PII-bearing per the rule). Passwords / hashes /
-- temp-passwords are NEVER stored or logged here.
-- =====================================================================

-- Every authentication event. user_id is NULL when the email did not resolve
-- (we never record which non-existent email was tried — no account-existence
-- disclosure, no PII of a mistyped real address).
CREATE TABLE IF NOT EXISTS login_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER,
  event TEXT NOT NULL
    CHECK (event IN ('login_success','login_fail','logout','password_set','password_reset')),
  at TEXT NOT NULL,                 -- LOCAL 'YYYY-MM-DDTHH:MM:SS'
  ip TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_login_audit_user ON login_audit(user_id, at);
CREATE INDEX IF NOT EXISTS idx_login_audit_at ON login_audit(at);

-- Every role change (assignment is admin-only; a user can NEVER change their
-- own role — enforced server-side in auth_admin.py).
CREATE TABLE IF NOT EXISTS role_change_audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  old_role TEXT,
  new_role TEXT,
  changed_by INTEGER,               -- the admin user id who made the change
  at TEXT NOT NULL,                 -- LOCAL 'YYYY-MM-DDTHH:MM:SS'
  reason TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id),
  FOREIGN KEY (changed_by) REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_role_change_user ON role_change_audit(user_id, at);
