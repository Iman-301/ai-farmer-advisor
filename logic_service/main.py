from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
import os
import re
import logging
import requests
import base64
import time
from typing import Optional
from database import (
    collection, add_to_escalation, log_conversation,
    get_conversation_history, get_market_price, register_farmer,
    get_farmer_profile, get_alerts_for_region, set_session_state,
    get_session_state, insert_call_record,
)
from nlu import analyze_intent, needs_slot_filling, normalize_ethiopic_input

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("logic_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        import rag_pg
        rag_pg.init_pg_schema()
    except Exception as exc:
        logger.warning("Postgres KB init skipped: %s", exc)
    yield


app = FastAPI(lifespan=lifespan)

# Mount admin REST API (used by the frontend microservice)
from admin_api import router as admin_router
app.include_router(admin_router)

# ── Config (externalized) ────────────────────────────────────────────────────
RAG_DISTANCE_THRESHOLD = float(os.environ.get("RAG_DISTANCE_THRESHOLD", "1.2"))
RAG_PG_MAX_L2_DISTANCE = float(os.environ.get("RAG_PG_MAX_L2_DISTANCE", "1.35"))
TTS_URL = os.environ.get("TTS_URL", "http://tts_service:8002/synthesize")
STT_URL = os.environ.get("STT_URL", "http://stt_service:8000/transcribe")
RAG_PG_CANDIDATE_K = int(os.environ.get("RAG_PG_CANDIDATE_K", "16"))
RAG_PG_FINAL_K = int(os.environ.get("RAG_PG_FINAL_K", "4"))
# FR04 / FR11: NLU below this is flagged in `advisory` (RAG still runs if agronomy signals exist).
NLU_LOW_CONFIDENCE_THRESHOLD = float(os.environ.get("NLU_LOW_CONFIDENCE_THRESHOLD", "0.38"))
# FR10: lexical score must be at least this to avoid escalation when vector distance is above threshold.
RAG_PG_ESCALATION_MIN_LEXICAL = int(os.environ.get("RAG_PG_ESCALATION_MIN_LEXICAL", "2"))


def compute_retrieval_confidence(hits: list, best_distance: float) -> float:
    """
    SRS FR10 / FR13: simple post-retrieval score (orthogonal to NLU rule confidence).
    Uses best L2 distance vs configured ceiling plus a small boost when top hits agree on one document.
    """
    if not hits:
        return 0.0
    try:
        d = float(best_distance)
    except (TypeError, ValueError):
        return 0.0
    denom = max(RAG_PG_MAX_L2_DISTANCE, 1e-6)
    dist_conf = max(0.0, min(1.0, 1.0 - (d / denom)))
    doc_ids = {h.get("document_id") for h in hits[:3] if h.get("document_id")}
    boost = 0.08 if len(doc_ids) == 1 else 0.0
    return round(min(0.95, dist_conf + boost), 3)


# ── LLM Initialization (optional) ────────────────────────────────────────────
#
# Best Amharic quality: use OpenAI-compatible chat models (e.g. gpt-4o-mini).
# Offline option: local GGUF via llama.cpp if you mount a model under DATA_DIR/models/.
#
# Env:
#   LLM_PROVIDER=none|openai|llama_cpp
#   OPENAI_API_KEY=...
#   OPENAI_MODEL=gpt-4o-mini
#   OPENAI_BASE_URL=... (optional; for compatible gateways)
#   LLAMA_GGUF_PATH=/data/models/<model>.gguf (optional; defaults to llama-2-7b-chat path)
LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or "none").strip().lower()
llm = None  # llama.cpp callable (prompt: str) -> str
llm_provider_active = "none"
DATA_DIR = os.environ.get("DATA_DIR", "/data")
_default_llama_path = os.path.join(DATA_DIR, "models/llama-2-7b-chat.Q4_K_M.gguf")
LLAMA_GGUF_PATH = (os.environ.get("LLAMA_GGUF_PATH") or _default_llama_path).strip()


def _init_llama_cpp() -> Optional[object]:
    global llm_provider_active
    if not LLAMA_GGUF_PATH or not os.path.exists(LLAMA_GGUF_PATH):
        return None
    try:
        from langchain_community.llms import LlamaCpp
    except Exception as exc:
        logger.warning("llama.cpp unavailable (langchain_community LlamaCpp import failed): %s", exc)
        return None

    logger.info("Initializing local GGUF model for RAG generation: %s", LLAMA_GGUF_PATH)
    llm_provider_active = "llama_cpp"
    return LlamaCpp(
        model_path=LLAMA_GGUF_PATH,
        temperature=0.1,
        max_tokens=320,
        top_p=0.95,
        n_ctx=2048,
    )


def _openai_client():
    try:
        from openai import OpenAI
    except Exception:
        return None
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    base_url = (os.environ.get("OPENAI_BASE_URL") or "").strip() or None
    return OpenAI(api_key=api_key, base_url=base_url)


