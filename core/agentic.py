"""
Agentic turn handling — the slot-filling conversation.

Sits BESIDE classic mode, never inside it: core/session.py's classic functions
are untouched and remain the default. main.py branches on settings.agentic.

A turn produces a speech PLAN — an ordered list of {tier, key} references into
the cached T1 question set and the T2 fragment library. resolve_plan() turns
that into the same payload shape speak() already knows (text + audio_urls), so
the frontend contract is unchanged.

Cost invariants:
- fast path (clean expected answer) -> zero LLM, ~13 ms
- every spoken part is a cache lookup; nothing is synthesized at runtime
"""
from __future__ import annotations

import logging
import re
import random
import time

from config import settings
from core import avatar, dialogue, fragments, kb, selector, tts
from core.extractor import Extraction, extract
from core.questions import get_string
from core.slots import (CONFIRMED, SKIPPABLE, SLOT_PRIORITY, SlotState, age_of)

log = logging.getLogger("sakhi.agentic")

T1, T2, KB_TIER = "T1", "T2", "KB"


# --------------------------------------------------------------- speech plans
def resolve_plan(lang: str, plan: list[dict], key: str) -> dict:
    """Plan -> prompt payload. Every part is validated against the curated key
    registry first; anything else is DROPPED (the structural guarantee that only
    hand-written strings can ever be spoken). Audio attaches only when every part
    is already cached — nothing is generated at request time."""
    clean, texts = [], []
    for part in dialogue.validate(lang, plan):
        t = dialogue.part_text(lang, part)
        if not t:
            continue
        clean.append(part)
        texts.append(t)
    if not texts:
        texts = [get_string(lang, key)]
        clean = [{"tier": T1, "key": key}]

    audios = [tts.lookup(t, lang, key=c['key'], tier=c['tier'])
              for t, c in zip(texts, clean)]
    payload = {
        "key": key,
        "text": " ".join(texts),
        "audio_url": None,
        "speech_plan": clean,
    }
    if all(audios):
        payload["audio_urls"] = [f"/audio/{a}" for a in audios]
        if len(audios) == 1:
            payload["audio_url"] = f"/audio/{audios[0]}"
    if settings.avatar_enabled:
        clips = [avatar.get_clip(t, lang) for t in texts]
        payload["video_urls"] = [f"/avatar/{c}" for c in clips] if all(clips) else None
    return payload


# ------------------------------------------------------------------ the turn
def _ack_part(sess) -> dict:
    """Session arc: warmer/longer acks early, clipped ones once rapport exists."""
    key = fragments.pick_ack(sess.used_fragments, sess.turn)
    sess.used_fragments.append(key)
    del sess.used_fragments[:-4]        # remember the last few only
    return {"tier": T2, "key": key}


def _reaction_part(sess, accepted: list) -> dict | None:
    """React to WHAT was said, not just that something was said. Echoes the
    value; never evaluates. Only fires on neutral fields — the trigger table
    physically cannot contain caste/religion/income/marital/gender."""
    from core.naturalness import REACTION_TRIGGERS
    for a in accepted:
        key = REACTION_TRIGGERS.get((a.get("key"), a.get("value")))
        if key and fragments.exists(sess.language, key) and key not in sess.used_fragments:
            sess.used_fragments.append(key)
            del sess.used_fragments[:-4]
            return {"tier": T2, "key": key}
    return None


def _earned_ack(sess, accepted: list, *, forced: bool = False) -> list[dict]:
    """Acknowledging EVERY turn is the most robotic pattern we have.
    An ack is EARNED by a multi-slot capture, a correction, a skip, a resolved
    clarification or an off-script detour. A plain single-slot answer gets one
    only occasionally (ACK_RATE), and a value-reaction beats a generic ack."""
    react = _reaction_part(sess, accepted)
    if react:
        return [react]
    if forced or len(accepted) >= 2:
        return [_ack_part(sess)]
    if random.random() < settings.ACK_RATE:
        return [_ack_part(sess)]
    return []          # straight to the next question — this is what humans do


def _chain_part(sess, prev_key: str | None, next_key: str | None) -> list[dict]:
    """Connect naturally-adjacent questions instead of hard-stopping between
    them. Never leads into a sensitive question."""
    from core.naturalness import CHAINS, CHAIN_FORBIDDEN_TARGETS
    if not prev_key or not next_key or next_key in CHAIN_FORBIDDEN_TARGETS:
        return []
    key = CHAINS.get((prev_key, next_key))
    if not key or not fragments.exists(sess.language, key):
        return []
    if key in sess.used_fragments[-2:]:
        return []
    sess.used_fragments.append(key)
    del sess.used_fragments[:-4]
    return [{"tier": T2, "key": key}]


