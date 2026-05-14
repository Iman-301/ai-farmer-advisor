import os
import requests
import time
import wave
import uuid
import logging
import audioop
import threading
from typing import Optional
import numpy as np
from scipy.signal import resample_poly
import webrtcvad
from pyVoIP.VoIP import VoIPPhone, VoIPCall, CallState

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("telephony_service")

# ── Service URLs ─────────────────────────────────────────────────────────────
STT_URL = os.environ.get("STT_URL", "http://stt_service:8000/transcribe")
LOGIC_URL = os.environ.get("LOGIC_URL", "http://logic_service:8000/ask")
REPEAT_URL = os.environ.get("LOGIC_URL", "http://logic_service:8000") + "/repeat"
SAVE_RECORD_URL = os.environ.get("SAVE_RECORD_URL", "http://logic_service:8000/save_call_record")
TTS_URL = os.environ.get("TTS_URL", "http://tts_service:8000/synthesize")

# ── SIP Config ────────────────────────────────────────────────────────────────
# SIP_SERVER = registrar / PBX (REGISTER + INVITE reply destination).
# SIP_BIND  = local UDP bind (often 0.0.0.0 in Docker).
# Legacy: if only SIP_IP is set to a real host (not 0.0.0.0), use it as SIP_SERVER.
_sip_ip_legacy = os.environ.get("SIP_IP", "")
if os.environ.get("SIP_SERVER"):
    SIP_SERVER = os.environ["SIP_SERVER"]
elif _sip_ip_legacy and _sip_ip_legacy not in ("0.0.0.0", "::", "0.0.0.0/0"):
    SIP_SERVER = _sip_ip_legacy
else:
    SIP_SERVER = "127.0.0.1"

SIP_BIND = os.environ.get("SIP_BIND") or (
    _sip_ip_legacy if _sip_ip_legacy in ("0.0.0.0", "::", "0.0.0.0/0") else "0.0.0.0"
)
SIP_PORT = int(os.environ.get("SIP_PORT", 5060))
SIP_USER = os.environ.get("SIP_USER", "advisor")
SIP_PASS = os.environ.get("SIP_PASS", "password")

# ── VAD Config ────────────────────────────────────────────────────────────────
VAD_SILENCE_THRESHOLD = 30          # 30 × 32ms ≈ 960ms of silence → end of utterance
VAD_NO_SPEECH_TIMEOUT = 500         # 500 × 32ms ≈ 16s with no speech → reprompt
VAD_CALL_TIMEOUT_ROUNDS = 3         # Reprompt up to 3 times before hanging up

# ── Amharic prompts ───────────────────────────────────────────────────────────
PROMPT_GREETING    = "እንኳን ደህና ነዎት! የገበሬ አማካሪ ስልክ ላይ ደወሉ። ጥያቄዎን ይጠይቁ።"
PROMPT_ASK_MORE    = "ሌላ ጥያቄ አለዎት?"           # Do you have another question?
PROMPT_REPROMPT    = "እባክዎ ጥያቄዎን ይጠይቁ።"      # Please ask your question.
PROMPT_GOODBYE     = "ሰላም! ጥሩ ቀን ይሁንልዎ።"     # Goodbye! Have a good day.
PROMPT_NO_SPEECH   = "ምንም ድምፅ አልሰማሁም። ጥሩ ቀን ይሁንልዎ።"  # No audio detected. Goodbye.
PROMPT_STT_FAIL    = "ይቅርታ፣ ድምፅዎን ሰምቼ ለመረዳት አልቻልኩም። እባክዎ ይድገሙ።"  # Could not understand. Please repeat.


def _load_vad(aggressiveness: int = 2) -> webrtcvad.Vad:
    """
    Create a WebRTC VAD instance.
    aggressiveness: 0 (least aggressive) to 3 (most aggressive).
    2 is a good default for telephony with background noise.
    """
    vad = webrtcvad.Vad(aggressiveness)
    return vad


