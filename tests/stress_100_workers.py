"""
stress_100_workers.py — bulk-create 100 synthetic workers, issue a
representative sample of CoF + Company ID cards at scale, time the
workforce list / DCR / Weekly Hours Log endpoints, capture p50/p95
latencies, then clean back to the 8-worker baseline.

PII-safe: synthetic workers (employee_id 'SMK-...'), no real names/phones
beyond test phones (5550...). Only IDs/counts/latencies printed.

Layout:
  - Create 100 SMK- workers, assign each a worker_id, set phone (-> PIN)
  - Upload a tiny test JPEG as face photo to every worker
  - 50 of them get a SCAFFOLD-16 cert -> eligible for CoF
  - Issue CoF for 20 of those 50
  - Issue Company ID for 20 of the other 50 (no prereq)
  - Add backdated sign-ins so the DCR + Hours Log have data to aggregate
  - Time intake-summary, DCR aggregator, Weekly Hours Log — 10 iterations
    each — and compute p50 / p95 / max
  - Append a row to TESTING_LIMITS.md
  - Cleanup: hard-delete all SMK- workers via API or direct SQL (their
    history is also test-marked); verify back to 8 workers
"""
import base64
import hashlib
import os
import statistics
import sqlite3
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
import db_layer  # noqa: E402  # #260 — route DB access through the env-driven layer (SSC_DB_URL)

PROJECT = "FR-BX-001"
N_TOTAL = 100
N_PREREQ = 50          # workers given SCAFFOLD-16 (CoF-eligible)
N_COF_ISSUE = 20       # workers actually issued CoF
N_CID_ISSUE = 20       # workers actually issued Company ID
ITERS = 10             # iterations per endpoint timing
RUN_MARKER = "STR_" + uuid.uuid4().hex[:6].upper()

JPG_TINY = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8U"
    "HRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgN"
    "DRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIy"
    "MjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAr/xAAU"
    "EAEAAAAAAAAAAAAAAAAAAAAA/8QAFAEBAAAAAAAAAAAAAAAAAAAAAP/EABQRAQAAAAAA"
    "AAAAAAAAAAAAAAD/2gAMAwEAAhEDEQA/AKp//9k="
)


def db():
    conn = db_layer.connect()
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def time_n(fn, n=ITERS):
    """Run fn() n times, return list of elapsed seconds."""
    elapsed = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        elapsed.append(time.perf_counter() - t0)
    return elapsed


def pct(xs, q):
    """Quantile q in [0,1] over xs."""
    if not xs:
        return None
    xs = sorted(xs)
    idx = int(round(q * (len(xs) - 1)))
    return xs[idx]


def fmt_lat(xs):
    if not xs:
        return "—"
    return (f"p50={1000*statistics.median(xs):.1f}ms "
            f"p95={1000*pct(xs, 0.95):.1f}ms "
            f"max={1000*max(xs):.1f}ms "
            f"mean={1000*statistics.mean(xs):.1f}ms")


# ---------- Setup ----------

def bulk_create_workers():
    print(f"[setup] creating {N_TOTAL} synthetic workers ...")
    ids = []
    for i in range(N_TOTAL):
        sid = f"SMK-{RUN_MARKER[-6:]}-{i:03d}"
        r = requests.post(f"{BASE}/api/workers/create", json={
            "employee_id": sid,
            "name": f"SMK Stress {i:03d}",
            "trade": "SMK_STRESS",
        }, timeout=10)
        if r.status_code != 200:
            raise RuntimeError(f"create {sid}: {r.status_code} {r.text[:120]}")
        ids.append(sid)
    return ids


def assign_worker_ids(ids):
    print("[setup] assigning W-#### + setting phone (-> PIN) ...")
    from worker_id import next_worker_id_sequence, format_worker_id
    conn = db()
    try:
        # Allocate W-#### in a single transaction so the sequence is contiguous.
        seq = next_worker_id_sequence(conn)
        wid_by = {}
        for i, sid in enumerate(ids):
            wid = format_worker_id(seq + i)
            conn.execute("UPDATE employees SET worker_id = ? WHERE employee_id = ?", (wid, sid))
            wid_by[sid] = wid
        conn.commit()
    finally:
        conn.close()
    # Use the public PATCH to derive PIN from phone — exercises that path
    # at scale. Phones intentionally vary so PINs differ across workers.
    for i, sid in enumerate(ids):
        phone = f"555{i:04d}{(i*7) % 1000:03d}"   # 10-digit, varying
        requests.patch(f"{BASE}/api/employees/{sid}", json={"phone": phone}, timeout=10)
    return wid_by


