#!/usr/bin/env python3
"""Renumber a project's DCR sequences in date-ascending order.

Earliest report_date → -001, next → -002, etc. Renames the rendered
HTML/PDF files + on-disk sequence directories
(data_room/reports/dcr/<project>/<NNN>/) and updates the report_id
strings in report_index ("DCR-PROJ-NNN-{audience}") to match.

Why this script: the legacy gap-fill allocator (smallest-unused
sequence) assigned a backdated 5-04 entry seq 5, even though the
chronology runs 5-04 → 5-18 → 5-19 → 5-20 → 5-21. After this runs,
seq follows date order; the live allocator change (server.py
next_dcr_sequence_date_ordered + issue_dcr renumber-on-backdate) keeps
it that way going forward.

Safe two-step swap: every old sequence first goes to its negative
twin (sequence * -1), then to its new positive sequence. That avoids
the (project_code, sequence) collision a one-pass update would hit
when an old seq still occupied the slot a different row needs to
take. On-disk dir renames happen the same way: <project>/NNN ->
<project>/.tmp_NNN -> <project>/MMM.

Usage:
  python renumber_dcrs_by_date.py [--project FR-BX-001] [--dry-run]
"""
from __future__ import annotations
import argparse
import re
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

# Matches the TRAILING sequence segment of a report_id:
# "DCR-FR-BX-001-005-internal" → captures the "005" before the audience.
# Anchored to ${audience}$ so an inner project-code "-NNN-" can't match
# (the bug the first run hit: project_code FR-BX-001 contains "-001-",
# which collided with old_seq=1 when we did a naive .replace).
_SEQ_TAIL_RE = re.compile(r"-(\d{3})-(internal|client)$")

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
REPORTS_ROOT = SCRIPT_DIR / "data_room" / "reports" / "dcr"


