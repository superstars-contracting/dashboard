-- =====================================================================
-- DCR sequence-based ID refactor: per-project incrementing counter.
-- report_id format changes from DCR-{project}-{date}-{audience}
-- to DCR-{project}-{seq:03d}-{audience}. Date stays in report content,
-- not in the ID. Sequence tracks ISSUANCE order, not chronological.
-- Re-issuing a DCR for the same (project, date) preserves the sequence.
-- =====================================================================

ALTER TABLE report_index ADD COLUMN dcr_sequence INTEGER;

CREATE INDEX IF NOT EXISTS idx_report_index_project_seq
  ON report_index(project_code, dcr_sequence);
