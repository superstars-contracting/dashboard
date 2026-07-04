"""#274 — IRA inspection pipeline: the post-award execution tracker + the inspection
calendar, inside the #273 'estimates' company-console section (same CRM-class gating:
every endpoint @requires_section('estimates') = admin/c_suite, server-enforced).

PRINCIPLES
  * A JOB is a CONVERTED IRA estimate (ira_job PK = project_code). The list
    SELF-HEALS: a converted IRA estimate with no job row gains one on read (and at
    convert time via the #273 hook), so the call-back case ("two more days, months
    later") always finds its job.
  * CHECKLIST RAIL: contract / CD-5 / COI artifacts live in estimate_document (ONE
    consistent home for IRA paper — uploaded here by-kind, served by the #273 gated
    by-id route). CD-5 is TRACKED (filing happens in DOB NOW): not_filed -> filed ->
    approved, adjacent moves only (a jump not_filed->approved never happened in the
    real world — it means the filing was never recorded). The COI carries
    expiry_date and gets the standard #271 pill (expired / expiring 30d / on_file),
    which also feeds the waiting-on digest sweep.
  * VISITS: MULTIPLE per job BY DESIGN — add rows, never edit history. A performed
    visit is immutable except its status; nothing hard-deletes (cancelled is the
    correction). Same-day visits across jobs are ALLOWED (subvendor days) — the UI
    stacks them with a badge; warn, never block.
  * Fieldwire = a LINK field (integrate-don't-rebuild; live API is Build C, blocked
    on vaulted credentials). QuickBooks = reference fields only, same rule.
  * Every artifact landing / tracked-status change writes crm_activity on the linked
    org, function_tag 'ops' (the execution axis; the estimate pipeline itself logs
    'sales' — #273).

Dates LOCAL (CLAUDE.md). All SQL parameterized via db_layer — identical on SQLite
(default/production) and Postgres (the gate).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

from flask import jsonify, request

import crm
import estimates
from auth import _db, current_user, requires_section

CD5_STATUSES = ("not_filed", "filed", "approved")
_CD5_MOVES = {"not_filed": {"filed"}, "filed": {"approved", "not_filed"}, "approved": {"filed"}}
BALANCE_STATUSES = ("open", "paid")
VISIT_STATUSES = ("scheduled", "performed", "cancelled")
ARTIFACT_KINDS = ("contract", "cd5", "coi")
_KIND_COL = {"contract": "contract_doc_id", "cd5": "cd5_doc_id", "coi": "coi_doc_id"}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _uid():
    return (current_user() or {}).get("id")


def _expiry_status(exp, today_iso, d30_iso):
    """The #271 pill thresholds: expired < today, expiring <= today+30, else on_file."""
    if not exp:
        return None
    if exp < today_iso:
        return "expired"
    if exp <= d30_iso:
        return "expiring"
    return "on_file"


# ============================ core (shared with the smoke) ============================

def ensure_job(conn, project_code, estimate_id) -> None:
    """Idempotent job-row creation — called at convert time (#273 hook) AND self-healing
    on every list read, so a converted IRA estimate can never be missing its job."""
    if not conn.execute("SELECT 1 FROM ira_job WHERE project_code=?", (project_code,)).fetchone():
        conn.execute(
            "INSERT INTO ira_job (project_code, estimate_id, cd5_status, deposit_received, "
            "balance_status, updated_at) VALUES (?,?, 'not_filed', 0, 'open', ?)",
            (project_code, estimate_id, _now()))
        conn.commit()


def _self_heal(conn) -> None:
    for r in conn.execute(
            "SELECT id, converted_project_code FROM estimate WHERE est_type='IRA' "
            "AND status='converted' AND converted_project_code IS NOT NULL").fetchall():
        ensure_job(conn, r["converted_project_code"], r["id"])


def set_cd5_status(conn, job, new_status, filed_date=None, actor=None) -> None:
    """Adjacent-move CD-5 tracking (raise ValueError on a jump). Stamps/keeps the
    filed date; logs the change on the org timeline ('ops')."""
    old = job["cd5_status"] or "not_filed"
    new_status = (new_status or "").strip().lower()
    if new_status not in CD5_STATUSES:
        raise ValueError(f"unknown cd5_status: {new_status}")
    if new_status == old:
        return
    if new_status not in _CD5_MOVES.get(old, set()):
        raise ValueError(f"illegal CD-5 move: {old} -> {new_status}")
    fd = job["cd5_filed_date"]
    if new_status in ("filed", "approved"):
        fd = (filed_date or "").strip() or fd or date.today().isoformat()
        datetime.strptime(fd, "%Y-%m-%d")
    if new_status == "not_filed":
        fd = None
    conn.execute("UPDATE ira_job SET cd5_status=?, cd5_filed_date=?, updated_at=? WHERE project_code=?",
                 (new_status, fd, _now(), job["project_code"]))
    conn.commit()
    _log(conn, job, f"CD-5 {old} → {new_status}" + (f" (filed {fd})" if fd else ""), actor)


