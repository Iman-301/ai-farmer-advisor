/**
 * pages/market.js — Market Prices: list + add new price entry.
 * Depends on: api.js, utils.js (toast, emptyRow, fmt), router.js (PAGE_LOADERS)
 */

PAGE_LOADERS['market'] = loadMarket;

async function loadMarket() {
  const data = await api('GET', '/admin/market-prices');
  if (!data) return;

  const tbody = document.getElementById('market-body');
  if (!data.length) {
    tbody.innerHTML = emptyRow(5, '💰', 'No market prices recorded yet.');
    return;
  }

  tbody.innerHTML = data.map(p => `
    <tr>
      <td><strong>${p.crop_name || '—'}</strong></td>
      <td>${p.region || '—'}</td>
      <td style="color:var(--gold);font-weight:700">${
        p.price != null ? Number(p.price).toLocaleString('en-ET', { minimumFractionDigits: 2 }) : '—'
      } ETB</td>
      <td><span class="badge bg-gray">${p.unit || '—'}</span></td>
      <td style="color:var(--t2)">${fmt(p.updated_at)}</td>
    </tr>
  `).join('');
}

async function addPrice(e) {
  e.preventDefault();
  const crop   = document.getElementById('mp-crop').value.trim();
  const region = document.getElementById('mp-region').value.trim();
  const price  = parseFloat(document.getElementById('mp-price').value);
  const unit   = document.getElementById('mp-unit').value.trim();

  if (!crop || !region || isNaN(price) || !unit) return;

  const res = await api('POST', '/admin/market-prices', {
    crop_name: crop, region, price, unit,
  });
  if (!res) return;

  toast('Price entry added ✔', 'ok');
  document.getElementById('market-form').reset();
  loadMarket();
}
