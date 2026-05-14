import json

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query

from vad_engine import SileroStreamingVAD


app = FastAPI(title="Silero VAD Service")


@app.get("/health")
def health_check():
    return {
        "status": "ok",
        "service": "silero-vad-service"
    }


@app.websocket("/ws/vad")
async def vad_websocket(
    websocket: WebSocket,
    session_id: str = Query(...),
    sample_rate: int = Query(default=16000),
):
    await websocket.accept()

    vad = SileroStreamingVAD(
        session_id=session_id,
        sample_rate=sample_rate,
        threshold=0.5,
        min_speech_start_ms=120,
        speech_end_silence_ms=900,
        speech_pad_ms=200,
        output_dir="utterances"
    )

    await websocket.send_json({
        "event": "vad_ready",
        "session_id": session_id,
        "sample_rate": sample_rate,
        "message": "Silero VAD is ready"
    })

    print(f"[VAD READY] session={session_id}, sample_rate={sample_rate}")


    chunk_count = 0
    total_audio_bytes = 0

    try:
        while True:
            message = await websocket.receive()

            if "bytes" in message:
                pcm_chunk = message["bytes"]

                if pcm_chunk:
                    chunk_count += 1
                    total_audio_bytes += len(pcm_chunk)

                    if chunk_count % 20 == 0:
                        print(
                            f"[VAD AUDIO RECEIVED] session={session_id}, "
                            f"chunks={chunk_count}, "
                            f"bytes={total_audio_bytes}",
                            flush=True
                        )

                events = vad.process_pcm_chunk(pcm_chunk)

                for event in events:
                    await websocket.send_json({
                        "event": event["event"],
                        "session_id": session_id,
                        "timestamp": event.get("timestamp"),
                        "utterance_path": event.get("utterance_path"),
                        "duration_seconds": event.get("duration_seconds"),
                        "speech_probability": event.get("speech_probability")
                    })

                    if event["event"] == "speech_started":
                        print(f"[SPEECH STARTED] session={session_id}")

                    if event["event"] == "speech_ended":
                        print(
                            f"[SPEECH ENDED] session={session_id}, "
                            f"file={event.get('utterance_path')}"
                        )

            elif "text" in message:
                text = message["text"]

                try:
                    data = json.loads(text)

                    if data.get("event") == "reset":
                        vad.reset()
                        await websocket.send_json({
                            "event": "reset_done",
                            "session_id": session_id
                        })

                    elif data.get("event") == "end_session":
                        utterance_path = vad.finalize()

                        if utterance_path:
                            await websocket.send_json({
                                "event": "speech_ended",
                                "session_id": session_id,
                                "utterance_path": utterance_path,
                                "duration_seconds": None,
                                "message": "Final utterance saved on session end"
                            })

                            print(
                                f"[SPEECH ENDED ON CLOSE] session={session_id}, "
                                f"file={utterance_path}"
                            )

                        break

                except json.JSONDecodeError:
                    if text == "END":
                        break

    except WebSocketDisconnect:
        print(f"[VAD DISCONNECTED] session={session_id}")

    finally:
        try:
            await websocket.close()
        except Exception:
            pass

        print(f"[VAD CLOSED] session={session_id}")