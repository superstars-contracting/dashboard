-- =====================================================================
-- Cert library replacement — schema additions
-- =====================================================================
-- Add the two columns the new catalog needs:
--   category      — groups the cert library UI (Concrete, Scaffold, etc.)
--   reference_url — DOB-published PDF describing the course, opens from
--                   the cert library so the operator can hand the link to
--                   a worker or sub. Non-DOB entries (CPR / OSHA 30) have
--                   no reference URL and render without a link.
-- The two columns are nullable so existing rows survive the migration
-- before the catalog replacement runs. ALTER TABLE ... ADD COLUMN is
-- idempotent via the standard split_statements pattern (see
-- apply_riggers_schema.py for the reference implementation).
-- =====================================================================
ALTER TABLE cert_types ADD COLUMN category TEXT;
ALTER TABLE cert_types ADD COLUMN reference_url TEXT;
