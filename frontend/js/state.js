/**
 * state.js — Global application state and shared variables.
 * Loaded first; all other modules depend on this.
 */

// ── Session state (persisted in localStorage) ─────────────────────────────
const S = {
  token:    localStorage.getItem('fa_tok'),
  role:     localStorage.getItem('fa_role'),
  username: localStorage.getItem('fa_user'),
};

// ── In-memory page data (used by filter/render functions) ─────────────────
let _farmersAll = [];
let _kbAll      = [];
let _charts     = {};  // keyed by canvas id