def upload_face_photos(ids):
    print(f"[setup] uploading face photos ({len(ids)}) ...")
    for sid in ids:
        requests.post(
            f"{BASE}/api/employees/{sid}/face-photo",
            files={"file": ("face.jpg", JPG_TINY, "image/jpeg")},
            timeout=15,
        )


def add_prereq(ids):
    print(f"[setup] adding SCAFFOLD-16 prereq to {len(ids)} workers ...")
    for sid in ids:
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


def issue_for(ids, want_type, n):
    print(f"[setup] issuing {want_type.upper()} for {n} workers ...")
    issued = []
    for sid in ids[:n]:
        r = requests.post(
            f"{BASE}/api/employees/{sid}/credential/issue",
            json={"issued_by": RUN_MARKER, "override_active": True},
            timeout=30,
        )
        if r.status_code == 201:
            issued.append(sid)
    return issued


def add_sign_ins_for_day(ids, day):
    """Backdated 8-hr shift for every worker on `day`."""
    print(f"[setup] adding sign-ins on {day} for {len(ids)} workers ...")
    for sid in ids:
        requests.post(f"{BASE}/api/sign-ins", json={
            "employee_id": sid, "project_code": PROJECT,
            "date": day, "time_in": "07:00", "time_out": "15:30",
        }, timeout=10)


# ---------- Timing ----------

def timing_pass(ids):
    """Time the 3 user-facing surfaces at 100-worker scale."""
    # 1) workforce list (intake-summary)
    iw = time_n(lambda: requests.get(f"{BASE}/api/workers/intake-summary", timeout=30).raise_for_status())
    # 2) DCR aggregator — pick a date that has sign-ins
    target_date = (date.today() - timedelta(days=2)).isoformat()
    dc = time_n(lambda: requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{target_date}", timeout=30,
    ).raise_for_status())
    # 3) Weekly Hours Log — last completed week
    # Pick the Monday of (today - 8 days) to ensure a completed week
    today_d = date.today()
    monday = today_d - timedelta(days=today_d.weekday() + 7)
    hl = time_n(lambda: requests.get(
        f"{BASE}/api/payroll/hours?week_start={monday.isoformat()}", timeout=30,
    ).raise_for_status())
    return {
        "intake_summary": iw,
        "dcr_aggregator": dc,
        "weekly_hours_log": hl,
        "dcr_date": target_date,
        "weekly_monday": monday.isoformat(),
    }


# ---------- Cleanup ----------

def cleanup(ids):
    print(f"[cleanup] removing {len(ids)} synthetic workers and their history ...")
    conn = db()
    try:
        ph = ",".join(["?"] * len(ids))
        # Cards / certs / sign-ins / docs / assignments first (FK-friendly order)
        for tbl in ("cof_cards", "company_id_cards", "certifications",
                    "worker_documents", "sign_in_log",
                    "project_assignments", "employees"):
            conn.execute(f"DELETE FROM {tbl} WHERE employee_id IN ({ph})", ids)
        conn.commit()
    finally:
        conn.close()
    # Remove the worker_records folders we made
    wr = SCRIPT_DIR / "worker_records"
    if wr.exists():
        for p in wr.iterdir():
            if p.is_dir() and any(p.name.startswith(sid + "_") for sid in ids):
                try:
                    import shutil
                    shutil.rmtree(str(p))
                except Exception:
                    pass
    # Remove any rendered cards / snapshots for these workers
    for sub in ("cof", "company_id"):
        d = SCRIPT_DIR / "data_room" / "credentials" / sub
        if d.exists():
            for p in d.iterdir():
                if any(p.name.startswith(sid + "_") or p.name.startswith(sid + ".") for sid in ids):
                    try: p.unlink()
                    except Exception: pass


def baseline_active_count():
    r = requests.get(f"{BASE}/api/workers/intake-summary", timeout=15).json()["data"]
    return len(r)


# ---------- Logging to TESTING_LIMITS.md ----------

