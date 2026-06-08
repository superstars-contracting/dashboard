"""
smoke_design_conventions.py — design-system guard (#236).

Stops the two recurring UI regressions at the root by FAILING the build if:
  (a) a known PRIMARY/SUBMIT button on a Lumen-modal surface would compute to a
      transparent / near-white background — the invisible-button bug (#230 Docs,
      #235 Field Photos). Cause: the button's background is var(--X) where --X is
      a per-MODULE token (--fp-accent on .fp-wrap, etc.) that does NOT exist at
      :root — and the modal renders at the page root, OUTSIDE that wrapper, so
      var(--X) resolves to nothing -> transparent.
  (b) a raw, un-wired MM/DD/YYYY text date field exists on those surfaces (the
      auto-wire only catches .ssc-date + <input type=date>; a bare text box with
      a date placeholder slips through).

It works WITHOUT a browser: it parses the served HTML + widgets.css and resolves
the CSS custom-property graph the way a modal at page root would (only :root
tokens resolve). A self-test proves the guard FAILS on a deliberately broken
button + raw date and PASSES on the fixed ones. Read-only; touches no data.
"""
import os
import re
import sys
from pathlib import Path

import requests

import _smoke_auth  # noqa: E402
_smoke_auth.setup()

BASE = os.environ.get("SMOKE_BASE", "http://127.0.0.1:5050")
PASS, FAIL = [], []


def ok(name, cond, note=""):
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {note}" if note else ""))
    return bool(cond)


# ---------- CSS token / color resolution (modal = page root: only :root resolves) ----------
def parse_root_tokens(css):
    tokens = {}
    for block in re.findall(r":root\s*\{([^}]*)\}", css, re.DOTALL):
        for m in re.finditer(r"(--[\w-]+)\s*:\s*([^;]+);", block):
            tokens[m.group(1).strip()] = m.group(2).strip()
    return tokens


def class_background(css, cls):
    """Last `background[-color]` declaration for a bare `.cls { ... }` rule."""
    bg = None
    for m in re.finditer(r"(?:^|[,\s}])\." + re.escape(cls) + r"\s*\{([^}]*)\}", css, re.DOTALL):
        bm = re.search(r"background(?:-color)?\s*:\s*([^;]+)", m.group(1))
        if bm:
            bg = bm.group(1).strip()
    return bg


def resolve_color(value, root_tokens):
    """Resolve a CSS color value as a MODAL (page-root) would: var() resolves
    ONLY from :root tokens. Returns the literal color, or None if a var() can't
    resolve (which computes to transparent -> the invisible-button bug)."""
    value = (value or "").strip()
    for _ in range(6):
        m = re.match(r"var\(\s*(--[\w-]+)\s*(?:,\s*([^)]+))?\)\s*$", value)
        if not m:
            break
        name, fallback = m.group(1), (m.group(2) or "").strip()
        if name in root_tokens:
            value = root_tokens[name].strip()
        elif fallback:
            value = fallback
        else:
            return None  # unresolved -> transparent
    return value


def is_visible_bg(color):
    if not color:
        return False
    c = color.strip().lower()
    if c in ("transparent", "none", "inherit", "initial", "unset", ""):
        return False
    if c in ("#fff", "#ffffff", "white", "#fefefe"):
        return False
    if c.startswith("rgba") and re.search(r",\s*0(?:\.0+)?\s*\)$", c):
        return False  # zero alpha
    return True


def find_tag(html, el_id):
    m = re.search(r"<button[^>]*\bid=\"" + re.escape(el_id) + r"\"[^>]*>", html)
    if not m:
        m = re.search(r"<[a-zA-Z]+[^>]*\bid=\"" + re.escape(el_id) + r"\"[^>]*>", html)
    return m.group(0) if m else None


def button_bg(html, css, el_id, root_tokens):
    tag = find_tag(html, el_id)
    if not tag:
        return None, "(button not found)"
    cm = re.search(r'class="([^"]*)"', tag)
    classes = cm.group(1).split() if cm else []
    bg = None
    for cls in classes:
        b = class_background(css, cls)
        if b:
            bg = b
    if bg is None:
        sm = re.search(r"style=\"[^\"]*background(?:-color)?\s*:\s*([^;\"]+)", tag)
        if sm:
            bg = sm.group(1).strip()
    if bg is None:
        return None, f"(no background for classes {classes})"
    return resolve_color(bg, root_tokens), bg


