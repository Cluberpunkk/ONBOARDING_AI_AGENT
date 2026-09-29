"""
Response selection: the model DECIDES, the registry BOUNDS, code ENFORCES.

Every failure we kept hitting was a decision failure, not an extraction failure.
"किसका नाम पूछ रही हो" was heard perfectly — the routing table simply had no
good entry, so it fell through to `unclear` and repeated the same question.
Hardcoded intent→key tables cannot cover what people actually say.

So on any turn that is not a clean fast-path answer, the model is handed a menu
of responses that are VALID IN THIS STATE and returns an ordered plan of keys.

Three things keep this safe:
  1. BOUNDED   — it can only choose keys we authored; dialogue.validate() drops
                 anything else, so the worst case is silence, never a lie.
  2. FILTERED  — the menu is built from state (20-30 keys, not all 130), so it
                 cannot offer skip_ack on a required question or a gender
                 confirmation when no inference is pending.
  3. ENFORCED  — post-conditions below are applied in CODE after the model
                 answers. Repetition, the clarification ladder, sensitive-field
                 rules and the guardrails are not left to good behaviour.

The menu carries ENGLISH glosses rather than the Hindi text. We already author
both, the model reasons about meaning either way, and Devanagari costs roughly
four times the tokens — measured, see docs. The server still speaks the Hindi.
"""
from __future__ import annotations

import logging

from core import fragments, kb
from core.naturalness import REACTION_TRIGGERS
from core.questions import EXPANSIONS, S, SUBJECT_SENSITIVE
from core.slots import SKIPPABLE, SLOT_PRIORITY

log = logging.getLogger("sakhi.selector")

T1, T2, KB_TIER, EXPAND = "T1", "T2", "KB", "EXPAND"

# Never offered — these are chosen by code, not by the model.
CODE_OWNED = {"age_invalid"}          # the 18+ gate fires on parsed age alone

# Fragments that are always reasonable to reach for.
# Trimmed from 19 after measuring: the omitted ones were never selected across
# 45 fuzzed non-answers, and every entry costs tokens on every selection call.
ALWAYS = [
    "ack_ok", "ack_noted", "ack_ji",
    "steer_back", "meta_repeat", "meta_no_problem",
    "calm_redirect", "text_mode_offer", "offscript_no_answer", "recover_oh",
]

MAX_MENU = 30


def build_menu(sess, state, current: str | None) -> list[dict]:
    """Responses that make sense RIGHT NOW. Filtering is what keeps the menu
    honest: an option that must not be chosen simply is not offered."""
    lang = sess.language
    menu: list[dict] = []
    seen: set[tuple] = set()

    def add(tier: str, key: str, gloss: str | None):
        if not gloss or (tier, key) in seen or key in CODE_OWNED:
            return
        seen.add((tier, key))
        menu.append({"tier": tier, "key": key, "means": gloss.strip()})

    # 1. The current question — always available, and the subject-aware variant
    #    is what actually gets spoken (part_text resolves it from for_whom).
    if current and current in S.get("en", {}):
        add(T1, current, S["en"][current])
        if current in EXPANSIONS.get(lang, {}) or current in EXPANSIONS.get("en", {}):
            add(EXPAND, current,
                f"EXPLAINS what '{current}' means in plain words — use this "
                f"instead of repeating the question when they did not understand")

    # 2. State-gated options
    if current in SKIPPABLE:
        add(T1, "skip_ack", S["en"].get("skip_ack"))
    pending = state.pending_confirmation() if hasattr(state, "pending_confirmation") else None
    if pending == "gender":
        add(T2, "confirm_gender_male", fragments.text("en", "confirm_gender_male"))
        add(T2, "confirm_gender_female", fragments.text("en", "confirm_gender_female"))
    if current == "dob":
        add(T2, "need_full_dob", fragments.text("en", "need_full_dob"))
    if state.remaining() <= 2:
        add(T1, "almost_done", S["en"].get("almost_done"))

    # 3. Reactions — ONLY for neutral fields, and only for a value just captured.
    #    The trigger table physically cannot contain caste/religion/income/
    #    marital/gender, so a reaction on a sensitive field is unreachable.
    for a in getattr(sess, "_last_accepted", []) or []:
        rk = REACTION_TRIGGERS.get((a.get("key"), a.get("value")))
        if rk:
            add(T2, rk, fragments.text("en", rk))

    # 4. The general-purpose fragments. The gloss says what each is FOR, not
    #    just what it says — "Ah, I see." reads as a generic ack and got picked
    #    for a user who had NOT understood.
    USE_FOR = {
        "recover_oh": "use after a CORRECTION",
        "meta_no_problem": "reassurance when struggling",
        "meta_repeat": "they asked you to repeat",
        "calm_redirect": "after rudeness; never scold",
        "text_mode_offer": "offer the text box",
        "offscript_no_answer": "cannot answer their off-topic question",
        "steer_back": "return to the profile",
    }
    for k in ALWAYS:
        gloss = fragments.text("en", k)
        if k in USE_FOR:
            gloss = f"{gloss} — use {USE_FOR[k]}"
        add(T2, k, gloss)

    # 5. Never offer what we just played — the model is told not to repeat, and
    #    this makes it impossible rather than merely discouraged.
    recent = set(sess.used_fragments[-3:]) if sess.used_fragments else set()
    menu = [m for m in menu
            if m["key"] not in recent or m["tier"] in (T1, EXPAND)]
    return menu[:MAX_MENU]


