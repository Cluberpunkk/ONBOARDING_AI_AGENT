#!/usr/bin/env python3
"""
Sakhi voice lab — generate an A/B sample matrix so the final voice is picked by EAR.

Matrix: voices x settings-profiles x models x test-lines -> samples/*.mp3
Default run prints the character/credit estimate and exits.
Real generation only with --go (gated on explicit approval in chat).

  python3 scripts/voice_lab.py           # estimate only, $0
  python3 scripts/voice_lab.py --go      # generate the samples
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings               # noqa: E402
from core.questions import S              # noqa: E402

SAMPLES_DIR = Path("samples")

VOICES = {
    "riya":    "e6h2ged6ThVk1jTnIwnC",   # original .env voice: "Riya Rao - Elegant Ad Narration"
    "akshita": "9SsFrOutdZkCkU5hIoQm",   # user candidate: "Akshita - Cute & Romantic AI Girlfriend"
    "tara":    "PId0lEbL3SOYkQZSraml",   # user candidate 2: "Tara - Love Story & Romance Narrator"
}

PROFILES = {
    "warm":   {"stability": 0.40, "similarity_boost": 0.80, "style": 0.40, "speed": 0.92},
    "steady": {"stability": 0.65, "similarity_boost": 0.80, "style": 0.15, "speed": 0.97},
}

MODELS = ["eleven_v3", "eleven_v4"]

LINES = {
    "hi_intro":  ("hi", S["hi"]["intro"]),
    "hi_income": ("hi", S["hi"]["income"]),
    "ta_intro":  ("ta", S["ta"]["intro"]),
}


def snap_for_model(profile: dict, model: str) -> dict:
    """eleven_v3 only accepts stability 0.0 / 0.5 / 1.0."""
    p = dict(profile)
    if model.startswith("eleven_v3"):
        p["stability"] = min((0.0, 0.5, 1.0), key=lambda v: abs(v - p["stability"]))
    return p


def matrix() -> list[dict]:
    out = []
    for vtag, vid in VOICES.items():
        for ptag, prof in PROFILES.items():
            for model in MODELS:
                for ltag, (lang, text) in LINES.items():
                    mtag = model.replace("eleven_", "")
                    out.append({
                        "file": SAMPLES_DIR / f"{ltag}__{vtag}__{ptag}__{mtag}.mp3",
                        "voice_id": vid, "model": model, "lang": lang,
                        "text": text, "settings": snap_for_model(prof, model),
                    })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--go", action="store_true", help="actually generate (spends credits)")
    args = ap.parse_args()

    jobs = matrix()
    todo = [j for j in jobs if not j["file"].exists()]
    total_chars = sum(len(j["text"]) for j in todo)

    print(f"Matrix: {len(VOICES)} voices x {len(PROFILES)} profiles x {len(MODELS)} models "
          f"x {len(LINES)} lines = {len(jobs)} samples ({len(jobs)-len(todo)} already on disk)")
    for j in todo:
        print(f"  {j['file'].name:<44} {len(j['text']):>4} chars")
    print(f"\nTotal characters: {total_chars}")
    print(f"Estimated credits: ~{total_chars} (assuming 1 credit/char; check your tier's multiplier)")

    if not args.go:
        print("\nEstimate only — nothing generated. Re-run with --go after approval.")
        return
    if not settings.tts_enabled:
        sys.exit("ELEVENLABS keys not configured")

    import httpx
    SAMPLES_DIR.mkdir(exist_ok=True)
    ok = failed = 0
    for i, j in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {j['file'].name} ... ", end="", flush=True)
        try:
            r = httpx.post(
                f"{settings.ELEVENLABS_BASE_URL}/v1/text-to-speech/{j['voice_id']}",
                params={"output_format": "mp3_44100_128"},
                headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
                json={"text": j["text"], "model_id": j["model"], "voice_settings": j["settings"]},
                timeout=60,
            )
            r.raise_for_status()
            j["file"].write_bytes(r.content)
            print("ok")
            ok += 1
        except Exception as e:
            print(f"FAILED: {str(e)[:160]}")
            failed += 1
        time.sleep(0.4)   # gentle on rate limits
    print(f"\ndone — {ok} generated, {failed} failed -> {SAMPLES_DIR}/")


if __name__ == "__main__":
    main()
