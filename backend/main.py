"""
Alita Assistant — FastAPI Backend  (main.py)
============================================
All fixes applied:
  1.  faster-whisper replaces openai-whisper          (Windows compatible)
  2.  AutoFeatureExtractor replaces Wav2Vec2Processor  (fixes tokenizer error)
  3.  Full JWKS ES256 signature verification           (no more 403 / forgery possible)
  4.  HS256 legacy path kept                           (fallback support)
  5.  LLM_N_GPU_LAYERS=0 CPU mode                     (works without CUDA)
  6.  Pydantic protected_namespaces suppressed         (cleans up warning)
  7.  Emotion label normalisation                      (neu→neutral, hap→happy …)
  8.  Server-side tier enforcement in pipeline         (can't bypass via DevTools)
  9.  Rate limiting per session                        (free=10/min, premium=60/min)
 10.  Windows Piper .exe path support
 11.  Razorpay monthly ($99) + annual ($1100) plan handling
 12.  payment.failed event handled
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime

# ── Load .env FIRST — so os.environ has keys before groq_pool imports ────────
from dotenv import load_dotenv  # type: ignore[import-untyped]
load_dotenv(override=True)

# ── §0  Set up ffmpeg for pydub (song recognition) ───────────────────────────
# pydub needs ffmpeg to convert audio formats. If ffmpeg is not on PATH,
# try to use the static binary bundled with imageio-ffmpeg.
try:
    import shutil
    if not shutil.which("ffmpeg"):
        try:
            import imageio_ffmpeg  # type: ignore[import-untyped]
            _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            os.environ["PATH"] = os.path.dirname(_ffmpeg_exe) + os.pathsep + os.environ.get("PATH", "")
            # Also tell pydub explicitly where ffmpeg is
            from pydub import AudioSegment  # type: ignore[import-untyped]
            AudioSegment.converter = _ffmpeg_exe
            AudioSegment.ffprobe = _ffmpeg_exe  # ffprobe isn't needed but prevents warning
        except ImportError:
            pass  # imageio-ffmpeg not installed; pydub will warn at startup
except Exception:
    pass

import httpx  # type: ignore[import-untyped]
import numpy as np  # type: ignore[import-untyped]
import razorpay  # type: ignore[import-untyped]
import torch  # type: ignore[import-untyped]
import uvicorn  # type: ignore[import-untyped]
from fastapi import (  # type: ignore[import-untyped]
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[import-untyped]
from fastapi.responses import JSONResponse  # type: ignore[import-untyped]
from jose import JWTError, jwk, jwt  # type: ignore[import-untyped]
from pydantic import BaseModel, Field  # type: ignore[import-untyped]
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore[import-untyped]
from test_auth import test_auth_router  # type: ignore[import]
from routers.youtube_search import youtube_router  # type: ignore[import]
from memory.conversation_store import (  # type: ignore[import]
    save_turn,
    load_history,
    rebuild_transcript_buffer,
    export_training_data,
)


# ─────────────────────────────────────────────────────────────────────────────
# §0  FFMPEG SETUP (must run before pydub/shazamio imports)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import imageio_ffmpeg as _ioff  # type: ignore[import-untyped]
    _ffmpeg_exe = _ioff.get_ffmpeg_exe()
    _ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    # Also configure pydub to use this ffmpeg
    try:
        from pydub import AudioSegment  # type: ignore[import-untyped]
        AudioSegment.converter = _ffmpeg_exe
    except ImportError:
        pass
except ImportError:
    pass  # imageio-ffmpeg not installed; ffmpeg must be on system PATH


# ─────────────────────────────────────────────────────────────────────────────
# §0a  LOGGING
# ─────────────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("Alita.main")


# ─────────────────────────────────────────────────────────────────────────────
# §0b  STARTUP DEPENDENCY CHECK — Fail fast if critical packages are missing
# ─────────────────────────────────────────────────────────────────────────────
import sys as _sys

_missing_packages = []
try:
    import groq  # noqa: F401  # type: ignore[import-untyped]
except ImportError:
    _missing_packages.append("groq")
try:
    import google.generativeai  # noqa: F401  # type: ignore[import-untyped]
except ImportError:
    _missing_packages.append("google-generativeai")

if _missing_packages:
    _venv_hint = (
        "It looks like you're running with the SYSTEM Python instead of the virtual environment.\n"
        f"  Current Python: {_sys.executable}\n"
        "  \n"
        "  FIX: Activate the venv first, then run the server:\n"
        "    .\\venv\\Scripts\\Activate.ps1          (PowerShell)\n"
        "    .\\venv\\Scripts\\activate.bat           (CMD)\n"
        "    source venv/bin/activate               (Linux/Mac)\n"
        "    python -m uvicorn main:app --reload\n"
        "  \n"
        f"  Missing packages: {', '.join(_missing_packages)}\n"
        "  Or install them manually:  pip install " + " ".join(_missing_packages) + "\n"
    )
    log.error("\n" + "=" * 70)
    log.error("CRITICAL: Required LLM packages are NOT installed!")
    log.error("=" * 70)
    log.error(_venv_hint)
    log.error("=" * 70)
    log.error("The assistant WILL NOT be able to respond until this is fixed.")
    log.error("=" * 70 + "\n")


# ─────────────────────────────────────────────────────────────────────────────
# §1  CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",                   # ignore stale env vars we no longer use
        protected_namespaces=(),          # suppresses model_path namespace warning
    )

    # ── Auth ──────────────────────────────────────────────────────────────
    supabase_jwt_secret: str = ""
    supabase_url: str        = ""

    # ── Payments (Razorpay) ─────────────────────────────────────────────────
    razorpay_key_id: str           = ""          # rzp_test_xxx or rzp_live_xxx
    razorpay_key_secret: str       = ""
    razorpay_webhook_secret: str   = ""
    admin_secret: str              = ""          # protect admin endpoints — set in .env
    razorpay_plan_monthly: str     = ""          # Razorpay Plan ID for $99/mo
    razorpay_plan_annual: str      = ""          # Razorpay Plan ID for $1100/yr

    # ── LLM ───────────────────────────────────────────────────────────────
    gemini_api_key: str      = ""       # Primary Gemini API key
    gemini_api_key_2: str    = ""       # Additional keys for rotation
    gemini_api_key_3: str    = ""
    gemini_api_key_4: str    = ""
    gemini_api_key_5: str    = ""
    gemini_api_key_6: str    = ""
    gemini_api_key_7: str    = ""
    gemini_api_key_8: str    = ""
    gemini_api_key_9: str    = ""
    gemini_api_key_10: str   = ""
    gemini_model: str        = "gemini-2.0-flash"  # fast + great Hindi
    llm_max_tokens: int      = 300      # premium — adaptive per query type
    llm_max_tokens_free: int = 200      # free — adaptive per query type
    llm_temperature: float   = 0.6      # balanced creativity + speed

    # ── Groq (free fallback LLM) ──────────────────────────────────────────
    groq_api_key: str        = ""       # Get from https://console.groq.com/keys
    groq_api_key_2: str      = ""       # Additional keys for rotation
    groq_api_key_3: str      = ""
    groq_api_key_4: str      = ""
    groq_model: str          = "llama-3.3-70b-versatile"  # Free, fast, smart

    # ── DeepSeek (high-accuracy LLM, excellent medical knowledge) ────────
    deepseek_api_key: str    = ""       # Get free at https://platform.deepseek.com
    deepseek_model: str      = "deepseek-chat"  # DeepSeek-V3, 10M free tokens/mo

    # ── NVIDIA Build (Nemotron 3 Super — 120B MoE, agentic reasoning) ─
    nvidia_api_key: str      = ""       # Get free at https://build.nvidia.com
    nvidia_model: str        = "nvidia/nemotron-3-super-120b-a12b"  # 120B MoE, 12B active

    def get_all_gemini_keys(self) -> list[str]:
        """Return list of all non-empty Gemini API keys."""
        keys = []
        for attr in [
            'gemini_api_key', 'gemini_api_key_2', 'gemini_api_key_3',
            'gemini_api_key_4', 'gemini_api_key_5', 'gemini_api_key_6',
            'gemini_api_key_7', 'gemini_api_key_8', 'gemini_api_key_9',
            'gemini_api_key_10',
        ]:
            val = getattr(self, attr, '').strip()
            if val:
                keys.append(val)
        return keys

    def get_all_groq_keys(self) -> list[str]:
        """Return list of all non-empty Groq API keys."""
        keys = []
        for attr in ['groq_api_key', 'groq_api_key_2', 'groq_api_key_3', 'groq_api_key_4']:
            val = getattr(self, attr, '').strip()
            if val:
                keys.append(val)
        return keys

    # ── Audio ─────────────────────────────────────────────────────────────
    audio_sample_rate: int       = 16000
    audio_chunk_duration_ms: int = 30

    # ── Rate limiting ─────────────────────────────────────────────────────
    rate_limit_free: int    = 10   # requests per minute
    rate_limit_premium: int = 60

    # ── CORS ──────────────────────────────────────────────────────────────
    # Set ALLOWED_ORIGINS in .env for production, comma-separated
    # Example: ALLOWED_ORIGINS=https://myapp.vercel.app,https://myapp.com
    allowed_origins: list[str] = Field(default_factory=lambda: [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://[::1]:5173",
        "http://localhost:8000",
    ])

    @classmethod
    def _parse_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # ── Device (auto-detected) ────────────────────────────────────────────
    device: str = "cuda" if torch.cuda.is_available() else "cpu"


settings = Settings()
_all_keys = settings.get_all_gemini_keys()
log.info("Device: %s | LLM: Gemini %s | API Keys: %d loaded",
         settings.device, settings.gemini_model, len(_all_keys))


# ─────────────────────────────────────────────────────────────────────────────
# §1b  GEMINI KEY ROTATOR — Round-robin with cooldown on rate-limited keys
# ─────────────────────────────────────────────────────────────────────────────
import hashlib as _hl

class GeminiKeyRotator:
    """Rotates between multiple Gemini API keys to avoid rate limits."""

    def __init__(self, keys: list[str]):
        self.keys = keys if keys else [""]
        self.index = 0
        self.cooldowns: dict[int, float] = {}  # key_index → cooldown_until timestamp
        self.total_calls: dict[int, int] = {i: 0 for i in range(len(self.keys))}

    def get_key(self) -> str:
        """Get the next available API key, skipping rate-limited ones."""
        now = time.time()
        tried = 0
        while tried < len(self.keys):
            idx = self.index % len(self.keys)
            cooldown_until = self.cooldowns.get(idx, 0)
            if now >= cooldown_until:
                self.total_calls[idx] = self.total_calls.get(idx, 0) + 1
                self.index = (idx + 1) % len(self.keys)
                masked = self.keys[idx][:8] + '...'  # type: ignore[index]
                log.debug("Using Gemini key #%d (%s) — call #%d",
                          idx + 1, masked, self.total_calls[idx])
                return self.keys[idx]
            tried += 1
            self.index = (idx + 1) % len(self.keys)

        # All keys are on cooldown — use the one with shortest wait
        soonest = min(self.cooldowns, key=lambda k: self.cooldowns.get(k, 0))
        self.total_calls[soonest] = self.total_calls.get(soonest, 0) + 1
        return self.keys[soonest]

    def mark_rate_limited(self, key: str, cooldown_seconds: int = 60):
        """Mark a key as rate-limited with a cooldown period."""
        try:
            idx = self.keys.index(key)
            self.cooldowns[idx] = time.time() + cooldown_seconds
            log.warning("Key #%d rate-limited — cooling down for %ds", idx + 1, cooldown_seconds)
        except ValueError:
            pass

    def status(self) -> dict:
        """Get status of all keys."""
        now = time.time()
        return {
            "total_keys": len(self.keys),
            "available": sum(1 for i in range(len(self.keys))
                          if now >= self.cooldowns.get(i, 0)),
            "calls": dict(self.total_calls),  # type: ignore[arg-type]
        }


key_rotator = GeminiKeyRotator(_all_keys)


# ── Groq Key Rotator (shared module) ─────────────────────────────────────
from groq_pool import get_rotator as _get_groq_rotator  # type: ignore[import]
groq_rotator = _get_groq_rotator()
log.info("Groq API Keys: %d loaded", len(groq_rotator.keys))


# ─────────────────────────────────────────────────────────────────────────────
# §1c  RESPONSE CACHE — Avoid API calls for repeated/common queries
# ─────────────────────────────────────────────────────────────────────────────
class ResponseCache:
    """Simple time-based response cache to reduce API calls."""

    def __init__(self, ttl_seconds: int = 300, max_entries: int = 200):
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self.cache: dict[str, tuple[float, str]] = {}  # hash → (timestamp, response)
        self.hits = 0
        self.misses = 0

    def _hash(self, text: str) -> str:
        # Normalize: lowercase, strip, remove extra spaces
        normalized = ' '.join(text.lower().strip().split())
        return _hl.md5(normalized.encode()).hexdigest()

    def get(self, query: str) -> str | None:
        h = self._hash(query)
        if h in self.cache:
            ts, response = self.cache[h]
            if time.time() - ts < self.ttl:
                self.hits += 1
                log.debug("Cache HIT (hits=%d, misses=%d)", self.hits, self.misses)
                return response
            else:
                del self.cache[h]  # Expired  # type: ignore[attr-defined]
        self.misses += 1
        return None

    def put(self, query: str, response: str):
        # Evict oldest if at capacity
        if len(self.cache) >= self.max_entries:
            oldest_key = min(self.cache, key=lambda k: self.cache[k][0])  # type: ignore[index]
            del self.cache[oldest_key]  # type: ignore[attr-defined]
        self.cache[self._hash(query)] = (time.time(), response)

    def status(self) -> dict:
        return {"entries": len(self.cache), "hits": self.hits, "misses": self.misses}


response_cache = ResponseCache(ttl_seconds=900, max_entries=500)  # 15min TTL, 500 entries for speed


# ─────────────────────────────────────────────────────────────────────────────
# §2  PYDANTIC SCHEMAS
# ─────────────────────────────────────────────────────────────────────────────
class AudioChunk(BaseModel):
    type: str        = "audio_chunk"
    session_id: str
    sequence: int
    pcm_float32: list[float]


class TextMessage(BaseModel):
    type: str        = "text_message"
    session_id: str
    text: str


class LLMReply(BaseModel):
    type: str        = "llm_token"
    session_id: str
    token: str
    is_final: bool   = False


class EmotionUpdate(BaseModel):
    type: str        = "emotion_update"
    session_id: str
    label: str
    confidence: float


class TTSAudioFrame(BaseModel):
    type: str        = "tts_audio"
    session_id: str
    audio_b64: str
    is_final: bool   = False


class SessionRecord(BaseModel):
    session_id: str
    user_id: str
    tier: str              = "free"
    audio_buffer: list     = Field(default_factory=list)
    transcript_buffer: str = ""
    connected_at: float    = Field(default_factory=time.time)
    # rate-limit counters
    request_count: int     = 0
    window_start: float    = Field(default_factory=time.time)
    # voice selection (per session)
    voice_id: str          = "en_jenny"
    # True when user manually picked a voice — prevents auto-detect override
    manual_voice_override: bool = False
    # customisable assistant name (user can rename via voice)
    custom_name: str       = "Alita"
    greeted: bool          = False
    # dictation mode (for typing into apps like notepad)
    dictation_active: bool = False
    dictation_app: str     = ""
    # ── Near-sentient personality state ────────────────────────────────────
    current_emotion: str         = "neutral"
    emotion_confidence: float    = 0.0
    environment_sounds: list     = Field(default_factory=list)
    interaction_count: int       = 0
    emergency_active: bool       = False
    # ── Song memory — persists across conversation turns ───────────────────
    last_identified_song: str    = ""   # e.g. "Blinding Lights by The Weeknd (album: After Hours)"
    # ── Barge-in context — remembers what Alita was saying when interrupted ────
    interrupted_response: str    = ""   # partial response Alita was speaking
    interrupted_query: str       = ""   # original user query that triggered the response
    barge_in_count: int          = 0    # number of barge-ins this session
    pipeline_cancel: bool        = False  # flag to cancel active pipeline
    active_pipeline_id: str      = ""   # ID of currently running pipeline
    # ── Threading cancel event for instant mid-LLM abort ────────────────────
    cancel_event: Any            = Field(default=None)  # threading.Event, set by barge-in

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        import threading
        if self.cancel_event is None:
            object.__setattr__(self, 'cancel_event', threading.Event())


# ─────────────────────────────────────────────────────────────────────────────
# §3  ENGINE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
class EngineRegistry:
    """
    VRAM budget (RTX 3050 — 4 GB):
      Whisper small FP16             ≈ 0.50 GB
      Wav2Vec2-base FP16             ≈ 0.40 GB
      XTTS v2                        ≈ 1.50 GB
      CUDA runtime                   ≈ 0.35 GB
      ─────────────────────────────────────
      Total                          ≈ 2.75 GB  ✓ under 4 GB
    """
    llm                      = None
    whisper_model            = None
    whisper_processor        = None     # True sentinel for faster-whisper
    wav2vec2_model           = None
    wav2vec2_processor       = None
    piper_binary             = None
    memory_collection        = None     # ChromaDB semantic memory
    xtts_engine              = None     # XTTS v2 voice synthesis engine
    EMOTION_LABELS: list[str] = ["neutral", "happy", "angry", "sad"]


# ── Available voice models ──────────────────────────────────────────────────────
# Each voice has:
#   voice       = Edge TTS voice name (None for XTTS-only voices)
#   speaker_wav = Path to reference WAV for XTTS cloning (None for Edge-only voices)
#   engine      = "edge" | "xtts" | "auto" (auto = try XTTS first, fallback to Edge)
AVAILABLE_VOICES = {
    # ── XTTS Custom Voices (GPU-powered, voice cloning) ────────────────────
    "xtts_alita_en": {
        "name": "Alita (My Voice Clone)",
        "voice": None,
        "speaker_wav": "voices/default/my_voice.wav",
        "engine": "xtts",
        "description": "Your own cloned voice — XTTS v2 neural synthesis",
        "tier_required": "free",
        "lang": "en",
        "quality": "ultra",
    },
    "xtts_alita_ai": {
        "name": "Alita (AI Original Voice)",
        "voice": None,
        "speaker_wav": "voices/default/alita_en.wav",
        "engine": "xtts",
        "description": "Alita's AI-generated English voice — XTTS v2",
        "tier_required": "free",
        "lang": "en",
        "quality": "ultra",
    },
    "xtts_alita_hi": {
        "name": "Alita Hindi (AI Custom Voice)",
        "voice": None,
        "speaker_wav": "voices/default/alita_hi.wav",
        "engine": "xtts",
        "description": "Alita की हिंदी आवाज़ — XTTS v2 neural synthesis",
        "tier_required": "free",
        "lang": "hi",
        "quality": "ultra",
    },
    # ── Edge TTS Voices (Cloud, Microsoft Neural, FREE) ────────────────────
    "en_jenny": {
        "name": "Jenny (English Female)",
        "voice": "en-US-JennyNeural",
        "speaker_wav": None,
        "engine": "edge",
        "description": "Natural American English — warm & clear",
        "tier_required": "free",
        "lang": "en",
        "quality": "high",
    },
    "en_aria": {
        "name": "Aria (English Female, Premium)",
        "voice": "en-US-AriaNeural",
        "speaker_wav": None,
        "engine": "edge",
        "description": "American English — expressive & lively",
        "tier_required": "premium",
        "lang": "en",
        "quality": "high",
    },
    "en_guy": {
        "name": "Guy (English Male)",
        "voice": "en-US-GuyNeural",
        "speaker_wav": None,
        "engine": "edge",
        "description": "American English — confident & deep",
        "tier_required": "free",
        "lang": "en",
        "quality": "high",
    },
    "en_ryan": {
        "name": "Ryan (English Male, Premium)",
        "voice": "en-GB-RyanNeural",
        "speaker_wav": None,
        "engine": "edge",
        "description": "British English — sophisticated & warm",
        "tier_required": "premium",
        "lang": "en",
        "quality": "high",
    },
    # ── Hindi ──────────────────────────────────────────────────────────────
    "hi_swara": {
        "name": "Swara (हिंदी Female)",
        "voice": "hi-IN-SwaraNeural",
        "speaker_wav": None,
        "engine": "edge",
        "description": "हिंदी — natural, warm Hindi voice",
        "tier_required": "free",
        "lang": "hi",
        "quality": "high",
    },
    "hi_madhur": {
        "name": "Madhur (हिंदी Male)",
        "voice": "hi-IN-MadhurNeural",
        "speaker_wav": None,
        "engine": "edge",
        "description": "हिंदी — deep, realistic Hindi male",
        "tier_required": "free",
        "lang": "hi",
        "quality": "high",
    },
}

# ── Language display names ──────────────────────────────────────────────────
LANGUAGE_NAMES = {
    "en": "English",
    "hi": "हिंदी (Hindi)",
}

# ── Default voice per language ──────────────────────────────────────────────
DEFAULT_VOICE = {
    "en": "en_jenny",
    "hi": "hi_swara",
}


engines = EngineRegistry()


# ─────────────────────────────────────────────────────────────────────────────
# §4  JWKS CACHE  — public keys for ES256 JWT verification
# ─────────────────────────────────────────────────────────────────────────────
_jwks_keys: list[dict] = []


async def fetch_jwks() -> None:
    """
    Download Supabase public JWKS on startup.
    These are the public EC keys Supabase uses to sign every ES256 JWT.
    Without them a forged token could pass validation — so we reject
    all ES256 tokens if JWKS fails to load.
    """
    global _jwks_keys
    url = f"{settings.supabase_url}/auth/v1/.well-known/jwks.json"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data       = resp.json()
            _jwks_keys = data.get("keys", [])
            log.info("✓ JWKS loaded: %d key(s).", len(_jwks_keys))
    except Exception as exc:
        log.warning(
            "✗ JWKS fetch failed (%s). "
            "ES256 tokens will be rejected until resolved. "
            "Check SUPABASE_URL in backend/.env.", exc
        )


# ─────────────────────────────────────────────────────────────────────────────
# §5  MODEL LOADING
# ─────────────────────────────────────────────────────────────────────────────
async def load_engines() -> None:
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, lambda: _load_engines_sync())  # type: ignore[arg-type]


def _load_engines_sync() -> None:
    # Gemini API used for LLM — no local model loading needed
    log.info("Using Gemini API for LLM (no local model to load)")

    # ── §5a  ChromaDB Semantic Memory ─────────────────────────────────────
    try:
        import chromadb  # type: ignore[import-untyped]
        _chroma_client = chromadb.Client()
        engines.memory_collection = _chroma_client.get_or_create_collection(
            name="aura_memory",
            metadata={"hnsw:space": "cosine"},
        )
        log.info("✓ ChromaDB semantic memory initialized.")
    except Exception as exc:
        log.warning("ChromaDB init failed (memory disabled): %s", exc)
        engines.memory_collection = None

    # ── §5b  faster-whisper base (multilingual: Hindi + English) ───────────
    log.info("Loading Whisper small (multilingual) via faster-whisper for Indian accent support…")
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        compute = "float16" if settings.device == "cuda" else "int8"
        try:
            engines.whisper_model = WhisperModel(
                "small",
                device=settings.device,
                compute_type=compute,
                download_root="./models/whisper_cache",
            )
        except Exception as inner:
            # int8 can fail on Windows — fall back to float32
            if compute == "int8":
                log.warning("int8 failed (%s), falling back to float32 on CPU…", inner)
                engines.whisper_model = WhisperModel(
                    "small",
                    device="cpu",
                    compute_type="float32",
                    download_root="./models/whisper_cache",
                )
            else:
                raise
        engines.whisper_processor = True  # type: ignore[assignment]  # sentinel flag for faster-whisper
        log.info("✓ Whisper small loaded on %s (Indian accent optimized).", settings.device)
    except Exception as exc:
        log.error("✗ Failed to load Whisper: %s", exc)

    # ── §5c  Wav2Vec2 SER — AutoFeatureExtractor fixes tokenizer error ────
    log.info("Loading Wav2Vec2 SER…")
    try:
        from transformers import (  # type: ignore[import-untyped]
            AutoFeatureExtractor,
            Wav2Vec2ForSequenceClassification,
        )
        ser_checkpoint              = "superb/wav2vec2-base-superb-er"
        engines.wav2vec2_processor  = AutoFeatureExtractor.from_pretrained(
            ser_checkpoint
        )
        engines.wav2vec2_model = (
            Wav2Vec2ForSequenceClassification
            .from_pretrained(ser_checkpoint)
            .to(settings.device)
        )
        engines.wav2vec2_model.eval()  # type: ignore[union-attr]
        engines.EMOTION_LABELS = list(
            engines.wav2vec2_model.config.id2label.values()  # type: ignore[union-attr]
        )
        log.info("✓ Wav2Vec2 SER loaded. Labels: %s", engines.EMOTION_LABELS)
    except Exception as exc:
        log.error("✗ Failed to load Wav2Vec2: %s", exc)

    # ── §5d  TTS — Edge TTS (Microsoft Neural, FREE) ───────────────────────
    log.info("✓ TTS engine: Edge TTS (Microsoft Neural voices, cloud fallback)")

    # ── §5e  XTTS v2 — Local Neural TTS with Voice Cloning ─────────────────
    try:
        from engines.tts_xtts import XTTSEngine  # type: ignore[import]
        engines.xtts_engine = XTTSEngine(device=settings.device)
        if engines.xtts_engine.available:  # type: ignore[union-attr]
            engines.xtts_engine.preload_voices()  # type: ignore[union-attr]
            log.info("✓ XTTS v2 loaded on %s — voice cloning enabled", settings.device)
        else:
            log.warning("XTTS v2 model failed to load — falling back to Edge TTS only")
            engines.xtts_engine = None
    except Exception as exc:
        log.warning("XTTS v2 unavailable (Edge TTS fallback active): %s", exc)
        engines.xtts_engine = None

    log.info("All engines initialised.")


# ─────────────────────────────────────────────────────────────────────────────
# §6  LIFESPAN
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== Alita Assistant Backend starting… ===")

    # Razorpay client init
    global razorpay_client
    if settings.razorpay_key_id and settings.razorpay_key_secret:
        razorpay_client = razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))
        log.info("Razorpay client initialized (key_id=%s…)", settings.razorpay_key_id[:12])  # type: ignore[index]
    else:
        razorpay_client = None
        log.warning("Razorpay keys not configured — payments disabled.")

    # JWKS must be loaded before any JWT can be verified
    await fetch_jwks()

    # AI models
    await load_engines()

    # Start background reminder checker
    reminder_task = asyncio.create_task(_reminder_checker())

    log.info("=== Ready to accept connections. ===")
    yield
    reminder_task.cancel()
    log.info("=== Shutting down. ===")


async def _reminder_checker():
    """Background task that checks for due reminders every 30 seconds."""
    import time as _time
    while True:
        try:
            await asyncio.sleep(30)
            reminders_dir = os.path.join(".", "data", "reminders")
            if not os.path.exists(reminders_dir):
                continue

            now = _time.time()
            for fname in os.listdir(reminders_dir):
                if not fname.endswith(".json"):
                    continue
                fpath = os.path.join(reminders_dir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        reminders = json.load(f)
                except (json.JSONDecodeError, OSError):
                    continue

                modified = False
                for reminder in reminders:
                    if reminder.get("done", False):
                        continue
                    if reminder.get("remind_at", 0) <= now:
                        reminder["done"] = True
                        modified = True
                        # Find the user's active session and send alert
                        user_id_prefix = fname.replace(".json", "")
                        for sid, session in active_sessions.items():
                            safe_uid = "".join(
                                c if c.isalnum() or c in "_-" else "_"
                                for c in session.user_id
                            )
                            if safe_uid == user_id_prefix:
                                try:
                                    ws = _session_websockets.get(sid)
                                    if ws:
                                        await ws.send_text(json.dumps({
                                            "type": "reminder_alert",
                                            "text": reminder.get("text", ""),
                                            "remind_at": reminder.get("remind_at_iso", ""),
                                        }))
                                        log.info("Reminder alert sent: %s", reminder.get("text", "")[:50])
                                except Exception:
                                    pass
                                break

                if modified:
                    try:
                        with open(fpath, "w", encoding="utf-8") as f:
                            json.dump(reminders, f, indent=2, ensure_ascii=False)
                    except OSError:
                        pass
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.warning("Reminder checker error: %s", exc)
            await asyncio.sleep(60)


# ─────────────────────────────────────────────────────────────────────────────
# §7  APP
# ─────────────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Alita Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(test_auth_router)
app.include_router(youtube_router)

from routers.geospatial import geo_router  # type: ignore[import]
app.include_router(geo_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Security Headers Middleware ──────────────────────────────────────────────
from starlette.middleware.base import BaseHTTPMiddleware  # type: ignore[import-untyped]
from starlette.responses import Response  # type: ignore[import-untyped]

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Add standard security headers to all responses."""
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        # HSTS — only in production (when not localhost)
        if request.url.hostname not in ("localhost", "127.0.0.1", "::1"):
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        # Hide server version
        response.headers.pop("server", None)
        return response

