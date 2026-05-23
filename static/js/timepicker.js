/* SSC Time Picker — typed HH:MM + AM/PM toggle replacement for the
 * native `<input type="time">` scroll-wheel. The scroll wheel is
 * painful in the field (operator entering time-in / time-out on a
 * phone in glare, on a ladder, with gloves on); typing is faster.
 *
 * Wraps an existing `<input type="time">` without changing its id,
 * name, or value semantics:
 *   - The original input stays in the DOM as type="hidden", value is
 *     24h "HH:MM" (the canonical storage form — payroll_hours
 *     parses 24h HH:MM, the sign_in_log columns store 24h HH:MM).
 *   - A sibling visible component handles HH + MM text entry and an
 *     AM/PM toggle. The hidden input mirrors every change.
 *
 * Consumers can keep doing `document.getElementById('foo').value` and
 * get back canonical 24h HH:MM — no API changes needed downstream.
 *
 * Usage:
 *   <script src="/files/static/js/timepicker.js"></script>
 *   SSCTimePicker.wire(document.getElementById('dcr-labor-add-in'));
 *   SSCTimePicker.wireAll('input[type="time"]');
 */
(function(global) {
  'use strict';

  var BRAND_RED = '#B11E2E';
  var HAIR = '#E8E4DD';
  var INK = '#14161C';
  var STYLE_ID = 'ssc-tp-style';

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = [
      '.ssc-tp{',
      '  display:inline-flex;align-items:center;gap:2px;',
      '  padding:4px 6px;border:1px solid ' + HAIR + ';border-radius:4px;',
      "  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;",
      '  font-size:13px;background:#fff;color:' + INK + ';',
      '  -webkit-font-smoothing:antialiased;box-sizing:border-box;',
      '}',
      '.ssc-tp:focus-within{outline:1px solid ' + BRAND_RED + ';outline-offset:0;}',
      '.ssc-tp input.ssc-tp-num{',
      '  width:2.2em;border:none;outline:none;padding:2px 0;',
      '  text-align:center;font-family:inherit;font-size:inherit;',
      '  color:inherit;background:transparent;',
      '  font-variant-numeric:tabular-nums;',
      '  -moz-appearance:textfield;appearance:textfield;',
      '}',
      '.ssc-tp input.ssc-tp-num::-webkit-outer-spin-button,',
      '.ssc-tp input.ssc-tp-num::-webkit-inner-spin-button{',
      '  -webkit-appearance:none;margin:0;',
      '}',
      '.ssc-tp .ssc-tp-sep{padding:0 1px;color:#76777E;font-weight:600;}',
      '.ssc-tp button.ssc-tp-ampm{',
      '  margin-left:4px;padding:2px 8px;',
      '  border:1px solid ' + HAIR + ';border-radius:3px;',
      '  background:#fff;color:' + INK + ';cursor:pointer;',
      '  font-family:inherit;font-size:11px;font-weight:700;',
      '  letter-spacing:0.04em;line-height:1.3;min-width:32px;',
      '}',
      '.ssc-tp button.ssc-tp-ampm:hover{background:#F1EEE8;}',
      '.ssc-tp button.ssc-tp-ampm:focus{outline:1px solid ' + BRAND_RED + ';}',
      '.ssc-tp.invalid{border-color:' + BRAND_RED + ';}',
    ].join('');
    document.head.appendChild(s);
  }

  function pad2(n) { return (n < 10 ? '0' : '') + n; }

  // Parse '07:00' or '7:0' (24h or with leading zeros) into {hh, mm, ampm}
  // for the visible UI. Empty / invalid input returns null.
  function parse24(s) {
    if (!s) return null;
    var m = /^(\d{1,2}):(\d{1,2})$/.exec(String(s).trim());
    if (!m) return null;
    var h = +m[1], mm = +m[2];
    if (h < 0 || h > 23 || mm < 0 || mm > 59) return null;
    var ampm = (h < 12) ? 'AM' : 'PM';
    var h12 = (h % 12) || 12;
    return {hh12: h12, mm: mm, ampm: ampm};
  }

  // Compose a visible UI state ({hh12, mm, ampm}) back into canonical 24h
  // 'HH:MM'. Returns '' when any field is empty / invalid so caller can
  // distinguish "operator hasn't entered anything" from "operator entered 0".
  function compose24(state) {
    if (!state) return '';
    var h12 = state.hh12;
    var mm = state.mm;
    var ampm = state.ampm;
    if (h12 == null || h12 === '' || isNaN(h12) || mm == null || mm === '' || isNaN(mm)) return '';
    if (h12 < 1 || h12 > 12 || mm < 0 || mm > 59) return '';
    var h24 = h12 % 12;
    if (ampm === 'PM') h24 += 12;
    return pad2(h24) + ':' + pad2(mm);
  }

  // Build the visible component beside the hidden input. Returns the wrapper
  // element so wire() can keep a reference for value mirroring.
  function buildUI(hidden) {
    var wrap = document.createElement('span');
    wrap.className = 'ssc-tp';
    wrap.dataset.sscTpFor = hidden.id || '';

    var hh = document.createElement('input');
    hh.type = 'text';
    hh.className = 'ssc-tp-num ssc-tp-hh';
    hh.setAttribute('inputmode', 'numeric');
    hh.setAttribute('pattern', '[0-9]*');
    hh.setAttribute('maxlength', '2');
    hh.setAttribute('aria-label', 'Hour');
    hh.setAttribute('autocomplete', 'off');
    hh.placeholder = 'HH';

    var sep = document.createElement('span');
    sep.className = 'ssc-tp-sep';
    sep.textContent = ':';

    var mm = document.createElement('input');
    mm.type = 'text';
    mm.className = 'ssc-tp-num ssc-tp-mm';
    mm.setAttribute('inputmode', 'numeric');
    mm.setAttribute('pattern', '[0-9]*');
    mm.setAttribute('maxlength', '2');
    mm.setAttribute('aria-label', 'Minute');
    mm.setAttribute('autocomplete', 'off');
    mm.placeholder = 'MM';

    var ampm = document.createElement('button');
    ampm.type = 'button';
    ampm.className = 'ssc-tp-ampm';
    ampm.setAttribute('aria-label', 'AM or PM toggle');
    ampm.textContent = 'AM';

    wrap.appendChild(hh);
    wrap.appendChild(sep);
    wrap.appendChild(mm);
    wrap.appendChild(ampm);
    return {wrap: wrap, hh: hh, mm: mm, ampm: ampm};
  }

  // Reflect a 24h value from the hidden input into the visible UI.
  function syncFromHidden(parts, hidden) {
    var s = parse24(hidden.value);
    if (s) {
      parts.hh.value = pad2(s.hh12);
      parts.mm.value = pad2(s.mm);
      parts.ampm.textContent = s.ampm;
    } else {
      parts.hh.value = '';
      parts.mm.value = '';
      parts.ampm.textContent = 'AM';
    }
  }

  // Read the visible UI back into a 24h value on the hidden input, fire a
  // 'change' event so existing change-listeners on the original input keep
  // working. Operator-entered partial state (only HH typed, MM blank) leaves
  // the hidden value empty until both fields are valid.
  function syncToHidden(parts, hidden, wrap) {
    var state = {
      hh12: parts.hh.value === '' ? null : parseInt(parts.hh.value, 10),
      mm:   parts.mm.value === '' ? null : parseInt(parts.mm.value, 10),
      ampm: parts.ampm.textContent.trim() || 'AM',
    };
    var v = compose24(state);
    if (v) {
      wrap.classList.remove('invalid');
    } else if (parts.hh.value !== '' || parts.mm.value !== '') {
      // Operator started typing — flag partial / invalid state until both
      // fields settle, but don't paint the empty state as an error.
      wrap.classList.add('invalid');
    } else {
      wrap.classList.remove('invalid');
    }
    if (hidden.value !== v) {
      hidden.value = v;
      hidden.dispatchEvent(new Event('change', {bubbles: true}));
      hidden.dispatchEvent(new Event('input', {bubbles: true}));
    }
  }

  // Filter the keystroke to digits-only (operator typing a letter / symbol
  // gets nothing). Then clamp to the field's allowed range.
  function attachInputBehavior(parts, hidden, wrap) {
    function clampHH() {
      var raw = (parts.hh.value || '').replace(/\D+/g, '');
      raw = raw.slice(0, 2);
      // Don't aggressively clamp partial input — wait for blur or a second
      // digit. "1" might become "10" / "12"; "8" stays "8".
      if (raw.length === 2) {
        var n = parseInt(raw, 10);
        if (n > 12) raw = '12';
        else if (n === 0) raw = '01';
      }
      if (parts.hh.value !== raw) parts.hh.value = raw;
    }
    function clampMM() {
      var raw = (parts.mm.value || '').replace(/\D+/g, '');
      raw = raw.slice(0, 2);
      if (raw.length === 2) {
        var n = parseInt(raw, 10);
        if (n > 59) raw = '59';
      }
      if (parts.mm.value !== raw) parts.mm.value = raw;
    }
    parts.hh.addEventListener('input', function() {
      clampHH();
      // Auto-advance to MM once HH is 2 digits (or 1-9 + the natural cursor
      // wouldn't accept another) — operator types "0700" and tabs through.
      if (parts.hh.value.length === 2) {
        parts.mm.focus();
        parts.mm.select();
      }
      syncToHidden(parts, hidden, wrap);
    });
    parts.mm.addEventListener('input', function() {
      clampMM();
      syncToHidden(parts, hidden, wrap);
    });
    parts.hh.addEventListener('blur', function() {
      // Normalize on blur — '7' becomes '07'.
      var v = (parts.hh.value || '').replace(/\D+/g, '');
      if (v && v.length === 1) parts.hh.value = pad2(parseInt(v, 10));
      syncToHidden(parts, hidden, wrap);
    });
    parts.mm.addEventListener('blur', function() {
      var v = (parts.mm.value || '').replace(/\D+/g, '');
      if (v && v.length === 1) parts.mm.value = pad2(parseInt(v, 10));
      syncToHidden(parts, hidden, wrap);
    });
    parts.ampm.addEventListener('click', function(e) {
      e.preventDefault();
      parts.ampm.textContent = (parts.ampm.textContent.trim() === 'AM') ? 'PM' : 'AM';
      syncToHidden(parts, hidden, wrap);
    });
    // Keyboard: arrow-up/down on HH or MM nudges the value. Same on AM/PM
    // toggles between AM and PM.
    parts.hh.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        var n = parseInt(parts.hh.value || '0', 10);
        n += (e.key === 'ArrowUp') ? 1 : -1;
        if (n < 1) n = 12;
        if (n > 12) n = 1;
        parts.hh.value = pad2(n);
        syncToHidden(parts, hidden, wrap);
      }
    });
    parts.mm.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        var n = parseInt(parts.mm.value || '0', 10);
        n += (e.key === 'ArrowUp') ? 1 : -1;
        if (n < 0) n = 59;
        if (n > 59) n = 0;
        parts.mm.value = pad2(n);
        syncToHidden(parts, hidden, wrap);
      }
    });
    parts.ampm.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowUp' || e.key === 'ArrowDown' || e.key === ' ') {
        e.preventDefault();
        parts.ampm.textContent = (parts.ampm.textContent.trim() === 'AM') ? 'PM' : 'AM';
        syncToHidden(parts, hidden, wrap);
      }
    });
  }

  // Wire one `<input type="time">` (or any input intended to hold a 24h
  // HH:MM string). Idempotent — re-wiring is a no-op.
  function wire(input) {
    if (!input || input.dataset.sscTpWired === '1') return;
    input.dataset.sscTpWired = '1';
    ensureStyles();

    // Preserve the operator's current value before flipping the type —
    // `<input type="time">` accepts 24h "HH:MM" and exposes that on .value;
    // we want the same canonical form on the hidden input that replaces it.
    var initialValue = input.value || input.getAttribute('value') || '';
    try { input.type = 'hidden'; } catch (_) { input.style.display = 'none'; }
    input.value = initialValue;

    var parts = buildUI(input);
    // Insert the visible UI immediately after the hidden input so it occupies
    // the same flow position the original input did.
    if (input.parentNode) {
      input.parentNode.insertBefore(parts.wrap, input.nextSibling);
    }
    syncFromHidden(parts, input);
    attachInputBehavior(parts, input, parts.wrap);
    // Cache the wrap reference for re-syncs initiated by callers via set().
    input._sscTp = {wrap: parts.wrap, parts: parts};
  }

  function wireAll(selector) {
    var nodes = document.querySelectorAll(selector || 'input[type="time"]');
    for (var i = 0; i < nodes.length; i++) wire(nodes[i]);
  }

  // Read canonical 24h HH:MM from a wired input. Falls through to .value for
  // unwired inputs so call sites are safe to use unconditionally.
  function get(input) {
    if (!input) return '';
    return input.value || '';
  }

  // Programmatically set the visible UI from a 24h HH:MM string. Used by
  // callers that need to reset / pre-fill (e.g., the Hours Log "8h" button
  // which writes 07:00 / 15:30).
  function set(input, hhmm24) {
    if (!input) return;
    input.value = hhmm24 || '';
    if (input._sscTp) {
      syncFromHidden(input._sscTp.parts, input);
      input.dispatchEvent(new Event('change', {bubbles: true}));
    }
  }

  global.SSCTimePicker = {
    wire: wire,
    wireAll: wireAll,
    get: get,
    set: set,
    parse24: parse24,
    compose24: compose24,
  };
})(window);
