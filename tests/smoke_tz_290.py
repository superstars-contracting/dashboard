"""#290 (Cloud M4) guard — SSC_TZ enforcement: the app's "today" is Eastern
regardless of the host clock.

What this proves:
  1. ssc_tz.enforce() contract: unset -> no-op; set on a no-tzset platform
     (Windows) -> no-op that also never exports TZ (a child python.exe on
     Windows would misparse an IANA TZ value and fall back to UTC — the module
     must not plant that trap); set on POSIX -> TZ exported + tzset applied.
  2. THE PLANTED EVENING BOUNDARY: instants late in the Eastern evening
     (23:30 local = 03:30Z next day, both winter and summer) where the UTC
     calendar date != the Eastern calendar date. An enforced process's
     todayLocal-equivalents (date.fromtimestamp / datetime.fromtimestamp)
     must return the EASTERN date for those instants.
       * POSIX: the child runs with TZ=UTC pre-set (a simulated UTC cloud
         host); enforce() must flip it to Eastern. A CONTROL child with
         enforcement skipped must return the UTC date — proving this suite
         can fail.
       * Windows: tzset does not exist, so enforcement no-ops and the child
         reports the WORKSTATION zone. This workstation is Eastern — that IS
         production's timezone correctness on Windows, so the assertion
         still holds. On a non-Eastern Windows box this suite goes red, and
         that is a true alarm, not a false one: unenforced hosts must keep
         their OS clock on Eastern.
  3. Fail-fast: SSC_TZ naming a nonexistent zone RAISES at boot on POSIX
     (never a silent UTC fallback); on Windows it stays a no-op.
  4. Boot order: server.py calls ssc_tz.enforce() BEFORE the first flask
     import — no module-level date derivation can precede enforcement.
  5. The live gate server's /api/today equals Eastern today (midnight-safe
     double-read).
  6. db_layer: with SSC_TZ set, a Postgres session opens with
     TimeZone=<SSC_TZ> (skipped on the SQLite backend, where the same env
     must simply not break connect()).

Runs on both backends; on Windows the POSIX-only branches print SKIP and the
platform no-op contract is asserted instead (the spec: tzset absent -> no-op,
unset -> today's behavior).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5434")
ZONE = "America/New_York"
EASTERN = ZoneInfo(ZONE)

# The planted boundary instants: 23:30 Eastern = 03:30Z the NEXT UTC day.
# One in EST (winter, UTC-5) and one in EDT (summer, UTC-4) so a DST-side
# mistake cannot slip through. Fixed instants, not now()-derived — the
# boundary is planted, never dependent on when the gate happens to run.
PLANTED = [
    # (utc_iso, expected_eastern_date, utc_date)
    ("2026-01-15T03:30:00+00:00", "2026-01-14", "2026-01-15"),  # 22:30 EST
    ("2026-07-15T03:30:00+00:00", "2026-07-14", "2026-07-15"),  # 23:30 EDT
]

HAS_TZSET = hasattr(time, "tzset")

failures = []


def expect(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"  {tag}  {name}" + (f"  [{detail}]" if (detail and not cond) else ""))
    if not cond:
        failures.append(name)


# One child script serves every subprocess probe: enforce (or not, per env
# knob), then report what the process-local clock says about the planted
# instants. JSON on stdout; enforcement errors escape as a nonzero exit.
CHILD = r"""
import json, os, sys
from datetime import date, datetime
mode = "skipped"
if os.environ.get("TZCHILD_ENFORCE") == "1":
    import ssc_tz
    mode = ssc_tz.enforce()
