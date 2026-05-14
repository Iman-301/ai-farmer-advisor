/**
 * api.js — Core API helper, auth (logout / showApp).
 * Depends on: state.js, utils.js (toast), router.js (nav)
 */

const API_BASE = '/api';

// ── Core fetch wrapper ────────────────────────────────────────────────────
async function api(method, path, body) {
  const headers = { 'Content-Type': 'application/json' };
  if (S.token) headers['Authorization'] = 'Bearer ' + S.token;

  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (res.status === 401) {
    // Session expired — force logout
    logout();
    return null;
  }
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    toast(err.detail || `Error ${res.status}`, 'err');
    return null;
  }
  return res.json();
}

// ── Auth helpers ──────────────────────────────────────────────────────────
function logout() {
  api('POST', '/admin/logout');                              // fire-and-forget
  ['fa_tok', 'fa_role', 'fa_user'].forEach(k => localStorage.removeItem(k));
  S.token = S.role = S.username = null;
  document.getElementById('login-page').style.display = 'flex';
  document.getElementById('app').style.display = 'none';
}

function showApp() {
  document.getElementById('login-page').style.display = 'none';
  document.getElementById('app').style.display = 'flex';
  document.getElementById('uav').textContent   = (S.username || 'A')[0].toUpperCase();
  document.getElementById('uname').textContent = S.username || 'Admin';
  document.getElementById('urole').textContent = S.role     || 'admin';
  startClock();
  nav('dashboard');
}
