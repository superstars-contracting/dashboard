# Certifications Import Template

How to add worker certifications to the dashboard in bulk.

## What this template is for

Fill `certifications_import_template.csv` with one row per cert each worker holds (OSHA-30, scaffold user, fire watch, etc.), then run `import_certifications.py` to insert into the `certifications` table.

Prerequisite: the workers themselves must already exist in the `employees` table. If a worker isn't there yet, run `import_workers.py` first.

## How to fill it

1. Open `certifications_import_template.csv` in any spreadsheet tool. 7 columns, 40 blank rows.
2. For each cert each worker holds, fill one row. Read the cert details directly off the cards/JPEGs.
3. `cert_type_id` is mandatory and must be one of the 47 known codes — see the reference table below. Don't make up new codes; if a real cert doesn't map to anything in the library, flag it and we'll add it via a schema migration.
4. `card_number`, `date_obtained`, `expiration_date`, `issuing_body`, `notes` are optional. Fill what you have.
5. Save back to `certifications_import_template.csv` in the dashboard folder root.
6. Dry-run first: `python import_certifications.py`. Review the table.
7. When the dry-run looks right: `python import_certifications.py --execute`.

The CSV is machine-readable — no comment rows. All guidance lives in this README.

## Column reference

| Column | Required | Format | Example | Notes |
|---|---|---|---|---|
| `employee_id` | YES | `E-XXXXX` | `E-00001` | Must exist in `employees` |
| `cert_type_id` | YES | code from library | `OSHA-30` | Must exist in `cert_types`; see table below |
| `card_number` | optional | text | `12345678` | Number printed on the cert card |
| `date_obtained` | optional | ISO `YYYY-MM-DD` | `2024-03-15` | Issue / training-completion date |
| `expiration_date` | optional | ISO `YYYY-MM-DD` | `2029-03-15` | Some certs don't expire — leave blank |
| `issuing_body` | optional | free text | `NYC DOB` | `OSHA`, `NYCCT`, `FDNY`, etc. |
| `notes` | optional | free text | `replacement card` | Audit trail / context |

Rows where `employee_id` is blank are treated as empty template rows and silently skipped — leave un-needed rows alone.

## cert_type_id reference (47 codes)

These are the **course / training** codes the worker holds — NOT the FDNY-issued Certificate of Fitness card codes (like S-58, S-95). FDNY CoF cards are issued AFTER the worker passes a prerequisite course; CoF cards are tracked separately in the `cof_cards` table. Only `SCAFFOLD-16` and `SCAFFOLD-32` are flagged as CoF prerequisites in this library.

