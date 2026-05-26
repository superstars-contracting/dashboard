-- =====================================================================
-- DCR stale flag — issued artifact diverges from live sign_in_log
-- =====================================================================
-- An issued DCR is a frozen artifact (HTML + PDF on disk) of the
-- moment of issuance. If sign_in_log mutates on that date AFTER
-- issuance (operator adds/edits/deletes labor), the rendered artifact
-- stops matching live data. This column flags that drift so the UI
-- can prompt the operator to re-issue.
--
-- stale=1 set by _mark_dcr_stale() called from every sign_in_log
-- mutation path. Cleared (stale=0) by _issue_one_dcr on a fresh
-- issuance — re-issue regenerates the rendered HTML from current data.
-- =====================================================================
ALTER TABLE report_index ADD COLUMN stale INTEGER NOT NULL DEFAULT 0;
ALTER TABLE report_index ADD COLUMN stale_marked_at TIMESTAMP;
