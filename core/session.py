"""
Conversation state machine.

States: asking (index into QUESTION_ORDER) -> photo -> review -> done

Smart behavior:
- gender auto-filled and skipped when for_whom is son/daughter
- per-question retry counter: 2 unconfident parses -> frontend shows text input
- 18+ age gate on dob (never stores an underage dob; re-validated at confirm)
- caste/income skippable via multilingual skip words -> stored as null, "—"
- composite prompts (clarify+question, skip_ack+next, almost_done+income,
  thanks+review, age_invalid+dob) ship as audio_urls of CACHED per-line mp3s —
  runtime never synthesizes a concatenated string, preserving zero-runtime-TTS
- sessions expire after 30 idle minutes (touch-refreshed); resume supported
- per-question funnel metrics (attempts, clarifies, answer duration)
- everything persisted to data/profiles/<session_id>.json on confirm
"""
from __future__ import annotations
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from config import settings
from core.questions import QUESTION_ORDER, FIELD_LABELS, S, get_string
from core import avatar, tts

SESSION_TTL_SEC = 30 * 60
SKIPPABLE = {"caste", "income"}


@dataclass
class Session:
    id: str
    language: str
    fields: dict = field(default_factory=dict)      # key -> {value, display}
    q_index: int = 0
    retries: int = 0
    attempts: dict = field(default_factory=dict)     # key -> attempt count
    clarifies: dict = field(default_factory=dict)    # key -> clarify count
    durations: dict = field(default_factory=dict)    # key -> seconds to accept
    q_asked_at: dict = field(default_factory=dict)   # key -> monotonic ask time
    photo_file: str | None = None
    stage: str = "asking"                            # asking | photo | review | done
    created_at: float = field(default_factory=time.time)
    touched_at: float = field(default_factory=time.time)
    # --- agentic mode only; classic never reads or writes these ---
    slot_state: Any = None                           # core.slots.SlotState
    used_fragments: list = field(default_factory=list)
    llm_calls: int = 0
    t3_chars: int = 0
    milestone_done: bool = False
    kb_hits: int = 0
    kb_misses: int = 0
    nonsense_strikes: int = 0
    resolved_mode: str = "classic"       # what this session ACTUALLY runs as
    clarification_count: dict = field(default_factory=dict)  # NOT failures
    turn: int = 0                        # drives the session arc (warm -> clipped)
    history: list = field(default_factory=list)   # last 3 turns, for selection
    selected_turns: int = 0              # turns the model chose the response
    last_plan: list = field(default_factory=list)  # consecutive-differ check


_SESSIONS: dict[str, Session] = {}


def age_of(iso: str) -> int:
    y, m, d = map(int, iso.split("-"))
    t = date.today()
    return t.year - y - ((t.month, t.day) < (m, d))


def _prompt_payload(sess: Session, key: str, text_key: str | None = None) -> dict:
    """Build the speak-this payload for a single question/system key."""
    text = get_string(sess.language, text_key or key)
    audio = tts.synthesize(text, sess.language)
    payload = {
        "key": key,
        "text": text,
        "audio_url": f"/audio/{audio}" if audio else None,
    }
    if settings.avatar_enabled:
        clip = avatar.get_clip(text, sess.language)
        payload["video_url"] = f"/avatar/{clip}" if clip else None
    return payload


def _composite_prompt(sess: Session, key: str, part_keys: list[str]) -> dict:
    """Two cached lines played back-to-back. Never synthesizes concatenations —
    each part is a warmed base line, so runtime TTS stays at zero."""
    texts = [get_string(sess.language, k) for k in part_keys]
    audios = [tts.synthesize(t, sess.language) for t in texts]
    payload = {"key": key, "text": " ".join(texts), "audio_url": None}
    if all(audios):
        payload["audio_urls"] = [f"/audio/{a}" for a in audios]
    if settings.avatar_enabled:
        clips = [avatar.get_clip(t, sess.language) for t in texts]
        if all(clips):
            payload["video_urls"] = [f"/avatar/{c}" for c in clips]
        else:
            payload["video_url"] = None
    return payload


def _mark_asked(sess: Session, key: str):
    sess.q_asked_at[key] = time.monotonic()


