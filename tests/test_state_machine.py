"""Offline state-machine test: drives a full Hindi and a full English session
through core.session + core.parser with all API keys blanked (mock parser,
no TTS, no avatar) and asserts the flow reaches 'done' with correct fields.

Run:  python3 tests/test_state_machine.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from config_pin import pin, assert_all_reads_pinned

# EVERY behaviour knob this suite touches is pinned here. A result that depends
# on someone's local .env is not a guarantee — see config_pin.py.
pin(
    CONVERSATION_MODE="classic",   # this is the CLASSIC regression suite
    ELEVENLABS_API_KEY="",         # never spend credits
    ELEVENLABS_VOICE_ID="",
    GEMINI_API_KEY="",             # mock parser, deterministic
    AVATAR_ENABLED=False,
)

from core import session as sm            # noqa: E402
from core.parser import parse_answer      # noqa: E402

ANSWERS = {
    "hi": {
        "for_whom": "अपने बेटे के लिए",
        "full_name": "मेरा नाम विरेंद्र पाटील है",
        # gender auto-skipped (for_whom = son)
        # mock parser handles digits + Indic month names (spelled-out number
        # words need Gemini mode)
        "dob": "१५ अगस्त १९९५",
        "district": "नागपुर",
        "religion": "हिंदू",
        "caste": "मराठा",
        "marital": "कभी नहीं",
        "qualification": "बारहवीं",
        "job": "खेती",
        "income": "25 हज़ार महीना",
    },
    "en": {
        "for_whom": "for myself",
        "full_name": "my name is Anita Sharma",
        "gender": "girl",
        "dob": "15 August 1995",
        "district": "Pune",
        "religion": "Hindu",
        "caste": "Maratha",
        "marital": "never married",
        "qualification": "graduation",
        "job": "private job",
        "income": "3 lakh per year",
    },
}


def drive(lang: str):
    sess, intro, first_q = sm.start(lang)
    assert intro["text"] and first_q["text"]
    assert intro["audio_url"] is None, "zero-key: no audio expected"
    assert "video_url" not in intro or intro["video_url"] is None

    steps = 0
    while sm.current_question(sess) not in (None, "photo"):
        key = sm.current_question(sess)
        answer = ANSWERS[lang].get(key)
        assert answer is not None, f"[{lang}] no scripted answer for {key}"
        result = parse_answer(key, answer, lang)
        assert result.confident, f"[{lang}] mock parser unsure on {key}: {answer!r}"
        sm.accept_answer(sess, key, result.value, result.display)
        steps += 1
        assert steps < 20, "flow did not terminate"

    assert sess.stage == "photo", f"[{lang}] expected photo stage, got {sess.stage}"

    # dob parsed to ISO
    assert sess.fields["dob"]["value"] == "1995-08-15", sess.fields["dob"]

    if lang == "hi":
        # gender auto-fill from for_whom=son
        assert sess.fields["for_whom"]["value"] == "son"
        assert sess.fields["gender"]["value"] == "male"
        assert sess.fields["income"]["value"] == "3L-5L"  # 25k/month -> 3L/yr

    # photo skip -> review (composite thanks path exercised on upload elsewhere)
    resp = sm.photo_done(sess, None)
    assert resp["stage"] == "review" and sess.stage == "review"
    assert len(resp["summary"]) == 11, f"expected 11 fields, got {len(resp['summary'])}"

    # clarify payload shape (composite line, no clips -> no video_urls)
    sess2, _, _ = sm.start(lang)
    c = sm.clarify(sess2)
    assert c["prompt"]["text"] and c["retries"] == 1
    assert "video_urls" not in c["prompt"]

    done = sm.confirm(sess)
    assert done["stage"] == "done" and done["profile_file"].endswith(".json")
    print(f"[{lang}] full session OK — {len(sess.fields)} fields, profile {done['profile_file']}")


if __name__ == "__main__":
    assert not settings.tts_enabled and not settings.parser_enabled
    assert not settings.avatar_enabled, "no clips on disk yet — avatar must report disabled"
    drive("hi")
    drive("en")
    assert_all_reads_pinned()
    print("ALL STATE-MACHINE TESTS PASSED")


def hardening():
    """Phase 4: age gate, sensitive skips, milestone, resume, funnel, TTL."""
    from fastapi.testclient import TestClient
    import main as mainmod
    from core.questions import S
    c = TestClient(mainmod.app)

    s = c.post("/api/session/start", json={"language": "hi"}).json()
    sid = s["session_id"]

    def answer(t):
        return c.post(f"/api/session/{sid}/answer", json={"transcript": t}).json()

    assert answer("अपने बेटे के लिए")["accepted"]["key"] == "for_whom"
    answer("विरेंद्र पाटील")

    # 18+ age gate: underage dob is rejected, not stored, re-asked warmly
    r = answer("15 August 2010")
    assert r.get("age_gate") is True, r
    assert S["hi"]["age_invalid"] in r["prompt"]["text"]
    r = answer("१५ अगस्त १९९५")
    assert r["accepted"]["key"] == "dob", r

    answer("नागपुर")
    answer("हिंदू")

    # caste skip -> null field, skip_ack prefix, moves on
    r = answer("skip")
    assert r["accepted"] == {"key": "caste", "display": "—", "skipped": True}
    assert S["hi"]["skip_ack"] in r["prompt"]["text"]

    answer("कभी नहीं")
    answer("बारहवीं")

    # milestone: income question arrives prefixed with almost_done
    r = answer("खेती")
    assert r["prompt"]["key"] == "income"
    assert S["hi"]["almost_done"] in r["prompt"]["text"]

    # resume mid-session lands on the exact question
    rr = c.get(f"/api/session/{sid}/resume").json()
    assert rr["stage"] == "asking" and rr["prompt"]["key"] == "income"

    # income skip too
    r = answer("बाद में")
    assert r["accepted"]["skipped"] and r["stage"] == "photo"

    c.post(f"/api/session/{sid}/skip-photo")
    done = c.post(f"/api/session/{sid}/confirm").json()
    assert done["stage"] == "done"

    import json as _json
    prof = _json.loads((settings.PROFILES_DIR / done["profile_file"]).read_text())
    assert sorted(prof["skipped"]) == ["caste", "income"]
    assert prof["metrics"]["clarifies"].get("dob") == 1
    assert "answer_seconds" in prof["metrics"]

    # underage confirm backstop
    s2 = c.post("/api/session/start", json={"language": "en"}).json()
    sid2 = s2["session_id"]
    assert c.post(f"/api/session/{sid2}/confirm").status_code == 400

    # funnel stats shape
    st = c.get("/api/stats").json()
    assert "per_question" in st and st["per_question"]["dob"]["clarify_rate"] > 0
    print("HARDENING TESTS PASSED (age gate, skips, milestone, resume, funnel, backstop)")


if __name__ == "__main__" and "--hardening-only" not in sys.argv:
    hardening()
