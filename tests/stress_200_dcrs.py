"""
stress_200_dcrs.py - bulk-create up to 200 synthetic DCRs across a date
range with labor + work + photo payload, exercise the full operator
lifecycle / every interactive control, time the key endpoints (p50 /
p95 / max), then clean back to baseline.

Mirrors the cohort + cleanup pattern in `stress_100_workers.py` but for
DCR volume - answers "do the per-DCR controls hold at scale?" rather
than the 100-worker test's "do workforce-list / DCR / Hours-Log
aggregators stay fast under 100 workers?".

PII-safe: only DCR sequences / counts / latencies / W-#### identifiers
are printed. Never names, phones, image bytes, or absolute paths.

What it does:
  1. SETUP. Snapshot the DB. Capture pre-state baseline (current DCR
     count for FR-BX-001, active worker count = 8).
  2. PAYLOAD. Pick the first 3 real workers (W-0001..W-0003 - guaranteed
     present by the 8-worker baseline) and use them as the sign-in
     cohort, so the labor section has real rows the renderer can JOIN.
     Use a far-future date range (2099-01-01 .. 2099-07-19 = 200 days)
     to guarantee no conflict with any real or backdated data.
  3. PER-DATE LOOP. For each of N_DCRS dates:
        - POST 2 sign-ins (W-0001, W-0002, W-0003 alternating cohorts of 3)
        - POST 2 work_log rows
        - POST 1 photo (tiny synthetic JPEG)
        - POST /issue -> expect 201 + internal.html + client.html on disk
       Per-step timing tracked in dedicated lists.
  4. CONTROL CHECKS (per-control PASS/FAIL):
        a. Issue New DCR - all 200 returned 201
        b. Internal + client HTML files written
        c. Open DCR archive list - returns >= N_DCRS rows
        d. Date-filtered archive - returns exactly N_DCRS rows for our range
        e. Open a single DCR aggregator - returns labor + work + photos
        f. Add labor row - sample POST + verify in aggregator
        g. Remove labor row - DELETE the sample + verify aggregator drops
        h. Add work row - sample POST + verify in aggregator
        i. Remove work row - DELETE + verify
        j. Add photo - sample upload + verify
        k. Remove photo - DELETE + verify file removed from disk
        l. Truncation / pagination - confirm no row caps imposed
        m. Labor / work totals - confirm aggregator math matches inserted
  5. TIMING TABLE (p50 / p95 / max / mean) for:
        - Issue DCR (POST .../issue)
        - Load archive (GET .../reports filtered)
        - Open single DCR (GET .../daily/<date>)
        - Save labor row (POST /api/sign-ins)
        - Save work row (POST /api/work-log)
        - Upload photo (POST /api/photos/upload)
  6. APPEND to TESTING_LIMITS.md. New row under a dated section.
  7. CLEANUP. Targeted DELETE on the date range + sequences we created.
     Verify DB back to baseline pre-DCR count + 8-worker roster + no
     orphan files under data_room/reports/dcr/FR-BX-001/<seq>/ or
     data_room/photos/FR-BX-001/2099-*/.
"""
import base64
import json
import os
import shutil
import sqlite3
import statistics
import subprocess
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

PROJECT = "FR-BX-001"
N_DCRS = 200                       # the volume tier we're validating
START_DATE = date(2099, 1, 1)      # far future - no risk of overlapping real data
RUN_MARKER = "DCR200_" + uuid.uuid4().hex[:6].upper()

# Tiny valid JPEG - same bytes pattern used by smoke_card_propagation.
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
    backups = SCRIPT_DIR / "data_room" / "db_backups"
    backups.mkdir(parents=True, exist_ok=True)
    dest = backups / f"superstars-pre-{label}-{ts}.db"
    shutil.copy2(str(DB_PATH), str(dest))
    return dest


# ---------- Per-control PASS/FAIL bookkeeping ----------

CONTROLS = {}     # name -> (pass_count, fail_count, notes)


def record(control, ok, note=""):
    p, f, ns = CONTROLS.get(control, (0, 0, []))
    if ok:
        p += 1
    else:
        f += 1
        if note:
            ns.append(note)
    CONTROLS[control] = (p, f, ns)


