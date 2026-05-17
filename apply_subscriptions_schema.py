#!/usr/bin/env python3
"""Idempotent migration: subscriptions table + monthly_burn / upcoming_renewals views.

Run once on the workstation to create the schema. Re-runnable safely (duplicate
column / already-exists errors are caught and counted as skipped).

After the schema is created, run import_subscriptions_from_csv() to load the
seed rows from subscriptions_ledger.csv. From then on, the dashboard is the
source of truth and the CSV becomes a historical record.
"""
import csv
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_subscriptions.sql"
CSV_PATH = SCRIPT_DIR / "subscriptions_ledger.csv"


def split_statements(sql_text):
    """Split SQL into individual statements, stripping line comments."""
    cleaned = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[:line.index("--")]
        cleaned.append(line)
    text = "\n".join(cleaned)
    out, buf = [], []
    for ch in text:
        buf.append(ch)
        if ch == ";":
            s = "".join(buf).strip()
            if s and s != ";":
                out.append(s)
            buf = []
    return out


def apply_schema():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    if not SQL_PATH.exists():
        print(f"ERROR: schema_subscriptions.sql not found at {SQL_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()
    conn.close()

    print(f"[subscriptions] schema: applied={applied} skipped={skipped} failed={failed}")
    return 0 if failed == 0 else 1


def import_csv():
    """One-time import of seed rows from subscriptions_ledger.csv.
    Skips rows whose service_name already exists (so re-running is safe)."""
    if not CSV_PATH.exists():
        print(f"[subscriptions] no CSV at {CSV_PATH}, skipping import")
        return 0

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row

    existing = {r["service_name"] for r in conn.execute("SELECT service_name FROM subscriptions").fetchall()}
    inserted = skipped = 0

    with CSV_PATH.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row["service_name"] in existing:
                skipped += 1
                continue
            conn.execute("""
                INSERT INTO subscriptions
                  (service_name, provider, category, owner_email, billing_email,
                   plan_tier, seats, unit_cost_usd, billing_cycle,
                   start_date, renewal_date, status, mfa_method, admin_url, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                row["service_name"], row["provider"], row["category"],
                row["owner_email"], row["billing_email"], row["plan_tier"],
                int(row["seats"]) if row["seats"] else 1,
                float(row["unit_cost_usd"]) if row["unit_cost_usd"] else 0.0,
                row["billing_cycle"], row["start_date"], row["renewal_date"],
                row["status"], row["mfa_method"], row["admin_url"], row["notes"],
            ))
            inserted += 1
    conn.commit()

    # Report current burn by category
    print(f"[subscriptions] csv import: inserted={inserted} skipped={skipped}")
    print("[subscriptions] active monthly burn by category:")
    for r in conn.execute("SELECT * FROM subscriptions_monthly_burn").fetchall():
        print(f"  {r['category']:<15} {r['active_count']:>2} subs   ${r['monthly_usd']:>8.2f}/mo")
    conn.close()
    return 0


def main():
    rc = apply_schema()
    if rc != 0:
        return rc
    return import_csv()


if __name__ == "__main__":
    sys.exit(main())
