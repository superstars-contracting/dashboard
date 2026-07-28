#!/usr/bin/env python3
"""#280 — North Elevation drop plan: persistence for the elevation / drop / cell model.

The drop plan Amit files the drop report from. Four elevations by design (N/S/E/W) even
though only North is seeded — `elevation.face` costs nothing now and a rewrite later.

db_layer-aware, idempotent, dual-backend. NO production cutover; honors SSC_DB_URL.

===============================================================================
THREE DEVIATIONS FROM THE SPEC'D SCHEMA — each forced by the existing database
===============================================================================

1. `project_id`  ->  `project_code TEXT`
   `projects` has NO `id` column; its primary key is `project_code` TEXT ('FR-BX-001'),
   and every table in this codebase keys on it. A `project_id` INTEGER would join to
   nothing that exists.

2. `drop` / `drop_cell` / `cell_event`  ->  `elevation_drop` / `elevation_cell` /
   `elevation_cell_event`
   Two reasons, either sufficient:
     (a) DROP IS A RESERVED WORD. `CREATE TABLE drop` / `SELECT ... FROM drop` is a
         syntax error on Postgres unless quoted everywhere, forever.
     (b) A `drops` table ALREADY EXISTS — the #201/#256 Drop Plan schedule model
         (drop_id, project_code, elevation, sequence_no, lifecycle) that feeds
         drop_stage_status and the dropplan rollups. Two tables named for the same
         noun, on the same project, meaning different things, is a bug factory. The
         `elevation_` prefix says which model a row belongs to at a glance.
   The COLUMN names inside are exactly as spec'd.

3. `status_tone` is created HERE.
   Step 1 says "use status_tone keys, do NOT invent a parallel enum" — but the table is
   a phase-2 deliverable and does not exist yet. Rather than invent the parallel enum
   the spec forbids, this migration creates status_tone with the FULL phase-2 shape
   (incl. client_visible / client_label / client_fallback, default-deny) and seeds only
   the five elevation statuses. Phase 2 then seeds the remaining modules into a table
   that already exists, and this build's statuses are already in the one vocabulary.

Run:  python apply_elevation_280.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
from apply_crm_266 import _columns, _table_exists  # noqa: E402

# The five elevation statuses. `reason_required` is enforced SERVER-SIDE on every write
# (see elevation.py) — a hold or a rework with no reason is exactly the row that is
# useless three weeks later.
#
# client_visible=1 across the board: per the operator's correction, the external view is
# IDENTICAL to the internal one for status. Rework included — it is a field condition,
# not an internal metric.
#
# severity_rank orders ALERTS, not progress. It answers "which of these wins the last
# slot in a decision band", and it is also what derives a drop's roll-up status from its
# five cells (see elevation.derive_drop_status) — so the ordering lives in the status
# table, never in a template or a JS switch.
#
# client_key is the CLIENT-SAFE STABLE KEY. External payloads carry it; the internal key
# never ships. For elevation the two happen to spell the same words — every one of these
# five is safe to show an owner — but the PLUMBING is what matters: the external payload
# is built from client_key, so a module whose internal keys are not client-safe inherits
# a working mechanism instead of needing one invented.
ELEVATION_STATUSES = [
    # key,                     module,      label,         tone,      c_vis, sev, sort, client_key
    ("elevation.not_started",  "elevation", "Not started", "neutral",     1,   0,  10, "not_started"),
    ("elevation.in_progress",  "elevation", "In progress", "blue",        1,  20,  20, "in_progress"),
    ("elevation.on_hold",      "elevation", "On hold",     "gold",        1,  60,  30, "on_hold"),
    ("elevation.rework",       "elevation", "Rework",      "coral",       1,  80,  40, "rework"),
    ("elevation.complete",     "elevation", "Complete",    "green",       1,  10,  50, "complete"),
]

# The short keys the API and UI speak. Mapped to status_tone keys so the drawing never
# hard-codes a tone (non-negotiable #7: colour comes from the status table only).
STATUS_KEYS = ("not_started", "in_progress", "on_hold", "rework", "complete")
REASON_REQUIRED = ("on_hold", "rework")


def ensure_status_tone(conn) -> bool:
    """Create status_tone in its FULL phase-2 shape + seed the elevation statuses.

    THE SHAPE IS FIXED HERE ON PURPOSE. Tonight is the only cheap moment: adding
    severity_rank or client_key after phase 2 has seeded ~61 rows across a dozen modules
    is a second migration plus a re-seed. So the table lands complete —

      escalates_to / escalates_days   phase-2 read-time escalation (never a stored write)
      client_visible                  DEFAULT 0, default-deny
      client_label / client_fallback  what the client sees instead, or falls back to
      severity_rank                   which alert wins a decision-band slot; also derives
                                      a drop's roll-up from its cells
      client_key                      client-safe stable key — the internal key never
                                      ships to a client payload

    PHASE 2 MUST BE WRITTEN TO EXPECT THIS TABLE ALREADY EXISTS and to seed the
    remaining modules into it — not to CREATE it. Its migration should call this
    function (or mirror it) and then insert its own rows.
    """
    created = not _table_exists(conn, "status_tone")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS status_tone (
             key             TEXT PRIMARY KEY,   -- 'elevation.on_hold'
             module          TEXT NOT NULL,
             label           TEXT NOT NULL,
             tone            TEXT NOT NULL,      -- green|blue|gold|coral|neutral
             escalates_to    TEXT,               -- tone to become after the threshold
             escalates_days  INTEGER,            -- NULL = never escalates
             client_visible  INTEGER NOT NULL DEFAULT 0,
             client_label    TEXT,
             client_fallback TEXT,
             severity_rank   INTEGER NOT NULL DEFAULT 0,
             client_key      TEXT,
             sort_order      INTEGER NOT NULL DEFAULT 0
           )""")
    # Idempotent top-up for a status_tone created before these two columns existed.
    cols = _columns(conn, "status_tone")
    if "severity_rank" not in cols:
        conn.execute("ALTER TABLE status_tone ADD COLUMN severity_rank INTEGER NOT NULL DEFAULT 0")
    if "client_key" not in cols:
        conn.execute("ALTER TABLE status_tone ADD COLUMN client_key TEXT")

    for key, module, label, tone, cvis, sev, sort, ckey in ELEVATION_STATUSES:
        conn.execute(
            "INSERT OR IGNORE INTO status_tone "
            "(key, module, label, tone, client_visible, client_label, severity_rank, "
            " client_key, sort_order) VALUES (?,?,?,?,?,?,?,?,?)",
            (key, module, label, tone, cvis, label, sev, ckey, sort))
        # Re-running must correct a row seeded before the shape was complete.
        conn.execute(
            "UPDATE status_tone SET severity_rank=?, client_key=?, client_label=?, tone=? "
            "WHERE key=?", (sev, ckey, label, tone, key))
    conn.commit()
    return created


