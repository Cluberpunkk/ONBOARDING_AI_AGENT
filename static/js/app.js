/* Sakhi — voice conversation loop
 * TTS: ElevenLabs mp3 from backend, else browser speechSynthesis fallback
 * STT: Web Speech API (Chrome) with per-language locale, else text input fallback
 */

const $ = (id) => document.getElementById(id);
const state = {
  lang: null,
  sttLocale: "en-IN",
  sessionId: null,
  currentPrompt: null,
  stage: "asking",
  listening: false,
  recog: null,
  audioEl: null,
};

const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

// ------------------------------------------------------- localized UI chrome
// Tier 2/3 rule: every button, hint and screen title in the user's language.
const UI_STRINGS = {
  hi: { speaking:"बोल रही हूँ...", listening:"सुन रही हूँ...", thinking:"सोच रही हूँ...", tapToSpeak:"बोलने के लिए टैप करें", choosePhoto:"फोटो चुनें", uploading:"अपलोड हो रहा है...", skipForNow:"अभी नहीं", typePlaceholder:"यहाँ लिखें...", send:"भेजें", reviewTitle:"अपनी जानकारी देख लीजिए", confirmBtn:"✓ प्रोफाइल बनाएँ", doneTitle:"प्रोफाइल बन गई!", doneSub:"लोकल में स्वागत है", resumeChip:"अधूरी प्रोफाइल मिली — जारी रखें?", resumeBtn:"जारी रखें", freshBtn:"नई शुरुआत", micDenied:"माइक नहीं मिला — आप लिखकर जवाब दे सकते हैं", tapHint:"👆 सखी को टैप करके आगे बढ़ें", sayOrTap:"\"स्किप\" बोलें या नीचे टैप करें", feedCta:"आपके लिए रिश्ते तैयार हैं →", feedTitle:"आपके लिए रिश्ते", feedSub:"प्रोफाइल के हिसाब से चुने गए" },
  en: { speaking:"Speaking...", listening:"Listening...", thinking:"Thinking...", tapToSpeak:"Tap to speak", choosePhoto:"Choose photo", uploading:"Uploading...", skipForNow:"Skip for now", typePlaceholder:"Type your answer...", send:"Send", reviewTitle:"Check your details", confirmBtn:"✓ Create profile", doneTitle:"Profile created!", doneSub:"Welcome to Lokal", resumeChip:"Unfinished profile found — continue?", resumeBtn:"Continue", freshBtn:"Start fresh", micDenied:"No mic — you can type instead", tapHint:"👆 Tap Sakhi to move ahead", sayOrTap:'Say "skip" or tap below', feedCta:"Matches ready for you →", feedTitle:"Matches for you", feedSub:"Picked for this profile" },
  mr: { speaking:"बोलत आहे...", listening:"ऐकत आहे...", thinking:"विचार करत आहे...", tapToSpeak:"बोलण्यासाठी टॅप करा", choosePhoto:"फोटो निवडा", uploading:"अपलोड होत आहे...", skipForNow:"आत्ता नाही", typePlaceholder:"इथे लिहा...", send:"पाठवा", reviewTitle:"तुमची माहिती बघा", confirmBtn:"✓ प्रोफाइल बनवा", doneTitle:"प्रोफाइल तयार!", doneSub:"लोकलमध्ये स्वागत", resumeChip:"अपूर्ण प्रोफाइल आहे — पुढे चालू ठेवायचं?", resumeBtn:"चालू ठेवा", freshBtn:"नव्याने सुरू करा", micDenied:"माइक नाही — तुम्ही लिहू शकता", tapHint:"👆 पुढे जाण्यासाठी सखीला टॅप करा", sayOrTap:"\"स्किप\" म्हणा किंवा खाली टॅप करा", feedCta:"तुमच्यासाठी स्थळं तयार →", feedTitle:"तुमच्यासाठी स्थळं", feedSub:"प्रोफाइलनुसार निवडलेली" },
  ta: { speaking:"பேசுகிறேன்...", listening:"கேட்கிறேன்...", thinking:"யோசிக்கிறேன்...", tapToSpeak:"பேச தட்டவும்", choosePhoto:"போட்டோ தேர்வு", uploading:"அப்லோட்...", skipForNow:"இப்போது வேண்டாம்", typePlaceholder:"இங்கே எழுதுங்கள்...", send:"அனுப்பு", reviewTitle:"விவரங்களை பாருங்கள்", confirmBtn:"✓ ப்ரொஃபைல் உருவாக்கு", doneTitle:"ப்ரொஃபைல் தயார்!", doneSub:"லோக்கலுக்கு வரவேற்பு", resumeChip:"முடிக்காத ப்ரொஃபைல் உள்ளது — தொடரலாமா?", resumeBtn:"தொடரவும்", freshBtn:"புதிதாக", micDenied:"மைக் இல்லை — எழுதலாம்", tapHint:"👆 சகியை தட்டி முன்னே செல்லுங்கள்", sayOrTap:"\"ஸ்கிப்\" சொல்லுங்கள் அல்லது கீழே தட்டவும்", feedCta:"உங்களுக்கான வரன்கள் தயார் →", feedTitle:"உங்களுக்கான வரன்கள்", feedSub:"ப்ரொஃபைல் படி தேர்வு" },
  te: { speaking:"మాట్లాడుతున్నాను...", listening:"వింటున్నాను...", thinking:"ఆలోచిస్తున్నాను...", tapToSpeak:"మాట్లాడటానికి నొక్కండి", choosePhoto:"ఫోటో ఎంచుకోండి", uploading:"అప్‌లోడ్...", skipForNow:"ఇప్పుడు కాదు", typePlaceholder:"ఇక్కడ రాయండి...", send:"పంపండి", reviewTitle:"మీ వివరాలు చూడండి", confirmBtn:"✓ ప్రొఫైల్ సృష్టించండి", doneTitle:"ప్రొఫైల్ సిద్ధం!", doneSub:"లోకల్‌కి స్వాగతం", resumeChip:"అసంపూర్ణ ప్రొఫైల్ ఉంది — కొనసాగించాలా?", resumeBtn:"కొనసాగించండి", freshBtn:"కొత్తగా", micDenied:"మైక్ లేదు — టైప్ చేయవచ్చు", tapHint:"👆 ముందుకు వెళ్ళడానికి సఖిని నొక్కండి", sayOrTap:"\"స్కిప్\" చెప్పండి లేదా కింద నొక్కండి", feedCta:"మీ కోసం సంబంధాలు సిద్ధం →", feedTitle:"మీ కోసం సంబంధాలు", feedSub:"ప్రొఫైల్ ప్రకారం ఎంపిక" },
  kn: { speaking:"ಮಾತನಾಡುತ್ತಿದ್ದೇನೆ...", listening:"ಕೇಳುತ್ತಿದ್ದೇನೆ...", thinking:"ಯೋಚಿಸುತ್ತಿದ್ದೇನೆ...", tapToSpeak:"ಮಾತನಾಡಲು ಟ್ಯಾಪ್ ಮಾಡಿ", choosePhoto:"ಫೋಟೋ ಆರಿಸಿ", uploading:"ಅಪ್‌ಲೋಡ್...", skipForNow:"ಈಗ ಬೇಡ", typePlaceholder:"ಇಲ್ಲಿ ಬರೆಯಿರಿ...", send:"ಕಳುಹಿಸಿ", reviewTitle:"ನಿಮ್ಮ ವಿವರ ನೋಡಿ", confirmBtn:"✓ ಪ್ರೊಫೈಲ್ ಮಾಡಿ", doneTitle:"ಪ್ರೊಫೈಲ್ ರೆಡಿ!", doneSub:"ಲೋಕಲ್‌ಗೆ ಸ್ವಾಗತ", resumeChip:"ಅಪೂರ್ಣ ಪ್ರೊಫೈಲ್ ಇದೆ — ಮುಂದುವರಿಸಬೇಕಾ?", resumeBtn:"ಮುಂದುವರಿಸಿ", freshBtn:"ಹೊಸದಾಗಿ", micDenied:"ಮೈಕ್ ಇಲ್ಲ — ಟೈಪ್ ಮಾಡಬಹುದು", tapHint:"👆 ಮುಂದೆ ಹೋಗಲು ಸಖಿಯನ್ನು ಟ್ಯಾಪ್ ಮಾಡಿ", sayOrTap:"\"ಸ್ಕಿಪ್\" ಹೇಳಿ ಅಥವಾ ಕೆಳಗೆ ಟ್ಯಾಪ್ ಮಾಡಿ", feedCta:"ನಿಮಗಾಗಿ ಸಂಬಂಧಗಳು ಸಿದ್ಧ →", feedTitle:"ನಿಮಗಾಗಿ ಸಂಬಂಧಗಳು", feedSub:"ಪ್ರೊಫೈಲ್ ಪ್ರಕಾರ ಆಯ್ಕೆ" },
  ml: { speaking:"സംസാരിക്കുന്നു...", listening:"കേൾക്കുന്നു...", thinking:"ആലോചിക്കുന്നു...", tapToSpeak:"സംസാരിക്കാൻ ടാപ്പ് ചെയ്യൂ", choosePhoto:"ഫോട്ടോ തിരഞ്ഞെടുക്കൂ", uploading:"അപ്‌ലോഡ്...", skipForNow:"ഇപ്പോൾ വേണ്ട", typePlaceholder:"ഇവിടെ എഴുതൂ...", send:"അയയ്ക്കൂ", reviewTitle:"വിവരങ്ങൾ നോക്കൂ", confirmBtn:"✓ പ്രൊഫൈൽ ഉണ്ടാക്കൂ", doneTitle:"പ്രൊഫൈൽ റെഡി!", doneSub:"ലോക്കലിലേക്ക് സ്വാഗതം", resumeChip:"പൂർത്തിയാകാത്ത പ്രൊഫൈൽ ഉണ്ട് — തുടരണോ?", resumeBtn:"തുടരൂ", freshBtn:"പുതുതായി", micDenied:"മൈക്ക് ഇല്ല — ടൈപ്പ് ചെയ്യാം", tapHint:"👆 മുന്നോട്ട് പോകാൻ സഖിയെ ടാപ്പ് ചെയ്യൂ", sayOrTap:"\"സ്കിപ്പ്\" പറയൂ അല്ലെങ്കിൽ താഴെ ടാപ്പ് ചെയ്യൂ", feedCta:"നിങ്ങൾക്കായി ആലോചനകൾ തയ്യാർ →", feedTitle:"നിങ്ങൾക്കായി ആലോചനകൾ", feedSub:"പ്രൊഫൈൽ അനുസരിച്ച്" },
  bn: { speaking:"বলছি...", listening:"শুনছি...", thinking:"ভাবছি...", tapToSpeak:"বলতে ট্যাপ করুন", choosePhoto:"ছবি বাছুন", uploading:"আপলোড...", skipForNow:"এখন নয়", typePlaceholder:"এখানে লিখুন...", send:"পাঠান", reviewTitle:"আপনার তথ্য দেখুন", confirmBtn:"✓ প্রোফাইল বানান", doneTitle:"প্রোফাইল তৈরি!", doneSub:"লোকালে স্বাগতম", resumeChip:"অসম্পূর্ণ প্রোফাইল আছে — চালিয়ে যাবেন?", resumeBtn:"চালিয়ে যান", freshBtn:"নতুন করে", micDenied:"মাইক নেই — লিখতে পারেন", tapHint:"👆 এগোতে সখীকে ট্যাপ করুন", sayOrTap:"\"স্কিপ\" বলুন বা নিচে ট্যাপ করুন", feedCta:"আপনার জন্য সম্বন্ধ তৈরি →", feedTitle:"আপনার জন্য সম্বন্ধ", feedSub:"প্রোফাইল অনুযায়ী বাছাই" },
  gu: { speaking:"બોલી રહી છું...", listening:"સાંભળી રહી છું...", thinking:"વિચારી રહી છું...", tapToSpeak:"બોલવા માટે ટૅપ કરો", choosePhoto:"ફોટો પસંદ કરો", uploading:"અપલોડ...", skipForNow:"હમણાં નહીં", typePlaceholder:"અહીં લખો...", send:"મોકલો", reviewTitle:"તમારી વિગતો જુઓ", confirmBtn:"✓ પ્રોફાઇલ બનાવો", doneTitle:"પ્રોફાઇલ તૈયાર!", doneSub:"લોકલમાં સ્વાગત", resumeChip:"અધૂરી પ્રોફાઇલ છે — ચાલુ રાખશો?", resumeBtn:"ચાલુ રાખો", freshBtn:"નવેસરથી", micDenied:"માઇક નથી — લખી શકો છો", tapHint:"👆 આગળ વધવા સખીને ટૅપ કરો", sayOrTap:"\"સ્કિપ\" કહો અથવા નીચે ટૅપ કરો", feedCta:"તમારા માટે સંબંધો તૈયાર →", feedTitle:"તમારા માટે સંબંધો", feedSub:"પ્રોફાઇલ પ્રમાણે પસંદ" },
};