# ---------- Setup ----------

def pre_state():
    conn = db()
    try:
        # All DCR rows for FR-BX-001 (any audience) - baseline count we must
        # restore at cleanup. Using report_index since the project-scoped
        # archive endpoint reads it.
        n_reports = conn.execute(
            "SELECT COUNT(*) FROM report_index WHERE project_code = ? AND report_type = 'DCR'",
            (PROJECT,)
        ).fetchone()[0]
        n_workers = conn.execute(
            "SELECT COUNT(*) FROM employees WHERE archived_at IS NULL"
        ).fetchone()[0]
    finally:
        conn.close()
    return {"reports": n_reports, "workers": n_workers}


def pick_test_workers():
    """Pick the 3 lowest-numbered active workers - guaranteed present in the
    8-worker baseline. Their employee_ids are returned for sign-in POSTs."""
    conn = db()
    try:
        rows = conn.execute(
            "SELECT employee_id, worker_id FROM employees "
            "WHERE worker_id IS NOT NULL AND archived_at IS NULL "
            "ORDER BY CAST(SUBSTR(worker_id, 3) AS INTEGER) ASC LIMIT 3"
        ).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def issue_one_dcr(d_str, workers, signin_ms, work_ms, photo_ms, issue_ms):
    """One full DCR build-and-issue for a single date. Times each step
    and appends to the supplied accumulators. Returns the issued
    dcr_sequence (or None on failure)."""
    # 2 sign-ins (alternating between workers[0] and workers[1])
    for i, w in enumerate(workers[:2]):
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/sign-ins", json={
            "employee_id": w["employee_id"], "project_code": PROJECT,
            "date": d_str, "time_in": f"0{7+i}:00", "time_out": f"1{5+i}:30",
        }, timeout=10)
        signin_ms.append(time.perf_counter() - t0)
        record("save_labor_row", r.status_code in (201,), f"{d_str}: {r.status_code}")
    # 2 work_log rows
    for i in range(2):
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/work-log", json={
            "project_code": PROJECT, "date": d_str,
            "trade_area": "Mason",
            "location_elevation": f"L{i+5}",
            "description": f"{RUN_MARKER} synthetic work row {i+1}",
        }, timeout=10)
        work_ms.append(time.perf_counter() - t0)
        record("save_work_row", r.status_code in (201,), f"{d_str}: {r.status_code}")
    # 1 photo
    t0 = time.perf_counter()
    r = requests.post(
        f"{BASE}/api/photos/upload",
        data={
            "project_code": PROJECT, "date": d_str,
            "location": f"{RUN_MARKER} L5",
            "description": f"{RUN_MARKER} synthetic",
        },
        files={"photo": ("stress.jpg", JPG_TINY, "image/jpeg")},
        timeout=15,
    )
    photo_ms.append(time.perf_counter() - t0)
    record("save_photo", r.status_code in (201,), f"{d_str}: {r.status_code}")
    # ISSUE
    t0 = time.perf_counter()
    r = requests.post(
        f"{BASE}/api/projects/{PROJECT}/daily/{d_str}/issue",
        json={"audience": "both", "override_active": True},
        timeout=60,
    )
    issue_ms.append(time.perf_counter() - t0)
    seq = None
    if r.status_code == 201:
        try:
            seq = r.json()["data"]["sequence"]
        except Exception:
            seq = None
    record("issue_dcr", r.status_code == 201, f"{d_str}: {r.status_code}")
    # File-system check for the issued HTML - internal + client
    if seq is not None:
        seq_dir = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PROJECT / f"{seq:03d}"
        internal_ok = (seq_dir / "internal.html").exists()
        client_ok = (seq_dir / "client.html").exists()
        record("internal_html_written", internal_ok, f"seq={seq}")
        record("client_html_written", client_ok, f"seq={seq}")
    return seq


# ---------- Lifecycle / control checks (post-issue) ----------

