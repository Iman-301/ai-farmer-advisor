/**
 * pages/alerts.js — Alerts & Forecasts: broadcast form + history table + region chart.
 * Depends on: api.js, utils.js (toast, emptyRow, fmt, mkChart), router.js (PAGE_LOADERS)
 */

PAGE_LOADERS['alerts'] = loadAlerts;

async function loadAlerts() {
  const data = await api('GET', '/admin/alerts');
  if (!data) return;

  // ── Recent alerts table ────────────────────────────────────────────────────
  const tbody = document.getElementById('alerts-body');
  if (!data.length) {
    tbody.innerHTML = emptyRow(4, '📡', 'No alerts broadcast yet.');
  } else {
    tbody.innerHTML = data.map(a => {
      const sevBadge = {
        info:     '<span class="badge bg-blue">ℹ️ Info</span>',
        warning:  '<span class="badge bg-gold">⚠️ Warning</span>',
        critical: '<span class="badge bg-red">🔴 Critical</span>',
      }[a.severity] || `<span class="badge bg-gray">${a.severity}</span>`;

      return `
        <tr>
          <td>${a.target_region || 'All'}</td>
          <td style="max-width:280px;color:var(--t2)">${(a.alert_message || '').substring(0, 80)}${(a.alert_message || '').length > 80 ? '…' : ''}</td>
          <td>${sevBadge}</td>
          <td style="color:var(--t2)">${fmt(a.created_at)}</td>
        </tr>
      `;
    }).join('');
  }

  // ── Alerts-by-region chart ─────────────────────────────────────────────────
  const regionCounts = {};
  data.forEach(a => {
    const key = a.target_region || 'All';
    regionCounts[key] = (regionCounts[key] || 0) + 1;
  });

  const regionLabels = Object.keys(regionCounts);
  const regionValues = regionLabels.map(k => regionCounts[k]);
  const palette = [
    'rgba(34,197,94,.7)', 'rgba(59,130,246,.7)', 'rgba(245,158,11,.7)',
    'rgba(239,68,68,.7)', 'rgba(168,85,247,.7)', 'rgba(20,184,166,.7)',
    'rgba(251,191,36,.7)', 'rgba(99,102,241,.7)',
  ];

  mkChart('chart-alerts', 'bar', regionLabels, [{
    label:           'Alerts',
    data:            regionValues,
    backgroundColor: regionLabels.map((_, i) => palette[i % palette.length]),
    borderRadius:    5,
    borderWidth:     0,
  }], {
    indexAxis: 'y',
  });
}

async function addAlert(e) {
  e.preventDefault();
  const target_region  = document.getElementById('al-region').value;
  const alert_message  = document.getElementById('al-msg').value.trim();
  const severity       = document.getElementById('al-sev').value;

  if (!alert_message) return;

  const res = await api('POST', '/admin/alerts', { target_region, alert_message, severity });
  if (!res) return;

  toast('Alert broadcast ✔', 'ok');
  document.getElementById('alert-form').reset();
  loadAlerts();
}
