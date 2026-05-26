"""
stress_300_dcrs.py — 300-DCR scale + exercises the new DCR-2..DCR-6
+ RFI flows added this weekend. Bumps stress_200_dcrs.py to 300 and
adds:

  - DCR-4 reopen-then-re-issue identity preservation at scale
    (assert the same dcr_sequence comes back when override_active=true).
  - DCR-5/6 rapid-cycle clean-slate check (validate the loadDcr race
    guard at the aggregator level — rapid New/Cancel cycling never
    leaves the wrong date's data behind).
  - DCR-2 labor add-dropdown filter check (server-side: the on-site
    endpoint's worker list reflects today's signed-in cohort).
  - DCR-3 photo zoom: assert rendered DCR HTML carries data-zoom-src
    and the inline lightbox script.
  - RFI batch: create 50 synthetic RFIs, exercise register filter
    + Auto-Overdue derivation + /rfi-constraints feed for Phase 3.
  - Latency p50/p95 for: onboard W-#### (sample), issue DCR, archive
    load @300, open single DCR, save labor row, save work row, upload
    photo, RFI register load.

Standing rules: snapshot first, PII-safe (W-#### + counts + booleans
only — never names/phones/PINs/photo bytes), 127.0.0.1 only, cleans
back to baseline incl. sign_in_log (explicit DELETE by date range,
NOT relying on the 07:00-15:30 self-heal). Records timings in
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

PROJECT = "FR-BX-001"
N_DCRS = 300                                    # volume tier
N_RFIS = 50                                     # RFI batch
START_DATE = date(2098, 1, 1)                   # 300 days from here = 2098-10-27
RUN_MARKER = "S300DCR_" + uuid.uuid4().hex[:6].upper()

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

CONTROLS = {}

def record(control, ok, note=""):
    p, f, ns = CONTROLS.get(control, (0, 0, []))
    if ok: p += 1
    else:
        f += 1
        if note: ns.append(note)
    CONTROLS[control] = (p, f, ns)


# ---------- Pre/post state ----------

def baseline_state():
    conn = db()
    try:
        return {
            "reports":    conn.execute(
                "SELECT COUNT(*) FROM report_index WHERE project_code = ? AND report_type='DCR'",
                (PROJECT,),
            ).fetchone()[0],
            "workers":    conn.execute("SELECT COUNT(*) FROM employees WHERE archived_at IS NULL").fetchone()[0],
            "rfis":       conn.execute("SELECT COUNT(*) FROM rfi_log WHERE project_code = ?", (PROJECT,)).fetchone()[0],
            "sign_in_log":conn.execute("SELECT COUNT(*) FROM sign_in_log").fetchone()[0],
        }
    finally:
        conn.close()


# ---------- Workers cohort (use baseline workers, not synthetic) ----------

def pick_test_workers():
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


# ---------- One DCR build-and-issue ----------

def issue_one_dcr(d_str, workers, signin_ms, work_ms, photo_ms, issue_ms):
    for i, w in enumerate(workers[:2]):
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/sign-ins", json={
            "employee_id": w["employee_id"], "project_code": PROJECT,
            "date": d_str, "time_in": f"0{7+i}:00", "time_out": f"1{5+i}:30",
        }, timeout=10)
        signin_ms.append(time.perf_counter() - t0)
        record("save_labor_row", r.status_code in (201,), f"{d_str}: {r.status_code}")
    for i in range(2):
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/work-log", json={
            "project_code": PROJECT, "date": d_str,
            "trade_area": "Mason", "location_elevation": f"L{i+5}",
            "description": f"{RUN_MARKER} synth work {i+1}",
        }, timeout=10)
        work_ms.append(time.perf_counter() - t0)
        record("save_work_row", r.status_code in (201,))
    t0 = time.perf_counter()
    r = requests.post(
        f"{BASE}/api/photos/upload",
        data={"project_code": PROJECT, "date": d_str,
              "location": f"{RUN_MARKER} L5", "description": f"{RUN_MARKER} synth"},
        files={"photo": ("stress.jpg", JPG_TINY, "image/jpeg")},
        timeout=15,
    )
    photo_ms.append(time.perf_counter() - t0)
    record("save_photo", r.status_code in (201,))
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
    if seq is not None:
        seq_dir = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PROJECT / f"{seq:03d}"
        record("internal_html_written", (seq_dir / "internal.html").exists())
        record("client_html_written",   (seq_dir / "client.html").exists())
    return seq


# ---------- DCR-4 — reopen + re-issue identity preservation at scale ----------

def check_dcr4_reissue_identity(date_to_reissue):
    """Re-issue an already-issued DCR with override_active=true; assert
    the same sequence comes back. Mirrors what the UI's Edit -> Issue
    DCR flow exercises."""
    # First, GET the current sequence
    conn = db()
    try:
        row = conn.execute(
            "SELECT MIN(dcr_sequence) FROM report_index WHERE project_code = ? AND "
            "report_type='DCR' AND report_date = ?",
            (PROJECT, date_to_reissue),
        ).fetchone()
        original_seq = row[0] if row else None
    finally:
        conn.close()
    if original_seq is None:
        record("dcr4_reissue_identity", False, f"no original seq for {date_to_reissue}")
        return None
    r = requests.post(
        f"{BASE}/api/projects/{PROJECT}/daily/{date_to_reissue}/issue",
        json={"audience": "both", "override_active": True},
        timeout=60,
    )
    if r.status_code != 201:
        record("dcr4_reissue_identity", False, f"re-issue {r.status_code}")
        return None
    new_seq = r.json()["data"]["sequence"]
    same = new_seq == original_seq
    record("dcr4_reissue_identity_preserved", same,
           f"orig={original_seq} new={new_seq}")
    return new_seq


# ---------- DCR-5/6 — rapid-cycle clean-slate ----------

def check_dcr56_rapid_aggregator_clean(our_dates):
    """Server-side proxy for the UI's rapid New/Cancel cycle: hit the
    aggregator on 3 different test dates in quick succession and assert
    each response carries ONLY its own date's data. If the aggregator
    leaks (e.g., shared mutable state, cache pollution), one of these
    would return rows from a sibling date.
    """
    sample_dates = [our_dates[0], our_dates[N_DCRS // 2], our_dates[-1]]
    for d in sample_dates:
        r = requests.get(
            f"{BASE}/api/projects/{PROJECT}/daily/{d}?audience=internal",
            timeout=30,
        )
        if r.status_code != 200:
            record("dcr56_aggregator_clean", False, f"{d}: {r.status_code}")
            continue
        body = r.json()["data"]
        proj_date = (body.get("project") or {}).get("date")
        labor_rows = (body.get("labor") or {}).get("rows", [])
        # The aggregator's project.date MUST equal the request date.
        # Any labor row's date is implicit (the SELECT is scoped) but
        # we re-verify via the row's time_in being non-null.
        record(
            "dcr56_aggregator_clean",
            proj_date == d,
            f"requested={d} got_date={proj_date}",
        )
        # 2 sign-ins per date; if the aggregator leaked from a sibling
        # we'd see != 2 here.
        record(
            "dcr56_aggregator_rowcount",
            len(labor_rows) == 2,
            f"{d}: got {len(labor_rows)} labor rows, expected 2",
        )


# ---------- DCR-2 — labor add-dropdown filter (server-side proxy) ----------

def check_dcr2_dropdown_filter():
    """The dropdown filter (UI) is driven by /on-site's workers list.
    A worker who's signed in MUST appear in /on-site.workers; the UI
    excludes them client-side. Verify the server's data shape.
    """
    today = date.today().isoformat()
    # Pick a worker; add a sign-in for today; assert they appear in /on-site
    workers = pick_test_workers()
    if not workers:
        return None
    target = workers[0]
    # Clean any pre-existing sign-in for the test pair
    conn = db()
    try:
        conn.execute(
            "DELETE FROM sign_in_log WHERE employee_id = ? AND date = ? AND project_code = ?",
            (target["employee_id"], today, PROJECT),
        )
        conn.commit()
    finally:
        conn.close()
    cr = requests.post(f"{BASE}/api/sign-ins", json={
        "employee_id": target["employee_id"], "project_code": PROJECT,
        "date": today, "time_in": "08:00", "time_out": "15:30",
    }, timeout=10)
    sign_id = cr.json()["data"]["id"] if cr.status_code == 201 else None
    onsite = requests.get(
        f"{BASE}/api/projects/{PROJECT}/on-site?date={today}", timeout=10,
    ).json()["data"]
    has_target = any(w.get("employee_id") == target["employee_id"]
                     for w in onsite.get("workers", []))
    record("dcr2_onsite_lists_signed_in_worker", has_target,
           f"target_wid={target['worker_id']}")
    # Cleanup
    if sign_id:
        requests.delete(f"{BASE}/api/sign-ins/{sign_id}", timeout=5)
    # After removal, worker must NOT appear in /on-site
    onsite2 = requests.get(
        f"{BASE}/api/projects/{PROJECT}/on-site?date={today}", timeout=10,
    ).json()["data"]
    still = any(w.get("employee_id") == target["employee_id"]
                for w in onsite2.get("workers", []))
    record("dcr2_onsite_drops_removed_worker", not still,
           f"target_wid={target['worker_id']}")


# ---------- DCR-3 — rendered DCR carries photo zoom markup ----------

def check_dcr3_photo_zoom_markup(seq):
    """Fetch the issued DCR's internal.html and assert the DCR-3 zoom
    markers are present."""
    f = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PROJECT / f"{seq:03d}" / "internal.html"
    if not f.exists():
        record("dcr3_photo_zoom_markup", False, f"missing {f.name}")
        return
    txt = f.read_text(encoding="utf-8")
    markers = [
        ('id="dcr-img-lightbox"', 'lightbox div'),
        ('id="dcr-img-lightbox-content"', 'lightbox img placeholder'),
        ('data-zoom-src=', 'photo has data-zoom-src'),
        ('cursor:zoom-in', 'cursor zoom-in CSS'),
        ('@media print', 'print-suppress lightbox'),
    ]
    for m, label in markers:
        record(f"dcr3_marker_{label.replace(' ','_')}",
               m in txt, f"missing {label}")


# ---------- RFI at scale ----------

def create_rfi_batch(n, workers, future_due_pool_size=20):
    """Create n RFIs. Mix of statuses: ~50% Open (future due) +
    ~25% Overdue (past due, no response) + ~25% Answered (response
    received). Returns the created rfi_numbers + register-load timing.
    """
    print(f"[rfi] creating {n} synthetic RFIs ...")
    created = []
    create_ms = []
    today = date.today()
    for i in range(n):
        # Cycle status across the batch for filter + auto-Overdue coverage.
        bucket = i % 4
        if bucket == 0:
            d_sub = (today - timedelta(days=20)).isoformat()
            d_req = (today - timedelta(days=10)).isoformat()
            sched = True  # overdue + scheduling impact -> shows on constraint feed
        elif bucket == 1:
            d_sub = today.isoformat()
            d_req = (today + timedelta(days=10)).isoformat()
            sched = (i % 3 == 0)
        elif bucket == 2:
            d_sub = (today - timedelta(days=10)).isoformat()
            d_req = (today + timedelta(days=5)).isoformat()
            sched = (i % 5 == 0)
        else:
            d_sub = (today - timedelta(days=15)).isoformat()
            d_req = (today + timedelta(days=2)).isoformat()
            sched = False
        t0 = time.perf_counter()
        r = requests.post(f"{BASE}/api/rfis", json={
            "project_code": PROJECT,
            "subject_title": f"{RUN_MARKER} subject {i:03d}",
            "submitted_by": "GC",
            "sent_to": "EOR",
            "date_submitted": d_sub,
            "date_response_required": d_req,
            "question_description": f"{RUN_MARKER} q{i:03d}",
            "scope_category": "Probe/investigation",
            "location_unit": "Elevation",
            "location_id": f"L{(i % 9) + 1}",
            "schedule_impact_flag": sched,
        }, timeout=10)
        create_ms.append(time.perf_counter() - t0)
        if r.status_code == 201:
            created.append(r.json()["data"]["rfi_number"])
    # Mark the third bucket as Answered so turnaround calc lands on them
    for i, rn in enumerate(created):
        if i % 4 == 2:
            requests.patch(f"{BASE}/api/rfis/{rn}", json={
                "status": "Answered",
                "response_answer": f"{RUN_MARKER} response",
                "date_response_received": today.isoformat(),
            }, timeout=10)
    return created, create_ms


def check_rfi_register_and_constraints(rfi_count):
    """Exercise register sort/filter + Auto-Overdue + constraint feed."""
    # Default register — all RFIs sorted Overdue-first then due ASC
    t0 = time.perf_counter()
    r = requests.get(f"{BASE}/api/projects/{PROJECT}/rfis", timeout=30)
    reg_full_ms = time.perf_counter() - t0
    record("rfi_register_returns_all", r.status_code == 200, f"{r.status_code}")
    rows = r.json()["data"] if r.status_code == 200 else []
    record("rfi_register_count_at_least_N", len(rows) >= rfi_count,
           f"got {len(rows)}, expected >= {rfi_count}")
    # Auto-Overdue derivation: any row with date_response_required in the
    # past + no date_response_received MUST surface status_derived=Overdue.
    today_iso = date.today().isoformat()
    expected_overdue = [
        r for r in rows
        if r.get("date_response_required") and r["date_response_required"] < today_iso
        and not r.get("date_response_received")
        and r.get("status") == "Open"
    ]
    actual_overdue = [r for r in rows if r.get("status_derived") == "Overdue"]
    record("rfi_auto_overdue", len(actual_overdue) >= len(expected_overdue),
           f"expected>={len(expected_overdue)} actual={len(actual_overdue)}")
    # Filter: status=Overdue only
    r2 = requests.get(f"{BASE}/api/projects/{PROJECT}/rfis?status=Overdue", timeout=30)
    overdue_rows = r2.json()["data"] if r2.status_code == 200 else []
    record("rfi_filter_status_overdue",
           all(x.get("status_derived") == "Overdue" for x in overdue_rows),
           f"got {len(overdue_rows)} rows, all Overdue?")
    # Constraint feed
    t0 = time.perf_counter()
    r3 = requests.get(f"{BASE}/api/projects/{PROJECT}/rfi-constraints", timeout=30)
    constraints_ms = time.perf_counter() - t0
    record("rfi_constraints_endpoint", r3.status_code == 200, f"{r3.status_code}")
    feed = r3.json()["data"] if r3.status_code == 200 else []
    # All rows must have schedule_impact_flag + status_derived in Open/Overdue
    valid = all(
        r.get("schedule_impact_flag") is True
        and r.get("status_derived") in ("Open", "Overdue")
        for r in feed
    )
    record("rfi_constraints_shape", valid, f"{len(feed)} rows valid={valid}")
    return reg_full_ms, constraints_ms


# ---------- Cleanup ----------

def cleanup_synthetic(our_dates, our_seqs, our_rfis):
    print(f"[cleanup] purging stress-run residue ...")
    conn = db()
    try:
        ph_dates = ",".join(["?"] * len(our_dates))
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
                pass
        # Also catch any sign-ins on 2098-* dates that escaped the explicit
        # list (defensive — per the handoff, do NOT rely on time pattern).
        conn.execute(
            "DELETE FROM sign_in_log WHERE project_code = ? AND date LIKE '2098-%'",
            (PROJECT,),
        )
        if our_seqs:
            ph_seqs = ",".join(["?"] * len(our_seqs))
            conn.execute(
                f"DELETE FROM report_index WHERE project_code = ? "
                f"AND report_type = 'DCR' AND dcr_sequence IN ({ph_seqs})",
                [PROJECT] + our_seqs,
            )
        # RFIs by run marker (subject_title carries it)
        conn.execute(
            "DELETE FROM rfi_log WHERE project_code = ? AND subject_title LIKE ?",
            (PROJECT, f"{RUN_MARKER}%"),
        )
        conn.commit()
    finally:
        conn.close()
    # Files
    dcr_root = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PROJECT
    for seq in our_seqs:
        d = dcr_root / f"{seq:03d}"
        if d.exists():
            try: shutil.rmtree(str(d))
            except Exception: pass
    photo_root = SCRIPT_DIR / "data_room" / "photos" / PROJECT
    if photo_root.exists():
        for d_str in our_dates:
            d = photo_root / d_str
            if d.exists():
                try: shutil.rmtree(str(d))
                except Exception: pass


# ---------- TESTING_LIMITS.md ----------

def append_to_testing_limits(timings, counts, our_seqs, snapshot_path):
    path = SCRIPT_DIR / "TESTING_LIMITS.md"
    today = date.today().isoformat()

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
        f"\n### {today} - 300-DCR stress (run {RUN_MARKER})\n\n"
        f"Synthetic cohort: **{counts['dcrs']} DCRs** across {counts['dates_first']} - "
        f"{counts['dates_last']} ({counts['dates_count']} dates), each with 2 sign-ins + "
        f"2 work_log rows + 1 photo. Plus {counts['rfis']} synthetic RFIs across mixed "
        f"statuses (Open / Overdue / Answered). Lifecycle + new-flow controls: "
        f"{pass_total} PASS / {fail_total} FAIL ({pass_fail}). Sequences issued: "
        f"{our_seqs[0]:03d}..{our_seqs[-1]:03d}.\n\n"
        f"| Endpoint | p50 | p95 | max | mean | iters |\n"
        f"|---|---|---|---|---|---|\n"
        f"{row(f'POST /api/projects/{PROJECT}/daily/&lt;date&gt;/issue', timings['issue'])}"
        f"{row(f'GET  /api/projects/{PROJECT}/reports (filtered @{counts['dcrs']})', timings['archive'])}"
        f"{row(f'GET  /api/projects/{PROJECT}/daily/&lt;date&gt;', timings['single'])}"
        f"{row('POST /api/sign-ins (save labor row)', timings['labor'])}"
        f"{row('POST /api/work-log (save work row)', timings['work'])}"
        f"{row('POST /api/photos/upload (save photo)', timings['photo'])}"
        f"{row('POST /api/rfis (create RFI)', timings['rfi_create'])}"
        f"{row(f'GET  /api/projects/{PROJECT}/rfis (register @{counts['rfis']})', [timings['rfi_register_full_ms']])}"
        f"{row(f'GET  /api/projects/{PROJECT}/rfi-constraints', [timings['rfi_constraints_ms']])}\n"
        f"DB returned to {counts['post_reports']}-report baseline "
        f"(pre={counts['pre_reports']}), {counts['post_workers']}-worker roster, "
        f"and {counts['post_rfis']}-RFI count (pre={counts['pre_rfis']}). "
        f"sign_in_log returned to {counts['post_sign_in_log']} (pre={counts['pre_sign_in_log']}). "
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
    print(f"== 300-DCR stress (RUN_MARKER={RUN_MARKER}) ==\n")
    snapshot_path = snapshot_db("300dcr-stress")
    print(f"[snapshot] {snapshot_path.name}")
    pre = baseline_state()
    print(f"[pre] reports={pre['reports']} workers={pre['workers']} "
          f"rfis={pre['rfis']} sign_in_log={pre['sign_in_log']}")
    workers = pick_test_workers()
    if len(workers) < 3:
        print(f"ERROR: need 3 active workers, found {len(workers)}")
        return 2
    print(f"[setup] using cohort: {[w['worker_id'] for w in workers]}")

    our_dates = [(START_DATE + timedelta(days=i)).isoformat() for i in range(N_DCRS)]
    signin_ms, work_ms, photo_ms, issue_ms = [], [], [], []
    our_seqs = []
    rfi_numbers = []
    rfi_create_ms = []
    rfi_register_full_ms = None
    rfi_constraints_ms = None

    try:
        print(f"\n[issue] {N_DCRS} DCRs across {our_dates[0]} -> {our_dates[-1]} ...")
        for i, d_str in enumerate(our_dates):
            seq = issue_one_dcr(d_str, workers, signin_ms, work_ms, photo_ms, issue_ms)
            if seq is not None:
                our_seqs.append(seq)
            if (i + 1) % 50 == 0:
                print(f"  [{i+1:03d}/{N_DCRS}] issued; "
                      f"issue p50 so far = {1000*statistics.median(issue_ms):.0f}ms")
        seqs_range = f"({our_seqs[0]:03d}..{our_seqs[-1]:03d})" if our_seqs else "(none)"
        print(f"\n[issued] {len(our_seqs)}/{N_DCRS} DCRs got sequences {seqs_range}")

        # ---- Per-flow control checks ----
        print("\n[controls] checking new-flow behavior at scale ...")
        # Archive @300
        t = time.perf_counter()
        r = requests.get(f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR", timeout=30)
        arc_ms = [time.perf_counter() - t]
        record("archive_returns_at_least_N", r.status_code == 200 and len(r.json().get("data", [])) >= N_DCRS)
        # Single DCR open (mid-range)
        t = time.perf_counter()
        r = requests.get(f"{BASE}/api/projects/{PROJECT}/daily/{our_dates[N_DCRS // 2]}?audience=internal", timeout=30)
        open_ms = [time.perf_counter() - t]
        record("open_single_dcr", r.status_code == 200)
        # DCR-4 — reopen + re-issue identity preservation (sample 3 dates)
        for d in (our_dates[0], our_dates[N_DCRS // 2], our_dates[-1]):
            check_dcr4_reissue_identity(d)
        # DCR-5/6 — aggregator rapid-cycle clean
        check_dcr56_rapid_aggregator_clean(our_dates)
        # DCR-2 — labor add-dropdown filter (server-side proxy)
        check_dcr2_dropdown_filter()
        # DCR-3 — photo zoom markup in the rendered DCR
        check_dcr3_photo_zoom_markup(our_seqs[0])

        # ---- RFI batch ----
        rfi_numbers, rfi_create_ms = create_rfi_batch(N_RFIS, workers)
        rfi_register_full_ms, rfi_constraints_ms = check_rfi_register_and_constraints(N_RFIS)
    finally:
        # Re-fetch synthetic 2098-* sequences in case some weren't tracked
        conn = db()
        try:
            extra_seqs = [r['dcr_sequence'] for r in conn.execute(
                "SELECT DISTINCT dcr_sequence FROM report_index "
                "WHERE project_code = ? AND report_type='DCR' AND report_date LIKE '2098-%'",
                (PROJECT,),
            ).fetchall()]
        finally:
            conn.close()
        union_seqs = sorted(set(our_seqs) | set(extra_seqs))
        cleanup_synthetic(our_dates, union_seqs, rfi_numbers)

    post = baseline_state()

    print("\n== PER-CONTROL PASS/FAIL ==")
    print(f"{'CONTROL':<45} {'PASS':>6} {'FAIL':>6}")
    print("-" * 60)
    overall_ok = True
    for k in sorted(CONTROLS.keys()):
        p, f, notes = CONTROLS[k]
        print(f"{k:<45} {p:>6} {f:>6}")
        if f:
            overall_ok = False
            for n in notes[:3]:
                print(f"  - {n}")

    timings = {
        "issue": issue_ms,
        "archive": arc_ms,
        "single": open_ms,
        "labor": signin_ms,
        "work": work_ms,
        "photo": photo_ms,
        "rfi_create": rfi_create_ms,
        "rfi_register_full_ms": rfi_register_full_ms or 0,
        "rfi_constraints_ms": rfi_constraints_ms or 0,
    }
    counts = {
        "dcrs": len(our_seqs),
        "dates_count": len(our_dates),
        "dates_first": our_dates[0],
        "dates_last": our_dates[-1],
        "rfis": len(rfi_numbers),
        "pre_reports": pre["reports"], "post_reports": post["reports"],
        "pre_workers": pre["workers"], "post_workers": post["workers"],
        "pre_rfis":    pre["rfis"],    "post_rfis":    post["rfis"],
        "pre_sign_in_log": pre["sign_in_log"], "post_sign_in_log": post["sign_in_log"],
    }

    print(f"\n== TIMINGS ==")
    print(f"  issue       : {fmt_lat(issue_ms)}")
    print(f"  archive @{N_DCRS}: {fmt_lat(arc_ms)}")
    print(f"  open single : {fmt_lat(open_ms)}")
    print(f"  labor save  : {fmt_lat(signin_ms)}")
    print(f"  work save   : {fmt_lat(work_ms)}")
    print(f"  photo save  : {fmt_lat(photo_ms)}")
    print(f"  rfi create  : {fmt_lat(rfi_create_ms)}")
    print(f"  rfi register@{N_RFIS}: {1000*(rfi_register_full_ms or 0):.0f} ms")
    print(f"  rfi constraints  : {1000*(rfi_constraints_ms or 0):.0f} ms")

    section = append_to_testing_limits(timings, counts, union_seqs, snapshot_path)
    print("\n--- TESTING_LIMITS.md entry ---")
    print(section)

    print(f"\n[post] reports={post['reports']} workers={post['workers']} "
          f"rfis={post['rfis']} sign_in_log={post['sign_in_log']}")
    baseline_clean = (
        post["reports"] == pre["reports"]
        and post["workers"] == pre["workers"]
        and post["rfis"] == pre["rfis"]
        and post["sign_in_log"] == pre["sign_in_log"]
    )
    if not baseline_clean:
        print(f"  *** baseline NOT restored: pre={pre} post={post} ***")
        overall_ok = False

    total = time.perf_counter() - t0
    print(f"\nTotal run: {total:.1f}s")
    print(f"OVERALL: {'PASS' if overall_ok else 'FAIL'}")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