def main(project_code: str, dry_run: bool) -> int:
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # ---- Build the date → old_seq map for this project's DCRs --------
    pairs = conn.execute(
        "SELECT report_date, dcr_sequence FROM report_index "
        "WHERE project_code = ? AND report_type = 'DCR' "
        "AND dcr_sequence IS NOT NULL "
        "GROUP BY report_date, dcr_sequence "
        "ORDER BY report_date",
        (project_code,),
    ).fetchall()
    if not pairs:
        print(f"[renumber] no DCRs for project {project_code!r} — nothing to do")
        conn.close()
        return 0

    # Multiple rows per date (one per audience) all share one sequence —
    # the GROUP BY collapses that already. Flag a dup-date / multi-seq
    # collision before we touch anything.
    by_date: dict[str, set[int]] = defaultdict(set)
    for r in pairs:
        by_date[r["report_date"]].add(int(r["dcr_sequence"]))
    duplicates = {d: seqs for d, seqs in by_date.items() if len(seqs) > 1}
    if duplicates:
        print("[renumber] STOP: dates with multiple distinct sequences:")
        for d, seqs in duplicates.items():
            print(f"  {d}: {sorted(seqs)}")
        print("[renumber] resolve those manually first.")
        conn.close()
        return 1

    # Sorted (date, old_seq) — also the new_seq order
    date_old = sorted(((d, list(s)[0]) for d, s in by_date.items()))
    moves = []  # (date, old_seq, new_seq)
    for new_seq, (d, old_seq) in enumerate(date_old, start=1):
        moves.append((d, old_seq, new_seq))

    # ---- Before/after preview ---------------------------------------
    print("[renumber] proposed renumber (project " + project_code + "):")
    print(f"  {'date':>12} {'old':>5} {'new':>5}")
    changed = []
    for d, o, n in moves:
        marker = "  *" if o != n else ""
        print(f"  {d:>12} {o:>5} {n:>5}{marker}")
        if o != n:
            changed.append((d, o, n))
    print(f"[renumber] rows to renumber: {len(changed)} (out of {len(moves)})")
    if not changed:
        print("[renumber] already in date order — no-op.")
        conn.close()
        return 0
    if dry_run:
        print("[renumber] --dry-run: stopping without writing.")
        conn.close()
        return 0

    # ---- DB renumber via two-step negative-temp swap -----------------
    # Step A: bump every changing row's sequence to its NEGATIVE twin.
    # Step B: write the new positive sequence + the new report_id.
    # This avoids (project_code, sequence) collisions a one-pass UPDATE
    # would hit when two rows swap sequences.
    seq_to_old_rows = defaultdict(list)
    for r in conn.execute(
        "SELECT id, dcr_sequence, report_id FROM report_index "
        "WHERE project_code = ? AND report_type = 'DCR' "
        "AND dcr_sequence IS NOT NULL",
        (project_code,),
    ).fetchall():
        seq_to_old_rows[int(r["dcr_sequence"])].append(dict(r))

    moves_by_old = {o: (d, n) for d, o, n in moves}

    # Step A — to negative
    for old_seq in moves_by_old:
        for row in seq_to_old_rows[old_seq]:
            conn.execute(
                "UPDATE report_index SET dcr_sequence = ? WHERE id = ?",
                (-old_seq, row["id"]),
            )

    # Step B — to new positive + new report_id string.
    # Use the trailing-sequence regex so an inner project-code "-NNN-"
    # (like "FR-BX-001") can't be mistaken for the sequence segment.
    for old_seq, (d, new_seq) in moves_by_old.items():
        for row in seq_to_old_rows[old_seq]:
            old_rid = row["report_id"] or ""
            m = _SEQ_TAIL_RE.search(old_rid)
            if m:
                audience = m.group(2)
                new_rid = _SEQ_TAIL_RE.sub(f"-{new_seq:03d}-{audience}", old_rid)
            else:
                # Defensive — convention drifted; recompute from scratch.
                audience = "internal" if old_rid.endswith("internal") else (
                    "client" if old_rid.endswith("client") else "internal"
                )
                new_rid = f"DCR-{project_code}-{new_seq:03d}-{audience}"
            conn.execute(
                "UPDATE report_index SET dcr_sequence = ?, report_id = ?, "
                "       updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_seq, new_rid, row["id"]),
            )

    # ---- On-disk dir renames — same two-step (NNN → .tmp_NNN → MMM) ---
    # Hardening: stale .tmp_NNN from a prior aborted run blocks step A
    # on Windows (rename is non-overwriting → WinError 183). Pre-clean
    # by quarantining any pre-existing temp / collision target to
    # .orphan_*_<ts> so the rename can complete without data loss.
    import time as _time
    project_root = REPORTS_ROOT / project_code
    if not project_root.exists():
        print(f"[renumber] WARN: report dir {project_root} doesn't exist; DB-only renumber.")
    else:
        # A: rename each old NNN to a temp sentinel.
        for d, old, new in changed:
            src = project_root / f"{old:03d}"
            tmp = project_root / f".tmp_{old:03d}"
            if tmp.exists():
                quarantine = project_root / f".orphan_{old:03d}_{int(_time.time())}"
                print(f"[renumber] WARN: pre-existing {tmp.name} quarantined to {quarantine.name}")
                tmp.rename(quarantine)
            if src.exists():
                src.rename(tmp)
        # B: rename each temp to the new NNN.
        for d, old, new in changed:
            tmp = project_root / f".tmp_{old:03d}"
            dst = project_root / f"{new:03d}"
            if tmp.exists():
                if dst.exists():
                    quarantine = project_root / f".orphan_dst_{new:03d}_{int(_time.time())}"
                    print(f"[renumber] WARN: target {dst.name} exists; quarantining to {quarantine.name}")
                    dst.rename(quarantine)
                tmp.rename(dst)

    conn.commit()

    # ---- Verification block -----------------------------------------
    print()
    print("[renumber] verification — post-renumber state:")
    print(f"  {'date':>12} {'seq':>4} {'report_id':<40}")
    for r in conn.execute(
        "SELECT report_date, dcr_sequence, report_id "
        "FROM report_index WHERE project_code = ? AND report_type = 'DCR' "
        "ORDER BY report_date, report_id",
        (project_code,),
    ).fetchall():
        print(f"  {r['report_date']:>12} {r['dcr_sequence']:>4} {r['report_id']:<40}")
    print()
    if project_root.exists():
        print(f"[renumber] on-disk dirs in {project_root.name}/:")
        for p in sorted(project_root.iterdir()):
            print(f"  {p.name}")
    conn.close()
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project", default="FR-BX-001",
                    help="project_code to renumber (default FR-BX-001)")
    ap.add_argument("--dry-run", action="store_true",
                    help="show the proposed renumber without writing")
    args = ap.parse_args()
    sys.exit(main(args.project, args.dry_run))
