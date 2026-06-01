import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from voice_flow import (
    build_asr_confirmation_prompt,
    chunk_tts_text,
    classify_confirmation_reply,
    classify_confirmation_reply_from_asr,
    should_synthesize_as_single_chunk,
)
from transcript_quality import is_asr_gibberish


def test_classify_confirmation_reply_amharic_yes_no():
    assert classify_confirmation_reply("አዎ ትክክል ነው") == "yes"
    assert classify_confirmation_reply("አይ አይደለም") == "no"


def test_classify_confirmation_reply_accepts_asr_yes_variants():
    for text in ("awo", "aw", "አው", "አዋ", "ኣዎ", "እሽ", "eshi", "ok"):
        assert classify_confirmation_reply(text) == "yes"


def test_classify_confirmation_reply_does_not_match_inside_unrelated_words():
    assert classify_confirmation_reply("የአፈር አይነት") == "unknown"
    assert classify_confirmation_reply("በቆሎ አውጪ ተባይ") == "unknown"
    assert classify_confirmation_reply("አውም ትክክል") == "yes"


def test_classify_confirmation_reply_uses_raw_asr_when_final_is_unclear():
    result = {
        "transcript": "አ ወ",
        "final_transcript": "አው",
        "raw_transcript": "awo",
    }

    assert classify_confirmation_reply_from_asr(result) == "yes"


def test_short_clarity_prompt_is_single_tts_chunk():
    prompt = "የጠየቁት፦ በቆሎ ላይ ተባይ አለ ነው? እባክዎ አዎ ወይም አይ ይበሉ።"

    assert should_synthesize_as_single_chunk(prompt) is True


def test_long_tts_text_is_split_into_manageable_chunks():
    text = (
        "የስንዴ ተባይ ችግር ካለ መጀመሪያ ቅጠሉን ይመርምሩ ከዚያም የተጎዳውን ክፍል "
        "በጥንቃቄ ያስወግዱ እና የአካባቢዎን የግብርና ባለሙያ በመጠየቅ ትክክለኛውን "
        "የመከላከያ ዘዴ ይምረጡ።"
    )
    chunks = chunk_tts_text(text, max_chars=80)

    assert len(chunks) > 1
    assert all(len(chunk) <= 90 for chunk in chunks)


def test_short_greeting_and_confirmation_words_are_not_gibberish():
    for text in ("selam", "ሰላም", "eshi", "እሺ", "awo"):
        assert is_asr_gibberish(text, confidence=0.05) is False


def test_asr_confirmation_prompt_includes_assumed_transcript():
    prompt = build_asr_confirmation_prompt("በቆሎ ላይ ተባይ አለ", "እባክዎ አዎ ወይም አይ ይበሉ።")

    assert "በቆሎ ላይ ተባይ አለ" in prompt
    assert "አዎ" in prompt
    assert "አይ" in prompt
