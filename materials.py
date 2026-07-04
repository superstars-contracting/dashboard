"""#272a — Materials & Deliveries, Part 1: per-project catalog + delivery/pickup/
transfer ledger + EXPECTED deliveries + weekly-count reconciliation.

PRINCIPLES
  * CATALOG RULE (operator-mandated): nothing hardcoded — no material names, vendors,
    yields, or seed lists anywhere. Every project starts EMPTY; rows are created in the
    UI or copied from another project. Units REUSE the expense taxonomy's canonical
    enum (server.EXPENSE_UNITS, read lazily — one source, no second unit system).
  * ON-HAND IS DERIVED, NEVER STORED: SUM(material_txn.qty_base) — qty_base is SIGNED
    (delivery/pickup/transfer_in +; return/transfer_out/writeoff −; count_adjust is the
    signed drift). Unit conversion happens ONCE, at entry: qty_entered × pack_qty →
    qty_base when the entered unit is the purchase unit ("1 pallet" stores 56 bags,
    both kept).
  * NO FINANCIALS here — costs live in the expense module; payloads carry no cost/price
    keys (guarded). Packing slips are served ONLY by a gated by-id route (slip_path
    never in JSON — #229 pattern).
  * ROLES: operational section — admin/c_suite/pm(assigned)/super. Project-path
    endpoints inherit the central pm_scoping hook; by-id endpoints re-derive the
    project from the row and re-check pm_can_access_project (per-resource, #263).
    Clients never reach any of this (the #267/#269 containment gate).
  * AGENT-READY: expected_delivery.source is 'manual' now; the future materials@ agent
    writes source='agent' rows as Tier-B proposals with NO schema change (#272b+).
  * #272b SLOT: consumption derivation will READ this ledger + drop-plan quantities and
    fill the burn/days-left/order-by chips — additive; nothing here assumes it.

Dates LOCAL (YYYY-MM-DD). All SQL parameterized via the caller's db_layer connection —
identical on SQLite (default/production) and Postgres.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path

from flask import jsonify, request, send_file

from auth import _db, _now_iso, current_user, requires_company, requires_role
import db_layer
import pm_scoping

SCRIPT_DIR = Path(__file__).resolve().parent
_SLIP_BASE = SCRIPT_DIR / "data_room" / "material_slips"
_SLIP_EXT = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
             '.heic': 'image/heic', '.heif': 'image/heif', '.pdf': 'application/pdf'}

_MAT_ROLES = ('admin', 'c_suite', 'pm', 'super')   # operational section (#262 default)

# The ledger enum — in code, no CHECK (additive). Signs make on-hand a plain SUM.
TXN_TYPES = ("delivery", "pickup", "return", "transfer_out", "transfer_in",
             "count_adjust", "writeoff")
_TXN_SIGN = {"delivery": 1, "pickup": 1, "transfer_in": 1,
             "return": -1, "transfer_out": -1, "writeoff": -1}
# the direct log endpoint accepts only these; transfers + counts have their own
# atomic endpoints, and transfer_in/count_adjust must never be minted by hand
_DIRECT_TYPES = ("delivery", "pickup", "return", "writeoff")

EXPECTED_STATUSES = ("ordered", "confirmed", "arriving", "received", "cancelled")
_OPEN_STATUSES = ("ordered", "confirmed", "arriving")


def _units():
    """The canonical unit enum — the expense taxonomy's list, read from server lazily
    (one source of truth; lazy so there is no circular import at module load)."""
    from server import EXPENSE_UNITS
    return EXPENSE_UNITS


def _iso_date(s):
    s = (s or "").strip()
    if not s:
        return None
    datetime.strptime(s, "%Y-%m-%d")   # raises ValueError on junk — caller maps to 400
    return s


def _actor():
    return current_user() or {}


def _can_project(conn, code) -> bool:
    u = _actor()
    return pm_scoping.pm_can_access_project(u.get("role"), u.get("id"), code, conn)


# ============= ROW HELPERS =============

def _material(conn, material_id):
    return conn.execute("SELECT * FROM material WHERE id=?", (material_id,)).fetchone()


def _on_hand_map(conn, project_code) -> dict:
    rows = conn.execute(
        "SELECT material_id, SUM(qty_base) FROM material_txn WHERE project_code=? "
        "GROUP BY material_id", (project_code,)).fetchall()
    return {r[0]: round(r[1] or 0, 4) for r in rows}


def _last_delivery_map(conn, project_code) -> dict:
    """{material_id: {date, qty, vendor}} — the latest material-IN from a vendor
    (delivery or self-pickup), the field the operator explicitly asked to SEE."""
    rows = conn.execute(
        "SELECT material_id, txn_date, qty_base, vendor, id FROM material_txn "
        "WHERE project_code=? AND txn_type IN ('delivery','pickup') "
        "ORDER BY txn_date DESC, id DESC", (project_code,)).fetchall()
    out = {}
    for r in rows:
        if r[0] not in out:
            out[r[0]] = {"date": r[1], "qty": round(r[2] or 0, 4), "vendor": r[3]}
    return out


def _next_expected_map(conn, project_code) -> dict:
    """{material_id: {date, status, vendor}} — the SOONEST still-open expected delivery."""
    rows = conn.execute(
        f"SELECT material_id, expected_date, status, vendor, id FROM expected_delivery "
        f"WHERE project_code=? AND status IN ({','.join(['?']*len(_OPEN_STATUSES))}) "
        f"AND material_id IS NOT NULL ORDER BY expected_date ASC, id ASC",
        (project_code, *_OPEN_STATUSES)).fetchall()
    out = {}
    for r in rows:
        if r[0] not in out:
            out[r[0]] = {"date": r[1], "status": r[2], "vendor": r[3]}
    return out


def _mat_public(m, on_hand, last_delivery, next_expected) -> dict:
    return {
        "id": m["id"], "name": m["name"], "category": m["category"],
        "purchase_unit": m["purchase_unit"], "base_unit": m["base_unit"],
        "pack_qty": m["pack_qty"], "default_vendor": m["default_vendor"],
        "lead_time_days": m["lead_time_days"], "pinned": bool(m["pinned"]),
        "active": bool(m["active"]),
        "on_hand": on_hand, "last_delivery": last_delivery, "next_expected": next_expected,
    }


def _txn_public(r) -> dict:
    """Curated ledger row — NO slip_path, NO cost keys (there are none by design)."""
    return {
        "id": r["id"], "material_id": r["material_id"],
        "material_name": r["material_name"] if "material_name" in r.keys() else None,
        "txn_type": r["txn_type"], "qty_base": r["qty_base"],
        "qty_entered": r["qty_entered"], "unit_entered": r["unit_entered"],
        "vendor": r["vendor"], "txn_date": r["txn_date"], "note": r["note"],
        "expense_link_id": r["expense_link_id"],
        "has_slip": bool(r["slip_path"]),
        "slip_url": (f"/api/material-txns/{r['id']}/slip" if r["slip_path"] else None),
        "created_at": r["created_at"],
    }


def _expected_public(r, mat_name=None) -> dict:
    return {
        "id": r["id"], "material_id": r["material_id"], "material_name": mat_name,
        "vendor": r["vendor"], "description": r["description"],
        "qty": r["qty"], "unit": r["unit"], "expected_date": r["expected_date"],
        "status": r["status"], "source": r["source"], "source_note": r["source_note"],
        "created_at": r["created_at"], "updated_at": r["updated_at"],
    }


def _convert(mat, qty, unit):
    """(qty_base, qty_entered, unit_entered) — conversion happens HERE, once, at entry.
    The entered unit must be the material's base unit (×1) or its purchase unit
    (×pack_qty). Anything else is a 400 (raise ValueError)."""
    try:
        q = float(qty)
    except (TypeError, ValueError):
        raise ValueError("quantity must be a number")
    if q <= 0:
        raise ValueError("quantity must be positive")
    unit = (unit or mat["base_unit"]).strip()
    if unit == mat["base_unit"]:
        return q, q, unit
    if mat["purchase_unit"] and unit == mat["purchase_unit"]:
        return q * (mat["pack_qty"] or 1), q, unit
    raise ValueError(f"unit must be {mat['base_unit']}"
                     + (f" or {mat['purchase_unit']}" if mat["purchase_unit"] else ""))


def _insert_txn(conn, project_code, material_id, txn_type, qty_base, qty_entered,
                unit_entered, vendor, txn_date, note, slip_path=None,
                expense_link_id=None):
    cur = conn.execute(
        "INSERT INTO material_txn (project_code, material_id, txn_type, qty_base, "
        "qty_entered, unit_entered, vendor, txn_date, expense_link_id, slip_path, note, "
        "created_by, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (project_code, material_id, txn_type, qty_base, qty_entered, unit_entered,
         vendor, txn_date, expense_link_id, slip_path, note,
         _actor().get("id"), _now_iso()))
    return cur.lastrowid


def _save_slip(project_code, fs):
    """Store a packing slip under data_room/material_slips/<project>/<uuid>.<ext>.
    Returns the disk path (never serialized). Raises ValueError on a bad type."""
    ext = Path(fs.filename or "slip").suffix.lower()
    if ext not in _SLIP_EXT:
        raise ValueError("slip must be a JPG, PNG, HEIC, or PDF")
    base = _SLIP_BASE.resolve()
    pdir = _SLIP_BASE / project_code
    if not pdir.resolve().is_relative_to(base):
        raise ValueError("invalid project path")
    pdir.mkdir(parents=True, exist_ok=True)
    p = pdir / f"{uuid.uuid4().hex}{ext}"
    fs.save(str(p))
    return str(p)


# ============= CATALOG =============

@requires_role(*_MAT_ROLES)
def _api_list_materials(project_code):
    """GET /api/projects/<code>/materials[?all=1] — the catalog + the two fields the
    operator asked to SEE per item: last_delivery {date,qty,vendor} and next_expected
    {date,status,vendor}, plus derived on_hand. Batched (no N+1)."""
    include_inactive = request.args.get("all") == "1"
    conn = _db()
    try:
        rows = conn.execute(
            "SELECT * FROM material WHERE project_code=? "
            + ("" if include_inactive else "AND active=1 ")
            + "ORDER BY pinned DESC, LOWER(name)", (project_code,)).fetchall()
        on_hand = _on_hand_map(conn, project_code)
        last_d = _last_delivery_map(conn, project_code)
        next_e = _next_expected_map(conn, project_code)
        mats = [_mat_public(m, on_hand.get(m["id"], 0), last_d.get(m["id"]),
                            next_e.get(m["id"])) for m in rows]
        # #272b — mapped materials gain derived burn/forecast fields; unmapped get
        # NOTHING (honest absence, never zeros pretending). Compute-on-read.
        extras = {}
        if consumption_ready(conn):
            derived, extras = _project_derivation(conn, project_code, rows, on_hand)
            for m in mats:
                if m["id"] in derived:
                    m.update(derived[m["id"]])
        return jsonify({"data": {"materials": mats,
                                 "units": list(_units()),
                                 "drivers": list(DRIVERS),
                                 "safety_default": SAFETY_DEFAULT,
                                 "pinned_count": sum(1 for m in mats if m["pinned"]),
                                 "total": len(mats),
                                 **extras}})
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_create_material(project_code):
    """POST /api/projects/<code>/materials — Add material. NOTHING is preloaded: the
    operator names it, picks units from the canonical enum, sets the pack conversion."""
    b = request.get_json(silent=True) or {}
    name = (b.get("name") or "").strip()
    base_unit = (b.get("base_unit") or "").strip()
    purchase_unit = (b.get("purchase_unit") or "").strip() or None
    category = (b.get("category") or "").strip() or None
    default_vendor = (b.get("default_vendor") or "").strip() or None
    if not name:
        return jsonify({"error": "name is required"}), 400
    units = _units()
    if base_unit not in units:
        return jsonify({"error": "base_unit must be one of the canonical units"}), 400
    if purchase_unit is not None and purchase_unit not in units:
        return jsonify({"error": "purchase_unit must be one of the canonical units"}), 400
    try:
        pack_qty = float(b.get("pack_qty") or 1)
    except (TypeError, ValueError):
        return jsonify({"error": "pack_qty must be a number"}), 400
    if pack_qty <= 0:
        return jsonify({"error": "pack_qty must be positive"}), 400
    lead = b.get("lead_time_days")
    if lead is not None and str(lead).strip() != "":
        try:
            lead = int(lead)
        except (TypeError, ValueError):
            return jsonify({"error": "lead_time_days must be an integer"}), 400
        if lead < 0:
            return jsonify({"error": "lead_time_days must be >= 0"}), 400
    else:
        lead = None
    conn = _db()
    try:
        if conn.execute("SELECT 1 FROM material WHERE project_code=? AND name=?",
                        (project_code, name)).fetchone():
            return jsonify({"error": "a material with that name already exists on this project"}), 409
        cur = conn.execute(
            "INSERT INTO material (project_code, name, category, purchase_unit, base_unit, "
            "pack_qty, default_vendor, lead_time_days, pinned, active, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,1,?)",
            (project_code, name, category, purchase_unit, base_unit, pack_qty,
             default_vendor, lead, 1 if b.get("pinned") else 0, _now_iso()))
        conn.commit()
        m = _material(conn, cur.lastrowid)
        return jsonify({"data": _mat_public(m, 0, None, None)}), 201
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_patch_material(material_id):
    """PATCH /api/materials/<id> — edit / pin / deactivate. Per-resource project gate."""
    b = request.get_json(silent=True) or {}
    conn = _db()
    try:
        m = _material(conn, material_id)
        if not m:
            return jsonify({"error": "not found"}), 404
        if not _can_project(conn, m["project_code"]):
            return jsonify({"error": "forbidden"}), 403
        fields = {}
        units = _units()
        if "name" in b:
            nm = (b.get("name") or "").strip()
            if not nm:
                return jsonify({"error": "name cannot be empty"}), 400
            dup = conn.execute("SELECT 1 FROM material WHERE project_code=? AND name=? AND id<>?",
                               (m["project_code"], nm, material_id)).fetchone()
            if dup:
                return jsonify({"error": "a material with that name already exists on this project"}), 409
            fields["name"] = nm
        if "category" in b:
            fields["category"] = (b.get("category") or "").strip() or None
        if "base_unit" in b:
            if b["base_unit"] not in units:
                return jsonify({"error": "base_unit must be one of the canonical units"}), 400
            fields["base_unit"] = b["base_unit"]
        if "purchase_unit" in b:
            pu = (b.get("purchase_unit") or "").strip() or None
            if pu is not None and pu not in units:
                return jsonify({"error": "purchase_unit must be one of the canonical units"}), 400
            fields["purchase_unit"] = pu
        if "pack_qty" in b:
            try:
                pq = float(b["pack_qty"])
            except (TypeError, ValueError):
                return jsonify({"error": "pack_qty must be a number"}), 400
            if pq <= 0:
                return jsonify({"error": "pack_qty must be positive"}), 400
            fields["pack_qty"] = pq
        if "default_vendor" in b:
            fields["default_vendor"] = (b.get("default_vendor") or "").strip() or None
        if "lead_time_days" in b:
            lv = b.get("lead_time_days")
            if lv is None or str(lv).strip() == "":
                fields["lead_time_days"] = None
            else:
                try:
                    lv = int(lv)
                except (TypeError, ValueError):
                    return jsonify({"error": "lead_time_days must be an integer"}), 400
                if lv < 0:
                    return jsonify({"error": "lead_time_days must be >= 0"}), 400
                fields["lead_time_days"] = lv
        if "pinned" in b:
            fields["pinned"] = 1 if b.get("pinned") else 0
        if "active" in b:
            fields["active"] = 1 if b.get("active") else 0
        if not fields:
            return jsonify({"error": "no fields"}), 400
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE material SET {sets} WHERE id=?", (*fields.values(), material_id))
        conn.commit()
        m = _material(conn, material_id)
        oh = _on_hand_map(conn, m["project_code"]).get(material_id, 0)
        return jsonify({"data": _mat_public(m, oh,
                                            _last_delivery_map(conn, m["project_code"]).get(material_id),
                                            _next_expected_map(conn, m["project_code"]).get(material_id))})
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_delete_material(material_id):
    """DELETE /api/materials/<id> — allowed ONLY while the material has no transactions
    (a just-created mistake). Once the ledger references it: 409 -> deactivate instead."""
    conn = _db()
    try:
        m = _material(conn, material_id)
        if not m:
            return jsonify({"error": "not found"}), 404
        if not _can_project(conn, m["project_code"]):
            return jsonify({"error": "forbidden"}), 403
        n = conn.execute("SELECT COUNT(*) FROM material_txn WHERE material_id=?",
                         (material_id,)).fetchone()[0]
        if n:
            return jsonify({"error": "this material has ledger history — deactivate it instead"}), 409
        conn.execute("DELETE FROM expected_delivery WHERE material_id=?", (material_id,))
        conn.execute("DELETE FROM material WHERE id=?", (material_id,))
        conn.commit()
        return jsonify({"data": {"deleted": material_id}})
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_copy_catalog(project_code):
    """POST /api/projects/<code>/materials/copy-from {source_project_code} — copy the
    catalog DEFINITIONS (never transactions) so project #2 takes minutes. The actor
    must be able to access BOTH projects (admin/c_suite any; pm assigned to both).
    Name collisions are skipped, not overwritten."""
    b = request.get_json(silent=True) or {}
    src = (b.get("source_project_code") or "").strip()
    if not src:
        return jsonify({"error": "source_project_code is required"}), 400
    if src == project_code:
        return jsonify({"error": "source and target are the same project"}), 400
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM projects WHERE project_code=?", (src,)).fetchone():
            return jsonify({"error": "source project not found"}), 404
        if not _can_project(conn, src):
            return jsonify({"error": "forbidden"}), 403
        rows = conn.execute(
            "SELECT * FROM material WHERE project_code=? AND active=1 ORDER BY id", (src,)).fetchall()
        existing = {r[0] for r in conn.execute(
            "SELECT name FROM material WHERE project_code=?", (project_code,)).fetchall()}
        copied, skipped = [], []
        now = _now_iso()
        for m in rows:
            if m["name"] in existing:
                skipped.append(m["name"])
                continue
            conn.execute(
                "INSERT INTO material (project_code, name, category, purchase_unit, base_unit, "
                "pack_qty, default_vendor, lead_time_days, pinned, active, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,1,?)",
                (project_code, m["name"], m["category"], m["purchase_unit"], m["base_unit"],
                 m["pack_qty"], m["default_vendor"], m["lead_time_days"], m["pinned"], now))
            copied.append(m["name"])
        conn.commit()
        logging.info(f"materials: catalog copy {src} -> {project_code} "
                     f"copied={len(copied)} skipped={len(skipped)} by={_actor().get('id')}")
        return jsonify({"data": {"copied": len(copied), "skipped": len(skipped),
                                 "skipped_names": skipped}})
    finally:
        conn.close()


# ============= LEDGER =============

@requires_role(*_MAT_ROLES)
def _api_create_txn(project_code):
    """POST /api/projects/<code>/material-txns — log delivery / self-pickup / return /
    writeoff. JSON, or multipart with an optional packing `slip` file. Conversion at
    entry: the entered unit must be the base unit or the purchase unit (× pack_qty)."""
    if request.content_type and "multipart" in request.content_type:
        b = request.form
        slip_fs = request.files.get("slip")
    else:
        b = request.get_json(silent=True) or {}
        slip_fs = None
    txn_type = (b.get("txn_type") or "delivery").strip()
    if txn_type not in _DIRECT_TYPES:
        return jsonify({"error": f"txn_type must be one of {', '.join(_DIRECT_TYPES)} "
                                 f"(transfers and counts have their own endpoints)"}), 400
    try:
        material_id = int(b.get("material_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "material_id is required"}), 400
    conn = _db()
    try:
        m = _material(conn, material_id)
        if not m or m["project_code"] != project_code:
            return jsonify({"error": "material not found on this project"}), 404
        if not m["active"]:
            return jsonify({"error": "material is deactivated"}), 409
        try:
            qty_base, qty_entered, unit_entered = _convert(m, b.get("qty"), b.get("unit"))
            txn_date = _iso_date(b.get("txn_date")) or datetime.now().strftime("%Y-%m-%d")
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        vendor = (b.get("vendor") or "").strip() or None
        note = (b.get("note") or "").strip() or None
        expense_link_id = b.get("expense_link_id") or None
        if expense_link_id:
            try:
                expense_link_id = int(expense_link_id)
            except (TypeError, ValueError):
                return jsonify({"error": "expense_link_id must be an integer"}), 400
            if not conn.execute("SELECT 1 FROM expenses WHERE id=?", (expense_link_id,)).fetchone():
                return jsonify({"error": "linked expense not found"}), 404
        slip_path = None
        if slip_fs and slip_fs.filename:
            try:
                slip_path = _save_slip(project_code, slip_fs)
            except ValueError as ve:
                return jsonify({"error": str(ve)}), 400
        signed = qty_base * _TXN_SIGN[txn_type]
        tid = _insert_txn(conn, project_code, material_id, txn_type, signed, qty_entered,
                          unit_entered, vendor, txn_date, note, slip_path, expense_link_id)
        conn.commit()
        r = conn.execute("SELECT t.*, m.name AS material_name FROM material_txn t "
                         "JOIN material m ON m.id=t.material_id WHERE t.id=?", (tid,)).fetchone()
        oh = _on_hand_map(conn, project_code).get(material_id, 0)
        return jsonify({"data": {"txn": _txn_public(r), "on_hand": oh}}), 201
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_list_txns(project_code):
    """GET /api/projects/<code>/material-txns[?material_id=&limit=] — the activity log,
    newest first. Curated rows (no *_path)."""
    try:
        limit = max(1, min(int(request.args.get("limit", 60)), 200))
    except (TypeError, ValueError):
        limit = 60
    mat_f = request.args.get("material_id")
    conn = _db()
    try:
        where, params = ["t.project_code=?"], [project_code]
        if mat_f:
            try:
                where.append("t.material_id=?")
                params.append(int(mat_f))
            except (TypeError, ValueError):
                return jsonify({"error": "material_id must be an integer"}), 400
        rows = conn.execute(
            f"SELECT t.*, m.name AS material_name FROM material_txn t "
            f"JOIN material m ON m.id=t.material_id WHERE {' AND '.join(where)} "
            f"ORDER BY t.txn_date DESC, t.id DESC LIMIT ?", (*params, limit)).fetchall()
        return jsonify({"data": {"txns": [_txn_public(r) for r in rows]}})
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_txn_slip(txn_id):
    """GET /api/material-txns/<id>/slip — the ONLY way slip bytes are served (#229
    pattern: per-resource gate, path confined, never in JSON)."""
    conn = _db()
    try:
        r = conn.execute("SELECT project_code, slip_path FROM material_txn WHERE id=?",
                         (txn_id,)).fetchone()
        if not r or not r["slip_path"]:
            return jsonify({"error": "not found"}), 404
        if not _can_project(conn, r["project_code"]):
            return jsonify({"error": "forbidden"}), 403
    finally:
        conn.close()
    p = Path(r["slip_path"])
    try:
        if not (p.resolve().is_relative_to(_SLIP_BASE.resolve()) and p.exists()):
            return jsonify({"error": "file missing"}), 404
    except (OSError, ValueError):
        return jsonify({"error": "file missing"}), 404
    resp = send_file(str(p), mimetype=_SLIP_EXT.get(p.suffix.lower(), "application/octet-stream"),
                     as_attachment=False, download_name=f"slip-{txn_id}{p.suffix.lower()}")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@requires_role(*_MAT_ROLES)
def _api_transfer(project_code):
    """POST /api/projects/<code>/material-transfers {material_id, to_project_code, qty,
    unit, txn_date, note} — ATOMIC transfer_out (here) + transfer_in (destination) in
    one transaction. The actor must access BOTH projects. If the destination doesn't
    track the material yet, its definition is copied there (unpinned) so the receiving
    side has a ledger home — nothing is ever lost in transit."""
    b = request.get_json(silent=True) or {}
    dest = (b.get("to_project_code") or "").strip()
    if not dest:
        return jsonify({"error": "to_project_code is required"}), 400
    if dest == project_code:
        return jsonify({"error": "source and destination are the same project"}), 400
    try:
        material_id = int(b.get("material_id"))
    except (TypeError, ValueError):
        return jsonify({"error": "material_id is required"}), 400
    conn = _db()
    try:
        if not conn.execute("SELECT 1 FROM projects WHERE project_code=?", (dest,)).fetchone():
            return jsonify({"error": "destination project not found"}), 404
        if not _can_project(conn, dest):
            return jsonify({"error": "forbidden"}), 403
        m = _material(conn, material_id)
        if not m or m["project_code"] != project_code:
            return jsonify({"error": "material not found on this project"}), 404
        try:
            qty_base, qty_entered, unit_entered = _convert(m, b.get("qty"), b.get("unit"))
            txn_date = _iso_date(b.get("txn_date")) or datetime.now().strftime("%Y-%m-%d")
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        note = (b.get("note") or "").strip() or None
        dm = conn.execute("SELECT * FROM material WHERE project_code=? AND name=?",
                          (dest, m["name"])).fetchone()
        if not dm:
            cur = conn.execute(
                "INSERT INTO material (project_code, name, category, purchase_unit, base_unit, "
                "pack_qty, default_vendor, lead_time_days, pinned, active, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,0,1,?)",
                (dest, m["name"], m["category"], m["purchase_unit"], m["base_unit"],
                 m["pack_qty"], m["default_vendor"], m["lead_time_days"], _now_iso()))
            dest_mat_id = cur.lastrowid
        else:
            dest_mat_id = dm["id"]
        out_note = f"transfer to {dest}" + (f" — {note}" if note else "")
        in_note = f"transfer from {project_code}" + (f" — {note}" if note else "")
        _insert_txn(conn, project_code, material_id, "transfer_out", -qty_base,
                    qty_entered, unit_entered, None, txn_date, out_note)
        _insert_txn(conn, dest, dest_mat_id, "transfer_in", qty_base,
                    qty_entered, unit_entered, None, txn_date, in_note)
        conn.commit()   # one commit = the pair lands together or not at all
        oh = _on_hand_map(conn, project_code).get(material_id, 0)
        return jsonify({"data": {"transferred": qty_base, "to_project_code": dest,
                                 "on_hand": oh}}), 201
    finally:
        conn.close()


# ============= EXPECTED DELIVERIES (the future materials@ agent's home) =============

@requires_role(*_MAT_ROLES)
def _api_list_expected(project_code):
    """GET /api/projects/<code>/expected-deliveries[?all=1] — open rows by default
    (ordered/confirmed/arriving), soonest first."""
    include_all = request.args.get("all") == "1"
    conn = _db()
    try:
        if include_all:
            rows = conn.execute(
                "SELECT * FROM expected_delivery WHERE project_code=? "
                "ORDER BY expected_date ASC, id ASC", (project_code,)).fetchall()
        else:
            rows = conn.execute(
                f"SELECT * FROM expected_delivery WHERE project_code=? "
                f"AND status IN ({','.join(['?']*len(_OPEN_STATUSES))}) "
                f"ORDER BY expected_date ASC, id ASC",
                (project_code, *_OPEN_STATUSES)).fetchall()
        names = {r[0]: r[1] for r in conn.execute(
            "SELECT id, name FROM material WHERE project_code=?", (project_code,)).fetchall()}
        return jsonify({"data": {"expected": [
            _expected_public(r, names.get(r["material_id"])) for r in rows],
            "statuses": list(EXPECTED_STATUSES)}})
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_create_expected(project_code):
    """POST /api/projects/<code>/expected-deliveries — a manual heads-up row. The future
    materials@ agent inserts the same shape with source='agent' (Tier-B proposal)."""
    b = request.get_json(silent=True) or {}
    material_id = b.get("material_id")
    conn = _db()
    try:
        if material_id is not None and str(material_id).strip() != "":
            try:
                material_id = int(material_id)
            except (TypeError, ValueError):
                return jsonify({"error": "material_id must be an integer"}), 400
            m = _material(conn, material_id)
            if not m or m["project_code"] != project_code:
                return jsonify({"error": "material not found on this project"}), 404
        else:
            material_id = None   # multi-line / general order
        status = (b.get("status") or "ordered").strip()
        if status not in EXPECTED_STATUSES:
            return jsonify({"error": f"status must be one of {', '.join(EXPECTED_STATUSES)}"}), 400
        try:
            expected_date = _iso_date(b.get("expected_date"))
        except ValueError:
            return jsonify({"error": "expected_date must be YYYY-MM-DD"}), 400
        if not expected_date:
            return jsonify({"error": "expected_date is required"}), 400
        qty = b.get("qty")
        if qty is not None and str(qty).strip() != "":
            try:
                qty = float(qty)
            except (TypeError, ValueError):
                return jsonify({"error": "qty must be a number"}), 400
        else:
            qty = None
        now = _now_iso()
        cur = conn.execute(
            "INSERT INTO expected_delivery (project_code, material_id, vendor, description, "
            "qty, unit, expected_date, status, source, source_note, created_by, created_at, "
            "updated_at) VALUES (?,?,?,?,?,?,?,?,'manual',NULL,?,?,?)",
            (project_code, material_id, (b.get("vendor") or "").strip() or None,
             (b.get("description") or "").strip() or None, qty,
             (b.get("unit") or "").strip() or None, expected_date, status,
             _actor().get("id"), now, now))
        conn.commit()
        r = conn.execute("SELECT * FROM expected_delivery WHERE id=?", (cur.lastrowid,)).fetchone()
        return jsonify({"data": _expected_public(
            r, _material(conn, material_id)["name"] if material_id else None)}), 201
    finally:
        conn.close()


def _expected_row_gate(conn, exp_id):
    r = conn.execute("SELECT * FROM expected_delivery WHERE id=?", (exp_id,)).fetchone()
    if not r:
        return None, (jsonify({"error": "not found"}), 404)
    if not _can_project(conn, r["project_code"]):
        return None, (jsonify({"error": "forbidden"}), 403)
    return r, None


@requires_role(*_MAT_ROLES)
def _api_patch_expected(exp_id):
    """PATCH /api/expected-deliveries/<id> — status walk (ordered->confirmed->arriving),
    date/vendor/qty edits, cancel. Per-resource gate."""
    b = request.get_json(silent=True) or {}
    conn = _db()
    try:
        r, err = _expected_row_gate(conn, exp_id)
        if err:
            return err
        fields = {}
        if "status" in b:
            if b["status"] not in EXPECTED_STATUSES:
                return jsonify({"error": f"status must be one of {', '.join(EXPECTED_STATUSES)}"}), 400
            fields["status"] = b["status"]
        if "vendor" in b:
            fields["vendor"] = (b.get("vendor") or "").strip() or None
        if "description" in b:
            fields["description"] = (b.get("description") or "").strip() or None
        if "expected_date" in b:
            try:
                d = _iso_date(b.get("expected_date"))
            except ValueError:
                return jsonify({"error": "expected_date must be YYYY-MM-DD"}), 400
            if not d:
                return jsonify({"error": "expected_date cannot be empty"}), 400
            fields["expected_date"] = d
        if "qty" in b:
            q = b.get("qty")
            if q is None or str(q).strip() == "":
                fields["qty"] = None
            else:
                try:
                    fields["qty"] = float(q)
                except (TypeError, ValueError):
                    return jsonify({"error": "qty must be a number"}), 400
        if "unit" in b:
            fields["unit"] = (b.get("unit") or "").strip() or None
        if not fields:
            return jsonify({"error": "no fields"}), 400
        fields["updated_at"] = _now_iso()
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE expected_delivery SET {sets} WHERE id=?",
                     (*fields.values(), exp_id))
        conn.commit()
        r = conn.execute("SELECT * FROM expected_delivery WHERE id=?", (exp_id,)).fetchone()
        nm = _material(conn, r["material_id"])["name"] if r["material_id"] else None
        return jsonify({"data": _expected_public(r, nm)})
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_receive_expected(exp_id):
    """POST /api/expected-deliveries/<id>/receive — MARK RECEIVED in one step: writes a
    pre-filled delivery txn (body may override qty/unit/date/vendor; material_id
    required if the row was a general order) and closes the row. On-hand goes up,
    next_expected clears, last_delivery updates — exactly the operator's flow."""
    b = request.get_json(silent=True) or {}
    conn = _db()
    try:
        r, err = _expected_row_gate(conn, exp_id)
        if err:
            return err
        if r["status"] in ("received", "cancelled"):
            return jsonify({"error": f"already {r['status']}"}), 409
        material_id = b.get("material_id") or r["material_id"]
        if not material_id:
            return jsonify({"error": "material_id is required to receive a general order"}), 400
        material_id = int(material_id)
        m = _material(conn, material_id)
        if not m or m["project_code"] != r["project_code"]:
            return jsonify({"error": "material not found on this project"}), 404
        try:
            qty_base, qty_entered, unit_entered = _convert(
                m, b.get("qty", r["qty"]), b.get("unit", r["unit"]))
            txn_date = _iso_date(b.get("txn_date")) or datetime.now().strftime("%Y-%m-%d")
        except ValueError as ve:
            return jsonify({"error": str(ve)}), 400
        vendor = (b.get("vendor") or r["vendor"] or "").strip() or None
        tid = _insert_txn(conn, r["project_code"], material_id, "delivery", qty_base,
                          qty_entered, unit_entered, vendor, txn_date,
                          f"received expected delivery #{exp_id}")
        conn.execute("UPDATE expected_delivery SET status='received', updated_at=? WHERE id=?",
                     (_now_iso(), exp_id))
        conn.commit()
        oh = _on_hand_map(conn, r["project_code"]).get(material_id, 0)
        return jsonify({"data": {"txn_id": tid, "on_hand": oh, "status": "received"}}), 201
    finally:
        conn.close()


