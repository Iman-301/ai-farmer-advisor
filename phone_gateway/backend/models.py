from sqlalchemy import Column, String, DateTime, Float, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime

from backend.database import Base


class Caller(Base):
    __tablename__ = "callers"

    caller_id = Column(String, primary_key=True, index=True)
    full_name = Column(String, nullable=False)
    phone_number = Column(String, unique=True, nullable=False, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen_at = Column(DateTime, default=datetime.utcnow)

    calls = relationship("CallSession", back_populates="caller")


class CallSession(Base):
    __tablename__ = "call_sessions"

    session_id = Column(String, primary_key=True, index=True)

    caller_id = Column(String, ForeignKey("callers.caller_id"), nullable=True)

    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)

    audio_file_path = Column(String, nullable=True)
    status = Column(String, default="active")

    caller = relationship("Caller", back_populates="calls")