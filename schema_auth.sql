-- =====================================================================
-- Dashboard auth foundation (#48): users + sessions.
--
-- Scope is the DASHBOARD only — the operator + future C-suite/PM/super
-- accounts that hit the company console + project dashboard. Worker-app
-- PIN sign-in (employees.pin) is unaffected; workers do not get rows here.
--
-- Password hashing: bcrypt (60-char string, includes salt). No plaintext
-- passwords are ever stored. Per CLAUDE.md PII discipline, password_hash
-- and session ids are treated as secret material — never logged, never
-- emitted in API responses, never pasted in chats.
-- =====================================================================

CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('admin', 'c_suite', 'pm', 'super')),
  full_name TEXT NOT NULL,
  -- Optional link to employees.employee_id when the dashboard user is
  -- also a worker on the books (e.g. operator who is also onboarded).
  -- NULL for dashboard-only accounts.
  employee_id_link TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at TIMESTAMP,
  FOREIGN KEY (employee_id_link) REFERENCES employees(employee_id)
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);

-- Sessions are server-side: the cookie holds an opaque random id, the
-- row is the truth. Logout / password change / admin revoke = DELETE the
-- row. 12-hour sliding window: last_used_at refreshed on each authed
-- request, expires_at recomputed off that.
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,                          -- 32-byte hex (token_urlsafe-derived, opaque)
  user_id INTEGER NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_used_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at TIMESTAMP NOT NULL,
  -- Coarse client metadata for audit. NOT used for auth decisions —
  -- UA spoofing is trivial; this is forensic breadcrumb only.
  user_agent TEXT,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at);
