#!/usr/bin/env python3
"""Add the stale + stale_marked_at columns to report_index. Idempotent.

Also seeds stale=1 for any DCR whose rendered internal.html disagrees
with current sign_in_log — so the existing drift the operator already
introduced shows up the moment the schema lands.
"""
import re
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_dcr_stale.sql"
REPORTS_ROOT = SCRIPT_DIR / "data_room" / "reports" / "dcr"

ROW_RE = re.compile(
    r'<tr><td>\d+</td><td class="wid">([^<]+)</td><td>([^<]+)</td>'
    r'<td>([^<]*)</td><td class="num">([^<]*)</td><td class="num">([^<]*)</td>'
    r'<td class="num">([^<]*)</td></tr>',
    re.IGNORECASE
)


def split_statements(sql_text):
    cleaned = []
    for line in sql_text.splitlines():
        if "--" in line:
            line = line[:line.index("--")]
        cleaned.append(line)
    text = "\n".join(cleaned)
    out, buf = [], []
    for ch in text:
        buf.append(ch)
        if ch == ";":
            s = "".join(buf).strip()
            if s and s != ";":
                out.append(s)
            buf = []
    return out


def issued_labor_wids(html_path):
    if not html_path.exists():
        return None
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    wids = set()
    for m in ROW_RE.finditer(html):
        wid = m.group(1).strip()
        if wid and wid != "—":
            wids.add(wid)
    return wids


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.row_factory = sqlite3.Row

    # ---- 1) Schema ALTERs (idempotent) ----
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "duplicate column" in msg or "already exists" in msg:
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    conn.commit()

    # ---- 2) Seed stale flag from existing drift ----
    # For every issued DCR, parse the rendered internal.html and compare
    # against live sign_in_log. Set stale=1 where they disagree.
    dcrs = conn.execute(
        "SELECT DISTINCT project_code, report_date, dcr_sequence "
        "FROM report_index WHERE report_type='DCR' AND dcr_sequence IS NOT NULL "
        "ORDER BY project_code, dcr_sequence"
    ).fetchall()
    flagged = 0
    examined = 0
    for r in dcrs:
        pcode = r["project_code"]; date = r["report_date"]; seq = r["dcr_sequence"]
        f = REPORTS_ROOT / pcode / f"{seq:03d}" / "internal.html"
        issued = issued_labor_wids(f)
        if issued is None:
            continue  # no rendered file, skip
        examined += 1
        live_rows = conn.execute(
            "SELECT e.worker_id FROM sign_in_log s "
            "LEFT JOIN employees e ON e.employee_id = s.employee_id "
            "WHERE s.project_code = ? AND s.date = ?",
            (pcode, date),
        ).fetchall()
        live = {row["worker_id"] for row in live_rows if row["worker_id"]}
        if issued != live:
            conn.execute(
                "UPDATE report_index SET stale = 1, stale_marked_at = CURRENT_TIMESTAMP "
                "WHERE project_code = ? AND report_date = ? AND report_type='DCR'",
                (pcode, date),
            )
            flagged += 1
    conn.commit()

    print(f"[dcr-stale] schema: applied={applied} skipped={skipped} failed={failed}")
    print(f"[dcr-stale] examined {examined} issued DCRs; flagged {flagged} as stale")
    for r in conn.execute(
        "SELECT DISTINCT project_code, report_date, dcr_sequence, stale "
        "FROM report_index WHERE report_type='DCR' AND stale=1 "
        "ORDER BY project_code, report_date"
    ):
        print(f"  STALE: {r['project_code']} {r['report_date']} seq={r['dcr_sequence']}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
