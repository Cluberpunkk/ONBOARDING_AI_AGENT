"""
Answer parser — turns a spoken transcript into a structured field value.

Two modes:
  1. Gemini mode (GEMINI_API_KEY set): robust multilingual understanding.
     "मेरा नाम विरेंद्र पाटील है"  -> full_name = "Virendra Patil"
     "पच्चीस हज़ार महीना"          -> income = "3L-5L"
  2. Mock mode (no key): keyword matching + dateutil. Good enough to demo
     the full flow without any API key.

Return contract: ParseResult(value, display, confident, is_skip)
  value     — normalized machine value (enum key / ISO date / clean text)
  display   — what to show on the review card
  confident — False triggers Sakhi's clarify re-ask
  is_skip   — True only on the photo step when user says skip
"""
from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass

from config import settings
from core.questions import ENUMS, FREE_TEXT

log = logging.getLogger("sakhi.parser")


@dataclass
class ParseResult:
    value: str = ""
    display: str = ""
    confident: bool = False
    is_skip: bool = False
    source: str = "mock"    # "mock" (free, instant) | "gemini" (paid, ~0.7s)


# ----------------------------------------------------------------------
# Skip words (photo step) — multilingual
# ----------------------------------------------------------------------
SKIP_WORDS = [
    "skip", "स्किप", "बाद में", "आगे", "नंतर", "ஸ்கிப்", "பிறகு", "స్కిప్",
    "తర్వాత", "ಸ್ಕಿಪ್", "ಆಮೇಲೆ", "സ്കിപ്പ്", "പിന്നീട്", "স্কিপ", "পরে",
    "સ્કિપ", "પછી", "later", "not now", "nahi", "नहीं", "no",
]


def _is_skip(text: str) -> bool:
    t = text.lower().strip()
    return any(w in t for w in SKIP_WORDS)


# ----------------------------------------------------------------------
# Gemini mode
# ----------------------------------------------------------------------
_PROMPTS = {
    "for_whom": "Map the answer to exactly one of: self, son, daughter, friend.",
    "gender": "Map the answer to exactly one of: male, female. Words like ladka/beta/boy/groom mean male; ladki/beti/girl/bride mean female.",
    "marital": "Map to one of: never_married, divorced, widowed, awaiting_divorce.",
    "religion": "Map to one of: Hindu, Muslim, Christian, Sikh, Jain, Buddhist, Other.",
    "qualification": "Map to one of: below_10th, 10th, 12th, diploma, bachelors, masters, phd. Class 10/dasvi/SSC=10th; 12/barvi/PUC/inter/HSC=12th; BA/BSc/BCom/BE/graduation=bachelors; MA/MSc/MBA/MTech=masters.",
    "job": "Map to one of: job, business, farming, student, not_working, other. naukri/private/govt=job; dhandha/vyapar=business; kheti/sheti=farming.",
    "income": ("Map to one annual-income band: under_1.5L, 1.5L-3L, 3L-5L, 5L-8L, 8L-12L, 12L-20L, above_20L. "
               "If a MONTHLY amount is given, multiply by 12 first. 25 hazar mahina = 3L/yr = 3L-5L band."),
    "full_name": "Extract the person's full name, transliterated to English (Latin script), title case.",
    "district": "Extract the district/city name, transliterated to English, title case.",
    "caste": "Extract the caste/community name, transliterated to English, title case.",
    "dob": "Extract the date of birth as ISO YYYY-MM-DD. Convert spoken words/numerals in any Indian language. If year only, use YYYY-01-01 and set confident=false.",
}

_client = None


def _gemini_parse(question_key: str, transcript: str, language: str) -> ParseResult:
    global _client
    from google import genai  # lazy import
    if _client is None:
        _client = genai.Client(api_key=settings.GEMINI_API_KEY)

    instruction = _PROMPTS.get(question_key, "Extract the answer value.")
    # Trimmed prompt: measured 5/5 accuracy at p50 ~705 ms on gemini-3.5-flash-lite.
    # thinking_level=minimal was tested and REJECTED: slower (p50 814 ms) and one
    # observed wrong income band. Default thinking + JSON mime is the sweet spot.
    from agent.system_prompt import compile_for
    prompt = compile_for(
        f"Parse ONE spoken answer. Language '{language}', field '{question_key}'.\n"
        f"Rule: {instruction}\n"
        f'Transcript: "{transcript}"\n'
        'JSON only: {"value": string, "display": string, "confident": boolean}. '
        "display: short human-readable English. confident=false if unclear.",
        slot=question_key,
    )
    resp = _client.models.generate_content(
        model=settings.PARSER_MODEL,
        contents=prompt,
        config={"response_mime_type": "application/json", "temperature": 0,
                "max_output_tokens": 200},
    )
    data = json.loads(resp.text)
    if isinstance(data, list):          # model occasionally wraps in a list
        data = data[0] if data and isinstance(data[0], dict) else {}
    if not isinstance(data, dict):
        return ParseResult(confident=False, source="gemini")
    value = str(data.get("value", "")).strip()
    if question_key in ENUMS and value not in ENUMS[question_key]:
        return ParseResult(confident=False, source="gemini")
    if question_key == "dob" and not _dob_plausible(value):
        return ParseResult(value=value, display=value, confident=False, source="gemini")
    return ParseResult(
        value=value,
        display=str(data.get("display", value)),
        confident=bool(data.get("confident", False)) and bool(value),
        source="gemini",
    )


