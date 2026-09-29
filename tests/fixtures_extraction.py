"""
Extraction fixtures — the regression net for every future prompt edit.

Each case covers a §5 domain rule the model does not reliably know on its own.
`expect` lists (slot_key, value) pairs that MUST be produced; `forbid` lists
slot keys that must NOT appear; `intent` is checked when given.
"""

FIXTURES = [
    # --- multi-slot capture -------------------------------------------------
    dict(id="multi_3facts", lang="hi", current="full_name",
         text="मैं राहुल शर्मा हूं, पुणे से, अट्ठाइस साल का",
         expect=[("full_name", "Rahul Sharma"), ("district", "Pune")],
         forbid=["dob"], age_years=28),
    dict(id="multi_name_district", lang="hi", current="full_name",
         text="प्रिया पाटील, नाशिक की रहने वाली",
         expect=[("full_name", "Priya Patil"), ("district", "Nashik")]),

    # --- age is never a date of birth (C8) ----------------------------------
    dict(id="age_only", lang="hi", current="dob", text="तीस साल का हूं",
         expect=[], forbid=["dob"], age_years=30),
    dict(id="real_date_spelled", lang="hi", current="dob",
         text="पंद्रह अगस्त उन्नीस सौ पचानवे", expect=[("dob", "1995-08-15")]),
    dict(id="real_date_slashes", lang="hi", current="dob",
         text="15/8/95", expect=[("dob", "1995-08-15")]),

    # --- income: monthly must be annualized ---------------------------------
    dict(id="income_monthly_hazaar", lang="hi", current="income",
         text="पच्चीस हज़ार महीना", expect=[("income", "3L-5L")]),
    dict(id="income_annual_lakh", lang="hi", current="income",
         text="दो लाख सालाना", expect=[("income", "1.5L-3L")]),
    dict(id="income_range", lang="hi", current="income",
         text="बीस-पच्चीस हज़ार महीना", expect=[("income", "3L-5L")]),
    dict(id="income_nonanswer", lang="hi", current="income",
         text="ठीक-ठाक कमा लेता हूँ", expect=[], forbid=["income"]),
    dict(id="income_nonanswer2", lang="hi", current="income",
         text="बस गुज़ारा हो जाता है", expect=[], forbid=["income"]),

    # --- education terms vary by state --------------------------------------
    dict(id="edu_puc", lang="hi", current="qualification",
         text="पीयूसी किया है", expect=[("qualification", "12th")]),
    dict(id="edu_inter", lang="hi", current="qualification",
         text="इंटर तक पढ़ाई", expect=[("qualification", "12th")]),
    dict(id="edu_matric", lang="hi", current="qualification",
         text="मैट्रिक पास", expect=[("qualification", "10th")]),
    dict(id="edu_btech", lang="hi", current="qualification",
         text="बीटेक किया है", expect=[("qualification", "bachelors")]),
    dict(id="edu_iti", lang="hi", current="qualification",
         text="आईटीआई किया हुआ है", expect=[("qualification", "diploma")]),

    # --- ambiguous names: never infer gender (C3) ---------------------------
    dict(id="ambiguous_kiran", lang="hi", current="full_name",
         text="किरण देशमुख", expect=[("full_name", "Kiran Deshmukh")],
         no_gender_guess=True),
    dict(id="ambiguous_jyoti", lang="hi", current="full_name",
         text="ज्योति", expect=[("full_name", "Jyoti")], no_gender_guess=True),

    # --- occupation phrasings ------------------------------------------------
    dict(id="job_kheti", lang="hi", current="job", text="खेती-बाड़ी करते हैं",
         expect=[("job", "farming")]),
    dict(id="job_dhandha", lang="hi", current="job", text="अपना धंधा है",
         expect=[("job", "business")]),

    # --- village/city answers map to district, never re-asked ---------------
    dict(id="district_village", lang="hi", current="district",
         text="हमारा गाँव वर्धा ज़िले में है", expect=[("district", "Wardha")]),

    # --- intents -------------------------------------------------------------
    dict(id="intent_correction", lang="hi", current="religion",
         text="नहीं नहीं, ज़िला नाशिक है, पुणे नहीं", intent="correction",
         expect=[("district", "Nashik")]),
    dict(id="intent_side_question", lang="hi", current="district",
         text="ये सब फ्री है क्या?", intent="side_question", expect=[]),
    dict(id="intent_backchannel", lang="hi", current="district",
         text="हाँ हाँ", intent="backchannel", expect=[]),
]
