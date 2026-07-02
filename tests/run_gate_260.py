#!/usr/bin/env python3
r"""#260 — run the FULL gate against an ISOLATED database, never the live superstars.db.

Phase 1 (hosting migration) test-isolation: the gate must never write to production.
This runner stands up a *separate* waitress test server bound to 127.0.0.1:<GATE_PORT>
(default 5434, away from the live :5050) with SSC_DB_URL pointed at an isolated backend
— either a SQLite snapshot COPY (sqlite:///C:/.../copy.db) or the ssc_test Postgres
database — runs every gate suite against it, then tree-kills ONLY its own server PID
(never the production server). server:app and every routed smoke read SSC_DB_URL through
db_layer, so nothing touches the live SQLite file.

Usage (from the dashboard dir):
  # Postgres test db
  $env:SSC_DB_URL="postgresql://postgres@127.0.0.1:5433/ssc_test"; venv\Scripts\python.exe tests\run_gate_260.py
  # SQLite isolated copy
  $env:SSC_DB_URL="sqlite:///C:/Users/SSC-Admin/Superstars/snapshots/ssc_gate_sqlite.db"; venv\Scripts\python.exe tests\run_gate_260.py
  # one or more named suites only:
  ... tests\run_gate_260.py smoke_dropplan_api.py smoke_auth.py

Env knobs: SSC_DB_URL (required, isolated backend), GATE_PORT (default 5434),
SMOKE_STATIC_PORT (default 5152 — static-exposure launches its own server).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DASH = Path(__file__).resolve().parent.parent
VENV_PY = DASH / "venv" / "Scripts" / "python.exe"
PORT = int(os.environ.get("GATE_PORT", "5434"))
BASE = f"http://127.0.0.1:{PORT}"

# The standard gate, in run order. The meta-smoke runs CRUD + worker_lifecycle as its
# own subprocesses; we also run them standalone for clear per-suite results.
GATE = [
    "smoke_design_conventions.py",
    "smoke_auth.py",
    "smoke_auth_roles.py",
    "smoke_auth_sso.py",          # #261 — Google SSO (mocked verification, own server)
    "smoke_labor_rates.py",
    "smoke_behavior_conventions.py",
    "smoke_pm_scoping_263.py",    # #263 — PM project-scoping (assignment + close lifecycle)
    "smoke_client_portal_264.py", # #264 — client portal + default-deny visibility engine
    "smoke_client_welcome_267.py",# #267 — client welcome hard-stop containment (client → /welcome only)
    "smoke_client_grants_269.py",# #269 — selective client un-gating (per-section default-off grants)
    "smoke_preview_presets_270.py",# #270 — preview-as-client parity + presets + doc bulk share
    "smoke_crm_266.py",           # #266 — CRM/ops core (C-suite-gated; entities/activity/tasks/needs-attention)
    "smoke_dropplan_api.py",
    "smoke_worker_lifecycle.py",
    "smoke_dcr214_lifecycle.py",
    "smoke_crud_data_integrity.py",
    "smoke_static_exposure.py",
    "smoke_no_production_data_corruption.py",
]


def wait_health(deadline: float = 45.0) -> bool:
    end = time.time() + deadline
    while time.time() < end:
        try:
            with urllib.request.urlopen(f"{BASE}/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    suites = [a for a in sys.argv[1:] if not a.startswith("--")] or GATE
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    if not db_url:
        print("REFUSING TO RUN: SSC_DB_URL is unset — that would target the LIVE superstars.db.\n"
              "Set it to an isolated backend (sqlite:///<copy> or postgresql://...ssc_test).")
        return 2

    env = {**os.environ, "SMOKE_BASE": BASE}
    # static-exposure launches its own server; keep it off 5151 (operator preview) by default
    env.setdefault("SMOKE_STATIC_PORT", "5152")

    # #262/#266 — an isolated SQLite copy of live inherits FK-OFF ORPHAN child rows
    # (audit_log.actor_user_id, etc.) whose users.id target was long deleted. When a smoke
    # seeds a fresh user whose auto-increment id COLLIDES with an orphan's ref, the enforced
    # FK on the copy blocks that smoke's teardown DELETE (false FK failure). clean_user_orphans
    # NULLs/DELETEs those orphans; it self-skips Postgres (cleaned during migration) and refuses
    # to run against live. Self-healing here keeps the gate deterministic across DB snapshots.
    orphan_rc = subprocess.run(
        [str(VENV_PY), str(DASH / "clean_user_orphans.py")],
        cwd=str(DASH), capture_output=True, text=True, env=env)
    print((orphan_rc.stdout or "").strip() or "[orphans] (no output)")

    logf = open(DASH / "tests" / "_gate260_srv.log", "w", encoding="utf-8")
    srv = subprocess.Popen(
        [str(VENV_PY), "-m", "waitress", "--host=127.0.0.1", f"--port={PORT}",
         "--threads=8", "server:app"],
        cwd=str(DASH), stdout=logf, stderr=subprocess.STDOUT, env=env,
    )
    try:
        if not wait_health():
            print(f"test server did not come up on {BASE}; see tests/_gate260_srv.log")
            return 2
        print(f"isolated test server up on {BASE}")
        print(f"SSC_DB_URL = {db_url}\n")

        results = []
        for s in suites:
            t = time.time()
            try:
                p = subprocess.run(
                    [str(VENV_PY), str(DASH / "tests" / s)], cwd=str(DASH),
                    capture_output=True, text=True, env=env, timeout=1200,
                )
                rc, out, err = p.returncode, p.stdout, p.stderr
            except subprocess.TimeoutExpired as e:
                rc, out, err = 124, (e.stdout or ""), "TIMEOUT"
            ok = rc == 0
            dt = time.time() - t
            results.append((s, ok, rc, dt))
            print(f"{'PASS' if ok else 'FAIL'}  {s:<42} rc={rc}  {dt:5.1f}s")
            if not ok:
                for line in (out or "").splitlines()[-35:]:
                    print("    |", line)
                for line in (err or "").splitlines()[-12:]:
                    print("   E|", line)
                print()

        npass = sum(1 for _, ok, _, _ in results if ok)
        print("\n" + "=" * 60)
        for s, ok, rc, dt in results:
            print(f"  {'PASS' if ok else 'FAIL'}  {s:<42} {dt:5.1f}s")
        print(f"=== {npass}/{len(results)} suites green ===")
        return 0 if npass == len(results) else 1
    finally:
        # tree-kill ONLY our test server (never the production :5050 server)
        subprocess.run(["cmd", "/c", f"taskkill /F /T /PID {srv.pid}"], capture_output=True)
        logf.close()


if __name__ == "__main__":
    sys.exit(main())
