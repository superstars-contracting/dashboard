/* ===== Reusable per-user dashboard layout framework (#209 → shared in #210) =====
 * Wraps the vendored GridStack + the GENERIC /api/dashboard/layout endpoints +
 * the dashboard_layouts table so ANY surface gets drag/resize + per-user saved
 * layouts by calling DashLayout.init(cfg) — no per-page rebuild.
 *
 *   DashLayout.init({
 *     pageKey:      'company_console',     // server-allowlisted page_key
 *     defaultLayout:[{id,x,y,w,h}, ...],   // applied when no saved layout / on reset
 *     gridSelector: '.grid-stack',         // optional (default '.grid-stack')
 *     resetBtnId:   'cc-reset-layout',     // optional reset-to-default button
 *     hintId:       'cc-layout-hint',      // optional status text element
 *     gridOpts:     {},                    // optional GridStack option overrides
 *     onChange:     fn,                    // optional (e.g. re-fit charts on resize)
 *   })  -> returns the GridStack instance (or null if the lib is unavailable).
 *
 * Persisted layout = [{id,x,y,w,h}] — widget ids + grid positions ONLY (no PII).
 * Layout saves are debounced on drag/resize-stop; restore on load; DELETE resets.
 */
(function () {
  function fmtMDY() {
    var d = new Date();
    return String(d.getMonth() + 1).padStart(2, '0') + '/' +
           String(d.getDate()).padStart(2, '0') + '/' + d.getFullYear();
  }
  function api(method, body, qs) {
    var opt = { method: method, credentials: 'include' };
    if (body) { opt.headers = { 'Content-Type': 'application/json' }; opt.body = JSON.stringify(body); }
    return fetch('/api/dashboard/layout' + (qs || ''), opt);
  }

  window.DashLayout = {
    init: function (cfg) {
      cfg = cfg || {};
      var hintEl = cfg.hintId ? document.getElementById(cfg.hintId) : null;
      var hint = function (t) { if (hintEl) hintEl.textContent = t; };
      if (typeof GridStack === 'undefined') { hint('Drag library unavailable — layout is fixed'); return null; }

      var PAGE_KEY = cfg.pageKey;
      var DEFAULT = cfg.defaultLayout || [];
      var opts = Object.assign({
        column: 12, cellHeight: 88, margin: 8, handle: '.ph-grip',
        draggable: { handle: '.ph-grip' }, resizable: { handles: 'e,se,s,sw,w' }, float: false
      }, cfg.gridOpts || {});
      var grid = GridStack.init(opts, cfg.gridSelector || '.grid-stack');

      var timer = null, suppress = false;
      var serialize = function () { return grid.save(false).map(function (n) { return { id: n.id, x: n.x, y: n.y, w: n.w, h: n.h }; }); };
      var save = function () {
        return api('PUT', { page_key: PAGE_KEY, layout: serialize() })
          .then(function () { hint('Layout saved · ' + fmtMDY()); })
          .catch(function () { hint('Save failed — will retry on next move'); });
      };
      var schedule = function () { if (suppress) return; clearTimeout(timer); timer = setTimeout(save, 500); };
      var apply = function (layout) { suppress = true; grid.load(layout); setTimeout(function () { suppress = false; if (cfg.onChange) cfg.onChange(); }, 60); };

      grid.on('change', function () { schedule(); if (cfg.onChange) cfg.onChange(); });

      if (cfg.resetBtnId) {
        var rb = document.getElementById(cfg.resetBtnId);
        if (rb) rb.addEventListener('click', function () {
          api('DELETE', null, '?page_key=' + encodeURIComponent(PAGE_KEY)).catch(function () {});
          apply(DEFAULT); hint('Reset to default layout');
        });
      }

      // restore saved layout (or default)
      api('GET', null, '?page_key=' + encodeURIComponent(PAGE_KEY))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          var saved = j && j.data && j.data.layout;
          if (Array.isArray(saved) && saved.length) { apply(saved); hint('Your saved layout restored'); }
          else { hint('Default layout'); }
        })
        .catch(function () { hint('Default layout'); });

      return grid;
    }
  };
})();
