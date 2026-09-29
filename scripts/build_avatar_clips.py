#!/usr/bin/env python3
"""
Batch builder for Sakhi's pre-rendered lipsync clips.

THE ONLY FILE IN THIS CODEBASE ALLOWED TO CALL fal.ai.
Runtime code must never import it — clips are served from disk forever.

Pipeline per clip:
  ensure mp3 via core.tts.synthesize() (cached)
  -> upload drive video (once per run) + mp3 to fal storage
  -> submit lipsync job on the queue API, poll until done
  -> download result, ffprobe-verify video+audio streams
  -> mux the mp3 in (-c:v copy) if the model returned silent video
  -> write data/avatar_cache/<stem>.mp4 + update manifest.json

Mandatory safety sequence (see README / docs/avatar_layer.md):
  1. --dry-run first — approve the cost in chat.
  2. ONE clip: --langs hi --keys intro --limit 1 — review quality.
  3. Only after explicit approval: the full batch (needs --confirm).

Skip-existing is the default: re-running with a full cache costs $0.

Usage:
  python scripts/build_avatar_clips.py --dry-run [--langs hi,en] [--keys intro]
  python scripts/build_avatar_clips.py --langs hi --keys intro --limit 1
  python scripts/build_avatar_clips.py --langs hi --confirm
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings                       # noqa: E402  (loads .env)
from core import tts                              # noqa: E402
from core.cachekey import cache_stem              # noqa: E402
from core.questions import S                      # noqa: E402

DRIVE_VIDEO = Path("assets/sakhi_drive.mp4")
CACHE_DIR = settings.AVATAR_CACHE_DIR
MANIFEST = CACHE_DIR / "manifest.json"

ALL_LANGS = list(S.keys())
ALL_KEYS = list(S["en"].keys())

# Current pricing (checked 2026-07-28 on the fal model pages — re-verify before
# big batches, prices drift). rate_per_sec bills on output seconds; flat_per_clip
# bills per request (clips here are all <= 40 s).
PRICING = {
    "fal-ai/sync-lipsync":    {"rate_per_sec": 0.70 / 60},
    "fal-ai/sync-lipsync/v2": {"rate_per_sec": 3.00 / 60},
    "fal-ai/latentsync":      {"flat_per_clip": 0.20},
}

# Words fal returns in billing/credit failures — abort the whole batch on these,
# never retry (burning retries on an exhausted balance helps nobody).
BILLING_ERROR_MARKERS = ("balance", "credit", "billing", "payment", "402", "exhausted")

# Speech-rate heuristic for lines whose mp3 isn't cached yet (dry-run only).
EST_CHARS_PER_SEC = 12.0
EST_MIN_SEC = 2.5


def log(msg: str):
    print(msg, flush=True)


def ffprobe_json(path: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout
    return json.loads(out)


def media_duration(path: Path) -> float:
    return float(ffprobe_json(path)["format"]["duration"])


def stream_types(path: Path) -> set[str]:
    return {s.get("codec_type") for s in ffprobe_json(path)["streams"]}


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text())
    return {"clips": {}, "failed": {}}


def save_manifest(m: dict):
    MANIFEST.write_text(json.dumps(m, ensure_ascii=False, indent=2))


def clip_cost(model: str, audio_sec: float) -> float:
    p = PRICING.get(model, {})
    if "flat_per_clip" in p:
        return p["flat_per_clip"]
    return audio_sec * p.get("rate_per_sec", 0.0)


def build_inventory(langs: list[str], keys: list[str], force: bool) -> list[dict]:
    """Every (lang, key) requested, with cache state and best-known duration."""
    inv = []
    for lang in langs:
        for key in keys:
            text = S[lang][key]
            stem = cache_stem(text, lang)
            mp3 = settings.TTS_CACHE_DIR / f"{stem}.mp3"
            mp4 = CACHE_DIR / f"{stem}.mp4"
            if mp3.exists():
                dur, est = media_duration(mp3), False
            else:
                dur, est = max(EST_MIN_SEC, len(text) / EST_CHARS_PER_SEC), True
            inv.append({
                "lang": lang, "key": key, "text": text, "stem": stem,
                "mp3": mp3, "mp4": mp4, "audio_sec": dur, "estimated": est,
                "cached": mp4.exists() and not force,
            })
    return inv


def dry_run(inv: list[dict], model: str):
    todo = [c for c in inv if not c["cached"]]
    log(f"\nDRY RUN — model: {model}  (no paid endpoints touched)")
    log(f"{'lang':<5} {'key':<14} {'audio':>7}  {'cost':>7}  clip")
    total_sec = total_cost = 0.0
    for c in todo:
        cost = clip_cost(model, c["audio_sec"])
        total_sec += c["audio_sec"]
        total_cost += cost
        mark = "~" if c["estimated"] else " "
        log(f"{c['lang']:<5} {c['key']:<14} {mark}{c['audio_sec']:>5.1f}s  ${cost:>6.3f}  {c['stem']}.mp4")
    skipped = len(inv) - len(todo)
    log(f"\nTo generate : {len(todo)} clips  ({skipped} already cached, skipped)")
    log(f"Total audio : {total_sec:.1f} s  (~ = estimated from text length; real mp3 not cached yet)")
    log(f"Est. cost   : ${total_cost:.2f}  at current {model} pricing")
    log("Next: generate ONE clip (--langs hi --keys intro --limit 1), review quality, then full batch with --confirm.")


def is_billing_error(err: Exception) -> bool:
    s = str(err).lower()
    return any(m in s for m in BILLING_ERROR_MARKERS)


def lipsync_arguments(model: str, video_url: str, audio_url: str) -> dict:
    args = {"video_url": video_url, "audio_url": audio_url}
    if model.startswith("fal-ai/sync-lipsync"):
        # loop: repeat the drive video when the audio is longer than 10 s
        args["sync_mode"] = "loop"
    if model == "fal-ai/latentsync":
        args["loop_mode"] = "loop"
    return args


def generate_clip(fal_client, httpx, model: str, drive_url: str, c: dict) -> dict:
    """One clip through the full pipeline. Returns manifest entry. Raises on failure."""
    if not c["mp3"].exists():
        fname = tts.synthesize(c["text"], c["lang"])
        if not fname:
            raise RuntimeError("TTS synthesis failed (check ELEVENLABS_* keys)")
        c["audio_sec"] = media_duration(c["mp3"])

    audio_url = fal_client.upload_file(str(c["mp3"]))
    handle = fal_client.submit(model, arguments=lipsync_arguments(model, drive_url, audio_url))

    deadline = time.time() + 600
    while True:
        status = handle.status(with_logs=False)
        if type(status).__name__ == "Completed":
            break
        if time.time() > deadline:
            raise TimeoutError("lipsync job exceeded 10 min")
        time.sleep(3)

    result = handle.get()
    video_url = result["video"]["url"]

    tmp = c["mp4"].with_suffix(".tmp.mp4")
    with httpx.stream("GET", video_url, timeout=120, follow_redirects=True) as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)

    types = stream_types(tmp)
    if "video" not in types:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"model returned no video stream ({types})")
    if "audio" not in types:
        log(f"    silent video returned — muxing mp3 back in")
        muxed = c["mp4"].with_suffix(".mux.mp4")
        subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(tmp), "-i", str(c["mp3"]),
             "-c:v", "copy", "-c:a", "aac", "-shortest", str(muxed), "-y"],
            check=True,
        )
        tmp.unlink()
        tmp = muxed

    tmp.rename(c["mp4"])
    return {
        "lang": c["lang"], "key": c["key"], "text": c["text"],
        "duration": round(media_duration(c["mp4"]), 2),
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main():
    ap = argparse.ArgumentParser(description="Pre-render Sakhi lipsync clips via fal.ai")
    ap.add_argument("--langs", default=",".join(ALL_LANGS))
    ap.add_argument("--keys", default=",".join(ALL_KEYS))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--force", action="store_true", help="regenerate even if cached")
    ap.add_argument("--confirm", action="store_true",
                    help="required for real runs generating more than 1 clip")
    args = ap.parse_args()

    langs = [l.strip() for l in args.langs.split(",") if l.strip()]
    keys = [k.strip() for k in args.keys.split(",") if k.strip()]
    for l in langs:
        if l not in ALL_LANGS:
            sys.exit(f"Unknown language: {l}")
    for k in keys:
        if k not in ALL_KEYS:
            sys.exit(f"Unknown key: {k}")

    model = settings.LIPSYNC_MODEL
    if model not in PRICING:
        sys.exit(f"No pricing entry for LIPSYNC_MODEL={model} — add it to PRICING first.")

    inv = build_inventory(langs, keys, args.force)
    if args.limit is not None:
        pending, kept = 0, []
        for c in inv:
            if not c["cached"] and pending < args.limit:
                kept.append(c)
                pending += 1
            elif c["cached"]:
                kept.append(c)
        inv = kept

    if args.dry_run:
        dry_run(inv, model)
        return

    todo = [c for c in inv if not c["cached"]]
    if not todo:
        log("Nothing to generate — all requested clips are cached. ($0)")
        return
    if len(todo) > 1 and not args.confirm:
        sys.exit(f"{len(todo)} clips would be generated. Safety gate: run --dry-run, "
                 "generate 1 clip (--limit 1), review quality, then re-run with --confirm.")
    if not settings.FAL_KEY:
        sys.exit("FAL_KEY is not set in .env")
    if not DRIVE_VIDEO.exists():
        sys.exit(f"Drive video missing: {DRIVE_VIDEO}")

    import fal_client   # deferred: dry-run must work without the dependency
    import httpx

    manifest = load_manifest()
    log(f"Uploading drive video {DRIVE_VIDEO} ...")
    drive_url = fal_client.upload_file(str(DRIVE_VIDEO))

    generated, failed, spend = [], [], 0.0
    for i, c in enumerate(todo, 1):
        log(f"[{i}/{len(todo)}] {c['lang']}/{c['key']} -> {c['stem']}.mp4")
        last_err = None
        for attempt in (1, 2):
            try:
                entry = generate_clip(fal_client, httpx, model, drive_url, c)
                manifest["clips"][c["stem"]] = entry
                manifest["failed"].pop(c["stem"], None)
                save_manifest(manifest)
                cost = clip_cost(model, entry["duration"])
                spend += cost
                generated.append(c)
                log(f"    ok — {entry['duration']}s, ~${cost:.3f}")
                last_err = None
                break
            except Exception as e:
                last_err = e
                if is_billing_error(e):
                    log(f"\nBILLING/CREDIT ERROR — stopping the batch immediately, no retry:\n  {e}")
                    save_manifest(manifest)
                    summary(generated, failed, inv, spend, aborted=True)
                    sys.exit(2)
                log(f"    attempt {attempt} failed: {e}")
        if last_err is not None:
            failed.append(c)
            manifest["failed"][c["stem"]] = {
                "lang": c["lang"], "key": c["key"], "error": str(last_err),
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            save_manifest(manifest)

    summary(generated, failed, inv, spend)


def summary(generated, failed, inv, spend, aborted=False):
    skipped = sum(1 for c in inv if c["cached"])
    log("\n===== SUMMARY " + ("(ABORTED) " if aborted else "") + "=====")
    log(f"generated : {len(generated)}")
    log(f"skipped   : {skipped} (already cached)")
    log(f"failed    : {len(failed)}" + (f"  -> {[c['lang']+'/'+c['key'] for c in failed]}" if failed else ""))
    log(f"est spend : ${spend:.2f}")


if __name__ == "__main__":
    main()
