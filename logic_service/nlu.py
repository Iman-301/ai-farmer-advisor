"""
Amharic-oriented NLU: intent classification + light entity extraction (SRS FR04-style).
Rule-based MVP — no training on your PDFs; more documents improve retrieval coverage, not this layer.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Optional

# Conservative folding so NLU keywords match common OCR/font spelling variants.
_ETHIOPIC_CHAR_FOLD: dict[str, str] = {
    "ሃ": "ሀ",
    "ኅ": "ሀ",
    "ኃ": "ሀ",
    "ሐ": "ሀ",
    "ሓ": "ሀ",
    "ኻ": "ሀ",
    "ሗ": "ኋ",
    # Removed: ዐ→አ, ዓ→አ, ዕ→እ — these merge semantically distinct words
    # e.g. ዓመት (year) ≠ አመት (hundred), ዓለም (world) ≠ አለም
    "ጸ": "ፀ",
    "ጹ": "ፁ",
    "ጺ": "ፂ",
    "ጻ": "ፃ",
    "ጼ": "ፄ",
    "ጽ": "ፅ",
    "ጾ": "ፆ",
}


def normalize_ethiopic_input(text: str) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    for old, new in _ETHIOPIC_CHAR_FOLD.items():
        t = t.replace(old, new)
    for z in ("\u200b", "\u200c", "\u200d", "\ufeff"):
        t = t.replace(z, "")
    # Preserve prior baseline behavior: collapse whitespace + lowercase.
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

# Crop / commodity mentions → English key used by market_prices table
CROP_KEYWORDS: dict[str, str] = {
    "ጤፍ": "Teff",
    "teff": "Teff",
    "ስንዴ": "Wheat",
    "wheat": "Wheat",
    "ቦሎቄ": "Maize",
    "corn": "Maize",
    "maize": "Maize",
    "ገብስ": "Barley",
    "barley": "Barley",
    "ቦርኬ": "Sorghum",
    "sorghum": "Sorghum",
    "ዳጉሳ": "Sorghum",
    "ሽምብራ": "Chickpea",
    "chickpea": "Chickpea",
    "ምስር": "Lentil",
    "lentil": "Lentil",
    "ቅቤ": "Butter",
    "ቡና": "Coffee",
    "coffee": "Coffee",
    "ሙዝ": "Banana",
    "banana": "Banana",
    "ሽንኩርት": "Onion",
    "onion": "Onion",
    "አኩሪ አተር": "Mung bean",
    "ሙንግ ባቄላ": "Mung bean",
    "ሙንግ": "Mung bean",
    "mung bean": "Mung bean",
    "ማሸላ": "Millet",
    "millet": "Millet",
}

CROP_ENTITY_WORDS = set(CROP_KEYWORDS.keys())

# Do not use bare "ስንት" — it matches agronomy ranges like "ከስንት እስከ ስንት ሚሊ ሜትር" (rainfall).
MARKET_KEYWORDS = [
    "ዋጋ",
    "ስንት ነው",
    "ገበያ",
    "price",
    "market",
    "cost",
    "ብር",
]

GREETING_KEYWORDS = [
    "ሰላም",
    "ሰላም ነው",
    "እንዴት ነህ",
    "እንዴት ነሽ",
    "እንዴት ነዎት",
    "ስምህ",
    "ስምሽ",
    "ስምዎ",
    "ማነህ",
    "ማነሽ",
    "ማን ነህ",
    "ማን ነሽ",
    "ማን ነዎት",
]

AGRI_INTENT_KEYWORDS = [
    "ማዳበሪያ",
    "ፀረ-ተባይ",
    "ፀረ ተባይ",
    "ምርት",
    "ዘር",
    "መዝራት",
    "fertilizer",
    "pest",
    "disease",
    "plant",
    "crop",
    "spray",
    "harvest",
    "ሰብል",
    "ለምለም",
    "ፍሬ",
    "ቅጠል",
    "መሬት",
    "ውኃ",
    "ጥበቃ",
    "extension",
    "ማራዘም",
    "ድህረ ምርት",
    "ድህረ-ምርት",
    "ማከማቻ",
    "ኪሳራ",
    "ደህንነት",
]

# (intent_id, keywords) — Amharic + English tokens; first match wins by score
_TOPIC_RULES: list[tuple[str, list[str]]] = [
    (
        "post_harvest",
        [
            "post-harvest",
            "postharvest",
            "phl",
            "ከመከር",
            "አከማችት",
            "አከማቻ",
            "ማከማቻ",
            "ሲከማች",
            "በጎተራ",
            "ድራር",
            "ማደስ",
            "እንዴት ይቆማል",
            "storage",
            "loss",
            "ጎተራ",
            "ኪሳራ",
            "እህል",
            "የእህል",
            "ማጠባበቅ",
            "የድህረ ምርት",
            "የድረ ምርት",
        ],
    ),
    (
        "soil_water_conservation",
        [
            "soil and water",
            "water conservation",
            "soil conservation",
            "የመሬት",
            "ውኃ",
            "ጥበቃ",
            "erosion",
            "terrace",
            "ቋሚነት",
        ],
    ),
    (
        "soil_fertility",
        [
            "soil fertility",
            "fertility",
            "ማዳበሪያ",
            "nutrient",
            "organic matter",
            "የመሬት ሀብት",
            "isfm",
            "የመሬት ስም",
        ],
    ),
    (
        "pest_disease",
        [
            "pest",
            "vector",
            "disease",
            "ፀረ",
            "ተባይ",
            "የቬክተር",
            "ቬክተር",
            "በሽታ",
            "አፈድ",
            "aphid",
            "russian wheat aphid",
            "የሩሲያ",
            "wheat value chain",
            "pvmp",
            "ipm",
        ],
    ),
    (
        "land_characterization",
        [
            "landpks",
            "ላንድፒኬኤስ",
            "soil type",
            "classification",
            "soil color",
            "አፈር ቀለም",
            "ውስንነት",
            "የመሬት አይነት",
            "land potential",
        ],
    ),
    (
        "extension_advisory",
        [
            "extension",
            "ማራዘም",
            "ማስፋፊያ",
            "ቁሳቁስ",
            "ቁሳቁሶች",
            "መመሪያ",
            "መምሪያ",
            "ፖስተር",
            "ፍሊፕ",
            "ፍሊፕ መጽሐፍ",
            "የውይይት ቡድን",
            "የመስክ ጉብኝት",
            "material",
            "ttl",
            "da ",
            "development agent",
            "የማራዘም",
        ],
    ),
    (
        "crop_production",
        [
            "lowland",
            "crop option",
            "ዝቅተኛ",
            "ሰብል",
            "irrigation",
            "መስኖ",
            "planting",
            "መዝራት",
            "cultivar",
            # Fodder / native vegetation guides (012) — beats extension_advisory on "መመሪያ" alone
            "መኖ",
            "እፅዋቶች",
            "እፅዋት",
            "ሳር",
        ],
    ),
]

# Short Amharic hints appended only for embedding search (not shown to user)
_RETRIEVAL_HINTS: dict[str, str] = {
    "post_harvest": "የከመር ምርት አያያዝ ማከማቻ እና ኪሳራ መቀነስ",
    "soil_water_conservation": "የመሬት እና ውኃ ጥበቃ እና መሬት ማቆየት",
    "soil_fertility": "የመሬት ሀብት ማዳበሪያ እና ISFM",
    "pest_disease": "ፀረ ተባይ እና በሽታ አስተዳደር",
    "land_characterization": "የመሬት ምድብ እና LandPKS",
    "extension_advisory": "የማራዘም ቅያት እና ሰነዶች",
    "crop_production": "የሰብል ምርት እና የመስኖ አማራጮች",
    "general_agronomy": "የግብርና ምክር እና ልምድ",
}


_TOKEN_RE = re.compile(r"[\u1200-\u137F]+|[A-Za-z]+")


def _tokens(text: str) -> list[str]:
    """Ethiopic tokens + ASCII letter tokens (avoid substring false-positives)."""
    return _TOKEN_RE.findall(text or "")


def _keyword_matches_text(text: str, kw: str) -> bool:
    """
    Match keywords without substring collisions.

    Examples:
    - Must NOT match \"መስኖ\" inside \"መመሪያ\".
    - ASCII keywords use word-boundary regex on lowered text.
    - Multi-word phrases match as contiguous substring on normalized whitespace.
    """
    if not kw:
        return False
    if len(kw) < 2:
        return False

    stripped = (text or "").strip()
    if not stripped:
        return False

    # Multi-token English phrases like \"soil and water\"
    if " " in kw.strip():
        norm_text = re.sub(r"\s+", " ", stripped.lower())
        return kw.lower() in norm_text

    # ASCII token-ish keywords → word boundaries
    if re.fullmatch(r"[A-Za-z][A-Za-z\-]*", kw):
        return re.search(rf"(?<!\w){re.escape(kw.lower())}(?!\w)", stripped.lower()) is not None

    # Ethiopic keyword → token match with light suffix tolerance.
    # This avoids substring collisions (e.g. መስኖ inside መመሪያ), but still matches
    # common Amharic affixes like "ው/ዋ/ን/ዎች".
    if re.search(r"[\u1200-\u137F]", kw):
        toks = _tokens(stripped)
        # Tighter affix budget for short stems (e.g. prevent ብር matching ብርሃን).
        suffix_budget = 2 if len(kw) <= 4 else 3
        prefix_budget = 1  # allow 1-char prefixes like የ-/በ-/ለ-
        _common_prefixes = {"የ", "በ", "ለ"}
        for tok in toks:
            if tok == kw:
                return True
            # Common suffixes: መመሪያ + ው → መመሪያው
            if tok.startswith(kw) and len(tok) <= len(kw) + suffix_budget:
                return True
            # Common prefixes: የ + ተባይ → የተባይ (should match "ተባይ")
            if tok.endswith(kw) and len(tok) <= len(kw) + prefix_budget:
                if tok[:1] in _common_prefixes:
                    return True
        return False

    # Fallback: substring match for mixed/unusual keywords
    lower = stripped.lower()
    return kw.lower() in lower or kw in stripped


@dataclass
class NLUResult:
    primary_intent: str
    confidence: float
    entities: dict[str, Any] = field(default_factory=dict)
    retrieval_query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "primary_intent": self.primary_intent,
            "confidence": round(self.confidence, 3),
            "entities": self.entities,
        }


def _extract_crop_entities(text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for kw, crop_en in CROP_KEYWORDS.items():
        if _keyword_matches_text(text, kw):
            out["crop_en"] = crop_en
            out["crop_keyword"] = kw
            break
    return out


def analyze_intent(text: str) -> NLUResult:
    """
    Classify farmer question intent and build a retrieval query
    (original question + optional Amharic topic hint for embedding).
    """
    stripped = normalize_ethiopic_input((text or "").strip())
    if not stripped:
        return NLUResult("unknown", 0.0, {}, "")

    # Greetings / chit-chat: do NOT trigger retrieval.
    if any(_keyword_matches_text(stripped, k) for k in GREETING_KEYWORDS):
        return NLUResult("greeting", 0.95, {}, stripped)

    entities = _extract_crop_entities(stripped)

    # Market price (separate data path in main)
    if any(_keyword_matches_text(stripped, k) for k in MARKET_KEYWORDS):
        conf = 0.88 if entities.get("crop_en") else 0.72
        return NLUResult("market_price", conf, entities, stripped)

    best_intent = "general_agronomy"
    best_score = 0
    for intent_id, keywords in _TOPIC_RULES:
        score = 0
        for kw in keywords:
            if _keyword_matches_text(stripped, kw):
                score += 1
        if score > best_score:
            best_score = score
            best_intent = intent_id

    if best_score == 0:
        # Weak agr signal → unknown vs general
        has_agri = any(_keyword_matches_text(stripped, k) for k in AGRI_INTENT_KEYWORDS)
        if has_agri:
            best_intent = "general_agronomy"
            best_score = 1
            conf = 0.42
        else:
            best_intent = "unknown"
            conf = 0.28
    else:
        conf = min(0.93, 0.38 + 0.11 * best_score)

    # For "unknown" we do NOT append topic hints; it can bias retrieval
    # away from the user's exact wording (e.g. manuals / extension materials).
    if best_intent == "unknown":
        retrieval = stripped
    else:
        hint = _RETRIEVAL_HINTS.get(best_intent, _RETRIEVAL_HINTS["general_agronomy"])
        retrieval = f"{stripped}\n{hint}"

    return NLUResult(
        primary_intent=best_intent,
        confidence=conf,
        entities=entities,
        retrieval_query=retrieval,
    )


def needs_slot_filling(text: str, session_state: Optional[dict], nlu: NLUResult) -> Optional[str]:
    """
    Ask for crop when agronomy question lacks crop (skipped for market / unknown with no agr).
    """
    if session_state and session_state.get("current_state") != "active":
        return None
    if nlu.primary_intent == "market_price":
        return None

    # Manual/extension/policy questions rarely need a crop entity.
    if nlu.primary_intent in {"extension_advisory", "land_characterization", "post_harvest"}:
        return None
    if nlu.primary_intent in {"greeting", "unknown"}:
        return None

    # "Principles"/"guidelines" questions are often answerable without a crop.
    # Don't block retrieval with crop slot-filling for these generic queries.
    generic_principles_markers = [
        "መርሆ",
        "መርሆዎች",
        "መመሪያ",
        "መመሪያዎች",
        "ዋና ዋና",
        "መሰረታዊ",
    ]
    if nlu.primary_intent == "pest_disease":
        if any(_keyword_matches_text(text, k) for k in generic_principles_markers):
            return None

    # Only ask for crop on intents where crop is usually required to give safe/specific advice.
    # Post-harvest and general info can often be answered generically.
    intents_requiring_crop = {
        "crop_production",
        "soil_fertility",
        "pest_disease",
    }
    if nlu.primary_intent not in intents_requiring_crop:
        return None

    has_agri = any(_keyword_matches_text(text, k) for k in AGRI_INTENT_KEYWORDS)
    has_crop = any(_keyword_matches_text(text, k) for k in CROP_ENTITY_WORDS)

    if has_agri and not has_crop:
        return "ለምን ሰብል ነው ጥያቄዎ? (ስንዴ፣ ጤፍ፣ ቦሎቄ፣ ወዘተ.)"
    return None
