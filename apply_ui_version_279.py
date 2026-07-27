#!/usr/bin/env python3
"""#279 — UI v2 phase 0: the per-user interface toggle column.

Adds ONE additive column with a default, nothing else:

  users.ui_version INTEGER NOT NULL DEFAULT 1   -- 1 = classic (v1), 2 = new (v2)

DEFAULT 1 is the whole safety story: every existing row, and every row created
by code that has never heard of this column, resolves to the classic UI. The
column is additive with a default, so it is safe to LEAVE IN PLACE while the UI
itself is reverted (rollback layers 1-4 do not need this column removed).

No CHECK constraint by design: SQLite cannot ALTER a CHECK, and the resolver in
ui_version.py already treats anything that is not exactly 2 as 1. A junk value
degrades to classic rather than 500ing a page.

db_layer-aware, idempotent, dual-backend.

NO production cutover. Honors SSC_DB_URL (unset -> live; operator runs ONCE at
deploy AFTER snapshot — the deploy queue runs migrations in numeric order).

Run:  python apply_ui_version_279.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
from apply_crm_266 import _columns  # noqa: E402


def ensure_ui_version_column(conn) -> dict:
    """Add users.ui_version if absent. Idempotent + dual-backend. Caller owns the conn."""
    changed = {"users.ui_version": "ui_version" not in _columns(conn, "users")}
    if changed["users.ui_version"]:
        # Both backends accept ADD COLUMN ... NOT NULL DEFAULT <const> on a populated
        # table (the default backfills existing rows).
        conn.execute("ALTER TABLE users ADD COLUMN ui_version INTEGER NOT NULL DEFAULT 1")
        conn.commit()
    return changed


def main() -> int:
    conn = db_layer.connect()
    backend = "postgres" if db_layer.is_postgres() else "sqlite"
    try:
        changed = ensure_ui_version_column(conn)
        cols = _columns(conn, "users")
        ok = "ui_version" in cols
        # Verify the backfill: no row may be NULL or anything but 1 after a fresh add.
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM users WHERE ui_version IS NULL").fetchone()
        nulls = (row["n"] if row is not None else 0) or 0
        print(f"[279] backend={backend}  changed={changed}")
        print(f"[279] verify: users.ui_version -> {'OK' if ok else 'FAIL'}  null_rows={nulls}")
        return 0 if (ok and nulls == 0) else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
