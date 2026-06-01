import os
import httpx
from pathlib import Path

TTS_SERVICE_URL = os.getenv(
    "TTS_SERVICE_URL",
    "http://tts_service:8000",
)


async def synthesize_speech(text: str, utterance_path: str) -> str:
    url = f"{TTS_SERVICE_URL.rstrip('/')}/synthesize"

    original_p = Path(utterance_path)
    tts_filename = f"{original_p.stem}_response.wav"
    tts_path = str(original_p.parent / tts_filename)

    try:
        print(f"[TTS HTTP] Requesting synthesis from {url}", flush=True)
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, json={"text": text})
            response.raise_for_status()

            with open(tts_path, "wb") as f:
                f.write(response.content)

            print(f"[TTS SAVED] {tts_path} (size={len(response.content)})", flush=True)
            return tts_path

    except Exception as e:
        print(f"[TTS ERROR] Request failed: {e}", flush=True)
        return ""
