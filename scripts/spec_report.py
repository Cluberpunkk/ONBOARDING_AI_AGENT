#!/usr/bin/env python3
"""
Curation backlog for agent/SAKHI.md §5 and the KB.

Reads the live gap logs and prints what users actually said that we did not
handle. This is the intended input to spec updates (see §10).

  python3 scripts/spec_report.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.system_prompt import (approx_tokens, compile_base, constitution_rules,
                                 governance_text, spec_sections)   # noqa: E402
from core import kb                                                # noqa: E402
from core.session import stats                                     # noqa: E402


def main():
    print("=" * 68)
    print("SAKHI SPEC REPORT")
    print("=" * 68)

    print("\n-- spec sections --")
    for num, s in spec_sections().items():
        tag = "compiled" if s["compiled"] else "        "
        print(f"  {num:<4} {tag}  {s['chars']:>5} chars  {s['title'].replace('`[compiled]`','').strip()}")
    base = compile_base()
    print(f"\n  latency-path prompt : {len(base)} chars ~{approx_tokens(base)} tokens")
    print(f"  governance (not sent): ~{approx_tokens(governance_text())} tokens")

    print("\n-- constitution --")
    for r in constitution_rules():
        print(f"  {r['id']}  {r['rule'][:58]:<58} {', '.join(r['tests'])}")

    print("\n-- KB gaps (questions we could not answer) --")
    g = kb.gaps(limit=15)
    print(f"  {g['total']} unanswered side questions logged")
    if not g["top_unanswered"]:
        print("  (none yet — run some sessions)")
    for row in g["top_unanswered"]:
        print(f"   x{row['count']:<3} {row['question'][:60]}")
    print("  -> each recurring question is a candidate KB entry")

    print("\n-- most-clarified questions (copy-quality signal) --")
    st = stats()
    rows = [(k, v.get("clarification_requests", 0), v.get("clarify_rate", 0))
            for k, v in st.get("per_question", {}).items()]
    rows = [r for r in rows if r[1] or r[2]]
    if not rows:
        print("  (no clarifications recorded in this process)")
    for k, c, rate in sorted(rows, key=lambda r: -r[1])[:10]:
        print(f"   {k:<15} clarifications={c:<4} clarify_rate={rate}")
    print("  -> a frequently clarified question is a badly worded question")
    print("\n" + "=" * 68)


if __name__ == "__main__":
    main()
