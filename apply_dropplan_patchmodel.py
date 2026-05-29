#!/usr/bin/env python3
"""Drop Plan redesign migration (#202) — dimensioned concrete-patch model.

Rebuilds quantity_entries to replace the old area_sf/depth_in patch model
with L x W x D, each dimension carrying its own ft/in unit, and a
volume_cf GENERATED column that normalizes each dimension to feet and
multiplies (DROP_PLAN_REDESIGN.md §3). SQLite cannot ALTER a generated
column, so this does the standard table rebuild: create new -> copy the
transferable (non-generated) columns -> drop old -> rename.

  * Adds: length, width, depth (REAL) + length_unit/width_unit/depth_unit
    (TEXT, 'ft'|'in', default 'ft').
  * Drops: area_sf, depth_in (deprecated old patch model). They cannot be
    losslessly converted to L x W x D (area is 2D), so any pre-existing
    area/depth patch rows keep their identity + simple columns but lose
    their dimensions (volume_cf becomes NULL until re-entered as L x W x D).
  * Keeps: quantity/unit (for NON-patch lines), step_no, logged_on (LOCAL),
    logged_by (W-####/uid, PII-safe), note, created_at. Append-only.

Idempotent: if quantity_entries already has a `length` column, this is a
no-op. Snapshot the DB BEFORE running (standing rule).
"""
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"

REBUILD_SQL = """
DROP TABLE IF EXISTS quantity_entries_new;

CREATE TABLE quantity_entries_new (
  entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
  drop_id TEXT NOT NULL,
  sov_line_item INTEGER NOT NULL,
  step_no INTEGER,
  quantity REAL,
  unit TEXT,
  length REAL,
  width REAL,
  depth REAL,
  length_unit TEXT DEFAULT 'ft',
  width_unit  TEXT DEFAULT 'ft',
  depth_unit  TEXT DEFAULT 'ft',
  volume_cf REAL GENERATED ALWAYS AS (
    CASE WHEN length IS NOT NULL AND width IS NOT NULL AND depth IS NOT NULL
      THEN (length * (CASE length_unit WHEN 'in' THEN 1.0/12.0 ELSE 1.0 END))
         * (width  * (CASE width_unit  WHEN 'in' THEN 1.0/12.0 ELSE 1.0 END))
         * (depth  * (CASE depth_unit  WHEN 'in' THEN 1.0/12.0 ELSE 1.0 END))
      ELSE NULL END
  ) VIRTUAL,
  logged_on TEXT NOT NULL,
  logged_by TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  note TEXT,
  FOREIGN KEY (drop_id) REFERENCES drops(drop_id),
  FOREIGN KEY (sov_line_item) REFERENCES sov_line_items(sov_id)
);

INSERT INTO quantity_entries_new
  (entry_id, drop_id, sov_line_item, step_no, quantity, unit, logged_on, logged_by, created_at, note)
SELECT
   entry_id, drop_id, sov_line_item, step_no, quantity, unit, logged_on, logged_by, created_at, note
FROM quantity_entries;

DROP TABLE quantity_entries;
ALTER TABLE quantity_entries_new RENAME TO quantity_entries;

CREATE INDEX IF NOT EXISTS idx_qty_drop   ON quantity_entries(drop_id, sov_line_item);
CREATE INDEX IF NOT EXISTS idx_qty_logged ON quantity_entries(logged_on);
"""


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA busy_timeout=60000;")
    # foreign_keys default OFF — safe for the drop/rename rebuild.

    cols = [x[1] for x in conn.execute("PRAGMA table_xinfo(quantity_entries)").fetchall()]
    if "length" in cols:
        n = conn.execute("SELECT COUNT(*) FROM quantity_entries").fetchone()[0]
        print(f"[patchmodel] already migrated — quantity_entries has dimensioned columns. rows={n}")
        conn.close()
        return 0

    before = conn.execute("SELECT COUNT(*) FROM quantity_entries").fetchone()[0]
    legacy_patch = conn.execute(
        "SELECT COUNT(*) FROM quantity_entries WHERE area_sf IS NOT NULL OR depth_in IS NOT NULL"
    ).fetchone()[0]
    print(f"[patchmodel] pre-migration: {before} rows ({legacy_patch} with legacy area_sf/depth_in — "
          f"identity + simple columns preserved; dimensions dropped, re-enter as L x W x D).")

    conn.executescript(REBUILD_SQL)
    conn.commit()

    after = conn.execute("SELECT COUNT(*) FROM quantity_entries").fetchone()[0]
    newcols = [x[1] for x in conn.execute("PRAGMA table_xinfo(quantity_entries)").fetchall()]
    conn.close()
    print(f"[patchmodel] rebuilt. rows copied: {after} (was {before}).")
    print(f"[patchmodel] columns: {newcols}")
    if after != before:
        print(f"[patchmodel] WARNING: row count changed ({before} -> {after})!", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