def start(language: str) -> tuple[Session, dict, dict]:
    sess = Session(id=uuid.uuid4().hex[:12], language=language)
    _SESSIONS[sess.id] = sess
    # Agentic only engages on a language it can actually speak in full.
    from core.coverage import mode_for
    sess.resolved_mode = mode_for(language)
    if sess.resolved_mode == "agentic":
        from core.slots import SLOT_PRIORITY, SlotState
        sess.slot_state = SlotState()
        first_key = SLOT_PRIORITY[0]
        intro = _prompt_payload(sess, "intro")
        first_q = _prompt_payload(sess, first_key)
        sess.slot_state.mark_asked(first_key)
        _mark_asked(sess, first_key)
        return sess, intro, first_q
    intro = _prompt_payload(sess, "intro")
    first_q = _prompt_payload(sess, QUESTION_ORDER[0])
    _mark_asked(sess, QUESTION_ORDER[0])
    return sess, intro, first_q


def get(session_id: str) -> Session | None:
    sess = _SESSIONS.get(session_id)
    if not sess:
        return None
    if time.time() - sess.touched_at > SESSION_TTL_SEC:
        _SESSIONS.pop(session_id, None)
        return None
    sess.touched_at = time.time()
    return sess


def current_question(sess: Session) -> str | None:
    if sess.stage == "asking" and sess.q_index < len(QUESTION_ORDER):
        return QUESTION_ORDER[sess.q_index]
    if sess.stage == "photo":
        return "photo"
    return None


def _advance_index(sess: Session):
    """Move to the next question, auto-skipping gender when inferable."""
    sess.q_index += 1
    sess.retries = 0
    while sess.q_index < len(QUESTION_ORDER):
        key = QUESTION_ORDER[sess.q_index]
        if key == "gender":
            fw = sess.fields.get("for_whom", {}).get("value")
            if fw == "son":
                sess.fields["gender"] = {"value": "male", "display": "Male"}
                sess.q_index += 1
                continue
            if fw == "daughter":
                sess.fields["gender"] = {"value": "female", "display": "Female"}
                sess.q_index += 1
                continue
        break
    if sess.q_index >= len(QUESTION_ORDER):
        sess.stage = "photo"


def _record_answered(sess: Session, key: str):
    asked = sess.q_asked_at.get(key)
    if asked is not None:
        sess.durations[key] = round(time.monotonic() - asked, 2)
    sess.attempts[key] = sess.attempts.get(key, 0) + 1


def _next_prompt(sess: Session, prefix_key: str | None = None) -> dict:
    """Prompt for the current position, optionally prefixed with a cached
    system line (skip_ack). Handles the almost_done milestone before income."""
    if sess.stage == "photo":
        parts = [prefix_key, "photo"] if prefix_key else None
        prompt = _composite_prompt(sess, "photo", parts) if parts else _prompt_payload(sess, "photo")
        return {"stage": "photo", "prompt": prompt,
                "prefetch_audio_url": prefetch_url(sess), **_progress(sess)}
    next_key = QUESTION_ORDER[sess.q_index]
    parts = [prefix_key] if prefix_key else []
    if next_key == "income":
        parts.append("almost_done")   # milestone: one breath before the last stretch
    parts.append(next_key)
    prompt = _composite_prompt(sess, next_key, parts) if len(parts) > 1 else _prompt_payload(sess, next_key)
    _mark_asked(sess, next_key)
    return {"stage": "asking", "prompt": prompt,
            "prefetch_audio_url": prefetch_url(sess), **_progress(sess)}


def accept_answer(sess: Session, key: str, value: str, display: str) -> dict:
    """Store a confident answer and return the next prompt payload."""
    _record_answered(sess, key)
    sess.fields[key] = {"value": value, "display": display}
    _advance_index(sess)
    return _next_prompt(sess)


def skip_field(sess: Session, key: str) -> dict:
    """Sensitive-question skip (caste/income): store null, acknowledge softly."""
    _record_answered(sess, key)
    sess.fields[key] = {"value": None, "display": "—"}
    _advance_index(sess)
    out = _next_prompt(sess, prefix_key="skip_ack")
    out["accepted"] = {"key": key, "display": "—", "skipped": True}
    return out


