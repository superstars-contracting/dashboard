"""#284 GUARD — THE PORTAL FLIP: matrix, nav-from-grants, registry-served payloads,
preview parity, and the landing switch.

What it proves:
  MATRIX      fail-closed on every axis: an unseeded role resolves to an EMPTY
              section set (unit); a client's payload endpoint refuses a section
              without a grant even though the matrix allows it; a vendor/unknown
              external role has no portal surface at all.
  NAV         the served shell's DOM (scripts stripped — the #283 lesson) carries
              EXACTLY the effective sections as nav+views, zero internal nav
              items, for BOTH seeded grant shapes (progress+daily, and
              progress+photos+documents).
  PAYLOADS    right-subset by id for all four sections: photos/documents list
              ONLY item-shared ids of the client's own project; daily days carry
              only registered fields; progress carries only registered fields.
  DAILY       the operator-approved allowlist, asserted as recursive KEY-ABSENCE
              over the whole JSON (worker/hours/rate/headcount/quantity/note/
              reason/free-text keys never appear at any depth).
  PARITY      an admin preview of a client's shell is BYTE-IDENTICAL to the
              client's own page, and the section payloads are JSON-identical.
  LANDING     /welcome and Classic /portal forward a granted client to
              /portal/<code>; the #267 zero-grant hard-stop is byte-unchanged
              (welcome only, APIs 403); the architect keeps /drawing-markup;
              internal roles keep the internal shell on the same route.
  ISOLATION   cross-project by URL is 403 on every new endpoint; cross-project /
              unshared by-id photo and document fetches are 404; a client on the
              internal /api/* namespace is still 403.

Isolated backend REQUIRED (seeds users/projects/photos/documents/elevation rows).
PII-safe: synthetic identities, ids/keys/counts only. 127.0.0.1 only.
"""
from __future__ import annotations

import os
import re
import secrets
import sys
from pathlib import Path

import requests

SCRIPT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPT_DIR))

import db_layer  # noqa: E402
import portal_matrix  # noqa: E402
import client_registry as reg  # noqa: E402

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PC, PD = "SMK284-C", "SMK284-D"
PASS, FAIL = [], []
IDS = {"users": [], "photos": [], "docs": []}


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note and not cond else ""))
    return bool(cond)


def markup(s):
    s = re.sub(r"<script\b.*?</script>", "", s, flags=re.S | re.I)
    return re.sub(r"<style\b.*?</style>", "", s, flags=re.S | re.I)


