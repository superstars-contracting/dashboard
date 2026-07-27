/* UI v2 — the persistent "You're on the new interface · Switch back" affordance (#279).
 *
 * This is NOT decoration. It is the primary support channel for the v2 rollout: the one
 * control that lets someone who hit a broken or unfamiliar v2 page put themselves back on
 * a working screen without finding the operator. Every v2 page carries it.
 *
 * Usage — one line near the end of a v2 page body:
 *     <script src="/files/static/v2/switch-back.js"></script>
 *
 * It self-mounts on DOM ready. It is inert on v1 pages by construction: no v1 file
 * references it, and deleting static/v2/ removes it along with the rest of v2.
 *
 * Switching back POSTs the user's own preference (/api/ui/version) and reloads. The
 * ?ui= override is deliberately NOT used for the switch: a query-string flip lasts one
 * request, so the next navigation would drop the user straight back into v2.
 */
(function () {
  'use strict';

  var BAR_ID = 'ssc-v2-switchback';

  function post(version) {
    return fetch('/api/ui/version', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ ui_version: version })
    });
  }

  function switchToClassic(btn) {
    btn.disabled = true;
    btn.textContent = 'Switching…';
    post(1).then(function (r) {
      if (!r.ok) throw new Error('status ' + r.status);
      // Drop any ?ui= override on the way out, or it would win over what we just stored.
      var u = new URL(window.location.href);
      u.searchParams.delete('ui');
      window.location.replace(u.toString());
    }).catch(function () {
      btn.disabled = false;
      btn.textContent = 'Switch back';
      var note = document.getElementById(BAR_ID + '-err');
      if (note) note.hidden = false;
    });
  }

  function mount() {
    if (document.getElementById(BAR_ID)) return;

    var bar = document.createElement('div');
    bar.id = BAR_ID;
    bar.setAttribute('role', 'status');
    bar.style.cssText = [
      'position:fixed', 'left:50%', 'bottom:16px', 'transform:translateX(-50%)',
      'z-index:9999', 'display:flex', 'align-items:center', 'gap:10px',
      'background:#fff', 'border:1px solid #eceef3', 'border-radius:10px',
      'padding:8px 12px', 'box-shadow:0 4px 16px rgba(34,38,51,.10)',
      'font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif',
      'font-size:12.5px', 'color:#222633', 'max-width:calc(100vw - 32px)'
    ].join(';');

    var label = document.createElement('span');
    label.textContent = "You're on the new interface";
    label.style.cssText = 'white-space:nowrap;overflow:hidden;text-overflow:ellipsis';

    var dot = document.createElement('span');
    dot.setAttribute('aria-hidden', 'true');
    dot.textContent = '·';
    dot.style.cssText = 'color:#8c92a0';

    var btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Switch back';
    btn.style.cssText = [
      'background:none', 'border:none', 'padding:0', 'cursor:pointer',
      'font:inherit', 'font-weight:600', 'color:#4364dc', 'text-decoration:underline'
    ].join(';');
    btn.addEventListener('click', function () { switchToClassic(btn); });

    var err = document.createElement('span');
    err.id = BAR_ID + '-err';
    err.hidden = true;
    err.textContent = "Couldn't switch — try again";
    err.style.cssText = 'color:#B11E2E';

    bar.appendChild(label);
    bar.appendChild(dot);
    bar.appendChild(btn);
    bar.appendChild(err);
    document.body.appendChild(bar);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', mount);
  } else {
    mount();
  }
})();
