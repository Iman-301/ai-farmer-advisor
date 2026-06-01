from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
import os
import logging
import subprocess
import tempfile
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("tts_service")

app = FastAPI()

TTS_PROVIDER = (os.getenv("TTS_PROVIDER") or "gtts").strip().lower()
TTS_LANG = os.getenv("TTS_LANG", "am")
TTS_SAMPLE_RATE = int(os.getenv("TTS_SAMPLE_RATE", "16000"))
TTS_ATEMPO = float(os.getenv("TTS_ATEMPO", "1.15"))
TTS_SLOW = os.getenv("TTS_SLOW", "0").strip().lower() in ("1", "true", "yes")


class TTSRequest(BaseModel):
    text: str


def _synthesize_gtts_sync(text: str) -> str:
    """gTTS → MP3 → ffmpeg → 16 kHz mono PCM WAV (fast path for voice calls)."""
    from gtts import gTTS

    mp3_fd, mp3_path = tempfile.mkstemp(suffix=".mp3")
    os.close(mp3_fd)
    wav_path = mp3_path.replace(".mp3", ".wav")

    try:
        gTTS(text=text, lang=TTS_LANG, slow=TTS_SLOW).save(mp3_path)

        af_parts: list[str] = []
        if TTS_ATEMPO and abs(TTS_ATEMPO - 1.0) > 0.01:
            # atempo accepts 0.5–2.0 per filter; chain if needed
            tempo = TTS_ATEMPO
            while tempo > 2.0:
                af_parts.append("atempo=2.0")
                tempo /= 2.0
            while tempo < 0.5:
                af_parts.append("atempo=0.5")
                tempo /= 0.5
            if abs(tempo - 1.0) > 0.01:
                af_parts.append(f"atempo={tempo:.3f}")

        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-i", mp3_path,
            "-ar", str(TTS_SAMPLE_RATE),
            "-ac", "1",
        ]
        if af_parts:
            cmd.extend(["-af", ",".join(af_parts)])
        cmd.extend(["-f", "wav", wav_path])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise RuntimeError(result.stderr or "ffmpeg failed")

        return wav_path
    finally:
        if os.path.exists(mp3_path):
            os.remove(mp3_path)


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "provider": TTS_PROVIDER,
        "lang": TTS_LANG,
        "sample_rate": TTS_SAMPLE_RATE,
        "atempo": TTS_ATEMPO,
    }


@app.post("/synthesize")
async def synthesize(req: TTSRequest):
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="Text must not be empty.")

    try:
        logger.info("Synthesizing %d chars via %s", len(text), TTS_PROVIDER)
        if TTS_PROVIDER == "gtts":
            wav_path = await asyncio.to_thread(_synthesize_gtts_sync, text)
        else:
            raise HTTPException(
                status_code=501,
                detail=f"TTS provider {TTS_PROVIDER!r} not supported. Use TTS_PROVIDER=gtts.",
            )

        return FileResponse(
            wav_path,
            media_type="audio/wav",
            filename="response.wav",
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("TTS failed: %s", exc)
        raise HTTPException(status_code=500, detail="TTS generation failed.")
