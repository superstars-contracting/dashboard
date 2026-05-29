"""#199 — Drop Plan Batch A smoke (synthetic-only, SMK- prefixed).

Exercises all eight drop-plan tables against the real DB using only
SMK--prefixed synthetic rows (under FR-BX-001 so FKs are satisfied),
cleaned up in `finally`. Asserts the design's load-bearing invariants:

  * per-table insert/assert
  * APPEND-ONLY quantities: two entries on the same drop+SOV SUM (not
    overwrite) — the overwrite-loses-history class is designed out
  * generated volume_cf = area_sf * depth_in / 12 (10sf,8in -> 6.6667;
    NULL when depth missing)
  * LOCAL-date round-trip: write date.today(), read back, no UTC
    off-by-one (#74/#77 — this system is entirely date-driven)
  * STRESS to 100 drops (+1100 stage rows): insert/query perform, then
    delete all synthetic and confirm only the 35 real drops remain

PII discipline: logged_by is a W-#### / id token; no names anywhere.
Prints booleans + counts + timings only.

Run:
  python tests/smoke_dropplan.py
"""
from __future__ import annotations

import datetime as _dt
import sqlite3
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB = SCRIPT_DIR / "superstars.db"
PROJECT = "FR-BX-001"
PASS, FAIL = 0, 0


def check(label, ok, note=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}" + (f" — {note}" if note else ""))


def cleanup(conn):
    """Remove every SMK--prefixed synthetic row across all 8 tables.
    Children first (FK-safe regardless of PRAGMA foreign_keys)."""
    conn.execute("DELETE FROM quantity_entries WHERE drop_id LIKE 'SMK-%' "
                 "OR sov_line_item IN (SELECT sov_id FROM sov_line_items WHERE sov_code LIKE 'SMK-%')")
    conn.execute("DELETE FROM expense_entries WHERE drop_id LIKE 'SMK-%' OR note LIKE 'SMK-%'")
    conn.execute("DELETE FROM drop_stage_status WHERE drop_id LIKE 'SMK-%'")
    conn.execute("DELETE FROM drops WHERE drop_id LIKE 'SMK-%'")
    conn.execute("DELETE FROM stage_template_steps WHERE template_id IN "
                 "(SELECT template_id FROM stage_templates WHERE name LIKE 'SMK-%')")
    conn.execute("DELETE FROM stage_templates WHERE name LIKE 'SMK-%'")
    conn.execute("DELETE FROM sov_line_items WHERE sov_code LIKE 'SMK-%'")
    conn.execute("DELETE FROM paint_phases WHERE elevation LIKE 'SMK-%' OR project_code LIKE 'SMK-%'")
    conn.commit()


