let websocket = null;
let timerInterval = null;
let seconds = 0;
let activeCall = false;

let audioContext = null;
let mediaStream = null;
let sourceNode = null;
let processorNode = null;

const DEFAULT_SERVICE_NUMBER = "8028";
const TARGET_SAMPLE_RATE = 16000;

let callerId = localStorage.getItem("caller_id");
let callerName = localStorage.getItem("caller_name");
let callerPhone = localStorage.getItem("caller_phone");

const callerForm = document.getElementById("callerForm");
const dialer = document.getElementById("dialer");
const callerInfo = document.getElementById("callerInfo");

const numberDisplay = document.getElementById("numberDisplay");
const statusEl = document.getElementById("status");
const timerEl = document.getElementById("timer");
const sessionInfo = document.getElementById("sessionInfo");

document.addEventListener("DOMContentLoaded", () => {
  if (numberDisplay && !numberDisplay.value) {
    numberDisplay.value = DEFAULT_SERVICE_NUMBER;
  }

  if (callerId && callerName && callerPhone) {
    showDialer();
  } else {
    showCallerForm();
  }
});

function showCallerForm() {
  if (!callerForm || !dialer) return;

  callerForm.classList.remove("hidden");
  dialer.classList.add("hidden");

  callerForm.style.display = "flex";
  dialer.style.display = "none";
}

function showDialer() {
  if (!callerForm || !dialer) return;

  callerForm.classList.add("hidden");
  dialer.classList.remove("hidden");

  callerForm.style.display = "none";
  dialer.style.display = "flex";

  if (callerInfo) {
    callerInfo.innerText = `${callerName} | ${callerPhone}`;
  }

  if (numberDisplay && !numberDisplay.value) {
    numberDisplay.value = DEFAULT_SERVICE_NUMBER;
  }

  setStatus("Idle");
}

async function registerCaller() {
  const fullNameInput = document.getElementById("fullName");
  const phoneNumberInput = document.getElementById("phoneNumber");

  const fullName = fullNameInput ? fullNameInput.value.trim() : "";
  const phoneNumber = phoneNumberInput ? phoneNumberInput.value.trim() : "";

  if (!fullName || !phoneNumber) {
    alert("Please enter full name and phone number.");
    return;
  }

  try {
    const continueButton = document.querySelector(".continue-btn");

    if (continueButton) {
      continueButton.disabled = true;
      continueButton.innerText = "Please wait...";
    }

    const response = await fetch("/api/callers/register", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        full_name: fullName,
        phone_number: phoneNumber
      })
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error("Registration failed:", errorText);
      alert("Failed to register caller.");
      return;
    }

    const data = await response.json();

    if (!data.caller || !data.caller.caller_id) {
      console.error("Unexpected register response:", data);
      alert("Registration response is invalid.");
      return;
    }

    callerId = data.caller.caller_id;
    callerName = data.caller.full_name;
    callerPhone = data.caller.phone_number;

    localStorage.setItem("caller_id", callerId);
    localStorage.setItem("caller_name", callerName);
    localStorage.setItem("caller_phone", callerPhone);

    showDialer();

  } catch (error) {
    console.error("Could not connect to the server:", error);
    alert("Could not connect to the server.");
  } finally {
    const continueButton = document.querySelector(".continue-btn");

    if (continueButton) {
      continueButton.disabled = false;
      continueButton.innerText = "Continue";
    }
  }
}

function clearCaller() {
  if (activeCall) {
    alert("End the current call before changing caller.");
    return;
  }

  localStorage.removeItem("caller_id");
  localStorage.removeItem("caller_name");
  localStorage.removeItem("caller_phone");

  callerId = null;
  callerName = null;
  callerPhone = null;

  const fullNameInput = document.getElementById("fullName");
  const phoneNumberInput = document.getElementById("phoneNumber");

  if (fullNameInput) fullNameInput.value = "";
  if (phoneNumberInput) phoneNumberInput.value = "";

  if (numberDisplay) {
    numberDisplay.value = DEFAULT_SERVICE_NUMBER;
  }

  if (sessionInfo) {
    sessionInfo.innerText = "";
  }

  if (timerEl) {
    timerEl.innerText = "00:00";
  }

  setStatus("Idle");
  showCallerForm();
}

function pressKey(key) {
  if (activeCall || !numberDisplay) return;

  if (numberDisplay.value === DEFAULT_SERVICE_NUMBER) {
    numberDisplay.value = "";
  }

  numberDisplay.value += key;
}

function deleteKey() {
  if (activeCall || !numberDisplay) return;

  numberDisplay.value = numberDisplay.value.slice(0, -1);

  if (!numberDisplay.value) {
    numberDisplay.value = DEFAULT_SERVICE_NUMBER;
  }
}

function setStatus(text) {
  if (statusEl) {
    statusEl.innerText = text;
  }
}

function startTimer() {
  seconds = 0;

  if (timerEl) {
    timerEl.innerText = "00:00";
  }

  stopTimer();

  timerInterval = setInterval(() => {
    seconds++;

    const mins = String(Math.floor(seconds / 60)).padStart(2, "0");
    const secs = String(seconds % 60).padStart(2, "0");

    if (timerEl) {
      timerEl.innerText = `${mins}:${secs}`;
    }
  }, 1000);
}

