#!/usr/bin/env python3
"""Bulk import workers from workers_import_template.csv into employees.

DRY-RUN by default; pass --execute to actually INSERT. Pre-flight validates
every row before any DB writes — any failure aborts before a single INSERT
runs. PIN collisions across the incoming batch or against existing rows
abort the entire import (operator resolves manually). Re-runnable: rows
already in the table (matched by name + normalized phone) are reported as
already imported and skipped.

  python import_workers.py             # dry-run (default)
  python import_workers.py --execute   # actually insert
"""

import argparse
import csv
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
CSV_PATH = SCRIPT_DIR / "workers_import_template.csv"
WORKER_RECORDS_DIR = SCRIPT_DIR / "worker_records"


def slugify_name(name):
    """Mirror of server.py:1008 slugify_name. Reimplemented here so this
    script does not pull in Flask app setup. Keep in sync with the canonical
    implementation."""
    if not name:
        return "unknown"
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^A-Za-z0-9 _-]", "", normalized)
    return re.sub(r"\s+", "_", cleaned).strip("_") or "unknown"


def normalize_phone(raw):
    return re.sub(r"\D", "", raw or "")


def parse_iso_date(s, field, row_idx, errors):
    if not s:
        return None
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return s
    except ValueError:
        errors.append(f"Row {row_idx}: {field}={s!r} is not a valid ISO YYYY-MM-DD date")
        return None


