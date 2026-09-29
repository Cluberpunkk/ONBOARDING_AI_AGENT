"""Pre-rendered avatar clip lookup — disk only, zero API calls.

Clips are generated offline by scripts/build_avatar_clips.py (the only file
allowed to call fal.ai) and share their sha1 stem with the TTS cache:
data/tts_cache/<stem>.mp3  <->  data/avatar_cache/<stem>.mp4
"""
from __future__ import annotations

from config import settings
from core.cachekey import cache_stem


def get_clip(text: str, lang: str) -> str | None:
    """Return cached clip filename for this line, or None. NEVER generates."""
    fname = f"{cache_stem(text, lang)}.mp4"
    return fname if (settings.AVATAR_CACHE_DIR / fname).exists() else None


def clip_count() -> int:
    return sum(1 for _ in settings.AVATAR_CACHE_DIR.glob("*.mp4"))