function ui() { return UI_STRINGS[state.lang] || UI_STRINGS.en; }

function applyUI() {
  const u = ui();
  $("micHint").textContent = u.tapToSpeak;
  $("photoBtnLabel").textContent = u.choosePhoto;
  $("skipBtn").textContent = u.skipForNow;
  $("textAnswer").placeholder = u.typePlaceholder;
  $("textSend").textContent = u.send;
  $("reviewTitle").textContent = u.reviewTitle;
  $("confirmBtn").textContent = u.confirmBtn;
  $("doneTitle").textContent = u.doneTitle;
  document.querySelector(".done-sub").textContent = u.doneSub;
  $("feedCta").textContent = u.feedCta;
  $("feedTitle").textContent = u.feedTitle;
  $("feedSub").textContent = u.feedSub;
}

// ---------------------------------------------------------------- screens
function show(screenId) {
  document.querySelectorAll(".screen").forEach((s) => s.classList.remove("active"));
  $(screenId).classList.add("active");
}

// ---------------------------------------------------------------- language grid
const settings = { bargeIn: false, conversationMode: "classic",
                   vadEndpointing: false, sttSilenceMs: 800 };

async function initLanguages() {
  const res = await fetch("/api/languages");
  const data = await res.json();
  setIdleMode(data.idle_mode || "static");
  // Two independent switches: barge-in can be killed for a noisy demo room
  // without giving up agentic conversation, and vice versa.
  settings.bargeIn = !!data.barge_in;
  settings.conversationMode = data.conversation_mode || "classic";
  settings.vadEndpointing = !!data.vad_endpointing;
  settings.sttSilenceMs = data.stt_endpoint_silence_ms || 800;
  if (settings.bargeIn) {
    fetch("/api/chunk-maps").then((r) => r.json())
      .then((m) => { state.chunkMaps = m; }).catch(() => {});
  }
  const grid = $("langGrid");
  data.languages.forEach((l) => {
    const tile = document.createElement("button");
    tile.className = "lang-tile";
    tile.innerHTML = `<span class="lang-native">${l.name}</span><span class="lang-en">${l.en_name}</span>`;
    tile.onclick = () => startSession(l.code, l.stt);
    grid.appendChild(tile);
  });
}

