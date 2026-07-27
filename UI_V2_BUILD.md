# UI v2 — build log

Rebuild of the four UI surfaces (admin, c_suite, active projects, client portal) behind a
per-user toggle. v2 ships *alongside* v1, never on top of it. Any page without a v2 twin
silently serves v1, so partial migration is always in a shippable state.

One branch, one tag, one commit, one deploy per phase. A phase does not start until the
previous phase's gate is green.

---

## ARCHITECTURE DECISION — `serve_ui`, not `render_ui`

The build brief specifies a Jinja shape: `render_template(f"v2/{template}", **ctx)` with a
`TemplateNotFound` fallback, and "replace `render_template` with `render_ui` at every route"
as the whole integration.

**This application makes ZERO `render_template` calls and has no `templates/` tree.** Every
UI surface is a standalone static HTML file served with `send_file`/`Response`; all data
arrives over `/api/*` JSON. The substitution as literally specified has nothing to attach to.

The same contract is therefore implemented against the real architecture, in `ui_version.py`:

| Brief (Jinja)                    | Here (static pages)                       |
|----------------------------------|-------------------------------------------|
| `render_template(f"v2/{name}")`  | `templates/v2/<name>` if it exists         |
| `render_template(name)`          | `<dashboard root>/<name>` — v1, ALWAYS     |
| `TemplateNotFound` → fall back   | `Path.exists()` is False → fall back       |
| `render_ui(template, **ctx)`     | `ui_version.resolve_page(v1_path)`         |

Every property the brief depends on is preserved:

* v1 files are never touched or read differently — same bytes, same headers.
* A page with no v2 twin silently serves v1.
* "Context dicts stay identical" is free — there are none. A v2 twin consumes exactly the
  same `/api/*` endpoints its v1 original does, so access filtering is untouched.
* Deleting `templates/v2/` restores the old UI completely, by construction.

Where a route already transformed its HTML (`/projects/<code>` runs `access.render_sections`
and `access.render_role_nav`), those transforms run on **whichever file was chosen**. Server-side
access enforcement is not a v1 behaviour a v2 page gets to opt out of.

---

## PHASE 0 — Safety rails · `#279` · tag `ui-v2-phase-0` · no user-visible change

### What shipped

| File | Purpose |
|---|---|
| `ui_version.py` | The whole toggle: resolution order, v2 page resolution, the switch API |
| `apply_ui_version_279.py` | `users.ui_version INTEGER NOT NULL DEFAULT 1` — additive, idempotent, dual-backend |
| `ui_settings.html` | `/settings/interface` — the Classic / New control |
| `static/v2/switch-back.js` | The persistent "You're on the new interface · Switch back" affordance |
| `templates/v2/`, `static/v2/` | Created empty (`.gitkeep` documents each) |
| `tests/smoke_ui_v2_phase0.py` | The gate — byte-identity, resolution order, kill switch, rollback layer 3 |

### Resolution order (highest priority first)

```
1. SSC_UI_FORCE_V1=1     env kill switch → everyone gets v1, ignore everything below
2. ?ui=1 | ?ui=2         per-request override, this request only, never persisted
3. users.ui_version      INTEGER NOT NULL DEFAULT 1
4. default               1
```

Read per request, not cached at import: flipping the kill switch is rollback layer 2, and it
must not depend on which module imported first.

**Default-safe by construction** — anything that is not exactly `2` resolves to `1`. An
unmigrated database, a NULL, a junk value, an anonymous request, or a DB error all degrade to
Classic rather than 500ing a page. The column carries no CHECK constraint deliberately: SQLite
cannot ALTER one, and the resolver already treats junk as 1.

`users.ui_version` is read through a **catalog probe** (`sqlite_master` / `information_schema`),
never by try/except-ing a SELECT — on Postgres a failed statement aborts the surrounding
transaction. Resolution is lazy and cached on `g`, so `/api/*` routes pay nothing.

### Routes now serving through the toggle (13)

| Route | Page | Module |
|---|---|---|
| `/` | `company-dashboard.html` | `server.py` |
| `/projects` | `projects.html` | `server.py` |
| `/projects/<code>` | `dashboard-static.html` | `server.py` |
| `/dashboard` | `dashboard-static.html` | `server.py` |
| `/dropplan` | `dropplan.html` | `server.py` |
| `/admin/labor-rates` | `admin_labor_rates.html` | `server.py` |
| `/login` | `login.html` | `auth.py` |
| `/set-password` | `set_password.html` | `auth.py` |
| `/admin/users` | `admin_users.html` | `auth_admin.py` |
| `/admin/projects` | `admin_projects.html` | `pm_scoping.py` |
| `/estimating` | `estimating.html` | `estimating.py` |
| `/portal` | `client_portal.html` | `client_portal.py` |
| `/welcome` | `welcome.html` | `client_portal.py` |
| `/settings/interface` | `ui_settings.html` | `ui_version.py` (new) |

