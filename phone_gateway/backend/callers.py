from datetime import datetime
import uuid

from backend.database import SessionLocal
from backend.models import Caller


def create_or_get_caller(full_name: str, phone_number: str) -> dict:
    db = SessionLocal()

    try:
        phone_number = phone_number.strip()
        full_name = full_name.strip()

        caller = db.query(Caller).filter(
            Caller.phone_number == phone_number
        ).first()

        if caller:
            caller.full_name = full_name
            caller.last_seen_at = datetime.utcnow()
        else:
            caller = Caller(
                caller_id=str(uuid.uuid4()),
                full_name=full_name,
                phone_number=phone_number,
                created_at=datetime.utcnow(),
                last_seen_at=datetime.utcnow()
            )
            db.add(caller)

        db.commit()
        db.refresh(caller)

        return {
            "caller_id": caller.caller_id,
            "full_name": caller.full_name,
            "phone_number": caller.phone_number,
            "created_at": caller.created_at.isoformat(),
            "last_seen_at": caller.last_seen_at.isoformat()
        }

    finally:
        db.close()