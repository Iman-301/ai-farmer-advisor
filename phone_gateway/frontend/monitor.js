const POLL_MS = 800;

const els = {
  systemStatus: document.getElementById("systemStatus"),
  lastUpdated: document.getElementById("lastUpdated"),
  voiceRing: document.getElementById("voiceRing"),
  callStateText: document.getElementById("callStateText"),
  waveform: document.getElementById("waveform"),
  audioLevelValue: document.getElementById("audioLevelValue"),

  sessionId: document.getElementById("sessionId"),
  callerName: document.getElementById("callerName"),
  callerPhone: document.getElementById("callerPhone"),
  callStatus: document.getElementById("callStatus"),
  audioFormat: document.getElementById("audioFormat"),
  sampleRate: document.getElementById("sampleRate"),

  audioChunks: document.getElementById("audioChunks"),
  audioBytes: document.getElementById("audioBytes"),
  vadStatus: document.getElementById("vadStatus"),
  utteranceCount: document.getElementById("utteranceCount"),

  utteranceList: document.getElementById("utteranceList"),
  eventLog: document.getElementById("eventLog"),
  recentCalls: document.getElementById("recentCalls"),

  stepGateway: document.getElementById("stepGateway"),
  stepAudio: document.getElementById("stepAudio"),
  stepVad: document.getElementById("stepVad"),
  stepUtterance: document.getElementById("stepUtterance"),
};