# ============= WEEKLY COUNT (the 5-minute truth) =============

@requires_role(*_MAT_ROLES)
def _api_weekly_count(project_code):
    """POST /api/projects/<code>/material-count {counts: {material_id: counted_qty},
    txn_date?} — reconciles reality vs the ledger: writes a count_adjust txn for each
    non-zero delta and returns the drift per item. The count is truth."""
    b = request.get_json(silent=True) or {}
    counts = b.get("counts")
    if not isinstance(counts, dict) or not counts:
        return jsonify({"error": "counts {material_id: counted_qty} is required"}), 400
    try:
        txn_date = _iso_date(b.get("txn_date")) or datetime.now().strftime("%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "txn_date must be YYYY-MM-DD"}), 400
    conn = _db()
    try:
        from datetime import date, timedelta
        on_hand = _on_hand_map(conn, project_code)
        today = date.today()
        maps = (_maps_for(conn, [int(k) for k in counts.keys()])
                if consumption_ready(conn) else {})
        results = []
        for k, v in counts.items():
            try:
                mid = int(k)
                counted = float(v)
            except (TypeError, ValueError):
                return jsonify({"error": f"bad count entry {k!r}"}), 400
            m = _material(conn, mid)
            if not m or m["project_code"] != project_code:
                return jsonify({"error": f"material {mid} not found on this project"}), 404
            before = on_hand.get(mid, 0)
            drift = round(counted - before, 4)
            item = {"material_id": mid, "name": m["name"], "before": before,
                    "counted": counted, "drift": drift}
            # #272b — estimate-vs-count recalibration HINT (never auto-adjusts the map).
            # The ledger never subtracts consumption, so (ledger − counted) IS the
            # actual usage since the ledger was last true (the previous count, or the
            # trailing window). Compare to what the operator's map PREDICTED for the
            # same window; suggest a waste% that would have matched. Read BEFORE the
            # count_adjust below lands, so the math uses the pre-reconcile ledger.
            mp = maps.get(mid)
            if mp:
                last = conn.execute(
                    "SELECT MAX(txn_date) FROM material_txn WHERE material_id=? "
                    "AND txn_type='count_adjust'", (mid,)).fetchone()[0]
                start = last or (today - timedelta(days=TRAIL_DAYS)).isoformat()
                win = _quantity_window(conn, project_code, start, today.isoformat())
                f = 1.0 + (float(mp["waste_pct"] or 0) / 100.0)
                y = float(mp["yield_per_unit"])
                if mp["driver"] == "manual_rate":
                    expected = y * f * win["workdays"]
                else:
                    qty = win["volume_cf"] if mp["driver"] == "volume_cf" else win["area_sf"]
                    expected = (qty / y) * f if y > 0 else 0.0
                actual = round(before - counted, 4)   # positive = used since last truth
                if expected > 1e-9 and actual > 0:
                    over = (actual - expected) / expected
                    item["usage_check"] = {"expected_used": round(expected, 2),
                                           "actual_used": actual,
                                           "over_pct": round(over * 100)}
                    if abs(over) >= 0.05:
                        w = float(mp["waste_pct"] or 0)
                        suggested = max(0, round(((1 + w / 100.0) * (actual / expected) - 1) * 100))
                        item["usage_check"]["hint"] = (
                            f"actual usage ran ~{abs(round(over*100))}% "
                            f"{'over' if over > 0 else 'under'} the map — "
                            f"consider waste {round(w)}%→{suggested}%")
            if abs(drift) > 1e-9:
                _insert_txn(conn, project_code, mid, "count_adjust", drift, counted,
                            m["base_unit"], None, txn_date,
                            f"weekly count: counted {counted}, ledger said {before}")
            results.append(item)
        conn.commit()
        return jsonify({"data": {"results": results,
                                 "adjusted": sum(1 for x in results if abs(x["drift"]) > 1e-9)}})
    finally:
        conn.close()


# ============= #272b — DERIVED CONSUMPTION, BURN, REORDER (compute-on-read) =============
# The field never logs usage. Consumption is DERIVED from the drop-plan quantity_entries
# the crew already enters, through a PER-MATERIAL, OPERATOR-EDITED map (yield + waste —
# the catalog rule extends to numbers: nothing hardcoded, blank until set). No map = no
# burn/forecast fields at all (honest absence). Nothing derived is ever stored — every
# number traces to quantity_entries rows × the operator's own map at read time.

DRIVERS = ("volume_cf", "area_sf", "manual_rate")
SAFETY_DEFAULT = 4        # days — spec default; per-material override on the map
TRAIL_DAYS = 14           # trailing burn window (LOCAL calendar days)
FWD_DAYS = 14             # look-ahead window for forward demand
AMBER_DAYS = 7            # order_by within a week -> amber chip

_CONSUMPTION_READY = False


def consumption_ready(conn) -> bool:
    """Catalog probe for material_consumption_map (the #269 lesson: NEVER try/except a
    failed statement on Postgres — it aborts the whole transaction). Pre-migration the
    module degrades to #272a behavior: no derived fields anywhere."""
    global _CONSUMPTION_READY
    if _CONSUMPTION_READY:
        return True
    if db_layer.is_postgres():
        found = bool(conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_schema='public' "
            "AND table_name='material_consumption_map'").fetchone())
    else:
        found = bool(conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='material_consumption_map'"
        ).fetchone())
    if found:
        _CONSUMPTION_READY = True
    return found