def seed():
    conn = db_layer.connect()
    try:
        for code in (PC, PD):
            conn.execute("DELETE FROM projects WHERE project_code=?", (code,))
            conn.execute("INSERT INTO projects (project_code, name, status) VALUES (?,?,'active')",
                         (code, f"Smoke 284 {code[-1]}"))
        users = {}
        for key, role in (("admin", "admin"), ("pm_on", "pm"), ("cli_min", "client"),
                          ("cli_full", "client"), ("cli_zero", "client"), ("cli_b", "client"),
                          ("arch", "architect"), ("vend", "vendor")):
            cur = conn.execute(
                "INSERT INTO users (email, password_hash, role, full_name, is_active, status, "
                "must_reset_password, is_system) VALUES (?,?,?,?,1,'active',0,1)",
                (f"smk284-{key}@superstars.local", "x!unusable", role, f"SMK284 {key}"))
            users[key] = cur.lastrowid
            IDS["users"].append(cur.lastrowid)
        for key, code in (("pm_on", PC), ("cli_min", PC), ("cli_full", PC), ("cli_zero", PC),
                          ("cli_b", PD), ("arch", PC), ("vend", PC)):
            conn.execute("INSERT INTO pm_project_assignment (user_id, project_code, assigned_by, "
                         "assigned_at) VALUES (?,?,?, '2026-07-28T00:00:00')",
                         (users[key], code, users["admin"]))
        for key, code, secs in (("cli_min", PC, ("progress", "daily")),
                                ("cli_full", PC, ("progress", "photos", "documents")),
                                ("cli_b", PD, ("progress", "photos", "documents", "daily"))):
            for s in secs:
                conn.execute("INSERT INTO client_section_grant (user_id, project_code, section, "
                             "granted_by, granted_at) VALUES (?,?,?,?, '2026-07-28T00:00:00')",
                             (users[key], code, s, users["admin"]))

        def photo(code, cap, shared):
            cur = conn.execute(
                "INSERT INTO field_photos (project_code, caption, taken_at, uploaded_at, "
                "file_path, thumb_path, mime) VALUES (?,?, '2026-07-27 10:00:00', "
                "'2026-07-27 10:05:00', 'x/none.jpg', 'x/none_t.jpg', 'image/jpeg')", (code, cap))
            pid = cur.lastrowid
            IDS["photos"].append(pid)
            if shared:
                conn.execute("INSERT INTO item_visibility (item_type, item_id, audience, "
                             "shared_by, shared_at) VALUES ('photo', ?, 'client', ?, "
                             "'2026-07-27T12:00:00')", (pid, users["admin"]))
            return pid

        def doc(code, title, shared):
            cur = conn.execute(
                "INSERT INTO project_documents (project_code, category, title, doc_type, "
                "file_path, effective_date, uploaded_at) VALUES (?, 'PERMITS', ?, 'PDF', "
                "'x/none.pdf', '2026-07-01', '2026-07-01T09:00:00')", (code, title))
            did = cur.lastrowid
            IDS["docs"].append(did)
            if shared:
                conn.execute("INSERT INTO item_visibility (item_type, item_id, audience, "
                             "shared_by, shared_at) VALUES ('document', ?, 'client', ?, "
                             "'2026-07-27T12:00:00')", (did, users["admin"]))
            return did

        fx = {
            "p_shared": photo(PC, "smk284 shared", True),
            "p_unshared": photo(PC, "smk284 unshared", False),
            "p_other": photo(PD, "smk284 other-project shared", True),
            "d_shared": doc(PC, "SMK284 Shared Permit", True),
            "d_unshared": doc(PC, "SMK284 Unshared", False),
            "d_other": doc(PD, "SMK284 Other Project", True),
        }
        # daily fixtures on PC: an issued day with weather + stage + cell change.
        # Free-text columns are POPULATED with sentinels so a leak is detectable.
        conn.execute("INSERT INTO report_index (report_date, project_code, report_type, status, "
                     "report_id, dcr_sequence, no_work, no_work_reason, no_work_note) VALUES "
                     "('2026-07-27', ?, 'DCR', 'issued', 'SMK-284-RI', 99902, 0, "
                     "'SENTINEL-284-REASON', 'SENTINEL-284-NOTE')", (PC,))
        conn.execute("INSERT INTO weather_log (date, project_code, am_temp_f, pm_temp_f, "
                     "am_conditions, pm_conditions, wind) VALUES ('2026-07-27', ?, 71.0, 84.0, "
                     "'Sunny', 'Partly cloudy', '5-10 mph')", (PC,))
        conn.execute("INSERT INTO work_log (date, project_code, scope_of_work, description) "
                     "VALUES ('2026-07-27', ?, 'SENTINEL-284-SCOPE', 'SENTINEL-284-DESC')", (PC,))
        conn.execute("INSERT INTO drops (drop_id, project_code, elevation, sequence_no, lifecycle) "
                     "VALUES ('SMK284-DP3', ?, 'North', 3, 'scaffold_active')", (PC,))
        cur = conn.execute("INSERT INTO stage_templates (project_code, name) VALUES (?, 'SMK284 T')",
                           (PC,))
        tmpl = cur.lastrowid
        conn.execute("INSERT INTO stage_template_steps (template_id, step_no, name) "
                     "VALUES (?, 2, 'Grinding & Routing')", (tmpl,))
        conn.execute("INSERT INTO drop_stage_status (drop_id, step_no, status, started_on, note) "
                     "VALUES ('SMK284-DP3', 2, 'in_progress', '2026-07-27', 'SENTINEL-284-STAGE')")
        cur = conn.execute("INSERT INTO elevation (project_code, face, name) VALUES (?, 'N', "
                           "'SMK284 North')", (PC,))
        elev = cur.lastrowid
        cur = conn.execute("INSERT INTO elevation_drop (elevation_id, idx) VALUES (?, 3)", (elev,))
        cur = conn.execute("INSERT INTO elevation_cell (drop_id, level_id, level_name, status_key, "
                           "internal_note) VALUES (?, 'L2', 'Level 2', 'in_progress', "
                           "'SENTINEL-284-INTNOTE')", (cur.lastrowid,))
        conn.execute("INSERT INTO elevation_cell_event (cell_id, from_status, to_status, reason, "
                     "actor_uid, created_at) VALUES (?, 'not_started', 'in_progress', "
                     "'SENTINEL-284-CELLREASON', ?, '2026-07-27T09:30:00')",
                     (cur.lastrowid, users["admin"]))
        sessions = {}
        for key, uid in users.items():
            tok = secrets.token_urlsafe(32)
            conn.execute("INSERT INTO sessions (id, user_id, expires_at, user_agent) "
                         "VALUES (?,?, '2099-01-01T00:00:00', 'smk284')", (tok, uid))
            sessions[key] = tok
        conn.commit()
        return users, sessions, fx
    finally:
        conn.close()