# ---------- raw-date detection ----------
def raw_date_inputs(html):
    """Text inputs with a MM/DD/YYYY-style placeholder that LACK .ssc-date — the
    auto-wire can't reach them, so they ship as raw date boxes."""
    hits = []
    for tag in re.findall(r"<input\b[^>]*>", html):
        ph = (re.search(r'placeholder="([^"]*)"', tag) or _N).group(1) if re.search(r'placeholder="([^"]*)"', tag) else ""
        cls = (re.search(r'class="([^"]*)"', tag) or _N).group(1) if re.search(r'class="([^"]*)"', tag) else ""
        is_mdy_text = bool(re.search(r"MM\s*[/-]\s*DD\s*[/-]\s*YYYY", ph, re.I)) and 'type="date"' not in tag
        if is_mdy_text and "ssc-date" not in cls:
            hits.append(tag[:90])
    return hits


class _N:
    @staticmethod
    def group(_):
        return ""


# ---------- drop-zone boundary (#237): a known modal drop zone must show a box ----------
def class_decl(css, cls, prop):
    """Last `prop: value` declaration for a bare `.cls { ... }` rule."""
    val = None
    for m in re.finditer(r"(?:^|[,\s}])\." + re.escape(cls) + r"\s*\{([^}]*)\}", css, re.DOTALL):
        pm = re.search(prop + r"\s*:\s*([^;]+)", m.group(1))
        if pm:
            val = pm.group(1).strip()
    return val


_COLOR_TOK = r"(var\([^)]*\)|#[0-9a-fA-F]{3,8}|rgba?\([^)]*\)|hsla?\([^)]*\)|transparent|currentColor|[a-zA-Z]+)"


def border_color_of(border_decl):
    """The color token from a `border` shorthand (skip width/style keywords)."""
    if not border_decl:
        return None
    for t in reversed(re.findall(_COLOR_TOK, border_decl)):
        if t.lower() in ("solid", "dashed", "dotted", "double", "groove", "ridge", "inset",
                         "outset", "none", "hidden", "px", "em", "rem"):
            continue
        if re.match(r"^\d", t):
            continue
        return t
    return None


def box_visible(html, css, el_id, root):
    """A drop zone is visible iff its border-color OR background resolves (the way
    a page-root modal would) to a non-transparent value."""
    tag = find_tag(html, el_id)
    if not tag:
        return None
    classes = (re.search(r'class="([^"]*)"', tag).group(1).split()
               if re.search(r'class="([^"]*)"', tag) else [])
    border = bg = None
    for cls in classes:
        b = class_decl(css, cls, "border")
        bc = class_decl(css, cls, "border-color")
        g = class_background(css, cls)
        if b:
            border = b
        if bc:
            border = bc            # explicit border-color wins the color
        if g:
            bg = g
    bcol = border_color_of(border)
    bres = resolve_color(bcol, root) if bcol else None
    gres = resolve_color(bg, root) if bg else None
    return {"visible": is_visible_bg(bres) or is_visible_bg(gres),
            "dashed": bool(border and "dashed" in border),
            "border": bcol, "border_resolved": bres, "bg": bg, "bg_resolved": gres}


# ---------- form-field boxes (#238): inputs/selects/textareas must be bordered ----------
def selector_decl(css, selector, prop):
    """Last `prop:value` for a rule whose comma-separated selector list contains
    `selector` (e.g. ".fp-field input")."""
    val = None
    for m in re.finditer(r"([^{}]+)\{([^}]*)\}", css, re.DOTALL):
        if selector in [s.strip() for s in m.group(1).split(",")]:
            pm = re.search(prop + r"\s*:\s*([^;]+)", m.group(2))
            if pm:
                val = pm.group(1).strip()
    return val


