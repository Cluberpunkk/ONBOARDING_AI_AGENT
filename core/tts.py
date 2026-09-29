"""
ElevenLabs TTS with aggressive disk caching.

Every Sakhi line is a fixed string, so each (language, text) pair is synthesized
exactly ONCE, cached as data/tts_cache/<sha1>.mp3, then served forever from disk.
9 languages x ~17 strings = ~150 clips total, generated lazily. Your ElevenLabs
credits are only spent on first play.

No API key configured -> synthesize() returns None and the frontend falls back
to the browser's built-in speechSynthesis. The demo never blocks on a key.
"""
from __future__ import annotations
import logging

import httpx

from config import settings
from core.cachekey import cache_stem

log = logging.getLogger("sakhi.tts")

# One keep-alive client for all TTS calls (only cold generates hit the network)
_http = httpx.Client(timeout=30)


def _cache_name(text: str, lang: str) -> str:
    return f"{cache_stem(text, lang)}.mp3"


# Every cache miss is a moment where the browser's robotic voice would speak.
# Recorded so a miss can never be silent again (surfaced in /api/stats).
MISSES: dict[str, dict] = {}


def lookup(text: str, lang: str, *, key: str = "?", tier: str = "?",
           probe: bool = False) -> str | None:
    """Cache-ONLY lookup: return the filename if this line is already on disk,
    else None. NEVER generates. Agentic fragments/value-bank entries go through
    here so an un-warmed key degrades to browser TTS instead of spending."""
    fname = _cache_name(text, lang)
    if (settings.TTS_CACHE_DIR / fname).exists():
        return fname
    if probe:
        # A coverage/capability check, not a line anyone was about to hear.
        # Recording it would make the miss counter cry wolf on every boot.
        return None
    slot = f"{lang}/{tier}/{key}"
    rec = MISSES.setdefault(slot, {"lang": lang, "tier": tier, "key": key,
                                   "text": text[:60], "count": 0})
    rec["count"] += 1
    log.warning("CACHE MISS -> browser voice would speak: %s %r", slot, text[:60])
    return None


def _endpoint() -> str:
    return f"{settings.ELEVENLABS_BASE_URL}/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}"


def voice_settings(model: str | None = None) -> dict:
    """Voice character from .env. eleven_v3 only accepts discrete stability
    values (0.0 creative / 0.5 natural / 1.0 robust) — snap to nearest."""
    model = model or settings.ELEVENLABS_MODEL
    stability = settings.ELEVENLABS_STABILITY
    if model.startswith("eleven_v3"):
        stability = min((0.0, 0.5, 1.0), key=lambda v: abs(v - stability))
    return {
        "stability": stability,
        "similarity_boost": settings.ELEVENLABS_SIMILARITY,
        "style": settings.ELEVENLABS_STYLE,
        "speed": settings.ELEVENLABS_SPEED,
    }


def synthesize(text: str, lang: str) -> str | None:
    """Return the cache filename for this line, generating it if needed.
    Returns None when ElevenLabs isn't configured or the call fails."""
    if not settings.tts_enabled:
        return None

    fname = _cache_name(text, lang)
    fpath = settings.TTS_CACHE_DIR / fname
    if fpath.exists():
        return fname

    payload = {
        "text": text,
        "model_id": settings.ELEVENLABS_MODEL,
        "voice_settings": voice_settings(),
    }
    try:
        resp = _http.post(
            _endpoint(),
            params={"output_format": "mp3_44100_128"},
            headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
            json=payload,
            timeout=30,
        )
        if resp.status_code == 422:
            # settings not accepted by this model — degrade to defaults rather
            # than silently losing the voice again
            log.warning("voice_settings rejected (422) — retrying without: %s", resp.text[:200])
            payload.pop("voice_settings")
            resp = _http.post(
                _endpoint(),
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
                json=payload,
                timeout=30,
            )
        resp.raise_for_status()
        fpath.write_bytes(resp.content)
        log.info("TTS generated [%s] %s chars -> %s", lang, len(text), fname)
        return fname
    except Exception as e:
        log.error("ElevenLabs TTS failed: %s", e)
        return None
