#!/usr/bin/env python3
"""
Kill onset artifacts in every cached clip — free, no regeneration.

Two defects diagnosed in the generated audio:
  1. HARD START — some clips begin at full amplitude on sample 0. With no ramp
     that is a step discontinuity: a click/rasp on every playback.
  2. BREATH ONSET — some clips carry non-speech energy (an intake breath) before
     the first phoneme.

Normalisation made both worse: short clips get a flat volume boost that lifts a
breath exactly as much as speech, while the true-peak limiter compresses the
SPEECH peaks — raising the breath's relative level.

Fix: trim the non-speech lead (keeping a 10 ms cushion so nothing clips the
first phoneme), then apply a short fade-in to every clip. Re-normalise after,
since trimming changes the measured level.

  python3 scripts/fix_onsets.py --dry-run
  python3 scripts/fix_onsets.py
"""
from __future__ import annotations

import argparse
import math
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                        # noqa: E402
from core.cachekey import cache_stem               # noqa: E402
from core.fragments import FRAGMENTS               # noqa: E402
from core.questions import S, SUBJECT_VARIANTS, EXPANSIONS   # noqa: E402
from core import kb                                # noqa: E402

FADE_MS = 20            # long enough to kill the transient, short enough to be inaudible
LEAD_CUSHION_MS = 10    # keep this much before the first phoneme
FRAME_MS = 10
SPEECH_FRACTION = 0.25  # a frame is "speech" at 25% of the clip's peak frame energy
MIN_TRIM_MS = 30        # don't bother trimming less than this


def head_pcm(path: Path, ms: int = 600):
    out = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-t", str(ms / 1000),
                          "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True).stdout
    n = len(out) // 2
    return [struct.unpack_from("<h", out, i * 2)[0] / 32768.0 for i in range(n)]


def speech_onset_ms(path: Path) -> tuple[int, float]:
    """(ms before the first speech frame, lead energy as a fraction of peak)."""
    x = head_pcm(path)
    size = int(16000 * FRAME_MS / 1000)
    frames = [x[i:i + size] for i in range(0, max(0, len(x) - size), size)]
    if not frames:
        return 0, 0.0
    energies = [math.sqrt(sum(v * v for v in f) / len(f)) for f in frames]
    peak = max(energies) or 1.0
    thresh = peak * SPEECH_FRACTION
    onset = next((i for i, e in enumerate(energies) if e >= thresh), 0)
    lead = max(energies[:onset], default=0.0) / peak
    return onset * FRAME_MS, lead


def all_cached(lang="hi"):
    seen = set()
    def add(tag, key, text):
        if not text:
            return
        stem = cache_stem(text, lang)
        f = settings.TTS_CACHE_DIR / f"{stem}.mp3"
        if f.exists() and stem not in seen:
            seen.add(stem)
            yield f"{tag}/{key}", f
    for k, t in S[lang].items():
        yield from add("T1", k, t)
    for k, t in FRAGMENTS.get(lang, {}).items():
        yield from add("T2", k, t)
    for k in kb.KB_KEYS:
        yield from add("KB", k, kb.text(lang, k))
    for subj, qs in SUBJECT_VARIANTS.get(lang, {}).items():
        for k, t in qs.items():
            yield from add(f"VAR:{subj}", k, t)
    for k, t in EXPANSIONS.get(lang, {}).items():
        yield from add("EXPAND", k, t)


def fix(path: Path, trim_ms: int):
    af = []
    if trim_ms >= MIN_TRIM_MS:
        af.append(f"atrim=start={trim_ms/1000:.3f}")
        af.append("asetpts=PTS-STARTPTS")
    af.append(f"afade=t=in:st=0:d={FADE_MS/1000:.3f}")
    tmp = path.with_suffix(".o.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-af", ",".join(af),
                    "-ar", "44100", "-b:a", "128k", str(tmp), "-y"], check=True)
    tmp.rename(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", default="hi")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    import importlib.util
    spec = importlib.util.spec_from_file_location("ln", Path(__file__).parent / "loudnorm_cache.py")
    ln = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ln)

    clips = list(all_cached(args.lang))
    trimmed = faded = 0
    print(f"{'clip':<26} {'lead':>7} {'lead%':>7}  action")
    for name, f in clips:
        onset, lead = speech_onset_ms(f)
        cut = onset - LEAD_CUSHION_MS
        will_trim = cut >= MIN_TRIM_MS and lead > 0.05
        action = f"trim {cut}ms + fade" if will_trim else f"fade {FADE_MS}ms"
        if will_trim or onset == 0:
            print(f"{name:<26} {onset:>6}ms {lead:>6.0%}  {action}")
        if args.dry_run:
            continue
        fix(f, cut if will_trim else 0)
        trimmed += int(will_trim)
        faded += 1
        # trimming/fading changes the measured level — renormalise
        if ln.duration(f) < 3.0:
            ln.normalize_short(f)
        else:
            lufs, _ = ln.measure(f)
            if abs(lufs + 16) > 1.0:
                ln.normalize(f)

    if args.dry_run:
        print(f"\nDRY RUN: {len(clips)} clips would get a {FADE_MS}ms fade-in")
        return
    print(f"\n{faded} clips faded, {trimmed} also had a breath/lead trimmed, all renormalised")


if __name__ == "__main__":
    main()
