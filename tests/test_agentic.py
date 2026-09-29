"""
Phase 1 — slot-filling state machine tests (agentic mode).

Covers: multi-slot capture, no re-asking, gender inference (offered, never
assumed), ambiguous-name refusal, silent state derivation, sensitive skips,
the 18+ gate, sensitive-last priority, and the cost invariant that a clean
cooperative turn makes ZERO LLM calls.

Run:  python3 tests/test_agentic.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from config_pin import pin, assert_all_reads_pinned

# Pin every knob this suite touches so the result cannot drift with .env.
pin(
    CONVERSATION_MODE="agentic",       # engage the branch under test
    BARGE_IN_ENABLED=True,
    VAD_ENDPOINTING_ENABLED=False,     # flagged-off feature must not alter results
    STT_ENDPOINT_SILENCE_MS=800,
    T3_CHAR_BUDGET_PER_SESSION=0,
    ACK_RATE=1.0,                      # deterministic: an ack every earned turn
    THINK_TIME_MS_RANGE="0-0",         # no pacing jitter inside assertions
    THINK_TIME_MS_RANGE_DEEP="0-0",
    TURN_GAP_MS_RANGE="0-0",
    # The voice recipe decides every cache hash. Without pinning it, assertions
    # like "the daughter variant has cached audio" depend on the developer's
    # .env rather than on the shipped clips.
    ELEVENLABS_API_KEY="",             # never spend credits
    ELEVENLABS_VOICE_ID="PId0lEbL3SOYkQZSraml",
    ELEVENLABS_MODEL="eleven_v4",
    ELEVENLABS_STABILITY=0.75,
    ELEVENLABS_SIMILARITY=0.80,
    ELEVENLABS_STYLE=0.15,
    ELEVENLABS_SPEED=0.97,
    SOFT_OPENER_RATE=0.0,
    AVATAR_ENABLED=False,
    AVATAR_IDLE_MODE="static",
)

from core import agentic                        # noqa: E402
from core import session as sm                  # noqa: E402
from core.extractor import Extraction, SlotUpdate  # noqa: E402
from core.slots import SLOT_PRIORITY, SlotState  # noqa: E402


def new_session(lang="hi"):
    sess, _intro, _q = sm.start(lang)
    assert sess.slot_state is not None, "agentic session must carry slot state"
    return sess


def fake_extraction(monkey_updates, *, intent="answer_other_slots", gender=None,
                    used_llm=True, is_skip=False):
    """Bypass the network: feed the turn handler a validated extraction."""
    return Extraction(
        intent=intent,
        updates=[SlotUpdate(*u) if not isinstance(u, SlotUpdate) else u
                 for u in monkey_updates],
        gender_guess=gender, used_llm=used_llm, is_skip=is_skip,
    )


def patch_extract(result):
    agentic.extract = lambda *a, **k: result


# ---------------------------------------------------------------- the tests
def test_priority_order():
    st = SlotState()
    assert SLOT_PRIORITY[-2:] == ["caste", "income"], "sensitive questions must be last"
    assert st.next_slot() == "for_whom"
    print("  ok  priority: identity -> basics -> background -> sensitive last")


def test_multi_slot_capture():
    """'मैं राहुल हूं, पुणे से, अट्ठाइस साल का' fills 3 slots, confirms once,
    and never re-asks any of them."""
    sess = new_session()
    patch_extract(fake_extraction([
        ("full_name", "Rahul Sharma", "Rahul Sharma", 0.95),
        ("district", "Pune", "Pune", 0.93),
        ("dob", "1998-01-01", "1998", 0.6),
    ]))
    out = agentic.handle_turn(sess, "मैं राहुल शर्मा हूं, पुणे से, अट्ठाइस साल का")
    st = sess.slot_state

    assert len(out["accepted_all"]) == 3, out
    assert st["full_name"].known and st["district"].known and st["dob"].known
    plan = out["prompt"]["speech_plan"]
    assert plan[0] == {"tier": "T2", "key": "batch_confirm"}, plan
    # next question must be something still empty — never one of the three
    assert out["prompt"]["key"] not in ("full_name", "district", "dob")
    assert st.derived.get("state") == "Maharashtra", "district -> state derived silently"
    print(f"  ok  multi-slot: 3 slots in one breath, batched confirm, next={out['prompt']['key']}")


def test_gender_inferred_but_never_assumed():
    sess = new_session()
    sess.slot_state.fill("full_name", "Rahul Sharma", "Rahul Sharma")
    patch_extract(fake_extraction([], gender=("male", 0.95)))
    out = agentic.handle_turn(sess, "राहुल शर्मा")
    st = sess.slot_state
    assert st["gender"].status == "needs_confirmation", st["gender"]
    assert st["gender"].source == "inferred"
    assert out["prompt"]["speech_plan"][-1]["key"] == "confirm_gender_male", out["prompt"]
    # user confirms -> becomes trusted
    out2 = agentic.handle_turn(sess, "हाँ, सही है")
    assert st["gender"].status == "filled" and st["gender"].source == "confirmed"
    print("  ok  gender: inferred -> confirmation asked -> only then filled")


def test_gender_confirmation_rejected():
    sess = new_session()
    sess.slot_state.fill("full_name", "Rahul", "Rahul")
    sess.slot_state.offer_gender_inference("male", 0.95, "Rahul")
    agentic.handle_turn(sess, "नहीं")
    assert sess.slot_state["gender"].status == "empty", "a 'no' must clear the guess"
    print("  ok  gender: rejected inference clears the slot, asks properly")


def test_ambiguous_name_not_inferred():
    st = SlotState()
    st.fill("full_name", "Kiran Patil", "Kiran Patil")
    assert st.offer_gender_inference("female", 0.99, "Kiran Patil") is False
    assert st["gender"].status == "empty"
    print("  ok  ambiguous name (Kiran) -> no inference, question asked normally")


def test_low_confidence_not_inferred():
    st = SlotState()
    assert st.offer_gender_inference("male", 0.6, "Rahul") is False
    print("  ok  low-confidence inference refused (<0.85)")


def test_for_whom_autoskip_preserved():
    st = SlotState()
    st.fill("for_whom", "son", "Son")
    assert st["gender"].value == "male" and st["gender"].source == "derived"
    assert st.next_slot() == "full_name", "gender must be skipped, not asked"
    print("  ok  classic rule preserved: son/daughter -> gender auto-skipped")


def test_age_gate():
    sess = new_session()
    patch_extract(fake_extraction([("dob", "2012-08-15", "15 Aug 2012", 0.95)]))
    out = agentic.handle_turn(sess, "15 अगस्त 2012")
    assert out.get("age_gate") is True
    assert sess.slot_state["dob"].status == "empty", "underage dob must never be stored"
    assert out["prompt"]["speech_plan"][0]["key"] == "age_invalid"
    print("  ok  18+ gate fires; underage dob not stored")


def test_sensitive_skip():
    sess = new_session()
    for k, v, d in [("for_whom", "self", "Self"), ("full_name", "Rahul", "Rahul"),
                    ("gender", "male", "Male"), ("dob", "1995-08-15", "15 Aug 1995"),
                    ("district", "Pune", "Pune"), ("religion", "Hindu", "Hindu"),
                    ("marital", "never_married", "Never married"),
                    ("qualification", "12th", "12th"), ("job", "farming", "Farming")]:
        sess.slot_state.fill(k, v, d)
    assert sess.slot_state.next_slot() == "caste", "caste is asked second-last"
    patch_extract(Extraction(is_skip=True, used_llm=False))
    out = agentic.handle_turn(sess, "स्किप")
    assert sess.slot_state["caste"].status == "skipped"
    assert out["prompt"]["speech_plan"][0]["key"] == "skip_ack"
    print("  ok  sensitive skip: caste -> skipped + skip_ack, moves on")


def test_no_llm_on_fast_path():
    """THE COST REGRESSION TEST: clean expected answers must never call the LLM."""
    import core.extractor as ex_mod
    agentic.extract = ex_mod.extract          # real router, real fast path
    calls = {"n": 0}
    ex_mod.llm_extract = lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("LLM called on a clean fast-path answer"))

    sess = new_session()
    for utterance in ["अपने बेटे के लिए"]:      # enum answer, 4 words
        out = agentic.handle_turn(sess, utterance)
        assert out["parser"] == "mock", out
    assert sess.llm_calls == 0, f"expected 0 LLM calls, got {sess.llm_calls}"
    print("  ok  fast path: clean answer -> 0 LLM calls (cost invariant holds)")


def test_profile_has_source_per_field():
    sess = new_session()
    st = sess.slot_state
    st.fill("for_whom", "self", "Self")
    st.fill("full_name", "Rahul", "Rahul")
    st.fill("dob", "1995-08-15", "15 Aug 1995")
    st.fill("district", "Nagpur", "Nagpur")
    for k, v, d in [("gender", "male", "Male"), ("religion", "Hindu", "Hindu"),
                    ("marital", "never_married", "Never married"),
                    ("qualification", "12th", "12th"), ("job", "farming", "Farming")]:
        st.fill(k, v, d)
    st.skip("caste")
    st.skip("income")
    sess.stage = "review"
    done = sm.confirm(sess)
    import json
    prof = json.loads((settings.PROFILES_DIR / done["profile_file"]).read_text())
    assert all("source" in f for f in prof["fields"].values()), prof["fields"]
    assert prof["metrics"]["mode"] == "agentic"
    assert prof["metrics"]["derived"].get("state") == "Maharashtra"
    assert sorted(prof["skipped"]) == ["caste", "income"]
    assert prof["metrics"]["capture_sources"], "source summary must be recorded"
    print(f"  ok  profile: source per field, derived state, capture_sources="
          f"{prof['metrics']['capture_sources']}")


if __name__ == "__main__":
    print("AGENTIC PHASE 1 — slot-filling state machine")
    test_priority_order()
    test_multi_slot_capture()
    test_gender_inferred_but_never_assumed()
    test_gender_confirmation_rejected()
    test_ambiguous_name_not_inferred()
    test_low_confidence_not_inferred()
    test_for_whom_autoskip_preserved()
    test_age_gate()
    test_sensitive_skip()
    test_no_llm_on_fast_path()
    test_profile_has_source_per_field()
    print("ALL AGENTIC PHASE 1 TESTS PASSED")


def test_rejected_inference_never_reoffered():
    """A guess the user corrected must not come back — that's a loop."""
    st = SlotState()
    st.fill("full_name", "Rahul", "Rahul")
    assert st.offer_gender_inference("male", 0.95, "Rahul") is True
    st.confirm("gender", False)                      # user says no
    assert st.offer_gender_inference("male", 0.99, "Rahul") is False
    assert st["gender"].status == "empty"
    print("  ok  rejected inference is never re-offered (no confirmation loop)")


