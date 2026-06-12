"""#171 — Ensure W-0001..W-0012 have active CoFs with the new Arun Mal /
#7652 rigger info. Per-worker commit so partial failures don't lose work.

Action per worker:
  - REFRESH path (already has an active 'issued' CoF):
      UPDATE rigger_name_snapshot + rigger_license_snapshot + issued_by
      + issuer_license. Preserve issued_date + expires_date. Re-render
      the static HTML at html_export_path. Audit-log
      action='cof_metadata_refresh'.
  - ISSUE path (no active CoF, prereq cert on file):
      cof_issuer.issue_cof() with today's date and the new default rigger.
      Audit-log action='cof_issue'.
  - FORCE-ISSUE path (no active CoF, no prereq cert):
      Per task #144 eligibility-override policy: issue an admin-overridden
      CoF directly via INSERT. 1-year expiry from today. Audit-log
      action='cof_issue_override' with note explaining the operator
      override and the missing prereq.

PII discipline: W-#### + counts + hashes only. The audit JSON in the
gated DB carries the rigger fields and the prereq reason (no names,
no PII).
"""
import hashlib
import json
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

import jinja2

SCRIPT_DIR = Path(r'C:\Users\SSC-Admin\Superstars\dashboard')
sys.path.insert(0, str(SCRIPT_DIR))

from worker_rates import log_audit  # noqa: E402
from cof_issuer import (  # noqa: E402
    issue_cof,
    has_valid_prerequisite,
    get_default_rigger_for_project,
    card_number_for_employee,
    _next_cof_revision,
)

DB = SCRIPT_DIR / "superstars.db"
TARGET_WORKERS = [f"W-{i:04d}" for i in range(1, 13)]
NEW_RIGGER_NAME = "Arun Mal"
NEW_RIGGER_LICENSE = "7652"
ACTOR_ROLE = "admin"
TODAY = date.today().isoformat()
OVERRIDE_EXPIRY = (date.today() + timedelta(days=365)).isoformat()


def _fmt_mdy(d):
    if not d:
        return ""
    try:
        y, m, dd = d[:10].split("-")
        return f"{m}-{dd}-{y}"
    except Exception:
        return d or ""


def file_hash(p):
    if not p.exists():
        return None
    return hashlib.sha256(p.read_bytes()).hexdigest()[:12]


def rerender_static_html(emp_id, card_row):
    """Re-render data_room/credentials/cof/<emp_id>.html using current
    snapshot fields. Returns (pre_hash, post_hash) or None on failure."""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        emp = conn.execute(
            "SELECT name, trade, pin, face_image_path FROM employees "
            "WHERE employee_id = ?",
            (card_row["employee_id"],),
        ).fetchone()
    finally:
        conn.close()
    if not emp:
        return None
    photo_url = ""
    snap = card_row["photo_snapshot_path"]
    if snap:
        full = SCRIPT_DIR / snap.lstrip("/")
        if full.exists():
            # #248 — artifacts are served by the gated /project-files/ route
            photo_url = "/project-files/" + snap
    sig_url = ""
    sig_path = card_row["signature_path"]
    if sig_path:
        sf = SCRIPT_DIR / sig_path.lstrip("/")
        if sf.exists():
            sig_url = "/project-files/" + sig_path
    cnd = card_row["card_number_display"] or card_row["card_id"]
    ctx = {
        "NAME": emp["name"] or "",
        "EMPLOYEE_ID": card_row["employee_id"],
        "CARD_NUMBER_DISPLAY": cnd,
        "ISSUED_DATE": _fmt_mdy(card_row["issued_date"]),
        "ISSUED_BY": card_row["issued_by"] or NEW_RIGGER_NAME,
        "EXPIRES_DATE": _fmt_mdy(card_row["expires_date"]),
        "TRADE": emp["trade"] or "",
        "PIN": emp["pin"] or "----",
        "PHOTO_URL_OR_BLANK": photo_url,
        "RIGGER_NAME": NEW_RIGGER_NAME,
        "RIGGER_LICENSE": NEW_RIGGER_LICENSE,
        "SIGNATURE_URL": sig_url,
    }
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(SCRIPT_DIR)),
        autoescape=True,
    )
    html = env.get_template("cof_card_print.html").render(**ctx)
    out_dir = SCRIPT_DIR / "data_room" / "credentials" / "cof"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{card_row['employee_id']}.html"
    pre_hash = file_hash(out_file)
    out_file.write_text(html, encoding="utf-8")
    rel = out_file.relative_to(SCRIPT_DIR).as_posix()
    conn = sqlite3.connect(str(DB))
    try:
        conn.execute(
            "UPDATE cof_cards SET html_export_path = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE card_id = ?",
            (rel, card_row["card_id"]),
        )
        conn.commit()
    finally:
        conn.close()
    return pre_hash, file_hash(out_file)


