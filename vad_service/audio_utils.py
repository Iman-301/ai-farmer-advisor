import wave
from pathlib import Path

import numpy as np


def pcm16_bytes_to_float32(pcm_bytes: bytes) -> np.ndarray:
    """
    Convert signed 16-bit PCM bytes to float32 audio in range [-1.0, 1.0].
    Expected input:
    - mono
    - 16-bit PCM
    - little-endian
    """
    if not pcm_bytes:
        return np.array([], dtype=np.float32)

    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)

    audio_float32 = audio_int16.astype(np.float32) / 32768.0

    return audio_float32


def float32_to_pcm16_bytes(audio_float32: np.ndarray) -> bytes:
    """
    Convert float32 audio in range [-1.0, 1.0] to signed 16-bit PCM bytes.
    """
    audio_float32 = np.clip(audio_float32, -1.0, 1.0)
    audio_int16 = (audio_float32 * 32767).astype(np.int16)
    return audio_int16.tobytes()


def save_pcm16_wav(
    file_path: str | Path,
    pcm_bytes: bytes,
    sample_rate: int = 16000
) -> str:
    """
    Save raw PCM16 mono bytes as WAV.
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(file_path), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm_bytes)

    return str(file_path)