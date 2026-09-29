"""
Config pinning + leak detection for the test suite.

A test whose result changes with someone's local .env is not a guarantee. This
module makes that failure loud instead of silent — which is exactly how the
classic regression suite quietly stopped testing classic mode when a developer
left CONVERSATION_MODE=agentic in .env.

Usage in a test file:

    from config_pin import pin, assert_all_reads_pinned
    pin(CONVERSATION_MODE="classic", GEMINI_API_KEY="")   # before importing core.*
    ...
    assert_all_reads_pinned()                              # at the end

Every environment-driven setting the test TOUCHED must have been pinned by the
test. Reading one it didn't set is a leak and fails the run.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Settings, settings   # noqa: E402

# Environment-driven knobs that change behaviour. Derived paths are excluded —
# they don't vary between machines in a way that changes a result.
TRACKED = {
    "CONVERSATION_MODE", "BARGE_IN_ENABLED", "VAD_ENDPOINTING_ENABLED",
    "STT_ENDPOINT_SILENCE_MS", "T3_CHAR_BUDGET_PER_SESSION", "T3_MODEL",
    "ACK_RATE", "THINK_TIME_MS_RANGE", "THINK_TIME_MS_RANGE_DEEP",
    "TURN_GAP_MS_RANGE", "SOFT_OPENER_RATE", "AVATAR_IDLE_MODE",
    "AVATAR_ENABLED", "AVATAR_BASE_VIDEO", "LIPSYNC_MODEL", "FAL_KEY",
    "ELEVENLABS_API_KEY", "ELEVENLABS_VOICE_ID", "ELEVENLABS_MODEL",
    "ELEVENLABS_BASE_URL", "ELEVENLABS_STABILITY", "ELEVENLABS_SIMILARITY",
    "ELEVENLABS_STYLE", "ELEVENLABS_SPEED", "GEMINI_API_KEY", "PARSER_MODEL",
}

_pinned: set[str] = set()
_read: set[str] = set()
_installed = False


def _install():
    global _installed
    if _installed:
        return
    original = Settings.__getattribute__

    def tracking(self, name):
        if name in TRACKED:
            _read.add(name)
        return original(self, name)

    Settings.__getattribute__ = tracking
    _installed = True


def pin(**values):
    """Set config explicitly for this test run and mark it as intentional."""
    _install()
    for key, value in values.items():
        if key not in TRACKED:
            raise KeyError(f"{key} is not a tracked config knob; add it to TRACKED")
        object.__setattr__(settings, key, value) if hasattr(settings, "__dict__") \
            else setattr(Settings, key, value)
        setattr(settings, key, value)
        _pinned.add(key)
    # Pinning is a write, not a read — don't let it count as one.
    _read.difference_update(values.keys())


def declare_unpinned(*keys, reason: str = ""):
    """Escape hatch for a value a test deliberately inherits (rare). Must give a
    reason; it is printed so the exception stays visible."""
    _install()
    for k in keys:
        _pinned.add(k)
    if keys:
        print(f"  ..  deliberately inheriting {sorted(keys)}: {reason or 'no reason given'}")


def assert_all_reads_pinned():
    """Fail if the test read a behaviour knob it never set."""
    leaked = sorted(_read - _pinned)
    if leaked:
        raise AssertionError(
            "CONFIG LEAK — this test's result depends on the local .env.\n"
            f"  read but never pinned: {leaked}\n"
            "  Pin them with config_pin.pin(...) so the result is a guarantee, "
            "not a coincidence.")
    print(f"  ok  config pinned: {len(_pinned)} knobs set, 0 leaks")


def summary() -> dict:
    return {"pinned": sorted(_pinned), "read": sorted(_read),
            "leaked": sorted(_read - _pinned)}