def main() -> int:
    conn = sqlite3.connect(str(DB), timeout=60.0)
    conn.execute("PRAGMA busy_timeout=60000;")
    try:
        cleanup(conn)
        today = _dt.date.today().isoformat()

        # baseline real counts (must be untouched at the end)
        real_drops0 = conn.execute(
            "SELECT COUNT(*) FROM drops WHERE project_code=? AND drop_id NOT LIKE 'SMK-%'", (PROJECT,)).fetchone()[0]
        check("baseline: 35 real FR-BX-001 drops", real_drops0 == 35, f"got {real_drops0}")

        # ---- per-table inserts ----
        conn.execute("INSERT INTO drops(drop_id,project_code,elevation,sequence_no,lifecycle) "
                     "VALUES('SMK-DP-T1',?, 'North',9001,'not_started')", (PROJECT,))
        check("drops insert", conn.execute("SELECT COUNT(*) FROM drops WHERE drop_id='SMK-DP-T1'").fetchone()[0] == 1)

        conn.execute("INSERT INTO stage_templates(project_code,name) VALUES(?, 'SMK-tmpl')", (PROJECT,))
        tid = conn.execute("SELECT template_id FROM stage_templates WHERE name='SMK-tmpl'").fetchone()[0]
        conn.execute("INSERT INTO stage_template_steps(template_id,step_no,name,default_working_days,is_cure_gate) "
                     "VALUES(?,1,'SMK-step',2.0,1)", (tid,))
        check("stage_templates + steps insert",
              conn.execute("SELECT COUNT(*) FROM stage_template_steps WHERE template_id=?", (tid,)).fetchone()[0] == 1)

        conn.execute("INSERT INTO drop_stage_status(drop_id,step_no,status,started_on) "
                     "VALUES('SMK-DP-T1',1,'in_progress',?)", (today,))
        check("drop_stage_status insert", conn.execute(
            "SELECT COUNT(*) FROM drop_stage_status WHERE drop_id='SMK-DP-T1'").fetchone()[0] == 1)

        conn.execute("INSERT INTO sov_line_items(project_code,sov_code,description,unit) "
                     "VALUES(?, 'SMK-SOV1','SMK synthetic line','CF')", (PROJECT,))
        sid = conn.execute("SELECT sov_id FROM sov_line_items WHERE sov_code='SMK-SOV1'").fetchone()[0]
        check("sov_line_items insert", sid is not None)

        conn.execute("INSERT INTO expense_entries(project_code,drop_id,category,amount,logged_on,logged_by,source,note) "
                     "VALUES(?, 'SMK-DP-T1','material',1.00,?, 'W-0001','manual','SMK-exp')", (PROJECT, today))
        check("expense_entries insert (synthetic $1.00, logged_by W-####)",
              conn.execute("SELECT COUNT(*) FROM expense_entries WHERE note='SMK-exp'").fetchone()[0] == 1)

        conn.execute("INSERT INTO paint_phases(project_code,elevation,status) VALUES(?, 'SMK-Elev','not_ready')", (PROJECT,))
        check("paint_phases insert", conn.execute(
            "SELECT COUNT(*) FROM paint_phases WHERE elevation='SMK-Elev'").fetchone()[0] == 1)

        # ---- APPEND-ONLY: two entries on same drop+SOV SUM, not overwrite ----
        conn.execute("INSERT INTO quantity_entries(drop_id,sov_line_item,quantity,unit,logged_on,logged_by) "
                     "VALUES('SMK-DP-T1',?,5.0,'CF',?, 'W-0001')", (sid, today))
        conn.execute("INSERT INTO quantity_entries(drop_id,sov_line_item,quantity,unit,logged_on,logged_by) "
                     "VALUES('SMK-DP-T1',?,3.0,'CF',?, 'W-0001')", (sid, today))
        n_entries = conn.execute("SELECT COUNT(*) FROM quantity_entries WHERE drop_id='SMK-DP-T1' AND sov_line_item=?", (sid,)).fetchone()[0]
        total = conn.execute("SELECT SUM(quantity) FROM quantity_entries WHERE drop_id='SMK-DP-T1' AND sov_line_item=?", (sid,)).fetchone()[0]
        check("APPEND: two qty entries persist as 2 rows (no overwrite)", n_entries == 2, f"rows={n_entries}")
        check("APPEND: total = SUM(entries) = 8.0", abs(total - 8.0) < 1e-9, f"sum={total}")

        # ---- generated volume_cf ----
        conn.execute("INSERT INTO quantity_entries(drop_id,sov_line_item,area_sf,depth_in,unit,logged_on,logged_by) "
                     "VALUES('SMK-DP-T1',?,10,8,'CF',?, 'W-0001')", (sid, today))
        vol = conn.execute("SELECT volume_cf FROM quantity_entries WHERE drop_id='SMK-DP-T1' AND area_sf=10 AND depth_in=8").fetchone()[0]
        check("volume_cf = area*depth/12 (10sf,8in -> 6.6667)", vol is not None and abs(vol - 6.6667) < 0.001, f"vol={vol}")
        conn.execute("INSERT INTO quantity_entries(drop_id,sov_line_item,area_sf,unit,logged_on,logged_by) "
                     "VALUES('SMK-DP-T1',?,10,'CF',?, 'W-0001')", (sid, today))
        vol_nodepth = conn.execute("SELECT volume_cf FROM quantity_entries WHERE drop_id='SMK-DP-T1' AND area_sf=10 AND depth_in IS NULL").fetchone()[0]
        check("volume_cf NULL when depth missing", vol_nodepth is None)

        # ---- LOCAL-date round-trip (no UTC off-by-one) ----
        rt = conn.execute("SELECT logged_on FROM quantity_entries WHERE drop_id='SMK-DP-T1' ORDER BY entry_id LIMIT 1").fetchone()[0]
        check("LOCAL-date round-trip: logged_on == today (no UTC shift)", rt == today, f"stored={rt} today={today}")
        rt2 = conn.execute("SELECT started_on FROM drop_stage_status WHERE drop_id='SMK-DP-T1' AND step_no=1").fetchone()[0]
        check("LOCAL-date round-trip: stage started_on == today", rt2 == today, f"stored={rt2} today={today}")

        # ---- PII-safety: logged_by is W-#### / id token, never a name ----
        bys = [r[0] for r in conn.execute("SELECT DISTINCT logged_by FROM quantity_entries WHERE drop_id='SMK-DP-T1'").fetchall()]
        check("logged_by is W-#### token (PII-safe)", all(b is None or b.startswith('W-') for b in bys), f"{bys}")

        conn.commit()

        # ---- STRESS to 100 drops (+1100 stage rows) ----
        t0 = time.time()
        conn.execute("BEGIN")
        for i in range(1, 101):
            did = f"SMK-STRESS-{i:04d}"
            conn.execute("INSERT INTO drops(drop_id,project_code,elevation,sequence_no,lifecycle) "
                         "VALUES(?,?,?,?, 'not_started')", (did, PROJECT, "North", 10000 + i))
            for step in range(1, 12):
                conn.execute("INSERT INTO drop_stage_status(drop_id,step_no,status) VALUES(?,?, 'not_started')", (did, step))
        conn.commit()
        insert_dt = time.time() - t0
        stress_drops = conn.execute("SELECT COUNT(*) FROM drops WHERE drop_id LIKE 'SMK-STRESS-%'").fetchone()[0]
        stress_rows = conn.execute("SELECT COUNT(*) FROM drop_stage_status WHERE drop_id LIKE 'SMK-STRESS-%'").fetchone()[0]
        check("STRESS: 100 synthetic drops inserted", stress_drops == 100, f"got {stress_drops}")
        check("STRESS: 1100 synthetic stage rows inserted", stress_rows == 1100, f"got {stress_rows}")
        check(f"STRESS: insert perf OK ({insert_dt:.2f}s for 1200 rows)", insert_dt < 15.0, f"{insert_dt:.2f}s")
        # roll-up query perf across the now-larger table
        t1 = time.time()
        rollup = conn.execute(
            "SELECT d.drop_id, COUNT(*) FROM drops d JOIN drop_stage_status s ON s.drop_id=d.drop_id "
            "WHERE d.project_code=? GROUP BY d.drop_id", (PROJECT,)).fetchall()
        query_dt = time.time() - t1
        check(f"STRESS: roll-up query perf OK ({query_dt:.3f}s, {len(rollup)} drops)", query_dt < 2.0, f"{query_dt:.3f}s")

        # delete the stress synthetics, confirm only the 35 real remain
        conn.execute("DELETE FROM drop_stage_status WHERE drop_id LIKE 'SMK-STRESS-%'")
        conn.execute("DELETE FROM drops WHERE drop_id LIKE 'SMK-STRESS-%'")
        conn.commit()
        after_stress = conn.execute(
            "SELECT COUNT(*) FROM drops WHERE project_code=? AND drop_id NOT LIKE 'SMK-%'", (PROJECT,)).fetchone()[0]
        check("STRESS cleanup: 35 real drops remain", after_stress == 35, f"got {after_stress}")

    finally:
        cleanup(conn)
        # confirm full synthetic purge + real counts intact
        smk_left = conn.execute("SELECT COUNT(*) FROM drops WHERE drop_id LIKE 'SMK-%'").fetchone()[0]
        real_drops = conn.execute("SELECT COUNT(*) FROM drops WHERE project_code=? AND drop_id NOT LIKE 'SMK-%'", (PROJECT,)).fetchone()[0]
        real_sov = conn.execute("SELECT COUNT(*) FROM sov_line_items WHERE project_code=? AND sov_code NOT LIKE 'SMK-%'", (PROJECT,)).fetchone()[0]
        real_paint = conn.execute("SELECT COUNT(*) FROM paint_phases WHERE project_code=? AND elevation NOT LIKE 'SMK-%'", (PROJECT,)).fetchone()[0]
        conn.close()
        print()
        print(f"  cleanup: SMK- drops left = {smk_left}; real drops = {real_drops}; "
              f"real SOV = {real_sov}; real paint = {real_paint}")
        check("cleanup: 0 synthetic drops remain", smk_left == 0)
        check("cleanup: real seed intact (35 drops / 11 SOV / 4 paint)",
              real_drops == 35 and real_sov == 11 and real_paint == 4)

    print()
    print(f"=== Drop Plan smoke: {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
