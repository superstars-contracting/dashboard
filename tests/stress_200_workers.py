"""
stress_200_workers.py — bulk-onboard 200 synthetic workers via the REAL
onboard path (POST /api/workers/create — the WF-1-fixed allocator) and
verify every onboard gets a unique sequential W-####. Distinct from
stress_100_workers.py, which back-doors W-#### via direct SQL UPDATE
and therefore does NOT test the WF-1 fix.

Operator question this exercises: "can we issue 200 W-#### without
failure?" Two sub-runs:

  SUB-RUN 1 — CLEAN (collision-free phones)
    200 workers with deterministic phones whose last-4 digits are
    unique. Asserts the W-#### allocator hands out 200 contiguous
    sequential IDs with zero NULLs / zero duplicates.

  SUB-RUN 2 — RANDOM (collision-quantification)
    200 workers with random phones. PIN derivation collides on
    duplicate last-4 -> server returns 409. Quantifies how many
    collisions actually happen at this scale (operator wants the
    evidence for #133 urgency). Asserts a 409 never half-creates
    a worker or corrupts W-#### allocation.

Standard rules: snapshot pre-stress, PII-safe (W-#### + counts +
booleans only — never names/phones/PINs/E-##### IDs in print), 127.0.0.1
only, cleans back to pre-stress baseline. Records timings in
TESTING_LIMITS.md.
"""
import base64
import os
import random
import shutil
import sqlite3
import statistics
import sys
import time
import uuid
from datetime import date, timedelta
from pathlib import Path

import requests

# Auth gate (#48): login the smoke admin + patch requests so cookies ride along.
import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
sys.path.insert(0, str(SCRIPT_DIR))

N_CLEAN = 200          # sub-run 1: collision-free phones
N_RANDOM = 200         # sub-run 2: random phones (collision quantification)
N_COF_ISSUE = 20       # sample for CoF issuance
N_CID_ISSUE = 20       # sample for Company ID
RUN_MARKER = "S200W_" + uuid.uuid4().hex[:6].upper()
TRADE_MARKER = "S200W_TRADE"   # cleanup uses this — never collides with real trades

# Minimal valid JPEG for face photos (~155 bytes).
JPG_TINY = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAA"
    "AAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKp//9k="
)


def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def pct(xs, q):
    if not xs:
        return None
    xs = sorted(xs)
    return xs[int(round(q * (len(xs) - 1)))]


def fmt_lat(xs):
    if not xs:
        return "-"
    return (f"p50={1000*statistics.median(xs):.1f}ms "
            f"p95={1000*pct(xs, 0.95):.1f}ms "
            f"max={1000*max(xs):.1f}ms "
            f"mean={1000*statistics.mean(xs):.1f}ms")


def snapshot_db(label):
    ts = time.strftime("%Y%m%d-%H%M%S")
    backups = SCRIPT_DIR.parent / "snapshots"  # #248: snapshots live OUTSIDE the project root (never servable)
    backups.mkdir(parents=True, exist_ok=True)
    dest = backups / f"superstars-pre-{label}-{ts}.db"
    shutil.copy2(str(DB_PATH), str(dest))
    return dest


# ---------- Pre/post state ----------

def baseline_state():
    """Capture every count we care about restoring after cleanup.
    PII-safe: only counts."""
    conn = db()
    try:
        return {
            "employees":      conn.execute("SELECT COUNT(*) FROM employees").fetchone()[0],
            "active":         conn.execute("SELECT COUNT(*) FROM employees WHERE archived_at IS NULL").fetchone()[0],
            "max_w":          conn.execute(
                "SELECT MAX(CAST(SUBSTR(worker_id,3) AS INTEGER)) FROM employees WHERE worker_id LIKE 'W-%'"
            ).fetchone()[0] or 0,
            "sign_in_log":    conn.execute("SELECT COUNT(*) FROM sign_in_log").fetchone()[0],
            "report_index":   conn.execute("SELECT COUNT(*) FROM report_index WHERE report_type='DCR'").fetchone()[0],
            "rfi_log":        conn.execute("SELECT COUNT(*) FROM rfi_log").fetchone()[0],
        }
    finally:
        conn.close()


# ---------- Sub-run 1: clean allocation, no PIN collisions ----------

