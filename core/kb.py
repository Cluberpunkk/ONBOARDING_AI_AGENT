"""
The knowledge base — the anti-hallucination mechanism.

Every fact Sakhi can state about Lokal lives here as a hand-written string.
The dialogue manager may only ever return a KB *key*; it cannot author a
sentence. If nothing matches, she says so and steers back — she never
improvises pricing, policy, features or timelines.

Unmatched questions are appended to data/kb_gaps.jsonl so the gaps become a
curation backlog instead of invisible failures (surfaced in /api/stats).

SCOPE RULE (hard, applies to every entry):
    KB answers describe THE PRODUCT, never the world.
No astrology, health, legal, financial or religious interpretation — not even a
helpful-sounding one-liner. When a user asks what मंगल दोष means, whether two
people are compatible, or what a medical/legal term implies, the only honest
answer is what Lokal does about it. Explaining the world is out of scope and
out of competence; a confident wrong answer is worse than no answer.

DEFERRAL POLICY (hard):
    When a claim cannot be verified, the answer DEFERS — it does not assert.
A content-free line pointing at the app's Help section is always safe;
"ये मैं पक्का नहीं बता सकती" beats a confident wrong answer every time. A KB
full of honest deferrals is strictly better than one with unverified claims,
because a deferral costs a little trust and a wrong claim costs all of it.

VERIFICATION STATUS: entries in FACTUAL_CLAIMS assert something about Lokal's
pricing, data handling, features or timelines. Those MUST be verified against
real product policy before their audio is generated — see
docs/kb_claims_signoff.md. Entries whose status is "deferred" make no claim
and are safe to ship as-is.

PHASE 2: text is curated here and reviewed with the Phase 3 fragment library;
audio is generated in Phase 3. Until then kb answers speak via browser TTS —
tts.lookup is cache-only, so an un-warmed entry costs nothing.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from config import settings

GAP_LOG = settings.DATA_DIR / "kb_gaps.jsonl"

# key -> {text per language, trigger keywords per language}
KB = {
"kb_is_free": {
    # CORRECTED: profile creation is free; contacting is a paid unlock. The old
    # "बिलकुल फ्री है" was a straight factual error about how Lokal monetizes.
    "hi": "प्रोफाइल बनाना बिलकुल फ्री है। आगे किसी से बात करने के लिए कुछ प्लान होते हैं, वो आप बाद में देख लीजिएगा।",
    "en": "Creating the profile is completely free. To contact someone later there are some plans — you can look at those afterwards.",
    "kw": {"hi": ["फ्री", "मुफ़्त", "मुफ्त", "पैसा", "पैसे", "चार्ज", "कितने का", "कीमत"],
           "en": ["free", "cost", "charge", "money", "price", "pay"]},
},
"kb_who_sees_data": {
    # DEFERRED — highest-risk entry in the set. Contact details are revealed
    # through paid unlocks, so "किसी को नहीं दिखता" would be a false privacy
    # promise. Defers until exact approved privacy wording is supplied.
    "hi": "ये मैं पक्का नहीं बता सकती। ऐप के मदद वाले हिस्से में प्राइवेसी की पूरी जानकारी दी हुई है।",
    "en": "I can't say that for certain. The full privacy details are in the Help section of the app.",
    "kw": {"hi": ["नंबर किसे", "नंबर किस", "कौन देखेगा", "कौन देखता", "डेटा", "प्राइवेसी", "नंबर दिख"],
           "en": ["who sees", "my number", "privacy", "data", "share my"]},
},
"kb_how_long": {
    "hi": "बस दो-तीन मिनट। कुछ ही सवाल बाकी हैं।",
    "en": "Just two or three minutes. Only a few questions left.",
    "kw": {"hi": ["कितना टाइम", "कितनी देर", "कितना समय", "कब तक"],
           "en": ["how long", "how much time", "how many questions"]},
},
"kb_photo_required": {
    # Engagement statistic removed — it was invented. States only what is true
    # of this flow: the photo step is optional and can be done later.
    "hi": "फोटो ज़रूरी नहीं है। बाद में भी लगा सकते हैं।",
    "en": "A photo isn't required. You can add it later.",
    "kw": {"hi": ["फोटो ज़रूरी", "फोटो जरूरी", "फोटो देना", "बिना फोटो"],
           "en": ["photo required", "must i add a photo", "without photo", "need a photo"]},
},
"kb_can_edit_later": {
    # DEFERRED per sign-off: post-creation edit rights unverified.
    "hi": "ये मैं पक्का नहीं बता सकती। ऐप के मदद वाले हिस्से में इसकी जानकारी मिल जाएगी।",
    "en": "I can't say that for certain. You'll find that in the Help section of the app.",
    "kw": {"hi": ["बदल सकते", "बदल सकता", "एडिट", "सुधार"],
           "en": ["edit later", "change later", "modify", "update it"]},
},
"kb_why_caste_income": {
    "hi": "ये सवाल सिर्फ़ सही रिश्ते दिखाने के लिए हैं। नहीं बताना चाहें तो स्किप बोल दीजिए।",
    "en": "These only help show suitable matches. If you'd rather not say, just say skip.",
    "kw": {"hi": ["जाति क्यों", "कमाई क्यों", "क्यों पूछ", "ये क्यों"],
           "en": ["why caste", "why income", "why do you need", "why ask"]},
},
"kb_are_you_real": {
    "hi": "मैं सखी हूँ, लोकल की आवाज़ वाली मदद। असली इंसान नहीं, पर आपकी प्रोफाइल पूरी बनवा दूँगी।",
    "en": "I'm Sakhi, Lokal's voice helper. Not a real person, but I'll get your profile done.",
    "kw": {"hi": ["असली", "इंसान हो", "रोबोट", "मशीन", "आदमी हो"],
           "en": ["are you real", "are you human", "robot", "a person", "bot"]},
},
"kb_delete_profile": {
    # CORRECTED per sign-off: deletion right kept, exact UI path dropped.
    "hi": "प्रोफाइल कभी भी हटा सकते हैं। कैसे करना है, वो ऐप के मदद वाले हिस्से में दिया हुआ है।",
    "en": "You can delete the profile at any time. How to do it is explained in the app's Help section.",
    "kw": {"hi": ["हटा", "डिलीट", "मिटा", "बंद कर"],
           "en": ["delete", "remove my profile", "close account"]},
},
"kb_after_profile": {
    # CORRECTED per sign-off: no immediacy claim, no personalisation claim.
    "hi": "प्रोफाइल बनने के बाद आपको रिश्तों की प्रोफाइल दिखने लगेंगी।",
    "en": "Once the profile is made, you'll start seeing other profiles.",
    "kw": {"hi": ["उसके बाद", "आगे क्या", "फिर क्या", "बनने के बाद"],
           "en": ["what happens after", "what next", "then what"]},
},
"kb_is_safe": {
    # DEFERRED per sign-off: data-use assertions need legal/policy wording.
    "hi": "ये मैं पक्का नहीं बता सकती। सुरक्षा और प्राइवेसी की पूरी जानकारी ऐप के मदद वाले हिस्से में दी हुई है।",
    "en": "I can't say that for certain. The full safety and privacy details are in the app's Help section.",
    "kw": {"hi": ["सुरक्षित", "सेफ", "भरोसा", "धोखा"],
           "en": ["is it safe", "secure", "trust", "scam"]},
},
"kb_family_use": {
    "hi": "बिलकुल। घर के किसी भी सदस्य के लिए प्रोफाइल बना सकते हैं।",
    "en": "Of course. You can make a profile for any family member.",
    "kw": {"hi": ["घरवाले", "परिवार", "मम्मी", "पापा", "भाई के लिए", "बहन के लिए"],
           "en": ["my family", "for my brother", "for my sister", "parents"]},
},
"kb_internet_slow": {
    "hi": "थोड़ा इंटरनेट चाहिए। धीमा चले तो नीचे टाइप करके भी जवाब दे सकते हैं।",
    "en": "A little internet is needed. If it's slow, you can also type your answers below.",
    "kw": {"hi": ["इंटरनेट", "नेट", "धीमा", "स्लो", "हैंग"],
           "en": ["internet", "data", "slow", "lagging", "hang"]},
},
"kb_change_language": {
    "hi": "हाँ, भाषा बदल सकते हैं। पेज दोबारा खोलकर अपनी भाषा चुन लीजिए।",
    "en": "Yes, you can change the language. Reopen the page and pick your language.",
    "kw": {"hi": ["भाषा बदल", "दूसरी भाषा", "हिंदी में", "इंग्लिश में"],
           "en": ["change language", "another language", "in english", "in hindi"]},
},
"kb_what_is_lokal": {
    "hi": "लोकल आपके शहर और भाषा का ऐप है। ये उसी का शादी-ब्याह वाला हिस्सा है।",
    "en": "Lokal is your city-and-language app. This is its matrimony section.",
    "kw": {"hi": ["लोकल क्या", "ये क्या ऐप", "कौन सा ऐप"],
           "en": ["what is lokal", "what app", "which app"]},
},
"kb_who_are_you": {
    "hi": "मैं सखी हूँ। आपकी प्रोफाइल बनाने में मदद करती हूँ।",
    "en": "I'm Sakhi. I help you create your profile.",
    "kw": {"hi": ["तुम कौन", "आप कौन", "कौन हो", "नाम क्या तुम्हारा"],
           "en": ["who are you", "your name", "what are you"]},
},
"kb_do_later": {
    # Corrected to match what is actually built: sessions live ~30 minutes in
    # memory. A short pause resumes; a long one does not. No storage promise.
    "hi": "थोड़ी देर रुककर वहीं से चालू कर सकते हैं। ज़्यादा देर हो जाए तो फिर से शुरू करना पड़ेगा।",
    "en": "You can pause a little while and pick up from there. If it's too long, we'll have to start again.",
    "kw": {"hi": ["बाद में करूँ", "बाद में कर", "अभी नहीं कर", "फिर करूँगा"],
           "en": ["do this later", "finish later", "not now"]},
},
"kb_dont_understand": {
    "hi": "कोई बात नहीं, मैं आसान शब्दों में फिर से पूछती हूँ।",
    "en": "No problem, let me ask that again in simpler words.",
    "kw": {"hi": ["समझ नहीं आया", "समझा नहीं", "मतलब क्या", "क्या पूछ"],
           "en": ["don't understand", "what do you mean", "didn't get"]},
},
"kb_talk_to_human": {
    # CORRECTED per sign-off: team is reachable via Help; no specific UI path.
    "hi": "अभी मैं ही हूँ। टीम तक पहुँचने का तरीक़ा ऐप के मदद वाले हिस्से में मिल जाएगा।",
    "en": "It's just me right now. You'll find how to reach the team in the app's Help section.",
    "kw": {"hi": ["इंसान से बात", "किसी से बात", "कस्टमर केयर", "हेल्पलाइन"],
           "en": ["talk to a human", "customer care", "support", "real person to talk"]},
},
"kb_kundli": {
    # SCOPE RULE in action: says what Lokal does, explains nothing about
    # astrology. No definition of मंगल दोष, no compatibility opinion — ever.
    "hi": "कुंडली मैं नहीं देख सकती। प्रोफाइल में जन्म की तारीख़ रहती है, बाकी बात आप दोनों परिवार आपस में तय कर लीजिएगा।",
    "en": "I can't check kundli. The profile keeps the date of birth; the two families can discuss the rest between themselves.",
    "kw": {"hi": ["कुंडली", "मंगल दोष", "मांगलिक", "राशि", "ज्योतिष", "गुण मिलान", "नक्षत्र", "जन्म कुंडली"],
           "en": ["kundli", "horoscope", "manglik", "mangal dosh", "astrology", "zodiac", "star sign", "compatib"]},
},
}

KB_KEYS = tuple(KB.keys())

# Entries that assert something about Lokal's pricing, data handling, features
# or timelines. Each must be checked against real product policy BEFORE its
# audio is generated. Everything not listed here is self-descriptive or refers
# only to behavior this app itself implements.
FACTUAL_CLAIMS = {
    # key: (english statement of the claim, status)
    #   unverified -> asserts something; MUST be signed off before generation
    #   deferred   -> makes no claim; safe to ship as written
    #   verified   -> checked against real Lokal policy
    "kb_is_free":        ("Creating a profile is free; contacting someone later "
                          "requires a paid plan.", "verified"),
    "kb_who_sees_data":  ("(defers) Points the user to the app's Help section for "
                          "privacy details. Makes no privacy promise.", "deferred"),
    "kb_photo_required": ("The photo step is optional and can be completed later.", "verified"),
    "kb_can_edit_later": ("(defers) Points to Help for edit rights. Makes no claim.", "deferred"),
    "kb_why_caste_income": ("Caste and income are collected to improve match "
                            "relevance, and may be skipped.", "verified"),
    "kb_delete_profile": ("A user can delete their profile themselves from the app "
                          "settings.", "verified"),
    "kb_after_profile":  ("Matches personalised to the profile appear as soon as it "
                          "is created.", "verified"),
    "kb_is_safe":        ("The user's details are used only for finding matches.", "deferred"),
    "kb_family_use":     ("A user may create a profile on behalf of a family member.", "verified"),
    "kb_what_is_lokal":  ("Lokal is a local-language city app; this is its matrimony "
                          "section.", "verified"),
    "kb_do_later":       ("A paused session can be resumed shortly afterwards; after "
                          "a longer gap it must be restarted. Describes this app's "
                          "own 30-minute session TTL — your directed rewrite.",
                          "verified"),
    "kb_talk_to_human":  ("Users can reach the team by writing from the app's Help "
                          "section.", "verified"),
    "kb_how_long":       ("Profile creation takes about two to three minutes. Measured wall clock: 1.8 min fast user, 2.0 typical, 2.5-3.3 slow/with friction.", "verified"),
    "kb_kundli":         ("Lokal does not perform kundli/horoscope matching; the "
                          "profile stores date of birth and families discuss it "
                          "themselves.", "verified"),
}

SAFE_STATUSES = {"deferred", "verified"}


def unverified_keys() -> list[str]:
    """Entries that may not have audio generated until a human signs them off."""
    return [k for k, (_, status) in FACTUAL_CLAIMS.items()
            if status not in SAFE_STATUSES]


def text(lang: str, key: str) -> str | None:
    entry = KB.get(key)
    if not entry:
        return None
    return entry.get(lang) or entry.get("en")


def exists(key: str) -> bool:
    return key in KB


def match(transcript: str, lang: str) -> str | None:
    """Free keyword pre-filter. Runs before any LLM key selection."""
    t = (transcript or "").lower()
    best, best_len = None, 0
    for key, entry in KB.items():
        for kw in entry["kw"].get(lang, []) + entry["kw"].get("en", []):
            if kw.lower() in t and len(kw) > best_len:
                best, best_len = key, len(kw)
    return best


def log_gap(question: str, lang: str, session_id: str):
    """An unanswered side question is a curation task, not a silent failure."""
    try:
        GAP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with GAP_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "question": (question or "").strip()[:300],
                "language": lang,
                "session_id": session_id,
                "ts": round(time.time(), 1),
            }, ensure_ascii=False) + "\n")
    except Exception:
        pass    # telemetry must never break a conversation


def gaps(limit: int = 10) -> dict:
    """Top unanswered questions, for /api/stats."""
    if not GAP_LOG.exists():
        return {"total": 0, "top_unanswered": []}
    rows, counts = 0, {}
    try:
        for line in GAP_LOG.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows += 1
            try:
                q = json.loads(line).get("question", "").strip().lower()
            except json.JSONDecodeError:
                continue
            if q:
                counts[q] = counts.get(q, 0) + 1
    except Exception:
        return {"total": 0, "top_unanswered": []}
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:limit]
    return {"total": rows, "top_unanswered": [{"question": q, "count": n} for q, n in top]}
