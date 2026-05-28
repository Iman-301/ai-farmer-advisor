from fastapi import FastAPI, UploadFile, File
import aiofiles
import asyncio
import os
import time
import uuid
import math
import logging
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("asr_service")

app = FastAPI()

# Load faster-whisper model with CUDA/CPU fallback.
# Prefer WHISPER_MODEL_PATH (local CTranslate2 dir, e.g. fine-tuned Amharic checkpoint).
# Otherwise WHISPER_MODEL: tiny / base / small / medium / large-v3 / HuggingFace model id.
_model_path = os.environ.get("WHISPER_MODEL_PATH", "").strip()
_model_size = os.environ.get("WHISPER_MODEL", "small")
if _model_path and os.path.isdir(_model_path):
    _model_ref = _model_path
    logger.info("Loading faster-whisper from local path: %s", _model_ref)
elif _model_path:
    logger.warning(
        "WHISPER_MODEL_PATH=%r is not a directory; using WHISPER_MODEL=%r instead.",
        _model_path,
        _model_size,
    )
    _model_ref = _model_size
    logger.info("Loading faster-whisper model id/size: %s", _model_ref)
else:
    _model_ref = _model_size
    logger.info("Loading faster-whisper model id/size: %s", _model_ref)

try:
    asr_model = WhisperModel(_model_ref, device="cuda", compute_type="float16")
    logger.info("Loaded successfully on CUDA.")
except Exception as e:
    logger.warning(f"Failed to load on CUDA: {e}. Falling back to CPU...")
    # cpu_threads: use available cores — Ryzen 7 7840HS has 8 cores / 16 threads
    import multiprocessing
    _cpu_threads = int(os.environ.get("WHISPER_THREADS", multiprocessing.cpu_count()))
    asr_model = WhisperModel(
        _model_ref,
        device="cpu",
        compute_type="int8",
        cpu_threads=_cpu_threads,
        num_workers=2,
    )
    logger.info(f"Loaded on CPU with int8 quantization ({_cpu_threads} threads).")

# BCP-47 language code passed to transcribe(); default am for this product.
_WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "am").strip() or "am"

# ── Decoding tuning ──────────────────────────────────────────────────────────
# beam_size=1 (greedy) is 3-5x faster on CPU than beam=5; we still get good
# Amharic accuracy from the fine-tuned model.
_BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
# Hard wall-clock cap for a single transcription. If exceeded we abort and
# return empty text so the caller doesn't hang for minutes. Whisper hallucinates
# repetition loops on noisy/silent audio (\"ነው ነው ነው...\") that can run 5-9 min.
_TRANSCRIBE_TIMEOUT_S = float(os.environ.get("WHISPER_TIMEOUT_S", "30"))


def _do_transcribe(temp_filename: str):
    """Run faster-whisper with anti-hallucination/anti-loop decoding params."""
    segments, info = asr_model.transcribe(
        temp_filename,
        language=_WHISPER_LANGUAGE,
        beam_size=_BEAM_SIZE,
        # ── Anti-repetition / anti-hallucination guards ───────────────────────
        # Don't feed previous output back in — biggest single cause of
        # "ነው ነው ነው..." infinite-loop transcriptions on noisy audio.
        condition_on_previous_text=False,
        # Auto-discard segments whose gzip compression ratio is too high
        # (indicates repetition like "ነው ነው ነው") and segments whose avg
        # log-prob is too low (pure noise).
        compression_ratio_threshold=2.2,
        log_prob_threshold=-1.0,
        # Skip pure-silence/noise frames instead of inventing text.
        no_speech_threshold=0.6,
        # Block 3-gram repetition during decoding itself.
        repetition_penalty=1.15,
        no_repeat_ngram_size=3,
        # Single low temperature → faster, but allow fallback if quality is poor.
        temperature=[0.0, 0.2, 0.4],
        # Built-in VAD to skip silence inside the audio.
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=500),
    )
    text_parts = []
    log_probs = []
    for segment in segments:
        text_parts.append(segment.text.strip())
        if hasattr(segment, "avg_logprob") and segment.avg_logprob is not None:
            log_probs.append(math.exp(max(segment.avg_logprob, -10)))
    text = " ".join(text_parts).strip()
    confidence = round(sum(log_probs) / len(log_probs), 3) if log_probs else 0.0
    return text, confidence


@app.post("/transcribe")
async def transcribe(audio_file: UploadFile = File(...)):
    """
    Accepts a WAV audio file, transcribes it using faster-whisper (Amharic),
    and returns the transcription text with an average confidence score.

    Returns:
        {"text": str, "confidence": float}  on success / timeout
        {"text": "", "confidence": 0.0, "error": str}  on failure
    """
    orig = audio_file.filename or ""
    ext = os.path.splitext(orig)[1].lower()
    if ext not in (".wav", ".ogg", ".opus", ".mp3", ".webm", ".flac", ".m4a"):
        ext = ".wav"
    temp_filename = f"temp_{uuid.uuid4()}{ext}"
    started = time.time()
    try:
        async with aiofiles.open(temp_filename, "wb") as out_file:
            content = await audio_file.read()
            await out_file.write(content)

        # Run blocking faster-whisper in a thread with a hard timeout so the
        # caller never waits longer than _TRANSCRIBE_TIMEOUT_S.
        try:
            text, confidence = await asyncio.wait_for(
                asyncio.to_thread(_do_transcribe, temp_filename),
                timeout=_TRANSCRIBE_TIMEOUT_S,
            )
        except asyncio.TimeoutError:
            elapsed = time.time() - started
            logger.warning(
                "Transcription aborted after %.1fs hard timeout (limit=%.1fs). "
                "Likely a noisy clip Whisper got stuck on; returning empty.",
                elapsed,
                _TRANSCRIBE_TIMEOUT_S,
            )
            return {
                "text": "",
                "confidence": 0.0,
                "error": f"transcription timeout after {elapsed:.1f}s",
            }

        elapsed = time.time() - started
        logger.info(
            "Transcription: '%s' | Confidence: %s | took=%.2fs",
            text,
            confidence,
            elapsed,
        )
        return {"text": text, "confidence": confidence}

    except Exception as e:
        logger.error(f"ASR Error: {e}")
        return {"text": "", "confidence": 0.0, "error": str(e)}

    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)