#!/usr/bin/env python3
"""
Generate T2 conversational fragments at the locked voice recipe.

Safety: KB answers are BLOCKED while any factual claim is unsigned
(core.kb.unverified_keys()). Fragments carry no product claims, so they
generate freely. High-frequency fragments get 3 takes for the same
gold-master curation workflow used for the T1 questions.

  python3 scripts/build_fragments.py --dry-run
  python3 scripts/build_fragments.py --go
  python3 scripts/build_fragments.py --go --kb        # only after sign-off
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                     # noqa: E402
from core import kb                             # noqa: E402
from core.cachekey import cache_stem            # noqa: E402
from core.fragments import FRAGMENTS            # noqa: E402

TAKES_DIR = Path("samples/takes_fragments")

# Spoken on nearly every turn — worth curating by ear.
HIGH_FREQUENCY = [
    "ack_ok", "ack_good", "ack_noted", "ack_understood", "ack_right", "ack_ji",
    "batch_confirm", "steer_back", "bridge_next", "interrupt_ack",
    "confirm_gender_male", "confirm_gender_female",
]


def jobs(lang: str, include_kb: bool):
    out = []
    for key, text in FRAGMENTS[lang].items():
        # Once a winning take is promoted into the cache, the losing takes are
        # deleted on purpose. Never regenerate them — that is pure wasted spend.
        promoted = (settings.TTS_CACHE_DIR / f"{cache_stem(text, lang)}.mp3").exists()
        takes = 3 if (key in HIGH_FREQUENCY and not promoted) else 1
        out.append({"kind": "T2", "key": key, "text": text, "takes": takes})
    if include_kb:
        blocked = set(kb.unverified_keys())
        for key in kb.KB_KEYS:
            if key in blocked:
                continue
            out.append({"kind": "KB", "key": key, "text": kb.text(lang, key), "takes": 1})
    return out


def synth(text: str, out_path: Path):
    import httpx
    r = httpx.post(
        f"{settings.ELEVENLABS_BASE_URL}/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}",
        params={"output_format": "mp3_44100_128"},
        headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
        json={"text": text, "model_id": settings.ELEVENLABS_MODEL,
              "voice_settings": {"stability": settings.ELEVENLABS_STABILITY,
                                 "similarity_boost": settings.ELEVENLABS_SIMILARITY,
                                 "style": settings.ELEVENLABS_STYLE,
                                 "speed": settings.ELEVENLABS_SPEED}},
        timeout=60,
    )
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="hi")
    ap.add_argument("--go", action="store_true")
    ap.add_argument("--kb", action="store_true", help="include signed-off KB answers")
    args = ap.parse_args()

    blocked = kb.unverified_keys()
    if args.kb and blocked:
        sys.exit(f"BLOCKED: {len(blocked)} KB entries still unsigned — "
                 f"fill docs/kb_claims_signoff.md first.\n{blocked}")

    work = jobs(args.lang, include_kb=args.kb)
    single = sum(len(j["text"]) for j in work)
    extra = sum(len(j["text"]) * (j["takes"] - 1) for j in work)
    files = sum(j["takes"] for j in work)

    print(f"lang={args.lang}  items={len(work)}  files={files}")
    print(f"  single-take chars : {single}")
    print(f"  extra-take chars  : {extra}  ({len([j for j in work if j['takes']>1])} items x3)")
    print(f"  TOTAL CHARS       : {single + extra}")
    if blocked:
        print(f"  KB answers held   : {len(blocked)} unsigned (not included)")
    if not args.go:
        print("\nEstimate only. Re-run with --go.")
        return

    ok = fail = 0
    for i, j in enumerate(work, 1):
        for t in range(1, j["takes"] + 1):
            if j["takes"] > 1:
                dest = TAKES_DIR / f"{j['key']}__t{t}.mp3"
            else:
                dest = settings.TTS_CACHE_DIR / f"{cache_stem(j['text'], args.lang)}.mp3"
            if dest.exists():
                continue
            try:
                synth(j["text"], dest)
                ok += 1
            except Exception as e:
                fail += 1
                print(f"  FAIL {j['key']} t{t}: {str(e)[:120]}")
            time.sleep(0.35)
        print(f"[{i}/{len(work)}] {j['kind']} {j['key']} x{j['takes']}")
    print(f"\ngenerated {ok}, failed {fail}")
    print("High-frequency takes -> samples/takes_fragments/ (pick winners, then promote)")


if __name__ == "__main__":
    main()
