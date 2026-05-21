/* SSC Date Picker — small custom popup that REPLACES the native
 * <input type="date"> calendar across every dashboard surface. No external
 * library. Brand-matched (Inter + #B11E2E red accent). Header has prev/next
 * month, a month <select>, and a year <select> covering ~1940..(current+5)
 * for instant decade jumps (the whole point — DOB shouldn't require 480
 * prev-month clicks).
 *
 * Value contract: stored as YYYY-MM-DD on the input's .value, written
 * with local date arithmetic only — never via toISOString() (#74 / CLAUDE.md
 * dates rule).
 *
 * Usage:
 *   <script src="/files/static/js/datepicker.js"></script>
 *   SSCDatePicker.wire(document.getElementById('in-dob'), {max: 'today'});
 *   SSCDatePicker.wireAll('input.date-field');
 *
 * Options:
 *   max: 'today'   -> disallow future dates (DOB)
 *   minYear / maxYear: override the year range (default 1940..currentYear+5)
 */
(function(global) {
  'use strict';

  var BRAND_RED = '#B11E2E';
  var HAIR = '#E8E4DD';
  var INK = '#14161C';
  var MUTE = '#76777E';
  var STYLE_ID = 'ssc-dp-style';

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    var s = document.createElement('style');
    s.id = STYLE_ID;
    s.textContent = [
      '.ssc-dp-popup{',
      '  position:absolute;z-index:99999;background:#fff;',
      '  border:1px solid ' + HAIR + ';border-radius:8px;',
      '  box-shadow:0 8px 24px rgba(0,0,0,0.18);padding:12px;width:264px;',
      "  font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;",
      '  color:' + INK + ';font-size:13px;line-height:1.2;',
      '  -webkit-font-smoothing:antialiased;',
      '}',
      '.ssc-dp-popup *{box-sizing:border-box;}',
      '.ssc-dp-popup .head{display:flex;align-items:center;gap:4px;margin-bottom:8px;}',
      '.ssc-dp-popup button.nav{',
      '  background:#fff;border:1px solid ' + HAIR + ';border-radius:4px;',
      '  cursor:pointer;padding:4px 9px;color:' + INK + ';',
      '  font-family:inherit;font-size:16px;line-height:1;font-weight:600;',
      '}',
      '.ssc-dp-popup button.nav:hover{background:#F1EEE8;}',
      '.ssc-dp-popup select{',
      '  flex:1 1 auto;min-width:0;padding:4px 6px;',
      '  border:1px solid ' + HAIR + ';border-radius:4px;',
      '  font-family:inherit;font-size:13px;background:#fff;color:' + INK + ';',
      '  cursor:pointer;font-weight:600;',
      '}',
      '.ssc-dp-popup select:focus{outline:1px solid ' + BRAND_RED + ';outline-offset:0;}',
      '.ssc-dp-popup .grid{display:grid;grid-template-columns:repeat(7,1fr);gap:2px;}',
      '.ssc-dp-popup .dow{',
      '  text-align:center;font-size:10px;text-transform:uppercase;',
      '  letter-spacing:0.5px;color:' + MUTE + ';padding:4px 0;font-weight:700;',
      '}',
      '.ssc-dp-popup .day{',
      '  text-align:center;padding:6px 0;cursor:pointer;border-radius:4px;',
      '  font-size:13px;user-select:none;font-weight:500;',
      '}',
      '.ssc-dp-popup .day:hover{background:#F1EEE8;}',
      '.ssc-dp-popup .day.muted{color:#C8C0B4;cursor:default;}',
      '.ssc-dp-popup .day.muted:hover{background:transparent;}',
      '.ssc-dp-popup .day.today{outline:1px solid ' + BRAND_RED + ';outline-offset:-1px;font-weight:700;}',
      '.ssc-dp-popup .day.selected{background:' + BRAND_RED + ';color:#fff;font-weight:700;}',
      '.ssc-dp-popup .day.selected:hover{background:' + BRAND_RED + ';}',
      '.ssc-dp-popup .day.disabled{color:#C8C0B4;cursor:not-allowed;text-decoration:line-through;}',
      '.ssc-dp-popup .day.disabled:hover{background:transparent;}',
      '.ssc-dp-popup .foot{',
      '  display:flex;justify-content:space-between;gap:6px;',
      '  margin-top:8px;padding-top:8px;border-top:1px solid ' + HAIR + ';',
      '}',
      '.ssc-dp-popup .foot button{',
      '  background:#fff;border:1px solid ' + HAIR + ';border-radius:4px;',
      '  cursor:pointer;padding:5px 12px;font-size:12px;',
      '  font-family:inherit;color:' + INK + ';font-weight:600;',
      '}',
      '.ssc-dp-popup .foot button:hover{background:#F1EEE8;}',
      '.ssc-dp-popup .foot button.today-btn{color:' + BRAND_RED + ';border-color:' + BRAND_RED + ';}',
      'input[data-ssc-dp]{cursor:pointer;background:#fff;}',
      'input[data-ssc-dp]:focus{outline:1px solid ' + BRAND_RED + ';}',
    ].join('');
    document.head.appendChild(s);
  }

  var MONTHS = ['January','February','March','April','May','June',
                'July','August','September','October','November','December'];
  var DOW = ['Su','Mo','Tu','We','Th','Fr','Sa'];

  function pad(n) { return n < 10 ? '0' + n : '' + n; }

  // Format a JS Date (local) as YYYY-MM-DD. NEVER via toISOString — that
  // returns UTC and corrupts dates entered in the evening (the #74 bug).
  function toYMD(d) {
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  // Parse YYYY-MM-DD as a local-midnight Date. Returns null on bad input.
  function parseYMD(s) {
    if (!s) return null;
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s);
    if (!m) return null;
    var y = +m[1], mo = +m[2] - 1, d = +m[3];
    var dt = new Date(y, mo, d);
    if (dt.getFullYear() !== y || dt.getMonth() !== mo || dt.getDate() !== d) return null;
    return dt;
  }

  // Today as a local-midnight Date (so date comparisons via > / < work).
  function todayLocal() {
    var d = new Date();
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
  }

  function buildPopup(input, opts) {
    opts = opts || {};
    var minYear = opts.minYear || 1940;
    var curY = new Date().getFullYear();
    var maxYear = opts.maxYear || (curY + 5);
    var maxDate = (opts.max === 'today') ? todayLocal() :
                  (opts.max instanceof Date ? opts.max :
                   (typeof opts.max === 'string' ? parseYMD(opts.max) : null));

    ensureStyles();
    var popup = document.createElement('div');
    popup.className = 'ssc-dp-popup';

    var viewYear, viewMonth, selected;

    function init() {
      var cur = parseYMD(input.value) || todayLocal();
      selected = parseYMD(input.value);
      viewYear = cur.getFullYear();
      viewMonth = cur.getMonth();
      // Clamp the initial view into the allowed year range
      if (viewYear < minYear) { viewYear = minYear; viewMonth = 0; }
      if (viewYear > maxYear) { viewYear = maxYear; viewMonth = 11; }
    }

    function jumpMonth(delta) {
      var m = viewMonth + delta, y = viewYear;
      while (m < 0) { m += 12; y -= 1; }
      while (m > 11) { m -= 12; y += 1; }
      if (y < minYear) { y = minYear; m = 0; }
      if (y > maxYear) { y = maxYear; m = 11; }
      viewYear = y; viewMonth = m;
      render();
    }

    function pick(y, m, d) {
      var dt = new Date(y, m, d);
      if (maxDate && dt > maxDate) return;
      selected = dt;
      input.value = toYMD(dt);
      input.dispatchEvent(new Event('change', {bubbles: true}));
      close();
    }

    function render() {
      popup.innerHTML = '';
      var head = document.createElement('div');
      head.className = 'head';

      var prev = document.createElement('button');
      prev.type = 'button'; prev.className = 'nav';
      prev.innerHTML = '&#8249;'; prev.title = 'Previous month';
      prev.addEventListener('click', function(e) { e.preventDefault(); jumpMonth(-1); });

      var monthSel = document.createElement('select');
      monthSel.title = 'Month';
      MONTHS.forEach(function(name, i) {
        var o = document.createElement('option');
        o.value = String(i); o.textContent = name;
        if (i === viewMonth) o.selected = true;
        monthSel.appendChild(o);
      });
      monthSel.addEventListener('change', function() { viewMonth = +monthSel.value; render(); });

      var yearSel = document.createElement('select');
      yearSel.title = 'Year';
      for (var y = maxYear; y >= minYear; y--) {
        var o = document.createElement('option');
        o.value = String(y); o.textContent = String(y);
        if (y === viewYear) o.selected = true;
        yearSel.appendChild(o);
      }
      yearSel.addEventListener('change', function() { viewYear = +yearSel.value; render(); });

      var next = document.createElement('button');
      next.type = 'button'; next.className = 'nav';
      next.innerHTML = '&#8250;'; next.title = 'Next month';
      next.addEventListener('click', function(e) { e.preventDefault(); jumpMonth(1); });

      head.appendChild(prev);
      head.appendChild(monthSel);
      head.appendChild(yearSel);
      head.appendChild(next);
      popup.appendChild(head);

      var grid = document.createElement('div');
      grid.className = 'grid';
      DOW.forEach(function(d) {
        var el = document.createElement('div');
        el.className = 'dow'; el.textContent = d;
        grid.appendChild(el);
      });

      var firstDow = new Date(viewYear, viewMonth, 1).getDay();   // 0..6, Sun=0
      var daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();
      var daysInPrev = new Date(viewYear, viewMonth, 0).getDate();
      // Leading days (muted) so the first row aligns to the correct DOW
      for (var i = 0; i < firstDow; i++) {
        var dn = daysInPrev - firstDow + 1 + i;
        var ml = document.createElement('div');
        ml.className = 'day muted'; ml.textContent = String(dn);
        grid.appendChild(ml);
      }
      var today = todayLocal();
      var today_y = today.getFullYear(), today_m = today.getMonth(), today_d = today.getDate();
      for (var dn2 = 1; dn2 <= daysInMonth; dn2++) {
        var el = document.createElement('div');
        el.className = 'day'; el.textContent = String(dn2);
        var candidate = new Date(viewYear, viewMonth, dn2);
        if (viewYear === today_y && viewMonth === today_m && dn2 === today_d) {
          el.classList.add('today');
        }
        if (selected && selected.getFullYear() === viewYear
            && selected.getMonth() === viewMonth
            && selected.getDate() === dn2) {
          el.classList.add('selected');
        }
        if (maxDate && candidate > maxDate) {
          el.classList.add('disabled');
        } else {
          (function(yy, mm, dd) {
            el.addEventListener('click', function() { pick(yy, mm, dd); });
          })(viewYear, viewMonth, dn2);
        }
        grid.appendChild(el);
      }
      // Trailing muted days so the grid is rectangular
      var filled = firstDow + daysInMonth;
      var trailing = (filled % 7 === 0) ? 0 : (7 - (filled % 7));
      for (var t = 1; t <= trailing; t++) {
        var mt = document.createElement('div');
        mt.className = 'day muted'; mt.textContent = String(t);
        grid.appendChild(mt);
      }
      popup.appendChild(grid);

      var foot = document.createElement('div');
      foot.className = 'foot';
      var clearBtn = document.createElement('button');
      clearBtn.type = 'button';
      clearBtn.textContent = 'Clear';
      clearBtn.addEventListener('click', function(e) {
        e.preventDefault();
        input.value = '';
        selected = null;
        input.dispatchEvent(new Event('change', {bubbles: true}));
        close();
      });
      var todayBtn = document.createElement('button');
      todayBtn.type = 'button';
      todayBtn.className = 'today-btn';
      todayBtn.textContent = 'Today';
      todayBtn.addEventListener('click', function(e) {
        e.preventDefault();
        var t = todayLocal();
        pick(t.getFullYear(), t.getMonth(), t.getDate());
      });
      foot.appendChild(clearBtn);
      foot.appendChild(todayBtn);
      popup.appendChild(foot);
    }

    function position() {
      var r = input.getBoundingClientRect();
      var top = window.scrollY + r.bottom + 4;
      var left = window.scrollX + r.left;
      // Keep popup inside viewport — flip above input if there isn't room
      var popupH = 320;  // approximate; we don't render twice for measurement
      if (top + popupH > window.scrollY + window.innerHeight) {
        top = window.scrollY + r.top - popupH - 4;
      }
      // Keep popup inside viewport horizontally
      var popupW = 264;
      if (left + popupW > window.scrollX + window.innerWidth - 4) {
        left = window.scrollX + window.innerWidth - popupW - 4;
      }
      popup.style.top = Math.max(window.scrollY + 4, top) + 'px';
      popup.style.left = Math.max(window.scrollX + 4, left) + 'px';
    }

    function onOutsideMouse(e) {
      if (popup.contains(e.target) || e.target === input) return;
      close();
    }
    function onKey(e) {
      if (e.key === 'Escape') close();
    }

    function open() {
      init();
      render();
      document.body.appendChild(popup);
      position();
      // Defer the outside-click listener so the click that opens us doesn't immediately close us
      setTimeout(function() {
        document.addEventListener('mousedown', onOutsideMouse, true);
        document.addEventListener('keydown', onKey, true);
      }, 0);
    }
    function close() {
      try { popup.remove(); } catch (_) {}
      document.removeEventListener('mousedown', onOutsideMouse, true);
      document.removeEventListener('keydown', onKey, true);
    }

    return { open: open, close: close };
  }

  // Wire one input. Idempotent — re-wiring is a no-op.
  function wire(input, opts) {
    if (!input || input.dataset.sscDpWired === '1') return;
    input.dataset.sscDpWired = '1';
    // Switch off native picker — keep YYYY-MM-DD as the stored value.
    try { input.type = 'text'; } catch (_) {}
    input.setAttribute('data-ssc-dp', '1');
    input.setAttribute('readonly', '');           // operator must use the popup
    if (!input.getAttribute('placeholder')) {
      input.setAttribute('placeholder', 'YYYY-MM-DD');
    }
    input.setAttribute('autocomplete', 'off');
    input.style.cursor = 'pointer';

    var live = null;
    function toggle(e) {
      if (e) e.preventDefault();
      if (live) { live.close(); live = null; return; }
      live = buildPopup(input, opts);
      var origClose = live.close;
      live.close = function() { origClose(); live = null; };
      live.open();
    }
    input.addEventListener('focus', toggle);
    input.addEventListener('click', toggle);
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        toggle();
      }
    });
  }

  function wireAll(selector, opts) {
    var nodes = document.querySelectorAll(selector);
    for (var i = 0; i < nodes.length; i++) wire(nodes[i], opts);
  }

  global.SSCDatePicker = { wire: wire, wireAll: wireAll, parseYMD: parseYMD, toYMD: toYMD };
})(window);
