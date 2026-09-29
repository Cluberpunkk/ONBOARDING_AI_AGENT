"""
The dialogue manager — intent handling and the plan validator.

Two jobs:

1. Turn a routed intent into a speech PLAN made only of curated keys
   (T1 questions / T2 fragments / KB answers). Nothing here can author prose.

2. VALIDATE every plan before it reaches the speaker. This is the structural
   half of the anti-hallucination guarantee: even if the model returns a made-up
   key or a free-text sentence, validate() drops it. The prompt asks nicely;
   this makes it impossible.
"""
from __future__ import annotations

import logging

from core import fragments, kb
from core.questions import S

log = logging.getLogger("sakhi.dialogue")

T1, T2, T3, KB_TIER = "T1", "T2", "T3", "KB"
EXPAND = "EXPAND"      # clarification expansions: "what this field means"

# Intents the router may emit (mirrored in core/extractor.INTENTS)
ANSWER_INTENTS = {"answer_current", "answer_other_slots", "correction"}


def known_key(lang: str, tier: str, key: str) -> bool:
    if tier == T1:
        return key in S.get(lang, S["en"]) or key in S["en"]
    if tier == T2:
        return fragments.exists(lang, key)
    if tier == KB_TIER:
        return kb.exists(key)
    return False


def validate(lang: str, plan: list) -> list[dict]:
    """Keep only well-formed parts naming keys that actually exist. Anything
    else — invented keys, free text, wrong tiers — is discarded silently."""
    clean = []
    for part in plan or []:
        if not isinstance(part, dict):
            continue
        tier, key = part.get("tier"), part.get("key")
        if not isinstance(tier, str) or not isinstance(key, str):
            continue
        if tier == T3:                      # T3 is budgeted elsewhere, never free text here
            continue
        if tier == EXPAND:
            from core.questions import expansion_text
            if expansion_text(lang, key):
                clean.append({"tier": EXPAND, "key": key})
            continue
        if known_key(lang, tier, key):
            out = {"tier": tier, "key": key}
            # Carry the subject through so part_text picks the right variant.
            if tier == T1 and part.get("for_whom"):
                out["for_whom"] = part["for_whom"]
            clean.append(out)
    return clean


def part_text(lang: str, part: dict) -> str | None:
    """Returns the text AND whether it is genuinely in the requested language.
    A silent fall-through to English is the bug that puts a robotic male voice
    mid-conversation: the English string has no Hindi cache entry, so the whole
    prompt drops to browser TTS."""
    tier, key = part["tier"], part["key"]
    if tier == EXPAND:
        from core.questions import expansion_text
        return expansion_text(lang, key)
    if tier == T1:
        from core.questions import S, question_text
        if key not in S.get(lang, {}):
            log.warning("LANGUAGE FALLBACK: T1/%s missing in %r -> English text", key, lang)
        # Subject-aware when we know who the profile is for.
        return question_text(lang, key, part.get("for_whom"))
    if tier == T2:
        if key not in fragments.FRAGMENTS.get(lang, {}):
            log.warning("LANGUAGE FALLBACK: T2/%s missing in %r -> English text", key, lang)
        return fragments.text(lang, key)
    if tier == KB_TIER:
        entry = kb.KB.get(key) or {}
        if lang not in entry:
            log.warning("LANGUAGE FALLBACK: KB/%s missing in %r -> English text", key, lang)
        return kb.text(lang, key)
    return None


# --------------------------------------------------------------- intent plans
def side_question_plan(transcript: str, lang: str, session_id: str,
                       llm_key: str | None = None) -> tuple[list[dict], bool]:
    """KB answer + bridge, or a graceful 'I don't know' + steer back.
    Returns (plan, matched).

    The LLM's selection wins when it names a real key: it read the whole
    sentence, whereas a keyword hit can be a false friend ("क्या लोकल पैसे
    देता है?" contains पैसे but is NOT the is-it-free question). The LLM can
    only ever *select* — kb.exists() rejects anything it invents, and the
    keyword matcher is the free fallback."""
    key = llm_key if (llm_key and kb.exists(llm_key)) else None
    if not key:
        key = kb.match(transcript, lang)
    if key:
        return [{"tier": KB_TIER, "key": key}, {"tier": T2, "key": "steer_back"}], True
    kb.log_gap(transcript, lang, session_id)
    return [{"tier": T2, "key": "offscript_no_answer"},
            {"tier": T2, "key": "steer_back"}], False


def meta_plan(transcript: str, lang: str) -> list[dict]:
    t = (transcript or "").lower()
    slow_words = ("धीरे", "आराम", "slow", "मंद", "हळू", "மெதுவாக", "నెమ్మది")
    back_words = ("पीछे", "वापस", "back", "पिछला", "previous", "मागे")
    if any(w in t for w in slow_words):
        return [{"tier": T2, "key": "meta_slow"}]
    if any(w in t for w in back_words):
        return [{"tier": T2, "key": "meta_back"}]
    return [{"tier": T2, "key": "meta_repeat"}]


def nonsense_plan(strikes: int) -> list[dict]:
    """One calm redirect. A second time, offer text mode. Never scold."""
    if strikes >= 2:
        return [{"tier": T2, "key": "calm_redirect"}, {"tier": T2, "key": "text_mode_offer"}]
    return [{"tier": T2, "key": "calm_redirect"}]


