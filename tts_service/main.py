from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.responses import FileResponse
from transformers import VitsModel, AutoTokenizer
import torch
import soundfile as sf
import tempfile
import os
import logging
import subprocess

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("tts_service")

app = FastAPI()


class TTSRequest(BaseModel):
    text: str


MODEL_ID = "facebook/mms-tts-amh"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

logger.info(f"Loading model {MODEL_ID} on {DEVICE}...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
model = VitsModel.from_pretrained(MODEL_ID).to(DEVICE)
model.eval()
logger.info("Model loaded successfully.")


def romanize_text(text: str) -> str:
    """
    MMS Amharic TTS works best with romanized input.
    This uses the external `uroman` command if installed.
    Falls back to the original text if romanization fails.
    """
    try:
        result = subprocess.run(
            ["uroman"],
            input=text,
            text=True,
            capture_output=True,
            check=True
        )
        romanized = result.stdout.strip()
        if romanized:
            return romanized
        return text
    except Exception as e:
        logger.warning(f"Romanization failed, using original text: {e}")
        return text


@app.post("/synthesize")
async def synthesize(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text must not be empty.")

    try:
        logger.info(f"Synthesizing speech for payload: {req.text}")

        processed_text = romanize_text(req.text)
        logger.info(f"Processed text: {processed_text}")

        inputs = tokenizer(processed_text, return_tensors="pt").to(DEVICE)

        with torch.no_grad():
            output = model(**inputs).waveform

        audio = output.squeeze().cpu().numpy()
        sample_rate = model.config.sampling_rate

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
        tmp_path = tmp.name
        tmp.close()

        sf.write(tmp_path, audio, sample_rate)
        logger.info("Speech generation successful.")

        return FileResponse(
            tmp_path,
            media_type="audio/wav",
            filename="response.wav"
        )

    except Exception as e:
        logger.exception(f"TTS failed: {e}")
        raise HTTPException(status_code=500, detail="TTS generation failed.")