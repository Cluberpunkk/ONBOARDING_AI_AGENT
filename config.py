"""Sakhi configuration — loads .env, exposes settings."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")


class Settings:
    # ElevenLabs (voice) — leave empty to use browser-TTS fallback
    ELEVENLABS_API_KEY: str = os.getenv("ELEVENLABS_API_KEY", "")
    ELEVENLABS_VOICE_ID: str = os.getenv("ELEVENLABS_VOICE_ID", "")
    ELEVENLABS_MODEL: str = os.getenv("ELEVENLABS_MODEL", "eleven_v3")
    # Data-residency accounts MUST use their stack's URL (e.g.
    # https://api.in.residency.elevenlabs.io) — the global URL 401s their keys.
    ELEVENLABS_BASE_URL: str = os.getenv("ELEVENLABS_BASE_URL", "https://api.elevenlabs.io")
    # Voice character (folded into the TTS cache hash — changing them regenerates)
    ELEVENLABS_STABILITY: float = float(os.getenv("ELEVENLABS_STABILITY", "0.45"))
    ELEVENLABS_SIMILARITY: float = float(os.getenv("ELEVENLABS_SIMILARITY", "0.80"))
    ELEVENLABS_STYLE: float = float(os.getenv("ELEVENLABS_STYLE", "0.35"))
    ELEVENLABS_SPEED: float = float(os.getenv("ELEVENLABS_SPEED", "0.93"))

    # Gemini (answer parsing) — leave empty to use keyword-mock parser
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    PARSER_MODEL: str = os.getenv("PARSER_MODEL", "gemini-2.5-flash")

    # fal.ai avatar layer — used ONLY by scripts/build_avatar_clips.py.
    # Runtime code never calls fal.ai; clips are served from disk.
    FAL_KEY: str = os.getenv("FAL_KEY", "")
    AVATAR_ENABLED: bool = os.getenv("AVATAR_ENABLED", "true").lower() == "true"
    AVATAR_BASE_VIDEO: str = os.getenv("AVATAR_BASE_VIDEO", "assets/sakhi_base.mp4")
    LIPSYNC_MODEL: str = os.getenv("LIPSYNC_MODEL", "fal-ai/sync-lipsync")
    # Idle avatar: "static" = still portrait + CSS breathing (default);
    # "video" = the old palindrome idle loop (kept for A/B, reads uncanny)
    AVATAR_IDLE_MODE: str = os.getenv("AVATAR_IDLE_MODE", "static")

    # Conversation engine. "classic" = the deterministic fixed-order flow that
    # ships today (byte-identical, always demo-safe). "agentic" = slot-filling
    # dialogue. Every v4 capability lives behind agentic; classic is the default.
    CONVERSATION_MODE: str = os.getenv("CONVERSATION_MODE", "classic")
    # T3 (live TTS) per-session character ceiling. 0 = off. At ~$0.05/1k chars on
    # Flash v2.5, 40 chars ~ Rs 0.17 — the whole session budget is Rs 0.40.
    T3_CHAR_BUDGET_PER_SESSION: int = int(os.getenv("T3_CHAR_BUDGET_PER_SESSION", "0"))
    T3_MODEL: str = os.getenv("T3_MODEL", "eleven_flash_v2_5")
    BARGE_IN_ENABLED: bool = os.getenv("BARGE_IN_ENABLED", "true").lower() == "true"

    # --- conversational tone knobs (all free; tune by ear) ---
    # How often a plain single-slot answer earns a light acknowledgment.
    # Acknowledging EVERY turn is the most robotic pattern there is.
    ACK_RATE: float = float(os.getenv("ACK_RATE", "0.35"))
    # "Think time" before her voice starts. Replying in 13 ms reads as a machine.
    # Visual feedback still fires instantly — this delays audio only.
    THINK_TIME_MS_RANGE: str = os.getenv("THINK_TIME_MS_RANGE", "250-600")
    THINK_TIME_MS_RANGE_DEEP: str = os.getenv("THINK_TIME_MS_RANGE_DEEP", "400-900")
    # Natural handover before the mic opens after she finishes.
    TURN_GAP_MS_RANGE: str = os.getenv("TURN_GAP_MS_RANGE", "250-400")
    # Soft sentence-openers ("तो,", "चलिए,") before a question.
    SOFT_OPENER_RATE: float = float(os.getenv("SOFT_OPENER_RATE", "0.22"))

    # --- VAD-assisted end-of-speech (measured as the single largest per-turn
    # cost: Chrome waits out its own silence timeout before firing onend).
    # OFF by default: cutting off a slow Tier 2/3 speaker mid-sentence is far
    # worse than a second of dead air. Degrades to Chrome's native behaviour
    # whenever the VAD stream is unavailable.
    VAD_ENDPOINTING_ENABLED: bool = os.getenv("VAD_ENDPOINTING_ENABLED", "false").lower() == "true"
    STT_ENDPOINT_SILENCE_MS: int = int(os.getenv("STT_ENDPOINT_SILENCE_MS", "800"))

    @staticmethod
    def _range(spec: str, fallback=(250, 600)) -> tuple[int, int]:
        try:
            lo, hi = spec.split("-")
            return int(lo), int(hi)
        except Exception:
            return fallback

    @property
    def think_time(self) -> tuple[int, int]:
        return self._range(self.THINK_TIME_MS_RANGE, (250, 600))

    @property
    def think_time_deep(self) -> tuple[int, int]:
        return self._range(self.THINK_TIME_MS_RANGE_DEEP, (400, 900))

    @property
    def turn_gap(self) -> tuple[int, int]:
        return self._range(self.TURN_GAP_MS_RANGE, (250, 400))

    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8010"))

    DATA_DIR: Path = BASE_DIR / "data"
    TTS_CACHE_DIR: Path = DATA_DIR / "tts_cache"
    PROFILES_DIR: Path = DATA_DIR / "profiles"
    PHOTOS_DIR: Path = DATA_DIR / "photos"
    AVATAR_CACHE_DIR: Path = DATA_DIR / "avatar_cache"

    @property
    def tts_enabled(self) -> bool:
        return bool(self.ELEVENLABS_API_KEY and self.ELEVENLABS_VOICE_ID)

    @property
    def parser_enabled(self) -> bool:
        return bool(self.GEMINI_API_KEY)

    @property
    def agentic(self) -> bool:
        return self.CONVERSATION_MODE.lower() == "agentic"

    @property
    def avatar_enabled(self) -> bool:
        """True only when the flag is on AND pre-rendered clips exist on disk."""
        return self.AVATAR_ENABLED and any(self.AVATAR_CACHE_DIR.glob("*.mp4"))


settings = Settings()
for d in (settings.TTS_CACHE_DIR, settings.PROFILES_DIR, settings.PHOTOS_DIR,
          settings.AVATAR_CACHE_DIR):
    d.mkdir(parents=True, exist_ok=True)