def chitchat_plan() -> list[dict]:
    return [{"tier": T2, "key": "ack_ji"}, {"tier": T2, "key": "steer_back"}]


# ------------------------------------------------- clarify_current (Phase C)
# "किसका नाम?" is not an off-topic question (side_question) and not unparseable
# audio (unclear). It is: "I heard you, I don't understand what you're ASKING."
# Matched against this whitelist BEFORE any LLM call so it resolves in ~20 ms.
CLARIFY_PATTERNS = {
    # STEMS, not literal phrases. Matching whole phrases was too brittle: it
    # missed "क्या पूछ रही हो", "ज़रा फिर से" and "समझ में नहीं आया" (the infixed
    # में breaks a "समझ नहीं" substring), and every miss fell through to
    # `unclear` — i.e. counted as a failed answer. Stems + the short-utterance
    # guard keep recall high without reintroducing false positives.
    "hi": ["किसक",          # किसका / किसकी / किसके / किसको
           "कौन स",         # कौन सा / कौन सी / कौनसा
           "मतलब",
           "समझ न", "समझ म", "समझा न", "समझी न", "नहीं समझ", "समझ आ",
           "पूछ रह", "पूछ रही", "क्या पूछ", "पूछा क्या",
           "फिर से", "दोबारा", "दुबारा",
           "क्या बोल", "क्या कह", "किसके बारे", "किसकी बात"],
    "en": ["whose", "which one", "what do you mean", "understand", "come again",
           "say that again", "about whom", "what was that", "repeat that"],
}

# Question-shaped stems used ONLY by the near-miss safety net below: a short
# utterance we could not parse that carries one of these is far more likely to
# be "I don't understand the question" than a failed answer.
NEAR_MISS_STEMS = {
    "hi": ["क्या", "कौन", "किस", "कैसे", "कैसा", "मतलब", "समझ", "पूछ", "बोल",
           "कह", "फिर", "दोबारा", "बता"],
    "en": ["what", "which", "who", "whose", "how", "mean", "repeat", "again",
           "understand", "sorry", "pardon"],
}
# Short bare interrogatives only count when the whole utterance is one of them —
# "क्या?" alone is a clarification; "क्या मैं बेटी की बात करूँ" is not.
CLARIFY_EXACT = {
    "hi": ["क्या", "क्या?", "जी", "जी?", "हैं?", "मतलब?", "कौन", "कौन?",
           "किसका?", "मैं", "मैं?", "कैसा", "कैसे"],
    "en": ["what", "what?", "sorry", "sorry?", "huh", "huh?", "eh", "pardon",
           "who", "who?", "me", "me?", "meaning", "meaning?"],
}


def looks_like_question(transcript: str, lang: str) -> bool:
    """NEAR-MISS SAFETY NET. Used only after extraction produced nothing usable:
    a short, question-shaped utterance must route to the clarification ladder
    (she re-explains) rather than to `unclear` (which counts as a failed answer
    and marches the user toward the text fallback). A whitelist miss must never
    be punished as a failure."""
    t = (transcript or "").strip().lower()
    if not t or len(t.split()) > 7:
        return False
    if t.endswith("?"):
        return True
    stems = NEAR_MISS_STEMS.get(lang, []) + NEAR_MISS_STEMS["en"]
    return any(s in t for s in stems)


def is_clarification(transcript: str, lang: str) -> bool:
    t = (transcript or "").strip().lower()
    if not t:
        return False
    bare = t.rstrip("?।.! ")
    if bare in [x.rstrip("?।.! ") for x in CLARIFY_EXACT.get(lang, []) + CLARIFY_EXACT["en"]]:
        return True
    # Multi-word clarifications: must be short. A long sentence containing
    # "मतलब" is usually a real answer, not a request to re-explain.
    if len(t.split()) > 6:
        return False
    pats = CLARIFY_PATTERNS.get(lang, []) + CLARIFY_PATTERNS["en"]
    return any(p in t for p in pats)


def clarify_ladder(lang: str, key: str, count: int, for_whom: str | None) -> list[dict]:
    """Escalate, never repeat identically.
      1st -> "जी," + the subject-aware question (Phase B asset)
      2nd -> a fuller expansion: what the field IS, in plain words
      3rd -> offer the text box and move on gracefully
    """
    if count <= 1:
        return [{"tier": T2, "key": "ack_ji"},
                {"tier": T1, "key": key, "for_whom": for_whom}]
    if count == 2:
        from core.questions import expansion_text
        if expansion_text(lang, key):
            return [{"tier": "EXPAND", "key": key}]
        return [{"tier": T2, "key": "meta_repeat"},
                {"tier": T1, "key": key, "for_whom": for_whom}]
    return [{"tier": "EXPAND", "key": key} if _has_expansion(lang, key)
            else {"tier": T1, "key": key, "for_whom": for_whom},
            {"tier": T2, "key": "text_mode_offer"}]


def _has_expansion(lang: str, key: str) -> bool:
    from core.questions import expansion_text
    return bool(expansion_text(lang, key))