def menu_keys(menu: list[dict]) -> set[str]:
    return {m["key"] for m in menu}


def render_menu(menu: list[dict]) -> str:
    return "\n".join(f"{m['key']}|{m['tier']}: {m['means']}" for m in menu)


# --------------------------------------------------------------- enforcement
def enforce(sess, state, plan: list[dict], *, current: str | None,
            clarification_n: int, menu: list[dict]) -> tuple[list[dict], list[str]]:
    """Post-conditions applied in CODE. The model proposes; this disposes.
    Returns (plan, notes) — notes are for the funnel log, not the user."""
    notes: list[str] = []
    allowed = menu_keys(menu)

    # a) Only keys we offered. dialogue.validate() also runs later; this is the
    #    tighter, state-aware gate.
    cleaned = []
    for p in plan:
        if not isinstance(p, dict):
            continue
        k, t = p.get("key"), p.get("tier")
        if k in allowed:
            cleaned.append({"tier": t, "key": k})
        else:
            notes.append(f"dropped off-menu:{k}")
    plan = cleaned

    # b) No two consecutive turns may say the same thing. This compares the
    #    WHOLE previous plan across every tier — comparing only T2 fragments let
    #    an identical EXPAND repeat straight through.
    prev = getattr(sess, "last_plan", None) or []
    prev_sig = [(p.get("tier"), p.get("key")) for p in prev]
    if prev_sig and [(p["tier"], p["key"]) for p in plan] == prev_sig:
        # identical turn — escalate instead of echoing
        alt = next((m for m in menu if m["tier"] == EXPAND
                    and (m["tier"], m["key"]) not in prev_sig), None)
        plan = ([{"tier": alt["tier"], "key": alt["key"]}] if alt else []) + \
               [{"tier": T2, "key": "text_mode_offer"}]
        notes.append("identical to previous turn — escalated")
    elif prev_sig and plan and (plan[0]["tier"], plan[0]["key"]) == prev_sig[0]:
        plan = plan[1:]
        notes.append("dropped repeat-of-previous opener")

    # b2) EXPAND already restates the question in plainer words. Following it
    #     with the original T1 says the same thing twice — "profile is for whom,
    #     yourself or someone at home? Who is this profile for — yourself, son,
    #     daughter...". The model picks both because both look relevant; EXPAND
    #     exists precisely to REPLACE the question, so the T1 goes.
    expanded = {p["key"] for p in plan if p["tier"] == EXPAND}
    if expanded:
        before = len(plan)
        plan = [p for p in plan
                if not (p["tier"] == T1 and p["key"] in expanded)]
        if len(plan) != before:
            notes.append("dropped question already restated by EXPAND")

    # c) The clarification ladder must terminate. Three non-answers on the same
    #    question and the text box is offered, whatever the model preferred.
    if clarification_n >= 3 and not any(p["key"] == "text_mode_offer" for p in plan):
        plan = plan + [{"tier": T2, "key": "text_mode_offer"}]
        notes.append("forced text_mode_offer at 3rd clarification")

    # d) A turn that leaves the user with nothing to answer is a dead turn.
    if current and not any(p["tier"] in (T1, EXPAND) for p in plan):
        plan = plan + [{"tier": T1, "key": current}]
        notes.append("appended the question — plan had nothing to answer")

    # e) Sensitive-field rule, defence in depth: the menu cannot offer a
    #    reaction on a sensitive field, and neither can the plan carry one.
    sensitive_reactions = {rk for (f, _v), rk in REACTION_TRIGGERS.items()
                           if f not in ("job", "qualification")}
    before = len(plan)
    plan = [p for p in plan if p["key"] not in sensitive_reactions]
    if len(plan) != before:
        notes.append("dropped reaction on a sensitive field")

    # f) Length: two or three parts is a turn, four is a speech.
    if len(plan) > 3:
        plan = plan[:3]
        notes.append("truncated to 3 parts")

    return plan, notes
