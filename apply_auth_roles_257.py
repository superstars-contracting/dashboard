#!/usr/bin/env python3
"""Idempotent migration for multi-user accounts & roles — Phase 1 (#257).

EXTENDS the #48 users table. SQLite cannot ALTER a CHECK constraint in place, so
the role-catalog expansion + new columns are applied via the documented
table-rebuild procedure (create new -> copy -> drop -> rename), guarded so a
re-run is a no-op. Then the additive audit tables (schema_auth_roles.sql) are
applied with CREATE IF NOT EXISTS.

Safety: snapshot the DB FIRST (caller does this). The rebuild preserves every
row id (sessions.user_id FK stays valid), runs under foreign_keys=OFF with a
foreign_key_check before COMMIT, and asserts the row count is unchanged. Every
existing column is preserved, so the #256 server keeps working before its
restart. No passwords/hashes are read or printed.

Run:  python apply_auth_roles_257.py
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
AUDIT_SQL = SCRIPT_DIR / "schema_auth_roles.sql"

ROLE_CATALOG = ('admin', 'c_suite', 'pm', 'super', 'client', 'architect', 'vendor')
_ROLE_LIST_SQL = ", ".join(f"'{r}'" for r in ROLE_CATALOG)

USERS_NEW_DDL = f"""
CREATE TABLE users_new (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ({_ROLE_LIST_SQL})),
  full_name TEXT NOT NULL,
  display_name TEXT,
  employee_id_link TEXT,
  is_active INTEGER NOT NULL DEFAULT 1,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','pending','disabled')),
  must_reset_password INTEGER NOT NULL DEFAULT 0,
  created_by TEXT,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  last_login_at TIMESTAMP,
  deactivated_at TIMESTAMP,
  FOREIGN KEY (employee_id_link) REFERENCES employees(employee_id)
);
"""

# Copy every existing column; backfill display_name<-full_name and
# status<-is_active. must_reset_password defaults to 0 for EXISTING accounts
# (the real admin + smoke fixture are NOT forced to reset).
USERS_COPY_SQL = """
INSERT INTO users_new
  (id, email, password_hash, role, full_name, display_name, employee_id_link,
   is_active, status, must_reset_password, created_by, created_at, last_login_at, deactivated_at)
SELECT
  id, email, password_hash, role, full_name, full_name, employee_id_link,
  is_active,
  CASE WHEN is_active = 1 THEN 'active' ELSE 'disabled' END,
  0, NULL, created_at, last_login_at, NULL
FROM users;
"""


def _split(sql_text: str):
    """Split a .sql file into statements, stripping -- line comments."""
    lines = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[:line.index("--")]
        lines.append(line)
    stmts, cur = [], []
    for ch in "\n".join(lines):
        cur.append(ch)
        if ch == ";":
            s = "".join(cur).strip()
            if s and s != ";":
                stmts.append(s)
            cur = []
    return stmts


def _already_migrated(conn) -> bool:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()
    sql = (row[0] if row else "") or ""
    new_cols = {"display_name", "status", "must_reset_password", "created_by", "deactivated_at"}
    has_cols = new_cols.issubset(cols)
    has_roles = all(f"'{r}'" in sql for r in ("client", "architect", "vendor"))
    return has_cols and has_roles


def _rebuild_users(conn) -> tuple[int, int]:
    """Documented SQLite table redefinition (a CHECK constraint can't be ALTERed in place)."""
    conn.isolation_level = None  # explicit transaction control
    conn.execute("PRAGMA foreign_keys=OFF;")
    before = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.execute("BEGIN;")
    try:
        conn.execute("DROP TABLE IF EXISTS users_new;")
        conn.execute(USERS_NEW_DDL)
        conn.execute(USERS_COPY_SQL)
        conn.execute("DROP TABLE users;")
        conn.execute("ALTER TABLE users_new RENAME TO users;")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_active ON users(is_active);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_users_status ON users(status);")
        after = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if after != before:
            raise RuntimeError(f"row count changed during rebuild: {before} -> {after}")
        # Scope the integrity check to the rebuild's blast radius: the new users
        # table (users->employees) and the children that reference it (sessions->
        # users). Ids are preserved, so any other child FK stays valid. A whole-DB
        # check would trip on 2 PRE-EXISTING orphans elsewhere (unrelated to auth).
        viol = (conn.execute("PRAGMA foreign_key_check(users)").fetchall()
                + conn.execute("PRAGMA foreign_key_check(sessions)").fetchall())
        if viol:
            raise RuntimeError(f"foreign_key_check (users/sessions) found {len(viol)} violation(s): {viol}")
        conn.execute("COMMIT;")
    except Exception:
        conn.execute("ROLLBACK;")
        raise
    finally:
        conn.execute("PRAGMA foreign_keys=ON;")
    return before, after


def main() -> int:
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA busy_timeout=60000;")
    try:
        if _already_migrated(conn):
            print("[257] users already migrated (role catalog + columns present) — skipping rebuild")
        else:
            before, after = _rebuild_users(conn)
            print(f"[257] users rebuilt: role catalog expanded + columns added; rows {before} -> {after} (preserved)")

        conn.isolation_level = ""  # default transaction handling for the audit DDL
        applied = skipped = 0
        for stmt in _split(AUDIT_SQL.read_text(encoding="utf-8")):
            try:
                conn.execute(stmt)
                applied += 1
            except sqlite3.OperationalError as e:
                if "already exists" in str(e).lower():
                    skipped += 1
                else:
                    raise
        conn.commit()

        # report — counts/shape only, no PII
        cols = [r[1] for r in conn.execute("PRAGMA table_info(users)").fetchall()]
        users_sql = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='users'").fetchone()[0]
        roles_ok = all(f"'{r}'" in users_sql for r in ROLE_CATALOG)
        ntables = sorted(t[0] for t in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('login_audit','role_change_audit')").fetchall())
        nusers = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        print(f"[257] audit DDL: applied={applied} skipped={skipped}; audit tables present={ntables}")
        print(f"[257] users columns: {cols}")
        print(f"[257] role catalog complete (7 roles): {roles_ok}; users={nusers}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