// ---------------------------------------------------------------- session
async function startSession(lang, sttLocale) {
  // The language-tile tap is our user gesture — unlock audio for Chrome/iOS
  initAudioGraph();
  initBargeIn();
  timing.sessionStart = performance.now();          // mic stream for listening-while-speaking (no await)
  state.lang = lang;
  state.sttLocale = sttLocale;
  applyUI();
  clearChips();
  const res = await fetch("/api/session/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language: lang }),
  });
  const data = await res.json();
  state.sessionId = data.session_id;
  state.fragmentUrls = data.fragment_urls || {};
  localStorage.setItem("sakhi_sess", JSON.stringify({ sid: data.session_id, lang, locale: sttLocale }));
  show("screen-talk");
  prefetchAudio(data.prefetch_audio_url);
  if (state.micDenied) showTextFallback(true);

  // Intro, then first question (tap-to-skip affordance on the first Q only)
  await speak(data.intro);
  showTapHint();
  await askPrompt(data.first_question);
}

// ---------------------------------------------------------------- resume
async function checkResume() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem("sakhi_sess") || "null"); } catch (e) {}
  if (!saved || !saved.sid) return;
  const res = await fetch(`/api/session/${saved.sid}/resume`).catch(() => null);
  if (!res || !res.ok) { localStorage.removeItem("sakhi_sess"); return; }
  const data = await res.json();
  const u = UI_STRINGS[saved.lang] || UI_STRINGS.en;
  $("resumeText").textContent = u.resumeChip;
  $("resumeYes").textContent = u.resumeBtn;
  $("resumeNo").textContent = u.freshBtn;
  $("resumeBar").classList.add("active");
  $("resumeYes").onclick = () => { $("resumeBar").classList.remove("active"); resumeSession(saved, data); };
  $("resumeNo").onclick = () => { $("resumeBar").classList.remove("active"); localStorage.removeItem("sakhi_sess"); };
}

async function resumeSession(saved, data) {
  initAudioGraph();
  state.lang = saved.lang;
  state.sttLocale = data.stt_locale || saved.locale;
  state.sessionId = data.session_id;
  applyUI();
  clearChips();
  (data.summary || []).forEach((f) => addChip(f.display));
  setProgress(data.progress);
  if (data.stage === "review") {
    state.stage = "review";
    renderReview(data.summary);
    show("screen-review");
    await speak(data.prompt);
    return;
  }
  show("screen-talk");
  if (state.micDenied) showTextFallback(true);
  if (data.stage === "photo") {
    state.stage = "photo";
    await speak(data.prompt);
    $("photoPanel").classList.add("active");
    $("micHint").textContent = ui().sayOrTap;
    startListening();
    return;
  }
  state.stage = "asking";
  await askPrompt(data.prompt);
}

// ---------------------------------------------------------------- mic pre-flight
async function micPreflight() {
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
    state.micDenied = !SR;
    return;
  }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((t) => t.stop());
    state.micDenied = false;
  } catch (e) {
    state.micDenied = true;
    const note = $("micNote");
    note.textContent = UI_STRINGS.hi.micDenied + " · " + UI_STRINGS.en.micDenied;
    note.classList.add("denied");
  }
}

// ---------------------------------------------------------------- chips
function clearChips() { $("chipsRow").innerHTML = ""; }
function addChip(text) {
  const c = document.createElement("span");
  c.className = "chip";
  c.textContent = `${text} ✓`;
  $("chipsRow").appendChild(c);
  $("chipsRow").scrollLeft = $("chipsRow").scrollWidth;
}

function showTapHint() {
  if (state.tapHintShown) return;
  state.tapHintShown = true;
  const el = $("tapHint");
  el.textContent = ui().tapHint;
  el.style.display = "block";
  setTimeout(() => { el.style.display = "none"; }, 8000);
}

function setProgress(p) {
  if (!p) return;
  $("progressFill").style.width = `${Math.round((p.done / p.total) * 100)}%`;
}

// ---------------------------------------------------------------- audio-reactive animation
// Voice waveform -> rings intensity + avatar breathing + gold glow.
// mp3 path: real analyser level. Browser-TTS path: gentle fixed rhythm.
const reducedMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let audioCtx = null, analyser = null, levelData = null;
const _sourceNodes = new WeakMap(); // audio element -> MediaElementSourceNode (create ONCE per element)

function initAudioGraph() {
  const AC = window.AudioContext || window.webkitAudioContext;
  if (!AC) return;
  if (!audioCtx) {
    audioCtx = new AC();
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.5;
    analyser.connect(audioCtx.destination);
    levelData = new Uint8Array(analyser.frequencyBinCount);
  }
  if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
}

function tapAnalyser(audioEl) {
  if (!audioCtx || !audioEl) return;
  try {
    if (!_sourceNodes.has(audioEl)) {
      const src = audioCtx.createMediaElementSource(audioEl);
      src.connect(analyser);
      _sourceNodes.set(audioEl, src);
    }
  } catch (e) { /* element already routed elsewhere — audio still plays */ }
}

let _animating = false, _level = 0;
function currentLevel() {
  if (analyser && state.audioEl && !state.audioEl.paused && _sourceNodes.has(state.audioEl)) {
    analyser.getByteFrequencyData(levelData);
    let sum = 0;
    for (let i = 0; i < levelData.length; i++) sum += levelData[i];
    return Math.min(1, (sum / (levelData.length * 255)) * 2.2);
  }
  // no analyser (browser TTS / clip layer): gentle fixed-rhythm pulse
  return 0.28 + 0.16 * Math.sin(performance.now() / 260);
}

// Idle mode: "static" = still portrait + imperceptible CSS breathing (default);
// "video" = legacy palindrome loop. The dormant lipsync clip layer is unaffected.
function setIdleMode(mode) {
  state.idleMode = mode;
  const idle = $("avatarIdle"), img = $("avatarImg");
  if (mode === "static") {
    if (idle) { idle.removeAttribute("src"); idle.load(); idle.style.display = "none"; }
    if (img && !reducedMotion) img.classList.add("breathe");
  } else if (img) {
    img.classList.remove("breathe");
  }
}

function applyLevel(l) {
  if (state.idleMode === "static") {
    // Breathing amplitude rises gently with the voice. Capped at 1.015, no bob.
    const img = $("avatarImg");
    if (img) {
      if (l > 0.001) {
        img.classList.remove("breathe");
        img.style.transform = `scale(${(1 + Math.min(l * 0.02, 0.015)).toFixed(4)})`;
      } else {
        img.style.transform = "";
        if (!reducedMotion) img.classList.add("breathe");
      }
    }
  } else {
    const idle = $("avatarIdle");
    if (idle) idle.style.transform = l > 0.001
      ? `scale(${(1 + l * 0.025).toFixed(4)}) translateY(${(-l * 2).toFixed(2)}px)`
      : "";
  }
  $("avatarGlow").style.opacity = (l * 0.9).toFixed(3);
  $("avatarRings").style.opacity = l > 0.001 ? (0.45 + l * 0.55).toFixed(3) : "";
}