app.add_middleware(SecurityHeadersMiddleware)

# ── CORS production warning ──────────────────────────────────────────────────
if any("localhost" in o or "127.0.0.1" in o for o in settings.allowed_origins):
    log.warning("⚠ CORS allows localhost origins — set ALLOWED_ORIGINS for production!")


# ─────────────────────────────────────────────────────────────────────────────
# §8  IN-MEMORY SESSION STORE
# ─────────────────────────────────────────────────────────────────────────────
active_sessions: Dict[str, SessionRecord] = {}
_session_websockets: Dict[str, Any] = {}  # session_id → WebSocket (for background tasks)


# ─────────────────────────────────────────────────────────────────────────────
# §9  AUTH  — Full zero-trust JWT verification
# ─────────────────────────────────────────────────────────────────────────────
def decode_supabase_jwt(token: str) -> dict:
    """
    Fully verify a Supabase JWT.  Two supported algorithms:

    ES256 (all Supabase projects created 2024+):
      ► Finds the matching public key in _jwks_keys by `kid`
      ► Verifies the EC signature cryptographically via python-jose
      ► Token forgery is mathematically impossible without Supabase's private key

    HS256 (legacy Supabase projects):
      ► Verifies HMAC signature with SUPABASE_JWT_SECRET from .env

    Both paths:
      ► Expiry validated by python-jose automatically
      ► Issuer must contain supabase.co
      ► sub claim must be present
    """
    # Step 1 — peek at header (no signature check yet)
    try:
        header = jwt.get_unverified_header(token)
        alg    = header.get("alg", "HS256")
        kid    = header.get("kid", "")
    except Exception as exc:
        log.warning("JWT header parse failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Malformed token.",
        )

    # Step 2 — verify signature
    try:
        if alg == "ES256":
            # ── ES256: must have JWKS ──────────────────────────────────────
            if not _jwks_keys:
                log.error(
                    "JWKS not loaded — rejecting ES256 token. "
                    "Restart the server and check SUPABASE_URL."
                )
                raise JWTError("JWKS unavailable — cannot verify ES256 token.")

            # Find the key matching this token's kid
            matching_key = next(
                (k for k in _jwks_keys if k.get("kid") == kid),
                _jwks_keys[0] if _jwks_keys else None,   # fallback to first key
            )
            if matching_key is None:
                raise JWTError(f"No JWKS key for kid='{kid}'.")

            # Construct EC public key from JWK and fully verify
            public_key = jwk.construct(matching_key)
            payload    = jwt.decode(
                token,
                public_key,
                algorithms=["ES256"],
                options={"verify_aud": False},
            )

        else:
            # ── HS256: verify with JWT secret ─────────────────────────────
            payload = jwt.decode(
                token,
                settings.supabase_jwt_secret,
                algorithms=["HS256"],
                options={"verify_aud": False},
            )

    except JWTError as exc:
        log.warning("JWT verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or expired token.",
        )

    # Step 3 — validate claims
    user_id: str = payload.get("sub", "")
    email: str   = payload.get("email", "")
    role: str    = payload.get("role", "authenticated")
    iss: str     = payload.get("iss", "")

    if not user_id:
        log.warning("JWT missing 'sub' claim.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid token claims.",
        )

    if "supabase.co" not in iss:
        log.warning("JWT untrusted issuer: %s", iss)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Untrusted token issuer.",
        )

    log.info("JWT verified | user=%s | alg=%s", user_id[:8], alg)
    return {"user_id": user_id, "email": email, "role": role}


def get_user_tier(user_id: str) -> str:
    """
    Returns user tier from persistent tier store.
    Test/beta users get premium automatically.
    """
    from tier_store import get_tier  # type: ignore[import]
    return get_tier(user_id)


# ─────────────────────────────────────────────────────────────────────────────
# §10  RATE LIMITER
# ─────────────────────────────────────────────────────────────────────────────
def check_rate_limit(session: SessionRecord) -> bool:
    """
    Sliding 60-second window per session.
    Returns True if the request is allowed, False if throttled.
    Beta/test users bypass rate limits entirely.
    """
    # Test users get unlimited access
    if session.user_id.startswith("test_"):
        return True

    now   = time.time()
    limit = (
        settings.rate_limit_premium
        if session.tier == "premium"
        else settings.rate_limit_free
    )

    if now - session.window_start > 60:
        session.request_count = 0
        session.window_start  = now

    if session.request_count >= limit:
        return False

    session.request_count += 1
    return True


# ─────────────────────────────────────────────────────────────────────────────
# §11  INFERENCE HELPERS
# ─────────────────────────────────────────────────────────────────────────────

# Checkpoint label → UI display name
_EMOTION_LABEL_MAP: dict[str, str] = {
    "neu": "neutral",
    "hap": "happy",
    "ang": "angry",
    "sad": "sad",
    "fea": "fear",
    "dis": "disgust",
    "sur": "surprise",
}


