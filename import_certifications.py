#!/usr/bin/env python3
"""Bulk import worker certifications from certifications_import_template.csv.

DRY-RUN by default; pass --execute to actually INSERT. Pre-flight validates
every row before any DB writes — any failure aborts before a single INSERT
runs. Re-runnable: rows already in the table (matched by the 4-tuple of
employee_id + cert_type_id + card_number + date_obtained) are reported as
already imported and skipped.

  python import_certifications.py             # dry-run (default)
  python import_certifications.py --execute   # actually insert
"""

import argparse
import csv
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
CSV_PATH = SCRIPT_DIR / "certifications_import_template.csv"


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
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def initial(name):
    return (name[:1] + ".") if name else "—"


def redact_card_number(n):
    if not n:
        return "—"
    s = str(n)
    return ("XXX-" + s[-4:]) if len(s) >= 4 else ("XXX-" + s)


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
    # Blank employee_id rows are template scaffolding (or trailing blanks) — skip silently.
    rows = [r for r in raw_rows if (r.get("employee_id") or "").strip()]

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    print(f"[{mode}] Certifications import from {csv_path.name} — "
          f"{len(rows)} populated row(s) (of {len(raw_rows)} in file)")
    print()

    if not rows:
        print("Nothing to import. Fill the template and re-run.")
        return 0

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    valid_emp_ids = {
        r["employee_id"] for r in conn.execute("SELECT employee_id FROM employees")
    }
    valid_cert_types = {
        r["cert_type_id"] for r in conn.execute("SELECT cert_type_id FROM cert_types")
    }
    worker_initials = {
        r["employee_id"]: initial(r["name"])
        for r in conn.execute("SELECT employee_id, name FROM employees")
    }

    errors = []
    parsed = []
    for i, row in enumerate(rows, start=2):  # row 2 = first data row (after header)
        emp_id = (row.get("employee_id") or "").strip()
        cert_type_id = (row.get("cert_type_id") or "").strip()
        card_number = (row.get("card_number") or "").strip() or None
        date_obtained_raw = (row.get("date_obtained") or "").strip()
        expiration_date_raw = (row.get("expiration_date") or "").strip()
        issuing_body = (row.get("issuing_body") or "").strip() or None
        notes = (row.get("notes") or "").strip() or None

        if not emp_id:
            errors.append(f"Row {i}: employee_id is required")
        elif emp_id not in valid_emp_ids:
            errors.append(
                f"Row {i}: employee_id={emp_id!r} not in employees table"
            )

        if not cert_type_id:
            errors.append(f"Row {i}: cert_type_id is required")
        elif cert_type_id not in valid_cert_types:
            errors.append(
                f"Row {i}: cert_type_id={cert_type_id!r} not in cert_types library"
            )

        dob = parse_iso_date(date_obtained_raw, "date_obtained", i, errors)
        exp = parse_iso_date(expiration_date_raw, "expiration_date", i, errors)
        if dob and exp and exp < dob:
            errors.append(
                f"Row {i}: expiration_date ({exp}) is before date_obtained ({dob})"
            )

        parsed.append({
            "row_idx": i,
            "employee_id": emp_id,
            "cert_type_id": cert_type_id,
            "card_number": card_number,
            "date_obtained": dob,
            "expiration_date": exp,
            "issuing_body": issuing_body,
            "notes": notes,
        })

    if errors:
        print("Validation errors:")
        for e in errors:
            print(f"  - {e}")
        print()
        print("Fix the CSV and re-run. No DB writes attempted.")
        conn.close()
        return 1

    existing_tuples = {
        (r["employee_id"], r["cert_type_id"], r["card_number"], r["date_obtained"])
        for r in conn.execute(
            "SELECT employee_id, cert_type_id, card_number, date_obtained FROM certifications"
        )
    }

    new_rows = []
    skipped = []
    for p in parsed:
        key = (p["employee_id"], p["cert_type_id"], p["card_number"], p["date_obtained"])
        if key in existing_tuples:
            skipped.append(p)
        else:
            new_rows.append(p)

    if skipped:
        print(f"Already imported (skipped): {len(skipped)}")
        for p in skipped:
            wi = worker_initials.get(p["employee_id"], "—")
            print(
                f"  - {p['employee_id']:<10}  [{wi:<3}]  "
                f"{p['cert_type_id']:<18}  {redact_card_number(p['card_number'])}  "
                f"(CSV row {p['row_idx']})"
            )
        print()

    if not new_rows:
        print("Nothing new to insert. Exiting.")
        conn.close()
        return 0

    verb = "Inserting" if args.execute else "Would insert"
    print(f"{verb} {len(new_rows)} new certification(s):")
    print()
    header = (f"  {'employee_id':<10}  {'W#':<5}  {'cert_type_id':<18}  "
              f"{'card_num':<12}  {'obtained':<11}  {'expires':<11}")
    print(header)
    print("  " + "-" * (len(header) - 2))
    for p in new_rows:
        wi = worker_initials.get(p["employee_id"], "—")
        print(
            f"  {p['employee_id']:<10}  [{wi:<3}]  {p['cert_type_id']:<18}  "
            f"{redact_card_number(p['card_number']):<12}  "
            f"{(p['date_obtained'] or '—'):<11}  {(p['expiration_date'] or '—'):<11}"
        )

    if not args.execute:
        print()
        print("Dry-run only. Re-run with --execute to insert.")
        conn.close()
        return 0

    print()
    print("Inserting...")
    inserted = 0
    try:
        for p in new_rows:
            conn.execute(
                """INSERT INTO certifications
                   (employee_id, cert_type_id, card_number, date_obtained,
                    expiration_date, issuing_body, notes, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'active')""",
                (
                    p["employee_id"], p["cert_type_id"], p["card_number"],
                    p["date_obtained"], p["expiration_date"], p["issuing_body"],
                    p["notes"],
                ),
            )
            inserted += 1
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"ERROR: SQL failure, transaction rolled back: {e}", file=sys.stderr)
        conn.close()
        return 1

    conn.close()
    print()
    print(f"Inserted: {inserted}")
    print(f"Skipped (already imported): {len(skipped)}")
    print()
    print("Certification rows visible above include card-number tails — keep "
          "this output local. Do not paste into chats.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
