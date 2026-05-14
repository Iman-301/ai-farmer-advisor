"""
Admin REST API — all dashboard endpoints for the frontend microservice.
Uses in-memory Bearer token sessions backed by bcrypt auth against admin_users DB table.
"""
import secrets
import sqlite3
import uuid
import bcrypt
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from typing import Optional

from database import DB_PATH, collection

try:
    import rag_pg as _rag_pg
except ImportError:
    _rag_pg = None

router = APIRouter(prefix="/admin", tags=["admin"])

# ── In-memory session store  {token: {username, role}} ──────────────────────
_sessions: dict[str, dict] = {}


# ── Auth helpers ─────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str


class MarketPriceRequest(BaseModel):
    crop_name: str
    region: str
    price: float
    unit: str


class AlertRequest(BaseModel):
    target_region: str
    alert_message: str
    severity: str = "warning"


class KBRequest(BaseModel):
    intent: str
    response: str


def _get_session(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authentication required")
    token = authorization.split(" ", 1)[1]
    session = _sessions.get(token)
    if not session:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return session


def _require_admin(session: dict = Depends(_get_session)) -> dict:
    if session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return session


# ── Auth endpoints ────────────────────────────────────────────────────────────
@router.post("/login")
def login(req: LoginRequest):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT password_hash, role FROM admin_users WHERE username=?", (req.username,))
    row = c.fetchone()
    conn.close()

    if not row or not bcrypt.checkpw(req.password.encode(), row[0].encode()):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = secrets.token_hex(32)
    _sessions[token] = {"username": req.username, "role": row[1]}
    return {"token": token, "role": row[1], "username": req.username}


@router.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        _sessions.pop(authorization.split(" ", 1)[1], None)
    return {"status": "ok"}


# ── Dashboard stats ───────────────────────────────────────────────────────────
@router.get("/stats")
def get_stats(session: dict = Depends(_get_session)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("SELECT COUNT(*) FROM farmers")
    total_farmers = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM call_records WHERE date(timestamp) = date('now')")
    calls_today = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM call_records")
    total_calls = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM escalated_queries WHERE status='pending'")
    pending_escalations = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM alerts")
    total_alerts = c.fetchone()[0]

    # Calls per day — last 7 days
    c.execute("""
        SELECT date(timestamp) as day, COUNT(*) as count
        FROM call_records
        WHERE timestamp >= datetime('now', '-7 days')
        GROUP BY day ORDER BY day
    """)
    calls_per_day = [{"date": r[0], "count": r[1]} for r in c.fetchall()]

    # Escalation breakdown by status
    c.execute("SELECT status, COUNT(*) FROM escalated_queries GROUP BY status")
    esc_breakdown = {r[0]: r[1] for r in c.fetchall()}

    conn.close()
    kb_pg_chunks = None
    if _rag_pg and _rag_pg.kb_pg_enabled():
        try:
            _rag_pg.init_pg_schema()
            kb_pg_chunks = _rag_pg.count_approved_chunks()
        except Exception:
            kb_pg_chunks = None

    return {
        "total_farmers": total_farmers,
        "calls_today": calls_today,
        "total_calls": total_calls,
        "pending_escalations": pending_escalations,
        "total_alerts": total_alerts,
        "calls_per_day": calls_per_day,
        "escalation_breakdown": esc_breakdown,
        "kb_count": collection.count(),
        "kb_pg_chunks": kb_pg_chunks,
    }


# ── Farmers ───────────────────────────────────────────────────────────────────
@router.get("/farmers")
def list_farmers(session: dict = Depends(_get_session)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, phone_number, name, location, preferred_language, registered_at
        FROM farmers ORDER BY registered_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "phone_number": r[1], "name": r[2],
         "location": r[3], "language": r[4], "registered_at": r[5]}
        for r in rows
    ]


# ── Call Logs ─────────────────────────────────────────────────────────────────
@router.get("/calls")
def list_calls(session: dict = Depends(_get_session)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT c.id, c.session_id, c.phone_number, f.name,
               c.duration, c.timestamp, c.recording_path
        FROM call_records c
        LEFT JOIN farmers f ON c.phone_number = f.phone_number
        ORDER BY c.timestamp DESC LIMIT 100
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "session_id": r[1], "phone_number": r[2], "farmer_name": r[3],
         "duration": r[4], "timestamp": r[5], "recording_path": r[6]}
        for r in rows
    ]


# ── Escalation Queue ──────────────────────────────────────────────────────────
@router.get("/escalations")
def list_escalations(session: dict = Depends(_get_session)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, query, context, status, timestamp
        FROM escalated_queries ORDER BY timestamp DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "query": r[1], "context": r[2], "status": r[3], "timestamp": r[4]}
        for r in rows
    ]


@router.put("/escalations/{ticket_id}/resolve")
def resolve_escalation(ticket_id: int, session: dict = Depends(_get_session)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE escalated_queries SET status='resolved' WHERE id=?", (ticket_id,))
    conn.commit()
    conn.close()
    return {"status": "ok", "ticket_id": ticket_id}


# ── Market Prices ─────────────────────────────────────────────────────────────
@router.get("/market-prices")
def list_market_prices(session: dict = Depends(_get_session)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, crop_name, region, price, unit, updated_at
        FROM market_prices ORDER BY updated_at DESC
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "crop_name": r[1], "region": r[2],
         "price": r[3], "unit": r[4], "updated_at": r[5]}
        for r in rows
    ]


@router.post("/market-prices")
def add_market_price(req: MarketPriceRequest, session: dict = Depends(_require_admin)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO market_prices (crop_name, region, price, unit) VALUES (?, ?, ?, ?)",
        (req.crop_name, req.region, req.price, req.unit)
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


# ── Alerts ────────────────────────────────────────────────────────────────────
@router.get("/alerts")
def list_alerts(session: dict = Depends(_get_session)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT id, target_region, alert_message, severity, created_at
        FROM alerts ORDER BY created_at DESC LIMIT 50
    """)
    rows = c.fetchall()
    conn.close()
    return [
        {"id": r[0], "target_region": r[1], "alert_message": r[2],
         "severity": r[3], "created_at": r[4]}
        for r in rows
    ]


@router.post("/alerts")
def create_alert(req: AlertRequest, session: dict = Depends(_require_admin)):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "INSERT INTO alerts (target_region, alert_message, severity) VALUES (?, ?, ?)",
        (req.target_region, req.alert_message, req.severity)
    )
    conn.commit()
    conn.close()
    return {"status": "ok"}


# ── Knowledge Base ────────────────────────────────────────────────────────────
@router.get("/kb")
def list_kb(session: dict = Depends(_get_session)):
    if collection.count() == 0:
        return []
    result = collection.get(include=["documents", "metadatas"])
    return [
        {"id": doc_id, "intent": meta.get("intent", ""), "response": doc}
        for doc_id, doc, meta in zip(
            result["ids"], result["documents"], result["metadatas"]
        )
    ]


@router.post("/kb")
def add_kb(req: KBRequest, session: dict = Depends(_require_admin)):
    doc_id = f"kb_{uuid.uuid4()}"
    collection.add(
        documents=[req.response],
        metadatas=[{"intent": req.intent}],
        ids=[doc_id]
    )
    return {"status": "ok", "id": doc_id}


@router.delete("/kb/{entry_id}")
def delete_kb(entry_id: str, session: dict = Depends(_require_admin)):
    try:
        collection.delete(ids=[entry_id])
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=404, detail=str(e))
