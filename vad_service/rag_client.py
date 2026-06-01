import os
import httpx
import logging

logger = logging.getLogger("rag_client")

RAG_SERVICE_URL = os.getenv(
    "RAG_SERVICE_URL",
    "http://logic_service:8000",
)


async def get_rag_answer(
    text: str,
    session_id: str,
    phone_number: str = "Unknown",
    asr_meta: dict | None = None,
) -> dict:
    url = f"{RAG_SERVICE_URL.rstrip('/')}/rag/answer"

    payload = {
        "text": text,
        "session_id": session_id,
        "phone_number": phone_number,
        "voice_mode": True,
    }
    if asr_meta:
        payload["asr"] = asr_meta

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()
    except Exception as e:
        logger.error("RAG request failed: %s", e)
        return {
            "response": "ይቅርታ፣ መልስ ማግኘት አልተቻለም። እባክዎ እንደገና ይሞክሩ።",
            "references": [],
            "meta": {"strategy": "FALLBACK", "error": str(e)},
        }
