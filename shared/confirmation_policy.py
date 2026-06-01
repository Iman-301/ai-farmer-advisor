"""ASR confirmation and clarify-reprompt policy for the VAD orchestrator."""

from __future__ import annotations

import os
import re


CLARIFY_REPROMPT_AM = (
    "ይቅርታ፣ ጥያቄዎን በትክክል አልተረዳኩም። "
    "እባክዎ በአማርኛ እንደገና በግልጽ ይናገሩ።"
)


def vad_confirmation_gate_enabled() -> bool:
    return os.getenv("VAD_CONFIRMATION_GATE", "0").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _as_float(value) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def vad_flow_decision(asr_result: dict) -> str:
    """
    Returns:
      - confirm: ask yes/no before RAG
      - reprompt: low confidence — ask to repeat
      - proceed: send to RAG
    """
    if asr_result.get("needs_confirmation"):
        return "confirm"

    conf = _as_float(asr_result.get("confidence"))
    threshold = _as_float(os.getenv("VAD_ASR_REPROMPT_CONF", "0.55")) or 0.55
    transcript = (asr_result.get("transcript") or "").strip()

    if conf is not None and conf < threshold and len(transcript) < 80:
        return "reprompt"
    return "proceed"


def best_transcript_from_asr(asr_result: dict) -> str:
    for key in (
        "final_transcript",
        "structured_transcript",
        "domain_corrected_transcript",
        "transcript",
        "text",
        "raw_transcript",
    ):
        val = asr_result.get(key)
        if val and str(val).strip():
            return re.sub(r"\s+", " ", str(val).strip())
    return ""


def apply_normalized_transcript_to_asr_result(asr_result: dict) -> dict:
    out = dict(asr_result)
    transcript = best_transcript_from_asr(out)
    if transcript:
        out["transcript"] = transcript
        out["vad_normalized_transcript"] = transcript
    return out
