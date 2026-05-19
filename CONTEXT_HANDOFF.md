# Context Handoff — Superstars Contracting Ops Platform

> **For the new Claude on the workstation:** paste this entire document as your first message in the new thread. Combined with reading the code files, you'll be fully oriented in seconds.

---

## Who you're working with

**Amit Mal**, currently filling the admin role at Superstars Contracting Inc. (NYC facade restoration contractor, growing toward a $4M EBITDA target). Owner of record is Arun Mal (Amit's brother, principal/VP). Amit is acting as consultant + admin during this digital infrastructure buildout.

The architecture is **role-based, not person-based**: `admin@superstarscontracting.com` is the role currently held by Amit, but is designed to outlast any individual. Future ops/admin hires take over this account intact.

Communication style: blunt, fast, wants execution not lectures. Skip "great question." Push back when scope creep or research-as-procrastination shows up. Acknowledge methodical decision-making.

---

## What the project is

A **local-first project management + operations platform** for a small facade restoration shop. Three primary surfaces:

- **Company Console** (`company-dashboard.html`) — strategic top-of-org view for the operator wearing the admin hat. EN/ES bilingual toggle. Eventually adds Subscriptions module, asset inventory, financial roll-up, portfolio health.
- **Project Dashboard** (`dashboard-static.html`) — operational per-project view for the PM. Currently focused on **890 E 135th Street (FR-BX-001)** — facade work in the Bronx, ~7 workers.
- **Worker PWA** (`worker-app.html`) — mobile sign-in app for the field crew. PIN = last 4 of worker's phone. Tested live on site, works.

Plus a **Certificate of Fitness (CoF) card** issuance system (NYC DOB suspended scaffold credential, ID-1 sized, multi-rigger schema for auto-fill).

---

## Stack

- **Backend:** Flask (Python 3.12) on `localhost:5050`. Binds to 127.0.0.1 only — never expose to LAN.
- **DB:** SQLite with WAL mode (`superstars.db`). Future: SQLCipher wrapper.
- **PDF generation:** WeasyPrint (HTML → PDF, called from `render_pdf.py`). Only used at export time. **All design happens in HTML first** — this is a hard rule (see CLAUDE.md).
- **Frontend:** Vanilla HTML/JS, no build step
- **Integrations:** SendGrid (email), NYC OpenData/DOB (compliance), Open-Meteo (weather, no auth needed)
- **OS:** Windows 11 Pro on Lenovo ThinkStation P3
- **PDF/dashboard preview infrastructure:** `preview_routes.py` (Blueprint registered in server.py) exposes `/preview/*` URLs for browser-iteration of every template — this is the design surface; WeasyPrint is the export-only path

---

## What's built and working

- Schema for `projects`, `workers`, `certifications`, `project_assignments`, `project_riggers`, `cof_cards`, `subscriptions`
- All schema migrations idempotent (`split_statements` pattern handles duplicate-column errors)
- Worker IDs format `E-XXXXX` — **critical: sort numerically via `CAST(SUBSTR(employee_id, 3) AS INTEGER)`, NOT lexicographically** (lexicographic caused the E-00013 collision bug, don't repeat it)
- Bilingual EN/ES dashboard via `data-i18n` attributes + JS `I18N` dict + `localStorage.dashboard_lang`
- Worker PWA with phone-PIN login, tested live, working
- CoF card print template (single + 4-up) — user-approved final design (`cof_card_final_4.pdf`)
- Multi-rigger schema with auto-fill on CoF back (1+ riggers per project, one default)
- Card numbering format: `SSC-COF-{employee_id}`
- NYC compliance live pulls (163 permits, 278 violations, 16 complaints verified for Bronx site)
- `/preview/*` routes — browser-first design surface for all templates
- `subscriptions_ledger.csv` + `schema_subscriptions.sql` — subscription tracking discipline live

---

## What's left for the immediate roadmap (post-migration)

In rough priority order:

1. **Workers CSV import** (Phase 1 of the Monday deployment plan) — bulk-import the 8 real 890 E 135th St workers from CSV, auto-derive PINs from phone last-4. **Status (2026-05-18):** completed via `import_workers.py --execute` during the FR-BX-001 rebuild flow.
2. **Certifications CSV import** (Phase 2) — link certs to workers by employee_id
3. **CoF Phase C** — dashboard issuance UI (PM picks worker + rigger → generates printable PDF)
4. **OpenCV card auto-crop script** — Amit has fresh phone photos of worker IDs/certs against white background; script detects, deskews, crops per-worker folders. Task #105 / `crop_id_cards.py` (pending build)
5. **PDF image extraction script** — pull embedded images out of existing roster PDFs in Drive (`extract_pdf_images.py`, pending build)
6. **Audit existing 6 Workspace users** — legacy accounts in the Workspace that need cleanup
7. **Add amit@ and arun@ as Workspace users + 1Password users** — currently only admin@ exists in 1Password
8. **Buy 2nd and 3rd YubiKey pairs** for amit@ and arun@ (~$200), enroll on their respective accounts
9. **Set up Arun as backup super-admin on Google Workspace** — real break-glass recovery layer
10. **SendGrid migration** — recreate under admin@ (currently on legacy account), update DNS, generate new API key

---

## What's deferred (do NOT pull forward)

- Full auth on Flask app (Tier 1, P3 phase)
- SQLCipher migration (Tier 1, this week if time)
- Twilio SMS / voice memos (Tier 3, next week+)
- Mac mini as automation node (next week or after)
- Cowork mobile / WhatsApp prompting (future, needs approval-gate design)
- Low-voltage contracting division (future, 6+ months out — don't conflate with current facade work)

---

## Security posture

- **Workstation = only place real PII lives.** Hardened: BitLocker + PIN, YubiKey-gated Windows login (via 1Password), Windows Defender on with clean baseline, standard user account, Windows firewall on, separate T-Mobile internet line.
- **Personal laptop is being destroyed** (or already destroyed). Was sandbox only.
- **Phone is low-trust** — personal only, no company data.
- **Three Claude accounts:** personal (phone, old laptop — if still alive) and company (this workstation under admin@superstarscontracting.com — you, the new Claude, are on the company account).
- **Role-based:** admin@ owns infrastructure. amit@ does PM work (on his own device, never on workstation). arun@ is backup admin (when set up).
- **Flask binds to `127.0.0.1`** only. Never `0.0.0.0`. Never port-forward.
- **2FA enforced** on admin@ in Google Workspace (Advanced Protection) and 1Password (org-wide enforcement). Both YubiKeys enrolled directly on both services. Recovery codes in 1Password + paper in safe.

---

## Data rules (firm)

- **Real worker PII never appears in Claude chats.** Not phone numbers, addresses, SSNs, ID photos, license numbers. If a value needs discussing, redact (W1, XXX-XXX-1234, [name redacted]).
- All real data lives in `superstars.db` on the BitLocker-encrypted workstation drive.
- API keys live in `.env` (gitignored, never committed). See `SECRETS_CHECKLIST.md` for what each is.
- Generated code that handles PII uses parameterized SQL, never logs raw PII to stdout or files.

---

## File layout (after migration)

```
C:\Users\SSC-Admin\Superstars\dashboard\
├── run_server.bat              # Starts Flask
├── server.py                    # Main Flask app, all API routes
├── preview_routes.py            # Browser preview Blueprint
├── requirements.txt             # pip deps
├── .env                         # API keys (LOCAL ONLY, never committed)
├── .gitignore                   # excludes secrets, DB, uploads, caches
├── CLAUDE.md                    # project rules (you should have read this on session start)
├── CONTEXT_HANDOFF.md           # this file
├── MIGRATION_MANIFEST.md        # migration playbook (already complete by now)
├── SECRETS_CHECKLIST.md         # secrets inventory
├── SUBSCRIPTIONS_TRACKING.md    # subscription discipline
├── AUDIT_REPORT.md              # HTML-first audit
├── subscriptions_ledger.csv     # active subscription tracker
├── superstars.db                # SQLite DB (starts empty, fills with real data here)
├── schema*.sql                  # schema definitions
├── apply_*_schema.py            # idempotent migration runners
├── generate_*.py / render_*.py  # per-document-type generators + renderers
├── render_pdf.py                # WeasyPrint CLI (production export only)
├── *.html                       # dashboards, worker app, CoF templates, etc.
├── cof_*.html, cof_issuer.py    # CoF card system
├── nyc_compliance.py            # NYC OpenData pulls
└── (uploads/, worker_intake_inbox/, venv/ — created locally, never committed)
```

---

## Known landmines / hard-earned lessons

- WeasyPrint silently breaks `flex` and `grid` on cards — use `<table>` with explicit row heights
- WeasyPrint struggles with SVG `<text>` elements — use HTML text alongside SVG shapes
- Escaped apostrophes in JS string literals (`worker\\'s`) can crash an entire dashboard — rephrase to avoid possessives
- Address lines on CoF front need `white-space: nowrap` + 1.55mm font, otherwise they wrap and push the footer off
- **NEVER design in PDF — design in HTML, browser-preview, export to PDF only at the end.** Iterating through PDF is what cost us 15+ rebuild cycles on the CoF card. This rule is hard. See CLAUDE.md.
- Worker IDs sort numerically (CAST), not lexicographically — see E-00013 collision in task history

---

## Communication style with Amit

- Brief acknowledge → execute → report. No long preambles.
- He'll tell you when he wants depth.
- If a decision is genuinely ambiguous, ask one focused question. If not, make the call and explain why in one line.
- Skills available at `C:\Users\SSC-Admin\.claude\skills\` (docx, pdf, pptx, xlsx) — Read SKILL.md before producing those file types.
- Push back when shopping creep, research-as-procrastination, or scope drift surfaces. He's specifically asked for this.

---

## Immediate next step when you start

If Amit hasn't directed you elsewhere, the next concrete task is **Phase 1: Workers CSV import**:

1. Generate `workers_import_template.csv` with columns: `first_name, last_name, phone, dob, emergency_contact_name, emergency_contact_phone, role, hire_date`
2. Write `import_workers.py` that reads CSV, generates `employee_id` (numeric-safe), derives PIN from phone last 4, inserts into `workers` table, prints summary table
3. Smoke-test by logging into the worker PWA as one of the new workers with their derived PIN

Phase 2 is the same pattern for certifications. Phase 3 is the CoF Phase C dashboard issuance UI. Phase 4 is OpenCV card auto-crop.

---

## What the laptop Claude (the previous thread) accomplished today

Major foundation work that you're inheriting:

- HTML-first audit done — every template clean, `/preview/*` routes added
- Subscription tracking system live (ledger + schema + import script)
- 1Password Business set up properly with YubiKeys + 2FA enforcement + corporate billing routed to subscriptions@
- Google Workspace admin@ active with Advanced Protection
- Subscriptions Google Group routing external email correctly
- All key credentials moved from paper to 1Password (Google admin password, BitLocker key, Secret Key)
- Subscription ledger entries created/updated for: T-Mobile, Workspace (pending payment), 1Password (active May 16 — $104.39/year annual), ThinkStation, monitors, UPS, YubiKeys, GitHub Free
- GitHub account under admin@ with both YubiKeys + recovery codes saved
- GitHub Organization `superstars-contracting` created with private `dashboard` repo
- Python 3.12.7 installed on workstation with PATH set
- All migration package files written (this one, .gitignore, requirements.txt, MIGRATION_MANIFEST, SECRETS_CHECKLIST)

You're picking up an established, secured, well-architected foundation. Build on it. The PM (Amit) has earned the right to focus on operational work now that infrastructure is sound.

---

## DB backup & restore (post-2026-05-18 incident)

On 2026-05-18 the working `superstars.db` was unexpectedly replaced with a 0-byte file under unclear circumstances mid-session; no backup existed, and the DB was rebuilt from `workers_import_template.csv` + the schema migrations. To prevent recurrence:

**Manual snapshot before any destructive operation:**

```powershell
$ts = Get-Date -Format yyyyMMdd-HHmmss
Copy-Item C:\Users\SSC-Admin\Superstars\dashboard\superstars.db `
          C:\Users\SSC-Admin\Superstars\dashboard\data_room\db_backups\superstars-checkpoint-$ts.db
```

**Daily scheduled snapshot (set up 2026-05-18, runs 23:00 nightly):**

```powershell
schtasks /Query /TN "Superstars DB Snapshot"     # verify it's installed
schtasks /Run   /TN "Superstars DB Snapshot"     # force a run now
schtasks /Delete /TN "Superstars DB Snapshot" /F # remove if no longer needed
```

**Restore from snapshot:**

```powershell
# 1. Stop the running Flask server first (Ctrl-C in its terminal)
# 2. Pick a snapshot
Get-ChildItem C:\Users\SSC-Admin\Superstars\dashboard\data_room\db_backups\ |
    Sort-Object LastWriteTime -Descending | Select-Object Name, Length, LastWriteTime
# 3. Restore
Copy-Item C:\Users\SSC-Admin\Superstars\dashboard\data_room\db_backups\<chosen-snapshot>.db `
          C:\Users\SSC-Admin\Superstars\dashboard\superstars.db -Force
# 4. Restart server
```

Snapshots are gitignored (`*.db`) and stay local. Rotate manually — there's no auto-prune.

---

**Now, read CLAUDE.md and the project files. Then ask Amit what he wants to work on first.**
