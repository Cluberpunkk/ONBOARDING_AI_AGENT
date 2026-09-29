# Sakhi (सखी) — Voice-First Profile Creation

A voice agent for Lokal Matrimony. The user picks a language, and **Sakhi — a warm female avatar — asks the profile questions out loud in that language.** The user answers by speaking. Two minutes later, the profile is done. No typing, no forms.

Built for the user who finds 11 screens of form-filling hard: low literacy, unfamiliar with keyboards in their script, or just tired. Which in Tier 2/3/4 India is most users.

**9 languages:** Hindi, English, Marathi, Tamil, Telugu, Kannada, Malayalam, Bengali, Gujarati.

---

## Quickstart (works with ZERO API keys)

```bash
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8010
# open http://127.0.0.1:8010 in CHROME (voice input needs Chrome)
```

With no keys configured, the app runs in **demo mode**:
- Voice OUT: browser's built-in speech synthesis (robotic but functional)
- Understanding: keyword matching (handles common phrasings)

Add your keys to `.env` (copy from `.env.example`) to unlock the real experience:
- **ElevenLabs** → beautiful natural voice in all 9 languages
- **Gemini** → robust understanding of any phrasing ("पच्चीस हज़ार महीना कमा लेता हूं" → income band 3L-5L)

## Setting up the ElevenLabs voice (5 minutes)

