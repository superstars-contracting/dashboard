#!/usr/bin/env python3
"""
Idempotent schema migration for the NYC Compliance Watch tables.
Applies schema_compliance.sql; tolerates ALTER TABLE failures
when columns already exist (re-runnable).
"""

import sqlite3
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_compliance.sql"


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    if not SQL_PATH.exists():
        print(f"ERROR: schema_compliance.sql not found at {SQL_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH))
    sql_text = SQL_PATH.read_text(encoding="utf-8")

    # Strip out one-line ALTER TABLE statements; run individually so
    # "duplicate column" errors don't block the rest of the script.
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

    conn.executescript(remainder)
    conn.commit()
    conn.close()

    print(f"[schema] Compliance tables ready ({added} columns added, {skipped} already existed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