test_rejected_inference_never_reoffered()


def test_llm_can_never_fill_gender_directly():
    """The model returning gender in the slots array must NOT fill it —
    it can only ever land as a confirmation. Hard guardrail."""
    sess = new_session()
    sess.slot_state.fill("full_name", "Rahul Sharma", "Rahul Sharma")
    patch_extract(fake_extraction([("gender", "male", "Male", 0.99)], used_llm=True))
    agentic.handle_turn(sess, "राहुल शर्मा, लड़का")
    st = sess.slot_state["gender"]
    assert st.status == "needs_confirmation", f"gender was silently filled: {st}"
    assert st.source == "inferred"
    print("  ok  guardrail: LLM-extracted gender routes to confirmation, never fills")


test_llm_can_never_fill_gender_directly()


# ============================== PHASE 2 ==============================
from core import dialogue, kb                      # noqa: E402


def test_plan_validator_drops_invented_keys():
    """Structural anti-hallucination: only curated keys survive."""
    plan = [
        {"tier": "T2", "key": "ack_ok"},                    # real
        {"tier": "T2", "key": "lokal_is_free_until_2027"},  # invented
        {"tier": "T1", "key": "district"},                  # real
        {"tier": "T3", "key": "anything"},                  # T3 never inline
        "just a sentence about Lokal pricing",              # not even a dict
        {"tier": "KB", "key": "kb_is_free"},                # real
        {"tier": "KB", "key": "kb_we_guarantee_marriage"},  # invented
    ]
    clean = dialogue.validate("hi", plan)
    assert clean == [{"tier": "T2", "key": "ack_ok"},
                     {"tier": "T1", "key": "district"},
                     {"tier": "KB", "key": "kb_is_free"}], clean
    print("  ok  plan validator: invented keys and free text dropped structurally")


