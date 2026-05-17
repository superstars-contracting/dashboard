#!/usr/bin/env python3
"""
Idempotent schema migration for the Certificate of Fitness feature.
Tolerates ALTER TABLE failures when columns already exist.
Reports what was applied vs. skipped.
"""

import sqlite3
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_cof.sql"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    if not SQL_PATH.exists():
        print(f"ERROR: schema_cof.sql not found at {SQL_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    sql_text = SQL_PATH.read_text(encoding="utf-8")

    # Pull ALTER TABLE statements out (run individually; tolerate dup columns)
    alter_re = re.compile(r"^ALTER TABLE.*?;$", re.MULTILINE)
    alters = alter_re.findall(sql_text)
    remainder = alter_re.sub("", sql_text)

    added = skipped = 0
    for alter in alters:
        try:
            conn.execute(alter)
            added += 1
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                skipped += 1
            else:
                print(f"ERROR on: {alter}\n  {e}", file=sys.stderr)
                return 1

    # Run the rest as a script
    conn.executescript(remainder)
    conn.commit()

    # Report on the prerequisite flag
    flagged = conn.execute(
        "SELECT cert_type_id, name FROM cert_types WHERE is_cof_prerequisite = 1"
    ).fetchall()
    conn.close()

    print(f"[schema] CoF tables ready ({added} columns added, {skipped} already existed).")
    if flagged:
        print(f"[seed]   Marked {len(flagged)} cert type(s) as CoF prerequisite:")
        for r in flagged:
            print(f"           • {r[0]} — {r[1]}")
    else:
        print("[seed]   WARNING: No cert type matched the '16-hr Suspended Scaffold' pattern.")
        print("[seed]   You'll need to manually flag the right cert_type via the dashboard")
        print("[seed]   or by running: UPDATE cert_types SET is_cof_prerequisite=1 WHERE cert_type_id='YOUR_ID';")
    return 0


if __name__ == "__main__":
    sys.exit(main())
