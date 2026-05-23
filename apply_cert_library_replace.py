#!/usr/bin/env python3
"""Replace the cert_types catalog with the full DOB + SST + non-DOB list.

What this script does (in order, transactionally):
  1. Adds the `category` and `reference_url` columns to cert_types
     (idempotent — `duplicate column` is caught and counted as skipped).
  2. Captures the current set of cert_type_ids referenced by any row in
     `certifications` (the existing worker-cert assignments — if any).
  3. WIPES cert_types and re-inserts the full catalog from
     `cert_library_DOB_SST.md` — every DOB course in its proper category,
     plus the two non-DOB entries (CPR, OSHA 30).
  4. Re-maps any prior worker-cert assignment whose old `cert_type_id`
     doesn't appear in the new catalog. Reports every assignment that
     can't be mapped cleanly so the operator can decide manually.
  5. Prints a summary: total courses inserted, per-category counts,
     prereq count, and any orphaned assignments.

CoF prerequisites: ONLY two entries flip is_cof_prerequisite=1 —
  RIGGER-32 (32-Hour Rigging Supervisor) and SCAFFOLD-16 (16-Hour
  Suspended Scaffold User). Their codes are preserved so the
  CoF-eligibility logic (cof_issuer.py) keeps issuing for any worker
  who holds either credential.

Two genuine duplicate-name courses with different DOB URLs are kept
as distinct entries — their codes encode the variant so they don't
collide:
  - SCAFFOLD-4-CARD vs SCAFFOLD-4-SST   ("Scaffold Card and SST"
                                         vs "SST only" variants of
                                         the 4-Hour Supported
                                         Scaffold User and Refresher)
  - SAFETY-8-LIC   vs SAFETY-8-SST      ("License Requirement and SST"
                                         vs "SST Only" variants of
                                         the 8-Hour Site Safety)

Expiry intervals stay nullable / per-worker — the new catalog does
NOT hardcode `validity_months`. Expiry is captured on the worker's
cert assignment row, not on the cert type, because the same course
issues differ in card validity across instructors / refreshers.

Re-run safety: if the catalog has already been replaced (i.e., codes
already match), the wipe-and-reinsert is still a no-op equivalent —
identical rows go back in. The schema-add ALTERs are individually
idempotent via the standard duplicate-column suppression.
"""
import sqlite3
import sys
from pathlib import Path
from collections import Counter, defaultdict

SCRIPT_DIR = Path(__file__).resolve().parent
DB_PATH = SCRIPT_DIR / "superstars.db"
SQL_PATH = SCRIPT_DIR / "schema_cert_library_replace.sql"


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


