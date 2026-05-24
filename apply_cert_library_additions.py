#!/usr/bin/env python3
"""Additive cert-library entries on top of the DOB+SST baseline.

DOES NOT rebuild the catalog. Inserts only the new rows operator added
via HANDOFF_CERT_LIBRARY_ADDITIONS.md, all using INSERT OR IGNORE so
re-runs are safe.

New entries:
  - Rope Access (non-DOB, SPRAT + IRATA Levels 1/2/3) — 6 rows.
    Core business line — SPRAT/IRATA are industry rope-access bodies,
    not NYC DOB. No DOB reference URL; not CoF prerequisites.
  - SST Cards (NYC DOB SST card credentials) — 2 rows. The two NYC
    SST card tiers (40-hr Worker, 62-hr Supervisor). No single-PDF
    reference URL — the SST cards aren't a single course.

After this script: catalog goes 67 -> 75. CoF prereqs remain exactly
RIGGER-32 + SCAFFOLD-16. validity_months stays NULL (expiry captured
per-worker per CLAUDE.md).
"""
import sqlite3
import sys
from pathlib import Path
from collections import Counter

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"

# (cert_type_id, name, category, reference_url, is_cof_prerequisite)
NEW_ENTRIES = [
    # ---- Rope Access (non-DOB) -----------------------------------------
    ("ROPE-SPRAT-1", "SPRAT Level 1 — Rope Access Technician",        "Rope Access", None, 0),
    ("ROPE-SPRAT-2", "SPRAT Level 2 — Rope Access Lead Technician",   "Rope Access", None, 0),
    ("ROPE-SPRAT-3", "SPRAT Level 3 — Rope Access Supervisor",        "Rope Access", None, 0),
    ("ROPE-IRATA-1", "IRATA Level 1 — Rope Access Technician",        "Rope Access", None, 0),
    ("ROPE-IRATA-2", "IRATA Level 2 — Rope Access Technician",        "Rope Access", None, 0),
    ("ROPE-IRATA-3", "IRATA Level 3 — Rope Access Supervisor",        "Rope Access", None, 0),

    # ---- SST Cards (NYC DOB SST credentials, not single-PDF courses) ----
    ("SST-WORKER",   "SST Worker Card (40-Hour)",                     "SST Cards",   None, 0),
    ("SST-SUP-62",   "SST Supervisor Card (62-Hour)",                 "SST Cards",   None, 0),
]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    inserted = ignored = 0
    for code, name, category, ref_url, is_prereq in NEW_ENTRIES:
        cur = conn.execute(
            "INSERT OR IGNORE INTO cert_types "
            "  (cert_type_id, name, category, reference_url, is_cof_prerequisite, validity_months) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (code, name, category, ref_url, is_prereq),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            ignored += 1
    conn.commit()

    # ---- Report ------------------------------------------------------
    total = conn.execute("SELECT COUNT(*) FROM cert_types").fetchone()[0]
    by_category = conn.execute(
        "SELECT category, COUNT(*) FROM cert_types GROUP BY category ORDER BY category"
    ).fetchall()
    prereqs = conn.execute(
        "SELECT cert_type_id FROM cert_types WHERE is_cof_prerequisite=1 ORDER BY cert_type_id"
    ).fetchall()
    conn.close()

    print(f"[cert-lib] new rows: inserted={inserted} (ignored={ignored})")
    print(f"[cert-lib] catalog total: {total}")
    print(f"[cert-lib] per category:")
    for cat, n in by_category:
        print(f"             • {cat}: {n}")
    print(f"[cert-lib] CoF prereqs ({len(prereqs)}): {', '.join(r[0] for r in prereqs)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