def cleanup():
    conn = db_layer.connect()
    try:
        uids = IDS["users"]
        if uids:
            ph = ",".join("?" * len(uids))
            for t, c in (("client_section_grant", "user_id"), ("pm_project_assignment", "user_id"),
                         ("sessions", "user_id"), ("login_audit", "user_id"),
                         ("audit_log", "actor_user_id"), ("dashboard_layouts", "user_id")):
                try:
                    conn.execute(f"DELETE FROM {t} WHERE {c} IN ({ph})", tuple(uids))
                except Exception as e:
                    print(f"    [cleanup] {t}: {e}")
            try:
                conn.execute(f"DELETE FROM audit_log WHERE target_type='user' AND target_id IN ({ph})",
                             tuple(str(u) for u in uids))
            except Exception as e:
                print(f"    [cleanup] audit_log targets: {e}")
            conn.execute(f"DELETE FROM users WHERE id IN ({ph})", tuple(uids))
        if IDS["photos"]:
            ph = ",".join("?" * len(IDS["photos"]))
            conn.execute(f"DELETE FROM item_visibility WHERE item_type='photo' AND item_id IN ({ph})",
                         tuple(IDS["photos"]))
            conn.execute(f"DELETE FROM field_photos WHERE id IN ({ph})", tuple(IDS["photos"]))
        if IDS["docs"]:
            ph = ",".join("?" * len(IDS["docs"]))
            conn.execute(f"DELETE FROM item_visibility WHERE item_type='document' AND item_id IN ({ph})",
                         tuple(IDS["docs"]))
            conn.execute(f"DELETE FROM project_documents WHERE id IN ({ph})", tuple(IDS["docs"]))
        conn.execute("DELETE FROM drop_stage_status WHERE drop_id='SMK284-DP3'")
        conn.execute("DELETE FROM stage_template_steps WHERE template_id IN "
                     "(SELECT template_id FROM stage_templates WHERE project_code IN (?,?))", (PC, PD))
        conn.execute("DELETE FROM elevation_cell_event WHERE cell_id IN (SELECT c.id FROM "
                     "elevation_cell c JOIN elevation_drop d ON d.id=c.drop_id JOIN elevation e "
                     "ON e.id=d.elevation_id WHERE e.project_code IN (?,?))", (PC, PD))
        conn.execute("DELETE FROM elevation_cell WHERE drop_id IN (SELECT d.id FROM elevation_drop d "
                     "JOIN elevation e ON e.id=d.elevation_id WHERE e.project_code IN (?,?))", (PC, PD))
        conn.execute("DELETE FROM elevation_drop WHERE elevation_id IN (SELECT id FROM elevation "
                     "WHERE project_code IN (?,?))", (PC, PD))
        for t in ("elevation", "report_index", "weather_log", "work_log", "drops",
                  "stage_templates"):
            conn.execute(f"DELETE FROM {t} WHERE project_code IN (?,?)", (PC, PD))
        conn.execute("DELETE FROM projects WHERE project_code IN (?,?)", (PC, PD))
        conn.commit()
        print("  [cleanup] synthetic rows removed (scoped to SMK284 ids)")
    finally:
        conn.close()


