/**
 * router.js — Client-side page router.
 * Exposes: nav(page)
 * Depends on: state.js, page loader functions defined in pages/*.js
 */

const PAGE_TITLES = {
  dashboard:   'Dashboard',
  farmers:     'Farmers',
  calls:       'Call Logs',
  escalations: 'Escalations',
  kb:          'Knowledge Base',
  market:      'Market Prices',
  alerts:      'Alerts & Forecasts',
};

// Page-loader registry — each pages/*.js registers itself here
const PAGE_LOADERS = {};

function nav(page) {
  // Hide all pages, deactivate all nav items
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  // Show target page + mark nav item active
  const pageEl = document.getElementById('page-' + page);
  if (pageEl) pageEl.classList.add('active');

  const navEl = document.getElementById('nav-' + page);
  if (navEl) navEl.classList.add('active');

  // Update topbar title
  document.getElementById('pg-title').textContent = PAGE_TITLES[page] || page;

  // Call the registered page loader if it exists
  if (PAGE_LOADERS[page]) PAGE_LOADERS[page]();
}
