# Reports Phase 1 — Shared Spine (consumer guide for Phases 2–4)

This phase built the **data spine** for the connected-reports system
(Weekly Summary, Two-Week Look-Ahead, RFI Log) defined in
`construction_builds_spec.json`. **No report UI was built.** This doc
tells the next three phases exactly where to read the shared config
and how to persist `location_reference` + the four shared fields so
the spec's `linkage_rules` work without each build re-inventing them.

If you're a Phase 2/3/4 author: read this top-to-bottom before
shipping anything.

---

## TL;DR — where everything lives

| You need… | Read from… |
|---|---|
| Project-type config (location_unit_options, typical_scopes, typical_inspections, typical_long_lead) | `project_type_config.py` (Python) **or** `GET /api/project-types` / `GET /api/projects/<code>/project-config` (HTTP) |
| The valid set of project_type ids (DB CHECK constraint mirror) | `project_type_config.PROJECT_TYPE_IDS` |
| `status` enum (full superset) | `project_type_config.STATUS_ENUM` |
| `status` enum (RFI subset per spec) | `project_type_config.RFI_STATUS_SUBSET` |
| `scope_category` / `schedule_impact_flag` / `cost_impact_flag` defs | `project_type_config.SHARED_FIELD_DEFS` |
| `location_reference` persisted column shape | `project_type_config.LOCATION_REFERENCE_SCHEMA` |
| Authoritative spec | `C:\Users\SSC-Admin\Documents\Claude\Projects\Superstars Dashboard\construction_builds_spec.json` |

**Do not duplicate any of those lists into your build's templates,
seed scripts, or per-field option arrays.** If the spec changes, only
`project_type_config.py` should change (and `SPINE_VERSION` should
bump). Drift is the bug we're paying upfront to prevent.

---

## What landed in this phase

### 1. Schema changes (idempotent migration)

Applied via `python apply_project_type_schema.py`. Source SQL:
`schema_project_type.sql`.

**`projects.project_type`** — `TEXT NOT NULL DEFAULT 'generic'` with
`CHECK IN (facade, garage, interiors, ira, generic)`. Pre-existing
projects keep `'generic'` until reclassified deliberately.

**`rfi_log` got the spine columns:**

| Column | Type | Default | Purpose |
|---|---|---|---|
| `location_unit` | TEXT | NULL | Enum chosen from the project's `location_unit_options` |
| `location_id` | TEXT | NULL | Free-text per handoff (no 890 dropdown for Phase 1) |
| `scope_category` | TEXT | NULL | Free-text; UI offers `typical_scopes` as suggestions |
| `schedule_impact_flag` | INTEGER | 0 | Boolean — drives `rfi_to_lookahead` linkage |
| `cost_impact_flag` | INTEGER | 0 | Boolean |

`rfi_log.status` already existed before this phase — Phase 2 normalizes
its values to `RFI_STATUS_SUBSET` on write.

**Indexes added:** `idx_rfi_log_project_status (project_code, status)`,
`idx_rfi_log_location (project_code, location_unit, location_id)`. The
Phase-2 list/filter endpoints will use both.

**Backfill:** FR-BX-001 set to `project_type = 'facade'`. All other
project_codes (none currently) stay `'generic'`.

**Snapshot:** `data_room/db_backups/superstars-pre-project-type-spine-20260521-223514.db`.

### 2. `project_type_config.py` — the single source

Mirrors `construction_builds_spec.json` verbatim. Exports:

- `PROJECT_TYPES` — the 5 type dicts
- `PROJECT_TYPE_IDS` — frozenset of valid ids
- `STATUS_ENUM`, `RFI_STATUS_SUBSET`
- `SHARED_FIELD_DEFS` (`scope_category` / `status` / `schedule_impact_flag` / `cost_impact_flag`)
- `LOCATION_REFERENCE_SCHEMA`
- `SPINE_VERSION` (bump when content changes)
- `get_project_type(type_id)` and `get_project_config_for(conn, project_code)` helpers

### 3. Read-only HTTP endpoints

- `GET /api/project-types` — full payload (every type + shared field
  defs + location_reference shape + status enum). Use this when a UI
  needs to iterate every type (e.g. an admin project-type picker).
- `GET /api/projects/<project_code>/project-config` — resolved config
  for one project. Returns 404 if the project_code is unknown. Use
  this in every per-project UI: cleaner than fetching all types + a
  client-side lookup.

