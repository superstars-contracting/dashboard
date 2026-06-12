#!/usr/bin/env python3
"""#246 — canonical worker-roster views. Idempotent (DROP + CREATE).

THE rule (#241), defined once, consumed everywhere:
  labor_worker_state.status is the single source of truth for whether a
  worker is active; a worker with NO state row is active (LEFT JOIN
  semantics). Surfaces must consume these views — never re-implement
  the join (CLAUDE.md roster rule, added in #246):

  v_worker_roster   — every employee + labor_status ('active'/'inactive').
                      For MASTER surfaces (Workforce roster, profile) that
                      show everyone with an Inactive badge, and for
                      consumers with their own inclusion rule (payroll's
                      active-or-has-hours).
  v_active_workers  — the operational roster: not archived AND labor-
                      active. For every selector/gallery/count where
                      project work happens.

Views are additive DDL — re-running is safe; the DROP refreshes the
definition when this file changes.
"""
import sqlite3
from pathlib import Path

DB = Path(__file__).resolve().parent / "superstars.db"

STATEMENTS = [
    "DROP VIEW IF EXISTS v_active_workers",
    "DROP VIEW IF EXISTS v_worker_roster",
    """
    CREATE VIEW v_worker_roster AS
    SELECT e.*, COALESCE(ls.status, 'active') AS labor_status
    FROM employees e
    LEFT JOIN labor_worker_state ls ON ls.worker_id = e.worker_id
    """,
    """
    CREATE VIEW v_active_workers AS
    SELECT * FROM v_worker_roster
    WHERE archived_at IS NULL AND labor_status = 'active'
    """,
]


def main():
    conn = sqlite3.connect(str(DB), timeout=60.0)
    try:
        applied = 0
        for stmt in STATEMENTS:
            conn.execute(stmt)
            applied += 1
        conn.commit()
        # PII-safe sanity: counts only.
        total = conn.execute("SELECT COUNT(*) FROM v_worker_roster").fetchone()[0]
        active = conn.execute("SELECT COUNT(*) FROM v_active_workers").fetchone()[0]
        print(f"roster views applied ({applied} statements): "
              f"v_worker_roster={total} rows, v_active_workers={active} rows")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
