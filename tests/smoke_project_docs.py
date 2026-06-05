"""
smoke_project_docs.py — Project Documents Batch A (#229).

Compliance checklist + readiness rollup + single/bulk upload + gated file serve +
edit/delete/superseded + ~100 stress, against the running server. OPERATOR-LIVE
SAFE: a synthetic project SMK-PROJDOCS + synthetic files only; cleanup is SCOPED to
that project (rows + the on-disk file dir). PII / path discipline: asserts NO *_path
in any payload; the global document_requirements (27) are read-only and left intact.
"""
import io
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
PROJ = "SMK-PROJDOCS"
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    c = sqlite3.connect(str(DB_PATH), timeout=60.0)
    c.row_factory = sqlite3.Row
    return c


def pdf(name):
    return io.BytesIO(b"%PDF-1.4 " + name.encode() + b" %%EOF")


def checklist():
    return requests.get(f"{BASE}/api/projects/{PROJ}/documents", timeout=20).json()["data"]


def upload(name, cat, rk=None, eff="2026-05-01", exp=None):
    data = {"category": cat, "title": name, "effective_date": eff}
    if rk:
        data["requirement_key"] = rk
    if exp:
        data["expiry_date"] = exp
    return requests.post(f"{BASE}/api/projects/{PROJ}/documents",
                         files={"file": (name, pdf(name), "application/pdf")}, data=data, timeout=20)


def main():
    print("== #229 Project Documents smoke ==")
    conn = db()
    conn.execute("INSERT OR IGNORE INTO projects (project_code,name,status) VALUES (?,?,?)",
                 (PROJ, "SMK ProjDocs", "active"))
    conn.commit()
    base_req = conn.execute("SELECT COUNT(*) FROM document_requirements").fetchone()[0]
    conn.close()

    # ---- 1) checklist: 27 required, all missing ----
    cl = checklist()
    ok("requirements_seeded_27", cl["readiness"]["required_total"] == 27, str(cl["readiness"]["required_total"]))
    ok("checklist_6_categories", len(cl["categories"]) == 6)
    ok("all_missing_initially",
       cl["readiness"]["missing"] == 27 and cl["readiness"]["on_file"] == 0 and cl["readiness"]["pct"] == 0)

    # ---- 2) single upload -> on_file + ticks the required item + NO *_path ----
    r = upload("site-safety-plan.pdf", "SAFETY", "site_safety_plan", eff="2026-06-01")
    ok("upload_201", r.status_code == 201, f"HTTP {r.status_code}")
    doc = r.json()["data"]
    did = doc["id"]
    ok("upload_status_on_file", doc["status"] == "on_file")
    ok("upload_no_path_key", not any("path" in k.lower() for k in doc.keys()), str(sorted(doc.keys())))
    txt = requests.get(f"{BASE}/api/projects/{PROJ}/documents", timeout=20).text
    ok("checklist_no_path_substring",
       "file_path" not in txt and "data_room" not in txt and "project_docs" not in txt.lower())
    cl2 = checklist()
    safety = [c for c in cl2["categories"] if c["category"] == "SAFETY"][0]
    ssp = [it for it in safety["items"] if it["requirement_key"] == "site_safety_plan"][0]
    ok("required_item_on_file", ssp["status"] == "on_file" and ssp["doc"]["effective_date"] == "2026-06-01")
    ok("readiness_incr", cl2["readiness"]["on_file"] == 1)

    # ---- 3) gated file serve + unauth 401 ----
    fr = requests.get(f"{BASE}{doc['file_url']}", timeout=10)
    ok("file_serves_gated", fr.status_code == 200 and "no-store" in fr.headers.get("Cache-Control", ""), f"HTTP {fr.status_code}")
    ok("file_unauth_401", requests.Session().get(f"{BASE}{doc['file_url']}", timeout=10).status_code == 401)
    ok("checklist_unauth_401", requests.Session().get(f"{BASE}/api/projects/{PROJ}/documents", timeout=10).status_code == 401)

    # ---- 4) expiry flags (LOCAL date math) ----
    t = date.today()
    de = upload("coi.pdf", "CONTRACTS", "coi", exp=(t + timedelta(days=15)).isoformat()).json()["data"]
    dx = upload("old-variance.pdf", "PERMITS", "after_hours", exp=(t - timedelta(days=3)).isoformat()).json()["data"]
    ok("expiring_flag", de["status"] == "expiring", de["status"])
    ok("expired_flag", dx["status"] == "expired", dx["status"])
    ok("readiness_attention_2", checklist()["readiness"]["attention"] == 2)

    # ---- 5) bulk upload + filename heuristic ----
    files = [("file_0", ("PW2-work-permit.pdf", pdf("a"), "application/pdf")),
             ("file_1", ("rope-access.pdf", pdf("b"), "application/pdf")),
             ("file_2", ("arch-revC.pdf", pdf("c"), "application/pdf"))]
    br = requests.post(f"{BASE}/api/projects/{PROJ}/documents/bulk", files=files, timeout=20).json()["data"]
    ok("bulk_3_saved", br["saved"] == 3, str(br.get("saved")))
    conn = db()
    cats = {x["file_name"]: x["category"] for x in conn.execute(
        "SELECT file_name,category FROM project_documents WHERE id IN (%s)" % ",".join("?" * len(br["ids"])),
        br["ids"]).fetchall()}
    conn.close()
    ok("bulk_heuristic", cats.get("PW2-work-permit.pdf") == "PERMITS"
       and cats.get("rope-access.pdf") == "SAFETY" and cats.get("arch-revC.pdf") == "DRAWINGS", str(cats))

    # ---- 6) edit (PATCH) persists ----
    pr = requests.patch(f"{BASE}/api/documents/{did}", json={"notes": "reviewed", "version": "v2"}, timeout=10)
    ok("patch_persists", pr.status_code == 200 and pr.json()["data"]["version"] == "v2")

    # ---- 7) superseded -> the required item reads missing again ----
    sr = requests.patch(f"{BASE}/api/documents/{de['id']}", json={"superseded": 1}, timeout=10).json()["data"]
    ok("superseded_status", sr["status"] == "superseded")
    coi = [it for c in checklist()["categories"] if c["category"] == "CONTRACTS"
           for it in c["items"] if it["requirement_key"] == "coi"][0]
    ok("superseded_unfulfills", coi["status"] == "missing")

    # ---- 8) delete -> row + file gone ----
    dl = requests.delete(f"{BASE}/api/documents/{did}", timeout=10)
    ok("delete_200", dl.status_code == 200)
    ok("delete_file_404", requests.get(f"{BASE}{doc['file_url']}", timeout=10).status_code == 404)

    # ---- 9) stress ~100 docs ----
    _stress()

    # ---- cleanup (scoped to the synthetic project) ----
    _cleanup(base_req)

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


