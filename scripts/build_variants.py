#!/usr/bin/env python3
"""Generate Phase B subject variants + Phase C clarification expansions."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, "scripts")
from config import settings
from core.cachekey import cache_stem
from proposed_subject_variants import SUBJECT_VARIANTS, EXPANSIONS, SUBJECT_SENSITIVE

TAKES = Path("samples/takes_variants")
HIGH_FREQ = [("full_name", s) for s in ("self", "son", "daughter", "friend")] + \
            [("district", "son"), ("district", "daughter")]

def jobs(lang="hi"):
    out = []
    for subj, qs in SUBJECT_VARIANTS[lang].items():
        for q, text in qs.items():
            promoted = (settings.TTS_CACHE_DIR / f"{cache_stem(text, lang)}.mp3").exists()
            takes = 3 if ((q, subj) in HIGH_FREQ and not promoted) else 1
            out.append({"kind": f"var:{subj}", "key": f"{q}__{subj}", "text": text, "takes": takes})
    for k, text in EXPANSIONS[lang].items():
        out.append({"kind": "expand", "key": f"expand_{k}", "text": text, "takes": 1})
    return out

def synth(text, out_path):
    import httpx
    r = httpx.post(f"{settings.ELEVENLABS_BASE_URL}/v1/text-to-speech/{settings.ELEVENLABS_VOICE_ID}",
        params={"output_format": "mp3_44100_128"}, headers={"xi-api-key": settings.ELEVENLABS_API_KEY},
        json={"text": text, "model_id": settings.ELEVENLABS_MODEL,
              "voice_settings": {"stability": settings.ELEVENLABS_STABILITY,
                                 "similarity_boost": settings.ELEVENLABS_SIMILARITY,
                                 "style": settings.ELEVENLABS_STYLE, "speed": settings.ELEVENLABS_SPEED}},
        timeout=60)
    r.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)

if __name__ == "__main__":
    go = "--go" in sys.argv
    work = jobs()
    single = sum(len(j["text"]) for j in work)
    extra = sum(len(j["text"]) * (j["takes"]-1) for j in work)
    print(f"items={len(work)} files={sum(j['takes'] for j in work)}")
    print(f"  single={single}  extra-takes={extra}  TOTAL={single+extra}")
    if not go:
        print("estimate only; re-run with --go"); sys.exit()
    ok = fail = 0
    for i, j in enumerate(work, 1):
        for t in range(1, j["takes"]+1):
            dest = (TAKES / f"{j['key']}__t{t}.mp3") if j["takes"] > 1 else \
                   (settings.TTS_CACHE_DIR / f"{cache_stem(j['text'], 'hi')}.mp3")
            if dest.exists(): continue
            try: synth(j["text"], dest); ok += 1
            except Exception as e: fail += 1; print(f"  FAIL {j['key']}: {str(e)[:100]}")
            time.sleep(0.35)
        print(f"[{i}/{len(work)}] {j['kind']} {j['key']} x{j['takes']}")
    print(f"\ngenerated {ok}, failed {fail}")