def check_archive_and_filter(min_count, our_dates):
    # Archive list - no filter (returns ALL DCRs for FR-BX-001).
    arc_ms = []
    t0 = time.perf_counter()
    r = requests.get(f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR", timeout=30)
    arc_ms.append(time.perf_counter() - t0)
    record("archive_open", r.status_code == 200)
    rows = (r.json() or {}).get("data", []) if r.status_code == 200 else []
    record("archive_returns_at_least_N", len(rows) >= min_count,
           f"got {len(rows)}, expected >= {min_count}")
    # Date-filtered archive
    t0 = time.perf_counter()
    r = requests.get(
        f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR"
        f"&from_date={our_dates[0]}&to_date={our_dates[-1]}",
        timeout=30,
    )
    arc_ms.append(time.perf_counter() - t0)
    record("archive_date_filter", r.status_code == 200)
    filtered = (r.json() or {}).get("data", []) if r.status_code == 200 else []
    # Filter yields rows whose report_date falls in the range. Each of our
    # dates produces 1 internal row in report_index (client also in DB but
    # the public endpoint dedupes via display_id-by-sequence).
    matched = [row for row in filtered if row.get("report_date") in our_dates]
    record("archive_filter_matches_run", len(matched) == len(our_dates),
           f"got {len(matched)}, expected {len(our_dates)}")
    return arc_ms


def check_single_dcr(d_str):
    """Open the aggregator for one of our dates; confirm labor + work + photos
    populated. Returns elapsed-seconds list."""
    open_ms = []
    t0 = time.perf_counter()
    r = requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{d_str}?audience=internal", timeout=30,
    )
    open_ms.append(time.perf_counter() - t0)
    record("open_single_dcr", r.status_code == 200)
    d = (r.json() or {}).get("data") if r.status_code == 200 else {}
    labor = (d or {}).get("labor") or {}
    rows = labor.get("rows") or []
    # 2 sign-ins per DCR -> 2 labor rows expected
    record("labor_rows_match_inserted", len(rows) == 2, f"got {len(rows)}, expected 2")
    # work_performed: 2 work_log rows -> 2 entries
    work = (d or {}).get("work_performed") or []
    record("work_rows_match_inserted", len(work) == 2, f"got {len(work)}, expected 2")
    # photos
    photos = (d or {}).get("photos") or []
    record("photos_match_inserted", len(photos) == 1, f"got {len(photos)}, expected 1")
    # Totals check - total_hours equals sum of per-row hours
    expected_total = round(sum(r.get("hours") or 0 for r in rows), 2)
    record("labor_total_correct", float(labor.get("total_hours") or 0) == expected_total,
           f"reported {labor.get('total_hours')}, expected {expected_total}")
    return open_ms


def check_add_remove_labor(d_str, w):
    """Add an extra labor row, verify aggregator shows 3 rows; remove and
    verify back to 2."""
    # Add
    r = requests.post(f"{BASE}/api/sign-ins", json={
        "employee_id": w["employee_id"], "project_code": PROJECT,
        "date": d_str, "time_in": "06:00", "time_out": "06:30",
    }, timeout=10)
    record("add_labor_row", r.status_code == 201)
    sign_in_id = r.json().get("data", {}).get("id") if r.status_code == 201 else None
    after_add = requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{d_str}?audience=internal", timeout=30,
    ).json()["data"]["labor"]["rows"]
    record("labor_row_visible_after_add", len(after_add) == 3,
           f"got {len(after_add)}, expected 3")
    # Remove
    if sign_in_id:
        rr = requests.delete(f"{BASE}/api/sign-ins/{sign_in_id}", timeout=10)
        record("remove_labor_row", rr.status_code in (200, 204))
    after_rem = requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{d_str}?audience=internal", timeout=30,
    ).json()["data"]["labor"]["rows"]
    record("labor_row_gone_after_remove", len(after_rem) == 2,
           f"got {len(after_rem)}, expected 2")


