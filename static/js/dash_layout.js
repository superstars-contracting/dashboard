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
 *
 * #292 S2.0 — ZERO LAYOUT SHIFT. The user's last-known layout is cached under
 * ssc.boot.layout.<page_key> and applied SYNCHRONOUSLY in the same task as
 * GridStack.init, with animation disabled — the first painted frame already
 * shows the saved positions. The server GET is demoted to background
 * reconciliation: applied (animation OFF) only on a genuine difference, then
 * written through to the cache. Cache rides SSC_BOOT (staff: localStorage,
 * 24h TTL, logout purge, uid guard) when the staff chrome is present, else a
 * sessionStorage envelope under the same ssc.boot.* prefix (the portal — its
 * own purge/uid sweep covers that store; shared devices never touch
 * localStorage). First-ever visit in a browser has no cache by definition:
 * the server layout then applies as an unanimated snap, once, and is cached
 * from that point on.
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

  // #292 — layout cache, store chosen by surface (see module header)
  function readCachedLayout(pageKey) {
    try {
      if (window.SSC_BOOT) {
        var env = window.SSC_BOOT.read('layout.' + pageKey);
        return env && env.bd;
      }
      var j = JSON.parse(sessionStorage.getItem('ssc.boot.layout.' + pageKey) || 'null');
      return j && j.bd;
    } catch (e) { return null; }
  }
  function writeCachedLayout(pageKey, layout) {
    try {
      if (window.SSC_BOOT) { window.SSC_BOOT.write('layout.' + pageKey, layout); return; }
      sessionStorage.setItem('ssc.boot.layout.' + pageKey, JSON.stringify({
        bd: layout,
        uid: (window.__PORTAL_UID != null ? window.__PORTAL_UID : null),
        at: Date.now()
      }));
    } catch (e) { }
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
        draggable: { handle: '.ph-grip' }, resizable: { handles: 'e,se,s,sw,w' }, float: false,
        // #292 — init with animation OFF so the synchronous cache-apply below
        // lands inside the FIRST painted frame (no tween from markup positions).
        // Re-enabled right after, so drag/resize UX keeps its motion.
        animate: false
      }, cfg.gridOpts || {});
      var grid = GridStack.init(opts, cfg.gridSelector || '.grid-stack');

      var timer = null, suppress = false;
      var serialize = function () { return grid.save(false).map(function (n) { return { id: n.id, x: n.x, y: n.y, w: n.w, h: n.h }; }); };
      var save = function () {
        var snap = serialize();
        writeCachedLayout(PAGE_KEY, snap);   // #292 — write-through on every persist
        return api('PUT', { page_key: PAGE_KEY, layout: snap })
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
      // #292 — reconcile-grade apply: guaranteed animation-free, cache-updating
      var applySilent = function (layout) {
        var wasAnim = grid.opts.animate;
        try { grid.setAnimation(false); } catch (e) { }
        apply(layout);
        writeCachedLayout(PAGE_KEY, mergeUnknown(layout));
        try { grid.setAnimation(wasAnim); } catch (e) { }
      };

      grid.on('change', function () { schedule(); if (cfg.onChange) cfg.onChange(); });

      if (cfg.resetBtnId) {
        var rb = document.getElementById(cfg.resetBtnId);
        if (rb) rb.addEventListener('click', function () {
          api('DELETE', null, '?page_key=' + encodeURIComponent(PAGE_KEY)).catch(function () {});
          apply(DEFAULT); writeCachedLayout(PAGE_KEY, DEFAULT); hint('Reset to default layout');
        });
      }

      // #292 — FIRST FRAME: apply the cached layout synchronously, same task as
      // init, animation still off — widgets are painted in their saved
      // positions from the very first frame. MUST precede the server GET below.
      var cached = readCachedLayout(PAGE_KEY);
      var painted = null;
      if (Array.isArray(cached) && cached.length) {
        suppress = true;
        grid.load(mergeUnknown(cached));
        suppress = false;
        painted = JSON.stringify(mergeUnknown(cached));
        hint('Your saved layout');
        // permanent first-frame evidence: this mark's startTime must precede
        // first-contentful-paint whenever the cache path ran
        try { performance.mark('ssc-layout-cache-applied'); } catch (e) { }
      }
      // animation back on for human drag/resize UX (after the sync apply)
      try { grid.setAnimation(cfg.gridOpts && cfg.gridOpts.animate === false ? false : true); } catch (e) { }
      if (cfg.onChange && painted) { try { cfg.onChange(); } catch (e) { } }

      // #292 — server fetch DEMOTED to background reconciliation: apply only on
      // a genuine difference, and never with animation.
      api('GET', null, '?page_key=' + encodeURIComponent(PAGE_KEY))
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (j) {
          var saved = j && j.data && j.data.layout;
          if (Array.isArray(saved) && saved.length) {
            var want = JSON.stringify(mergeUnknown(saved));
            if (painted !== null && want === painted) { hint('Your saved layout restored'); return; }
            applySilent(saved);
            hint('Your saved layout restored');
          } else if (painted === null) {
            hint('Default layout');
          } else {
            // server has no layout but we painted a cached one (reset elsewhere)
            applySilent(DEFAULT);
            hint('Default layout');
          }
        })
        .catch(function () { if (painted === null) hint('Default layout'); });

      return grid;
    }
  };
})();