def _log(conn, job, text, actor=None):
    est = conn.execute("SELECT client_org_id, code FROM estimate WHERE id=?",
                       (job["estimate_id"],)).fetchone()
    if est:
        crm.add_activity(conn, entity_type="organization", entity_id=est["client_org_id"],
                         activity_type="system", author_user_id=actor, function_tag="ops",
                         summary=f"IRA {job['project_code']}: {text}")


# ============================ payload shaping ============================

def _doc_or_none(conn, doc_id, today_iso, d30_iso):
    if not doc_id:
        return None
    r = conn.execute("SELECT * FROM estimate_document WHERE id=?", (doc_id,)).fetchone()
    if not r:
        return None
    d = estimates.doc_public(dict(r))
    d["expiry_status"] = _expiry_status(d.get("expiry_date"), today_iso, d30_iso)
    return d


def job_public(conn, job, *, org_name=None, building_address=None, today_iso=None):
    today_iso = today_iso or date.today().isoformat()
    d30_iso = (date.fromisoformat(today_iso) + timedelta(days=30)).isoformat()
    nxt = conn.execute(
        "SELECT visit_date, label FROM ira_visit WHERE project_code=? AND status='scheduled' "
        "AND visit_date >= ? ORDER BY visit_date LIMIT 1", (job["project_code"], today_iso)).fetchone()
    nvis = conn.execute("SELECT COUNT(*) AS n FROM ira_visit WHERE project_code=?",
                        (job["project_code"],)).fetchone()["n"]
    coi = _doc_or_none(conn, job["coi_doc_id"], today_iso, d30_iso)
    out = {
        "project_code": job["project_code"], "estimate_id": job["estimate_id"],
        "org_name": org_name, "building_address": building_address,
        "cd5_status": job["cd5_status"] or "not_filed", "cd5_filed_date": job["cd5_filed_date"],
        "cd5_doc": _doc_or_none(conn, job["cd5_doc_id"], today_iso, d30_iso),
        "coi_doc": coi,
        "coi_expiry_status": (coi or {}).get("expiry_status"),
        "contract_doc": _doc_or_none(conn, job["contract_doc_id"], today_iso, d30_iso),
        "fieldwire_url": job["fieldwire_url"],
        "report_sent_date": job["report_sent_date"],
        "deposit_received": bool(job["deposit_received"]),
        "deposit_date": job["deposit_date"],
        "balance_status": job["balance_status"] or "open",
        "qb_invoice_ref": job["qb_invoice_ref"],
        "next_visit": dict(nxt) if nxt else None,
        "visits_count": nvis,
    }
    missing = []
    if not out["contract_doc"]:
        missing.append("contract")
    if out["cd5_status"] != "approved":
        missing.append("cd5")
    if not out["coi_doc"]:
        missing.append("coi")
    elif out["coi_expiry_status"] == "expired":
        missing.append("coi_expired")
    out["missing"] = missing
    return out


def _jobs_with_estimate(conn):
    return conn.execute(
        "SELECT j.*, e.building_address, e.code AS est_code, o.name AS org_name "
        "FROM ira_job j JOIN estimate e ON e.id = j.estimate_id "
        "JOIN crm_organization o ON o.id = e.client_org_id "
        "ORDER BY j.project_code").fetchall()


# ============================ endpoints ============================

@requires_section('estimates')
def _api_jobs():
    """GET /api/ira/jobs — every converted IRA job with its checklist state, next
    visit, and waiting-on flags. Self-heals missing job rows first."""
    conn = _db()
    try:
        _self_heal(conn)
        today_iso = date.today().isoformat()
        out = [job_public(conn, dict(j), org_name=j["org_name"],
                          building_address=j["building_address"], today_iso=today_iso)
               for j in _jobs_with_estimate(conn)]
        return jsonify({"data": {"jobs": out}})
    finally:
        conn.close()


