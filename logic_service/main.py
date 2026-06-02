from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
import os
import re
import logging
import requests
import base64
import io
import time
from typing import Optional
from database import (
    collection, add_to_escalation, log_conversation,
    get_conversation_history, get_market_price, register_farmer,
    get_farmer_profile, get_alerts_for_region, set_session_state,
    get_session_state, insert_call_record,
)
from nlu import (
    analyze_intent,
    has_crop_in_query,
    is_crop_slot_reply,
    needs_slot_filling,
    normalize_ethiopic_input,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("logic_service")


def _warm_embedder() -> None:
    try:
        import rag_pg
        rag_pg._get_embedder()
        logger.info("Embedding model warmup complete.")
    except Exception as exc:
        logger.warning("Embedder warmup skipped: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        import rag_pg
        rag_pg.init_pg_schema()
    except Exception as exc:
        logger.warning("Postgres KB init skipped: %s", exc)
    import threading
    threading.Thread(target=_warm_embedder, daemon=True, name="embedder-warmup").start()
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
RAG_PG_CANDIDATE_K = int(os.environ.get("RAG_PG_CANDIDATE_K", "24"))
RAG_PG_FINAL_K = int(os.environ.get("RAG_PG_FINAL_K", "6"))
# When top vector match is weaker than this, also retrieve on raw user text (no NLU hint).
RAG_WEAK_MATCH_DISTANCE = float(os.environ.get("RAG_WEAK_MATCH_DISTANCE", "0.85"))
# Voice: Gemini first for quality; compose/chunks only when LLM fails (keeps speed via gTTS streaming)
RAG_VOICE_LLM_FIRST = os.environ.get("RAG_VOICE_LLM_FIRST", "1").strip().lower() in (
    "1", "true", "yes",
)
RAG_VOICE_COMPOSE_FIRST = os.environ.get("RAG_VOICE_COMPOSE_FIRST", "0").strip().lower() in (
    "1", "true", "yes",
)
RAG_VOICE_ANSWER_MAX_CHARS = int(os.environ.get("RAG_VOICE_RAG_ANSWER_MAX_CHARS", "600"))
RAG_VOICE_LLM_MAX_TOKENS = int(os.environ.get("RAG_VOICE_LLM_MAX_TOKENS", "450"))
RAG_VOICE_PG_FINAL_K = int(os.environ.get("RAG_VOICE_PG_FINAL_K", "3"))
RAG_RESPONSE_CACHE_TTL_SEC = int(os.environ.get("RAG_RESPONSE_CACHE_TTL_SEC", "0"))
_response_cache: dict[str, tuple[float, tuple]] = {}

# ── LLM Initialization (optional) ────────────────────────────────────────────
#
# Best Amharic quality: use OpenAI-compatible chat models (e.g. gpt-4o-mini).
# Offline option: local GGUF via llama.cpp if you mount a model under DATA_DIR/models/.
#
# Env:
#   LLM_PROVIDER=none|gemini|openai|llama_cpp
#   Groq (free): LLM_PROVIDER=openai + OPENAI_BASE_URL=https://api.groq.com/openai/v1
#   GEMINI_API_KEY=...          (from https://aistudio.google.com/apikey)
#   GEMINI_MODEL=gemini-2.0-flash
#   OPENAI_API_KEY=...
#   OPENAI_MODEL=gpt-4o-mini
#   OPENAI_BASE_URL=... (optional; for compatible gateways)
#   LLAMA_GGUF_PATH=/data/models/<model>.gguf (optional; defaults to llama-2-7b-chat path)
LLM_PROVIDER = (os.environ.get("LLM_PROVIDER") or "none").strip().lower()
llm = None  # llama.cpp callable (prompt: str) -> str
llm_provider_active = "none"
# Updated on each /ask: ok | quota_exceeded | error | disabled | not_configured | not_used
llm_last_status: dict[str, str] = {"state": "not_used", "detail": ""}
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
GEMINI_API_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
GEMINI_MODEL = (os.environ.get("GEMINI_MODEL") or "gemini-2.0-flash-lite").strip()
_default_gemini_models = "gemini-2.0-flash-lite,gemini-1.5-flash,gemini-2.0-flash"
GEMINI_MODEL_FALLBACKS = [
    m.strip()
    for m in (os.environ.get("GEMINI_MODEL_FALLBACKS") or _default_gemini_models).split(",")
    if m.strip()
]
LLM_CONTEXT_MAX_CHARS = int(os.environ.get("LLM_CONTEXT_MAX_CHARS", "2400"))
# Re-tries Gemini once when Groq returns 429 / rate-limit / error. Off by default unless a
# GEMINI_API_KEY is also configured. Set LLM_GROQ_FALLBACK_GEMINI=0 to disable.
LLM_GROQ_FALLBACK_GEMINI = (os.environ.get("LLM_GROQ_FALLBACK_GEMINI") or "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Default: one model, no retry — avoids burning free-tier quota (was up to 6 calls/request).
GEMINI_RETRY_ON_QUOTA = (os.environ.get("GEMINI_RETRY_ON_QUOTA") or "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
GEMINI_TRY_FALLBACK_MODELS = (os.environ.get("GEMINI_TRY_FALLBACK_MODELS") or "0").strip().lower() in (
    "1",
    "true",
    "yes",
)
_gemini_call_counter = 0
_llm_api_call_counter = 0


def _gemini_models_to_try() -> list[str]:
    """Primary model only unless GEMINI_TRY_FALLBACK_MODELS=1."""
    seen: set[str] = set()
    ordered: list[str] = []
    names = [GEMINI_MODEL]
    if GEMINI_TRY_FALLBACK_MODELS:
        names.extend(GEMINI_MODEL_FALLBACKS)
    for name in names:
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def _is_gemini_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    if "429" in msg or "quota" in msg or "rate limit" in msg or "resourceexhausted" in msg:
        return True
    return type(exc).__name__ in ("ResourceExhausted", "TooManyRequests")


def _requires_safety_confirmation(query_text: str, nlu) -> bool:
    """
    FR12 / UC-05: confirm before pesticide/chemical *application* advice.
    Skip confirmation for KB rate questions (DAP kg/ha) and symptom identification.
    """
    q = query_text or ""
    q_lower = q.lower()

    treatment_ask = any(
        x in q_lower or x in q
        for x in (
            "ርጭት",
            "መርጨት",
            "spray",
            "pesticide",
            "herbicide",
            "insecticide",
            "ቁጥጥር",
            "መከላከል",
            "ኬሚካል",
            "chemical",
        )
    )

    symptom_info = (
        "ምልክት" in q
        or "ምልክቶች" in q
        or "symptom" in q_lower
        or "signs" in q_lower
    )
    if symptom_info and not treatment_ask:
        return False

    fert_markers = (
        "dap",
        "nps",
        "urea",
        "ዲኤኤፒ",
        "ዩሪያ",
        "ማዳበሪያ",
        "fertilizer",
        "ኮምፖስት",
    )
    rate_markers = (
        "ያህል",
        "መጠን",
        "ኪ.ግ",
        "kg",
        "ሄክታር",
        "/ha",
        "ha",
        "ስንት",
        "recommended",
        "መጠቀም ይመከራ",
    )
    if any(f in q_lower or f in q for f in fert_markers) and any(
        r in q_lower or r in q for r in rate_markers
    ):
        if not treatment_ask:
            return False

    intent = getattr(nlu, "primary_intent", None) or ""
    if intent == "soil_fertility":
        return treatment_ask
    if intent == "pest_disease":
        return treatment_ask

    high_risk = ("pesticide", "chemical", "spray", "ርጭት", "መርጨት", "ፀረ-ተባይ", "ፀረ")
    return any(hk in q_lower for hk in high_risk)


def _crop_entity_boost(nlu_obj, blob: str) -> int:
    """Prefer chunks that mention the crop named in the question (onion vs tomato)."""
    if not nlu_obj:
        return 0
    ents = getattr(nlu_obj, "entities", None) or {}
    bonus = 0
    kw = ents.get("crop_keyword") or ""
    en = ents.get("crop_en") or ""
    if kw and kw in blob:
        bonus += 35
    if en and len(en) >= 4 and en.lower() in blob.lower():
        bonus += 12
    return bonus


def _truncate_for_llm(text: str, max_chars: int = LLM_CONTEXT_MAX_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 20].rstrip() + "\n…(truncated)"


WHY_ANSWER_MARKERS = (
    "ፍንጭ",
    "ይሰጣል",
    "ምክንያት",
    "አስፈላጊ",
    "ለማወቅ",
    "ስለምን",
    "because",
    "important",
    "helps",
    "clue",
)
UI_NOISE_MARKERS = (
    "ምስል",
    "settings",
    "መጫን",
    "more >>",
    "ገፅ",
    "camera",
    "manual",
    "application settings",
    "input source",
    "data input",
    "texture guide",
)
OBJECTIVE_ANSWER_MARKERS = (
    "ዓላማ",
    "ዋና ዓላማ",
    "አጠቃላይ ዓላማ",
    "ግብ",
    "objectives",
)
INTRO_TOC_NOISE_MARKERS = (
    "መግቢያ",
    "ይዘት ማውጫ",
    "table of contents",
    "2025/26",
    "2025",
    "2026",
    "ራዕይ",
    "vision",
    "introduction",
    "ኤፕሪል 26",
)


def _question_type(query_text: str) -> str:
    q = (query_text or "").lower()
    q_raw = query_text or ""
    # List-style questions (methods/symptoms/types/options) — keep all bullets verbatim
    if any(
        x in q_raw
        for x in (
            "ምን ዘዴዎች",
            "ምን ምልክቶች",
            "ምን አይነቶች",
            "ምን ዓይነቶች",
            "ምን ምን",
            "የትኞቹ",
            "ዘዴዎች አሉ",
            "ምልክቶች ያሳያል",
            "ምልክቶች አሉ",
        )
    ) or any(x in q for x in ("what methods", "what symptoms", "what types", "list ")):
        return "list"
    if any(x in q for x in ("ለምን", "why", "ምክንያት", "አስፈላጊ")):
        return "why"
    if any(x in q for x in ("እንዴት", "how to", "ዘዴ", "ሴራ")):
        return "how"
    if any(x in q for x in ("ምን", "what is", "what are")):
        return "what"
    if any(
        x in q
        for x in (
            "ዓላማ",
            "ዋና ዓላማ",
            "objectives",
            "main purpose",
            "main goal",
        )
    ):
        return "objectives"
    return "general"


def _query_terms(query_text: str) -> list[str]:
    q = re.sub(r"\([^)]*\)", " ", query_text or "")
    terms = [t for t in re.split(r"[\s,.?!;:]+", q) if len(t) >= 2 and not t.isdigit()]
    return list(dict.fromkeys(terms))


def _split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[።.?!])\s+|[\n•]+", text or "")
    out: list[str] = []
    for p in parts:
        s = p.strip().strip("*").strip()
        if len(s) >= 15:
            out.append(s)
    return out


def _score_sentence(sentence: str, terms: list[str], qtype: str) -> float:
    low = sentence.lower()
    score = float(sum(1 for t in terms if t in sentence or t.lower() in low))

    if qtype == "why":
        score += 4.0 * sum(1 for m in WHY_ANSWER_MARKERS if m in sentence or m in low)
        score -= 3.0 * sum(1 for m in UI_NOISE_MARKERS if m in low)
        # Prefer definitional / explanatory sentences over long UI bullets.
        if 40 <= len(sentence) <= 320:
            score += 2.0
        if len(sentence) > 450:
            score -= 2.0

    if qtype == "how":
        score += 1.5 * sum(1 for m in ("ዘዴ", "በመ", "እንዲ", "steps", "ሂደት") if m in sentence or m in low)
        score -= 2.0 * sum(1 for m in UI_NOISE_MARKERS if m in low)

    if qtype == "objectives":
        score += 5.0 * sum(
            1 for m in OBJECTIVE_ANSWER_MARKERS if m in sentence or m in low
        )
        score -= 4.0 * sum(
            1 for m in INTRO_TOC_NOISE_MARKERS if m in sentence or m in low
        )
        if re.search(r"\.{4,}|_{4,}", sentence):
            score -= 6.0
        if "ተባይ መቆጣጠሪያ ዕቅዱ ዓላማዎች" in sentence or "ዓላማዎች 44" in sentence:
            score += 4.0

    # Down-rank pure navigation / figure captions.
    if re.search(r"ምስል\s*\d+", sentence):
        score -= 4.0

    return score


def _best_sentences_for_answer(
    query_text: str, hits: list[dict], top_k: int = 5
) -> list[str]:
    terms = _query_terms(query_text)
    qtype = _question_type(query_text)
    if not terms and not hits:
        return []

    scored: list[tuple[float, str]] = []
    for h in hits[:4]:
        for sent in _split_sentences(h.get("content") or ""):
            s = _score_sentence(sent, terms, qtype)
            if s > 0:
                scored.append((s, sent))

    if not scored:
        return []

    scored.sort(key=lambda x: (-x[0], len(x[1])))
    picked: list[str] = []
    seen: set[str] = set()
    # For "why" questions, send 3 best sentences — limit=1 was too strict and caused
    # the LLM to receive the wrong sentence when scoring slightly mis-ranked.
    limit = 3 if qtype in ("why", "objectives") else min(top_k, 4)
    for _, sent in scored:
        if sent in seen:
            continue
        seen.add(sent)
        picked.append(sent)
        if len(picked) >= limit:
            break
    return picked


def _build_focused_context(query_text: str, hits: list[dict]) -> str:
    """Compact context for LLM: top scored sentences PLUS full chunk content as backup.

    Each chunk is preceded by a [TITLE: ...] marker so the LLM can cite a real
    document title instead of inventing one or echoing internal section labels.
    """
    sents = _best_sentences_for_answer(query_text, hits, top_k=6)
    parts: list[str] = []

    # Distinct document titles available for citation
    seen_titles: list[str] = []
    for h in hits[:4]:
        t = (h.get("title") or "").strip()
        if t and t not in seen_titles:
            seen_titles.append(t)
    if seen_titles:
        parts.append("Available source titles (cite ONLY from this list):")
        parts.extend(f"  • {t}" for t in seen_titles)
        parts.append("")

    if sents:
        parts.append("Top extracted sentences (use these as the primary answer source):")
        parts.extend(f"- {s}" for s in sents)
        parts.append("")
    parts.append("Full retrieved chunks (consult if the extracted sentences are insufficient):")
    for i, h in enumerate(hits[:4], 1):
        body = (h.get("content") or "").strip()
        title = (h.get("title") or "").strip() or "untitled"
        if body:
            parts.append(f"[CHUNK {i} | TITLE: {title}] {body[:900]}")
    return "\n".join(parts)


def _llm_system_prompt(qtype: str = "general") -> str:
    base = (
        "You are an expert agricultural advisor for Ethiopian farmers (FR-10 grounded generation).\n"
        "You MUST answer in clear, natural Amharic only — never English, never mixed languages.\n"
        "\n"
        "GROUNDING RULES (CRITICAL — SRS FR-10) — READ BEFORE ANSWERING:\n"
        "  1. Use ONLY the provided CONTEXT chunks. Do NOT add outside knowledge, opinions, or guesses.\n"
        "  2. STRICT TOPIC CHECK: Read the user question carefully. Identify the key entities\n"
        "     (crop, place, technique, problem). If ANY key entity in the question is NOT mentioned\n"
        "     in the CONTEXT, you MUST refuse and use the fallback below — do NOT improvise from\n"
        "     loosely related chunks. Example: user asks about Mars/መንግሥተ ሰማይ/Saudi/America but\n"
        "     context only covers Ethiopia regions → REFUSE.\n"
        "  3. If the context covers a DIFFERENT crop or DIFFERENT region than the user asked about,\n"
        "     REFUSE — do not substitute. Example: user asks about wheat, context is only mango → REFUSE.\n"
        "  4. FALLBACK MESSAGE — when refusing, reply with EXACTLY this and nothing else:\n"
        "      በቂ መረጃ የለም። ጥያቄዎ በተገኙ ሰነዶች ውስጥ አልተገኘም። እባክዎ ጥያቄዎን በተለየ መንገድ ይጠይቁ ወይም ለግብርና ባለሙያ ይደውሉ።\n"
        "  5. Do NOT cite documents that don't exist. Use ONLY real source titles you see in the\n"
        "     CONTEXT block (titles appear as part of the chunks — never invent or paraphrase them).\n"
        "  6. NEVER write \"ምንጭ: የተመረጡ ዓረፍተ ነገሮች\" or \"ምንጭ: Selected sentences\" —\n"
        "     those are internal labels, not real document sources.\n"
        "\n"
        "STYLE (be expressive and helpful — only when answering, not when refusing):\n"
        "  - Length must MATCH the available evidence. If the context has rich coverage of the\n"
        "    topic, write 2-3 paragraphs (~150-220 Amharic words). If the context only gives a\n"
        "    single fact, answer in 2-4 sentences and STOP. NEVER pad. NEVER repeat the same\n"
        "    sentence in different words.\n"
        "  - Each idea appears AT MOST ONCE. Do NOT restate the question. Do NOT restate the\n"
        "    same fact in the intro and then again in the body.\n"
        "  - Always finish your last sentence cleanly. Do not stop mid-sentence. If you are\n"
        "    running long, end earlier with a complete sentence and the citation line.\n"
        "  - Explain clearly so a farmer with low literacy can understand when read aloud.\n"
        "  - Use simple words, short sentences, end sentences with the Ethiopic full stop \"።\".\n"
        "  - If the context mentions specific numbers, units, dates, or place names — keep them verbatim.\n"
        "  - End with EXACTLY ONE citation line. The citation MUST use a title that\n"
        "    appears verbatim under \"Available source titles\" in the CONTEXT block.\n"
        "    Do NOT invent a title. Do NOT use section labels like \"Selected sentences\",\n"
        "    \"Full document chunks\", \"Top extracted sentences\", \"ሙሉ ሰነድ ቁርጥራጮች\",\n"
        "    \"የተመረጡ ዓረፍተ ነገሮች\", or chunk numbers like [አንድ]/[1] — those are NOT real titles.\n"
        "    Format: \"ምንጭ: <real title from the list>\". If no Available source titles are\n"
        "    listed, omit the citation line entirely.\n"
    )
    if qtype == "why":
        return (
            base
            + "\nQUESTION TYPE: WHY / IMPORTANCE / REASON.\n"
            "  - Open with the direct reason in 1-2 sentences.\n"
            "  - Then expand with the supporting explanation from the context (1-2 short paragraphs).\n"
            "  - Avoid procedural how-to detail; focus on cause, purpose, importance, or benefit.\n"
            "  - Use markers from the context like: ምክንያቱም / አስፈላጊ ነው / ለ...ይረዳል / ምክንያቱ ግልጽ ነው።\n"
        )
    if qtype == "how":
        return (
            base
            + "\nQUESTION TYPE: HOW-TO / METHOD.\n"
            "  - Open with a one-sentence overview of the goal.\n"
            "  - Then list the steps as Amharic bullet points (• or -) in the order they should be done.\n"
            "  - Each bullet: short, actionable, mention quantities/timing if the context has them.\n"
            "  - End with 1-2 sentences on common pitfalls or what to watch for (only if in context).\n"
        )
    if qtype == "list":
        return (
            base
            + "\nQUESTION TYPE: LIST (methods, symptoms, types, options, varieties).\n"
            "  - List EVERY distinct item found in the context as its own bullet (• or -).\n"
            "  - Each bullet: 1 short concrete line.\n"
            "  - Add a brief 1-sentence intro before the bullets and an optional 1-sentence closing tip.\n"
            "  - Do NOT drop items just to be short. Do NOT invent items.\n"
        )
    if qtype == "objectives":
        return (
            base
            + "\nQUESTION TYPE: OBJECTIVES / PURPOSE OF A PLAN OR STRATEGY.\n"
            "  - Look for sections labeled አጠቃላይ ዓላማ / ዋና ዓላማ / ዓላማዎች (numbered or bulleted).\n"
            "  - IGNORE intro/vision/table-of-contents/background sections.\n"
            "  - Open with a one-sentence statement of the overall objective.\n"
            "  - Then list each specific objective as a bullet (• or -).\n"
            "  - Optional 1-sentence closing on the expected outcome (only if in context).\n"
        )
    return (
        base
        + "\nQUESTION TYPE: GENERAL ADVISORY.\n"
        "  - Start with a direct 1-2 sentence answer to the exact question.\n"
        "  - Then expand with 1-2 supporting paragraphs ONLY if the context has new facts to add.\n"
        "  - If the context mentions warnings or risks, include them at the end as a short caution.\n"
        "  - If the context only contains 1-2 facts about the topic, give a SHORT answer (2-4\n"
        "    sentences) and STOP. Do not invent extra paragraphs to look thorough.\n"
    )


def _llm_user_prompt(
    query_text: str,
    context: str,
    history_str: str,
    user_context: str,
    *,
    voice_mode: bool = False,
) -> str:
    ctx = _truncate_for_llm(f"{user_context}{context}")
    hist = _truncate_for_llm(history_str, max_chars=800) if history_str else ""
    hist_block = f"Conversation history:\n{hist}\n\n" if hist.strip() else ""
    voice_note = (
        "VOICE CALL: Answer the exact question in 3-6 clear Amharic sentences. "
        "Put the direct answer first; no long lists unless the user asked for steps.\n\n"
        if voice_mode
        else ""
    )
    return (
        f"{voice_note}"
        f"CONTEXT (search this for the answer):\n{ctx}\n\n"
        f"{hist_block}"
        f"USER QUESTION: {query_text}\n\n"
        "YOUR ANSWER (Amharic only, follow the system instructions strictly):"
    )


def _call_gemini_model(
    model_name: str,
    prompt: str,
    *,
    max_output_tokens: int | None = None,
) -> Optional[str]:
    global _gemini_call_counter
    _gemini_call_counter += 1
    n = _gemini_call_counter
    logger.info("Calling Gemini API (#%s) model=%s prompt_chars=%s", n, model_name, len(prompt))
    print(f"[logic_service] Calling Gemini API call #{n} model={model_name}", flush=True)

    import google.generativeai as genai

    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(model_name)
    token_limit = max_output_tokens or int(os.environ.get("LLM_MAX_TOKENS", "900"))
    resp = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.2,
            max_output_tokens=token_limit,
        ),
    )
    if getattr(resp, "candidates", None):
        for cand in resp.candidates:
            if getattr(cand, "content", None) and cand.content.parts:
                text = "".join(
                    p.text for p in cand.content.parts if getattr(p, "text", None)
                ).strip()
                if text:
                    return text
    return (getattr(resp, "text", None) or "").strip() or None


def _is_insufficient_llm_answer(text: str) -> bool:
    t = (text or "").strip()
    return t == "በቂ መረጃ የለም።" or t.startswith("በቂ መረጃ")


SRS_FALLBACK_MESSAGE = (
    "በቂ መረጃ የለም። ጥያቄዎ በተገኙ ሰነዶች ውስጥ አልተገኘም። "
    "እባክዎ ጥያቄዎን በተለየ መንገድ ይጠይቁ ወይም ለግብርና ባለሙያ ይደውሉ።"
)


# Topics that should NEVER answer from agri KB even if entities partially match.
# Catches "በማርስ ላይ ጤፍ" (teff is in KB but Mars is nonsense for agronomy).
_OUT_OF_SCOPE_KEYWORDS = (
    "ማርስ",        # Mars
    "ጨረቃ",        # Moon
    "ፕላኔት",       # Planet (when used as off-Earth)
    "መንግሥተ ሰማይ",  # Heaven
    "ጁፒተር",       # Jupiter
    "ቬነስ",        # Venus
    "ሳተርን",       # Saturn
    "ሜርኩሪ",       # Mercury
    "ኔፕቱን",       # Neptune
    "ዩራነስ",       # Uranus
    "ጠፈር",        # Space (outer space)
    "mars",
    "moon",
    "jupiter",
    "saturn",
)


def _question_is_out_of_scope(query: str) -> bool:
    """Detect questions about off-planet / non-agricultural settings even if a crop name appears."""
    q = (query or "").lower()
    return any(kw in q or kw.lower() in q for kw in _OUT_OF_SCOPE_KEYWORDS)


def _all_chunks_too_distant(hits: list[dict], min_distance: float = 1.05) -> bool:
    """
    True when even the BEST chunk is too far semantically. Used as a soft "no relevant
    content" guard for questions where escalation threshold (1.35) is too loose.
    """
    if not hits:
        return True
    return min(float(h.get("distance") or 999.0) for h in hits) > min_distance

# Internal labels that must never appear in user-facing citations.
_BAD_CITATION_REGEXES = (
    # Old label-style citations
    re.compile(r"ምንጭ\s*[:፦]\s*የተመረጡ ዓረፍተ ነገሮች[።\.]?"),
    re.compile(r"ምንጭ\s*[:፦]\s*[Ss]elected sentences[።\.]?"),
    re.compile(r"ምንጭ\s*[:፦]\s*ሙሉ ሰነድ ቁርጥራጮች\s*\[[^\]]*\][።\.]?"),
    re.compile(r"ምንጭ\s*[:፦]\s*Full document chunks[^\n]*", re.IGNORECASE),
    re.compile(r"ምንጭ\s*[:፦]\s*Top extracted sentences[^\n]*", re.IGNORECASE),
    re.compile(r"ምንጭ\s*[:፦]\s*CHUNK[^\n]*", re.IGNORECASE),
    # Bare chunk-number citations like "ምንጭ: [አንድ]" or "ምንጭ: [1]"
    re.compile(r"ምንጭ\s*[:፦]\s*\[?(?:አንድ|ሁለት|ሦስት|አራት|\d+)\]?[።\.]?\s*$", re.MULTILINE),
    re.compile(r"የተመረጡ ዓረፍተ ነገሮች[።\.]"),
)


def _strip_bad_citations(text: str) -> str:
    """Remove citations that point to internal context labels rather than real documents."""
    if not text:
        return text
    cleaned = text
    for rx in _BAD_CITATION_REGEXES:
        cleaned = rx.sub("", cleaned)
    return cleaned.strip()


def _answer_meta(
    answer_source: str,
    *,
    strategy: str | None = None,
    best_distance: float | None = None,
) -> dict:
    src = (answer_source or "unknown").lower()
    if strategy is None:
        if src in ("llm", "gemini", "openai"):
            strategy = "LLM"
        elif src in ("rag", "rag_compose", "system"):
            strategy = "RAG" if src != "system" else "STATIC"
        else:
            strategy = "RAG"
    meta = {
        "answer_source": answer_source,
        "strategy": strategy,
        "llm_status": llm_last_status.get("state", "not_used"),
        "llm_detail": (llm_last_status.get("detail") or "")[:300],
        "llm_api_calls": _llm_api_call_counter,
        "gemini_api_calls": _gemini_call_counter,
    }
    if best_distance is not None:
        meta["best_distance"] = best_distance
    return meta


def _rag_cache_key(query_text: str, phone_number: str) -> str:
    return f"{phone_number}:{(query_text or '').strip().lower()}"


def _rag_cache_get(key: str):
    if RAG_RESPONSE_CACHE_TTL_SEC <= 0:
        return None
    entry = _response_cache.get(key)
    if not entry:
        return None
    ts, payload = entry
    if time.time() - ts > RAG_RESPONSE_CACHE_TTL_SEC:
        _response_cache.pop(key, None)
        return None
    return payload


def _rag_cache_set(key: str, payload: tuple) -> None:
    if RAG_RESPONSE_CACHE_TTL_SEC <= 0:
        return
    _response_cache[key] = (time.time(), payload)


def _set_llm_status(state: str, detail: str = "") -> None:
    global llm_last_status
    llm_last_status = {"state": state, "detail": detail}


def probe_gemini_api() -> dict:
    """One minimal API call to test key + quota (uses free-tier quota)."""
    if (LLM_PROVIDER or "none").strip().lower() != "gemini":
        return {"ok": False, "reason": "LLM_PROVIDER is not gemini"}
    if not GEMINI_API_KEY:
        return {"ok": False, "reason": "GEMINI_API_KEY not set"}
    model = _gemini_models_to_try()[0]
    try:
        out = _call_gemini_model(model, "Reply with exactly: OK")
        if out:
            _set_llm_status("ok", f"probe succeeded ({model})")
            return {"ok": True, "model": model, "sample": out[:40]}
        return {"ok": False, "reason": "empty response", "model": model}
    except Exception as exc:
        msg = str(exc)
        if "quota" in msg.lower() or "429" in msg or "ResourceExhausted" in type(exc).__name__:
            _set_llm_status("quota_exceeded", msg[:300])
            return {"ok": False, "reason": "quota_exceeded", "model": model, "detail": msg[:200]}
        _set_llm_status("error", msg[:300])
        return {"ok": False, "reason": "error", "model": model, "detail": msg[:200]}


def _gemini_retry_seconds(exc: Exception) -> float:
    msg = str(exc)
    m = re.search(r"retry_delay\s*\{\s*seconds:\s*(\d+)", msg)
    if m:
        return float(m.group(1)) + 1.0
    return 12.0


def generate_amharic_answer_llm(
    query_text: str,
    context: str,
    history_str: str,
    user_context: str,
    *,
    max_tokens: int | None = None,
    voice_mode: bool = False,
) -> Optional[str]:
    """
    Returns a short, human-readable Amharic answer grounded in `context`.
    Returns None if no LLM provider is configured/available.
    """
    global llm_provider_active
    provider = (LLM_PROVIDER or "none").strip().lower()
    if provider in ("none", ""):
        _set_llm_status("disabled", "LLM_PROVIDER=none")
        return None

    qtype = _question_type(query_text)
    system_prompt = _llm_system_prompt(qtype)
    user_prompt = _llm_user_prompt(
        query_text, context, history_str, user_context, voice_mode=voice_mode
    )
    token_limit = max_tokens or int(os.environ.get("LLM_MAX_TOKENS", "900"))

    if provider == "gemini":
        if not GEMINI_API_KEY:
            logger.warning("LLM_PROVIDER=gemini but GEMINI_API_KEY is missing.")
            _set_llm_status("not_configured", "GEMINI_API_KEY missing")
        else:
            global _gemini_call_counter
            _gemini_call_counter = 0
            models = _gemini_models_to_try()
            logger.info(
                "Gemini generation start: models=%s (fallbacks=%s, retry_on_quota=%s)",
                models,
                GEMINI_TRY_FALLBACK_MODELS,
                GEMINI_RETRY_ON_QUOTA,
            )
            print(
                f"[logic_service] Gemini start for /ask — will try up to {len(models)} model(s): {models}",
                flush=True,
            )
            prompt = f"{system_prompt}\n\n{user_prompt}"
            try:
                from google.api_core.exceptions import ResourceExhausted
            except Exception:
                ResourceExhausted = ()  # type: ignore

            for model_name in models:
                try:
                    out = _call_gemini_model(
                        model_name, prompt, max_output_tokens=token_limit
                    )
                    if out:
                        llm_provider_active = f"gemini:{model_name}"
                        _set_llm_status("ok", model_name)
                        logger.info(
                            "Gemini answer via model=%s (api_calls=%s)",
                            model_name,
                            _gemini_call_counter,
                        )
                        print(
                            f"[logic_service] Gemini OK after {_gemini_call_counter} API call(s)",
                            flush=True,
                        )
                        return out
                except ResourceExhausted as exc:
                    _set_llm_status("quota_exceeded", str(exc)[:300])
                    logger.warning(
                        "Gemini quota exceeded model=%s (api_calls=%s); stopping — no more models/retries.",
                        model_name,
                        _gemini_call_counter,
                    )
                    print(
                        f"[logic_service] Gemini quota exceeded after {_gemini_call_counter} call(s); using RAG only",
                        flush=True,
                    )
                    break
                except Exception as exc:
                    if _is_gemini_quota_error(exc):
                        _set_llm_status("quota_exceeded", str(exc)[:300])
                        logger.warning(
                            "Gemini 429/quota model=%s (api_calls=%s): %s",
                            model_name,
                            _gemini_call_counter,
                            exc,
                        )
                        print(
                            f"[logic_service] Gemini quota (429) after {_gemini_call_counter} call(s); using RAG only",
                            flush=True,
                        )
                        break
                    _set_llm_status("error", str(exc)[:300])
                    logger.warning("Gemini failed model=%s: %s", model_name, exc)
                    print(f"[logic_service] Gemini error: {exc}", flush=True)
                    if not GEMINI_TRY_FALLBACK_MODELS:
                        break
            if llm_last_status.get("state") not in ("quota_exceeded", "error"):
                _set_llm_status("error", "all Gemini models failed")
            logger.warning(
                "Gemini unavailable (%s, api_calls=%s); trying Groq fallback if configured.",
                llm_last_status.get("state"),
                _gemini_call_counter,
            )

            # ── Groq fallback (used when Gemini is primary and hits quota/error) ──
            if (
                os.environ.get("LLM_GEMINI_FALLBACK_GROQ", "1").strip().lower() in ("1", "true")
                and (os.environ.get("OPENAI_API_KEY") or "").strip()
            ):
                fallback_client = _openai_client()
                if fallback_client:
                    base = (os.environ.get("OPENAI_BASE_URL") or "").strip()
                    backend = "groq" if "groq.com" in base.lower() else "openai"
                    logger.info(
                        "Trying %s fallback after Gemini failure (state=%s)",
                        backend,
                        llm_last_status.get("state"),
                    )
                    print(
                        f"[logic_service] Gemini {llm_last_status.get('state')} — "
                        f"trying {backend} fallback",
                        flush=True,
                    )
                    try:
                        messages = [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ]
                        resp = fallback_client.chat.completions.create(
                            model=OPENAI_MODEL,
                            messages=messages,
                            temperature=0.2,
                            max_tokens=token_limit,
                            presence_penalty=float(os.environ.get("LLM_PRESENCE_PENALTY", "0.6")),
                            frequency_penalty=float(os.environ.get("LLM_FREQUENCY_PENALTY", "0.5")),
                        )
                        out = (resp.choices[0].message.content or "").strip()
                        if out:
                            llm_provider_active = f"{backend}-fallback:{OPENAI_MODEL}"
                            _set_llm_status("ok", f"{backend}-fallback:{OPENAI_MODEL}")
                            print(
                                f"[logic_service] {backend} fallback OK after Gemini failure",
                                flush=True,
                            )
                            return out
                    except Exception as exc:
                        logger.warning("%s fallback also failed: %s", backend, exc)
                        print(f"[logic_service] {backend} fallback failed: {exc}", flush=True)

    # OpenAI-compatible APIs (OpenAI, Groq, etc.)
    if provider == "openai":
        global _llm_api_call_counter
        _llm_api_call_counter = 0
        client = _openai_client()
        if not client:
            logger.warning("LLM_PROVIDER=openai but OPENAI_API_KEY is missing/unavailable.")
            _set_llm_status("not_configured", "OPENAI_API_KEY missing")
        else:
            base = (os.environ.get("OPENAI_BASE_URL") or "").strip()
            backend = "groq" if "groq.com" in base.lower() else "openai"
            llm_provider_active = f"{backend}:{OPENAI_MODEL}"
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
            try:
                _llm_api_call_counter += 1
                logger.info(
                    "Calling LLM API (#%s) backend=%s model=%s",
                    _llm_api_call_counter,
                    backend,
                    OPENAI_MODEL,
                )
                print(
                    f"[logic_service] Calling LLM API call #{_llm_api_call_counter} "
                    f"backend={backend} model={OPENAI_MODEL}",
                    flush=True,
                )
                resp = client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    temperature=0.2,
                    max_tokens=token_limit,
                    presence_penalty=float(os.environ.get("LLM_PRESENCE_PENALTY", "0.6")),
                    frequency_penalty=float(os.environ.get("LLM_FREQUENCY_PENALTY", "0.5")),
                )
                out = (resp.choices[0].message.content or "").strip()
                if out:
                    _set_llm_status("ok", f"{backend}:{OPENAI_MODEL}")
                    print(
                        f"[logic_service] LLM OK after {_llm_api_call_counter} API call(s)",
                        flush=True,
                    )
                    return out
            except Exception as exc:
                if _is_gemini_quota_error(exc) or "rate_limit" in str(exc).lower():
                    _set_llm_status("quota_exceeded", str(exc)[:300])
                else:
                    _set_llm_status("error", str(exc)[:300])
                logger.warning(
                    "LLM call failed backend=%s (api_calls=%s): %s",
                    backend,
                    _llm_api_call_counter,
                    exc,
                )
                print(f"[logic_service] LLM failed: {exc}", flush=True)

                # ── Gemini fallback (only when Groq quota/error) ──────────
                if LLM_GROQ_FALLBACK_GEMINI and GEMINI_API_KEY:
                    logger.info(
                        "Trying Gemini fallback after Groq failure (state=%s)",
                        llm_last_status.get("state"),
                    )
                    print(
                        f"[logic_service] Groq {llm_last_status.get('state')} — "
                        f"trying Gemini fallback",
                        flush=True,
                    )
                    prompt = f"{system_prompt}\n\n{user_prompt}"
                    for model_name in _gemini_models_to_try()[:1]:
                        try:
                            out = _call_gemini_model(
                                model_name, prompt, max_output_tokens=token_limit
                            )
                            if out:
                                llm_provider_active = f"gemini-fallback:{model_name}"
                                _set_llm_status(
                                    "ok", f"gemini-fallback:{model_name}"
                                )
                                print(
                                    "[logic_service] Gemini fallback OK",
                                    flush=True,
                                )
                                return out
                        except Exception as gem_exc:
                            if _is_gemini_quota_error(gem_exc):
                                _set_llm_status(
                                    "quota_exceeded",
                                    f"groq+gemini: {str(gem_exc)[:200]}",
                                )
                            else:
                                _set_llm_status(
                                    "error",
                                    f"gemini-fallback: {str(gem_exc)[:200]}",
                                )
                            logger.warning(
                                "Gemini fallback failed model=%s: %s",
                                model_name,
                                gem_exc,
                            )

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
                if out:
                    _set_llm_status("ok", "llama_cpp")
                    return out
            except Exception as exc:
                _set_llm_status("error", str(exc)[:300])
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