OPENAI_MODEL = (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip()


def generate_amharic_answer_llm(
    query_text: str,
    context: str,
    history_str: str,
    user_context: str,
) -> Optional[str]:
    """
    Returns a short, human-readable Amharic answer grounded in `context`.
    Returns None if no LLM provider is configured/available.
    """
    global llm_provider_active
    provider = (LLM_PROVIDER or "none").strip().lower()

    # Prefer hosted models for best Amharic fluency.
    if provider == "openai":
        client = _openai_client()
        if not client:
            logger.warning("LLM_PROVIDER=openai but OPENAI_API_KEY is missing/unavailable.")
        else:
            llm_provider_active = f"openai:{OPENAI_MODEL}"
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an agricultural advisory assistant for farmers in Ethiopia.\n"
                        "You MUST answer in Amharic only.\n"
                        "Use ONLY the provided context. Do not add outside facts.\n"
                        "If the context is insufficient, say you don't have enough information and ask a short clarifying question.\n"
                        "Keep the answer short, practical, and easy to understand."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Context:\n{user_context}{context}\n\n"
                        f"Conversation history:\n{history_str}\n\n"
                        f"Question:\n{query_text}\n\n"
                        "Answer in Amharic only."
                    ),
                },
            ]
            try:
                resp = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=420,
                )
                out = (resp.choices[0].message.content or "").strip()
                return out or None
            except Exception as exc:
                logger.warning("OpenAI LLM call failed, falling back. Error: %s", exc)

    # Offline fallback: llama.cpp if present.
    if provider in ("llama_cpp", "llama", "gguf"):
        global llm
        if llm is None:
            llm = _init_llama_cpp()
        if not llm:
            logger.warning("LLM_PROVIDER=llama_cpp but GGUF model not found/usable.")
        else:
            prompt = (
                "መመሪያ: ከታች ያለው መረጃ ብቻ ተጠቅመህ መልስ ስጥ፤ ከውጭ እውቀት አትጨምር።\n"
                "መልስህ በአማርኛ ብቻ ይሁን፣ አጭር እና ተግባራዊ ይሁን።\n\n"
                f"Context:\n{user_context}{context}\n\n"
                f"ታሪክ:\n{history_str}\n\n"
                f"ጥያቄ:\n{query_text}\n\n"
                "መልስ (በአማርኛ ብቻ):"
            )
            try:
                out = (llm(prompt) or "").strip()
                return out or None
            except Exception as exc:
                logger.warning("llama.cpp generation failed: %s", exc)

    return None


# ── Pydantic Models ──────────────────────────────────────────────────────────
class Query(BaseModel):
    text: str
    phone_number: str = "Unknown"
    session_id: str = "default_session"


class FarmerProfile(BaseModel):
    phone_number: str
    name: str
    location: str
    preferred_language: str = "am"


class E2ERequest(BaseModel):
    text_input: str
    phone_number: str = "Unknown"
    session_id: str = "test_session"


# ── Text Normalization ───────────────────────────────────────────────────────
UNIT_MAP = {
    r'\bkg\b': 'ኪሎ ግራም',
    r'\bg\b': 'ግራም',
    r'\bha\b': 'ሄክታር',
    r'\bhectare\b': 'ሄክታር',
    r'\bL\b': 'ሊትር',
    r'\bliter\b': 'ሊትር',
    r'\bml\b': 'ሚሊ ሊትር',
    r'\bquintal\b': 'ኩንታል',
    r'\bqt\b': 'ኩንታል',
    r'\bbirr\b': 'ብር',
    r'\bETB\b': 'ብር',
}


def normalize_text(text: str) -> str:
    """Expand agricultural units/abbreviations for natural TTS pronunciation."""
    for pattern, replacement in UNIT_MAP.items():
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text


# ── Language Detection ───────────────────────────────────────────────────────
def is_amharic(text: str) -> bool:
    """Returns True if the text is primarily in Amharic (Ethiopic Unicode block)."""
    if not text:
        return False
    amharic_chars = sum(1 for c in text if '\u1200' <= c <= '\u137f')
    return amharic_chars / max(len(text.replace(' ', '')), 1) > 0.3


# ── Grounded answer without LLM (combine top chunks, Amharic framing) ───────
def compose_grounded_answer_no_llm(query_text: str, hits: list[dict], max_chars: int = 3200) -> str:
    if not hits:
        return ""
    if len(hits) == 1:
        return (hits[0].get("content") or "")[:max_chars]
    intro = "ከሰነዶች የተገኘው መረጃ እንደሚከተለው ነው።\n\n"
    parts: list[str] = []
    budget = max(200, max_chars - len(intro) - 40)
    per = budget // min(len(hits), 3)
    for i, h in enumerate(hits[:3], 1):
        body = (h.get("content") or "").strip()
        if not body:
            continue
        cap = min(len(body), per)
        parts.append(f"({i}) {body[:cap]}")
    return (intro + "\n\n".join(parts))[:max_chars]


