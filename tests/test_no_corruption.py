"""
THE invariant: a non-answer must never become an answer.

This is the most valuable test in the repo, because every other failure mode is
recoverable and this one is not. A filled slot is never re-asked, so a value
invented from "पता नहीं" or "ज़्यादा नहीं पढ़ी" is permanent, user-visible, and
silent — the session looks perfectly healthy while writing a fact the user never
gave into their matrimony profile.

It is also the failure the model produces most willingly. Asked to extract, it
extracts; "डिग्री का नाम बताऊं" ("shall I tell you the degree name?") came back
as qualification=`bachelors`, an answer that appears nowhere in the utterance.
Prompting does not fix this — §5 says so explicitly and the model still did it.
So the rule is enforced in code and asserted here, for EVERY slot.

Three shapes of non-answer, per slot:
  DONT_KNOW  — they cannot answer          ("याद नहीं", "पता नहीं")
  VAGUE      — they said something unquantified, naming no value
  ASKING     — they asked about the question instead of answering it

Outcomes that PASS: the slot is empty, or (for a skippable field) skipped.
The only outcome that fails is `filled`.

Run: python3 tests/test_no_corruption.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_pin import pin, assert_all_reads_pinned, declare_unpinned   # noqa: E402

pin(CONVERSATION_MODE="agentic", BARGE_IN_ENABLED=False,
    VAD_ENDPOINTING_ENABLED=False, AVATAR_ENABLED=False,
    # Must match the recipe the cache was warmed with, or coverage collapses and
    # the session silently runs classic — testing a path that isn't the one here.
    ELEVENLABS_API_KEY="",
    ELEVENLABS_VOICE_ID="PId0lEbL3SOYkQZSraml",
    ELEVENLABS_MODEL="eleven_v4",
    ELEVENLABS_STABILITY=0.75, ELEVENLABS_SIMILARITY=0.80,
    ELEVENLABS_STYLE=0.15, ELEVENLABS_SPEED=0.97,
    ACK_RATE=0.0, THINK_TIME_MS_RANGE=(0, 0), THINK_TIME_MS_RANGE_DEEP=(0, 0),
    TURN_GAP_MS_RANGE=(0, 0))
declare_unpinned("GEMINI_API_KEY", "PARSER_MODEL",
                 reason="live model calls are the point of this suite")

from core import agentic, session as sm                # noqa: E402
from core.slots import SKIPPABLE, SLOT_PRIORITY        # noqa: E402

SEED = {
    "for_whom": "self", "full_name": "Rahul Sharma", "gender": "male",
    "dob": "1995-03-12", "district": "Jaipur", "religion": "hindu",
    "marital": "never_married", "qualification": "graduate", "job": "business",
    "income": 20000, "caste": "general",
}

# Real speech. Each one names NO value for its field.
NON_ANSWERS = {
    "for_whom": [
        ("ASKING", "किसके लिए मतलब"),
        ("ASKING", "समझ नहीं आया"),
        ("DONT_KNOW", "अभी तय नहीं किया"),
    ],
    "full_name": [
        ("ASKING", "किसका नाम पूछ रही हो"),
        ("ASKING", "पूरा नाम मतलब"),
        ("VAGUE", "नाम तो बता ही दिया था"),
    ],
    "dob": [
        ("DONT_KNOW", "तारीख़ याद नहीं"),
        ("DONT_KNOW", "जन्म तारीख़ पता नहीं"),
        ("VAGUE", "बहुत पुरानी बात है"),
        ("ASKING", "जन्म तारीख़ मतलब"),
    ],
    "district": [
        ("DONT_KNOW", "ज़िला नहीं पता"),
        ("VAGUE", "हम तो गाँव में रहते हैं"),
        ("ASKING", "कौन सा ज़िला"),
    ],
    "religion": [
        ("ASKING", "ये क्यों पूछ रहे हैं"),
        ("ASKING", "क्या ऑप्शन हैं"),
        ("VAGUE", "जो सब मानते हैं वही"),
    ],
    "marital": [
        ("ASKING", "मतलब क्या"),
        ("ASKING", "क्या ऑप्शन हैं"),
        ("ASKING", "समझ नहीं आया"),
    ],
    "qualification": [
        ("VAGUE", "ज़्यादा नहीं पढ़ी"),
        ("VAGUE", "बीच में छोड़ दी थी"),
        ("ASKING", "डिग्री का नाम बताऊं"),
        ("ASKING", "कितनी पढ़ाई मतलब"),
    ],
    "job": [
        ("ASKING", "काम मतलब क्या"),
        ("VAGUE", "अभी कुछ तय नहीं है"),
        ("DONT_KNOW", "क्या बताऊं समझ नहीं आ रहा"),
    ],
    "caste": [
        ("ASKING", "ये क्यों पूछना ज़रूरी है"),
        ("ASKING", "मतलब क्या"),
    ],
    "income": [
        ("VAGUE", "ठीक-ठाक है"),
        ("VAGUE", "गुज़ारा हो जाता है"),
        ("VAGUE", "फिक्स नहीं है"),
        ("ASKING", "महीने का या साल का"),
    ],
}


def seat(question: str):
    """Fresh session sitting at `question`, with earlier slots seeded directly."""
    sess, _, _ = sm.start("hi")
    state = sess.slot_state
    for key in SLOT_PRIORITY:
        if key == question:
            break
        if key in SKIPPABLE:
            state.skip(key)
        else:
            state.fill(key, SEED[key], str(SEED[key]), confidence=1.0,
                       source="spoken")
    assert state.next_slot() == question, \
        f"seeding landed on {state.next_slot()!r}, not {question!r}"
    state.mark_asked(question)
    return sess


def test_classic_skip_vocabulary_is_untouched():
    """The agentic skip layer must EXTEND, never edit, the shared list — classic
    mode is required to stay byte-identical."""
    from core.extractor import AGENTIC_SKIP_PHRASES, _is_skip_ext
    from core.parser import SKIP_WORDS, _is_skip

    expected = [
        "skip", "स्किप", "बाद में", "आगे", "नंतर", "ஸ்கிப்", "பிறகு", "స్కిప్",
        "తర్వాత", "ಸ್ಕಿಪ್", "ಆಮೇಲೆ", "സ്കിപ്പ്", "പിന്നീട്", "স্কিপ", "পরে",
        "સ્કિપ", "પછી", "later", "not now", "nahi", "नहीं", "no",
    ]
    assert SKIP_WORDS == expected, (
        "core.parser.SKIP_WORDS changed — classic mode is no longer "
        "byte-identical. The agentic layer must extend, not edit.")
    assert not _is_skip("छोड़ दीजिए"), \
        "classic _is_skip now matches an agentic-only phrase — the layers leaked"
    assert _is_skip_ext("छोड़ दीजिए"), "agentic layer does not recognise 'छोड़ दीजिए'"
    for w in ("skip", "बाद में", "नहीं"):
        assert _is_skip_ext(w), f"agentic layer lost the classic word {w!r}"
    assert AGENTIC_SKIP_PHRASES, "agentic skip phrase list is empty"
    print(f"  ok  classic SKIP_WORDS untouched; agentic adds "
          f"{len(AGENTIC_SKIP_PHRASES)} phrases on top")


def test_caste_and_religion_are_never_inferred():
    """C9. Surnames carry caste in India, and the model will read it off one.

    Found live, not in a fixture: a plain session — "अपने लिए" / "राहुल शर्मा" /
    "हाँ" / "मैं जयपुर से हूं" — stored caste=`Sharma` in 1 of 6 identical runs.
    Nobody stated it, the slot is never re-asked, and the skip the user was
    entitled to on a sensitive field was never offered. Intermittent, so a
    single run proves nothing; this repeats the session enough to catch it.
    """
    RUNS = 6
    script = ["अपने लिए", "किसका नाम पूछ रही हो", "राहुल शर्मा", "हाँ",
              "मैं जयपुर से हूं"]
    inferred = []
    for _ in range(RUNS):
        sess, _, _ = sm.start("hi")
        for utt in script:
            agentic.handle_turn(sess, utt)
        for key in ("caste", "religion"):
            slot = sess.slot_state.slots[key]
            if slot.status == "filled":
                inferred.append((key, slot.value))
    assert not inferred, (
        f"{len(inferred)}/{RUNS} sessions inferred a sensitive identity field "
        f"nobody stated: {inferred}. This is C9 — and it is never re-asked.")

    # ...but a value the user actually STATES must still be captured.
    for key, said, expect in [("caste", "शर्मा", "Sharma"),
                              ("caste", "ब्राह्मण", "Brahman"),
                              ("religion", "हिन्दू", "Hindu")]:
        sess = seat(key)
        agentic.handle_turn(sess, said)
        slot = sess.slot_state.slots[key]
        assert slot.status == "filled", \
            f"{key} stated as {said!r} was NOT captured — the guard is too wide"
    print(f"  ok  caste/religion never inferred across {RUNS} sessions; "
          "stated values still captured")


def test_a_non_answer_never_fills_any_slot():
    rows, failures = [], []
    for question, cases in NON_ANSWERS.items():
        filled = 0
        for shape, utt in cases:
            sess = seat(question)
            agentic.handle_turn(sess, utt)
            slot = sess.slot_state.slots[question]
            if slot.status == "filled":
                filled += 1
                failures.append((question, shape, utt, slot.value))
        rows.append((question, len(cases), filled))

    print(f"\n  {'slot':<15}{'cases':>7}{'FILLED':>9}")
    print("  " + "-" * 31)
    for q, n, f in rows:
        print(f"  {q:<15}{n:>7}{f:>9}{'  <-- corruption' if f else ''}")
    print("  " + "-" * 31)
    print(f"  {'TOTAL':<15}{sum(r[1] for r in rows):>7}{sum(r[2] for r in rows):>9}")

    if failures:
        print("\n  values invented from non-answers:")
        for q, shape, utt, val in failures:
            print(f"    [{shape}] {q} <- {utt!r}  stored {val!r}")
    assert not failures, (
        f"{len(failures)} slot(s) filled from a non-answer. These are never "
        "re-asked, so each one ships a fact the user never gave.")
    print("\n  ok  no slot can be filled by a non-answer")


if __name__ == "__main__":
    print("CORRUPTION INVARIANT")
    test_classic_skip_vocabulary_is_untouched()
    test_caste_and_religion_are_never_inferred()
    test_a_non_answer_never_fills_any_slot()
    assert_all_reads_pinned()
    print("\nCORRUPTION INVARIANT PASSED")
