from datetime import datetime
import uuid

from backend.database import SessionLocal
from backend.models import CallSession


def create_session(caller_id: str | None = None) -> dict:
    db = SessionLocal()

    try:
        session_id = str(uuid.uuid4())

        call_session = CallSession(
            session_id=session_id,
            caller_id=caller_id,
            start_time=datetime.utcnow(),
            status="active"
        )

        db.add(call_session)
        db.commit()
        db.refresh(call_session)

        return {
            "session_id": call_session.session_id,
            "caller_id": call_session.caller_id,
            "start_time": call_session.start_time.isoformat(),
            "status": call_session.status
        }

    finally:
        db.close()


def end_session(session_id: str, audio_file: str | None = None) -> dict:
    db = SessionLocal()

    try:
        call_session = db.query(CallSession).filter(
            CallSession.session_id == session_id
        ).first()

        if not call_session:
            raise ValueError("Session not found")

        end_time = datetime.utcnow()
        duration = (end_time - call_session.start_time).total_seconds()

        call_session.end_time = end_time
        call_session.duration_seconds = round(duration, 2)
        call_session.audio_file_path = audio_file
        call_session.status = "ended"

        db.commit()
        db.refresh(call_session)

        return {
            "session_id": call_session.session_id,
            "caller_id": call_session.caller_id,
            "start_time": call_session.start_time.isoformat(),
            "end_time": call_session.end_time.isoformat(),
            "duration_seconds": call_session.duration_seconds,
            "audio_file_path": call_session.audio_file_path,
            "status": call_session.status
        }

    finally:
        db.close()