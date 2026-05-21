-- Worker archive (soft-delete) columns. Allows DELETE /api/employees/<id>
-- to preserve history (sign-ins, certs, docs, credentials) when the worker
-- has any. Active worker = archived_at IS NULL.
ALTER TABLE employees ADD COLUMN archived_at TEXT;
ALTER TABLE employees ADD COLUMN archived_reason TEXT;
CREATE INDEX IF NOT EXISTS idx_employees_archived_at ON employees(archived_at);
