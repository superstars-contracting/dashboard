"""#290 (Cloud M4) — SSC_TZ enforcement. The app's clock speaks Eastern even
when the host's clock speaks UTC.

The entire codebase derives "today" from Python's LOCAL clock (date.today(),
datetime.now() — the CLAUDE.md LOCAL-dates rule; dates are stored as TEXT and
never converted to UTC). That discipline is correct on the Eastern workstation
and silently wrong on a UTC cloud host: every datetime.now() after 8 PM Eastern
would land on tomorrow's date — the #74 bug class, resurrected at the process
level. Rather than touch hundreds of call sites, we move the PROCESS to the
operator's timezone before any of them run:

    SSC_TZ unset          -> no-op. The workstation today: host tz already local.
    SSC_TZ set, POSIX     -> os.environ["TZ"] = SSC_TZ; time.tzset(). From that
                             moment every localtime derivation in this process —
                             date.today(), datetime.now(), time.localtime(),
                             strftime — and in every CHILD process (env inherits)
                             is in SSC_TZ. Runs BEFORE any other app import.
    SSC_TZ set, Windows   -> no-op (time.tzset does not exist). Deliberately does
                             NOT write os.environ["TZ"]: the MSVC runtime parses
                             TZ in a pre-IANA format ("EST5EDT"), so a child
                             python.exe inheriting TZ=America/New_York would
                             misparse it and fall back to UTC — injecting the
                             exact bug this module exists to prevent. Windows
                             hosts must (and do) run with the OS clock already
                             set to Eastern.

Fail-fast contract (same doctrine as SSC_CHROMIUM_PATH in #288): on a POSIX
host an SSC_TZ value that does not resolve to a real IANA zone RAISES at boot
instead of letting glibc fall back to UTC silently. A typo'd zone on the cloud
host is a setup error to surface loudly, never a quiet UTC drift.

The Postgres side of the same enforcement lives in db_layer._PgConn: when
SSC_TZ is set, every PG session opens with TimeZone=<SSC_TZ> so the few
SQL-side CURRENT_TIMESTAMP audit stamps render in the same zone the app
writes (matching the workstation's dev PG, which inherits Eastern from the OS).

Guard: tests/smoke_tz_290.py (gate #36).
"""
from __future__ import annotations

import os
import time


def enforce() -> str:
    """Apply SSC_TZ to this process. Call before ANY other app import so no
    module-level date derivation runs on the host's default zone.

    Returns one of (for logging / the guard suite):
      "unset"     — SSC_TZ not set; nothing done (today's workstation behavior)
      "no-tzset"  — SSC_TZ set but the platform has no time.tzset (Windows);
                    nothing done, including no TZ env write (see module doc)
      "enforced"  — TZ exported + tzset() applied; local clock is now SSC_TZ

    Raises RuntimeError on a POSIX host when SSC_TZ names a zone the tz
    database cannot resolve (fail fast, never silent UTC).
    """
    tz = (os.environ.get("SSC_TZ") or "").strip()
    if not tz:
        return "unset"
    if not hasattr(time, "tzset"):
        return "no-tzset"
    # Validate BEFORE applying: glibc's tzset() silently falls back to UTC on
    # an unknown zone name — exactly the failure mode we must never inherit.
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(tz)
    except Exception as e:
        raise RuntimeError(
            f"SSC_TZ={tz!r} does not resolve to an IANA timezone on this host "
            f"({e.__class__.__name__}: {e}). Fix the env value (e.g. "
            "America/New_York) or install the tz database (tzdata)."
        ) from None
    os.environ["TZ"] = tz
    time.tzset()
    return "enforced"
