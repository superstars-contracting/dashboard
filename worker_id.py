"""Worker ID allocation — central source of truth for the W-#### identifier.

Worker IDs are human-facing labels (shown alongside the worker's name on
every surface where identity matters). The format is `W-` + zero-padded
4-digit sequence (W-0001, W-0002, ...). They're stable: once a worker has
an ID it never changes. New onboards get `max(existing) + 1` — numbers
are NEVER reused even after a worker is deleted.

These helpers are used by:
  - apply_worker_id_schema.py (backfill on first run)
  - import_workers.py (assign on bulk CSV import)
  - server.py POST /api/employees (assign on UI-driven onboard)

Distinct from the internal employee_id (E-#####) primary key: that one
is used by foreign keys (sign_in_log, project_assignments, certifications,
etc.) and stays the canonical join key. worker_id is for humans.
"""
import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent / "superstars.db"


def worker_id_for_display(employee_id):
    """Resolve an employee_id (E-#####) to the human-facing W-#### for
    use in operator-facing error/warning messages. Returns the W-####
    string if found, else None — callers should phrase the message so
    they NEVER echo the E-##### back to the operator (per CLAUDE.md
    terminology rule: nothing user-facing shows E-).

    Opens its own short-lived read-only connection so callers don't need
    to thread a conn into error-handling branches that may run before a
    conn is open."""
    if not employee_id:
        return None
    try:
        import db_layer  # #260 — honor SSC_DB_URL; production default = live SQLite.
        conn = db_layer.connect()
    except Exception:
        return None
    try:
        row = conn.execute(
            "SELECT worker_id FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    if not row:
        return None
    return row[0] or None


def next_worker_id_sequence(conn):
    """Return the next available worker_id sequence integer.

    Uses MAX+1 on the numeric portion of existing worker_ids. The numeric
    cast (SUBSTR + CAST) is the same pattern CLAUDE.md mandates for
    zero-padded IDs — lexicographic MAX would silently order 'W-0009'
    after 'W-0010'.
    """
    row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(worker_id, 3) AS INTEGER)) FROM employees "
        "WHERE worker_id LIKE 'W-%'"
    ).fetchone()
    return (row[0] or 0) + 1


def format_worker_id(seq):
    """Format an integer sequence as 'W-####' (zero-padded to 4 digits).

    Sequence is allowed to exceed 4 digits if the company grows past
    9999 workers — at that point the string just lengthens (W-10000).
    The format string keeps the leading-zero discipline for normal
    sub-10000 IDs so they sort visually as well as numerically.
    """
    return f"W-{seq:04d}"


def assign_worker_id(conn):
    """Allocate a new worker_id by reading + incrementing the max.

    Caller is expected to be inside a transaction that will then INSERT
    or UPDATE the employees row using the returned string. The caller
    owns the commit. The unique index on worker_id catches any race;
    if two callers concurrently read the same max, the second INSERT
    fails — caller should retry.
    """
    return format_worker_id(next_worker_id_sequence(conn))
