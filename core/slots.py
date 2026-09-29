"""
Slot-filling state for agentic mode.

Replaces "question index" with "slot state": every profile field is a slot that
can be filled from ANY utterance, in any order, and is never re-asked once known.

Preserved from classic (non-negotiable):
- gender auto-skip when for_whom is son/daughter
- 18+ age gate on dob (never stores an underage date)
- caste/income skippable
- the same 11 fields, same enum values, same display strings

New in agentic:
- conversational priority order (identity -> basics -> background -> sensitive last)
- inference: name -> gender (ALWAYS confirmed, never silently filled)
            district -> state (derived silently; not user-facing data entry)
- confirmation batching: 2+ slots filled at once confirm together, once
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from core.questions import ENUMS

# Conversationally sensible order. Sensitive questions land last so a drop-off
# costs us the least valuable fields (validated against classic via the funnel).
SLOT_PRIORITY = [
    "for_whom", "full_name", "gender", "dob", "district",
    "religion", "marital", "qualification", "job",
    "caste", "income",
]
SKIPPABLE = {"caste", "income"}

EMPTY = "empty"
FILLED = "filled"
SKIPPED = "skipped"
NEEDS_CONFIRMATION = "needs_confirmation"

# Sources, in ascending order of trust
SPOKEN = "spoken"
INFERRED = "inferred"
CONFIRMED = "confirmed"
DERIVED = "derived"

# Gender inference below this confidence is never even offered for confirmation —
# we just ask the question. A wrong guess on a matrimony profile is a serious error.
GENDER_INFER_MIN_CONFIDENCE = 0.85

# Names that are common for both genders in India — never inferred, always asked.
AMBIGUOUS_NAMES = {
    "kiran", "jyoti", "anand", "ashwini", "harpreet", "gurpreet", "manpreet",
    "sandhya", "shashi", "sharan", "nirmal", "prabhat", "rajni", "madhu",
    "chandan", "suman", "sonu", "monu", "raj", "shivangi", "anmol", "amar",
    "किरण", "ज्योति", "आनंद", "अश्विनी", "निर्मल", "सुमन", "मधु", "राज",
}

# district -> state, for the silent derivation. Seeded with high-volume Tier 2/3
# districts; extended from the CSV the value-bank loader ingests (Phase 3).
DISTRICT_STATE = {
    "nagpur": "Maharashtra", "pune": "Maharashtra", "nashik": "Maharashtra",
    "aurangabad": "Maharashtra", "thane": "Maharashtra", "solapur": "Maharashtra",
    "kolhapur": "Maharashtra", "amravati": "Maharashtra", "latur": "Maharashtra",
    "jalgaon": "Maharashtra", "akola": "Maharashtra", "satara": "Maharashtra",
    "lucknow": "Uttar Pradesh", "kanpur": "Uttar Pradesh", "varanasi": "Uttar Pradesh",
    "agra": "Uttar Pradesh", "meerut": "Uttar Pradesh", "prayagraj": "Uttar Pradesh",
    "gorakhpur": "Uttar Pradesh", "bareilly": "Uttar Pradesh", "aligarh": "Uttar Pradesh",
    "patna": "Bihar", "gaya": "Bihar", "muzaffarpur": "Bihar", "bhagalpur": "Bihar",
    "darbhanga": "Bihar", "purnia": "Bihar",
    "jaipur": "Rajasthan", "jodhpur": "Rajasthan", "udaipur": "Rajasthan",
    "kota": "Rajasthan", "ajmer": "Rajasthan", "bikaner": "Rajasthan",
    "indore": "Madhya Pradesh", "bhopal": "Madhya Pradesh", "jabalpur": "Madhya Pradesh",
    "gwalior": "Madhya Pradesh", "ujjain": "Madhya Pradesh", "sagar": "Madhya Pradesh",
    "ahmedabad": "Gujarat", "surat": "Gujarat", "vadodara": "Gujarat",
    "rajkot": "Gujarat", "bhavnagar": "Gujarat", "jamnagar": "Gujarat",
    "chennai": "Tamil Nadu", "coimbatore": "Tamil Nadu", "madurai": "Tamil Nadu",
    "tiruchirappalli": "Tamil Nadu", "salem": "Tamil Nadu", "erode": "Tamil Nadu",
    "hyderabad": "Telangana", "warangal": "Telangana", "nizamabad": "Telangana",
    "vijayawada": "Andhra Pradesh", "visakhapatnam": "Andhra Pradesh",
    "guntur": "Andhra Pradesh", "tirupati": "Andhra Pradesh", "nellore": "Andhra Pradesh",
    "bengaluru": "Karnataka", "bangalore": "Karnataka", "mysuru": "Karnataka",
    "mysore": "Karnataka", "hubli": "Karnataka", "belagavi": "Karnataka",
    "mangaluru": "Karnataka", "davangere": "Karnataka",
    "kochi": "Kerala", "thiruvananthapuram": "Kerala", "kozhikode": "Kerala",
    "thrissur": "Kerala", "kollam": "Kerala", "kannur": "Kerala",
    "kolkata": "West Bengal", "howrah": "West Bengal", "durgapur": "West Bengal",
    "siliguri": "West Bengal", "asansol": "West Bengal", "malda": "West Bengal",
    "ludhiana": "Punjab", "amritsar": "Punjab", "jalandhar": "Punjab", "patiala": "Punjab",
    "delhi": "Delhi", "new delhi": "Delhi", "mumbai": "Maharashtra",
    "ranchi": "Jharkhand", "jamshedpur": "Jharkhand", "dhanbad": "Jharkhand",
    "raipur": "Chhattisgarh", "bhilai": "Chhattisgarh", "bilaspur": "Chhattisgarh",
    "bhubaneswar": "Odisha", "cuttack": "Odisha", "rourkela": "Odisha",
    "guwahati": "Assam", "dibrugarh": "Assam", "silchar": "Assam",
    "dehradun": "Uttarakhand", "haridwar": "Uttarakhand",
    "shimla": "Himachal Pradesh", "srinagar": "Jammu and Kashmir", "jammu": "Jammu and Kashmir",
    "gurugram": "Haryana", "faridabad": "Haryana", "hisar": "Haryana", "rohtak": "Haryana",
}


def normalize_key(text: str) -> str:
    """Lookup key that survives spelling/spacing/case noise. Devanagari and Latin
    forms of the same word do NOT collapse here — the value bank handles
    cross-script aliasing (Phase 3); this only normalizes within a script."""
    t = (text or "").strip().lower()
    t = re.sub(r"[\s\-_.]+", " ", t)
    return t.strip()


def state_for_district(display: str) -> str | None:
    return DISTRICT_STATE.get(normalize_key(display))


@dataclass
class Slot:
    key: str
    status: str = EMPTY
    value: Any = None
    display: str = ""
    confidence: float = 0.0
    source: str = ""
    asked_count: int = 0

    @property
    def known(self) -> bool:
        """Filled or skipped — either way, never ask again."""
        return self.status in (FILLED, SKIPPED)

    def to_field(self) -> dict:
        return {"value": self.value, "display": self.display, "source": self.source}


@dataclass
class SlotState:
    slots: dict[str, Slot] = field(default_factory=lambda: {k: Slot(k) for k in SLOT_PRIORITY})
    derived: dict[str, Any] = field(default_factory=dict)   # state, age
    last_batch: list[str] = field(default_factory=list)     # slots filled in the last turn
    refused: set = field(default_factory=set)   # inferences the user rejected — never re-offer

    # ------------------------------------------------------------------ reads
    def __getitem__(self, key: str) -> Slot:
        return self.slots[key]

    def value_of(self, key: str) -> Any:
        return self.slots[key].value if key in self.slots else None

    def pending_confirmation(self) -> str | None:
        for k in SLOT_PRIORITY:
            if self.slots[k].status == NEEDS_CONFIRMATION:
                return k
        return None

    def next_slot(self) -> str | None:
        """Next thing to ask: a pending confirmation first, else the highest
        priority empty slot. None means every slot is resolved -> photo stage."""
        pending = self.pending_confirmation()
        if pending:
            return pending
        self._apply_gender_autoskip()
        for k in SLOT_PRIORITY:
            if self.slots[k].status == EMPTY:
                return k
        return None

    def remaining(self) -> int:
        return sum(1 for k in SLOT_PRIORITY if self.slots[k].status == EMPTY)

    def answered(self) -> int:
        return sum(1 for k in SLOT_PRIORITY if self.slots[k].known)

    # ----------------------------------------------------------------- writes
    def fill(self, key: str, value: Any, display: str, *,
             confidence: float = 1.0, source: str = SPOKEN) -> bool:
        if key not in self.slots:
            return False
        s = self.slots[key]
        s.value, s.display = value, display
        s.confidence, s.source = confidence, source
        s.status = FILLED
        if key == "district":
            st = state_for_district(display)
            if st:
                self.derived["state"] = st      # silent, never asked or confirmed
        if key == "dob":
            self.derived["age"] = age_of(value)
        if key == "for_whom":
            self._apply_gender_autoskip()
        return True

    def skip(self, key: str) -> bool:
        if key not in self.slots or key not in SKIPPABLE:
            return False
        s = self.slots[key]
        s.status, s.value, s.display, s.source = SKIPPED, None, "—", SPOKEN
        return True

    def mark_needs_confirmation(self, key: str, value: Any, display: str,
                                confidence: float) -> bool:
        """Inference landing zone: the value is held, NOT trusted, until the user
        confirms. next_slot() surfaces it before anything else."""
        if key not in self.slots or self.slots[key].known:
            return False
        s = self.slots[key]
        s.value, s.display = value, display
        s.confidence, s.source = confidence, INFERRED
        s.status = NEEDS_CONFIRMATION
        return True

    def confirm(self, key: str, accepted: bool) -> bool:
        s = self.slots.get(key)
        if not s or s.status != NEEDS_CONFIRMATION:
            return False
        if accepted:
            s.status, s.source = FILLED, CONFIRMED
        else:
            s.status, s.value, s.display, s.source, s.confidence = EMPTY, None, "", "", 0.0
            self.refused.add(key)   # asked once, got it wrong — never guess again
        return True

    def mark_asked(self, key: str):
        if key in self.slots:
            self.slots[key].asked_count += 1

    # ------------------------------------------------------------- inference
    def _apply_gender_autoskip(self):
        """Classic rule, preserved: son/daughter implies gender. This is a
        derivation from an explicit answer, not a guess — no confirmation."""
        g = self.slots["gender"]
        if g.known or g.status == NEEDS_CONFIRMATION:
            return
        fw = self.slots["for_whom"].value
        if fw == "son":
            self.fill("gender", "male", "Male", source=DERIVED)
        elif fw == "daughter":
            self.fill("gender", "female", "Female", source=DERIVED)

    def offer_gender_inference(self, gender: str, confidence: float, name: str) -> bool:
        """name -> gender. Returns True only if we will ASK for confirmation.
        Never fills. Refuses on ambiguous names or low confidence."""
        if self.slots["gender"].known or self.slots["gender"].status == NEEDS_CONFIRMATION:
            return False
        if "gender" in self.refused:
            return False        # already guessed once and was corrected — just ask
        if gender not in ENUMS["gender"] or confidence < GENDER_INFER_MIN_CONFIDENCE:
            return False
        first = normalize_key(name).split(" ")[0] if name else ""
        if first in AMBIGUOUS_NAMES:
            return False
        display = "Male" if gender == "male" else "Female"
        return self.mark_needs_confirmation("gender", gender, display, confidence)

    # -------------------------------------------------------------- reporting
    def fields(self) -> dict:
        """Classic-shaped fields dict (+ source), for the profile record."""
        out = {}
        for k in SLOT_PRIORITY:
            s = self.slots[k]
            if s.known:
                out[k] = s.to_field()
        return out

    def source_summary(self) -> dict:
        """How much of the profile was captured conversationally vs asked."""
        counts = {}
        for k in SLOT_PRIORITY:
            s = self.slots[k]
            if s.known:
                counts[s.source or "unknown"] = counts.get(s.source or "unknown", 0) + 1
        return counts


def age_of(iso: str) -> int:
    y, m, d = map(int, iso.split("-"))
    t = date.today()
    return t.year - y - ((t.month, t.day) < (m, d))