# ── Amharic Number Verbalization (for TTS) ───────────────────────────────────
# Native Amharic word forms for digits 0-19, 20, 30, ..., 100, 1000, 1000000.
_AM_DIGITS = {
    0: "ዜሮ", 1: "አንድ", 2: "ሁለት", 3: "ሦስት", 4: "አራት",
    5: "አምስት", 6: "ስድስት", 7: "ሰባት", 8: "ስምንት", 9: "ዘጠኝ",
    10: "አስር", 11: "አስራ አንድ", 12: "አስራ ሁለት", 13: "አስራ ሦስት",
    14: "አስራ አራት", 15: "አስራ አምስት", 16: "አስራ ስድስት", 17: "አስራ ሰባት",
    18: "አስራ ስምንት", 19: "አስራ ዘጠኝ",
}
_AM_TENS = {
    20: "ሃያ", 30: "ሰላሳ", 40: "አርባ", 50: "ሃምሳ", 60: "ስድሳ",
    70: "ሰባ", 80: "ሰማንያ", 90: "ዘጠና",
}


def _amharic_integer(n: int) -> str:
    """Convert a non-negative integer to spoken Amharic (best-effort up to 10^9)."""
    if n < 0:
        return "ሲቀነስ " + _amharic_integer(-n)
    if n < 20:
        return _AM_DIGITS[n]
    if n < 100:
        tens, ones = divmod(n, 10)
        base = _AM_TENS[tens * 10]
        return base if ones == 0 else f"{base} {_AM_DIGITS[ones]}"
    if n < 1000:
        hundreds, rest = divmod(n, 100)
        head = "መቶ" if hundreds == 1 else f"{_AM_DIGITS[hundreds]} መቶ"
        return head if rest == 0 else f"{head} {_amharic_integer(rest)}"
    if n < 1_000_000:
        thousands, rest = divmod(n, 1000)
        head = "ሺ" if thousands == 1 else f"{_amharic_integer(thousands)} ሺ"
        return head if rest == 0 else f"{head} {_amharic_integer(rest)}"
    if n < 1_000_000_000:
        millions, rest = divmod(n, 1_000_000)
        head = "ሚሊዮን" if millions == 1 else f"{_amharic_integer(millions)} ሚሊዮን"
        return head if rest == 0 else f"{head} {_amharic_integer(rest)}"
    return str(n)


