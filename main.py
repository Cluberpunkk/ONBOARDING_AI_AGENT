"""
Sakhi — voice-first matrimony profile creation agent.

Run:  uvicorn main:app --reload --host 127.0.0.1 --port 8010
Open: http://127.0.0.1:8010
"""
import logging
import shutil
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from config import settings
from core import avatar, coverage, runtime_state
from core import session as sm
from core.parser import parse_answer, _is_skip
from core.questions import LANGUAGES, STT_LOCALES

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s — %(message)s")
log = logging.getLogger("sakhi")

app = FastAPI(title="Sakhi", version="1.0")


@app.on_event("startup")
def _warm_llm_paths():
    """Throwaway calls in the background so the first REAL turn skips the ~1s
    Gemini client/TLS init. Both LLM entry points need it: the classic parser
    and the agentic extractor build separate clients and separate prompt
    shapes (measured 1.6s cold vs ~0.8s warm on each)."""
    if not settings.parser_enabled:
        return
    import threading

    def warm():
        try:
            parse_answer("for_whom", "अपने लिए", "hi")
        except Exception:
            pass
        if settings.agentic:
            try:
                from core.extractor import llm_extract
                from core.slots import SlotState
                llm_extract("अपने लिए", "hi", SlotState(), "for_whom")
            except Exception:
                pass

    threading.Thread(target=warm, daemon=True).start()


@app.on_event("startup")
def _print_state_banner():
    """State visibility: if what you are about to test isn't in this banner,
    it isn't running. Printed before the first request can arrive."""
    print(runtime_state.banner(), flush=True)

app.mount("/audio", StaticFiles(directory=settings.TTS_CACHE_DIR), name="audio")
app.mount("/avatar", StaticFiles(directory=settings.AVATAR_CACHE_DIR), name="avatar")
app.mount("/photos", StaticFiles(directory=settings.PHOTOS_DIR), name="photos")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ----------------------------- schemas ---------------------------------
class StartRequest(BaseModel):
    language: str


class AnswerRequest(BaseModel):
    transcript: str


class EditRequest(BaseModel):
    key: str
    value: str


# ----------------------------- routes ----------------------------------
@app.get("/")
def index():
    return FileResponse("static/index.html")


@app.get("/api/healthz")
def healthz():
    return {
        "ok": True,
        "tts": "elevenlabs" if settings.tts_enabled else "browser-fallback",
        "parser": "gemini" if settings.parser_enabled else "mock-keywords",
        "avatar": "clips" if settings.avatar_enabled else "disabled",
        "avatar_clips": avatar.clip_count(),
        "conversation_mode": settings.CONVERSATION_MODE,
        # Languages with full fragment+KB audio. Any language NOT listed here
        # runs classic even when CONVERSATION_MODE=agentic.
        "agentic_languages": coverage.agentic_languages(refresh=True),
    }


@app.get("/api/languages")
def languages():
    return {"languages": LANGUAGES, "stt_locales": STT_LOCALES,
            "idle_mode": settings.AVATAR_IDLE_MODE,
            # Two independent switches: conversation intelligence and the
            # microphone behaviour. A noisy demo room can kill barge-in
            # without giving up agentic mode.
            "conversation_mode": settings.CONVERSATION_MODE,
            "barge_in": settings.BARGE_IN_ENABLED,
            "vad_endpointing": settings.VAD_ENDPOINTING_ENABLED,
            "stt_endpoint_silence_ms": settings.STT_ENDPOINT_SILENCE_MS}


@app.post("/api/session/start")
def start_session(req: StartRequest):
    if req.language not in STT_LOCALES:
        raise HTTPException(400, f"Unsupported language: {req.language}")
    sess, intro, first_q = sm.start(req.language)
    log.info("Session %s started [%s] mode=%s (configured=%s)",
             sess.id, req.language, sess.resolved_mode, settings.CONVERSATION_MODE)
    return {
        "session_id": sess.id,
        "stt_locale": STT_LOCALES[req.language],
        "intro": intro,
        "first_question": first_q,
        "prefetch_audio_url": sm.prefetch_url(sess),
        # Cached URLs for the fragments the frontend plays on its own
        # (interruption ack, resume bridge) — no synthesis, disk only.
        "fragment_urls": sm.fragment_urls(sess, ["interrupt_ack", "bridge_resume", "silence"]),
        "progress": {"done": 0, "total": 12},
    }


