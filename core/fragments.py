"""
T2 — the conversational fragment library.

Fixed strings, exactly like the T1 questions, so they cache once and cost Rs 0
forever. The dialogue manager may only reference these KEYS; it can never emit a
sentence of its own. That is the anti-hallucination mechanism, enforced
structurally by resolve() dropping unknown keys.

PHASE 1 SCAFFOLD: this is the minimum set the slot machine needs to behave
conversationally (acks, confirmations, bridges). The full ~50-fragment library
plus the ~18 KB answers is written, reviewed and GENERATED in Phase 3 — until
then these have no audio, and resolve() degrades to browser TTS rather than
spending a single character (see tts.lookup, cache-only).

Register: locked bol-chaal didi voice. One breath each.
"""
from __future__ import annotations

import random

# Acknowledgment pool — repetition control picks from here, never twice in a row.
ACK_KEYS = ["ack_ok", "ack_good", "ack_noted", "ack_understood", "ack_right", "ack_ji"]

# SESSION ARC: humans get more casual as a conversation settles. Warmer, longer
# acknowledgments early; clipped ones once rapport exists.
ACK_EARLY = ["ack_noted", "ack_understood", "ack_right", "ack_sure"]
ACK_LATE = ["ack_ji", "ack_ok", "ack_fine", "ack_good"]
ARC_TURNS = 5          # roughly where "early" becomes "settled"

# Soft sentence-openers, used sparingly before a question.
SOFT_OPENERS = ["open_to", "open_accha", "open_chaliye", "bridge_resume"]

# Longer KB answers get a beat first so she doesn't launch into a paragraph.
PRE_ANSWER_BEATS = ["beat_batati_hoon", "beat_dekhiye"]

# Conversational recovery after a correction — never formal.
RECOVERY_KEYS = ["recover_oh", "recover_samjhi", "recover_theek"]