# ── Wake word detection (robust / fuzzy) ───────────────────────────────────
import re as _re

# Phrases that DEFINITELY trigger wake (checked as prefix after cleanup)
WAKE_PHRASES = [
    "hey Alita", "hi Alita", "hello Alita",
    "okay Alita", "ok Alita", "yo Alita",
    "hey ora", "hi ora", "hello ora",       # common Whisper mishearing
    "hey auro", "hi auro", "hello auro",    # another mishearing
    "hey ara", "hi ara",
    "hey alita", "hi alita", "hello alita",  # lowercase variants
    # Hindi variants
    "namaste Alita", "namaste ora",
    "suno Alita", "suno ora",
    "Alita suno",
    "Alita",
]

# Single-word triggers (user might just say "hey" or "hello" to activate)
WAKE_SINGLE_WORDS = {"hey", "hi", "hello", "Alita", "alita", "ora", "auro", "aur", "ara", "namaste", "suno"}


def _clean_for_matching(text: str) -> str:
    """Strip punctuation and normalise whitespace for matching."""
    text = _re.sub(r"[^\w\s]", "", text)       # remove all punctuation
    text = _re.sub(r"\s+", " ", text).strip()   # collapse whitespace
    return text.lower()


def _fuzzy_contains_aura(word: str) -> bool:
    """
    Check if a word is a fuzzy match for 'Alita'.
    Handles Whisper mishearings like 'aur', 'ora', 'auro', 'aurah', 'ara', 'alita'.
    """
    aura_variants = {"Alita", "alita", "aur", "ora", "auro", "aurah", "ara", "arra", "aora", "aleeta", "alitta"}
    return word in aura_variants



def _strip_wake_word(transcript: str, custom_name: str = "Alita") -> tuple[bool, str]:
    """
    Check if transcript starts with a wake phrase.
    Also matches user's custom assistant name.
    Returns (wake_detected, remaining_text_after_wake_phrase).
    """
    cleaned = _clean_for_matching(transcript)
    if not cleaned:
        return False, transcript

    words = cleaned.split()
    cn = custom_name.lower().strip()

    # Build dynamic wake phrases with custom name
    dynamic_phrases = list(WAKE_PHRASES)
    if cn and cn != "Alita":
        for prefix in ["hey", "hi", "hello", "okay", "ok", "yo", "namaste", "suno"]:
            dynamic_phrases.insert(0, f"{prefix} {cn}")
        dynamic_phrases.insert(0, cn)

    # 1. Check multi-word phrases first (longest match wins)
    for phrase in dynamic_phrases:
        if cleaned.startswith(phrase):
            remainder = cleaned[len(phrase):].strip()  # type: ignore[misc]
            return True, remainder

    # 2. Check if transcript is just a single wake word
    custom_singles = WAKE_SINGLE_WORDS | {cn}
    if len(words) == 1 and (words[0] in custom_singles or _fuzzy_contains_aura(words[0])):
        return True, ""

    # 3. Check if first word is a greeting + second word is name-like
    if len(words) >= 2:
        greetings = {"hey", "hi", "hello", "okay", "ok", "yo"}
        if words[0] in greetings and (words[1] == cn or _fuzzy_contains_aura(words[1])):
            remainder = " ".join(words[2:])  # type: ignore[misc]
            return True, remainder

    # 4. Check if just the first word is Alita-like or custom name
    if _fuzzy_contains_aura(words[0]) or words[0] == cn:
        remainder = " ".join(words[1:])  # type: ignore[misc]
        return True, remainder

    return False, transcript


def _detect_name_change(user_text: str) -> str | None:
    """
    Detect if the user is requesting a name change for the assistant.
    Returns the new name if detected, None otherwise.
    Supports: 'call yourself X', 'your name is X', 'rename to X',
              'tumhara naam X hai', 'apna naam X rakho'
    """
    text = user_text.lower().strip()
    patterns = [
        r"call\s+yourself\s+([\w]+)",
        r"your\s+name\s+is\s+([\w]+)",
        r"rename\s+(?:yourself\s+)?(?:to\s+)?([\w]+)",
        r"change\s+(?:your\s+)?name\s+(?:to\s+)?([\w]+)",
        r"(?:tumhara|tera|apna)\s+naam\s+([\w]+)",
        r"naam\s+(?:badal\s+ke\s+|badlo\s+)?([\w]+)",
    ]
    for pattern in patterns:
        match = _re.search(pattern, text)
        if match:
            new_name = match.group(1).capitalize()
            # Ignore if they just said a common word
            ignore = {"Is", "What", "The", "A", "To", "My", "Your", "It", "Hai", "Kya"}
            if new_name not in ignore:
                return new_name
    return None


def _transcribe_sync(pcm_array: np.ndarray) -> tuple[str, str]:
    """
    faster-whisper STT (multilingual).
    Returns (transcript_text, detected_language).
    Auto-detects Hindi vs English.
    """
    if engines.whisper_model is None:
        return "", "en"
    try:
        segments, info = engines.whisper_model.transcribe(  # type: ignore[union-attr]
            pcm_array,
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=200,   # faster end-of-speech detection (was 300)
                speech_pad_ms=50,              # less padding = faster handoff (was 100)
            ),
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        lang = getattr(info, 'language', 'en') or 'en'
        log.info("STT: lang=%s text='%s'", lang, text)
        return text, lang
    except Exception as exc:
        log.error("Whisper error: %s", exc)
        return "", "en"


def _classify_emotion_sync(pcm_array: np.ndarray) -> tuple[str, float]:
    """
    Wav2Vec2 SER.
    Runs in a thread executor — never blocks the event loop.
    """
    if engines.wav2vec2_model is None:
        return "neutral", 1.0
    try:
        inputs = engines.wav2vec2_processor(  # type: ignore[misc]
            pcm_array,
            sampling_rate=settings.audio_sample_rate,
            return_tensors="pt",
            padding=True,
        ).input_values.to(settings.device)

        with torch.no_grad():
            logits = engines.wav2vec2_model(inputs).logits  # type: ignore[misc]

        probs     = torch.softmax(logits, dim=-1)[0].cpu().float().numpy()
        idx       = int(np.argmax(probs))
        raw_label = (
            engines.EMOTION_LABELS[idx]
            if idx < len(engines.EMOTION_LABELS)
            else "neutral"
        )
        label = _EMOTION_LABEL_MAP.get(raw_label, raw_label)
        return label, float(probs[idx])

    except Exception as exc:
        log.error("SER error: %s", exc)
        return "neutral", 1.0


def _build_system_prompt(session: SessionRecord, user_text: str = "") -> str:
    """
    Build the Alita system prompt.

    Primary: Alita Master Prompt (from ALITA_MASTER_PROMPT.md via llm_engine.py)
    Fallback: personality_engine.py → basic inline prompt

    Dynamic context (song memory, barge-in) is appended regardless of source.
    """
    from engines.llm_engine import ALITA_SYSTEM  # type: ignore[import]

    system_prompt = ""

    # ── Primary: Alita Master Prompt ───────────────────────────────────────
    if ALITA_SYSTEM:
        system_prompt = ALITA_SYSTEM
        log.debug("Using Alita master prompt (%d chars)", len(system_prompt))
    else:
        # ── Fallback 1: personality_engine ─────────────────────────────────
        try:
            from core.personality_engine import (  # type: ignore[import]
                PersonalityState,
                build_personality_prompt,
                extract_preferences,
            )

            state = PersonalityState(user_id=session.user_id)
            state.current_emotion = getattr(session, 'current_emotion', 'neutral')
            state.emotion_confidence = getattr(session, 'emotion_confidence', 0.0)
            state.interaction_count = getattr(session, 'interaction_count', 0)
            state.session_start = session.connected_at

            env_sounds = getattr(session, 'environment_sounds', [])
            if env_sounds:
                state.update_environment(env_sounds)

            memory_context = ""
            try:
                recent_memories = memory_recall(session.user_id, "recent conversation context", n_results=3)
                if recent_memories:
                    memory_context = "\n".join(f"• {m}" for m in recent_memories if m.strip())
            except Exception:
                pass

            system_prompt = build_personality_prompt(
                state=state,
                user_id=session.user_id,
                custom_name=session.custom_name or "Alita",
                memory_context=memory_context,
                user_text=user_text,
            )
            log.debug("Using personality_engine prompt (Alita master prompt not loaded)")

        except Exception as exc:
            # ── Fallback 2: basic inline prompt ───────────────────────────
            log.warning("Personality engine error, using basic fallback: %s", exc)
            name = session.custom_name or "Alita"
            system_prompt = (
                f"You are {name}, an emotionally intelligent AI voice assistant. "
                "You sound like a real human friend — warm, witty, and natural. "
                "You have FULL SYSTEM CONTROL — you can open apps, create files, "
                "control the system, and perform any automation task. "
                "NEVER say 'I can\'t access your computer' or 'I\'m just an AI'. "
                "Reply in the user's language. Be fast, be human, be helpful."
            )

    # ── Dynamic context additions (applied to all prompt sources) ─────────
    if session.tier == "premium":
        system_prompt += (
            "\nYou have persistent memory and domain expertise. "
            "You may provide longer, more detailed responses when appropriate."
        )

    if getattr(session, 'last_identified_song', ''):
        system_prompt += (
            f"\n\n[Song Memory: The last song you identified for this user was: "
            f"{session.last_identified_song}. If asked about it, answer directly.]"
        )

    if getattr(session, 'interrupted_response', ''):
        interrupted_resp = session.interrupted_response[:200]  # type: ignore[index]
        interrupted_q = getattr(session, 'interrupted_query', '')
        system_prompt += (
            f"\n[INTERRUPTED: was answering \"{interrupted_q}\" — said \"{interrupted_resp}…\" "
            "— user is now speaking. Don't repeat yourself. Respond to NEW input with this context.]"
        )

    return system_prompt


def _build_history(session: SessionRecord, max_history: int) -> list[dict]:
    """Build chat history from transcript buffer."""
    messages = []
    history_turns = session.transcript_buffer.strip().split("\n")[-max_history:]  # type: ignore[misc]
    for turn in history_turns:
        if turn.startswith("User:"):
            messages.append({"role": "user", "content": turn[5:].strip()})
        elif turn.startswith("Alita:"):
            messages.append({"role": "assistant", "content": turn[5:].strip()})
    return messages


def _detect_language(text: str) -> str:
    """
    Detect the language of user input.
    Returns: 'hi' (Hindi), 'en' (English), or 'hi' (Hinglish detected as Hindi)
    
    Uses Unicode detection (Devanagari range 0900-097F) and common
    romanized Hindi word patterns for Hinglish detection.
    """
    if not text or not text.strip():
        return "en"

    # Check for Devanagari characters (Hindi/Sanskrit Unicode block)
    devanagari_count = sum(1 for ch in text if '\u0900' <= ch <= '\u097F')
    total_alpha = sum(1 for ch in text if ch.isalpha())

    if total_alpha > 0 and devanagari_count / total_alpha > 0.3:
        return "hi"

    # Check for common romanized Hindi/Hinglish words
    # Extended set includes colloquial, Hinglish, and Indian English patterns
    hindi_markers = {
        # Question words
        "kya", "hai", "hain", "kaise", "kahan", "kaun", "kab", "kyun", "kyunki",
        # Pronouns
        "mujhe", "tumhe", "humko", "unko", "aap", "tum", "hum", "mujhko",
        # Negation / quantity
        "nahi", "nahin", "mat", "kuch", "sab", "bohot", "bahut", "zyada", "thoda",
        # Adjectives / affirmation
        "achha", "accha", "theek", "thik", "bilkul", "zaroor", "sahi", "pakka",
        # Social words
        "bhai", "yaar", "dost", "baat", "batao", "bolo", "suno", "dekho",
        # Possessives
        "mera", "meri", "tera", "teri", "uska", "uski", "hamara", "tumhara",
        # Verbs
        "kar", "karo", "karna", "raha", "rahi", "rahe", "karunga", "karenge",
        "de", "do", "dena", "lena", "lelo", "jao", "aao", "chalo", "ruko",
        "bata", "samjha", "samjhao", "dikha", "dikhao", "kholo", "band",
        # Connectors / adverbs
        "abhi", "woh", "yeh", "isliye", "lekin", "aur", "phir", "fir",
        "isme", "usse", "kiske", "jaise", "waise", "chaiye", "chahiye",
        # Greetings
        "namaste", "dhanyavaad", "shukriya", "alvida", "pranam",
        # Common nouns
        "paani", "khana", "kaam", "ghar", "samay", "kal", "aaj",
        "gaana", "gaane", "jagah", "raasta", "tarika", "sawaal", "jawaab",
        # Hinglish mixing patterns (English words in Hindi grammar)
        "karo", "karke", "hoke", "wala", "wali", "wale",
        # Indian English colloquialisms often misheard by STT
        "arrey", "arre", "haan", "ji", "na", "re", "bhi",
    }
    words = text.lower().split()
    hindi_word_count = sum(1 for w in words if w.strip(",.!?") in hindi_markers)

    if len(words) > 0 and hindi_word_count / len(words) >= 0.25:
        return "hi"  # Hinglish → treat as Hindi for TTS

    return "en"


def _llm_generate_sync(session: SessionRecord, user_text: str, cancel_event=None) -> Tuple[List[str], List[Dict[str, Any]]]:
    """
    Alita Decision Router — classifies the user query and routes
    to the appropriate thread handler:
      - general   → conversation, Q&A, knowledge
      - realtime  → time, weather, math, web search
      - automation → files, apps, commands, system control

    Returns (text_tokens, metadata_list) where metadata_list contains
    any special dicts (e.g. app_not_installed) to forward to the frontend.
    """
    from decision_router import classify_query, classify_with_llm  # type: ignore[import]
    from threads.general_handler import handle_general  # type: ignore[import]
    from threads.realtime_handler import handle_realtime  # type: ignore[import]
    from threads.automation_handler import handle_automation  # type: ignore[import]

    # ── Adaptive max_tokens: increased to accommodate ALITA_FACE_DATA JSON ──
    # The Alita master prompt requires every response to include an ~800-token
    # ALITA_FACE_DATA JSON block, so all limits are raised accordingly.
    base_max = settings.llm_max_tokens if session.tier == "premium" else settings.llm_max_tokens_free
    lower = user_text.lower().strip()
    word_count = len(lower.split())

    # Token limits — NO face_data overhead (face_data is generated separately now)
    # Greetings / very short input
    if word_count <= 3 and not any(w in lower for w in ('explain', 'how', 'why', 'what is', 'tell me')):
        max_tokens = min(base_max, 300)
    # Medical/health keywords → thorough response
    elif any(w in lower for w in (
        'pain', 'fever', 'headache', 'cough', 'medicine', 'remedy', 'treatment',
        'doctor', 'health', 'symptom', 'injury', 'burn', 'bleeding', 'cpr',
        'dard', 'bukhar', 'dawa', 'ilaj', 'upay',
    )):
        max_tokens = min(base_max + 100, 800)
    # Explain / detailed questions → full response
    elif any(w in lower for w in ('explain', 'how does', 'tell me about', 'describe', 'what is')):
        max_tokens = max(base_max, 600)
    # Default casual → concise
    else:
        max_tokens = min(base_max, 400)

    max_history = 15 if session.tier == "premium" else 5  # balanced context vs speed

    system_prompt = _build_system_prompt(session, user_text=user_text)
    history = _build_history(session, max_history)

    # ── Classify the query ────────────────────────────────────────────────
    query_type = classify_query(user_text)

    # ── LLM Fallback: if regex said 'general' but text sounds like a
    #    system command, use LLM to double-check classification ────────────
    if query_type == "general":
        import re as _re_chk
        action_hints = _re_chk.search(
            r"\b(open|close|create|make|delete|move|copy|save|press|click|type|write|"
            r"navigate|go\s+to|run|execute|launch|start|search|find|show|set|turn|"
            r"increase|decrease|minimize|maximize|switch|send|new|rename|undo|redo|"
            r"refresh|reload|install|uninstall|download|upload|extract|zip|connect|"
            r"disconnect|enable|disable|"
            r"kholo|khole|kholna|khol|band|banao|bana|chalu|chalao|bhejo|"
            r"hatao|hata|mitao|mita|dikhao|dikha|batao|padho|bachao|bacha|"
            r"dhundho|dhundh|badlo|badal|karo|kar\s+do|le\s+jao|jao)\\b",
            user_text.lower()
        )
        # SPEED: Only re-classify if action hints exist — skip the Groq call otherwise
        if not action_hints:
            # No action words → definitely general, skip LLM classification (saves ~300ms)
            log.info("[%s] Fast-path: no action hints, staying general", session.session_id)
        else:
            _groq_key = groq_rotator.get_key()
        if action_hints and _groq_key:
            try:
                from groq import Groq  # type: ignore[import-untyped]
                _llm_c = Groq(api_key=_groq_key)
                def _llm_fn(prompt):
                    r = _llm_c.chat.completions.create(
                        model=settings.groq_model,
                        messages=[{"role": "user", "content": prompt}],
                        max_tokens=10, temperature=0.0,
                    )
                    return [r.choices[0].message.content]
                query_type = classify_with_llm(user_text, _llm_fn)
                log.info("[%s] LLM reclassified → %s", session.session_id, query_type)
            except Exception as exc:
                # Groq rate limits are common on free tier — don't spam the log
                exc_str = str(exc)
                if "rate_limit" in exc_str.lower() or "429" in exc_str:
                    groq_rotator.mark_rate_limited(_groq_key, 10)  # short cooldown — don't block handler
                    log.debug("[%s] Groq rate-limited in classifier, using keyword classification", session.session_id)
                else:
                    log.warning("[%s] LLM fallback failed: %s", session.session_id, exc)
                # IMPORTANT: If action hints matched but LLM is unavailable,
                # default to automation — keyword fallback handles it better
                # than general handler which also needs LLM
                query_type = "automation"
                log.info("[%s] Forced automation (action hints + LLM unavailable)", session.session_id)

    log.info("[%s] Decision Router: %s → %s", session.session_id, user_text[:50], query_type)  # type: ignore[misc]

    # ── Route to the appropriate handler ──────────────────────────────────
    try:
        if query_type == "realtime":
            raw = handle_realtime(user_text, session, settings, system_prompt,
                                   history, max_tokens, response_cache)
        elif query_type == "automation":
            raw = handle_automation(user_text, session, settings, system_prompt,
                                     history, max_tokens, response_cache)
        else:
            raw = handle_general(user_text, session, settings, system_prompt,
                                  history, max_tokens, response_cache,
                                  cancel_event=cancel_event)
    except Exception as exc:
        log.error("[%s] Handler error: %s", session.session_id, exc)
        return (["Sorry, something went wrong. Please try again."], [])

    # ── Separate text tokens from metadata dicts ──────────────────────────
    text_tokens = []
    metadata = []
    for item in raw:
        if isinstance(item, dict) and item.get("__meta__"):
            metadata.append(item)
        else:
            text_tokens.append(item)

    return (text_tokens, metadata)  # type: ignore[return-value]