def test_kb_answers_and_steers_back():
    sess = new_session()
    sess.slot_state.fill("for_whom", "self", "Self")
    patch_extract(fake_extraction([], intent="side_question"))
    out = agentic.handle_turn(sess, "ये फ्री है?")
    keys = [p["key"] for p in out["prompt"]["speech_plan"]]
    assert keys[0] == "kb_is_free" and keys[1] == "steer_back", keys
    assert out["kb_matched"] is True
    assert keys[-1] == out["prompt"]["key"], "must re-ask the question it interrupted"
    print(f"  ok  off-script: KB answer -> steer back -> re-asks {out['prompt']['key']}")


def test_kb_miss_is_graceful_and_logged():
    before = kb.gaps()["total"]
    sess = new_session()
    patch_extract(fake_extraction([], intent="side_question"))
    out = agentic.handle_turn(sess, "आपके ऑफिस में कितने लोग बैठते हैं?")
    keys = [p["key"] for p in out["prompt"]["speech_plan"]]
    assert keys[0] == "offscript_no_answer" and "steer_back" in keys, keys
    assert out["kb_matched"] is False
    after = kb.gaps()
    assert after["total"] == before + 1, "unmatched question must be logged"
    assert any("ऑफिस" in g["question"] for g in after["top_unanswered"])
    print(f"  ok  KB miss: graceful refusal + logged to kb_gaps.jsonl (total={after['total']})")