function stopTimer() {
  if (timerInterval) {
    clearInterval(timerInterval);
    timerInterval = null;
  }
}

async function startCall() {
  const dialedNumber = numberDisplay ? numberDisplay.value.trim() : "";

  if (!callerId) {
    alert("Please register caller first.");
    return;
  }

  if (!dialedNumber) {
    alert("Please dial the service number first.");
    return;
  }

  if (activeCall) {
    return;
  }

  try {
    setStatus("Requesting microphone...");

    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: {
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true
      }
    });

    setStatus("Connecting...");

    const protocol = window.location.protocol === "https:" ? "wss" : "ws";

    const wsUrl =
      `${protocol}://${window.location.host}/ws/call` +
      `?caller_id=${encodeURIComponent(callerId)}` +
      `&audio_format=pcm16` +
      `&sample_rate=${TARGET_SAMPLE_RATE}`;

    websocket = new WebSocket(wsUrl);
    websocket.binaryType = "arraybuffer";

    websocket.onopen = async () => {
      setStatus("In call");
      activeCall = true;
      startTimer();

      await startPCMStreaming(mediaStream);
    };

    websocket.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);

        if (data.type === "session_started") {
          if (sessionInfo) {
            sessionInfo.innerText = `Session: ${data.session_id}`;
          }
        }

        if (data.event === "speech_started") {
          setStatus("Speaking...");
        }

        if (data.event === "speech_ended") {
          setStatus("Listening...");
        }

        if (data.type === "session_ended") {
          if (sessionInfo) {
            sessionInfo.innerText = "Call ended.";
          }
        }

      } catch (err) {
        console.log("Message:", event.data);
      }
    };

    websocket.onerror = (error) => {
      console.error("WebSocket error:", error);
      setStatus("Connection error");
    };

    websocket.onclose = (event) => {
      console.log("WebSocket closed:", event.code, event.reason);

      cleanupAudio();

      setStatus("Ended");
      activeCall = false;
      stopTimer();
    };

  } catch (error) {
    console.error("Microphone error:", error);
    setStatus("Microphone error");
    alert("Could not access microphone. Please allow microphone permission.");
  }
}

async function startPCMStreaming(stream) {
  audioContext = new AudioContext();

  sourceNode = audioContext.createMediaStreamSource(stream);

  const bufferSize = 4096;
  processorNode = audioContext.createScriptProcessor(bufferSize, 1, 1);

  processorNode.onaudioprocess = (event) => {
    if (!activeCall || !websocket || websocket.readyState !== WebSocket.OPEN) {
      return;
    }

    const inputBuffer = event.inputBuffer.getChannelData(0);

    const downsampled = downsampleBuffer(
      inputBuffer,
      audioContext.sampleRate,
      TARGET_SAMPLE_RATE
    );

    const pcm16 = float32ToPCM16(downsampled);

    websocket.send(pcm16.buffer);
  };

  sourceNode.connect(processorNode);
  processorNode.connect(audioContext.destination);
}

function downsampleBuffer(buffer, inputSampleRate, outputSampleRate) {
  if (outputSampleRate === inputSampleRate) {
    return buffer;
  }

  if (outputSampleRate > inputSampleRate) {
    throw new Error("Output sample rate must be lower than input sample rate.");
  }

  const sampleRateRatio = inputSampleRate / outputSampleRate;
  const newLength = Math.round(buffer.length / sampleRateRatio);
  const result = new Float32Array(newLength);

  let offsetResult = 0;
  let offsetBuffer = 0;

  while (offsetResult < result.length) {
    const nextOffsetBuffer = Math.round((offsetResult + 1) * sampleRateRatio);

    let accum = 0;
    let count = 0;

    for (let i = offsetBuffer; i < nextOffsetBuffer && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }

    result[offsetResult] = count > 0 ? accum / count : 0;

    offsetResult++;
    offsetBuffer = nextOffsetBuffer;
  }

  return result;
}

function float32ToPCM16(float32Array) {
  const pcm16 = new Int16Array(float32Array.length);

  for (let i = 0; i < float32Array.length; i++) {
    let sample = Math.max(-1, Math.min(1, float32Array[i]));

    if (sample < 0) {
      pcm16[i] = sample * 0x8000;
    } else {
      pcm16[i] = sample * 0x7fff;
    }
  }

  return pcm16;
}

function endCall() {
  if (!activeCall) return;

  setStatus("Ending call...");

  activeCall = false;
  stopTimer();

  if (websocket && websocket.readyState === WebSocket.OPEN) {
    websocket.send("END_CALL");

    setTimeout(() => {
      websocket.close();
    }, 300);
  }

  cleanupAudio();
}

function cleanupAudio() {
  if (processorNode) {
    try {
      processorNode.disconnect();
    } catch (e) {}
    processorNode = null;
  }

  if (sourceNode) {
    try {
      sourceNode.disconnect();
    } catch (e) {}
    sourceNode = null;
  }

  if (audioContext) {
    try {
      audioContext.close();
    } catch (e) {}
    audioContext = null;
  }

  if (mediaStream) {
    mediaStream.getTracks().forEach(track => track.stop());
    mediaStream = null;
  }
}