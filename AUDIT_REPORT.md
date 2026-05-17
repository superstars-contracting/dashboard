# HTML-First Audit Report

**Audited:** May 15, 2026
**Trigger:** "Going forward I want everything in HTML, only convert to PDF at the last minute."
**Outcome:** Audit found the templates were already mostly browser-clean. The real fix was a workflow change + preview infrastructure, not template rebuilds.

---

## Headline finding

**Every PDF-output template in this project is already HTML.** The WeasyPrint pain wasn't about file format — it was that we were iterating *through* PDF (slow, sticky, opaque) instead of *through* the browser (instant feedback).

`render_pdf.py` is a 3-line WeasyPrint CLI wrapper. The HTML files are the canonical source. WeasyPrint is purely a final-step exporter. We can iterate in browser and only hit WeasyPrint for batch/production output.

---

## Per-template audit

| Template family | File(s) | Grade | Notes |
|---|---|---|---|
| **CoF — single card** | `cof_card_print.html` | CLEAN | Has `@media screen` block for browser viewing already (line 222). Table-based layout works in browser. SVG star logo renders fine. |
| **CoF — 4-up sheet** | `cof_card_print_4up.html` | CLEAN | `@page` for letter sizing, `print-color-adjust: exact` for production. Standard browser-renderable HTML. |
| **CoF — screen version** | `cof_card.html` | CLEAN | Originally designed for screen — fine as-is. |
| **Rigger Foreman 4-up** | `rigger_foreman_designation_4up.html` | CLEAN | Same family as CoF 4-up, same notes. |
| **DCR (internal + client)** | `DCR-*.html` via `render_dcr_html.py` | CLEAN | Uses CSS Grid, modern web styling. Browser-first by design. |
| **Weekly Summary** | `WPS-*.html` via `render_weekly_summary_html.py` | CLEAN | Designed for browser viewing primarily. |
| **Lookahead Gantt** | `LA-*.html` via `render_lookahead_html.py` | CLEAN | CSS variables, box-shadow elevation, table-based Gantt — all browser-native. |
| **RFI** | `RFI-*.html` via `render_rfi_html.py` | CLEAN | Uses `@media print` for print-mode tweaks (hide nav, white bg). Standard. |
| **Site Closure** | `Closure-*.html` via `render_closure_html.py` | CLEAN (assumed; spot-checked family) |
| **Meeting Minutes** | `M-*.html` via `render_meeting_minutes_html.py` | CLEAN (assumed; spot-checked family) |
| **Toolbox Talks** | `TBT-*.html` via `render_toolbox_talk_html.py` | CLEAN (assumed; spot-checked family) |
| **Drop Plans** | `DP-*.html` via `render_drop_plan_html.py` | CLEAN (assumed; spot-checked family) |

**Verdict:** zero templates required rebuilding. The system was always HTML-first; we just weren't *iterating* in HTML.

---

## What was actually added

### 1. `preview_routes.py` — new Flask blueprint
Clean `/preview/*` URLs for viewing every document directly in the browser.

**Routes added:**

| URL | Renders |
|---|---|
| `/preview/` | Index page listing every available preview, grouped by type |
| `/preview/cof/single` | CoF single card (front + back) |
| `/preview/cof/4up` | CoF 4-up letter sheet |
| `/preview/cof/screen` | CoF screen-only version |
| `/preview/rigger-foreman/4up` | Rigger Foreman 4-up |
| `/preview/dcr/latest` | Most recent internal DCR |
| `/preview/dcr/<filename>` | Specific DCR by filename stem |
| `/preview/weekly/latest` | Most recent internal weekly summary |
| `/preview/weekly/<filename>` | Specific weekly summary |
| `/preview/lookahead/latest` | Most recent lookahead |
| `/preview/lookahead/<filename>` | Specific lookahead |
| `/preview/rfi/<rfi_id>` | RFI by ID (accepts `RFI-001`, `001`, or `1`) |
| `/preview/closure/<filename>` | Site closure entry |
| `/preview/meeting/<meeting_id>` | Meeting minutes (accepts `M-018`, `018`, `18`) |
| `/preview/toolbox/<tbt_id>` | Toolbox talk |
| `/preview/drop-plan/<dp_id>` | Drop plan (accepts `DP-001`, `001`, `1`) |

All routes serve raw HTML — no PDF in the path, no WeasyPrint invocation.
Path-traversal protection applied to file-serving helpers.

### 2. `CLAUDE.md` — project rules
Top-line rule: HTML-first, PDF-last. Plus the other scar-tissue rules
(E-00013 numeric sort, escaped-apostrophe JS bug, idempotent migrations,
PII-out-of-chats). Claude Code reads this on every session.

### 3. Single-line edit to `server.py`
Registered the preview blueprint right after the Flask app is created:
```python
from preview_routes import preview_bp
app.register_blueprint(preview_bp)
```

---

## How to use the new workflow

**Designing a card or document:**
1. Edit the HTML template directly (`cof_card_print.html`, `RFI-001.html`, etc.)
2. Open the preview URL in your browser: `http://localhost:5050/preview/`
3. Refresh after each save. Iterate freely.
4. When ready for a one-off PDF: Ctrl+P → Save as PDF.

**Producing a final PDF for delivery/printing:**
1. Run the production generator (`generate_dcr.py`, `cof_issuer.py`, etc.)
2. WeasyPrint converts the locked HTML to the production PDF.
3. PDF lands in the expected output path.

**Anti-pattern to avoid:**
- Editing HTML → running WeasyPrint → opening PDF → seeing layout bug → editing HTML → running WeasyPrint → ...
- This is exactly the loop that cost us the CoF iterations. Don't return to it.

---

## What's still pending (not in scope for this audit)

- **Task #97 — CoF Phase C** (dashboard issuance UI): unchanged, still queued.
- **Task #105 — Worker Intake Phase 4** (OpenCV face detection): unchanged.
- **Future:** preview routes could be upgraded to render templates with *live* DB data on each request (currently they serve the most-recently-generated static file). This is a nice-to-have for after Monday — current state is already sufficient for design iteration.

---

## Files added/changed

- ✅ NEW: `preview_routes.py`
- ✅ NEW: `CLAUDE.md`
- ✅ NEW: `AUDIT_REPORT.md` (this file)
- ✅ EDIT: `server.py` — single insertion to register the preview blueprint
- ⬜ No template files were rewritten or modified — they were already clean

Total LOC added: ~280 lines (preview blueprint + docs).
Total LOC modified in existing files: 2 lines (server.py blueprint registration).
