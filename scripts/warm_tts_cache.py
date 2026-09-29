#!/usr/bin/env python3
"""
Warm the full TTS cache: every system string x every language, through the
existing cached path (core.tts.synthesize). After this, runtime NEVER calls
ElevenLabs during a session — audio is served from disk.

  python3 scripts/warm_tts_cache.py --dry-run          # lines/chars/credit estimate, $0
  python3 scripts/warm_tts_cache.py                    # warm everything missing
  python3 scripts/warm_tts_cache.py --langs hi,ta      # subset

Skip-existing is inherent: synthesize() returns the cached file untouched.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings               # noqa: E402
from core import tts                      # noqa: E402
from core.cachekey import cache_stem      # noqa: E402
from core.questions import S              # noqa: E402

ALL_LANGS = list(S.keys())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--langs", default=",".join(ALL_LANGS))
    args = ap.parse_args()

    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    for l in langs:
        if l not in ALL_LANGS:
            sys.exit(f"Unknown language: {l}")

    jobs = []
    for lang in langs:
        for key, text in S[lang].items():
            cached = (settings.TTS_CACHE_DIR / f"{cache_stem(text, lang)}.mp3").exists()
            jobs.append({"lang": lang, "key": key, "text": text, "cached": cached})
    todo = [j for j in jobs if not j["cached"]]
    total_chars = sum(len(j["text"]) for j in todo)

    per_lang = {}
    for j in todo:
        per_lang[j["lang"]] = per_lang.get(j["lang"], 0) + len(j["text"])
    print(f"Lines: {len(jobs)} total, {len(todo)} to generate, {len(jobs)-len(todo)} cached")
    for lang in langs:
        n = sum(1 for j in todo if j["lang"] == lang)
        print(f"  {lang}: {n:>2} lines, {per_lang.get(lang, 0):>5} chars")
    print(f"\nTotal characters: {total_chars}")
    print(f"Estimated credits: ~{total_chars} (assuming 1 credit/char)")
    print(f"Voice: {settings.ELEVENLABS_VOICE_ID}  model: {settings.ELEVENLABS_MODEL}  "
          f"settings: {tts.voice_settings()}")

    if args.dry_run:
        print("\nDry run — nothing generated.")
        return
    if not settings.tts_enabled:
        sys.exit("ELEVENLABS keys not configured")

    ok = failed = 0
    failures = []
    t0 = time.time()
    for i, j in enumerate(todo, 1):
        fname = tts.synthesize(j["text"], j["lang"])
        if fname:
            ok += 1
            print(f"[{i}/{len(todo)}] {j['lang']}/{j['key']} -> {fname}")
        else:
            failed += 1
            failures.append(f"{j['lang']}/{j['key']}")
            print(f"[{i}/{len(todo)}] {j['lang']}/{j['key']} -> FAILED")
        time.sleep(0.3)   # gentle on rate limits

    print(f"\n===== SUMMARY =====")
    print(f"generated : {ok}")
    print(f"skipped   : {len(jobs) - len(todo)} (already cached)")
    print(f"failed    : {failed}" + (f"  -> {failures}" if failures else ""))
    print(f"time      : {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()