def _stress():
    cats = ["PERMITS", "DRAWINGS", "CONTRACTS", "INSPECTIONS", "SAFETY", "CLOSEOUT"]
    files = [(f"file_{i}", (f"stress-{i}.pdf", pdf(f"s{i}"), "application/pdf")) for i in range(100)]
    form = {f"category_{i}": cats[i % 6] for i in range(100)}
    t0 = time.perf_counter()
    r = requests.post(f"{BASE}/api/projects/{PROJ}/documents/bulk", files=files, data=form, timeout=120)
    up_ms = (time.perf_counter() - t0) * 1000
    saved = r.json().get("data", {}).get("saved") if r.status_code == 201 else None
    ok("stress_bulk_100", r.status_code == 201 and saved == 100, f"{r.status_code} saved={saved} in {up_ms:.0f}ms")
    t = time.perf_counter()
    cl = checklist()
    ms = (time.perf_counter() - t) * 1000
    conn = db()
    ndocs = conn.execute("SELECT COUNT(*) FROM project_documents WHERE project_code=?", (PROJ,)).fetchone()[0]
    conn.close()
    ok("stress_checklist_perf", cl["readiness"]["required_total"] == 27 and ms < 3000,
       f"{ndocs} docs, checklist in {ms:.0f}ms")


def _cleanup(base_req):
    conn = db()
    n = conn.execute("DELETE FROM project_documents WHERE project_code=?", (PROJ,)).rowcount
    conn.execute("DELETE FROM projects WHERE project_code=?", (PROJ,))
    conn.commit()
    res = conn.execute("SELECT COUNT(*) FROM project_documents WHERE project_code=?", (PROJ,)).fetchone()[0]
    req_now = conn.execute("SELECT COUNT(*) FROM document_requirements").fetchone()[0]
    conn.close()
    pdir = SCRIPT_DIR / "data_room" / "project_docs" / PROJ
    file_residue = len(list(pdir.glob("*"))) if pdir.exists() else 0
    if pdir.exists():
        shutil.rmtree(pdir, ignore_errors=True)
    print(f"    purged {n} docs; on-disk files removed (had {file_residue})")
    ok("cleanup_zero_residue", res == 0 and not pdir.exists())
    ok("cleanup_requirements_intact", req_now == base_req == 27, f"{req_now}")


if __name__ == "__main__":
    sys.exit(main())