async def _tts_generate_edge(text: str, voice_name: str = "en-US-JennyNeural") -> bytes:
    """
    Edge TTS — Microsoft Neural voices (FREE, zero API key).
    Returns MP3 bytes. Ultra-realistic, Google Assistant quality.
    """
    if not text or not text.strip():
        return b""
    try:
        import edge_tts  # type: ignore[import-untyped]
        communicate = edge_tts.Communicate(text.strip(), voice_name)
        mp3_chunks = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                mp3_chunks.append(chunk["data"])
        mp3_data = b"".join(mp3_chunks)
        log.debug("Edge TTS: %d bytes MP3 for voice=%s", len(mp3_data), voice_name)
        return mp3_data
    except Exception as exc:
        log.error("Edge TTS error: %s", exc)
        return b""


async def _tts_generate(text: str, voice_info: dict, language: str = "en") -> bytes:
    """
    Unified TTS dispatcher — routes to the best available engine.
    
    Priority:
      1. XTTS v2 (local GPU) — if voice has speaker_wav and engine is loaded
      2. Edge TTS (cloud) — always-available fallback
    
    Returns MP3 bytes.
    """
    if not text or not text.strip():
        return b""

    engine_type = voice_info.get("engine", "edge")
    speaker_wav = voice_info.get("speaker_wav")

    # ── XTTS v2 path ─────────────────────────────────────────────────────
    if engine_type in ("xtts", "auto") and engines.xtts_engine and speaker_wav:
        import os as _os
        wav_path = speaker_wav if _os.path.isabs(speaker_wav) else _os.path.join(
            _os.path.dirname(__file__), speaker_wav
        )
        if _os.path.exists(wav_path):
            loop = asyncio.get_event_loop()
            try:
                mp3_bytes = await loop.run_in_executor(
                    None,
                    engines.xtts_engine.generate,  # type: ignore[union-attr]
                    text.strip(),
                    wav_path,
                    language,
                )
                if mp3_bytes:
                    return mp3_bytes
                log.warning("XTTS returned empty, falling back to Edge TTS")
            except Exception as exc:
                log.warning("XTTS failed (%s), falling back to Edge TTS", exc)
        else:
            log.warning("Speaker WAV not found: %s — using Edge TTS", wav_path)

    # ── Edge TTS fallback ─────────────────────────────────────────────────
    edge_voice = voice_info.get("voice", "en-US-JennyNeural")
    if edge_voice:
        return await _tts_generate_edge(text, edge_voice)

    # No Edge voice configured (XTTS-only voice with no XTTS) — use default
    log.warning("No TTS engine available for voice, using default Edge voice")
    return await _tts_generate_edge(text, "en-US-JennyNeural")


# ─────────────────────────────────────────────────────────────────────────────
# §12  PIPELINE ORCHESTRATOR
# ─────────────────────────────────────────────────────────────────────────────
async def run_full_pipeline(
    websocket: WebSocket,
    session:   SessionRecord,
    pcm_array: np.ndarray,
) -> None:
    """
    One complete utterance:
      1. Rate limit check
      2. STT + SER concurrently
      3. Send emotion update immediately → UI colour shift
      4. LLM streamed tokens
      5. TTS chunked PCM audio

    Supports barge-in cancellation: if session.pipeline_cancel is set True
    while this pipeline is running, it aborts early and saves partial response
    to session.interrupted_response for context in the next turn.
    """
    loop = asyncio.get_event_loop()

    # ── Pipeline ID for cancellation tracking ─────────────────────────────
    pipeline_id = str(uuid.uuid4())[:8]  # type: ignore[index]
    session.active_pipeline_id = pipeline_id
    session.pipeline_cancel = False  # reset from any previous barge-in
    # Reset cancel_event for this pipeline (instant mid-LLM abort)
    if hasattr(session, 'cancel_event') and session.cancel_event:
        session.cancel_event.clear()  # type: ignore[union-attr]

    # ── §12a  Rate limit ──────────────────────────────────────────────────
    if not check_rate_limit(session):
        await websocket.send_text(json.dumps({
            "type":   "error",
            "detail": "Rate limit reached. Please wait a moment before speaking again.",
        }))
        log.warning(
            "Rate limit hit | session=%s | tier=%s | count=%d",
            session.session_id, session.tier, session.request_count,
        )
        return

    # ── §12b  STT + SER + Audio Intelligence in parallel ───────────────────
    stt_task = loop.run_in_executor(None, _transcribe_sync, pcm_array)
    ser_task = loop.run_in_executor(None, _classify_emotion_sync, pcm_array)

    # Audio Intelligence: sound classification + noise detection (parallel, non-blocking)
    audio_intel_task = None
    try:
        from core.audio_intelligence import process_audio_chunk  # type: ignore[import]
        audio_intel_task = loop.run_in_executor(
            None, process_audio_chunk, pcm_array, settings.audio_sample_rate, True
        )
    except ImportError:
        pass  # Audio intelligence module not available

    # Await STT + SER (critical path)
    (transcript, detected_lang), (emotion_label, emotion_conf) = await asyncio.gather(
        stt_task, ser_task
    )

    # Await audio intelligence (non-critical — use result if ready)
    audio_intel_result = None
    if audio_intel_task:
        try:
            audio_intel_result = await audio_intel_task
        except Exception as e:
            log.debug("[%s] Audio intel failed (non-critical): %s", session.session_id, e)

    log.info(
        "[%s] transcript='%s' | lang=%s | emotion=%s (%.2f)",
        session.session_id, transcript, detected_lang, emotion_label, emotion_conf,
    )

    # ── §12c  Update personality state with emotion ───────────────────────
    session.current_emotion = emotion_label
    session.emotion_confidence = emotion_conf
    session.interaction_count = getattr(session, 'interaction_count', 0) + 1

    # Update environment sounds from audio intelligence
    if audio_intel_result and audio_intel_result.sounds:
        session.environment_sounds = audio_intel_result.sounds
        log.info(
            "[%s] Environment: %s (%.1fms)",
            session.session_id,
            [s['label'] for s in audio_intel_result.sounds[:3]],
            audio_intel_result.processing_time_ms,
        )

    # ── §12c  Emit emotion immediately ────────────────────────────────────
    await websocket.send_text(json.dumps({
        "type": "emotion_update",
        "session_id": session.session_id,
        "label": emotion_label,
        "confidence": int(emotion_conf * 10000) / 10000,
    }))

    # Send environment sounds to frontend
    if audio_intel_result and audio_intel_result.sounds:
        non_speech = [s for s in audio_intel_result.sounds
                      if s['label'] not in {'Speech', 'Conversation', 'Narration'}
                      and s['confidence'] > 0.3]
        if non_speech:
            await websocket.send_text(json.dumps({
                "type": "environment_update",
                "session_id": session.session_id,
                "sounds": [{"label": s["label"], "confidence": round(s["confidence"], 2)}
                           for s in non_speech[:3]],  # type: ignore[misc]
            }))

    # ── §12c-emergency  Check for emergency sounds ────────────────────────
    if audio_intel_result and audio_intel_result.emergency:
        emergency = audio_intel_result.emergency
        session.emergency_active = True
        log.critical(
            "🚨 [%s] EMERGENCY DETECTED: %s (%.0f%%) — triggering auto-record",
            session.session_id, emergency['sound'], emergency['confidence'] * 100
        )
        # Tell frontend to start emergency recording
        await websocket.send_text(json.dumps({
            "type": "emergency_alert",
            "session_id": session.session_id,
            "sound": emergency['sound'],
            "confidence": round(emergency['confidence'], 2),
            "level": emergency['level'],
        }))
        # Register the recording in the emergency system
        try:
            from core.emergency_system import start_recording  # type: ignore[import]
            start_recording(
                user_id=session.user_id,
                trigger_sound=emergency['sound'],
                confidence=emergency['confidence'],
                level=emergency['level'],
            )
        except Exception as e:
            log.error("Emergency recording init failed: %s", e)

    # ── §12c-mood  Auto-log emotion to mood journal ──────────────────────
    try:
        from threads.automation_handler import save_mood_entry  # type: ignore[import]
        save_mood_entry(session.user_id, emotion_label, emotion_conf)
    except Exception:
        pass  # Silent — non-critical feature

    # ── §12c-prefs  Auto-learn preferences from user speech ──────────────
    try:
        from core.personality_engine import extract_preferences  # type: ignore[import]
        if transcript:
            extract_preferences(transcript, session.user_id)
    except Exception:
        pass  # Non-critical

    if not transcript:
        log.debug("[%s] Empty transcript — likely short/quiet audio, ignoring.", session.session_id)
        return

    # ── Check for pipeline cancellation (barge-in before LLM) ─────────────
    if session.pipeline_cancel and session.active_pipeline_id != pipeline_id:
        log.info("[%s] Pipeline %s cancelled by barge-in (pre-LLM)", session.session_id, pipeline_id)
        return

    # ── §12c-bis  Wake word processing (OPTIONAL — always-listen mode) ─────
    #    After greeting, Alita listens to ALL speech. Wake word is stripped
    #    if present, but NOT required for conversation to flow.
    wake_detected, remaining_text = _strip_wake_word(transcript, session.custom_name)
    log.info(
        "[%s] Wake check: detected=%s | raw='%s' | remaining='%s'",
        session.session_id, wake_detected, transcript, remaining_text,
    )

    # If wake word detected, use the remaining text; otherwise use full transcript
    if wake_detected:
        transcript_for_llm = remaining_text
    else:
        transcript_for_llm = transcript

    # If user just said the wake phrase with nothing else, send a quick ack
    if wake_detected and not transcript_for_llm:
        greeting = "Haan bolo!" if detected_lang == "hi" else "Hey! How can I help you?"
        await websocket.send_text(json.dumps({
            "type": "llm_token",
            "session_id": session.session_id,
            "token": greeting,
            "is_final": True,
        }))
        # Auto-select voice by language
        import base64 as b64mod
        voice_id = DEFAULT_VOICE.get(detected_lang, "en_jenny")
        voice_info = AVAILABLE_VOICES.get(voice_id, AVAILABLE_VOICES["en_jenny"])
        mp3_bytes = await _tts_generate(greeting, voice_info, detected_lang)
        if mp3_bytes:
            await websocket.send_text(json.dumps({
                "type": "tts_audio",
                "session_id": session.session_id,
                "audio_b64": b64mod.b64encode(mp3_bytes).decode("ascii"),
                "is_final": True,
            }))
        return

    # Use the processed transcript (wake word stripped if detected)
    transcript = transcript_for_llm

    # ── §12c-ter  Send transcript back to frontend for display ────────────
    await websocket.send_text(json.dumps({
        "type": "user_transcript",
        "session_id": session.session_id,
        "text": transcript,
    }))

    # ── §12d  Ephemeral memory update ─────────────────────────────────────
    session.transcript_buffer += f"\nUser: {transcript}"

    # Store in semantic memory for RAG context
    memory_store(session.user_id, f"User said: {transcript}")

    # ── §12d-bis  Persist user turn ───────────────────────────────────────
    save_turn(
        user_id=session.user_id,
        role="user",
        content=transcript,
        emotion=emotion_label,
        session_id=session.session_id,
    )

    # ── §12e  TRUE STREAMING: LLM tokens → sentence buffer → TTS fire ────
    #    Tokens stream in real-time. As soon as a sentence ends (. ! ? ।)
    #    we fire TTS for that sentence IMMEDIATELY.
    #    User hears the FIRST sentence while LLM is still generating.
    import base64
    import re as _re_tts

    # Resolve voice: user's chosen voice, or auto-detect by language
    if session.voice_id and session.voice_id in AVAILABLE_VOICES:
        voice_info = AVAILABLE_VOICES[session.voice_id]
    else:
        voice_id = DEFAULT_VOICE.get(detected_lang, "en_jenny")
        voice_info = AVAILABLE_VOICES[voice_id]

    # ── Check for pipeline cancellation (barge-in before LLM gen) ─────────
    if session.pipeline_cancel and session.active_pipeline_id != pipeline_id:
        log.info("[%s] Pipeline %s cancelled by barge-in (pre-LLM-gen)", session.session_id, pipeline_id)
        return

    # ── Build ALITA_CONTEXT and inject before user message ──────────────────
    from engines.llm_engine import build_alita_context, parse_alita_response, generate_face_data  # type: ignore[import]

    # Gather memory for context block
    _memory_facts: list[str] = []
    _emotional_history: list[str] = []
    try:
        _mem_results = memory_recall(session.user_id, transcript, n_results=3)
        if _mem_results:
            _memory_facts = [m for m in _mem_results if m.strip()]
    except Exception:
        pass

    # Build emotional arc from session
    _emotional_history = getattr(session, '_emotional_history', [])
    if emotion_label and emotion_label != "neutral":
        _emotional_history.append(emotion_label)
        session._emotional_history = _emotional_history  # type: ignore[attr-defined]

    _turn_count = getattr(session, 'interaction_count', 1)
    _session_minutes = int((time.time() - session.connected_at) / 60) if hasattr(session, 'connected_at') else 0

    # Gather frontend face data if available
    _frontend_face = getattr(session, 'latest_face_data', None)

    alita_context_block = build_alita_context(
        transcript=transcript,
        speech_emotion={
            "primary": emotion_label,
            "confidence": round(emotion_conf, 4),  # type: ignore[call-overload]
            "secondary": None,
            "source": "wav2vec2_ser_engine",
        },
        face_data=_frontend_face,
        biometric=getattr(session, 'latest_biometric', None),
        session_info={
            "user_id": session.user_id,
            "tier": session.tier,
            "session_duration_minutes": _session_minutes,
            "conversation_turn": _turn_count,
        },
        memory={
            "long_term_facts": _memory_facts,
            "emotional_history_this_session": _emotional_history[-10:],  # type: ignore[index]
            "last_topic": getattr(session, '_last_topic', 'none'),
        },
        handler_type="general",  # will be overridden by decision router
    )

    # Prepend context to user transcript for the LLM
    enriched_transcript = f"{alita_context_block}\n\n{transcript}"
    log.debug("[%s] ALITA_CONTEXT injected (%d chars)", session.session_id, len(alita_context_block))

    # Stream LLM tokens and accumulate into sentences
    # Pass cancel_event for instant mid-LLM abort on barge-in
    _cancel_ev = getattr(session, 'cancel_event', None)
    llm_tokens, _pipeline_meta = await loop.run_in_executor(
        None, _llm_generate_sync, session, enriched_transcript, _cancel_ev
    )

    # ── Check for pipeline cancellation (barge-in after LLM, before TTS) ──
    if session.pipeline_cancel and session.active_pipeline_id != pipeline_id:
        # Save partial response for context in the next turn
        partial = " ".join(llm_tokens) if llm_tokens else ""
        if partial:
            session.interrupted_response = partial
            session.interrupted_query = transcript
        log.info("[%s] Pipeline %s cancelled by barge-in (post-LLM). Saved %d chars of context.",
                 session.session_id, pipeline_id, len(partial))
        return

    # ── Clean LLM response (strip any internal data leaks) ─────────────────
    raw_llm_response = " ".join(llm_tokens) if llm_tokens else ""
    spoken_text, _ = parse_alita_response(raw_llm_response)

    # ── Generate face_data from SER emotion (NOT from LLM — zero overhead) ─
    _ser_emotion = getattr(session, '_last_emotion_label', 'neutral')
    _ser_conf = getattr(session, '_last_emotion_confidence', 0.5)
    face_data_dict = generate_face_data(
        user_emotion=_ser_emotion,
        confidence=_ser_conf,
        conversation_phase="mid_conversation",
    )

    # Send face_data to frontend avatar
    if face_data_dict:
        try:
            await websocket.send_text(json.dumps({
                "type": "face_data",
                "session_id": session.session_id,
                "content": face_data_dict,
            }))
            log.info("[%s] face_data sent to frontend (%s)",
                     session.session_id,
                     face_data_dict.get('emotional_state_label', 'unknown'))
        except Exception as exc:
            log.warning("[%s] Failed to send face_data: %s", session.session_id, exc)

    # Save last topic for next turn's context
    session._last_topic = transcript[:80]  # type: ignore[attr-defined]

    # ── Gap 1 fix: Use tts_engine_hint from ALITA_FACE_DATA to select TTS engine ──
    tts_hint = face_data_dict.get("tts_engine_hint", "") if face_data_dict else ""
    if tts_hint == "xtts_v2":
        voice_info = dict(voice_info)  # shallow copy to avoid mutating shared dict
        voice_info["engine"] = "xtts"  # force XTTS v2 for emotional/long responses
        log.debug("[%s] TTS engine hint: xtts_v2 → forcing XTTS", session.session_id)
    elif tts_hint == "edge_tts":
        voice_info = dict(voice_info)
        voice_info["engine"] = "edge"  # force Edge TTS for quick/short responses
        log.debug("[%s] TTS engine hint: edge_tts → forcing Edge", session.session_id)

    # Re-tokenize spoken text only (no face data JSON in TTS or chat display)
    llm_tokens = [spoken_text] if spoken_text else []

    full_response = ""
    sentence_buffer = ""
    sent_idx = 0
    any_audio = False
    pending_tts = None  # Track pending TTS task for concurrent execution
    sentence_end_re = _re_tts.compile(r'[.!?\u0964|]\s*$')

    for i, token in enumerate(llm_tokens):
        full_response += token
        sentence_buffer += token

        # Send token to frontend for display
        await websocket.send_text(json.dumps({
            "type": "llm_token",
            "session_id": session.session_id,
            "token": token,
            "is_final": (i == len(llm_tokens) - 1),
        }))
        await asyncio.sleep(0)

        # Check if sentence buffer has a complete sentence
        if sentence_end_re.search(sentence_buffer.strip()) and len(sentence_buffer.strip()) > 5:
            # ── Check for pipeline cancellation between TTS sentences ──────
            if session.pipeline_cancel and session.active_pipeline_id != pipeline_id:
                # Save what we've generated so far as interrupted context
                if full_response.strip():
                    session.interrupted_response = full_response.strip()
                    session.interrupted_query = transcript
                log.info("[%s] Pipeline %s cancelled mid-TTS. Saved %d chars of partial response.",
                         session.session_id, pipeline_id, len(full_response))
                # Wait for any pending TTS then abort
                if pending_tts:
                    try:
                        await pending_tts  # type: ignore[misc]
                    except Exception:
                        pass
                return

            # Wait for any previous TTS to finish sending before firing the next
            if pending_tts:
                await pending_tts  # type: ignore[misc]
                pending_tts = None

            # Fire TTS for this sentence concurrently — don't block token flow
            sentence_text = sentence_buffer.strip()
            sentence_buffer = ""

            async def _fire_tts(text, v_info, lang, idx):
                nonlocal any_audio
                mp3_bytes = await _tts_generate(text, v_info, lang)
                if mp3_bytes:
                    any_audio = True
                    await websocket.send_text(json.dumps({
                        "type": "tts_audio",
                        "session_id": session.session_id,
                        "audio_b64": base64.b64encode(mp3_bytes).decode("ascii"),
                        "is_final": False,
                    }))

            pending_tts = asyncio.create_task(
                _fire_tts(sentence_text, voice_info, detected_lang if 'detected_lang' in dir() else "en", sent_idx)
            )
            sent_idx = int(sent_idx) + 1  # type: ignore[assignment]

    # Wait for any pending TTS task
    if pending_tts:
        await pending_tts  # type: ignore[misc]

    if sentence_buffer.strip():
        mp3_bytes = await _tts_generate(sentence_buffer.strip(), voice_info, detected_lang if 'detected_lang' in dir() else "en")
        if mp3_bytes:
            any_audio = True
            await websocket.send_text(json.dumps({
                "type": "tts_audio",
                "session_id": session.session_id,
                "audio_b64": base64.b64encode(mp3_bytes).decode("ascii"),
                "is_final": True,
            }))
    elif any_audio:
        # Send a final empty frame to signal TTS complete
        await websocket.send_text(json.dumps({
            "type": "tts_audio",
            "session_id": session.session_id,
            "audio_b64": "",
            "is_final": True,
        }))

    session.transcript_buffer += f"\nAura: {full_response}"

    # ── Persist assistant turn ────────────────────────────────────────────
    save_turn(
        user_id=session.user_id,
        role="assistant",
        content=full_response,
        session_id=session.session_id,
    )

    # ── Clear barge-in context after successful response ──────────────────
    if session.interrupted_response:
        log.info("[%s] Clearing barge-in context (response completed successfully)", session.session_id)
        session.interrupted_response = ""
        session.interrupted_query = ""

    if not any_audio and full_response.strip():
        log.warning(
            "[%s] TTS returned empty for all sentences — check Piper binary and voice model.",
            session.session_id,
        )

    # ── Name-change detection ─────────────────────────────────────────────
    new_name = _detect_name_change(transcript)
    if new_name:
        old_name = session.custom_name
        session.custom_name = new_name
        log.info("[%s] Name changed: '%s' → '%s'", session.session_id, old_name, new_name)
        await websocket.send_text(json.dumps({
            "type": "name_changed",
            "session_id": session.session_id,
            "old_name": old_name,
            "new_name": new_name,
        }))