function startVoiceAnim() {
  if (_animating || reducedMotion) return;
  _animating = true;
  const tick = () => {
    if (!_animating) return;
    _level = currentLevel() * 0.7 + _level * 0.3; // smoothing: organic, never jittery
    applyLevel(_level);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function stopVoiceAnim() {
  _animating = false;
  _level = 0;
  applyLevel(0);
}

// ------------------------------------------------- visual listening (Phase 4b)
// While the USER speaks, drive the same glow/breathing from the mic level, so
// she visibly attends instead of freezing. Cooler + softer than her speaking
// state so the two are never confused.
let _listenAnim = false, _listenLevel = 0;
function setListeningVisual(on) {
  const glow = $("avatarGlow");
  glow.classList.toggle("listening", on);
  $("avatarRings").classList.toggle("listening", on);
  if (on) startListenAnim(); else stopListenAnim();
}

function startListenAnim() {
  if (_listenAnim || reducedMotion || !bargeState.analyser) return;
  _listenAnim = true;
  const tick = () => {
    if (!_listenAnim) return;
    // same smoothing as her voice, but a gentler ceiling — attending, not talking
    const raw = Math.min(1, micEnergy() * 6);
    _listenLevel = raw * 0.6 + _listenLevel * 0.4;
    const l = _listenLevel * 0.7;
    const img = $("avatarImg");
    if (img && state.idleMode === "static") {
      img.classList.remove("breathe");
      img.style.transform = `scale(${(1 + Math.min(l * 0.012, 0.010)).toFixed(4)})`;
    }
    $("avatarGlow").style.opacity = (l * 0.75).toFixed(3);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
}

function stopListenAnim() {
  _listenAnim = false;
  _listenLevel = 0;
  $("avatarGlow").style.opacity = "0";
  const img = $("avatarImg");
  if (img && state.idleMode === "static") {
    img.style.transform = "";
    if (!reducedMotion) img.classList.add("breathe");
  }
}

// ---------------------------------------------------------------- prefetch + instant ack
// Warm the next prompt's mp3 while the user is still talking (deterministic order,
// backend accounts for the gender auto-skip). The browser HTTP cache serves it
// instantly when speak() plays the same URL.
function prefetchAudio(url) {
  if (!url) return;
  const a = new Audio(url);
  a.preload = "auto";
  state.prefetched = a;
}

// Perceived latency: flip to a "thinking" shimmer the instant recognition ends,
// before the network round-trip. Cleared when Sakhi starts (or stops) speaking.
function setThinking(on) {
  const el = $("avatarState");
  el.classList.toggle("thinking", on);
  if (on) el.textContent = "सोच रही हूँ...";
}

// ======================================================= BARGE-IN (rebuilt)
// SYMPTOM FIXED: she ignored real speech. The old probe ducked to 20% and
// called anything that dropped below 45% "echo" — but over laptop speakers her
// voice dominates the mic mix, so a genuine interruption also collapsed and was
// misclassified. Four changes:
//   1. duck far deeper (6%) and demand a much bigger collapse (<25%) for echo
//   2. absolute-energy override — a loud mic is a human regardless of ratio
//   3. noise floor FROZEN at pre-playback ambient, so her own voice can't
//      inflate the very threshold that is supposed to detect someone else
//   4. SEMANTIC CONFIRM — recognition runs while she speaks; if the words
//      coming back don't match the line she is playing, it is the user.
//      This works even when acoustic echo cancellation fails entirely.
const BARGE = {
  SELF_ONSET_MS: 400,      // her voice ramps in; ignore it
  SUSTAIN_MS: 120,         // was 300 — target duck <=150ms
  DUCK_VOLUME: 0.06,       // was 0.20 — deep duck makes echo unmistakable
  DUCK_MS: 40,             // was 100
  PROBE_MS: 150,
  ECHO_RATIO: 0.25,        // was 0.45 — must COLLAPSE to count as her own voice
  ABS_HUMAN_RMS: 0.075,    // absolute override: this loud is a person, period
  STOP_AFTER_MS: 400,      // was 500 — full stop budget
  FLOOR_ALPHA: 0.995,
  MARGIN: 2.2,
};

const bargeState = {
  enabled: false, stream: null, analyser: null, buf: null,
  floor: 0.01, frozenFloor: 0.01, raf: null, active: false,
  aec: null,               // what the browser says about echoCancellation
  lastDecision: "-",       // for the debug panel
};

async function initBargeIn() {
  if (!settings.bargeIn || !navigator.mediaDevices || !audioCtx) return;
  try {
    bargeState.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    // Does the browser actually have AEC on? If this is true and her voice
    // still reaches the mic, the leak is AEC suppression DEPTH, not routing.
    const track = bargeState.stream.getAudioTracks()[0];
    const st = track && track.getSettings ? track.getSettings() : {};
    bargeState.aec = st.echoCancellation;
    console.info("[sakhi] mic settings:", JSON.stringify({
      echoCancellation: st.echoCancellation, noiseSuppression: st.noiseSuppression,
      autoGainControl: st.autoGainControl, deviceId: st.deviceId ? "set" : "default",
    }));
    const src = audioCtx.createMediaStreamSource(bargeState.stream);
    const an = audioCtx.createAnalyser();
    an.fftSize = 512;
    an.smoothingTimeConstant = 0.2;
    src.connect(an);                       // analyser only — never to destination
    bargeState.analyser = an;
    bargeState.buf = new Uint8Array(an.fftSize);
    bargeState.enabled = true;
  } catch (e) {
    bargeState.enabled = false;            // denied/unsupported -> tap-to-skip only
    console.warn("[sakhi] barge-in unavailable:", e && e.name);
  }
}

function micEnergy() {
  const an = bargeState.analyser;
  if (!an) return 0;
  an.getByteTimeDomainData(bargeState.buf);
  let sum = 0;
  for (let i = 0; i < bargeState.buf.length; i++) {
    const v = (bargeState.buf[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / bargeState.buf.length);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------- semantic discriminator (monitor)
// A recognition instance runs WHILE she speaks. Whatever text comes back is
// either her own line echoing through the speakers, or the user talking over
// her. Comparing against the clip text tells the two apart reliably.
const monitor = { rec: null, text: "", clipText: "", running: false };

function normTokens(s) {
  return (s || "").toLowerCase().replace(/[।,.!?—\-]/g, " ").split(/\s+/).filter(Boolean);
}

function matchesHerLine(heard, clipText) {
  const h = normTokens(heard), c = new Set(normTokens(clipText));
  if (!h.length) return null;                       // nothing heard yet
  const hits = h.filter((w) => c.has(w)).length;
  return hits / h.length;                            // 1.0 = purely her words
}

function startMonitor(clipText) {
  if (!SR || !settings.bargeIn || monitor.running) return;
  try {
    const r = new SR();
    r.lang = state.sttLocale;
    r.interimResults = true;
    r.continuous = true;
    r.onresult = (e) => {
      let t = "";
      for (const res of e.results) t += res[0].transcript + " ";
      monitor.text = t;
    };
    r.onerror = () => {};
    r.onend = () => { monitor.running = false; };
    monitor.text = "";
    monitor.clipText = clipText || "";
    monitor.rec = r;
    monitor.running = true;
    r.start();
  } catch (e) { monitor.running = false; }
}

function stopMonitor() {
  if (monitor.rec) { try { monitor.rec.stop(); } catch (e) {} }
  monitor.rec = null; monitor.running = false;
  const t = monitor.text; monitor.text = "";
  return t;
}

// Returns true if the caller should STOP (real human speech).
async function duckProbe(audioEl) {
  const before = micEnergy();
  const original = audioEl ? audioEl.volume : 1;
  if (audioEl) audioEl.volume = BARGE.DUCK_VOLUME;      // duck deep, duck fast
  setThinkingHint(true);
  await sleep(BARGE.DUCK_MS);

  let peak = 0;
  const t0 = performance.now();
  while (performance.now() - t0 < BARGE.PROBE_MS) {
    peak = Math.max(peak, micEnergy());
    await sleep(15);
  }
  const ratio = before > 0 ? peak / before : 1;

  // 1) SEMANTIC CONFIRM — the reliable signal. If recognition heard words that
  //    are NOT in the line she is playing, a person is talking.
  const overlap = matchesHerLine(monitor.text, monitor.clipText);
  if (overlap !== null) {
    if (overlap < 0.5) {
      bargeState.lastDecision = `STOP semantic(overlap ${(overlap*100).toFixed(0)}%)`;
      if (audioEl) audioEl.volume = original;
      return true;
    }
    bargeState.lastDecision = `resume semantic(overlap ${(overlap*100).toFixed(0)}%)`;
    if (audioEl) audioEl.volume = original;
    setThinkingHint(false);
    return false;
  }

  // 2) ABSOLUTE OVERRIDE — this loud is a person whatever the ratio says.
  if (peak >= BARGE.ABS_HUMAN_RMS) {
    bargeState.lastDecision = `STOP absolute(${peak.toFixed(3)})`;
    if (audioEl) audioEl.volume = original;
    return true;
  }

  // 3) RATIO — only now, and only a real collapse counts as her own echo.
  if (ratio < BARGE.ECHO_RATIO) {
    bargeState.lastDecision = `resume echo(ratio ${ratio.toFixed(2)})`;
    if (audioEl) audioEl.volume = original;
    setThinkingHint(false);
    return false;
  }

  // Still loud and not her words: give it the rest of the stop budget.
  const spent = BARGE.DUCK_MS + BARGE.PROBE_MS;
  const t1 = performance.now();
  while (performance.now() - t1 < Math.max(0, BARGE.STOP_AFTER_MS - spent)) {
    if (micEnergy() < bargeState.frozenFloor * BARGE.MARGIN) {
      bargeState.lastDecision = `resume trailed-off(ratio ${ratio.toFixed(2)})`;
      if (audioEl) audioEl.volume = original;
      setThinkingHint(false);
      return false;
    }
    await sleep(20);
  }
  bargeState.lastDecision = `STOP sustained(ratio ${ratio.toFixed(2)})`;
  if (audioEl) audioEl.volume = original;
  return true;
}

function watchForBargeIn(audioEl, onBarge) {
  if (!bargeState.enabled || bargeState.active) return () => {};
  bargeState.active = true;
  // FREEZE the floor at pre-playback ambient. Letting it adapt while she speaks
  // was self-defeating: her own voice raised the bar for detecting anyone else.
  bargeState.frozenFloor = Math.max(0.004, bargeState.floor);
  const startedAt = performance.now();
  let aboveSince = 0, probing = false, stopped = false;

  const tick = async () => {
    if (stopped) return;
    const e = micEnergy();
    const past = performance.now() - startedAt > BARGE.SELF_ONSET_MS;
    const loud = e > bargeState.frozenFloor * BARGE.MARGIN;
    if (past && loud) {
      if (!aboveSince) aboveSince = performance.now();
      if (!probing && performance.now() - aboveSince > BARGE.SUSTAIN_MS) {
        probing = true;
        const shouldStop = await duckProbe(audioEl);
        probing = false;
        aboveSince = 0;
        if (shouldStop && !stopped) { stopped = true; onBarge(); return; }
      }
    } else if (!probing) {
      aboveSince = 0;
    }
    bargeState.raf = requestAnimationFrame(tick);
  };
  bargeState.raf = requestAnimationFrame(tick);

  return () => {
    stopped = true;
    bargeState.active = false;
    if (bargeState.raf) cancelAnimationFrame(bargeState.raf);
  };
}

// Ambient sampling while nothing is playing — this is what the frozen floor uses.
setInterval(() => {
  if (!bargeState.enabled || bargeState.active || state.listening) return;
  const e = micEnergy();
  bargeState.floor = Math.max(0.004,
    bargeState.floor * BARGE.FLOOR_ALPHA + e * (1 - BARGE.FLOOR_ALPHA));
}, 120);

function setThinkingHint(on) {
  $("avatarState").textContent = on ? ui().listening : ui().speaking;
}

// ---------------------------------------------------------------- speaking
// Tap-to-skip (barge-in lite): tapping the avatar while Sakhi speaks stops
// playback immediately and resolves the speak() Promise, so the mic opens.
function interruptSpeech() {
  const d = state.speakingDone;
  if (!d) return;
  try { if (state.audioEl) { state.audioEl.onended = null; state.audioEl.pause(); } } catch (e) {}
  try { if ("speechSynthesis" in window) speechSynthesis.cancel(); } catch (e) {}
  const clip = $("avatarClip");
  if (clip) { clip.onended = clip.onerror = null; clip.pause(); clip.classList.remove("active"); }
  $("tapHint").style.display = "none";
  d();
}
$("avatarCircle").addEventListener("click", interruptSpeech);

function setSpeaking(on) {
  setThinking(false);
  if (on) setListeningVisual(false);
  if (on) startVoiceAnim(); else stopVoiceAnim();
  $("avatarRings").classList.toggle("speaking", on);
  $("avatarState").textContent = on ? ui().speaking : "\u00a0";
}

function speak(prompt) {
  return new Promise(async (resolve) => {
    if (!prompt || !prompt.text) return resolve();
    $("questionBubble").textContent = prompt.text;

    // THINK TIME: a human doesn't answer in 13 ms. Delay her VOICE only —
    // the shimmer already fired the instant recognition ended, so the UI
    // never feels laggy. interrupt_ack and resumes are exempt (instant).
    const think = prompt.instant ? 0 : (state.nextThinkMs || 0);
    state.nextThinkMs = 0;
    if (think > 0) await sleep(think);

    setSpeaking(true);

    let finished = false;
    const done = () => {
      if (finished) return;   // idempotent: tap-to-skip + onended can both fire
      finished = true;
      state.speakingDone = null;
      setSpeaking(false);
      resolve();
    };
    state.speakingDone = done;

    // Fallback ladder: lipsync clip(s) -> cached mp3(s) -> browser TTS.
    // Composite lines arrive as video_urls / audio_urls, played back-to-back.
    const clips = prompt.video_urls || (prompt.video_url ? [prompt.video_url] : []);
    if (clips.length) playClips(clips, prompt, done);
    else if (prompt.audio_urls && prompt.audio_urls.length) speakAudioList(prompt.audio_urls, prompt, done);
    else speakAudio(prompt, done);
  });
}

function makeAudio(url, prompt, onEnd, done) {
  const a = new Audio(url);
  a.preload = "auto";
  tapAnalyser(a);
  state.audioEl = a;
  a.onended = onEnd;
  a.onerror = () => browserSpeak(prompt.text, done);

  // Sentence-level resume: if this is the clip we were cut off in, restart at
  // the START of that sentence, never mid-word.
  const seek = (state.resumeSeek && state.resumeSeek.url === url)
    ? state.resumeSeek.at : 0;
  if (seek > 0) {
    a.currentTime = seek;
    a.addEventListener("loadedmetadata", () => { try { a.currentTime = seek; } catch (e) {} }, { once: true });
  }
  state.resumeSeek = null;

  // Watch for a real human interrupting this clip. The monitor recognition
  // gives duckProbe the words it needs to tell her voice from the user's.
  startMonitor(prompt && prompt.text);
  const stopWatch = watchForBargeIn(a, () => {
    stopWatch();
    onBargeIn(a, url, prompt);
  });
  const wrapEnd = a.onended;
  a.onended = () => { stopWatch(); stopMonitor(); wrapEnd && wrapEnd(); };
  a.play().catch(() => browserSpeak(prompt.text, done));
}

// Cut off mid-sentence: remember exactly where, ack instantly, open the mic.
function onBargeIn(audioEl, url, prompt) {
  const at = audioEl.currentTime || 0;
  const map = state.chunkMaps && state.chunkMaps[stemOf(url)];
  let chunkStart = 0;
  if (map && map.resume_safe) {
    for (const c of map.chunks) {
      if (at >= c.start && at < c.end) { chunkStart = c.start; break; }
    }
  }
  state.interrupted = { url, at: chunkStart, key: prompt.key };
  state.nextThinkMs = 0;   // an interruption ack must be instant
  try { audioEl.pause(); } catch (e) {}
  // Instant proof she heard you — cached fragment, plays in ~0ms
  playFragment("interrupt_ack");
  // The monitor heard the interruption; don't make the user say it twice.
  const heard = stopMonitor();
  const overlap = matchesHerLine(heard, prompt && prompt.text);
  state.bargeTranscript = (overlap !== null && overlap < 0.5) ? heard.trim() : "";
  if (state.speakingDone) state.speakingDone();
}

function stemOf(url) {
  const m = /([0-9a-f]{20})\.mp3$/.exec(url || "");
  return m ? m[1] : "";
}

function playFragment(key) {
  const url = state.fragmentUrls && state.fragmentUrls[key];
  if (!url) return;
  try { new Audio(url).play().catch(() => {}); } catch (e) {}
}

// Backchannel: "हाँ… अच्छा… हम्म" while she talks is not an answer. Never sent
// to the server, never stops her — she keeps going.
const BACKCHANNEL = {
  hi: ["हाँ", "हां", "हूँ", "जी", "अच्छा", "ओके", "हम्म", "ठीक", "ok", "hmm", "haan"],
  en: ["yes", "yeah", "ok", "okay", "hmm", "mhm", "right", "sure", "uh huh"],
};
function isBackchannel(t) {
  const words = (t || "").toLowerCase().replace(/[।.,!?]/g, " ").split(/\s+/).filter(Boolean);
  if (!words.length || words.length > 3) return false;
  const list = (BACKCHANNEL[state.lang] || []).concat(BACKCHANNEL.en);
  return words.every((w) => list.includes(w));
}

function speakAudio(prompt, done) {
  if (prompt.audio_url) {
    // Cached ElevenLabs mp3, routed through the analyser for the reactive avatar
    makeAudio(prompt.audio_url, prompt, done, done);
  } else {
    browserSpeak(prompt.text, done);
  }
}

// Composite prompt: cached base clips back-to-back (the server never
// synthesizes concatenations — runtime TTS stays at zero)
function speakAudioList(urls, prompt, done) {
  let i = 0;
  const next = () => {
    if (i >= urls.length) return done();
    makeAudio(urls[i++], prompt, next, done);
  };
  next();
}

function playClips(clips, prompt, done) {
  const clip = $("avatarClip");
  let i = 0;
  const cleanup = () => {
    clip.classList.remove("active");
    clip.onended = clip.onerror = null;
    clip.removeAttribute("src");
    clip.load();
  };
  // Any video failure falls through to the audio path — never stall the flow
  const fail = () => { cleanup(); speakAudio(prompt, done); };
  const next = () => {
    if (i >= clips.length) { cleanup(); return done(); }
    clip.src = clips[i++];
    clip.onended = next;
    clip.onerror = fail;
    clip.classList.add("active");
    // Unmuted play is allowed: the language-tile tap already provided the gesture
    clip.play().catch(fail);
  };
  next();
}

// Idle loop: if the file is missing/corrupt, drop the layer so the still shows
const _idle = $("avatarIdle");
if (_idle) _idle.addEventListener("error", () => { _idle.style.display = "none"; });

// Known-female voice names across platforms. Sakhi is a woman; the browser's
// default for hi-IN on macOS is often a male English voice, which shatters the
// illusion. If we ever reach this path at all, at least sound like her.
const FEMALE_VOICE_HINTS = [
  "lekha", "kalpana", "veena", "rishi", "swara", "aditi", "heera", "priya",
  "female", "woman", "samantha", "victoria", "karen", "moira", "tessa", "fiona",
  "google हिन्दी", "google hindi", "microsoft swara", "microsoft heera",
  "microsoft kalpana", "sangeeta", "vani", "shruti", "neerja",
];
const MALE_VOICE_HINTS = ["male", "rishi ", "ravi", "hemant", "madhur", "prabhat", "daniel", "alex", "fred"];

function pickVoice(locale) {
  if (!("speechSynthesis" in window)) return null;
  const voices = speechSynthesis.getVoices() || [];
  if (!voices.length) return null;
  const lang2 = (locale || "en-IN").slice(0, 2).toLowerCase();
  const sameLang = voices.filter((v) => (v.lang || "").toLowerCase().startsWith(lang2));
  const score = (v) => {
    const n = (v.name || "").toLowerCase();
    if (MALE_VOICE_HINTS.some((m) => n.includes(m))) return -1;
    return FEMALE_VOICE_HINTS.some((f) => n.includes(f)) ? 2 : 1;
  };
  const pool = sameLang.length ? sameLang : voices;
  const ranked = pool.slice().sort((a, b) => score(b) - score(a));
  return score(ranked[0]) > 0 ? ranked[0] : (sameLang[0] || null);
}

function browserSpeak(text, cb, whyKey) {
  if (!("speechSynthesis" in window) || !text) return cb();
  // Reaching browser TTS at all is a cache miss — never let it be silent.
  console.warn("[sakhi] browser TTS fallback fired" +
               (whyKey ? ` for key "${whyKey}"` : "") +
               " — a cached clip is missing:", text.slice(0, 60));
  const u = new SpeechSynthesisUtterance(text);
  u.lang = state.sttLocale;
  u.rate = 0.95;
  const v = pickVoice(state.sttLocale);
  if (v) u.voice = v;
  u.onend = cb;
  u.onerror = cb;
  speechSynthesis.speak(u);
}
// Voice list loads async in Chrome; warm it so the first pick isn't empty.
if ("speechSynthesis" in window) {
  speechSynthesis.onvoiceschanged = () => { try { speechSynthesis.getVoices(); } catch (e) {} };
}

// ---------------------------------------------------------------- prompt cycle
async function askPrompt(prompt) {
  state.currentPrompt = prompt;
  $("transcript").textContent = "";
  await speak(prompt);
  if (state.stage === "photo") return; // photo panel handles the rest

  // TURN HANDOVER: don't snatch the mic open the instant she stops. Show the
  // listening indicator at the START of the gap so the user knows it's their
  // turn, then actually open the mic a beat later.
  // If a barge-in already captured what the user said, act on it immediately.
  if (state.bargeTranscript) {
    const t = state.bargeTranscript;
    state.bargeTranscript = "";
    $("transcript").textContent = t;
    setThinking(true);
    sendAnswer(t);
    return;
  }
  const gap = state.nextTurnGapMs || 0;
  state.nextTurnGapMs = 0;
  if (gap > 0) {
    $("avatarState").textContent = ui().listening;
    setListeningVisual(true);
    await sleep(gap);
  }
  startListening();
}

// ============================ TURN INSTRUMENTATION ============================
// Two numbers we could previously only model:
//   endpointing — how long after the user actually stops speaking Chrome takes
//                 to fire onend. Measured as the largest single per-turn cost.
//   wall clock  — language tile tap -> profile created.
const timing = {
  sessionStart: 0,
  endpointMs: [],        // per-turn endpointing waits
  turnStart: 0,
  lastVoiceAt: 0,        // last moment the mic heard speech this turn
};

function timingSummary() {
  const e = timing.endpointMs.slice().sort((a, b) => a - b);
  const p50 = e.length ? e[Math.floor(e.length / 2)] : 0;
  const total = e.reduce((a, b) => a + b, 0);
  return { turns: e.length, p50: Math.round(p50), totalSec: (total / 1000).toFixed(1),
           wallSec: timing.sessionStart ? ((performance.now() - timing.sessionStart) / 1000).toFixed(1) : "0" };
}

// ---------------------- VAD-assisted end-of-speech (flagged off) ------------
// Conservative BY DESIGN. Cutting a slow speaker off mid-sentence is far worse
// than a second of dead air, so: long silence requirement, never fire on an
// empty transcript, never fire when the transcript looks mid-utterance, and a
// longer allowance on questions where multi-fact answers are expected.
const CONTINUATION_WORDS = {
  hi: ["और", "से", "का", "की", "के", "में", "मैं", "पर", "को", "तक", "ने", "या",
       "फिर", "वाला", "वाली", "पे", "साथ", "लिए"],
  en: ["and", "of", "the", "a", "in", "to", "for", "with", "from", "at", "or", "but"],
};
// Questions that invite several facts in one breath get more room.
const LONG_ANSWER_KEYS = ["full_name", "district", "caste", "for_whom"];

function looksMidUtterance(text, lang) {
  const words = (text || "").trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return true;
  const last = words[words.length - 1].replace(/[।,.!?]/g, "");
  const list = (CONTINUATION_WORDS[lang] || []).concat(CONTINUATION_WORDS.en);
  return list.includes(last);
}

function endpointSilenceFor(key) {
  const base = settings.sttSilenceMs || 800;
  return LONG_ANSWER_KEYS.includes(key) ? Math.round(base * 1.6) : base;
}

// ---------------------------------------------------------------- listening
function startListening() {
  if (!SR || state.micDenied) {
    showTextFallback(true);
    $("micHint").textContent = ui().micDenied;
    return;
  }
  if (state.listening) return;

  const recog = new SR();
  recog.lang = state.sttLocale;
  recog.interimResults = true;
  recog.maxAlternatives = 1;
  state.recog = recog;
  state.listening = true;
  setListeningVisual(true);          // she visibly attends while you speak
  $("micBtn").classList.add("listening");
  $("avatarState").textContent = ui().listening;
  $("micHint").textContent = ui().listening;

  let finalText = "";
  let heardAnything = false;
  timing.turnStart = performance.now();
  timing.lastVoiceAt = 0;
  let endpointTimer = null;

  recog.onresult = (e) => {
    let interim = "";
    for (const r of e.results) {
      if (r.isFinal) finalText += r[0].transcript;
      else interim += r[0].transcript;
    }
    const shown = finalText || interim;
    $("transcript").textContent = shown;
    if (shown.trim()) { heardAnything = true; timing.lastVoiceAt = performance.now(); }
  };

  // VAD-assisted endpointing: stop recognition once the mic has been quiet long
  // enough AND the transcript looks like a finished thought. Falls back to
  // Chrome's own timeout whenever anything is missing.
  if (settings.vadEndpointing && bargeState.enabled) {
    const need = endpointSilenceFor(state.currentPrompt && state.currentPrompt.key);
    endpointTimer = setInterval(() => {
      if (!state.listening) return;
      const e = micEnergy();
      if (e > bargeState.floor * BARGE.MARGIN) { timing.lastVoiceAt = performance.now(); return; }
      if (!heardAnything || !timing.lastVoiceAt) return;         // never on an empty transcript
      const quietFor = performance.now() - timing.lastVoiceAt;
      if (quietFor < need) return;
      const shown = $("transcript").textContent;
      if (looksMidUtterance(shown, state.lang)) return;          // still forming a sentence
      clearInterval(endpointTimer); endpointTimer = null;
      try { recog.stop(); } catch (err) {}
    }, 100);
  }
  recog.onend = () => {
    if (endpointTimer) { clearInterval(endpointTimer); endpointTimer = null; }
    // THE MEASUREMENT: from the user's last detected speech to onend firing.
    if (timing.lastVoiceAt) timing.endpointMs.push(performance.now() - timing.lastVoiceAt);
    state.listening = false;
    setListeningVisual(false);
    $("micBtn").classList.remove("listening");
    $("micHint").textContent = "Tap to speak";
    if (finalText.trim()) {
      // Instant acknowledgment: transcript is frozen on screen; flip to the
      // thinking shimmer NOW, before the network round-trip.
      setThinking(true);
      sendAnswer(finalText.trim());
    } else {
      $("avatarState").textContent = "\u00a0";
      handleSilence();
    }
  };
  recog.onerror = () => { /* onend fires after */ };
  recog.start();
}

let silenceCount = 0;
async function handleSilence() {
  silenceCount++;
  if (silenceCount >= 2) { showTextFallback(true); return; }
  // BUGFIX: this used to call speechSynthesis with an EMPTY string and no
  // chosen voice, which is how a robotic male voice appeared mid-conversation.
  // The "silence" line is a real cached clip — play that instead.
  await speakSystemLine("silence");
  startListening();
}

// Play a cached system line by key (URLs handed over at session start).
function speakSystemLine(key) {
  return new Promise((resolve) => {
    const url = state.fragmentUrls && state.fragmentUrls[key];
    if (!url) {
      console.warn(`[sakhi] no cached clip for system key "${key}" — staying silent`);
      return resolve();     // silence beats a wrong-gender robot
    }
    const a = new Audio(url);
    tapAnalyser(a);
    state.audioEl = a;
    setSpeaking(true);
    const done = () => { setSpeaking(false); resolve(); };
    a.onended = done;
    a.onerror = done;
    a.play().catch(done);
  });
}

// ---------------------------------------------------------------- answers
async function sendAnswer(transcript) {
  // Backchannel during speech is not an answer — resume where she was cut off.
  if (isBackchannel(transcript) && state.interrupted) {
    resumeInterrupted();
    return;
  }
  silenceCount = 0;
  const t0 = performance.now();
  const res = await fetch(`/api/session/${state.sessionId}/answer`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ transcript }),
  });
  const data = await res.json();
  demoTurn(performance.now() - t0, data);
  await handleResponse(data);
}

// She was cut off but the interruption carried no answer -> pick up at the
// start of the sentence she was in, after a short cached bridge.
function resumeInterrupted() {
  const it = state.interrupted;
  state.interrupted = null;
  if (!it) { startListening(); return; }
  state.resumeSeek = { url: it.url, at: it.at };
  const prompt = { key: it.key, text: state.currentPrompt ? state.currentPrompt.text : "",
                   audio_urls: [state.fragmentUrls.bridge_resume, it.url].filter(Boolean) };
  if (!prompt.audio_urls.length) { startListening(); return; }
  askPrompt(prompt);
}

async function handleResponse(data) {
  setProgress(data.progress);
  prefetchAudio(data.prefetch_audio_url);
  // server-suggested pacing for this turn
  state.nextThinkMs = data.think_ms || 0;
  state.nextTurnGapMs = data.turn_gap_ms || 0;

  // If the interruption ALREADY answered the question, never resume it —
  // acknowledge and move on. This is the behaviour that reads as human.
  if (state.interrupted) {
    const captured = data.accepted || data.accepted_all;
    if (captured) state.interrupted = null;      // answered: drop the resume
    else if (data.side_question) state.interrupted = null;  // KB path re-asks itself
  }

  // Comprehension chip: silent visual proof she understood, the instant
  // an answer lands (skips show as "—")
  if (data.accepted && data.accepted.display) addChip(data.accepted.display);

  if (data.text_fallback) showTextFallback(true);

  if (data.stage === "photo" && data.prompt) {
    state.stage = "photo";
    await speak(data.prompt);
    $("photoPanel").classList.add("active");
    $("micHint").textContent = ui().sayOrTap;
    startListening(); // keep listening for "skip"
    return;
  }

  if (data.stage === "photo" && !data.prompt) {
    // Still awaiting upload/skip — keep listening
    startListening();
    return;
  }

  if (data.stage === "review") {
    state.stage = "review";
    $("photoPanel").classList.remove("active");
    stopListening();
    renderReview(data.summary);
    show("screen-review");
    await speak(data.prompt);
    return;
  }

  if (data.stage === "asking" && data.prompt) {
    state.stage = "asking";
    showTextFallback(false);
    await askPrompt(data.prompt);
  }
}

function stopListening() {
  if (state.recog) try { state.recog.stop(); } catch (e) {}
  state.listening = false;
  setListeningVisual(false);
  $("micBtn").classList.remove("listening");
}

// ---------------------------------------------------------------- mic + text fallback
$("micBtn").onclick = () => {
  if (state.listening) stopListening();
  else startListening();
};

function showTextFallback(on) {
  $("textFallback").classList.toggle("active", on);
  if (on) $("textAnswer").focus();
}
$("textSend").onclick = () => {
  const v = $("textAnswer").value.trim();
  if (!v) return;
  $("transcript").textContent = v;
  $("textAnswer").value = "";
  setThinking(true);
  sendAnswer(v);
};
$("textAnswer").addEventListener("keydown", (e) => { if (e.key === "Enter") $("textSend").click(); });

// ---------------------------------------------------------------- photo handoff
$("photoInput").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  stopListening();
  $("photoBtnLabel").textContent = ui().uploading;
  const fd = new FormData();
  fd.append("file", file);
  const res = await fetch(`/api/session/${state.sessionId}/photo`, { method: "POST", body: fd });
  const data = await res.json();
  state.photoFile = data.summary ? null : null;
  if (data.stage === "review") {
    state.uploadedPhoto = URL.createObjectURL(file);
    await handleResponse(data);
  }
});

$("skipBtn").onclick = async () => {
  stopListening();
  const res = await fetch(`/api/session/${state.sessionId}/skip-photo`, { method: "POST" });
  const data = await res.json();
  await handleResponse(data);
};

// ---------------------------------------------------------------- review
function renderReview(summary) {
  const grid = $("fieldsGrid");
  grid.innerHTML = "";
  if (state.uploadedPhoto) {
    $("photoPreview").innerHTML = `<img src="${state.uploadedPhoto}" alt="Profile photo">`;
  }
  (summary || []).forEach((f) => {
    const card = document.createElement("div");
    card.className = "field-card";
    card.innerHTML = `<span class="field-label">${f.label}</span><span class="field-value">${f.display}</span>`;
    card.onclick = () => editField(card, f);
    grid.appendChild(card);
  });
}

function editField(card, f) {
  const valEl = card.querySelector(".field-value, input");
  if (valEl.tagName === "INPUT") return;
  const input = document.createElement("input");
  input.value = f.display;
  valEl.replaceWith(input);
  input.focus();
  const save = async () => {
    const v = input.value.trim() || f.display;
    await fetch(`/api/session/${state.sessionId}/edit`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key: f.key, value: v }),
    });
    const span = document.createElement("span");
    span.className = "field-value";
    span.textContent = v;
    input.replaceWith(span);
    f.display = v;
  };
  input.addEventListener("blur", save);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); });
}