def _amharic_number(token: str) -> str:
    """Convert a numeric token (possibly with a decimal) to Amharic words."""
    token = token.replace(",", "")
    try:
        if "." in token:
            int_part, dec_part = token.split(".", 1)
            int_val = int(int_part) if int_part else 0
            int_words = _amharic_integer(int_val)
            dec_words = " ".join(_AM_DIGITS[int(d)] for d in dec_part if d.isdigit())
            return f"{int_words} ነጥብ {dec_words}".strip()
        return _amharic_integer(int(token))
    except (ValueError, KeyError):
        return token


def _verbalize_numbers(text: str) -> str:
    """
    Replace numbers in `text` with their Amharic spoken form so TTS reads them correctly.
    Handles ranges (500-1000), decimals (1.5), grouped numbers (1,000), and percentages.

    Why we use (?<!\\d)/(?!\\d) instead of \\b: Python's \\b sees Ethiopic letters as
    word chars, so \\b between e.g. 'ለ' and '1' does NOT trigger, leaving the leading
    digit untouched and only converting the part after a dot. Lookahead/lookbehind
    avoid that pitfall while still preventing matches in the middle of longer numbers.
    """
    # Ranges: 500-1000  →  ከ five-hundred እስከ one-thousand
    def _range_repl(m: re.Match) -> str:
        a, b = m.group(1), m.group(2)
        return f"ከ{_amharic_number(a)} እስከ {_amharic_number(b)}"

    text = re.sub(
        r"(?<!\d)(\d+(?:[\.,]\d+)?)\s*[-–]\s*(\d+(?:[\.,]\d+)?)(?!\d)",
        _range_repl,
        text,
    )
    # Percent: 50% → ሃምሳ በመቶ
    text = re.sub(
        r"(?<!\d)(\d+(?:[\.,]\d+)?)\s*%",
        lambda m: f"{_amharic_number(m.group(1))} በመቶ",
        text,
    )
    # Remaining single numbers (decimal or integer)
    text = re.sub(
        r"(?<!\d)\d+(?:[\.,]\d+)?(?!\d)",
        lambda m: _amharic_number(m.group(0)),
        text,
    )
    return text


