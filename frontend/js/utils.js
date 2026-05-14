/**
 * utils.js — Shared utility functions.
 * toast, startClock, fmt, emptyRow, mkChart, playAudio, closeAudio
 * Depends on: state.js (_charts)
 */

// ── Toast notifications ───────────────────────────────────────────────────
function toast(msg, type = 'ok') {
  const el = document.createElement('div');
  el.className  = 'toast toast-' + type;
  el.textContent = msg;
  document.getElementById('toasts').appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; }, 3500);
  setTimeout(() => el.remove(), 4000);
}

// ── Live clock ────────────────────────────────────────────────────────────
function startClock() {
  const tick = () => {
    document.getElementById('clock').textContent =
      new Date().toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  };
  tick();
  setInterval(tick, 1000);
}

// ── Date formatter ────────────────────────────────────────────────────────
function fmt(s) {
  if (!s) return '—';
  try {
    return new Date(s).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return s;
  }
}

// ── Empty-state table row ─────────────────────────────────────────────────
function emptyRow(cols, icon, msg) {
  return `<tr><td colspan="${cols}"><div class="empty"><div class="empty-ico">${icon}</div><p>${msg}</p></div></td></tr>`;
}

// ── Chart.js factory ──────────────────────────────────────────────────────
function mkChart(id, type, labels, datasets, opts = {}) {
  const ctx = document.getElementById(id);
  if (!ctx) return;
  if (_charts[id]) _charts[id].destroy();
  _charts[id] = new Chart(ctx, {
    type,
    data: { labels, datasets },
    options: {
      responsive:          true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#94a3b8', boxWidth: 12, font: { size: 11 } } },
        ...(opts.plugins || {}),
      },
      scales: (type === 'pie' || type === 'doughnut') ? undefined : {
        x: { grid: { color: 'rgba(255,255,255,.05)' }, ticks: { color: '#64748b', font: { size: 11 } } },
        y: { grid: { color: 'rgba(255,255,255,.05)' }, ticks: { color: '#64748b', font: { size: 11 } }, beginAtZero: true },
      },
      ...opts,
    },
  });
}

// ── Audio modal ───────────────────────────────────────────────────────────
function playAudio(path) {
  document.getElementById('modal-audio').src = path;
  document.getElementById('audio-modal').classList.add('open');
}

function closeAudio() {
  const el = document.getElementById('modal-audio');
  el.pause();
  el.src = '';
  document.getElementById('audio-modal').classList.remove('open');
}
