#!/usr/bin/env python3
"""
Company ID — issuance backend.

Sibling to cof_issuer.py. Issues the fallback credential for workers
who lack the CoF prerequisites (no SCAFFOLD-16 and no RIGGER-32).

Differences from CoF:
  - No eligibility gate inside the module — eligibility is the caller's
    decision (the route picks CoF vs Company ID based on cert_types).
  - No cert-derived expiry. Perpetual lifecycle managed by status flag:
    'active' | 'inactive' | 'replaced'. HR flips to 'inactive' on
    termination; issuance flips prior 'active' to 'replaced' before
    inserting the new active row.
  - No rigger / signature snapshot — the card just identifies employment.

Usage:
  python company_id_issuer.py status <emp_id>          # current state
  python company_id_issuer.py issue <emp_id> [--by NAME]   # issue / reissue
"""
import sys
import shutil
import sqlite3
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
CREDENTIALS_DIR = SCRIPT_DIR / "data_room" / "credentials" / "company_id"


# =====================================================================
# DB helpers
# =====================================================================

def db_conn():
    # #260 — route through the env-driven layer (SSC_DB_URL). Production default is
    # the live SQLite file (unchanged); honors test isolation when SSC_DB_URL is set.
    import db_layer
    return db_layer.connect()


# =====================================================================
# Card numbering
# =====================================================================

def card_number_for_employee(employee_id):
    """Stable display number — same across reissues. Format:
    SSC-CID-{worker_id}, e.g. SSC-CID-W-0001. Resolves worker_id from
    the DB; falls back to SSC-CID-{employee_id} with a logged warning if
    no worker_id is on file. The card_id (internal PK) keeps the
    employee_id + revision suffix for FK stability."""
    if not employee_id:
        raise RuntimeError("employee_id required to generate card number")
    conn = db_conn()
    try:
        row = conn.execute(
            "SELECT worker_id FROM employees WHERE employee_id = ?",
            (employee_id,)
        ).fetchone()
    finally:
        conn.close()
    if row and row["worker_id"]:
        return f"SSC-CID-{row['worker_id']}"
    print(
        f"[company_id_issuer] WARN: employee {employee_id} has no worker_id on file; "
        f"falling back to legacy E- card number format",
        file=sys.stderr,
    )
    return f"SSC-CID-{employee_id}"


def _next_revision(conn, employee_id):
    """Next revision number for this employee. Counts existing rows since
    every issuance creates one row (active + history of replaced rows).
    Returns 1 if no prior cards."""
    n = conn.execute(
        "SELECT COUNT(*) FROM company_id_cards WHERE employee_id = ?",
        (employee_id,)
    ).fetchone()[0]
    return n + 1


# =====================================================================
# Status
# =====================================================================

def get_active_card(conn, employee_id):
    """Most recent 'active' card row for this employee, or None."""
    row = conn.execute(
        """SELECT * FROM company_id_cards
           WHERE employee_id = ? AND status = 'active'
           ORDER BY issued_date DESC, created_at DESC LIMIT 1""",
        (employee_id,)
    ).fetchone()
    return dict(row) if row else None


def company_id_status_for_employee(employee_id):
    """Returns {employee_id, has_active_card, active_card, outcome}.
    outcome ∈ {'active', 'needs_new', 'needs_reissue'}.
      active        — current card in good standing
      needs_new     — no card ever issued
      needs_reissue — prior card replaced/inactive, nothing currently active
    """
    conn = db_conn()
    active = get_active_card(conn, employee_id)
    any_history = conn.execute(
        "SELECT 1 FROM company_id_cards WHERE employee_id = ? LIMIT 1",
        (employee_id,)
    ).fetchone()
    conn.close()
    if active:
        outcome = "active"
    elif any_history:
        outcome = "needs_reissue"
    else:
        outcome = "needs_new"
    return {
        "employee_id": employee_id,
        "has_active_card": active is not None,
        "active_card": active,
        "outcome": outcome,
    }


# =====================================================================
# Photo snapshot
# =====================================================================