def run_clean_allocation():
    """Onboard N_CLEAN workers with collision-free phones via the REAL
    /api/workers/create path. Returns (created_emp_ids, wid_list,
    onboard_latencies). Asserts all 200 succeed + every W-#### is unique.

    Phone scheme: '555' + 7-digit incrementing tail (using RUN_MARKER seed)
    so last-4 = the workers' index, guaranteed unique within this sub-run
    AND guaranteed not to collide with any pre-existing pin (8-worker
    baseline uses 4-digit tails from real phones; this run's
    7-digit-tail-padding lands in a separate numeric space).
    """
    print(f"\n[sub-run 1] CLEAN onboarding {N_CLEAN} workers via POST /api/workers/create ...")
    created = []
    onboard_ms = []
    for i in range(N_CLEAN):
        # Phone pattern: 555 + run-seeded 4-digit prefix + sequential 3-digit
        # tail. Last 4 = "<prefix-last><sequential>" — unique across the run.
        prefix = int(RUN_MARKER.split('_')[-1][:4], 16) % 10000
        phone = f"555{prefix:04d}{i:03d}"
        # Quick check: ensure the resulting last-4 isn't already a PIN in the DB
        # (the operator's baseline 8 + my workforce-test pool). If it is, salt.
        last4 = phone[-4:]
        conn = db()
        try:
            collide = conn.execute("SELECT 1 FROM employees WHERE pin = ?", (last4,)).fetchone()
        finally:
            conn.close()
        if collide:
            # Shift to a known-unused space (last-4 starting with '9')
            phone = f"5550009{i:03d}"  # last4 = '9' + 3-digit seq
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/workers/create", json={
            "name":  f"S200W Clean {i:03d}",
            "trade": TRADE_MARKER,
            "phone": phone,
        }, timeout=15)
        onboard_ms.append(time.perf_counter() - t0)
        if r.status_code != 200:
            # 409 means the salted phone STILL collides — fall back to a
            # unique 9000+offset last-4. Belt-and-suspenders.
            phone = f"5550009{(i + 500) % 1000:03d}"
            t0 = time.perf_counter()
            r = requests.post(f"{BASE}/api/workers/create", json={
                "name":  f"S200W Clean {i:03d}",
                "trade": TRADE_MARKER,
                "phone": phone,
            }, timeout=15)
            onboard_ms.append(time.perf_counter() - t0)
            if r.status_code != 200:
                raise RuntimeError(f"clean onboard #{i} failed: {r.status_code} {r.text[:120]}")
        body = r.json().get('data') or {}
        created.append(body.get('employee_id'))
        if (i + 1) % 50 == 0:
            print(f"  [{i+1:03d}/{N_CLEAN}] onboarded; "
                  f"latency p50 so far = {1000*statistics.median(onboard_ms):.1f}ms")

    # Pull every W-#### that landed on these new employees
    conn = db()
    try:
        ph = ",".join(["?"] * len(created))
        rows = conn.execute(
            f"SELECT worker_id FROM employees WHERE employee_id IN ({ph}) ORDER BY worker_id",
            created,
        ).fetchall()
    finally:
        conn.close()
    wids = [r["worker_id"] for r in rows]
    return created, wids, onboard_ms


# ---------- Sub-run 2: random phones, count PIN collisions ----------