def check_add_remove_work(d_str):
    r = requests.post(f"{BASE}/api/work-log", json={
        "project_code": PROJECT, "date": d_str,
        "trade_area": "Carp",
        "location_elevation": "L9",
        "description": f"{RUN_MARKER} add-remove-test row",
    }, timeout=10)
    record("add_work_row", r.status_code == 201)
    row_id = r.json().get("data", {}).get("id") if r.status_code == 201 else None
    after_add = requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{d_str}?audience=internal", timeout=30,
    ).json()["data"].get("work_performed") or []
    record("work_row_visible_after_add", len(after_add) == 3,
           f"got {len(after_add)}, expected 3")
    if row_id:
        rr = requests.delete(f"{BASE}/api/work-log/{row_id}", timeout=10)
        record("remove_work_row", rr.status_code in (200, 204))
    after_rem = requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{d_str}?audience=internal", timeout=30,
    ).json()["data"].get("work_performed") or []
    record("work_row_gone_after_remove", len(after_rem) == 2,
           f"got {len(after_rem)}, expected 2")


def check_add_remove_photo(d_str):
    r = requests.post(
        f"{BASE}/api/photos/upload",
        data={"project_code": PROJECT, "date": d_str,
              "location": f"{RUN_MARKER} extra",
              "description": f"{RUN_MARKER} add-remove"},
        files={"photo": ("extra.jpg", JPG_TINY, "image/jpeg")},
        timeout=15,
    )
    record("add_photo", r.status_code == 201)
    pid = r.json().get("data", {}).get("id") if r.status_code == 201 else None
    after_add = requests.get(
        f"{BASE}/api/projects/{PROJECT}/daily/{d_str}?audience=internal", timeout=30,
    ).json()["data"].get("photos") or []
    record("photo_visible_after_add", len(after_add) == 2,
           f"got {len(after_add)}, expected 2")
    # Check the actual photo file is on disk
    file_path_on_disk = None
    if pid:
        conn = db()
        try:
            row = conn.execute("SELECT file_path FROM photos WHERE id = ?", (pid,)).fetchone()
            file_path_on_disk = row["file_path"] if row else None
        finally:
            conn.close()
        record("photo_file_on_disk", bool(file_path_on_disk and Path(file_path_on_disk).exists()))
    # Remove
    if pid:
        rr = requests.delete(f"{BASE}/api/photos/{pid}", timeout=10)
        record("remove_photo", rr.status_code in (200, 204))
        if file_path_on_disk:
            record("photo_file_removed_from_disk", not Path(file_path_on_disk).exists())


# ---------- Cleanup ----------

def cleanup(our_dates, our_seqs):
    """Hard-delete every test row + file by the run's date range and
    sequence list. Verify counts after."""
    print(f"[cleanup] removing {len(our_dates)} dates of synthetic DCR data ...")
    conn = db()
    try:
        ph_dates = ",".join(["?"] * len(our_dates))
        # Tables with project_code + date columns
        for tbl in ("sign_in_log", "work_log", "deliveries", "photos",
                    "equipment_log", "weather_log", "safety_events",
                    "issues", "inspections", "visitors",
                    "toolbox_talk_records"):
            try:
                conn.execute(
                    f"DELETE FROM {tbl} WHERE project_code = ? AND date IN ({ph_dates})",
                    [PROJECT] + our_dates,
                )
            except sqlite3.OperationalError:
                # Some tables may not exist on older schemas; ignore.
                pass
        # report_index - drop both audiences for each of our sequences
        if our_seqs:
            ph_seqs = ",".join(["?"] * len(our_seqs))
            conn.execute(
                f"DELETE FROM report_index WHERE project_code = ? "
                f"AND report_type = 'DCR' AND dcr_sequence IN ({ph_seqs})",
                [PROJECT] + our_seqs,
            )
        conn.commit()
    finally:
        conn.close()

    # Remove HTML output dirs for each sequence
    dcr_root = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PROJECT
    for seq in our_seqs:
        d = dcr_root / f"{seq:03d}"
        if d.exists():
            try:
                shutil.rmtree(str(d))
            except Exception:
                pass

    # Remove any photo files left under data_room/photos/FR-BX-001/<date>/
    photo_root = SCRIPT_DIR / "data_room" / "photos" / PROJECT
    if photo_root.exists():
        for d_str in our_dates:
            d = photo_root / d_str
            if d.exists():
                try:
                    shutil.rmtree(str(d))
                except Exception:
                    pass


