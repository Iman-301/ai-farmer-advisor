"""Lightweight farmer query normalization before RAG."""

from __future__ import annotations

import re


def normalize_farmer_query(text: str) -> str:
    normalized = re.sub(r"\s+", " ", (text or "").strip())
    # Normalize common Ethiopic variant letters
    normalized = normalized.replace("ኣ", "አ").replace("ዐ", "አ").replace("ዓ", "አ")
    return normalized
