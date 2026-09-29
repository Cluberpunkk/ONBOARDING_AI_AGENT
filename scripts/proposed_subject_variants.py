"""
Phase B/C staging — subject-aware question variants + clarification expansions.

Written as WHOLE sentences per subject, never assembled by prefixing a fragment:
Hindi conjugation makes "बेटी" + "क्या काम करते हैं?" stilted. Verb agreement is
carried through ("बेटा क्या काम करता है?" vs "बेटी क्या काम करती है?").

Load-bearing content preserved in every variant: the dob date example, the
qualification examples, the full marital/job option lists.

Applied to core/questions.py ONLY after the diff gate is approved.
Classic mode keeps today's neutral questions untouched.
"""

# subject key -> question key -> text
SUBJECT_VARIANTS = {
"hi": {
"self": {
    "full_name":     "आपका पूरा नाम क्या है?",
    "dob":           "आपकी जन्म तारीख़? जैसे, पंद्रह अगस्त, उन्नीस सौ पचानवे।",
    "district":      "आप कौन से ज़िले से हैं?",
    "religion":      "आपका धर्म क्या है?",
    "caste":         "और आपकी जाति?",
    "marital":       "आपकी पहले शादी हुई है? कभी नहीं, तलाक़, या विधवा-विधुर?",
    "qualification": "आपकी पढ़ाई कहाँ तक हुई है? जैसे दसवीं, बारहवीं, ग्रेजुएशन।",
    "job":           "आपका काम क्या है? नौकरी, बिज़नेस, खेती, या कुछ और?",
    "income":        "आपकी महीने की कमाई लगभग कितनी है?",
},
"son": {
    "full_name":     "बेटे का पूरा नाम क्या है?",
    "dob":           "बेटे की जन्म तारीख़? जैसे, पंद्रह अगस्त, उन्नीस सौ पचानवे।",
    "district":      "बेटा कौन से ज़िले का है?",
    "religion":      "बेटे का धर्म क्या है?",
    "caste":         "और बेटे की जाति?",
    "marital":       "बेटे की पहले शादी हुई है? कभी नहीं, तलाक़, या विधुर?",
    "qualification": "बेटे की पढ़ाई कहाँ तक हुई है? जैसे दसवीं, बारहवीं, ग्रेजुएशन।",
    "job":           "बेटा क्या काम करता है? नौकरी, बिज़नेस, खेती, या कुछ और?",
    "income":        "बेटे की महीने की कमाई लगभग कितनी है?",
},
"daughter": {
    "full_name":     "बेटी का पूरा नाम क्या है?",
    "dob":           "बेटी की जन्म तारीख़? जैसे, पंद्रह अगस्त, उन्नीस सौ पचानवे।",
    "district":      "बेटी कौन से ज़िले की है?",
    "religion":      "बेटी का धर्म क्या है?",
    "caste":         "और बेटी की जाति?",
    "marital":       "बेटी की पहले शादी हुई है? कभी नहीं, तलाक़, या विधवा?",
    "qualification": "बेटी की पढ़ाई कहाँ तक हुई है? जैसे दसवीं, बारहवीं, ग्रेजुएशन।",
    "job":           "बेटी क्या काम करती है? नौकरी, बिज़नेस, खेती, या कुछ और?",
    "income":        "बेटी की महीने की कमाई लगभग कितनी है?",
},
"friend": {
    "full_name":     "दोस्त का पूरा नाम क्या है?",
    "dob":           "दोस्त की जन्म तारीख़? जैसे, पंद्रह अगस्त, उन्नीस सौ पचानवे।",
    "district":      "दोस्त कौन से ज़िले से हैं?",
    "religion":      "दोस्त का धर्म क्या है?",
    "caste":         "और दोस्त की जाति?",
    "marital":       "दोस्त की पहले शादी हुई है? कभी नहीं, तलाक़, या विधवा-विधुर?",
    "qualification": "दोस्त की पढ़ाई कहाँ तक हुई है? जैसे दसवीं, बारहवीं, ग्रेजुएशन।",
    "job":           "दोस्त का काम क्या है? नौकरी, बिज़नेस, खेती, या कुछ और?",
    "income":        "दोस्त की महीने की कमाई लगभग कितनी है?",
},
},
}

# Second clarification on the same question: say what the field IS, in plain
# words, then ask. Subject-neutral on purpose — the subject was already named in
# the first clarification; this one explains the FIELD.
EXPANSIONS = {
"hi": {
    "full_name":     "पूरा नाम मतलब — नाम और सरनेम, दोनों बता दीजिए।",
    "dob":           "जन्म का दिन, महीना और साल बता दीजिए।",
    "district":      "किस शहर या ज़िले में रहते हैं, वो बता दीजिए।",
    "religion":      "हिंदू, मुस्लिम, ईसाई, सिख — इनमें से कौन सा?",
    "caste":         "जाति या समाज का नाम बता दीजिए। न बताना हो तो स्किप बोलिए।",
    "marital":       "पहले कभी शादी हुई थी या नहीं, बस वो बता दीजिए।",
    "qualification": "सबसे आख़िरी कौन सी क्लास या डिग्री पूरी की, वो बता दीजिए।",
    "job":           "रोज़ी-रोटी के लिए क्या करते हैं, वो बता दीजिए।",
    "income":        "महीने में लगभग कितने पैसे आते हैं, अंदाज़ा बता दीजिए।",
    "for_whom":      "प्रोफाइल किसके लिए बना रहे हैं — अपने लिए, या घर में किसी और के लिए?",
    "gender":        "लड़के की प्रोफाइल है या लड़की की, वो बता दीजिए।",
},
}

SUBJECT_SENSITIVE = ["full_name", "dob", "district", "religion", "caste",
                     "marital", "qualification", "job", "income"]
