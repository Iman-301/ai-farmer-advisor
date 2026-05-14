/**
 * pages/dashboard.js — Dashboard stats + charts.
 * Depends on: state.js, api.js, utils.js (mkChart, fmt), router.js (PAGE_LOADERS)
 */

PAGE_LOADERS['dashboard'] = loadDashboard;

async function loadDashboard() {
  const data = await api('GET', '/admin/stats');
  if (!data) return;

  // Stat cards
  document.getElementById('s-farmers').textContent = data.total_farmers   ?? '—';
  document.getElementById('s-calls').textContent   = data.calls_today     ?? '—';
  document.getElementById('s-esc').textContent     = data.pending_escalations ?? '—';
  document.getElementById('s-alerts').textContent  = data.total_alerts    ?? '—';
  document.getElementById('s-kb').textContent      = data.kb_count        ?? '—';

  // Escalation badge in sidebar
  const badge = document.getElementById('esc-badge');
  const pend  = data.pending_escalations || 0;
  badge.textContent    = pend;
  badge.style.display  = pend > 0 ? 'inline-block' : 'none';

  // ── Chart: Calls last 7 days ───────────────────────────────────────────────
  const days    = data.calls_per_day || [];
  const dayLabels = days.map(d => {
    const dt = new Date(d.date);
    return dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  });
  const dayCounts = days.map(d => d.count);

  mkChart('chart-calls', 'bar', dayLabels, [{
    label:           'Calls',
    data:            dayCounts,
    backgroundColor: 'rgba(59,130,246,.55)',
    borderColor:     'rgba(59,130,246,.9)',
    borderWidth:     1,
    borderRadius:    5,
  }]);

  // ── Chart: Escalation status breakdown ────────────────────────────────────
  const esc     = data.escalation_breakdown || {};
  const escKeys = Object.keys(esc);
  const escVals = escKeys.map(k => esc[k]);
  const escColors = {
    pending:  'rgba(245,158,11,.75)',
    resolved: 'rgba(34,197,94,.75)',
    escalated:'rgba(239,68,68,.75)',
  };
  const colors = escKeys.map(k => escColors[k] || 'rgba(148,163,184,.5)');

  mkChart('chart-esc', 'doughnut', escKeys, [{
    data:            escVals,
    backgroundColor: colors,
    borderWidth:     0,
    hoverOffset:     6,
  }], {
    plugins: { legend: { position: 'bottom', labels: { color: '#94a3b8', boxWidth: 12, font: { size: 11 } } } },
  });
}
