# Secrets & runtime-env inventory (#289 → the M4 Render environment group)

Every environment variable the app reads at runtime. The runtime reads **environment
only** — no module opens `.env` (verified by grep + the #289 guard). On the
workstation, `run_server.ps1` injects these from the gitignored local `.env`; at M4
they become the Render **environment group**, values sourced from the 1Password
"Dashboard Secrets" vault. Names only below — never values.

## Authenticating secrets (vault-required, per CLAUDE.md secrets rule)
| Var | Purpose | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Cert/expense/doc AI extraction | Optional; absent → clean 503 |
| `GOOGLE_OAUTH_CLIENT_ID` | Staff SSO (#261) | Public-ish (client id) but grouped w/ its secret |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Staff SSO | **Secret** |
| `SENDGRID_API_KEY` | Outbound email (notifications) | **Secret** |

## Configuration (non-secret, but env-injected — belong in the group)
| Var | Purpose |
|---|---|
| `SSC_DB_URL` | DB backend selector (SQLite default / Postgres) — **M4 sets the managed PG URL** |
| `SSC_DATA_ROOT` | #287 data root — **M4 sets the Render persistent-disk path** |
| `SSC_PDF_ENGINE` | #288 PDF engine — **M4 sets `chromium`** |
| `SSC_CHROMIUM_PATH` | #288 chromium binary — set if not on PATH |
| `SSC_TRUSTED_PROXY` | #289 — trust `X-Forwarded-For` (hops count) — **M4 sets for Render/Cloudflare** |
| `GOOGLE_OAUTH_ALLOWED_DOMAIN` | SSO domain restriction (@superstarscontracting.com) |
| `GOOGLE_OAUTH_REDIRECT_URI` | SSO callback — **M4 sets the app.superstarscontracting.com URL** |
| `APP_BASE_URL` | Absolute-URL base for links/redirects — **M4 sets the public origin** |
| `PORT` | Bind port (waitress) |

## Test-only seams (never set in production; documented so they're not mistaken for prod)
`GOOGLE_OAUTH_FAKE_VERIFY`, `DOC_SCAN_FAKE`, `DOC_SCAN_MODEL`, `EXPENSE_SCAN_FAKE`,
`EXPENSE_SCAN_MODEL` — deterministic-AI / mock-verify switches used by the gate.

## Secrets that live in the DB, not env (comp-data class, BitLocker at rest; SQLCipher roadmap)
- `users.password_hash` (bcrypt), `users.totp_secret` (#289 TOTP shared secret),
  `users.totp_recovery` (bcrypt-hashed), `worker_device.token_hash` /
  `provision_code_hash` (bcrypt). None ever logged or emitted post-enrollment.

*Generated #289 (Cloud M3). Update as M4 wiring lands.*