def verify_back_to_baseline(pre, our_dates, our_seqs):
    post = pre_state()
    record("reports_back_to_baseline", post["reports"] == pre["reports"],
           f"pre={pre['reports']} post={post['reports']}")
    record("workers_back_to_baseline", post["workers"] == pre["workers"],
           f"pre={pre['workers']} post={post['workers']}")
    # File-system orphan checks
    dcr_root = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PROJECT
    orphan_seq_dirs = [s for s in our_seqs if (dcr_root / f"{s:03d}").exists()]
    record("no_orphan_seq_dirs", not orphan_seq_dirs,
           f"orphans: {orphan_seq_dirs[:5]}{'...' if len(orphan_seq_dirs) > 5 else ''}")
    photo_root = SCRIPT_DIR / "data_room" / "photos" / PROJECT
    orphan_photo_dirs = []
    if photo_root.exists():
        orphan_photo_dirs = [d for d in our_dates if (photo_root / d).exists()]
    record("no_orphan_photo_dirs", not orphan_photo_dirs,
           f"orphans: {orphan_photo_dirs[:5]}")


# ---------- TESTING_LIMITS.md ----------

def append_to_testing_limits(timings, counts, our_seqs, snapshot_path):
    path = SCRIPT_DIR / "TESTING_LIMITS.md"
    today = date.today().isoformat()
    issue, archive, single, labor, work, photo = (
        timings["issue"], timings["archive"], timings["single"],
        timings["labor"], timings["work"], timings["photo"],
    )

    def row(label, xs):
        if not xs:
            return f"| {label} | - | - | - | - | 0 |\n"
        return (f"| {label} | "
                f"{1000*statistics.median(xs):.0f} ms | "
                f"{1000*pct(xs, 0.95):.0f} ms | "
                f"{1000*max(xs):.0f} ms | "
                f"{1000*statistics.mean(xs):.0f} ms | "
                f"{len(xs)} |\n")

    pass_total = sum(p for (p, f, _) in CONTROLS.values())
    fail_total = sum(f for (p, f, _) in CONTROLS.values())
    pass_fail = "all-PASS" if fail_total == 0 else f"{fail_total} FAIL"

    section = (
        f"\n### {today} - 200-DCR stress (run {RUN_MARKER})\n\n"
        f"Synthetic cohort: **{counts['dcrs']} DCRs** across "
        f"{counts['dates_first']} -> {counts['dates_last']} "
        f"({counts['dates_count']} dates), each with 2 sign-ins + "
        f"2 work_log rows + 1 photo. Sequences issued: "
        f"{our_seqs[0]:03d}..{our_seqs[-1]:03d}. "
        f"Lifecycle controls: {pass_total} PASS / {fail_total} FAIL ({pass_fail}).\n\n"
        f"| Endpoint | p50 | p95 | max | mean | iters |\n"
        f"|---|---|---|---|---|---|\n"
        f"{row(f'POST /api/projects/{PROJECT}/daily/&lt;date&gt;/issue', issue)}"
        f"{row(f'GET  /api/projects/{PROJECT}/reports (filtered)', archive)}"
        f"{row(f'GET  /api/projects/{PROJECT}/daily/&lt;date&gt;', single)}"
        f"{row('POST /api/sign-ins (save labor row)', labor)}"
        f"{row('POST /api/work-log (save work row)', work)}"
        f"{row('POST /api/photos/upload (save photo)', photo)}\n"
        f"DB returned to {counts['post_reports']}-report baseline "
        f"(pre={counts['pre_reports']}) and {counts['post_workers']}-worker roster "
        f"(pre={counts['pre_workers']}) after cleanup. "
        f"Snapshot: `{snapshot_path.name}`.\n"
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
    print(f"== 200-DCR stress (RUN_MARKER={RUN_MARKER}) ==\n")
    snapshot_path = snapshot_db("dcr-200-stress")
    print(f"[snapshot] {snapshot_path.name}")
    pre = pre_state()
    print(f"[pre] reports={pre['reports']} active workers={pre['workers']}")
    workers = pick_test_workers()
    if len(workers) < 3:
        print(f"ERROR: need 3 active workers, only found {len(workers)}")
        return 2
    print(f"[setup] using cohort: {[w['worker_id'] for w in workers]}")

    # Build the date range
    our_dates = [(START_DATE + timedelta(days=i)).isoformat() for i in range(N_DCRS)]
    signin_ms, work_ms, photo_ms, issue_ms = [], [], [], []
    our_seqs = []

    print(f"\n[issue] {N_DCRS} DCRs across {our_dates[0]} -> {our_dates[-1]} ...")
    for i, d_str in enumerate(our_dates):
        seq = issue_one_dcr(d_str, workers, signin_ms, work_ms, photo_ms, issue_ms)
        if seq is not None:
            our_seqs.append(seq)
        if (i + 1) % 25 == 0:
            print(f"  [{i+1:03d}/{N_DCRS}] issued; "
                  f"issue p50 so far = {1000*statistics.median(issue_ms):.0f}ms")

    seqs_range = f"({our_seqs[0]:03d}..{our_seqs[-1]:03d})" if our_seqs else "(none)"
    print(f"\n[issued] {len(our_seqs)}/{N_DCRS} DCRs got sequences {seqs_range}")

    arc_ms, open_ms = [], []
    try:
        print("\n[controls] running per-control PASS/FAIL checks ...")
        arc_ms = check_archive_and_filter(min_count=len(our_seqs), our_dates=our_dates)
        # Sample a DCR mid-range for the open/add/remove flows
        sample_date = our_dates[len(our_dates) // 2]
        open_ms = check_single_dcr(sample_date)
        check_add_remove_labor(sample_date, workers[2])
        check_add_remove_work(sample_date)
        check_add_remove_photo(sample_date)
    finally:
        # Cleanup is non-negotiable — even if a control check raised, we
        # restore the DB so the next run starts from baseline.
        print("\n[cleanup]")
        # Also fold in any sequences we didn't capture (rare: a 201 with
        # malformed JSON) by sweeping report_index for our date range.
        conn = db()
        try:
            extra_seqs = [r['dcr_sequence'] for r in conn.execute(
                "SELECT DISTINCT dcr_sequence FROM report_index "
                "WHERE project_code = ? AND report_type = 'DCR' AND report_date LIKE ?",
                (PROJECT, '2099-%'),
            ).fetchall()]
        finally:
            conn.close()
        union_seqs = sorted(set(our_seqs) | set(extra_seqs))
        cleanup(our_dates, union_seqs)
        verify_back_to_baseline(pre, our_dates, union_seqs)
    post = pre_state()

    timings = {
        "issue": issue_ms,
        "archive": arc_ms,
        "single": open_ms,
        "labor": signin_ms,
        "work": work_ms,
        "photo": photo_ms,
    }
    counts = {
        "dcrs": len(our_seqs),
        "dates_count": len(our_dates),
        "dates_first": our_dates[0],
        "dates_last": our_dates[-1],
        "pre_reports": pre["reports"], "post_reports": post["reports"],
        "pre_workers": pre["workers"], "post_workers": post["workers"],
    }

    # ---- Per-control summary ----
    print("\n== PER-CONTROL PASS/FAIL ==")
    print(f"{'CONTROL':<38} {'PASS':>6} {'FAIL':>6}")
    print("-" * 52)
    overall_ok = True
    for k in sorted(CONTROLS.keys()):
        p, f, notes = CONTROLS[k]
        print(f"{k:<38} {p:>6} {f:>6}")
        if f:
            overall_ok = False
            for n in notes[:3]:
                print(f"  - {n}")

    print("\n== TIMINGS ==")
    print(f"  issue        : {fmt_lat(issue_ms)}")
    print(f"  archive (x2) : {fmt_lat(arc_ms)}")
    print(f"  open single  : {fmt_lat(open_ms)}")
    print(f"  labor save   : {fmt_lat(signin_ms)}")
    print(f"  work save    : {fmt_lat(work_ms)}")
    print(f"  photo save   : {fmt_lat(photo_ms)}")

    section = append_to_testing_limits(timings, counts, our_seqs, snapshot_path)
    print("\n--- TESTING_LIMITS.md entry ---")
    print(section)

    total = time.perf_counter() - t0
    print(f"\nTotal run: {total:.1f}s")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