# ── Core RAG Pipeline ────────────────────────────────────────────────────────
def generate_rag_response(query_text: str, phone_number: str, session_id: str):
    """
    Returns (response_text, intent, references, nlu_dict, advisory_meta).

    - intent: outcome label for routing (often same as NLU primary_intent for KB turns).
    - nlu_dict: { primary_intent, confidence, entities } from analyze_intent.
    - advisory_meta: SRS-style decision metadata (FR04/FR10/FR11/FR22), e.g. strategy and scores.
    """
    query_text = normalize_ethiopic_input((query_text or "").strip())
    logger.info(f"Processing query for session={session_id} phone={phone_number}: '{query_text}'")
    log_conversation(phone_number, session_id, "user", query_text)

    # ── Language Check ────────────────────────────────────────────────────────
    if query_text and not is_amharic(query_text):
        resp = "እባክዎ ጥያቄዎን በአማርኛ ይናገሩ።"  # Please ask your question in Amharic.
        log_conversation(phone_number, session_id, "assistant", resp)
        return resp, "non_amharic", [], {}, {"strategy": "non_amharic", "srs": ["FR01"]}

    nlu = analyze_intent(query_text)
    logger.info("NLU intent=%s conf=%.2f entities=%s", nlu.primary_intent, nlu.confidence, nlu.entities)

    # ── Greeting / Out-of-domain Handling (SRS FR04/FR11/FR10) ─────────────────
    # If intent is greeting or unknown with low confidence, do not force retrieval.
    if nlu.primary_intent == "greeting":
        resp = "ሰላም! እኔ የገበሬ አማካሪ ረዳት ነኝ። ስለ አፈር፣ ሰብል፣ ተባይ/በሽታ፣ መስኖ፣ የድህረ ምርት አያያዝ እና የማስፋፊያ ቁሳቁሶች ጥያቄዎችን ልመልስ እችላለሁ። ጥያቄዎን ይጠይቁ።"
        log_conversation(phone_number, session_id, "assistant", resp)
        return resp, "greeting", [], nlu.to_dict(), {"strategy": "greeting", "srs": ["FR04"]}
    if nlu.primary_intent == "unknown" and nlu.confidence <= 0.35:
        # Don't block retrieval for agronomy-looking questions; let RAG decide by distance.
        # Only fallback early for clearly out-of-domain queries.
        q = query_text or ""
        ql = q.lower()
        agr_signals = (
            "አፈር" in q
            or "መሬት" in q
            or "ሰብል" in q
            or "ተባይ" in q
            or "በሽታ" in q
            or "ማዳበሪያ" in q
            or "መስኖ" in q
            or "ድህረ" in q
            or "ማከማቻ" in q
            or "ጎተራ" in q
            or "landpks" in ql
            or "ላንድፒኬኤስ" in q
            or "soil" in ql
            or "pest" in ql
            or "disease" in ql
            or bool(nlu.entities.get("crop_en"))
            or "ዝናብ" in q
            or "እፅዋት" in q
            or "መኖ" in q
        )
        if not agr_signals:
            resp = "ይቅርታ፣ ጥያቄዎን በግብርና ጉዳይ እንዲሆን ትንሽ ይገልጹልኝ። ለምሳሌ፦ ሰብል ስም (ስንዴ/ጤፍ/ቦቆሎ)፣ ችግኝ (ተባይ/በሽታ)፣ ወቅት (መዝራት/እድገት/መከር) ወይም ማከማቻ ጥያቄ ይጨምሩ።"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "fallback", [], nlu.to_dict(), {"strategy": "fallback_clarify", "srs": ["FR04", "FR11"]}

    # ── Farmer Profile & Context ──────────────────────────────────────────────
    profile = get_farmer_profile(phone_number)
    farmer_location = profile['location'] if profile else "Unknown"
    user_context = f"Farmer Location: {farmer_location}. " if profile else ""

    # ── Active Alerts ─────────────────────────────────────────────────────────
    alerts = get_alerts_for_region(farmer_location)
    alerts_text = f"ማሳሰቢያ: {alerts[0][0]}\n\n" if alerts else ""

    # ── Safety Confirmation State ─────────────────────────────────────────────
    state = get_session_state(session_id)
    if state and state["current_state"] == "awaiting_confirmation":
        ql = (query_text or "").lower()
        if "አዎ" in query_text or "yes" in ql:
            set_session_state(session_id, "active", None)
            resp = alerts_text + state["pending_action"]
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "confirmed_action", [], nlu.to_dict(), {"strategy": "confirmed_action"}
        elif "አይ" in query_text or "no" in ql:
            set_session_state(session_id, "active", None)
            resp = "እሺ፣ እርምጃው ተሰርዟል። ሌላ ምን ልርዳዎት?"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "cancelled_action", [], nlu.to_dict(), {"strategy": "cancelled_action"}
        else:
            # If the user asks a new question instead of confirming, don't trap them in a loop.
            # Cancel the pending action and continue normally with the new query.
            set_session_state(session_id, "active", None)

    # ── Slot Awaiting State ───────────────────────────────────────────────────
    if state and state["current_state"] == "awaiting_slot":
        # If the user provides the missing entity (e.g., crop), resume; otherwise treat as a new question.
        # This avoids getting "stuck" asking the crop question on every turn.
        slot_nlu = analyze_intent(query_text)
        if slot_nlu.entities.get("crop_en"):
            original_query = state.get("pending_action", "")
            enriched_query = f"{original_query} {query_text}"
            set_session_state(session_id, "active", None)
            return generate_rag_response(enriched_query, phone_number, session_id)
        else:
            # User didn't actually answer the slot (asked another question); cancel slot state and continue.
            set_session_state(session_id, "active", None)

    # ── Slot Filling Check ────────────────────────────────────────────────────
    clarification = needs_slot_filling(query_text, state, nlu)
    if clarification:
        set_session_state(session_id, "awaiting_slot", query_text)
        log_conversation(phone_number, session_id, "assistant", clarification)
        return clarification, "awaiting_slot", [], nlu.to_dict(), {"strategy": "awaiting_slot", "srs": ["FR05", "UC-03"]}

    # ── Market Price Intent ───────────────────────────────────────────────────
    if nlu.primary_intent == "market_price":
        crop_name = nlu.entities.get("crop_en")
        logger.info("Market price intent; crop=%s", crop_name)
        if crop_name:
            price_data = get_market_price(crop_name, farmer_location) or get_market_price(crop_name)
            if price_data:
                price, unit, updated_at = price_data
                resp = f"የ{crop_name} ዋጋ {price} ብር በ {unit} ነው። (የዋጋ ቀን: {updated_at})"
                log_conversation(phone_number, session_id, "assistant", resp)
                return resp, "market_price", [], nlu.to_dict(), {"strategy": "market_price", "srs": ["FR09", "UC-04"]}
            else:
                resp = f"ለ{crop_name} ዋጋ መረጃ አሁን የለም። ቆይተው ይደውሉ።"
                log_conversation(phone_number, session_id, "assistant", resp)
                return resp, "market_price_unavailable", [], nlu.to_dict(), {"strategy": "market_price_unavailable"}
        else:
            # Crop not specified
            resp = "ስለ ምን ሰብል ዋጋ ይፈልጋሉ? (ጤፍ፣ ስንዴ፣ ቦሎቄ፣ ወዘተ.)"
            set_session_state(session_id, "awaiting_slot", query_text)
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "awaiting_slot", [], nlu.to_dict(), {"strategy": "awaiting_slot", "srs": ["FR05"]}

    # ── RAG: Postgres+pgvector (preferred) or legacy Chroma ───────────────────
    import rag_pg

    def _keyword_overlap_score(query: str, text: str) -> int:
        """
        Tiny hybrid-rerank: prefer chunks that contain key query words.
        This fixes common embedding confusion for generic words like "መመሪያ".
        """
        if not query or not text:
            return 0
        q = re.sub(r"\s+", " ", query.strip())
        t = (text or "")
        # Prefer longer / more specific tokens, keep Ethiopic + ASCII words
        tokens = re.findall(r"[\u1200-\u137F]+|[A-Za-z]+", q)
        stop = {
            "የ",
            "እና",
            "ወይም",
            "ነው",
            "ለ",
            "በ",
            "ላይ",
            "ነበር",
            "ምን",
            "ማን",
            "እንዴት",
            "እባክዎ",
            "ይህ",
            "ይህን",
            "መሆኑ",
            "መሆን",
            "እንዲሁም",
            "ማለት",
        }
        scored = 0

        def _amharic_stems(tok: str) -> list[str]:
            # Very small stemmer: remove common suffixes for matching (MVP).
            # Helps tokens like "ኪሳራዎች" match chunks containing "ኪሳራ".
            if not tok:
                return []
            out = {tok}
            for suf in ("ዎች", "ዎ", "ው", "ዋ", "ን", "ም", "ች"):
                if tok.endswith(suf) and len(tok) > len(suf) + 2:
                    out.add(tok[: -len(suf)])
            # also try dropping one char (often punctuation/affix artifacts)
            if len(tok) >= 5:
                out.add(tok[:-1])
            return sorted(out, key=len, reverse=True)

        for tok in tokens:
            if len(tok) < 3:
                continue
            if tok in stop:
                continue
            if re.search(r"[\u1200-\u137F]", tok):
                if any(stem in t for stem in _amharic_stems(tok) if len(stem) >= 3):
                    scored += 2
            else:
                if tok in t:
                    scored += 2
        return scored

    def _extension_chunk_phrase_boost(user_q: str, title: str, original_filename: str | None, content: str) -> int:
        """
        Heavy lexical boosts for the GIZ extension-materials manual (001): embeddings often pick
        wrong PDFs when queries share generic tokens (መመሪያ፣ ቁሳቁስ፣ ደረጃ/ርዕስ confusion).
        """
        if not _is_extension_manual_doc(title or "", original_filename):
            return 0
        u = (user_q or "").strip()
        body = ((content or "") + "\n" + (title or "")).strip()
        bonus = 0
        # Two bundles — intro section wording
        if "ጥቅል" in u and ("አንድ" in u or "ሁለት" in u):
            if any(
                p in body
                for p in (
                    "ጥቅል 1",
                    "ጥቅል 2",
                    "የአፈር እና የውሃ ጥበቃ",
                    "በዝቅተኛ አካባቢዎች የሰብል ምርት",
                )
            ):
                bonus += 40
        # Field visit + materials list
        if "መስክ ጉብኝት" in u and ("ቁሳቁስ" in u or "ቁሳቁሶች" in u):
            if any(p in body for p in ("የመስክ ጉብኝቶች", "ከጥቅል 1", "ከጥቅል 2")):
                bonus += 35
        # Discussion group duration (manual uses ASCII 1.5)
        if "ውይይት ቡድን" in u or "ውይይት ቡድኖች" in u:
            if any(p in body for p in ("ውይይት ቡድን", "የውይይት ቡድን", "የውይይት ቡድኖች")):
                bonus += 25
            if ("ሰዓት" in u or "ስንት" in u) and ("1.5" in body or "ለ1.5" in body.replace(" ", "")):
                bonus += 50
        return bonus

    def _narrow_extension_manual_candidates(
        candidates: list[dict], intent: str, user_q: str
    ) -> list[dict]:
        """
        When the question clearly targets the extension-materials playbook (001), drop other PDFs
        from the candidate pool so reranking cannot mix in irrigation / PH strategy chunks.
        """
        if intent != "extension_advisory" or not candidates:
            return candidates
        u = user_q or ""
        signals = (
            "ማስፋፊያ ቁሳቁሶች" in u
            or ("ጥቅል" in u and ("አንድ" in u or "ሁለት" in u))
            or "ውይይት ቡድን" in u
            or ("መስክ ጉብኝት" in u and ("ቁሳቁስ" in u or "ቁሳቁሶች" in u))
            or ("ፍሊፕ" in u and "መጽሐፍ" in u)
        )
        if not signals:
            return candidates
        ext_only = [
            h
            for h in candidates
            if _is_extension_manual_doc(h.get("title") or "", h.get("original_filename"))
        ]
        return ext_only if ext_only else candidates

    def _doc_blob(title: str, original_filename: str | None) -> str:
        return ((original_filename or "") + " " + (title or "")).lower()

    def _is_landpks_doc(title: str, original_filename: str | None) -> bool:
        b = _doc_blob(title, original_filename)
        return "landpks" in b or "006_landpks" in b.replace(" ", "_")

    def _is_extension_manual_doc(title: str, original_filename: str | None) -> bool:
        raw_fn = (original_filename or "").lower()
        if "use-of-extension" in raw_fn or "extension-materials" in raw_fn.replace("_", "-"):
            return True
        blob = _doc_blob(title, original_filename)
        if "use of extension" in blob or "extension materials" in blob:
            return True
        return "001" in blob and "extension" in blob

    def _filter_extension_candidates(candidates: list[dict], intent: str) -> list[dict]:
        """Drop LandPKS chunks when extension-materials chunks exist in the same candidate pool."""
        if intent != "extension_advisory" or not candidates:
            return candidates
        if not any(
            _is_extension_manual_doc(h.get("title") or "", h.get("original_filename"))
            for h in candidates
        ):
            return candidates
        filtered = [
            h
            for h in candidates
            if not _is_landpks_doc(h.get("title") or "", h.get("original_filename"))
        ]
        return filtered if filtered else candidates

    def _keyword_query_for_rerank(user_q: str, intent: str) -> str:
        extras = {
            "extension_advisory": "ቁሳቁስ እንፖስተር የውይይት ቡድን የመስክ ጉብኝት ማራዘም ቅያት አጠቃቀም",
            "post_harvest": "እህል ጎተራ ማከማቻ ኪሳራ ድህረ ምርት ማጠባበቅ መቀነስ",
            "land_characterization": "LandPKS መተግበሪያ አፈር ቀለም",
        }
        extra = extras.get(intent, "")
        return (user_q + "\n" + extra).strip() if extra else user_q

    def _doc_bias_for_intent(intent: str, title: str, original_filename: str | None = None) -> int:
        """
        Nudge ranking toward the right PDF family when embeddings tie on generic words
        like \"መመሪያ\" (LandPKS manuals vs extension materials). Uses original_filename
        because ingest replaces hyphens in titles (\"use-of-extension\" → \"use of extension\").
        """
        if not intent:
            return 0
        if intent == "extension_advisory":
            bias = 0
            if _is_landpks_doc(title, original_filename):
                bias -= 24
            if _is_extension_manual_doc(title, original_filename):
                bias += 16
            elif (
                "extension" in _doc_blob(title, original_filename)
                and not _is_landpks_doc(title, original_filename)
            ):
                bias += 6
            return bias
        if intent == "land_characterization":
            return 10 if _is_landpks_doc(title, original_filename) else -3
        if intent == "post_harvest":
            b = _doc_blob(title, original_filename)
            if any(x in b for x in ("010", "fao", "post-harvest-manual", "post harvest manual")):
                return 14
            if any(x in b for x in ("011", "phm-strategy", "postharvest management strategy")):
                return 6
            return 0
        return 0

    def _build_retrieval_queries(user_q: str, nlu_obj) -> list[str]:
        """
        Multi-query retrieval improves recall for Amharic phrasing variance.
        We keep queries short and grounded (no hallucinated expansions).
        """
        q = (user_q or "").strip()
        if not q:
            return []

        queries: list[str] = []

        # 1) Raw user query (highest priority)
        queries.append(q)

        intent_early = (getattr(nlu_obj, "primary_intent", "") or "").strip()
        # 2) Standalone semantic queries — pulls the right PDF family into the merged pool when
        # the user question is dominated by generic words (e.g. መመሪያ) that match many manuals.
        if intent_early == "extension_advisory":
            queries.append(
                "የማራዘም ቅያት ቁሳቁስ እንፖስተር የመስክ ጉብኝት የውይይት ቡድን አጠቃቀም ማስተር ዕቅድ"
            )
            if "ጥቅል" in q and ("አንድ" in q or "ሁለት" in q):
                queries.append(
                    "ጥቅል 1 የአፈር እና የውሃ ጥበቃ ጥቅል 2 በዝቅተኛ አካባቢዎች የሰብል ምርት የማስፋፊያ ቁሳቁሶች"
                )
            if "መስክ ጉብኝት" in q:
                queries.append(
                    "የመስክ ጉብኝቶች ከጥቅል 1 ከጥቅል 2 የሚገኙ ቁሳቁሶች ፍሊፕ ፖስተር"
                )
            if "ውይይት ቡድን" in q:
                queries.append("የውይይት ቡድኖች ስብሰባ ሰዓት 1.5 አመቻች")
            # Table / package list questions (001 manual) — FR10 retrieval expansion
            if "ጥቅል" in q and (
                "ዝርዝር" in q
                or "ምን" in q
                or "ያለ" in q
                or "አሉ" in q
                or "ቁሳቁስ" in q
                or "ቁሳቁሶች" in q
            ):
                queries.append(
                    "ሠንጠረዥ ጥቅል 1 የአፈር እና የውሃ ጥበቃ ቁሳቁሶች ዝርዝር ዓይነት ቁጥር ርዕስ"
                )
        elif intent_early == "post_harvest":
            queries.append(
                "እህል ጎተራ ማከማቻ ኪሳራ የድህረ ምርት ማጠባበቅ መንስኤ መፍትሄ"
            )

        # 3) NLU retrieval query (adds a short topic hint for embedding search)
        rq = (getattr(nlu_obj, "retrieval_query", "") or "").strip()
        if rq and rq != q:
            queries.append(rq)

        # 4) Light normalization: collapse whitespace/punctuation
        q_norm = re.sub(r"\s+", " ", re.sub(r"[“”\"'’]", "", q)).strip()
        if q_norm and q_norm != q:
            queries.append(q_norm)

        # 5) Intent-aware “title bias” tokens (helps pick the right manual/plan)
        # NOTE: These tokens are appended only for retrieval; not shown to user.
        intent = intent_early
        if intent == "land_characterization":
            queries.append(q + "\nLandPKS መመሪያ መተግበሪያ")
        elif intent == "extension_advisory":
            queries.append(
                q + "\nየማራዘም ቅያት ቁሳቁስ እንፖስተር ወረቀት የመስክ ጉብኝት የውይይት ቡድን"
            )
        elif intent == "pest_disease":
            queries.append(q + "\nተባይ በሽታ አስተዳደር ዕቅድ plan")
        elif intent == "post_harvest":
            queries.append(q + "\nድህረ ምርት እህል ጎተራ ማከማቻ ኪሳራ መቀነስ")
        elif intent == "crop_production":
            queries.append(q + "\nመስኖ ሰብል ምርት ቴክኒክ")

        # Dedup while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for item in queries:
            key = item.strip()
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
        return out

    def _rerank_hits(
        keyword_query: str,
        candidates: list[dict],
        intent: str = "",
        raw_user_q: str = "",
    ) -> list[dict]:
        """
        Hybrid rerank:
          - keyword overlap against title+content (query + intent discriminators)
          - document-family bias using title + original_filename
          - extension-manual phrase boosts (001 section targeting)
          - lower vector distance
        """
        rq = raw_user_q or keyword_query

        def _score(h: dict) -> float:
            blob = (h.get("title") or "") + "\n" + (h.get("content") or "")
            return (
                _keyword_overlap_score(keyword_query, blob)
                + _doc_bias_for_intent(
                    intent,
                    (h.get("title") or ""),
                    h.get("original_filename"),
                )
                + _extension_chunk_phrase_boost(
                    rq,
                    (h.get("title") or ""),
                    h.get("original_filename"),
                    (h.get("content") or ""),
                )
            )

        return sorted(
            candidates,
            key=lambda h: (-_score(h), float(h.get("distance") or 999.0)),
        )

    def _should_escalate_pg(best_distance: float, best_kw: int) -> bool:
        """
        Avoid over-escalating. Distance alone can be high for Amharic OCR/manuals.
        Escalate when distance is too high AND we have no strong lexical match.
        If the KB still contains a related chunk (lexical score), prefer answering (FR10/FR11).
        """
        if best_distance <= RAG_PG_MAX_L2_DISTANCE:
            return False
        return best_kw < RAG_PG_ESCALATION_MIN_LEXICAL

    references: list = []
    context: str | None = None
    hits: list[dict] = []
    closest_distance = 999.0
    rag_lex_score: int | None = None
    use_pg = rag_pg.kb_pg_enabled() and rag_pg.count_approved_chunks() > 0
    retrieval_queries = _build_retrieval_queries(query_text, nlu)

    if use_pg:
        # Multi-query retrieval (merge by chunk_id, keep best distance)
        merged: dict[str, dict] = {}
        best_distance = 999.0
        for rq in (retrieval_queries or [query_text]):
            cand, cand_best = rag_pg.retrieve_for_query(rq, top_k=RAG_PG_CANDIDATE_K)
            if cand_best < best_distance:
                best_distance = cand_best
            for h in cand:
                cid = h.get("chunk_id")
                if not cid:
                    continue
                prev = merged.get(cid)
                if not prev or float(h.get("distance") or 999.0) < float(prev.get("distance") or 999.0):
                    merged[cid] = h

        intent_s = (nlu.primary_intent or "").strip()
        candidates = _filter_extension_candidates(list(merged.values()), intent_s)
        candidates = _narrow_extension_manual_candidates(candidates, intent_s, query_text)
        if not candidates:
            closest_distance = 999.0
        else:
            closest_distance = min(float(h.get("distance") or 999.0) for h in candidates)

        kw_q = _keyword_query_for_rerank(query_text, intent_s)
        ranked = _rerank_hits(kw_q, candidates, intent_s, raw_user_q=query_text)
        hits = ranked[: max(1, RAG_PG_FINAL_K)]

        # Decide escalation more carefully (distance + lexical confidence)
        best_kw = (
            (
                _keyword_overlap_score(
                    kw_q,
                    (hits[0].get("title") or "") + "\n" + (hits[0].get("content") or ""),
                )
                + _doc_bias_for_intent(
                    intent_s,
                    (hits[0].get("title") or ""),
                    hits[0].get("original_filename"),
                )
                + _extension_chunk_phrase_boost(
                    query_text,
                    (hits[0].get("title") or ""),
                    hits[0].get("original_filename"),
                    (hits[0].get("content") or ""),
                )
            )
            if hits
            else 0
        )
        rag_lex_score = int(best_kw)
        if _should_escalate_pg(best_distance if best_distance != 999.0 else closest_distance, best_kw):
            logger.warning(
                "Postgres RAG escalation: best_distance=%.3f max=%.3f best_kw=%s",
                (best_distance if best_distance != 999.0 else closest_distance),
                RAG_PG_MAX_L2_DISTANCE,
                best_kw,
            )
            add_to_escalation(
                query_text,
                f"PG RAG escalation: best_distance={(best_distance if best_distance != 999.0 else closest_distance):.3f} "
                f"max={RAG_PG_MAX_L2_DISTANCE:.3f} kw={best_kw}",
            )
            resp = "ይቅርታ፣ ይህንን ጥያቄ በግልጽ መልኩ ለመመለስ በቂ መረጃ አላገኘሁም። ትንሽ ተጨማሪ መረጃ ይስጡ ወይም ለባለሙያ እልካለሁ።"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "escalated", [], nlu.to_dict(), {
                "strategy": "escalated",
                "srs": ["FR10", "FR22", "UC-10"],
                "reason": "pg_rag_distance_and_lexical_weak",
                "rag_best_distance": round(
                    float(best_distance if best_distance != 999.0 else closest_distance), 4
                ),
                "rag_lexical_score": int(best_kw),
            }

        references = [
            {
                "chunk_id": h["chunk_id"],
                "document_id": h["document_id"],
                "title": h["title"],
                "original_filename": h.get("original_filename"),
                "source_org": h["source_org"],
                "source_url": h["source_url"],
                "distance": h["distance"],
                "snippet": (h["content"][:400] + "...") if len(h["content"]) > 400 else h["content"],
            }
            for h in hits[:3]
        ]
        context = "\n\n".join(h["content"] for h in hits[:3])
    else:
        if not collection:
            add_to_escalation(query_text, "Chroma disabled and Postgres KB empty/unavailable.")
            resp = "ይቅርታ፣ የመረጃ መዝገቡ አሁን አልተዘጋጀም። እባክዎ ቆይተው ይሞክሩ።"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "kb_unavailable", [], nlu.to_dict(), {"strategy": "kb_unavailable", "srs": ["FR08", "FR10"]}

        # Keep Chroma behavior unchanged; just use retrieval hint if available.
        retrieval_query = (
            retrieval_queries[0] if retrieval_queries else (nlu.retrieval_query or query_text)
        )
        results = collection.query(query_texts=[retrieval_query], n_results=2)

        if not results["documents"] or not results["documents"][0]:
            distances = [999]
        else:
            distances = results["distances"][0]

        closest_distance = distances[0] if distances else 999

        if closest_distance > RAG_DISTANCE_THRESHOLD:
            logger.warning(
                "Chroma distance %.2f > threshold %.2f. Escalating.",
                closest_distance,
                RAG_DISTANCE_THRESHOLD,
            )
            add_to_escalation(
                query_text, f"Chroma distance: {closest_distance:.2f}. No confident KB match."
            )
            resp = "ይቅርታ፣ ይህንን ጥያቄ ሙሉ በሙሉ ልመልስ አልቻልኩም። ለባለሙያ አስተላልፌዋለሁ።"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "escalated", [], nlu.to_dict(), {
                "strategy": "escalated",
                "srs": ["FR10", "FR22"],
                "reason": "chroma_distance_weak",
                "rag_best_distance": float(closest_distance),
            }

        context = results["documents"][0][0]
        hits = [{"content": context}]

    intent = nlu.primary_intent

    history = get_conversation_history(session_id, limit=3)
    history_str = "\n".join([f"{h[0]}: {h[1]}" for h in history])

    # ── LLM or Direct KB Response ─────────────────────────────────────────────
    response_text = None
    if context:
        response_text = generate_amharic_answer_llm(query_text, context, history_str, user_context)

    if not response_text:
        if use_pg and hits:
            response_text = compose_grounded_answer_no_llm(query_text, hits)
        else:
            response_text = context or ""

    # FR10: generation produced nothing meaningful despite retrieval — clarify (do not pretend).
    if not (response_text or "").strip():
        resp = alerts_text + (
            "ይቅርታ፣ ከዚህ ጥያቄ ጋር በቂ የመረጃ ክፍል አላገኘሁም። እባክዎ በአጭሉ ይድገሙ ወይም ለቅርብ የማራዘም ሰራተኛ ይደውሉ።"
        )
        log_conversation(phone_number, session_id, "assistant", resp)
        return resp, "fallback_no_kb_excerpt", references, nlu.to_dict(), {
            "strategy": "fallback_clarify",
            "srs": ["FR10", "FR11", "UC-10"],
            "reason": "empty_generation",
            "rag_best_distance": round(float(closest_distance), 4) if use_pg else None,
            "rag_lexical_score": rag_lex_score,
        }

    # ── High-Risk Safety Interceptor ──────────────────────────────────────────
    # Trigger confirmation ONLY for actionable/dosage/chemical instructions.
    # Do NOT block general "principles/guidelines" questions.
    q_lower = (query_text or "").lower()
    principles_markers = ("መርሆ", "መርሆዎች", "መመሪያ", "መመሪያዎች", "መሰረታዊ", "ዋና ዋና")
    is_principles_question = any(p in (query_text or "") for p in principles_markers)

    high_risk_action_markers = [
        "dose",
        "dosage",
        "ml",
        "l/",
        "mix",
        "spray",
        "chemical",
        "pesticide",
        "fertilizer",
        "መድኃኒት",
        "መድሀኒት",
        "መርጨት",
        "ርጭት",
        "መጠን",
        "መጠን ስንት",
        "ስንት መጠን",
        "መቼ ልርጭ",
        "ምን እርጭት",
        "ፀረ-ተባይ",
        "ማዳበሪያ",
    ]
    is_high_risk_action = any(hk in q_lower for hk in high_risk_action_markers)
    is_risky_intent = nlu.primary_intent in ("pest_disease", "soil_fertility")

    if is_risky_intent and is_high_risk_action and not is_principles_question:
        logger.warning(f"High-risk actionable query detected for session {session_id}. Requiring confirmation.")
        set_session_state(session_id, "awaiting_confirmation", response_text)
        resp = alerts_text + "ይህ እርምጃ ጥንቃቄ ይፈልጋል። ስለ ሁኔታዎ እርግጠኛ ነዎት? (አዎ ወይም አይ)"
        log_conversation(phone_number, session_id, "assistant", resp)
        return resp, "requires_confirmation", references, nlu.to_dict(), {
            "strategy": "requires_confirmation",
            "srs": ["FR12", "UC-05"],
        }

    final_response = alerts_text + normalize_text(response_text)

    advisory: dict = {
        "strategy": "rag",
        "srs": ["FR10", "FR11"],
        "nlu_intent": nlu.primary_intent,
        "nlu_confidence": round(float(nlu.confidence), 3),
        "rag_best_distance": round(float(closest_distance), 4),
        "rag_distance_threshold_pg": RAG_PG_MAX_L2_DISTANCE,
        "rag_lexical_score": rag_lex_score,
    }
    if use_pg and hits:
        advisory["retrieval_confidence"] = compute_retrieval_confidence(hits, float(closest_distance))
        advisory["srs"].append("FR13")
    if nlu.confidence < NLU_LOW_CONFIDENCE_THRESHOLD:
        advisory["nlu_low_confidence"] = True
        advisory["srs"].append("FR04")
        advisory["suggested_follow_up_am"] = (
            "ጥያቄዎ ካልተረዳ በአጭሩ ይድገሙ፣ ወይም ለቅርብ የማራዘም ሰራተኛ ይደውሉ።"
        )
    if use_pg and float(closest_distance) > RAG_PG_MAX_L2_DISTANCE and rag_lex_score is not None:
        if rag_lex_score >= RAG_PG_ESCALATION_MIN_LEXICAL:
            advisory["rag_match"] = "weak_but_grounded"
            advisory["srs"].append("FR10")
            prev = advisory.get("suggested_follow_up_am", "")
            extra = " ከሰነዱ ጋር ያለው ተስማሚነት ዝቅተኛ ሊሆን ይችላል።"
            advisory["suggested_follow_up_am"] = (prev + extra).strip()

    log_conversation(phone_number, session_id, "assistant", final_response)
    return final_response, intent, references, nlu.to_dict(), advisory


