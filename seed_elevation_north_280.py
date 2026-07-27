#!/usr/bin/env python3
"""#280 — seed the North elevation of 890 E 135th (FR-BX-001).

===============================================================================
READ THIS BEFORE RUNNING — THE TRACED GEOMETRY IS NOT IN THIS REPOSITORY
===============================================================================
The build instruction says "Geometry is already traced and correct; transcribe it, do
not re-derive it." That trace — the reviewed three-audience mockup with its geometry
constants, CMU pattern, stair stack, overhead door, grid bubbles, datum lines and
dimension strings — **does not exist anywhere under C:\\Users\\SSC-Admin\\Superstars**.
It was searched for by filename, by content (grid/datum/CMU/stair/bulkhead/overhead
door), and across every .html/.svg/.md in the tree. dropplan.html contains no elevation
renderer. So there is nothing here to transcribe.

Re-deriving bay dimensions from memory would be inventing numbers for a drawing a DOB
drop report gets filed from. That is not a corner worth cutting, so this seed ships in
two clearly separated halves:

  STRUCTURE  (below, REAL)       — confirmed against the live database:
                                   12 North drops, FR-BX-001-DP1..DP12, and the
                                   5 levels. 12 x 5 = the 60 cells the brief specifies.
  GEOMETRY   (below, PROVISIONAL) — evenly-spaced placeholder bays. NOT the traced
                                   drawing. Every row it writes is stamped
                                   provisional=true, and the page renders a hazard
                                   banner while that flag is set.

WHEN THE TRACE ARRIVES: fill GEOMETRY_NORTH below and set PROVISIONAL = False. Nothing
else changes — no schema edit, no renderer edit, no endpoint edit. The drawing is data
(elevation.geometry_json + elevation_drop.x0/x1/width_ft), which is what the spec'd
schema already implies. It is a paste, not a rebuild.

Idempotent + dual-backend. Honors SSC_DB_URL. Run:
  python seed_elevation_north_280.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
from apply_elevation_280 import STATUS_KEYS  # noqa: E402,F401

PROJECT = "FR-BX-001"          # 890 E 135th Street
FACE = "N"

# ============================================================================
# STRUCTURE — REAL. Verified against the live `drops` table (12 North rows).
# ============================================================================

# The 5 levels, ground up. level_id is the stable key; level_name is what everyone reads.
LEVELS = [
    ("L1", "Level 1"),
    ("L2", "Level 2"),
    ("L3", "Level 3"),
    ("L4", "Level 4"),
    ("L5", "Level 5"),
]

# 13 grid lines bounding 12 drops: drop n spans GL n -> GL n+1.
GRID_LINES = [f"GL {n}" for n in range(1, 14)]

# The 12 drops, linked to the EXISTING #201/#256 drop rows so the two models can be
# reconciled instead of quietly diverging.
DROPS = [
    # idx, grid_from, grid_to,   drops_drop_id
    (n, f"GL {n}", f"GL {n + 1}", f"{PROJECT}-DP{n}")
    for n in range(1, 13)
]

# ============================================================================
# GEOMETRY — PROVISIONAL. Replace wholesale when the trace arrives.
# ============================================================================
PROVISIONAL = True

# Placeholder: 12 equal bays across a nominal facade. These are NOT measured.
_BAY_W = 20.0                   # ft, nominal — placeholder only
_LEVEL_H = 12.0                 # ft, nominal — placeholder only

GEOMETRY_NORTH = {
    "provisional": PROVISIONAL,
    "units": "ft",
    "grid_lines": GRID_LINES,
    "levels": [{"id": lid, "name": lname,
                "y0": round(i * _LEVEL_H, 2), "y1": round((i + 1) * _LEVEL_H, 2)}
               for i, (lid, lname) in enumerate(LEVELS)],
    # Special features the trace carries. EMPTY until it arrives — the renderer draws
    # only what is present, so an empty list is an honest blank, never a wrong guess.
    "features": {"bulkheads": [], "overhead_door": None, "stair_tower": None},
    "notes": ("PROVISIONAL placeholder geometry — evenly spaced bays, nominal heights. "
              "NOT the traced drawing. Do not file from this."),
}


def _now():
    return datetime.now().isoformat(timespec="seconds")   # LOCAL, never UTC


def seed(conn) -> dict:
    made = {"elevation": 0, "drops": 0, "cells": 0}
    row = conn.execute(
        "SELECT id FROM elevation WHERE project_code=? AND face=?", (PROJECT, FACE)).fetchone()
    if row:
        elev_id = row["id"]
        conn.execute("UPDATE elevation SET geometry_json=?, scale_note=? WHERE id=?",
                     (json.dumps(GEOMETRY_NORTH),
                      "PROVISIONAL GEOMETRY" if PROVISIONAL else None, elev_id))
    else:
        cur = conn.execute(
            "INSERT INTO elevation (project_code, face, name, source_sheet, sheet_date, "
            "dob_job, scale_note, geometry_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (PROJECT, FACE, "North Elevation", None, None, None,
             "PROVISIONAL GEOMETRY" if PROVISIONAL else None,
             json.dumps(GEOMETRY_NORTH), _now()))
        elev_id = cur.lastrowid
        made["elevation"] = 1

    for idx, gfrom, gto, drops_id in DROPS:
        d = conn.execute("SELECT id FROM elevation_drop WHERE elevation_id=? AND idx=?",
                         (elev_id, idx)).fetchone()
        x0 = round((idx - 1) * _BAY_W, 2)
        x1 = round(idx * _BAY_W, 2)
        if d:
            drop_id = d["id"]
            conn.execute("UPDATE elevation_drop SET grid_from=?, grid_to=?, x0=?, x1=?, "
                         "width_ft=?, drops_drop_id=? WHERE id=?",
                         (gfrom, gto, x0, x1, _BAY_W, drops_id, drop_id))
        else:
            cur = conn.execute(
                "INSERT INTO elevation_drop (elevation_id, idx, grid_from, grid_to, x0, x1, "
                "width_ft, area_sf, note, drops_drop_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (elev_id, idx, gfrom, gto, x0, x1, _BAY_W, None, None, drops_id))
            drop_id = cur.lastrowid
            made["drops"] += 1

        for lid, lname in LEVELS:
            c = conn.execute("SELECT id FROM elevation_cell WHERE drop_id=? AND level_id=?",
                             (drop_id, lid)).fetchone()
            if not c:
                conn.execute(
                    "INSERT INTO elevation_cell (drop_id, level_id, level_name, status_key, "
                    "updated_at) VALUES (?,?,?,'not_started',?)", (drop_id, lid, lname, _now()))
                made["cells"] += 1
    conn.commit()
    return made


def main() -> int:
    conn = db_layer.connect()
    backend = "postgres" if db_layer.is_postgres() else "sqlite"
    try:
        made = seed(conn)
        elev = conn.execute("SELECT id FROM elevation WHERE project_code=? AND face=?",
                            (PROJECT, FACE)).fetchone()
        nd = conn.execute("SELECT COUNT(*) AS n FROM elevation_drop WHERE elevation_id=?",
                          (elev["id"],)).fetchone()["n"]
        nc = conn.execute(
            "SELECT COUNT(*) AS n FROM elevation_cell c JOIN elevation_drop d ON d.id=c.drop_id "
            "WHERE d.elevation_id=?", (elev["id"],)).fetchone()["n"]
        ok = (nd == 12 and nc == 60)
        print(f"[280-seed] backend={backend}  created={made}")
        print(f"[280-seed] verify: drops={nd}/12  cells={nc}/60  -> {'OK' if ok else 'FAIL'}")
        if PROVISIONAL:
            print("[280-seed] *** GEOMETRY IS PROVISIONAL — placeholder bays, not the trace.")
            print("[280-seed] *** Structure (12 drops x 5 levels) is real. Do not file from this.")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
