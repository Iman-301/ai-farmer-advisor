/**
 * pages/calls.js — Call log table with audio playback.
 * Depends on: api.js, utils.js (fmt, emptyRow, playAudio), router.js (PAGE_LOADERS)
 */

PAGE_LOADERS['calls'] = loadCalls;

async function loadCalls() {
  const data = await api('GET', '/admin/calls');
  if (!data) return;

  const tbody = document.getElementById('calls-body');
  if (!data.length) {
    tbody.innerHTML = emptyRow(6, '📞', 'No call records found.');
    return;
  }

  tbody.innerHTML = data.map(c => {
    const dur = c.duration != null
      ? `${Math.floor(c.duration / 60)}m ${c.duration % 60}s`
      : '—';

    const farmerDisplay = c.farmer_name
      ? `<strong>${c.farmer_name}</strong>`
      : `<span style="color:var(--t3)">${c.phone_number || '—'}</span>`;

    const recordingBtn = c.recording_path
      ? `<button class="btn btn-sm bsm-blue" onclick="playAudio('${c.recording_path}')">▶ Play</button>`
      : `<span style="color:var(--t3)">—</span>`;

    return `
      <tr>
        <td><code style="font-size:11px;color:var(--t3)">${(c.session_id || '').substring(0, 8)}…</code></td>
        <td><span class="chip">${c.phone_number || '—'}</span></td>
        <td>${farmerDisplay}</td>
        <td>${dur}</td>
        <td style="color:var(--t2)">${fmt(c.timestamp)}</td>
        <td>${recordingBtn}</td>
      </tr>
    `;
  }).join('');
}