# ── API Endpoints ────────────────────────────────────────────────────────────

@app.post("/ask")
async def process_query(query: Query):
    response_text, intent, references, nlu_out, advisory = generate_rag_response(
        query.text, query.phone_number, query.session_id
    )
    out = {"response": response_text, "intent": intent, "nlu": nlu_out, "advisory": advisory}
    if references:
        out["references"] = references
    return out


@app.get("/repeat/{session_id}")
async def repeat_last_response(session_id: str):
    """Returns the last assistant response for a given session (UC-06)."""
    history = get_conversation_history(session_id, limit=10)
    for role, message in reversed(history):
        if role == "assistant":
            return {"response": message}
    return {"response": "ቀዳሚ ምላሽ የለም።"}  # No previous response.


@app.post("/register")
async def register(profile: FarmerProfile):
    register_farmer(profile.phone_number, profile.name, profile.location, profile.preferred_language)
    return {"status": "success", "message": f"Farmer {profile.name} registered successfully."}


@app.get("/profile/{phone_number}")
async def get_profile(phone_number: str):
    profile = get_farmer_profile(phone_number)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@app.post("/save_call_record")
async def save_call_record(
    audio_file: UploadFile = File(...),
    session_id: str = Form(...),
    phone_number: str = Form(...),
    duration: int = Form(...)
):
    recordings_dir = os.path.join(DATA_DIR, "recordings")
    os.makedirs(recordings_dir, exist_ok=True)
    file_path = os.path.join(recordings_dir, f"{session_id}.wav")

    with open(file_path, "wb") as f:
        f.write(await audio_file.read())

    insert_call_record(session_id, phone_number, file_path, duration)

    if not get_farmer_profile(phone_number):
        register_farmer(phone_number, "Unknown Caller", "Unknown")

    return {"status": "success", "file_path": file_path}


