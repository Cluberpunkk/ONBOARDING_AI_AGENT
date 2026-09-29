"""
Runtime state visibility.

WHY THIS EXISTS: it is possible to spend a night testing a build that is not
running what you think it is running — agentic configured but silently falling
back to classic, barge-in enabled but the mic denied, a feature flag off, or a
server still serving code from before your last edit. Every one of those looks
identical from the outside: the app just behaves "wrong".

So the app states, loudly and in three places, exactly what is live:
  - a startup banner in the server log
  - GET /api/state, the machine-readable truth
  - an always-visible badge in the browser (not hidden behind ?demo=1)

Anything CONFIGURED but not ACTIVE is reported as a warning, because that gap is
precisely where the wasted night lives.
"""
from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

from config import settings

BOOT_TIME = time.time()

# Files whose content defines behaviour. Their combined hash is the build id:
# if it changes and the server didn't restart, you are testing stale code.
_SOURCE_GLOBS = ("core/*.py", "agent/*.py", "agent/*.md", "main.py", "config.py",
                 "static/js/*.js", "static/css/*.css", "static/index.html")
_ROOT = Path(__file__).resolve().parent.parent


def _source_files() -> list[Path]:
    out = []
    for pat in _SOURCE_GLOBS:
        out.extend(sorted(_ROOT.glob(pat)))
    return out


def build_id() -> str:
    """Short hash of all behaviour-defining source. Changes when you edit code."""
    h = hashlib.sha1()
    for f in _source_files():
        try:
            h.update(f.name.encode())
            h.update(str(int(f.stat().st_mtime)).encode())
            h.update(str(f.stat().st_size).encode())
        except OSError:
            continue
    return h.hexdigest()[:10]


_BOOT_BUILD = build_id()


def is_stale() -> bool:
    """True when source changed after boot — i.e. the running server is NOT the
    code on disk. Without --reload this is the classic silent time-waster."""
    return build_id() != _BOOT_BUILD