def _subject(state: SlotState) -> str | None:
    """Who the profile is for — drives subject-aware question variants."""
    return state["for_whom"].value if state["for_whom"].known else None


def _q_part(state: SlotState, key: str) -> dict:
    return {"tier": T1, "key": key, "for_whom": _subject(state)}


def _ask_plan(sess, state: SlotState, lead: list[dict]) -> dict:
    """lead (acks/confirms) + the next question, or the photo hand-off."""
    nxt = state.next_slot()
    if nxt is None:
        sess.stage = "photo"
        return resolve_plan(sess.language, lead + [{"tier": T1, "key": "photo"}], "photo")

    if state[nxt].status == "needs_confirmation":
        # inference confirmation: one beat, patterned, never names the value
        fkey = ("confirm_gender_male" if state[nxt].value == "male"
                else "confirm_gender_female") if nxt == "gender" else "confirm_generic"
        state.mark_asked(nxt)
        return resolve_plan(sess.language, lead + [{"tier": T2, "key": fkey}], nxt)

    # milestone: one breath before the last stretch
    if state.remaining() == 2 and not sess.milestone_done:
        sess.milestone_done = True
        lead = lead + [{"tier": T1, "key": "almost_done"}]

    state.mark_asked(nxt)
    sess.q_asked_at[nxt] = time.monotonic()
    return resolve_plan(sess.language, lead + [_q_part(state, nxt)], nxt)


# Refusals/ignorance, normalised (no spaces). A value containing one of these is
# the user telling us they cannot answer — that is a skip or a clarification,
# never a stored fact.
DONT_KNOW_STEMS = (
    "नहींपता", "पतानहीं", "मालूमनहीं", "नहींमालूम", "यादनहीं", "नहींयाद",
    "नहींजानता", "नहींजानती", "पक्कानहीं", "dontknow", "donotknow", "noidea",
)


def _norm_echo(t: str) -> str:
    """Strip punctuation/spacing so 'ज़िला नहीं पता' and 'ज़िला नहीं पता?' compare equal."""
    return re.sub(r"[\s\.,!?।]+", "", (t or "")).strip().lower()


# Words that frame a place without naming one. A value made only of these is a
# description of where someone lives, not a district.
# NOTE: Hindi only. The other eight languages need the same list before this
# guard protects them — until then they fall back to the length rule below.
_GENERIC_PLACE = {
    "गाँव", "गांव", "शहर", "कस्बा", "गाव", "village", "town", "city",
    "इधर", "उधर", "यहाँ", "यहां", "वहाँ", "वहां",
}
# Frame words that surround a place name in ordinary speech.
_PLACE_FRAME = {
    "मैं", "मे", "में", "हम", "तो", "से", "का", "की", "के", "है", "हैं", "हूं",
    "हूँ", "रहते", "रहता", "रहती", "पास", "जिला", "ज़िला", "ही", "ka", "se",
    "मेरा", "मेरी", "मेरे", "हमारा", "हमारी", "हमारे", "अपना", "अपनी", "आया",
    "आयी", "वाला", "वाली", "और", "जी", "थी", "था", "थे", "अभी", "फिलहाल",
}
_MAX_PLACE_TOKENS = 3

# Identity fields that may only ever be STATED, never derived. Gender is absent
# because it has a stronger mechanism already: it is inferred but then always
# routed through explicit confirmation (C3).
NEVER_INFERRED = ("caste", "religion")


def _clean_place(display: str) -> str | None:
    """A district is a NAME, not a sentence.

    The model returns the user's whole utterance as the value — "मैं जयपुर से हूं"
    was stored verbatim as the district, and §5 telling it otherwise did not
    change that. Since the slot is never re-asked, the sentence ships in the
    profile. So the shape is enforced here: strip the frame words and keep what
    is left if it looks like a name. If nothing name-like remains, return None
    and let her ask again — an unanswered question beats a wrong answer.
    """
    tokens = [t for t in re.split(r"\s+", (display or "").strip()) if t]
    if not tokens:
        return None
    content = [t for t in tokens if t.lower() not in _PLACE_FRAME]
    if not content or any(t.lower() in _GENERIC_PLACE for t in content):
        return None
    if len(content) > _MAX_PLACE_TOKENS:
        return None
    return " ".join(content)