def clarify(sess: Session) -> dict:
    """Unconfident parse: bump retry, re-ask (clarify + question, both cached)."""
    key = current_question(sess) or "clarify"
    sess.retries += 1
    sess.attempts[key] = sess.attempts.get(key, 0) + 1
    sess.clarifies[key] = sess.clarifies.get(key, 0) + 1
    prompt = _composite_prompt(sess, key, ["clarify", key])
    return {
        "stage": sess.stage,
        "prompt": prompt,
        "retries": sess.retries,
        "text_fallback": sess.retries >= 2,
        **_progress(sess),
    }


def age_reask(sess: Session) -> dict:
    """18+ gate: dob parsed to an underage date. Do NOT store; warm re-ask."""
    sess.retries += 1
    sess.attempts["dob"] = sess.attempts.get("dob", 0) + 1
    sess.clarifies["dob"] = sess.clarifies.get("dob", 0) + 1
    prompt = _composite_prompt(sess, "dob", ["age_invalid", "dob"])
    return {
        "stage": sess.stage,
        "prompt": prompt,
        "retries": sess.retries,
        "age_gate": True,
        "text_fallback": sess.retries >= 2,
        **_progress(sess),
    }


def photo_done(sess: Session, filename: str | None) -> dict:
    sess.photo_file = filename
    sess.stage = "review"
    if filename:
        prompt = _composite_prompt(sess, "review", ["photo_thanks", "review"])
    else:
        prompt = _prompt_payload(sess, "review")
    return {"stage": "review", "prompt": prompt, "summary": summary(sess),
            "prefetch_audio_url": prefetch_url(sess), **_progress(sess)}


def edit_field(sess: Session, key: str, value: str) -> dict:
    if key in sess.fields:
        sess.fields[key] = {"value": value, "display": value}
    return {"summary": summary(sess)}


def _live_fields(sess: Session) -> dict:
    """Agentic keeps truth in the slot state; classic in sess.fields."""
    if sess.slot_state is not None:
        return sess.slot_state.fields()
    return sess.fields


def confirm(sess: Session) -> dict:
    fields = _live_fields(sess)
    # Compliance backstop: an underage dob can never become a profile.
    dob = (fields.get("dob") or {}).get("value")
    if not dob or age_of(dob) < 18:
        raise ValueError("age_invalid")
    sess.stage = "done"
    profile = {
        "session_id": sess.id,
        "language": sess.language,
        "fields": fields,
        "photo": sess.photo_file,
        "skipped": [k for k, v in fields.items() if v["value"] is None],
        "metrics": {
            "attempts": sess.attempts,
            "clarifies": sess.clarifies,
            "answer_seconds": sess.durations,
            "clarifications": sess.clarification_count,
            "mode": settings.CONVERSATION_MODE,
            "llm_calls": sess.llm_calls,
            "t3_chars": sess.t3_chars,
            "kb_hits": sess.kb_hits,
            "kb_misses": sess.kb_misses,
            "capture_sources": (sess.slot_state.source_summary()
                                if sess.slot_state is not None else {}),
            "derived": (sess.slot_state.derived if sess.slot_state is not None else {}),
        },
        "completed_at": time.time(),
        "duration_sec": round(time.time() - sess.created_at, 1),
    }
    out = settings.PROFILES_DIR / f"{sess.id}.json"
    out.write_text(json.dumps(profile, ensure_ascii=False, indent=2))
    return {"stage": "done", "prompt": _prompt_payload(sess, "done"), "profile_file": out.name}


def resume_payload(sess: Session) -> dict:
    """Everything the frontend needs to continue mid-session after a reload."""
    if sess.stage == "asking":
        key = QUESTION_ORDER[sess.q_index]
        prompt = _prompt_payload(sess, key)
        _mark_asked(sess, key)
    elif sess.stage == "photo":
        prompt = _prompt_payload(sess, "photo")
    else:
        prompt = _prompt_payload(sess, "review")
    return {"stage": sess.stage, "prompt": prompt, "summary": summary(sess),
            "prefetch_audio_url": prefetch_url(sess), **_progress(sess)}