@requires_section('estimates')
def _api_job_detail(project_code):
    conn = _db()
    try:
        _self_heal(conn)
        j = conn.execute(
            "SELECT j.*, e.building_address, e.code AS est_code, o.name AS org_name "
            "FROM ira_job j JOIN estimate e ON e.id=j.estimate_id "
            "JOIN crm_organization o ON o.id=e.client_org_id WHERE j.project_code=?",
            (project_code,)).fetchone()
        if not j:
            return jsonify({"error": "not found"}), 404
        visits = [dict(v) for v in conn.execute(
            "SELECT * FROM ira_visit WHERE project_code=? ORDER BY visit_date DESC, id DESC",
            (project_code,)).fetchall()]
        docs = estimates.list_documents(conn, j["estimate_id"])
        return jsonify({"data": {
            "job": job_public(conn, dict(j), org_name=j["org_name"],
                              building_address=j["building_address"]),
            "visits": visits,
            "documents": docs,
        }})
    finally:
        conn.close()


@requires_section('estimates')
def _api_job_update(project_code):
    """PUT — the tracked (non-artifact) checklist fields: CD-5 status/date, Fieldwire
    link, report sent, payment strip. Logs 'ops' activity on each tracked change."""
    d = request.get_json(silent=True) or {}
    conn = _db()
    try:
        job = conn.execute("SELECT * FROM ira_job WHERE project_code=?", (project_code,)).fetchone()
        if not job:
            return jsonify({"error": "not found"}), 404
        job = dict(job)
        try:
            if "cd5_status" in d:
                set_cd5_status(conn, job, d.get("cd5_status"), d.get("cd5_filed_date"), _uid())
                job = dict(conn.execute("SELECT * FROM ira_job WHERE project_code=?",
                                        (project_code,)).fetchone())
            sets, params, logs = [], [], []
            if "fieldwire_url" in d:
                url = (d.get("fieldwire_url") or "").strip() or None
                if url and not (url.startswith("https://") or url.startswith("http://")):
                    return jsonify({"error": "fieldwire_url must be an http(s) link"}), 400
                sets.append("fieldwire_url=?"); params.append(url)
                if url and url != job["fieldwire_url"]:
                    logs.append("Fieldwire link set")
            if "report_sent_date" in d:
                v = (d.get("report_sent_date") or "").strip() or None
                if v:
                    datetime.strptime(v, "%Y-%m-%d")
                sets.append("report_sent_date=?"); params.append(v)
                if v and v != job["report_sent_date"]:
                    logs.append(f"report sent {v}")
            if "deposit_received" in d:
                dep = 1 if d.get("deposit_received") in (1, True, "1", "true") else 0
                dd = (d.get("deposit_date") or "").strip() or None
                if dep and not dd:
                    dd = job["deposit_date"] or date.today().isoformat()
                if dd:
                    datetime.strptime(dd, "%Y-%m-%d")
                if not dep:
                    dd = None
                sets += ["deposit_received=?", "deposit_date=?"]; params += [dep, dd]
                if dep and not job["deposit_received"]:
                    logs.append(f"deposit received {dd}")
            if "balance_status" in d:
                b = (d.get("balance_status") or "").strip().lower()
                if b not in BALANCE_STATUSES:
                    return jsonify({"error": "balance_status must be open or paid"}), 400
                sets.append("balance_status=?"); params.append(b)
                if b != (job["balance_status"] or "open"):
                    logs.append(f"balance {b}")
            if "qb_invoice_ref" in d:
                sets.append("qb_invoice_ref=?")
                params.append((str(d.get("qb_invoice_ref") or "").strip() or None))
            if sets:
                sets.append("updated_at=?"); params.append(_now())
                params.append(project_code)
                conn.execute(f"UPDATE ira_job SET {', '.join(sets)} WHERE project_code=?", params)
                conn.commit()
            for msg in logs:
                _log(conn, job, msg, _uid())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        j = conn.execute(
            "SELECT j.*, e.building_address, o.name AS org_name FROM ira_job j "
            "JOIN estimate e ON e.id=j.estimate_id JOIN crm_organization o ON o.id=e.client_org_id "
            "WHERE j.project_code=?", (project_code,)).fetchone()
        return jsonify({"data": job_public(conn, dict(j), org_name=j["org_name"],
                                           building_address=j["building_address"])})
    finally:
        conn.close()


