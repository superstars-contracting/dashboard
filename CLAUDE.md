# CLAUDE.md — Project Rules for Superstars Ops Platform

This file is read at the start of every Claude Code session. Keep it short.
Pin only rules that have already cost us hours.

---

## Convention: reference rules by what they say, not by number

Never reference hard rules by number in code comments. Rules can be inserted,
moved, or removed — numbered cross-references become wrong silently. Reference
rules by what they say (e.g., `per CLAUDE.md loopback policy`,
`per CLAUDE.md PII rule`) so the cross-reference survives reordering.

---

## 1. Design rule: HTML-first, PDF-last

**Always design in HTML. Iterate in the browser. Convert to PDF only at the moment of delivery.**

- The browser's print preview (Ctrl+P → Save as PDF) is a real PDF renderer.
  Use it for ad-hoc previews and one-offs.
- `render_pdf.py` (WeasyPrint) is the production export tool. It is *not* the
  design surface. Invoke it only when generating final deliverables or batch output.
- The `/preview/*` routes (see `preview_routes.py`) serve every template
  directly in the browser. Use them.
- **Why this rule exists:** the CoF card iteration cost ~15 cycles fighting
  WeasyPrint-specific quirks (flex/grid failures, SVG text rendering, inline-block
  hacks). Every one of those would have been a 30-second browser refresh if we'd
  iterated in HTML instead of regenerating PDF each time.

## 2. Data rule: real PII never enters Claude chats

Worker phone numbers, addresses, SSNs, ID photos, license numbers — none of
these are pasted into chats. When values must be discussed, redact: `W1`,
`XXX-XXX-1234`, `[name redacted]`.

All real data lives in `superstars.db` on the encrypted workstation drive.
API keys live in `.env`, gitignored, never committed.

## 3. Schema rule: IDs sort numerically, not lexicographically

Employee IDs are `E-XXXXX`. When computing the next ID or sorting workers:

```sql
SELECT MAX(CAST(SUBSTR(employee_id, 3) AS INTEGER)) FROM workers
```

NOT:

```sql
SELECT MAX(employee_id) FROM workers  -- WRONG: "E-012" > "E-00013" textually
```

This rule caused the E-00013 collision bug. Apply the same pattern to any
zero-padded ID format (employee, card, RFI, etc.).

## 4. JS rule: avoid possessive apostrophes in i18n string literals

`'modal-step3': "the worker\\'s folder is created"` will crash JS parsing in
some contexts and silently break an entire dashboard. Rephrase to drop the
possessive: `"the worker folder is created"`. This cost us a half-day of
"why is nothing loading?" debugging.

## 5. Migration rule: schema scripts are idempotent

Use the `split_statements` pattern (see `apply_riggers_schema.py`) so re-running
a migration is safe. Duplicate column errors are caught and counted as skipped.
Never write a migration that fails on second run.

## 6. Secrets rule: vault all authenticating API keys, never plaintext on disk

All API keys that authenticate as the company, are billed against the company's
accounts, or grant access to non-public data live in 1Password Business under
the "Dashboard Secrets" vault. Never store such keys in plaintext anywhere on
disk — not in `.env`, not in source code, not in config, not in scripts. Code
accesses them via 1Password CLI references (`op://Vault/Item/field`) injected
at runtime by `op run`, or via explicit `op read` within an authenticated
1Password session. No agent, script, or process gets unfiltered access — every
fetch goes through the Windows Hello / master password / YubiKey-gated
1Password session and is audit-logged. This rule does NOT apply to: (a) no-key
public APIs like Open-Meteo, (b) intentionally-public client-side keys like
Stripe publishable keys or domain-restricted Maps keys. For operational
hygiene, every external service the dashboard depends on still gets a
1Password vault item even with no credential — the vault doubles as the
service inventory.

## Dependency security tooling (safety net, not a substitute for judgment)

Two automated dependency-security layers are active on this repo:
- **GitHub Dependabot** — alerts on known CVEs in dependencies and auto-opens patch PRs.
- **Socket Security** (GitHub app, scoped to this repo only) — supply-chain attack detection: malware, typosquatting, hidden/obfuscated code, suspicious privileged-API usage (filesystem/network/child_process/eval), reviewed inline on pull requests.

These are a SAFETY NET. Their presence must NOT reduce the system's own vigilance or confidence in preventing malware, spyware, data exfiltration, or anything that could harm the system or leak PII. When adding or updating ANY dependency, Claude/agents still:
- Vet the package first — legitimate, actively maintained, exact correct name. No blind `pip install` / `npm install` of unfamiliar packages.
- Never introduce malware, spyware, obfuscated code, or anything that exfiltrates data, credentials, or worker PII.
- Uphold all existing security rules — secrets vaulted in 1Password (never plaintext on disk), PII never in chats or logs, parameterized SQL, 127.0.0.1 loopback bind only.

The tools catch what slips past discipline; they do not license carelessness. Socket and Dependabot run quietly in the background so the operator can focus on organizing the business and the work — not on policing threats. First-principles security judgment remains the system's responsibility; the tooling is backup, not the primary defense.

---

## File layout

| Path | Purpose |
|------|---------|
| `server.py` | Flask server, all API routes, port 5050 |
| `preview_routes.py` | Browser preview blueprint (registered in server.py) |
| `superstars.db` | SQLite DB. NEVER commit. NEVER paste contents in chats. |
| `.env` | API keys (SendGrid, etc). NEVER commit. |
| `.gitignore` | Excludes secrets, DB, uploads, caches. |
| `schema*.sql` | Schema definitions. Commit these. |
| `apply_*_schema.py` | Idempotent migration runners. |
| `cof_*.html`, `cof_*.py` | Certificate of Fitness card system. |
| `render_*_html.py` | Per-document-type HTML renderers. |
| `generate_*.py` | Per-document-type generators (read DB, render, write). |
| `render_pdf.py` | WeasyPrint CLI — production PDF export only. |
| `worker-app.html` | Mobile PWA for worker check-in. PIN = last 4 of phone. |
| `company-dashboard.html` | Cross-project console with EN/ES toggle. |
| `dashboard-static.html` | Per-project dashboard. |

## Architecture

- Flask binds to `127.0.0.1:5050` (localhost only — never expose to LAN).
- SQLite with WAL mode for concurrent reads + writes.
- Vanilla HTML/JS frontend, no build step.
- WeasyPrint is the only PDF tool. SQLite is the only data store.
- Bilingual (EN/ES) via `data-i18n` attributes + `I18N` dict in JS,
  persisted in `localStorage.dashboard_lang`.

## Communication style

Direct. No long preambles. Brief acknowledge → execute → report.
Ask one focused clarifying question only when genuinely ambiguous;
otherwise make the call and explain in one line.