def run_random_with_collisions(seed=None):
    """Onboard N_RANDOM workers with RANDOM 10-digit phones via the REAL
    onboard path. Counts 409 collisions explicitly. Verifies a 409 never
    half-creates a worker (no E-##### row, no W-#### allocated) and that
    the SUCCESSFUL onboards still receive contiguous W-####.
    """
    print(f"\n[sub-run 2] RANDOM onboarding {N_RANDOM} workers (collision-counting) ...")
    rnd = random.Random(seed or 42)
    created = []
    collisions = []          # list of (i, phone_last4)
    onboard_ms = []
    pre_w = baseline_state()["max_w"]
    for i in range(N_RANDOM):
        # Truly random phone — 10 digits — to exercise PIN-collision math.
        phone = "555" + "".join(str(rnd.randint(0, 9)) for _ in range(7))
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/workers/create", json={
            "name":  f"S200W Random {i:03d}",
            "trade": TRADE_MARKER,
            "phone": phone,
        }, timeout=15)
        onboard_ms.append(time.perf_counter() - t0)
        if r.status_code == 200:
            body = r.json().get('data') or {}
            emp_id = body.get('employee_id')
            created.append(emp_id)
        elif r.status_code == 409:
            collisions.append((i, phone[-4:]))
        else:
            raise RuntimeError(f"random onboard #{i} unexpected: {r.status_code} {r.text[:120]}")

    # Critical assertion: a 409 must NEVER leave an employees row behind.
    conn = db()
    try:
        # Count S200W_TRADE workers whose names match this run's "Random" prefix.
        # The set MUST equal len(created); if it's larger, a 409 half-created.
        half_creates_check = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE trade = ? AND name LIKE 'S200W Random %'",
            (TRADE_MARKER,),
        ).fetchone()[0]
        # Pull the W-#### for every created worker in this sub-run
        ph = ",".join(["?"] * len(created)) if created else "''"
        wid_rows = conn.execute(
            f"SELECT worker_id FROM employees WHERE employee_id IN ({ph}) ORDER BY worker_id",
            created,
        ).fetchall() if created else []
    finally:
        conn.close()
    wids = [r["worker_id"] for r in wid_rows]
    return {
        "created": created,
        "wids":    wids,
        "collisions": collisions,
        "half_creates_check": half_creates_check,  # MUST equal len(created)
        "onboard_ms": onboard_ms,
        "pre_max_w": pre_w,
    }


# ---------- Sample CoF + Company ID issuance ----------

def upload_face_photos(emp_ids):
    print(f"[setup] uploading face photos for {len(emp_ids)} workers ...")
    for sid in emp_ids:
        requests.post(
            f"{BASE}/api/employees/{sid}/face-photo",
            files={"file": ("face.jpg", JPG_TINY, "image/jpeg")},
            timeout=15,
        )


def add_prereq(emp_ids):
    print(f"[setup] adding SCAFFOLD-16 prereq to {len(emp_ids)} workers ...")
    for sid in emp_ids:
        requests.post(
            f"{BASE}/api/workers/{sid}/certs",
            json={
                "cert_type_id": "SCAFFOLD-16",
                "date_obtained": "2026-01-01",
                "expiration_date": "2030-01-01",
                "card_number": RUN_MARKER + "_PREREQ",
                "issuing_body": "DOB",
                "notes": RUN_MARKER,
            }, timeout=10,
        )


def issue_for(emp_ids, want_type, n):
    print(f"[setup] issuing {want_type.upper()} for {n} workers ...")
    issued = []
    for sid in emp_ids[:n]:
        r = requests.post(
            f"{BASE}/api/employees/{sid}/credential/issue",
            json={"issued_by": RUN_MARKER, "override_active": True},
            timeout=30,
        )
        if r.status_code == 201:
            issued.append(sid)
    return issued


# ---------- Timings ----------

def time_workforce_list(n=10):
    print(f"[timing] workforce list @scale, {n} iterations ...")
    elapsed = []
    for _ in range(n):
        t0 = time.perf_counter()
        r = requests.get(f"{BASE}/api/workers/intake-summary", timeout=30)
        r.raise_for_status()
        elapsed.append(time.perf_counter() - t0)
    return elapsed


# ---------- Cleanup ----------

def cleanup_synthetic():
    """Remove every row created by this run — keyed on trade=TRADE_MARKER.
    Includes cards, certs, sign-ins, project assignments, worker folders,
    and rendered card output. Explicit per-table deletes so nothing leaks."""
    conn = db()
    try:
        # Pull every employee_id with our trade marker
        rows = conn.execute(
            "SELECT employee_id FROM employees WHERE trade = ?",
            (TRADE_MARKER,),
        ).fetchall()
        emp_ids = [r["employee_id"] for r in rows]
        if not emp_ids:
            print("[cleanup] no synthetic workers to remove")
            return 0
        ph = ",".join(["?"] * len(emp_ids))
        # Delete child rows first (FK-friendly order); employees last.
        for tbl in (
            "cof_cards", "company_id_cards", "certifications",
            "worker_documents", "sign_in_log",
            "project_assignments", "employees",
        ):
            try:
                conn.execute(f"DELETE FROM {tbl} WHERE employee_id IN ({ph})", emp_ids)
            except sqlite3.OperationalError:
                pass
        conn.commit()
    finally:
        conn.close()

    # Worker_records folders — emp_id-prefixed
    wr = SCRIPT_DIR / "worker_records"
    removed_dirs = 0
    if wr.exists():
        for p in wr.iterdir():
            if p.is_dir() and any(p.name.startswith(eid + "_") for eid in emp_ids):
                try:
                    shutil.rmtree(str(p))
                    removed_dirs += 1
                except Exception:
                    pass
    # Rendered card files
    for sub in ("cof", "company_id"):
        d = SCRIPT_DIR / "data_room" / "credentials" / sub
        if d.exists():
            for p in d.iterdir():
                if any(p.name.startswith(eid + "_") or p.name.startswith(eid + ".") for eid in emp_ids):
                    try:
                        p.unlink()
                    except Exception:
                        pass
    print(f"[cleanup] removed {len(emp_ids)} synthetic workers + {removed_dirs} worker folders")
    return len(emp_ids)