def _map_public(r) -> dict:
    return {"driver": r["driver"], "yield_per_unit": r["yield_per_unit"],
            "waste_pct": r["waste_pct"],
            "safety_days": r["safety_days"] if r["safety_days"] is not None else SAFETY_DEFAULT,
            "notes": r["notes"], "updated_at": r["updated_at"]}


def _maps_for(conn, material_ids) -> dict:
    ids = [int(i) for i in material_ids]
    if not ids or not consumption_ready(conn):
        return {}
    rows = conn.execute(
        f"SELECT * FROM material_consumption_map WHERE material_id IN ({','.join(['?']*len(ids))})",
        ids).fetchall()
    return {r["material_id"]: r for r in rows}


def _quantity_window(conn, project_code, start_iso, end_iso) -> dict:
    """Drop-plan quantities logged in (start, end] for this project: total volume_cf,
    derived area_sf (length×width unit-corrected + flat entries logged with unit SF),
    and the count of distinct work days. LOCAL date strings; REAL sums (dual-backend)."""
    r = conn.execute(
        "SELECT COALESCE(SUM(q.volume_cf), 0), "
        "COALESCE(SUM(CASE WHEN q.length IS NOT NULL AND q.width IS NOT NULL "
        "  THEN (q.length * CASE q.length_unit WHEN 'in' THEN 1.0/12.0 ELSE 1.0 END) "
        "     * (q.width  * CASE q.width_unit  WHEN 'in' THEN 1.0/12.0 ELSE 1.0 END) "
        "  ELSE 0 END), 0), "
        "COALESCE(SUM(CASE WHEN q.quantity IS NOT NULL AND UPPER(COALESCE(q.unit,''))='SF' "
        "  THEN q.quantity ELSE 0 END), 0), "
        "COUNT(DISTINCT q.logged_on) "
        "FROM quantity_entries q JOIN drops d ON d.drop_id = q.drop_id "
        "WHERE d.project_code=? AND q.logged_on > ? AND q.logged_on <= ?",
        (project_code, start_iso, end_iso)).fetchone()
    return {"volume_cf": round(float(r[0] or 0), 4),
            "area_sf": round(float(r[1] or 0) + float(r[2] or 0), 4),
            "workdays": int(r[3] or 0)}


