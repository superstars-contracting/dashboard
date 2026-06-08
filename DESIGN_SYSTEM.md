# Superstars Dashboard — Design System & Conventions (v1.0)

**Why this exists:** we kept re-fixing the same UI bugs on each new page (the invisible primary button; raw date fields instead of the picker). The cause: every surface defined its own colors and re-built its own button/date field, so a fix on one page didn't carry. This doc is the single source of truth so **a design decision made once applies site-wide.** Every build prompt references it; a guard smoke enforces the load-bearing parts.

---

## 1. Design tokens are GLOBAL (`:root`), never per-module

The core tokens live ONCE at `:root` in the shared stylesheet (`static/css/widgets.css`), loaded on every page:

- Accent (Lumen azure): `--accent:#4364dc` · `--accent-ink:#3a5fd0` · `--accent-soft:#ebf0fe` · `--accent-edge:rgba(67,100,220,.30)`
- Neutrals: `--ink:#222633` · `--muted:#8c92a0` · `--line:#eceef3` · `--canvas:#fafbfd`
- Status (Lumen+Oat — **status meaning only**): complete `#15a07e` · active `#4364dc` · behind `#e9685a` · not-started/oat `#cabfad` (each with its `-soft` tint)

**Rule:** never define these tokens *only* on a per-module wrapper (`.pd-wrap`, `.fp-wrap`, `.dp-wrap`, etc.). **Modals/overlays render at the page root, OUTSIDE those wrappers** — if a token is only on the wrapper, `var(--accent)` resolves to nothing inside the modal → the transparent/invisible-button bug (#230, #235→#236). Module wrappers may add *extra* local vars, but anything a modal uses must come from `:root`.

## 2. One shared primary button — it must always be blue + labeled

There is ONE primary CTA style: `.btn-primary` (background `var(--accent)`, white text, label + optional icon). Every "Save / Upload / Submit / Confirm" button uses it. **A primary button must NEVER render with a transparent or white background, and must always have a visible label.** (Guarded — see §6.) Secondary = `.btn-ghost` (white, line border, ink text).

## 3. Modals use the shared modal component + global tokens

Use the shared modal/overlay shell. Because it renders at the page root, it relies on the `:root` tokens (§1). Footer = `.btn-ghost` Cancel + `.btn-primary` action.

## 4. All dates go through SSCDatePicker — auto-wired

Every date field uses **SSCDatePicker** (the calendar popup). A global initializer auto-wires every date field (standard class `.ssc-date` and/or any `<input type="date">`) on page load **and on modal open** (for dynamically-rendered modals). **Never ship a raw `MM/DD/YYYY` text input.** Display = MM/DD/YYYY; store/compute = LOCAL date (never UTC).

## 5. Color = status only

`green / amber(behind=coral) / red` carry STATUS meaning only. Categories/elevations/decoration use the non-semantic palette (slate-blue, teal, violet, indigo, oat). (Established across Drop Plan, Docs, Field Photos.)

## 6. Enforcement — the design-conventions guard smoke

A lightweight smoke (`smoke_design_conventions.py`) fails the build if:
- a primary/submit button on a known surface computes to a transparent / near-white background (the invisible-button regression), or
- a raw, unwired `<input type="date">` (or `MM/DD/YYYY` text field) exists on a modal/known surface (the un-wired-date regression).

Run it alongside CRUD + meta-smoke on every UI build.

## 7. Standing rule for every build prompt (and for Cowork when writing them)

Bake these in by default, every time:
- Use the GLOBAL `:root` tokens + `.btn-primary` / shared modal — do not re-define colors on a wrapper a modal escapes.
- All dates via SSCDatePicker (auto-wired).
- Verify in Preview: the primary button's computed background == the accent and its label is present; date fields are `data-ssc-dp`.
- Run the design-conventions guard smoke.

## Recurring-bug log (fixed at root)
- **Invisible primary button** (module-scoped tokens; modal renders outside) — #230 (Docs), recurred #235 (Field Photos) → root fix #236 (tokens globalized + guard).
- **Raw date field instead of SSCDatePicker** — recurred on several modals → root fix #236 (global auto-wire + guard).
