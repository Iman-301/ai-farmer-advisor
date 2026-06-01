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
    - 8 kHz or 16 kHz
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
        candidate_threshold: float | None = None,
        continue_threshold: float | None = None,
        energy_threshold: float = 0.012,
        energy_min_speech_prob: float = 0.2,
        min_speech_start_ms: int = 120,
        speech_start_gap_ms: int = 96,
        speech_end_silence_ms: int = 900,
        speech_pad_ms: int = 200,
        output_dir: str = "utterances",
    ):
        self.session_id = session_id
        if sample_rate not in (8000, 16000):
            raise ValueError(f"Unsupported VAD sample_rate={sample_rate}; expected 8000 or 16000")

        self.sample_rate = sample_rate
        self.threshold = threshold
        self.candidate_threshold = (
            candidate_threshold if candidate_threshold is not None else threshold * 0.75
        )
        self.continue_threshold = (
            continue_threshold if continue_threshold is not None else threshold * 0.6
        )
        self.energy_threshold = energy_threshold
        self.energy_min_speech_prob = energy_min_speech_prob

        self.min_speech_start_ms = min_speech_start_ms
        self.speech_start_gap_ms = speech_start_gap_ms
        self.speech_end_silence_ms = speech_end_silence_ms
        self.speech_pad_ms = speech_pad_ms

        # Silero expects 256 samples at 8 kHz and 512 samples at 16 kHz.
        self.window_samples = 256 if sample_rate == 8000 else 512
        self.window_bytes = self.window_samples * 2

        self.model = load_silero_vad()
        self.model.eval()

        self.pending_bytes = bytearray()

        self.is_speaking = False
        self.speech_candidate_ms = 0
        self.speech_candidate_gap_ms = 0
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
        self.speech_candidate_gap_ms = 0
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

        rms_energy = float(np.sqrt(np.mean(np.square(audio_float32)))) if len(audio_float32) else 0.0
        energy_speech = (
            rms_energy >= self.energy_threshold
            and speech_prob >= self.energy_min_speech_prob
        )
        start_speech = speech_prob >= self.threshold or energy_speech
        candidate_speech = speech_prob >= self.candidate_threshold or energy_speech
        continue_speech = speech_prob >= self.continue_threshold or energy_speech

        # Always keep a small pre-speech buffer so the beginning of speech is not cut.
        self._append_pre_speech(frame)

        if self.is_speaking:
            if continue_speech:
                self.silence_ms = 0
            else:
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
                    "speech_probability": round(speech_prob, 4),
                    "rms_energy": round(rms_energy, 5),
                })

                self.is_speaking = False
                self.silence_ms = 0
                self.speech_candidate_ms = 0
                self.speech_candidate_gap_ms = 0
                self.speech_started_at = None
                self.current_utterance = bytearray()

        elif start_speech or (self.speech_candidate_ms > 0 and candidate_speech):
            self.silence_ms = 0
            self.speech_candidate_ms += frame_ms
            self.speech_candidate_gap_ms = 0

            if self.speech_candidate_ms >= self.min_speech_start_ms:
                self.is_speaking = True
                self.speech_started_at = now

                # Include pre-speech audio at the beginning.
                self.current_utterance.extend(self.pre_speech_buffer)
                self.pre_speech_buffer = bytearray()

                events.append({
                    "event": "speech_started",
                    "timestamp": now,
                    "speech_probability": round(speech_prob, 4),
                    "rms_energy": round(rms_energy, 5),
                })

                self.current_utterance.extend(frame)

        else:
            if self.speech_candidate_ms > 0:
                self.speech_candidate_gap_ms += frame_ms
                if self.speech_candidate_gap_ms > self.speech_start_gap_ms:
                    self.speech_candidate_ms = 0
                    self.speech_candidate_gap_ms = 0

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