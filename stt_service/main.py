from fastapi import FastAPI, UploadFile, File, HTTPException
from pydantic import BaseModel
import aiofiles
import asyncio
import os
import time
import uuid
import math
import logging
import threading
from faster_whisper import WhisperModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("asr_service")

app = FastAPI()

_model_path = os.environ.get("WHISPER_MODEL_PATH", "").strip()
_model_size = os.environ.get("WHISPER_MODEL", "small")
if _model_path and os.path.isdir(_model_path):
    _model_ref = _model_path
elif _model_path:
    _model_ref = _model_size
else:
    _model_ref = _model_size

_WHISPER_LANGUAGE = os.environ.get("WHISPER_LANGUAGE", "am").strip() or "am"
_BEAM_SIZE = int(os.environ.get("WHISPER_BEAM_SIZE", "1"))
_TRANSCRIBE_TIMEOUT_S = float(os.environ.get("WHISPER_TIMEOUT_S", "30"))
_SHARED_UTTERANCES_DIR = os.environ.get("SHARED_UTTERANCES_DIR", "/shared/utterances")
_COMPUTE_TYPE = os.environ.get("ASR_COMPUTE_TYPE", "").strip()

asr_model: WhisperModel | None = None
_model_load_error: str | None = None
_model_lock = threading.Lock()


def _load_model() -> None:
    global asr_model, _model_load_error
    compute_type = _COMPUTE_TYPE or "float16"
    try:
        asr_model = WhisperModel(_model_ref, device="cuda", compute_type=compute_type)
        logger.info("Loaded successfully on CUDA (%s).", compute_type)
        return
    except Exception as cuda_exc:
        logger.warning("CUDA load failed: %s. Falling back to CPU...", cuda_exc)

    import multiprocessing
    cpu_threads = int(os.environ.get("WHISPER_THREADS", multiprocessing.cpu_count()))
    cpu_compute = _COMPUTE_TYPE or "int8"
    try:
        asr_model = WhisperModel(
            _model_ref,
            device="cpu",
            compute_type=cpu_compute,
            cpu_threads=cpu_threads,
            num_workers=2,
        )
        logger.info("Loaded on CPU (%s, %s threads).", cpu_compute, cpu_threads)
    except Exception as exc:
        _model_load_error = str(exc)
        logger.error("Failed to load ASR model: %s", exc)


@app.on_event("startup")
def startup_event():
    threading.Thread(target=_load_model, daemon=True, name="asr-model-load").start()


@app.get("/health")
def health_check():
    if asr_model is not None:
        return {"status": "ok", "model": _model_ref}
    if _model_load_error:
        return {"status": "error", "detail": _model_load_error}
    return {"status": "loading", "model": _model_ref}


class TranscribeFileRequest(BaseModel):
    filename: str
    language: str = "am"


def _do_transcribe(temp_filename: str, language: str | None = None):
    if asr_model is None:
        raise RuntimeError("ASR model still loading")
    lang = language or _WHISPER_LANGUAGE
    segments, info = asr_model.transcribe(
        temp_filename,
        language=lang,
        beam_size=_BEAM_SIZE,
        condition_on_previous_text=False,
        compression_ratio_threshold=2.2,
        log_prob_threshold=-1.0,
        no_speech_threshold=0.6,
        repetition_penalty=1.15,
        no_repeat_ngram_size=3,
        temperature=[0.0, 0.2, 0.4],
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


async def _transcribe_path(path: str, language: str | None = None) -> dict:
    if asr_model is None:
        if _model_load_error:
            return {"text": "", "transcript": "", "confidence": 0.0, "error": _model_load_error}
        return {"text": "", "transcript": "", "confidence": 0.0, "error": "model loading"}

    started = time.time()
    try:
        text, confidence = await asyncio.wait_for(
            asyncio.to_thread(_do_transcribe, path, language),
            timeout=_TRANSCRIBE_TIMEOUT_S,
        )
    except asyncio.TimeoutError:
        elapsed = time.time() - started
        logger.warning("Transcription timeout after %.1fs for %s", elapsed, path)
        return {
            "text": "",
            "transcript": "",
            "confidence": 0.0,
            "error": f"transcription timeout after {elapsed:.1f}s",
        }

    elapsed = time.time() - started
    logger.info("Transcription: %r | conf=%s | took=%.2fs", text[:80], confidence, elapsed)
    return {"text": text, "transcript": text, "confidence": confidence, "engine": "faster-whisper"}


@app.post("/transcribe-file")
async def transcribe_file(req: TranscribeFileRequest):
    """Read WAV from shared utterances volume (zero-copy handoff from VAD)."""
    filename = os.path.basename(req.filename)
    path = os.path.join(_SHARED_UTTERANCES_DIR, filename)
    if not os.path.isfile(path):
        alt = os.path.join("/app/utterances", filename)
        if os.path.isfile(alt):
            path = alt
        else:
            raise HTTPException(status_code=404, detail=f"Utterance not found: {filename}")
    return await _transcribe_path(path, req.language or _WHISPER_LANGUAGE)


@app.post("/transcribe")
async def transcribe(audio_file: UploadFile = File(...)):
    orig = audio_file.filename or ""
    ext = os.path.splitext(orig)[1].lower()
    if ext not in (".wav", ".ogg", ".opus", ".mp3", ".webm", ".flac", ".m4a"):
        ext = ".wav"
    temp_filename = f"temp_{uuid.uuid4()}{ext}"
    try:
        async with aiofiles.open(temp_filename, "wb") as out_file:
            content = await audio_file.read()
            await out_file.write(content)
        result = await _transcribe_path(temp_filename)
        return {"text": result.get("text", ""), "confidence": result.get("confidence", 0.0), **{
            k: v for k, v in result.items() if k not in ("text",)
        }}
    except Exception as e:
        logger.error("ASR Error: %s", e)
        return {"text": "", "confidence": 0.0, "error": str(e)}
    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)
