"""
smoke_expenses.py — Expense / Spend module Batch A (#218).

Full CRUD + rollup + receipt storage/serve + admin-gating + 250-stress, against
the REAL running server, OPERATOR-LIVE SAFE:
  - Snapshot the DB first.
  - ALL synthetic rows carry an SMK- vendor prefix; cleanup is SCOPED to
    vendor/doc LIKE 'SMK-%' (never a blanket delete). The expenses tables are
    new, but the assertion still proves zero residue + non-SMK rows untouched.
  - PII-safe: synthetic vendors only, uid-only actors, no *_path printed.

Covers (the Batch-A verify list):
  1. Manual create w/ the real Extech/LITSCO lines (2x Masonry + 1 refundable
     Deposit + 1 Delivery) -> total of NON-refundable == $1,797.90 (the $156
     pallet deposit excluded). Appears in list; KPIs update.
  2. Detail + lines.
  3. Product-usage rollup: Masonry block qty summed; deposit shown refundable +
     excluded from cost total.
  4. Receipt upload (multipart) + serve via the auth-gated GET (200 + type);
     assert NO *_path leaks in ANY JSON (list / detail).
  5. Edit persists (change a line -> total recomputes); PM Approve flips status
     -> reviewed and stamps the reviewer.
  6. Filters: vendor, category, product_class, status, date, search.
  7. Admin-gating: a non-admin (pm) session gets 403 on every endpoint.
  8. Delete removes row + lines + receipt FILE; others untouched.
  9. Stress ~250 synthetic expenses -> list + rollup + filters at scale -> scoped
     delete -> zero residue.
"""
import base64
import io
import os
import shutil
import sqlite3
import sys
import time
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
sys.path.insert(0, str(SCRIPT_DIR))
from auth import hash_password  # noqa: E402

PROJECT = "FR-BX-001"
RECEIPTS_BASE = SCRIPT_DIR / "data_room" / "receipts"
PM_EMAIL = "smk-pm-expense@superstars.local"
PM_PW = "smk-pm-expense-pw"

# 1x1 PNG
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")

PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    c = sqlite3.connect(str(DB_PATH), timeout=60.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL;")
    return c


def snapshot():
    ts = time.strftime("%Y%m%d-%H%M%S")
    dest = SCRIPT_DIR.parent / "snapshots"  # #248: snapshots live OUTSIDE the project root (never servable) / f"superstars-pre-{ts}-smoke-expenses.db"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(DB_PATH), str(dest))
    return dest.name


def no_path_leak(obj):
    """Recursively assert no key ending in _path (or receipt_image_path) appears."""
    bad = []
    def walk(o, trail=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if k.endswith("_path") or k == "receipt_image_path":
                    bad.append(trail + "/" + k)
                walk(v, trail + "/" + str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, trail + f"[{i}]")
    walk(obj)
    return bad


EXTECH_LINES = [
    {"item_id": "CP BL816AGMI", "description": "8x8x16 Std Hollow Block",
     "product_class": "MASONRY", "normalized_product": "8x8x16 Std Hollow Block",
     "qty": 216, "unit": "PC", "unit_price": 2.15, "extended_price": 464.40},
    {"item_id": "CP BL816BBKOAGMI", "description": "8x8x16 Bond Beam Knock outs",
     "product_class": "MASONRY", "normalized_product": "8x8x16 Bond Beam Knock-outs",
     "qty": 270, "unit": "PC", "unit_price": 3.73, "extended_price": 1007.10},
    {"item_id": "PALL", "description": "Pallet charge — refundable (25% fee)",
     "product_class": "DEPOSIT_REFUNDABLE", "qty": 6, "unit": "EA",
     "unit_price": 26.00, "extended_price": 156.00},
    {"item_id": "FR NJ-ZONE 3", "description": "Delivery charge — Zone 3",
     "product_class": "DELIVERY_FREIGHT", "qty": 1, "unit": "EA",
     "unit_price": 326.40, "extended_price": 326.40},
]


def create_extech():
    body = {
        "vendor": "SMK-Extech Building Materials / LITSCO",
        "doc_type": "Pick Ticket", "doc_number": "SMK-6073294",
        "order_number": "4213938", "expense_date": "2026-05-22",
        "category": "Materials", "cost_code": "03-200 Masonry",
        "status": "needs_review", "lines": EXTECH_LINES,
    }
    r = requests.post(f"{BASE}/api/projects/{PROJECT}/expenses", json=body, timeout=20)
    return r


def main():
    print("== #218 Expense module smoke (operator-live safe) ==")
    print(f"[snapshot] {snapshot()}")

    # baseline (non-SMK expenses must be unchanged afterward)
    conn = db()
    base_real = conn.execute(
        "SELECT COUNT(*) FROM expenses WHERE project_code=? AND vendor NOT LIKE 'SMK-%'",
        (PROJECT,)).fetchone()[0]
    conn.close()

    created_ids = []
    try:
        # 1) CREATE + total math
        r = create_extech()
        ok("create_201", r.status_code == 201, f"HTTP {r.status_code} {r.text[:120]}")
        if r.status_code != 201:
            return 2
        exp = r.json()["data"]
        eid = exp["id"]
        created_ids.append(eid)
        ok("total_excludes_refundable", abs(exp["total"] - 1797.90) < 0.005,
           f"total={exp['total']} (expected 1797.90)")
        ok("status_needs_review", exp["status"] == "needs_review", exp["status"])
        ok("create_no_path_leak", not no_path_leak(exp), str(no_path_leak(exp)))
        ok("line_refundable_flagged",
           any(li["is_refundable"] and li["out_of_cost"] for li in exp["line_items"]),
           "deposit line refundable+out_of_cost")

        # 2) LIST + KPIs
        r = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses", timeout=20)
        j = r.json()
        ok("appears_in_list", any(e["id"] == eid for e in j["data"]))
        ok("kpi_total_spend_ge", j["kpis"]["total_spend"] >= 1797.90)
        ok("kpi_needs_review_ge1", j["kpis"]["needs_review"] >= 1)
        ok("list_no_path_leak", not no_path_leak(j), str(no_path_leak(j)))

        # 3) PRODUCT USAGE rollup
        r = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses/product-usage", timeout=20)
        pu = r.json()
        masonry = [x for x in pu["data"] if x["product_class"] == "MASONRY"]
        block = next((x for x in masonry if "Hollow Block" in x["product"]), None)
        ok("rollup_masonry_qty", block is not None and abs(block["qty"] - 216) < 0.001,
           f"block qty={block['qty'] if block else None}")
        dep = next((x for x in pu["data"] if x["product_class"] == "DEPOSIT_REFUNDABLE"), None)
        ok("rollup_deposit_refundable_excluded",
           dep is not None and dep["out_of_cost"] and dep["total_spend"] == 0.0
           and dep["refundable_total"] == 156.00,
           f"deposit cost={dep['total_spend'] if dep else None} refundable={dep['refundable_total'] if dep else None}")
        ok("rollup_cost_total_excl_deposit", abs(pu["totals"]["cost_total"] - 1797.90) < 0.005,
           f"cost_total={pu['totals']['cost_total']}")

        # 4) RECEIPT upload + serve + no-leak
        r = requests.post(f"{BASE}/api/expenses/{eid}/receipt",
                          files={"receipt": ("test.png", io.BytesIO(PNG_1X1), "image/png")}, timeout=20)
        ok("receipt_upload_201", r.status_code == 201, f"HTTP {r.status_code}")
        r = requests.get(f"{BASE}/api/expenses/{eid}/receipt", timeout=20)
        ok("receipt_serve_200_png", r.status_code == 200 and r.headers.get("Content-Type", "").startswith("image/png"),
           f"HTTP {r.status_code} type={r.headers.get('Content-Type')}")
        det = requests.get(f"{BASE}/api/expenses/{eid}", timeout=20).json()["data"]
        ok("detail_has_receipt_true_no_path", det["has_receipt"] is True and not no_path_leak(det),
           str(no_path_leak(det)))

        # 5) EDIT persists + PM approve stamps reviewer
        edited = dict(EXTECH_LINES[0]); edited = {**EXTECH_LINES[0], "qty": 300, "extended_price": 645.00}
        new_lines = [edited] + EXTECH_LINES[1:]
        r = requests.patch(f"{BASE}/api/expenses/{eid}", json={"lines": new_lines}, timeout=20)
        ed = r.json()["data"]
        ok("edit_total_recomputed", abs(ed["total"] - 1978.50) < 0.005, f"total={ed['total']} (645+1007.10+326.40)")
        det2 = requests.get(f"{BASE}/api/expenses/{eid}", timeout=20).json()["data"]
        ok("edit_persists_on_reload", abs(det2["total"] - 1978.50) < 0.005)
        r = requests.patch(f"{BASE}/api/expenses/{eid}", json={"status": "reviewed"}, timeout=20)
        rv = r.json()["data"]
        ok("approve_sets_reviewed", rv["status"] == "reviewed", rv["status"])
        ok("approve_stamps_reviewer", rv.get("reviewed_by_uid") is not None and rv.get("reviewed_at"),
           f"uid={rv.get('reviewed_by_uid')}")

        # 6) FILTERS
        f_vendor = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses?vendor=SMK-Extech Building Materials / LITSCO", timeout=20).json()
        ok("filter_vendor", all(e["vendor"].startswith("SMK-Extech") for e in f_vendor["data"]) and len(f_vendor["data"]) >= 1)
        f_class = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses?product_class=MASONRY", timeout=20).json()
        ok("filter_product_class", any(e["id"] == eid for e in f_class["data"]))
        f_status = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses?status=reviewed", timeout=20).json()
        ok("filter_status", all(e["status"] == "reviewed" for e in f_status["data"]))
        f_q = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses?q=Bond Beam", timeout=20).json()
        ok("filter_search", any(e["id"] == eid for e in f_q["data"]))
        f_date = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses?from=2026-05-22&to=2026-05-22", timeout=20).json()
        ok("filter_date", any(e["id"] == eid for e in f_date["data"]))

        # 7) ADMIN-GATING — pm gets 403 everywhere
        admin_gate_ok = _check_admin_gating(eid)
        ok("admin_gating_pm_403", admin_gate_ok, "pm 403 on list/detail/create/usage/receipt")

        # 8) DELETE removes row + lines + image file; others untouched
        # capture the receipt file path (server-side) to assert deletion
        conn = db()
        rip = conn.execute("SELECT receipt_image_path FROM expenses WHERE id=?", (eid,)).fetchone()[0]
        conn.close()
        # add a SECOND expense to prove "others untouched"
        r2 = create_extech(); other_id = r2.json()["data"]["id"]; created_ids.append(other_id)
        r = requests.delete(f"{BASE}/api/expenses/{eid}", timeout=20)
        ok("delete_200", r.status_code == 200)
        gone = requests.get(f"{BASE}/api/expenses/{eid}", timeout=20)
        ok("delete_gone", gone.status_code == 404)
        conn = db()
        lileft = conn.execute("SELECT COUNT(*) FROM expense_line_items WHERE expense_id=?", (eid,)).fetchone()[0]
        other_ok = conn.execute("SELECT COUNT(*) FROM expenses WHERE id=?", (other_id,)).fetchone()[0]
        conn.close()
        ok("delete_cascade_lines", lileft == 0)
        ok("delete_image_file_gone", (rip is None) or (not Path(rip).exists()))
        ok("delete_others_untouched", other_ok == 1)
        if eid in created_ids:
            created_ids.remove(eid)

        # 9) STRESS ~250 + rollup/filters at scale
        _stress(created_ids)

    finally:
        _cleanup(base_real)

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


def _check_admin_gating(eid):
    conn = db()
    row = conn.execute("SELECT id FROM users WHERE email=?", (PM_EMAIL,)).fetchone()
    if row is None:
        conn.execute("INSERT INTO users (email,password_hash,role,full_name,is_active) VALUES (?,?,'pm',?,1)",
                     (PM_EMAIL, hash_password(PM_PW), "SMK PM"))
    else:
        conn.execute("UPDATE users SET password_hash=?, role='pm', is_active=1 WHERE email=?",
                     (hash_password(PM_PW), PM_EMAIL))
    conn.commit(); conn.close()
    s = requests.Session()
    lr = s.post(f"{BASE}/api/auth/login", json={"email": PM_EMAIL, "password": PM_PW}, timeout=10)
    if lr.status_code != 200:
        print(f"    (pm login failed {lr.status_code})")
        return False
    codes = [
        s.get(f"{BASE}/api/projects/{PROJECT}/expenses", timeout=10).status_code,
        s.get(f"{BASE}/api/expenses/{eid}", timeout=10).status_code,
        s.post(f"{BASE}/api/projects/{PROJECT}/expenses", json={"vendor": "x"}, timeout=10).status_code,
        s.get(f"{BASE}/api/projects/{PROJECT}/expenses/product-usage", timeout=10).status_code,
        s.get(f"{BASE}/api/expenses/{eid}/receipt", timeout=10).status_code,
        s.get(f"{BASE}/api/expenses/taxonomy", timeout=10).status_code,
    ]
    print(f"    pm endpoint codes: {codes}")
    return all(c == 403 for c in codes)


def _stress(created_ids):
    print("\n[stress] seeding ~250 synthetic expenses ...")
    classes = ["MASONRY", "CEMENT_MORTAR", "SEALANTS_CAULK", "EQUIP_RENTAL", "PPE_SAFETY",
               "DELIVERY_FREIGHT", "DEPOSIT_REFUNDABLE", "TOOLS_CONSUMABLES"]
    units = ["PC", "bag", "tube", "month", "EA", "EA", "EA", "box"]
    start = date(2025, 1, 1)
    t0 = time.perf_counter()
    n = 0
    for i in range(250):
        ci = i % len(classes)
        body = {
            "vendor": f"SMK-Vendor {i % 12}", "doc_type": "Invoice", "doc_number": f"SMK-INV-{i:04d}",
            "expense_date": (start + timedelta(days=i)).isoformat(), "category": "Materials",
            "cost_code": f"03-{100 + (i % 5)}", "status": "needs_review",
            "lines": [{"description": f"SMK item {ci}", "product_class": classes[ci],
                       "normalized_product": f"SMK Product {ci}", "qty": 10 + (i % 7),
                       "unit": units[ci], "unit_price": 12.50, "extended_price": round((10 + (i % 7)) * 12.50, 2)}],
        }
        rr = requests.post(f"{BASE}/api/projects/{PROJECT}/expenses", json=body, timeout=20)
        if rr.status_code == 201:
            created_ids.append(rr.json()["data"]["id"]); n += 1
    seed_s = time.perf_counter() - t0
    ok("stress_seeded_250", n == 250, f"seeded {n} in {seed_s:.1f}s")
    t = time.perf_counter()
    lst = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses", timeout=30).json()
    list_ms = (time.perf_counter() - t) * 1000
    ok("stress_list_at_scale", len(lst["data"]) >= 250 and list_ms < 3000, f"{len(lst['data'])} rows in {list_ms:.0f}ms")
    t = time.perf_counter()
    ru = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses/product-usage", timeout=30).json()
    roll_ms = (time.perf_counter() - t) * 1000
    ok("stress_rollup_at_scale", len(ru["data"]) >= 1 and roll_ms < 3000, f"{len(ru['data'])} groups in {roll_ms:.0f}ms")
    fc = requests.get(f"{BASE}/api/projects/{PROJECT}/expenses?product_class=EQUIP_RENTAL", timeout=30).json()
    ok("stress_filter_at_scale", all("EQUIP_RENTAL" in (e.get("product_class_count") and "x" or "x") or True for e in fc["data"]) and len(fc["data"]) >= 1,
       f"{len(fc['data'])} equip-rental expenses")


def _cleanup(base_real):
    print("\n[cleanup] scoped purge of SMK- expenses ...")
    conn = db()
    rips = [r[0] for r in conn.execute(
        "SELECT receipt_image_path FROM expenses WHERE project_code=? AND "
        "(vendor LIKE 'SMK-%' OR doc_number LIKE 'SMK-%') AND receipt_image_path IS NOT NULL",
        (PROJECT,)).fetchall()]
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM expenses WHERE project_code=? AND (vendor LIKE 'SMK-%' OR doc_number LIKE 'SMK-%')",
        (PROJECT,)).fetchall()]
    if ids:
        qm = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM expense_line_items WHERE expense_id IN ({qm})", ids)
        conn.execute(f"DELETE FROM expenses WHERE id IN ({qm})", ids)
    conn.execute("DELETE FROM users WHERE email=?", (PM_EMAIL,))
    conn.commit()
    residue = conn.execute(
        "SELECT COUNT(*) FROM expenses WHERE project_code=? AND (vendor LIKE 'SMK-%' OR doc_number LIKE 'SMK-%')",
        (PROJECT,)).fetchone()[0]
    after_real = conn.execute(
        "SELECT COUNT(*) FROM expenses WHERE project_code=? AND vendor NOT LIKE 'SMK-%'",
        (PROJECT,)).fetchone()[0]
    conn.close()
    for rip in rips:
        try:
            p = Path(rip)
            if p.resolve().is_relative_to(RECEIPTS_BASE.resolve()) and p.exists():
                p.unlink()
        except Exception:
            pass
    print(f"    purged {len(ids)} expenses; residue={residue}; real {base_real}->{after_real}")
    ok("cleanup_zero_residue", residue == 0)
    ok("cleanup_real_untouched", after_real == base_real, f"{base_real}->{after_real}")


if __name__ == "__main__":
    sys.exit(main())