@requires_section('estimates')
def _api_job_artifact(project_code):
    """POST (multipart) — ONE atomic artifact landing: kind=contract|cd5|coi + file
    (+ expiry_date for the COI). Saves into estimate_document (the one home for IRA
    paper), points the job's slot at it, writes the 'ops' activity row."""
    conn = _db()
    try:
        job = conn.execute("SELECT * FROM ira_job WHERE project_code=?", (project_code,)).fetchone()
        if not job:
            return jsonify({"error": "not found"}), 404
        job = dict(job)
        kind = (request.form.get("kind") or "").strip().lower()
        if kind not in ARTIFACT_KINDS:
            return jsonify({"error": f"kind must be one of {'/'.join(ARTIFACT_KINDS)}"}), 400
        if 'file' not in request.files:
            return jsonify({"error": "no file"}), 400
        expiry = (request.form.get("expiry_date") or "").strip() or None
        if expiry:
            try:
                datetime.strptime(expiry, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "expiry_date must be YYYY-MM-DD"}), 400
        try:
            doc_id = estimates.add_document(
                conn, job["estimate_id"], request.files['file'], category=kind,
                title=(request.form.get("title") or "").strip() or None,
                uploaded_by=_uid(), expiry_date=expiry)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        conn.execute(f"UPDATE ira_job SET {_KIND_COL[kind]}=?, updated_at=? WHERE project_code=?",
                     (doc_id, _now(), project_code))
        conn.commit()
        _log(conn, job, f"{kind.upper()} uploaded" + (f" (expires {expiry})" if expiry else ""), _uid())
        j = conn.execute(
            "SELECT j.*, e.building_address, o.name AS org_name FROM ira_job j "
            "JOIN estimate e ON e.id=j.estimate_id JOIN crm_organization o ON o.id=e.client_org_id "
            "WHERE j.project_code=?", (project_code,)).fetchone()
        return jsonify({"data": job_public(conn, dict(j), org_name=j["org_name"],
                                           building_address=j["building_address"])})
    finally:
        conn.close()


