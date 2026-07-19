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
      // #278 ROOT FIX — a layout array must never DELETE widgets it predates.
      // GridStack.load(layout) treats the array as the complete desired state and
      // REMOVES grid items missing from it, so a per-user layout saved before a
      // new widget shipped silently erased that widget for that user (hit live
      // with the #272b/#278 additions: markup present, widget gone on restore).
      // Merge instead: saved/default positions win for known ids; any grid item
      // the layout doesn't know is APPENDED BELOW at its own width/height. The
      // next drag persists the merged result, adopting the new widget forever.
      var mergeUnknown = function (layout) {
        // real widgets = what's actually in the grid right now; a saved id with
        // no matching grid item (a widget removed in a later build) is DROPPED —
        // GridStack.load would otherwise create an empty box for it.
        var real = {};
        grid.save(false).forEach(function (n) { if (n.id) real[n.id] = true; });
        var kept = (layout || []).filter(function (n) { return n && real[n.id]; });
        var known = {}, maxY = 0;
        kept.forEach(function (n) {
          known[n.id] = true;
          maxY = Math.max(maxY, (n.y || 0) + (n.h || 1));
        });
        var extras = grid.save(false)
          .filter(function (n) { return n.id && !known[n.id]; })
          .map(function (n) { var e = { id: n.id, x: n.x || 0, y: maxY, w: n.w, h: n.h }; maxY += (n.h || 1); return e; });
        return kept.concat(extras);
      };
      var apply = function (layout) { suppress = true; grid.load(mergeUnknown(layout)); setTimeout(function () { suppress = false; if (cfg.onChange) cfg.onChange(); }, 60); };

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