def force_issue_override(emp_id, prereq_reason, rigger):
    """Issue an admin-overridden CoF without the prereq cert (#144
    eligibility override policy). Returns the new card_id."""
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        # Supersede any prior 'issued' CoF (defensive)
        conn.execute(
            "UPDATE cof_cards SET status='replaced', "
            "updated_at=CURRENT_TIMESTAMP "
            "WHERE employee_id = ? AND status = 'issued'",
            (emp_id,),
        )
        cnd = card_number_for_employee(emp_id)
        revision = _next_cof_revision(conn, emp_id)
        card_id = f"{cnd}-{revision}"
        conn.execute(
            "INSERT INTO cof_cards "
            "(card_id, employee_id, issued_date, expires_date, issued_by, "
            " issuer_license, signature_path, photo_snapshot_path, status, "
            " basis_certs_json, rigger_id, rigger_name_snapshot, "
            " rigger_license_snapshot, card_number_display, notes) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'issued', ?, ?, ?, ?, ?, ?)",
            (
                card_id, emp_id, TODAY, OVERRIDE_EXPIRY,
                NEW_RIGGER_NAME, NEW_RIGGER_LICENSE,
                rigger.get("signature_path") if rigger else "",
                json.dumps({"override": True, "missing_prereq": prereq_reason}),
                rigger.get("id") if rigger else None,
                NEW_RIGGER_NAME, NEW_RIGGER_LICENSE, cnd,
                f"#144 / #171 eligibility override — missing prereq: {prereq_reason}",
            ),
        )
        conn.commit()
        # Photo snapshot — copy current face_image_path into credentials dir
        emp = conn.execute(
            "SELECT face_image_path FROM employees WHERE employee_id = ?",
            (emp_id,),
        ).fetchone()
        photo_snapshot = None
        if emp and emp["face_image_path"]:
            from pathlib import Path as P
            import shutil
            src = P(emp["face_image_path"])
            if not src.is_absolute():
                src = SCRIPT_DIR / src
            if src.exists():
                cred_dir = SCRIPT_DIR / "data_room" / "credentials"
                cred_dir.mkdir(parents=True, exist_ok=True)
                ext = src.suffix.lower() or ".jpg"
                dest = cred_dir / f"{emp_id}_v{revision}{ext}"
                try:
                    shutil.copy2(str(src), str(dest))
                    photo_snapshot = dest.relative_to(SCRIPT_DIR).as_posix()
                except Exception:
                    pass
        if photo_snapshot:
            conn.execute(
                "UPDATE cof_cards SET photo_snapshot_path = ? WHERE card_id = ?",
                (photo_snapshot, card_id),
            )
            conn.commit()
        return card_id
    finally:
        conn.close()


def actor_user_id():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT id FROM users WHERE role IN ('admin','c_suite') "
            "AND email NOT LIKE 'smoke%' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if not row:
            row = conn.execute(
                "SELECT id FROM users WHERE role IN ('admin','c_suite') "
                "ORDER BY id ASC LIMIT 1"
            ).fetchone()
        return row["id"] if row else None
    finally:
        conn.close()