def _peek_next_key(sess: Session) -> str | None:
    """Most likely NEXT prompt after the one being spoken now — used for
    frontend audio prefetch. Gender auto-skip aware."""
    if sess.stage == "photo":
        return "review"
    if sess.stage == "review":
        return "done"
    if sess.stage != "asking":
        return None
    i = sess.q_index + 1
    while i < len(QUESTION_ORDER):
        key = QUESTION_ORDER[i]
        if key == "gender":
            fw = sess.fields.get("for_whom", {}).get("value")
            if fw in ("son", "daughter") or "gender" in sess.fields:
                i += 1
                continue
        return key
    return "photo"


def fragment_urls(sess: Session, keys: list[str]) -> dict:
    """Cached URLs for lines the frontend plays on its own (barge-in ack,
    resume bridge, the silence prompt). Looks in the fragment library first,
    then the T1 question set. Cache-only — a missing one is omitted, never
    synthesized at request time."""
    from core import fragments
    out = {}
    for k in keys:
        text = fragments.text(sess.language, k) if fragments.exists(sess.language, k) else None
        tier = "T2"
        if text is None and k in S.get(sess.language, {}):
            text, tier = S[sess.language][k], "T1"
        if not text:
            continue
        fname = tts.lookup(text, sess.language, key=k, tier=tier)
        if fname:
            out[k] = f"/audio/{fname}"
    return out


def prefetch_url(sess: Session) -> str | None:
    key = _peek_next_key(sess)
    if not key:
        return None
    audio = tts.synthesize(get_string(sess.language, key), sess.language)
    return f"/audio/{audio}" if audio else None


def summary(sess: Session) -> list[dict]:
    labels = FIELD_LABELS.get(sess.language, FIELD_LABELS["en"])
    return [
        {"key": k, "label": labels.get(k, k), "display": v["display"], "value": v["value"],
         "source": v.get("source", "spoken")}
        for k, v in _live_fields(sess).items()
    ]


def _progress(sess: Session) -> dict:
    total = len(QUESTION_ORDER) + 1  # + photo
    done = min(sess.q_index, len(QUESTION_ORDER)) + (1 if sess.stage in ("review", "done") else 0)
    return {"progress": {"done": done, "total": total}}


def stats() -> dict:
    """Funnel analytics: per-question medians + clarify rates + drop points."""
    all_s = list(_SESSIONS.values())
    completed = [s for s in all_s if s.stage == "done"]

    def median(xs):
        xs = sorted(xs)
        return round(xs[len(xs) // 2], 2) if xs else None

    per_q = {}
    for key in QUESTION_ORDER:
        durs = [s.durations[key] for s in all_s if key in s.durations]
        att = sum(s.attempts.get(key, 0) for s in all_s)
        cla = sum(s.clarifies.get(key, 0) for s in all_s)
        clarif = sum(s.clarification_count.get(key, 0) for s in all_s)
        per_q[key] = {
            "answered": len(durs),
            "median_sec": median(durs),
            "attempts": att,
            "clarify_rate": round(cla / att, 2) if att else 0.0,
            # A question clarified often is a badly worded question — copy backlog.
            "clarification_requests": clarif,
        }
    drop_points = {}
    for s in all_s:
        if s.stage in ("asking", "photo"):
            k = current_question(s) or "?"
            drop_points[k] = drop_points.get(k, 0) + 1
    from core import kb as _kb
    return {
        "sessions_started": len(all_s),
        "sessions_completed": len(completed),
        "by_language": {l: sum(1 for s in all_s if s.language == l) for l in {s.language for s in all_s}},
        "per_question": per_q,
        "in_flight_at": drop_points,
        "conversation_mode": settings.CONVERSATION_MODE,
        "llm_calls_total": sum(s.llm_calls for s in all_s),
        "kb": {"hits": sum(s.kb_hits for s in all_s),
               "misses": sum(s.kb_misses for s in all_s),
               **_kb.gaps()},
        # Any entry here means the browser's robotic voice spoke a line.
        "cache_misses": sorted(tts.MISSES.values(), key=lambda m: -m["count"])[:20],
    }
