/**
 * pages/farmers.js — Farmer list with client-side search filter.
 * Depends on: state.js (_farmersAll), api.js, utils.js (fmt, emptyRow), router.js (PAGE_LOADERS)
 */

PAGE_LOADERS['farmers'] = loadFarmers;

async function loadFarmers() {
  const data = await api('GET', '/admin/farmers');
  if (!data) return;

  _farmersAll = data;
  document.getElementById('farmers-count').textContent =
    `${data.length} farmer${data.length !== 1 ? 's' : ''}`;
  renderFarmers(data);
}

function renderFarmers(list) {
  const tbody = document.getElementById('farmers-body');
  if (!list.length) {
    tbody.innerHTML = emptyRow(6, '👨‍🌾', 'No farmers registered yet.');
    return;
  }

  tbody.innerHTML = list.map((f, i) => `
    <tr>
      <td style="color:var(--t3)">${i + 1}</td>
      <td><span class="chip">${f.phone_number || '—'}</span></td>
      <td>${f.name ? `<strong>${f.name}</strong>` : '<span style="color:var(--t3)">—</span>'}</td>
      <td>${f.location || '—'}</td>
      <td><span class="badge bg-blue">${f.language || '—'}</span></td>
      <td style="color:var(--t2)">${fmt(f.registered_at)}</td>
    </tr>
  `).join('');
}

function filterFarmers() {
  const q = document.getElementById('farmer-search').value.toLowerCase();
  const filtered = _farmersAll.filter(f =>
    (f.name          || '').toLowerCase().includes(q) ||
    (f.phone_number  || '').toLowerCase().includes(q) ||
    (f.location      || '').toLowerCase().includes(q)
  );
  renderFarmers(filtered);
}