def state() -> dict:
    """The resolved truth about what is actually running right now."""
    from core import avatar, coverage, fragments, kb, tts
    from core.questions import S

    agentic_langs = coverage.agentic_languages(refresh=True)
    configured = settings.CONVERSATION_MODE
    warnings: list[str] = []

    # --- the gap between CONFIGURED and ACTIVE — where wasted nights live ----
    if configured == "agentic" and not agentic_langs:
        warnings.append("CONVERSATION_MODE=agentic but NO language has full "
                        "audio coverage — every session will run classic.")
    elif configured == "agentic":
        missing = [l for l in S if l not in agentic_langs]
        if missing:
            warnings.append(f"agentic is active only for {agentic_langs}; "
                            f"{len(missing)} other languages fall back to classic")
    if settings.VAD_ENDPOINTING_ENABLED and not settings.BARGE_IN_ENABLED:
        warnings.append("VAD_ENDPOINTING_ENABLED=true but BARGE_IN_ENABLED=false "
                        "— endpointing needs the barge-in mic stream, so it is INERT.")
    if not settings.tts_enabled:
        warnings.append("No ElevenLabs key — every line falls back to the browser voice.")
    if not settings.parser_enabled:
        warnings.append("No Gemini key — keyword parsing only; agentic extraction is inert.")
    if tts.MISSES:
        warnings.append(f"{len(tts.MISSES)} cache miss(es) since boot — the browser "
                        f"voice spoke: {sorted(tts.MISSES)[:3]}")
    if is_stale():
        warnings.append("STALE BUILD — source files changed since this server "
                        "started. Restart, or you are testing old code.")

    cached_hi = sum(1 for t in S.get("hi", {}).values() if tts.lookup(t, "hi"))
    return {
        "build": {
            "id": _BOOT_BUILD,
            "current": build_id(),
            "stale": is_stale(),
            "booted_at": BOOT_TIME,
            "uptime_sec": round(time.time() - BOOT_TIME, 1),
            "pid": os.getpid(),
        },
        "conversation": {
            "configured_mode": configured,
            "agentic_languages": agentic_langs,
            "effective_for_hi": coverage.mode_for("hi"),
        },
        "voice": {
            "tts": "elevenlabs" if settings.tts_enabled else "browser-fallback",
            "voice_id": settings.ELEVENLABS_VOICE_ID[:8] + "…" if settings.ELEVENLABS_VOICE_ID else "",
            "model": settings.ELEVENLABS_MODEL,
            "recipe": f"stab {settings.ELEVENLABS_STABILITY} · sim {settings.ELEVENLABS_SIMILARITY}"
                      f" · style {settings.ELEVENLABS_STYLE} · speed {settings.ELEVENLABS_SPEED}",
            "questions_cached_hi": f"{cached_hi}/{len(S.get('hi', {}))}",
            "fragments": len(fragments.FRAGMENTS.get("hi", {})),
            "kb_entries": len(kb.KB_KEYS),
        },
        "parser": {
            "engine": "gemini" if settings.parser_enabled else "mock-keywords",
            "model": settings.PARSER_MODEL,
        },
        "mic": {
            "barge_in": settings.BARGE_IN_ENABLED,
            "vad_endpointing": settings.VAD_ENDPOINTING_ENABLED,
            "endpoint_silence_ms": settings.STT_ENDPOINT_SILENCE_MS,
        },
        "pacing": {
            "ack_rate": settings.ACK_RATE,
            "think_ms": settings.THINK_TIME_MS_RANGE,
            "think_ms_deep": settings.THINK_TIME_MS_RANGE_DEEP,
            "turn_gap_ms": settings.TURN_GAP_MS_RANGE,
            "soft_opener_rate": settings.SOFT_OPENER_RATE,
        },
        "avatar": {
            "enabled": settings.avatar_enabled,
            "idle_mode": settings.AVATAR_IDLE_MODE,
            "clips": avatar.clip_count(),
        },
        "budget": {"t3_chars_per_session": settings.T3_CHAR_BUDGET_PER_SESSION},
        "cache_misses": sorted(tts.MISSES.values(), key=lambda m: -m["count"])[:10],
        "warnings": warnings,
    }


def banner() -> str:
    """Printed at startup. If what you are about to test isn't here, it isn't on."""
    s = state()
    c, m, v, p = s["conversation"], s["mic"], s["voice"], s["parser"]
    W = 62

    def row(text: str) -> str:
        return "│ " + text[:W - 2].ljust(W - 2) + "│"

    lines = [
        "",
        "┌" + "─" * W + "┐",
        row(f"SAKHI  build {s['build']['id']}   pid {s['build']['pid']}"),
        "├" + "─" * W + "┤",
        row(f"mode      : {c['configured_mode']:<10} → hi runs {c['effective_for_hi']}"),
        row(f"agentic in: {c['agentic_languages']}"),
        row(f"voice     : {v['tts']:<17} {v['model']:<12} q{v['questions_cached_hi']}"),
        row(f"recipe    : {v['recipe']}"),
        row(f"parser    : {p['engine']:<17} {p['model']}"),
        row(f"mic       : barge_in={str(m['barge_in']):<6} vad_endpointing={m['vad_endpointing']}"),
        row(f"avatar    : {('clips ' + str(s['avatar']['clips'])) if s['avatar']['enabled'] else 'disabled':<17} idle={s['avatar']['idle_mode']}"),
    ]
    if s["warnings"]:
        lines.append("├" + "─" * W + "┤")
        for w in s["warnings"]:
            for i, chunk in enumerate(_wrap(w, W - 6)):
                mark = "⚠" if i == 0 else " "
                lines.append("│ " + f"{mark} {chunk}"[:W - 2].ljust(W - 2) + "│")
    lines.append("└" + "─" * W + "┘")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words, out, cur = text.split(), [], ""
    for w in words:
        if len(cur) + len(w) + 1 > width:
            out.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        out.append(cur)
    return out
