-- schema_rfi_log_phase2.sql — Reports Phase 2 (Handoff
-- HANDOFF_REPORTS_PHASE2_RFI_LOG.md). Reconciles rfi_log to the FULL
-- field set defined in construction_builds_spec.json, build_id="rfi_log".
--
-- The spine columns (location_unit, location_id, scope_category,
-- schedule_impact_flag, cost_impact_flag) landed in Phase 1
-- (schema_project_type.sql). This migration adds the remaining 9
-- spec fields that don't yet have a column:
--
--   subject_title              short scannable description
--   sent_to                    responsible party to answer (architect, EOR, etc.)
--   date_response_required     drives turnaround calc + Overdue flag
--   date_response_received     closes the loop; absent + past-due => Overdue
--   question_description       full question body (replaces legacy `description`)
--   response_answer            captured answer in the log (replaces `response`)
--   drawing_spec_reference     sheet/detail/spec section in question
--   impact_magnitude_note      free text — why the impact matters
--   related_documents          links to change orders/submittals/other RFIs
--
-- Legacy columns retained for backward compat / smooth migration:
--   description       -> kept (Phase-2 writes mirror into question_description)
--   response          -> kept (mirror into response_answer)
--   due_date          -> kept (mirror into date_response_required)
--   response_date     -> kept (mirror into date_response_received)
--   discipline        -> kept; new writes use scope_category (spine)
--
-- Idempotent — apply_rfi_log_phase2.py catches duplicate-column errors.

-- ----------------------------------------------------------------------
-- 1) Add the 9 spec columns
-- ----------------------------------------------------------------------
ALTER TABLE rfi_log ADD COLUMN subject_title TEXT;
ALTER TABLE rfi_log ADD COLUMN sent_to TEXT;
ALTER TABLE rfi_log ADD COLUMN date_response_required DATE;
ALTER TABLE rfi_log ADD COLUMN date_response_received DATE;
ALTER TABLE rfi_log ADD COLUMN question_description TEXT;
ALTER TABLE rfi_log ADD COLUMN response_answer TEXT;
ALTER TABLE rfi_log ADD COLUMN drawing_spec_reference TEXT;
ALTER TABLE rfi_log ADD COLUMN impact_magnitude_note TEXT;
ALTER TABLE rfi_log ADD COLUMN related_documents TEXT;

-- ----------------------------------------------------------------------
-- 2) Backfill the new names from any legacy values (cheap — table starts
--    empty in this snapshot, but the COALESCE-style UPDATE makes the
--    migration safe to re-run after rows accumulate).
-- ----------------------------------------------------------------------
UPDATE rfi_log
   SET date_response_required = COALESCE(date_response_required, due_date)
 WHERE due_date IS NOT NULL AND date_response_required IS NULL;

UPDATE rfi_log
   SET date_response_received = COALESCE(date_response_received, response_date)
 WHERE response_date IS NOT NULL AND date_response_received IS NULL;

UPDATE rfi_log
   SET question_description = COALESCE(question_description, description)
 WHERE description IS NOT NULL AND question_description IS NULL;

UPDATE rfi_log
   SET response_answer = COALESCE(response_answer, response)
 WHERE response IS NOT NULL AND response_answer IS NULL;

UPDATE rfi_log
   SET scope_category = COALESCE(scope_category, discipline)
 WHERE discipline IS NOT NULL AND scope_category IS NULL;

-- ----------------------------------------------------------------------
-- 3) Index for the register's default sort
--    (status, date_response_required ASC). Open/Overdue first is a
--    client-side ORDER BY CASE; the index speeds the underlying scan.
-- ----------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_rfi_log_register
  ON rfi_log (project_code, status, date_response_required);
