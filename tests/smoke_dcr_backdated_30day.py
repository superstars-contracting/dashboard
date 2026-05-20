#!/usr/bin/env python3
"""30-day backdated DCR volume smoke test with manual labor entry.

Exercises the backdated-labor path end-to-end: writes 2-4 sign_in_log rows
per day (via POST /api/sign-ins with both time_in and time_out, on a date
in the past), plus work_log + deliveries rows, then issues the DCR and
verifies the result. Then a full cleanup back to baseline.

Invoke manually:

  python tests/smoke_dcr_backdated_30day.py

Asserts per day:
  - sign-in POSTs all return 201 (uses real workers' employee_ids, never
    echoes names — PII discipline)
  - work_log / deliveries POSTs return 201
  - DCR issue returns 201
  - sequence == day_index (1..30)
  - display_id matches DCR-FR-BX-001-{seq:03d}
  - both internal.html and client.html exist with non-trivial size
  - sign_in_log has the expected count for the day (no double-counting)

End-of-run:
  - Archive lists 30 DCRs with consecutive sequences 1..30 and the right
    dates
  - Full cleanup wipes everything for those 30 dates back to baseline
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

D = Path(__file__).resolve().parent.parent
DB = D / "superstars.db"
LOG = D / "tests" / "_smoke_dcr_backdated_30day_server.log"
VENV_PY = D / "venv" / "Scripts" / "python.exe"

PROJECT = "FR-BX-001"
N_DAYS = 30
SEED = 7  # reproducible worker-selection randomness
TODAY = date.today()
START_DATE = TODAY - timedelta(days=N_DAYS)  # so range is [today-30, today-1]


def hit(method, path, body=None, timeout=15):
    url = "http://127.0.0.1:5050" + path
    data = None
    h = {}
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read().decode()
        except Exception:
            return e.code, ""
    except Exception as e:
        return None, repr(e)


PASS, FAIL = [], []
TIMING = []


def expect(label, cond, extra=""):
    line = f"{'PASS' if cond else 'FAIL'}: {label}" + (f" ({extra})" if extra else "")
    if cond:
        PASS.append(line)
    else:
        FAIL.append(line)
        print(line)


def cleanup_dates(dates_iso):
    """Wipe all FR-BX-001 data for the given dates + report_index for the
    project (since the smoke test owns all DCRs in this run)."""
    with sqlite3.connect(str(DB)) as c:
        placeholders = ",".join("?" * len(dates_iso))
        n_si = c.execute(
            f"DELETE FROM sign_in_log WHERE project_code=? AND date IN ({placeholders})",
            (PROJECT, *dates_iso)).rowcount
        n_w = c.execute(
            f"DELETE FROM work_log WHERE project_code=? AND date IN ({placeholders})",
            (PROJECT, *dates_iso)).rowcount
        n_d = c.execute(
            f"DELETE FROM deliveries WHERE project_code=? AND date IN ({placeholders})",
            (PROJECT, *dates_iso)).rowcount
        n_r = c.execute(
            "DELETE FROM report_index WHERE project_code=? AND report_type='DCR'",
            (PROJECT,)).rowcount
        c.commit()
    out_root = D / "data_room" / "reports" / "dcr" / PROJECT
    rmd = 0
    if out_root.exists():
        for child in list(out_root.iterdir()):
            if child.is_dir():
                shutil.rmtree(child)
                rmd += 1
    return n_si, n_w, n_d, n_r, rmd


def main():
    print(f"=== 30-day backdated DCR volume smoke ===")
    print(f"  project: {PROJECT}")
    print(f"  date range: {START_DATE.isoformat()} .. {(TODAY - timedelta(days=1)).isoformat()}  ({N_DAYS} days)")

    # Get the worker pool (employee_ids only — no names echoed)
    with sqlite3.connect(str(DB)) as c:
        worker_ids = [r[0] for r in c.execute(
            "SELECT employee_id FROM employees ORDER BY employee_id"
        ).fetchall()]
    if len(worker_ids) < 4:
        print(f"FATAL: need at least 4 workers, found {len(worker_ids)}")
        sys.exit(2)
    print(f"  worker pool: {len(worker_ids)} workers (e.g. {worker_ids[0]}..{worker_ids[-1]})")

    # Pre-clean: wipe any stale data for the date range
    target_dates = [(START_DATE + timedelta(days=i)).isoformat() for i in range(N_DAYS)]
    cleanup_dates(target_dates)
    print(f"  pre-clean done")

    # Start server
    LOG.parent.mkdir(parents=True, exist_ok=True)
    f = open(LOG, "w")
    proc = subprocess.Popen(
        [str(VENV_PY), "server.py"], cwd=str(D), stdout=f, stderr=subprocess.STDOUT
    )
    print(f"  started server pid={proc.pid}")
    try:
        for i in range(20):
            time.sleep(1)
            s, _ = hit("GET", "/")
            if s == 200:
                print(f"  server up after {i+1}s")
                break
            if proc.poll() is not None:
                print(f"  server DIED rc={proc.returncode}")
                sys.exit(2)
        else:
            print("  server did NOT come up")
            sys.exit(2)

        rng = random.Random(SEED)
        phase_start = time.time()

        for day_index in range(1, N_DAYS + 1):
            d = (START_DATE + timedelta(days=day_index - 1)).isoformat()
            iter_start = time.time()

            # 2-4 manual sign-ins with varied realistic times (worker-IDs only)
            crew_size = rng.randint(2, 4)
            crew = rng.sample(worker_ids, crew_size)
            sign_in_failures = 0
            for emp in crew:
                # Slight variations: 06:30-07:30 start, 15:00-16:30 end
                ti = f"0{rng.randint(6, 7)}:{rng.choice(['00', '15', '30', '45'])}"
                to_hour = rng.randint(15, 16)
                to_minute = rng.choice(['00', '15', '30', '45'])
                to = f"{to_hour}:{to_minute}"
                s, body = hit("POST", "/api/sign-ins", body={
                    "employee_id": emp,
                    "project_code": PROJECT,
                    "date": d,
                    "time_in": ti,
                    "time_out": to,
                })
                if s != 201:
                    sign_in_failures += 1
                    FAIL.append(f"day {day_index} ({d}): sign-in POST emp={emp} status={s} body={body[:140]}")

            # 1-2 work_log rows
            n_work = rng.randint(1, 2)
            for k in range(n_work):
                s, _ = hit("POST", "/api/work-log", body={
                    "project_code": PROJECT, "date": d,
                    "trade_area": f"area-{k}",
                    "location_elevation": f"L{(day_index % 12) + 1}",
                    "description": f"backdated smoke day {day_index} work {k}",
                })
                if s != 201:
                    FAIL.append(f"day {day_index}: work_log POST status={s}")

            # 1 delivery
            s, _ = hit("POST", "/api/deliveries", body={
                "project_code": PROJECT, "date": d,
                "time": "09:30",
                "material": f"material-d{day_index}",
                "qty": 1.0, "unit": "each",
                "supplier": "backdated-smoke-supplier",
            })
            if s != 201:
                FAIL.append(f"day {day_index}: deliveries POST status={s}")

            # Issue the DCR
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
                FAIL.append(f"day {day_index} ({d}): issue HTTP {s} body={body[:200]}")
                continue

            expected_display = f"DCR-{PROJECT}-{day_index:03d}"
            if dat.get("display_id") != expected_display:
                FAIL.append(f"day {day_index}: display_id={dat.get('display_id')!r} expected {expected_display!r}")
            if dat.get("sequence") != day_index:
                FAIL.append(f"day {day_index}: sequence={dat.get('sequence')!r} expected {day_index}")

            seq_dir = D / "data_room" / "reports" / "dcr" / PROJECT / f"{day_index:03d}"
            for aud in ("internal", "client"):
                f_html = seq_dir / f"{aud}.html"
                if not f_html.exists() or f_html.stat().st_size < 500:
                    FAIL.append(f"day {day_index}: {aud}.html missing/too small")

            # Verify the sign_in_log writes landed (count match — no PII)
            with sqlite3.connect(str(DB)) as c:
                actual_si = c.execute(
                    "SELECT COUNT(*) FROM sign_in_log WHERE project_code=? AND date=?",
                    (PROJECT, d)).fetchone()[0]
            expected_si = crew_size - sign_in_failures
            if actual_si != expected_si:
                FAIL.append(f"day {day_index}: sign_in_log count {actual_si} != expected {expected_si}")

            if day_index % 5 == 0 or day_index == N_DAYS:
                window = TIMING[-5:]
                avg = sum(window) / len(window)
                print(f"  day {day_index:2d}/{N_DAYS}  date={d}  crew={crew_size}  "
                      f"last 5 avg: {avg*1000:.0f}ms  total: {time.time()-phase_start:.1f}s")

        # End-of-run archive check
        s, body = hit("GET", f"/api/projects/{PROJECT}/reports")
        j = json.loads(body)
        archive = j.get("data") or []
        # Each DCR has two audience rows in report_index but the /reports
        # endpoint returns one row per audience too; that's the same shape
        # as the dashboard archive uses.
        seqs_seen = sorted({r["dcr_sequence"] for r in archive if r.get("dcr_sequence")})
        expect(f"archive lists {N_DAYS} distinct sequences",
               len(seqs_seen) == N_DAYS, f"got {len(seqs_seen)}")
        expect(f"archive sequences are exactly 1..{N_DAYS}",
               seqs_seen == list(range(1, N_DAYS + 1)),
               f"got {seqs_seen[:5]}..{seqs_seen[-5:]}")

        # All issuance asserts → pass count
        expect(f"all {N_DAYS} day-iterations succeeded",
               not any("issue HTTP" in x for x in FAIL),
               f"{len([x for x in FAIL if 'issue HTTP' in x])} failed")
    finally:
        # Cleanup phase — always runs
        print(f"\n=== Cleanup ===")
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=4)
        f.close()
        n_si, n_w, n_d, n_r, n_rmd = cleanup_dates(target_dates)
        print(f"  removed: sign_ins={n_si}, work_log={n_w}, deliveries={n_d}, "
              f"report_index={n_r}, seq dirs={n_rmd}")

        # Verify baseline
        with sqlite3.connect(str(DB)) as c:
            for tbl, dates_filter in [
                ("sign_in_log", f"date IN ({','.join('?'*len(target_dates))})"),
                ("work_log",    f"date IN ({','.join('?'*len(target_dates))})"),
                ("deliveries",  f"date IN ({','.join('?'*len(target_dates))})"),
                ("report_index", "1=1"),
            ]:
                params = (PROJECT, *target_dates) if dates_filter != "1=1" else (PROJECT,)
                n = c.execute(
                    f"SELECT COUNT(*) FROM {tbl} WHERE project_code=? AND {dates_filter}",
                    params).fetchone()[0]
                expect(f"post-cleanup {tbl} for date range == 0", n == 0)
        out_root = D / "data_room" / "reports" / "dcr" / PROJECT
        leftover = []
        if out_root.exists():
            leftover = [c.name for c in out_root.iterdir() if c.is_dir()]
        expect("post-cleanup leftover seq dirs == 0", not leftover, f"{leftover}")

    # Summary
    print(f"\n=== Summary ===")
    if TIMING:
        chrono = list(TIMING)  # preserve chronological order before sorting
        srt = sorted(TIMING)
        p50 = srt[len(srt)//2]
        p95 = srt[int(len(srt)*0.95)] if len(srt) > 1 else srt[-1]
        max_t = srt[-1]
        first_half = sum(chrono[:len(chrono)//2]) / max(1, len(chrono)//2)
        second_half = sum(chrono[len(chrono)//2:]) / max(1, len(chrono) - len(chrono)//2)
        degradation_pct = ((second_half - first_half) / first_half * 100) if first_half > 0 else 0.0
        print(f"  timing: p50={p50*1000:.0f}ms  p95={p95*1000:.0f}ms  max={max_t*1000:.0f}ms  n={len(TIMING)}")
        print(f"  degradation: first half avg {first_half*1000:.0f}ms, "
              f"second half avg {second_half*1000:.0f}ms ({degradation_pct:+.1f}%)")
    print(f"  pass: {len(PASS)}, fail: {len(FAIL)}")
    if FAIL:
        print(f"  first 15 failures:")
        for x in FAIL[:15]:
            print(f"    - {x}")
        sys.exit(1)
    print(f"\n  ALL CLEAR — 30 backdated DCRs (with manual labor) issued + cleanup green.")
    sys.exit(0)


if __name__ == "__main__":
    main()
