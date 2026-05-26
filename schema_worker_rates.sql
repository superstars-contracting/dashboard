-- =====================================================================
-- Worker Rates — pay-rate history with effective dates (#158)
-- =====================================================================
-- Each worker carries a HISTORY of hourly rates over time. The currently
-- active rate is the row with `effective_to IS NULL`. When a new rate
-- is added the existing active row's `effective_to` is set to
-- (new.effective_from - 1 day) in the SAME transaction — no overlapping
-- active periods per worker.
--
-- This is COMPENSATION data under the strict surface-restriction rule
-- in CLAUDE.md: it MUST NEVER appear on field-reachable surfaces
-- (project dashboard, worker app, rendered DCRs). API responses
-- carrying rate values are gated to roles 'admin' / 'c_suite' via the
-- @requires_role decorator from #48; non-authorized callers receive
-- responses with the rate fields *omitted entirely* — not zeroed, not
-- "—", but missing keys — so a sniffed payload reveals nothing.
--
-- Rate VALUES never appear in server.log, agent reports, smoke output,
-- or screenshots. The audit log entry below stores before/after JSON
-- in the gated DB (fine — the table lives behind the encrypted volume
-- + the auth gate); but logging code MUST NOT echo those JSON blobs
-- out to disk-side log files.
-- =====================================================================

CREATE TABLE IF NOT EXISTS worker_rates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  employee_id TEXT NOT NULL,
  hourly_rate REAL NOT NULL,             -- dollars per hour, two-decimal precision
  effective_from DATE NOT NULL,
  effective_to   DATE,                   -- NULL = currently active
  notes TEXT,
  created_by INTEGER,                    -- users.id (admin who set it)
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (employee_id) REFERENCES employees(employee_id),
  FOREIGN KEY (created_by)  REFERENCES users(id)
);

-- Fast "current rate per worker" + "rate effective on date" lookups.
CREATE INDEX IF NOT EXISTS idx_worker_rates_emp_eff
  ON worker_rates(employee_id, effective_from DESC);

-- =====================================================================
-- Audit Log — generic mutation audit trail (rates, future use)
-- =====================================================================
-- Used by log_audit() helper. Stores actor + target + before/after JSON
-- for any structural mutation that needs review later. NOT logged to
-- server.log — only to this table (which is in the gated DB).
-- =====================================================================
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  action TEXT NOT NULL,                  -- e.g. 'rate_change'
  actor_user_id INTEGER,                 -- users.id who did it
  actor_role TEXT,                       -- snapshot of role at the time
  target_type TEXT,                      -- e.g. 'worker'
  target_id   TEXT,                      -- e.g. 'E-00001'
  before_json TEXT,                      -- JSON or NULL
  after_json  TEXT,                      -- JSON or NULL
  note TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (actor_user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_audit_log_action_created
  ON audit_log(action, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_target
  ON audit_log(target_type, target_id);