def read_csv_rows(path):
    # utf-8-sig handles a BOM if Excel saved the file with one.
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--execute", action="store_true",
                        help="Actually INSERT. Default is dry-run.")
    parser.add_argument("--csv", default=str(CSV_PATH),
                        help=f"Path to the CSV (default: {CSV_PATH.name})")
    args = parser.parse_args()

    csv_path = Path(args.csv).resolve()
    if not csv_path.exists():
        print(f"ERROR: {csv_path} not found", file=sys.stderr)
        return 1
    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        return 1

    raw_rows = read_csv_rows(csv_path)
    # Rows with no name are template scaffolding (or trailing blanks) — skip silently.
    rows = [r for r in raw_rows if (r.get("name") or "").strip()]

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"[{mode}] Workers import from {csv_path.name} — "
          f"{len(rows)} populated row(s) (of {len(raw_rows)} in file)")
    print()

    if not rows:
        print("Nothing to import. Fill the template and re-run.")
        return 0

    errors = []
    parsed = []
    # row index starts at 2 because row 1 is the CSV header
    for i, row in enumerate(rows, start=2):
        name = (row.get("name") or "").strip()
        phone_raw = (row.get("phone") or "").strip()
        trade = (row.get("trade") or "").strip() or None
        dob_raw = (row.get("dob") or "").strip()
        email = (row.get("email") or "").strip() or None
        ec_name = (row.get("emergency_contact_name") or "").strip() or None
        ec_phone_raw = (row.get("emergency_contact_phone") or "").strip()
        ec_relation = (row.get("emergency_contact_relation") or "").strip() or None
        language = (row.get("language") or "").strip() or "EN"
        hire_date_raw = (row.get("hire_date") or "").strip()

        if not phone_raw:
            errors.append(f"Row {i}: phone is required")
        phone_digits = normalize_phone(phone_raw)
        if phone_raw and len(phone_digits) < 4:
            errors.append(
                f"Row {i}: phone {phone_raw!r} has fewer than 4 digits — can't derive PIN"
            )
        pin = phone_digits[-4:] if len(phone_digits) >= 4 else None

        ec_phone_digits = normalize_phone(ec_phone_raw) if ec_phone_raw else None

        dob = parse_iso_date(dob_raw, "dob", i, errors)
        hire_date = parse_iso_date(hire_date_raw, "hire_date", i, errors)

        if language not in ("EN", "ES"):
            errors.append(
                f"Row {i}: language={language!r} must be 'EN' or 'ES' (case-sensitive)"
            )

        parsed.append({
            "row_idx": i,
            "name": name,
            "trade": trade,
            "dob": dob,
            "phone": phone_digits or None,
            "email": email,
            "emergency_contact_name": ec_name,
            "emergency_contact_phone": ec_phone_digits,
            "emergency_contact_relation": ec_relation,
            "language": language,
            "hire_date": hire_date,
            "pin": pin,
        })

    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  - {e}")
        print()
        print("Fix the CSV and re-run. No DB writes attempted.")
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    existing = conn.execute(
        "SELECT employee_id, name, phone, pin FROM employees"
    ).fetchall()
    existing_by_name_phone = {
        (e["name"], e["phone"]): e["employee_id"] for e in existing
    }
    existing_pins = [
        (e["pin"], e["employee_id"], e["name"]) for e in existing if e["pin"]
    ]

    new_rows = []
    skipped = []
    for p in parsed:
        key = (p["name"], p["phone"])
        if key in existing_by_name_phone:
            skipped.append((existing_by_name_phone[key], p["name"], p["row_idx"]))
        else:
            new_rows.append(p)

    pin_owners = {}
    for p in new_rows:
        pin_owners.setdefault(p["pin"], []).append(f"row {p['row_idx']}: {p['name']}")
    for pin, eid, ename in existing_pins:
        if pin in pin_owners:
            pin_owners[pin].insert(0, f"existing {eid}: {ename}")

    collisions = {pin: owners for pin, owners in pin_owners.items() if len(owners) > 1}
    if collisions:
        print("PIN collisions detected — import aborted:")
        for pin, owners in collisions.items():
            print(f"  PIN {pin}:")
            for owner in owners:
                print(f"    - {owner}")
        print()
        print("Resolve by using a different phone or assigning a manual PIN later, "
              "then re-run.")
        conn.close()
        return 1

    max_row = conn.execute(
        "SELECT MAX(CAST(SUBSTR(employee_id, 3) AS INTEGER)) AS max_n "
        "FROM employees WHERE employee_id LIKE 'E-%'"
    ).fetchone()
    max_n = max_row["max_n"] if max_row and max_row["max_n"] is not None else 0
    # Pre-allocate human-facing Worker IDs (W-####). Numbers are never
    # reused; new onboards get max+1 across the whole table. The unique
    # index on worker_id catches any race so this is safe even under
    # concurrent imports.
    from worker_id import next_worker_id_sequence, format_worker_id
    next_wid_seq = next_worker_id_sequence(conn)
    for offset, p in enumerate(new_rows, start=1):
        p["employee_id"] = f"E-{max_n + offset:05d}"
        p["worker_id"] = format_worker_id(next_wid_seq + offset - 1)
        p["folder_slug"] = slugify_name(p["name"])
        p["folder_path"] = str(WORKER_RECORDS_DIR / f"{p['employee_id']}_{p['folder_slug']}")

    if skipped:
        print(f"Already imported (skipped): {len(skipped)}")
        for eid, name, row_idx in skipped:
            print(f"  - {eid:<10} {name}  (CSV row {row_idx})")
        print()

    if not new_rows:
        print("Nothing new to insert. Exiting.")
        conn.close()
        return 0

    verb = "Inserting" if args.execute else "Would insert"
    print(f"{verb} {len(new_rows)} new worker(s):")
    print()
    header = f"  {'employee_id':<10}  {'name':<24}  {'trade':<22}  {'PIN':<6}  {'folder_path':<42}  {'hire_date':<11}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for p in new_rows:
        folder_display = f"worker_records/{p['employee_id']}_{p['folder_slug']}"
        trade_display = (p["trade"] or "-")[:22]
        print(
            f"  {p['employee_id']:<10}  {p['name'][:24]:<24}  {trade_display:<22}  "
            f"{p['pin']:<6}  {folder_display[:42]:<42}  {p['hire_date'] or '-':<11}"
        )

    if not args.execute:
        print()
        print("Dry-run only. Re-run with --execute to insert.")
        conn.close()
        return 0

    print()
    print("Inserting...")
    try:
        for p in new_rows:
            conn.execute(
                """INSERT INTO employees
                   (employee_id, worker_id, name, trade, dob, phone, email,
                    emergency_contact_name, emergency_contact_phone,
                    emergency_contact_relation, language, hire_date, pin,
                    folder_path, intake_status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    p["employee_id"], p["worker_id"], p["name"], p["trade"], p["dob"], p["phone"],
                    p["email"], p["emergency_contact_name"], p["emergency_contact_phone"],
                    p["emergency_contact_relation"], p["language"], p["hire_date"],
                    p["pin"], p["folder_path"], "pending",
                ),
            )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"ERROR: SQL failure, transaction rolled back: {e}", file=sys.stderr)
        conn.close()
        return 1

    folder_failures = []
    for p in new_rows:
        try:
            (Path(p["folder_path"]) / "id").mkdir(parents=True, exist_ok=True)
        except OSError as e:
            folder_failures.append(f"{p['folder_path']}: {e}")

    if folder_failures:
        print()
        print("WARNING: some folder creations failed (DB row exists; the intake UI "
              "will auto-create the folder on first access):")
        for f in folder_failures:
            print(f"  - {f}")

    conn.close()
    print()
    print(f"Inserted {len(new_rows)} worker(s). PIN values are visible above — "
          f"keep this output local. Do not paste into chats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