$("confirmBtn").onclick = async () => {
  const res = await fetch(`/api/session/${state.sessionId}/confirm`, { method: "POST" });
  if (!res.ok) return;   // age backstop etc. — stay on review
  const data = await res.json();
  localStorage.removeItem("sakhi_sess");
  show("screen-done");
  await speak(data.prompt);
};

// ---------------------------------------------------------------- feed bridge
$("feedCta").onclick = () => show("screen-feed");

// ---------------------------------------------------------------- demo mode (?demo=1)
const DEMO = new URLSearchParams(location.search).has("demo");
let demoStats = { turns: 0, geminiCalls: 0 };
function demoTurn(ms, data) {
  if (!DEMO) return;
  demoStats.turns++;
  if (data && data.parser === "gemini") demoStats.geminiCalls++;
  $("demoMs").textContent = `${Math.round(ms)} ms`;
  $("demoCost").textContent = `₹${(demoStats.geminiCalls * 0.01).toFixed(2)}`;
  const p = data && data.progress;
  if (p) $("demoQ").textContent = `${p.done}/${p.total}`;
  const t = timingSummary();
  $("demoEndpoint").textContent = t.turns ? `${t.p50} ms` : "–";
  $("demoWall").textContent = `${t.wallSec}s`;
}
if (DEMO) {
  $("demoOverlay").style.display = "flex";
  $("bargeDebug").style.display = "block";
  // Live view of every input to the barge-in decision, so a wrong call is
  // diagnosable instead of mysterious.
  setInterval(() => {
    const on = bargeState.enabled;
    $("bdEnabled").textContent = on ? "on" : "OFF";
    $("bdAec").textContent = bargeState.aec === null ? "?" : String(bargeState.aec);
    const e = on ? micEnergy() : 0;
    const thresh = bargeState.frozenFloor * BARGE.MARGIN;
    $("bdRms").textContent = e.toFixed(3);
    $("bdFloor").textContent = bargeState.frozenFloor.toFixed(3);
    $("bdThresh").textContent = thresh.toFixed(3);
    $("bdRms").className = e > thresh ? "hot" : "";
    $("bdOnset").textContent = bargeState.active ? "armed" : "-";
    $("bdSustain").textContent = `${BARGE.SUSTAIN_MS}ms`;
    $("bdProbing").textContent = bargeState.active ? "watching" : "-";
    $("bdDecision").textContent = bargeState.lastDecision;
    $("bdHeard").textContent = (monitor.text || "").slice(-48) || "-";
  }, 150);
  document.addEventListener("keydown", (e) => {
    if (e.key === "r" || e.key === "R") { localStorage.clear(); location.href = location.pathname + "?demo=1"; }
  });
}

