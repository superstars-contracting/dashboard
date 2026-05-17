# Code Migration Manifest

**Source:** Personal laptop (this machine)
**Destination:** Lenovo ThinkStation P3 workstation (AMG-BKBASE)
**Transit:** GitHub private repository at `github.com/superstars-contracting/dashboard`
**Date:** May 2026

This document is the step-by-step playbook for migrating the codebase from laptop to workstation cleanly. Follow it in order. Each step lists what to do, why, and what to verify before moving to the next.

---

## Pre-flight checklist

Before starting the migration, all of these should already be true:

- [ ] **Workstation**: BitLocker on, YubiKey-protected admin@ Workspace + Advanced Protection, 1Password Business installed with both YubiKeys enrolled, Windows Defender on with clean baseline scan
- [ ] **GitHub**: admin@ account with both YubiKeys enrolled, `superstars-contracting` Organization created (free plan), private `dashboard` repository created, GitHub Desktop installed and signed in as admin@
- [ ] **Python 3.12** installed on workstation with PATH set, `python --version` and `pip --version` both work
- [ ] **Subscriptions Group** working end-to-end (verified by test emails)
- [ ] **subscriptions_ledger.csv** has GitHub Free entry added

If any of these are not complete, finish them first.

---

## Phase 1 — Prepare the laptop (5 min)

These files should already exist in `outputs/`. Verify they're all there:

- [ ] `.gitignore` (excludes secrets, DB, uploads from git)
- [ ] `requirements.txt` (Python dependencies)
- [ ] `MIGRATION_MANIFEST.md` (this file)
- [ ] `SECRETS_CHECKLIST.md` (what to set up in .env on workstation)
- [ ] `CONTEXT_HANDOFF.md` (paste as first message to new Claude on workstation)
- [ ] `CLAUDE.md` (project rules for Claude Code sessions)
- [ ] `AUDIT_REPORT.md` (HTML-first audit findings)
- [ ] `SUBSCRIPTIONS_TRACKING.md` (subscription discipline doc)
- [ ] `subscriptions_ledger.csv` (active subscription tracker)

---

## Phase 2 — Initialize git on laptop (10 min)

1. **Open Command Prompt or PowerShell on the LAPTOP**, navigate to the outputs folder:
   ```
   cd C:\Users\amitm\AppData\Roaming\Claude\...\outputs
   ```
   (Adjust path to wherever the laptop has the outputs folder.)

