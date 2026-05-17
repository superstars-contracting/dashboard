#!/usr/bin/env python3
"""Pre-deployment wipe of sample workers and all their dependent records.

Distinct from cleanup_sample_workers.py, which targets only the 5 newer rows
(E-00013..E-00017) added in a botched seed attempt and intentionally preserves
the 12 legacy E-001..E-012 rows. This script wipes ALL rows from the employees
table and every table that FK-references it, plus per-worker folders on disk
under worker_records/.

Run before importing the real worker roster. The legacy 12 must also go so
next-numeric-ID logic starts from a clean slate and fake sign-in history does
not pollute future analytics. Safe to re-run: if the database is already clean,
prints "nothing to delete" and exits 0.

  python cleanup_all_sample_workers.py             # dry-run (default)
  python cleanup_all_sample_workers.py --execute   # actually delete
"""

import argparse
import re
import shutil
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
WORKER_RECORDS_DIR = SCRIPT_DIR / "worker_records"

# Dependent-first order. SQLite has foreign_keys=OFF by default so no cascades
# fire — manual ordering is what guarantees we never leave orphan rows even if
# FK enforcement is turned on in a future session.
DEPENDENT_TABLES = [
    "sign_in_log",
    "cof_cards",
    "certifications",
    "worker_documents",
    "employee_documents",
    "identifications",
    "project_assignments",
    "employee_assignments",
]
ROOT_TABLE = "employees"

# Matches worker_records/E-00013_Jose_Vargas etc. — any slug suffix.
EMPLOYEE_FOLDER_RE = re.compile(r"^E-\d+_")


def count_table(conn, table):
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def matching_folders():
    if not WORKER_RECORDS_DIR.exists():
        return []
    return sorted(
        p for p in WORKER_RECORDS_DIR.iterdir()
        if p.is_dir() and EMPLOYEE_FOLDER_RE.match(p.name)
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--execute", action="store_true",
        help="Actually delete. Without this flag, runs dry."
    )
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    pre_counts = {t: count_table(conn, t) for t in [ROOT_TABLE] + DEPENDENT_TABLES}
    folders = matching_folders()

    if all(v == 0 for v in pre_counts.values()) and not folders:
        print(
            "Database is already clean: no employees, no dependent rows, "
            "no matching worker_records folders. Nothing to delete."
        )
        conn.close()
        return 0

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"[{mode}] Pre-deployment cleanup of sample workers")
    print()
    print("Database rows that would be deleted:")
    for t in DEPENDENT_TABLES + [ROOT_TABLE]:
        print(f"  {t:<24}  {pre_counts[t]:>6} row(s)")

    print()
    print(f"Disk folders that would be deleted under {WORKER_RECORDS_DIR.name}/:")
    if folders:
        for f in folders:
            print(f"  {f.name}")
    else:
        print("  (none)")

    if not args.execute:
        print()
        print("Dry-run only. Re-run with --execute to actually delete.")
        conn.close()
        return 0

    print()
    print("Executing deletions...")
    deleted = {}
    try:
        for t in DEPENDENT_TABLES:
            cur = conn.execute(f"DELETE FROM {t}")
            deleted[t] = cur.rowcount
        cur = conn.execute(f"DELETE FROM {ROOT_TABLE}")
        deleted[ROOT_TABLE] = cur.rowcount
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"ERROR: SQL failure, transaction rolled back: {e}", file=sys.stderr)
        conn.close()
        return 1

    folders_removed = 0
    for f in folders:
        try:
            shutil.rmtree(f)
            folders_removed += 1
        except OSError as e:
            print(f"  WARN: could not remove {f}: {e}", file=sys.stderr)

    post_counts = {t: count_table(conn, t) for t in [ROOT_TABLE] + DEPENDENT_TABLES}
    conn.close()

    print()
    print("Deletion summary:")
    for t in DEPENDENT_TABLES + [ROOT_TABLE]:
        print(f"  {t:<24}  deleted={deleted[t]:>6}  remaining={post_counts[t]}")
    print(f"  worker_records folders    deleted={folders_removed}")

    leftovers = {t: c for t, c in post_counts.items() if c != 0}
    if leftovers:
        print()
        print(f"WARNING: non-zero rows remain in: {leftovers}", file=sys.stderr)
        return 2

    print()
    print("Cleanup complete. employees and dependents are empty.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
