# Sakhi Avatar & Voice Layer

## v1.1 (SHIPPED 2026-07-28): Ultimate Polish — gold-master voice + product hardening

**The locked voice recipe** (part of the cache hash — change any knob and clips re-key):
Tara (`PId0lEbL3SOYkQZSraml`) · `eleven_v4` · stability **0.75** (picked by ear from an
s65-vs-s75 A/B; seed pinning and `previous_text` conditioning are NOT supported on v4,
so consistency comes from **human-curated takes**) · similarity 0.80 · style 0.15 · speed 0.97.
Hindi is a **gold master**: 3–4 takes per line (4 for the anchors intro/for_whom/photo/review),
winner hand-picked per line via `samples/review_hi.html`, promoted + loudnormed. The other
8 languages run single takes on the locked recipe (spot-checked; takes treatment on request).

**Loudness**: every clip −16 LUFS ±1 LU, true peaks ≤ −1.6 dBTP (`scripts/loudnorm_cache.py`,
idempotent — run after any regeneration). Diagnosis note: the original "heavy vs smooth"
complaint measured as only 4.1 LU spread with zero ±2.5 LU outliers — it was prosodic
take-variance, not loudness; takes-curation was the actual fix.

**Script v3** (the trim): intro lost its self-explanation, enumerations compressed,
one `!` per language (in `done`), theatrical em-dashes → commas. Load-bearing kept:
full-year dob examples, complete enum lists, skip words. Hindi core session
**61 s → 51.9 s** of audio (all languages −1.7 to −11.6 s). Three new lines per
language: `age_invalid`, `almost_done`, `skip_ack`.

**Composite prompts** ship as `audio_urls` of cached base lines played back-to-back —
the server never synthesizes concatenations, so runtime ElevenLabs stays at zero
even for clarify/age-gate/skip/milestone/thanks turns.

**Product hardening (all verified in tests/test_state_machine.py::hardening)**:
18+ age gate (parse-time + confirm backstop) · caste/income skips with `skip_ack` ·
30-min session TTL + resume (`GET /api/session/{id}/resume` + localStorage chip) ·
mic pre-flight on the language screen · comprehension chips · tap-to-skip speech ·
`almost_done` milestone · `?demo=1` overlay with live cost from `parser: mock|gemini`
tags (`R` = reset) · static mock-feed bridge on the done screen · per-question funnel
metrics in profile JSON + `/api/stats`.

**Parser fast path**: curated-keyword answers (enums, digit dates/incomes) parse
locally in ~13 ms; only free-text (name/district/caste) hits Gemini (~1 s). Ambiguity
always falls through to Gemini. Answer round-trips: **p50 ~20 ms** per language.

**Avatar**: idle = static portrait + imperceptible CSS breathing (scale ≤1.006, 5 s),
voice raises amplitude to ≤1.015, no bob. The palindrome loop lives behind
`AVATAR_IDLE_MODE=video` (default `static`). Director kit: `docs/demo_kit.md`.

---

## v1 (2026-07-28, superseded above where noted): audio-reactive avatar + human voice + warm cache

**The pivot (2026-07-28):** the fal.ai lipsync path was parked before any clip was
generated (account balance blocker + cost). v1 instead ships the idle-loop video
(she breathes/blinks) with an **audio-reactive speaking animation** driven by the
real voice waveform. All 9 languages live immediately, zero video cost. The
lipsync machinery stays dormant behind its kill switch as the v2 upgrade path.

### The voice (and the bug that made it sound "machine-like")

The original complaint — "the voice sounds robotic" — was diagnosed to a silent
fallback: the ElevenLabs key belongs to the **India data-residency stack**, and
calls to the global `api.elevenlabs.io` returned 401 forever. Users only ever
heard browser `speechSynthesis`. Fix: `ELEVENLABS_BASE_URL` in `.env`
(`https://api.in.residency.elevenlabs.io`).

Locked voice, picked by ear from a 36-sample A/B lab (`scripts/voice_lab.py`):

- Voice: **Tara – Love Story & Romance Narrator** (`PId0lEbL3SOYkQZSraml`)
- Model: **eleven_v4** (all 9 languages; IN stack)
- Profile: **steady** — stability 0.65, similarity 0.80, style 0.15, speed 0.97
- All five knobs + model are part of the TTS cache hash (`core/cachekey.py`) —
  changing any of them regenerates cleanly.