@app.post("/simulate_call")
async def simulate_call(req: E2ERequest):
    """End-to-end test endpoint: text in → logic → TTS → confirms pipeline is live."""
    transcribed_text = req.text_input
    response_text, intent, references, nlu_out, advisory = generate_rag_response(
        transcribed_text, req.phone_number, req.session_id
    )

    audio_b64 = None
    try:
        tts_resp = requests.post(TTS_URL, json={"text": response_text}, timeout=30)
        if tts_resp.status_code == 200:
            audio_b64 = base64.b64encode(tts_resp.content).decode("utf-8")
        else:
            logger.error(f"TTS returned HTTP {tts_resp.status_code}")
    except Exception as e:
        logger.error(f"TTS request failed: {e}")

    payload = {
        "stt_output": transcribed_text,
        "logic_intent": intent,
        "logic_response": response_text,
        "nlu": nlu_out,
        "advisory": advisory,
        "audio_base64_length": len(audio_b64) if audio_b64 else 0,
    }
    if references:
        payload["references"] = references
    return payload


@app.get("/system_check")
async def system_check():
    """Connectivity health check for all downstream services."""
    results = {}

    try:
        import sqlite3
        from database import DB_PATH
        conn = sqlite3.connect(DB_PATH)
        conn.cursor().execute("SELECT 1")
        conn.close()
        results["database"] = "ok"
    except Exception as e:
        results["database"] = f"error: {e}"

    try:
        results["chroma_db"] = "ok" if collection.count() >= 0 else "empty"
    except Exception as e:
        results["chroma_db"] = f"error: {e}"

    try:
        stt_base = (os.environ.get("STT_URL") or "").strip()
        if not stt_base:
            results["stt_service"] = "disabled"
        else:
            stt_check = stt_base.rstrip("/") + "/docs"
        resp = requests.get(stt_check, timeout=3)
        results["stt_service"] = "ok" if resp.status_code == 200 else f"status {resp.status_code}"
    except Exception as e:
        results["stt_service"] = f"error: {e}"

    try:
        tts_base = (os.environ.get("TTS_URL") or "").strip()
        if not tts_base:
            results["tts_service"] = "disabled"
        else:
            tts_check = tts_base.replace("/synthesize", "").rstrip("/") + "/docs"
        resp = requests.get(tts_check, timeout=3)
        results["tts_service"] = "ok" if resp.status_code == 200 else f"status {resp.status_code}"
    except Exception as e:
        results["tts_service"] = f"error: {e}"

    results["rag_threshold"] = RAG_DISTANCE_THRESHOLD
    results["llm_provider"] = llm_provider_active

    try:
        import rag_pg

        if rag_pg.kb_pg_enabled():
            rag_pg.init_pg_schema()
            results["postgres_kb"] = "ok"
            results["kb_pg_documents"] = rag_pg.count_documents()
            results["kb_pg_chunks"] = rag_pg.count_approved_chunks()
            results["rag_pg_max_l2"] = RAG_PG_MAX_L2_DISTANCE
        else:
            results["postgres_kb"] = "disabled"
    except Exception as e:
        results["postgres_kb"] = f"error: {e}"

    return results
