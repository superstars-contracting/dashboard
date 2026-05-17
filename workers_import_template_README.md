# Workers Import Template

How to add new workers to the dashboard in bulk.

## What this template is for

Fill `workers_import_template.csv` with the real roster, then run `import_workers.py` to insert them into the `employees` table.

## How to fill it

1. Open `workers_import_template.csv` in any spreadsheet tool (Excel, Numbers, LibreOffice). The file has a header row and 8 blank data rows.
2. Fill one row per worker. The `language` and `hire_date` cells are pre-filled with sensible defaults — overwrite per row if needed.
3. Save back to `workers_import_template.csv` in the dashboard folder root.
4. Dry-run first: `python import_workers.py`. Review what it would do.
5. When the dry-run looks right: `python import_workers.py --execute`.

The CSV stays machine-readable — no comment rows, no header notes. All guidance lives in this README.

## Column reference

| Column | Required | Format | Example | Notes |
|---|---|---|---|---|
| `name` | YES | text, single field | `Bob Smith` | Only NOT NULL field in the schema. No first/last split. |
| `phone` | YES | flexible | `(917) 555-0123` or `9175550123` | Script normalizes to digits-only for storage. Drives PIN. |
| `trade` | no | free text | `Mason / Pointer` | Free text — variety is fine. |
| `dob` | no | ISO `YYYY-MM-DD` | `1985-03-14` | PII — only fill if on file. |
| `email` | no | text | `bob@example.com` | |
| `emergency_contact_name` | no | text | `Maria Smith` | |
| `emergency_contact_phone` | no | flexible | `(917) 555-0456` | Same normalization as `phone`. |
| `emergency_contact_relation` | no | free text | `Wife`, `Brother`, `Mother` | Free text. |
| `language` | no (defaults `EN`) | `EN` or `ES` only | `EN` | Drives the worker app's i18n. Case-sensitive. |
| `hire_date` | no (defaults `2026-05-04`) | ISO `YYYY-MM-DD` | `2026-05-04` | Pre-filled with Monday-1; override per row. |

Rows where `name` is blank are treated as empty template rows and silently skipped — leave un-needed rows alone.

## Auto-generated at import time (not in the CSV)

- `employee_id` — next numeric ID via `CAST(SUBSTR(employee_id, 3) AS INTEGER)` + 1, formatted `E-{n:05d}`. First worker in an empty table becomes `E-00001`.
- `pin` — last 4 digits of `phone` after stripping non-digits.
- `folder_path` — `worker_records/{employee_id}_{slugified_name}/`. Script also creates the folder and a nested `id/` subdirectory.
- `intake_status` — `pending`.
- `created_at`, `updated_at` — SQLite `CURRENT_TIMESTAMP`.

## Left NULL at import

- `face_image_path`, `photo_path` — populated later via the intake UI / OpenCV cropper.

## Pre-flight validation

Before any DB write, the script checks every row:

- `name` not blank
- `phone` present and yields at least 4 digits after non-digit stripping
- `dob` and `hire_date` parse as ISO `YYYY-MM-DD` when non-blank
- `language` is `EN` or `ES` (case-sensitive) when non-blank
- **No PIN collisions** — across incoming rows AND existing `employees.pin` values. Any collision aborts the entire import with the names involved. Resolve manually (e.g., use a different phone or a manual PIN override later) and re-run.

Any validation failure aborts before a single INSERT runs.

## Re-running on an already-imported CSV

Safe. The script dedups by `(name, phone-digits-only)`. Rows already present in the table are reported as already imported and skipped — nothing duplicates.

## Local PII protection

The template is tracked in git in its blank state. Once filled with the real roster, the file contains worker PII — phone numbers, emergency contacts — which per CLAUDE.md rule #2 must never leave the BitLocker-encrypted workstation. The risk: a future `git add .` or `git commit -am` would happily commit that PII to the private repo on GitHub.

The mitigation is `git update-index --skip-worktree workers_import_template.csv`. Git stops noticing local edits to the file; the repo's tracked version stays the blank template; the operator can refill or edit the local copy freely without ever staging it. Verify with `git ls-files -v workers_import_template.csv` — an `S` prefix means skip-worktree is active.

If the template structure needs to change for everyone (a new column, a different default), reverse the flag temporarily:

```
git update-index --no-skip-worktree workers_import_template.csv
# edit the template — keep the data rows blank
git add workers_import_template.csv
git commit -m "..."
git push
git update-index --skip-worktree workers_import_template.csv
```

This pattern is preferred over `.gitignore` because the template itself must remain tracked so anyone cloning the repo gets the column structure and defaults. Only the local *contents* are hidden.

## CLAUDE.md rules that apply

- Real PII lives in `superstars.db` on the BitLocker-encrypted workstation drive. **Never paste the filled CSV contents into chats.**
- The dashboard binds to `127.0.0.1` only; the database is local.
- The script's stdout includes PIN values after a successful run — keep that output local too.
