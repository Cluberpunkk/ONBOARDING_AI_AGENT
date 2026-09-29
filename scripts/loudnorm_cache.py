#!/usr/bin/env python3
"""Normalize every CURRENT-hash cache clip to -16 LUFS / -1.5 dBTP.

Idempotent: clips already within ±1 LU are skipped. Short high-crest clips
that linear loudnorm can't lift get a gain + true-peak limiter pass
(the Phase 1 recipe). Only touches clips whose hash matches the live
voice/settings — orphans are ignored.

  python3 scripts/loudnorm_cache.py [--langs hi,en]
"""
from __future__ import annotations
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings               # noqa: E402
from core.cachekey import cache_stem      # noqa: E402
from core.questions import S              # noqa: E402


# EBU R128 integrated loudness gates out material shorter than ~2 s: a 0.3 s
# fragment reads -70 LUFS no matter how loud it actually is. Short clips are
# matched on RMS instead, against the RMS that correctly-normalised long clips
# exhibit at -16 LUFS.
SHORT_CLIP_SEC = 2.0
SHORT_TARGET_RMS = -16.6      # measured mean_volume of the -16 LUFS gold masters
PEAK_CEILING = -1.6


def duration(f) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", str(f)], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def rms_peak(f) -> tuple[float, float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f),
                        "-af", "volumedetect", "-f", "null", "-"],
                       capture_output=True, text=True)
    rms = re.findall(r"mean_volume:\s+(-?[\d.]+) dB", r.stderr)
    peak = re.findall(r"max_volume:\s+(-?[\d.]+) dB", r.stderr)
    return (float(rms[0]) if rms else 0.0, float(peak[0]) if peak else 0.0)


def measure(f):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f),
                        "-filter:a", "ebur128=peak=true", "-f", "null", "-"],
                       capture_output=True, text=True)
    return (float(re.findall(r"I:\s+(-?[\d.]+) LUFS", r.stderr)[-1]),
            float(re.findall(r"Peak:\s+(-?[\d.]+) dBFS", r.stderr)[-1]))


def normalize_short(f: Path) -> tuple[float, float]:
    """RMS-match a sub-2s clip and hold the true-peak ceiling."""
    rms, peak = rms_peak(f)
    gain = min(SHORT_TARGET_RMS - rms, PEAK_CEILING - peak)
    if abs(gain) < 0.1:
        return rms, peak
    tmp = f.with_suffix(".s.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(f),
                    # NB: alimiter's limit is linear amplitude; the signed dB form
                    # converts correctly (-1.6dB -> 0.83). abs() would give 1.2 = out of range.
                    "-af", f"volume={gain:.2f}dB,alimiter=limit={PEAK_CEILING}dB:level=false",
                    "-ar", "44100", "-b:a", "128k", str(tmp), "-y"], check=True)
    tmp.rename(f)
    return rms_peak(f)


def normalize(f: Path) -> tuple[float, float]:
    r = subprocess.run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(f),
                        "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                        "-f", "null", "-"], capture_output=True, text=True)
    stats = json.loads(r.stderr[r.stderr.rfind("{"):r.stderr.rfind("}") + 1])
    af = ("loudnorm=I=-16:TP=-1.5:LRA=11:"
          f"measured_I={stats['input_i']}:measured_TP={stats['input_tp']}:"
          f"measured_LRA={stats['input_lra']}:measured_thresh={stats['input_thresh']}:"
          f"offset={stats['target_offset']}:linear=true")
    tmp = f.with_suffix(".n.mp3")
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(f), "-af", af,
                    "-ar", "44100", "-b:a", "128k", str(tmp), "-y"], check=True)
    tmp.rename(f)
    lufs, peak = measure(f)
    need = -16.0 - lufs
    if need > 1.0:   # peak-limited short clip: gain + limiter
        tmp = f.with_suffix(".l.mp3")
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(f),
                        "-af", f"volume={need:.2f}dB,alimiter=limit=-1.6dB:level=false",
                        "-ar", "44100", "-b:a", "128k", str(tmp), "-y"], check=True)
        tmp.rename(f)
        lufs, peak = measure(f)
    return lufs, peak


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--langs", default=",".join(S.keys()))
    args = ap.parse_args()
    langs = [l.strip() for l in args.langs.split(",") if l.strip()]

    vals, fixed, skipped, missing = [], 0, 0, 0
    for lang in langs:
        for key, text in S[lang].items():
            f = settings.TTS_CACHE_DIR / f"{cache_stem(text, lang)}.mp3"
            if not f.exists():
                missing += 1
                print(f"  MISSING {lang}/{key}")
                continue
            lufs, _ = measure(f)
            if abs(lufs + 16) <= 1.0:
                skipped += 1
                vals.append(lufs)
                continue
            lufs, peak = normalize(f)
            fixed += 1
            vals.append(lufs)
            print(f"  {lang}/{key:<14} -> {lufs:6.1f} LUFS (peak {peak:.1f})")
    off = sum(1 for v in vals if abs(v + 16) > 1.0)
    print(f"\nnormalized {fixed}, already-good {skipped}, missing {missing}, "
          f"still outside ±1 LU: {off}")


if __name__ == "__main__":
    main()