def test_llm_cannot_smuggle_a_kb_key():
    """A kb_key outside the registry is rejected -> falls back to 'I don't know'."""
    from core.extractor import Extraction as Ex
    agentic.extract = lambda *a, **k: Ex(intent="side_question", used_llm=True,
                                         kb_key="kb_lokal_pays_you_5000")
    sess = new_session()
    out = agentic.handle_turn(sess, "आपके ऑफिस में कितने लोग बैठते हैं?")
    keys = [p["key"] for p in out["prompt"]["speech_plan"]]
    assert keys[0] == "offscript_no_answer", keys
    print("  ok  guardrail: an out-of-registry KB key cannot be spoken")


def test_backchannel_does_not_answer():
    sess = new_session()
    patch_extract(fake_extraction([], intent="backchannel"))
    out = agentic.handle_turn(sess, "हाँ... हाँ")
    assert out.get("backchannel") is True
    assert sess.slot_state["for_whom"].status == "empty", "backchannel must not fill slots"
    print("  ok  backchannel: no slot touched, nothing new said")


def test_nonsense_escalates_calmly():
    sess = new_session()
    patch_extract(fake_extraction([], intent="abusive_or_nonsense"))
    out1 = agentic.handle_turn(sess, "बकवास")
    assert [p["key"] for p in out1["prompt"]["speech_plan"]][0] == "calm_redirect"
    assert not out1.get("text_fallback")
    out2 = agentic.handle_turn(sess, "बेकार बकवास")   # no clarification stem
    keys2 = [p["key"] for p in out2["prompt"]["speech_plan"]]
    assert "text_mode_offer" in keys2 and out2.get("text_fallback"), keys2
    print("  ok  nonsense: one calm redirect, then text mode. Never scolds.")


def test_meta_repeat_and_slow():
    sess = new_session()
    patch_extract(fake_extraction([], intent="meta"))
    out = agentic.handle_turn(sess, "ज़रा धीरे बोलिए")
    assert [p["key"] for p in out["prompt"]["speech_plan"]][0] == "meta_slow"
    out2 = agentic.handle_turn(sess, "पीछे चलिए")
    assert [p["key"] for p in out2["prompt"]["speech_plan"]][0] == "meta_back"
    # NOTE: "फिर से बोलिए" is deliberately NOT meta any more — it is a
    # clarify_current trigger, handled by the subject-aware escalating ladder.
    assert dialogue.is_clarification("फिर से बोलिए", "hi")
    print("  ok  meta: slow-down and go-back from cached fragments; repeat -> clarify ladder")


def test_spoken_age_never_becomes_dob():
    """DATA QUALITY: an age must never fabricate a birth date."""
    from core.extractor import _validate
    # the model tries to turn 28 years old into a date -> structurally rejected
    assert _validate("dob", "1998-01-01", "1998", 0.9, "अट्ठाइस साल का") is None
    # a real spoken date still passes
    assert _validate("dob", "1995-08-15", "15 Aug 1995", 0.95,
                     "पंद्रह अगस्त उन्नीस सौ पचानवे") is not None

    sess = new_session()
    # put the flow right before dob so the nudge is observable
    sess.slot_state.fill("for_whom", "self", "Self")
    sess.slot_state.fill("full_name", "Rahul", "Rahul")
    sess.slot_state.fill("gender", "male", "Male")
    assert sess.slot_state.next_slot() == "dob"
    agentic.extract = lambda *a, **k: Extraction(
        intent="answer_other_slots", age_years=28, used_llm=True)
    out = agentic.handle_turn(sess, "अट्ठाइस साल का हूं")
    st = sess.slot_state
    assert st["dob"].status == "empty", "age must never fill dob"
    assert st.derived.get("age_approx") == 28, st.derived
    assert out["prompt"]["key"] == "dob", "dob is still asked properly"
    assert "need_full_dob" in [p["key"] for p in out["prompt"]["speech_plan"]]
    print("  ok  age->dob: age kept as age_approx, real date still asked (kundli-safe)")


def test_spoken_underage_gates_early():
    sess = new_session()
    agentic.extract = lambda *a, **k: Extraction(
        intent="answer_other_slots", age_years=15, used_llm=True)
    out = agentic.handle_turn(sess, "पंद्रह साल का हूं")
    assert out.get("age_gate") is True
    assert sess.slot_state["dob"].status == "empty"
    print("  ok  spoken age under 18 -> warm age_invalid, nothing stored")


test_plan_validator_drops_invented_keys()
test_kb_answers_and_steers_back()
test_kb_miss_is_graceful_and_logged()
test_llm_cannot_smuggle_a_kb_key()
test_backchannel_does_not_answer()
test_nonsense_escalates_calmly()
test_meta_repeat_and_slow()
test_spoken_age_never_becomes_dob()
test_spoken_underage_gates_early()
print("ALL AGENTIC PHASE 2 TESTS PASSED")


