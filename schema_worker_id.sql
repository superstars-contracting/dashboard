-- =====================================================================
-- Worker ID — a human-facing identifier shown alongside each worker's
-- name everywhere identity matters. Format: W-#### (zero-padded 4-digit
-- sequence). Stable: once assigned, never changes. Distinct from the
-- internal employee_id primary key (E-#####); FKs continue to reference
-- employee_id. This column is for display + uniqueness only.
-- =====================================================================

ALTER TABLE employees ADD COLUMN worker_id TEXT;

-- Partial unique index: enforces uniqueness on assigned values without
-- blocking pre-assignment NULLs. SQLite supports partial indexes.
CREATE UNIQUE INDEX IF NOT EXISTS idx_employees_worker_id
  ON employees(worker_id) WHERE worker_id IS NOT NULL;