def _snapshot_photo(employee_id, revision, source_path):
    """Copy the worker's face_image_path to
    data_room/credentials/company_id/<emp_id>_v<rev>.<ext>. Returns the
    repo-relative POSIX path (suitable for storing in DB / serving via
    /files), or None if no source file available."""
    if not source_path:
        return None
    src = Path(source_path)
    if not src.is_absolute():
        src = SCRIPT_DIR / src
    if not src.exists():
        return None
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower() or ".jpg"
    dest = CREDENTIALS_DIR / f"{employee_id}_v{revision}{ext}"
    try:
        shutil.copy2(str(src), str(dest))
    except Exception as e:
        print(f"[company_id_issuer] photo snapshot failed: {e}", file=sys.stderr)
        return None
    return dest.relative_to(SCRIPT_DIR).as_posix()


# =====================================================================
# Issuance
# =====================================================================

def issue_company_id(employee_id, issued_by, today_override=None):
    """Atomically issue (or re-issue) a Company ID card for one employee.

    1. Marks any existing 'active' row for this employee as 'replaced'.
    2. Computes the next revision number (= existing row count + 1).
    3. Snapshots the employee's face_image_path into the credentials
       directory if a source file exists; otherwise photo_snapshot_path
       stays NULL and the card prints with the placeholder photo box.
    4. INSERTs the new row with status='active'.

    Returns the new card row as a dict. Raises RuntimeError if the
    employee_id is unknown.
    """
    if not employee_id:
        raise RuntimeError("employee_id required")
    if not issued_by:
        raise RuntimeError("issued_by required (operator name)")

    if today_override is None:
        issued_date = date.today().isoformat()
    elif isinstance(today_override, str):
        issued_date = today_override
    else:
        issued_date = today_override.isoformat()

    conn = db_conn()
    emp = conn.execute(
        "SELECT face_image_path FROM employees WHERE employee_id = ?",
        (employee_id,)
    ).fetchone()
    if not emp:
        conn.close()
        # Don't echo the internal employee_id back — per CLAUDE.md the
        # operator only ever sees worker_id (W-####). Since this branch
        # means the employee_id didn't resolve, there's no W-#### to
        # report; just say so.
        raise RuntimeError("Worker not found.")
    face_path = emp["face_image_path"]

    revision = _next_revision(conn, employee_id)
    card_id = f"SSC-CID-{employee_id}-{revision}"
    card_number_display = card_number_for_employee(employee_id)
    photo_snapshot = _snapshot_photo(employee_id, revision, face_path)

    # Supersede any prior active card so there's only ever one active row per worker.
    conn.execute(
        "UPDATE company_id_cards SET status='replaced', updated_at=CURRENT_TIMESTAMP "
        "WHERE employee_id = ? AND status = 'active'",
        (employee_id,)
    )

    conn.execute(
        """INSERT INTO company_id_cards
           (card_id, employee_id, issued_date, issued_by, card_number_display,
            photo_snapshot_path, status)
           VALUES (?, ?, ?, ?, ?, ?, 'active')""",
        (card_id, employee_id, issued_date, issued_by, card_number_display, photo_snapshot)
    )
    conn.commit()

    row = conn.execute("SELECT * FROM company_id_cards WHERE card_id = ?", (card_id,)).fetchone()
    conn.close()
    return dict(row)


# =====================================================================
# CLI
# =====================================================================

def cli_status(employee_id):
    s = company_id_status_for_employee(employee_id)
    print(f"Employee:        {s['employee_id']}")
    print(f"Outcome:         {s['outcome']}")
    print(f"Has active card: {s['has_active_card']}")
    if s['active_card']:
        c = s['active_card']
        print(f"  card_id:        {c['card_id']}")
        print(f"  display:        {c['card_number_display']}")
        print(f"  issued:         {c['issued_date']} by {c['issued_by']}")
        print(f"  photo:          {c.get('photo_snapshot_path') or '(none)'}")
        print(f"  status:         {c['status']}")


def cli_issue(employee_id, issued_by):
    try:
        result = issue_company_id(employee_id, issued_by)
    except Exception as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"ISSUED card {result['card_id']}")
    print(f"  display:        {result['card_number_display']}")
    print(f"  issued:         {result['issued_date']} by {result['issued_by']}")
    print(f"  photo:          {result.get('photo_snapshot_path') or '(none)'}")
    print(f"  status:         {result['status']}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "status":
        cli_status(sys.argv[2])
    elif cmd == "issue":
        issued_by = "admin"
        for i, arg in enumerate(sys.argv):
            if arg == "--by" and i + 1 < len(sys.argv):
                issued_by = sys.argv[i + 1]
        cli_issue(sys.argv[2], issued_by)
    else:
        print(__doc__)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