# ---- The new catalog ----------------------------------------------------
# Tuple shape: (cert_type_id, name, category, reference_url, is_cof_prerequisite)
# Codes are short, stable, and (where the spec required) preserve the legacy
# RIGGER-32 / SCAFFOLD-16 ids so CoF eligibility behavior carries over.
# Source of truth: cert_library_DOB_SST.md.
CATALOG = [
    # ---- Concrete ------------------------------------------------------
    ("CSM-30",          "30-Hour Concrete Safety Manager",                            "Concrete",
     "https://www.nyc.gov/assets/buildings/pdf/30_hour_csm.pdf", 0),
    ("CSM-8-REF",       "8-Hour Concrete Safety Manager Refresher",                   "Concrete",
     "https://www.nyc.gov/assets/buildings/pdf/8_hour_csm_refresher.pdf", 0),

    # ---- Cranes and Derrick --------------------------------------------
    ("MAST-CLIMBER-4",  "4-Hour Mast Climber User/Operator and Refresher",            "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/mast_climber_user_and_operator_4_hour_course.pdf", 0),
    ("TOWER-CRANE-30",  "30-Hour Tower Crane Rigger",                                 "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/30_hour_climber_tower_crane.pdf", 0),
    ("TOWER-CRANE-8-REN", "8-Hour Tower Crane Rigger Renewal",                         "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/8_hour_climber_tower_crane_renewal.pdf", 0),
    ("HMO-40",          "40-Hour Hoisting Machine Operator",                          "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/40-hour_hmo.pdf", 0),
    ("HMO-8-REF",       "8-Hour Hoisting Machine Operator Refresher",                 "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/8-hour_hmo_refresher.pdf", 0),
    ("HMO-8-CLASS-B",   "8-Hour Hoisting Machine Operator Class B Rating",            "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/8-hour_hmo_class_B_rating.pdf", 0),
    ("RIGGER-WORKER-16", "16-Hour Rigging Worker",                                    "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/16%20_hr_rigger_worker.pdf", 0),
    ("RIGGER-WORKER-8-REF", "8-Hour Rigging Worker Refresher",                         "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/8_hr_rigger_worker_refresher.pdf", 0),
    ("RIGGER-32",       "32-Hour Rigging Supervisor",                                 "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/32_hr_rigger_supervisor.pdf", 1),
    ("RIGGER-SUP-16-REF", "16-Hour Rigging Supervisor Refresher",                      "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/16_hr_rigger_supervisor_refresher.pdf", 0),
    ("SPECIAL-RIGGER-16", "16-Hour Special Rigger",                                    "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/16-hour_special_rigger.pdf", 0),
    ("SPECIAL-RIGGER-8-REN", "8-Hour Special Rigger Renewal",                          "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/8-hour_special_rigger_renewal.pdf", 0),
    ("LIFT-DIR-32",     "32-Hour Lift Director",                                      "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/32-hour_lift_dir.pdf", 0),
    ("LIFT-DIR-8-REF",  "8-Hour Lift Director Refresher",                             "Cranes and Derrick",
     "https://www.nyc.gov/assets/buildings/pdf/8_hr_lift_director_refresher.pdf", 0),

    # ---- Electrical ----------------------------------------------------
    ("ELEC-8-REN",      "8-Hour Master & Special Electrician Renewal",                "Electrical",
     "https://www.nyc.gov/assets/buildings/pdf/8_hr_electrician.pdf", 0),

    # ---- Plumbing ------------------------------------------------------
    ("PLUMB-7-REN",     "7-Hour Master Plumber & Master Fire Suppression Piping Contractor Renewal", "Plumbing",
     "https://www.nyc.gov/assets/buildings/pdf/7_hour_plumbing_fire_sup_renewal.pdf", 0),
    ("GAS-LTD-16",      "16-Hour Limited Gas Work Qualification",                     "Plumbing",
     "https://www.nyc.gov/assets/buildings/pdf/16_hour_limited_gas_work_course_requirements.pdf", 0),
    ("GAS-PERIODIC-7",  "7-Hour Periodic Gas Piping Inspector Qualification",         "Plumbing",
     "https://www.nyc.gov/assets/buildings/pdf/7-hour_periodic_gas_piping_insp_qualification.pdf", 0),

    # ---- Safety --------------------------------------------------------
    ("SAFETY-40",       "40-Hour Site Safety",                                        "Safety",
     "https://www.nyc.gov/assets/buildings/pdf/40_hour_safety.pdf", 0),
    ("SAFETY-8-LIC",    "8-Hour Site Safety (License Requirement and SST)",           "Safety",
     "https://www.nyc.gov/assets/buildings/pdf/8_hour_safety_all.pdf", 0),

    # ---- Scaffold ------------------------------------------------------
    ("SCAFFOLD-4-CARD", "4-Hour Supported Scaffold User and Refresher (Scaffold Card and SST)", "Scaffold",
     "https://www.nyc.gov/assets/buildings/pdf/4_Hour_Supported_Scaffold_User_and_Refresher.pdf", 0),
    ("SCAFFOLD-SUP-INSTALL-32", "32-Hour Supported Scaffold Installer and Remover",   "Scaffold",
     "https://www.nyc.gov/assets/buildings/pdf/32_Hour_Supported_Scaffold_Installer_and_Remover.pdf", 0),
    ("SCAFFOLD-SUP-INSTALL-8-REF", "8-Hour Supported Scaffold Installer and Remover Refresher", "Scaffold",
     "https://www.nyc.gov/assets/buildings/pdf/8_Hour_Supported_Scaffold_Installer_and_Remover_Refresher.pdf", 0),
    ("SCAFFOLD-SUSP-SUP-32", "32-Hour Suspended Scaffold Supervisor",                 "Scaffold",
     "https://www.nyc.gov/assets/buildings/pdf/32_Hour_Suspended_Scaffold_Supervisor.pdf", 0),
    ("SCAFFOLD-SUSP-SUP-8-REF", "8-Hour Suspended Scaffold Supervisor Refresher",     "Scaffold",
     "https://www.nyc.gov/assets/buildings/pdf/8_Hour_Suspended_Supervisor_Refresher.pdf", 0),
    ("SCAFFOLD-16",     "16-Hour Suspended Scaffold User",                            "Scaffold",
     "https://www.nyc.gov/assets/buildings/pdf/16_Hour_Suspended_Scaffold_User.pdf", 1),
    ("SCAFFOLD-SUSP-8-REF", "8-Hour Suspended Scaffold User Refresher",               "Scaffold",
     "https://www.nyc.gov/assets/buildings/pdf/8_Hour_Suspended_User_Refresher.pdf", 0),

    # ---- SST General Electives -----------------------------------------
    ("SST-1-ELECTRO",   "1-Hour Electrocution Prevention",                            "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_electrocution_prevention.pdf", 0),
    ("SST-1-FIRE-PROT", "1-Hour Fire Protection and Prevention",                      "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_fire_protection_and_prevention.pdf", 0),
    ("SST-1-FIRST-AID-CPR", "1-Hour First Aid and CPR",                               "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_first_aid_and_cpr.pdf", 0),
    ("SST-1-HEAVY-MAT", "1-Hour Handling Heavy Materials and Proper Lifting Techniques", "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_handling_heavy_materials_proper_lifting_techniques.pdf", 0),
    ("SST-1-HOIST-RIG", "1-Hour Hoisting and Rigging",                                "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_hoisting_and_rigging.pdf", 0),
    ("SST-1-MAT-HANDLE", "1-Hour Materials Handling, Storage, Use, and Disposal",     "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_materials_handling_storage_use_and_disposal.pdf", 0),
    ("SST-1-SUN-EXP",   "1-Hour Protection from Sun Exposure",                        "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_protection_from_sun_exposure.pdf", 0),
    ("SST-1-REP-MOTION", "1-Hour Repetitive Motion Injuries",                         "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_repetitive_motion_injuries.pdf", 0),
    ("SST-1-STAIRS-LAD", "1-Hour Stairways and Ladders",                              "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_stairways_and_ladders.pdf", 0),
    ("SST-1-TOOLS-HP",  "1-Hour Tools Hand and Power",                                "SST General Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_tools_hand_and_power.pdf", 0),

    # ---- SST Prescribed Courses ----------------------------------------
    ("SST-2-MENTAL-HEALTH", "2-Hour Mental Health Awareness Course",                  "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/2-hour_mentalha.pdf", 0),
    ("SST-2-DRUG-ALC",  "2-Hour Drug and Alcohol Awareness",                          "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/sst_2-hour_drug_and_alcohol_awareness.pdf", 0),
    ("SST-2-PRETASK",   "2-Hour Pre-Task Meeting",                                    "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/sst_2-hour_pre-Task_meetings.pdf", 0),
    ("SST-2-SSP",       "2-Hour Site Safety Plan (SSP)",                              "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/sst_2-hour_site_safety_plan_ssp.pdf", 0),
    ("SST-2-TOOLBOX",   "2-Hour Tool Box Talks",                                      "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/sst_2-hour_tool_box_talks.pdf", 0),
    ("SST-4-FALL",      "4-Hour Fall Prevention",                                     "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/sst_4-hour_fall_prevention.pdf", 0),
    ("SCAFFOLD-4-SST",  "4-Hour Supported Scaffold User and Refresher (SST only)",    "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/4_Hour_Supported_Scaffold_User_and_Refresher_sst.pdf", 0),
    ("SST-8-FALL",      "8-Hour Fall Prevention",                                     "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/sst_8-hour_fall_prevention.pdf", 0),
    ("SAFETY-8-SST",    "8-Hour Site Safety (SST Only)",                              "SST Prescribed Courses",
     "https://www.nyc.gov/assets/buildings/pdf/8_hour_safety_sst.pdf", 0),

    # ---- SST Specialized Electives -------------------------------------
    ("SST-1-ASB-LEAD",  "1-Hour Asbestos/Lead Awareness",                             "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_asbestos_lead_awareness.pdf", 0),
    ("SST-1-CONCRETE",  "1-Hour Concrete and Masonry Construction",                   "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_concrete_and_masonry_construction.pdf", 0),
    ("SST-1-CONFINED",  "1-Hour Confined Space Entry",                                "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_confined_space_entry.pdf", 0),
    ("SST-1-CRANES",    "1-Hour Cranes, Derricks, Hoists, Elevators and Conveyors",   "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_cranes_derricks_hoists_elevators_and_conveyors.pdf", 0),
    ("SST-1-DEMO",      "1-Hour Demolition Safety",                                   "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_demoliton_safety.pdf", 0),
    ("SST-1-ERGO",      "1-Hour Ergonomics",                                          "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_ergonomics.pdf", 0),
    ("SST-1-EXCAV",     "1-Hour Excavations",                                         "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_excavations.pdf", 0),
    ("SST-1-FLAG",      "1-Hour Flag Person",                                         "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_flag_person.pdf", 0),
    ("SST-1-HSP",       "1-Hour Health and Safety Programs in Construction",          "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_health_and_safety_constr_programs.pdf", 0),
    ("SST-1-JHA",       "1-Hour Job Hazard Analysis",                                 "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_job_hazard_analysis.pdf", 0),
    ("SST-1-MOTOR-VEH", "1-Hour Motor Vehicles, Mechanized Equipment and Marine Operations; Rollover Protective Structures and Overhead Protection; and Signs, Signals and Barricades",
     "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_motor_vehicles_mechanized_epuipment_and_marine_operations.pdf", 0),
    ("SST-1-PERS-LIFTS", "1-Hour Personnel Lifts: Aerial Lifts, Scissor Lifts and Mobile Scaffolds", "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_personnel_lifts_aerial_lifts_scissor_lifts_safety.pdf", 0),
    ("SST-1-RISK",      "1-Hour Risk Assessment and Accident Investigation",          "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_risk_assessment_and_accident_investigation.pdf", 0),
    ("SST-1-SCAFF-SUSP", "1-Hour Scaffolds — Suspended",                              "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_scaffolds_suspended.pdf", 0),
    ("SST-1-STEEL",     "1-Hour Steel Erection",                                      "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_steel_erection.pdf", 0),
    ("SST-1-WELD",      "1-Hour Welding and Cutting",                                 "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_1-hour_welding_and_cutting.pdf", 0),
    ("SST-2.5-FSL",     "2.50-Hour Foundations for Safety Leadership",                "SST Specialized Electives",
     "https://www.nyc.gov/assets/buildings/pdf/sst_2.5-hour_foundations_for_safety_leadership.pdf", 0),

    # ---- Other / Non-DOB -----------------------------------------------
    ("CPR-FIRST-AID",   "CPR Training (First Aid / CPR certification — e.g. AHA or Red Cross)", "OSHA/Other",
     None, 0),
    ("OSHA-30",         "OSHA 30-Hour Construction",                                  "OSHA/Other",
     None, 0),
]