def main():
    actor_id = actor_user_id()
    print(f"actor_user_id={actor_id}  rigger={NEW_RIGGER_NAME} #{NEW_RIGGER_LICENSE}\n")
    refreshed = 0
    issued = 0
    force_issued = 0
    skipped = 0
    hash_changes = 0
    audit_added = 0

    for wid in TARGET_WORKERS:
        conn = sqlite3.connect(str(DB))
        conn.row_factory = sqlite3.Row
        try:
            emp = conn.execute(
                "SELECT employee_id FROM employees WHERE worker_id = ?",
                (wid,),
            ).fetchone()
            if not emp:
                print(f"  {wid}: not in employees — SKIPPED")
                skipped += 1
                continue
            emp_id = emp["employee_id"]
            cof = conn.execute(
                "SELECT * FROM cof_cards "
                "WHERE employee_id = ? AND status = 'issued' "
                "ORDER BY issued_date DESC LIMIT 1",
                (emp_id,),
            ).fetchone()
        finally:
            conn.close()

        if cof:
            # REFRESH path — update + audit, then re-render static HTML.
            conn = sqlite3.connect(str(DB))
            conn.row_factory = sqlite3.Row
            try:
                before = {
                    "rigger_name_snapshot": cof["rigger_name_snapshot"],
                    "rigger_license_snapshot": cof["rigger_license_snapshot"],
                    "issued_by": cof["issued_by"],
                    "issuer_license": cof["issuer_license"],
                }
                conn.execute(
                    "UPDATE cof_cards SET "
                    "  rigger_name_snapshot = ?, rigger_license_snapshot = ?, "
                    "  issued_by = ?, issuer_license = ?, "
                    "  updated_at = CURRENT_TIMESTAMP "
                    "WHERE card_id = ?",
                    (NEW_RIGGER_NAME, NEW_RIGGER_LICENSE,
                     NEW_RIGGER_NAME, NEW_RIGGER_LICENSE, cof["card_id"]),
                )
                log_audit(
                    conn,
                    action="cof_metadata_refresh",
                    actor_user_id=actor_id,
                    actor_role=ACTOR_ROLE,
                    target_type="cof_card",
                    target_id=cof["card_id"],
                    before=before,
                    after={
                        "rigger_name_snapshot": NEW_RIGGER_NAME,
                        "rigger_license_snapshot": NEW_RIGGER_LICENSE,
                    },
                    note=f"#171 metadata refresh for {wid}",
                )
                conn.commit()
                audit_added += 1
            finally:
                conn.close()
            # Re-fetch then re-render
            conn = sqlite3.connect(str(DB))
            conn.row_factory = sqlite3.Row
            try:
                fresh = conn.execute(
                    "SELECT * FROM cof_cards WHERE card_id = ?",
                    (cof["card_id"],),
                ).fetchone()
            finally:
                conn.close()
            hashes = rerender_static_html(emp_id, fresh)
            hash_changed = hashes is not None and hashes[0] != hashes[1]
            if hash_changed:
                hash_changes += 1
            refreshed += 1
            print(f"  {wid}: REFRESH  card_id={cof['card_id']}  hash_changed={hash_changed}")
        else:
            # No active CoF — try natural issue, else force-issue (override).
            try:
                card = issue_cof(emp_id, project_code='FR-BX-001')
                # Natural-issue path. Re-render the static HTML.
                conn = sqlite3.connect(str(DB))
                conn.row_factory = sqlite3.Row
                try:
                    fresh = conn.execute(
                        "SELECT * FROM cof_cards WHERE card_id = ?",
                        (card["card_id"],),
                    ).fetchone()
                finally:
                    conn.close()
                rerender_static_html(emp_id, fresh)
                # Audit log
                conn = sqlite3.connect(str(DB))
                conn.row_factory = sqlite3.Row
                try:
                    log_audit(
                        conn,
                        action="cof_issue",
                        actor_user_id=actor_id,
                        actor_role=ACTOR_ROLE,
                        target_type="cof_card",
                        target_id=card["card_id"],
                        before=None,
                        after={
                            "rigger_name_snapshot": NEW_RIGGER_NAME,
                            "rigger_license_snapshot": NEW_RIGGER_LICENSE,
                            "issued_date": card.get("issued_date"),
                            "expires_date": card.get("expires_date"),
                        },
                        note=f"#171 issue (natural eligibility) for {wid}",
                    )
                    conn.commit()
                    audit_added += 1
                finally:
                    conn.close()
                issued += 1
                print(f"  {wid}: ISSUE    card_id={card['card_id']}  date={card.get('issued_date')}  exp={card.get('expires_date')}")
            except RuntimeError as e:
                reason = str(e)
                # Force-issue path (#144 eligibility override).
                rigger = get_default_rigger_for_project('FR-BX-001')
                card_id = force_issue_override(emp_id, reason, rigger)
                conn = sqlite3.connect(str(DB))
                conn.row_factory = sqlite3.Row
                try:
                    fresh = conn.execute(
                        "SELECT * FROM cof_cards WHERE card_id = ?",
                        (card_id,),
                    ).fetchone()
                finally:
                    conn.close()
                rerender_static_html(emp_id, fresh)
                conn = sqlite3.connect(str(DB))
                conn.row_factory = sqlite3.Row
                try:
                    log_audit(
                        conn,
                        action="cof_issue_override",
                        actor_user_id=actor_id,
                        actor_role=ACTOR_ROLE,
                        target_type="cof_card",
                        target_id=card_id,
                        before=None,
                        after={
                            "rigger_name_snapshot": NEW_RIGGER_NAME,
                            "rigger_license_snapshot": NEW_RIGGER_LICENSE,
                            "issued_date": TODAY,
                            "expires_date": OVERRIDE_EXPIRY,
                            "missing_prereq": reason,
                        },
                        note=f"#171 force-issue (#144 override) for {wid}: {reason}",
                    )
                    conn.commit()
                    audit_added += 1
                finally:
                    conn.close()
                force_issued += 1
                print(f"  {wid}: FORCE    card_id={card_id}  reason={reason}")

    print()
    print(f"refreshed: {refreshed}   issued: {issued}   force-issued: {force_issued}   skipped: {skipped}")
    print(f"audit_log entries added this run: {audit_added}")
    print(f"static HTMLs whose hash changed (refresh path): {hash_changes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