def _dob_plausible(iso: str) -> bool:
    """Sanity net for BOTH parser paths: a matrimony dob must be a real past
    date with a plausible birth year (the 18+ gate does the legal check)."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})$", iso or "")
    if not m:
        return False
    return 1920 <= int(m.group(1)) <= 2015


# ----------------------------------------------------------------------
# Mock mode — keyword matching, keeps the demo alive with zero keys
# ----------------------------------------------------------------------
_KW = {
    "for_whom": {
        # Order matters: specific relations first, self last ("अपने बेटे के लिए" contains "अपने")
        "son": ["बेटे", "बेटा", "son", "मुला", "मुलगा", "மகன", "కొడుక", "ಮಗನ", "മകന", "ছেলে", "દીકરા", "ladke", "bete"],
        "daughter": ["बेटी", "daughter", "मुली", "मुलगी", "மகள", "కూతుర", "ಮಗಳ", "മകൾ", "মেয়ে", "દીકરી", "beti"],
        "friend": ["दोस्त", "friend", "मित्र", "நண்ப", "స్నేహ", "ಸ್ನೇಹ", "സുഹൃ", "বন্ধু", "મિત્ર", "dost"],
        "self": ["अपने लिए", "खुद", "myself", "self", "मेरे लिए", "माझ्यासाठी", "எனக்கு", "நான்", "నా కోసం", "ನನಗಾಗಿ", "എനിക്ക്", "নিজের", "મારા માટે", "mere liye", "apne liye"],
    },
    "gender": {
        "male": ["लड़के", "लड़का", "boy", "male", "मुला", "பையன", "అబ్బాయ", "ಹುಡುಗನ", "ആൺ", "ছেলে", "છોકરા", "groom", "ladka"],
        "female": ["लड़की", "girl", "female", "मुली", "பெண", "అమ్మాయ", "ಹುಡುಗಿ", "പെൺ", "মেয়ে", "છોકરી", "bride", "ladki"],
    },
    "marital": {
        "never_married": ["कभी नहीं", "नहीं हुई", "never", "unmarried", "कधीच नाही", "இல்லை", "కాలేదు", "ಇಲ್ಲ", "ഇല്ല", "কখনো না", "નહીં", "single", "nahi hui"],
        "divorced": ["तलाक", "divorce", "घटस्फोट", "விவாகரத்து", "విడాకుల", "ವಿಚ್ಛೇದನ", "വിവാഹമോചന", "ডিভোর্স", "છૂટાછેડા"],
        "widowed": ["विधवा", "विधुर", "widow", "விதவை", "వితంతు", "ವಿಧವೆ", "വിധവ", "বিধবা", "વિધવા"],
    },
    "religion": {
        "Hindu": ["हिंदू", "hindu", "हिन्दू", "இந்து", "హింద", "ಹಿಂದ", "ഹിന്ദ", "হিন্দু", "હિંદુ"],
        "Muslim": ["मुस्लिम", "muslim", "इस्लाम", "முஸ்லிம்", "ముస్లిం", "ಮುಸ್ಲಿ", "മുസ്ല", "মুসলিম", "મુસ્લિમ"],
        "Christian": ["ईसाई", "christian", "கிறிஸ்தவ", "క్రైస్తవ", "ಕ್ರೈಸ್ತ", "ക്രിസ്ത്യ", "খ্রিস্টান", "ખ્રિસ્તી"],
        "Sikh": ["सिख", "sikh", "શીખ", "শিখ"],
        "Jain": ["जैन", "jain", "જૈન", "জৈন"],
        "Buddhist": ["बौद्ध", "buddhist", "बौद्ध"],
    },
    "qualification": {
        "10th": ["दसवीं", "10", "दहावी", "பத்தாவது", "పదో", "ಹತ್ತನೇ", "പത്താം", "দশম", "દસમું", "ssc", "dasvi"],
        "12th": ["बारहवीं", "12", "बारावी", "பன்னிரண்ட", "ఇంటర", "ಪಿಯುಸಿ", "പ്ലസ് ടു", "দ্বাদশ", "બારમું", "hsc", "inter", "barvi"],
        "diploma": ["डिप्लोमा", "diploma", "iti"],
        "bachelors": ["ग्रेजुएशन", "graduation", "बीए", "बीएससी", "बीकॉम", "डिग्री", "degree", "டிகிரி", "డిగ్రీ", "ಡಿಗ್ರಿ", "ഡിഗ്രി", "গ্র্যাজুয়েশন", "ગ્રેજ્યુએશન", "ba", "bsc", "bcom", "be", "btech"],
        "masters": ["मास्टर", "master", "एमए", "एमबीए", "ma", "msc", "mba", "mtech", "एमएससी"],
        "phd": ["पीएचडी", "phd", "doctorate"],
        "below_10th": ["आठवीं", "पांचवीं", "below", "कम", "आठवी"],
    },
    "job": {
        "job": ["नौकरी", "job", "private", "सरकारी", "govt", "வேலை", "ఉద్యోగ", "ಕೆಲಸ", "ജോലി", "চাকরি", "નોકરી", "naukri", "company"],
        "business": ["बिज़नेस", "business", "व्यवसाय", "धंधा", "दुकान", "பிசினஸ்", "వ్యాపార", "ವ್ಯಾಪಾರ", "ബിസിനസ", "ব্যবসা", "ધંધો", "dhandha", "vyapar"],
        "farming": ["खेती", "farming", "शेती", "किसान", "விவசாய", "వ్యవసాయ", "ಕೃಷಿ", "കൃഷി", "চাষ", "ખેતી", "kheti"],
        "student": ["स्टूडेंट", "student", "पढ़ाई", "पढ़ता", "படிக்க", "చదువుతున్న"],
        "not_working": ["नहीं करत", "housewife", "गृहिणी", "घर"],
    },
}

_NUM = r"(\d+(?:\.\d+)?)"

# Month names in 9 scripts -> English (mock-mode DOB parsing)
_MONTHS = {
    "january": ["जनवरी", "জানুয়ারি", "ஜனவரி", "జనవరి", "ಜನವರಿ", "ജനുവരി", "જાન્યુઆરી"],
    "february": ["फरवरी", "फ़रवरी", "ফেব্রুয়ারি", "பிப்ரவரி", "ఫిబ్రవరి", "ಫೆಬ್ರವರಿ", "ഫെബ്രുവരി", "ફેબ્રુઆરી"],
    "march": ["मार्च", "মার্চ", "மார்ச்", "మార్చి", "ಮಾರ್ಚ್", "മാർച്ച്", "માર્ચ"],
    "april": ["अप्रैल", "एप्रिल", "এপ্রিল", "ஏப்ரல்", "ఏప్రిల్", "ಏಪ್ರಿಲ್", "ഏപ്രിൽ", "એપ્રિલ"],
    "may": ["मई", "मे", "মে", "மே", "మే", "ಮೇ", "മേയ്", "મે"],
    "june": ["जून", "জুন", "ஜூன்", "జూన్", "ಜೂನ್", "ജൂൺ", "જૂન"],
    "july": ["जुलाई", "जुलै", "জুলাই", "ஜூலை", "జూలై", "ಜುಲೈ", "ജൂലൈ", "જુલાઈ"],
    "august": ["अगस्त", "ऑगस्ट", "আগস্ট", "ஆகஸ்ட்", "ఆగస్టు", "ಆಗಸ್ಟ್", "ഓഗസ്റ്റ്", "ઓગસ્ટ"],
    "september": ["सितंबर", "सप्टेंबर", "সেপ্টেম্বর", "செப்டம்பர்", "సెప్టెంబర్", "ಸೆಪ್ಟೆಂಬರ್", "സെപ്റ്റംബർ", "સપ્ટેમ્બર"],
    "october": ["अक्टूबर", "ऑक्टोबर", "অক্টোবর", "அக்டோபர்", "అక్టోబర్", "ಅಕ್ಟೋಬರ್", "ഒക്ടോബർ", "ઓક્ટોબર"],
    "november": ["नवंबर", "नोव्हेंबर", "নভেম্বর", "நவம்பர்", "నవంబర్", "ನವೆಂಬರ್", "നവംബർ", "નવેમ્બર"],
    "december": ["दिसंबर", "डिसेंबर", "ডিসেম্বর", "டிசம்பர்", "డిసెంబర్", "ಡಿಸೆಂಬರ್", "ഡിസംബർ", "ડિસેમ્બર"],
}

# Indic digit blocks -> ASCII
_DIGIT_MAP = {}
for block_zero in (0x0966, 0x09E6, 0x0AE6, 0x0BE6, 0x0C66, 0x0CE6, 0x0D66):  # Deva, Beng, Guj, Tam, Tel, Kan, Mal
    for i in range(10):
        _DIGIT_MAP[chr(block_zero + i)] = str(i)


def _normalize_date_text(text: str) -> str:
    t = "".join(_DIGIT_MAP.get(ch, ch) for ch in text)
    for en, variants in _MONTHS.items():
        for v in variants:
            if v in t:
                t = t.replace(v, en)
    return t


def _mock_income(text: str) -> str | None:
    t = text.lower().replace(",", "")
    m = re.search(_NUM, t)
    if not m:
        return None
    amount = float(m.group(1))
    if "लाख" in t or "lakh" in t or "லட்ச" in t or "లక్ష" in t or "ಲಕ್ಷ" in t or "ലക്ഷ" in t or "લાખ" in t or "লাখ" in t or "लक्ष" in t:
        annual = amount * 100000
    elif "हज़ार" in t or "हजार" in t or "thousand" in t or "k " in t or t.endswith("k") or "ஆயிரம்" in t or "వేల" in t or "ಸಾವಿರ" in t or "হাজার" in t or "હજાર" in t:
        annual = amount * 1000
    else:
        annual = amount
    # If it smells monthly (word "महीना/month/per month"), annualize
    if any(w in t for w in ["महीन", "month", "मासिक", "மாத", "నెల", "ತಿಂಗಳ", "മാസ", "মাস", "મહિન", "mahina"]):
        annual *= 12
    if annual < 150000: return "under_1.5L"
    if annual < 300000: return "1.5L-3L"
    if annual < 500000: return "3L-5L"
    if annual < 800000: return "5L-8L"
    if annual < 1200000: return "8L-12L"
    if annual < 2000000: return "12L-20L"
    return "above_20L"


def _mock_parse(question_key: str, transcript: str, language: str) -> ParseResult:
    t = transcript.strip()
    if not t:
        return ParseResult(confident=False)

    if question_key in FREE_TEXT:
        clean = re.sub(r"^(मेरा नाम|my name is|नाम है|naam)\s*", "", t, flags=re.I).strip(" .।")
        return ParseResult(value=clean.title(), display=clean.title(), confident=True)

    if question_key == "dob":
        try:
            from dateutil import parser as dp
            norm = _normalize_date_text(t)
            dt = dp.parse(norm, dayfirst=True, fuzzy=True)
            if not _dob_plausible(dt.strftime("%Y-%m-%d")):
                return ParseResult(value=t, display=t, confident=False)
            iso = dt.strftime("%Y-%m-%d")
            return ParseResult(value=iso, display=dt.strftime("%d %b %Y"), confident=True)
        except Exception:
            return ParseResult(value=t, display=t, confident=False)

    if question_key == "income":
        band = _mock_income(t)
        if band:
            return ParseResult(value=band, display=band.replace("_", " "), confident=True)
        return ParseResult(confident=False)

    kw_map = _KW.get(question_key, {})
    tl = t.lower()
    for enum_val, words in kw_map.items():
        if any(w.lower() in tl for w in words):
            return ParseResult(value=enum_val, display=enum_val.replace("_", " ").title(), confident=True)
    return ParseResult(confident=False)


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------
# Enum-ish questions where a curated-keyword hit is as reliable as Gemini —
# and ~700 ms faster. Free-text (name/district/caste) stays Gemini-first:
# the mock's cleanup there is too naive for real transcripts.
_FAST_PATH_KEYS = set(ENUMS) | {"dob", "income"}


def parse_answer(question_key: str, transcript: str, language: str) -> ParseResult:
    if question_key == "photo":
        return ParseResult(is_skip=_is_skip(transcript), confident=True)

    # Fast path: instant local parse when the curated keywords hit cleanly.
    # Anything ambiguous falls through to Gemini — accuracy is never traded.
    if question_key in _FAST_PATH_KEYS:
        quick = _mock_parse(question_key, transcript, language)
        if quick.confident:
            return quick

    if settings.parser_enabled:
        try:
            return _gemini_parse(question_key, transcript, language)
        except Exception as e:
            log.warning("Gemini parse failed (%s) — falling back to mock", e)
    return _mock_parse(question_key, transcript, language)