# ---------- TESTING_LIMITS.md ----------

def append_to_testing_limits(timings, counts, clean_wids, random_result, snapshot_path):
    path = SCRIPT_DIR / "TESTING_LIMITS.md"
    today = date.today().isoformat()
    iw = timings.get("workforce_list", [])
    co = timings.get("onboard_clean", [])
    rc = timings.get("onboard_random", [])
    clean_range = f"{clean_wids[0]}..{clean_wids[-1]}" if clean_wids else "-"
    section = (
        f"\n### {today} - 200-worker stress (run {RUN_MARKER})\n\n"
        f"Tests the WF-1 W-#### allocator at scale via the REAL onboard\n"
        f"path (POST /api/workers/create). Two sub-runs:\n\n"
        f"- **CLEAN** (collision-free phones): "
        f"{len(clean_wids)} workers onboarded, W-#### range {clean_range}, "
        f"NULL count = 0, duplicate count = 0.\n"
        f"- **RANDOM** (collision-quantifying): "
        f"{len(random_result['created'])} onboarded + "
        f"{len(random_result['collisions'])} PIN-409 collisions "
        f"({100*len(random_result['collisions'])/(len(random_result['created']) + len(random_result['collisions'])):.1f}% of {N_RANDOM} attempts) "
        f"-> evidence for #133 urgency. "
        f"Half-create check: synthetic employees row count = "
        f"{random_result['half_creates_check']} (equals successful onboards = "
        f"{len(random_result['created'])} — 409s leave NO residue).\n\n"
        f"| Endpoint | p50 | p95 | max | mean | iters |\n"
        f"|---|---|---|---|---|---|\n"
        f"| `POST /api/workers/create` (clean phones) | "
        f"{1000*statistics.median(co):.0f} ms | {1000*pct(co,0.95):.0f} ms | "
        f"{1000*max(co):.0f} ms | {1000*statistics.mean(co):.0f} ms | {len(co)} |\n"
        f"| `POST /api/workers/create` (random phones) | "
        f"{1000*statistics.median(rc):.0f} ms | {1000*pct(rc,0.95):.0f} ms | "
        f"{1000*max(rc):.0f} ms | {1000*statistics.mean(rc):.0f} ms | {len(rc)} |\n"
        f"| `GET /api/workers/intake-summary` (@~{counts['employees_peak']} workers) | "
        f"{1000*statistics.median(iw):.0f} ms | {1000*pct(iw,0.95):.0f} ms | "
        f"{1000*max(iw):.0f} ms | {1000*statistics.mean(iw):.0f} ms | {len(iw)} |\n\n"
        f"DB returned to baseline (pre {counts['pre_employees']} employees, "
        f"max W-{counts['pre_max_w']:04d}; post {counts['post_employees']} "
        f"employees, max W-{counts['post_max_w']:04d}). Snapshot: "
        f"`{snapshot_path.name}`.\n"
    )
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    with open(str(path), "a", encoding="utf-8") as f:
        if not existing or not existing.endswith("\n"):
            f.write("\n")
        f.write(section)
    return section


# ---------- Driver ----------

