#!/usr/bin/env python3
r"""#280 — seed the North elevation of 890 East 135th Street (FR-BX-001).

TRACED DATA. Not placeholder, not re-derived.

Source: approved set A-001.00 (Sheet 3 of 7), Frank S. Caminiti RA, issued 06/05/2022,
DOB approved 08/16/2022, DOBNOW X00768844-I1. Block 2594, Lot 5, Bronx NY.

Scope notes carried from the trace:
  * All Sto / EIFS notation deleted — that scope is removed. Current scope is concrete
    patch, CMU block infill at window openings, and paint.
  * Window openings are taken from the EXISTING elevation on that sheet, NOT the
    proposed one (the proposed view showed continuous Sto panels).

DIMENSION BASIS — read before using for takeoff: widths are SCALED off the approved set
and normalised to its overall 265'-0" x 67'-0". They are traced+scaled, NOT dimensioned.
`DIMENSION_BASIS` and `SCALE_NOTE` ride in geometry_json and surface on the page, so the
distinction survives into the drawing rather than living only in this file.

Geometry is DATA: everything the renderer needs is in elevation.geometry_json plus the
elevation_drop rows. Re-running this seed re-traces the drawing without touching the
schema, the endpoints, or the renderer — and without disturbing any status already
marked (cells are created once; status/reason/internal_note are never overwritten here).

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

PROJECT = "FR-BX-001"          # 890 East 135th Street
FACE = "N"                     # north (East 135 St) elevation

# ============================================================================
# GEOMETRY_NORTH — traced. Feet, x from the west end, y from grade.
# ============================================================================

PROVISIONAL = False            # this is traced data, not placeholder
DIMENSION_BASIS = "scaled"     # traced+scaled, NOT dimensioned — see SCALE_NOTE

SOURCE = {
    "sheet": "A-001.00 (Sheet 3 of 7)",
    "architect": "Frank S. Caminiti RA",
    "issued": "2022-06-05",
    "dob_approved": "2022-08-16",
    "dob_job": "X00768844-I1",
    "block_lot": "Block 2594, Lot 5, Bronx NY",
    "scope_note": ("Sto / EIFS scope removed. Current scope: concrete patch, "
                   "CMU block infill at window openings, and paint."),
    "openings_from": ("EXISTING elevation on the sheet, not the proposed one "
                      "(proposed showed continuous Sto panels)."),
}

SCALE_NOTE = (
    "Widths are SCALED off the 2022 approved set and normalised to its overall "
    "265'-0\" x 67'-0\". The sheet's 18'-6\" bay note is the clear opening between "
    "finished column faces; grid c/c scales to about 22'-3\". Window openings are "
    "taken from the EXISTING elevation, not the proposed one. Confirm against the "
    "architect's current set before using for takeoff."
)

FACADE = {"width_ft": 265.0, "height_ft": 67.0, "draw_top_ft": 79.8}

COL_W       = 3.14   # exposed structural column face
PARAPET_TOP = 67.0
HEAD_BELOW  = 1.10   # window head below the slab above
SILL_ABOVE  = 3.35   # window sill above the slab below  -> 6'-11" opening
WIN_INSET   = 2.78   # opening jamb inset from the grid line

GRIDS = [
    {"id": "1",  "x":   1.82}, {"id": "2",  "x":  24.08}, {"id": "3",  "x":  46.33},
    {"id": "4",  "x":  69.05}, {"id": "5",  "x":  91.33}, {"id": "6",  "x": 113.65},
    {"id": "7",  "x": 135.27}, {"id": "8",  "x": 157.70}, {"id": "9",  "x": 180.31},
    {"id": "10", "x": 202.38}, {"id": "11", "x": 224.81}, {"id": "12", "x": 246.99},
    {"id": "13", "x": 261.92},
]

DATUMS = [
    {"id": "F", "name": "ROOF",         "y": 62.30},
    {"id": "E", "name": "FIFTH FLOOR",  "y": 50.83},
    {"id": "D", "name": "FOURTH FLOOR", "y": 39.38},
    {"id": "C", "name": "THIRD FLOOR",  "y": 27.90},
    {"id": "B", "name": "SECOND FLOOR", "y": 16.46},
    {"id": "A", "name": "FIRST FLOOR",  "y":  4.98},
]

# The five occupied levels, TOP-DOWN as drawn. One elevation_cell per (drop, level).
LEVELS = [
    {"id": "L5", "name": "Fifth Floor",  "top": 62.30, "bot": 50.83},
    {"id": "L4", "name": "Fourth Floor", "top": 50.83, "bot": 39.38},
    {"id": "L3", "name": "Third Floor",  "top": 39.38, "bot": 27.90},
    {"id": "L2", "name": "Second Floor", "top": 27.90, "bot": 16.46},
    {"id": "L1", "name": "First Floor",  "top": 16.46, "bot":  4.98},
]

# 13 boundaries, 12 drops. Drop 1 starts at the west face, drop 12 ends at the east
# face; both include a corner return (so neither aligns to its grid line).
BOUNDS = [0.00, 24.08, 46.33, 69.05, 91.33, 113.65, 135.27,
          157.70, 180.31, 202.38, 224.81, 246.99, 265.00]

# Clear-bay dimension AS WRITTEN on the approved sheet. "*" = bay not dimensioned on
# the sheet, typical assumed. Rendered verbatim — never recomputed from the scaled
# widths, because what the sheet says and what it scales to are different facts.
BAY_DIMS = ["18'-6\"", "18'-5\"", "18'-5\"", "18'-5\"", "18'-6\"*", "18'-6\"*",
            "18'-6\"", "18'-6\"", "18'-6\"", "18'-6\"", "18'-6\"", "EQ + EQ"]

DROPS = [
    # idx, grid_from, grid_to, x0, x1, width_ft, area_sf, clear_bay, note
    (1,  "1",  "2",    0.00,  24.08, 24.08, 1613, BAY_DIMS[0],
     "Includes the west corner return beyond grid 1."),
    (2,  "2",  "3",   24.08,  46.33, 22.25, 1491, BAY_DIMS[1],  ""),
    (3,  "3",  "4",   46.33,  69.05, 22.72, 1522, BAY_DIMS[2],  ""),
    (4,  "4",  "5",   69.05,  91.33, 22.28, 1493, BAY_DIMS[3],  ""),
    (5,  "5",  "6",   91.33, 113.65, 22.32, 1495, BAY_DIMS[4],  ""),
    (6,  "6",  "7",  113.65, 135.27, 21.62, 1449, BAY_DIMS[5],  ""),
    (7,  "7",  "8",  135.27, 157.70, 22.43, 1503, BAY_DIMS[6],  ""),
    (8,  "8",  "9",  157.70, 180.31, 22.61, 1515, BAY_DIMS[7],  ""),
    (9,  "9",  "10", 180.31, 202.38, 22.07, 1479, BAY_DIMS[8],  ""),
    (10, "10", "11", 202.38, 224.81, 22.43, 1503, BAY_DIMS[9],  ""),
    (11, "11", "12", 224.81, 246.99, 22.18, 1486, BAY_DIMS[10],
     "Overhead door fills the first-floor opening - no window here."),
    (12, "12", "13", 246.99, 265.00, 18.01, 1207, BAY_DIMS[11],
     "Enclosed stair tower: 13 equal stacked lites, 2 wide, full height. "
     "Includes the east corner return beyond grid 13."),
]

# Non-typical features. Drawn, but NOT status-tracked — they carry no elevation_cell.
FEATURES = {
    "bulkheads": [
        {"x0": 115.19, "x1": 163.20, "top": 79.76, "label": "ROOF BULKHEAD (BEYOND)"},
        {"x0": 212.95, "x1": 231.87, "top": 79.76, "label": "BULKHEAD"},
    ],
    "overhead_door": {"x0": 226.90, "x1": 244.86, "top": 15.36, "bot":  0.40},
    "stair_tower":   {"x0": 260.06, "x1": 263.99, "top": 65.74, "bot":  0.95, "bands": 13},
    "east_pier":     {"x0": 259.06, "x1": 260.06},
}

# The cell that has no window: drop 11 / L1 is filled by the overhead door.
NO_OPENING = {(11, "L1")}

_GRID_X = {g["id"]: g["x"] for g in GRIDS}


def _openings():
    """Every window opening, precomputed from the traced constants so the renderer draws
    rather than derives. One per (drop, level) except drop 11 / L1.

    Two documented specials:
      * Drop 12 (stair tower bay): the opening runs from grid 12 + WIN_INSET to
        east_pier.x0 - 1.2, NOT to grid 13 - WIN_INSET. Grid 13 lands mid-window inside
        the stair tower rather than on a pier, so there is no column to inset from.
      * Drop 1 and drop 12 include corner returns, so their drop extents are wider than
        their grid span. Openings key off the GRIDS, never off x0/x1.
    """
    out = []
    for idx, g_from, g_to, *_rest in DROPS:
        for lv in LEVELS:
            if (idx, lv["id"]) in NO_OPENING:
                continue
            if idx == 12:
                ox0 = _GRID_X[g_from] + WIN_INSET
                ox1 = FEATURES["east_pier"]["x0"] - 1.2
            else:
                ox0 = _GRID_X[g_from] + WIN_INSET
                ox1 = _GRID_X[g_to] - WIN_INSET
            out.append({
                "drop_idx": idx,
                "level_id": lv["id"],
                "x0": round(ox0, 2),
                "x1": round(ox1, 2),
                "top": round(lv["top"] - HEAD_BELOW, 2),
                "bot": round(lv["bot"] + SILL_ABOVE, 2),
            })
    return out


def _columns_drawn():
    """Grid columns that are actually drawn as piers. Grid 13 is excluded: it lands
    mid-window in the stair tower, not on a pier (per the trace)."""
    return [{"id": g["id"], "x0": round(g["x"] - COL_W / 2, 2),
             "x1": round(g["x"] + COL_W / 2, 2)}
            for g in GRIDS if g["id"] != "13"]


def build_geometry() -> dict:
    return {
        "provisional": PROVISIONAL,
        "dimension_basis": DIMENSION_BASIS,
        "scale_note": SCALE_NOTE,
        "source": SOURCE,
        "units": "ft",
        "facade": FACADE,
        "constants": {"col_w": COL_W, "parapet_top": PARAPET_TOP,
                      "head_below": HEAD_BELOW, "sill_above": SILL_ABOVE,
                      "win_inset": WIN_INSET},
        "grids": GRIDS,
        "datums": DATUMS,
        "levels": LEVELS,
        "bounds": BOUNDS,
        "columns": _columns_drawn(),
        "openings": _openings(),
        "features": FEATURES,
        "drops": [{"idx": d[0], "grid_from": d[1], "grid_to": d[2], "x0": d[3], "x1": d[4],
                   "width_ft": d[5], "area_sf": d[6], "clear_bay": d[7], "note": d[8]}
                  for d in DROPS],
    }


# ============================================================================
# SELF-CHECK — the trace has to agree with itself before it reaches the DB
# ============================================================================

def verify_geometry() -> list:
    """Consistency failures in the traced data. A bad transcription is far cheaper to
    catch here than in a drop report."""
    bad = []
    if len(GRIDS) != 13:
        bad.append(f"expected 13 grids, got {len(GRIDS)}")
    if len(BOUNDS) != 13:
        bad.append(f"expected 13 bounds, got {len(BOUNDS)}")
    if len(DROPS) != 12:
        bad.append(f"expected 12 drops, got {len(DROPS)}")
    if len(LEVELS) != 5:
        bad.append(f"expected 5 levels, got {len(LEVELS)}")
    for idx, _gf, _gt, x0, x1, w, area, _cb, _n in DROPS:
        if abs((x1 - x0) - w) > 0.011:
            bad.append(f"drop {idx}: x1-x0={x1 - x0:.2f} != width_ft={w}")
        if abs(w * FACADE["height_ft"] - area) > 1.0:
            bad.append(f"drop {idx}: width*height={w * FACADE['height_ft']:.0f} != area_sf={area}")
        if abs(BOUNDS[idx - 1] - x0) > 0.011 or abs(BOUNDS[idx] - x1) > 0.011:
            bad.append(f"drop {idx}: extents disagree with BOUNDS")
    total = sum(d[5] for d in DROPS)
    if abs(total - FACADE["width_ft"]) > 0.05:
        bad.append(f"drop widths sum to {total:.2f}, facade is {FACADE['width_ft']}")
    n_open = len(_openings())
    if n_open != len(DROPS) * len(LEVELS) - len(NO_OPENING):
        bad.append(f"openings={n_open}, expected {len(DROPS) * len(LEVELS) - len(NO_OPENING)}")
    od = FEATURES["overhead_door"]
    l1 = next(lv for lv in LEVELS if lv["id"] == "L1")
    if abs(od["top"] - (l1["top"] - HEAD_BELOW)) > 0.02:
        bad.append("overhead door head does not align with the L1 window head")
    if not (DROPS[10][3] <= od["x0"] and od["x1"] <= DROPS[10][4]):
        bad.append("overhead door does not sit inside drop 11")
    st = FEATURES["stair_tower"]
    if not (DROPS[11][3] <= st["x0"] and st["x1"] <= DROPS[11][4]):
        bad.append("stair tower does not sit inside drop 12")
    return bad


def _now():
    return datetime.now().isoformat(timespec="seconds")   # LOCAL, never UTC


def seed(conn) -> dict:
    made = {"elevation": 0, "drops": 0, "cells": 0, "retraced": 0}
    geom = json.dumps(build_geometry())
    row = conn.execute("SELECT id FROM elevation WHERE project_code=? AND face=?",
                       (PROJECT, FACE)).fetchone()
    if row:
        elev_id = row["id"]
        conn.execute(
            "UPDATE elevation SET name=?, source_sheet=?, sheet_date=?, dob_job=?, "
            "scale_note=?, geometry_json=? WHERE id=?",
            ("North Elevation", SOURCE["sheet"], SOURCE["issued"], SOURCE["dob_job"],
             SCALE_NOTE, geom, elev_id))
        made["retraced"] = 1
    else:
        cur = conn.execute(
            "INSERT INTO elevation (project_code, face, name, source_sheet, sheet_date, "
            "dob_job, scale_note, geometry_json, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (PROJECT, FACE, "North Elevation", SOURCE["sheet"], SOURCE["issued"],
             SOURCE["dob_job"], SCALE_NOTE, geom, _now()))
        elev_id = cur.lastrowid
        made["elevation"] = 1

    for idx, g_from, g_to, x0, x1, width, area, _clear, note in DROPS:
        drops_link = f"{PROJECT}-DP{idx}"
        d = conn.execute("SELECT id FROM elevation_drop WHERE elevation_id=? AND idx=?",
                         (elev_id, idx)).fetchone()
        if d:
            drop_id = d["id"]
            conn.execute(
                "UPDATE elevation_drop SET grid_from=?, grid_to=?, x0=?, x1=?, width_ft=?, "
                "area_sf=?, note=?, drops_drop_id=? WHERE id=?",
                (g_from, g_to, x0, x1, width, area, note or None, drops_link, drop_id))
        else:
            cur = conn.execute(
                "INSERT INTO elevation_drop (elevation_id, idx, grid_from, grid_to, x0, x1, "
                "width_ft, area_sf, note, drops_drop_id) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (elev_id, idx, g_from, g_to, x0, x1, width, area, note or None, drops_link))
            drop_id = cur.lastrowid
            made["drops"] += 1

        # Cells are created ONCE and never reset by a re-trace — re-running this seed
        # must not wipe a morning's markup.
        for lv in LEVELS:
            c = conn.execute("SELECT id FROM elevation_cell WHERE drop_id=? AND level_id=?",
                             (drop_id, lv["id"])).fetchone()
            if c:
                conn.execute("UPDATE elevation_cell SET level_name=? WHERE id=?",
                             (lv["name"], c["id"]))
            else:
                conn.execute(
                    "INSERT INTO elevation_cell (drop_id, level_id, level_name, status_key, "
                    "updated_at) VALUES (?,?,?,'not_started',?)",
                    (drop_id, lv["id"], lv["name"], _now()))
                made["cells"] += 1
    conn.commit()
    return made


def main() -> int:
    bad = verify_geometry()
    print(f"[280-seed] geometry self-check: {'OK' if not bad else str(len(bad)) + ' PROBLEM(S)'}")
    for b in bad:
        print(f"           ! {b}")
    if bad:
        print("[280-seed] REFUSING to seed inconsistent geometry.")
        return 1

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
        print(f"[280-seed] backend={backend}  {made}")
        print(f"[280-seed] verify: drops={nd}/12  cells={nc}/60  openings={len(_openings())}/59"
              f"  -> {'OK' if ok else 'FAIL'}")
        print(f"[280-seed] basis={DIMENSION_BASIS} (traced+scaled, NOT dimensioned) "
              f"provisional={PROVISIONAL}")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
