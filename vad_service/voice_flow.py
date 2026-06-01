import os
import re


VAD_TTS_SINGLE_CHUNK_MAX_CHARS = int(os.getenv("VAD_TTS_SINGLE_CHUNK_MAX_CHARS", "180"))
VAD_TTS_CHUNK_MAX_CHARS = int(os.getenv("VAD_TTS_CHUNK_MAX_CHARS", "140"))


def _normalize_confirmation_text(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip().lower())
    normalized = normalized.replace("ኣ", "አ").replace("ዐ", "አ").replace("ዓ", "አ")
    normalized = re.sub(r"[።፣፤፦፧!?.,:;\"'`]+", " ", normalized)
    return re.sub(r"\s+", " ", normalized).strip()


def classify_confirmation_reply(text: str) -> str:
    normalized = _normalize_confirmation_text(text)
    if not normalized:
        return "unknown"

    yes_terms = (
        "አዎ",
        "አወ",
        "አው",
        "አዋ",
        "አዌ",
        "አውነት",
        "እሺ",
        "እሽ",
        "ልክ",
        "ትክክል",
        "ትክክል ነው",
        "እውነት",
        "awo",
        "aw",
        "awe",
        "eshi",
        "ishi",
        "yes",
        "yeah",
        "yep",
        "ok",
        "okay",
        "correct",
        "right",
    )
    no_terms = (
        "አይ",
        "አይደለም",
        "አይደለ",
        "አይ አይደለም",
        "አይደል",
        "አይዎ",
        "የለም",
        "aye",
        "no",
        "nope",
        "wrong",
        "incorrect",
    )

    tokens = normalized.split()
    token_set = set(tokens)
    first_token = tokens[0] if tokens else ""

    def matches_reply(term: str) -> bool:
        if term == normalized or term in token_set:
            return True
        # Accept short ASR suffixes at the start only, e.g. "አውም".
        if first_token.startswith(term) and len(first_token) <= len(term) + 2:
            return True
        # Multi-word phrases can be recognized as a leading phrase.
        return " " in term and normalized.startswith(f"{term} ")

    if any(matches_reply(term) for term in no_terms):
        return "no"
    if any(matches_reply(term) for term in yes_terms):
        return "yes"

    return "unknown"


def classify_confirmation_reply_from_asr(asr_result: dict) -> str:
    """Use all ASR transcript variants because short yes/no words are often unstable."""
    candidates = [
        asr_result.get("transcript"),
        asr_result.get("final_transcript"),
        asr_result.get("structured_transcript"),
        asr_result.get("domain_corrected_transcript"),
        asr_result.get("cleaned_transcript"),
        asr_result.get("raw_transcript"),
        asr_result.get("text"),
    ]
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        normalized = _normalize_confirmation_text(str(candidate))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        classification = classify_confirmation_reply(normalized)
        if classification != "unknown":
            return classification
    return "unknown"


def should_synthesize_as_single_chunk(text: str) -> bool:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return False
    if 0 < VAD_TTS_SINGLE_CHUNK_MAX_CHARS >= len(normalized):
        return True
    clarity_markers = (
        "አዎ ወይም አይ",
        "እባክዎን ሰብሉን",
        "ተጨማሪ መረጃ",
        "እንደገና ይናገሩ",
        "አልተረዳሁም",
    )
    return (
        len(normalized) <= max(80, VAD_TTS_SINGLE_CHUNK_MAX_CHARS)
        and any(marker in normalized for marker in clarity_markers)
    )


def build_asr_confirmation_prompt(transcript: str, existing_prompt: str | None = None) -> str:
    normalized_transcript = re.sub(r"\s+", " ", (transcript or "").strip())
    prompt = re.sub(r"\s+", " ", (existing_prompt or "").strip())
    if normalized_transcript and normalized_transcript in prompt:
        return prompt
    if normalized_transcript:
        return (
            f"የሰማሁት ይህ ነው፦ {normalized_transcript}። "
            "ልክ ከሆነ አዎ ወይም።"
            "ልክ ካልሆነ ደግሞ አይ ይበሉ።"
        )
    return prompt or "የሰማሁት ግልፅ አልሆነልኝም። እባክዎ ጥያቄዎን እንደገና ይናገሩ።"

def _split_long_words(text: str, max_chars: int) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_tts_text(text: str, max_chars: int | None = None) -> list[str]:
    """Split long spoken text into natural TTS-sized chunks."""
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    if not normalized:
        return []
    if max_chars is None and should_synthesize_as_single_chunk(normalized):
        return [normalized]

    if max_chars is None:
        max_chars = VAD_TTS_CHUNK_MAX_CHARS
    max_chars = max(60, int(max_chars or 140))

    pieces = [
        piece.strip()
        for piece in re.findall(r".+?(?:[።!?፤፣,;]|$)", normalized)
        if piece.strip()
    ]
    chunks: list[str] = []
    current = ""

    for piece in pieces:
        subpieces = [piece]
        if len(piece) > max_chars:
            subpieces = _split_long_words(piece, max_chars)

        for subpiece in subpieces:
            candidate = f"{current} {subpiece}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = subpiece
            else:
                current = candidate

    if current:
        chunks.append(current)
    return chunks
