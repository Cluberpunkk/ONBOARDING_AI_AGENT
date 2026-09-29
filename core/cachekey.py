"""Shared cache identity for a spoken Sakhi line.

One sha1 stem per (lang, voice, text) — the TTS mp3 and the avatar mp4 for the
same line share this stem: data/tts_cache/<stem>.mp3  <->  data/avatar_cache/<stem>.mp4
Changing a line's text in questions.py changes its stem and orphans both files.
"""
import hashlib

from config import settings


def cache_stem(text: str, lang: str) -> str:
    basis = (
        f"{lang}|{settings.ELEVENLABS_VOICE_ID}|{settings.ELEVENLABS_MODEL}"
        f"|{settings.ELEVENLABS_STABILITY}|{settings.ELEVENLABS_SIMILARITY}"
        f"|{settings.ELEVENLABS_STYLE}|{settings.ELEVENLABS_SPEED}|{text}"
    )
    return hashlib.sha1(basis.encode()).hexdigest()[:20]