function formatBytes(bytes) {
  if (!bytes) return "0 KB";

  if (bytes < 1024 * 1024) {
    return `${Math.round(bytes / 1024)} KB`;
  }

  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

function safeText(value, fallback = "—") {
  if (value === null || value === undefined || value === "") {
    return fallback;
  }

  return String(value);
}

function setStep(el, active, text) {
  if (!el) return;

  if (active) {
    el.classList.add("active");
  } else {
    el.classList.remove("active");
  }

  const span = el.querySelector("span");
  if (span) {
    span.innerText = text;
  }
}

function setSystemStatus(text, mode) {
  if (!els.systemStatus) return;

  els.systemStatus.innerText = text;
  els.systemStatus.className = `status-badge ${mode}`;
}

function setVoiceRing(mode) {
  if (!els.voiceRing) return;

  els.voiceRing.className = "voice-ring";

  if (mode) {
    els.voiceRing.classList.add(mode);
  }
}

function renderWaveform(levels, currentLevel = 0) {
  if (!els.waveform) return;

  const bars = Array.from(els.waveform.querySelectorAll(".wave-bar"));

  if (!bars.length) return;

  const sourceLevels = Array.isArray(levels) && levels.length
    ? levels.slice(-bars.length)
    : [];

  while (sourceLevels.length < bars.length) {
    sourceLevels.unshift(0);
  }

  bars.forEach((bar, index) => {
    const level = sourceLevels[index] || 0;

    const minHeight = 8;
    const maxHeight = 86;
    const height = minHeight + level * maxHeight;

    bar.style.height = `${height}px`;

    if (level > 0.55) {
      bar.classList.add("hot");
    } else {
      bar.classList.remove("hot");
    }
  });

  if (els.audioLevelValue) {
    els.audioLevelValue.innerText = `${Math.round((currentLevel || 0) * 100)}%`;
  }
}

function renderNoActiveCall(data) {
  setSystemStatus("No Active Call", "offline");
  setVoiceRing(null);

  if (els.callStateText) {
    els.callStateText.innerText = "Waiting for incoming browser call";
  }

  if (els.sessionId) els.sessionId.innerText = "—";
  if (els.callerName) els.callerName.innerText = "—";
  if (els.callerPhone) els.callerPhone.innerText = "—";
  if (els.callStatus) els.callStatus.innerText = "—";
  if (els.audioFormat) els.audioFormat.innerText = "—";
  if (els.sampleRate) els.sampleRate.innerText = "—";

  if (els.audioChunks) els.audioChunks.innerText = "0";
  if (els.audioBytes) els.audioBytes.innerText = "0 KB";
  if (els.vadStatus) els.vadStatus.innerText = "Waiting";
  if (els.utteranceCount) els.utteranceCount.innerText = "0";

  setStep(els.stepGateway, false, "Waiting");
  setStep(els.stepAudio, false, "No audio");
  setStep(els.stepVad, false, "Waiting");
  setStep(els.stepUtterance, false, "None");

  renderWaveform([], 0);

  if (els.utteranceList) {
    els.utteranceList.innerHTML = `
      <div class="empty">No active utterance detected.</div>
    `;
  }
}

function renderActiveCall(call) {
  const vadStatus = call.vad_status || "waiting";
  const audioChunks = call.audio_chunks || 0;
  const audioBytes = call.audio_bytes || 0;
  const utteranceCount = call.utterance_count || 0;

  if (call.status === "ended") {
    setSystemStatus("Call Ended", "ended");
    setVoiceRing(null);

    if (els.callStateText) {
      els.callStateText.innerText = "Call ended. Waiting for next call.";
    }

  } else if (vadStatus === "speech_started") {
    setSystemStatus("Voice Detected", "speaking");
    setVoiceRing("speaking");

    if (els.callStateText) {
      els.callStateText.innerText = "Caller voice is reaching the AI system";
    }

  } else if (vadStatus === "speech_ended") {
    setSystemStatus("Speech Segment Saved", "listening");
    setVoiceRing("listening");

    if (els.callStateText) {
      els.callStateText.innerText = "Speech segment saved. Listening for the next utterance.";
    }

  } else if (audioChunks > 0) {
    setSystemStatus("Listening", "listening");
    setVoiceRing("listening");

    if (els.callStateText) {
      els.callStateText.innerText = "Audio stream is live; waiting for speech";
    }

  } else {
    setSystemStatus("Connected", "online");
    setVoiceRing("connected");

    if (els.callStateText) {
      els.callStateText.innerText = "Call connected; waiting for microphone audio";
    }
  }

  if (els.sessionId) els.sessionId.innerText = safeText(call.session_id);
  if (els.callerName) els.callerName.innerText = safeText(call.caller_name, "Unknown");
  if (els.callerPhone) els.callerPhone.innerText = safeText(call.caller_phone, "Unknown");
  if (els.callStatus) els.callStatus.innerText = safeText(call.status);
  if (els.audioFormat) els.audioFormat.innerText = safeText(call.audio_format);
  if (els.sampleRate) els.sampleRate.innerText = call.sample_rate ? `${call.sample_rate} Hz` : "—";

  if (els.audioChunks) els.audioChunks.innerText = String(audioChunks);
  if (els.audioBytes) els.audioBytes.innerText = formatBytes(audioBytes);
  if (els.vadStatus) els.vadStatus.innerText = safeText(vadStatus, "Waiting");
  if (els.utteranceCount) els.utteranceCount.innerText = String(utteranceCount);

  setStep(els.stepGateway, true, "Session active");

  setStep(
    els.stepAudio,
    audioChunks > 0,
    audioChunks > 0 ? "PCM16 streaming" : "Waiting"
  );

  setStep(
    els.stepVad,
    vadStatus !== "waiting",
    vadStatus
  );

  setStep(
    els.stepUtterance,
    utteranceCount > 0,
    utteranceCount > 0 ? "Saved" : "None"
  );

  renderUtterances(call.utterances || []);
  renderWaveform(call.waveform || [], call.audio_level || 0);
}

function renderUtterances(utterances) {
  if (!els.utteranceList) return;

  if (!utterances || !utterances.length) {
    els.utteranceList.innerHTML = `
      <div class="empty">No utterance detected yet.</div>
    `;
    return;
  }

  els.utteranceList.innerHTML = utterances.map((u) => {
    const index = safeText(u.index, "?");
    const duration = u.duration_seconds ?? "unknown";
    const probability = u.speech_probability ?? "—";
    const path = safeText(u.utterance_path, "No path");

    return `
      <div class="utterance-item">
        <strong>Utterance ${index}</strong>
        <span>Duration: ${duration} sec</span>
        <span>Probability: ${probability}</span>
        <small>${path}</small>
      </div>
    `;
  }).join("");
}

function renderEvents(events) {
  if (!els.eventLog) return;

  if (!events || !events.length) {
    els.eventLog.innerHTML = `
      <div class="empty">No backend events yet.</div>
    `;
    return;
  }

  els.eventLog.innerHTML = events.slice(0, 80).map((event) => {
    const time = event.time ? new Date(event.time).toLocaleTimeString() : "—";
    const eventType = safeText(event.event_type, "event");
    const payload = event.payload ? JSON.stringify(event.payload) : "";

    return `
      <div class="event-line">
        <span class="time">[${time}]</span>
        <span class="event">${eventType}</span>
        <span class="payload">${payload}</span>
      </div>
    `;
  }).join("");
}

function renderRecentCalls(calls) {
  if (!els.recentCalls) return;

  if (!calls || !calls.length) {
    els.recentCalls.innerHTML = `
      <div class="empty">No completed calls yet.</div>
    `;
    return;
  }

  els.recentCalls.innerHTML = calls.map((call) => {
    const caller = safeText(call.caller_name, "Unknown Caller");
    const phone = safeText(call.caller_phone, "No phone");
    const utterances = call.utterance_count || 0;
    const session = safeText(call.session_id, "No session");

    return `
      <div class="recent-call">
        <strong>${caller}</strong>
        <span>${phone} | ${utterances} utterances</span>
        <small>${session}</small>
      </div>
    `;
  }).join("");
}

async function loadMonitor() {
  try {
    const response = await fetch("/api/monitor/state", {
      cache: "no-store"
    });

    if (!response.ok) {
      throw new Error(`Monitor API failed: ${response.status}`);
    }

    const data = await response.json();

    if (els.lastUpdated) {
      els.lastUpdated.innerText = new Date().toLocaleTimeString();
    }

    if (data.active_call) {
      renderActiveCall(data.active_call);
    } else {
      renderNoActiveCall(data);
    }

    renderEvents(data.events || []);
    renderRecentCalls(data.recent_calls || []);

  } catch (error) {
    console.error(error);

    setSystemStatus("Monitor Error", "ended");

    if (els.callStateText) {
      els.callStateText.innerText = "Could not fetch backend monitor state.";
    }

    if (els.eventLog) {
      els.eventLog.innerHTML = `
        <div class="event-line">
          <span class="event">monitor_error</span>
          <span class="payload">${error.message}</span>
        </div>
      `;
    }
  }
}

window.loadMonitor = loadMonitor;

loadMonitor();
setInterval(loadMonitor, POLL_MS);