def test_kundli_is_product_scoped_never_explained():
    """SCOPE RULE: she says what Lokal does about kundli. She never explains
    astrology, never opines on compatibility."""
    banned = ["दोष का मतलब", "ग्रह", "शुभ", "अशुभ", "मंगल ग्रह", "उपाय", "पूजा",
              "compatible", "auspicious", "planet", "remedy", "will suit"]
    for lang in ("hi", "en"):
        ans = kb.text(lang, "kb_kundli")
        assert ans, "kb_kundli must exist"
        low = ans.lower()
        for b in banned:
            assert b.lower() not in low, f"kb_kundli explains the world: {b!r} in {ans!r}"

    for q in ["मंगल दोष का क्या मतलब होता है?", "क्या हमारी कुंडली मिलेगी?",
              "क्या ये रिश्ता शुभ रहेगा?", "is she manglik compatible with me?"]:
        sess = new_session()
        patch_extract(fake_extraction([], intent="side_question"))
        out = agentic.handle_turn(sess, q)
        keys = [p["key"] for p in out["prompt"]["speech_plan"]]
        assert keys[0] in ("kb_kundli", "offscript_no_answer"), (q, keys)
        assert "steer_back" in keys, keys
    print("  ok  scope rule: kundli/compatibility -> product-scoped answer, never an explanation")


def test_every_factual_claim_is_registered():
    """Any KB entry asserting a product fact must be in the verification list —
    so nothing factual can be generated without a human signing off on it."""
    unregistered = []
    for key in kb.KB_KEYS:
        if key in kb.FACTUAL_CLAIMS:
            continue
        if key not in ("kb_are_you_real", "kb_who_are_you", "kb_dont_understand",
                       "kb_internet_slow", "kb_change_language"):
            unregistered.append(key)
    assert not unregistered, f"factual entries missing from FACTUAL_CLAIMS: {unregistered}"
    # deferral policy: the highest-risk privacy entry must not assert anything
    priv = kb.text("hi", "kb_who_sees_data")
    assert "किसी को नहीं दिखता" not in priv, "privacy answer must not promise invisibility"
    assert "पक्का नहीं" in priv, "unverifiable claims must defer, not assert"
    assert kb.FACTUAL_CLAIMS["kb_who_sees_data"][1] == "deferred"
    # invented engagement statistic must be gone
    assert "ज़्यादा लोग देखते" not in kb.text("hi", "kb_photo_required")
    # no long-term storage promise
    assert "सेव रहेगा" not in kb.text("hi", "kb_do_later")
    ans = kb.text("hi", "kb_is_free")
    # the free claim must be SCOPED to profile creation, and paid plans disclosed
    assert "प्रोफाइल बनाना" in ans, "the 'free' claim must be scoped to profile creation"
    assert "प्लान" in ans, "must disclose that contacting involves paid plans"
    assert kb.text("en", "kb_is_free").lower().count("free") == 1
    print(f"  ok  {len(kb.FACTUAL_CLAIMS)} factual claims registered for human verification")


test_kundli_is_product_scoped_never_explained()
test_every_factual_claim_is_registered()
print("ALL SCOPE / FACTUAL-CLAIM TESTS PASSED")


# ============================== PHASE 4 ==============================
def test_chunk_maps_are_sane():
    """Bad chunk maps make resume sound broken — every map must be either
    sentence-aligned or explicitly marked unsafe (whole-clip replay)."""
    import json as _json
    p = settings.DATA_DIR / "chunk_maps.json"
    assert p.exists(), "run scripts/build_chunk_maps.py"
    maps = _json.loads(p.read_text(encoding="utf-8"))
    multi = [m for m in maps.values() if len(m["chunks"]) > 1]
    assert multi, "expected multi-sentence lines"
    for m in maps.values():
        # chunks must tile the clip in order with no gaps or overlaps
        for i, c in enumerate(m["chunks"]):
            assert c["end"] > c["start"], (m["key"], c)
            if i:
                assert abs(c["start"] - m["chunks"][i-1]["end"]) < 1e-6, (m["key"], "gap")
        assert abs(m["chunks"][-1]["end"] - m["duration"]) < 0.01, (m["key"], "tail")
        # a resume-safe map must have one chunk per sentence
        if m["resume_safe"] and len(m["chunks"]) > 1:
            assert m["aligned"], m["key"]
    for anchor in ("intro", "for_whom", "photo", "review"):
        m = next(x for x in maps.values() if x["key"] == anchor and x["tier"] == "T1")
        assert m["aligned"] and m["resume_safe"], (anchor, m)
    unsafe = [m["key"] for m in multi if not m["resume_safe"]]
    print(f"  ok  chunk maps: {len(maps)} lines, {len(multi)} multi-sentence, "
          f"{len(unsafe)} fall back to whole-clip replay {unsafe}")


