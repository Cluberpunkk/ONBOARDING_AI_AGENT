# KB factual claims — sign-off sheet

**Nothing in this table generates audio until its Verdict column is filled.**
Source of truth: the Saathi CS chatbot KB (internal Lokal policy).

How to fill the **Verdict** column:
- `approve` — the claim is accurate as written
- `correct-to: <text>` — the claim is wrong; here is the right Hindi wording
- `defer` — we can't state this; replace with a Help-section deferral

Policy in force (encoded in `core/kb.py`):
1. **Scope rule** — KB answers describe the product, never the world. No astrology,
   health, legal or religious interpretation.
2. **Deferral policy** — when a claim can't be verified, defer rather than assert.
   "ये मैं पक्का नहीं बता सकती" beats a confident wrong answer.

---

## Needs verdict (13 entries)

| # | Key | Hindi text (as it would be spoken) | The factual claim, in English | Verdict |
|---|-----|------------------------------------|-------------------------------|---------|
| 1 | `kb_is_free` | प्रोफाइल बनाना बिलकुल फ्री है। आगे किसी से बात करने के लिए कुछ प्लान होते हैं, वो आप बाद में देख लीजिएगा। | Creating a profile is free; contacting someone later requires a paid plan. | |
| 2 | `kb_how_long` | बस दो मिनट। कुछ ही सवाल बाकी हैं। | Profile creation takes about two minutes. | |
| 3 | `kb_photo_required` | फोटो ज़रूरी नहीं है। बाद में भी लगा सकते हैं। | The photo step is optional and can be completed later. | |
| 4 | `kb_can_edit_later` | हाँ, कभी भी बदल सकते हैं। प्रोफाइल बनने के बाद भी। | Any field can be edited at any time, including after the profile is created. | |
| 5 | `kb_why_caste_income` | ये सवाल सिर्फ़ सही रिश्ते दिखाने के लिए हैं। नहीं बताना चाहें तो स्किप बोल दीजिए। | Caste and income are collected to improve match relevance, and may be skipped. | |
| 6 | `kb_delete_profile` | प्रोफाइल कभी भी हटा सकते हैं — ऐप की सेटिंग में जाकर। | A user can delete their profile themselves from the app settings. | |
| 7 | `kb_after_profile` | प्रोफाइल बनते ही आपको आपके हिसाब से रिश्ते दिखने लगेंगे। | Matches personalised to the profile appear as soon as it is created. | |
| 8 | `kb_is_safe` | जी हाँ, सुरक्षित है। आपकी जानकारी सिर्फ़ रिश्ते ढूँढने के लिए इस्तेमाल होती है। | The user's details are used only for finding matches. | |
| 9 | `kb_family_use` | बिलकुल। घर के किसी भी सदस्य के लिए प्रोफाइल बना सकते हैं। | A user may create a profile on behalf of a family member. | |
| 10 | `kb_what_is_lokal` | लोकल आपके शहर और भाषा का ऐप है। ये उसी का शादी-ब्याह वाला हिस्सा है। | Lokal is a local-language city app; this is its matrimony section. | |
| 11 | `kb_do_later` | थोड़ी देर रुककर वहीं से चालू कर सकते हैं। ज़्यादा देर हो जाए तो फिर से शुरू करना पड़ेगा। | A paused session can be resumed shortly afterwards; after a longer gap it must be restarted (~30 min TTL). | |
| 12 | `kb_talk_to_human` | अभी मैं ही हूँ, पर ऐप में मदद वाले हिस्से से आप टीम को लिख सकते हैं। | Users can reach the team by writing from the app's Help section. | |
| 13 | `kb_kundli` | कुंडली मैं नहीं देख सकती। प्रोफाइल में जन्म की तारीख़ रहती है, बाकी बात आप दोनों परिवार आपस में तय कर लीजिएगा। | Lokal does not perform kundli/horoscope matching; the profile stores date of birth and families discuss it themselves. | |

---

## Already safe — no verdict needed (6 entries)

| Key | Hindi text | Why it's safe |
|-----|-----------|---------------|
| `kb_who_sees_data` | ये मैं पक्का नहीं बता सकती। ऐप के मदद वाले हिस्से में प्राइवेसी की पूरी जानकारी दी हुई है। | **deferred** — makes no claim, points to Help |
| `kb_are_you_real` | मैं सखी हूँ, लोकल की आवाज़ वाली मदद। असली इंसान नहीं, पर आपकी प्रोफाइल पूरी बनवा दूँगी। | self-descriptive (who Sakhi is) — no product claim |
| `kb_internet_slow` | थोड़ा इंटरनेट चाहिए। धीमा चले तो नीचे टाइप करके भी जवाब दे सकते हैं। | describes this flow's own text fallback |
| `kb_change_language` | हाँ, भाषा बदल सकते हैं। पेज दोबारा खोलकर अपनी भाषा चुन लीजिए। | describes this flow's own language picker |
| `kb_who_are_you` | मैं सखी हूँ। आपकी प्रोफाइल बनाने में मदद करती हूँ। | self-descriptive — no product claim |
| `kb_dont_understand` | कोई बात नहीं, मैं आसान शब्दों में फिर से पूछती हूँ। | conversational only — no product claim |

---

## Changes already applied from your review

| Key | Was | Now |
|-----|-----|-----|
| `kb_is_free` | "बिलकुल फ्री है" (flatly free) | free scoped to profile creation + paid plans disclosed |
| `kb_photo_required` | claimed photo profiles get seen more | invented statistic **deleted**; optional + add-later only |
| `kb_do_later` | "जो बना है वो सेव रहेगा" | matches the real 30-min TTL; no storage promise |
| `kb_who_sees_data` | "आपका नंबर किसी को नहीं दिखता" | **deferred** to Help section — never promises invisibility |
| `kb_kundli` | (did not exist) | added, product-scoped; explains nothing about astrology |

## Generation status

- **T2 fragments (42):** no factual claims → generated in this phase.
- **KB answers (19):** blocked. `core/kb.unverified_keys()` returns 13;
  generation is gated on this file being returned with every Verdict filled.

## v2 backlog item raised by this review

**Session persistence.** `kb_do_later` had to be weakened because sessions are
in-memory with a ~30-minute TTL. Durable server-side session storage (phone-keyed)
would let Sakhi honestly promise "जो बना है वो सेव रहेगा" and would recover
interrupted Tier 2/3 sessions hours later — a real completion-rate lever.
