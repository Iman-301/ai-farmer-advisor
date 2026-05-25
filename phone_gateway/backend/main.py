import asyncio
import json
import os
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from backend.database import Base, engine, SessionLocal
from backend.models import Caller
from backend.sessions import create_session, end_session
from backend.recorder import AudioRecorder
from backend.callers import create_or_get_caller

from backend.monitor_state import (
    start_call_monitor,
    update_audio_stats,
    update_vad_status,
    add_utterance,
    end_call_monitor,
    add_event,
    get_monitor_state,
    get_monitor_events,
    get_recent_calls,
)


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Phone Browser Telephony Gateway")

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

VAD_WS_BASE_URL = os.getenv(
    "VAD_WS_BASE_URL",
    "ws://vad-service:8010/ws/vad"
)
VAD_UTTERANCES_DIR = Path(
    os.getenv("VAD_UTTERANCES_DIR", "/app/utterances")
)
LOGIC_SERVICE_URL = os.getenv(
    "LOGIC_SERVICE_URL",
    "http://host.docker.internal:8002",
).rstrip("/")
VOICE_ASK_ENABLED = os.getenv("VOICE_ASK_ENABLED", "1").strip().lower() in {
    "1",
    "true",
    "yes",
}


class CallerRegisterRequest(BaseModel):
    full_name: str
    phone_number: str


def get_caller_details(caller_id: str | None):
    if not caller_id:
        return None, None

    db = SessionLocal()

    try:
        caller = db.query(Caller).filter(
            Caller.caller_id == caller_id
        ).first()

        if not caller:
            return None, None

        return caller.full_name, caller.phone_number

    finally:
        db.close()


def calculate_pcm16_audio_level(pcm_bytes: bytes) -> float:
    """
    Calculate rough audio level from PCM16 mono audio.
    Returns a value between 0.0 and 1.0.
    """
    if not pcm_bytes:
        return 0.0

    try:
        import array

        samples = array.array("h")
        samples.frombytes(pcm_bytes)

        if not samples:
            return 0.0

        total = 0.0

        for sample in samples:
            normalized = sample / 32768.0
            total += normalized * normalized

        rms = (total / len(samples)) ** 0.5

        # Boost for visual display
        visual_level = min(1.0, rms * 8)

        return round(visual_level, 4)

    except Exception:
        return 0.0


@app.get("/")
def serve_frontend():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/monitor")
def serve_monitor():
    return FileResponse(FRONTEND_DIR / "monitor.html")


@app.get("/vad-test")
def serve_vad_test():
    """Standalone VAD tester: mic → Silero VAD → events (no STT/LLM/TTS)."""
    return FileResponse(FRONTEND_DIR / "vad_test.html")


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "phone-gateway"
    }


@app.get("/api/monitor/state")
def api_monitor_state():
    return get_monitor_state()


@app.get("/api/monitor/events")
def api_monitor_events():
    return {
        "events": get_monitor_events()
    }


@app.get("/api/monitor/calls")
def api_monitor_calls():
    return {
        "calls": get_recent_calls()
    }


@app.post("/api/callers/register")
def register_caller(payload: CallerRegisterRequest):
    caller = create_or_get_caller(
        full_name=payload.full_name,
        phone_number=payload.phone_number
    )

    return {
        "message": "Caller registered",
        "caller": caller
    }


def resolve_utterance_path(utterance_path: str | None) -> Path | None:
    if not utterance_path:
        return None

    candidate = Path(utterance_path)
    if candidate.is_file():
        return candidate

    by_name = VAD_UTTERANCES_DIR / candidate.name
    if by_name.is_file():
        return by_name

    # VAD returns paths like "utterances/<session>_utterance_001.wav"
    stripped = candidate.as_posix().removeprefix("utterances/").lstrip("/")
    nested = VAD_UTTERANCES_DIR / stripped
    if nested.is_file():
        return nested

    return None


