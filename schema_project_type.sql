-- schema_project_type.sql — Reports Phase 1 shared spine (Handoff
-- HANDOFF_REPORTS_PHASE1_SPINE.md). Foundation only — no report UI, no
-- DCR changes per operator decision. The schema below establishes the
-- 'location_reference' spine + shared field definitions that the future
-- Weekly Summary, Two-Week Look-Ahead, and RFI Log builds (Phases 2-4)
-- consume verbatim. Read in concert with project_type_config.py (the
-- Python source of truth mirroring construction_builds_spec.json) and
-- REPORTS_PHASE1_SHARED_SPINE.md (consumer guide for Phases 2-4).
--
-- Schema rule (CLAUDE.md): every ALTER below is idempotent — apply_project_
-- type_schema.py catches "duplicate column" / "already exists" and counts
-- them as skipped. Re-running is safe.

-- ----------------------------------------------------------------------
-- 1) projects.project_type — enum carved from construction_builds_spec.json
--    "project_types.types[].id". Default 'generic' so any pre-existing
--    project without an explicit type still validates. The apply script
--    backfills FR-BX-001 to 'facade' separately so the change is logged.
-- ----------------------------------------------------------------------
ALTER TABLE projects ADD COLUMN project_type TEXT NOT NULL DEFAULT 'generic'
  CHECK (project_type IN ('facade', 'garage', 'interiors', 'ira', 'generic'));

-- ----------------------------------------------------------------------
-- 2) rfi_log — add the location_reference + shared field columns so the
--    Phase-2 RFI Log build can persist them. The columns match the spec's
--    'shared_fields.fields' verbatim. The existing rfi_log.status column
--    stays; Phase 2 should treat it as the enum
--      Open | In Progress | Complete | Closed | Overdue | Void
--    (the spec's RFI build uses a 5-value variant; the spine's 6-value
--    enum is the superset and what future builds extend).
--
--    Look-Ahead table doesn't exist yet — it'll be created in Phase 2
--    with the same column shapes via a follow-up migration. The shape is
--    documented in REPORTS_PHASE1_SHARED_SPINE.md so Phase 2 doesn't drift.
-- ----------------------------------------------------------------------
ALTER TABLE rfi_log ADD COLUMN location_unit TEXT;
ALTER TABLE rfi_log ADD COLUMN location_id TEXT;
ALTER TABLE rfi_log ADD COLUMN scope_category TEXT;
ALTER TABLE rfi_log ADD COLUMN schedule_impact_flag INTEGER NOT NULL DEFAULT 0;
ALTER TABLE rfi_log ADD COLUMN cost_impact_flag INTEGER NOT NULL DEFAULT 0;

-- ----------------------------------------------------------------------
-- 3) Index — Phase-2 RFI Log will sort/filter by (project, status,
--    date_response_required). The status + project_code combo is the most
--    common scan; index now so the Phase-2 list endpoint stays snappy
--    even at high RFI counts.
-- ----------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_rfi_log_project_status
  ON rfi_log (project_code, status);

CREATE INDEX IF NOT EXISTS idx_rfi_log_location
  ON rfi_log (project_code, location_unit, location_id);