stamps = [float(a) for a in os.environ["TZCHILD_TS"].split(",")]
print(json.dumps({
    "mode": mode,
    "tz_env": os.environ.get("TZ"),
    "dates": [date.fromtimestamp(t).isoformat() for t in stamps],
    "dates_dt": [datetime.fromtimestamp(t).date().isoformat() for t in stamps],
    "today": date.today().isoformat(),
}))
"""


def run_child(enforce: bool, ssc_tz_value=None, preset_utc=False):
    env = {k: v for k, v in os.environ.items() if k not in ("SSC_TZ", "TZ")}
    if ssc_tz_value is not None:
        env["SSC_TZ"] = ssc_tz_value
    if preset_utc:
        env["TZ"] = "UTC"          # simulated UTC cloud host (POSIX only)
    env["TZCHILD_ENFORCE"] = "1" if enforce else "0"
    env["TZCHILD_TS"] = ",".join(
        str(datetime.fromisoformat(u).timestamp()) for u, _, _ in PLANTED)
    p = subprocess.run([sys.executable, "-c", CHILD], capture_output=True,
                       text=True, cwd=str(SCRIPT_DIR), env=env, timeout=60)
    if p.returncode != 0:
        return None, (p.stderr or p.stdout or "").strip()[-400:]
    return json.loads(p.stdout.strip().splitlines()[-1]), None


def main() -> int:
    print(f"=== smoke_tz_290: SSC_TZ enforcement (platform tzset={HAS_TZSET}) ===")

    # ---- 1. the planted boundary is REAL (pure zoneinfo math, no env) ----
    for utc_iso, eastern_d, utc_d in PLANTED:
        inst = datetime.fromisoformat(utc_iso)
        expect(f"planted {utc_iso}: UTC date != Eastern date",
               inst.astimezone(timezone.utc).date().isoformat() == utc_d
               and inst.astimezone(EASTERN).date().isoformat() == eastern_d
               and utc_d != eastern_d)

    # ---- 2. enforce() contract: unset -> no-op ----
    out, err = run_child(enforce=True, ssc_tz_value=None)
    expect("SSC_TZ unset -> enforce() returns 'unset'",
           out is not None and out["mode"] == "unset", str(err))
    expect("SSC_TZ unset -> TZ env untouched",
           out is not None and out["tz_env"] is None)

    # ---- 3. enforce() with SSC_TZ set — the platform-split contract ----
    out, err = run_child(enforce=True, ssc_tz_value=ZONE, preset_utc=HAS_TZSET)
    if HAS_TZSET:
        expect("POSIX: enforce() returns 'enforced'",
               out is not None and out["mode"] == "enforced", str(err))
        expect("POSIX: TZ env exported", out is not None and out["tz_env"] == ZONE)
    else:
        expect("Windows: enforce() returns 'no-tzset' (no-op)",
               out is not None and out["mode"] == "no-tzset", str(err))
        expect("Windows: TZ env NOT exported (child-poisoning guard)",
               out is not None and out["tz_env"] is None)

    # Either way: the enforced process's local-date derivations return the
    # EASTERN date for both planted boundary instants (see module doc for
    # why this also holds on the unenforced-but-Eastern Windows host).
    if out is not None:
        for i, (utc_iso, eastern_d, _u) in enumerate(PLANTED):
            expect(f"enforced process: {utc_iso} -> local date {eastern_d}",
                   out["dates"][i] == eastern_d and out["dates_dt"][i] == eastern_d,
                   f"got {out['dates'][i]}/{out['dates_dt'][i]}")

    # ---- 4. CONTROL: without enforcement the UTC host stays UTC (POSIX) ----
    if HAS_TZSET:
        ctrl, err = run_child(enforce=False, ssc_tz_value=ZONE, preset_utc=True)
        expect("POSIX control: unenforced UTC host reports the UTC date "
               "(this suite can fail)",
               ctrl is not None and ctrl["dates"] == [u for _, _, u in PLANTED],
               str(err))
    else:
        print("  SKIP  POSIX control (no tzset on this platform)")
        ctrl, err = run_child(enforce=False, ssc_tz_value=ZONE)
        expect("Windows control: enforcement changes nothing (no-op == skip)",
               ctrl is not None and out is not None and ctrl["dates"] == out["dates"],
               str(err))

    # ---- 5. fail-fast on an unresolvable zone ----
    out2, err2 = run_child(enforce=True, ssc_tz_value="Not/AZone")
    if HAS_TZSET:
        expect("POSIX: SSC_TZ=Not/AZone raises at boot (no silent UTC)",
               out2 is None and "SSC_TZ" in (err2 or ""))
    else:
        expect("Windows: SSC_TZ=Not/AZone stays a no-op",
               out2 is not None and out2["mode"] == "no-tzset", str(err2))

    # ---- 6. boot order: enforcement precedes the first flask import ----
    src = (SCRIPT_DIR / "server.py").read_text(encoding="utf-8", errors="replace")
    call_at = src.find("ssc_tz.enforce()")
    flask_at = src.find("from flask import")
    expect("server.py calls ssc_tz.enforce() before importing flask",
           0 <= call_at < flask_at)

    # ---- 7. live server: /api/today == Eastern today (midnight-safe) ----
    got = expected = None
    for _ in range(2):
        expected_before = datetime.now(EASTERN).date().isoformat()
        r = requests.get(f"{BASE}/api/today", timeout=10)
        got = (r.json().get("data") or {}).get("date") if r.status_code == 200 else None
        expected_after = datetime.now(EASTERN).date().isoformat()
        if expected_before == expected_after:
            expected = expected_before
            break                      # no midnight rollover mid-probe
    expect("live /api/today returns Eastern today",
           got is not None and got == expected, f"got {got} want {expected}")

    # ---- 8. db_layer: PG session TimeZone rides SSC_TZ ----
    import db_layer
    if db_layer.is_postgres():
        saved = os.environ.get("SSC_TZ")
        os.environ["SSC_TZ"] = ZONE
        try:
            conn = db_layer.connect()
            row = conn.execute("SELECT current_setting('TimeZone')").fetchone()
            conn.close()
            expect("PG session opens with TimeZone=SSC_TZ", row is not None and row[0] == ZONE,
                   f"got {row and row[0]}")
        finally:
            if saved is None:
                os.environ.pop("SSC_TZ", None)
            else:
                os.environ["SSC_TZ"] = saved
    else:
        saved = os.environ.get("SSC_TZ")
        os.environ["SSC_TZ"] = ZONE
        try:
            conn = db_layer.connect()
            one = conn.execute("SELECT 1").fetchone()
            conn.close()
            expect("SQLite backend: SSC_TZ set does not disturb connect()",
                   one is not None and one[0] == 1)
        finally:
            if saved is None:
                os.environ.pop("SSC_TZ", None)
            else:
                os.environ["SSC_TZ"] = saved

    print(f"\n=== smoke_tz_290: {'ALL GREEN' if not failures else f'{len(failures)} FAILURE(S)'} ===")
    for f in failures:
        print(f"  FAILED: {f}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
