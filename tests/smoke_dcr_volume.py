#!/usr/bin/env python3
"""200-DCR volume smoke test.

Confidence check for the DCR ID allocation, entry-row save path, and atomic
delete + re-issue behavior under sustained load. Invoke manually; not wired
into the regular dashboard launch.

  python tests/smoke_dcr_volume.py

What it does:
  Phase 1: issues 200 sequential DCRs for FR-BX-001 starting 2024-01-01, each
           preceded by 2 work_log + 1 deliveries entry. Asserts:
             - HTTP 201
             - display_id == DCR-FR-BX-001-{i:03d}
             - sequence == i
             - both /<seq:03d>/internal.html and client.html exist on disk
             - per-iteration timing tracked
  Phase 2: deletes 30 random sequences via DELETE /by-sequence/<seq>, after
           each delete issues a new DCR for a fresh date and asserts that the
           new sequence == max+1 — a deleted number stays RETIRED, never
           reused (immutable-number policy from the repair pass).
  Phase 3: full cleanup — wipes all FR-BX-001 report_index rows, work_log,
           deliveries, and per-sequence HTML directories. Verifies post-state
           matches baseline (0 DCRs, 0 work_log, 0 deliveries).

Requires:
  - dashboard/superstars.db with FR-BX-001 project + at least one project_riggers row
  - dashboard/venv/Scripts/python.exe (Windows venv with Flask installed)
  - port 5050 free (script starts/stops its own server)
"""
import json
import random
import shutil
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

DASHBOARD_DIR = Path(__file__).resolve().parent.parent
DB = DASHBOARD_DIR / "superstars.db"
LOG = DASHBOARD_DIR / "tests" / "_smoke_dcr_volume_server.log"
VENV_PY = DASHBOARD_DIR / "venv" / "Scripts" / "python.exe"
sys.path.insert(0, str(DASHBOARD_DIR))
import db_layer  # noqa: E402  # #260 — route DB access through the env-driven layer (SSC_DB_URL)
PROJECT = "FR-BX-001"
N_DCRS = 200
N_DELETE_REISSUE = 30
SEED = 42  # deterministic delete-set so failures are reproducible
BASE_DATE = date(2024, 1, 1)

PASS, FAIL, TIMING = [], [], []


def expect(label, cond, extra=""):
    line = f"{'PASS' if cond else 'FAIL'}: {label}" + (f"  ({extra})" if extra else "")
    if cond:
        PASS.append(line)
    else:
        FAIL.append(line)
        print(line)


def hit(method, path, body=None, timeout=15):
    url = "http://127.0.0.1:5050" + path
    data = headers = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode("utf-8", errors="replace")
        except Exception:
            return e.code, ""
    except Exception as e:
        return None, repr(e)


def refuse_if_operator_data_present():
    """Abort if the project already has DCRs / sign-ins / work_log / deliveries
    — wipe_fr_bx_001() does an unconditional truncate on the project and would
    destroy them. The smoke is invoked manually and assumes a clean project
    state; if real operator data exists, the operator must run on a separate
    dev DB instead. (Same guard pattern as smoke_weekly_hours after #163.)
    """
    with db_layer.connect() as c:
        n_dcr = c.execute(
            "SELECT COUNT(*) FROM report_index WHERE project_code=? AND report_type='DCR'",
            (PROJECT,),
        ).fetchone()[0]
        n_si = c.execute(
            "SELECT COUNT(*) FROM sign_in_log WHERE project_code=?", (PROJECT,)
        ).fetchone()[0]
        n_wl = c.execute(
            "SELECT COUNT(*) FROM work_log WHERE project_code=?", (PROJECT,)
        ).fetchone()[0]
        n_dl = c.execute(
            "SELECT COUNT(*) FROM deliveries WHERE project_code=?", (PROJECT,)
        ).fetchone()[0]
    if n_dcr or n_si or n_wl or n_dl:
        print(
            f"REFUSE TO RUN: {PROJECT} already has operator data — "
            f"DCRs={n_dcr} sign-ins={n_si} work_log={n_wl} deliveries={n_dl}. "
            f"smoke_dcr_volume.wipe_fr_bx_001() does an unconditional truncate "
            f"on the project and would destroy them. Run on a dev DB instead.",
            file=sys.stderr,
        )
        sys.exit(3)