def test_barge_in_switch_is_independent():
    """A noisy demo room must kill barge-in without losing agentic.

    NB: this used to importlib.reload(config), which rebuilt Settings from the
    real .env and silently un-pinned every knob for every test after it. Assert
    on the resolution logic directly instead of rebuilding global state."""
    from config import Settings
    for mode in ("classic", "agentic"):
        for barge in (True, False):
            probe = Settings()
            probe.CONVERSATION_MODE = mode
            probe.BARGE_IN_ENABLED = barge
            assert probe.agentic == (mode == "agentic")
            assert probe.BARGE_IN_ENABLED is barge
    assert settings.CONVERSATION_MODE == "agentic", "pins must survive this test"
    print("  ok  BARGE_IN_ENABLED is independent of CONVERSATION_MODE (4/4 combos)")


def test_fragment_urls_are_cache_only():
    sess, _, _ = sm.start("hi")
    urls = sm.fragment_urls(sess, ["interrupt_ack", "bridge_resume", "does_not_exist"])
    assert "interrupt_ack" in urls and urls["interrupt_ack"].startswith("/audio/")
    assert "does_not_exist" not in urls, "unknown keys must be omitted, never synthesized"
    print(f"  ok  barge-in fragment URLs served from cache: {sorted(urls)}")


test_chunk_maps_are_sane()
test_barge_in_switch_is_independent()
test_fragment_urls_are_cache_only()
print("ALL PHASE 4 TESTS PASSED")


# ========================= CLARITY MISSION =========================
def test_subject_aware_questions():
    from core.questions import question_text
    assert question_text("hi", "full_name", "daughter") == "बेटी का पूरा नाम क्या है?"
    assert question_text("hi", "full_name", "son") == "बेटे का पूरा नाम क्या है?"
    assert question_text("hi", "full_name", "self") == "आपका पूरा नाम क्या है?"
    assert question_text("hi", "full_name", None) == "पूरा नाम क्या है?"   # classic neutral
    # verb agreement really differs (not a prefixed fragment)
    assert "करता है" in question_text("hi", "job", "son")
    assert "करती है" in question_text("hi", "job", "daughter")
    # gender-safe noun form for self/friend (no masculine "करते हैं")
    assert "करते हैं" not in question_text("hi", "job", "self")
    assert "करते हैं" not in question_text("hi", "job", "friend")
    # load-bearing content preserved in every variant
    for subj in ("self", "son", "daughter", "friend"):
        assert "पंद्रह अगस्त" in question_text("hi", "dob", subj)
        assert "दसवीं" in question_text("hi", "qualification", subj)
        assert "नौकरी" in question_text("hi", "job", subj)
    print("  ok  subject variants: agreement correct, examples + options preserved")


def test_daughter_session_uses_daughter_variants():
    sess = new_session()
    sess.slot_state.fill("for_whom", "daughter", "Daughter")
    out = agentic._ask_plan(sess, sess.slot_state, [])
    assert "बेटी" in out["text"], out["text"]
    assert out["audio_urls"], "daughter variant must have cached audio"
    print(f"  ok  daughter session asks: {out['text']}")


def test_clarification_is_not_a_failure():
    sess = new_session()
    sess.slot_state.fill("for_whom", "daughter", "Daughter")
    before_retries = sess.retries
    out = agentic.handle_turn(sess, "किसका नाम?")
    assert out["clarification"] == 1
    # Clarifications intentionally reach the model now (it picks the response);
    # what must never change is that they are not counted as failures.
    assert sess.retries == before_retries, "clarification must NOT count as a failure"
    assert "बेटी" in out["prompt"]["text"], out["prompt"]["text"]
    assert not out.get("text_fallback")
    print(f"  ok  1st clarification -> {out['prompt']['text']}")


def test_clarification_ladder_escalates():
    sess = new_session()
    sess.slot_state.fill("for_whom", "daughter", "Daughter")
    first = agentic.handle_turn(sess, "किसका नाम?")["prompt"]["text"]
    second = agentic.handle_turn(sess, "मतलब?")["prompt"]["text"]
    assert second != first, "2nd clarification must not repeat the same line"
    assert "सरनेम" in second, second      # the expansion explains the field
    third = agentic.handle_turn(sess, "समझ नहीं आया")
    assert third["text_fallback"], "3rd clarification offers the text box"
    assert third["clarification"] == 3
    assert sess.clarification_count["full_name"] == 3
    print(f"  ok  ladder: variant -> expansion -> text fallback (never loops)")


def test_language_aware_mode_fallback():
    from core import coverage
    assert coverage.supports_agentic("hi", refresh=True), "Hindi must support agentic"
    for lang in ("mr", "ta", "te", "kn", "ml", "bn", "gu"):
        assert not coverage.supports_agentic(lang, refresh=True), lang
    settings.CONVERSATION_MODE = "agentic"
    assert coverage.mode_for("hi") == "agentic"
    assert coverage.mode_for("mr") == "classic", "uncovered language must fall back"
    print(f"  ok  agentic languages = {coverage.agentic_languages()}; others run classic")


