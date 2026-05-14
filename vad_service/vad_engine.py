import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from silero_vad import load_silero_vad

from audio_utils import pcm16_bytes_to_float32, save_pcm16_wav


class SileroStreamingVAD:
    """
    Streaming Silero VAD engine.

    Expected input:
    - 16 kHz
    - mono
    - signed 16-bit PCM bytes

    The service receives arbitrary PCM chunks, buffers them,
    splits them into Silero-friendly windows, estimates speech probability,
    and emits:
    - speech_started
    - speech_ended
    """

    def __init__(
        self,
        session_id: str,
        sample_rate: int = 16000,
        threshold: float = 0.5,
        min_speech_start_ms: int = 120,
        speech_end_silence_ms: int = 900,
        speech_pad_ms: int = 200,
        output_dir: str = "utterances",
    ):
        self.session_id = session_id
        self.sample_rate = sample_rate
        self.threshold = threshold

        self.min_speech_start_ms = min_speech_start_ms
        self.speech_end_silence_ms = speech_end_silence_ms
        self.speech_pad_ms = speech_pad_ms

        # Silero commonly works well with 512 samples at 16 kHz.
        # 512 samples = 32 ms at 16 kHz.
        self.window_samples = 512
        self.window_bytes = self.window_samples * 2

        self.model = load_silero_vad()
        self.model.eval()

        self.pending_bytes = bytearray()

        self.is_speaking = False
        self.speech_candidate_ms = 0
        self.silence_ms = 0

        self.current_utterance = bytearray()
        self.pre_speech_buffer = bytearray()

        self.utterance_index = 0
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.speech_started_at: float | None = None

    def reset(self):
        self.pending_bytes = bytearray()
        self.is_speaking = False
        self.speech_candidate_ms = 0
        self.silence_ms = 0
        self.current_utterance = bytearray()
        self.pre_speech_buffer = bytearray()
        self.speech_started_at = None

    def process_pcm_chunk(self, pcm_chunk: bytes) -> list[dict[str, Any]]:
        """
        Process arbitrary PCM16 bytes and return VAD events.
        """
        events: list[dict[str, Any]] = []

        if not pcm_chunk:
            return events

        self.pending_bytes.extend(pcm_chunk)

        while len(self.pending_bytes) >= self.window_bytes:
            frame = bytes(self.pending_bytes[:self.window_bytes])
            del self.pending_bytes[:self.window_bytes]

            frame_events = self._process_frame(frame)
            events.extend(frame_events)

        return events

    def _process_frame(self, frame: bytes) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        audio_float32 = pcm16_bytes_to_float32(frame)

        if len(audio_float32) == 0:
            return events

        audio_tensor = torch.from_numpy(audio_float32)

        with torch.no_grad():
            speech_prob = float(self.model(audio_tensor, self.sample_rate).item())

        frame_ms = int((len(audio_float32) / self.sample_rate) * 1000)
        now = time.time()

        is_speech = speech_prob >= self.threshold

        # Always keep a small pre-speech buffer so the beginning of speech is not cut.
        self._append_pre_speech(frame)

        if is_speech:
            self.silence_ms = 0
            self.speech_candidate_ms += frame_ms

            if not self.is_speaking:
                if self.speech_candidate_ms >= self.min_speech_start_ms:
                    self.is_speaking = True
                    self.speech_started_at = now

                    # Include pre-speech audio at the beginning.
                    self.current_utterance.extend(self.pre_speech_buffer)
                    self.pre_speech_buffer = bytearray()

                    events.append({
                        "event": "speech_started",
                        "timestamp": now,
                        "speech_probability": round(speech_prob, 4)
                    })

            if self.is_speaking:
                self.current_utterance.extend(frame)

        else:
            self.speech_candidate_ms = 0

            if self.is_speaking:
                self.silence_ms += frame_ms
                self.current_utterance.extend(frame)

                if self.silence_ms >= self.speech_end_silence_ms:
                    utterance_path = self._save_current_utterance()

                    duration_seconds = None
                    if self.speech_started_at:
                        duration_seconds = round(now - self.speech_started_at, 2)

                    events.append({
                        "event": "speech_ended",
                        "timestamp": now,
                        "utterance_path": utterance_path,
                        "duration_seconds": duration_seconds,
                        "speech_probability": round(speech_prob, 4)
                    })

                    self.is_speaking = False
                    self.silence_ms = 0
                    self.speech_candidate_ms = 0
                    self.speech_started_at = None
                    self.current_utterance = bytearray()

        return events

    def _append_pre_speech(self, frame: bytes):
        """
        Keep a short buffer before speech starts.
        """
        self.pre_speech_buffer.extend(frame)

        max_pre_speech_bytes = int(
            self.sample_rate * 2 * self.speech_pad_ms / 1000
        )

        if len(self.pre_speech_buffer) > max_pre_speech_bytes:
            self.pre_speech_buffer = self.pre_speech_buffer[-max_pre_speech_bytes:]

    def _save_current_utterance(self) -> str | None:
        if not self.current_utterance:
            return None

        self.utterance_index += 1

        file_path = self.output_dir / (
            f"{self.session_id}_utterance_{self.utterance_index:03d}.wav"
        )

        return save_pcm16_wav(
            file_path=file_path,
            pcm_bytes=bytes(self.current_utterance),
            sample_rate=self.sample_rate
        )
    
    def finalize(self) -> str | None:
        """
        Save current utterance when the WebSocket/session ends,
        even if silence-based speech_ended was not triggered.
        """
        if self.current_utterance:
            utterance_path = self._save_current_utterance()

            self.is_speaking = False
            self.silence_ms = 0
            self.speech_candidate_ms = 0
            self.speech_started_at = None
            self.current_utterance = bytearray()

            return utterance_path

        return None