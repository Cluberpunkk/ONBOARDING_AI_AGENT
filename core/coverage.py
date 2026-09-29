"""
Language-aware mode resolution.

Agentic mode speaks in fragments and KB answers. A language that has only its
T1 questions cached would fall through to English text — and then to the
browser's robotic voice — on every acknowledgement. So agentic NEVER activates
on a language it cannot speak properly: that language runs classic instead,
which only ever needs the T1 lines it already has.

Demo-safe by construction, and this is the natural gate for rollout: generate a
language's fragments + KB, and it joins the agentic set automatically.
"""
from __future__ import annotations

import logging

from config import settings
from core import fragments, kb, tts
from core.questions import S

log = logging.getLogger("sakhi.coverage")

_cache: dict[str, bool] = {}


def _has_full_coverage(lang: str) -> bool:
    """Every fragment and KB answer must exist IN THIS LANGUAGE and be cached.
    T1 questions are checked too, though they are warmed for all languages."""
    frags = fragments.FRAGMENTS.get(lang)
    if not frags or set(frags) != set(fragments.FRAGMENTS["en"]):
        return False
    for key, text in S.get(lang, {}).items():
        if tts.lookup(text, lang, key=key, tier="T1", probe=True) is None:
            return False
    for key, text in frags.items():
        if tts.lookup(text, lang, key=key, tier="T2", probe=True) is None:
            return False
    from core.questions import SUBJECT_VARIANTS, EXPANSIONS
    for subj, qs in SUBJECT_VARIANTS.get(lang, {}).items():
        for key, text in qs.items():
            if tts.lookup(text, lang, key=f"{key}/{subj}", tier="VAR", probe=True) is None:
                return False
    for key, text in EXPANSIONS.get(lang, {}).items():
        if tts.lookup(text, lang, key=key, tier="EXPAND", probe=True) is None:
            return False
    for key in kb.KB_KEYS:
        if lang not in kb.KB[key]:
            return False
        if tts.lookup(kb.KB[key][lang], lang, key=key, tier="KB", probe=True) is None:
            return False
    return True


def supports_agentic(lang: str, *, refresh: bool = False) -> bool:
    if refresh or lang not in _cache:
        _cache[lang] = _has_full_coverage(lang)
    return _cache[lang]


def agentic_languages(refresh: bool = False) -> list[str]:
    return [l for l in S if supports_agentic(l, refresh=refresh)]


def mode_for(lang: str) -> str:
    """The mode this session will ACTUALLY run in."""
    if not settings.agentic:
        return "classic"
    if supports_agentic(lang):
        return "agentic"
    log.info("Language %r lacks full agentic coverage — running classic for this session", lang)
    return "classic"