@requires_section('estimates')
def _api_visit_create(project_code):
    """POST — add a visit row (multiple per job BY DESIGN; the call-back case is just
    more rows). Same-day stacking across jobs is allowed — warn in the UI, never block."""
    d = request.get_json(silent=True) or {}
    conn = _db()
    try:
        job = conn.execute("SELECT * FROM ira_job WHERE project_code=?", (project_code,)).fetchone()
        if not job:
            return jsonify({"error": "not found"}), 404
        vd = (d.get("visit_date") or "").strip()
        try:
            datetime.strptime(vd, "%Y-%m-%d")
        except (ValueError, TypeError):
            return jsonify({"error": "visit_date must be YYYY-MM-DD"}), 400
        status = (d.get("status") or "scheduled").strip().lower()
        if status not in VISIT_STATUSES:
            return jsonify({"error": f"status must be one of {'/'.join(VISIT_STATUSES)}"}), 400
        conn.execute(
            "INSERT INTO ira_visit (project_code, visit_date, label, status, created_by, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (project_code, vd, (d.get("label") or "").strip() or None, status, _uid(), _now()))
        conn.commit()
        vid = conn.execute("SELECT MAX(id) AS m FROM ira_visit").fetchone()["m"]
        _log(conn, dict(job), f"visit {status} {vd}", _uid())
        v = conn.execute("SELECT * FROM ira_visit WHERE id=?", (vid,)).fetchone()
        return jsonify({"data": dict(v)})
    finally:
        conn.close()


@requires_section('estimates')
def _api_visit_update(visit_id):
    """PUT — performed visits are IMMUTABLE except status; visits are never deleted
    (cancelled is the correction). History rows stay history."""
    d = request.get_json(silent=True) or {}
    conn = _db()
    try:
        v = conn.execute("SELECT * FROM ira_visit WHERE id=?", (visit_id,)).fetchone()
        if not v:
            return jsonify({"error": "not found"}), 404
        v = dict(v)
        new_status = (d.get("status") or v["status"]).strip().lower()
        if new_status not in VISIT_STATUSES:
            return jsonify({"error": f"status must be one of {'/'.join(VISIT_STATUSES)}"}), 400
        wants_date = "visit_date" in d and (d.get("visit_date") or "").strip() != v["visit_date"]
        wants_label = "label" in d and ((d.get("label") or "").strip() or None) != v["label"]
        if v["status"] == "performed" and (wants_date or wants_label):
            return jsonify({"error": "a performed visit is immutable except its status"}), 400
        vd = v["visit_date"]
        if wants_date:
            vd = (d.get("visit_date") or "").strip()
            try:
                datetime.strptime(vd, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": "visit_date must be YYYY-MM-DD"}), 400
        label = ((d.get("label") or "").strip() or None) if wants_label else v["label"]
        conn.execute("UPDATE ira_visit SET status=?, visit_date=?, label=? WHERE id=?",
                     (new_status, vd, label, visit_id))
        conn.commit()
        if new_status != v["status"]:
            job = conn.execute("SELECT * FROM ira_job WHERE project_code=?",
                               (v["project_code"],)).fetchone()
            if job:
                _log(conn, dict(job), f"visit {vd} → {new_status}", _uid())
        r = conn.execute("SELECT * FROM ira_visit WHERE id=?", (visit_id,)).fetchone()
        return jsonify({"data": dict(r)})
    finally:
        conn.close()


@requires_section('estimates')
def _api_calendar():
    """GET /api/ira/calendar?month=YYYY-MM — the month's visits (all statuses; the UI
    stacks same-day rows with a badge), the upcoming-14-days list, and the WAITING-ON
    digest: jobs with a scheduled visit still missing CD-5 approval / COI (incl. the
    expired-COI sweep) / contract. That digest is the VP's daily glance."""
    conn = _db()
    try:
        _self_heal(conn)
        month = (request.args.get("month") or "").strip() or date.today().isoformat()[:7]
        try:
            first = date.fromisoformat(month + "-01")
        except ValueError:
            return jsonify({"error": "month must be YYYY-MM"}), 400
        last = (first.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        today_iso = date.today().isoformat()
        visits = [dict(v) for v in conn.execute(
            "SELECT v.*, e.building_address, o.name AS org_name FROM ira_visit v "
            "JOIN ira_job j ON j.project_code = v.project_code "
            "JOIN estimate e ON e.id = j.estimate_id "
            "JOIN crm_organization o ON o.id = e.client_org_id "
            "WHERE v.visit_date >= ? AND v.visit_date <= ? "
            "ORDER BY v.visit_date, v.project_code",
            (first.isoformat(), last.isoformat())).fetchall()]
        upcoming = [dict(v) for v in conn.execute(
            "SELECT v.*, e.building_address, o.name AS org_name FROM ira_visit v "
            "JOIN ira_job j ON j.project_code = v.project_code "
            "JOIN estimate e ON e.id = j.estimate_id "
            "JOIN crm_organization o ON o.id = e.client_org_id "
            "WHERE v.status='scheduled' AND v.visit_date >= ? AND v.visit_date <= ? "
            "ORDER BY v.visit_date, v.project_code",
            (today_iso, (date.today() + timedelta(days=14)).isoformat())).fetchall()]
        waiting = []
        for j in _jobs_with_estimate(conn):
            jp = job_public(conn, dict(j), org_name=j["org_name"],
                            building_address=j["building_address"], today_iso=today_iso)
            if jp["missing"] and jp["next_visit"]:
                waiting.append({"project_code": jp["project_code"], "org_name": jp["org_name"],
                                "next_visit_date": jp["next_visit"]["visit_date"],
                                "missing": jp["missing"]})
        waiting.sort(key=lambda w: w["next_visit_date"])
        return jsonify({"data": {"month": month, "first": first.isoformat(),
                                 "last": last.isoformat(), "visits": visits,
                                 "upcoming": upcoming, "waiting_on": waiting}})
    finally:
        conn.close()


def register(app) -> None:
    """Wire the IRA-pipeline endpoints (all admin/c_suite via the 'estimates' section
    — ONE access source). Call after the auth + containment gates."""
    app.add_url_rule("/api/ira/jobs", "ira_jobs", _api_jobs, methods=["GET"])
    app.add_url_rule("/api/ira/jobs/<project_code>", "ira_job_detail", _api_job_detail, methods=["GET"])
    app.add_url_rule("/api/ira/jobs/<project_code>", "ira_job_update", _api_job_update, methods=["PUT"])
    app.add_url_rule("/api/ira/jobs/<project_code>/artifact", "ira_job_artifact", _api_job_artifact, methods=["POST"])
    app.add_url_rule("/api/ira/jobs/<project_code>/visits", "ira_visit_create", _api_visit_create, methods=["POST"])
    app.add_url_rule("/api/ira/visits/<int:visit_id>", "ira_visit_update", _api_visit_update, methods=["PUT"])
    app.add_url_rule("/api/ira/calendar", "ira_calendar", _api_calendar, methods=["GET"])