test_subject_aware_questions()
test_daughter_session_uses_daughter_variants()
test_clarification_is_not_a_failure()
test_clarification_ladder_escalates()
test_language_aware_mode_fallback()
print("ALL CLARITY MISSION TESTS PASSED")


# ===================== NATURALNESS GUARDRAIL TESTS =====================
import importlib.util as _ilu, pathlib as _pl
from core import naturalness as nat
from core import fragments as _frag                     # noqa: E402
from core.slots import SLOT_PRIORITY as _PRIORITY       # noqa: E402

DISCOURSE_MARKERS = ("अच्छा,", "ah,", "oh,", "okay,")


def test_reactions_echo_never_evaluate():
    """A reaction restates what was heard. It never praises — praise implies
    its opposite was available, which is judgement on a matrimony profile."""
    offenders = []
    for lang in ("hi", "en"):
        for key in set(nat.REACTION_TRIGGERS.values()):
            text = _frag.text(lang, key) or ""
            body = text
            for m in DISCOURSE_MARKERS:          # "अच्छा," means "I see", not "good"
                if body.lower().startswith(m):
                    body = body[len(m):]
            low = body.lower()
            for word in nat.EVALUATIVE_WORDS:
                if word.lower() in low:
                    offenders.append(f"{lang}/{key}: {word!r} in {text!r}")
    assert not offenders, "evaluative language in reactions:\n  " + "\n  ".join(offenders)
    print(f"  ok  {len(set(nat.REACTION_TRIGGERS.values()))} reactions echo, none evaluate")


def test_reactions_only_on_neutral_fields():
    fields = {f for f, _v in nat.REACTION_TRIGGERS}
    assert fields == {"job", "qualification"}, fields
    assert not (fields & nat.REACTION_FORBIDDEN_FIELDS)
    # values that must NOT be reacted to, because any remark reads as judgement
    for banned in (("job", "not_working"), ("job", "other"),
                   ("qualification", "below_10th")):
        assert banned not in nat.REACTION_TRIGGERS, banned
    for dropped in ("react_home", "react_district_known",
                    "react_higher_study", "react_schooling"):
        assert dropped not in _frag.FRAGMENTS["hi"], f"{dropped} should be gone"
    print("  ok  reactions restricted to job/qualification; circumstance values excluded")


def test_reaction_keys_all_exist():
    for key in set(nat.REACTION_TRIGGERS.values()):
        for lang in ("hi", "en"):
            assert _frag.exists(lang, key), f"{lang}/{key} missing"
    print("  ok  every reaction trigger resolves to a real fragment in hi and en")


def test_chains_are_adjacent_and_safe():
    """An earlier draft chained religion->caste and job->income; neither is
    consecutive in the live priority order, so the connective would have been
    spoken across a gap."""
    adjacent = {(_PRIORITY[i], _PRIORITY[i + 1]) for i in range(len(_PRIORITY) - 1)}
    adjacent.add(("full_name", "dob"))        # gender auto-skipped on son/daughter
    bad_gap, bad_target = [], []
    for (a, b), conn in nat.CHAINS.items():
        if (a, b) not in adjacent:
            bad_gap.append(f"{a}->{b}")
        if b in nat.CHAIN_FORBIDDEN_TARGETS:
            bad_target.append(f"{a}->{b}")
        assert _frag.exists("hi", conn), conn
    assert not bad_gap, f"non-adjacent chains: {bad_gap}"
    assert not bad_target, f"chains into a sensitive question: {bad_target}"
    # the two from the earlier draft must be gone
    assert ("religion", "caste") not in nat.CHAINS
    assert ("job", "income") not in nat.CHAINS
    print(f"  ok  {len(nat.CHAINS)} chains all adjacent; none lead into "
          f"{sorted(nat.CHAIN_FORBIDDEN_TARGETS)}")


test_reactions_echo_never_evaluate()
test_reactions_only_on_neutral_fields()
test_reaction_keys_all_exist()
test_chains_are_adjacent_and_safe()
print("ALL NATURALNESS GUARDRAIL TESTS PASSED")


