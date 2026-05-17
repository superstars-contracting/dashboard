#!/usr/bin/env python3
"""
Idempotent schema migration for Worker Intake feature.
Tolerates duplicate-column and table-already-exists errors so it can be re-run
freely. Runs each statement individually; counts what was applied vs. skipped.
"""

import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_worker_intake.sql"


def split_sql_statements(sql_text):
    """Naive splitter — works because none of our statements contain semicolons in strings."""
    # Strip out -- single-line comments
    cleaned_lines = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[:line.index("--")]
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)

    statements = []
    buf = []
    for ch in cleaned:
        buf.append(ch)
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt and stmt != ";":
                statements.append(stmt)
            buf = []
    return statements


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    if not SQL_PATH.exists():
        print(f"ERROR: schema_worker_intake.sql not found at {SQL_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    sql_text = SQL_PATH.read_text(encoding="utf-8")
    statements = split_sql_statements(sql_text)

    applied = skipped = failed = 0
    for stmt in statements:
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                skipped += 1
            else:
                print(f"ERROR on statement:\n  {stmt[:200]}...\n  {e}", file=sys.stderr)
                failed += 1
                # don't bail — keep applying the rest
        except sqlite3.IntegrityError as e:
            # INSERT OR IGNORE shouldn't hit this, but be safe
            skipped += 1
    conn.commit()

    # Report
    cert_count = conn.execute("SELECT COUNT(*) FROM cert_types").fetchone()[0]
    prereqs = conn.execute(
        "SELECT cert_type_id, name FROM cert_types WHERE is_cof_prerequisite = 1"
    ).fetchall()

    print(f"[schema] Worker Intake migration complete.")
    print(f"         Applied: {applied}, skipped (already existed): {skipped}, failed: {failed}")
    print(f"[seed]   {cert_count} cert types now in library.")
    print(f"[seed]   {len(prereqs)} flagged as CoF prerequisite:")
    for c in prereqs:
        print(f"           • {c[0]} — {c[1]}")

    conn.close()
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