def _drop_echoed_updates(updates, transcript: str, lang: str,
                         current: str | None = None):
    """A question is not an answer.

    Free-text slots (district, job, qualification) have no closed vocabulary, so
    the model will happily hand back the user's own words as the value. Asking
    "ज़िला मतलब?" ("what do you mean by district?") stored district="ज़िला मतलब",
    and because a known slot is never re-asked, that garbage shipped in the
    profile and the real question was never put again.

    Prompting alone cannot fix this — the model believes it IS extracting. So
    the rule is enforced here: if the utterance is clarification-shaped, a slot
    value that merely echoes it back is dropped. A genuine answer ("जयपुर") is
    untouched because it is not clarification-shaped in the first place.
    """
    if not updates:
        return updates

    # "I don't know" is never a value, whatever the field. This one is not
    # question-shaped, so the echo rule below cannot see it: "ज़िला नहीं पता"
    # was stored verbatim as the district and never asked again.
    kept = []
    for u in updates:
        val = _norm_echo(str(u.display or u.value))
        if any(stem in val for stem in DONT_KNOW_STEMS):
            log.info("dropped don't-know update %s=%r", u.key, u.display)
            continue
        kept.append(u)
    updates = kept

    # Caste and religion are NEVER inferred — only stated.
    #
    # Measured: in 1 of 6 identical sessions the model read caste=`Sharma` off
    # the surname "राहुल शर्मा". The user never said it, caste is never re-asked,
    # and the skip path they were entitled to was never offered. This is the
    # same failure the gender guardrail exists to prevent (C3), and prompting
    # does not close it — §5 already says not to infer religion from a name.
    #
    # So these two may only be filled by a turn that is answering their own
    # question. Volunteering caste while answering something else costs one
    # re-ask; inferring it from a name assigns an identity nobody gave.
    final = []
    for u in updates:
        if u.key in NEVER_INFERRED and current != u.key:
            log.info("dropped %s=%r — inferred while asking %r, not stated",
                     u.key, u.display, current)
            continue
        final.append(u)
    updates = final

    # Value-shape sanity for the one free-text slot with no closed vocabulary.
    # This runs for EVERY utterance, not just question-shaped ones: the common
    # corruption is an ordinary answer ("मैं जयपुर से हूं") stored as a sentence.
    final = []
    for u in updates:
        if u.key == "district":
            cleaned = _clean_place(str(u.display or u.value))
            if cleaned is None:
                log.info("dropped district=%r — not a place name", u.display)
                continue
            if cleaned != (u.display or ""):
                log.info("district %r -> %r", u.display, cleaned)
                u.display = cleaned
                u.value = cleaned
        final.append(u)
    updates = final

    if not (dialogue.is_clarification(transcript, lang)
            or dialogue.looks_like_question(transcript, lang)):
        return updates

    # Asking ABOUT the question is not answering it. Dropping only verbatim
    # echoes was not enough: "डिग्री का नाम बताऊं" ("shall I tell you the degree
    # name?") came back as qualification=`bachelors` — an invented answer that
    # echoes nothing. So a clarification-shaped turn may not fill the slot it is
    # asking about at all. Other slots survive, since people do volunteer one
    # fact while querying another.
    kept = []
    for u in updates:
        if current and u.key == current:
            log.info("dropped %s=%r — the user was asking about the question, "
                     "not answering it", u.key, u.display)
            continue
        kept.append(u)
    updates = kept

    said = _norm_echo(transcript)
    kept = []
    for u in updates:
        val = _norm_echo(str(u.display or u.value))
        if val and (val in said or said in val):
            log.info("dropped echoed update %s=%r — the utterance was a question",
                     u.key, u.display)
            continue
        kept.append(u)
    return kept