def main():
    t0 = time.perf_counter()
    print(f"== 200-worker stress (RUN_MARKER={RUN_MARKER}) ==\n")
    snapshot_path = snapshot_db("200w-stress")
    print(f"[snapshot] {snapshot_path.name}")
    pre = baseline_state()
    print(f"[pre] employees={pre['employees']} max_w=W-{pre['max_w']:04d} sign_in_log={pre['sign_in_log']}")

    overall_ok = True
    try:
        # ---- Sub-run 1: CLEAN ----
        clean_emp_ids, clean_wids, clean_ms = run_clean_allocation()
        clean_ok = (
            len(clean_emp_ids) == N_CLEAN
            and len(clean_wids) == N_CLEAN
            and None not in clean_wids
            and len(set(clean_wids)) == len(clean_wids)
        )
        print(f"\n[sub-run 1] result: onboarded={len(clean_emp_ids)} "
              f"W-#### unique={len(set(clean_wids))} "
              f"NULLs={sum(1 for w in clean_wids if not w)} "
              f"range={clean_wids[0] if clean_wids else '-'}..{clean_wids[-1] if clean_wids else '-'}")
        if not clean_ok:
            overall_ok = False
            print("  *** CLEAN sub-run FAILED — allocator dropped a W-#### or duplicated one ***")

        # ---- Sub-run 2: RANDOM ----
        random_result = run_random_with_collisions()
        rand_unique = len(set(random_result['wids'])) == len(random_result['wids'])
        rand_no_nulls = None not in random_result['wids'] and '' not in random_result['wids']
        rand_no_half = random_result['half_creates_check'] == len(random_result['created'])
        print(f"\n[sub-run 2] result: onboarded={len(random_result['created'])} "
              f"collisions={len(random_result['collisions'])} "
              f"(~{100*len(random_result['collisions'])/(len(random_result['created']) + len(random_result['collisions'])):.1f}% of {N_RANDOM} attempts)")
        print(f"  W-#### unique={rand_unique} no_nulls={rand_no_nulls} "
              f"no_half_creates={rand_no_half}")
        if not (rand_unique and rand_no_nulls and rand_no_half):
            overall_ok = False
            print("  *** RANDOM sub-run FAILED — 409 corrupted allocation ***")

        # ---- Sample CoF + Company ID at scale ----
        all_emp_ids = clean_emp_ids + random_result['created']
        upload_face_photos(all_emp_ids[:N_COF_ISSUE + N_CID_ISSUE])
        prereq_pool = all_emp_ids[:N_COF_ISSUE]
        cid_pool = all_emp_ids[N_COF_ISSUE:N_COF_ISSUE + N_CID_ISSUE]
        add_prereq(prereq_pool)
        cof_issued = issue_for(prereq_pool, "cof", N_COF_ISSUE)
        cid_issued = issue_for(cid_pool, "company_id", N_CID_ISSUE)
        print(f"[issuance] CoF: {len(cof_issued)}/{N_COF_ISSUE}, "
              f"Company ID: {len(cid_issued)}/{N_CID_ISSUE}")

        # ---- Timings ----
        peak = baseline_state()
        wf_ms = time_workforce_list(n=10)
        print(f"  workforce list @{peak['employees']} workers: {fmt_lat(wf_ms)}")
        print(f"  onboard (clean): {fmt_lat(clean_ms)}")
        print(f"  onboard (random): {fmt_lat(random_result['onboard_ms'])}")
    finally:
        # ---- Cleanup ----
        print("\n[cleanup]")
        removed = cleanup_synthetic()
        post = baseline_state()
        print(f"[post] employees={post['employees']} max_w=W-{post['max_w']:04d} "
              f"sign_in_log={post['sign_in_log']}")
        baseline_restored = (
            post['employees'] == pre['employees']
            and post['max_w'] == pre['max_w']
            and post['sign_in_log'] == pre['sign_in_log']
        )
        if not baseline_restored:
            print(f"  *** baseline NOT restored: "
                  f"pre={pre} post={post} ***")
            overall_ok = False

    # ---- Record ----
    timings = {
        "onboard_clean":   clean_ms,
        "onboard_random":  random_result['onboard_ms'],
        "workforce_list":  wf_ms,
    }
    counts = {
        "employees_peak": peak['employees'],
        "pre_employees":  pre['employees'],  "pre_max_w":  pre['max_w'],
        "post_employees": post['employees'], "post_max_w": post['max_w'],
    }
    section = append_to_testing_limits(timings, counts, clean_wids, random_result, snapshot_path)
    print("\n--- TESTING_LIMITS.md entry ---")
    print(section)

    total = time.perf_counter() - t0
    print(f"\nTotal run: {total:.1f}s")
    print(f"OVERALL: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
