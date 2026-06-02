-- #220 Labor Rates redesign — approval-gated rate management layered ON TOP of
-- the existing effective-dated worker_rates table (which stays canonical for the
-- check-cutting sheet and is NEVER modified by the migration). Keyed by
-- worker_id (W-####) so synthetic test workers and real workers share one model.
-- COMPENSATION DATA — admin/c_suite only (PMs see ONLY the pending queue).
-- Money: REAL but all arithmetic via Decimal in Python; dates LOCAL (never UTC).

-- Per-worker rate STATE: current approved rate + trade + active/inactive status.
CREATE TABLE IF NOT EXISTS labor_worker_state (
  worker_id      TEXT PRIMARY KEY,                 -- W-####
  employee_id    TEXT,                             -- E-##### bridge for real workers (nullable)
  trade          TEXT,                             -- Mechanic | Laborer | Rope Access | Superintendent
  current_rate   REAL,                             -- latest APPROVED hourly rate
  status         TEXT NOT NULL DEFAULT 'active',   -- active | inactive
  effective_date TEXT,                             -- current rate's effective date (LOCAL YYYY-MM-DD)
  created_at     TEXT,
  updated_at     TEXT
);

-- Rate-change audit = history (approved) + approval queue (pending).
CREATE TABLE IF NOT EXISTS labor_rate_change (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  worker_id         TEXT NOT NULL,
  employee_id       TEXT,
  old_rate          REAL,                          -- null for the initial rate
  new_rate          REAL NOT NULL,
  effective_date    TEXT,
  status            TEXT NOT NULL DEFAULT 'pending', -- pending | approved | rejected
  is_initial        INTEGER NOT NULL DEFAULT 0,
  submitted_by_uid  INTEGER,
  submitted_by_role TEXT,                           -- role at submit time — PII-safe (no name)
  submitted_at      TEXT,
  decided_by_uid    INTEGER,
  decided_by_role   TEXT,                           -- role at decision time — PII-safe
  decided_at        TEXT,
  note              TEXT
);

CREATE INDEX IF NOT EXISTS idx_lws_status ON labor_worker_state(status);
CREATE INDEX IF NOT EXISTS idx_lrc_worker ON labor_rate_change(worker_id);
CREATE INDEX IF NOT EXISTS idx_lrc_status ON labor_rate_change(status);

-- #221 — change_type so the SAME approval queue carries rate changes AND
-- deactivation requests. ALTER is idempotent (migration skips duplicate column);
-- existing rows default to 'rate' (back-compat).
ALTER TABLE labor_rate_change ADD COLUMN change_type TEXT DEFAULT 'rate';
