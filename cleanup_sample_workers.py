#!/usr/bin/env python3
"""
Cleans up corrupted sample workers from the bad first seed attempt.
Deletes:
  - The single E-00013 employee record (which has all 5 sample workers' certs piled on)
  - All certifications attached to E-00013
  - All worker_documents attached to E-00013
  - All project_assignments for E-00013
  - The disk folders created for the 5 sample workers (E-00013_*)

Original pre-existing employees (12 from the seed data) are NOT touched.

Run:    python cleanup_sample_workers.py
"""

import sqlite3
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
WORKER_RECORDS_DIR = SCRIPT_DIR / "worker_records"

# Names that were inserted as sample workers (from create_sample_workers.py)
SAMPLE_NAMES = {"Jose Vargas", "Miguel Hernandez", "Carlos Rodriguez",
                "Pedro Castillo", "Anton Kowalski"}


def main():
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    # Find which employees match a sample name (likely just E-00013 with last-write-wins name)
    rows = conn.execute(
        "SELECT employee_id, name, folder_path FROM employees WHERE name IN (" +
        ",".join("?" * len(SAMPLE_NAMES)) + ")",
        tuple(SAMPLE_NAMES)
    ).fetchall()

    if not rows:
        print("No sample workers found in DB. Nothing to clean.")
        # Still try to clean folders
    else:
        for r in rows:
            eid = r["employee_id"]
            name = r["name"]
            print(f"  Deleting employee {eid} ({name})")
            n_certs = conn.execute(
                "DELETE FROM certifications WHERE employee_id = ?", (eid,)
            ).rowcount
            n_docs = conn.execute(
                "DELETE FROM worker_documents WHERE employee_id = ?", (eid,)
            ).rowcount
            n_asgn = conn.execute(
                "DELETE FROM project_assignments WHERE employee_id = ?", (eid,)
            ).rowcount
            conn.execute(
                "DELETE FROM employees WHERE employee_id = ?", (eid,)
            )
            print(f"    purged: {n_certs} certs, {n_docs} docs, {n_asgn} assignments")

    conn.commit()
    conn.close()

    # Clean up disk folders matching sample names
    if WORKER_RECORDS_DIR.exists():
        removed = 0
        for folder in WORKER_RECORDS_DIR.iterdir():
            if not folder.is_dir():
                continue
            folder_name = folder.name
            # Match if folder name contains a slugified sample worker name
            for sample in SAMPLE_NAMES:
                slug = sample.replace(" ", "_")
                if slug in folder_name:
                    print(f"  Removing folder: {folder.name}")
                    try:
                        shutil.rmtree(folder)
                        removed += 1
                    except Exception as e:
                        print(f"    WARN: could not remove {folder}: {e}")
                    break
        print(f"\n  Removed {removed} sample worker folders.")

    print("\nDone. You can now re-run create_sample_workers.py to re-seed cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
