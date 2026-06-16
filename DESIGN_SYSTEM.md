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

## 8. Behavioral protocol — verify the LIVED flow, guard the recurring classes

Design conventions (§1–§7) stop *visual* regressions. A second family keeps
recurring: **behavioral** bugs where the UI looks right but does the wrong
thing. Fixing those at the root means two standing rules:

**Verify the lived flow, not the API/computed style alone.** Reproduce the
operator's actual sequence with real clicks in Preview — *pick → submit →
reload → reopen → open the downstream view* — and confirm the end state. A
green API call or a correct computed style does not prove the feature works
(the #253 labor-rate submit "toasted Submitted" while creating nothing; the
#254 approval looked fine while the tracker still said "Rate not set").

**The recurring behavioral classes (enforced by `smoke_behavior_conventions.py`,
run in the gate):**
- **date-chosen-persists** — a user-chosen date is read from the picker
  (`SSCDatePicker.getISO`) on submit and stored as chosen, never silently `today()`.
- **submit-creates-record** — a primary "Submit / Approve" fires on the WHOLE
  change (e.g. rate *or* effective-date), and actually creates its row.
- **cancel-resets-form** — a modal's Cancel/close resets the form (incl. the
  SSCDatePicker `dataset.iso`, not just `.value`) so reopening is a clean slate.
- **cross-view propagation / single source of truth** — a change approved in
  one place is reflected EVERYWHERE the value is read (e.g. an approved labor
  rate bridged into the canonical `worker_rates` the tracker resolves). Guard it
  with a real write-flow assertion that fails on the broken path.

When you add a surface that submits a value, persists a date, or shows a value
that's set elsewhere, extend the behavioral guard with the matching class.

## Recurring-bug log (fixed at root)
- **Invisible primary button** (module-scoped tokens; modal renders outside) — #230 (Docs), recurred #235 (Field Photos) → root fix #236 (tokens globalized + guard).
- **Raw date field instead of SSCDatePicker** — recurred on several modals → root fix #236 (global auto-wire + guard).
