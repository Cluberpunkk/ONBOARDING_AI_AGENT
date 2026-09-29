"""
The agent spec is the single source of truth. These tests make that structural.

Run:  python3 tests/test_agent_spec.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from config_pin import pin, assert_all_reads_pinned   # noqa: E402
pin(CONVERSATION_MODE="classic", GEMINI_API_KEY="", ELEVENLABS_API_KEY="",
    ELEVENLABS_VOICE_ID="PId0lEbL3SOYkQZSraml", ELEVENLABS_MODEL="eleven_v4",
    ELEVENLABS_STABILITY=0.75, ELEVENLABS_SIMILARITY=0.80,
    ELEVENLABS_STYLE=0.15, ELEVENLABS_SPEED=0.97, AVATAR_ENABLED=False,
    BARGE_IN_ENABLED=True, VAD_ENDPOINTING_ENABLED=False,
    STT_ENDPOINT_SILENCE_MS=800, ACK_RATE=0.35, PARSER_MODEL="gemini-3.5-flash-lite",
    THINK_TIME_MS_RANGE="250-600", THINK_TIME_MS_RANGE_DEEP="400-900",
    TURN_GAP_MS_RANGE="250-400", SOFT_OPENER_RATE=0.22,
    AVATAR_IDLE_MODE="static", T3_CHAR_BUDGET_PER_SESSION=0)   # spec tests are offline

from agent import system_prompt as sp          # noqa: E402


def test_spec_document_exists_and_is_readable():
    text = sp.SPEC_PATH.read_text(encoding="utf-8")
    assert "THIS IS NOT A CONVERSATIONAL SYSTEM PROMPT" in text, \
        "the constraint must be stated at the top of the document itself"
    nums = [n for n, _t, _b in sp._sections()]
    # Contiguous from §1, however many there are. Pinning the count meant adding
    # a section broke this test for no reason; a GAP or a duplicate still fails,
    # which is the thing actually worth catching (a section that stopped parsing).
    assert nums == [f"§{i}" for i in range(1, len(nums) + 1)], \
        f"sections are not contiguous from §1: {nums}"
    assert len(nums) >= 10, f"sections went missing: {nums}"
    print(f"  ok  SAKHI.md present, {len(nums)} sections, constraint stated up front")


def test_prompt_is_compiled_from_the_document_not_duplicated():
    """Drift is impossible because there is no second copy. Mutate the document
    in memory and BOTH compilation paths must change with it:
      - the always-on base (from §7)
      - the per-slot domain rules (from §5, injected by compile_for)
    """
    original = sp.SPEC_PATH.read_text(encoding="utf-8")
    try:
        # (a) the selection role (§7), compiled only for turns that select
        sp.SPEC_PATH.write_text(
            original.replace("Return JSON only.", "Return JSON only. SENTINEL_BASE"),
            encoding="utf-8")
        sp.compile_base.cache_clear()
        assert "SENTINEL_BASE" in sp.compile_base(selecting=True), \
            "editing §7 did not change the selection prompt — there is a duplicate copy"
        assert "SENTINEL_BASE" not in sp.compile_base(), \
            "the selection role is being sent on extraction-only turns"

        # (b) the per-slot domain rules
        sp.SPEC_PATH.write_text(
            original.replace("गृहिणी/घर पर → `not_working`",
                             "गृहिणी/घर पर → `not_working`. SENTINEL_DOMAIN"),
            encoding="utf-8")
        sp.compile_base.cache_clear()
        assert "SENTINEL_DOMAIN" in sp.compile_for("x", slot="job"), \
            "editing §5 did not reach the job slot's prompt"
        assert "SENTINEL_DOMAIN" not in sp.compile_for("x", slot="income"), \
            "job-tagged domain rules leaked into the income prompt"
    finally:
        sp.SPEC_PATH.write_text(original, encoding="utf-8")
        sp.compile_base.cache_clear()
    print("  ok  both compilation paths parse the document — no copy can drift")


def test_prompt_never_becomes_conversational():
    """The guard that stops this turning into a speaking system prompt."""
    original = sp.SPEC_PATH.read_text(encoding="utf-8")
    try:
        sp.SPEC_PATH.write_text(
            original.replace("## §7 Response selection `[compiled]`",
                             "## §7 Response selection `[compiled]`\n\nRespond to the user warmly."),
            encoding="utf-8")
        sp.compile_base.cache_clear()
        try:
            sp.compile_base(selecting=True)
            raise AssertionError("conversational instruction was NOT rejected")
        except RuntimeError as e:
            assert "interpretation only" in str(e)
    finally:
        sp.SPEC_PATH.write_text(original, encoding="utf-8")
        sp.compile_base.cache_clear()
    print("  ok  a 'respond to the user' instruction in the spec fails the build")


def test_every_llm_call_site_shares_the_base():
    """Assert, don't trust: both call sites must carry the identical base."""
    from core.extractor import _prompt
    from core.slots import SlotState
    base = sp.compile_base()
    ext = _prompt("मैं राहुल हूं", "hi", SlotState(), "full_name")
    assert base in ext, "extractor prompt does not carry the shared base"

    src = (ROOT / "core" / "parser.py").read_text(encoding="utf-8")
    assert "compile_for(" in src, "classic parser does not use the shared base"
    # and no call site may reintroduce an inline persona
    for f in ("core/extractor.py", "core/parser.py"):
        body = (ROOT / f).read_text(encoding="utf-8")
        assert "You extract structured facts from ONE spoken turn" not in body, \
            f"{f} still has an inline persona string"
    print("  ok  every LLM call site shares one compiled base; no inline personas remain")