// ==================== ALWAYS-ON RUNTIME STATE BADGE ====================
// The cheapest possible answer to "is the thing I'm testing actually running?".
// Deliberately NOT gated behind ?demo=1.
async function refreshState() {
  let st;
  try { st = await (await fetch("/api/state")).json(); }
  catch (e) { return; }
  state.runtime = st;
  const warns = st.warnings || [];
  const stale = st.build && st.build.stale;
  const level = stale ? "bad" : (warns.length ? "warn" : "");
  const pill = $("statePill"), dot = $("stateDot");
  pill.className = "live-pill" + (level ? " " + level : "");
  dot.className = "dot" + (level ? " " + level : "");
  // The one line that would have saved the night: configured vs ACTUALLY running.
  const c = st.conversation;
  const mode = c.effective_for_hi === c.configured_mode
    ? c.configured_mode
    : `${c.configured_mode}→${c.effective_for_hi}`;
  $("statePillText").textContent =
    `${mode.toUpperCase()} · ${st.voice.tts === "elevenlabs" ? "TTS" : "no-TTS"}` +
    `${st.mic.barge_in ? " · barge" : ""}${stale ? " · STALE" : ""}` +
    `${warns.length ? " · ⚠" + warns.length : ""}`;

  const lines = [
    `build   ${st.build.id}${stale ? "  ← STALE, RESTART" : ""}  pid ${st.build.pid}`,
    `mode    ${c.configured_mode} → hi runs ${c.effective_for_hi}`,
    `agentic ${JSON.stringify(c.agentic_languages)}`,
    `voice   ${st.voice.tts}  ${st.voice.model}  q${st.voice.questions_cached_hi}`,
    `recipe  ${st.voice.recipe}`,
    `parser  ${st.parser.engine}  ${st.parser.model}`,
    `mic     barge_in=${st.mic.barge_in}  vad=${st.mic.vad_endpointing} (${st.mic.endpoint_silence_ms}ms)`,
    `pacing  ack=${st.pacing.ack_rate} think=${st.pacing.think_ms} gap=${st.pacing.turn_gap_ms}`,
    `avatar  ${st.avatar.enabled ? "clips " + st.avatar.clips : "disabled"}  idle=${st.avatar.idle_mode}`,
  ];
  if (warns.length) lines.push("", ...warns.map((w) => (stale ? "! " : "⚠ ") + w));
  $("statePanelBody").textContent = lines.join("\n");
}
$("statePill").onclick = () => $("statePanel").classList.toggle("open");
refreshState();
setInterval(refreshState, 5000);

// ---------------------------------------------------------------- boot
initLanguages();
micPreflight();
checkResume();