Both endpoints are read-only. Both include `spine_version` in their
response so a consumer can detect upstream changes.

---

## How Phase 2/3/4 builds should use the spine

### RFI Log (Phase 2)

- `rfi_log` already has every spine column — just read/write them.
- On render: hit `/api/projects/<code>/project-config` to populate the
  Location-Unit dropdown (`location_unit_options`) and the
  Scope-Category suggestion list (`typical_scopes`).
- Status writes: restrict UI choices to `data.rfi_status_subset`.
- `linkage_rules.rfi_to_lookahead`: when `status='Open'` AND
  `schedule_impact_flag=1`, the row becomes a Look-Ahead constraint on
  its `(location_unit, location_id)`.
- `linkage_rules.rfi_to_reports`: open/overdue RFIs surface in the
  Weekly Summary's "Change Orders & RFIs" + "Issues, Delays & Risks"
  sections; query by `(project_code, status IN ('Open', 'Overdue'))`
  — the index added in this phase covers this.

### Two-Week Look-Ahead (Phase 3)

You'll need two new tables. **Define them with the same column shapes
as `rfi_log` for the spine fields**, so a single helper can read either:

```sql
CREATE TABLE lookahead_activities (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  -- location_reference (mirror rfi_log)
  location_unit TEXT,
  location_id TEXT,
  scope_category TEXT,             -- mirrors rfi_log.scope_category
  scope_of_work TEXT NOT NULL,     -- the per-row scope description (spec)
  start_date DATE NOT NULL,
  finish_date DATE NOT NULL,
  duration_days INTEGER NOT NULL,
  predecessor_id INTEGER,          -- optional self-reference
  -- shared flags
  status TEXT,                     -- use STATUS_ENUM full set
  schedule_impact_flag INTEGER NOT NULL DEFAULT 0,
  cost_impact_flag INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code),
  FOREIGN KEY (predecessor_id) REFERENCES lookahead_activities(id)
);

CREATE TABLE lookahead_constraints (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  project_code TEXT NOT NULL,
  -- location_reference
  location_unit TEXT,
  location_id TEXT,
  -- the spec's constraints_and_readiness fields
  constraint_description TEXT NOT NULL,
  linked_rfi_number TEXT,          -- nullable FK by string to rfi_log
  blocks_start_date INTEGER NOT NULL DEFAULT 0,    -- boolean
  status TEXT,                     -- use STATUS_ENUM
  owner_to_remove TEXT,
  needed_by_date DATE,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_code) REFERENCES projects(project_code),
  FOREIGN KEY (linked_rfi_number) REFERENCES rfi_log(rfi_number)
);
```

Index suggestions: `(project_code, start_date, finish_date)` on activities;
`(project_code, status, needed_by_date)` on constraints.

### Weekly Summary (Phase 4)

Per the spec, this is an **aggregation** — no independent data entry.
The weekly is a roll-up of:
- the week's DCR rows (DCR untouched in Phase 1 — adding `location`
  to DCR tables is a **DEFERRED** task per handoff; weekly's location-
  grouped roll-up needs that first),
- open/overdue RFIs from `rfi_log` (filter `status IN ('Open','Overdue')`),
- look-ahead constraints from `lookahead_constraints` (filter
  `status='Open' AND blocks_start_date=1`).

Use `data.shared_fields.schedule_impact_flag` to identify "items that
elevate from clerical to management-tool" — those go on the cover page.

---

## DCR rule (do not touch this phase)

Per handoff: **the DCR stays untouched in Phase 1.** Adding
`location_unit` / `location_id` to `work_log`, `safety_events`,
`photos`, etc. is deferred to a later task — that's what unlocks the
Weekly Summary's location-grouped roll-up and lets RFIs link to a
specific daily entry. Don't be tempted to "while I'm here" the DCR
spine; that's a separate sign-off.

---

## Versioning

`SPINE_VERSION = "1.0.0"`.

When you change the content of any of these:
- `PROJECT_TYPES` (add/remove/rename a type, change any option list),
- `STATUS_ENUM` / `RFI_STATUS_SUBSET`,
- `SHARED_FIELD_DEFS`,
- `LOCATION_REFERENCE_SCHEMA`,

bump the version in `project_type_config.py` AND update the
`PROJECT_TYPE_IDS` mirror in `schema_project_type.sql`'s CHECK
constraint. Phase 2-4 consumers should treat `spine_version` mismatch
as a deploy-order signal.
