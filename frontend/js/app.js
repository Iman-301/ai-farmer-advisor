/**
 * app.js — Application boot: DOMContentLoaded + login handler.
 * Loaded last; all other modules must already be in scope.
 * Depends on: state.js, api.js (showApp, api), router.js (nav)
 */

document.addEventListener('DOMContentLoaded', () => {

  // ── Auto-restore session ──────────────────────────────────────────────────
  if (S.token) {
    showApp();
  }

  // ── Login form handler ────────────────────────────────────────────────────
  document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();

    const username = document.getElementById('lu').value.trim();
    const password = document.getElementById('lp').value;
    const errEl    = document.getElementById('lerr');
    const btn      = e.target.querySelector('button[type="submit"]');

    errEl.style.display = 'none';
    btn.textContent     = 'Signing in…';
    btn.disabled        = true;

    try {
      const res = await fetch('/api/admin/login', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ username, password }),
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        errEl.textContent   = body.detail || 'Login failed. Check your credentials.';
        errEl.style.display = 'block';
        return;
      }

      const data = await res.json();
      // Persist session
      localStorage.setItem('fa_tok',  data.token);
      localStorage.setItem('fa_role', data.role);
      localStorage.setItem('fa_user', data.username);
      S.token    = data.token;
      S.role     = data.role;
      S.username = data.username;

      showApp();
    } catch (err) {
      errEl.textContent   = 'Network error — is the server running?';
      errEl.style.display = 'block';
    } finally {
      btn.textContent = 'Sign In';
      btn.disabled    = false;
    }
  });

});