| code | description | CoF prereq |
|---|---|---|
| AERIAL-LIFT | Aerial Lift / Boom | |
| ASBESTOS-HANDLER | Asbestos Handler | |
| ASBESTOS-SUPER | Asbestos Supervisor | |
| AWS-WELDER | AWS Certified Welder | |
| CONFINED-COMP | Confined Space Competent Person | |
| CONFINED-ENTRY | Confined Space Entry | |
| CPR | CPR / AED | |
| CRANE-NCCCO | NCCCO Crane Operator | |
| DRUG-SCREEN | Drug Screening | |
| FALL-COMP | Competent Person Fall Protection | |
| FALL-PROT | Fall Protection | |
| FIRE-S56 | NYC Indoor Place of Assembly | |
| FIRE-S95 | NYC Fire Guard (S-95) | |
| FIRE-WATCH | NYC Hot Work Fire Watch | |
| FIRST-AID | First Aid | |
| FIRST-AID-CPR | First Aid + CPR/AED Combo | |
| FORKLIFT | Forklift / Powered Industrial Truck | |
| HAZWOPER-24 | HAZWOPER 24-hr | |
| HAZWOPER-40 | HAZWOPER 40-hr | |
| HAZWOPER-REF | HAZWOPER 8-hr Refresher | |
| HMO | NYC Hoist Machine Operator | |
| IRATA-L1 | IRATA Level 1 Rope Access | |
| IRATA-L2 | IRATA Level 2 Rope Access | |
| IRATA-L3 | IRATA Level 3 Rope Access | |
| LEAD-WORKER | Lead Worker (RRP) | |
| MASTER-RIGGER | NYC Master Rigger License | |
| MEDICAL-PHYSICAL | Annual Physical / Medical Clearance | |
| NYC-WELDER | NYC DOB Welder License | |
| OSHA-10 | OSHA 10-hour Construction | |
| OSHA-30 | OSHA 30-hour Construction | |
| RIGGER-32 | 32-hr Rigger | |
| RIGGER-OSHA | OSHA Qualified Rigger | |
| **SCAFFOLD-16** | **16-hr Suspended Scaffold User** | ✓ |
| **SCAFFOLD-32** | **32-hr Suspended Scaffold User** | ✓ |
| SCAFFOLD-4 | 4-hr Supported Scaffold User | |
| SCAFFOLD-ERECT | Scaffold Erector / Dismantler | |
| SCAFFOLD-USER | General Scaffold User | |
| SIGN-HANGER | NYC Sign Hanger License | |
| SIGNAL-PERSON | Crane Signal Person | |
| SILICA-COMP | Silica Competent Person | |
| SPECIAL-RIGGER | NYC Special Rigger License | |
| SPRAT-L1 | SPRAT Level 1 Rope Access | |
| SPRAT-L2 | SPRAT Level 2 Rope Access | |
| SPRAT-L3 | SPRAT Level 3 Rope Access | |
| SST-SUPER | SST Supervisor Card (62-hr) | |
| SST-TRAINEE | SST Temporary Trainee Card | |
| SST-WORKER | SST Worker Card (40-hr) | |

## Auto-generated at import (not in CSV)

- `id` — SQLite auto-increment
- `status` — explicit `'active'`. Read-time expiration check is the source of truth for whether a cert is currently valid.
- `created_at`, `updated_at` — SQLite `CURRENT_TIMESTAMP`

## Left NULL at import

- `scan_path` — populated later by Phase F (OpenCV cropper). After cropping, the JPEGs land in each worker's `worker_records/E-XXXXX_*/certs/` folder and the cropper links the rows.

## Pre-flight validation

Before any DB write, the script checks every row:

- `employee_id` present and exists in `employees`
- `cert_type_id` present and exists in `cert_types`
- `date_obtained` and `expiration_date` parse as ISO `YYYY-MM-DD` when non-blank
- If both dates present, `expiration_date >= date_obtained` (nonsensical otherwise)

Any failure aborts the entire import with row numbers and reasons — nothing inserts until the CSV is clean.

## Re-running safety

Safe. The script dedups by the **4-tuple** `(employee_id, cert_type_id, card_number, date_obtained)`. Rows that match an existing 4-tuple in the table are reported as already imported and skipped. Renewals (same worker + same cert type, different date or card_number) are correctly treated as new rows.

## Local PII protection

The template is tracked in git in its blank state. Once filled with real worker cert numbers and issue dates, the file contains PII (cert / license numbers are listed in CLAUDE.md as redactable).

The mitigation is `git update-index --skip-worktree certifications_import_template.csv`. Git stops noticing local edits; the repo's tracked version stays blank; the operator can fill or edit the local copy freely without ever staging it.

Verify with `git ls-files -v certifications_import_template.csv` — an `S` prefix means skip-worktree is active.

To update the template structure for everyone (new column, different defaults), temporarily reverse:

```
git update-index --no-skip-worktree certifications_import_template.csv
# edit the template — keep the data rows blank
git add certifications_import_template.csv
git commit -m "..."
git push
git update-index --skip-worktree certifications_import_template.csv
```

## CLAUDE.md rules that apply

- Real cert / license numbers, issue dates, and worker mappings are PII. **Never paste the filled CSV's contents into chats.**
- All real data lives in `superstars.db` on the BitLocker-encrypted workstation drive.
- The import script's stdout redacts to worker-initial + last-4-of-card-number.
