"""
Naturalness pass — reaction triggers and question chaining.

REACTION RULES (enforced by tests, not just convention):
- ECHO the captured value; never evaluate the person. "अच्छा, दसवीं।" not
  "अच्छा, अच्छी पढ़ाई है।" — praise implies its opposite is available.
- Neutral fields ONLY: job and qualification.
  Excluded: caste, religion, income, marital, gender (a remark reads as
  judgement), plus job=not_working and district (commenting on someone's
  circumstances or where they live is judgement too).
- A reaction REPLACES the generic acknowledgment; it never stacks.

CHAINING RULES:
- Only between slots that are genuinely ADJACENT in core.slots.SLOT_PRIORITY
  (validated by test — an earlier draft chained religion->caste and job->income,
  neither of which are consecutive).
- Never chain INTO a sensitive question (caste, income, marital): a breezy
  connective before "have you been divorced?" is flippant.
- income additionally excluded because the almost_done milestone fires there.
"""

# (field, value) -> fragment key. Neutral fields only.
REACTION_TRIGGERS = {
    ("job", "farming"):             "react_farming",
    ("job", "business"):            "react_business",
    ("job", "job"):                 "react_job",
    ("job", "student"):             "react_student",
    # job=not_working and job=other deliberately have NO reaction.
    ("qualification", "10th"):      "react_10th",
    ("qualification", "12th"):      "react_12th",
    ("qualification", "diploma"):   "react_diploma",
    ("qualification", "bachelors"): "react_graduate",
    ("qualification", "masters"):   "react_masters",
    ("qualification", "phd"):       "react_phd",
    # qualification=below_10th deliberately has NO reaction.
}

# Fields that may never trigger a reaction, whatever the value.
REACTION_FORBIDDEN_FIELDS = {"caste", "religion", "income", "marital", "gender",
                             "district", "for_whom", "full_name", "dob"}

# Questions a connective must never lead into.
CHAIN_FORBIDDEN_TARGETS = {"caste", "income", "marital"}

# (previous slot -> next slot) : connective key. Every pair must be adjacent in
# SLOT_PRIORITY, allowing for gender being auto-skipped on son/daughter.
CHAINS = {
    ("for_whom", "full_name"):      "conn_so",
    ("full_name", "gender"):        "conn_and",
    ("full_name", "dob"):           "conn_and",     # valid when gender auto-skipped
    ("gender", "dob"):              "conn_and",
    ("dob", "district"):            "conn_and",
    ("district", "religion"):       "conn_and_now",
    ("marital", "qualification"):   "conn_and",
    ("qualification", "job"):       "conn_so",
}

# Evaluative vocabulary that must never appear in a reaction. The leading
# discourse marker "अच्छा," is NOT evaluation — it means "I see" — so the test
# strips it before checking.
EVALUATIVE_WORDS = [
    "अच्छी", "बढ़िया", "शानदार", "उम्दा", "बेहतरीन", "काबिल", "होशियार",
    "तेज़", "कमज़ोर", "कम पढ़", "बहुत अच्छ", "ज़्यादा पढ़", "पढ़ा-लिखा",
    "good", "great", "excellent", "well educated", "smart", "clever", "impressive",
]
