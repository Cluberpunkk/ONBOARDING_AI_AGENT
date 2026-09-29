# Sakhi — Director Demo Kit

## Pre-demo checklist (run 15 min before)

- [ ] `uvicorn main:app --port 8010` — server up
- [ ] `curl -s localhost:8010/api/healthz` → `"tts":"elevenlabs"`, `"parser":"gemini"`
- [ ] Open `http://127.0.0.1:8010/?demo=1` in **Chrome**, allow mic when the language screen asks
- [ ] Cache warm check: pick Hindi, first line must be **Tara's voice** (if robotic browser voice: STOP, check `.env` / cache)
- [ ] Press `R` (demo reset) → clean language grid
- [ ] Phone on silent, notifications off, volume ~70%
- [ ] **The understudy**: play the backup video file once to confirm it opens

> **Record the happy-path backup video the night before.** Live demos deserve an
> understudy. Do one clean Hindi run with QuickTime screen+audio recording and
> keep it one keystroke away.

## Run of show (5 minutes)

1. **Open on the language grid** (10 s) — "Nine languages, one warm didi. Tier 2/3
   users pick their own script." Tap **हिन्दी**.
2. **Let the intro breathe** (10 s) — point at the avatar: "She's alive but calm —
   the animation is driven by her actual voice waveform. No video API, zero cost."
3. **Answer the flow by voice** (2 min) — for whom: *"अपने बेटे के लिए"* (gender
   question silently skipped — call it out). Name, then dob: **say "15 अगस्त 2010"
   first** → the 18+ gate refuses warmly. Then the real date. District, religion.
4. **The skip moment** (20 s) — on caste (or income): say *"स्किप"* → "कोई बात नहीं…"
   and a "—" chip. "Income is the classic drop-off question. A graceful skip beats
   a lost user."
5. **Chips + milestone** (15 s) — sweep a finger across the chips row: "Visible
   proof she understood — no time wasted on verbal confirmation." Note "बस दो
   सवाल और।" before income.
6. **Photo + review + edit** (40 s) — tap camera, pick any photo; "वाह, बढ़िया फोटो।"
   On review: tap one field, edit it. "Voice guides, touch acts."
7. **Done → feed bridge** (20 s) — green button → "प्रोफाइल बन गई!" → tap the CTA →
   mock feed. "Onboarding hands the user straight into the personalized feed —
   this is where matching and mutual-interest start."
8. **The numbers moment** (30 s) — point at the `?demo=1` overlay:
   response ms, live session cost, questions n/12. Then the talking points below.
9. If time: press `R`, start Tamil, let the intro play — "same woman, nine languages."

## Talking points (memorize the numbers)

- **Latency**: "Most answers land in **under 50 ms** — enum answers parse locally,
  only free-text touches the LLM at ~1 s. Voice starts instantly because the next
  question's audio is prefetched while the user is still speaking."
- **Cost**: "**~₹0.10 per session** — Gemini parsing only. Voice is pre-rendered
  once (~₹0 marginal), avatar is CSS + waveform (₹0). The voice cache for all
  nine languages cost about **15k ElevenLabs characters, one time**."
- **Trust**: "18+ gate on date-of-birth, sensitive questions skippable, every
  question instrumented — attempts, clarify-rate, drop-point — in `/api/stats`."
- **Resilience ladder**: "No mic → text. LLM down → keyword parser. TTS missing →
  browser voice. The conversation cannot dead-end."

## Failure playbook

| Symptom | Move |
|---|---|
| Mic flaky mid-demo | Type the answer — text fallback is a feature, narrate it as one |
| Wifi dies | Keyword parser keeps enums working offline; or switch to the backup video |
| Voice sounds robotic | Cache/hash issue — switch to backup video, debug later |
| Anything else | `R` → restart flow; it's 2 minutes end-to-end |
