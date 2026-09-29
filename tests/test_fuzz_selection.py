"""
Fuzz the response selector with real-speech non-answers.

WHY THIS IS A COMMITTED TEST AND NOT A SCRIPT: selection degrades SILENTLY. When
the model's plan fails to parse, agentic falls back to deterministic routing and
every reply still looks reasonable — the feature is dead and nothing says so.
That happened twice (paren format, then pipe format). So this file asserts two
different things:

  1. QUALITY  — a non-answer must produce a MORE HELPFUL turn than the one
                before it: different words, never silence, never the same
                sentence again.
  2. LIVENESS — the model must actually be doing the choosing. If the plan-parse
                path breaks again, `selected` collapses to 0 and this fails,
                instead of the fallback quietly covering for it.

Run: python3 tests/test_fuzz_selection.py
"""
from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config_pin import pin, assert_all_reads_pinned, declare_unpinned   # noqa: E402

pin(CONVERSATION_MODE="agentic", BARGE_IN_ENABLED=False,
    VAD_ENDPOINTING_ENABLED=False, AVATAR_ENABLED=False,
    # The voice recipe is part of the CACHE KEY, so it must match the recipe the
    # cache was warmed with — pinning it to stock defaults makes every cached
    # clip unfindable, coverage drops to zero and the session silently runs
    # classic, i.e. this suite would fuzz a path that isn't the one shipping.
    ELEVENLABS_API_KEY="",             # never spend credits
    ELEVENLABS_VOICE_ID="PId0lEbL3SOYkQZSraml",
    ELEVENLABS_MODEL="eleven_v4",
    ELEVENLABS_STABILITY=0.75, ELEVENLABS_SIMILARITY=0.80,
    ELEVENLABS_STYLE=0.15, ELEVENLABS_SPEED=0.97,
    ACK_RATE=0.0, THINK_TIME_MS_RANGE=(0, 0), THINK_TIME_MS_RANGE_DEEP=(0, 0),
    TURN_GAP_MS_RANGE=(0, 0))
declare_unpinned("GEMINI_API_KEY", "PARSER_MODEL",
                 reason="live model calls are the point of this suite")

from core import agentic, session as sm            # noqa: E402
from core.questions import get_string              # noqa: E402
from core.slots import SKIPPABLE, SLOT_PRIORITY    # noqa: E402
from fuzz_nonanswers import NON_ANSWERS            # noqa: E402

# Values used to seed the slots BEFORE the question under test. Storable values,
# not utterances — nothing here goes through extraction. Ordering comes from
# SLOT_PRIORITY at runtime, so a priority change can never leave this suite
# fuzzing the wrong question while still looking green. (It did: a hand-written
# path aimed the district cases at the gender confirmation, a code-owned prompt
# the selector never even sees.)
SEED = {
    "for_whom": "self", "full_name": "Rahul Sharma", "gender": "male",
    "dob": "1995-03-12", "district": "Jaipur", "religion": "hindu",
    "marital": "never_married", "qualification": "graduate", "job": "business",
    "income": 20000, "caste": "general",
}


def reach(question: str):
    """Put a fresh session at `question` by SEEDING state directly.

    Walking there by speaking answers meant ~8 live model turns per case, 360
    across the suite — so a single non-deterministic hiccup (one 'हाँ' not
    confirming) aborted the whole run, and the failure had nothing to do with
    the selector. The selector is what is under test here; how well extraction
    handles 'राहुल शर्मा' is test_extraction_fixtures' job. Seeding is
    deterministic, free, and isolates the thing being measured.

    Returns (session, the question text Sakhi just asked).
    """
    sess, _, _ = sm.start("hi")
    state = sess.slot_state
    assert question in SLOT_PRIORITY, f"{question!r} is not a slot"
    for key in SLOT_PRIORITY:
        if key == question:
            break
        if key in SKIPPABLE:
            state.skip(key)
        else:
            value = SEED[key]
            state.fill(key, value, str(value), confidence=1.0, source="spoken")
    assert state.next_slot() == question, (
        f"seeding left the session at {state.next_slot()!r}, not {question!r} — "
        "SEED is missing a slot or a filled value needs confirmation")
    state.mark_asked(question)
    return sess, get_string("hi", question)

MIN_HELPFUL_RATE = 0.90     # of turns, must beat the previous turn
MAX_REPEATS = 2             # identical-to-previous replies tolerated overall
MIN_SELECTED_RATE = 0.50    # the model, not the fallback, must be choosing