def _sched_days_next(conn, project_code, today) -> int:
    """Distinct calendar days in (today, today+FWD_DAYS] covered by look-ahead
    activities — v1's whole forward model (do NOT over-model)."""
    from datetime import timedelta
    lo, hi = today, today + timedelta(days=FWD_DAYS)
    rows = conn.execute(
        "SELECT planned_start, planned_finish FROM lookahead_activity "
        "WHERE project_code=? AND planned_finish > ? AND planned_start <= ?",
        (project_code, lo.isoformat(), hi.isoformat())).fetchall()
    days = set()
    for r in rows:
        try:
            s = datetime.strptime(str(r[0])[:10], "%Y-%m-%d").date()
            e = datetime.strptime(str(r[1])[:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        d = max(s, lo + timedelta(days=1))
        end = min(e, hi)
        while d <= end:
            days.add(d)
            d += timedelta(days=1)
    return len(days)


def _derive_one(map_row, window, sched_days, on_hand, lead_days, today) -> dict:
    """The whole #272b math, in one traceable place. Returns the derived fields for ONE
    mapped material. All 'consumed' figures are base units over the trailing window.

      volume_cf / area_sf : consumed = driver_qty ÷ yield × (1 + waste%)
                            burn/day = consumed ÷ 14 (calendar)
      manual_rate         : burn/day = yield × (1 + waste%) (flat per-workday rate)
                            consumed = burn/day × trailing workdays
      per-workday pace    = consumed ÷ max(trailing workdays, 1)
      forward/day         = per-workday × scheduled_days_next14 ÷ 14
      days_left           = on_hand ÷ max(burn/day, forward/day)
      order_by            = today + days_left − (lead_time + safety_days)
      chip                : order_by ≤ today -> order_now; ≤ today+7 -> order_by; else stocked
    """
    from datetime import timedelta
    f = 1.0 + (float(map_row["waste_pct"] or 0) / 100.0)
    y = float(map_row["yield_per_unit"])
    driver = map_row["driver"]
    workdays = window["workdays"]
    if driver == "manual_rate":
        burn_day = y * f
        consumed = burn_day * workdays
        per_workday = burn_day
    else:
        qty = window["volume_cf"] if driver == "volume_cf" else window["area_sf"]
        consumed = (qty / y) * f if y > 0 else 0.0
        burn_day = consumed / TRAIL_DAYS
        per_workday = consumed / max(workdays, 1)
    forward_day = per_workday * (sched_days / float(FWD_DAYS))
    rate = max(burn_day, forward_day)
    out = {"consumed_14d": round(consumed, 2), "burn_day": round(burn_day, 2),
           "forward_day": round(forward_day, 2)}
    if rate <= 1e-9:
        out.update({"days_left": None, "order_by_date": None, "stock_status": "stocked"})
        return out
    days_left = max(float(on_hand or 0), 0.0) / rate
    safety = map_row["safety_days"] if map_row["safety_days"] is not None else SAFETY_DEFAULT
    order_by = today + timedelta(days=int(days_left)) - timedelta(days=int(lead_days or 0) + int(safety))
    status = ("order_now" if order_by <= today
              else ("order_by" if order_by <= today + timedelta(days=AMBER_DAYS) else "stocked"))
    out.update({"days_left": round(days_left, 1), "order_by_date": order_by.isoformat(),
                "stock_status": status})
    return out


def _project_derivation(conn, project_code, mats_rows, on_hand_map):
    """(per-material derived dict, payload extras) for one project — one window query,
    one schedule scan, shared by the list endpoint and the company widget."""
    from datetime import date, timedelta
    today = date.today()
    start = (today - timedelta(days=TRAIL_DAYS)).isoformat()
    window = _quantity_window(conn, project_code, start, today.isoformat())
    sched = _sched_days_next(conn, project_code, today)
    maps = _maps_for(conn, [m["id"] for m in mats_rows])
    derived = {}
    for m in mats_rows:
        mp = maps.get(m["id"])
        if not mp:
            continue
        d = _derive_one(mp, window, sched, on_hand_map.get(m["id"], 0),
                        m["lead_time_days"], today)
        d["map"] = _map_public(mp)
        derived[m["id"]] = d
    return derived, {"quantity_window": window, "sched_days_next14": sched}


@requires_role(*_MAT_ROLES)
def _api_put_consumption_map(material_id):
    """PUT /api/materials/<id>/consumption-map — upsert the operator's map (driver,
    yield, waste %, safety days, notes). One map per material; per-resource gated."""
    b = request.get_json(silent=True) or {}
    conn = _db()
    try:
        if not consumption_ready(conn):
            return jsonify({"error": "consumption schema not migrated — run apply_material_consumption_272b.py"}), 503
        m = _material(conn, material_id)
        if not m:
            return jsonify({"error": "not found"}), 404
        if not _can_project(conn, m["project_code"]):
            return jsonify({"error": "forbidden"}), 403
        driver = (b.get("driver") or "").strip()
        if driver not in DRIVERS:
            return jsonify({"error": f"driver must be one of {', '.join(DRIVERS)}"}), 400
        try:
            y = float(b.get("yield_per_unit"))
        except (TypeError, ValueError):
            return jsonify({"error": "yield_per_unit must be a number"}), 400
        if y <= 0:
            return jsonify({"error": "yield_per_unit must be positive"}), 400
        try:
            waste = float(b.get("waste_pct") or 0)
        except (TypeError, ValueError):
            return jsonify({"error": "waste_pct must be a number"}), 400
        if waste < 0 or waste > 500:
            return jsonify({"error": "waste_pct must be between 0 and 500"}), 400
        safety = b.get("safety_days")
        if safety is None or str(safety).strip() == "":
            safety = None
        else:
            try:
                safety = int(safety)
            except (TypeError, ValueError):
                return jsonify({"error": "safety_days must be an integer"}), 400
            if safety < 0:
                return jsonify({"error": "safety_days must be >= 0"}), 400
        notes = (b.get("notes") or "").strip() or None
        now = _now_iso()
        if conn.execute("SELECT 1 FROM material_consumption_map WHERE material_id=?",
                        (material_id,)).fetchone():
            conn.execute(
                "UPDATE material_consumption_map SET driver=?, yield_per_unit=?, waste_pct=?, "
                "safety_days=?, notes=?, updated_at=? WHERE material_id=?",
                (driver, y, waste, safety, notes, now, material_id))
        else:
            conn.execute(
                "INSERT INTO material_consumption_map (material_id, driver, yield_per_unit, "
                "waste_pct, safety_days, notes, updated_at) VALUES (?,?,?,?,?,?,?)",
                (material_id, driver, y, waste, safety, notes, now))
        conn.commit()
        r = conn.execute("SELECT * FROM material_consumption_map WHERE material_id=?",
                         (material_id,)).fetchone()
        return jsonify({"data": {"material_id": material_id, "map": _map_public(r)}})
    finally:
        conn.close()


@requires_role(*_MAT_ROLES)
def _api_delete_consumption_map(material_id):
    """DELETE /api/materials/<id>/consumption-map — unmap; the material returns to the
    honest chipless state."""
    conn = _db()
    try:
        if not consumption_ready(conn):
            return jsonify({"error": "consumption schema not migrated"}), 503
        m = _material(conn, material_id)
        if not m:
            return jsonify({"error": "not found"}), 404
        if not _can_project(conn, m["project_code"]):
            return jsonify({"error": "forbidden"}), 403
        conn.execute("DELETE FROM material_consumption_map WHERE material_id=?", (material_id,))
        conn.commit()
        return jsonify({"data": {"material_id": material_id, "map": None}})
    finally:
        conn.close()


@requires_company
def _api_company_material_alerts():
    """GET /api/company/material-alerts — admin/c_suite console widget: every project's
    Order-NOW / Order-by materials in one list (order_now first, then soonest date)."""
    conn = _db()
    try:
        if not consumption_ready(conn):
            return jsonify({"data": {"alerts": []}})
        codes = [r[0] for r in conn.execute(
            "SELECT DISTINCT project_code FROM material WHERE active=1").fetchall()]
        names = {r[0]: r[1] for r in conn.execute(
            "SELECT project_code, name FROM projects").fetchall()}
        alerts = []
        for code in codes:
            mats = conn.execute(
                "SELECT * FROM material WHERE project_code=? AND active=1", (code,)).fetchall()
            if not mats:
                continue
            oh = _on_hand_map(conn, code)
            derived, _extras = _project_derivation(conn, code, mats, oh)
            for m in mats:
                d = derived.get(m["id"])
                if not d or d.get("stock_status") in (None, "stocked"):
                    continue
                alerts.append({
                    "project_code": code, "project_name": names.get(code) or code,
                    "material_id": m["id"], "name": m["name"], "base_unit": m["base_unit"],
                    "on_hand": oh.get(m["id"], 0), "burn_day": d["burn_day"],
                    "days_left": d["days_left"], "order_by_date": d["order_by_date"],
                    "lead_time_days": m["lead_time_days"], "stock_status": d["stock_status"],
                })
        alerts.sort(key=lambda a: (0 if a["stock_status"] == "order_now" else 1,
                                   a["order_by_date"] or "9999-12-31"))
        return jsonify({"data": {"alerts": alerts}})
    finally:
        conn.close()


def register(app) -> None:
    """Wire the materials endpoints. Project-path routes inherit the central pm_scoping
    hook; by-id routes re-derive per resource. Call after pm_scoping/client gates."""
    app.add_url_rule("/api/projects/<project_code>/materials", "materials_list",
                     _api_list_materials, methods=["GET"])
    app.add_url_rule("/api/projects/<project_code>/materials", "materials_create",
                     _api_create_material, methods=["POST"])
    app.add_url_rule("/api/materials/<int:material_id>", "materials_patch",
                     _api_patch_material, methods=["PATCH"])
    app.add_url_rule("/api/materials/<int:material_id>", "materials_delete",
                     _api_delete_material, methods=["DELETE"])
    app.add_url_rule("/api/projects/<project_code>/materials/copy-from", "materials_copy",
                     _api_copy_catalog, methods=["POST"])
    app.add_url_rule("/api/projects/<project_code>/material-txns", "materials_txn_create",
                     _api_create_txn, methods=["POST"])
    app.add_url_rule("/api/projects/<project_code>/material-txns", "materials_txn_list",
                     _api_list_txns, methods=["GET"])
    app.add_url_rule("/api/material-txns/<int:txn_id>/slip", "materials_txn_slip",
                     _api_txn_slip, methods=["GET"])
    app.add_url_rule("/api/projects/<project_code>/material-transfers", "materials_transfer",
                     _api_transfer, methods=["POST"])
    app.add_url_rule("/api/projects/<project_code>/expected-deliveries", "materials_expected_list",
                     _api_list_expected, methods=["GET"])
    app.add_url_rule("/api/projects/<project_code>/expected-deliveries", "materials_expected_create",
                     _api_create_expected, methods=["POST"])
    app.add_url_rule("/api/expected-deliveries/<int:exp_id>", "materials_expected_patch",
                     _api_patch_expected, methods=["PATCH"])
    app.add_url_rule("/api/expected-deliveries/<int:exp_id>/receive", "materials_expected_receive",
                     _api_receive_expected, methods=["POST"])
    app.add_url_rule("/api/projects/<project_code>/material-count", "materials_count",
                     _api_weekly_count, methods=["POST"])
    # #272b — consumption maps + the company-console reorder widget
    app.add_url_rule("/api/materials/<int:material_id>/consumption-map", "materials_map_put",
                     _api_put_consumption_map, methods=["PUT"])
    app.add_url_rule("/api/materials/<int:material_id>/consumption-map", "materials_map_delete",
                     _api_delete_consumption_map, methods=["DELETE"])
    app.add_url_rule("/api/company/material-alerts", "materials_company_alerts",
                     _api_company_material_alerts, methods=["GET"])