def normalize_text(text: str) -> str:
    """
    Prepare LLM output for natural TTS:
      1. Expand agricultural unit abbreviations.
      2. Verbalize numbers (1.5 → አንድ ነጥብ አምስት) so the Amharic VITS reads them.

    Citation lines (anything starting with "ምንጭ:") are passed through unchanged so
    document filename prefixes like "013_..." don't get mangled into Amharic words.
    Controlled by env TTS_VERBALIZE_NUMBERS=1 (default on).
    """
    do_numbers = os.environ.get("TTS_VERBALIZE_NUMBERS", "1") in ("1", "true", "True")

    def _process_line(line: str) -> str:
        stripped = line.lstrip()
        # Skip citation lines so titles like "013 irrigation..." stay intact.
        if stripped.startswith("ምንጭ:") or stripped.startswith("ምንጭ ") or stripped.startswith("ምንጭ፦"):
            return line
        for pattern, replacement in UNIT_MAP.items():
            line = re.sub(pattern, replacement, line, flags=re.IGNORECASE)
        if do_numbers:
            line = _verbalize_numbers(line)
        return line

    return "\n".join(_process_line(ln) for ln in text.splitlines())


# ── Language Detection ───────────────────────────────────────────────────────
def is_amharic(text: str) -> bool:
    """Returns True if the text is primarily in Amharic (Ethiopic Unicode block)."""
    if not text:
        return False
    amharic_chars = sum(1 for c in text if '\u1200' <= c <= '\u137f')
    return amharic_chars / max(len(text.replace(' ', '')), 1) > 0.3


