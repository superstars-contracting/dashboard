#!/usr/bin/env python3
"""Date-bounded wipe of DCR transactional data.

Deletes EVERY row in the DCR transactional tables whose date column falls
inside [START, END] inclusive. Also removes the per-sequence DCR output
directories on disk (data_room/reports/dcr/<project>/<NNN>/) for any
report_index row deleted, and deletes any photo files referenced by
rows in the photos table.

Reference data is untouched: employees, projects, project_assignments,
cert_types, certifications, cof_cards, company_id_cards, project_riggers,
app_settings, rfi_log, etc. — none of those have a per-day "date" column
in the same sense.

This is a one-shot cleanup, not a long-running migration. Re-running with
the same range is safe (no-op when the rows are already gone).
"""
import sqlite3
import sys
import shutil
from pathlib import Path
from collections import defaultdict

SCRIPT_DIR = Path(__file__).resolve().parent
import ssc_paths  # #287
DB_PATH = SCRIPT_DIR / "superstars.db"
REPORTS_ROOT = ssc_paths.under_root("data_room", "reports", "dcr")   # #287

START = "2026-05-04"
END   = "2026-05-17"

# (table_name, date_column) — every DCR-transactional table.
# work_log: 'date' (and 'updated_at' which is not a per-day filter).
# issues: also has 'due_date' but the wipe scopes by 'date' (the entry date).
TABLES = [
    ("report_index",         "report_date"),
    ("sign_in_log",          "date"),
    ("work_log",             "date"),
    ("deliveries",           "date"),
    ("equipment_log",        "date"),
    ("safety_events",        "date"),
    ("toolbox_talk_records", "date"),
    ("issues",               "date"),
    ("inspections",          "date"),
    ("visitors",             "date"),
    ("photos",               "date"),
    ("weather_log",          "date"),
]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    print(f"[wipe] Range: {START} .. {END} (inclusive)")
    print()

    # ---- 1) Capture file-system side effects BEFORE deleting rows. ----
    # For every DCR sequence in range, queue its output dir for removal.
    # For every photo row in range, queue its file_path for removal.
    seq_dirs_to_remove = set()
    for r in conn.execute(
        "SELECT DISTINCT project_code, dcr_sequence FROM report_index "
        "WHERE report_date BETWEEN ? AND ? AND dcr_sequence IS NOT NULL",
        (START, END),
    ).fetchall():
        seq_dirs_to_remove.add((r["project_code"], int(r["dcr_sequence"])))

    photo_files_to_remove = []
    try:
        photo_cols = [c[1] for c in conn.execute("PRAGMA table_info('photos')").fetchall()]
        path_col = None
        for cand in ("file_path", "path", "photo_path", "image_path"):
            if cand in photo_cols:
                path_col = cand
                break
        if path_col:
            for r in conn.execute(
                f"SELECT {path_col} AS p FROM photos WHERE date BETWEEN ? AND ?",
                (START, END),
            ).fetchall():
                if r["p"]:
                    photo_files_to_remove.append(r["p"])
    except sqlite3.OperationalError:
        pass

    # ---- 2) Delete rows per-table inside a transaction. ----------------
    before = {}
    after = {}
    deleted = {}
    for t, col in TABLES:
        try:
            before[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            cur = conn.execute(
                f"DELETE FROM {t} WHERE {col} BETWEEN ? AND ?",
                (START, END),
            )
            deleted[t] = cur.rowcount
            after[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.OperationalError as e:
            print(f"[wipe] WARN: {t}: {e}")
            before[t] = after[t] = deleted[t] = None
    conn.commit()

    # ---- 3) Delete on-disk sequence dirs + photo files. ---------------
    seq_dirs_removed = 0
    seq_dirs_missing = 0
    for project_code, seq in sorted(seq_dirs_to_remove):
        d = REPORTS_ROOT / project_code / f"{seq:03d}"
        if d.exists():
            shutil.rmtree(d, ignore_errors=True)
            seq_dirs_removed += 1
        else:
            seq_dirs_missing += 1

    photo_files_removed = 0
    photo_files_missing = 0
    for p in photo_files_to_remove:
        # Photo paths can be absolute or relative-to-project-root. Try both.
        candidates = [Path(p)]
        if not Path(p).is_absolute():
            candidates.append(SCRIPT_DIR / p)
        removed = False
        for c in candidates:
            if c.exists():
                try:
                    c.unlink()
                    removed = True
                    break
                except OSError:
                    pass
        if removed:
            photo_files_removed += 1
        else:
            photo_files_missing += 1

    # ---- 4) Report ----------------------------------------------------
    print(f"| {'table':22s} | {'before':>6s} | {'deleted':>7s} | {'after':>6s} | {'in-range now':>12s} |")
    print(f"|{'-'*24}|{'-'*8}|{'-'*9}|{'-'*8}|{'-'*14}|")
    grand_deleted = 0
    grand_in_range_now = 0
    for t, col in TABLES:
        if before[t] is None:
            continue
        # Confirm 0 in-range AFTER the wipe
        post = conn.execute(
            f"SELECT COUNT(*) FROM {t} WHERE {col} BETWEEN ? AND ?",
            (START, END),
        ).fetchone()[0]
        grand_in_range_now += post
        grand_deleted += deleted[t]
        print(f"| {t:22s} | {before[t]:>6d} | {deleted[t]:>7d} | {after[t]:>6d} | {post:>12d} |")
    print()
    print(f"[wipe] total rows deleted: {grand_deleted}")
    print(f"[wipe] post-wipe rows still in {START}..{END}: {grand_in_range_now}  (expect 0)")
    print(f"[wipe] sequence dirs removed: {seq_dirs_removed}  (already missing: {seq_dirs_missing})")
    print(f"[wipe] photo files removed:   {photo_files_removed}  (already missing: {photo_files_missing})")

    # ---- 5) Sanity-check the OUTSIDE-range counts stayed put ---------
    print()
    print("[wipe] sanity — totals across each table (outside-range should be untouched):")
    for t, col in TABLES:
        if before[t] is None:
            continue
        # outside-range = total - in-range (which should be 0). Before
        # was the same outside-range + the deleted in-range.
        outside_before = before[t] - deleted[t]
        if after[t] != outside_before:
            print(f"  WARN {t}: after={after[t]} but outside_before={outside_before} — out-of-range rows changed?")
    print()
    print(f"[wipe] reference data (untouched): employees={conn.execute('SELECT COUNT(*) FROM employees').fetchone()[0]}, "
          f"cert_types={conn.execute('SELECT COUNT(*) FROM cert_types').fetchone()[0]}, "
          f"certifications={conn.execute('SELECT COUNT(*) FROM certifications').fetchone()[0]}, "
          f"projects={conn.execute('SELECT COUNT(*) FROM projects').fetchone()[0]}, "
          f"cof_cards={conn.execute('SELECT COUNT(*) FROM cof_cards').fetchone()[0]}, "
          f"company_id_cards={conn.execute('SELECT COUNT(*) FROM company_id_cards').fetchone()[0]}, "
          f"rfi_log={conn.execute('SELECT COUNT(*) FROM rfi_log').fetchone()[0]}, "
          f"app_settings={conn.execute('SELECT COUNT(*) FROM app_settings').fetchone()[0]}")
    conn.close()
    return 0 if grand_in_range_now == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