async def run_voice_ask_pipeline(
    *,
    utterance_path: str | None,
    session_id: str,
    caller_phone: str | None,
    browser_ws: WebSocket,
) -> None:
    """
    After Silero VAD emits speech_ended, send the trimmed WAV through
    logic_service /voice/ask (STT -> RAG/LLM -> TTS) and relay JSON to browser.
    """
    if not VOICE_ASK_ENABLED:
        return

    wav_path = resolve_utterance_path(utterance_path)
    if not wav_path:
        print(
            f"[VOICE ASK SKIP] session={session_id}, "
            f"missing utterance file: {utterance_path}",
            flush=True,
        )
        add_event("voice_ask_skipped", {
            "session_id": session_id,
            "utterance_path": utterance_path,
            "error": "utterance file not found",
        })
        return

    try:
        await browser_ws.send_json({
            "type": "advisor_processing",
            "session_id": session_id,
            "message": "Processing your question...",
        })
    except Exception:
        return

    try:
        audio_bytes = wav_path.read_bytes()
    except OSError as exc:
        print(f"[VOICE ASK READ ERROR] session={session_id}, error={exc}", flush=True)
        add_event("voice_ask_read_error", {
            "session_id": session_id,
            "utterance_path": str(wav_path),
            "error": str(exc),
        })
        return

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0, connect=10.0)) as client:
            response = await client.post(
                f"{LOGIC_SERVICE_URL}/voice/ask",
                files={
                    "audio_file": (
                        wav_path.name,
                        audio_bytes,
                        "audio/wav",
                    )
                },
                data={
                    "phone_number": caller_phone or "Unknown",
                    "session_id": session_id,
                    "return_audio": "false",
                },
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        print(f"[VOICE ASK ERROR] session={session_id}, error={exc}", flush=True)
        add_event("voice_ask_error", {
            "session_id": session_id,
            "utterance_path": str(wav_path),
            "error": str(exc),
        })
        try:
            await browser_ws.send_json({
                "type": "advisor_error",
                "session_id": session_id,
                "message": "Could not get an answer. Please try again.",
            })
        except Exception:
            pass
        return

    advisor_message = {
        "type": "advisor_response",
        "session_id": session_id,
        "transcript": payload.get("transcript") or "",
        "response": payload.get("response") or "",
        "intent": payload.get("intent") or "",
        "stt_confidence": payload.get("stt_confidence"),
        "answer_source": payload.get("answer_source"),
        "audio_base64": payload.get("audio_base64") or "",
        "references": payload.get("references") or [],
    }

    add_event("advisor_response", {
        "session_id": session_id,
        "transcript": advisor_message["transcript"],
        "intent": advisor_message["intent"],
        "stt_confidence": advisor_message["stt_confidence"],
    })

    print(
        f"[VOICE ASK OK] session={session_id}, "
        f"transcript={advisor_message['transcript'][:80]!r}",
        flush=True,
    )

    try:
        await browser_ws.send_json(advisor_message)
    except Exception:
        pass


async def forward_vad_events_to_browser(
    vad_ws,
    browser_ws: WebSocket,
    *,
    session_id: str,
    caller_phone: str | None,
):
    """
    Receive VAD events from vad-service.
    Update backend monitor state.
    Also forward VAD events to the caller browser for simple status updates.
    On speech_ended, run the STT/RAG/TTS pipeline via logic_service.
    """

    try:
        async for message in vad_ws:
            try:
                data = json.loads(message)
            except Exception:
                data = {
                    "event": "vad_raw_message",
                    "message": message
                }

            print("[VAD EVENT]", data, flush=True)

            event_name = data.get("event")

            if event_name == "vad_ready":
                update_vad_status("vad_ready", data)

            elif event_name == "speech_started":
                update_vad_status("speech_started", data)

            elif event_name == "speech_ended":
                update_vad_status("speech_ended", data)

                add_utterance(
                    utterance_path=data.get("utterance_path"),
                    duration_seconds=data.get("duration_seconds"),
                    speech_probability=data.get("speech_probability"),
                )

                asyncio.create_task(
                    run_voice_ask_pipeline(
                        utterance_path=data.get("utterance_path"),
                        session_id=session_id,
                        caller_phone=caller_phone,
                        browser_ws=browser_ws,
                    )
                )

            else:
                add_event(event_name or "vad_event", data)

            try:
                await browser_ws.send_json(data)
            except Exception:
                break

    except Exception as exc:
        print("[VAD EVENT FORWARDER CLOSED]", exc, flush=True)
        add_event("vad_forwarder_closed", {"error": str(exc)})


@app.websocket("/ws/call")
async def call_websocket(
    websocket: WebSocket,
    caller_id: str | None = Query(default=None),
    audio_format: str = Query(default="pcm16"),
    sample_rate: int = Query(default=16000),
):
    await websocket.accept()

    session = create_session(caller_id=caller_id)
    session_id = session["session_id"]

    caller_name, caller_phone = get_caller_details(caller_id)

    recorder = AudioRecorder(session_id=session_id)

    start_call_monitor(
        session_id=session_id,
        caller_id=caller_id,
        caller_name=caller_name,
        caller_phone=caller_phone,
        sample_rate=sample_rate,
        audio_format=audio_format,
    )

    vad_url = (
        f"{VAD_WS_BASE_URL}"
        f"?session_id={session_id}"
        f"&sample_rate={sample_rate}"
    )

    vad_ws = None
    vad_event_task = None

    await websocket.send_json({
        "type": "session_started",
        "session_id": session_id,
        "caller_id": caller_id,
        "audio_format": audio_format,
        "sample_rate": sample_rate,
        "message": "Call session started"
    })

    print(
        f"[CALL STARTED] session={session_id}, "
        f"caller={caller_id}, "
        f"audio_format={audio_format}, "
        f"sample_rate={sample_rate}",
        flush=True
    )

    chunk_count = 0
    total_audio_bytes = 0

    try:
        vad_ws = await websockets.connect(vad_url)
        print(f"[VAD CONNECTED] {vad_url}", flush=True)

        vad_event_task = asyncio.create_task(
            forward_vad_events_to_browser(
                vad_ws,
                websocket,
                session_id=session_id,
                caller_phone=caller_phone,
            )
        )

        while True:
            message = await websocket.receive()

            if "bytes" in message:
                audio_chunk = message["bytes"]

                if not audio_chunk:
                    continue

                chunk_count += 1
                total_audio_bytes += len(audio_chunk)

                audio_level = calculate_pcm16_audio_level(audio_chunk)
                update_audio_stats(len(audio_chunk), audio_level=audio_level)

                if chunk_count % 20 == 0:
                    print(
                        f"[AUDIO CHUNKS] session={session_id}, "
                        f"chunks={chunk_count}, "
                        f"bytes={total_audio_bytes}, "
                        f"level={audio_level}",
                        flush=True
                    )

                recorder.write_chunk(audio_chunk)

                if vad_ws:
                    await vad_ws.send(audio_chunk)

            elif "text" in message:
                text = message["text"]

                if text == "END_CALL":
                    break

    except WebSocketDisconnect:
        print(f"[BROWSER DISCONNECTED] session={session_id}", flush=True)
        add_event("browser_disconnected", {
            "session_id": session_id
        })

    except Exception as exc:
        print(f"[CALL ERROR] session={session_id}, error={exc}", flush=True)
        add_event("call_error", {
            "session_id": session_id,
            "error": str(exc)
        })

        try:
            await websocket.send_json({
                "type": "error",
                "message": str(exc)
            })
        except Exception:
            pass

    finally:
        if vad_ws:
            try:
                await vad_ws.send(json.dumps({"event": "end_session"}))
                await vad_ws.close()
            except Exception:
                pass

        if vad_event_task:
            vad_event_task.cancel()

        audio_file = recorder.close()
        ended_session = end_session(session_id, audio_file=audio_file)

        end_call_monitor(audio_file_path=audio_file)

        print(f"[CALL ENDED] {ended_session}", flush=True)

        try:
            await websocket.send_json({
                "type": "session_ended",
                "session": ended_session
            })
        except Exception:
            pass