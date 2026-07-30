# Cloud M4 runbook (#290) — bring-up on Render, rehearsal, and the M5 final-sync procedure

What #290 shipped: `render.yaml` + `Dockerfile` (+`.dockerignore`) — the committed
service blueprint; `ssc_tz.py` SSC_TZ enforcement at boot (+ PG session TimeZone in
`db_layer`) with gate suite `tests/smoke_tz_290.py`; the Linux sweep
(`generate_credentials_batch` now goes through `db_layer`; dead Edge path list
removed); `tests/acceptance_battery_290.py` (remote probes) and
`tests/verify_media_remote_290.py` (media tree verification over SSH).

Region assumption baked into `render.yaml`: **virginia (US East)** — verify it
matches `ssc-dashboard-db` before applying (edit the yaml first if not).

---

## 1. OPERATOR MOMENT 1 — create the service from the blueprint (~15 min + ~10 min first build)

1. **Pre-check (1 min).** Render dashboard → `ssc-dashboard-db` → confirm the
   region reads **Virginia (US East)**. If it doesn't, STOP and say so — the
   `region:` line in render.yaml must be edited to match before applying
   (internal DB URLs resolve only within one region).
2. **New → Blueprint.** Connect GitHub if prompted and authorize Render for the
   `superstars-contracting/dashboard` repo (read access is enough; Render uses
   it for auto-deploy on push to main).
3. Render detects `render.yaml` → shows the plan: one web service
   `ssc-dashboard` (starter, docker, 5 GB disk at /var/data). Blueprint name:
   anything ("ssc-dashboard").
