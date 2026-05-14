from fastapi import FastAPI, UploadFile, File
import aiofiles
import os
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


@app.post("/transcribe")
async def transcribe(audio_file: UploadFile = File(...)):
    """
    Accepts a WAV audio file, transcribes it using faster-whisper (Amharic),
    and returns the transcription text with an average confidence score.

    Returns:
        {"text": str, "confidence": float}  on success
        {"text": "", "confidence": 0.0, "error": str}  on failure
    """
    orig = audio_file.filename or ""
    ext = os.path.splitext(orig)[1].lower()
    if ext not in (".wav", ".ogg", ".opus", ".mp3", ".webm", ".flac", ".m4a"):
        ext = ".wav"
    temp_filename = f"temp_{uuid.uuid4()}{ext}"
    try:
        # Save the uploaded audio to a temp file
        async with aiofiles.open(temp_filename, 'wb') as out_file:
            content = await audio_file.read()
            await out_file.write(content)

        # Transcribe (default language am; override with WHISPER_LANGUAGE)
        segments, info = asr_model.transcribe(
            temp_filename,
            language=_WHISPER_LANGUAGE,
            beam_size=5,
            vad_filter=True,          # built-in VAD to skip silence
            vad_parameters=dict(min_silence_duration_ms=500)
        )

        text_parts = []
        log_probs = []
        for segment in segments:
            text_parts.append(segment.text.strip())
            # avg_logprob is negative; convert to 0-1 confidence
            if hasattr(segment, 'avg_logprob') and segment.avg_logprob is not None:
                log_probs.append(math.exp(max(segment.avg_logprob, -10)))

        text = " ".join(text_parts).strip()
        confidence = round(sum(log_probs) / len(log_probs), 3) if log_probs else 0.0

        logger.info(f"Transcription: '{text}' | Confidence: {confidence}")
        return {"text": text, "confidence": confidence}

    except Exception as e:
        logger.error(f"ASR Error: {e}")
        return {"text": "", "confidence": 0.0, "error": str(e)}

    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)