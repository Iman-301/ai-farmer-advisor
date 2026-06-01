import os
from pathlib import Path

import httpx


ASR_HTTP_URL = os.getenv(
    "ASR_HTTP_URL",
    "http://stt_service:8000/transcribe-file",
)


async def transcribe_utterance_file(
    utterance_path: str,
    language: str = "am",
) -> dict:
    """Send utterance filename to STT (shared Docker volume)."""
    filename = Path(utterance_path).name

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            ASR_HTTP_URL,
            json={"filename": filename, "language": language},
        )
        response.raise_for_status()
        data = response.json()

    transcript = (data.get("transcript") or data.get("text") or "").strip()
    return {
        "transcript": transcript,
        "raw_transcript": data.get("raw_transcript") or transcript,
        "final_transcript": data.get("final_transcript") or transcript,
        "structured_transcript": data.get("structured_transcript") or transcript,
        "confidence": data.get("confidence"),
        "acoustic_confidence": data.get("acoustic_confidence") or data.get("confidence"),
        "engine": data.get("engine", "faster-whisper"),
        "needs_confirmation": data.get("needs_confirmation", False),
        "confirmation_prompt": data.get("confirmation_prompt"),
        "error": data.get("error"),
    }
