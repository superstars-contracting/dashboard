"""#262 — clean FK-OFF orphan rows in an ISOLATED gate DB. NEVER run against live.

The live SQLite DB ran with FK enforcement OFF (#259/#260 finding), leaving child rows
whose user_id / actor reference a since-DELETED users.id. A raw file copy of live (the
SQLite gate DB) inherits those orphans. When a smoke then creates a FRESH user whose new
auto-increment id COLLIDES with an orphan's reference, the enforced FK on the copy blocks
deleting that user at cleanup -> 'FOREIGN KEY constraint failed' (surfaced when the live
DB grew enough that test-user ids reached the orphan ids, e.g. 99/110).

This NULLs the orphan reference where the column is nullable and DELETEs the orphan row
where it's NOT NULL — exactly what migrate_sqlite_to_pg_259.py already does for the
Postgres path (so PG is clean; this brings the SQLite copy to parity). Idempotent: a
no-op on an already-consistent DB.

Honors SSC_DB_URL. Intended for the isolated gate copy (sqlite:///<snapshot-copy>); it
refuses to do anything on Postgres (the migration handles it there).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db_layer  # noqa: E402

# Every child column that references users.id (PRAGMA foreign_key_list confirms these).
_USER_CHILD_FKS = [
    ("sessions", "user_id"),
    ("login_audit", "user_id"),
    ("audit_log", "actor_user_id"),
    ("role_change_audit", "user_id"),
    ("role_change_audit", "changed_by"),
    ("worker_rates", "created_by"),
    ("dashboard_layouts", "user_id"),
]


def _colinfo(conn, table):
    """{col: notnull_bool} for an existing table, else {}."""
    return {r[1]: bool(r[3]) for r in conn.execute('PRAGMA table_info("%s")' % table).fetchall()}


def clean(conn) -> list:
    fixed = []
    for table, col in _USER_CHILD_FKS:
        info = _colinfo(conn, table)
        if col not in info:
            continue
        where = ('"%s" IS NOT NULL AND NOT EXISTS '
                 '(SELECT 1 FROM users u WHERE u.id = "%s"."%s")' % (col, table, col))
        n = conn.execute('SELECT COUNT(*) FROM "%s" WHERE %s' % (table, where)).fetchone()[0]
        if not n:
            continue
        if info[col]:  # NOT NULL -> can't NULL it; delete the orphan child row
            conn.execute('DELETE FROM "%s" WHERE %s' % (table, where))
            fixed.append("%s.%s DELETED %d orphan(s)" % (table, col, n))
        else:
            conn.execute('UPDATE "%s" SET "%s"=NULL WHERE %s' % (table, col, where))
            fixed.append("%s.%s NULLed %d orphan ref(s)" % (table, col, n))
    conn.commit()
    return fixed


def main() -> int:
    if db_layer.is_postgres():
        print("[orphans] Postgres path cleans orphans during the migration — nothing to do.")
        return 0
    conn = db_layer.connect()  # FK enforcement OFF by default — fine for NULL/DELETE of orphans
    try:
        fixed = clean(conn)
        print("[orphans] " + ("; ".join(fixed) if fixed else "already consistent (no orphans)"))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
