#!/usr/bin/env python3
"""#261 — Google SSO schema: add users.google_sub + login_audit.method.

db_layer-aware, idempotent, works on BOTH backends (SQLite default / Postgres via
SSC_DB_URL), following the #259/#260 dialect patterns. Adds:

  * users.google_sub   TEXT (nullable, UNIQUE) — the stable Google account id (the
    OIDC `sub` claim), stored on a user's first successful Google sign-in to harden
    the email -> account link (a Workspace email can change; the sub is stable).
  * login_audit.method TEXT (nullable) — 'google' for SSO logins, NULL for the
    existing email/password path, so the audit distinguishes the two login methods.

Idempotent: each ADD COLUMN is guarded by a BACKEND-AWARE column check — `PRAGMA
table_info` returns nothing on Postgres (db_layer no-ops PRAGMA), so we read
`information_schema.columns` there. The UNIQUE index uses CREATE UNIQUE INDEX IF NOT
EXISTS (valid on both; both backends allow multiple NULLs in a unique index, so
not-yet-linked accounts never collide).

NO production cutover. Honors SSC_DB_URL, so the SAME script serves:
  * unset           -> live superstars.db (operator runs this ONCE at deploy, AFTER
                       snapshotting — see CLAUDE.md operational-discipline rule)
  * sqlite:///<copy> / postgresql://...ssc_test -> the isolated test DBs (the gate)

Run:  python apply_google_sso_261.py
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402  # env-driven layer (SQLite default), per #259/#260


def _columns(conn, table: str) -> set:
    """Column names for `table`, backend-aware. PRAGMA table_info is a no-op on
    Postgres (db_layer returns an empty cursor for PRAGMA), so read the catalog there."""
    if db_layer.is_postgres():
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ?",
            (table,),
        ).fetchall()
        return {r[0] for r in rows}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def ensure_google_sso_schema(conn) -> dict:
    """Add google_sub + login_audit.method + the unique index if missing. Idempotent
    and dual-backend. Returns {what: bool_changed} for the log / smoke self-check.
    Caller owns the connection (so the smoke can pass its db_layer.connect())."""
    changed = {"google_sub": False, "login_audit_method": False}
    if "google_sub" not in _columns(conn, "users"):
        conn.execute("ALTER TABLE users ADD COLUMN google_sub TEXT")
        changed["google_sub"] = True
    if "method" not in _columns(conn, "login_audit"):
        conn.execute("ALTER TABLE login_audit ADD COLUMN method TEXT")
        changed["login_audit_method"] = True
    # Unique on non-null subs; multiple NULLs allowed on SQLite AND Postgres, so
    # unlinked accounts (google_sub IS NULL) never collide.
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub)")
    conn.commit()
    return changed


def main() -> int:
    conn = db_layer.connect()
    backend = "postgres" if db_layer.is_postgres() else "sqlite"
    try:
        changed = ensure_google_sso_schema(conn)
        ucols = _columns(conn, "users")
        lacols = _columns(conn, "login_audit")
        ok = ("google_sub" in ucols) and ("method" in lacols)
        print(f"[261] backend={backend}  added google_sub={changed['google_sub']}  "
              f"added login_audit.method={changed['login_audit_method']}  unique_index=ensured")
        print(f"[261] verify: users.google_sub={'google_sub' in ucols}  "
              f"login_audit.method={'method' in lacols}  -> {'OK' if ok else 'FAIL'}")
        return 0 if ok else 1
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