def main():
    if not DB_PATH.exists():
        print(f"ERROR: superstars.db not found at {DB_PATH}", file=sys.stderr)
        return 1

    conn = sqlite3.connect(str(DB_PATH), timeout=60.0)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=60000;")

    # ---- 1) Apply the schema additions (idempotent) -------------------
    applied = skipped = failed = 0
    for stmt in split_statements(SQL_PATH.read_text(encoding="utf-8")):
        try:
            conn.execute(stmt)
            applied += 1
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower() or "already exists" in str(e).lower():
                skipped += 1
            else:
                print(f"ERROR on: {stmt[:120]}\n  {e}", file=sys.stderr)
                failed += 1
    if failed:
        conn.rollback()
        conn.close()
        return 1

    # ---- 2) Capture existing certification assignments ---------------
    old_assignments = conn.execute(
        "SELECT id, employee_id, cert_type_id FROM certifications"
    ).fetchall()

    # ---- 3) Replace the catalog --------------------------------------
    conn.execute("DELETE FROM cert_types")
    for code, name, category, ref_url, is_prereq in CATALOG:
        conn.execute(
            "INSERT INTO cert_types (cert_type_id, name, category, reference_url, "
            "                        is_cof_prerequisite, validity_months) "
            "VALUES (?, ?, ?, ?, ?, NULL)",
            (code, name, category, ref_url, is_prereq),
        )

    new_codes = {row[0] for row in CATALOG}

    # ---- 4) Map old assignments to the new catalog -------------------
    # Best-effort by exact code match (the only mapping that's safe to do
    # silently — anything else gets surfaced for operator review).
    orphans = []
    preserved = 0
    for assign_id, emp_id, old_code in old_assignments:
        if old_code in new_codes:
            preserved += 1
        else:
            orphans.append((assign_id, emp_id, old_code))

    # ---- 5) Commit + report ------------------------------------------
    conn.commit()
    by_category = Counter(row[2] for row in CATALOG)
    prereq_codes = [row[0] for row in CATALOG if row[4] == 1]
    print(f"[cert-lib] schema ALTERs: applied={applied} skipped={skipped} failed={failed}")
    print(f"[cert-lib] catalog: {len(CATALOG)} courses inserted")
    for cat, n in sorted(by_category.items()):
        print(f"             • {cat}: {n}")
    print(f"[cert-lib] CoF prereqs ({len(prereq_codes)}): {', '.join(prereq_codes)}")
    print(f"[cert-lib] existing worker-cert assignments: "
          f"{len(old_assignments)} (preserved={preserved}, orphaned={len(orphans)})")
    if orphans:
        print(f"[cert-lib] ORPHANED assignments — operator must remap:")
        for assign_id, emp_id, old_code in orphans:
            # Per CLAUDE.md PII rule: surface the employee_id and the code, no
            # name lookup. The operator can resolve it in the company console.
            print(f"             • certifications.id={assign_id}  employee={emp_id}  "
                  f"old_code={old_code!r}")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
