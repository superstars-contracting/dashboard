# Secrets Checklist

**Purpose:** Every API key, token, and secret the dashboard needs to function on the workstation. None of these are in git. All live in `.env` on the workstation (BitLocker-encrypted drive).

**Rule:** admin@'s 1Password vault is the source of truth for every value listed here. The `.env` file on the workstation is a working copy. If you ever lose `.env`, regenerate from 1Password.

**admin@ is the only role with access to these. amit@ never sees any of these.**

---

## How to use this file

1. Create a file in the dashboard folder named exactly `.env` (no extension)
2. For each secret below: open the corresponding 1Password entry → reveal the value → copy → paste into `.env` in the format shown
3. Save `.env`
4. Verify `.env` does NOT show in `git status` (gitignored)
5. NEVER commit `.env`. NEVER paste contents into a chat. NEVER email it.

---

## Required secrets (the dashboard won't fully work without these)

### SENDGRID_API_KEY

- **Used for:** Sending RFI emails, meeting minutes distribution
- **Where it lives:** SendGrid account dashboard → Settings → API Keys
- **1Password entry:** Should be a Login titled "SendGrid (admin@superstarscontracting.com)"
- **Status:** ⏳ Pending — SendGrid needs to be re-signed up under admin@ (not yet done)
- **.env format:**
  ```
  SENDGRID_API_KEY=SG.actual-key-here
  ```

### Flask SECRET_KEY (for session cookies)

- **Used for:** Internal Flask sessions
- **Generate fresh on workstation:** open Python and run `import secrets; print(secrets.token_hex(32))`
- **1Password entry:** Create a new Secure Note: "Flask SECRET_KEY (workstation)"
- **.env format:**
  ```
  FLASK_SECRET_KEY=64-char-hex-string
  ```

---

## Optional secrets (features that depend on them)

### NYC_OPENDATA_APP_TOKEN

- **Used for:** Higher rate limits on NYC Compliance pulls
- **Not required** — unauthenticated requests work at lower rate limits, currently sufficient
- **Where it lives:** If/when you sign up, get from `data.cityofnewyork.us` (NYC OpenData portal)
- **1Password entry:** Login titled "NYC OpenData (admin@)" if signed up
- **.env format:**
  ```
  NYC_OPENDATA_APP_TOKEN=your-token-here
  ```

### ANTHROPIC_API_KEY

- **Used for:** Future AI integrations (drafting, summarization, intelligence layer)
- **Status:** ⏳ Pending — Anthropic API not yet added to roadmap as live integration
- **Where it lives:** console.anthropic.com → API Keys (under admin@'s Anthropic account when signed up)
- **1Password entry:** Login titled "Anthropic API (admin@)"
- **.env format:**
  ```
  ANTHROPIC_API_KEY=sk-ant-...
  ```

### OPEN_METEO_API_KEY

- **Not required** — Open-Meteo is unauthenticated, no key needed
- Currently used for weather widget. No setup needed.

---

## Future secrets (year 2+ when you scale)

These don't exist yet and won't until specific features are added:

- `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` — when SMS notifications are added (Tier 3)
- `GITHUB_TOKEN` — if dashboard needs to interact with GitHub API
- `BACKBLAZE_KEY_ID` / `BACKBLAZE_APP_KEY` — when backup automation is added
- `CLOUDFLARE_API_TOKEN` — when Cloudflare Tunnel is automated
- `OPENAI_API_KEY` — if you ever add OpenAI alongside Anthropic

Add to this checklist whenever a new secret enters the architecture.

---

## Example .env file

When fully populated, your `.env` looks like this:

```bash
# Superstars Contracting dashboard — workstation secrets
# DO NOT COMMIT. Lives locally only. Reset all values from 1Password if lost.

# Required
SENDGRID_API_KEY=SG.your-actual-key-here
FLASK_SECRET_KEY=64-char-hex-generated-from-secrets-module

# Optional (uncomment when configured)
# NYC_OPENDATA_APP_TOKEN=your-token-here
# ANTHROPIC_API_KEY=sk-ant-your-key-here
```

---

## Secret rotation schedule

| Secret | Rotate every | Why |
|---|---|---|
| `SENDGRID_API_KEY` | 12 months | Standard hygiene; longer if no breach indicators |
| `FLASK_SECRET_KEY` | Only if compromised | Rotating logs out all active sessions, do only if needed |
| `ANTHROPIC_API_KEY` | 12 months | Standard hygiene |
| `NYC_OPENDATA_APP_TOKEN` | Not required | NYC OpenData tokens are stable |

After rotation: update the `.env` file on the workstation + update the corresponding 1Password entry. Confirm dashboard still works.

---

## Audit log

Track when each secret was created / rotated / used:

| Date | Secret | Action | By |
|---|---|---|---|
| (fill in as you go) | | | |
| 2026-05-XX | SENDGRID_API_KEY | Initial setup under admin@ | admin@ |
| 2026-05-XX | FLASK_SECRET_KEY | Generated fresh on workstation | admin@ |
