/**
 * pages/escalations.js — Expert escalation queue with resolve action.
 * Depends on: api.js, utils.js (fmt, emptyRow, toast), router.js (PAGE_LOADERS)
 */

PAGE_LOADERS['escalations'] = loadEscalations;

async function loadEscalations() {
  const data = await api('GET', '/admin/escalations');
  if (!data) return;

  const tbody = document.getElementById('esc-body');
  if (!data.length) {
    tbody.innerHTML = emptyRow(6, '🚨', 'No escalations in the queue.');
    return;
  }

  tbody.innerHTML = data.map(e => {
    const statusBadge = {
      pending:  '<span class="badge bg-gold">⏳ Pending</span>',
      resolved: '<span class="badge bg-green">✅ Resolved</span>',
      escalated:'<span class="badge bg-red">🔴 Escalated</span>',
    }[e.status] || `<span class="badge bg-gray">${e.status}</span>`;

    const actionBtn = e.status !== 'resolved'
      ? `<button class="btn btn-sm bsm-green" onclick="resolveTicket(${e.id})">✔ Resolve</button>`
      : '<span style="color:var(--t3)">—</span>';

    const context = e.context
      ? `<span style="font-size:11px;color:var(--t3)">${String(e.context).substring(0, 60)}…</span>`
      : '<span style="color:var(--t3)">—</span>';

    return `
      <tr>
        <td style="color:var(--t3)">#${e.id}</td>
        <td style="max-width:260px">${e.query || '—'}</td>
        <td>${context}</td>
        <td>${statusBadge}</td>
        <td style="color:var(--t2)">${fmt(e.timestamp)}</td>
        <td>${actionBtn}</td>
      </tr>
    `;
  }).join('');
}

async function resolveTicket(id) {
  const res = await api('PUT', `/admin/escalations/${id}/resolve`);
  if (!res) return;
  toast('Ticket #' + id + ' resolved ✔', 'ok');
  loadEscalations();

  // Refresh sidebar badge if on another page
  const statsData = await api('GET', '/admin/stats');
  if (statsData) {
    const badge = document.getElementById('esc-badge');
    const pend  = statsData.pending_escalations || 0;
    badge.textContent   = pend;
    badge.style.display = pend > 0 ? 'inline-block' : 'none';
  }
}
