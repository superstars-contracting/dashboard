# Handoff to the next Claude Code session

> **Read this + `CLAUDE.md` at the start of every new session.** Together
> they orient you in ~2 minutes. This doc is the operational snapshot;
> CLAUDE.md is the pinned rules.

---

## Where the system is right now

A continuous-run, single-project ops platform for **Superstars
Contracting Inc.** (NYC facade restoration). Single active project:
**FR-BX-001 / 890 E 135th Street, Bronx** (client: Compass Point, LLC). 8-worker
real roster. Server runs unattended under a Windows scheduled task and is
exposed to the operator's phone/tablet via Tailscale (private serve, not
public funnel).

Real external users are on the live system: two **clients** and one
**architect**. Everything they can see is default-deny and re-derived
per request — see "Access model" below before touching any portal,
grant, or elevation code.

### Cloud M1 (#287) — the storage abstraction

Every DATA path resolves through **`ssc_paths.py`** driven by **`SSC_DATA_ROOT`**:
unset (production today) = exactly the old repo-dir layout, byte for byte; set =
all data categories under the root (`<root>/data_room/...`, `<root>/worker_records`,
`<root>/superstars.db`). Categories: media (field_photos, project_docs, photos,
receipts, walkthroughs, estimate_docs, material_slips, worker_records,
employee_photos, issuer_signatures), renders (reports, credentials, forms,
toolbox_talks, signage, cof_exports + the legacy root output dirs), logs, db.
Static assets and code stay repo-relative. STORED rows: every pre-#287 `*_path`
is an absolute Windows path — reads go through `ssc_paths.resolve_data_path()`
(as-is while it exists; re-anchored under the active root by its data anchor
once the tree moves); NEW media writes store RELATIVE paths (`store_rel`).
`migrate_data_root_287.py` copies + sha256-verifies the tree per category
(dry-run default; idempotent re-run = verify). Guard:
`tests/smoke_data_root_287.py` (own rooted server; upload/render/serve under a
scratch root; repo-tree mtime watchdog proves zero out-of-root writes). The
gate runs green in all four backend×root configs. NOT yet cloud: M2 = PDF on
Linux, M3 = public-door hardening, M4 = bring-up (see the operator's
CLOUD_MIGRATION_BLUEPRINT.md).

### Cloud M4 (#290) — bring-up artifacts (blueprint + tz + battery)

The repo now carries the full Render bring-up kit — see
**CLOUD_M4_RUNBOOK_290.md** for the operator flow, rehearsal procedure and the
M5 final-sync runbook. Pieces:

