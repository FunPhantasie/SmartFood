// Gemeinsame Navigationsleiste + User-Auswahl fuer alle Seiten.
// Wird per <script src="/static/nav.js"></script> eingebunden (Flask liefert
// den Server-Ordner unter /static/ aus, siehe static_folder in smartfood_server.py).
(function () {
  const USERS_ENDPOINT = '/api/users';
  const STORAGE_KEY = 'smartfood_user';

  function getUserFromUrl() {
    return new URLSearchParams(window.location.search).get('user');
  }

  function getCurrentUserId() {
    const fromUrl = getUserFromUrl();
    if (fromUrl) {
      try { localStorage.setItem(STORAGE_KEY, fromUrl); } catch (e) {}
      return fromUrl;
    }
    try { return localStorage.getItem(STORAGE_KEY) || ''; } catch (e) { return ''; }
  }

  function setCurrentUserId(id) {
    try { localStorage.setItem(STORAGE_KEY, id); } catch (e) {}
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('user', id); else url.searchParams.delete('user');
    history.replaceState(null, '', url);
  }

  // Von anderen Seiten genutzt, um den aktuellen User bei jeder Navigation
  // als Query-Parameter mitzugeben, z.B. location.href = SmartFoodUser.decorate('/recipe?id=52')
  window.SmartFoodUser = {
    get: getCurrentUserId,
    set: setCurrentUserId,
    decorate(path) {
      const id = getCurrentUserId();
      if (!id) return path;
      const url = new URL(path, window.location.origin);
      url.searchParams.set('user', id);
      return url.pathname + '?' + url.searchParams.toString();
    }
  };

  // Kein eigener Balken, keine "Bubble in der Bubble" - nur Text + Dropdown,
  // eingesetzt in den Platzhalter <span id="sf-user-slot"></span>, den jede
  // Seite selbst an der gewuenschten Stelle neben ihrem Titel platziert.
  async function buildNavbar() {
    const slot = document.getElementById('sf-user-slot');
    if (!slot) return;

    slot.innerHTML = `
      <style>
        #sf-user-slot select{
          background:#121a2a; color:#e9eefc; border:1px solid #2a3a58;
          border-radius:999px; padding:3px 10px; font-size:13px;
        }
      </style>
      <label for="sf-user-select" style="color:#a7b4d6; font-size:13px; font-weight:400;">User:</label>
      <select id="sf-user-select"><option value="">–</option></select>
    `;

    const select = slot.querySelector('#sf-user-select');
    try {
      const res = await fetch(USERS_ENDPOINT);
      const data = await res.json();
      const users = data.users || [];
      for (const u of users) {
        const opt = document.createElement('option');
        opt.value = u.user_id;
        opt.textContent = u.name;
        select.appendChild(opt);
      }
    } catch (e) {
      // Server evtl. nicht erreichbar - Navbar bleibt trotzdem nutzbar
    }

    select.value = getCurrentUserId();
    select.addEventListener('change', () => {
      setCurrentUserId(select.value);
      // history / Bewertungen gehoeren dem User -> Seiten mit User-Daten neu laden
      if (!['/create', '/ingredients'].includes(window.location.pathname)) window.location.reload();
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', buildNavbar);
  } else {
    buildNavbar();
  }
})();