1. Go to [elevenlabs.io/app/voice-library](https://elevenlabs.io/app/voice-library)
2. Search **"Hindi female"** (or browse Indian voices). Pick a voice that sounds warm and didi-like — you want *trusted elder sister*, not *corporate IVR*.
3. Add it to your voices, open it, copy the **Voice ID**
4. Paste into `.env`:
   ```
   ELEVENLABS_API_KEY=sk_...
   ELEVENLABS_VOICE_ID=<the id>
   ELEVENLABS_MODEL=eleven_v3
   ```
5. Restart. First playback of each line generates + caches the mp3; every replay after that is free.

**Model note:** `eleven_v3` covers all 9 Indian languages. `eleven_multilingual_v2` only covers Hindi + Tamil + English — don't use it unless you're limiting languages.

**Credits math:** Every Sakhi line is a fixed string, disk-cached by content hash (`data/tts_cache/`). ~17 strings × 9 languages ≈ **150 clips total, ever**. Generated lazily on first use. Your credits are spent once, not per user.

## The photo edge case — solved by multimodal handoff

Voice can't upload a photo. So at the photo step, the interaction deliberately switches modes:

1. **Sakhi speaks the instruction:** *"आख़िरी काम — एक बढ़िया फोटो! नीचे कैमरा बटन दबाइए और गैलरी से फोटो चुन लीजिए। बाद में लगाना हो तो बस स्किप बोल दीजिए।"*
2. **The UI simultaneously shows** a big camera button + a "skip for now" link
3. **The mic stays open** — saying "स्किप" / "skip" / "बाद में" in any language works
4. After upload, Sakhi verbally appreciates the photo and moves to review

The principle: **voice guides, touch acts.** Voice is the narrator for the entire journey; touch handles the two things voice can't do (file pickers, final consent tap). The user never feels a mode break because Sakhi herself is the one telling them where to tap.

The same pattern handles the final submit: Sakhi asks them to *check the screen* and *tap the green button* — final consent stays a deliberate physical action, which matters for a profile that will be publicly visible.

## Conversation design decisions

- **Silent visual confirmation.** After each answer, the field fills into the progress state without Sakhi verbally repeating it ("आपने कहा राहुल, सही?" after every answer would double session length). Verbal recap happens once, at review.
- **Gender auto-skip.** If the profile is for a son/daughter, gender is inferred and never asked. One less question = 10% shorter conversation for the parent-creating-profile segment (a large share of matrimony profiles in Tier 2/3).
- **Graceful degradation ladder.** ElevenLabs down → browser voice. No mic / Safari → text input. 2 failed parses → text input appears under the mic. Silence twice → text input. The conversation *cannot* dead-end.
- **Bol-chaal register.** Every line is written the way a friendly didi actually talks, not formal register. "पढ़ाई कहाँ तक हुई है?" not "आपकी शैक्षणिक योग्यता क्या है?"
- **Fixed strings only.** No runtime-composed sentences. This keeps every line cacheable (credits!) and every line human-reviewed (no LLM composing awkward Telugu on the fly).

## Architecture

```
Browser (Chrome)                      FastAPI backend
┌─────────────────────┐              ┌──────────────────────────┐
│ Language grid        │──start────▶ │ session.py state machine │
│ Sakhi avatar + rings │             │  asking → photo → review │
│ Web Speech API (STT) │──transcript▶│ parser.py                │
│ <audio> ElevenLabs   │◀─mp3 url────│  Gemini │ keyword mock   │
│ speechSynthesis fbk  │             │ tts.py                   │
│ photo picker         │──file─────▶ │  ElevenLabs + sha1 cache │
│ review cards (edit)  │             │ profiles/*.json          │
└─────────────────────┘              └──────────────────────────┘
```

- **STT** runs in the browser (Web Speech API, `hi-IN`/`ta-IN`/... locales) — zero server cost, zero latency
- **Parsing** is server-side Gemini (structured JSON per question: enums enforced, monthly income annualized, dates → ISO, names transliterated)
- **TTS** is server-side ElevenLabs, cached to disk, served as static mp3

## API surface

| Endpoint | Purpose |
|---|---|
| `POST /api/session/start` | `{language}` → session + intro + Q1 (with audio URLs) |
| `POST /api/session/{id}/answer` | `{transcript}` → accepted + next prompt, or clarify |
| `POST /api/session/{id}/photo` | multipart upload → review stage |
| `POST /api/session/{id}/skip-photo` | skip → review stage |
| `POST /api/session/{id}/edit` | fix a field from the review screen |
| `POST /api/session/{id}/confirm` | write profile JSON, done |
| `GET /api/stats` | sessions started/completed by language |

## The avatar & voice (v1: audio-reactive, all 9 languages, ₹0 runtime)

Sakhi is a **living avatar**: an idle video loop (she breathes and blinks) plus an
**audio-reactive speaking animation** — the rings, a warm gold glow, and a subtle
breathing motion all pulse with the real voice waveform via a Web Audio analyser.
Her voice is ElevenLabs (`eleven_v4`, all 9 languages), **fully pre-cached** by
`scripts/warm_tts_cache.py`: runtime makes zero ElevenLabs calls, so per-session
marginal cost is just Gemini parsing (~₹0.10).

Latency is conversational: recognition-end → voice-start ≈ **0.8 s p50** (next
prompt's audio is prefetched while the user is still talking; a "सोच रही हूँ…"
shimmer acknowledges instantly).

**Data-residency gotcha:** if your ElevenLabs key is on a residency stack
(India/EU), set `ELEVENLABS_BASE_URL` in `.env` — the global URL silently 401s
and you'll only ever hear the robotic browser fallback.

**v2 (dormant): pre-rendered lipsync clips** via fal.ai — the entire pipeline is
built and verified (`scripts/build_avatar_clips.py`, `video_url` payloads, clip
layer with fallback ladder) but no clips have been generated. Safety sequence
when reviving: `--dry-run` → 1-clip gate → batch with `--confirm`.
`AVATAR_ENABLED=false` kills the video layer. Full design, latency numbers, and
cost log: [docs/avatar_layer.md](docs/avatar_layer.md).

The still fallback lives at `static/avatar/avatar.png`; the idle loop at
`static/avatar/idle_loop.mp4`. If both are absent, a built-in illustrated Sakhi face renders.

## Production roadmap (beyond this prototype)

1. **Server-side STT** (ElevenLabs Scribe / Sarvam) for non-Chrome browsers and better Indic accuracy
2. **Barge-in** — let the user interrupt Sakhi mid-question
3. **Voice activity detection** for natural end-of-utterance instead of browser silence timeout
4. **Multi-provider LLM fallback** for the parser (the Gemini 403 lesson)
5. **Session resume** — phone number keyed, survive app close
6. **Streaming TTS** for the dynamic lines if any are added later
7. **A/B against form path**: completion rate, time-to-profile, field accuracy, D7 retention of voice-created vs form-created profiles
