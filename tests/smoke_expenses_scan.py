"""
smoke_expenses_scan.py — Expense AI scan (#219, Batch B).

Verifies the scan PIPELINE + alias memory + graceful gating WITHOUT needing the
live model: the validate/classify/alias logic (expense_scanner.process_scan_result)
is pure and tested with canned model outputs (the fixtures the operator can later
run through the real model). The full /scan ENDPOINT (draft + multi-page storage +
needs_review + no-path-leak) is exercised separately against a temp server with
EXPENSE_SCAN_FAKE set (see the build's verify step) — here we cover:

  - pipeline: Extech canned -> classes (MASONRY x2 / DEPOSIT_REFUNDABLE / DELIVERY),
    job-cost total 1797.90 (refundable excluded), no double-count warning (lines
    sum 1953.90 == stated 1953.90);
  - validation: bad class -> OTHER + warn; bad unit -> EA + warn; double-count ->
    warning when lines sum != stated total;
  - handwritten: low-confidence lines flagged;
  - alias memory END-TO-END: correct+save a line via the REAL create endpoint
    (fires learning) -> re-scan same vendor/SKU -> corrected class auto-applied
    at confidence 1.0;
  - graceful gating: /scan with no key -> clean 503; /scan as non-admin -> 403.

Operator-live safe: synthetic SMK- vendors only; cleanup scoped to SMK-.
"""
import io
import os
import sqlite3
import sys
import json
from pathlib import Path

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = SCRIPT_DIR / "superstars.db"
FX = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPT_DIR))
import expense_scanner as scanner  # noqa: E402
from auth import hash_password  # noqa: E402

PROJECT = "FR-BX-001"
PM_EMAIL = "smk-pm-scan@superstars.local"

# taxonomy enums (mirror server)
CLASSES = ['MASONRY', 'CEMENT_MORTAR', 'CONCRETE_REPAIR', 'SEALANTS_CAULK', 'WATERPROOFING',
           'GFRC_PRECAST', 'STUCCO_EIFS', 'COATINGS_PAINT', 'ROOFING', 'ELECTRICAL',
           'EQUIP_RENTAL', 'EQUIP_PURCHASE', 'SCAFFOLD_ACCESS', 'TOOLS_CONSUMABLES',
           'FASTENERS_HARDWARE', 'PPE_SAFETY', 'DUMPSTER_DISPOSAL', 'FUEL_VEHICLE',
           'DELIVERY_FREIGHT', 'PERMITS_FEES', 'SUBCONTRACTOR', 'DEPOSIT_REFUNDABLE',
           'CREDIT_RETURN', 'OTHER']
UNITS = ['PC', 'EA', 'bag', 'cube', 'pallet', 'tube', 'sausage', 'case', 'box', 'bucket', 'pail',
         'gallon', 'roll', 'board', 'SF', 'LF', 'lb', 'ton', 'day', 'week', 'month', 'pull', 'LS']

PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return cond


def db():
    c = sqlite3.connect(str(DB_PATH), timeout=60.0)
    c.row_factory = sqlite3.Row
    return c


