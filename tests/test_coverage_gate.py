"""
BUILD-BLOCKING COVERAGE GATE.

Every key that can appear in a speech plan must resolve to a cached clip in the
ACTIVE language set. A missing clip means the browser's speech synthesis speaks
that line — a robotic, usually male, voice mid-conversation. This test exists so
that can never ship silently again.

Active languages default to Hindi (the agentic demo language). Set
SAKHI_ACTIVE_LANGS=hi,en to widen the gate as other languages are generated.

Run:  python3 tests/test_coverage_gate.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_pin import pin, assert_all_reads_pinned, declare_unpinned

from core import fragments, kb, tts          # noqa: E402
from core.questions import S                 # noqa: E402

# The voice recipe decides which cache entries exist, so it must be pinned to
# whatever the shipped clips were generated with, not to the developer's .env.
pin(ELEVENLABS_VOICE_ID="PId0lEbL3SOYkQZSraml", ELEVENLABS_MODEL="eleven_v4",
    ELEVENLABS_STABILITY=0.75, ELEVENLABS_SIMILARITY=0.80,
    ELEVENLABS_STYLE=0.15, ELEVENLABS_SPEED=0.97)

# SAKHI_ACTIVE_LANGS is the ONE deliberate knob: it widens the gate as languages
# are generated. Default is the shipped set.
ACTIVE = [l.strip() for l in os.getenv("SAKHI_ACTIVE_LANGS", "hi").split(",") if l.strip()]


def registry(lang):
    from core.questions import SUBJECT_VARIANTS, EXPANSIONS
    for key, text in S[lang].items():
        yield "T1", key, text
    # Subject-aware variants and clarification expansions are spoken assets too —
    # a missing one puts the browser voice into a daughter/son session.
    for subj, qs in SUBJECT_VARIANTS.get(lang, {}).items():
        for key, text in qs.items():
            yield f"VAR:{subj}", key, text
    for key, text in EXPANSIONS.get(lang, {}).items():
        yield "EXPAND", key, text
    for key, text in fragments.FRAGMENTS.get(lang, {}).items():
        yield "T2", key, text
    for key in kb.KB_KEYS:
        yield "KB", key, kb.text(lang, key)


def test_every_key_has_audio():
    missing = []
    counts = {}
    for lang in ACTIVE:
        for tier, key, text in registry(lang):
            counts[tier] = counts.get(tier, 0) + 1
            if not text:
                missing.append(f"{lang}/{tier}/{key} (NO TEXT)")
            elif tts.lookup(text, lang, key=key, tier=tier) is None:
                missing.append(f"{lang}/{tier}/{key}")
    assert not missing, (
        f"\n{len(missing)} keys would fall back to the browser voice:\n  "
        + "\n  ".join(missing[:40])
        + "\n\nGenerate them with scripts/build_fragments.py before shipping.")
    total = sum(counts.values())
    print(f"  ok  coverage gate: {total} keys x {ACTIVE} all cached "
          f"({', '.join(f'{k}={v}' for k, v in sorted(counts.items()))})")


def test_language_parity_of_registries():
    """A key present in one active language must exist in all of them,
    otherwise part_text() silently serves English into a non-English clip."""
    if len(ACTIVE) < 2:
        print("  ok  language parity: single active language, nothing to compare")
        return
    base = set(fragments.FRAGMENTS[ACTIVE[0]])
    for lang in ACTIVE[1:]:
        diff = base ^ set(fragments.FRAGMENTS.get(lang, {}))
        assert not diff, f"fragment keys differ between {ACTIVE[0]} and {lang}: {sorted(diff)}"
    for lang in ACTIVE:
        for key in kb.KB_KEYS:
            assert lang in kb.KB[key], f"KB/{key} has no {lang} text"
    print(f"  ok  language parity across {ACTIVE}")


if __name__ == "__main__":
    print(f"COVERAGE GATE — active languages: {ACTIVE}")
    test_every_key_has_audio()
    test_language_parity_of_registries()
    assert_all_reads_pinned()
    print("COVERAGE GATE PASSED")