def handle_turn(sess, transcript: str) -> dict:
    """One user utterance -> updated slots + the next thing Sakhi says."""
    state: SlotState = sess.slot_state
    current = state.next_slot()
    if current and state[current].status == "needs_confirmation":
        return _handle_confirmation(sess, state, current, transcript)

    # RESPONSE SELECTION: on any turn the fast path can't handle, the model
    # chooses what she says next from a state-filtered menu of authored keys.
    # It rides on the SAME extraction call — a second call would double the
    # per-turn cost. The menu bounds it, enforce() polices it, and if any of it
    # fails we fall back to the deterministic routing below.
    menu = selector.build_menu(sess, state, current)
    ex: Extraction = extract(transcript, sess.language, state, current,
                             menu=menu, history=sess.history,
                             for_whom=_subject(state))
    sess.llm_calls += int(ex.used_llm)
    ex.updates = _drop_echoed_updates(ex.updates, transcript, sess.language, current)
    sess.history.append(f"user: {transcript[:80]}")
    del sess.history[:-3]

    # ---- model-selected response for anything that isn't a clean answer -----
    # This is the path that used to be a hardcoded intent->key table and kept
    # failing on utterances nobody predicted.
    if ex.speech_plan and ex.intent not in ("backchannel",) and not ex.updates:
        n = sess.clarification_count.get(current, 0)
        # This turn IS a clarification if the plan re-presents the question, so
        # the ladder must be evaluated at n+1, not n.
        asks_again = any(p.get("key") == current for p in ex.speech_plan
                         if isinstance(p, dict)) or any(
            (isinstance(p, str) and p == current) for p in ex.speech_plan)
        plan, notes = selector.enforce(sess, state, ex.speech_plan, current=current,
                                       clarification_n=n + (1 if asks_again else 0),
                                       menu=menu)
        if plan:
            for part in plan:
                if part["tier"] == T2:
                    sess.used_fragments.append(part["key"])
            del sess.used_fragments[:-4]
            if any(p["tier"] == T1 and p["key"] == current for p in plan) or \
               any(p["tier"] == "EXPAND" for p in plan):
                sess.clarification_count[current] = n + 1
            sess.last_plan = [dict(p) for p in plan]
            plan = [dict(p, for_whom=_subject(state)) if p["tier"] == T1 else p
                    for p in plan]
            out = resolve_plan(sess.language, plan, current or "clarify")
            sess.history.append(f"sakhi: {out['text'][:80]}")
            del sess.history[:-3]
            sess.selected_turns += 1
            if notes:
                log.info("selector adjustments: %s", notes)
            return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm,
                             selected=True,
                             text_fallback=sess.clarification_count.get(current, 0) >= 3)

    # ---- deterministic fallback: today's routing, unchanged ------------------
    # A question ABOUT the question. The model normally handles this now; this
    # whitelist is the safety net for when selection fails, times out or comes
    # back empty. It is engagement, not failure — the retry counter is untouched.
    if current and dialogue.is_clarification(transcript, sess.language):
        sess.clarification_count[current] = sess.clarification_count.get(current, 0) + 1
        n = sess.clarification_count[current]
        plan = dialogue.clarify_ladder(sess.language, current, n, _subject(state))
        out = resolve_plan(sess.language, plan, current)
        return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm,
                         clarification=n, text_fallback=n >= 3)

    if ex.intent == "backchannel":
        # "हाँ... अच्छा" while she's talking is not an answer. Say nothing new.
        return _envelope(sess, state, resolve_plan(sess.language, [], current or "clarify"),
                         accepted=[], used_llm=ex.used_llm, backchannel=True)

    if ex.intent == "side_question":
        plan, matched = dialogue.side_question_plan(
            transcript, sess.language, sess.id, ex.kb_key)
        sess.kb_hits += int(matched)
        sess.kb_misses += int(not matched)
        out = _ask_plan(sess, state, plan)      # answer -> steer back -> re-ask
        return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm,
                         side_question=True, kb_matched=matched)

    if ex.intent == "meta":
        out = _ask_plan(sess, state, dialogue.meta_plan(transcript, sess.language))
        return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm)

    if ex.intent == "abusive_or_nonsense":
        sess.nonsense_strikes += 1
        out = _ask_plan(sess, state, dialogue.nonsense_plan(sess.nonsense_strikes))
        return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm,
                         text_fallback=sess.nonsense_strikes >= 2)

    if ex.intent == "chitchat" and not ex.updates:
        out = _ask_plan(sess, state, dialogue.chitchat_plan())
        return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm)

    # sensitive skip
    if ex.is_skip and current in SKIPPABLE:
        _record(sess, current)
        state.skip(current)
        sess.turn += 1
        out = _ask_plan(sess, state, [{"tier": T1, "key": "skip_ack"}])
        return _envelope(sess, state, out, accepted=[{"key": current, "display": "—", "skipped": True}],
                         used_llm=ex.used_llm)

    # apply every validated update; the 18+ gate can veto dob
    accepted, age_gate, gender_pending = [], False, False
    for u in ex.updates:
        if u.key == "dob" and age_of(u.value) < 18:
            age_gate = True
            continue
        if state[u.key].known and u.key != current and ex.intent != "correction":
            continue        # already answered and not an explicit correction

        # HARD GUARDRAIL: gender may never be filled from a model extraction.
        # The model cannot reliably distinguish "the user said so" from "I read
        # it off the name", so anything it produces goes to confirmation. Only
        # the explicit for_whom derivation or a direct fast-path answer fills it.
        if u.key == "gender" and ex.used_llm and current != "gender":
            if state.offer_gender_inference(u.value, max(u.confidence, 0.9),
                                            state["full_name"].display):
                gender_pending = True
            continue

        was_known = state[u.key].known
        state.fill(u.key, u.value, u.display, confidence=u.confidence,
                   source="spoken" if not was_known else "confirmed")
        _record(sess, u.key)
        accepted.append({"key": u.key, "value": u.value, "display": u.display,
                         "corrected": bool(was_known)})

    # A spoken AGE is not a birth date: keep it as an approximation, still ask
    # dob properly. Matrimony needs the real date (kundli) and the 18+ gate must
    # be computed from something the user actually said.
    if ex.age_years is not None and not state["dob"].known:
        state.derived["age_approx"] = ex.age_years
        if ex.age_years < 18:
            age_gate = True         # gently gate early rather than let it ride

    if age_gate:
        sess.retries += 1
        sess.clarifies["dob"] = sess.clarifies.get("dob", 0) + 1
        out = resolve_plan(sess.language,
                           [{"tier": T1, "key": "age_invalid"}, {"tier": T1, "key": "dob"}], "dob")
        return _envelope(sess, state, out, accepted=accepted, age_gate=True,
                         used_llm=ex.used_llm)

    # Age captured but no date yet -> acknowledge what we got and ask for the date
    if (ex.age_years is not None and not state["dob"].known
            and state.next_slot() == "dob"):
        state.mark_asked("dob")
        sess.q_asked_at["dob"] = time.monotonic()
        lead = [{"tier": T2, "key": "batch_confirm"}] if accepted else [_ack_part(sess)]
        out = resolve_plan(sess.language,
                           lead + [{"tier": T1, "key": "dob"},
                                   {"tier": T2, "key": "need_full_dob"}], "dob")
        return _envelope(sess, state, out, accepted=accepted, used_llm=ex.used_llm)

    # gender inference from a captured name — offered for confirmation, never filled
    inference_offered = False
    if ex.gender_guess and state["full_name"].known:
        g, conf = ex.gender_guess
        inference_offered = state.offer_gender_inference(
            g, conf, state["full_name"].display)

    # An offered inference is progress: ask the one-beat confirm rather than
    # falling through to "I didn't understand".
    if not accepted and (inference_offered or gender_pending):
        sess.retries = 0
        return _envelope(sess, state, _ask_plan(sess, state, []), accepted=[],
                         used_llm=ex.used_llm)

    if not accepted:
        # NEAR-MISS SAFETY NET: nothing parsed, but the turn is question-shaped.
        # That is "I don't understand what you're asking", not a failed answer —
        # route it to the clarification ladder and do NOT touch the retry count.
        if current and dialogue.looks_like_question(transcript, sess.language):
            sess.clarification_count[current] = sess.clarification_count.get(current, 0) + 1
            n = sess.clarification_count[current]
            plan = dialogue.clarify_ladder(sess.language, current, n, _subject(state))
            out = resolve_plan(sess.language, plan, current)
            return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm,
                             clarification=n, text_fallback=n >= 3)

        # genuinely unparseable -> re-ask, with the SUBJECT-AWARE question
        sess.retries += 1
        if current:
            sess.clarifies[current] = sess.clarifies.get(current, 0) + 1
        out = resolve_plan(sess.language,
                           [{"tier": T1, "key": "clarify"},
                            _q_part(state, current) if current else {"tier": T1, "key": "clarify"}],
                           current or "clarify")
        return _envelope(sess, state, out, accepted=[], used_llm=ex.used_llm,
                         text_fallback=sess.retries >= 2)

    sess.retries = 0
    sess.turn += 1
    # confirmation batching: 2+ slots in one breath get ONE confirm, not three
    if len(accepted) >= 2:
        lead = [{"tier": T2, "key": "batch_confirm"}]
    elif any(a.get("corrected") for a in accepted):
        # conversational recovery, not a formal correction notice
        rk = fragments.pick_from(fragments.RECOVERY_KEYS, sess.used_fragments, sess.language)
        sess.used_fragments.append(rk or "")
        lead = [{"tier": T2, "key": rk}] if rk else [{"tier": T2, "key": "correction_ack"}]
    else:
        lead = _earned_ack(sess, accepted)

    prev = accepted[-1]["key"] if accepted else None
    nxt = state.next_slot()
    lead = lead + _chain_part(sess, prev, nxt)
    out = _ask_plan(sess, state, lead)
    return _envelope(sess, state, out, accepted=accepted, used_llm=ex.used_llm)