4. **The sync:false prompts.** The creation flow asks for a value per secret —
   every value comes from 1Password ("Dashboard Secrets" vault) → paste into
   Render. Never into chat, never into a file:
   | Env var | Where the value lives |
   |---|---|
   | `SSC_DB_URL` | `ssc-dashboard-db` page → **Internal Database URL** (also vaulted) |
   | `ANTHROPIC_API_KEY` | vault item (optional — may be set later; app 503s AI cleanly without it) |
   | `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` | vault (Google SSO #261 item) |
   | `SENDGRID_API_KEY` | vault |
   | `GOOGLE_OAUTH_REDIRECT_URI` | `https://ssc-dashboard.onrender.com/auth/google/callback` (fix after create if the URL got a suffix — see step 6) |
   | `APP_BASE_URL` | `https://ssc-dashboard.onrender.com` (same note) |
5. **Apply.** First build is a Docker build with chromium — expect ~5–10 min.
   Watch Events until "Deploy live"; health check is `/api/health`.
6. **Confirm the real URL.** The service page shows the actual
   `*.onrender.com` hostname (a suffix appears if the name was taken). If it
   differs from what you pasted in step 4, correct `APP_BASE_URL` and
   `GOOGLE_OAUTH_REDIRECT_URI` in the Environment tab (each save redeploys).
7. **SSH key (for the media rehearsal).** Account Settings → SSH Public Keys →
   add the workstation key (`type $env:USERPROFILE\.ssh\id_ed25519.pub`;
   if none exists: `ssh-keygen -t ed25519` first). Then copy the service's
   SSH address from ssc-dashboard → Connect → SSH (looks like
   `srv-xxxx@ssh.virginia.render.com`).

Then the executor runs the PRE battery from the workstation:

```powershell
venv\Scripts\python.exe tests\acceptance_battery_290.py https://<service>.onrender.com
```

Expected: health/login/auth-gate/static/worker-app/timezone all PASS
(timezone-eastern-today is the #290 SSC_TZ proof on the UTC host).

---

## 2. OPERATOR MOMENT 2 — rehearsal credentials (~5 min)

In the PowerShell terminal that will run the rehearsal (values from 1Password,
set in the terminal only — never in a committed file):

```powershell
$env:SSC_DB_URL = "<ssc-dashboard-db EXTERNAL Database URL>"
```

Also have ready: the service SSH address (step 1.7).

---

## 3. The rehearsal (full dress — executor drives, ~45 min)

1. **Fresh live snapshot** (server can keep running; snapshot is the
   consistent copy):
   ```powershell
   venv\Scripts\python.exe -c "import sqlite3; s=sqlite3.connect('file:superstars.db?mode=ro',uri=True); d=sqlite3.connect('../snapshots/ssc_m4_rehearsal.db'); s.backup(d)"
   ```
2. **DB migrate** (workstation → Render PG over the EXTERNAL URL, ~2–5 min):
   ```powershell
   venv\Scripts\python.exe migrate_sqlite_to_pg_259.py ..\snapshots\ssc_m4_rehearsal.db $env:SSC_DB_URL --reset
   ```
   Acceptance: **104 tables, 0 count deltas** (the #287-pattern verify table
   the script prints).
3. **Stage the media tree** (idempotent; sha256-verified per category):
   ```powershell
   venv\Scripts\python.exe migrate_data_root_287.py C:\Users\SSC-Admin\Superstars\cloud_staging_root --execute
   ```
4. **Ship media + renders to the service disk** (~300 MB; 10–20 min upstream).
   The db and logs categories deliberately stay home (cloud runs Postgres; a
   SQLite copy on the disk is liability, not backup):
   ```powershell
   cd C:\Users\SSC-Admin\Superstars\cloud_staging_root
   tar -cf ssc_media.tar --exclude superstars.db --exclude server.log --exclude data_room/server_logs data_room worker_records employee_photos issuer_signatures cof_exports meetings drop_plans site_closures toolbox_talks meeting_workflow_run rfi_workflow_run
   scp ssc_media.tar <SSH_ADDR>:/var/data/
   ssh <SSH_ADDR> "cd /var/data && tar -xf ssc_media.tar && rm ssc_media.tar"
   ```
   (A tree that's missing on the workstation — e.g. rfi_workflow_run — just
   tars empty; that's fine.)
5. **Verify media** (counts + bytes per tree + 40 sampled sha256, PII-safe):
   ```powershell
   cd C:\Users\SSC-Admin\Superstars\dashboard
   venv\Scripts\python.exe tests\verify_media_remote_290.py C:\Users\SSC-Admin\Superstars\cloud_staging_root <SSH_ADDR>
   ```
6. **FULL battery** (adds synthetic login, chromium PDF w/ page check, portal
   containment probes, photo-serves, DCR client render):
   ```powershell
   venv\Scripts\python.exe tests\acceptance_battery_290.py https://<service>.onrender.com --phase full
   ```
   Synthetic `is_system` fixtures only; cleaned up in a finally block. The
   script refuses to run its full phase against anything but a Postgres URL.

---

## 4. M5 final-sync runbook (the cutover — run when the operator says go)

Pre-flight gates (all BEFORE starting the sequence):
- [ ] #289 operator to-do complete: every staff account has a second factor,
      8 field phones provisioned, `worker_device_enforcement` flipped to 1.
      (Hard gate — do not expose the public DNS without it.)
- [ ] Google console: both redirect URIs registered (§6 below).
- [ ] M4.5 Cloudflare staging done (SPF + Google DKIM records added; DNSSEC
      confirmed off at GoDaddy; nameserver cutover plan per the blueprint).
- [ ] Rehearsal (§3) green within the last week.

The sequence:
| # | Step | Est. |
|---|---|---|
| 1 | Freeze workstation writes: `Stop-ScheduledTask "SSC Dashboard Server"` (tailnet users get told beforehand) | 2 min |
| 2 | Final snapshot + `migrate_sqlite_to_pg_259.py <snap> $env:SSC_DB_URL --reset` → expect 104 tables / 0 deltas | 5 min |
| 3 | Media delta: re-run `migrate_data_root_287.py <staging> --execute` (idempotent — copies only new files), re-tar, scp, extract-over (tar -xf overwrites), re-verify | 25 min |
| 4 | FULL battery against the onrender URL — all PASS | 5 min |
| 5 | Render service → Settings → Custom Domains → add `app.superstarscontracting.com` | 5 min |
| 6 | Cloudflare DNS: CNAME `app` → `<service>.onrender.com` (proxied). This is THE flip. | 5 min + propagation |
| 7 | Env flips in Render (each save redeploys): `APP_BASE_URL` + `GOOGLE_OAUTH_REDIRECT_URI` → the app.superstarscontracting.com forms; `SSC_TRUSTED_PROXY` → `2` (Cloudflare hop + Render hop) | 5 min |
| 8 | FULL battery against `https://app.superstarscontracting.com` + operator spot-check: staff SSO login, issue a DCR, PDF export, client portal page, worker-app PIN | 30 min |
| 9 | Burn-in: 2 days real use on the cloud. Workstation task stays STOPPED but intact (the parachute — restart it + Tailscale serve to roll back; cloud-era data entered after the final sync would need re-entry, which is the accepted cost) | 2 days |
| 10 | Post-burn-in cleanup: Render cron for the DB snapshot habit (Render PG has daily backups + Pro PITR; decide if the belt needs the suspender), subscriptions true-up (§5), retire the funnel exposure when ready | later |

Rollback at ANY step ≤ 8: point DNS back (or simply resume the workstation
task — the tailnet path never went away). After step 9 starts, rollback costs
re-entering the burn-in window's data.

---

## 5. Costs to record in the subscriptions ledger (true-up after moment 1)

| Item | Expected |
|---|---|
| Render web service (starter) | $7/mo |
| Render persistent disk 5 GB | ~$1.25/mo ($0.25/GB) |
| Render Postgres (tier the operator created) | read actual from the DB page |
| Render workspace Pro (operator decision 2026-07, PITR) | per-seat — read actual from billing |
| Cloudflare Free (M4.5) | $0 |

Add/update rows in `subscriptions_ledger.csv` + the subscriptions surface once
the first invoice confirms actuals.

---

## 6. Operator Google-console task (SSO on the new addresses)

Google Cloud Console → APIs & Services → Credentials → the dashboard's OAuth
2.0 Client → **Authorized redirect URIs** → add BOTH:

- `https://<service>.onrender.com/auth/google/callback`
- `https://app.superstarscontracting.com/auth/google/callback`

(Keep the existing tailnet redirect URI until the workstation parachute is
retired.) Without these, "Sign in with Google" on the new addresses fails at
Google's redirect_uri_mismatch screen. The TOTP/password path is unaffected.

---

## 7. Known cloud-vs-workstation deltas (accepted for M4)

- PDF fonts: the cloud renders with the real Inter (installed in the image);
  the workstation's Edge used the system fallback chain. Page counts verified
  by the battery; glyph-level look may differ hair-thin. Design intent is
  Inter, so the cloud is the MORE correct render.
- `render_pdf.py` (legacy WeasyPrint CLI) is non-functional in the image
  (pango not installed) — nothing imports it on the serving path; the
  production pipeline is pdf_export + chromium (#288).
- Starter instance = 512 MB RAM. If chromium PDF renders OOM under load, bump
  the plan to `standard` in render.yaml (one line) — watch the battery's
  pdf-export probe timing.
- CRLF shebangs exist on 22 tracked .py files — harmless (nothing on the
  cloud path executes them via shebang; everything is `python x.py` or a
  module import). Normalize opportunistically, not urgently.

*Written by #290. Update alongside any change to render.yaml, the battery, or
the M5 plan.*
