import json
import asyncio
import audioop
import os
import re
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query

from vad_engine import SileroStreamingVAD
from asr_client import transcribe_utterance_file
from rag_client import get_rag_answer
from tts_client import synthesize_speech
from voice_flow import (
    build_asr_confirmation_prompt,
    chunk_tts_text,
    classify_confirmation_reply_from_asr,
)
from shared.confirmation_policy import (
    CLARIFY_REPROMPT_AM,
    apply_normalized_transcript_to_asr_result,
    best_transcript_from_asr,
    vad_confirmation_gate_enabled,
    vad_flow_decision,
)
from shared.farmer_text_normalize import normalize_farmer_query


app = FastAPI(title="Silero VAD Service")


# ============================================================
# Configuration
# ============================================================

MAX_CONCURRENT_ASR = int(os.getenv("MAX_CONCURRENT_ASR", "2"))
VAD_THRESHOLD = float(os.getenv("VAD_THRESHOLD", "0.58"))
VAD_CANDIDATE_THRESHOLD = float(os.getenv("VAD_CANDIDATE_THRESHOLD", "0.38"))
VAD_CONTINUE_THRESHOLD = float(os.getenv("VAD_CONTINUE_THRESHOLD", "0.28"))
VAD_ENERGY_THRESHOLD = float(os.getenv("VAD_ENERGY_THRESHOLD", "0.012"))
VAD_ENERGY_MIN_SPEECH_PROB = float(os.getenv("VAD_ENERGY_MIN_SPEECH_PROB", "0.20"))
VAD_MIN_SPEECH_MS = int(os.getenv("VAD_MIN_SPEECH_MS", "128"))
VAD_SPEECH_START_GAP_MS = int(os.getenv("VAD_SPEECH_START_GAP_MS", "96"))
VAD_END_SILENCE_MS = int(os.getenv("VAD_END_SILENCE_MS", "520"))
VAD_TTS_MAX_SENTENCES = int(os.getenv("VAD_TTS_MAX_SENTENCES", "0"))
VAD_TTS_MAX_CHARS = int(os.getenv("VAD_TTS_MAX_CHARS", "0"))
VAD_AUDIO_LOG_EVERY = int(os.getenv("VAD_AUDIO_LOG_EVERY", "0"))
ASR_SEMAPHORE = asyncio.Semaphore(MAX_CONCURRENT_ASR)
PLAYBACK_LOCK = asyncio.Lock()


# ============================================================
# Health Check
# ============================================================

@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "silero-vad-service",
        "max_concurrent_asr": MAX_CONCURRENT_ASR,
        "vad_threshold": VAD_THRESHOLD,
        "vad_candidate_threshold": VAD_CANDIDATE_THRESHOLD,
        "vad_continue_threshold": VAD_CONTINUE_THRESHOLD,
        "vad_energy_threshold": VAD_ENERGY_THRESHOLD,
        "vad_energy_min_speech_prob": VAD_ENERGY_MIN_SPEECH_PROB,
        "vad_min_speech_ms": VAD_MIN_SPEECH_MS,
        "vad_speech_start_gap_ms": VAD_SPEECH_START_GAP_MS,
        "vad_end_silence_ms": VAD_END_SILENCE_MS,
    }


# ============================================================
# Safe WebSocket Send
# ============================================================

async def safe_send(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    payload: dict | bytes,
) -> bool:
    """Safely send JSON or binary to the WebSocket."""
    try:
        async with send_lock:
            if isinstance(payload, bytes):
                await websocket.send_bytes(payload)
            else:
                await websocket.send_json(payload)
        return True
    except (WebSocketDisconnect, RuntimeError):
        return False
    except Exception as e:
        print(f"[WS SEND ERROR] {e}", flush=True)
        return False


class SessionState:
    def __init__(self):
        self.playback_task = None
        self.pending_confirmation_transcript = None
        self.pending_confirmation_asr_meta = None
        self.pending_confirmation_utterance_path = None


