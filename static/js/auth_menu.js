/* Auth menu — small header affordance showing logged-in name + role + Sign out.
 *
 * Renders into a host element with id="user-menu". Fetches /api/auth/me; on
 * success populates the host with name/role + Sign out. On failure the
 * before_request gate has already redirected the page to /login, so the
 * fetch failing here is only seen during a stale-cookie race — we redirect
 * defensively.
 *
 * Shared by company-dashboard.html and dashboard-static.html. Worker app
 * does NOT include this file — workers use the PIN flow and have no
 * "user" entity here.
 */
(function () {
  'use strict';

  // Role labels for display. Server-side role values are short codes; the
  // UI shows a human form so the operator doesn't see "c_suite" in the chrome.
  var ROLE_LABEL = {
    admin: 'Admin',
    c_suite: 'C-Suite',
    pm: 'PM',
    super: 'Super'
  };

  function $(id) { return document.getElementById(id); }

  // #291 — instant-paint boot cache (sessionStorage). Pages render their last
  // bootstrap payload in ~0ms on back-navigation, then refresh in place.
  // Session-scoped (dies with the tab), purged on Sign out (guard-asserted)
  // and on any cached-uid/live-uid mismatch (shared-device belt-and-braces).
  window.SSC_BOOT = {
    _key: function (page) { return 'ssc.boot.' + page; },
    read: function (page) {
      try {
        var j = JSON.parse(sessionStorage.getItem(this._key(page)) || 'null');
        return (j && j.bd) ? j : null;
      } catch (e) { return null; }
    },
    write: function (page, bd) {
      try {
        var uid = (window.__SSC_USER && window.__SSC_USER.id) || null;
        sessionStorage.setItem(this._key(page),
          JSON.stringify({ bd: bd, uid: uid, at: Date.now() }));
      } catch (e) { /* quota/serialization — cache is optional */ }
    },
    purge: function () {
      try {
        var ks = [];
        for (var i = 0; i < sessionStorage.length; i++) {
          var k = sessionStorage.key(i);
          if (k && k.indexOf('ssc.boot.') === 0) ks.push(k);
        }
        ks.forEach(function (k) { sessionStorage.removeItem(k); });
      } catch (e) { }
    },
    guardUser: function (user) {
      // purge every cached page whose writer wasn't THIS user
      try {
        for (var i = sessionStorage.length - 1; i >= 0; i--) {
          var k = sessionStorage.key(i);
          if (!k || k.indexOf('ssc.boot.') !== 0) continue;
          var j = JSON.parse(sessionStorage.getItem(k) || 'null');
          if (j && j.uid != null && user && j.uid !== user.id) sessionStorage.removeItem(k);
        }
      } catch (e) { }
    }
  };

  function escapeHtml(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function injectStyles() {
    if ($('auth-menu-styles')) return;
    var style = document.createElement('style');
    style.id = 'auth-menu-styles';
    style.textContent = [
      '.auth-menu { display: inline-flex; align-items: center; gap: 10px; font-size: 12px; color: #14161C; }',
      '.auth-menu .au-name { font-weight: 600; }',
      '.auth-menu .au-role {',
      '  font-size: 10px; font-weight: 700; letter-spacing: 0.8px; text-transform: uppercase;',
      '  color: #76777E; background: #F1ECE2; padding: 3px 8px; border-radius: 99px;',
      '}',
      '.auth-menu .au-logout {',
      '  font: inherit; font-size: 11px; font-weight: 600; color: #76777E;',
      '  background: transparent; border: 1px solid #E8E4DD; border-radius: 6px;',
      '  padding: 4px 10px; cursor: pointer; transition: color .15s, border-color .15s;',
      '}',
      '.auth-menu .au-logout:hover { color: #B11E2E; border-color: #B11E2E; }',
      '.auth-menu .au-logout:disabled { opacity: 0.6; cursor: not-allowed; }',
      '.auth-menu .au-users {',
      '  font: inherit; font-size: 11px; font-weight: 700; color: #B11E2E;',
      '  text-decoration: none; border: 1px solid #E8E4DD; border-radius: 6px;',
      '  padding: 4px 10px; transition: border-color .15s;',
      '}',
      '.auth-menu .au-users:hover { border-color: #B11E2E; }'
    ].join('\n');
    document.head.appendChild(style);
  }

  function render(host, user) {
    var role = ROLE_LABEL[user.role] || user.role || '—';
    // #258 — admin-only entry point to the user-management console. Visible only to
    // role=admin; /admin/users is gated server-side (this link is UX, not the authority).
    var adminLink = (user.role === 'admin')
      ? '<a class="au-users" href="/admin/users" title="User management">Users</a>' : '';
    host.innerHTML =
      '<div class="auth-menu" data-user-id="' + escapeHtml(user.id) + '">' +
        '<span class="au-name">' + escapeHtml(user.full_name || user.email) + '</span>' +
        '<span class="au-role">' + escapeHtml(role) + '</span>' +
        adminLink +
        '<button type="button" class="au-logout" aria-label="Sign out">Sign out</button>' +
      '</div>';
    var btn = host.querySelector('.au-logout');
    btn.addEventListener('click', function () {
      btn.disabled = true;
      btn.textContent = 'Signing out…';
      // #291 — the boot cache dies WITH the session, before the network call
      // (logout must clear it even if the logout request itself fails)
      if (window.SSC_BOOT) window.SSC_BOOT.purge();
      fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Accept': 'application/json' }
      }).then(function () {
        window.location.href = '/login';
      }).catch(function () {
        // Even on network failure, the user wanted to log out — kick them.
        window.location.href = '/login';
      });
    });
  }

  function load() {
    var host = $('user-menu');
    if (!host) return;
    injectStyles();
    fetch('/api/auth/me', {
      credentials: 'same-origin',
      headers: { 'Accept': 'application/json' }
    }).then(function (res) {
      if (!res.ok) {
        if (res.status === 401) {
          window.location.href = '/login';
          return null;
        }
        throw new Error('me failed: ' + res.status);
      }
      return res.json();
    }).then(function (body) {
      if (body && body.user) {
        // Expose for other client code that needs to know the role (e.g. to
        // hide controls a non-admin shouldn't see). The server-side gating
        // remains the real authority — this is UX, not security.
        window.__SSC_USER = body.user;
        if (window.SSC_BOOT) window.SSC_BOOT.guardUser(body.user);  // #291
        render(host, body.user);
        document.dispatchEvent(new CustomEvent('ssc:user-loaded', { detail: body.user }));
      }
    }).catch(function () {
      // Quietly leave the placeholder; logging the URL would risk leaking
      // session info via a CORS-blocked console message.
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', load);
  } else {
    load();
  }
})();