def test_every_constitution_rule_has_a_test():
    """A rule nobody tests is a rule nobody keeps."""
    rules = sp.constitution_rules()
    assert len(rules) >= 8, f"expected the full constitution, got {len(rules)}"
    # Scan the WHOLE suite rather than a hand-listed subset: a new constitution
    # rule tested in a new file was reported as untested, which trains people to
    # edit this list instead of trusting the check.
    suite = "".join(p.read_text(encoding="utf-8")
                    for p in sorted((ROOT / "tests").glob("test_*.py")))
    missing = []
    for r in rules:
        for t in r["tests"]:
            if f"def {t}(" not in suite:
                missing.append(f"{r['id']} -> {t}")
    assert not missing, f"constitution rules with no test behind them: {missing}"
    print(f"  ok  all {len(rules)} constitution rules map to existing tests")


def test_latency_path_prompt_stays_lean():
    """Two shapes, two budgets. Extraction-only runs on every LLM turn and must
    stay minimal; the selection prompt is allowed the §7 role it actually uses."""
    extract = sp.approx_tokens(sp.compile_base())
    select = sp.approx_tokens(sp.compile_base(selecting=True))
    assert extract < 400, (
        f"extraction-only prompt is {extract} tokens — it runs on every LLM turn "
        "and carries no selection role; keep governance out of INTERPRETIVE.")
    assert select < 1000, (
        f"selection prompt is {select} tokens; trim §7 or the menu, don't grow it.")
    print(f"  ok  prompt ~{extract} tokens extracting, ~{select} selecting")


if __name__ == "__main__":
    print("AGENT SPEC")
    test_spec_document_exists_and_is_readable()
    test_prompt_is_compiled_from_the_document_not_duplicated()
    test_prompt_never_becomes_conversational()
    test_every_llm_call_site_shares_the_base()
    test_every_constitution_rule_has_a_test()
    test_latency_path_prompt_stays_lean()
    print("ALL AGENT SPEC TESTS PASSED")


# ===================== STATE VISIBILITY (Phase 0) =====================
def test_state_reports_configured_vs_actual():
    """The gap between what is CONFIGURED and what is ACTUALLY running must be
    visible, because that gap is where a wasted night of testing lives."""
    from core import runtime_state
    st = runtime_state.state()
    for section in ("build", "conversation", "voice", "parser", "mic", "pacing",
                    "avatar", "warnings"):
        assert section in st, f"/api/state missing {section}"
    c = st["conversation"]
    assert "configured_mode" in c and "effective_for_hi" in c, c
    assert isinstance(st["warnings"], list)
    print(f"  ok  state: configured={c['configured_mode']} "
          f"effective_hi={c['effective_for_hi']} warnings={len(st['warnings'])}")


def test_state_warns_when_agentic_is_configured_but_inert():
    """The exact silent failure: agentic set, but no language can run it."""
    from core import coverage, runtime_state
    from config import settings as cfg
    real = coverage.agentic_languages
    coverage.agentic_languages = lambda refresh=False: []
    prev = cfg.CONVERSATION_MODE
    cfg.CONVERSATION_MODE = "agentic"
    try:
        warns = runtime_state.state()["warnings"]
        assert any("every session will run classic" in w for w in warns), warns
    finally:
        coverage.agentic_languages = real
        cfg.CONVERSATION_MODE = prev
    print("  ok  state warns loudly when agentic is configured but inert")


def test_state_warns_on_inert_endpointing():
    from core import runtime_state
    from config import settings as cfg
    pv, pb = cfg.VAD_ENDPOINTING_ENABLED, cfg.BARGE_IN_ENABLED
    cfg.VAD_ENDPOINTING_ENABLED, cfg.BARGE_IN_ENABLED = True, False
    try:
        warns = runtime_state.state()["warnings"]
        assert any("INERT" in w for w in warns), warns
    finally:
        cfg.VAD_ENDPOINTING_ENABLED, cfg.BARGE_IN_ENABLED = pv, pb
    print("  ok  state warns when VAD endpointing is on but barge-in is off")


def test_stale_build_is_detectable():
    from core import runtime_state
    assert isinstance(runtime_state.build_id(), str)
    saved = runtime_state._BOOT_BUILD
    try:
        runtime_state._BOOT_BUILD = "definitely-not-current"
        assert runtime_state.is_stale()
        assert any("STALE" in w for w in runtime_state.state()["warnings"])
    finally:
        runtime_state._BOOT_BUILD = saved
    assert not runtime_state.is_stale()
    print("  ok  stale build (server serving code older than disk) is detected")


def test_coverage_probes_do_not_pollute_the_miss_counter():
    """A capability check is not 'the browser voice spoke'."""
    from core import tts
    before = dict(tts.MISSES)
    assert tts.lookup("यह लाइन कभी कैश नहीं हुई", "hi", key="x", tier="T2", probe=True) is None
    assert dict(tts.MISSES) == before, "probe lookups must not be recorded as misses"
    tts.lookup("यह लाइन कभी कैश नहीं हुई", "hi", key="x", tier="T2")
    assert len(tts.MISSES) == len(before) + 1, "a real miss must still be recorded"
    tts.MISSES.clear(); tts.MISSES.update(before)
    print("  ok  coverage probes don't cry wolf; real misses still recorded")


test_state_reports_configured_vs_actual()
test_state_warns_when_agentic_is_configured_but_inert()
test_state_warns_on_inert_endpointing()
test_stale_build_is_detectable()
test_coverage_probes_do_not_pollute_the_miss_counter()
print("ALL STATE VISIBILITY TESTS PASSED")
assert_all_reads_pinned()