@app.post("/api/session/{sid}/answer")
def answer(sid: str, req: AnswerRequest):
    sess = sm.get(sid)
    if not sess:
        raise HTTPException(404, "Session not found")

    # ---- agentic mode: slot-filling dialogue (classic path below is untouched)
    if sess.slot_state is not None and sess.stage == "asking":
        from core import agentic
        log.info("Session %s [agentic] answer: %r", sid, req.transcript[:80])
        return agentic.handle_turn(sess, req.transcript)

    key = sm.current_question(sess)
    if not key:
        raise HTTPException(400, f"Session is in stage '{sess.stage}', not expecting answers")

    log.info("Session %s [%s] answer: %r", sid, key, req.transcript[:80])

    # Sensitive-question skip: caste/income honor the multilingual skip words
    if key in sm.SKIPPABLE and _is_skip(req.transcript):
        return sm.skip_field(sess, key)

    result = parse_answer(key, req.transcript, sess.language)

    # Photo stage: only 'skip' is a valid spoken action
    if key == "photo":
        if result.is_skip:
            return sm.photo_done(sess, None)
        return {"stage": "photo", "prompt": None, "hint": "awaiting_upload_or_skip"}

    if not result.confident:
        return sm.clarify(sess)

    # 18+ age gate: never store an underage dob
    if key == "dob" and sm.age_of(result.value) < 18:
        log.info("Session %s age gate triggered (dob %s)", sid, result.value)
        return sm.age_reask(sess)

    payload = sm.accept_answer(sess, key, result.value, result.display)
    payload["accepted"] = {"key": key, "display": result.display}
    payload["parser"] = result.source   # demo overlay's live cost counter
    return payload


@app.post("/api/session/{sid}/photo")
async def upload_photo(sid: str, file: UploadFile = File(...)):
    sess = sm.get(sid)
    if not sess:
        raise HTTPException(404, "Session not found")
    ext = (file.filename or "photo.jpg").rsplit(".", 1)[-1].lower()
    if ext not in ("jpg", "jpeg", "png", "webp"):
        raise HTTPException(400, "Only JPG, PNG or WebP")
    fname = f"{sid}_{uuid.uuid4().hex[:6]}.{ext}"
    dest = settings.PHOTOS_DIR / fname
    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    log.info("Session %s photo saved: %s", sid, fname)
    return sm.photo_done(sess, fname)


@app.post("/api/session/{sid}/skip-photo")
def skip_photo(sid: str):
    sess = sm.get(sid)
    if not sess:
        raise HTTPException(404, "Session not found")
    return sm.photo_done(sess, None)


@app.post("/api/session/{sid}/edit")
def edit(sid: str, req: EditRequest):
    sess = sm.get(sid)
    if not sess:
        raise HTTPException(404, "Session not found")
    return sm.edit_field(sess, req.key, req.value)


@app.post("/api/session/{sid}/confirm")
def confirm(sid: str):
    sess = sm.get(sid)
    if not sess:
        raise HTTPException(404, "Session not found")
    try:
        result = sm.confirm(sess)
    except ValueError as e:
        raise HTTPException(400, str(e))   # age_invalid backstop
    log.info("Session %s confirmed — profile saved", sid)
    return result


@app.get("/api/session/{sid}/resume")
def resume(sid: str):
    """Continue an interrupted session at the exact question (30-min TTL)."""
    sess = sm.get(sid)
    if not sess or sess.stage == "done":
        raise HTTPException(404, "No resumable session")
    payload = sm.resume_payload(sess)
    payload["session_id"] = sess.id
    payload["language"] = sess.language
    payload["stt_locale"] = STT_LOCALES[sess.language]
    return payload


@app.get("/api/session/{sid}/state")
def state(sid: str):
    sess = sm.get(sid)
    if not sess:
        raise HTTPException(404, "Session not found")
    return {"stage": sess.stage, "summary": sm.summary(sess), "photo": sess.photo_file}


@app.get("/api/chunk-maps")
def chunk_maps():
    """Sentence boundaries for barge-in resume. Built offline by
    scripts/build_chunk_maps.py — no API cost, cached by the browser."""
    p = settings.DATA_DIR / "chunk_maps.json"
    if not p.exists():
        return {}
    import json as _json
    return _json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/state")
def state():
    """The resolved truth about what is actually running — configured vs active,
    build identity, and every gap between the two as an explicit warning."""
    return runtime_state.state()


@app.get("/api/stats")
def stats():
    return sm.stats()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.HOST, port=settings.PORT)