def _looks_like_expert_handoff_request(text: str) -> bool:
    q = (text or "").strip().lower()
    if not q:
        return False
    hints = (
        "ባለሙያ",
        "ለባለሙያ",
        "ወደ ባለሙያ",
        "expert",
        "human",
        "operator",
        "escalate",
        "handoff",
    )
    return any(token in q for token in hints)


def split_tts_sentences(text: str) -> list[str]:
    return [
        sentence.strip()
        for sentence in re.split(r"(?<=[።?!])\s+", text.strip())
        if sentence.strip()
    ]


def compact_voice_tts_text(text: str) -> str:
    """Normalize RAG text for speech without changing the answer by default."""
    normalized = re.sub(r"\s+", " ", (text or "")).strip()
    if not normalized:
        return ""

    answer_matches = re.findall(
        r"ምላሽ[፦:]\s*(.*?)(?=(?:\(\d+\)\s*ጥያቄ|ጥያቄ[፦:]|$))",
        normalized,
    )
    if answer_matches:
        normalized = " ".join(part.strip() for part in answer_matches if part.strip())
    else:
        normalized = re.sub(
            r"^ከሰነዶች\s+የተገኘው\s+መረጃ\s+እንደሚከተለው\s+ነው።\s*",
            "",
            normalized,
        )

    sentences = split_tts_sentences(normalized)
    if VAD_TTS_MAX_SENTENCES > 0 and sentences:
        normalized = " ".join(sentences[:VAD_TTS_MAX_SENTENCES])

    if VAD_TTS_MAX_CHARS > 0 and len(normalized) > VAD_TTS_MAX_CHARS:
        normalized = normalized[:VAD_TTS_MAX_CHARS].rstrip()

    return normalized


# ============================================================
# Playback Handling
# ============================================================

