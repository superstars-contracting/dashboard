"""#290 (Cloud M4) — verify the media tree on the Render service disk against
the workstation's #287-verified staging tree. Counts + sampled sha256, both
sides, PII-safe output (never prints a file name — worker_records folder names
embed worker names; only counts, byte totals, and OK/MISMATCH land in the
terminal).

Usage (from the dashboard dir; requires the service's SSH address from the
Render dashboard -> ssc-dashboard -> Connect -> SSH, and an SSH key already
added to the Render account):

  venv\\Scripts\\python.exe tests\\verify_media_remote_290.py ^
      <staging_root> <ssh_addr> [--remote-root /var/data] [--sample 40]

  e.g.  ... verify_media_remote_290.py C:\\Users\\SSC-Admin\\Superstars\\cloud_staging_root srv-abc123@ssh.virginia.render.com

Checks:
  1. remote file COUNT under each shipped tree == local staging count
  2. remote total BYTES per tree == local total bytes
  3. a random sample (default 40 files, spread across trees) hashes to the
     same sha256 on both sides
Exit 0 only if every check passes.
"""
from __future__ import annotations

import argparse
import hashlib
import random
import subprocess
import sys
from pathlib import Path

# The trees we ship to the cloud disk: media + renders categories of #287.
# Deliberately NOT logs (workstation server logs stay home) and NOT the db
# category (the cloud runs Postgres; parking a PII-bearing SQLite copy on the
# service disk would be pure liability).
SHIPPED_TREES = [
    "data_room/field_photos", "data_room/project_docs", "data_room/photos",
    "data_room/receipts", "data_room/walkthroughs", "data_room/estimate_docs",
    "data_room/material_slips", "worker_records", "employee_photos",
    "issuer_signatures",
    "data_room/reports", "data_room/credentials", "data_room/forms",
    "data_room/toolbox_talks", "data_room/signage", "cof_exports",
    "meetings", "drop_plans", "site_closures", "toolbox_talks",
    "meeting_workflow_run", "rfi_workflow_run",
]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def ssh_out(addr: str, cmd: str, stdin_text: str | None = None) -> str:
    p = subprocess.run(["ssh", "-o", "BatchMode=yes", addr, cmd],
                       input=stdin_text, capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        raise RuntimeError(f"ssh failed rc={p.returncode}: {(p.stderr or '')[:300]}")
    return p.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("staging_root")
    ap.add_argument("ssh_addr")
    ap.add_argument("--remote-root", default="/var/data")
    ap.add_argument("--sample", type=int, default=40)
    args = ap.parse_args()

    staging = Path(args.staging_root)
    if not staging.is_dir():
        print(f"staging root does not exist: {staging}")
        return 2

    failures = 0
    all_local: list[tuple[str, Path]] = []   # (posix_rel, local_path)

    print(f"=== media verify: staging tree vs {args.ssh_addr}:{args.remote_root} ===")
    for tree in SHIPPED_TREES:
        local_base = staging / Path(tree)
        files = [p for p in local_base.rglob("*") if p.is_file()] if local_base.exists() else []
        lc, lb = len(files), sum(p.stat().st_size for p in files)
        for p in files:
            all_local.append((tree + "/" + p.relative_to(local_base).as_posix(), p))
        # remote count + bytes for the same tree (0/0 when absent)
        out = ssh_out(args.ssh_addr,
                      f"if [ -d '{args.remote_root}/{tree}' ]; then "
                      f"find '{args.remote_root}/{tree}' -type f | wc -l; "
                      f"find '{args.remote_root}/{tree}' -type f -printf '%s\\n' "
                      f"| awk '{{s+=$1}} END {{print s+0}}'; "
                      f"else echo 0; echo 0; fi")
        parts = [x.strip() for x in out.strip().splitlines() if x.strip()]
        rc_, rb = (int(parts[0]), int(parts[1])) if len(parts) >= 2 else (-1, -1)
        ok = (rc_ == lc and rb == lb)
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {tree:32} local {lc:5} files/{lb:>11}b   "
              f"remote {rc_:5} files/{rb:>11}b")

    # sampled hash comparison
    if all_local:
        random.seed()                        # fresh sample every run
        sample = random.sample(all_local, min(args.sample, len(all_local)))
        listing = "\n".join(f"{args.remote_root}/{rel}" for rel, _ in sample)
        # tr strips the \r that Windows text-mode subprocess writes inject into
        # the \n-joined listing (CRLF -> the remote saw "path\r" and failed).
        out = ssh_out(args.ssh_addr, "tr -d '\\r' | xargs -d '\\n' sha256sum --",
                      stdin_text=listing + "\n")
        remote_hashes = {}
        for line in out.strip().splitlines():
            h, _, path = line.partition("  ")
            remote_hashes[path.strip()] = h.strip()
        bad = 0
        for rel, lp in sample:
            rh = remote_hashes.get(f"{args.remote_root}/{rel}")
            if rh is None or rh != sha256(lp):
                bad += 1
        ok = bad == 0
        failures += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} sampled sha256: {len(sample) - bad}/{len(sample)} match")
    else:
        print("  FAIL no local files found under the staging trees")
        failures += 1

    print(f"=== media verify: {'ALL GREEN' if failures == 0 else f'{failures} FAILURE(S)'} ===")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