def wipe_fr_bx_001():
    """Hard reset of all FR-BX-001 test data (DB + filesystem).

    DANGEROUS — wipes every row for the project. Guard before any call:
    `refuse_if_operator_data_present()` must run first.
    """
    with db_layer.connect() as c:
        c.execute("DELETE FROM report_index WHERE project_code=?", (PROJECT,))
        c.execute("DELETE FROM work_log WHERE project_code=?", (PROJECT,))
        c.execute("DELETE FROM deliveries WHERE project_code=?", (PROJECT,))
        c.commit()
    out_root = DASHBOARD_DIR / "data_room" / "reports" / "dcr" / PROJECT
    if out_root.exists():
        for child in list(out_root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)


def main():
    print(f"=== smoke_dcr_volume.py — {N_DCRS} DCRs + {N_DELETE_REISSUE} delete/re-issue ===")
    print(f"  project: {PROJECT}")
    print(f"  base date: {BASE_DATE.isoformat()}")
    print()

    # Refuse-to-run guard: wipe_fr_bx_001 truncates the project. Operator
    # data must not be present (handoff #175 / post-mortem of #163).
    refuse_if_operator_data_present()
    # Pre-clean
    wipe_fr_bx_001()
    print("pre-clean done")

    # Start server
    LOG.parent.mkdir(parents=True, exist_ok=True)
    f = open(LOG, "w")
    proc = subprocess.Popen(
        [str(VENV_PY), "server.py"], cwd=str(DASHBOARD_DIR), stdout=f, stderr=subprocess.STDOUT
    )
    print(f"started server pid={proc.pid}")
    try:
        for i in range(20):
            time.sleep(1)
            # Probe an unauthenticated endpoint — the auth gate (#48) makes / redirect
            # to /login, so "/" no longer signals readiness on its own.
            s, _ = hit("GET", "/api/health")
            if s == 200:
                print(f"  server up after {i+1}s")
                break
            if proc.poll() is not None:
                print(f"  PROCESS DIED rc={proc.returncode}")
                sys.exit(2)
        else:
            print("  server did NOT come up")
            sys.exit(2)
        # Auth gate (#48): server is up — login the smoke admin + patch
        # urllib so urlopen calls carry the session cookie.
        import _smoke_auth
        _smoke_auth.setup()

        # ================================================================
        # Phase 1 — 200 sequential issuances
        # ================================================================
        print(f"\n=== Phase 1: issuing {N_DCRS} DCRs ===")
        phase1_start = time.time()
        for i in range(1, N_DCRS + 1):
            d = (BASE_DATE + timedelta(days=i - 1)).isoformat()
            iter_start = time.time()

            # 2 work_log + 1 delivery entry per iteration to exercise the save path
            for k in range(2):
                s, _ = hit("POST", "/api/work-log", body={
                    "project_code": PROJECT, "date": d,
                    "trade_area": f"area-{k}",
                    "location_elevation": f"L{(i % 12) + 1}",
                    "description": f"volume-smoke work {i}.{k}",
                })
                if s != 201:
                    FAIL.append(f"work_log POST failed at i={i} k={k} status={s}")
                    break
            s, _ = hit("POST", "/api/deliveries", body={
                "project_code": PROJECT, "date": d,
                "time": "09:30",
                "material": f"material-{i}",
                "qty": 1.0, "unit": "each",
                "supplier": "smoke-supplier",
            })
            if s != 201:
                FAIL.append(f"deliveries POST failed at i={i} status={s}")

            # Issue
            s, body = hit("POST", f"/api/projects/{PROJECT}/daily/{d}/issue",
                          body={"audience": "both"})
            iter_elapsed = time.time() - iter_start
            TIMING.append(iter_elapsed)
            try:
                j = json.loads(body)
                dat = j.get("data", {})
            except Exception:
                dat = {}

            if s != 201:
                FAIL.append(f"issue HTTP failed at i={i} status={s} body={body[:200]}")
                continue

            expected_display = f"DCR-{PROJECT}-{i:03d}"
            if dat.get("display_id") != expected_display:
                FAIL.append(f"i={i}: display_id={dat.get('display_id')!r} expected {expected_display!r}")
            if dat.get("sequence") != i:
                FAIL.append(f"i={i}: sequence={dat.get('sequence')!r} expected {i}")
            seq_dir = DASHBOARD_DIR / "data_room" / "reports" / "dcr" / PROJECT / f"{i:03d}"
            internal = seq_dir / "internal.html"
            client = seq_dir / "client.html"
            if not internal.exists() or internal.stat().st_size < 100:
                FAIL.append(f"i={i}: internal.html missing/empty")
            if not client.exists() or client.stat().st_size < 100:
                FAIL.append(f"i={i}: client.html missing/empty")

            if i % 25 == 0 or i == N_DCRS:
                avg = sum(TIMING[-25:]) / min(25, len(TIMING))
                print(f"  i={i:3d}/{N_DCRS}  last 25 avg: {avg*1000:.0f}ms  total elapsed: {time.time()-phase1_start:.1f}s")
        phase1_elapsed = time.time() - phase1_start
        print(f"  phase 1 complete: {N_DCRS} DCRs in {phase1_elapsed:.1f}s "
              f"(avg {phase1_elapsed/N_DCRS*1000:.0f}ms per issuance)")
        expect("phase 1: 200 DCRs issued without errors", not any("issue HTTP failed" in x for x in FAIL))

        # ================================================================
        # Phase 2 — delete + re-issue, verify gap-fill
        # ================================================================
        print(f"\n=== Phase 2: {N_DELETE_REISSUE} delete + re-issue cycles ===")
        rng = random.Random(SEED)
        used = set(range(1, N_DCRS + 1))
        # Pick the delete sequences up front (deterministic order from the seed)
        delete_seqs = rng.sample(range(1, N_DCRS + 1), N_DELETE_REISSUE)
        reissue_base_date = BASE_DATE + timedelta(days=N_DCRS)  # fresh dates start here

        for j, seq_to_delete in enumerate(delete_seqs):
            # DELETE the chosen sequence atomically
            s, body = hit("DELETE", f"/api/projects/{PROJECT}/reports/by-sequence/{seq_to_delete}")
            if s != 200:
                FAIL.append(f"phase2 j={j}: DELETE seq={seq_to_delete} status={s}")
                continue
            used.discard(seq_to_delete)

            # Numbers are immutable identity and a deleted number stays
            # RETIRED (repair-pass policy; same posture as Worker-IDs):
            # every new issue takes max+1, the gap stays a gap.
            expected_seq = (max(used) if used else 0) + 1

            # Issue for a fresh date
            d = (reissue_base_date + timedelta(days=j)).isoformat()
            # Add a single work_log to exercise the path
            hit("POST", "/api/work-log", body={
                "project_code": PROJECT, "date": d,
                "trade_area": "reissue", "description": f"phase2 #{j}",
            })
            s, body = hit("POST", f"/api/projects/{PROJECT}/daily/{d}/issue",
                          body={"audience": "both"})
            if s != 201:
                FAIL.append(f"phase2 j={j}: re-issue HTTP {s}")
                continue
            j_body = json.loads(body)
            new_seq = j_body.get("data", {}).get("sequence")
            if new_seq != expected_seq:
                FAIL.append(f"phase2 j={j}: expected max+1 seq={expected_seq}, got {new_seq} (deleted {seq_to_delete} stays retired)")
            else:
                PASS.append(f"phase2 j={j}: max+1 allocated seq={expected_seq}, gap {seq_to_delete} retired")
            used.add(new_seq if new_seq is not None else expected_seq)

            if (j + 1) % 10 == 0 or j + 1 == N_DELETE_REISSUE:
                print(f"  phase2 cycle {j+1}/{N_DELETE_REISSUE}  last: deleted seq {seq_to_delete}, new issue took {new_seq}")

        expect(f"phase 2: all {N_DELETE_REISSUE} delete+re-issue cycles produced expected sequences",
               not any("phase2" in x and "FAIL" in x for x in FAIL),
               extra=f"failures={[x for x in FAIL if 'phase2' in x][:5]}")

        # Final size check: should still have N_DCRS distinct sequences (each delete was followed by an issue)
        with db_layer.connect() as c:
            distinct_seqs = c.execute(
                "SELECT COUNT(DISTINCT dcr_sequence) FROM report_index WHERE project_code=?",
                (PROJECT,)).fetchone()[0]
            total_rows = c.execute(
                "SELECT COUNT(*) FROM report_index WHERE project_code=?",
                (PROJECT,)).fetchone()[0]
        expect(f"distinct sequences after phase 2 == {N_DCRS}",
               distinct_seqs == N_DCRS, f"got {distinct_seqs}")
        expect(f"total rows after phase 2 == {N_DCRS*2}  (both audiences)",
               total_rows == N_DCRS * 2, f"got {total_rows}")
    finally:
        # ================================================================
        # Phase 3 — full cleanup
        # ================================================================
        print(f"\n=== Phase 3: cleanup ===")
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=4)
        f.close()
        print(f"  server rc={proc.returncode}")
        wipe_fr_bx_001()
        with db_layer.connect() as c:
            n_rep = c.execute("SELECT COUNT(*) FROM report_index WHERE project_code=?", (PROJECT,)).fetchone()[0]
            n_work = c.execute("SELECT COUNT(*) FROM work_log WHERE project_code=?", (PROJECT,)).fetchone()[0]
            n_del = c.execute("SELECT COUNT(*) FROM deliveries WHERE project_code=?", (PROJECT,)).fetchone()[0]
        print(f"  post-cleanup: report_index={n_rep}, work_log={n_work}, deliveries={n_del}")
        out_root = DASHBOARD_DIR / "data_room" / "reports" / "dcr" / PROJECT
        leftover_dirs = []
        if out_root.exists():
            leftover_dirs = [d.name for d in out_root.iterdir() if d.is_dir()]
        print(f"  post-cleanup leftover seq dirs: {leftover_dirs}")
        expect("post-cleanup report_index for FR-BX-001 == 0", n_rep == 0)
        expect("post-cleanup work_log for FR-BX-001 == 0", n_work == 0)
        expect("post-cleanup deliveries for FR-BX-001 == 0", n_del == 0)
        expect("post-cleanup leftover seq dirs == 0", not leftover_dirs)

    # Final report
    print(f"\n=== Summary ===")
    if TIMING:
        TIMING.sort()
        p50 = TIMING[len(TIMING)//2]
        p95 = TIMING[int(len(TIMING)*0.95)]
        p99 = TIMING[int(len(TIMING)*0.99)] if len(TIMING) > 99 else TIMING[-1]
        print(f"  issuance timing: p50={p50*1000:.0f}ms  p95={p95*1000:.0f}ms  p99={p99*1000:.0f}ms  max={TIMING[-1]*1000:.0f}ms")
    print(f"  pass: {len(PASS)},  fail: {len(FAIL)}")
    if FAIL:
        print(f"  first 10 failures:")
        for x in FAIL[:10]:
            print(f"    - {x}")
        sys.exit(1)
    print(f"\n  ALL CLEAR — 200 sequential issuances + 30 gap-fill cycles + cleanup all green.")
    sys.exit(0)


if __name__ == "__main__":
    main()