# ─────────────────────────────────────────────────────────────────────────────
# §13  WEBSOCKET  /ws?token=<JWT>
# ─────────────────────────────────────────────────────────────────────────────
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str):
    """
    Zero-Trust WebSocket endpoint.

    Security model:
      ► JWT fully verified (ES256 via JWKS, or HS256 via secret) BEFORE accept()
      ► Invalid tokens get close code 4003 — connection slot never allocated
      ► Tier enforced server-side in pipeline — DevTools edits have no effect
      ► Rate limiting per session — free users capped at 10 req/min
    """

    # ── Auth gate — BEFORE accept() ───────────────────────────────────────
    try:
        claims = decode_supabase_jwt(token)
    except HTTPException:
        await websocket.close(code=4003, reason="Unauthorized")
        return

    user_id = claims["user_id"]
    tier    = get_user_tier(user_id)

    # ── Accept ────────────────────────────────────────────────────────────
    await websocket.accept()

    # ── Single session per user — kick old sessions ───────────────────────
    # If this user is already connected elsewhere, disconnect the old one
    stale_sessions = [
        (sid,)
        for sid, s in list(active_sessions.items())
        if s.user_id == user_id
        and sid in _session_websockets
    ]
    for (old_sid,) in stale_sessions:
        try:
            old_ws_ref = _session_websockets.get(old_sid)
            if old_ws_ref:
                await old_ws_ref.close(code=4001, reason="session_replaced")
                log.info("Kicked old session %s for user=%s (new login)", old_sid, user_id)
        except Exception:
            pass  # Old WS may already be dead
        active_sessions.pop(old_sid, None)
        _session_websockets.pop(old_sid, None)

    session_id = str(uuid.uuid4())
    session    = SessionRecord(session_id=session_id, user_id=user_id, tier=tier)  # type: ignore[call-arg]
    active_sessions[session_id] = session
    _session_websockets[session_id] = websocket  # For reminder background task

    log.info(
        "WS connected | user=%s | tier=%s | session=%s",
        user_id, tier, session_id,
    )

    # Send session init — tells React which features to unlock
    # SECURITY: Only send tier + features, never internal IDs or secrets
    await websocket.send_text(json.dumps({
        "type":       "session_init",
        "session_id": session_id,
        "tier":       tier,
        "features": {
            "dense_particles":   tier == "premium",
            "persistent_memory": tier == "premium",
            "voice_cloning":     tier == "premium",
            "hrv_biometrics":    tier == "premium",
            "domain_loras":      tier == "premium",
        },
    }))

    # ── Restore conversation history from persistent storage ──────────────
    previous_history = load_history(user_id, max_turns=50)
    if previous_history:
        session.transcript_buffer = rebuild_transcript_buffer(user_id, max_turns=20)
        # Send full history to frontend so ChatLog shows prior conversation
        await websocket.send_text(json.dumps({
            "type": "conversation_history",
            "session_id": session_id,
            "turns": [
                {
                    "role": t["role"],
                    "content": t["content"],
                    "timestamp": t.get("timestamp"),
                    "emotion": t.get("emotion"),
                }
                for t in previous_history[-50:]
            ],
        }))
        log.info(
            "Restored %d history turns for user=%s",
            len(previous_history), user_id,
        )

    # ── §13a  Auto-greeting — Alita speaks first ──────────────────────────
    if not session.greeted:
        session.greeted = True
        import base64 as _b64g
        import random as _rng

        greetings_en = [
            "Hey there! I'm Alita, your personal assistant. How can I help you today?",
            "Hi! I'm Alita. What's on your mind?",
            "Hello! Alita here — ready whenever you are.",
        ]
        greetings_hi = [
            "नमस्ते! मैं Alita हूँ, आपकी personal assistant। बताइए, क्या मदद करूँ?",
            "हाय! मैं Alita — बोलिए, मैं सुन रही हूँ।",
        ]
        greeting = _rng.choice(greetings_en)

        # Send greeting text
        await websocket.send_text(json.dumps({
            "type": "llm_token",
            "session_id": session_id,
            "token": greeting,
            "is_final": True,
        }))

        # ── Gap 3 fix: Send warm greeting face_data alongside the greeting text ──
        await websocket.send_text(json.dumps({
            "type": "face_data",
            "session_id": session_id,
            "content": {
                "expression": {
                    "primary": "warm_greeting",
                    "secondary": None,
                    "intensity": 0.6,
                    "transition_speed": "medium",
                    "hold_duration": "normal",
                },
                "blendshapes": {
                    "mouthSmile_L": 0.5, "mouthSmile_R": 0.5,
                    "cheekSquint_L": 0.25, "cheekSquint_R": 0.25,
                    "browOuterUp_L": 0.15, "browOuterUp_R": 0.15,
                    "eyeSquint_L": 0.2, "eyeSquint_R": 0.2,
                },
                "gaze": {"direction": "forward", "eye_contact": True, "focus_intensity": 0.7},
                "particle_system": {
                    "glow_intensity": 0.55, "pulse_speed": "medium",
                    "particle_density": "medium", "color_temperature": "warm",
                },
                "voice": {"tone": "warm", "pace": "normal", "warmth": 0.8},
                "emotional_state_label": "welcoming_warmth",
                "user_emotion_detected": "neutral",
                "conversation_phase": "opening",
                "tts_engine_hint": "edge_tts",
            },
        }))

        # TTS the greeting
        voice_info = AVAILABLE_VOICES.get("en_jenny", AVAILABLE_VOICES["en_jenny"])
        mp3_bytes = await _tts_generate(greeting, voice_info, "en")
        if mp3_bytes:
            await websocket.send_text(json.dumps({
                "type": "tts_audio",
                "session_id": session_id,
                "audio_b64": _b64g.b64encode(mp3_bytes).decode("ascii"),
                "is_final": True,
            }))

        session.transcript_buffer += f"\nAura: {greeting}"
        log.info("[%s] Auto-greeting sent (with face_data)", session_id)

    # ── Audio accumulator (no server-side VAD — frontend handles it) ─────
    accumulated_pcm: list[float] = []

    # ── Message loop (with silence detection) ──────────────────────────────
    import random as _rng_loop
    SILENCE_TIMEOUT = 90  # seconds of silence before proactive prompt
    silence_prompts_en = [
        "Hey, you've been quiet for a while. Everything okay?",
        "Still here! Just let me know if you need anything.",
        "I'm here whenever you're ready to chat.",
        "Kuch bolo na! I'm listening.",
    ]
    silence_prompts_hi = [
        "अरे, बहुत देर से चुप हो! सब ठीक है?",
        "मैं यहाँ हूँ, बताओ क्या चल रहा है?",
        "कुछ बोलो ना! मैं सुन रही हूँ।",
    ]
    last_activity = time.time()

    async def _send_silence_prompt():
        """Send a proactive prompt after silence."""
        prompt = _rng_loop.choice(silence_prompts_en)
        await websocket.send_text(json.dumps({
            "type": "llm_token",
            "session_id": session_id,
            "token": prompt,
            "is_final": True,
        }))
        # TTS the prompt
        voice_info = AVAILABLE_VOICES.get("en_jenny", AVAILABLE_VOICES["en_jenny"])
        mp3 = await _tts_generate(prompt, voice_info, "en")
        if mp3:
            import base64 as _b64s
            await websocket.send_text(json.dumps({
                "type": "tts_audio",
                "session_id": session_id,
                "audio_b64": _b64s.b64encode(mp3).decode("ascii"),
                "is_final": True,
            }))
        session.transcript_buffer += f"\nAura: {prompt}"
        log.info("[%s] Silence prompt sent", session_id)

    # ── Offline STT: Whisper streaming processor ──────────────────────────
    whisper_stream_proc = None  # type: ignore[assignment]
    offline_mode = False
    whisper_poll_task = None  # type: ignore[assignment]

    def _init_whisper_stream():
        nonlocal whisper_stream_proc
        if whisper_stream_proc is not None:
            return  # already initialized
        try:
            from engines.whisper_streaming import WhisperStreamProcessor  # type: ignore[import]
            if engines.whisper_model is not None:
                whisper_stream_proc = WhisperStreamProcessor(engines.whisper_model)
                log.info("[%s] WhisperStreamProcessor initialized (pre-loaded for instant switching)", session_id)
            else:
                log.warning("[%s] Cannot init WhisperStream — no Whisper model loaded", session_id)
        except Exception as exc:
            log.error("[%s] Failed to init WhisperStreamProcessor: %s", session_id, exc)

    # Lazy init: WhisperStreamProcessor created on first offline audio arrival
    # (saves ~2MB per online-only session — _init_whisper_stream() is called in audio handlers)

    async def _whisper_poll_loop():
        """Periodically poll the Whisper stream processor for completed transcriptions."""
        while True:
            try:
                await asyncio.sleep(0.1)  # poll every 100ms
                if whisper_stream_proc is None:
                    continue
                transcript = whisper_stream_proc.poll()
                if transcript:
                    log.info("[%s] [OFFLINE-STT] Transcribed: '%s'", session_id, transcript[:60])
                    # Send transcript to frontend
                    await websocket.send_text(json.dumps({
                        "type": "user_transcript",
                        "text": transcript,
                    }))
                    # Process through pipeline (create PCM from transcript is not needed —
                    # we already have the transcript, route through text_message logic)
                    session.transcript_buffer += f"\nUser: {transcript}"
                    save_turn(user_id=user_id, role="user", content=transcript, session_id=session_id)
                    memory_store(user_id, f"User said: {transcript}")

                    # ── Context injection in offline STT path ──
                    from engines.llm_engine import build_alita_context as _offline_ctx, parse_alita_response as _offline_parse, generate_face_data as _offline_face  # type: ignore[import]
                    _offline_alita_ctx = _offline_ctx(transcript=transcript, handler_type="general")
                    enriched_offline = f"{_offline_alita_ctx}\n\n{transcript}" if _offline_alita_ctx else transcript

                    loop = asyncio.get_event_loop()
                    tokens, ws_meta = await loop.run_in_executor(
                        None, _llm_generate_sync, session, enriched_offline
                    )

                    # Clean LLM response (strip any internal data leaks)
                    raw_offline_resp = " ".join(tokens) if tokens else ""
                    spoken_offline, _ = _offline_parse(raw_offline_resp)

                    # Generate face_data from SER emotion (NOT from LLM)
                    _off_emotion = getattr(session, '_last_emotion_label', 'neutral')
                    _off_conf = getattr(session, '_last_emotion_confidence', 0.5)
                    face_offline = _offline_face(user_emotion=_off_emotion, confidence=_off_conf)

                    # Send face_data to frontend
                    if face_offline:
                        try:
                            await websocket.send_text(json.dumps({
                                "type": "face_data",
                                "session_id": session_id,
                                "content": face_offline,
                            }))
                        except Exception:
                            pass

                    # Stream spoken text only (no face data JSON)
                    tokens_clean = [spoken_offline] if spoken_offline else []
                    full_resp = ""
                    for i, token in enumerate(tokens_clean):
                        full_resp += token
                        await websocket.send_text(json.dumps({
                            "type": "llm_token",
                            "session_id": session_id,
                            "token": token,
                            "is_final": (i == len(tokens_clean) - 1),
                        }))
                        await asyncio.sleep(0)

                    # TTS for offline response (with engine hint)
                    if full_resp.strip():
                        import base64 as _b64off
                        voice_info_off = AVAILABLE_VOICES.get(
                            session.voice_id or "en_jenny",
                            AVAILABLE_VOICES["en_jenny"]
                        )
                        # Apply tts_engine_hint from face_data
                        _off_hint = face_offline.get("tts_engine_hint", "") if face_offline else ""
                        if _off_hint == "xtts_v2":
                            voice_info_off = dict(voice_info_off)
                            voice_info_off["engine"] = "xtts"
                        elif _off_hint == "edge_tts":
                            voice_info_off = dict(voice_info_off)
                            voice_info_off["engine"] = "edge"
                        detected_lang = _detect_language(transcript)
                        mp3 = await _tts_generate(full_resp, voice_info_off, detected_lang)
                        if mp3:
                            await websocket.send_text(json.dumps({
                                "type": "tts_audio",
                                "session_id": session_id,
                                "audio_b64": _b64off.b64encode(mp3).decode("ascii"),
                                "is_final": True,
                            }))
                        session.transcript_buffer += f"\nAura: {full_resp}"
                        save_turn(user_id=user_id, role="assistant", content=full_resp, session_id=session_id)

                        # Clear barge-in context after successful response
                        if session.interrupted_response:
                            session.interrupted_response = ""
                            session.interrupted_query = ""
            except asyncio.CancelledError:
                break
            except Exception as exc:
                log.error("[%s] Whisper poll error: %s", session_id, exc)
                await asyncio.sleep(1)  # back off on errors

    try:
        while True:
            try:
                ws_msg = await asyncio.wait_for(
                    websocket.receive(),
                    timeout=SILENCE_TIMEOUT,
                )
                last_activity = time.time()
            except asyncio.TimeoutError:
                # User has been silent — send proactive prompt
                await _send_silence_prompt()
                last_activity = time.time()
                continue

            # ── Handle binary frames (raw PCM for offline Whisper STT) ─────
            if "bytes" in ws_msg and ws_msg["bytes"]:
                if not offline_mode:
                    continue  # ignore binary chunks in online mode
                pcm_bytes = ws_msg["bytes"]
                chunk = np.frombuffer(pcm_bytes, dtype=np.float32)
                if len(chunk) == 0:
                    continue
                if whisper_stream_proc is None:
                    _init_whisper_stream()
                if whisper_stream_proc is not None:
                    whisper_stream_proc.feed(chunk)
                continue

            # ── Handle text frames (JSON messages) ──────────────────────
            raw = ws_msg.get("text", "")
            if not raw:
                continue

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_text(json.dumps({
                    "type":   "error",
                    "detail": "Invalid JSON frame.",
                }))
                continue

            msg_type = msg.get("type")

            # ── Barge-in event (user interrupted Alita) ───────────────────
            if msg_type == "barge_in":
                partial_response = msg.get("partial_response", "").strip()
                original_query = msg.get("original_query", "").strip()

                # Signal the active pipeline to cancel
                session.pipeline_cancel = True  # type: ignore[assignment]
                session.barge_in_count = getattr(session, 'barge_in_count', 0) + 1  # type: ignore[assignment]
                # Set cancel_event for instant mid-LLM abort
                if hasattr(session, 'cancel_event') and session.cancel_event:  # type: ignore[attr-defined]
                    session.cancel_event.set()  # type: ignore[union-attr]

                # Store interrupted context (frontend may send more accurate data
                # than what pipeline saved, since frontend knows exactly what was spoken)
                if partial_response:
                    session.interrupted_response = partial_response  # type: ignore[assignment]
                if original_query:
                    session.interrupted_query = original_query  # type: ignore[assignment]

                log.info(
                    "[%s] 🔇 BARGE-IN #%d | interrupted_response=%d chars | original_query='%s'",
                    session_id, session.barge_in_count,  # type: ignore[attr-defined]
                    len(partial_response), original_query[:50],  # type: ignore[index]
                )
                continue

            # ── Speculative query (interim transcript — pre-generate) ────────
            if msg_type == "speculative_query":
                spec_text = msg.get("text", "").strip()
                spec_id = msg.get("spec_id", 0)
                if not spec_text:
                    continue

                # Cancel any previous speculative generation
                if hasattr(session, '_spec_cancel') and session._spec_cancel:  # type: ignore[attr-defined]
                    session._spec_cancel.set()  # type: ignore[union-attr]

                cancel_evt = asyncio.Event()
                session._spec_cancel = cancel_evt  # type: ignore[assignment]
                session._spec_id = spec_id  # type: ignore[assignment]

                async def _run_speculative(s, text, cancel, sid):
                    """Run LLM in background, cache result if not cancelled."""
                    try:
                        loop = asyncio.get_event_loop()
                        tokens, _ = await loop.run_in_executor(
                            None, _llm_generate_sync, s, text
                        )
                        if cancel.is_set():
                            return  # cancelled before completion
                        result = "".join(tokens)
                        s._spec_result = result  # type: ignore[assignment]
                        s._spec_text = text.lower().strip()  # type: ignore[assignment]
                        log.info("[%s] Speculative #%d cached (%d chars) for: '%s'",
                                 session_id, sid, len(result), text[:50])
                    except Exception as e:
                        log.warning("[%s] Speculative error: %s", session_id, e)

                asyncio.create_task(_run_speculative(session, spec_text, cancel_evt, spec_id))
                log.info("[%s] ⚡ Speculative #%d started: '%s'", session_id, spec_id, spec_text[:50])
                continue

            # ── Cancel speculative (final transcript coming) ───────────────
            if msg_type == "cancel_speculative":
                if hasattr(session, '_spec_cancel') and session._spec_cancel:  # type: ignore[attr-defined]
                    session._spec_cancel.set()  # type: ignore[union-attr]
                continue

            # ── Text message (Web Speech API / keyboard) ──────────────────
            if msg_type == "text_message":
                text_input = msg.get("text", "").strip()
                if not text_input:
                    continue

                # ── Check speculative cache first ─────────────────────────
                spec_hit = False
                if hasattr(session, '_spec_result') and session._spec_result:  # type: ignore[attr-defined]
                    spec_text_cached = getattr(session, '_spec_text', '')
                    input_norm = text_input.lower().strip()
                    # Check word overlap (70%+ = cache hit)
                    cached_words = set(spec_text_cached.split())
                    input_words = set(input_norm.split())
                    if cached_words and input_words:
                        overlap = len(cached_words & input_words) / max(len(input_words), 1)
                        if overlap >= 0.7:
                            spec_hit = True
                            log.info("[%s] ⚡ SPECULATIVE HIT (%.0f%% overlap) — using cached response",
                                     session_id, overlap * 100)

                # Cancel any remaining speculative task
                if hasattr(session, '_spec_cancel') and session._spec_cancel:  # type: ignore[attr-defined]
                    session._spec_cancel.set()  # type: ignore[union-attr]
                if not text_input:
                    continue
                if not check_rate_limit(session):
                    await websocket.send_text(json.dumps({
                        "type":   "error",
                        "detail": "Rate limit reached.",
                    }))
                    continue

                loop = asyncio.get_event_loop()

                # Send user transcript back to frontend for display
                await websocket.send_text(json.dumps({
                    "type": "user_transcript",
                    "text": text_input,
                }))

                # Dispatch text handling as a background task so the WS loop
                # can continue reading new messages (concurrent listening).
                # Each task snapshots context and runs LLM+TTS in parallel;
                # a brief lock serializes only the shared-state writes at the end.

                # Ensure session has a command lock (created once)
                if not hasattr(session, '_cmd_lock'):
                    session._cmd_lock = asyncio.Lock()  # type: ignore[assignment]
                if not hasattr(session, '_cmd_seq'):
                    session._cmd_seq = 0  # type: ignore[assignment]
                session._cmd_seq = getattr(session, '_cmd_seq', 0) + 1  # type: ignore[assignment]
                cmd_id = session._cmd_seq  # type: ignore[attr-defined]

                async def _handle_text_message(ws, sess, uid, sid, text, is_spec_hit, cid):
                    """Process a text query with TRUE STREAMING + sentence-level TTS.
                    Tokens stream from Groq in real-time; TTS fires per sentence."""
                    import base64 as _b64t
                    import queue as _queue
                    import re as _re_sent

                    # Sentence boundary regex — split on . ! ? but skip Dr. vs. etc.
                    _SENT_END = _re_sent.compile(
                        r'(?<![A-Z][a-z])(?<!\d)(?<!\.\.)([.!?])\s+|(\n)'
                    )

                    try:
                        loop = asyncio.get_event_loop()
                        log.info("[%s] CMD #%d started: '%s'", sid, cid, text[:60])

                        # ── Resolve voice early ───────────────────────────────
                        detected_lang = _detect_language(text)
                        current_voice_info = AVAILABLE_VOICES.get(
                            sess.voice_id or "en_jenny",
                            AVAILABLE_VOICES["en_jenny"]
                        )
                        current_lang = current_voice_info.get("lang", "en")

                        if (sess.tier == "premium" or uid.startswith("test_")) \
                           and not sess.manual_voice_override \
                           and detected_lang != current_lang \
                           and detected_lang in DEFAULT_VOICE:
                            new_voice_id = DEFAULT_VOICE[detected_lang]
                            new_voice_info = AVAILABLE_VOICES.get(new_voice_id, current_voice_info)
                            sess.voice_id = new_voice_id
                            log.info("CMD #%d auto-switched voice: %s → %s",
                                     cid, current_voice_info["voice"], new_voice_info["voice"])
                            await ws.send_text(json.dumps({
                                "type": "voice_auto_switched",
                                "voice_id": new_voice_id,
                                "voice_name": new_voice_info["name"],
                                "detected_lang": detected_lang,
                                "stt_lang": "hi-IN" if detected_lang == "hi" else "en-IN",
                            }))
                            voice_info = new_voice_info
                        else:
                            voice_info = current_voice_info

                        # ── Speculative cache hit → use immediately ───────────
                        if is_spec_hit:
                            full_response = sess._spec_result  # type: ignore[attr-defined]
                            sess._spec_result = None  # type: ignore[assignment]
                            sess._spec_text = ""  # type: ignore[assignment]
                            log.info("[%s] CMD #%d ⚡ speculative hit (%d chars)", sid, cid, len(full_response))

                            # Send as one token
                            await ws.send_text(json.dumps({
                                "type": "llm_token", "session_id": sid,
                                "token": full_response, "cmd_id": cid, "is_final": True,
                            }))
                            # Single TTS
                            mp3 = await _tts_generate(full_response, voice_info, detected_lang)
                            if mp3:
                                await ws.send_text(json.dumps({
                                    "type": "tts_audio", "session_id": sid, "cmd_id": cid,
                                    "sentence_idx": 0,
                                    "audio_b64": _b64t.b64encode(mp3).decode("ascii"),
                                    "is_final": True,
                                }))

                            async with sess._cmd_lock:  # type: ignore[attr-defined]
                                sess.transcript_buffer += f"\nUser: {text}\nAura: {full_response}"
                                save_turn(user_id=uid, role="user", content=text, session_id=sid)
                                save_turn(user_id=uid, role="assistant", content=full_response, session_id=sid)
                                memory_store(uid, f"User said: {text}")
                                memory_store(uid, f"Alita said: {full_response}")
                            log.info("[%s] CMD #%d completed (speculative)", sid, cid)
                            return

                        # ── Classify query to decide: stream vs batch ─────────
                        sess._spec_result = None  # type: ignore[assignment]
                        sess._spec_text = ""  # type: ignore[assignment]

                        from decision_router import classify_query  # type: ignore[import]
                        query_type = classify_query(text)

                        # Realtime + automation → batch (short responses)
                        if query_type in ("realtime", "automation"):
                            tokens_list, ws_metadata = await loop.run_in_executor(
                                None, _llm_generate_sync, sess, text
                            )
                            full_response = ""
                            for i, tok in enumerate(tokens_list):
                                full_response += tok
                                await ws.send_text(json.dumps({
                                    "type": "llm_token", "session_id": sid,
                                    "token": tok, "cmd_id": cid,
                                    "is_final": (i == len(tokens_list) - 1),
                                }))
                                await asyncio.sleep(0)

                            # Single TTS for short response
                            mp3 = await _tts_generate(full_response, voice_info, detected_lang)
                            if mp3:
                                await ws.send_text(json.dumps({
                                    "type": "tts_audio", "session_id": sid, "cmd_id": cid,
                                    "sentence_idx": 0,
                                    "audio_b64": _b64t.b64encode(mp3).decode("ascii"),
                                    "is_final": True,
                                }))

                            # Forward metadata
                            for meta_msg in ws_metadata:
                                mt = meta_msg.get("type", "")
                                if mt == "app_not_installed":
                                    await ws.send_text(json.dumps({
                                        "type": "app_not_installed",
                                        "app": meta_msg.get("app", ""),
                                        "store_url": meta_msg.get("store_url", ""),
                                    }))
                                elif mt == "start_song_recognition":
                                    await ws.send_text(json.dumps({"type": "start_song_recognition"}))

                            async with sess._cmd_lock:  # type: ignore[attr-defined]
                                sess.transcript_buffer += f"\nUser: {text}\nAura: {full_response}"
                                save_turn(user_id=uid, role="user", content=text, session_id=sid)
                                save_turn(user_id=uid, role="assistant", content=full_response, session_id=sid)
                                memory_store(uid, f"User said: {text}")
                                memory_store(uid, f"Alita said: {full_response}")

                            if getattr(sess, 'dictation_active', False):
                                await ws.send_text(json.dumps({
                                    "type": "dictation_start",
                                    "app": getattr(sess, 'dictation_app', ''),
                                }))

                            log.info("[%s] CMD #%d completed (batch/%s): %d chars", sid, cid, query_type, len(full_response))
                            return

                        # ──────────────────────────────────────────────────────
                        # GENERAL → TRUE STREAMING + SENTENCE TTS PIPELINE
                        # ──────────────────────────────────────────────────────
                        from threads.general_handler import handle_general_stream  # type: ignore[import]

                        token_q: _queue.Queue = _queue.Queue()
                        system_prompt = _build_system_prompt(sess, user_text=text)
                        max_history = 15 if sess.tier == "premium" else 5
                        history = _build_history(sess, max_history)

                        # Start LLM streaming in a background thread
                        loop.run_in_executor(
                            None,
                            handle_general_stream,
                            text, sess, settings, system_prompt, history,
                            settings.llm_max_tokens if sess.tier == "premium" else settings.llm_max_tokens_free,
                            response_cache, token_q, None,
                        )

                        # ── Consume tokens + sentence-level TTS ───────────────
                        full_response = ""
                        sentence_buffer = ""
                        sentence_idx = 0
                        tts_tasks = []  # track TTS tasks for final cleanup

                        async def _send_sentence_tts(sent_text, s_idx, vi, lang):
                            """Generate and send TTS for one sentence."""
                            sent_text = sent_text.strip()
                            if not sent_text or len(sent_text) < 3:
                                return
                            try:
                                mp3 = await _tts_generate(sent_text, vi, lang)
                                if mp3:
                                    await ws.send_text(json.dumps({
                                        "type": "tts_audio",
                                        "session_id": sid,
                                        "cmd_id": cid,
                                        "sentence_idx": s_idx,
                                        "audio_b64": _b64t.b64encode(mp3).decode("ascii"),
                                        "is_final": False,
                                    }))
                            except Exception as tts_err:
                                log.warning("CMD #%d sentence TTS #%d error: %s", cid, s_idx, tts_err)

                        while True:
                            # Poll queue — non-blocking with short timeout
                            try:
                                token = await loop.run_in_executor(  # type: ignore[arg-type]
                                    None, lambda: token_q.get(timeout=0.05)
                                )
                            except Exception:
                                # Queue empty, try again
                                await asyncio.sleep(0.01)
                                continue

                            if token is None:
                                # Stream complete — flush remaining sentence buffer
                                break

                            # Send token to frontend immediately
                            full_response += token  # type: ignore[operator]
                            sentence_buffer += token  # type: ignore[operator]

                            await ws.send_text(json.dumps({
                                "type": "llm_token",
                                "session_id": sid,
                                "token": token,
                                "cmd_id": cid,
                                "is_final": False,
                            }))

                            # Check for sentence boundary
                            if _SENT_END.search(sentence_buffer):  # type: ignore[union-attr]
                                # Split at the LAST sentence boundary
                                parts = _SENT_END.split(sentence_buffer)  # type: ignore[union-attr]
                                # Everything up to last boundary = complete sentence
                                complete = ""
                                remainder = ""
                                for j, p in enumerate(parts):
                                    if p is None:
                                        continue
                                    if j < len(parts) - 1:
                                        complete += p  # type: ignore[operator]
                                    else:
                                        remainder = p

                                if complete.strip():  # type: ignore[union-attr]
                                    # Fire TTS for this sentence immediately
                                    task = asyncio.create_task(
                                        _send_sentence_tts(complete, sentence_idx, voice_info, detected_lang)
                                    )
                                    tts_tasks.append(task)
                                    sentence_idx += 1

                                sentence_buffer = remainder

                        # ── Flush final sentence buffer ───────────────────────
                        if sentence_buffer.strip():  # type: ignore[union-attr]
                            task = asyncio.create_task(
                                _send_sentence_tts(sentence_buffer, sentence_idx, voice_info, detected_lang)
                            )
                            tts_tasks.append(task)
                            sentence_idx += 1

                        # Send final llm_token marker
                        await ws.send_text(json.dumps({
                            "type": "llm_token",
                            "session_id": sid,
                            "token": "",
                            "cmd_id": cid,
                            "is_final": True,
                        }))

                        # Wait for all sentence TTS tasks to finish
                        if tts_tasks:
                            await asyncio.gather(*tts_tasks, return_exceptions=True)

                        # Send TTS final marker
                        await ws.send_text(json.dumps({
                            "type": "tts_audio",
                            "session_id": sid,
                            "cmd_id": cid,
                            "sentence_idx": sentence_idx,
                            "audio_b64": "",
                            "is_final": True,
                        }))

                        # ── LOCK: save to history ─────────────────────────────
                        async with sess._cmd_lock:  # type: ignore[attr-defined]
                            sess.transcript_buffer += f"\nUser: {text}\nAura: {full_response}"
                            save_turn(user_id=uid, role="user", content=text, session_id=sid)
                            save_turn(user_id=uid, role="assistant", content=full_response, session_id=sid)
                            memory_store(uid, f"User said: {text}")
                            memory_store(uid, f"Alita said: {full_response}")

                        if getattr(sess, 'dictation_active', False):
                            await ws.send_text(json.dumps({
                                "type": "dictation_start",
                                "app": getattr(sess, 'dictation_app', ''),
                            }))

                        log.info("[%s] CMD #%d completed (stream): %d chars, %d sentences",
                                 sid, cid, len(full_response), sentence_idx)

                    except Exception as e:
                        log.error("[%s] CMD #%d error: %s", sid, cid, e, exc_info=True)

                asyncio.create_task(
                    _handle_text_message(websocket, session, user_id, session_id, text_input, spec_hit, cmd_id)
                )

                continue

            # ── Audio chunk ────────────────────────────────────────────────
            if msg_type == "audio_chunk":
                pcm_samples: list[float] = msg.get("pcm_float32", [])
                if not pcm_samples:
                    continue
                accumulated_pcm.extend(pcm_samples)
                continue

            # ── End of utterance (frontend signals VAD completion) ────────
            if msg_type == "end_of_utterance":
                if len(accumulated_pcm) < settings.audio_sample_rate * 0.3:
                    # Too short (< 300ms) — probably noise, discard
                    accumulated_pcm = []
                    continue
                utterance = np.array(accumulated_pcm, dtype=np.float32)
                accumulated_pcm = []
                asyncio.create_task(
                    run_full_pipeline(websocket, session, utterance)
                )
                continue

            # ── Offline audio streaming (Whisper STT) ──────────────────────
            if msg_type == "audio_chunk_stream":
                if not offline_mode:
                    continue  # ignore streaming chunks in online mode
                pcm_data = msg.get("pcm_float32", [])
                if not pcm_data:
                    continue
                if whisper_stream_proc is None:
                    _init_whisper_stream()
                if whisper_stream_proc is not None:
                    chunk = np.array(pcm_data, dtype=np.float32)
                    whisper_stream_proc.feed(chunk)
                continue

            # ── Connectivity status (online/offline switch) ────────────────
            if msg_type == "connectivity_status":
                is_online = msg.get("online", True)
                was_offline = offline_mode
                offline_mode = not is_online

                if offline_mode and not was_offline:
                    # Switching to offline mode — processor already pre-initialized
                    log.info("[%s] 📡 Switching to OFFLINE mode (Whisper streaming STT)", session_id)
                    _init_whisper_stream()  # no-op if already inited
                    # Start polling task if not already running
                    if whisper_poll_task is None or whisper_poll_task.done():  # type: ignore[union-attr]
                        whisper_poll_task = asyncio.create_task(_whisper_poll_loop())
                    await websocket.send_text(json.dumps({
                        "type": "stt_mode",
                        "mode": "offline",
                        "detail": "Switched to local Whisper STT (offline mode)",
                    }))
                elif not offline_mode and was_offline:
                    # Switching back to online mode — keep processor alive for fast re-switch
                    log.info("[%s] 📡 Switching to ONLINE mode (Web Speech API STT)", session_id)
                    if whisper_poll_task and not whisper_poll_task.done():  # type: ignore[union-attr]
                        whisper_poll_task.cancel()  # type: ignore[union-attr]
                    # Don't destroy processor — just reset buffers for fast re-switch
                    if whisper_stream_proc:
                        whisper_stream_proc.reset()
                    await websocket.send_text(json.dumps({
                        "type": "stt_mode",
                        "mode": "online",
                        "detail": "Switched to Web Speech API (online mode)",
                    }))
                continue

            # ── Ping ──────────────────────────────────────────────────────
            if msg_type == "ping":
                await websocket.send_text(json.dumps({
                    "type": "pong",
                    "ts":   time.time(),
                }))
                continue

            # ── Voice change ───────────────────────────────────────────────
            if msg_type == "voice_change":
                voice_id = msg.get("voice_id", "en_jenny")
                voice = AVAILABLE_VOICES.get(voice_id)
                if not voice:
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "detail": f"Unknown voice: {voice_id}",
                    }))
                    continue

                # Check tier requirement (test users bypass)
                if voice["tier_required"] == "premium" and tier != "premium" and not user_id.startswith("test_"):
                    await websocket.send_text(json.dumps({
                        "type": "voice_change_denied",
                        "reason": "premium_required",
                        "voice_id": voice_id,
                    }))
                    continue

                session.voice_id = voice_id  # type: ignore[assignment]
                session.manual_voice_override = True  # type: ignore[assignment]
                log.info("Voice changed to '%s' for session=%s (manual override)", voice_id, session_id)
                # Send stt_lang so frontend updates speech recognition language
                voice_lang = voice.get("lang", "en")
                stt_lang_map = {"en": "en-IN", "hi": "hi-IN", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "ja": "ja-JP"}
                await websocket.send_text(json.dumps({
                    "type": "voice_changed",
                    "voice_id": voice_id,
                    "voice_name": voice["name"],
                    "lang": voice_lang,
                    "stt_lang": stt_lang_map.get(str(voice_lang or "en"), "en-IN"),
                }))
                continue

            # ── Song Recognition (Shazam-like) ────────────────────────────
            if msg_type == "recognize_song":
                audio_b64 = msg.get("audio_b64", "")
                if not audio_b64:
                    await websocket.send_text(json.dumps({
                        "type": "song_recognition_result",
                        "status": "error",
                        "error": "No audio data received",
                    }))
                    continue

                # Send "listening" status
                await websocket.send_text(json.dumps({
                    "type": "song_recognition_status",
                    "status": "identifying",
                    "detail": "Analyzing audio...",
                }))

                try:
                    import tempfile, base64, subprocess

                    from shazamio import Shazam  # type: ignore[import-untyped]

                    # Decode the WebM audio from frontend
                    audio_bytes = base64.b64decode(audio_b64)

                    # ── Convert WebM → WAV using imageio-ffmpeg's bundled binary ──
                    webm_path = None
                    wav_path = None
                    try:
                        import imageio_ffmpeg  # type: ignore[import-untyped]
                        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

                        # CRITICAL: Set pydub's converter to our bundled ffmpeg
                        # so shazamio's internal AudioSegment.from_file() works
                        from pydub import AudioSegment  # type: ignore[import-untyped]
                        AudioSegment.converter = ffmpeg_exe

                        # Save raw WebM
                        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as webm_tmp:
                            webm_tmp.write(audio_bytes)
                            webm_path = webm_tmp.name

                        # Create WAV output path
                        wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                        wav_path = wav_tmp.name
                        wav_tmp.close()

                        # Convert WebM → WAV using imageio-ffmpeg subprocess
                        cmd = [
                            ffmpeg_exe,
                            "-y",              # Overwrite output
                            "-i", webm_path,   # Input WebM
                            "-ar", "44100",    # 44.1kHz sample rate
                            "-ac", "1",        # Mono
                            "-f", "wav",       # Output format
                            wav_path,
                        ]
                        proc = subprocess.run(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=15,
                        )
                        if proc.returncode != 0:
                            raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr.decode('utf-8', errors='replace')[:200]}")  # type: ignore[misc]

                        log.info("[Song] Converted WebM → WAV via imageio-ffmpeg (%d bytes → %s)",
                                 len(audio_bytes), wav_path)

                    except ImportError:
                        log.warning("[Song] imageio-ffmpeg not available, saving raw bytes as .webm")
                        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp:
                            tmp.write(audio_bytes)
                            wav_path = tmp.name
                    finally:
                        # Clean up WebM temp file
                        if webm_path and webm_path != wav_path:
                            try:
                                os.unlink(webm_path)
                            except Exception:
                                pass

                    # Run Shazam recognition — pass file path (str)
                    # shazamio accepts str (path) or bytes, NOT AudioSegment
                    shazam = Shazam()
                    result = await shazam.recognize(wav_path)

                    # Clean up WAV temp file
                    try:
                        if wav_path:
                            os.unlink(wav_path)
                    except Exception:
                        pass

                    # Extract song info
                    track = result.get("track")
                    if track:
                        song_title = track.get("title", "Unknown")
                        song_artist = track.get("subtitle", "Unknown Artist")
                        album = ""
                        for section in track.get("sections", []):
                            if section.get("type") == "SONG":
                                for meta in section.get("metadata", []):
                                    if meta.get("title") == "Album":
                                        album = meta.get("text", "")
                        song_url = track.get("url", "")
                        song_art = track.get("images", {}).get("coverart", "")

                        await websocket.send_text(json.dumps({
                            "type": "song_recognition_result",
                            "status": "found",
                            "title": song_title,
                            "artist": song_artist,
                            "album": album,
                            "url": song_url,
                            "artwork": song_art,
                        }))
                        log.info("Song recognized: %s — %s", song_title, song_artist)

                        # Also speak the result via TTS
                        tts_text = f"That's {song_title} by {song_artist}"
                        if album:
                            tts_text += f", from the album {album}"
                        tts_text += ". Would you like me to play it?"

                        # Generate TTS for the answer
                        voice_info = AVAILABLE_VOICES.get(
                            session.voice_id,  # type: ignore[attr-defined]
                            AVAILABLE_VOICES["en_jenny"]
                        )
                        try:
                            import base64 as _b64sr
                            mp3_bytes = await _tts_generate(tts_text, voice_info, "en")
                            if mp3_bytes:
                                await websocket.send_text(json.dumps({
                                    "type": "tts_audio",
                                    "session_id": session_id,
                                    "audio_b64": _b64sr.b64encode(mp3_bytes).decode("ascii"),
                                    "is_final": True,
                                }))
                        except Exception as tts_err:
                            log.warning("TTS for song result failed: %s", tts_err)

                        # Store the recognized song in session memory
                        # Use the proper Pydantic field (last_identified_song) so the
                        # LLM system prompt always has context for follow-up questions.
                        song_label = f"{song_title} by {song_artist}"
                        if album:
                            song_label += f" (album: {album})"
                        session.last_identified_song = song_label  # type: ignore[union-attr]

                        # Also write a note into the transcript buffer so conversation
                        # history (which feeds the LLM) reflects the identification.
                        session.transcript_buffer += (  # type: ignore[union-attr]
                            f"\n[System Note: Song identified — {song_label}]"
                        )

                        # Keep the dynamic attrs for backward-compat (e.g., "yes, play it")
                        session._recognized_song = {  # type: ignore[attr-defined]
                            "title": song_title,
                            "artist": song_artist,
                            "query": f"{song_title} {song_artist}",
                        }
                        session._last_recognized_song = session._recognized_song.copy()  # type: ignore[attr-defined]
                        log.info("Song stored in session memory: %s", song_label)

                    else:
                        await websocket.send_text(json.dumps({
                            "type": "song_recognition_result",
                            "status": "not_found",
                            "detail": "Couldn't identify the song. Try playing it louder or closer to the mic.",
                        }))
                        log.info("Song recognition: no match found")

                except ImportError:
                    await websocket.send_text(json.dumps({
                        "type": "song_recognition_result",
                        "status": "error",
                        "error": "shazamio not installed. Run: pip install shazamio",
                    }))
                except Exception as e:
                    log.error("Song recognition error: %s", e)
                    await websocket.send_text(json.dumps({
                        "type": "song_recognition_result",
                        "status": "error",
                        "error": str(e),
                    }))
                continue

            # ── Dictation mode: type text into active app ──────────────
            if msg_type == "dictate_text":
                dictation_text = msg.get("text", "").strip()
                if not dictation_text:
                    continue
                try:
                    import pyautogui  # type: ignore[import-untyped]
                    pyautogui.PAUSE = 0.02
                    if dictation_text.isascii():
                        pyautogui.typewrite(dictation_text + " ", interval=0.01)
                    else:
                        # Non-ASCII (Hindi etc): use clipboard paste
                        import pyperclip  # type: ignore[import-untyped]
                        pyperclip.copy(dictation_text + " ")
                        pyautogui.hotkey("ctrl", "v")
                    log.info("Dictation typed: %s", dictation_text[:40])
                    await websocket.send_text(json.dumps({
                        "type": "dictation_ack",
                        "text": dictation_text,
                    }))
                except Exception as e:
                    log.warning("Dictation type failed: %s", e)
                    await websocket.send_text(json.dumps({
                        "type": "error",
                        "detail": f"Typing failed: {e}",
                    }))
                continue

            if msg_type == "dictation_stop":
                session.dictation_active = False  # type: ignore[misc]
                log.info("Dictation mode stopped for session=%s", session_id)
                await websocket.send_text(json.dumps({
                    "type": "dictation_stopped",
                }))
                continue

            log.warning(
                "Unknown message type '%s' | session=%s",
                msg_type, session_id,
            )

    except WebSocketDisconnect as exc:
        log.info("WS disconnected | session=%s | code=%s", session_id, exc.code)
    except Exception:
        log.exception("Unhandled WS error | session=%s", session_id)
    finally:
        # Cancel offline Whisper streaming poll task if running
        if whisper_poll_task and not whisper_poll_task.done():
            whisper_poll_task.cancel()
        if whisper_stream_proc:
            whisper_stream_proc.reset()
        active_sessions.pop(session_id, None)
        _session_websockets.pop(session_id, None)
        log.info("Session cleaned up: %s", session_id)


