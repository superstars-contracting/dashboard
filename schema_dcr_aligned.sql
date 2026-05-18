-- =====================================================================
-- DCR renderer alignment.
-- Adds the columns that render_dcr_html.py expects in the JSON shape
-- but were missing from the original schema. Each ALTER TABLE is wrapped
-- by apply_dcr_aligned_schema.py so duplicate-column errors are caught
-- and counted as skipped (re-runnable safely).
--
-- Pre-existing columns are left untouched. Where the new column overlaps
-- semantically with a legacy free-text column (e.g. weather_log.conditions),
-- the legacy column stays for backward compat — the renderer prefers the
-- new column when populated.
-- =====================================================================

-- work_log: scope_of_work + trades_working stay; renderer wants richer fields
ALTER TABLE work_log ADD COLUMN trade_area TEXT;
ALTER TABLE work_log ADD COLUMN location_elevation TEXT;
ALTER TABLE work_log ADD COLUMN description TEXT;

-- deliveries: description + delivered_by stay; renderer wants time/qty/supplier
ALTER TABLE deliveries ADD COLUMN time TEXT;
ALTER TABLE deliveries ADD COLUMN material TEXT;
ALTER TABLE deliveries ADD COLUMN qty REAL;
ALTER TABLE deliveries ADD COLUMN unit TEXT;
ALTER TABLE deliveries ADD COLUMN supplier TEXT;
ALTER TABLE deliveries ADD COLUMN notes TEXT;

-- equipment_log: equipment_type + status + notes stay
ALTER TABLE equipment_log ADD COLUMN equipment_id TEXT;
ALTER TABLE equipment_log ADD COLUMN owner TEXT;
ALTER TABLE equipment_log ADD COLUMN hours_used REAL;
ALTER TABLE equipment_log ADD COLUMN issues TEXT;

-- safety_events: event_type + severity + description + reported_by stay
ALTER TABLE safety_events ADD COLUMN time TEXT;
ALTER TABLE safety_events ADD COLUMN person TEXT;
ALTER TABLE safety_events ADD COLUMN action TEXT;

-- issues: owner + status + due_date stay; renderer wants category + lost-time
ALTER TABLE issues ADD COLUMN category TEXT;
ALTER TABLE issues ADD COLUMN time_lost_hrs REAL;
ALTER TABLE issues ADD COLUMN action TEXT;

-- inspections: inspector_name + scope + result + notes stay
ALTER TABLE inspections ADD COLUMN type TEXT;
ALTER TABLE inspections ADD COLUMN agency TEXT;
ALTER TABLE inspections ADD COLUMN area TEXT;

-- weather_log: existing `conditions` column kept for backward compat,
-- renderer prefers split am_conditions / pm_conditions + wind when present
ALTER TABLE weather_log ADD COLUMN am_conditions TEXT;
ALTER TABLE weather_log ADD COLUMN pm_conditions TEXT;
ALTER TABLE weather_log ADD COLUMN wind TEXT;

-- photos: file_path stays as the absolute path; filename/url/location are
-- the renderer-facing values (filename derivable, url for web display,
-- location is the human-readable site zone)
ALTER TABLE photos ADD COLUMN filename TEXT;
ALTER TABLE photos ADD COLUMN url TEXT;
ALTER TABLE photos ADD COLUMN location TEXT;

-- report_index: the renderer's "DCR-0001" string lives here per-project
ALTER TABLE report_index ADD COLUMN report_id TEXT;
