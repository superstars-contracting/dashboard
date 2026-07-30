#!/usr/bin/env python3
"""#287 (Cloud M1) — copy the data tree into a target SSC_DATA_ROOT, verified.

Usage (from the dashboard dir):
    python migrate_data_root_287.py <target_root>            # DRY RUN (default)
    python migrate_data_root_287.py <target_root> --execute  # copy + verify
    python migrate_data_root_287.py <target_root> --verify   # verify only

What it does, per DATA category (media / renders / logs / db):
  * walks the CURRENT tree (the repo dir, or SSC_DATA_ROOT if already set) and
    the same categories under <target_root>;
  * DRY RUN prints per-category file counts + total bytes and what WOULD copy;
  * EXECUTE copies missing files, then re-hashes BOTH sides (sha256) and prints
    per-category "n/n OK". A file that exists on both sides with a matching
    hash is skipped (IDEMPOTENT: a re-run is a verify, not a duplicate; a
    mismatch is reported and NOT overwritten — resolve by hand);
  * never deletes, never writes outside <target_root>, never touches the DB
    file in place (the SQLite file is copied cold like any other file — stop
    the server first for a consistent copy, or accept the WAL-checkpoint copy).

PII-safe output: counts, byte totals and category names only — NEVER file
names (worker_records folder names embed worker names).
"""
from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
import ssc_paths  # noqa: E402

# category -> top-level trees (relative to the source root)
CATEGORIES = {
    "media": ["data_room/field_photos", "data_room/project_docs", "data_room/photos",
              "data_room/receipts", "data_room/walkthroughs", "data_room/estimate_docs",
              "data_room/material_slips", "worker_records", "employee_photos",
              "issuer_signatures"],
    "renders": ["data_room/reports", "data_room/credentials", "data_room/forms",
                "data_room/toolbox_talks", "data_room/signage", "cof_exports",
                "meetings", "drop_plans", "site_closures", "toolbox_talks",
                "meeting_workflow_run", "rfi_workflow_run"],
    "logs": ["data_room/server_logs", "server.log"],
    "db": ["superstars.db"],
}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def walk_files(base: Path, rel: str):
    root = base / rel
    if not root.exists():
        return []
    if root.is_file():
        return [Path(rel)]
    return [p.relative_to(base) for p in sorted(root.rglob("*")) if p.is_file()]


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__)
        return 2
    target = Path(args[0]).resolve()
    execute = "--execute" in sys.argv
    verify_only = "--verify" in sys.argv
    source = ssc_paths.data_root().resolve()
    if target == source:
        print("REFUSING: target equals the current data root")
        return 2
    mode = "EXECUTE" if execute else ("VERIFY" if verify_only else "DRY RUN")
    print(f"[{mode}] source={source}")
    print(f"[{mode}] target={target}")

    grand_ok = True
    for cat, trees in CATEGORIES.items():
        n_src = n_have = n_copy = n_mismatch = bytes_src = 0
        to_copy: list[Path] = []
        for tree in trees:
            for rel in walk_files(source, tree):
                n_src += 1
                bytes_src += (source / rel).stat().st_size
                dst = target / rel
                if dst.exists():
                    if verify_only or execute:
                        if sha256(source / rel) == sha256(dst):
                            n_have += 1
                        else:
                            n_mismatch += 1
                    else:
                        n_have += 1
                else:
                    to_copy.append(rel)
        if execute:
            for rel in to_copy:
                dst = target / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source / rel, dst)
                if sha256(source / rel) == sha256(dst):
                    n_copy += 1
                else:
                    n_mismatch += 1
        else:
            n_copy = len(to_copy)
        verified = n_have + (n_copy if execute else 0)
        state = "OK" if (n_mismatch == 0 and (not execute or verified == n_src)) else "ATTENTION"
        if n_mismatch:
            grand_ok = False
        verb = "copied" if execute else "would copy"
        print(f"  {cat:8s} {n_src:6d} files {bytes_src/1e6:9.1f} MB | "
              f"already-verified {n_have:6d} | {verb} {n_copy:6d} | "
              f"mismatch {n_mismatch:3d} | {state}")
    print(f"[{mode}] {'ALL CATEGORIES OK' if grand_ok else 'MISMATCHES FOUND — nothing overwritten'}")
    return 0 if grand_ok else 1


if __name__ == "__main__":
    sys.exit(main())