def _text(payload) -> str:
    p = payload.get("prompt")
    if isinstance(p, dict):
        return (p.get("text") or "").strip()
    return (p or "").strip() if isinstance(p, str) else ""


def run():
    # If this is classic, every number below is meaningless — the selector is
    # not even in the call path. Fail loudly rather than reporting a green run.
    from core import coverage
    assert coverage.mode_for("hi") == "agentic", (
        f"hi resolves to {coverage.mode_for('hi')!r}, not agentic — the pinned "
        "voice recipe or audio coverage is wrong, so the selector is not running")

    rows, latencies, corrupted = [], [], []
    total = helpful = repeated = dead = selected = 0

    for question, utterances in NON_ANSWERS.items():
        q_total = q_helpful = q_repeat = q_dead = q_sel = q_corrupt = 0
        for utt in utterances:
            # The last thing Sakhi actually said is the baseline this turn has
            # to improve on. Repeating it is the exact failure we keep hitting.
            sess, before = reach(question)
            sel_before = sess.selected_turns

            t0 = time.perf_counter()
            reply = agentic.handle_turn(sess, utt)
            latencies.append((time.perf_counter() - t0) * 1000)

            after = _text(reply)
            q_total += 1
            if not after:
                q_dead += 1
            elif before and after == before:
                q_repeat += 1
            else:
                q_helpful += 1
            if sess.selected_turns > sel_before:
                q_sel += 1
            # THE invariant: a non-answer must never become the answer. A filled
            # slot is never re-asked, so anything stored here ships in the
            # profile forever — "district: I don't know the district".
            slot = sess.slot_state.slots[question]
            if slot.status == "filled":
                q_corrupt += 1
                corrupted.append((question, utt, slot.value))

        rows.append((question, q_total, q_helpful, q_repeat, q_dead, q_sel, q_corrupt))
        total += q_total; helpful += q_helpful
        repeated += q_repeat; dead += q_dead; selected += q_sel

    # ------------------------------------------------------------------ table
    print(f"\nFUZZ — RESPONSE SELECTION ({total} real-speech non-answers)\n")
    print(f"  {'question':<14}{'n':>4}{'more helpful':>14}{'repeated':>10}"
          f"{'dead':>6}{'model-chose':>13}{'CORRUPTED':>11}")
    print("  " + "-" * 72)
    for q, n, h, r, d, sel_n, c in rows:
        print(f"  {q:<14}{n:>4}{h:>10} {h/n*100:>3.0f}%{r:>10}{d:>6}"
              f"{sel_n:>9} {sel_n/n*100:>3.0f}%{c:>11}")
    print("  " + "-" * 72)
    print(f"  {'TOTAL':<14}{total:>4}{helpful:>10} {helpful/total*100:>3.0f}%"
          f"{repeated:>10}{dead:>6}{selected:>9} {selected/total*100:>3.0f}%"
          f"{len(corrupted):>11}")
    if corrupted:
        print("\n  slots filled from a NON-ANSWER (these ship in the profile):")
        for q, utt, val in corrupted:
            print(f"    {q}: {utt!r} -> {val!r}")
    print(f"\n  p50 turn latency {statistics.median(latencies):.0f} ms")

    # ------------------------------------------------------------------ gates
    assert not corrupted, (
        f"{len(corrupted)} non-answer(s) were stored as real slot values. A "
        "filled slot is never re-asked, so this corruption is permanent and "
        "user-visible — it is worse than any wording problem below.")
    assert dead == 0, f"{dead} turn(s) produced NO speech — silence is never an answer"
    assert repeated <= MAX_REPEATS, (
        f"{repeated} turn(s) repeated the previous sentence verbatim "
        f"(max {MAX_REPEATS}) — this is the failure the selector exists to fix")
    rate = helpful / total
    assert rate >= MIN_HELPFUL_RATE, (
        f"only {rate*100:.0f}% of non-answers produced a more helpful turn "
        f"(floor {MIN_HELPFUL_RATE*100:.0f}%)")
    sel_rate = selected / total
    assert sel_rate >= MIN_SELECTED_RATE, (
        f"the model chose the response on only {sel_rate*100:.0f}% of turns "
        f"(floor {MIN_SELECTED_RATE*100:.0f}%). Selection is falling back to "
        "deterministic routing — check that speech_plan still parses.")

    assert_all_reads_pinned()
    print("\nFUZZ SELECTION PASSED")


if __name__ == "__main__":
    run()
