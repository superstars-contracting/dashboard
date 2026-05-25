#!/usr/bin/env python3
"""Apply spec_products schema + seed the Sika catalog.

Source of truth: sika_specifications_db.md (operator-curated). Inserts
every product the file lists across the 10 Sika categories, with the
category-level official Sika TDS index as spec_url. Per the source
note: this is comprehensive by product line + flagship products; any
missing variant SKU is a one-row INSERT later — don't fabricate codes.

Re-run safe: every INSERT uses INSERT OR IGNORE on the
UNIQUE(manufacturer, product_name) constraint, so re-running this
script is a no-op once seeded.

The "⭐ flagged" categories in the source doc (the ones most relevant
to the active 890 scope) are mirrored as a `tags` value of '890-core'
so the UI can highlight them.
"""
import sqlite3
import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_spec_products.sql"


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


MFR = "Sika"

# ===== Seed catalog ==================================================
# (category, product_line, product_name, spec_url, tags)
# spec_url uses the category's official Sika TDS index page (verified
# in sika_specifications_db.md). Per-product TDS PDFs land later as
# the operator uploads them via datasheet_pdf_path on individual rows.
# =====================================================================

CAT1 = "Concrete Repair & Protection — Mortars"
URL1 = "https://usa.sika.com/en/construction/repair-protection/mortars.html"
CAT2 = "Concrete Repair & Protection — Coatings & Water Repellents"
URL2 = "https://usa.sika.com/en/construction/repair-protection/coatings-water-repellents.html"
CAT3 = "Structural Strengthening"
URL3 = "https://usa.sika.com/en/construction/repair-protection/structural-strengthening.html"
CAT4 = "Grouting & Anchoring"
URL4 = "https://usa.sika.com/en/construction/repair-protection/grouting.html"
CAT5 = "Sealing & Bonding"
URL5 = "https://usa.sika.com/en/construction/sealing-bonding.html"
CAT6 = "Waterproofing"
URL6 = "https://usa.sika.com/en/construction/waterproofing-coatings.html"
CAT7 = "Flooring"
URL7 = "https://usa.sika.com/en/construction/flooring.html"
CAT8 = "Roofing"
URL8 = "https://usa.sika.com/sarnafil/en/products-systems.html"
CAT9 = "Concrete Admixtures"
URL9 = "https://usa.sika.com/en/construction/concrete.html"
CAT10 = "Industry — Sealing & Bonding"
URL10 = "https://usa.sika.com/en/industry/products-solutions/adhesives-and-sealants.html"

# 890-core ("⭐") categories per the source doc
CORE_890 = "890-core"