def synthesize_text(text: str, prefix: str = "tts") -> Optional[str]:
    """Call TTS service and save the resulting WAV. Returns file path or None."""
    try:
        resp = requests.post(TTS_URL, json={"text": text}, timeout=20)
        if resp.status_code == 200:
            filename = f"{prefix}_{uuid.uuid4()}.wav"
            with open(filename, "wb") as f:
                f.write(resp.content)
            return filename
        logger.error(f"TTS returned HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"TTS request failed: {e}")
    return None


def stream_wav_to_voip_call(call: VoIPCall, filepath: str) -> None:
    """
    Stream a mono/stereo 16-bit WAV to pyVoIP (linear PCM @ 8 kHz for write_audio).
    Paces chunks at ~20 ms to match telephony frame timing.
    """
    with wave.open(filepath, "rb") as wf:
        nch = wf.getnchannels()
        sw = wf.getsampwidth()
        rate = wf.getframerate()
        nframes = wf.getnframes()
        if sw != 2:
            logger.warning(f"Unsupported WAV sample width {sw}; expected 16-bit")
            return
        pcm = np.frombuffer(wf.readframes(nframes), dtype=np.int16)
    if nch == 2:
        pcm = pcm.reshape(-1, 2).mean(axis=1).astype(np.int16)
    if rate != 8000:
        pcm = resample_poly(pcm, up=8000, down=rate).astype(np.int16)
    raw = pcm.tobytes()
    frame_bytes = 320  # 160 samples × 16-bit @ 8 kHz ≈ 20 ms
    for i in range(0, len(raw), frame_bytes):
        chunk = raw[i : i + frame_bytes]
        if len(chunk) < frame_bytes:
            chunk = chunk + b"\x00" * (frame_bytes - len(chunk))
        call.write_audio(chunk)
        time.sleep(0.02)


def _play_and_cleanup(call: VoIPCall, filepath: Optional[str]):
    """Play a WAV over the SIP call and then delete the file."""
    if filepath and os.path.exists(filepath):
        try:
            stream_wav_to_voip_call(call, filepath)
        except Exception as e:
            logger.warning(f"stream wav error: {e}")
        finally:
            os.remove(filepath)


def capture_utterance(call, vad: webrtcvad.Vad, session_id: str):
    """
    Captures one spoken utterance using Google WebRTC VAD.

    Returns:
        (audio_frames: bytearray, speech_detected: bool)

    Logic:
        - Accumulate G.711 μ-law frames, convert to 16-bit PCM.
        - WebRTC VAD operates on exactly 160-sample (20ms at 8 kHz) = 320-byte frames.
        - End of utterance = speech detected AND then ~960ms of silence.
        - Timeout = ~16s of no speech (triggers reprompt/hangup upstream).
    """
    audio_frames  = bytearray()
    vad_buffer    = bytearray()
    silence_frames   = 0
    no_speech_frames = 0
    speech_detected  = False

    # WebRTC VAD: 20ms frame at 8000 Hz = 160 samples × 2 bytes = 320 bytes
    FRAME_BYTES = 320

    while call.state == CallState.ANSWERED:
        frame = call.read_audio()
        if not frame:
            break

        try:
            pcm_frame = audioop.ulaw2lin(frame, 2)   # G.711 μ-law → 16-bit PCM
            audio_frames.extend(pcm_frame)
            vad_buffer.extend(pcm_frame)

            while len(vad_buffer) >= FRAME_BYTES:
                chunk = bytes(vad_buffer[:FRAME_BYTES])
                vad_buffer = vad_buffer[FRAME_BYTES:]

                is_speech = vad.is_speech(chunk, sample_rate=8000)

                if is_speech:
                    silence_frames   = 0
                    no_speech_frames = 0
                    speech_detected  = True
                else:
                    no_speech_frames += 1
                    if speech_detected:
                        silence_frames += 1

            if speech_detected and silence_frames > VAD_SILENCE_THRESHOLD:
                break  # End of utterance

            if not speech_detected and no_speech_frames > VAD_NO_SPEECH_TIMEOUT:
                break  # Timeout — no speech heard

        except Exception as e:
            logger.debug(f"VAD frame error: {e}")

    return audio_frames, speech_detected


def frames_to_wav_16k(audio_frames: bytearray, out_path: str):
    """Upsample 8 kHz PCM bytearray to 16 kHz WAV file for Whisper."""
    pcm_8k  = np.frombuffer(bytes(audio_frames), dtype=np.int16)
    # resample_poly(up=2, down=1) gives exact 8000→16000 Hz upsampling
    pcm_16k = resample_poly(pcm_8k, up=2, down=1).astype(np.int16)
    with wave.open(out_path, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)   # 16-bit
        wf.setframerate(16000)
        wf.writeframes(pcm_16k.tobytes())


def process_audio_pipeline(wav_path: str, phone_number: str, session_id: str) -> Optional[str]:
    """
    Runs the full STT → Logic/RAG → TTS pipeline.
    Returns path to TTS response WAV, or None on failure.
    """
    # 1. STT
    try:
        with open(wav_path, "rb") as f:
            stt_resp = requests.post(STT_URL, files={"audio_file": f}, timeout=30)
        data = stt_resp.json()
        text = data.get("text", "").strip()
        confidence = data.get("confidence", 0.0)
        logger.info(f"[{session_id}] STT: '{text}' (conf={confidence:.2f})")
    except Exception as e:
        logger.error(f"[{session_id}] STT request failed: {e}")
        return None

    if not text:
        logger.warning(f"[{session_id}] STT returned empty text.")
        return None

    # 2. Logic / RAG
    try:
        payload = {"text": text, "phone_number": phone_number, "session_id": session_id}
        logic_resp = requests.post(LOGIC_URL, json=payload, timeout=30)
        response_text = logic_resp.json().get("response", "").strip()
        logger.info(f"[{session_id}] Logic: '{response_text[:80]}'")
    except Exception as e:
        logger.error(f"[{session_id}] Logic request failed: {e}")
        return None

    if not response_text:
        return None

    # 3. TTS
    return synthesize_text(response_text, prefix=f"resp_{session_id}")


def upload_call_record(wav_path: str, phone_number: str, session_id: str, duration_sec: int):
    """Uploads the full call recording to the logic service for DB storage."""
    try:
        with open(wav_path, "rb") as f:
            resp = requests.post(
                SAVE_RECORD_URL,
                data={"session_id": session_id, "phone_number": phone_number, "duration": duration_sec},
                files={"audio_file": f},
                timeout=30
            )
        if resp.status_code == 200:
            logger.info(f"[{session_id}] Call record uploaded.")
        else:
            logger.warning(f"[{session_id}] Upload failed: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"[{session_id}] Upload error: {e}")



# ── Per-Call Handler (runs in its own thread) ────────────────────────────────
def handle_call(call, phone_number: str, session_id: str):
    """
    Handles a single SIP call:
      1. Answers and plays Amharic greeting.
      2. Captures utterance via Silero VAD.
      3. Runs STT → Logic → TTS pipeline.
      4. Plays response, then asks if farmer has another question.
      5. Loops up to VAD_CALL_TIMEOUT_ROUNDS times with no speech before hanging up.
      6. Saves full call recording to DB.
    """
    logger.info(f"[{session_id}] Call handler started for {phone_number}")
    all_audio = bytearray()  # accumulates the full call for recording
    vad_model = _load_vad()

    try:
        call.answer()
        logger.info(f"[{session_id}] Call answered.")

        # Play greeting
        _play_and_cleanup(call, synthesize_text(PROMPT_GREETING, f"greet_{session_id}"))

        reprompt_count = 0

        while call.state == CallState.ANSWERED:
            # Capture one utterance
            audio_frames, speech_detected = capture_utterance(call, vad_model, session_id)
            all_audio.extend(audio_frames)

            if not speech_detected:
                reprompt_count += 1
                logger.info(f"[{session_id}] No speech (attempt {reprompt_count}/{VAD_CALL_TIMEOUT_ROUNDS})")
                if reprompt_count >= VAD_CALL_TIMEOUT_ROUNDS:
                    _play_and_cleanup(call, synthesize_text(PROMPT_NO_SPEECH, f"ns_{session_id}"))
                    break
                _play_and_cleanup(call, synthesize_text(PROMPT_REPROMPT, f"rp_{session_id}"))
                continue

            reprompt_count = 0  # Reset on successful speech

            # Convert captured frames to 16 kHz WAV
            utterance_file = f"utt_{session_id}_{uuid.uuid4()}.wav"
            try:
                frames_to_wav_16k(audio_frames, utterance_file)
            except Exception as e:
                logger.error(f"[{session_id}] Resampling failed: {e}")
                continue

            # Run pipeline
            response_file = process_audio_pipeline(utterance_file, phone_number, session_id)

            # Cleanup utterance file
            if os.path.exists(utterance_file):
                os.remove(utterance_file)

            if response_file:
                _play_and_cleanup(call, response_file)
            else:
                # STT/Logic could not produce a response
                _play_and_cleanup(call, synthesize_text(PROMPT_STT_FAIL, f"fail_{session_id}"))

            # Brief pause then ask if they have another question
            time.sleep(0.5)
            if call.state == CallState.ANSWERED:
                _play_and_cleanup(call, synthesize_text(PROMPT_ASK_MORE, f"more_{session_id}"))

        # Hang up gracefully
        if call.state == CallState.ANSWERED:
            _play_and_cleanup(call, synthesize_text(PROMPT_GOODBYE, f"bye_{session_id}"))
            call.hangup()

    except Exception as e:
        logger.error(f"[{session_id}] Unhandled error in call handler: {e}")
        try:
            call.hangup()
        except Exception:
            pass

    finally:
        # Save full call recording to database
        if all_audio:
            full_path = f"full_{session_id}.wav"
            try:
                # Save at 8 kHz (telephony rate) for storage using wave module
                pcm = np.frombuffer(bytes(all_audio), dtype=np.int16)
                with wave.open(full_path, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)
                    wf.setframerate(8000)
                    wf.writeframes(pcm.tobytes())
                # Duration: 16-bit = 2 bytes/sample, 8000 samples/sec → 16000 bytes/sec
                duration_sec = int(len(all_audio) / 16000)
                upload_call_record(full_path, phone_number, session_id, duration_sec)
            except Exception as e:
                logger.error(f"[{session_id}] Failed to save call recording: {e}")
            finally:
                if os.path.exists(full_path):
                    os.remove(full_path)

        logger.info(f"[{session_id}] Call handler finished.")


# ── SIP Server ───────────────────────────────────────────────────────────────
class AdvisorSIPClient:
    """Thin wrapper around pyVoIP VoIPPhone (correct API for pyVoIP 1.6.x)."""

    def __init__(self):
        logger.info(
            f"Initializing VoIP phone: bind {SIP_BIND}:{SIP_PORT} → "
            f"registrar {SIP_SERVER}:{SIP_PORT} as '{SIP_USER}'"
        )
        self.phone = VoIPPhone(
            SIP_SERVER,
            SIP_PORT,
            SIP_USER,
            SIP_PASS,
            myIP=SIP_BIND,
            callCallback=self._on_incoming_call,
            sipPort=SIP_PORT,
        )

    def _on_incoming_call(self, call: VoIPCall) -> None:
        """pyVoIP delivers an incoming VoIPCall (RINGING) from a background Timer."""
        try:
            from_hdr = call.request.headers.get("From", {})
            if isinstance(from_hdr, dict):
                phone_number = from_hdr.get("number", "UnknownPhone")
            else:
                phone_number = "UnknownPhone"
        except Exception:
            phone_number = "UnknownPhone"
        session_id = str(uuid.uuid4())
        logger.info(f"Incoming call from {phone_number} → session {session_id}")
        threading.Thread(
            target=handle_call,
            args=(call, phone_number, session_id),
            daemon=True,
        ).start()

    def start(self) -> None:
        logger.info("Listening for incoming calls (VoIPPhone + worker threads)...")
        self.phone.start()
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            logger.info("Shutting down VoIP phone...")
            self.phone.stop()


# ── Entry Point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    time.sleep(5)   # Allow other containers to start first
    logger.info("Telephony Service starting...")
    client = AdvisorSIPClient()
    client.start()  # Blocks forever in accept loop