def field_border_visible(html, css, field_id, root):
    """Resolve a known modal field's effective border (from its `.wrapper tag`
    rule and/or its own classes) the way a page-root modal would, and report
    whether it is visible."""
    tag = find_tag(html, field_id)
    if not tag:
        return None
    tagname = re.match(r"<([a-zA-Z]+)", tag).group(1).lower()
    classes = (re.search(r'class="([^"]*)"', tag).group(1).split()
               if re.search(r'class="([^"]*)"', tag) else [])
    # nearest preceding wrapper class matching *-field
    pos = html.find('id="' + field_id + '"')
    wrapper = None
    for m in re.finditer(r'class="([^"]*)"', html[:pos]):
        for c in m.group(1).split():
            if re.match(r"^[\w-]+-field$", c):
                wrapper = c
    border = None
    if wrapper:
        b = (selector_decl(css, "." + wrapper + " " + tagname, "border-color")
             or selector_decl(css, "." + wrapper + " " + tagname, "border"))
        if b:
            border = b
    for c in classes:
        b = class_decl(css, c, "border-color") or class_decl(css, c, "border")
        if b:
            border = b   # an explicit class on the field wins
    bcol = border_color_of(border)
    bres = resolve_color(bcol, root) if bcol else None
    return {"visible": is_visible_bg(bres), "wrapper": wrapper, "tag": tagname,
            "border": bcol, "border_resolved": bres}