def S(sessions, key):
    s = requests.Session()
    s.cookies.set("ssc_session", sessions[key])
    return s


# The daily allowlist, enforced as recursive KEY-ABSENCE. Includes every column name a
# leak would ride in on, not just the obvious vocabulary.
BANNED_DAILY_KEYS = {
    "worker", "workers", "worker_id", "employee_id", "name", "full_name", "hours",
    "worked_hours", "headcount", "rate", "rates", "cost", "pay", "qty", "quantity",
    "sov", "note", "notes", "internal_note", "reason", "no_work_reason", "no_work_note",
    "scope_of_work", "trades_working", "trade_area", "location_elevation", "description",
    "time_in", "time_out", "caption", "report_id", "dcr_sequence", "actor_uid",
    "updated_by_uid", "uploaded_by_uid", "file_path", "thumb_path",
}


def banned_keys_found(obj, path=""):
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in BANNED_DAILY_KEYS:
                found.append(path + str(k))
            found += banned_keys_found(v, path + str(k) + ".")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += banned_keys_found(v, f"{path}{i}.")
    return found


def run():
    users, sessions, fx = seed()
    R = dict(allow_redirects=False, timeout=25)
    AD, PM = S(sessions, "admin"), S(sessions, "pm_on")
    CMIN, CFULL, CZERO = S(sessions, "cli_min"), S(sessions, "cli_full"), S(sessions, "cli_zero")
    CB, ARCH, VEND = S(sessions, "cli_b"), S(sessions, "arch"), S(sessions, "vend")

    print("\n-- matrix: fail-closed on every axis --")
    ok("matrix_unit_unknown_role_empty", portal_matrix.possible_sections("vendor") == frozenset()
       and portal_matrix.possible_sections("nope") == frozenset()
       and portal_matrix.possible_sections(None) == frozenset())
    ok("matrix_unit_client_row",
       portal_matrix.possible_sections("client") ==
       frozenset({"progress", "photos", "documents", "daily", "schedule", "drawing", "rfis"}))
    ok("matrix_unit_architect_row",
       portal_matrix.possible_sections("architect") == frozenset({"drawing", "rfis", "documents"}))
    r = VEND.get(f"{BASE}/portal/{PC}", **R)
    ok("vendor_has_no_portal_surface", r.status_code in (302, 403), f"{r.status_code}")
    r = CMIN.get(f"{BASE}/api/portal/{PC}/photos", **R)
    ok("granted_role_ungranted_section_403", r.status_code == 403, f"{r.status_code}")
    r = ARCH.get(f"{BASE}/api/portal/{PC}/documents", **R)
    ok("architect_matrix_without_grants_403", r.status_code == 403,
       "documents is in the architect ROW but no grant machinery exists — fail closed")

    print("\n-- landing: the flip, with the #267 hard-stop byte-unchanged --")
    r = CMIN.get(f"{BASE}/welcome", **R)
    ok("granted_welcome_forwards_to_shell", r.status_code == 302
       and r.headers.get("Location", "").endswith(f"/portal/{PC}"),
       f"{r.status_code} -> {r.headers.get('Location')}")
    r = CMIN.get(f"{BASE}/portal", **R)
    ok("classic_portal_forwards_to_shell", r.status_code == 302
       and r.headers.get("Location", "").endswith(f"/portal/{PC}"),
       f"{r.status_code} -> {r.headers.get('Location')}")
    r = CMIN.get(f"{BASE}/projects/{PC}", **R)
    ok("granted_client_contained_off_internal_pages", r.status_code == 302
       and r.headers.get("Location", "").endswith(f"/portal/{PC}"), f"{r.status_code}")
    r = CZERO.get(f"{BASE}/welcome", **R)
    ok("zero_grant_welcome_200", r.status_code == 200, f"{r.status_code}")
    r = CZERO.get(f"{BASE}/portal/{PC}", **R)
    ok("zero_grant_shell_redirects_welcome", r.status_code == 302
       and r.headers.get("Location", "").endswith("/welcome"), f"{r.status_code}")
    r = CZERO.get(f"{BASE}/api/portal/{PC}/progress", **R)
    ok("zero_grant_api_403", r.status_code == 403, f"{r.status_code}")
    r = CZERO.get(f"{BASE}/api/portal/context", **R)
    ok("zero_grant_classic_api_403", r.status_code == 403, f"{r.status_code}")
    r = ARCH.get(f"{BASE}/portal/{PC}", **R)
    ok("architect_landing_unchanged", r.status_code == 302
       and r.headers.get("Location", "").endswith("/drawing-markup"), f"{r.status_code}")
    r = PM.get(f"{BASE}/portal/{PC}", **R)
    ok("internal_role_keeps_internal_shell", r.status_code == 200
       and f"/api/projects/{PC}" in r.text and 'data-portal-nav=' not in markup(r.text),
       f"{r.status_code}")

    print("\n-- nav-from-grants: exact shapes, zero internal items --")
    shapes = (("cli_min", CMIN, ["progress", "daily"]),
              ("cli_full", CFULL, ["progress", "photos", "documents"]))
    pages = {}
    for label, sess, want in shapes:
        r = sess.get(f"{BASE}/portal/{PC}", **R)
        pages[label] = r.content if r.status_code == 200 else b""
        m = markup(r.text if r.status_code == 200 else "")
        navs = re.findall(r'data-portal-nav="(\w+)"', m)
        views = re.findall(r'data-portal-view="(\w+)"', m)
        ok(f"{label}_shell_200", r.status_code == 200, f"{r.status_code}")
        ok(f"{label}_nav_exact", navs == want, f"navs={navs} want={want}")
        ok(f"{label}_views_exact", views == want, f"views={views}")
        ok(f"{label}_zero_internal_nav", 'data-view="' not in m
           and not re.search(r"<!--\s*SECTION:", m) and "PORTAL_SECTION" not in m,
           "internal nav item / marker soup reached an external DOM")
        ok(f"{label}_no_drawing_or_rfis", "drawing" not in navs and "rfis" not in navs)

    print("\n-- payloads: right-subset by id, registered fields only --")
    r = CFULL.get(f"{BASE}/api/portal/{PC}/photos", **R)
    ids = [x["id"] for x in (r.json().get("data", {}) or {}).get("photos", [])] if r.status_code == 200 else []
    ok("photos_exactly_shared_own_project", ids == [fx["p_shared"]],
       f"{r.status_code} ids={ids} want=[{fx['p_shared']}]")
    if r.status_code == 200 and (r.json()["data"]["photos"] or [None])[0]:
        ok("photos_fields_registered_only",
           set((r.json()["data"]["photos"] or [{}])[0]) <= set(reg.DATASETS["portal.photo"]))
    r = CFULL.get(f"{BASE}/api/portal/{PC}/documents", **R)
    dids = [x["id"] for x in (r.json().get("data", {}) or {}).get("documents", [])] if r.status_code == 200 else []
    ok("documents_exactly_shared_own_project", dids == [fx["d_shared"]],
       f"{r.status_code} ids={dids} want=[{fx['d_shared']}]")
    r = CFULL.get(f"{BASE}/api/portal/{PC}/progress", **R)
    d = r.json().get("data", {}) if r.status_code == 200 else {}
    ok("progress_fields_registered_only",
       set(d.get("progress", {})) <= set(reg.DATASETS["health.progress"])
       and set(d.get("summary", {})) <= set(reg.DATASETS["portal.progress_summary"]),
       str(d))

    print("\n-- daily: the allowlist as recursive key-absence --")
    r = CMIN.get(f"{BASE}/api/portal/{PC}/daily", **R)
    ok("daily_200", r.status_code == 200, f"{r.status_code}")
    days = (r.json().get("data", {}) or {}).get("days", []) if r.status_code == 200 else []
    ok("daily_one_day", len(days) == 1, str(len(days)))
    if days:
        day = days[0]
        ok("daily_registered_day_fields", set(day) <= (set(reg.DATASETS["portal.daily_day"])
           | {"weather", "active_drops", "activities", "status_changes", "photos"}),
           str(sorted(day)))
        ok("daily_weather_present", (day.get("weather") or {}).get("wind") == "5-10 mph")
        ok("daily_activity_structured", day.get("activities") ==
           [{"category": "Grinding & Routing", "status": "started"}], str(day.get("activities")))
        ok("daily_change_client_vocab", day.get("status_changes") ==
           [{"drop_label": "Drop 3", "level": "Level 2", "from_label": "Not started",
             "to_label": "In progress"}], str(day.get("status_changes")))
        ok("daily_photos_shared_only", [p.get("id") for p in day.get("photos", [])] ==
           [fx["p_shared"]], str(day.get("photos")))
    body_text = r.text if r.status_code == 200 else ""
    found = banned_keys_found((r.json() if r.status_code == 200 else {}))
    ok("daily_banned_keys_absent_recursively", not found, str(found))
    ok("daily_no_sentinel_values", "SENTINEL-284" not in body_text,
       "a populated free-text column reached the client payload")

    print("\n-- preview parity: byte-for-byte page, JSON-identical payloads --")
    for label, sess, key in (("cli_min", CMIN, "cli_min"), ("cli_full", CFULL, "cli_full")):
        own = pages[label]
        pv = AD.get(f"{BASE}/portal/{PC}", params={"preview_client": users[key]}, **R)
        ok(f"parity_page_bytes_{label}", pv.status_code == 200 and pv.content == own,
           f"{pv.status_code} own={len(own)}B pv={len(pv.content)}B")
    own = CMIN.get(f"{BASE}/api/portal/{PC}/daily", **R).json()
    pv = AD.get(f"{BASE}/api/portal/{PC}/daily",
                params={"preview_client": users["cli_min"]}, **R).json()
    ok("parity_daily_json", own == pv)
    own = CFULL.get(f"{BASE}/api/portal/{PC}/photos", **R).json()
    pv = AD.get(f"{BASE}/api/portal/{PC}/photos",
                params={"preview_client": users["cli_full"]}, **R).json()
    ok("parity_photos_json", own == pv)

    print("\n-- isolation: cross-project by URL and by id; internal namespace closed --")
    for sec in ("progress", "photos", "documents", "daily"):
        r = CMIN.get(f"{BASE}/api/portal/{PD}/{sec}", **R)
        ok(f"cross_project_url_403_{sec}", r.status_code == 403, f"{r.status_code}")
    r = CFULL.get(f"{BASE}/api/portal/photos/{fx['p_other']}/thumb", **R)
    ok("cross_project_photo_by_id_404", r.status_code == 404, f"{r.status_code}")
    r = CFULL.get(f"{BASE}/api/portal/photos/{fx['p_unshared']}/thumb", **R)
    ok("unshared_photo_by_id_404", r.status_code == 404, f"{r.status_code}")
    r = CFULL.get(f"{BASE}/api/portal/documents/{fx['d_other']}/file", **R)
    ok("cross_project_document_by_id_404", r.status_code == 404, f"{r.status_code}")
    r = CFULL.get(f"{BASE}/api/portal/documents/{fx['d_unshared']}/file", **R)
    ok("unshared_document_by_id_404", r.status_code == 404, f"{r.status_code}")
    cb_ids = [x["id"] for x in (CB.get(f"{BASE}/api/portal/{PD}/photos", **R)
                                .json().get("data", {}) or {}).get("photos", [])]
    ok("other_client_sees_own_project_only", cb_ids == [fx["p_other"]], str(cb_ids))
    for path in (f"/api/projects/{PC}/health", "/api/workers", "/api/field-photos",
                 f"/api/projects/{PC}/photos", "/api/expenses"):
        r = CMIN.get(f"{BASE}{path}", **R)
        ok(f"client_internal_api_403_{path.split('/')[2]}", r.status_code == 403,
           f"{path} -> {r.status_code}")


def main():
    print(f"== #284 guard: portal flip (matrix / nav / payloads / parity / landing) ==  BASE={BASE}")
    db_url = (os.environ.get("SSC_DB_URL") or "").strip()
    print(f"   backend={'postgres' if db_layer.is_postgres() else 'sqlite'}  "
          f"SSC_DB_URL={'(set)' if db_url else '(unset)'}")
    if not db_url and os.environ.get("ALLOW_LIVE") != "1":
        print("REFUSING TO RUN: SSC_DB_URL is unset — this suite seeds users/projects "
              "and must never touch the live DB.")
        return 2
    try:
        run()
    finally:
        cleanup()
    print(f"\n== {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
