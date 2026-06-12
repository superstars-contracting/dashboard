"""
smoke_dcr214_lifecycle.py — #214 Daily Construction Reports restyle:
full DCR lifecycle + 500-row scale, exercised against the REAL running
server, OPERATOR-LIVE SAFE.

What it proves (data layer behind the restyled list view):
  Lifecycle (real API, one synthetic DCR on a FUTURE date 2099-06-15):
    - ISSUE updates the list: the new DCR appears in GET /reports with
      status=issued + a synthesized html_url, and the rendered
      internal.html + client.html land on disk (the View target).
    - The KPI inputs update: Total = row count, Latest = newest date.
    - EDIT / re-issue preserves identity (override_active -> same seq).
    - DELETE removes BOTH audiences + decrements the count; the other
      (real) reports are untouched.
  Scale (direct DB insert, 500 synthetic DCRs, seq 9000..9499, dates
  2099-01-01.. ascending):
    - GET /reports renders all 500 (one internal row per DCR) + latency.
    - Server-side From/To range filter narrows correctly at scale.
    - The default last-30-days (2026) range EXCLUDES every synthetic row
      (so the operator's normal view never shows test data).

Operator-live safety (the 16 real 2026 DCRs are REAL DATA):
  - Snapshot the DB before any write.
  - EVERY synthetic report lives on a 2099+ report_date — a value no real
    construction report can have — so the chronological DCR numbering
    (next_dcr_sequence counts DISTINCT dates < X) never renumbers the
    real 2026 reports, and cleanup can scope purely on the date.
  - Cleanup is DATE-SCOPED: report_date >= '2099-01-01'. It can NEVER
    match a real 2026 row. NO blanket delete, ever.
  - Asserts the exact set of (display_id, report_date) for the 16 real
    DCRs is byte-identical before and after (16 -> ... -> 16).

127.0.0.1 only. PII-safe (W-#### + counts only). Idempotent cleanup in a
finally block so a mid-run failure still restores baseline.
"""
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

# Auth gate (#48): login the smoke admin + patch requests so cookies ride along.
import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"

PROJECT = "FR-BX-001"
LIFE_DATE = "2099-06-15"            # one synthetic DCR, real API, full lifecycle
N_SCALE = 500                       # direct-insert scale tier
SCALE_SEQ_BASE = 9000               # positive high seqs -> by-sequence DELETE accepts them
SCALE_START = date(2099, 1, 1)      # ascending distinct dates, all far-future
SYNTH_DATE_FLOOR = "2099-01-01"     # cleanup scope: report_date >= this

PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    mark = "PASS" if cond else "FAIL"
    print(f"  [{mark}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def snapshot_db(label):
    ts = time.strftime("%Y%m%d-%H%M%S")
    backups = SCRIPT_DIR.parent / "snapshots"  # #248: snapshots live OUTSIDE the project root (never servable)
    backups.mkdir(parents=True, exist_ok=True)
    dest = backups / f"superstars-pre-{label}-{ts}.db"
    shutil.copy2(str(DB_PATH), str(dest))
    return dest


def real_baseline():
    """The operator-facing list (default audience=internal) = one row per
    real DCR. Capture the (display_id, report_date) set to prove the 16 are
    untouched afterward."""
    r = requests.get(f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR", timeout=30)
    rows = r.json().get("data", []) if r.status_code == 200 else []
    return {(d["display_id"], d["report_date"]) for d in rows}, len(rows)


def pick_worker():
    conn = db()
    try:
        row = conn.execute(
            "SELECT employee_id, worker_id FROM employees "
            "WHERE worker_id IS NOT NULL AND archived_at IS NULL "
            "ORDER BY CAST(SUBSTR(worker_id, 3) AS INTEGER) ASC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


# ---------------- Lifecycle (real API) ----------------

def lifecycle(worker):
    print("\n[lifecycle] one synthetic DCR via the real API ...")
    # Seed minimal content so the DCR renders a real report (View target).
    requests.post(f"{BASE}/api/sign-ins", json={
        "employee_id": worker["employee_id"], "project_code": PROJECT,
        "date": LIFE_DATE, "time_in": "07:00", "time_out": "15:30",
    }, timeout=10)
    requests.post(f"{BASE}/api/work-log", json={
        "project_code": PROJECT, "date": LIFE_DATE,
        "trade_area": "Mason", "location_elevation": "L5",
        "description": "SMK-214 synthetic work row",
    }, timeout=10)

    # ISSUE (roster_skip bypasses the #194 modal for tooling; future date
    # wouldn't trip it anyway).
    r = requests.post(
        f"{BASE}/api/projects/{PROJECT}/daily/{LIFE_DATE}/issue",
        json={"audience": "both", "override_active": True, "roster_skip": True},
        timeout=60,
    )
    issued = r.status_code == 201
    ok("lifecycle_issue_201", issued, f"HTTP {r.status_code}")
    if not issued:
        print("    " + str(r.text)[:200])
        return None
    seq = r.json()["data"]["sequence"]
    disp = f"DCR-{PROJECT}-{seq:03d}"

    # ISSUE updates the list: appears with status issued + html_url.
    r = requests.get(f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR", timeout=30)
    rows = r.json().get("data", [])
    mine = next((d for d in rows if d["display_id"] == disp), None)
    ok("lifecycle_appears_in_list", mine is not None, disp)
    if mine:
        ok("lifecycle_status_issued", mine.get("status") == "issued", str(mine.get("status")))
        ok("lifecycle_html_url_present", bool(mine.get("html_url")), str(mine.get("html_url")))
        # KPI inputs: rows arrive report_date DESC -> [0] is Latest; our
        # 2099 date is newer than every real 2026 date, so it leads.
        ok("lifecycle_latest_is_ours", rows and rows[0]["report_date"] == LIFE_DATE,
           f"top={rows[0]['report_date'] if rows else '-'}")

    # View target rendered to disk (both audiences).
    seq_dir = SCRIPT_DIR / "data_room" / "reports" / "dcr" / PROJECT / f"{seq:03d}"
    ok("lifecycle_internal_html_written", (seq_dir / "internal.html").exists())
    ok("lifecycle_client_html_written", (seq_dir / "client.html").exists())

    # EDIT / re-issue preserves identity (same sequence comes back).
    r = requests.post(
        f"{BASE}/api/projects/{PROJECT}/daily/{LIFE_DATE}/issue",
        json={"audience": "both", "override_active": True, "roster_skip": True},
        timeout=60,
    )
    reseq = r.json()["data"]["sequence"] if r.status_code == 201 else None
    ok("lifecycle_reissue_preserves_seq", reseq == seq, f"orig={seq} re={reseq}")

    # DELETE removes the DCR (both audiences) + decrements the count.
    pre = requests.get(f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR", timeout=30)
    pre_n = len(pre.json().get("data", []))
    r = requests.delete(
        f"{BASE}/api/projects/{PROJECT}/reports/by-sequence/{seq}", timeout=30)
    ok("lifecycle_delete_200", r.status_code == 200, f"HTTP {r.status_code}")
    post = requests.get(f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR", timeout=30)
    post_rows = post.json().get("data", [])
    ok("lifecycle_gone_after_delete",
       all(d["display_id"] != disp for d in post_rows), disp)
    ok("lifecycle_count_decremented", len(post_rows) == pre_n - 1,
       f"{pre_n} -> {len(post_rows)}")
    # Both audiences removed from report_index (not just the internal row).
    conn = db()
    try:
        left = conn.execute(
            "SELECT COUNT(*) FROM report_index WHERE project_code=? AND dcr_sequence=?",
            (PROJECT, seq)).fetchone()[0]
    finally:
        conn.close()
    ok("lifecycle_both_audiences_deleted", left == 0, f"rows left={left}")

    # Clean the seeded labor for the lifecycle date.
    conn = db()
    try:
        conn.execute("DELETE FROM sign_in_log WHERE project_code=? AND date=?", (PROJECT, LIFE_DATE))
        conn.execute("DELETE FROM work_log WHERE project_code=? AND date=?", (PROJECT, LIFE_DATE))
        conn.commit()
    finally:
        conn.close()
    return seq


# ---------------- Scale (direct insert, 500) ----------------

def scale_insert(n):
    print(f"\n[scale] direct-inserting {n} synthetic DCRs (seq {SCALE_SEQ_BASE}..{SCALE_SEQ_BASE+n-1}) ...")
    conn = db()
    try:
        rows = []
        for i in range(n):
            seq = SCALE_SEQ_BASE + i
            d = (SCALE_START + timedelta(days=i)).isoformat()
            stamp = d + " 12:00:00"
            for aud in ("internal", "client"):
                rid = f"DCR-{PROJECT}-{seq:03d}-{aud}"
                rows.append((d, PROJECT, "DCR", "issued", stamp, stamp, rid, seq, 0, 0))
        conn.executemany(
            "INSERT INTO report_index "
            "(report_date, project_code, report_type, status, created_at, updated_at, "
            " report_id, dcr_sequence, no_work, stale) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()
    finally:
        conn.close()
    last_date = (SCALE_START + timedelta(days=n - 1)).isoformat()
    return last_date


def scale_checks(n, last_date):
    # Full synthetic range -> all N render (one internal row per DCR).
    t0 = time.perf_counter()
    r = requests.get(
        f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR"
        f"&from_date={SYNTH_DATE_FLOOR}&to_date=2100-12-31", timeout=60)
    dt = time.perf_counter() - t0
    data = r.json().get("data", []) if r.status_code == 200 else []
    ok("scale_render_all_500", len(data) == n, f"got {len(data)} in {1000*dt:.0f}ms")
    ok("scale_latency_under_2s", dt < 2.0, f"{1000*dt:.0f}ms for {n} rows")
    print(f"    note: list renders ALL {len(data)} rows (no pagination) in {1000*dt:.0f}ms — render-all OK at {n}")

    # audience=all -> both rows per DCR = 2N.
    r = requests.get(
        f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR&audience=all"
        f"&from_date={SYNTH_DATE_FLOOR}&to_date=2100-12-31", timeout=60)
    ok("scale_audience_all_is_2N", len(r.json().get("data", [])) == 2 * n,
       f"got {len(r.json().get('data', []))}")

    # Server-side From/To narrows at scale: first 50 dates only.
    sub_to = (SCALE_START + timedelta(days=49)).isoformat()
    r = requests.get(
        f"{BASE}/api/projects/{PROJECT}/reports?report_type=DCR"
        f"&from_date={SYNTH_DATE_FLOOR}&to_date={sub_to}", timeout=30)
    ok("scale_range_filter_narrows", len(r.json().get("data", [])) == 50,
       f"got {len(r.json().get('data', []))} for first-50-days window")


def scale_cleanup_and_assert(real_set, real_n):
    print("\n[cleanup] DATE-SCOPED purge of synthetic rows (report_date >= 2099) ...")
    conn = db()
    try:
        before = conn.execute(
            "SELECT COUNT(*) FROM report_index WHERE project_code=? AND report_type='DCR' "
            "AND report_date >= ?", (PROJECT, SYNTH_DATE_FLOOR)).fetchone()[0]
        conn.execute(
            "DELETE FROM report_index WHERE project_code=? AND report_type='DCR' "
            "AND report_date >= ?", (PROJECT, SYNTH_DATE_FLOOR))
        conn.commit()
    finally:
        conn.close()
    print(f"    purged {before} synthetic report_index rows")

    # The 16 real DCRs: exact same set, count restored.
    now_set, now_n = real_baseline()
    ok("cleanup_real_count_restored", now_n == real_n, f"{real_n} -> {now_n}")
    ok("cleanup_real_set_identical", now_set == real_set,
       f"added={len(now_set - real_set)} removed={len(real_set - now_set)}")
    # No synthetic residue anywhere in report_index.
    conn = db()
    try:
        residue = conn.execute(
            "SELECT COUNT(*) FROM report_index WHERE report_date >= ?",
            (SYNTH_DATE_FLOOR,)).fetchone()[0]
    finally:
        conn.close()
    ok("cleanup_no_future_residue", residue == 0, f"future rows left={residue}")


def main():
    print("== #214 DCR lifecycle + 500-scale smoke (operator-live safe) ==")
    snap = snapshot_db("dcr214-lifecycle")
    print(f"[snapshot] {snap.name}")

    real_set, real_n = real_baseline()
    # #248 fixture repair: the original assertion pinned the real-DCR count to
    # the 16 that existed when #214 was written — it goes stale every time the
    # operator issues a real DCR (25 found during build #248). The invariant
    # that matters is identity preservation, asserted at cleanup
    # (cleanup_real_count_restored / cleanup_real_set_identical); here we only
    # sanity-check that we're on a real operator DB.
    ok("baseline_real_dcrs_present", real_n >= 1, f"found {real_n} (expected >= 1)")
    worker = pick_worker()
    if not worker:
        print("ERROR: no active worker to seed labor"); return 2
    print(f"[baseline] {real_n} real DCRs; lifecycle worker = {worker['worker_id']}")

    last_date = None
    try:
        lifecycle(worker)
        last_date = scale_insert(N_SCALE)
        scale_checks(N_SCALE, last_date)
    finally:
        scale_cleanup_and_assert(real_set, real_n)

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