def main():
    print("== #236 design-conventions guard ==")
    css = requests.get(f"{BASE}/files/static/css/widgets.css", timeout=15).text
    dp = requests.get(f"{BASE}/files/static/js/datepicker.js", timeout=15).text
    html = requests.get(f"{BASE}/projects/FR-BX-001", timeout=20).text
    # Resolve against widgets.css :root + the page's inline <style> blocks (where
    # per-module rules like .exp-primary live). :root tokens come only from true
    # :root blocks; module tokens on .fp-wrap/.pd-wrap are NOT global (correct).
    inline = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.DOTALL))
    css_all = css + "\n" + inline
    root = parse_root_tokens(css_all)

    # ---- 0) globalization wiring is in place ----
    ok("root_accent_is_lumen", root.get("--accent", "").lower() in ("#4364dc", "rgb(67,100,220)"),
       f"--accent={root.get('--accent')}")
    ok("root_has_core_tokens", all(t in root for t in ("--accent", "--ink", "--muted", "--line")),
       str(sorted(k for k in root if k in ("--accent", "--ink", "--muted", "--line"))))
    ok("shared_btn_primary_defined", class_background(css, "btn-primary") is not None)
    ok("datepicker_autowire_present", "autoWire" in dp and "MutationObserver" in dp)

    # ---- 1) SELF-TEST: the guard catches a deliberately-broken button + raw date ----
    print("\n-- self-test (must catch broken, pass fixed) --")
    broken = resolve_color("var(--fp-accent)", root)          # module token, not at :root
    ok("selftest_broken_button_caught", not is_visible_bg(broken), f"var(--fp-accent) -> {broken} (transparent)")
    good = resolve_color("var(--accent)", root)
    ok("selftest_fixed_button_passes", is_visible_bg(good), f"var(--accent) -> {good}")
    ok("selftest_raw_date_caught",
       len(raw_date_inputs('<input type="text" id="x" placeholder="MM/DD/YYYY">')) == 1)
    ok("selftest_ssc_date_passes",
       len(raw_date_inputs('<input type="text" class="ssc-date" placeholder="MM-DD-YYYY">')) == 0)

    # ---- 2) REAL: known Lumen-modal primary buttons must resolve to a visible accent ----
    print("\n-- real surfaces (project dashboard) --")
    checks = [
        ("fieldphotos_upload_btn", "fp-up-go"),
        ("docs_save_single", "pd-save-single"),
        ("docs_save_bulk", "pd-save-bulk"),
        ("expense_scan_btn", "exp-scan-btn"),
    ]
    for name, bid in checks:
        resolved, raw = button_bg(html, css_all, bid, root)
        ok(name + "_visible", is_visible_bg(resolved), f"{bid}: {raw} -> {resolved}")
        # extra: the modal action buttons should be the accent blue specifically
        if bid in ("fp-up-go", "pd-save-single", "pd-save-bulk"):
            ok(name + "_is_accent", (resolved or "").lower() in ("#4364dc", "rgb(67,100,220)"),
               f"{bid} -> {resolved}")

    # ---- 3) REAL: no raw un-wired date boxes anywhere on the dashboard ----
    raws = raw_date_inputs(html)
    ok("no_raw_date_inputs", len(raws) == 0, ("found: " + "; ".join(raws)) if raws else "none")

    # ---- 4) the Field Photos date field is the standard SSCDatePicker field ----
    fp_date = re.search(r'<input[^>]*id="fp-up-date"[^>]*>', html)
    ok("fieldphotos_date_is_ssc", bool(fp_date) and "ssc-date" in fp_date.group(0),
       fp_date.group(0)[:100] if fp_date else "(not found)")

    # ---- 5) drop zones must show a VISIBLE box (#237) ----
    print("\n-- drop-zone boundary (#237) --")
    # self-test (end-to-end): a module-token (page-root-unresolvable) drop zone is
    # caught; the shared .dropzone passes.
    broken = box_visible('<div class="brk-dz" id="brk">x</div>',
                         ".brk-dz{border:2px dashed var(--fp-accent-edge);background:var(--fp-accent-soft)}", "brk", root)
    ok("selftest_stripped_dropzone_caught", not broken["visible"],
       f"border->{broken['border_resolved']} bg->{broken['bg_resolved']}")
    fixed = box_visible('<div class="dropzone" id="fix">x</div>', css_all, "fix", root)
    ok("selftest_fixed_dropzone_passes", fixed["visible"],
       f"border->{fixed['border_resolved']} bg->{fixed['bg_resolved']}")
    ok("shared_dropzone_defined", class_decl(css, "dropzone", "border") is not None)
    # real: the Field Photos + Project Documents drop zones show a visible dashed box
    for name, did in (("fieldphotos_dropzone", "fp-dropzone"), ("docs_dropzone", "pd-drop")):
        box = box_visible(html, css_all, did, root)
        ok(name + "_visible_box", bool(box and box["visible"]),
           (f"border {box['border']}->{box['border_resolved']} · bg {box['bg']}->{box['bg_resolved']}")
           if box else "(not found)")
        ok(name + "_dashed_border", bool(box and box["dashed"]), str(box["dashed"] if box else None))

    # ---- 6) every form field on a known modal must have a VISIBLE box (#238) ----
    print("\n-- form-field boxes (#238) --")
    # self-test: a module-token field border (page-root-unresolvable) is caught; the
    # global token passes.
    ok("selftest_bare_field_caught", not is_visible_bg(resolve_color("var(--fp-line)", root)),
       f"var(--fp-line) -> {resolve_color('var(--fp-line)', root)}")
    ok("selftest_boxed_field_passes", is_visible_bg(resolve_color("var(--line)", root)),
       f"var(--line) -> {resolve_color('var(--line)', root)}")
    ok("shared_field_rule_resolves",
       is_visible_bg(resolve_color(border_color_of(selector_decl(css, ".fp-field input", "border")), root)),
       f".fp-field input -> {selector_decl(css, '.fp-field input', 'border')}")
    # real: known modal fields (input/select/textarea) render bordered
    for fid in ("fp-up-drop", "fp-up-date", "fp-up-desc",
                "pd-f-cat", "pd-f-title", "pd-f-eff", "pd-f-notes", "exp-f-date"):
        fb = field_border_visible(html, css_all, fid, root)
        ok("field_boxed_" + fid, bool(fb and fb["visible"]),
           (f"{fb['tag']} in .{fb['wrapper']}: {fb['border']}->{fb['border_resolved']}") if fb else "(not found)")
    # Field Photos: Description is a free-text textarea; Worker/Stage are gone
    ok("fp_description_is_textarea", bool(re.search(r'<textarea[^>]*id="fp-up-desc"', html)))
    ok("fp_worker_stage_removed",
       all(x not in html for x in ('id="fp-up-worker"', 'id="fp-up-stage"', 'id="fp-bar-stage"')))

    print(f"\n== RESULT: {len(PASS)} PASS / {len(FAIL)} FAIL ==")
    if FAIL:
        print("FAILURES: " + ", ".join(FAIL))
    print("OVERALL:", "PASS" if not FAIL else "FAIL")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
