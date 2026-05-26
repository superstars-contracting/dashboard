-- =====================================================================
-- No-Work Day designation on DCR
-- =====================================================================
-- Adds three columns to report_index so a DCR can carry a first-class
-- "no work" designation (rain / snow / holiday / other) instead of
-- requiring the operator to type prose into Work Performed:
--
--   no_work          INTEGER NOT NULL DEFAULT 0
--   no_work_reason   TEXT (Rain / Snow / Holiday / Other; NULL when not set)
--   no_work_note     TEXT (optional free-text)
--
-- Idempotent via the standard duplicate-column suppression.
-- =====================================================================
ALTER TABLE report_index ADD COLUMN no_work INTEGER NOT NULL DEFAULT 0;
ALTER TABLE report_index ADD COLUMN no_work_reason TEXT;
ALTER TABLE report_index ADD COLUMN no_work_note TEXT;