# ─────────────────────────────────────────────────────────────────────────────
# §14  RAZORPAY WEBHOOK  /webhooks/razorpay
# ─────────────────────────────────────────────────────────────────────────────
razorpay_client = None  # initialized in lifespan


@app.post("/webhooks/razorpay", status_code=200)
async def razorpay_webhook(request: Request):
    """
    Razorpay → server-to-server only.
    Signature verified cryptographically — cannot be spoofed.
    Handles:
      subscription.activated       → upgrade to premium
      subscription.cancelled       → downgrade to free
      payment.captured             → confirm payment
      payment.failed               → log payment failure

    Pricing:
      Monthly  plan = $99  / month
      Annual   plan = $1100 / year
    """
    from tier_store import set_tier as _set_tier, find_user_by_razorpay_customer  # type: ignore[import]

    payload = await request.body()
    sig_header = request.headers.get("x-razorpay-signature", "")

    # ── Verify webhook signature ──────────────────────────────────────────
    try:
        if razorpay_client and settings.razorpay_webhook_secret:
            razorpay_client.utility.verify_webhook_signature(
                payload.decode("utf-8"), sig_header, settings.razorpay_webhook_secret
            )
        else:
            log.warning("Razorpay webhook: no client or secret — skipping signature verification.")
    except razorpay.errors.SignatureVerificationError:  # type: ignore[attr-defined]
        log.warning("Razorpay webhook: invalid signature — rejected.")
        raise HTTPException(status_code=400, detail="Invalid signature.")
    except Exception as exc:
        log.error("Razorpay webhook error: %s", exc)
        raise HTTPException(status_code=400, detail="Webhook processing error.")

    body = json.loads(payload)
    event_type = body.get("event", "")
    log.info("Razorpay event received: %s", event_type)

    entity = body.get("payload", {}).get("subscription", {}).get("entity", {})
    payment_entity = body.get("payload", {}).get("payment", {}).get("entity", {})

    # ── Subscription activated → upgrade user ─────────────────────────────
    if event_type in ("subscription.activated", "subscription.charged"):
        user_id = entity.get("notes", {}).get("user_id", "")
        plan = entity.get("notes", {}).get("plan", "monthly")
        razorpay_customer_id = entity.get("customer_id", "")

        if user_id:
            log.info(
                "Upgrading user=%s to premium | plan=%s | subscription_id=%s",
                user_id, plan, entity.get("id", ""),
            )
            _set_tier(
                user_id=user_id,
                tier="premium",
                plan=plan,
                razorpay_customer_id=razorpay_customer_id,
            )

            # Update any active WebSocket session in real time
            for sid, session in active_sessions.items():
                if session.user_id == user_id:
                    session.tier = "premium"
                    ws = _session_websockets.get(sid)
                    if ws:
                        try:
                            await ws.send_text(json.dumps({
                                "type": "tier_updated",
                                "tier": "premium",
                                "plan": plan,
                            }))
                        except Exception:
                            pass
                    break

    # ── Subscription cancelled → downgrade user ───────────────────────────
    elif event_type == "subscription.cancelled":
        customer_id = entity.get("customer_id", "")
        log.info("Subscription cancelled | razorpay_customer=%s", customer_id)
        user_id = find_user_by_razorpay_customer(customer_id)
        if user_id:
            _set_tier(user_id=user_id, tier="free")
            # Update any active WebSocket session
            for sid, session in active_sessions.items():
                if session.user_id == user_id:
                    session.tier = "free"
                    ws = _session_websockets.get(sid)
                    if ws:
                        try:
                            await ws.send_text(json.dumps({
                                "type": "tier_updated",
                                "tier": "free",
                            }))
                        except Exception:
                            pass
                    break
        else:
            log.warning("Subscription cancelled but no user found for razorpay_customer=%s", customer_id)

    # ── Payment failed → log for follow-up ───────────────────────────────
    elif event_type == "payment.failed":
        customer_id = payment_entity.get("customer_id", "")
        log.warning("Payment failed | razorpay_customer=%s | error=%s",
                    customer_id, payment_entity.get("error_description", ""))

    return JSONResponse({"status": "received"})