2. **Verify .gitignore is in place** (so the next step doesn't accidentally stage secrets):
   ```
   dir .gitignore
   ```
   Should show the file exists.

3. **Initialize git** (if not already done):
   ```
   git init
   ```

4. **Configure git identity** (so commits are attributed to admin@):
   ```
   git config user.name "Superstars Administrator"
   git config user.email "admin@superstarscontracting.com"
   ```

5. **Stage everything** (the .gitignore controls what's actually included):
   ```
   git add .
   ```

6. **CRITICAL — Review what's about to be committed BEFORE pushing:**
   ```
   git status
   ```
   Look for any files that LOOK sensitive: `.env`, `*.db`, `uploads/`, anything with keys/credentials in the filename. If you see ANYTHING that shouldn't be public-ish, STOP and update `.gitignore` first.

7. **Commit:**
   ```
   git commit -m "Initial commit — clean migration from laptop"
   ```

---

## Phase 3 — Push to GitHub (5 min)

1. **Get the GitHub repo URL** from the GitHub web page. For `dashboard` under `superstars-contracting`, the URL will be one of:
   - HTTPS: `https://github.com/superstars-contracting/dashboard.git`
   - SSH: `git@github.com:superstars-contracting/dashboard.git`

   For first-time setup, **use HTTPS** (simpler — GitHub Desktop handles auth).

2. **Add the remote:**
   ```
   git remote add origin https://github.com/superstars-contracting/dashboard.git
   ```

3. **Push:**
   ```
   git branch -M main
   git push -u origin main
   ```

4. GitHub will prompt for authentication. Sign in via the browser pop-up using admin@ + YubiKey.

5. **Verify on GitHub.com:** open the `dashboard` repo in your browser. You should see all the source files. Check that:
   - `.env` is NOT there
   - `superstars.db` is NOT there
   - `uploads/` folder is NOT there
   - `requirements.txt`, `*.py`, `*.html`, `*.sql` files ARE there

If you see anything sensitive — `git rm --cached <file>`, commit, push. Then rotate any exposed credentials.

---

## Phase 4 — Clone on workstation (3 min)

1. **On the WORKSTATION**, open **GitHub Desktop**
2. Click **File → Clone repository**
3. Pick the `superstars-contracting/dashboard` repo from your list
4. Choose a local path — recommended: `C:\Users\SSC-Admin\Superstars\dashboard`
5. Click **Clone**
6. Wait for download to complete

Open the folder in File Explorer to verify all files came through.

---

## Phase 5 — Install Python dependencies (5 min)

1. **Open Command Prompt** on workstation
2. Navigate to the dashboard folder:
   ```
   cd C:\Users\SSC-Admin\Superstars\dashboard
   ```
3. (Recommended) Create a virtual environment:
   ```
   python -m venv venv
   venv\Scripts\activate
   ```
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. This takes 2-5 minutes depending on connection. WeasyPrint has the most dependencies (it ships its own font/PDF libraries).

If WeasyPrint install fails on Windows: install the **GTK runtime** separately first (Google "WeasyPrint Windows install" for the current GTK link).

---

## Phase 6 — Set up .env with secrets (10 min)

Follow `SECRETS_CHECKLIST.md` step by step. The short version:

1. Create a new file in the dashboard folder: `.env` (just the dotfile, no extension)
2. Open it in Notepad
3. Add each secret from the checklist, format:
   ```
   SENDGRID_API_KEY=SG.actual-key-here
   NYC_OPENDATA_APP_TOKEN=optional-token-here
   ```
4. Save. Verify the file is NOT showing up in `git status` (because of `.gitignore`).

For SendGrid specifically — since admin@ doesn't have a SendGrid account yet, you'll need to sign up for SendGrid under admin@ first (per the architecture). This step blocks until that signup happens.

---

## Phase 7 — Run schema migrations (5 min)

1. In the dashboard folder, the database doesn't exist yet (it's gitignored). Create it by running migrations in order:
   ```
   python migrate_workbook_to_sqlite.py
   python apply_compliance_schema.py
   python apply_cof_schema.py
   python apply_worker_intake_schema.py
   python apply_assignments_schema.py
   python apply_riggers_schema.py
   python apply_subscriptions_schema.py
   ```
2. Each one creates tables and (where applicable) imports seed data
3. After all migrations: `superstars.db` exists with empty tables ready for real data

---

## Phase 8 — Smoke test (5 min)

1. Start the Flask server:
   ```
   python server.py
   ```
2. Open browser to `http://localhost:5050`
3. You should see the Company Dashboard with empty data (no projects, no workers, no compliance pulls yet)
4. Try the preview routes: `http://localhost:5050/preview/` — should list all available templates
5. Click into a few — they should render in the browser

If the dashboard loads and preview routes work, the migration is successful.

---

## Phase 9 — Switch to new Claude thread (1 min)

The current Claude thread (running on the laptop) ends here. Continue work on the workstation under the new company Claude account:

1. On the workstation, open Claude desktop app
2. Sign in with `admin@superstarscontracting.com` (your new company Claude account)
3. Start a new conversation
4. Copy the entire contents of `CONTEXT_HANDOFF.md` and paste as your first message
5. New Claude reads the context + the code in the dashboard folder
6. You're back in flow, in the new environment

---

## Phase 10 — Decommission laptop (when ready)

After confirming the workstation is fully operational for a day or two:

- Sign out of Claude on the laptop
- Sign out of Google admin@ on the laptop
- Sign out of 1Password on the laptop
- Revoke the laptop as a "trusted device" in 1Password and Google Workspace admin
- Then: physical destruction of the drive OR thorough wipe per the destruction plan

---

## If something goes wrong at any step

- **Git push fails:** check that the GitHub repo exists and you're authenticated as admin@
- **Pip install fails:** check Python version (must be 3.12+), check internet connection, sometimes need to retry
- **Schema migrations fail:** run them one at a time, read the error, the migration scripts are idempotent so re-running is safe
- **Flask won't start:** check for missing dependency (the error will say what's missing), make sure you're in the venv, check `.env` has the required keys

Reach out via the new Claude thread on the workstation if you hit something not covered here.