def append_to_testing_limits(timings, counts):
    path = SCRIPT_DIR / "TESTING_LIMITS.md"
    today = date.today().isoformat()
    iw = timings["intake_summary"]
    dc = timings["dcr_aggregator"]
    hl = timings["weekly_hours_log"]
    section = (
        f"\n### {today} — 100-worker stress (run {RUN_MARKER})\n\n"
        f"Synthetic cohort: **{counts['workers']} workers**, "
        f"{counts['cof_issued']} CoF + {counts['cid_issued']} Company ID issued, "
        f"sign-ins recorded for {counts['signin_workers']} workers on {timings['dcr_date']}.\n\n"
        f"| Endpoint | p50 | p95 | max | mean | iters |\n"
        f"|---|---|---|---|---|---|\n"
        f"| `GET /api/workers/intake-summary` | "
        f"{1000*statistics.median(iw):.0f} ms | {1000*pct(iw,0.95):.0f} ms | "
        f"{1000*max(iw):.0f} ms | {1000*statistics.mean(iw):.0f} ms | {len(iw)} |\n"
        f"| `GET /api/projects/{PROJECT}/daily/{timings['dcr_date']}` | "
        f"{1000*statistics.median(dc):.0f} ms | {1000*pct(dc,0.95):.0f} ms | "
        f"{1000*max(dc):.0f} ms | {1000*statistics.mean(dc):.0f} ms | {len(dc)} |\n"
        f"| `GET /api/payroll/hours?week_start={timings['weekly_monday']}` | "
        f"{1000*statistics.median(hl):.0f} ms | {1000*pct(hl,0.95):.0f} ms | "
        f"{1000*max(hl):.0f} ms | {1000*statistics.mean(hl):.0f} ms | {len(hl)} |\n\n"
        f"DB returned to {counts['post_cleanup']}-worker baseline after run "
        f"(expected 8). Cleanup via direct SQL on test-marked rows; no real "
        f"worker rows touched.\n"
    )
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    with open(str(path), "a", encoding="utf-8") as f:
        if not existing or not existing.endswith("\n"):
            f.write("\n")
        f.write(section)
    print(f"\n[log] appended timing entry to TESTING_LIMITS.md")
    return section


# ---------- Driver ----------

def main():
    t0 = time.perf_counter()
    print(f"== 100-worker stress (RUN_MARKER={RUN_MARKER}) ==\n")
    pre_count = baseline_active_count()
    print(f"[pre] active workers: {pre_count}")

    ids = bulk_create_workers()
    wids = assign_worker_ids(ids)
    upload_face_photos(ids)

    # 50 get prereq -> 20 issued CoF
    prereq_pool = ids[:N_PREREQ]
    no_prereq_pool = ids[N_PREREQ:]
    add_prereq(prereq_pool)
    cof_issued = issue_for(prereq_pool, "cof", N_COF_ISSUE)
    cid_issued = issue_for(no_prereq_pool, "company_id", N_CID_ISSUE)
    print(f"[setup] CoF issued: {len(cof_issued)}, Company ID issued: {len(cid_issued)}")

    # Sign-ins so DCR + Hours Log have payload
    signin_day = (date.today() - timedelta(days=2)).isoformat()
    add_sign_ins_for_day(ids, signin_day)
    n_signin = len(ids)

    setup_secs = time.perf_counter() - t0
    print(f"\n[setup done] {setup_secs:.1f}s elapsed\n")

    print("[timing] 10 iterations per endpoint ...")
    timings = timing_pass(ids)
    print(f"  intake-summary: {fmt_lat(timings['intake_summary'])}")
    print(f"  dcr aggregator: {fmt_lat(timings['dcr_aggregator'])}")
    print(f"  weekly hours:   {fmt_lat(timings['weekly_hours_log'])}")

    print("\n[smoke] sample baseline CRUD still works at 100-worker scale ...")
    # Quick sanity: a sample worker's intake-summary row carries correct fields,
    # and we can render their live card.
    sample = ids[0]
    is_resp = requests.get(f"{BASE}/api/workers/intake-summary", timeout=15).json()["data"]
    sample_row = next((r for r in is_resp if r["employee_id"] == sample), None)
    has_wid = bool(sample_row and (sample_row.get("worker_id") or "").startswith("W-"))
    # Live render: pick a worker who was issued a card
    live_ok_cof = False
    live_ok_cid = False
    if cof_issued:
        live_ok_cof = requests.get(f"{BASE}/api/cards/{cof_issued[0]}/cof/live", timeout=15).status_code == 200
    if cid_issued:
        live_ok_cid = requests.get(f"{BASE}/api/cards/{cid_issued[0]}/company_id/live", timeout=15).status_code == 200
    print(f"  sample W-#### present: {has_wid}; live CoF render: {live_ok_cof}; live CID render: {live_ok_cid}")

    print("\n[cleanup]")
    cleanup(ids)
    post_count = baseline_active_count()
    print(f"[post] active workers: {post_count} (expected 8)")

    counts = {
        "workers": len(ids),
        "cof_issued": len(cof_issued),
        "cid_issued": len(cid_issued),
        "signin_workers": n_signin,
        "post_cleanup": post_count,
    }
    section = append_to_testing_limits(timings, counts)
    print("\n--- TESTING_LIMITS.md entry ---")
    print(section)

    total = time.perf_counter() - t0
    print(f"\nTotal run: {total:.1f}s")
    rc = 0
    if post_count != 8:
        print(f"WARN: post-cleanup count is {post_count}, expected 8")
        rc = 1
    return rc


if __name__ == "__main__":
    sys.exit(main())