def _handle_confirmation(sess, state: SlotState, key: str, transcript: str) -> dict:
    """Yes/no on an inferred value. A 'no' clears it and asks the real question."""
    from core.parser import _mock_parse
    t = (transcript or "").lower()
    yes_words = ("हाँ", "हां", "जी", "सही", "yes", "ha", "haan", "correct", "ஆம்",
                 "అవును", "ಹೌದು", "അതെ", "হ্যাঁ", "હા", "बरोबर", "right")
    no_words = ("नहीं", "नही", "no", "nahi", "galat", "ग़लत", "गलत", "इल்லै", "இல்லை",
                "కాదు", "ಇಲ್ಲ", "അല്ല", "না", "ના", "नाही")
    said_no = any(w in t for w in no_words)
    said_yes = (not said_no) and any(w in t for w in yes_words)

    if said_yes:
        state.confirm(key, True)
        _record(sess, key)
        out = _ask_plan(sess, state, [_ack_part(sess)])
        return _envelope(sess, state, out,
                         accepted=[{"key": key, "display": state[key].display}])

    if said_no:
        state.confirm(key, False)
        out = _ask_plan(sess, state, [{"tier": T2, "key": "correction_ack"}])
        return _envelope(sess, state, out, accepted=[])

    # An actual answer instead of yes/no (e.g. "लड़की के लिए") — take it as truth.
    direct = _mock_parse(key, transcript, sess.language)
    if direct.confident:
        state.confirm(key, False)
        state.fill(key, direct.value, direct.display, source="spoken")
        _record(sess, key)
        out = _ask_plan(sess, state, [_ack_part(sess)])
        return _envelope(sess, state, out,
                         accepted=[{"key": key, "display": direct.display}])

    state.confirm(key, False)      # unclear -> drop the guess, ask properly
    out = _ask_plan(sess, state, [])
    return _envelope(sess, state, out, accepted=[])


