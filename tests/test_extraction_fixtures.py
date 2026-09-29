"""
Extraction regression net. Any future prompt or spec edit must keep this green.

Costs ~23 Gemini calls (~Rs 0.5). Run before and after touching agent/SAKHI.md.
  python3 tests/test_extraction_fixtures.py
"""
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))

from config_pin import pin, assert_all_reads_pinned, declare_unpinned   # noqa: E402

pin(CONVERSATION_MODE="agentic", PARSER_MODEL="gemini-3.5-flash-lite")
# This suite genuinely needs the real key — it measures live extraction.
declare_unpinned("GEMINI_API_KEY", reason="live model calls are the point of this suite")

from core.extractor import llm_extract       # noqa: E402
from core.slots import SlotState             # noqa: E402
from fixtures_extraction import FIXTURES     # noqa: E402

MIN_PASS_RATE = 0.90      # below this, a prompt edit has regressed accuracy
# An ABSOLUTE latency gate here tests Gemini's round-trip, not our code. It was
# set at 1000 ms when the network happened to be quick; on a slower day a 6-token
# "reply with a digit" prompt to the same model measures 1068 ms p50 — the gate
# fails with no code change at all, and the only way to pass is to wait for
# better weather. So the gate is now RELATIVE: measure the bare round-trip in the
# same run and assert that our prompt adds little on top. That is the thing we
# actually control and the thing a regression would show up in.
MAX_OVERHEAD_MS = 400     # our prompt's cost ABOVE the model's own floor
MAX_P50_MS = 2500         # absolute backstop: something is badly wrong


def _roundtrip_floor() -> float:
    """p50 of the smallest possible call to the same model, measured NOW. This
    is the network + model cost that nothing in our code can remove."""
    from config import settings
    from google import genai
    c = genai.Client(api_key=settings.GEMINI_API_KEY)
    lat = []
    for i in range(7):
        t0 = time.perf_counter()
        c.models.generate_content(model=settings.PARSER_MODEL,
                                  contents=f"Reply with the digit {i % 3}.")
        lat.append((time.perf_counter() - t0) * 1000)
    return statistics.median(lat)


def run():
    ok = total = 0
    lat, fails = [], []
    for f in FIXTURES:
        t0 = time.perf_counter()
        ex = llm_extract(f["text"], f["lang"], SlotState(), f["current"])
        lat.append((time.perf_counter() - t0) * 1000)
        got = {u.key: u.value for u in ex.updates}

        def check(cond, msg):
            nonlocal ok, total
            total += 1
            if cond:
                ok += 1
            else:
                fails.append(f"{f['id']}: {msg}")

        for k, v in f.get("expect", []):
            check(got.get(k) == v, f"{k} got {got.get(k)!r} want {v!r}")
        for k in f.get("forbid", []):
            check(k not in got, f"{k} should be absent, got {got.get(k)!r}")
        if f.get("age_years") is not None:
            check(ex.age_years == f["age_years"],
                  f"age_years {ex.age_years} want {f['age_years']}")
        if f.get("no_gender_guess"):
            check(not ex.gender_guess,
                  f"inferred gender from an ambiguous name: {ex.gender_guess}")
        if f.get("intent"):
            check(ex.intent == f["intent"], f"intent {ex.intent!r} want {f['intent']!r}")
    return ok, total, lat, fails


if __name__ == "__main__":
    print(f"EXTRACTION FIXTURES ({len(FIXTURES)} utterances)")
    ok, total, lat, fails = run()
    rate = ok / total
    p50 = statistics.median(lat)
    for x in fails:
        print("  FAIL", x)
    print(f"  {ok}/{total} assertions ({rate*100:.0f}%)  p50 {p50:.0f} ms")
    assert rate >= MIN_PASS_RATE, f"accuracy {rate*100:.0f}% below {MIN_PASS_RATE*100:.0f}%"
    floor = _roundtrip_floor()
    overhead = p50 - floor
    print(f"  model round-trip floor {floor:.0f} ms → our prompt adds {overhead:+.0f} ms")
    assert p50 <= MAX_P50_MS, f"dialogue path p50 {p50:.0f} ms exceeds {MAX_P50_MS} ms"
    assert overhead <= MAX_OVERHEAD_MS, (
        f"our prompt adds {overhead:.0f} ms over the {floor:.0f} ms model floor "
        f"(budget {MAX_OVERHEAD_MS} ms) — the prompt or the menu has grown")
    assert_all_reads_pinned()
    print("EXTRACTION FIXTURES PASSED")
