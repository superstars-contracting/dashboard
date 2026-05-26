#!/usr/bin/env python3
"""Seed the first dashboard admin user (auth foundation #48).

One-shot interactive setup: prompts for email + password (twice, via
getpass so the terminal never echoes the password), then inserts an
`admin`-role row into users.

Refuses to run if any user already exists — bootstrap is the FIRST-user
path. Subsequent admins are added through the UI by an existing admin
(once that surface is built). This prevents accidental re-bootstrap
from clobbering or duplicating accounts.

PII discipline (per CLAUDE.md): the password never appears in stdout,
stderr, server.log, or any process listing. Only the email gets echoed
back to confirm. The bcrypt hash itself is stored in the DB but never
printed.

Run:
    python bootstrap_admin.py

Tailscale users: run on the workstation, not over SSH from a phone —
the password is typed plaintext in the local terminal, never goes
anywhere on the network.
"""
from __future__ import annotations

import getpass
import re
import sqlite3
import sys
from pathlib import Path

from auth import hash_password

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"

# Loose RFC-compliant email check — keeps obvious typos out, doesn't try
# to be exhaustive (no public sign-up here, the operator types this once).
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MIN_PASSWORD_LEN = 12  # one-operator workload, but still demand a real password


def _connect():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def _users_table_exists(conn) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone()
    return row is not None


def _existing_user_count(conn) -> int:
    return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def _prompt_email() -> str:
    while True:
        email = input("Admin email: ").strip().lower()
        if not email:
            print("  (required)")
            continue
        if not EMAIL_RE.match(email):
            print("  doesn't look like an email — try again")
            continue
        return email


def _prompt_full_name() -> str:
    while True:
        name = input("Full name: ").strip()
        if not name:
            print("  (required)")
            continue
        return name


def _prompt_password() -> str:
    while True:
        pw = getpass.getpass(f"Password (min {MIN_PASSWORD_LEN} chars): ")
        if len(pw) < MIN_PASSWORD_LEN:
            print(f"  too short — at least {MIN_PASSWORD_LEN} characters required")
            continue
        confirm = getpass.getpass("Confirm password: ")
        if pw != confirm:
            print("  doesn't match — try again")
            continue
        return pw


def main() -> int:
    conn = _connect()
    if not _users_table_exists(conn):
        print(
            "ERROR: users table does not exist. Run `python apply_auth_schema.py` "
            "first to create the auth schema, then re-run this script.",
            file=sys.stderr,
        )
        conn.close()
        return 1

    if _existing_user_count(conn) > 0:
        print(
            "ERROR: at least one user already exists. bootstrap_admin.py is the "
            "FIRST-user path only — add additional users via the dashboard once "
            "you're logged in as the existing admin.",
            file=sys.stderr,
        )
        conn.close()
        return 1

    print("=" * 60)
    print(" Superstars Dashboard — first-admin bootstrap")
    print("=" * 60)
    print("This creates the FIRST admin user for the dashboard.")
    print("After this, sign in at /login (or https://<tailnet>/login).")
    print("")

    email = _prompt_email()
    full_name = _prompt_full_name()
    password = _prompt_password()

    pw_hash = hash_password(password)
    # Scrub the plaintext from this process's memory as soon as we have the hash.
    # (Python strings are immutable so this is best-effort; the hash is the
    # value that lands on disk regardless.)
    del password

    try:
        conn.execute(
            "INSERT INTO users (email, password_hash, role, full_name, is_active) "
            "VALUES (?, ?, 'admin', ?, 1)",
            (email, pw_hash, full_name),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        print(f"ERROR: could not insert user — {e}", file=sys.stderr)
        conn.close()
        return 1

    row = conn.execute(
        "SELECT id, email, role, full_name FROM users WHERE email = ?", (email,)
    ).fetchone()
    conn.close()

    print("")
    print("✔ Admin created.")
    print(f"  id:    {row['id']}")
    print(f"  email: {row['email']}")
    print(f"  role:  {row['role']}")
    print(f"  name:  {row['full_name']}")
    print("")
    print("Sign in at /login.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