### The cache — runtime makes ZERO ElevenLabs calls

`scripts/warm_tts_cache.py` pre-generates every line × language (162 mp3s,
8,669 chars, one-time). `synthesize()` then serves from disk (measured 0.13 ms
vs 1,881 ms cold). Verified: full scripted sessions in all 9 languages with zero
ElevenLabs network calls. Changing a line in `questions.py` orphans its mp3 —
re-run the warmer (`--dry-run` first; skip-existing is default).

### Audio-reactive speaking animation (static/js/app.js)

- One `AudioContext` → per-element `MediaElementAudioSourceNode` (created ONCE
  per element via WeakMap — re-tapping an element throws) → shared `AnalyserNode`.
- Per animation frame: smoothed level `l = raw*0.7 + prev*0.3` drives three layers:
  ring intensity (container opacity), idle-video breathing (scale ≤1.025 +
  ≤2 px bob), and a gold radial glow (`#B8954A`) behind the circle.
- Browser-TTS fallback (no analyser): gentle fixed-rhythm pulse — zero-key mode
  still feels alive. `prefers-reduced-motion`: static rings only.
- Autoplay policy: `audioContext.resume()` fires on the language-tile tap.
  iOS Safari caveat: `webkitAudioContext` fallback is wired but untested on
  device; idle video uses `playsinline muted autoplay` which iOS allows.

### Latency (measured, scripted 10-question Hindi sessions)

| Metric | Before | After |
|---|---|---|
| Answer round-trip p50 | ~1,001 ms | **751 ms** |
| Answer round-trip p95 | ~2,019 ms | **969 ms** |
| First answer after boot | ~1,664 ms | **713 ms** (startup warm-up parse) |
| Recognition-end → voice-start (est.) | ~1.1–2.1 s | **~0.78 s p50 / ~1.0 s p95** |
| Visible feedback after speech ends | ~1 s | **~0 ms** (thinking shimmer) |

How: dead 300 ms failed-TTS call removed (base-URL fix + warm cache);
`prefetch_audio_url` on every response (gender-auto-skip-aware next-question
peek in `core/session.py`) + hidden `preload="auto"` Audio in the frontend;
trimmed parser prompt (5/5 accuracy, p50 705 ms); shared keep-alive httpx client;
Gemini client warmed at boot. Note: `thinking_level=minimal` was tested and
REJECTED — slower (p50 814 ms) and one observed wrong parse; the model's default
with JSON mime type wins.

### Per-session marginal cost

| Component | Cost |
|---|---|
| ElevenLabs (runtime) | ₹0 — all cached |
| Avatar video | ₹0 — idle loop + animation |
| Gemini parsing (~10 calls, flash-lite) | ~₹0.10 |
| **Total** | **~₹0.10 / session** |

## v2 (DORMANT): pre-rendered lipsync clips

Everything is built and verified with dummy clips; no paid clip was ever
generated. To revive: fund the fal.ai account, then run the safety sequence in
`scripts/build_avatar_clips.py` (dry-run → 1-clip gate → batch with `--confirm`).
Clips share the TTS cache stem, so the current voice/settings hash names the
clips too. Runtime picks them up automatically (`video_url` payloads + frontend
clip layer are live but inert while `data/avatar_cache/` is empty).
`AVATAR_ENABLED=false` kills the video layer outright.

Also on the v2 list: barge-in, server-side STT, voice-activity detection.

## Cost log

| Date | Item | Spend |
|------|------|-------|
| 2026-07-28 | fal.ai (all attempts — balance blocked before generation) | $0 |
| 2026-07-28 | ElevenLabs probes (2×17 chars) | 34 credits |
| 2026-07-28 | Voice lab: 36 samples | 3,612 credits |
| 2026-07-28 | Full cache warm (v2 voice): 162 lines × 9 langs | 8,693 credits |
| 2026-07-28 | Polish: capability probe + recipe test | 459 credits |
| 2026-07-28 | Polish: accidental window generation (7 lines) | ~405 credits |
| 2026-07-28 | Polish: Hindi takes (67 files) | 3,143 credits |
| 2026-07-28 | Polish: 8-language rollout (168 files) | 7,633 credits |
| | **Total ElevenLabs, all missions** | **~23,979 credits (chars)** |