# ------------------------------------------------------------------ plumbing
def _record(sess, key: str):
    asked = sess.q_asked_at.get(key)
    if asked is not None:
        sess.durations[key] = round(time.monotonic() - asked, 2)
    sess.attempts[key] = sess.attempts.get(key, 0) + 1


def _envelope(sess, state: SlotState, prompt: dict, *, accepted: list,
              used_llm: bool = False, age_gate: bool = False,
              text_fallback: bool = False, side_question: bool = False,
              kb_matched: bool = False, backchannel: bool = False,
              clarification: int = 0, selected: bool = False) -> dict:
    out = {
        "stage": sess.stage,
        "prompt": prompt,
        "progress": progress(state, sess),
        "slots": {k: state[k].status for k in SLOT_PRIORITY},
        "parser": "gemini" if used_llm else "mock",
        "mode": "agentic",
    }
    if side_question:
        out["side_question"] = True
        out["kb_matched"] = kb_matched
    if backchannel:
        out["backchannel"] = True
    if clarification:
        out["clarification"] = clarification
    if selected:
        out["selected"] = True
    # Replying in 13ms reads as a machine. The client delays her VOICE by this
    # much (visual feedback stays instant). Deeper "thought" after heavy turns.
    deep = clarification > 0 or len(accepted) >= 2
    lo, hi = settings.think_time_deep if deep else settings.think_time
    out["think_ms"] = random.randint(lo, hi)
    glo, ghi = settings.turn_gap
    out["turn_gap_ms"] = random.randint(glo, ghi)
    if accepted:
        out["accepted"] = accepted[0] if len(accepted) == 1 else accepted
        out["accepted_all"] = accepted
    if age_gate:
        out["age_gate"] = True
    if text_fallback:
        out["text_fallback"] = True
    if sess.stage == "photo":
        out["prefetch_audio_url"] = None
    return out


def progress(state: SlotState, sess) -> dict:
    total = len(SLOT_PRIORITY) + 1     # + photo
    done = state.answered() + (1 if sess.stage in ("review", "done") else 0)
    return {"done": done, "total": total}
