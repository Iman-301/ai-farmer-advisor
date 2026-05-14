/**
 * pages/kb.js — Knowledge Base: list, search, add, delete entries.
 * Depends on: state.js (_kbAll), api.js, utils.js (toast, emptyRow), router.js (PAGE_LOADERS)
 */

PAGE_LOADERS['kb'] = loadKB;

async function loadKB() {
  const data = await api('GET', '/admin/kb');
  if (!data) return;

  _kbAll = data;
  document.getElementById('kb-count').textContent = data.length;
  renderKB(data);
}

function renderKB(list) {
  const tbody = document.getElementById('kb-body');
  if (!list.length) {
    tbody.innerHTML = emptyRow(4, '📚', 'No knowledge base entries yet.');
    return;
  }

  tbody.innerHTML = list.map(e => `
    <tr>
      <td><span class="badge bg-blue">${e.intent || '—'}</span></td>
      <td style="max-width:340px;color:var(--t2)">${(e.response || '').substring(0, 80)}${e.response && e.response.length > 80 ? '…' : ''}</td>
      <td><code style="font-size:11px;color:var(--t3)">${(e.id || '').substring(0, 12)}…</code></td>
      <td>
        <button class="btn btn-sm bsm-red" onclick="deleteKBEntry('${e.id}')">🗑 Delete</button>
      </td>
    </tr>
  `).join('');
}

function filterKB() {
  const q = document.getElementById('kb-search').value.toLowerCase();
  const filtered = _kbAll.filter(e =>
    (e.intent   || '').toLowerCase().includes(q) ||
    (e.response || '').toLowerCase().includes(q)
  );
  renderKB(filtered);
}

async function addKB(e) {
  e.preventDefault();
  const intent   = document.getElementById('kb-intent').value.trim();
  const response = document.getElementById('kb-response').value.trim();
  if (!intent || !response) return;

  const res = await api('POST', '/admin/kb', { intent, response });
  if (!res) return;

  toast('KB entry added ✔', 'ok');
  document.getElementById('kb-form').reset();
  loadKB();
}

async function deleteKBEntry(id) {
  if (!confirm('Delete this KB entry?')) return;
  const res = await api('DELETE', `/admin/kb/${encodeURIComponent(id)}`);
  if (!res) return;
  toast('Entry deleted', 'ok');
  loadKB();
}