async def play_advisor_response(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session_id: str,
    utterance_path: str,
    rag_answer: str,
    playback_sample_rate: int = 16000,
):
    """
    Synthesizes and streams audio for a RAG answer.
    Locked by PLAYBACK_LOCK to avoid overlapping speech.
    """
    async with PLAYBACK_LOCK:
        try:
            spoken_answer = compact_voice_tts_text(rag_answer)
            if not spoken_answer:
                return

            print(
                f"[TTS STARTING] full_text_len={len(rag_answer)}, "
                f"spoken_text_len={len(spoken_answer)}, path={utterance_path}",
                flush=True,
            )
            sentences = chunk_tts_text(spoken_answer)
            
            print(f"[STREAMING] Total sentences: {len(sentences)}", flush=True)
            
            for i, sentence in enumerate(sentences):
                if not sentence.strip():
                    continue
                    
                print(f"[SENTENCE {i+1}/{len(sentences)}] Synthesizing: {sentence[:30]}...", flush=True)
                
                # Use a unique path for each sentence to avoid collisions
                sentence_path = f"{utterance_path}_s{i}.wav"
                
                started_at = time.monotonic()
                tts_path = await synthesize_speech(
                    text=sentence,
                    utterance_path=sentence_path
                )
                print(
                    f"[SENTENCE {i+1} SYNTH DONE] seconds={time.monotonic() - started_at:.2f}",
                    flush=True,
                )
                
                if tts_path:
                    try:
                        import wave
                        with wave.open(tts_path, "rb") as wf:
                            source_sample_rate = wf.getframerate()
                            channels = wf.getnchannels()
                            sample_width = wf.getsampwidth()
                            frames_per_chunk = max(1, source_sample_rate // 50)
                            rate_state = None
                            data = wf.readframes(frames_per_chunk)
                            while data:
                                if sample_width != 2:
                                    data = audioop.lin2lin(data, sample_width, 2)

                                if channels == 2:
                                    data = audioop.tomono(data, 2, 0.5, 0.5)
                                elif channels != 1:
                                    raise ValueError(f"Unsupported TTS channel count: {channels}")

                                if source_sample_rate != playback_sample_rate:
                                    data, rate_state = audioop.ratecv(
                                        data,
                                        2,
                                        1,
                                        source_sample_rate,
                                        playback_sample_rate,
                                        rate_state,
                                    )

                                sent = await safe_send(websocket, send_lock, data)
                                if not sent:
                                    break

                                await asyncio.sleep(len(data) / (2 * playback_sample_rate))
                                data = wf.readframes(frames_per_chunk)
                                
                        print(f"[SENTENCE {i+1} DONE] Streamed.", flush=True)
                    except Exception as e:
                        print(f"[SENTENCE {i+1} ERROR] {e}", flush=True)
                
                # Optional: Add a natural pause between sentences
                await asyncio.sleep(0.2)

            print(f"[TTS STREAM DONE] session={session_id}", flush=True)
        except asyncio.CancelledError:
            print(f"[PLAYBACK CANCELLED] session={session_id}", flush=True)
            raise
        except Exception as e:
            print(f"[PLAYBACK ERROR] session={session_id}, error={e}", flush=True)

# ============================================================
# ASR / RAG Handling
# ============================================================

async def handle_completed_utterance(
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session_id: str,
    utterance_path: str,
    session_state: SessionState,
    phone_number: str = "Unknown",
    playback_sample_rate: int = 16000,
):
    """
    Runs ASR for one completed utterance.

    This is started with asyncio.create_task(...), so it does not block
    the VAD loop. VAD can continue listening while ASR runs.
    """

    try:
        sent = await safe_send(
            websocket,
            send_lock,
            {
                "event": "asr_started",
                "session_id": session_id,
                "utterance_path": utterance_path,
                "message": "ASR is transcribing the saved utterance",
            },
        )

        if not sent:
            print(
                f"[ASR SKIPPED] WebSocket closed before ASR start event. "
                f"session={session_id}, file={utterance_path}",
                flush=True,
            )
            return

        print(
            f"[ASR STARTED] session={session_id}, file={utterance_path}",
            flush=True,
        )

        async with ASR_SEMAPHORE:
            asr_result = await transcribe_utterance_file(
                utterance_path=utterance_path,
                language="am",
            )

        await safe_send(
            websocket,
            send_lock,
            {
                "event": "asr_transcript",
                "session_id": session_id,
                "utterance_path": utterance_path,
                "transcript": asr_result.get("transcript"),
                "transcript_raw": asr_result.get("raw_transcript"),
                "structured_transcript": asr_result.get("structured_transcript"),
                "transcript_fix_backend": asr_result.get("transcript_fix_backend"),
                "confidence": asr_result.get("confidence"),
                "acoustic_confidence": asr_result.get("acoustic_confidence"),
                "fuzzy": asr_result.get("fuzzy"),
                "engine": asr_result.get("engine"),
                "audio_id": asr_result.get("audio_id"),
                "needs_confirmation": asr_result.get("needs_confirmation"),
                "confirmation_prompt": asr_result.get("confirmation_prompt"),
                "unusual_words": asr_result.get("unusual_words"),
                "message": "ASR transcription completed",
            },
        )

        print(
            f"[ASR DONE] session={session_id}, "
            f"file={utterance_path}, "
            f"engine={asr_result.get('engine')}, "
            f"confidence={asr_result.get('confidence')}, "
            f"transcript={asr_result.get('transcript')}",
            flush=True,
        )

        # ── RAG Step ────────────────────────────────────────────────────────
        transcript = asr_result.get("transcript")
        if not transcript:
            return

        confirmed_pending_transcript = False
        pending_transcript = session_state.pending_confirmation_transcript
        if pending_transcript:
            confirmation_reply = classify_confirmation_reply_from_asr(asr_result)
            if confirmation_reply == "yes":
                pending_meta = session_state.pending_confirmation_asr_meta or {}
                transcript = best_transcript_from_asr(
                    {**pending_meta, "transcript": pending_transcript}
                )
                transcript = normalize_farmer_query(transcript)
                confirmed_pending_transcript = True
                print(
                    f"[ASR CONFIRMED] session={session_id}, transcript={transcript!r}",
                    flush=True,
                )
                session_state.pending_confirmation_transcript = None
                session_state.pending_confirmation_asr_meta = None
                session_state.pending_confirmation_utterance_path = None
                asr_result = apply_normalized_transcript_to_asr_result(
                    {
                        **pending_meta,
                        "transcript": transcript,
                        "text": transcript,
                        "final_transcript": transcript,
                        "structured_transcript": transcript,
                        "needs_confirmation": False,
                        "confirmation_reply": "yes",
                    }
                )
            elif confirmation_reply == "no":
                session_state.pending_confirmation_transcript = None
                session_state.pending_confirmation_asr_meta = None
                session_state.pending_confirmation_utterance_path = None
                rag_answer = "እሺ፣ እባክዎን ጥያቄዎን በግልጽ እንደገና ይናገሩ።"
                print(
                    f"[ASR CONFIRMATION REJECTED] session={session_id}, reply={transcript!r}",
                    flush=True,
                )
                await safe_send(
                    websocket,
                    send_lock,
                    {
                        "event": "rag_answer",
                        "session_id": session_id,
                        "utterance_path": utterance_path,
                        "response": rag_answer,
                        "references": [],
                        "trust": {"grounding": "asr_confirmation"},
                        "meta": {"reason": "asr_confirmation_rejected"},
                        "message": "ASR confirmation rejected; asking user to repeat",
                    },
                )
                await safe_send(
                    websocket,
                    send_lock,
                    {
                        "event": "tts_started",
                        "session_id": session_id,
                        "utterance_path": utterance_path,
                        "message": "Synthesizing voice response...",
                    },
                )
                session_state.playback_task = asyncio.create_task(
                    play_advisor_response(
                        websocket=websocket,
                        send_lock=send_lock,
                        session_id=session_id,
                        utterance_path=utterance_path,
                        rag_answer=rag_answer,
                        playback_sample_rate=playback_sample_rate,
                    )
                )
                return
            else:
                rag_answer = "ይቅርታ፣ ማረጋገጫዎን አልተረዳሁም። እባክዎ አዎ ወይም አይ ብቻ ይበሉ።"
                print(
                    f"[ASR CONFIRMATION UNCLEAR] session={session_id}, reply={transcript!r}",
                    flush=True,
                )
                await safe_send(
                    websocket,
                    send_lock,
                    {
                        "event": "rag_answer",
                        "session_id": session_id,
                        "utterance_path": utterance_path,
                        "response": rag_answer,
                        "references": [],
                        "trust": {"grounding": "asr_confirmation"},
                        "meta": {"reason": "asr_confirmation_unclear"},
                        "message": "ASR confirmation reply was unclear",
                    },
                )
                await safe_send(
                    websocket,
                    send_lock,
                    {
                        "event": "tts_started",
                        "session_id": session_id,
                        "utterance_path": utterance_path,
                        "message": "Synthesizing voice response...",
                    },
                )
                session_state.playback_task = asyncio.create_task(
                    play_advisor_response(
                        websocket=websocket,
                        send_lock=send_lock,
                        session_id=session_id,
                        utterance_path=utterance_path,
                        rag_answer=rag_answer,
                        playback_sample_rate=playback_sample_rate,
                    )
                )
                return

        asr_result = apply_normalized_transcript_to_asr_result(asr_result)
        transcript = asr_result.get("transcript")
        force_rag_for_expert_request = _looks_like_expert_handoff_request(transcript)

        from transcript_quality import GIBBERISH_REPLY_AM, is_asr_gibberish

        conf = asr_result.get("confidence")
        try:
            conf_f = float(conf) if conf is not None else None
        except (TypeError, ValueError):
            conf_f = None
        if (
            not confirmed_pending_transcript
            and not force_rag_for_expert_request
            and is_asr_gibberish(transcript, conf_f)
        ):
            rag_answer = GIBBERISH_REPLY_AM
            print(
                f"[ASR GIBBERISH] session={session_id}, transcript={transcript!r}, conf={conf_f}",
                flush=True,
            )
            await safe_send(
                websocket,
                send_lock,
                {
                    "event": "rag_answer",
                    "session_id": session_id,
                    "utterance_path": utterance_path,
                    "response": rag_answer,
                    "references": [],
                    "message": "Low-confidence ASR; asking user to repeat in Amharic",
                },
            )
            await safe_send(
                websocket,
                send_lock,
                {
                    "event": "tts_started",
                    "session_id": session_id,
                    "utterance_path": utterance_path,
                    "message": "Synthesizing voice response...",
                },
            )
            session_state.playback_task = asyncio.create_task(
                play_advisor_response(
                    websocket=websocket,
                    send_lock=send_lock,
                    session_id=session_id,
                    utterance_path=utterance_path,
                    rag_answer=rag_answer,
                    playback_sample_rate=playback_sample_rate,
                )
            )
            return

        flow_decision = vad_flow_decision(asr_result)
        if (
            not confirmed_pending_transcript
            and not force_rag_for_expert_request
            and flow_decision == "reprompt"
        ):
            rag_answer = CLARIFY_REPROMPT_AM
            print(
                f"[ASR CLARIFY REPROMPT] session={session_id}, "
                f"transcript={transcript!r}, conf={conf_f}",
                flush=True,
            )
            await safe_send(
                websocket,
                send_lock,
                {
                    "event": "rag_answer",
                    "session_id": session_id,
                    "utterance_path": utterance_path,
                    "response": rag_answer,
                    "references": [],
                    "trust": {"grounding": "vad_clarify"},
                    "meta": {"reason": "vad_clarify_reprompt"},
                    "message": "Utterance unclear; asking user to repeat",
                },
            )
            await safe_send(
                websocket,
                send_lock,
                {
                    "event": "tts_started",
                    "session_id": session_id,
                    "utterance_path": utterance_path,
                    "message": "Synthesizing voice response...",
                },
            )
            session_state.playback_task = asyncio.create_task(
                play_advisor_response(
                    websocket=websocket,
                    send_lock=send_lock,
                    session_id=session_id,
                    utterance_path=utterance_path,
                    rag_answer=rag_answer,
                    playback_sample_rate=playback_sample_rate,
                )
            )
            return

        if (
            vad_confirmation_gate_enabled()
            and flow_decision == "confirm"
            and not confirmed_pending_transcript
            and not force_rag_for_expert_request
        ):
            session_state.pending_confirmation_transcript = transcript
            session_state.pending_confirmation_asr_meta = {
                "raw_transcript": asr_result.get("raw_transcript"),
                "final_transcript": asr_result.get("final_transcript"),
                "structured_transcript": asr_result.get("structured_transcript"),
                "domain_corrected_transcript": asr_result.get("domain_corrected_transcript"),
                "confidence": asr_result.get("confidence"),
                "acoustic_confidence": asr_result.get("acoustic_confidence"),
                "fuzzy": asr_result.get("fuzzy"),
                "transcript_fix_backend": asr_result.get("transcript_fix_backend"),
                "needs_confirmation": False,
                "confirmation_prompt": asr_result.get("confirmation_prompt"),
                "unusual_words": asr_result.get("unusual_words"),
                "engine": asr_result.get("engine"),
                "audio_id": asr_result.get("audio_id"),
            }
            session_state.pending_confirmation_utterance_path = utterance_path
            rag_answer = build_asr_confirmation_prompt(
                transcript,
                asr_result.get("confirmation_prompt"),
            )
            print(
                f"[ASR CONFIRMATION] session={session_id}, transcript={transcript!r}, "
                f"decision={flow_decision}",
                flush=True,
            )
            await safe_send(
                websocket,
                send_lock,
                {
                    "event": "rag_answer",
                    "session_id": session_id,
                    "utterance_path": utterance_path,
                    "response": rag_answer,
                    "references": [],
                    "trust": {"grounding": "asr_confirmation"},
                    "meta": {"reason": "asr_needs_confirmation"},
                    "message": "ASR requested transcript confirmation",
                },
            )
            await safe_send(
                websocket,
                send_lock,
                {
                    "event": "tts_started",
                    "session_id": session_id,
                    "utterance_path": utterance_path,
                    "message": "Synthesizing voice response...",
                },
            )
            session_state.playback_task = asyncio.create_task(
                play_advisor_response(
                    websocket=websocket,
                    send_lock=send_lock,
                    session_id=session_id,
                    utterance_path=utterance_path,
                    rag_answer=rag_answer,
                    playback_sample_rate=playback_sample_rate,
                )
            )
            return

        await safe_send(
            websocket,
            send_lock,
            {
                "event": "rag_started",
                "session_id": session_id,
                "utterance_path": utterance_path,
                "message": "Retrieving answer from Knowledge Base...",
            },
        )

        rag_result = await get_rag_answer(
            text=transcript,
            session_id=session_id,
            phone_number=phone_number,
            asr_meta={
                "raw_transcript": asr_result.get("raw_transcript"),
                "final_transcript": asr_result.get("final_transcript"),
                "structured_transcript": asr_result.get("structured_transcript"),
                "confidence": asr_result.get("confidence"),
                "acoustic_confidence": asr_result.get("acoustic_confidence"),
                "fuzzy": asr_result.get("fuzzy"),
                "transcript_fix_backend": asr_result.get("transcript_fix_backend"),
                "needs_confirmation": False,
                "confirmation_handled_by_vad": True,
                "confirmation_prompt": asr_result.get("confirmation_prompt"),
                "unusual_words": asr_result.get("unusual_words"),
                "engine": asr_result.get("engine"),
                "audio_id": asr_result.get("audio_id"),
                "vad_normalized_transcript": asr_result.get("vad_normalized_transcript"),
            },
        )

        rag_answer = rag_result.get("response")

        await safe_send(
            websocket,
            send_lock,
            {
                "event": "rag_answer",
                "session_id": session_id,
                "utterance_path": utterance_path,
                "response": rag_answer,
                "references": rag_result.get("references"),
                "trust": rag_result.get("trust"),
                "meta": rag_result.get("meta"),
                "best_distance": rag_result.get("best_distance"),
                "message": "RAG answer generated",
            },
        )

        print(
            f"[RAG DONE] session={session_id}, "
            f"file={utterance_path}, "
            f"response={rag_answer[:50]}...",
            flush=True,
        )

        # ── TTS Step ─────────────────────────────────────────────────────────
        if not rag_answer:
            return

        await safe_send(
            websocket,
            send_lock,
            {
                "event": "tts_started",
                "session_id": session_id,
                "utterance_path": utterance_path,
                "message": "Synthesizing voice response...",
            },
        )

        print(f"[TTS QUEUED] text_len={len(rag_answer)}, path={utterance_path}", flush=True)
        # ── Start Playback in background ──
        # We store it in session_state so the VAD loop can cancel it if barge-in occurs.
        session_state.playback_task = asyncio.create_task(
            play_advisor_response(
                websocket=websocket,
                send_lock=send_lock,
                session_id=session_id,
                utterance_path=utterance_path,
                rag_answer=rag_answer,
                playback_sample_rate=playback_sample_rate,
            )
        )

    except Exception as e:
        import traceback
        print(f"[FATAL ERROR in handle_completed_utterance]: {e}", flush=True)
        traceback.print_exc()
        
        await safe_send(
            websocket,
            send_lock,
            {
                "event": "asr_error",
                "session_id": session_id,
                "utterance_path": utterance_path,
                "error": str(e),
                "message": "Processing failed",
            },
        )

        print(
            f"[ASR ERROR] session={session_id}, "
            f"file={utterance_path}, "
            f"error={e}",
            flush=True,
        )


def start_asr_task(
    active_asr_tasks: set,
    websocket: WebSocket,
    send_lock: asyncio.Lock,
    session_id: str,
    utterance_path: str,
    session_state: SessionState,
    phone_number: str = "Unknown",
    playback_sample_rate: int = 16000,
):
    """
    Start ASR in the background.

    The task is stored in active_asr_tasks so it remains referenced until
    it completes.
    """

    task = asyncio.create_task(
        handle_completed_utterance(
            websocket=websocket,
            send_lock=send_lock,
            session_id=session_id,
            utterance_path=utterance_path,
            session_state=session_state,
            phone_number=phone_number,
            playback_sample_rate=playback_sample_rate,
        )
    )

    active_asr_tasks.add(task)

    def cleanup_task(done_task: asyncio.Task):
        active_asr_tasks.discard(done_task)

        try:
            exc = done_task.exception()
            if exc:
                print(
                    f"[ASR TASK ERROR] session={session_id}, error={exc}",
                    flush=True,
                )
        except asyncio.CancelledError:
            pass

    task.add_done_callback(cleanup_task)


# ============================================================
# VAD WebSocket Endpoint
# ============================================================

@app.websocket("/ws/vad")
async def vad_websocket(
    websocket: WebSocket,
    session_id: str = Query(...),
    sample_rate: int = Query(default=16000),
    phone_number: str = Query(default="Unknown"),
):
    await websocket.accept()

    send_lock = asyncio.Lock()
    active_asr_tasks = set()
    session_state = SessionState()

    output_dir = os.getenv("VAD_UTTERANCES_DIR", "utterances")

    vad = SileroStreamingVAD(
        session_id=session_id,
        sample_rate=sample_rate,
        threshold=VAD_THRESHOLD,
        candidate_threshold=VAD_CANDIDATE_THRESHOLD,
        continue_threshold=VAD_CONTINUE_THRESHOLD,
        energy_threshold=VAD_ENERGY_THRESHOLD,
        energy_min_speech_prob=VAD_ENERGY_MIN_SPEECH_PROB,
        min_speech_start_ms=VAD_MIN_SPEECH_MS,
        speech_start_gap_ms=VAD_SPEECH_START_GAP_MS,
        speech_end_silence_ms=VAD_END_SILENCE_MS,
        speech_pad_ms=160,
        output_dir=output_dir,
    )

    await safe_send(
        websocket,
        send_lock,
        {
            "event": "vad_ready",
            "session_id": session_id,
            "sample_rate": sample_rate,
            "message": "Silero VAD is ready",
        },
    )

    print(
        f"[VAD READY] session={session_id}, "
        f"sample_rate={sample_rate}, "
        f"output_dir={output_dir}",
        flush=True,
    )

    chunk_count = 0
    total_audio_bytes = 0

    try:
        while True:
            message = await websocket.receive()

            # ============================================================
            # Binary audio message
            # ============================================================

            if "bytes" in message and message["bytes"] is not None:
                pcm_chunk = message["bytes"]

                if pcm_chunk:
                    chunk_count += 1
                    total_audio_bytes += len(pcm_chunk)

                    if VAD_AUDIO_LOG_EVERY > 0 and chunk_count % VAD_AUDIO_LOG_EVERY == 0:
                        print(
                            f"[VAD AUDIO RECEIVED] session={session_id}, "
                            f"chunks={chunk_count}, "
                            f"bytes={total_audio_bytes}",
                            flush=True,
                        )

                events = vad.process_pcm_chunk(pcm_chunk)

                for event in events:
                    event_name = event.get("event")
                    utterance_path = event.get("utterance_path")

                    await safe_send(
                        websocket,
                        send_lock,
                        {
                            "event": event_name,
                            "session_id": session_id,
                            "timestamp": event.get("timestamp"),
                            "utterance_path": utterance_path,
                            "duration_seconds": event.get("duration_seconds"),
                            "speech_probability": event.get("speech_probability"),
                            "rms_energy": event.get("rms_energy"),
                        },
                    )

                    if event_name == "speech_started":
                        print(
                            f"[SPEECH STARTED] session={session_id}",
                            flush=True,
                        )
                        # Barge-in: Cancel current advisor playback if they were talking
                        if session_state.playback_task and not session_state.playback_task.done():
                            print(f"[BARGE-IN] Interrupting advisor playback", flush=True)
                            session_state.playback_task.cancel()

                    elif event_name == "speech_ended":
                        print(
                            f"[SPEECH ENDED] session={session_id}, "
                            f"file={utterance_path}",
                            flush=True,
                        )

                        if utterance_path:
                            start_asr_task(
                                active_asr_tasks=active_asr_tasks,
                                websocket=websocket,
                                send_lock=send_lock,
                                session_id=session_id,
                                utterance_path=utterance_path,
                                session_state=session_state,
                                phone_number=phone_number,
                                playback_sample_rate=sample_rate,
                            )

            # ============================================================
            # Text control message
            # ============================================================

            elif "text" in message and message["text"] is not None:
                text = message["text"]

                try:
                    data = json.loads(text)

                    if data.get("event") == "reset":
                        vad.reset()

                        await safe_send(
                            websocket,
                            send_lock,
                            {
                                "event": "reset_done",
                                "session_id": session_id,
                            },
                        )

                    elif data.get("event") == "end_session":
                        utterance_path = vad.finalize()

                        if utterance_path:
                            await safe_send(
                                websocket,
                                send_lock,
                                {
                                    "event": "speech_ended",
                                    "session_id": session_id,
                                    "utterance_path": utterance_path,
                                    "duration_seconds": None,
                                    "message": "Final utterance saved on session end",
                                },
                            )

                            print(
                                f"[SPEECH ENDED ON CLOSE] "
                                f"session={session_id}, "
                                f"file={utterance_path}",
                                flush=True,
                            )

                            start_asr_task(
                                active_asr_tasks=active_asr_tasks,
                                websocket=websocket,
                                send_lock=send_lock,
                                session_id=session_id,
                                utterance_path=utterance_path,
                                session_state=session_state,
                                phone_number=phone_number,
                                playback_sample_rate=sample_rate,
                            )

                        if active_asr_tasks:
                            await asyncio.gather(
                                *active_asr_tasks,
                                return_exceptions=True,
                            )

                        break

                except json.JSONDecodeError:
                    if text == "END":
                        utterance_path = vad.finalize()

                        if utterance_path:
                            await safe_send(
                                websocket,
                                send_lock,
                                {
                                    "event": "speech_ended",
                                    "session_id": session_id,
                                    "utterance_path": utterance_path,
                                    "duration_seconds": None,
                                    "message": "Final utterance saved on END message",
                                },
                            )

                            print(
                                f"[SPEECH ENDED ON END] "
                                f"session={session_id}, "
                                f"file={utterance_path}",
                                flush=True,
                            )

                            start_asr_task(
                                active_asr_tasks=active_asr_tasks,
                                websocket=websocket,
                                send_lock=send_lock,
                                session_id=session_id,
                                utterance_path=utterance_path,
                                session_state=session_state,
                                phone_number=phone_number,
                                playback_sample_rate=sample_rate,
                            )

                        if active_asr_tasks:
                            await asyncio.gather(
                                *active_asr_tasks,
                                return_exceptions=True,
                            )

                        break

    except WebSocketDisconnect:
        print(f"[VAD DISCONNECTED] session={session_id}", flush=True)

    finally:
        for task in list(active_asr_tasks):
            if not task.done():
                task.cancel()

        if active_asr_tasks:
            await asyncio.gather(
                *active_asr_tasks,
                return_exceptions=True,
            )

        try:
            await websocket.close()
        except Exception:
            pass

        print(f"[VAD CLOSED] session={session_id}", flush=True)