def main():
    print("== #219 Expense AI-scan smoke ==")

    # ---- 1) PIPELINE: Extech canned ----
    raw = json.loads((FX / "extech_scan_result.json").read_text(encoding="utf-8"))
    p = scanner.process_scan_result(raw, CLASSES, UNITS,
                                    refundable_classes={'DEPOSIT_REFUNDABLE'},
                                    ooc_classes={'DEPOSIT_REFUNDABLE', 'CREDIT_RETURN'})
    classes = [l['product_class'] for l in p['lines']]
    ok("extech_4_lines", len(p['lines']) == 4, str(len(p['lines'])))
    ok("extech_classes", classes == ['MASONRY', 'MASONRY', 'DEPOSIT_REFUNDABLE', 'DELIVERY_FREIGHT'], str(classes))
    ok("extech_total_excl_refundable", abs(p['total'] - 1797.90) < 0.005, f"total={p['total']}")
    dep = next(l for l in p['lines'] if l['product_class'] == 'DEPOSIT_REFUNDABLE')
    ok("extech_deposit_refundable_ooc", dep['is_refundable'] == 1 and dep['out_of_cost'] == 1)
    ok("extech_no_doublecount_warning", not any('double' in w or 'missed' in w for w in p['warnings']),
       f"sum_all={p['lines_sum_all']} stated={raw['stated_total']} warns={p['warnings']}")
    ok("extech_lines_sum_matches_stated", abs(p['lines_sum_all'] - 1953.90) < 0.005, str(p['lines_sum_all']))

    # ---- 2) VALIDATION: bad class + bad unit coerced + flagged ----
    bad = {"vendor": "X", "doc_type": "Receipt", "doc_number": "1", "order_number": None,
           "expense_date": "2026-05-01", "stated_total": 10.0, "lines": [
               {"description": "weird", "qty": 1, "unit": "frobnits", "unit_price": 10, "extended_price": 10,
                "product_class": "NOT_A_CLASS", "is_refundable": False, "confidence": 0.9}]}
    pb = scanner.process_scan_result(bad, CLASSES, UNITS)
    ok("coerce_bad_class_to_OTHER", pb['lines'][0]['product_class'] == 'OTHER')
    ok("coerce_bad_unit_to_EA", pb['lines'][0]['unit'] == 'EA')
    ok("coercion_warns", len([w for w in pb['warnings'] if 'Unknown' in w]) == 2, str(pb['warnings']))

    # ---- 3) DOUBLE-COUNT detection: lines sum != stated -> warning ----
    dbl = {"vendor": "X", "doc_type": "Receipt", "doc_number": "2", "order_number": None,
           "expense_date": "2026-05-01", "stated_total": 100.0, "lines": [
               {"description": "a", "qty": 1, "unit": "EA", "unit_price": 100, "extended_price": 100,
                "product_class": "MASONRY", "is_refundable": False, "confidence": 0.9},
               {"description": "page subtotal double-counted", "qty": 1, "unit": "EA", "unit_price": 100,
                "extended_price": 100, "product_class": "MASONRY", "is_refundable": False, "confidence": 0.9}]}
    pd = scanner.process_scan_result(dbl, CLASSES, UNITS)
    ok("doublecount_warns", any('double' in w or 'missed' in w for w in pd['warnings']), str(pd['warnings']))

    # ---- 4) HANDWRITTEN: low-confidence lines flagged ----
    hw = json.loads((FX / "handwritten_scan_result.json").read_text(encoding="utf-8"))
    ph = scanner.process_scan_result(hw, CLASSES, UNITS)
    low = [l for l in ph['lines'] if l['low_confidence']]
    ok("handwritten_flags_low_conf", len(low) >= 2 and ph['low_confidence_count'] >= 2,
       f"low={len(low)} count={ph['low_confidence_count']}")
    ok("handwritten_no_crash", isinstance(ph['total'], float))

    # ---- 5) ALIAS MEMORY end-to-end (learn via real endpoint -> override) ----
    vendor = "SMK-AliasVendor"
    sku = "SMK-SKU-1"
    # 5a. first "scan": no alias -> model's OTHER stays OTHER
    raw1 = {"vendor": vendor, "doc_type": "Receipt", "doc_number": "SMK-A1", "order_number": None,
            "expense_date": "2026-05-02", "stated_total": 50.0, "lines": [
                {"item_id": sku, "description": "mystery block", "qty": 10, "unit": "PC", "unit_price": 5,
                 "extended_price": 50, "product_class": "OTHER", "is_refundable": False, "confidence": 0.4}]}
    pre = scanner.process_scan_result(raw1, CLASSES, UNITS, alias_lookup={})
    ok("alias_pre_is_OTHER_lowconf", pre['lines'][0]['product_class'] == 'OTHER' and pre['lines'][0]['low_confidence'])
    # 5b. user corrects to MASONRY + saves via the REAL create endpoint -> learning fires
    create = requests.post(f"{BASE}/api/projects/{PROJECT}/expenses", json={
        "vendor": vendor, "doc_number": "SMK-A1", "expense_date": "2026-05-02", "category": "Materials",
        "status": "reviewed", "lines": [
            {"item_id": sku, "description": "mystery block", "product_class": "MASONRY",
             "normalized_product": "SMK Corrected Block", "qty": 10, "unit": "PC", "unit_price": 5,
             "extended_price": 50}]}, timeout=20)
    ok("alias_create_201", create.status_code == 201, f"HTTP {create.status_code}")
    conn = db()
    arow = conn.execute("SELECT product_class, normalized_product FROM expense_class_alias WHERE vendor=? AND item_key=?",
                        (vendor, sku.lower())).fetchone()
    conn.close()
    ok("alias_learned_row", arow is not None and arow["product_class"] == "MASONRY",
       f"alias={dict(arow) if arow else None}")
    # 5c. re-scan same vendor/SKU -> alias override applies @1.0
    alias_lookup = {sku.lower(): {"product_class": arow["product_class"], "normalized_product": arow["normalized_product"]}} if arow else {}
    post = scanner.process_scan_result(raw1, CLASSES, UNITS, alias_lookup=alias_lookup)
    l0 = post['lines'][0]
    ok("alias_override_applies", l0['product_class'] == 'MASONRY' and l0['confidence'] == 1.0 and l0['alias_applied'],
       f"class={l0['product_class']} conf={l0['confidence']} applied={l0['alias_applied']}")
    ok("alias_override_normalized", l0['normalized_product'] == 'SMK Corrected Block', str(l0['normalized_product']))

    # ---- 6) GATING: /scan no-key 503 (server Path A) + non-admin 403 ----
    png = b'\x89PNG\r\n\x1a\n' + b'0' * 40
    r = requests.post(f"{BASE}/api/expenses/scan",
                      files={"files": ("r.png", io.BytesIO(png), "image/png")}, timeout=20)
    ok("scan_no_key_503", r.status_code == 503 and r.json().get("ai_available") is False, f"HTTP {r.status_code}")
    # non-admin pm -> 403
    conn = db()
    if not conn.execute("SELECT 1 FROM users WHERE email=?", (PM_EMAIL,)).fetchone():
        conn.execute("INSERT INTO users (email,password_hash,role,full_name,is_active) VALUES (?,?,'pm','SMK PM',1)",
                     (PM_EMAIL, hash_password("pw")))
    else:
        conn.execute("UPDATE users SET role='pm',password_hash=?,is_active=1 WHERE email=?", (hash_password("pw"), PM_EMAIL))
    conn.commit(); conn.close()
    s = requests.Session(); s.post(f"{BASE}/api/auth/login", json={"email": PM_EMAIL, "password": "pw"}, timeout=10)
    r403 = s.post(f"{BASE}/api/expenses/scan", files={"files": ("r.png", io.BytesIO(png), "image/png")}, timeout=10)
    ok("scan_non_admin_403", r403.status_code == 403, f"HTTP {r403.status_code}")

    # ---- cleanup (scoped to SMK-) ----
    conn = db()
    ids = [r[0] for r in conn.execute("SELECT id FROM expenses WHERE vendor LIKE 'SMK-%'").fetchall()]
    if ids:
        qm = ",".join("?" * len(ids))
        conn.execute(f"DELETE FROM expense_line_items WHERE expense_id IN ({qm})", ids)
        conn.execute(f"DELETE FROM expenses WHERE id IN ({qm})", ids)
    conn.execute("DELETE FROM expense_class_alias WHERE vendor LIKE 'SMK-%'")
    conn.execute("DELETE FROM users WHERE email=?", (PM_EMAIL,))
    conn.commit()
    residue = conn.execute("SELECT COUNT(*) FROM expenses WHERE vendor LIKE 'SMK-%'").fetchone()[0]
    ares = conn.execute("SELECT COUNT(*) FROM expense_class_alias WHERE vendor LIKE 'SMK-%'").fetchone()[0]
    conn.close()
    ok("cleanup_zero_residue", residue == 0 and ares == 0, f"exp={residue} alias={ares}")

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
