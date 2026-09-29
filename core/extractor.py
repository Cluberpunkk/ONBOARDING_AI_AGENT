"""
Multi-slot extraction for agentic mode.

ONE Gemini call per uncertain turn returns everything at once: slot updates for
any fields mentioned, a gender-from-name inference with explicit confidence, and
the routed intent. Never a 3-call pipeline — that is what keeps a chatty session
at ~9 calls (~Rs 0.22) instead of ~27.

THE FAST PATH IS SACRED: a clean expected answer to the current slot is handled
by the existing curated-keyword parser with ZERO LLM involvement, exactly as in
classic mode (~13 ms). The extractor only runs when the fast path is uncertain
or the utterance is long enough to plausibly carry more than one fact.

Everything the model returns is validated against the slot/enum registry before
it can touch state — an invented key or an out-of-vocabulary enum is dropped,
not trusted.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from config import settings
from core.kb import KB_KEYS

TIERS = {"T1", "T2", "KB", "EXPAND"}

# ---------------------------------------------------------------- skip layer
# EXTENDS core.parser.SKIP_WORDS, never replaces it. Classic imports _is_skip and
# is unaffected — this module is only reachable from agentic, and _is_skip_ext
# below always consults the classic list first.
#
# Why: "छोड़ दीजिए" ("leave it") is one of the most natural ways to decline a
# sensitive question, and it was not recognised — so the user declined, was asked
# again, declined again. That re-ask loop is precisely the frustration we have
# been removing everywhere else.
#
# These are whole PHRASES, not the bare stem छोड़. "नौकरी छोड़ दी" ("I left my
# job") is an income-relevant statement, not a refusal, and matching the stem
# alone would silently skip the field.
AGENTIC_SKIP_PHRASES = (
    "छोड़दीजिए", "छोड़दीजिये", "छोड़दो", "छोड़दें", "छोड़िए", "छोड़िये", "छोड़ो",
    "रहनेदो", "रहनेदीजिए", "रहनेदें", "जानेदो", "जानेदीजिए",
    "मतपूछो", "मतपूछिए", "मतपूछें", "नहींबताना", "नहींबताऊंगा", "नहींबताऊंगी",
    "अगलासवाल", "आगेबढ़ो", "आगेबढ़िए", "छोड़देते", "पासकरो",
    "leaveit", "skipit", "passthis", "rathernotsay", "prefernottosay",
)


def _is_skip_ext(text: str) -> bool:
    """Classic skip words PLUS the agentic-only phrases above."""
    if _is_skip(text):
        return True
    flat = re.sub(r"[\s\.,!?।\-]+", "", (text or "").strip().lower())
    return any(phrase in flat for phrase in AGENTIC_SKIP_PHRASES)
from core.parser import ParseResult, _dob_plausible, _mock_parse, _is_skip
from core.questions import ENUMS, FREE_TEXT
from core.slots import SLOT_PRIORITY, SlotState

log = logging.getLogger("sakhi.extractor")

# A confident keyword hit on the current slot short-circuits the LLM only when the
# utterance is short enough that it is unlikely to carry extra facts. "अपने बेटे
# के लिए" (4 words) -> fast path. "मैं राहुल हूं, पुणे से, अट्ठाइस साल का" (8) -> LLM.
FAST_PATH_MAX_WORDS = 6

INTENTS = {
    "answer_current", "answer_other_slots", "correction", "side_question",
    "chitchat", "meta", "backchannel", "unclear", "abusive_or_nonsense",
}

_SLOT_SPEC = {
    "for_whom": "one of: self, son, daughter, friend",
    "full_name": "the person's full name, transliterated to English, title case",
    "gender": "one of: male, female",
    "dob": "ISO YYYY-MM-DD (convert spoken numerals in any Indian language; if only an age in years is given, compute the birth year and use YYYY-01-01 with confidence<=0.6)",
    "district": "district/city name, transliterated to English, title case",
    "religion": "one of: Hindu, Muslim, Christian, Sikh, Jain, Buddhist, Other",
    "caste": "caste/community name, transliterated to English, title case",
    "marital": "one of: never_married, divorced, widowed, awaiting_divorce",
    "qualification": "one of: below_10th, 10th, 12th, diploma, bachelors, masters, phd",
    "job": "one of: job, business, farming, student, not_working, other",
    "income": "one ANNUAL band: under_1.5L, 1.5L-3L, 3L-5L, 5L-8L, 8L-12L, 12L-20L, above_20L (multiply a monthly figure by 12 first)",
}


@dataclass
class SlotUpdate:
    key: str
    value: str
    display: str
    confidence: float = 1.0


@dataclass
class Extraction:
    intent: str = "answer_current"
    updates: list[SlotUpdate] = field(default_factory=list)
    gender_guess: tuple[str, float] | None = None    # (value, confidence)
    age_years: int | None = None      # spoken age; NEVER becomes a dob
    kb_key: str | None = None         # KB selection, validated against the registry
    speech_plan: list | None = None   # model-chosen response keys (bounded by the menu)
    is_skip: bool = False
    used_llm: bool = False
    raw_text: str = ""


# A real birth date needs a real date in the utterance. "अट्ठाइस साल का" is an
# AGE — turning it into 1998-01-01 would fabricate a kundli-grade fact and feed
# the 18+ gate a number nobody said. Age is captured separately; dob is asked.
_MONTH_WORDS = None


def _has_date_signal(transcript: str) -> bool:
    global _MONTH_WORDS
    if _MONTH_WORDS is None:
        from core.parser import _MONTHS
        _MONTH_WORDS = [v.lower() for variants in _MONTHS.values() for v in variants]
        _MONTH_WORDS += list(_MONTHS.keys())
    from core.parser import _normalize_date_text
    t = _normalize_date_text(transcript or "").lower()
    if any(m in t for m in _MONTH_WORDS):
        return True
    import re as _re
    return len(_re.findall(r"\d{1,4}", t)) >= 2      # e.g. "15 8 1995", "15/08/95"


def _word_count(t: str) -> int:
    return len([w for w in (t or "").split() if w.strip()])


def fast_path(transcript: str, lang: str, current_slot: str | None) -> Extraction | None:
    """Classic-speed lane. Returns None when the LLM is needed."""
    if not current_slot:
        return None
    if _word_count(transcript) > FAST_PATH_MAX_WORDS:
        return None
    if current_slot in FREE_TEXT and current_slot != "district":
        # names/castes need real understanding; the mock's regex cleanup is too naive
        return None
    quick: ParseResult = _mock_parse(current_slot, transcript, lang)
    if not quick.confident:
        return None
    return Extraction(
        intent="answer_current",
        updates=[SlotUpdate(current_slot, quick.value, quick.display, 1.0)],
        used_llm=False,
        raw_text=transcript,
    )


def _validate(key: str, value: str, display: str, confidence: float,
              transcript: str = "") -> SlotUpdate | None:
    """Structural gate: the model may only write real slots with legal values."""
    if key not in SLOT_PRIORITY or not str(value).strip():
        return None
    value = str(value).strip()
    if key in ENUMS and value not in ENUMS[key]:
        return None
    if key == "dob":
        if not _dob_plausible(value):
            return None
        # Guard against an age silently becoming a birthdate.
        if not _has_date_signal(transcript):
            return None
    try:
        confidence = float(confidence)
    except (TypeError, ValueError):
        confidence = 0.0
    if confidence < 0.5:
        return None
    return SlotUpdate(key, value, str(display or value).strip() or value, confidence)


def _prompt(transcript: str, lang: str, state: SlotState, current_slot: str | None,
            menu: list | None = None, history: list | None = None,
            for_whom: str | None = None) -> str:
    empty = [k for k in SLOT_PRIORITY if state[k].status == "empty"]
    known = {k: state[k].display for k in SLOT_PRIORITY if state[k].known}
    # Full prose for the slot being asked; bare names for the rest. Listing all
    # eleven descriptions cost ~500 tokens on every turn to restate rules the
    # domain section already covers.
    focus = [k for k in empty if k == current_slot]
    spec = "\n".join(f"- {k}: {_SLOT_SPEC[k]}" for k in focus)
    others = [k for k in empty if k not in focus]
    if others:
        spec += ("\n- also extractable if mentioned: " + ", ".join(others))
    from agent.system_prompt import compile_for
    from core.selector import render_menu
    menu_block = ""
    if menu:
        turns = "\n".join(f"  {h}" for h in (history or [])[-3:]) or "  (none)"
        menu_block = (
            f"\nRecent turns:\n{turns}\n"
            f"for_whom: {for_whom or 'not yet known'}\n"
            f"\nChoose Sakhi's next response from THESE keys only "
            f"(the text shown is an English gloss; she speaks the {lang} version):\n"
            f"{render_menu(menu)}\n"
            f'Add to your JSON: "speech_plan": ["key1","key2"] — ordered, 1-3 keys.\n')
    task = (
        f"Language code '{lang}'. Question just asked: {current_slot or 'none'}\n"
        f"Already known (do NOT re-extract unless the user is correcting them): "
        f"{json.dumps(known, ensure_ascii=False)}\n"
        f"Fields still needed:\n{spec}\n"
        f'User said: "{transcript}"\n\n'
        "Return JSON only:\n"
        '{"intent": one of ["answer_current","answer_other_slots","correction",'
        '"side_question","chitchat","meta","backchannel","unclear","abusive_or_nonsense"],\n'
        ' "slots": [{"key":str,"value":str,"display":str,"confidence":0-1}],\n'
        ' "gender_from_name": {"value":"male"|"female"|"","confidence":0-1},\n'
        ' "age_years": int|null,\n'
        f' "kb_key": one of {list(KB_KEYS)}|null}}\n\n'
        f"{menu_block}"
        "Extract EVERY field the turn mentions, not just the asked one. "
        "'display' is a short human-readable English form. Use confidence<0.5 when "
        "unsure — low-confidence items are discarded. kb_key only when intent is "
        "side_question and a listed key genuinely answers it; otherwise null."
    )
    return compile_for(task, slot=current_slot, selecting=bool(menu))


_client = None


def llm_extract(transcript: str, lang: str, state: SlotState,
                current_slot: str | None, menu: list | None = None,
                history: list | None = None, for_whom: str | None = None) -> Extraction:
    global _client
    from google import genai
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)

    resp = _client.models.generate_content(
        model=settings.PARSER_MODEL,
        contents=_prompt(transcript, lang, state, current_slot, menu, history, for_whom),
        config={"response_mime_type": "application/json", "temperature": 0,
                "max_output_tokens": 400},
    )
    data = json.loads(resp.text)
    if isinstance(data, list):
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return Extraction(intent="unclear", used_llm=True, raw_text=transcript)

    intent = str(data.get("intent", "answer_current"))
    if intent not in INTENTS:
        intent = "answer_current"

    updates = []
    for item in (data.get("slots") or []):
        if not isinstance(item, dict):
            continue
        u = _validate(item.get("key", ""), item.get("value", ""),
                      item.get("display", ""), item.get("confidence", 0), transcript)
        if u:
            updates.append(u)

    guess = None
    g = data.get("gender_from_name") or {}
    if isinstance(g, dict) and str(g.get("value", "")).strip():
        try:
            guess = (str(g["value"]).strip(), float(g.get("confidence", 0)))
        except (TypeError, ValueError):
            guess = None

    age = data.get("age_years")
    try:
        age = int(age) if age is not None else None
        if age is not None and not (10 <= age <= 100):
            age = None
    except (TypeError, ValueError):
        age = None

    kb_key = data.get("kb_key")
    kb_key = kb_key if isinstance(kb_key, str) and kb_key in KB_KEYS else None

    plan = None
    raw_plan = data.get("speech_plan")
    if isinstance(raw_plan, list) and menu:
        # Be forgiving about FORM, strict about CONTENT. The model echoes back
        # whatever shape the menu showed it — bare key, "key|TIER" (the render
        # format), "key (TIER)", occasionally reversed. Being strict about form
        # silently discarded CORRECT choices twice, and because selection then
        # falls back to deterministic routing, the feature looked alive while
        # doing nothing. So: tokenise, and let the menu decide which token is
        # the key. The menu still bounds what can be selected.
        plan = []
        for item in raw_plan:
            key, tier = None, None
            if isinstance(item, dict):
                key, tier = item.get("key"), item.get("tier")
            elif isinstance(item, str):
                tokens = [t for t in re.split(r"[^\w.]+", item) if t]
                tier = next((t.upper() for t in tokens if t.upper() in TIERS), None)
                key = next((t for t in tokens if t.upper() not in TIERS), None)
            if not key:
                continue
            options = [x for x in menu if x["key"] == key]
            if not options:
                continue
            chosen = next((x for x in options if x["tier"] == tier), options[0])
            plan.append({"tier": chosen["tier"], "key": chosen["key"]})
        plan = plan or None

    return Extraction(intent=intent, updates=updates, gender_guess=guess,
                      age_years=age, kb_key=kb_key, speech_plan=plan,
                      used_llm=True, raw_text=transcript)


def extract(transcript: str, lang: str, state: SlotState,
            current_slot: str | None, menu: list | None = None,
            history: list | None = None, for_whom: str | None = None) -> Extraction:
    """Fast path first, LLM only when it earns its keep."""
    if current_slot in ("caste", "income") and _is_skip_ext(transcript):
        return Extraction(intent="answer_current", is_skip=True, raw_text=transcript)

    quick = fast_path(transcript, lang, current_slot)
    if quick:
        return quick

    if settings.parser_enabled:
        try:
            return llm_extract(transcript, lang, state, current_slot,
                               menu=menu, history=history, for_whom=for_whom)
        except Exception as e:
            log.warning("LLM extraction failed (%s) — falling back to keyword parse", e)

    # Zero-key / LLM-down: degrade to a single-slot keyword parse, never break
    if current_slot:
        p = _mock_parse(current_slot, transcript, lang)
        if p.confident:
            return Extraction(updates=[SlotUpdate(current_slot, p.value, p.display, 1.0)],
                              raw_text=transcript)
    return Extraction(intent="unclear", raw_text=transcript)