- **render.yaml + Dockerfile + .dockerignore** — one web service
  (`ssc-dashboard`, docker runtime, starter, region virginia — MUST match
  ssc-dashboard-db), disk `/var/data` (5 GB), health `/api/health`, env
  topology values literal + every secret `sync: false` (names only; values
  1Password → Render). Image: python:3.12-slim + chromium (+ fonts-inter/
  liberation/dejavu, tzdata, rsync). Waitress binds 0.0.0.0:$PORT INSIDE the
  container — a documented, deliberate exception to the loopback rule (no LAN
  in a container; Render's proxy is the only ingress). The workstation deploy
  keeps 127.0.0.1:5050.
- **SSC_TZ enforcement (`ssc_tz.py`)** — `ssc_tz.enforce()` is the FIRST call
  in server.py: SSC_TZ set + POSIX → export TZ + tzset() before any date use
  (UTC host thinks in Eastern); unset → no-op; Windows → hard no-op that never
  exports TZ (MSVC would misparse IANA names in children). Unresolvable zone
  RAISES at boot (#288 fail-fast doctrine). db_layer opens PG sessions with
  `TimeZone=<SSC_TZ>` (libpq options, connection-scoped). Guard:
  `tests/smoke_tz_290.py` (gate #36) — planted 23:30-Eastern boundary instants
  (EST + EDT) where UTC date ≠ Eastern date, POSIX UTC-host simulation with a
  can-fail control, Windows no-op contract, boot-order source check, live
  /api/today probe.
- **Linux sweep** — generate_credentials_batch now goes through db_layer
  (was 3× raw sqlite3.connect: broke the bundle on PG AND read LIVE under the
  gate) and its dead EDGE_PATHS list is gone. Known-fine Windows-isms left in
  place: pdf_export's exists()-guarded Edge/Chrome fallback paths, workstation
  tooling (.ps1, tests' taskkill), 22 CRLF shebangs (nothing execs them
  directly), apply_refresh_cofs_171's hardcoded dir (one-time, historical).
- **Remote verification** — `tests/acceptance_battery_290.py` (PRE = health/
  login/auth-gate/static/worker-app/timezone; FULL adds synthetic is_system
  login, chromium PDF w/ page count, portal containment probes, photo-serves,
  DCR client render; refuses full phase on a non-Postgres SSC_DB_URL) and
  `tests/verify_media_remote_290.py` (per-tree counts/bytes + sampled sha256
  over Render SSH, PII-safe output).

### Cloud M3 (#289) — public-door hardening (DEPLOYED behavior)

The login endpoint, staff auth, and worker PIN flow are hardened for the M5
public exposure. **Enforcement switches ship OFF (grace) so the deploy strands
nobody; the operator flips them after enrolling people** — see the OPERATOR
2FA / DEVICE TO-DO below.

- **Login** (`auth.py`): per-account + per-source(IP) fail counting →
  exponential backoff, uniform on right/wrong password (no timing oracle);
  hard lockout refuses even a correct password with the identical 401
  (audited `login_lockout`); unknown-email ≡ wrong-password response (no
  enumeration). `_client_ip` trusts `X-Forwarded-For` ONLY when
  `SSC_TRUSTED_PROXY` is set. Sessions: rotate on login, absolute 7-day
  ceiling atop the 12h slide, logout server-invalidates. `_request_is_https`
  honors `SSC_TRUSTED_PROXY` (waitress strips untrusted XFP) so the Secure
  cookie flag is correct behind the M4 TLS edge.
- **Staff 2FA** (`totp.py` stdlib RFC-6238 + `auth_hardening.py`):
  self-service TOTP at `/api/2fa/begin|confirm|disable` (Settings panel UI),
  otpauth URI + 10 bcrypt-hashed single-use recovery codes; login two-step
  (password → `totp_required` 401 → code), enumeration-safe. `force_sso`
  admin flag disables the password path (403 `sso_required`), refused unless
  the account has `google_sub`. Console banner (`/api/admin/2fa-status`)
  lists staff still missing a factor.
- **Worker PIN** (`server.py` + `auth_hardening.py`): per-source PIN throttle
  ALWAYS ON; device binding behind `app_settings.worker_device_enforcement`
  (default `0` = grace). When `1`, a valid PIN also needs a `device_token`
  from one-time provisioning (admin issues a 6-digit code / `?provision=`
  URL → the phone redeems it for a localStorage token). Revocable per device.
- Schema: `apply_public_hardening_289.py` (idempotent, dual-backend, **ensured
  at server boot** — no manual migration step on deploy). Secrets: runtime
  reads env only (guard-asserted); inventory in `SECRETS_INVENTORY_289.md`
  (the M4 Render env group).

**OPERATOR 2FA / DEVICE TO-DO — before the M5 public DNS flip:**
1. Each staff account (admin/c_suite/pm/super/estimator) gets a second
   factor. Fastest: **link Google SSO** (already domain-restricted). Or
   enroll **TOTP** in Settings → Two-Factor. Do the **admin account(s) first**,
   then c_suite, then pm/super/estimator. The console banner lists who's still
   missing one; it clears as you go.
2. Optionally set `force_sso` on staff who should be SSO-only (must have SSO
   linked first).
3. Provision the **8 field phones** (worker-devices/provision → open the
   `?provision=` URL on each phone, enter the Worker ID). Then flip
   `worker_device_enforcement` to `1` (worker-devices/enforcement). This is a
   **hard pre-M5 gate** — do NOT flip the public DNS until it's on.
4. At M4, set `SSC_TRUSTED_PROXY` in the Render env group so per-IP throttling
   and Secure cookies read the real client through Cloudflare/Render.

### Cloud M2 (#288) — PDF engine abstraction

`pdf_export.py` is engine-selectable via **`SSC_PDF_ENGINE`** ('edge' |
'chromium'; unset -> edge, today's Windows path byte-for-byte). Chromium
binary from `SSC_CHROMIUM_PATH` (must exist when set — a wrong path raises
a clean PDFExportError, never a fallback), else PATH lookup (chromium /
chromium-browser / google-chrome / chrome), else the Windows Chrome dirs.
ALL engine-specific flags live in `engine_flags()` — edge keeps
`--headless=old` (its print-flush quirk); chromium uses `--headless
--no-sandbox` (modern Chrome dropped old-headless; containerized M4 hosts
need no-sandbox, and our renders are our own self-contained file:// HTML).
The result dict keeps its historical shape — the browser path stays under
"edge_path" (the #247 response scrub list keys on it) with an "engine" key
alongside. generate_credentials_batch consumes the SAME discovery + flags
(its two embedded Edge command blocks are gone). Engine parity proven on
the workstation across 7 doc types (DCR internal+client, weekly-hours,
blank form, toolbox talk, signage, CoF credential card): identical page
counts, size ratios 1.00-1.17; the credential BUNDLE shares the pipeline.
Guard: `tests/smoke_pdf_chromium_288.py` (gate #34). M4 sets
SSC_PDF_ENGINE=chromium on the cloud host.

### Architecture in one paragraph

Flask (Python 3.12) + waitress on `127.0.0.1:5050`, vanilla HTML/JS
frontend (no build step). Data access goes through **`db_layer`**, driven
by `SSC_DB_URL`: SQLite (`superstars.db`, WAL) is the default and what
production runs; Postgres is supported and the gate runs on both. PDF
render is headless Microsoft Edge (`pdf_export.py`) — WeasyPrint/GTK won't
install on Windows Home and is no longer used. Surfaces:

- **Company console** (`company-dashboard.html`) — workforce list, cert
  health, Weekly Hours Log. Hosts comp-side data; **field-restricted**.
- **Project dashboard** (`dashboard-static.html`) — per-project DCR
  entry + archive, sign-ins, photos. Field-reachable via Tailscale.
  Rendered **per role**: gated SECTION blocks are stripped server-side.
- **Worker app** (`worker-app.html`) — mobile PWA, PIN sign-in (PIN =
  last 4 of phone). Field-reachable.
- **Client portal** (`client_portal.html`, "Classic") — what real clients
  see today. Per-item visibility engine (`visibility.py`): a document or
  photo is invisible unless explicitly shared to the client audience, and
  ownership is re-derived from the row on every by-id fetch.
- **Drawing markup** (`templates/v2/drawing-markup.html`) — the #280
  elevation surface, shared by internal roles, architect and client.

DCR renderer (`render_dcr_html.py`) emits 11-section SSC-branded HTML
with inline-SVG logo, print-CSS that mirrors screen layout (0.55in
insets, two-column paired sections, `break-inside:avoid` on `.sec`),
and a `beforeprint` JS that fits-to-one-page when a report is
≤1.25× a page (Chromium `zoom` — paint-only `transform` was wrong).

### Access model (read before touching portal / grants / elevation)

Three independent axes, each enforced server-side on every request. Hiding
a nav item is never access control.

1. **ROLE → sections** (`access.py SECTION_ACCESS`). One source feeds both
   sidebar stripping and endpoint gates. Eight roles: `admin`, `c_suite`,
   `pm`, `super`, `estimator`, `client`, `architect`, `vendor`.
2. **ASSIGNMENT → projects** (`pm_project_assignment`). pm/super/estimator/
   architect see assigned projects only; a client sees the single project
   their portal is bound to.
3. **GRANT → portal sections** (`client_section_grant`, #269). Per-client,
   per-section, **default OFF**. Zero grants = the #267 hard-stop: the
   client is contained on `/welcome` and every API 403s.

**Grant wiring as of #283.** `client_grants.SECTIONS` is what MAY be
granted; `SERVED_SECTIONS` is what a grant actually OPENS today. The admin
UI renders toggles for the intersection, so a section whose portal payload
does not exist yet (`weekly`, `materials`) is catalogued but shows no
toggle — never a grant that opens to nothing. `drawing` gates the drawing
markup page, `/api/elevations`, `/api/elevation/*` and drop/photo comment
threads; `rfis` gates `/api/rfis` and RFI comment threads. Presets are
explicit copies, never the catalog object (an import-time guard enforces
it): Standard excludes drawing/rfis, Full includes them.

The architect is contained by an **allowlist** (`elevation._architect_gate`)
— a route added tomorrow is closed to them until someone opens it — plus
normal project scoping. Architects are not grant-gated on their own
drawing surface.

**#286 — THE PARITY CONTRACT (doctrine; supersedes the #285 wording).**
Parity is PAGE ANATOMY, not component styling: for every portal section the
page SKELETON — header block, KPI tile row, widget grid, tables, boards —
is IDENTICAL to its internal counterpart; only the data feeding it differs
(the `client_payload()` registry, as always). The shared layer is
`/files/static/css/widgets.css` (`shc-` families, extracted verbatim from
the internal fp-/ph-/dcr-/wx-/la- rules) PLUS the actual layout engine:
`/files/static/js/dash_layout.js` + vendored GridStack are consumed by
BOTH surfaces — the portal Progress grid is the same drag/persist/reset
machinery as the internal dashboards (page_key `portal_progress`,
`/api/dashboard/layout` opened to granted clients: user-scoped,
key-allowlisted, structurally sanitized). Plumbing separation unchanged:
allowlist shell, registry-only data, never serve internal pages to
external roles. Client-safe DELTAS are subtractions, never substitutions
(a removed workforce tile is not replaced with worker data; removed
actions leave read-only anatomy).

**PROVENANCE EXCEPTION (#286, planner-approved):** look-ahead activity
TITLES cross to the client — they are planning labels designed for
external consumption (the internal Print exists to share that board).
Delivery titles are REPLACED with the generic "Delivery" before
projection; crew, notes, source and constraint counts never cross. This
is the ONLY free-text field with an external pass; anything else still
requires its own explicit decision here.

**#286 anatomy notes.** Daily = the internal DCR archive (KPI tiles,
search + date range, black-header table); the view icon serves the
CLIENT-AUDIENCE render by sequence (`/api/portal/<code>/daily/<seq>/view`
— serves `client.html` and nothing else; audience is per-render). The
status-churn feed collapses to NET day-level changes (X→X and same-day
round trips render nothing) and lives as a secondary expand block inside
the table row. Schedule = the internal Two-Week Look-Ahead board
read-only via `load_window` (NEVER the drafting GET — a client request
must never write), minus the constraints column. Admin client-access page
has ONE Preview button; Classic remains server-side purely as rollback.

**#284 — THE FLIP IS LIVE.** `/portal/<code>` is the CLIENT's home:
`portal_shell.html` (allowlist-first — the file contains ONLY portal
components), nav + view panes rendered from the client's EFFECTIVE set =
`portal_matrix.ROLE_SECTION_MATRIX[role]` ∩ #269 grants, fetching
`/api/portal/<code>/{progress,photos,documents,daily}` (portal_sections.py —
every field through the `client_payload()` registry, audience hard-coded
"client", URL code must equal the client's bound project). `/welcome` and
Classic `/portal` 302 granted clients to `/portal/<code>`; the #267
zero-grant hard-stop is unchanged; the architect keeps `/drawing-markup`;
the Classic ENGINE (its /api/portal/* payloads + id-gated byte routes +
admin Classic preview) is intact. Admin preview of the new shell is
byte-identical to the client's own page by construction.
**ROLLBACK = `git revert 2c4fb4a` (the flip commit) + #244 restart — one
commit, nothing else.** Guarded by `tests/smoke_portal_flip_284.py` (56
checks, planted-failure-proven) + the updated landing contracts in
smoke_portal_shell_281 / smoke_client_grants_269.

### Two invariants that are load-bearing

**DCR numbers are immutable.** A DCR's number is its identity (report_id,
render dir, anything printed). `next_dcr_sequence` allocates strictly
`MAX(seq)+1`; issuing a report NEVER renumbers an existing one regardless
of date order; a deleted number stays retired (no gap-fill reuse). Date
ordering is a *display* concern — sort by `report_date`. The old
date-positional allocator + `shift_dcrs_for_backdate` renumbered two real
issued reports during normal operator use and were removed in the #282
repair pass; `renumber_dcrs_by_date.py` was deleted in #283 for the same
reason. Do not reintroduce either.

**Status colour comes from the status table, never from a template.**
`status_tone` holds the five-tone ladder used by the elevation module,
keyed `elevation.<key>`, ordered by `severity_rank`:

| key | label | tone | severity | client-visible |
|---|---|---|---|---|
| `not_started` | Not started | neutral | 0 | yes |
| `complete` | Complete | green | 10 | yes |
| `in_progress` | In progress | blue | 20 | yes |
| `on_hold` | On hold | gold | 60 | yes |
| `rework` | Rework | coral | 80 | yes |

`on_hold` and `rework` are alert statuses (severity ≥ 60) and **require a
reason** (400 without one). A drop's work status is **derived** from its
cells and never stored: any rework → rework; any on_hold → on_hold; all
complete → complete; any movement → in_progress; else not_started.
`reason` is external by construction; `internal_note` is a separate column
that never enters an external payload. Phase 2 seeds more modules into
this table — it must not recreate it.

### DB baseline

103 tables (SQLite live; Postgres `ssc_test` mirrors it for the gate).
The old 42-table/77-row "clean slate" figure below is historical.

```
(historical — 2026-05-20 clean slate)
42 tables, 77 rows total

reference (preserved):
  employees:            8       (full real roster, W-0001..W-0008 backfilled)
  projects:             1       (FR-BX-001 only)
  project_assignments:  8       (all active)
  project_riggers:      2       (TBD placeholders — replace before live CoF use)
  cert_types:          47       (catalog)
  app_settings:         3
  subscriptions:        8

transactional (all zero — clean slate):
  sign_in_log: 0   work_log: 0   deliveries: 0   equipment_log: 0
  safety_events: 0   toolbox_talk_records: 0   issues: 0   inspections: 0
  visitors: 0   photos: 0   weather_log: 0   report_index: 0

issued credentials (zero):
  cof_cards: 0   company_id_cards: 0   certifications: 0

flagged-but-untouched (RFI, meetings, lookahead, drop_plan, NYC DOB
caches, identifications, worker_documents, employee_assignments, ...):
  all at 0
```

Latest pre-wrap snapshot: `data_room/db_backups/superstars-post-clean-slate-2-20260520-232822.db`.

---

## How to run / test

### Start the server (continuous-run)

```powershell
# Start the scheduled task that runs waitress on 127.0.0.1:5050.
# Hidden, no PowerShell window required.
Start-ScheduledTask -TaskName "SSC Dashboard Server"

# Verify (expect HTTP 200, 121K-ish page):
Invoke-WebRequest http://127.0.0.1:5050/ -UseBasicParsing
```

### Stop / restart for maintenance

```powershell
Stop-ScheduledTask -TaskName "SSC Dashboard Server"
# Then for a code change: Start-ScheduledTask again. (No code-reload
# in the production task; restart applies new code.)
```

### Inspect the launcher logs

```
data_room/server_logs/server-YYYY-MM-DD.log
```

Boots, waitress-vs-dev decision, exits, restart-count, and Python
tracebacks all land here.

### Kill orphan on 5050 (before any smoke or new server)

```powershell
$c = Get-NetTCPConnection -LocalPort 5050 -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $c) { cmd /c "taskkill /F /T /PID $($conn.OwningProcess)" }
```

`Popen.terminate()` and `Stop-Process` don't reliably kill Flask on
Windows. Use the tree-kill. (See CLAUDE.md operational-discipline rule.)

### Run THE GATE (the thing to run before any deploy)

Never against live — the runner refuses without `SSC_DB_URL`:

```powershell
# SQLite, isolated copy of live
python -c "import sqlite3; s=sqlite3.connect('file:superstars.db?mode=ro',uri=True); d=sqlite3.connect('../snapshots/ssc_gate.db'); s.backup(d)"
$env:SSC_DB_URL="sqlite:///C:/Users/SSC-Admin/Superstars/snapshots/ssc_gate.db"
venv\Scripts\python.exe tests\run_gate_260.py
```

```powershell
# Postgres (portable dev instance; pg_ctl gets its OWN command — never
# chained with a python DB step, that wedges it)
.pgdev\pgsql\bin\pg_ctl.exe -D .pgdev\data -o "-p 5433" -l .pgdev\pg_start.log -w start
```

```powershell
venv\Scripts\python.exe migrate_sqlite_to_pg_259.py ..\snapshots\ssc_gate.db postgresql://postgres@127.0.0.1:5433/ssc_test --reset
$env:SSC_DB_URL="postgresql://postgres@127.0.0.1:5433/ssc_test"
venv\Scripts\python.exe tests\run_gate_260.py
```

31 suites, both backends, ~2 min (SQLite) / ~5 min (PG). A single suite:
pass its filename as an argument.

### Run a smoke test

Repository has two volume smokes in `tests/`:

```bash
python tests/smoke_dcr_volume.py             # 200 DCRs + 30 gap-fill cycles, ~7 min
python tests/smoke_dcr_backdated_30day.py    # 30 backdated days with manual labor, ~40 s
python tests/smoke_weekly_hours.py           # Weekly Hours Log + DCR consistency, ~30 s
```

Each self-manages the server lifecycle (starts a separate Popen,
`taskkill`s it on finally). PII-safe — synthetic IDs + counts only.
Validated-ceiling table in `TESTING_LIMITS.md`.

### Snapshot before any destructive op

```bash
# #248: snapshots live OUTSIDE the project root (never under a servable tree)
cp superstars.db "../snapshots/superstars-pre-<op>-$(date +%Y%m%d-%H%M%S).db"
```

---

## Builds #279–#283 (the current arc)

- **#279 — UI v2 toggle, phase 0.** Per-user Classic/New switch with silent
  fallback. There is **no Jinja in this app**: a v2 page is a twin file at
  `templates/v2/<name>`, resolved by `ui_version.resolve_page`, and the
  role-based SECTION stripping runs on whichever file is chosen.
- **#280 — Drawing markup / North elevation.** Traced North elevation, 12
  drops × 5 levels = 60 cells, per-cell work status with append-only
  events, plus comments (step 4) and RFIs (step 5). Introduced the
  `architect` role and its containment gate.
- **#281 — Portal foundation.** One shell served from two namespaces
  (`access.render_api_base`), the `client_payload()` field registry
  (provenance, not vocabulary — a field absent from the registry is never
  emitted), the Classic/New preview switch, four new grantable sections.
- **#282 — Verification + repair.** Audited what #280/#281 shipped
  straight to production. Found the containment lock existing only in a
  working tree (now committed), proved the Classic documents/photos chain
  untouched, and root-caused + fixed the DCR resequencer that had
  renumbered two real reports. Live numbering restored and re-rendered.
- **#283 — Fold-in (this build).** Grant wiring (above), two new guard
  suites, design-guard registration for the v2 tree, DCR artifact cleanup,
  `renumber_dcrs_by_date.py` retired, merge to main.

### Guard coverage added in #283

- `tests/smoke_markup_280.py` — elevation scoping, internal-vs-external
  vocabulary split, `internal_note` absence asserted **by key, recursively**,
  status-write validation and the reason law, drop-status derivation
  (five planted cell mixes), cell history audience filtering, comments
  (client read-only, rate limit, soft delete), RFIs (numeric allocation,
  role split, attach-later), and the grant wiring end to end.
- `tests/smoke_portal_shell_281.py` — the containment lock, pm scope,
  preview validation + audit on both paths, served-shell scrub asserted
  on the **DOM** (scripts stripped first — a view name inside a guarded
  `querySelector` is not a section), catalog shape, fail-closed registry.

Both are wired into `tests/run_gate_260.py` and both were proven by
planted regression: a payload leak and a fail-open registry each turn the
relevant suite red, and the code restores clean.

## Known gaps / operator decisions pending

- **RESOLVED (#284, operator-approved):** 2026-07-16 → **DCR-062** and
  2026-07-17 → **DCR-063** re-issued 2026-07-28 from surviving DB data
  through the standard pipeline (next-free numbers per immutability; 054/
  055 stay retired). Each report carries an Administrative issues-row note
  ("Re-issued 2026-07-28 from database records; original render lost in
  the 2026-07-23 renumbering incident."), rendered in BOTH audiences.
  **DCR-041** artifacts re-rendered at its existing number, content-
  verified. Audit: `dcr_reissue_284` / `dcr_rerender_284`. The quarantined
  originals at `snapshots/dcr_quarantine_283/054|055` are retained
  untouched. Tree verified: seqs 1–63 contiguous-by-allocation (54/55
  retired), zero unindexed dirs, zero missing renders.
- `report_index` id 11754 (2026-07-07) is a dead `no_work_pending`
  placeholder (no_work=0, seq NULL) beside that date's issued seq-47 rows —
  harmless promotion residue, excluded from contiguity checks. Delete or
  leave at leisure.
- The live architect user has **no `pm_project_assignment` row** — they
  cannot open any elevation until assigned to FR-BX-001.
- `.orphan_dst_058_*` — a PDF-only remnant whose identity could not be
  established (Edge PDFs use subset font encodings, so the text is not
  extractable). Quarantined, not destroyed.

## Pending work (by priority — pick from the top)

### The portal-flip track (#284 SHIPPED the core; remainder below)

- DONE 2026-07-28: matrix + nav-from-grants + progress/photos/documents/
  daily payloads through the registry + THE FLIP (clients land on
  `/portal/<code>`). The new shell's schedule view re-consumes Classic's
  curated `/api/portal/schedule`; drawing renders as a nav link when
  granted.
- REMAINING: weekly / materials portal payloads (catalogued, unserved);
  the fancy sections (weather, drops-by-status, progress-by-elevation)
  through the registry; S/E/W elevation tracing; architect grant
  machinery if the architect ever gets shell sections.

### Field-blocking before tomorrow's site test

- **#73 — Site Super onboarding flow.** The dashboard's "Onboard" button
  is wired (company-dashboard), but no end-to-end "I'm the site super,
  add me as a worker" walkthrough exists. Needs: a brief operator
  script + maybe a guided form, and a check that the new worker shows
  up in the labor manual-add dropdown and in the DCR labor section the
  same day.
- **#62 — Google Drive auto-archive (drive_targets.json `root` is
  empty).** Code is built (`drive_archive.py`, hooked into
  `_issue_one_dcr`). What's missing is the actual filesystem path to
  the Drive-synced "890 E 135th Street" folder. Install Drive for
  Desktop, sign in, find 890's folder in File Explorer, paste the
  path into `drive_targets.json` (the `_note` in that file is the
  cheat sheet). After that, every finalized DCR PDF auto-copies to
  `<root>/Daily Reports/`.

### Roadmap (not field-blocking, ordered)

- **#71 — Labor Sheet + pay rates** (company-console only). Per-worker
  hourly rate × weekly hours = gross labor cost; a comp-side view
  alongside the existing Weekly Hours Log. **Strict surface
  restriction**: never on the project dashboard, never field-reachable.
  See CLAUDE.md "Compensation / payroll data governance" section.
- **#72 — Comp-data governance / SQLCipher.** Encrypt the SQLite DB at
  rest (SQLCipher wrapper). BitLocker is the only encryption layer
  right now; a stolen workstation with BitLocker disabled exposes the
  DB. **Decision 2026-06-10 (#239):** the old pull-forward trigger
  ("before real pay-rate data lands") fired when Labor Rates (#220–#222)
  shipped — consciously NOT pulling SQLCipher forward. BitLocker covers
  at-rest on the workstation, and SQLCipher does not address the live
  attack surfaces (a running server reads a decrypted DB either way).
  Re-bundled into the **Backblaze backup task** — the point where DB
  copies first leave the BitLocker boundary; encrypted backups are the
  minimum bar there. New trigger: implement with (or before) Backblaze,
  not tied to Labor Rates.
- **#53 — Tailscale ACL.** Today the tailnet is open within the org;
  any device on the tailnet can hit the dashboard. Need ACL: which
  tailscale users / device-tags can reach `127.0.0.1:5050` via serve.
  Keep field devices to the project-dashboard surface only; keep
  company-console behind a stricter ACL.
- **Path B — `op run` integration with the scheduled task.** Currently
  the task launches without `op run`, so `ANTHROPIC_API_KEY` is unset
  → AI cert extraction returns 503. Path B injects the vaulted key at
  task start. Needs the 1Password CLI to be runnable from the scheduled-
  task context (S4U or stored credentials) — the design is in the
  `SECRETS_CHECKLIST.md` "vault pattern" section.
- **#64 — Live time model.** Today, `sign_in_log.time_in` /
  `time_out` are the BILLABLE in/out times the operator enters or the
  worker app records on sign-in. The roadmap adds a SEPARATE
  attendance-timestamp column so live-PIN attendance can layer on top
  without redefining what payroll reads. `payroll_hours.py` docstring
  flags this as a forward note; the schema migration + worker-app
  flow are TBD.

---

## Recent commits orientation — HISTORICAL (pre-#248 rebuild era)

The list below predates the auth/portal/estimating arc. For current
orientation use `git log --oneline -25` and the build summaries above.

### Older list (kept for the DCR-renderer context)

```
51ff3dc feat(deploy): continuous-run scheduled task — Path A, no `op run` (task #54)
717aeb0 feat(dcr): auto-fit-to-one-page when a report just barely overflows (≤1.25×)
c01cf01 fix(dcr): print insets match screen — PDF reads framed, not edge-to-edge
d6a65ea fix(dcr): preserve two-column layout in print/PDF (paired sections)
21efe9f fix(dcr): header title no longer clips at the right edge (browser + PDF)
0bddc00 feat(dcr): redesign render_dcr_html — black/red/white SSC brand + print pagination
9fc60c2 fix(dcr): use local-timezone today as date-picker default (#74)
8bbaf8a fix(dashboard): sweep remaining UTC toISOString() date sites (task #77)
626454f fix(workers): Onboard/Edit forms — relation reveal + live phone mask
0fe86ca feat(workers): emergency-contact relation dropdown (#13)
e5c397d refactor(payroll): "worked hours" terminology — rename helper + relabel
1ec775f feat(workers): "Add Worker"→"Onboard" + "Hired"→"Onboarded"
24aa693 feat(workers): display phone numbers as XXX-XXX-XXXX (Fix 2 / task #16)
d305a2b feat(workers): Worker ID (W-####) — schema, allocator, backfill, surfaces
c42856e test(payroll): PII-safe smoke for the Weekly Hours Log
a3dd977 feat(payroll): Weekly Hours Log frontend
f878fad feat(payroll): Weekly Hours Log backend
```

Earlier history (DCR + CoF + Company ID + 200-DCR smoke + Worker Intake
flows) extends back to the rebuild commit `683d574` (post-incident DB
restore from CSV).

---

## What to do on session start

1. Read CLAUDE.md (rules) + this file (state).
2. `git status` — should be clean, on `main`. **If anything is
   uncommitted, find out why before touching it**: #282 found production
   running a security lock that existed only in the working tree.
3. `git log --oneline -15` — orient on the last batch.
4. `Get-ScheduledTask "SSC Dashboard Server"` — confirm State: Running.
5. `Invoke-WebRequest http://127.0.0.1:5050/api/health` — should be 200.
6. If port 5050 is in use by an unexpected python.exe, tree-kill it
   (CLAUDE.md operational-discipline rule).
7. Wait for the user's first task — don't speculate.

### Non-negotiables when working in this codebase

- **Never run a suite or a migration against live.** Isolated copy via
  `SSC_DB_URL`, always. The gate runner refuses to start without it.
- **Snapshot before any live write** (`..\snapshots`, outside the served
  tree). A DB snapshot does NOT cover rendered artifacts — deleting a
  render dir is irreversible, so verify identity first or quarantine.
- **A running server has already imported the code.** On-disk edits do
  not reach it; restart per the #244 zombie-safe procedure and verify by
  API behaviour, never by the build stamp.
- New code goes through `db_layer` (never `sqlite3.connect` directly) and
  must pass on **both** backends.

---

*Last updated: 2026-07-30 #290 session — **M4 COMPLETE**. The cloud instance
is LIVE at https://ssc-dashboard-go4h.onrender.com (region virginia, docker/
chromium image, disk at /var/data): FULL acceptance battery 22/22 (chromium
PDF, DCR client render, photo-from-disk, containment probes, Eastern-today
on the UTC host), rehearsal data verified (104-table migrate, 2,293-file
media tree count+hash-matched). Production code is at dc905a5 on BOTH hosts;
en route #290 also fixed: anthropic/jinja2 never declared in requirements
(cloud boot crash), the ssc_paths Windows-path-on-POSIX resolver bug (every
pre-#287 stored row), and _fp_serve's missing resolver adoption. Workstation
remains the production of record until M5; cloud tracks main by auto-deploy.
Gate is 36 suites, green both backends. Flip rollback = revert 2c4fb4a +
#244 restart. Next: operator tasks (Google OAuth redirect URIs for both new
addresses, #289 2FA/device enrollment = the hard pre-M5 gate, subscriptions
true-up), M4.5 Cloudflare flip-week steps, then the M5 final-sync runbook in
CLOUD_M4_RUNBOOK_290.md §4.*