SEED = [
    # 1. Concrete Repair & Protection — Mortars ⭐
    (CAT1, "Sika MonoTop",   "Sika MonoTop-211",          URL1, CORE_890),
    (CAT1, "Sika MonoTop",   "Sika MonoTop-611",          URL1, CORE_890),
    (CAT1, "Sika MonoTop",   "Sika MonoTop-612",          URL1, CORE_890),
    (CAT1, "Sika MonoTop",   "Sika MonoTop-615 HB",       URL1, CORE_890),
    (CAT1, "Sika MonoTop",   "Sika MonoTop-4012",         URL1, CORE_890),
    (CAT1, "SikaTop",        "SikaTop-111 Plus",          URL1, CORE_890),
    (CAT1, "SikaTop",        "SikaTop-122 Plus",          URL1, CORE_890),
    (CAT1, "SikaTop",        "SikaTop-123 Plus",          URL1, CORE_890),
    (CAT1, "SikaQuick",      "SikaQuick-1000",            URL1, CORE_890),
    (CAT1, "SikaQuick",      "SikaQuick-2500",            URL1, CORE_890),
    (CAT1, "SikaQuick",      "SikaQuick VOH",             URL1, CORE_890),
    (CAT1, "SikaRepair",     "SikaRepair-222",            URL1, CORE_890),
    (CAT1, "SikaRepair",     "SikaRepair-223",            URL1, CORE_890),
    (CAT1, "SikaRepair",     "SikaRepair-224",            URL1, CORE_890),
    (CAT1, "Bonding agents / corrosion", "Sika Armatec-110 EpoCem",   URL1, CORE_890),
    (CAT1, "Bonding agents / corrosion", "Sika FerroGard-901",        URL1, CORE_890),
    (CAT1, "Bonding agents / corrosion", "Sika FerroGard-903+",       URL1, CORE_890),
    (CAT1, "Bonding agents / corrosion", "SikaLatex",                 URL1, CORE_890),
    (CAT1, "Bonding agents / corrosion", "SikaLatex R",               URL1, CORE_890),

    # 2. Coatings & Water Repellents ⭐
    (CAT2, "SikaGard",  "SikaGard-62",            URL2, CORE_890),
    (CAT2, "SikaGard",  "SikaGard-550W Elastic",  URL2, CORE_890),
    (CAT2, "SikaGard",  "SikaGard-670W",          URL2, CORE_890),
    (CAT2, "SikaGard",  "SikaGard-700S",          URL2, CORE_890),
    (CAT2, "SikaGard",  "SikaGard-705L",          URL2, CORE_890),
    (CAT2, "SikaGard",  "SikaGard-706 Thixo",     URL2, CORE_890),
    (CAT2, "SikaGard",  "SikaGard-905W",          URL2, CORE_890),
    (CAT2, "SikaGard",  "SikaGard-7600",          URL2, CORE_890),
    (CAT2, "Sikagard PW","Sikagard PW",           URL2, CORE_890),

    # 3. Structural Strengthening ⭐
    (CAT3, "Sika CarboDur", "Sika CarboDur S",         URL3, CORE_890),
    (CAT3, "Sika CarboDur", "Sika CarboDur M",         URL3, CORE_890),
    (CAT3, "Sika CarboDur", "Sika CarboDur Rods (NSM)", URL3, CORE_890),
    (CAT3, "SikaWrap",      "SikaWrap Hex series",     URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur-30",              URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur-31 Hi-Mod Gel",   URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur-32 Hi-Mod",       URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur-35 Hi-Mod LV",    URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur-52",              URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur-300",             URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur-330",             URL3, CORE_890),
    (CAT3, "Sikadur",       "Sikadur AnchorFix",       URL3, CORE_890),

    # 4. Grouting & Anchoring
    (CAT4, "SikaGrout",   "SikaGrout-212",       URL4, None),
    (CAT4, "SikaGrout",   "SikaGrout-300 PT",    URL4, None),
    (CAT4, "SikaGrout",   "SikaGrout-328",       URL4, None),
    (CAT4, "Sika AnchorFix", "Sika AnchorFix-1", URL4, None),
    (CAT4, "Sika AnchorFix", "Sika AnchorFix-2", URL4, None),
    (CAT4, "Sika AnchorFix", "Sika AnchorFix-3001+", URL4, None),
    (CAT4, "Sika AnchorFix", "Sika AnchorFix-3+",    URL4, None),

    # 5. Sealing & Bonding ⭐
    (CAT5, "Sikaflex",  "Sikaflex-1a",                  URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex-2c NS",               URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex-2c SL",               URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex-15 LM",               URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex-201 US",              URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex-227",                 URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex-429",                 URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex Self-Leveling",       URL5, CORE_890),
    (CAT5, "Sikaflex",  "Sikaflex Construction",        URL5, CORE_890),
    (CAT5, "Sikasil",   "Sikasil WS-290",               URL5, CORE_890),
    (CAT5, "Sikasil",   "Sikasil WS-295",               URL5, CORE_890),
    (CAT5, "Sikasil",   "Sikasil-728 NS",               URL5, CORE_890),
    (CAT5, "Sikasil",   "Sikasil-728 SL",               URL5, CORE_890),
    (CAT5, "Sikasil",   "Sikasil GP",                   URL5, CORE_890),
    (CAT5, "Sikasil",   "Sikasil SG",                   URL5, CORE_890),
    (CAT5, "Sikasil",   "Sikasil N Plus",               URL5, CORE_890),
    (CAT5, "SikaBond",  "SikaBond-T55",                 URL5, CORE_890),
    (CAT5, "SikaBond",  "SikaBond Construction Adhesive", URL5, CORE_890),
    (CAT5, "Ancillaries", "Sika Backer Rod",            URL5, CORE_890),
    (CAT5, "Ancillaries", "Sika Primer-3N",             URL5, CORE_890),
    (CAT5, "Ancillaries", "Sika Primer-429",            URL5, CORE_890),

    # 6. Waterproofing
    (CAT6, "Sikalastic",  "Sikalastic-1K",            URL6, None),
    (CAT6, "Sikalastic",  "Sikalastic-590",           URL6, None),
    (CAT6, "Sikalastic",  "Sikalastic-601 BC",        URL6, None),
    (CAT6, "Sikalastic",  "Sikalastic-621 TC",        URL6, None),
    (CAT6, "Sikalastic",  "Sikalastic-641 Lo-VOC",    URL6, None),
    (CAT6, "SikaProof",   "SikaProof A+",             URL6, None),
    (CAT6, "SikaProof",   "SikaProof-808",            URL6, None),
    (CAT6, "Cementitious", "Sika-1 Pre-Bagged System", URL6, None),
    (CAT6, "Cementitious", "SikaTop Seal-107",        URL6, None),
    (CAT6, "Cementitious", "Sika MonoTop-107 Seal",   URL6, None),
    (CAT6, "Waterstops",  "Sika Waterbar (PVC)",      URL6, None),
    (CAT6, "Waterstops",  "Sika Waterbar (TPO)",      URL6, None),
    (CAT6, "Waterstops",  "SikaSwell",                URL6, None),
    (CAT6, "Admixtures",  "Sika WT-200 P",            URL6, None),

    # 7. Flooring
    (CAT7, "Sikafloor", "Sikafloor-156 (epoxy primer)", URL7, None),
    (CAT7, "Sikafloor", "Sikafloor-161",                URL7, None),
    (CAT7, "Sikafloor", "Sikafloor-264",                URL7, None),
    (CAT7, "Sikafloor", "Sikafloor-359 N",              URL7, None),
    (CAT7, "Sikafloor", "Sikafloor-375",                URL7, None),
    (CAT7, "Sikafloor", "Sikafloor-3 QuartzTop",        URL7, None),
    (CAT7, "Sikafloor", "Sikafloor levelers & primers", URL7, None),

    # 8. Roofing
    (CAT8, "Sarnafil",  "Sarnafil PVC membranes",       URL8, None),
    (CAT8, "Sikaplan",  "Sikaplan PVC/TPO membranes",   URL8, None),
    (CAT8, "RhinoBond", "RhinoBond induction attachment", URL8, None),
    (CAT8, "Insulation","Sika roof insulation",         URL8, None),
    (CAT8, "Sikalastic","Sikalastic RoofPro",           URL8, None),

    # 9. Concrete Admixtures
    (CAT9, "Superplasticizers", "Sika ViscoCrete series",  URL9, None),
    (CAT9, "Superplasticizers", "Sika ViscoFlow",          URL9, None),
    (CAT9, "Plasticizers / retarders", "Plastiment series", URL9, None),
    (CAT9, "Other",             "Sika Control (SRA)",      URL9, None),
    (CAT9, "Other",             "Sika accelerators",       URL9, None),
    (CAT9, "Other",             "Sika air-entrainers",     URL9, None),
    (CAT9, "Other",             "Sikament",                URL9, None),

    # 10. Industry — Sealing & Bonding (non-construction, lower priority)
    (CAT10, "Sikaflex (industrial)",  "Sikaflex (industrial)",    URL10, None),
    (CAT10, "SikaForce",  "SikaForce (PU structural)",            URL10, None),
    (CAT10, "SikaPower",  "SikaPower (epoxy structural)",         URL10, None),
    (CAT10, "SikaMelt",   "SikaMelt (hot-melt)",                  URL10, None),
    (CAT10, "SikaTack",   "SikaTack (direct glazing)",            URL10, None),
    (CAT10, "SikaDamp",   "SikaDamp (acoustic)",                  URL10, None),
]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1
    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")
    conn.execute("PRAGMA foreign_keys=ON;")

    # ---- 1) Schema migration (idempotent) ---------------------------
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            msg = str(e).lower()
            if "already exists" in msg or "duplicate column" in msg:
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    if failed:
        conn.rollback()
        conn.close()
        return 1

    # ---- 2) Seed Sika catalog ---------------------------------------
    inserted = ignored = 0
    for category, product_line, product_name, spec_url, tags in SEED:
        cur = conn.execute(
            "INSERT OR IGNORE INTO spec_products "
            "  (manufacturer, category, product_line, product_name, spec_url, tags) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (MFR, category, product_line, product_name, spec_url, tags),
        )
        if cur.rowcount == 1:
            inserted += 1
        else:
            ignored += 1
    conn.commit()

    # ---- 3) Report --------------------------------------------------
    total = conn.execute(
        "SELECT COUNT(*) FROM spec_products WHERE manufacturer = ?", (MFR,)
    ).fetchone()[0]
    by_cat = conn.execute(
        "SELECT category, COUNT(*) FROM spec_products WHERE manufacturer = ? "
        "GROUP BY category ORDER BY category", (MFR,)
    ).fetchall()
    flagged = conn.execute(
        "SELECT COUNT(*) FROM spec_products WHERE manufacturer = ? AND tags = ?",
        (MFR, CORE_890),
    ).fetchone()[0]
    print(f"[spec-products] schema: applied={applied} skipped={skipped} failed={failed}")
    print(f"[spec-products] catalog: inserted={inserted} ignored={ignored} (total {total})")
    print(f"[spec-products] 890-core flagged: {flagged}")
    print(f"[spec-products] per category:")
    for c, n in by_cat:
        print(f"             • {c}: {n}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