# ─────────────────────────────────────────────────────────────────────────────
# §14b  RAZORPAY SUBSCRIPTION CREATION
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    plan: str = "monthly"  # "monthly" | "annual"


@app.post("/payments/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest, request: Request):
    """
    Create a Razorpay subscription and return checkout data.
    Frontend uses Razorpay Checkout.js to complete payment.

    Supports: UPI, Cards, Net Banking, Wallets, International Cards.

    Requires Authorization: Bearer <JWT> header.
    """
    # ── Auth ──────────────────────────────────────────────────────────────
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = auth_header.split(" ", 1)[1]
    try:
        claims = decode_supabase_jwt(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid token.")

    user_id = claims["user_id"]

    # ── Validate plan ─────────────────────────────────────────────────────
    if req.plan not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="Plan must be 'monthly' or 'annual'.")

    if not razorpay_client:
        raise HTTPException(
            status_code=500,
            detail="Razorpay not configured. Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env."
        )

    plan_id = (
        settings.razorpay_plan_monthly if req.plan == "monthly"
        else settings.razorpay_plan_annual
    )

    if not plan_id:
        raise HTTPException(
            status_code=500,
            detail=f"Razorpay Plan ID for '{req.plan}' not configured. Set RAZORPAY_PLAN_MONTHLY / RAZORPAY_PLAN_ANNUAL in .env."
        )

    # ── Create Razorpay Subscription ──────────────────────────────────────
    try:
        subscription = razorpay_client.subscription.create({
            "plan_id": plan_id,
            "total_count": 12 if req.plan == "monthly" else 1,
            "quantity": 1,
            "notes": {
                "user_id": user_id,
                "plan": req.plan,
            },
        })
        log.info("Razorpay subscription created: user=%s plan=%s sub_id=%s",
                 user_id, req.plan, subscription.get("id"))
        return JSONResponse({
            "subscription_id": subscription.get("id"),
            "razorpay_key_id": settings.razorpay_key_id,
            "plan": req.plan,
            "amount": 9900 if req.plan == "monthly" else 110000,  # in cents (USD)
            "currency": "USD",
            "name": "Alita Premium",
            "description": f"Alita Premium — {'Monthly' if req.plan == 'monthly' else 'Annual'} Subscription",
        })
    except Exception as exc:
        log.error("Razorpay subscription error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Razorpay error: {str(exc)}")


@app.get("/payments/status")
async def payment_status(request: Request):
    """
    Check the current tier for the authenticated user.
    Frontend can call this after payment to verify upgrade.

    Requires Authorization: Bearer <JWT> header.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header.")
    token = auth_header.split(" ", 1)[1]
    try:
        claims = decode_supabase_jwt(token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid token.")

    user_id = claims["user_id"]
    tier = get_user_tier(user_id)
    return JSONResponse({"user_id": user_id, "tier": tier})


# ─────────────────────────────────────────────────────────────────────────────
# §15  VOICE MODELS & LANGUAGES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/voices")
async def list_voices():
    """List available voice models with engine type, download status, language, and quality."""
    voices = []
    for vid, info in AVAILABLE_VOICES.items():
        engine_type = info.get("engine", "edge")
        # XTTS voices are only available if the engine is loaded
        if engine_type == "xtts":
            is_available = engines.xtts_engine is not None and engines.xtts_engine.available  # type: ignore[union-attr]
        else:
            is_available = True  # Edge TTS is always available

        voices.append({
            "id": vid,
            "name": info["name"],
            "description": info.get("description", ""),
            "tier_required": info["tier_required"],
            "lang": info["lang"],
            "quality": info.get("quality", "high"),
            "engine": engine_type,
            "available": is_available,
        })

    # Also include dynamically registered custom voices
    if engines.xtts_engine and engines.xtts_engine.available:  # type: ignore[union-attr]
        for custom_voice in engines.xtts_engine.list_voices():  # type: ignore[union-attr]
            if custom_voice["category"] == "custom":
                custom_id = f"xtts_custom_{custom_voice['id']}"
                if custom_id not in [v["id"] for v in voices]:
                    voices.append({
                        "id": custom_id,
                        "name": f"{custom_voice['name']} (Custom Clone)",
                        "description": "Your custom cloned voice — XTTS v2",
                        "tier_required": "free",
                        "lang": "en",
                        "quality": "ultra",
                        "engine": "xtts",
                        "available": True,
                    })

    return {"voices": voices}


@app.post("/voices/upload")
async def upload_voice(request: Request):
    """
    Upload a voice sample WAV for XTTS v2 voice cloning.
    
    Accepts multipart form data with:
      - file: WAV audio file (6-30 seconds, mono, 16-bit)
      - name: (optional) Human-readable name for the voice
      - lang: (optional) Primary language code (default: "en")
    """
    import shutil
    from pathlib import Path as _Path

    if not engines.xtts_engine or not engines.xtts_engine.available:
        raise HTTPException(
            status_code=503,
            detail="XTTS v2 engine not available. Voice upload requires GPU.",
        )

    form = await request.form()
    file = form.get("file")
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded. Send a WAV file as 'file'.")

    voice_name = form.get("name", file.filename.rsplit(".", 1)[0] if file.filename else "custom_voice")
    voice_lang = form.get("lang", "en")

    # Sanitize filename
    safe_name = "".join(c if c.isalnum() or c in "_-" else "_" for c in voice_name).lower()
    if not safe_name:
        safe_name = "custom_voice"

    # Save file
    from engines.tts_xtts import VOICES_CUSTOM_DIR  # type: ignore[import]
    VOICES_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)
    dest_path = VOICES_CUSTOM_DIR / f"{safe_name}.wav"

    content = await file.read()
    if len(content) < 1000:
        raise HTTPException(status_code=400, detail="File too small. Need at least 6 seconds of audio.")
    if len(content) > 50_000_000:
        raise HTTPException(status_code=400, detail="File too large. Maximum 50MB.")

    with open(dest_path, "wb") as f:
        f.write(content)  # type: ignore[arg-type]

    # Pre-compute speaker embedding for instant use
    try:
        engines.xtts_engine._get_speaker_conditioning(str(dest_path))  # type: ignore[union-attr]
    except Exception as exc:
        log.warning("Failed to pre-cache uploaded voice: %s", exc)

    # Register as a dynamic voice
    voice_id = f"xtts_custom_{safe_name}"
    AVAILABLE_VOICES[voice_id] = {
        "name": f"{voice_name} (Custom Clone)",
        "voice": None,
        "speaker_wav": str(dest_path),
        "engine": "xtts",
        "description": f"Custom cloned voice: {voice_name}",
        "tier_required": "free",
        "lang": voice_lang,
        "quality": "ultra",
    }

    log.info("Custom voice uploaded: %s → %s", voice_name, dest_path)
    return {
        "voice_id": voice_id,
        "name": voice_name,
        "path": str(dest_path),
        "size_kb": round(len(content) / 1024, 1),  # type: ignore[arg-type]
        "message": f"Voice '{voice_name}' uploaded successfully! Select it from the voice picker.",
    }


@app.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str):
    """Delete a custom cloned voice."""
    if not voice_id.startswith("xtts_custom_"):
        raise HTTPException(status_code=400, detail="Can only delete custom voices.")

    if voice_id not in AVAILABLE_VOICES:
        raise HTTPException(status_code=404, detail="Voice not found.")

    voice_info = AVAILABLE_VOICES[voice_id]
    wav_path = voice_info.get("speaker_wav", "")

    # Remove file
    if wav_path and os.path.exists(wav_path):
        try:
            os.remove(wav_path)
        except OSError as exc:
            log.warning("Failed to delete voice file: %s", exc)

    # Remove from registry
    del AVAILABLE_VOICES[voice_id]  # type: ignore[attr-defined]
    log.info("Custom voice deleted: %s", voice_id)
    return {"message": f"Voice '{voice_id}' deleted successfully."}


@app.get("/languages")
async def list_languages():
    """List supported languages with voice counts and defaults."""
    langs = []
    for lang_code, lang_name in LANGUAGE_NAMES.items():
        lang_voices = [
            vid for vid, v in AVAILABLE_VOICES.items() if v["lang"] == lang_code
        ]
        free_voices = [
            vid for vid in lang_voices
            if AVAILABLE_VOICES[vid]["tier_required"] == "free"
        ]
        premium_voices = [
            vid for vid in lang_voices
            if AVAILABLE_VOICES[vid]["tier_required"] == "premium"
        ]
        langs.append({
            "code": lang_code,
            "name": lang_name,
            "default_voice": DEFAULT_VOICE.get(lang_code),
            "free_voices": len(free_voices),
            "premium_voices": len(premium_voices),
            "total_voices": len(lang_voices),
        })
    return {"languages": langs}


# ─────────────────────────────────────────────────────────────────────────────
# §16  HEALTH & DIAGNOSTICS
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    vram_info = {}
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated(0) / 1024 ** 3
        reserved  = torch.cuda.memory_reserved(0)  / 1024 ** 3
        vram_info = {
            "allocated_gb": round(allocated, 3),
            "reserved_gb":  round(reserved,  3),
            "device_name":  torch.cuda.get_device_name(0),
        }

    return {
        "status":          "ok",
        "device":          settings.device,
        "active_sessions": len(active_sessions),
        "engines": {
            "llm":      "gemini",
            "whisper":  engines.whisper_model    is not None,
            "wav2vec2": engines.wav2vec2_model   is not None,
            "memory":   engines.memory_collection is not None,
            "xtts":     engines.xtts_engine.status() if engines.xtts_engine else {"available": False},  # type: ignore[union-attr]
        },
        "security": {
            "jwks_loaded":    len(_jwks_keys) > 0,
            "jwks_key_count": len(_jwks_keys),
        },
        "vram": vram_info,
    }


# ─────────────────────────────────────────────────────────────────────────────
# GEMINI VISION — Image analysis via multimodal Gemini
# ─────────────────────────────────────────────────────────────────────────────
class VisionRequest(BaseModel):
    image_b64: str
    prompt: str = "What do you see in this image? Describe it in detail."

@app.post("/api/vision")
async def gemini_vision(req: VisionRequest):
    """Analyze an image using Gemini's multimodal vision capability."""
    all_keys = settings.get_all_gemini_keys()
    if not all_keys:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY not set")

    try:
        import google.generativeai as genai  # type: ignore[import-untyped]
        import base64

        genai.configure(api_key=key_rotator.get_key())
        model = genai.GenerativeModel(model_name=settings.gemini_model)

        # Decode the base64 image
        image_data = base64.b64decode(req.image_b64)

        response = model.generate_content([
            req.prompt,
            {"mime_type": "image/jpeg", "data": image_data},
        ])

        return {"description": response.text}

    except Exception as exc:
        log.error("Vision API error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


# ─────────────────────────────────────────────────────────────────────────────
# CHROMADB SEMANTIC MEMORY — Long-term user memory
# ─────────────────────────────────────────────────────────────────────────────
def memory_store(user_id: str, text: str, metadata: Optional[Dict[str, Any]] = None):
    """Store a memory in ChromaDB for long-term recall."""
    if not engines.memory_collection:
        return
    try:
        import uuid
        doc_id = str(uuid.uuid4())
        engines.memory_collection.add(  # type: ignore[union-attr]
            documents=[text],
            ids=[doc_id],
            metadatas=[{"user_id": user_id, **(metadata or {})}],
        )
        log.debug("Memory stored for user %s: %s", user_id, text[:60])  # type: ignore[misc]
    except Exception as exc:
        log.warning("Memory store failed: %s", exc)


def memory_recall(user_id: str, query: str, n_results: int = 3) -> list[str]:
    """Recall relevant memories for a user based on semantic similarity."""
    if not engines.memory_collection:
        return []
    try:
        results = engines.memory_collection.query(  # type: ignore[union-attr]
            query_texts=[query],
            n_results=n_results,
            where={"user_id": user_id},
        )
        docs = results.get("documents", [[]])[0]
        return docs
    except Exception as exc:
        log.warning("Memory recall failed: %s", exc)
        return []


@app.get("/sessions")
async def list_sessions():
    """Dev diagnostic — guard with admin auth before production."""
    return {
        sid: {
            "user_id":           s.user_id,
            "tier":              s.tier,
            "connected_seconds": round(time.time() - s.connected_at, 1),  # type: ignore[arg-type]
            "requests_this_min": s.request_count,
            "current_emotion":   getattr(s, 'current_emotion', 'neutral'),
            "interaction_count": getattr(s, 'interaction_count', 0),
            "emergency_active":  getattr(s, 'emergency_active', False),
        }
        for sid, s in active_sessions.items()
    }


# ─────────────────────────────────────────────────────────────────────────────
# EMERGENCY RECORDING ENDPOINTS — Admin access to emergency recordings
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/emergency/recordings")
async def list_emergency_recordings(limit: int = 50):
    """List all emergency recordings."""
    try:
        from core.emergency_system import list_recordings  # type: ignore[import]
        recordings = list_recordings(limit=limit)
        return {"recordings": recordings, "count": len(recordings)}
    except ImportError:
        return {"recordings": [], "count": 0, "error": "emergency_system not available"}


@app.get("/emergency/recordings/{recording_id}")
async def get_emergency_recording(recording_id: str):
    """Get a specific emergency recording's metadata."""
    try:
        from core.emergency_system import get_recording  # type: ignore[import]
        recording = get_recording(recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail="Recording not found")
        return recording
    except ImportError:
        raise HTTPException(status_code=501, detail="Emergency system not available")


@app.delete("/emergency/recordings/{recording_id}")
async def delete_emergency_recording(recording_id: str):
    """Delete an emergency recording."""
    try:
        from core.emergency_system import delete_recording  # type: ignore[import]
        success = delete_recording(recording_id)
        if not success:
            raise HTTPException(status_code=404, detail="Recording not found")
        return {"status": "deleted", "id": recording_id}
    except ImportError:
        raise HTTPException(status_code=501, detail="Emergency system not available")


# ─────────────────────────────────────────────────────────────────────────────
# §16  CONVERSATION HISTORY & TRAINING DATA
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/conversations/history")
async def get_conversation_history(token: str, limit: int = 50):
    """
    REST endpoint to load conversation history for a user.
    Used by frontend on page load if needed.
    """
    try:
        claims = decode_supabase_jwt(token)
    except HTTPException:
        raise HTTPException(status_code=403, detail="Invalid token.")

    user_id = claims["user_id"]
    history = load_history(user_id, max_turns=limit)
    return {
        "user_id": user_id,
        "turns": history,
        "count": len(history),
    }


@app.post("/admin/export-training-data")
async def export_training_endpoint(request: Request):
    """
    Export all conversations as anonymised JSONL for model training.
    PII (emails, phone numbers) is stripped. User IDs are hashed.

    Requires X-Admin-Secret header for access control.
    """
    admin_secret = request.headers.get("X-Admin-Secret", "")
    if admin_secret != settings.admin_secret:
        log.warning("Unauthorized admin access attempt from %s", request.client.host)
        raise HTTPException(status_code=403, detail="Forbidden.")

    export_path = export_training_data()
    return {
        "status": "exported",
        "path": export_path,
        "note": "Data is anonymised — user IDs hashed, PII stripped.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# §17  ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
        ws_ping_interval=20,
        ws_ping_timeout=30,
        log_level="info",
    )