FRAGMENTS = {
"hi": {
    # --- acknowledgments (6) ---
    "ack_ok": "अच्छा।",
    "ack_good": "बढ़िया।",
    "ack_noted": "नोट कर लिया।",
    "ack_understood": "समझ गई।",
    "ack_right": "ठीक है।",
    "ack_ji": "जी।",
    # --- confirmations ---
    "confirm_gender_male": "लड़के के लिए, सही?",
    "confirm_gender_female": "लड़की के लिए, सही?",
    "confirm_generic": "ये सही है?",
    "batch_confirm": "अच्छा, ये सब नोट कर लिया।",
    # --- bridges ---
    "bridge_next": "चलिए, आगे बढ़ते हैं।",
    "bridge_remaining": "और बस ये बचा है।",
    "bridge_resume": "हाँ तो,",
    "bridge_where_we_were": "जहाँ थी वहीं से —",
    # --- corrections ---
    "correction_ack": "ठीक है, बदल दिया।",
    # --- interruption ---
    "interrupt_ack": "जी, बोलिए।",
    # --- off-script ---
    "offscript_no_answer": "ये मुझे नहीं पता, माफ़ कीजिए।",
    "offscript_later": "ये बाद में ऐप में देख लीजिएगा।",
    "steer_back": "चलिए, प्रोफाइल पूरी कर लेते हैं।",
    # --- meta ---
    "meta_repeat": "मैं फिर से पूछती हूँ।",
    "meta_slow": "ठीक है, आराम से।",
    "meta_back": "ठीक है, पीछे चलते हैं।",
    # --- nonsense / abuse: calm, never scolding ---
    "calm_redirect": "चलिए, प्रोफाइल पर वापस आते हैं।",
    "text_mode_offer": "आप नीचे टाइप करके भी बता सकते हैं।",
    # --- age given instead of a date ---
    "need_full_dob": "पूरी तारीख़ भी बता दीजिए।",
    # --- more acknowledgments (variety kills the robot feeling) ---
    "ack_sure": "जी बिलकुल।",
    "ack_fine": "ठीक।",
    # --- confirmations ---
    "confirm_one_more": "एक बार कन्फ़र्म कर दीजिए।",
    "confirm_heard_right": "मैंने सही सुना ना?",
    # --- multi-slot ---
    "batch_confirm_two": "दोनों बातें नोट कर लीं।",
    "batch_remaining": "और बस कुछ ही बाकी हैं।",
    # --- bridges ---
    "bridge_ok_moving": "ठीक है, आगे चलते हैं।",
    "bridge_one_second": "एक सेकंड, फिर से —",
    "bridge_almost": "बस थोड़ा और।",
    # --- meta ---
    "meta_no_problem": "कोई बात नहीं।",
    "meta_take_time": "आराम से सोचिए।",
    # --- listening / silence ---
    "still_listening": "जी, मैं सुन रही हूँ।",
    "didnt_hear": "आवाज़ नहीं आई।",
    # --- encouragement ---
    "encourage_good": "बहुत बढ़िया चल रहा है।",
    "encourage_last": "बस आख़िरी सवाल।",
    # --- photo stage ---
    "photo_nudge": "फोटो बाद में भी लगा सकते हैं।",
    # --- review stage ---
    "review_check": "एक बार देख लीजिए।",
    # --- reactions: ECHO the captured value, never evaluate the person.
    # Neutral fields only (job, qualification). No reaction on caste, religion,
    # income, marital status, gender — or on "not working" / district, where any
    # remark at all reads as a judgement about circumstances.
    "react_farming": "अच्छा, खेती।",
    "react_business": "अच्छा, बिज़नेस।",
    "react_job": "अच्छा, नौकरी।",
    "react_student": "अच्छा, पढ़ाई चल रही है।",
    "react_10th": "अच्छा, दसवीं।",
    "react_12th": "अच्छा, बारहवीं।",
    "react_diploma": "अच्छा, डिप्लोमा।",
    "react_graduate": "अच्छा, ग्रेजुएशन।",
    "react_masters": "अच्छा, मास्टर्स।",
    "react_phd": "अच्छा, पीएचडी।",
    # --- connectives: chain naturally-linked consecutive questions ---
    "conn_and": "और",
    "conn_so": "अच्छा, तो",
    "conn_and_now": "और अब",
    # --- soft openers (sparse; never before a sensitive question) ---
    "open_to": "तो,",
    "open_accha": "अच्छा,",
    "open_chaliye": "चलिए,",
    # --- pre-answer beat before a longer KB answer ---
    "beat_batati_hoon": "जी, बताती हूँ —",
    "beat_dekhiye": "देखिए,",
    # --- conversational recovery after a correction ---
    "recover_oh": "ओह, ठीक है।",
    "recover_samjhi": "अच्छा, समझ गई।",
    "recover_theek": "हाँ, ठीक कर देती हूँ।",
    # --- patience beat when the user took a while (warmth, not a re-ask) ---
    "patience": "कोई जल्दी नहीं।",
},
"en": {
    "ack_ok": "Okay.",
    "ack_good": "Lovely.",
    "ack_noted": "Noted.",
    "ack_understood": "Got it.",
    "ack_right": "Right.",
    "ack_ji": "Sure.",
    "confirm_gender_male": "For a boy, correct?",
    "confirm_gender_female": "For a girl, correct?",
    "confirm_generic": "Is that right?",
    "batch_confirm": "Okay, I've noted all of that.",
    "bridge_next": "Let's move on.",
    "bridge_remaining": "Just this left.",
    "bridge_resume": "So then,",
    "bridge_where_we_were": "Where we were —",
    "correction_ack": "Okay, changed it.",
    "interrupt_ack": "Yes, go ahead.",
    "offscript_no_answer": "I don't know that one, sorry.",
    "offscript_later": "You can check that in the app afterwards.",
    "steer_back": "Let's finish the profile.",
    "meta_repeat": "Let me ask that again.",
    "meta_slow": "Okay, taking it slow.",
    "meta_back": "Okay, let's go back.",
    "calm_redirect": "Let's get back to the profile.",
    "text_mode_offer": "You can also type your answer below.",
    "need_full_dob": "Please tell me the full date too.",
    "ack_sure": "Sure thing.",
    "ack_fine": "Fine.",
    "confirm_one_more": "Just confirm once.",
    "confirm_heard_right": "Did I hear that right?",
    "batch_confirm_two": "Noted both of those.",
    "batch_remaining": "Just a few left.",
    "bridge_ok_moving": "Okay, moving on.",
    "bridge_one_second": "One second, again —",
    "bridge_almost": "Almost there.",
    "meta_no_problem": "No problem.",
    "meta_take_time": "Take your time.",
    "still_listening": "Yes, I'm listening.",
    "didnt_hear": "I couldn't hear that.",
    "encourage_good": "This is going really well.",
    "encourage_last": "Just the last question.",
    "photo_nudge": "You can add the photo later too.",
    "review_check": "Have a look through.",
    "react_farming": "Ah, farming.",
    "react_business": "Ah, business.",
    "react_job": "Ah, a job.",
    "react_student": "Ah, still studying.",
    "react_10th": "Ah, tenth.",
    "react_12th": "Ah, twelfth.",
    "react_diploma": "Ah, a diploma.",
    "react_graduate": "Ah, graduation.",
    "react_masters": "Ah, masters.",
    "react_phd": "Ah, PhD.",
    "conn_and": "And",
    "conn_so": "Okay, so",
    "conn_and_now": "And now",
    "open_to": "So,",
    "open_accha": "Okay,",
    "open_chaliye": "Alright,",
    "beat_batati_hoon": "Yes, let me tell you —",
    "beat_dekhiye": "See,",
    "recover_oh": "Oh, okay.",
    "recover_samjhi": "Ah, I see.",
    "recover_theek": "Yes, I'll fix that.",
    "patience": "No hurry at all.",
},
}


def text(lang: str, key: str) -> str | None:
    return FRAGMENTS.get(lang, FRAGMENTS["en"]).get(key) or FRAGMENTS["en"].get(key)


def exists(lang: str, key: str) -> bool:
    return text(lang, key) is not None


def pick_ack(used: list[str], turn: int = 0) -> str:
    """Repetition control + session arc: never the same acknowledgment twice in
    a row, prefer unused ones, and bias warm-and-longer early / clipped later."""
    arc = ACK_EARLY if turn < ARC_TURNS else ACK_LATE
    candidates = [k for k in arc if exists("hi", k)] or ACK_KEYS
    fresh = [k for k in candidates if k not in used]
    pool = fresh or [k for k in candidates if not used or k != used[-1]] or candidates
    return random.choice(pool)


def pick_from(keys: list[str], used: list[str], lang: str = "hi") -> str | None:
    """Pick an unused-recently key from a pool, skipping any without text."""
    avail = [k for k in keys if exists(lang, k)]
    if not avail:
        return None
    fresh = [k for k in avail if k not in used]
    pool = fresh or [k for k in avail if not used or k != used[-1]] or avail
    return random.choice(pool)


def opener_word(lang: str, key: str) -> str:
    """First word of a fragment/question — used to stop consecutive turns
    starting with the same word."""
    t = (text(lang, key) or "").strip()
    return t.split(" ")[0].strip(",।?!") if t else ""