def ensure_elevation_schema(conn) -> dict:
    """Create the elevation model. Idempotent + dual-backend. Caller owns the conn."""
    pk = ("id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
          if db_layer.is_postgres() else "id INTEGER PRIMARY KEY AUTOINCREMENT")
    changed = {}

    # ---- elevation: one row per face of one building ----
    changed["elevation"] = not _table_exists(conn, "elevation")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS elevation (
              {pk},
              project_code  TEXT NOT NULL,
              face          TEXT NOT NULL,          -- 'N' | 'S' | 'E' | 'W'
              name          TEXT,
              source_sheet  TEXT,
              sheet_date    TEXT,                   -- LOCAL ISO date string (#259 rule)
              dob_job       TEXT,
              scale_note    TEXT,
              geometry_json TEXT,                   -- traced drawing geometry (see seed)
              created_at    TEXT
            )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_elev_project ON elevation(project_code)")

    # ---- elevation_drop: the vertical slices ----
    changed["elevation_drop"] = not _table_exists(conn, "elevation_drop")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS elevation_drop (
              {pk},
              elevation_id INTEGER NOT NULL,
              idx          INTEGER NOT NULL,        -- 1..12, the DROP n the whole world sees
              grid_from    TEXT,
              grid_to      TEXT,
              x0           REAL,
              x1           REAL,
              width_ft     REAL,
              area_sf      INTEGER,
              note         TEXT,
              -- NOT IN THE SPEC, ADDED DELIBERATELY (nullable, no FK — the #264/#266
              -- convention). The #201/#256 `drops` table ALREADY holds 12 North drops
              -- for this project (FR-BX-001-DP1..DP12) carrying live lifecycle state and
              -- 385 drop_stage_status rows. Standing up a second drop model beside it
              -- with NO way to say "this is that one" is how two sources of truth are
              -- born. This column is that link, left NULL until the mapping is
              -- confirmed. Costs nothing now; retrofitting it after both models have
              -- diverged costs a reconciliation.
              drops_drop_id TEXT
            )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_edrop_elev ON elevation_drop(elevation_id)")

    # ---- elevation_cell: one drop x one level = the unit that carries status ----
    # reason        EXTERNAL — shown to architect AND client.
    # internal_note NEVER leaves the building; excluded from every external payload.
    # That two-field split IS the security mechanism for this build: the phase-2
    # registry/serialiser does not exist yet, so external-by-construction and
    # internal-by-construction are separate COLUMNS rather than a filtering rule.
    changed["elevation_cell"] = not _table_exists(conn, "elevation_cell")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS elevation_cell (
              {pk},
              drop_id       INTEGER NOT NULL,
              level_id      TEXT NOT NULL,
              level_name    TEXT,
              status_key    TEXT NOT NULL DEFAULT 'not_started',
              reason        TEXT,
              internal_note TEXT,
              updated_by_uid INTEGER,
              updated_at    TEXT
            )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ecell_drop ON elevation_cell(drop_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_ecell_unique "
                 "ON elevation_cell(drop_id, level_id)")

    # ---- elevation_cell_event: append-only. Never overwrite history. ----
    changed["elevation_cell_event"] = not _table_exists(conn, "elevation_cell_event")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS elevation_cell_event (
              {pk},
              cell_id     INTEGER NOT NULL,
              from_status TEXT,
              to_status   TEXT,
              reason      TEXT,
              actor_uid   INTEGER,
              created_at  TEXT
            )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ecellev_cell ON elevation_cell_event(cell_id)")

    conn.commit()
    return changed


def ensure_collab_schema(conn) -> dict:
    """comment / rfi — steps 4 and 5. Created here so the whole build is one migration."""
    pk = ("id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY"
          if db_layer.is_postgres() else "id INTEGER PRIMARY KEY AUTOINCREMENT")
    changed = {}

    # target_type is CONSTRAINED, not conventional. 'drop_report' was removed before a
    # single row existed: it named a deliverable that turned out to be something else
    # entirely, and a wrong name baked into a schema outlives the misunderstanding that
    # created it. The CHECK means a stray value fails at the database, not in review.
    changed["comment"] = not _table_exists(conn, "comment")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS comment (
              {pk},
              project_code TEXT NOT NULL,
              target_type  TEXT NOT NULL CHECK (target_type IN ('drop','photo','rfi')),
              target_id    TEXT,
              body         TEXT NOT NULL,
              author_uid   INTEGER,
              created_at   TEXT,
              deleted_at   TEXT                -- SOFT DELETE ONLY, never a hard delete
            )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_comment_target "
                 "ON comment(project_code, target_type, target_id)")

    changed["rfi"] = not _table_exists(conn, "rfi")
    conn.execute(
        f"""CREATE TABLE IF NOT EXISTS rfi (
              {pk},
              project_code TEXT NOT NULL,
              elevation_id INTEGER,
              drop_id      INTEGER,        -- NULLABLE + EDITABLE after creation
              level_id     TEXT,           -- so an RFI can be attached to a drop later
              number       TEXT,
              title        TEXT NOT NULL,
              body         TEXT,
              raised_by_uid INTEGER,
              raised_at    TEXT,
              status       TEXT NOT NULL DEFAULT 'open',
              closed_at    TEXT
            )""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rfi_project ON rfi(project_code)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rfi_drop ON rfi(drop_id)")

    conn.commit()
    return changed


def main() -> int:
    conn = db_layer.connect()
    backend = "postgres" if db_layer.is_postgres() else "sqlite"
    try:
        tone_created = ensure_status_tone(conn)
        changed = ensure_elevation_schema(conn)
        changed.update(ensure_collab_schema(conn))
        ok = all(_table_exists(conn, t) for t in
                 ("status_tone", "elevation", "elevation_drop", "elevation_cell",
                  "elevation_cell_event", "comment", "rfi"))
        cols = _columns(conn, "elevation_cell")
        ok = ok and {"reason", "internal_note", "status_key"} <= cols
        n_tone = conn.execute(
            "SELECT COUNT(*) AS n FROM status_tone WHERE module='elevation'").fetchone()["n"]
        print(f"[280] backend={backend}  status_tone_created={tone_created}  changed={changed}")
        print(f"[280] verify: tables -> {'OK' if ok else 'FAIL'}   elevation statuses seeded={n_tone}")
        return 0 if (ok and n_tone == len(ELEVATION_STATUSES)) else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