# ================== CLARIFICATION ROUTING REGRESSION ==================
def test_clarification_recall_and_precision():
    """Live-observed misses. Every one of these fell through to `unclear` —
    i.e. was punished as a failed answer — before the stem rewrite."""
    SHOULD = ["किसका नाम बताऊं", "किसकी उम्र", "कौन सी वाली", "ये किसके बारे में है",
              "मैं समझी नहीं", "क्या पूछ रही हो", "दोबारा बोलो", "ज़रा फिर से",
              "कौन सा बताना है", "मतलब क्या", "समझ में नहीं आया", "किसका?",
              "समझ नहीं आ रहा"]
    SHOULD_NOT = ["मेरे बेटे का नाम राहुल", "नागपुर से", "बारहवीं पास",
                  "खेती करते हैं", "कभी शादी नहीं हुई", "तीन लाख के आसपास",
                  "हिंदू मराठा", "प्रिया शर्मा", "पंद्रह अगस्त उन्नीस सौ पचानवे",
                  "अपनी बेटी के लिए", "स्किप", "मास्टर्स किया है",
                  "is she manglik compatible with me?"]
    miss = [t for t in SHOULD if not dialogue.is_clarification(t, "hi")]
    fp = [t for t in SHOULD_NOT if dialogue.is_clarification(t, "hi")]
    assert not miss, f"clarifications not recognised: {miss}"
    assert not fp, f"real answers misread as clarifications: {fp}"
    # The near-miss net must not grab real ANSWERS. (A genuine question like
    # "is she manglik compatible with me?" SHOULD trip it — but it only ever
    # reaches the net if the extractor already failed, in which case
    # re-explaining the current question is the right degradation.)
    real_answers = [t for t in SHOULD_NOT if not t.endswith("?")]
    fp2 = [t for t in real_answers if dialogue.looks_like_question(t, "hi")]
    assert not fp2, f"near-miss net grabbed real answers: {fp2}"
    print(f"  ok  clarification routing: {len(SHOULD)}/{len(SHOULD)} recall, "
          f"0 false positives across {len(SHOULD_NOT)} real answers")


def test_near_miss_never_becomes_a_failure():
    """An unparseable but question-shaped turn goes to the ladder, and must NOT
    increment the retry counter that marches the user to the text fallback."""
    sess = new_session()
    sess.slot_state.fill("for_whom", "daughter", "Daughter")
    agentic.extract = lambda *a, **k: Extraction(intent="unclear", used_llm=True)
    before = sess.retries
    out = agentic.handle_turn(sess, "अरे ये कैसे बताएं")
    assert out.get("clarification") == 1, out
    assert sess.retries == before, "a question must never count as a failed answer"
    print("  ok  near-miss net: question-shaped miss -> ladder, retries untouched")


def test_reask_uses_subject_variant():
    """The unparseable re-ask must use the daughter variant, not the neutral clip."""
    sess = new_session()
    sess.slot_state.fill("for_whom", "daughter", "Daughter")
    agentic.extract = lambda *a, **k: Extraction(intent="unclear", used_llm=True)
    out = agentic.handle_turn(sess, "zzzz qqqq")     # no question shape at all
    assert not out.get("clarification"), "this one really is unparseable"
    assert "बेटी" in out["prompt"]["text"], out["prompt"]["text"]
    print(f"  ok  unparseable re-ask is subject-aware: {out['prompt']['text'][:52]}")


test_clarification_recall_and_precision()
test_near_miss_never_becomes_a_failure()
test_reask_uses_subject_variant()
print("ALL CLARIFICATION ROUTING TESTS PASSED")


def test_kb_identity_never_claims_humanity():
    """Constitution C1. A female-voiced agent WILL be asked "are you real?".
    The answer must be honest and warm — never coy, never implying humanity."""
    CLAIMS_HUMAN = [
        "मैं इंसान हूँ", "हाँ, असली", "मैं असली हूँ", "इंसान ही हूँ",
        "i am human", "i'm a real person", "yes, i am real", "i am a woman",
        "guess", "अंदाज़ा", "बताऊँ क्या",           # coyness is also banned
    ]
    for key in ("kb_are_you_real", "kb_who_are_you"):
        for lang in ("hi", "en"):
            ans = (kb.text(lang, key) or "").lower()
            assert ans, f"{lang}/{key} missing"
            for bad in CLAIMS_HUMAN:
                assert bad.lower() not in ans, f"{lang}/{key} may imply humanity: {bad!r}"
    # the direct question must actively disclose that she is not a person
    hi = kb.text("hi", "kb_are_you_real")
    en = kb.text("en", "kb_are_you_real").lower()
    assert "इंसान नहीं" in hi, f"must state plainly she is not human: {hi!r}"
    assert "not a real person" in en or "not a person" in en, en
    # and the routing actually reaches that answer
    for q in ["क्या तुम असली इंसान हो?", "are you a robot?", "तुम कौन हो?"]:
        sess = new_session()
        patch_extract(fake_extraction([], intent="side_question"))
        out = agentic.handle_turn(sess, q)
        keys = [p["key"] for p in out["prompt"]["speech_plan"]]
        assert keys[0] in ("kb_are_you_real", "kb_who_are_you", "offscript_no_answer"), (q, keys)
    print("  ok  C1: identity answers are honest, never claim or imply humanity")


test_kb_identity_never_claims_humanity()
assert_all_reads_pinned()
