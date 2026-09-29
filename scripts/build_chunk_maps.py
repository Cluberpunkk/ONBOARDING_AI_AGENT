#!/usr/bin/env python3
"""
Sentence-chunk maps for barge-in resume — zero API cost.

The clips already exist, so sentence boundaries are found with ffmpeg
`silencedetect` on the inter-sentence pauses. When Sakhi is interrupted we
resume from the START of the sentence she was cut off in, never mid-word —
which is what a human does.

Output: data/chunk_maps.json
    { "<cache_stem>": [ {"i":0,"start":0.0,"end":3.42,"text":"..."}, ... ] }

  python3 scripts/build_chunk_maps.py                 # build all cached lines
  python3 scripts/build_chunk_maps.py --verify        # print the anchor maps
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                     # noqa: E402
from core.cachekey import cache_stem            # noqa: E402
from core.fragments import FRAGMENTS            # noqa: E402
from core.questions import S                    # noqa: E402
from core import kb                             # noqa: E402

OUT = settings.DATA_DIR / "chunk_maps.json"
ANCHORS = ["intro", "for_whom", "photo", "review"]

# Detect PERMISSIVELY, then rank. In this voice a sentence pause (~0.14-0.29 s)
# is barely longer than a comma pause (~0.12 s), so a strict duration threshold
# either swallows real boundaries or keeps intra-sentence ones. Collect every
# candidate at d=0.10 and keep the (n_sentences - 1) longest.
NOISE_DB = -30
MIN_SILENCE = 0.10

# A boundary set is only trusted if each chunk's share of the runtime is close
# to its sentence's share of the characters. A 0.5 s chunk holding a 30-char
# sentence means the split is wrong — better to replay the whole clip than to
# resume from the wrong place.
MAX_SHARE_ERROR = 0.18

SENTENCE_END = re.compile(r"(?<=[।?!])\s+|(?<=\.)\s+(?=[A-Zऀ-෿])")


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_END.split(text or "") if p and p.strip()]
    return parts or [text]


def duration(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def silences(path: Path) -> list[tuple[float, float]]:
    r = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
         "-af", f"silencedetect=noise={NOISE_DB}dB:d={MIN_SILENCE}", "-f", "null", "-"],
        capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start:\s*(-?[\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*(-?[\d.]+)", r.stderr)]
    return list(zip(starts, ends))


def chunk_map(path: Path, text: str) -> dict:
    """Boundaries land at the START of each sentence — the resume point."""
    total = duration(path)
    sents = split_sentences(text)
    need = len(sents) - 1

    gaps = [(s, e) for s, e in silences(path) if s > 0.15 and e < total - 0.05]
    # Pick the gap nearest each EXPECTED boundary position (cumulative share of
    # characters x duration). Ranking purely by pause length picks the most
    # dramatic pause, which is often mid-sentence; position-matching picks the
    # one that actually separates the sentences. need == 0 keeps none — a comma
    # pause is not a resume point.
    if need <= 0:
        gaps = []
    elif len(gaps) > need:
        chars = sum(len(s) for s in sents) or 1
        chosen, cum, pool = [], 0, list(gaps)
        for s in sents[:-1]:
            cum += len(s)
            want = (cum / chars) * total
            best = min(pool, key=lambda g: abs(g[1] - want))
            chosen.append(best)
            pool.remove(best)
        gaps = sorted(chosen)
    starts = [0.0] + [e for _s, e in gaps]
    bounds = starts + [total]

    chunks = []
    for i in range(len(starts)):
        chunks.append({
            "i": i,
            "start": round(bounds[i], 3),
            "end": round(bounds[i + 1], 3),
            "text": sents[i] if i < len(sents) else "",
        })

    aligned = len(chunks) == len(sents)
    # One-sided safety net: a chunk that is too SHORT for its text means the
    # boundary landed late and the resume point is wrong. A chunk that is too
    # LONG is just a dramatic pause before the next sentence — harmless.
    worst = 0.0
    if aligned and total > 0 and len(chunks) > 1:
        chars = sum(len(s) for s in sents) or 1
        for c, s in zip(chunks, sents):
            deficit = (len(s) / chars) - ((c["end"] - c["start"]) / total)
            worst = max(worst, deficit)
    resume_safe = aligned and worst <= MAX_SHARE_ERROR

    return {
        "duration": round(total, 3),
        "sentences": len(sents),
        "chunks": chunks,
        "aligned": aligned,
        "share_error": round(worst, 3),
        # False -> the frontend replays the whole clip instead of seeking.
        "resume_safe": resume_safe or len(chunks) == 1,
    }


def all_lines(lang: str):
    for key, text in S[lang].items():
        yield ("T1", key, text)
    for key, text in FRAGMENTS[lang].items():
        yield ("T2", key, text)
    for key in kb.KB_KEYS:
        yield ("KB", key, kb.text(lang, key))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="hi")
    ap.add_argument("--verify", action="store_true",
                    help="print the anchor maps for human inspection")
    args = ap.parse_args()

    maps, built, missing, misaligned = {}, 0, 0, []
    for tier, key, text in all_lines(args.lang):
        stem = cache_stem(text, args.lang)
        path = settings.TTS_CACHE_DIR / f"{stem}.mp3"
        if not path.exists():
            missing += 1
            continue
        m = chunk_map(path, text)
        m["key"], m["tier"], m["lang"] = key, tier, args.lang
        maps[stem] = m
        built += 1
        if not m["aligned"]:
            misaligned.append(f"{tier}/{key} ({len(m['chunks'])} chunks vs {m['sentences']} sentences)")

    OUT.write_text(json.dumps(maps, ensure_ascii=False, indent=1), encoding="utf-8")
    multi = sum(1 for m in maps.values() if len(m["chunks"]) > 1)
    print(f"chunk maps: {built} lines ({multi} multi-sentence), {missing} uncached -> {OUT}")
    if misaligned:
        print(f"MISALIGNED ({len(misaligned)}): {misaligned[:6]}")

    if args.verify:
        print("\n" + "=" * 78)
        print("ANCHOR CHUNK VALIDATION — every boundary must be a sentence start")
        print("=" * 78)
        for key in ANCHORS:
            text = S[args.lang][key]
            m = maps.get(cache_stem(text, args.lang))
            if not m:
                print(f"\n{key}: NOT CACHED")
                continue
            flag = "OK" if m["aligned"] else "MISALIGNED"
            print(f"\n{key}  [{m['duration']}s, {len(m['chunks'])} chunks / "
                  f"{m['sentences']} sentences — {flag}]")
            for c in m["chunks"]:
                print(f"   #{c['i']}  {c['start']:>6.2f}s -> {c['end']:>6.2f}s  "
                      f"({c['end']-c['start']:>5.2f}s)  {c['text']}")


if __name__ == "__main__":
    main()
