"""
Compiles agent/SAKHI.md into the one system prompt every LLM call site shares.

DRIFT IS STRUCTURALLY IMPOSSIBLE: the prompt is parsed from the document at
import time. There is no second copy to fall out of sync. Sections tagged
`[compiled]` in their heading are included; everything else (changelog, prose
for humans) is not, which keeps the latency-path prompt lean.

THE CONSTRAINT, RESTATED: this prompt shapes INTERPRETATION only. It must never
contain instructions to address the user. Every call site returns structured
output; core.dialogue.validate() discards anything else. compile_base() asserts
the document has not acquired conversational language.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

SPEC_PATH = Path(__file__).parent / "SAKHI.md"

# Sections whose heading carries the [compiled] tag are sent to the model.
COMPILED_TAG = "[compiled]"

# Language that would turn an interpretation prompt into a speaking prompt.
# If any of these appear in a compiled section the build fails loudly.
FORBIDDEN_IN_PROMPT = [
    "respond to the user", "reply to the user", "say to the user",
    "your response should", "answer the user in", "generate a response",
    "write a reply", "compose a",
]

_HEADING = re.compile(r"^##\s+(§\d+)\s+(.+?)\s*$", re.M)


def _sections() -> list[tuple[str, str, str]]:
    """[(number, title, body)] for every §-section in the document."""
    text = SPEC_PATH.read_text(encoding="utf-8")
    marks = list(_HEADING.finditer(text))
    out = []
    for i, m in enumerate(marks):
        body_start = m.end()
        body_end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), m.group(2).strip(), text[body_start:body_end].strip()))
    return out


def _strip_markdown(s: str) -> str:
    """Tables, bold and bullets cost tokens and add nothing for the model."""
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"\*\*([^*]*)\*\*", r"\1", s)
    s = re.sub(r"^\s*\|.*\|\s*$", lambda m: _row_to_line(m.group(0)), s, flags=re.M)
    s = re.sub(r"^\s*\|?[-: ]+\|[-:| ]*$", "", s, flags=re.M)   # table rules
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def _row_to_line(row: str) -> str:
    cells = [c.strip() for c in row.strip().strip("|").split("|")]
    cells = [c for c in cells if c and not set(c) <= set("-: ")]
    return "- " + " — ".join(cells) if cells else ""


# MEASURED SPLIT (see §10 changelog and tests/test_agent_spec.py):
# running the extraction fixtures three ways showed the persona/constitution
# sections cost ~740 tokens and changed extraction accuracy by ZERO — they are
# enforced in code and tests, not by asking the model nicely. The domain
# sections are what move the numbers. So the latency-path prompt carries the
# INTERPRETIVE sections; the governance sections stay authored, reviewable and
# test-enforced. One source of truth either way: nothing is duplicated inline.
# §6 (examples) dropped from the latency path after §7 made the selection
# role explicit — measured no fixture regression, ~250 tokens saved.
# §7 is the RESPONSE-SELECTION role. It is only sent on turns that actually
# select — i.e. when a menu is offered. Sending it on extraction-only turns cost
# ~180 tokens and ~150 ms of p50 to teach a skill the call could not use.
INTERPRETIVE = ()                      # §5 per-slot, §7 only when selecting
SELECTION = ("§7",)
GOVERNANCE = ("§1", "§2", "§3", "§4", "§6")  # authored + test-enforced, not sent

_HEAD = ("You extract structured facts for Sakhi, a matrimony-profile voice agent "
         "in India. You never write text for the user to hear — you only extract, "
         "classify and select keys. Any free text you produce is discarded.")


def _render(nums) -> str:
    out = []
    for num, title, body in _sections():
        if num not in nums or COMPILED_TAG not in title:
            continue
        out.append(f"## {title.replace(COMPILED_TAG, '').strip(' `')}\n{_strip_markdown(body)}")
    return "\n\n".join(out)


@lru_cache(maxsize=2)
def compile_base(selecting: bool = False) -> str:
    """The shared block every LLM call site prepends. Parsed from SAKHI.md, so
    editing the document changes every call site at once.

    `selecting` adds the response-selection role — only for calls that are
    handed a menu. Extraction-only turns do not pay for it."""
    sections = INTERPRETIVE + (SELECTION if selecting else ())
    prompt = f"{_HEAD}\n\n{_render(sections)}".strip()
    low = prompt.lower()
    bad = [p for p in FORBIDDEN_IN_PROMPT if p in low]
    if bad:
        raise RuntimeError(
            "agent/SAKHI.md has acquired conversational instructions "
            f"({bad}). This prompt governs interpretation only — the server owns "
            "every string the user hears. Remove them from the [compiled] sections.")
    return prompt


@lru_cache(maxsize=1)
def governance_text() -> str:
    """Identity/mission/principles/constitution. Not sent to the model — it is
    enforced by the validator, the guardrails and the constitution tests. Exposed
    so those tests can read the rules from the same document a human edits."""
    return _render(GOVERNANCE)


def constitution_rules() -> list[dict]:
    """Parse the §4 table into {id, rule, tests}. The build fails if any rule
    has no passing test behind it."""
    body = next((b for n, _t, b in _sections() if n == "§4"), "")
    rules = []
    for line in body.splitlines():
        if not line.strip().startswith("| C"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        tests = [t.strip(" `") for t in cells[2].split(",") if t.strip()]
        rules.append({"id": cells[0], "rule": cells[1], "tests": tests})
    return rules


_SLOT_TAG = re.compile(r"<!--slots:([^>]*)-->")


def _domain_for(slot: str | None) -> str:
    """Only the domain rules that can apply to THIS slot. Sending all of §5 on
    every turn cost ~700 tokens to restate rules about income while asking for
    a name. Untagged paragraphs are always included."""
    body = next((b for n, _t, b in _sections() if n == "§5"), "")
    out = []
    for para in body.split("\n\n"):
        m = _SLOT_TAG.search(para)
        if m:
            slots = {x.strip() for x in m.group(1).split(",") if x.strip()}
            if slot and slot not in slots:
                continue
            if not slot:
                continue
        out.append(_SLOT_TAG.sub("", para))
    return _strip_markdown("\n\n".join(out))


def compile_for(task: str, slot: str | None = None,
                selecting: bool = False) -> str:
    """Shared base + slot-scoped domain rules + the task instruction."""
    domain = _domain_for(slot)
    parts = [compile_base(selecting)]
    if domain:
        parts.append(f"## Domain rules for this field\n{domain}")
    parts.append(f"## Your task now\n{task.strip()}")
    return "\n\n".join(parts)


def approx_tokens(s: str) -> int:
    """Cheap estimate — Devanagari runs ~1 token/char, Latin ~1 per 4."""
    deva = sum(1 for c in s if "ऀ" <= c <= "ॿ")
    return int(deva + (len(s) - deva) / 4)


def spec_sections() -> dict:
    return {num: {"title": t, "compiled": COMPILED_TAG in t, "chars": len(b)}
            for num, t, b in _sections()}


if __name__ == "__main__":
    base = compile_base()
    print(base)
    print("\n" + "=" * 60)
    print(f"compiled sections: "
          f"{[n for n, s in spec_sections().items() if s['compiled']]}")
    print(f"base prompt: {len(base)} chars, ~{approx_tokens(base)} tokens")