**Deliberately NOT toggled: `/worker-app`.** The worker PWA is not one of the four surfaces,
and workers have no `users` row — so they cannot hold a preference. It stays on v1.

### Where the settings control lives, and why it is its own page

Non-negotiable #1 is that no v1 file is ever modified, and the phase-0 gate is byte-identity on
every existing page. Putting the control inside `admin_users.html` would violate both. It is
therefore a **new, additive page** at `/settings/interface` — which also means rollback layer 1
("flip `users.ui_version` to 1") is something the operator can actually do from a browser on
day one, rather than a SQL statement.

API: `GET/POST /api/ui/version` (self — every role, since choosing your own interface grants no
access), `POST /api/admin/ui/version/<user_id>` (admin-only, audited to `audit_log`).

---

## PHASE 0 GATE RESULTS

Run against isolated backends only; live `superstars.db` never targeted (verified afterwards:
no `ui_version` column, no `smk279-*` rows).

### Byte-identity — the gate itself

**72 (role, page) pairs compared** across 6 roles × 12 pages — `admin`, `c_suite`, `pm`,
`super`, `estimator`, `client`. Every pair fetched at `ui_version=1` and again at
`ui_version=2`; **all 72 identical in status and body bytes.**

* status distribution: `200×35`, `302×14`, `403×23`
* of those, **35 were substantive rendered pages** (200, >2 KB body)
* **0 pages excluded as non-deterministic** — every page was byte-stable against itself

The coverage counts and the substantive-200 floor are asserted, not just printed. A
byte-identity check that silently compared nothing — every login broken, or 72 identical
redirects to `/login` — would otherwise pass exactly as quietly as a real one.

### Full gate

| Backend | Result |
|---|---|
| **Postgres** (`ssc_test` @ 127.0.0.1:5433) | **27 / 27 green** |
| **SQLite** (isolated snapshot copy) | **25 / 27** — the 2 failures are PRE-EXISTING |

The two SQLite failures — `smoke_dcr214_lifecycle.py` (`cleanup_real_set_identical`, added=2
removed=2) and the `smoke_no_production_data_corruption.py` cascade — were **reproduced on tag
`pre-ui-v2-phase-0` with the phase-0 changes stashed and a pristine DB copy**, failing
identically. They are a DCR-fixture defect in the SQLite gate data (the lifecycle smoke
renumbers real DCR rows instead of restoring them), not a phase-0 regression. Both pass on
Postgres. Tracked separately.

### Rollback rehearsed — all four UI layers, against a real waitress process

Verified by server behaviour (does the response still contain the v2 twin's marker), never by a
build stamp — per the CLAUDE.md restart rule.

| # | How | Verified |
|---|---|---|
| 1 | Flip `users.ui_version` to 1 | v1 immediately, no restart; flipping back returns to v2 |
| 2 | `SSC_UI_FORCE_V1=1` + restart waitress | **v1 returned clean for everyone** with the twin still on disk and the user still on `ui_version=2`; page healthy (200, 7419 bytes); `forced_v1:true` surfaced to the UI; clearing it brings v2 back — the switch is not one-way |
| 3 | Delete one file in `templates/v2/` | that page falls back to v1, no restart; restoring it returns v2 |
| 4 | Delete `templates/v2/` contents | all of v2 gone |

Layers 5–6 (git revert, snapshot restore) exist for the schema addition only; it is an additive
column with a default and is safe to leave in place while the UI is reverted.

### v1 untouched — verified

`git diff --name-only pre-ui-v2-phase-0` contains **no `.html` file and no `static/` asset**.
Changes are Python route wiring in 6 modules (36 insertions, 13 deletions) plus 2 test files.

### Visual check

Phase 0 has no visual change by design — proven byte-identically above. The one new visible
surface, `/settings/interface`, was checked in a real browser at 1280×720 and 375×812:
no horizontal overflow, no clipped text, no card overlap, nothing past the right edge, and the
primary button resolves to the shared accent `rgb(67,100,220)` on white (no invisible-button
regression). The switch was exercised end-to-end — 1 → 2 → back to 1 — and `/projects?ui=1`
vs `?ui=2` returned identical bytes with no twin present.

The harness could not composite screenshots in this session (`Browser pane is not displayed`),
so the layout was verified programmatically — computed geometry, `scrollWidth` vs `clientWidth`
clipping, and bounding-box overlap — rather than by eye. **From phase 3 onward, when there is
real v2 layout to judge, screenshots must be taken and actually looked at; a geometry audit
does not replace that.**

### Snapshot

`snapshots/superstars-pre-ui-v2-phase0-20260727-164921.db` (2,260,992 bytes), taken before the
schema change, retained.

---

## Deploy note

`apply_ui_version_279.py` has **not** been run against live. It runs at deploy, after the
snapshot, in the deploy queue's numeric order.