# ── Grounded answer without LLM (combine top chunks, Amharic framing) ───────
def compose_grounded_answer_extractive(
    query_text: str, hits: list[dict], max_chars: int = 700
) -> str:
    """Short grounded answer from best-matching sentences (when LLM unavailable)."""
    picked = _best_sentences_for_answer(query_text, hits)
    if not picked:
        return ""
    body = " ".join(picked)
    return f"በአጭሩ፦ {body}"[:max_chars]


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
def generate_rag_response(
    query_text: str,
    phone_number: str,
    session_id: str,
    *,
    voice_mode: bool = False,
):
    """
    Returns (response_text, intent, references, nlu_dict, meta_dict).
    - intent: outcome label for routing (often same as NLU primary_intent for KB turns).
    - nlu_dict: { primary_intent, confidence, entities } from analyze_intent.
    """
    query_text = normalize_ethiopic_input((query_text or "").strip())
    logger.info(
        "Processing query session=%s phone=%s voice=%s: %r",
        session_id,
        phone_number,
        voice_mode,
        query_text,
    )

    cache_key = _rag_cache_key(query_text, phone_number)
    cached = _rag_cache_get(cache_key)
    if cached is not None:
        logger.info("RAG cache hit for %r", query_text[:60])
        return cached

    log_conversation(phone_number, session_id, "user", query_text)

    # ── Language Check ────────────────────────────────────────────────────────
    if query_text and not is_amharic(query_text):
        resp = "እባክዎ ጥያቄዎን በአማርኛ ይናገሩ።"  # Please ask your question in Amharic.
        log_conversation(phone_number, session_id, "assistant", resp)
        return resp, "non_amharic", [], {}, _answer_meta("system")

    # ── Out-of-Scope Guard (FR-10: ground only on KB, never about planets/space) ─
    if _question_is_out_of_scope(query_text):
        logger.info("Out-of-scope keyword detected; serving SRS fallback.")
        log_conversation(phone_number, session_id, "assistant", SRS_FALLBACK_MESSAGE)
        return SRS_FALLBACK_MESSAGE, "out_of_scope", [], {}, _answer_meta("system")

    nlu = analyze_intent(query_text)
    logger.info("NLU intent=%s conf=%.2f entities=%s", nlu.primary_intent, nlu.confidence, nlu.entities)

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
        if "አዎ" in query_text or "yes" in query_text.lower():
            set_session_state(session_id, "active", None)
            resp = alerts_text + state["pending_action"]
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "confirmed_action", [], nlu.to_dict(), _answer_meta("system")
        elif "አይ" in query_text or "no" in query_text.lower():
            set_session_state(session_id, "active", None)
            resp = "እሺ፣ እርምጃው ተሰርዟል። ሌላ ምን ልርዳዎት?"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "cancelled_action", [], nlu.to_dict(), _answer_meta("system")
        else:
            resp = "እባክዎን 'አዎ' ወይም 'አይ' ብለው ያረጋግጡ።"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "awaiting_confirmation", [], nlu.to_dict(), _answer_meta("system")

    # ── Slot Awaiting State ───────────────────────────────────────────────────
    if state and state["current_state"] == "awaiting_slot":
        # Only merge when the user sent a crop name; otherwise treat as a new question.
        original_query = state.get("pending_action", "") or ""
        set_session_state(session_id, "active", None)
        if is_crop_slot_reply(query_text):
            enriched_query = f"{original_query} {query_text}".strip()
        else:
            enriched_query = query_text
        return generate_rag_response(
            enriched_query, phone_number, session_id, voice_mode=voice_mode
        )

    # ── Slot Filling Check ────────────────────────────────────────────────────
    clarification = needs_slot_filling(query_text, state, nlu)
    if clarification:
        set_session_state(session_id, "awaiting_slot", query_text)
        log_conversation(phone_number, session_id, "assistant", clarification)
        return clarification, "awaiting_slot", [], nlu.to_dict(), _answer_meta("system")

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
                return resp, "market_price", [], nlu.to_dict(), _answer_meta("system")
            else:
                resp = f"ለ{crop_name} ዋጋ መረጃ አሁን የለም። ቆይተው ይደውሉ።"
                log_conversation(phone_number, session_id, "assistant", resp)
                return resp, "market_price_unavailable", [], nlu.to_dict(), _answer_meta("system")
        else:
            # Crop not specified
            resp = "ስለ ምን ሰብል ዋጋ ይፈልጋሉ? (ጤፍ፣ ስንዴ፣ ቦሎቄ፣ ወዘተ.)"
            set_session_state(session_id, "awaiting_slot", query_text)
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "awaiting_slot", [], nlu.to_dict(), _answer_meta("system")

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

    def _is_plant_guide_user_q(user_q: str) -> bool:
        u = user_q or ""
        return (
            ("አፋር" in u or "ሶማሌ" in u)
            and ("እፅዋት" in u or "ዝርያ" in u)
            and ("መመሪያ" in u or "ይረዳ" in u)
        )

    def _narrow_extension_manual_candidates(
        candidates: list[dict], intent: str, user_q: str
    ) -> list[dict]:
        """
        When the question clearly targets the extension-materials playbook (001), drop other PDFs
        from the candidate pool so reranking cannot mix in irrigation / PH strategy chunks.
        """
        if _is_plant_guide_user_q(user_q):
            return candidates
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
        if intent == "crop_production":
            b = _doc_blob(title, original_filename)
            if any(
                x in b
                for x in (
                    "012",
                    "plant guide",
                    "lowland",
                    "trees herbs",
                    "herbs and grasses",
                )
            ):
                return 14
            if any(x in b for x in ("002", "lowland contextualized", "crop option")):
                return 8
            return 0
        if intent == "pest_disease":
            b = _doc_blob(title, original_filename)
            if any(x in b for x in ("014", "pest", "vector", "wheat value")):
                return 12
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
        if _is_plant_guide_user_q(q):
            queries.append(
                "አፋር ሶማሌ ዝቅተኛ ቦታ እፅዋት ዝርያ አገር ውስጥ plant guide lowland"
            )
        elif intent_early == "extension_advisory":
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
        elif intent_early == "post_harvest":
            queries.append(
                "እህል ጎተራ ማከማቻ ኪሳራ የድህረ ምርት ማጠባበቅ መንስኤ መፍትሄ"
            )
        elif "አፈድ" in q or "aphid" in q.lower():
            if "ስንዴ" in q or "wheat" in q.lower() or "ሩሲያ" in q:
                queries.append(
                    "የሩሲያ የስንዴ አፈድ Russian wheat aphid Diuraphis noxia symptom ምልክት"
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
        nlu_obj=None,
    ) -> list[dict]:
        """
        Hybrid rerank:
          - keyword overlap against title+content (query + intent discriminators)
          - document-family bias using title + original_filename
          - extension-manual phrase boosts (001 section targeting)
          - crop entity match (onion vs tomato in same manual)
          - lower vector distance
        """
        rq = raw_user_q or keyword_query

        def _score(h: dict) -> float:
            blob = (h.get("title") or "") + "\n" + (h.get("content") or "")
            return (
                _keyword_overlap_score(keyword_query, blob)
                + _crop_entity_boost(nlu_obj, blob)
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
        """
        if best_distance <= RAG_PG_MAX_L2_DISTANCE:
            return False
        # If we have a decent keyword overlap, prefer answering with caveats over escalation.
        return best_kw < 2

    references: list = []
    context: str | None = None
    hits: list[dict] = []
    closest_distance = 999.0
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
        ranked = _rerank_hits(kw_q, candidates, intent_s, raw_user_q=query_text, nlu_obj=nlu)
        hits = ranked[: max(1, RAG_PG_FINAL_K)]

        # Weak vector match: second pass with raw user text only (drops NLU retrieval hint).
        if hits and float(hits[0].get("distance") or 999.0) > RAG_WEAK_MATCH_DISTANCE:
            raw_cand, _ = rag_pg.retrieve_for_query(query_text, top_k=RAG_PG_CANDIDATE_K)
            if raw_cand:
                merged2 = {h["chunk_id"]: h for h in candidates if h.get("chunk_id")}
                for h in raw_cand:
                    cid = h.get("chunk_id")
                    if not cid:
                        continue
                    prev = merged2.get(cid)
                    if not prev or float(h.get("distance") or 999.0) < float(
                        prev.get("distance") or 999.0
                    ):
                        merged2[cid] = h
                candidates2 = _filter_extension_candidates(
                    list(merged2.values()), intent_s
                )
                candidates2 = _narrow_extension_manual_candidates(
                    candidates2, intent_s, query_text
                )
                if candidates2:
                    ranked2 = _rerank_hits(
                        kw_q, candidates2, intent_s, raw_user_q=query_text, nlu_obj=nlu
                    )
                    hits = ranked2[: max(1, RAG_PG_FINAL_K)]
                    closest_distance = min(
                        float(h.get("distance") or 999.0) for h in hits
                    )
                    logger.info(
                        "Weak-match re-retrieval: top_distance=%.3f (threshold=%.3f)",
                        closest_distance,
                        RAG_WEAK_MATCH_DISTANCE,
                    )

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
            return resp, "escalated", [], nlu.to_dict(), _answer_meta("system")

        # ── Weak-match guard: even if no escalation, if every chunk is far we
        #     should not pretend we have an answer. Serve SRS fallback instead.
        if _all_chunks_too_distant(hits, min_distance=float(os.environ.get("RAG_MIN_BEST_DISTANCE", "1.05"))):
            logger.info(
                "Weak-match guard: best_distance=%.3f > min (%s). Serving SRS fallback.",
                min(float(h.get("distance") or 999.0) for h in hits),
                os.environ.get("RAG_MIN_BEST_DISTANCE", "1.05"),
            )
            log_conversation(phone_number, session_id, "assistant", SRS_FALLBACK_MESSAGE)
            return SRS_FALLBACK_MESSAGE, "low_confidence", [], nlu.to_dict(), _answer_meta("system")

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
        ctx_k = RAG_VOICE_PG_FINAL_K if voice_mode else 3
        context = _build_focused_context(query_text, hits[:ctx_k])
    else:
        if not collection:
            add_to_escalation(query_text, "Chroma disabled and Postgres KB empty/unavailable.")
            resp = "ይቅርታ፣ የመረጃ መዝገቡ አሁን አልተዘጋጀም። እባክዎ ቆይተው ይሞክሩ።"
            log_conversation(phone_number, session_id, "assistant", resp)
            return resp, "kb_unavailable", [], nlu.to_dict(), _answer_meta("system")

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
            return resp, "escalated", [], nlu.to_dict(), _answer_meta("system")

        context = results["documents"][0][0]
        hits = [{"content": context}]

    intent = nlu.primary_intent

    history = get_conversation_history(session_id, limit=3)
    history_str = "\n".join([f"{h[0]}: {h[1]}" for h in history])

    # ── LLM or Direct KB Response ─────────────────────────────────────────────
    best_dist = float(hits[0].get("distance") or 999.0) if hits else 999.0
    response_text = None
    answer_source = "rag"
    strategy = "RAG"
    voice_token_limit = RAG_VOICE_LLM_MAX_TOKENS if voice_mode else None

    # Voice + Gemini first (default): synthesize from KB context, stay fast via short token cap
    if voice_mode and RAG_VOICE_LLM_FIRST and context:
        logger.info(
            "Voice LLM-first: calling Gemini (best_distance=%.3f, max_tokens=%s)",
            best_dist,
            RAG_VOICE_LLM_MAX_TOKENS,
        )
        response_text = generate_amharic_answer_llm(
            query_text,
            context,
            history_str,
            user_context,
            max_tokens=voice_token_limit,
            voice_mode=True,
        )
        if response_text and not _is_insufficient_llm_answer(response_text):
            answer_source = "llm"
            strategy = "LLM"
        else:
            logger.info(
                "Voice LLM-first: Gemini unavailable or insufficient; using compose fallback"
            )
            response_text = None

    # Optional compose-first (RAG_VOICE_COMPOSE_FIRST=1): skip LLM when match is strong
    if (
        not response_text
        and voice_mode
        and RAG_VOICE_COMPOSE_FIRST
        and use_pg
        and hits
        and best_dist <= RAG_WEAK_MATCH_DISTANCE
    ):
        composed = compose_grounded_answer_extractive(
            query_text, hits, max_chars=RAG_VOICE_ANSWER_MAX_CHARS
        )
        if composed and len(composed.strip()) >= 40:
            response_text = composed
            answer_source = "rag_compose"
            strategy = "RAG"
            logger.info(
                "Voice compose-first: skipped LLM (best_distance=%.3f, len=%d)",
                best_dist,
                len(composed),
            )

    # Text / admin path, or voice when LLM-first disabled: standard LLM attempt
    if not response_text and context and not (voice_mode and RAG_VOICE_LLM_FIRST):
        response_text = generate_amharic_answer_llm(
            query_text,
            context,
            history_str,
            user_context,
            max_tokens=voice_token_limit,
            voice_mode=voice_mode,
        )
        if response_text:
            answer_source = "llm"
            strategy = "LLM"

    if not response_text:
        answer_source = "rag"
        strategy = "RAG"
        if use_pg and hits:
            composed = compose_grounded_answer_extractive(
                query_text, hits, max_chars=RAG_VOICE_ANSWER_MAX_CHARS if voice_mode else 700
            )
            if composed and len(composed.strip()) >= 40:
                response_text = composed
                answer_source = "rag_compose"
            else:
                response_text = compose_grounded_answer_no_llm(
                    query_text, hits, max_chars=RAG_VOICE_ANSWER_MAX_CHARS if voice_mode else 3200
                )
        else:
            response_text = "\n\n".join(
                (h.get("content") or "") for h in hits[:3]
            ) or context or ""
    elif _is_insufficient_llm_answer(response_text) and use_pg and hits:
        logger.info(
            "LLM returned insufficient answer; falling back to RAG chunks (distance=%.3f)",
            best_dist,
        )
        composed = compose_grounded_answer_extractive(
            query_text, hits, max_chars=RAG_VOICE_ANSWER_MAX_CHARS if voice_mode else 700
        )
        response_text = composed or compose_grounded_answer_no_llm(
            query_text, hits, max_chars=RAG_VOICE_ANSWER_MAX_CHARS if voice_mode else 3200
        )
        answer_source = "rag_compose" if composed else "rag"
        strategy = "RAG"

    # ── High-Risk Safety Interceptor (FR12 / UC-05) ───────────────────────────
    if _requires_safety_confirmation(query_text, nlu):
        logger.warning(
            "High-risk topic detected for session %s. Requiring confirmation.",
            session_id,
        )
        set_session_state(session_id, "awaiting_confirmation", response_text)
        resp = alerts_text + "ይህ እርምጃ ጥንቃቄ ይፈልጋል። ስለ ሁኔታዎ እርግጠኛ ነዎት? (አዎ ወይም አይ)"
        log_conversation(phone_number, session_id, "assistant", resp)
        return resp, "requires_confirmation", references, nlu.to_dict(), _answer_meta("system")

    final_response = alerts_text + _strip_bad_citations(normalize_text(response_text))
    log_conversation(phone_number, session_id, "assistant", final_response)
    meta = _answer_meta(answer_source, strategy=strategy, best_distance=best_dist if hits else None)
    result = (final_response, intent, references, nlu.to_dict(), meta)
    if voice_mode and answer_source in ("rag", "rag_compose", "system"):
        _rag_cache_set(cache_key, result)
    return result


# ── API Endpoints ────────────────────────────────────────────────────────────

class RagAnswerRequest(BaseModel):
    text: str
    session_id: str
    phone_number: str = "Unknown"
    voice_mode: bool = True
    asr: dict | None = None


@app.post("/ask")
async def process_query(query: Query):
    response_text, intent, references, nlu_out, meta = generate_rag_response(
        query.text, query.phone_number, query.session_id
    )
    out = {"response": response_text, "intent": intent, "nlu": nlu_out, **meta}
    if references:
        out["references"] = references
    return out


@app.post("/rag/answer")
async def rag_answer(req: RagAnswerRequest):
    """Fast voice path used by vad_service (compose-first, shorter answers)."""
    response_text, intent, references, nlu_out, meta = generate_rag_response(
        req.text,
        req.phone_number,
        req.session_id,
        voice_mode=req.voice_mode,
    )
    return {
        "response": response_text,
        "intent": intent,
        "references": references or [],
        "nlu": nlu_out,
        "meta": meta,
        "trust": {"grounding": meta.get("answer_source", "unknown")},
        "best_distance": meta.get("best_distance"),
        "strategy": meta.get("strategy"),
    }


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


@app.post("/voice/ask")
async def voice_ask(
    audio_file: UploadFile = File(...),
    phone_number: str = Form("Unknown"),
    session_id: str = Form("default_session"),
    return_audio: bool = Form(True),
):
    """
    End-to-end voice pipeline (no telephony / no SIP).
    Pipeline: audio upload -> STT -> /ask logic (NLU + RAG + LLM) -> TTS audio back.

    Callers are expected to send a VAD-trimmed Amharic utterance (use the
    existing `vad_service` WebSocket or any client-side VAD). We do not run
    VAD again here.

    Returns:
      - If `return_audio=True` (default): audio/wav bytes with metadata in
        response headers (X-Transcript-B64, X-Response-Text-B64, X-Intent, ...).
        Amharic text in headers is UTF-8 base64 because HTTP headers must be ASCII.
      - Else: JSON with transcript + response text + base64 audio.
    """
    audio_bytes_in = await audio_file.read()
    if not audio_bytes_in:
        raise HTTPException(status_code=400, detail="Empty audio upload")

    try:
        stt_resp = requests.post(
            STT_URL,
            files={
                "audio_file": (
                    audio_file.filename or "utt.wav",
                    audio_bytes_in,
                    audio_file.content_type or "audio/wav",
                )
            },
            timeout=60,
        )
        stt_data = stt_resp.json()
        transcript = (stt_data.get("text") or "").strip()
        stt_conf = float(stt_data.get("confidence") or 0.0)
    except Exception as exc:
        logger.error("Voice /ask STT failed: %s", exc)
        raise HTTPException(status_code=502, detail=f"STT failed: {exc}")

    if not transcript:
        reprompt = "ይቅርታ፣ ድምፅዎን ሰምቼ ለመረዳት አልቻልኩም። እባክዎ በአማርኛ ይድገሙ።"
        return _voice_response_bundle(
            audio_text=reprompt,
            transcript="",
            stt_conf=stt_conf,
            response_text=reprompt,
            intent="asr_failed",
            references=[],
            nlu_out={},
            meta=_answer_meta("system"),
            return_audio=return_audio,
        )

    response_text, intent, references, nlu_out, meta = generate_rag_response(
        transcript, phone_number, session_id
    )

    return _voice_response_bundle(
        audio_text=response_text,
        transcript=transcript,
        stt_conf=stt_conf,
        response_text=response_text,
        intent=intent,
        references=references,
        nlu_out=nlu_out,
        meta=meta,
        return_audio=return_audio,
    )


def _trim_for_tts(text: str, max_chars: int = 600) -> str:
    """
    TTS struggles with very long Amharic strings (>~700 chars often times out).
    Trim to <= max_chars, breaking at the last sentence boundary when possible.
    """
    if not text:
        return ""

    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return cleaned

    cut = cleaned[:max_chars]
    for sep in ("። ", "! ", "? ", ". ", "።", "!", "?", "."):
        idx = cut.rfind(sep)
        if idx > max_chars * 0.5:
            return cut[: idx + len(sep)].strip()
    return cut.strip()


def _voice_response_bundle(
    *,
    audio_text: str,
    transcript: str,
    stt_conf: float,
    response_text: str,
    intent: str,
    references: list,
    nlu_out: dict,
    meta: dict,
    return_audio: bool,
):
    tts_max_chars = int(os.environ.get("TTS_MAX_CHARS", "600"))
    tts_timeout = int(os.environ.get("TTS_TIMEOUT_SECONDS", "120"))
    tts_text = _trim_for_tts(audio_text, max_chars=tts_max_chars)

    audio_out: bytes = b""
    tts_error: Optional[str] = None
    try:
        logger.info(
            "TTS request: %d chars (orig %d)", len(tts_text), len(audio_text or "")
        )
        tts_resp = requests.post(
            TTS_URL, json={"text": tts_text}, timeout=tts_timeout
        )
        if tts_resp.status_code == 200:
            audio_out = tts_resp.content
        else:
            tts_error = f"TTS HTTP {tts_resp.status_code}"
            logger.error(tts_error)
    except Exception as exc:
        tts_error = f"TTS exception: {exc}"
        logger.error(tts_error)

    if return_audio and audio_out:
        def _hdr_ascii(s: str, max_len: int = 128) -> str:
            return (s or "").replace("\n", " ").replace("\r", " ").strip()[:max_len]

        def _hdr_utf8_b64(s: str) -> str:
            text = (s or "").replace("\n", " ").replace("\r", " ").strip()
            if not text:
                return ""
            return base64.b64encode(text.encode("utf-8")).decode("ascii")

        headers = {
            "X-Stt-Confidence": f"{stt_conf:.3f}",
            "X-Intent": _hdr_ascii(intent),
            "X-Answer-Source": _hdr_ascii(meta.get("answer_source", "")),
            "X-Llm-Status": _hdr_ascii(meta.get("llm_status", "")),
            "Content-Disposition": 'attachment; filename="response.wav"',
            "Content-Length": str(len(audio_out)),
            "Accept-Ranges": "bytes",
            "Cache-Control": "no-store",
        }
        if transcript:
            headers["X-Transcript-B64"] = _hdr_utf8_b64(transcript)
        if response_text:
            headers["X-Response-Text-B64"] = _hdr_utf8_b64(response_text)

        return StreamingResponse(
            io.BytesIO(audio_out),
            media_type="audio/wav",
            headers=headers,
        )

    payload: dict = {
        "transcript": transcript,
        "stt_confidence": stt_conf,
        "response": response_text,
        "intent": intent,
        "nlu": nlu_out,
        **meta,
    }
    if references:
        payload["references"] = references
    if audio_out:
        payload["audio_base64"] = base64.b64encode(audio_out).decode("utf-8")
    if tts_error:
        payload["tts_error"] = tts_error
    return payload


@app.post("/simulate_call")
async def simulate_call(req: E2ERequest):
    """End-to-end test endpoint: text in → logic → TTS → confirms pipeline is live."""
    transcribed_text = req.text_input
    response_text, intent, references, nlu_out, meta = generate_rag_response(
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
        "audio_base64_length": len(audio_b64) if audio_b64 else 0,
        **meta,
    }
    if references:
        payload["references"] = references
    return payload


@app.get("/system_check")
async def system_check(probe: bool = False):
    """Connectivity health check for all downstream services.

    Set probe=true to run one minimal Gemini call (uses API quota).
    """
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
    results["llm"] = {
        "provider_config": LLM_PROVIDER,
        "model": GEMINI_MODEL,
        "api_key_set": bool(GEMINI_API_KEY),
        "last_status": dict(llm_last_status),
        "status_help": {
            "ok": "LLM worked on last request",
            "quota_exceeded": "Free API limit hit — wait or use a new key/project",
            "error": "API/key/network error",
            "disabled": "LLM_PROVIDER=none",
            "not_configured": "GEMINI_API_KEY missing",
            "not_used": "No /ask yet since service started",
        },
    }
    if probe:
        results["llm"]["probe"] = probe_gemini_api()

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
