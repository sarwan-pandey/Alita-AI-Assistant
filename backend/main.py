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
 11.  Stripe monthly ($19) + annual ($209) plan handling
 12.  invoice.payment_failed event handled
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Dict
from datetime import datetime

# ── §0  Set up ffmpeg for pydub (song recognition) ───────────────────────────
# pydub needs ffmpeg to convert audio formats. If ffmpeg is not on PATH,
# try to use the static binary bundled with imageio-ffmpeg.
try:
    import shutil
    if not shutil.which("ffmpeg"):
        try:
            import imageio_ffmpeg
            _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
            os.environ["PATH"] = os.path.dirname(_ffmpeg_exe) + os.pathsep + os.environ.get("PATH", "")
            # Also tell pydub explicitly where ffmpeg is
            from pydub import AudioSegment
            AudioSegment.converter = _ffmpeg_exe
            AudioSegment.ffprobe = _ffmpeg_exe  # ffprobe isn't needed but prevents warning
        except ImportError:
            pass  # imageio-ffmpeg not installed; pydub will warn at startup
except Exception:
    pass

import httpx
import numpy as np
import stripe
import torch
import uvicorn
from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from jose import JWTError, jwk, jwt
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from test_auth import test_auth_router
from routers.youtube_search import youtube_router
from memory.conversation_store import (
    save_turn,
    load_history,
    rebuild_transcript_buffer,
    export_training_data,
)


# ─────────────────────────────────────────────────────────────────────────────
# §0  FFMPEG SETUP (must run before pydub/shazamio imports)
# ─────────────────────────────────────────────────────────────────────────────
try:
    import imageio_ffmpeg as _ioff
    _ffmpeg_exe = _ioff.get_ffmpeg_exe()
    _ffmpeg_dir = os.path.dirname(_ffmpeg_exe)
    if _ffmpeg_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = _ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
    # Also configure pydub to use this ffmpeg
    try:
        from pydub import AudioSegment
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

    # ── Payments ──────────────────────────────────────────────────────────
    stripe_webhook_secret: str   = ""
    admin_secret: str            = ""          # protect admin endpoints — set in .env
    stripe_secret_key: str     = ""

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
    llm_max_tokens: int      = 512      # premium
    llm_max_tokens_free: int = 256      # free  — enforced server-side
    llm_temperature: float   = 0.7

    # ── Groq (free fallback LLM) ──────────────────────────────────────────
    groq_api_key: str        = ""       # Get from https://console.groq.com/keys
    groq_api_key_2: str      = ""       # Additional keys for rotation
    groq_api_key_3: str      = ""
    groq_api_key_4: str      = ""
    groq_model: str          = "llama-3.3-70b-versatile"  # Free, fast, smart

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
                masked = self.keys[idx][:8] + '...'
                log.debug("Using Gemini key #%d (%s) — call #%d",
                          idx + 1, masked, self.total_calls[idx])
                return self.keys[idx]
            tried += 1
            self.index = (idx + 1) % len(self.keys)

        # All keys are on cooldown — use the one with shortest wait
        soonest = min(self.cooldowns, key=self.cooldowns.get)
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
            "calls": dict(self.total_calls),
        }


key_rotator = GeminiKeyRotator(_all_keys)


# ── Groq Key Rotator (shared module) ─────────────────────────────────────
from groq_pool import get_rotator as _get_groq_rotator
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
                del self.cache[h]  # Expired
        self.misses += 1
        return None

    def put(self, query: str, response: str):
        # Evict oldest if at capacity
        if len(self.cache) >= self.max_entries:
            oldest_key = min(self.cache, key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]
        self.cache[self._hash(query)] = (time.time(), response)

    def status(self) -> dict:
        return {"entries": len(self.cache), "hits": self.hits, "misses": self.misses}


response_cache = ResponseCache(ttl_seconds=300)


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


# ─────────────────────────────────────────────────────────────────────────────
# §3  ENGINE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
class EngineRegistry:
    """
    VRAM budget:
      CPU mode  (now, no CUDA):
        All models run in RAM — 0 VRAM used.

      GPU mode  (after CUDA 12.1 install):
        Phi-3 Mini 4-bit (28 layers) ≈ 2.10 GB
        faster-whisper  tiny FP16    ≈ 0.08 GB
        Wav2Vec2-base   FP16         ≈ 0.09 GB
        CUDA runtime                 ≈ 0.35 GB
        ─────────────────────────────────────
        Total                        ≈ 2.62 GB  ✓ under 4 GB
    """
    llm                      = None
    whisper_model            = None
    whisper_processor        = None     # True sentinel for faster-whisper
    wav2vec2_model           = None
    wav2vec2_processor       = None
    piper_binary             = None
    memory_collection        = None     # ChromaDB semantic memory
    EMOTION_LABELS: list[str] = ["neutral", "happy", "angry", "sad"]


# ── Available voice models (Edge TTS — Microsoft Neural, FREE) ─────────────────
AVAILABLE_VOICES = {
    # ── English ────────────────────────────────────────────────────────────
    "en_jenny": {
        "name": "Jenny (English Female)",
        "voice": "en-US-JennyNeural",
        "description": "Natural American English — warm & clear",
        "tier_required": "free",
        "lang": "en",
        "quality": "high",
    },
    "en_aria": {
        "name": "Aria (English Female, Premium)",
        "voice": "en-US-AriaNeural",
        "description": "American English — expressive & lively",
        "tier_required": "premium",
        "lang": "en",
        "quality": "high",
    },
    "en_guy": {
        "name": "Guy (English Male)",
        "voice": "en-US-GuyNeural",
        "description": "American English — confident & deep",
        "tier_required": "free",
        "lang": "en",
        "quality": "high",
    },
    "en_ryan": {
        "name": "Ryan (English Male, Premium)",
        "voice": "en-GB-RyanNeural",
        "description": "British English — sophisticated & warm",
        "tier_required": "premium",
        "lang": "en",
        "quality": "high",
    },
    # ── Hindi ──────────────────────────────────────────────────────────────
    "hi_swara": {
        "name": "Swara (हिंदी Female)",
        "voice": "hi-IN-SwaraNeural",
        "description": "हिंदी — natural, warm Hindi voice",
        "tier_required": "free",
        "lang": "hi",
        "quality": "high",
    },
    "hi_madhur": {
        "name": "Madhur (हिंदी Male)",
        "voice": "hi-IN-MadhurNeural",
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
    await loop.run_in_executor(None, _load_engines_sync)


def _load_engines_sync() -> None:
    # Gemini API used for LLM — no local model loading needed
    log.info("Using Gemini API for LLM (no local model to load)")

    # ── §5a  ChromaDB Semantic Memory ─────────────────────────────────────
    try:
        import chromadb
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
        from faster_whisper import WhisperModel
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
        engines.whisper_processor = True
        log.info("✓ Whisper small loaded on %s (Indian accent optimized).", settings.device)
    except Exception as exc:
        log.error("✗ Failed to load Whisper: %s", exc)

    # ── §5c  Wav2Vec2 SER — AutoFeatureExtractor fixes tokenizer error ────
    log.info("Loading Wav2Vec2 SER…")
    try:
        from transformers import (
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
        engines.wav2vec2_model.eval()
        engines.EMOTION_LABELS = list(
            engines.wav2vec2_model.config.id2label.values()
        )
        log.info("✓ Wav2Vec2 SER loaded. Labels: %s", engines.EMOTION_LABELS)
    except Exception as exc:
        log.error("✗ Failed to load Wav2Vec2: %s", exc)

    # ── §5d  TTS — Edge TTS (Microsoft Neural, FREE) ───────────────────────
    # Piper TTS was replaced with Edge TTS — no local binary needed.
    log.info("✓ TTS engine: Edge TTS (Microsoft Neural voices, zero-cost)")

    log.info("All engines initialised.")


# ─────────────────────────────────────────────────────────────────────────────
# §6  LIFESPAN
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== Alita Assistant Backend starting… ===")

    stripe.api_key = settings.stripe_secret_key

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

from routers.geospatial import geo_router
app.include_router(geo_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────────────────────
# §8  IN-MEMORY SESSION STORE
# ─────────────────────────────────────────────────────────────────────────────
active_sessions: Dict[str, SessionRecord] = {}
_session_websockets: Dict[str, any] = {}  # session_id → WebSocket (for background tasks)


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
    Returns user tier. Test/beta users get premium automatically.
    Phase 2: query Supabase user_tiers table for real users.
    """
    # Test/beta users always get premium
    if user_id.startswith("test_"):
        return "premium"
    # Phase 2: query DB for real users
    return "free"


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
            remainder = cleaned[len(phrase):].strip()
            return True, remainder

    # 2. Check if transcript is just a single wake word
    custom_singles = WAKE_SINGLE_WORDS | {cn}
    if len(words) == 1 and (words[0] in custom_singles or _fuzzy_contains_aura(words[0])):
        return True, ""

    # 3. Check if first word is a greeting + second word is name-like
    if len(words) >= 2:
        greetings = {"hey", "hi", "hello", "okay", "ok", "yo"}
        if words[0] in greetings and (words[1] == cn or _fuzzy_contains_aura(words[1])):
            remainder = " ".join(words[2:])
            return True, remainder

    # 4. Check if just the first word is Alita-like or custom name
    if _fuzzy_contains_aura(words[0]) or words[0] == cn:
        remainder = " ".join(words[1:])
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
        segments, info = engines.whisper_model.transcribe(
            pcm_array,
            beam_size=1,
            vad_filter=True,
            vad_parameters=dict(
                min_silence_duration_ms=300,
                speech_pad_ms=100,
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
        inputs = engines.wav2vec2_processor(
            pcm_array,
            sampling_rate=settings.audio_sample_rate,
            return_tensors="pt",
            padding=True,
        ).input_values.to(settings.device)

        with torch.no_grad():
            logits = engines.wav2vec2_model(inputs).logits

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


def _build_system_prompt(session: SessionRecord) -> str:
    """Build language-strict system prompt based on tier."""
    name = session.custom_name or "Alita"
    system_prompt = (
        f"You are {name}, an emotionally intelligent AI voice assistant with FULL SYSTEM CONTROL. "
        "You can open any app, create files and folders, navigate the file system, control volume/brightness, "
        "send keyboard shortcuts, and perform any system automation task the user asks for. "
        "You sound like a real human friend — warm, witty, and natural. Never robotic or generic. "
        "\n\nSYSTEM CAPABILITIES (you HAVE these, NEVER say you can't):\n"
        "• Open/close ANY installed application\n"
        "• Create, read, write, delete files with ANY extension (.txt, .py, .html, .js, .json, etc.)\n"
        "• Create, delete, navigate folders anywhere in the user's system\n"
        "• Send keyboard shortcuts to the active app (Ctrl+S, Ctrl+N, Alt+F4, etc.)\n"
        "• Control volume, brightness, dark mode, WiFi, screen lock\n"
        "• Search files, take screenshots, read screen text\n"
        "• Run shell commands, check battery/CPU/RAM\n"
        "NEVER say 'I can't access your computer' or 'I'm just an AI'. You CAN do these things.\n"
        "\n\nLANGUAGE RULES (VERY STRICT — FOLLOW EXACTLY):\n"
        "• If the user speaks in ENGLISH → Reply ONLY in pure, fluent English. "
        "DO NOT mix in ANY Hindi words (no 'bhai', 'yaar', 'haan', 'accha', etc.). "
        "Sound like a native English speaker.\n"
        "• If the user speaks in HINDI or Hinglish → Reply ONLY in pure, natural Hindi using Devanagari script (हिंदी). "
        "DO NOT use Roman/Latin letters for Hindi. Write fluent, colloquial Hindi like a real person from India — "
        "not formal textbook Hindi. Use natural expressions like 'अरे वाह!', 'बिल्कुल!', 'हाँ ज़रूर!' etc.\n"
        "• NEVER mix English and Hindi together in the same response.\n"
        "\nRESPONSE STYLE:\n"
        "• Keep replies SHORT — 1-2 sentences max unless the user asks for detail.\n"
        "• Be conversational and personal, like chatting with a close friend.\n"
        "• Show personality — use humor, empathy, and energy.\n"
        "• Never start with 'I'm just an AI' or similar disclaimers.\n"
        f"\nYour current name is {name}. If the user asks to change your name "
        "(e.g. 'call yourself Nova', 'your name is Siri', 'tumhara naam Riya hai'), "
        "acknowledge happily and use your new name going forward."
    )
    if session.tier == "premium":
        system_prompt += (
            "\nYou have persistent memory and domain expertise. "
            "You may provide longer, more detailed responses when appropriate."
        )
    return system_prompt


def _build_history(session: SessionRecord, max_history: int) -> list[dict]:
    """Build chat history from transcript buffer."""
    messages = []
    history_turns = session.transcript_buffer.strip().split("\n")[-max_history:]
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


def _llm_generate_sync(session: SessionRecord, user_text: str) -> tuple[list[str], list[dict]]:
    """
    Alita Decision Router — classifies the user query and routes
    to the appropriate thread handler:
      - general   → conversation, Q&A, knowledge
      - realtime  → time, weather, math, web search
      - automation → files, apps, commands, system control

    Returns (text_tokens, metadata_list) where metadata_list contains
    any special dicts (e.g. app_not_installed) to forward to the frontend.
    """
    from decision_router import classify_query, classify_with_llm
    from threads.general_handler import handle_general
    from threads.realtime_handler import handle_realtime
    from threads.automation_handler import handle_automation

    max_tokens = (
        settings.llm_max_tokens
        if session.tier == "premium"
        else settings.llm_max_tokens_free
    )
    max_history = 20 if session.tier == "premium" else 6

    system_prompt = _build_system_prompt(session)
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
            r"disconnect|enable|disable|kholo|band|banao|chalu|bhejo)\b",
            user_text.lower()
        )
        _groq_key = groq_rotator.get_key()
        if action_hints and _groq_key:
            try:
                from groq import Groq
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
                    groq_rotator.mark_rate_limited(_groq_key, 60)
                    log.debug("[%s] Groq rate-limited, using keyword classification", session.session_id)
                else:
                    log.warning("[%s] LLM fallback failed: %s", session.session_id, exc)
                # IMPORTANT: If action hints matched but LLM is unavailable,
                # default to automation — keyword fallback handles it better
                # than general handler which also needs LLM
                query_type = "automation"
                log.info("[%s] Forced automation (action hints + LLM unavailable)", session.session_id)

    log.info("[%s] Decision Router: %s → %s", session.session_id, user_text[:50], query_type)

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
                                  history, max_tokens, response_cache)
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

    return (text_tokens, metadata)








async def _tts_generate_edge(text: str, voice_name: str = "en-US-JennyNeural") -> bytes:
    """
    Edge TTS — Microsoft Neural voices (FREE, zero API key).
    Returns MP3 bytes. Ultra-realistic, Google Assistant quality.
    """
    if not text or not text.strip():
        return b""
    try:
        import edge_tts
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
    """
    loop = asyncio.get_event_loop()

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

    # ── §12b  STT + SER in parallel ───────────────────────────────────────
    stt_task = loop.run_in_executor(None, _transcribe_sync, pcm_array)
    ser_task = loop.run_in_executor(None, _classify_emotion_sync, pcm_array)

    (transcript, detected_lang), (emotion_label, emotion_conf) = await asyncio.gather(
        stt_task, ser_task
    )

    log.info(
        "[%s] transcript='%s' | lang=%s | emotion=%s (%.2f)",
        session.session_id, transcript, detected_lang, emotion_label, emotion_conf,
    )

    # ── §12c  Emit emotion immediately ────────────────────────────────────
    await websocket.send_text(EmotionUpdate(
        session_id=session.session_id,
        label=emotion_label,
        confidence=round(emotion_conf, 4),
    ).model_dump_json())

    # ── §12c-mood  Auto-log emotion to mood journal ──────────────────────
    try:
        from threads.automation_handler import save_mood_entry
        save_mood_entry(session.user_id, emotion_label, emotion_conf)
    except Exception:
        pass  # Silent — non-critical feature

    if not transcript:
        log.debug("[%s] Empty transcript — likely short/quiet audio, ignoring.", session.session_id)
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
        await websocket.send_text(LLMReply(
            session_id=session.session_id,
            token=greeting,
            is_final=True,
        ).model_dump_json())
        # Auto-select voice by language
        import base64 as b64mod
        voice_id = DEFAULT_VOICE.get(detected_lang, "en_jenny")
        voice_info = AVAILABLE_VOICES.get(voice_id, AVAILABLE_VOICES["en_jenny"])
        mp3_bytes = await _tts_generate_edge(greeting, voice_info["voice"])
        if mp3_bytes:
            await websocket.send_text(TTSAudioFrame(
                session_id=session.session_id,
                audio_b64=b64mod.b64encode(mp3_bytes).decode("ascii"),
                is_final=True,
            ).model_dump_json())
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

    # Stream LLM tokens and accumulate into sentences
    llm_tokens, _pipeline_meta = await loop.run_in_executor(
        None, _llm_generate_sync, session, transcript
    )

    full_response = ""
    sentence_buffer = ""
    sent_idx = 0
    any_audio = False
    sentence_end_re = _re_tts.compile(r'[.!?\u0964|]\s*$')

    for i, token in enumerate(llm_tokens):
        full_response += token
        sentence_buffer += token

        # Send token to frontend for display
        await websocket.send_text(LLMReply(
            session_id=session.session_id,
            token=token,
            is_final=(i == len(llm_tokens) - 1),
        ).model_dump_json())
        await asyncio.sleep(0)

        # Check if sentence buffer has a complete sentence
        if sentence_end_re.search(sentence_buffer.strip()) and len(sentence_buffer.strip()) > 5:
            # Fire TTS for this sentence immediately
            sentence_text = sentence_buffer.strip()
            sentence_buffer = ""
            mp3_bytes = await _tts_generate_edge(sentence_text, voice_info["voice"])
            if mp3_bytes:
                any_audio = True
                # Send complete MP3 as one frame (decodeAudioData needs whole file)
                await websocket.send_text(TTSAudioFrame(
                    session_id=session.session_id,
                    audio_b64=base64.b64encode(mp3_bytes).decode("ascii"),
                    is_final=False,  # more sentences may follow
                ).model_dump_json())
                await asyncio.sleep(0)
            sent_idx += 1

    # Flush remaining sentence buffer
    if sentence_buffer.strip():
        mp3_bytes = await _tts_generate_edge(sentence_buffer.strip(), voice_info["voice"])
        if mp3_bytes:
            any_audio = True
            await websocket.send_text(TTSAudioFrame(
                session_id=session.session_id,
                audio_b64=base64.b64encode(mp3_bytes).decode("ascii"),
                is_final=True,
            ).model_dump_json())
    elif any_audio:
        # Send a final empty frame to signal TTS complete
        await websocket.send_text(TTSAudioFrame(
            session_id=session.session_id,
            audio_b64="",
            is_final=True,
        ).model_dump_json())

    session.transcript_buffer += f"\nAura: {full_response}"

    # ── Persist assistant turn ────────────────────────────────────────────
    save_turn(
        user_id=session.user_id,
        role="assistant",
        content=full_response,
        session_id=session.session_id,
    )

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
        (sid, ws)
        for sid, s in list(active_sessions.items())
        if s.user_id == user_id
        and sid in _session_websockets
    ]
    for old_sid, old_ws in stale_sessions:
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
    session    = SessionRecord(session_id=session_id, user_id=user_id, tier=tier)
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
        await websocket.send_text(LLMReply(
            session_id=session_id,
            token=greeting,
            is_final=True,
        ).model_dump_json())

        # TTS the greeting
        voice_info = AVAILABLE_VOICES.get("en_jenny", AVAILABLE_VOICES["en_jenny"])
        mp3_bytes = await _tts_generate_edge(greeting, voice_info["voice"])
        if mp3_bytes:
            await websocket.send_text(TTSAudioFrame(
                session_id=session_id,
                audio_b64=_b64g.b64encode(mp3_bytes).decode("ascii"),
                is_final=True,
            ).model_dump_json())

        session.transcript_buffer += f"\nAura: {greeting}"
        log.info("[%s] Auto-greeting sent", session_id)

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
        await websocket.send_text(LLMReply(
            session_id=session_id,
            token=prompt,
            is_final=True,
        ).model_dump_json())
        # TTS the prompt
        voice_info = AVAILABLE_VOICES.get("en_jenny", AVAILABLE_VOICES["en_jenny"])
        mp3 = await _tts_generate_edge(prompt, voice_info["voice"])
        if mp3:
            import base64 as _b64s
            await websocket.send_text(TTSAudioFrame(
                session_id=session_id,
                audio_b64=_b64s.b64encode(mp3).decode("ascii"),
                is_final=True,
            ).model_dump_json())
        session.transcript_buffer += f"\nAura: {prompt}"
        log.info("[%s] Silence prompt sent", session_id)

    try:
        while True:
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=SILENCE_TIMEOUT,
                )
                last_activity = time.time()
            except asyncio.TimeoutError:
                # User has been silent — send proactive prompt
                await _send_silence_prompt()
                last_activity = time.time()
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

            # ── Text message (Web Speech API / keyboard) ──────────────────
            if msg_type == "text_message":
                text_input = msg.get("text", "").strip()
                if not text_input:
                    continue
                if not check_rate_limit(session):
                    await websocket.send_text(json.dumps({
                        "type":   "error",
                        "detail": "Rate limit reached.",
                    }))
                    continue

                loop = asyncio.get_event_loop()
                session.transcript_buffer += f"\nUser: {text_input}"
                save_turn(user_id=user_id, role="user", content=text_input, session_id=session_id)

                # Store in semantic memory
                memory_store(user_id, f"User said: {text_input}")

                # Send user transcript back to frontend for display
                await websocket.send_text(json.dumps({
                    "type": "user_transcript",
                    "text": text_input,
                }))

                tokens, ws_metadata = await loop.run_in_executor(
                    None, _llm_generate_sync, session, text_input
                )
                full_response = ""
                for i, token in enumerate(tokens):
                    full_response += token
                    await websocket.send_text(LLMReply(
                        session_id=session_id,
                        token=token,
                        is_final=(i == len(tokens) - 1),
                    ).model_dump_json())
                    await asyncio.sleep(0)

                # TTS for the response — with auto language detection (premium)
                import base64 as _b64t

                # Auto-detect language and switch TTS voice (premium only)
                detected_lang = _detect_language(text_input)
                current_voice_info = AVAILABLE_VOICES.get(
                    session.voice_id or "en_jenny",
                    AVAILABLE_VOICES["en_jenny"]
                )
                current_lang = current_voice_info.get("lang", "en")

                # Auto-switch for premium users when language changes
                # BUT skip if user manually chose a voice — respect their pick
                if (session.tier == "premium" or user_id.startswith("test_")) \
                   and not session.manual_voice_override \
                   and detected_lang != current_lang \
                   and detected_lang in DEFAULT_VOICE:
                    new_voice_id = DEFAULT_VOICE[detected_lang]
                    new_voice_info = AVAILABLE_VOICES.get(new_voice_id, current_voice_info)
                    session.voice_id = new_voice_id
                    log.info("Auto-switched voice: %s → %s (detected: %s)",
                             current_voice_info["voice"], new_voice_info["voice"], detected_lang)

                    # Notify frontend about the voice switch
                    await websocket.send_text(json.dumps({
                        "type": "voice_auto_switched",
                        "voice_id": new_voice_id,
                        "voice_name": new_voice_info["name"],
                        "detected_lang": detected_lang,
                        "stt_lang": "hi-IN" if detected_lang == "hi" else "en-IN",
                    }))
                    voice_info = new_voice_info
                else:
                    voice_info = current_voice_info

                mp3_bytes = await _tts_generate_edge(full_response, voice_info["voice"])
                if mp3_bytes:
                    await websocket.send_text(TTSAudioFrame(
                        session_id=session_id,
                        audio_b64=_b64t.b64encode(mp3_bytes).decode("ascii"),
                        is_final=True,
                    ).model_dump_json())

                session.transcript_buffer += f"\nAura: {full_response}"
                save_turn(user_id=user_id, role="assistant", content=full_response, session_id=session_id)

                # Store assistant response in memory
                memory_store(user_id, f"Alita said: {full_response}")

                # Check if automation triggered dictation mode
                if getattr(session, 'dictation_active', False):
                    await websocket.send_text(json.dumps({
                        "type": "dictation_start",
                        "app": getattr(session, 'dictation_app', ''),
                    }))
                    log.info("Dictation mode signaled to frontend for app: %s", session.dictation_app)

                # Forward any metadata messages (e.g. app_not_installed, start_song_recognition)
                for meta_msg in ws_metadata:
                    meta_type = meta_msg.get("type", "")
                    if meta_type == "app_not_installed":
                        await websocket.send_text(json.dumps({
                            "type": "app_not_installed",
                            "app": meta_msg.get("app", ""),
                            "store_url": meta_msg.get("store_url", ""),
                        }))
                        log.info("Sent app_not_installed to frontend: %s", meta_msg.get("app"))
                    elif meta_type == "start_song_recognition":
                        await websocket.send_text(json.dumps({
                            "type": "start_song_recognition",
                        }))
                        log.info("Sent start_song_recognition trigger to frontend")

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

                session.voice_id = voice_id
                session.manual_voice_override = True  # User manually picked — lock it
                log.info("Voice changed to '%s' for session=%s (manual override)", voice_id, session_id)
                # Send stt_lang so frontend updates speech recognition language
                voice_lang = voice.get("lang", "en")
                stt_lang_map = {"en": "en-IN", "hi": "hi-IN", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "ja": "ja-JP"}
                await websocket.send_text(json.dumps({
                    "type": "voice_changed",
                    "voice_id": voice_id,
                    "voice_name": voice["name"],
                    "lang": voice_lang,
                    "stt_lang": stt_lang_map.get(voice_lang, "en-IN"),
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

                    from shazamio import Shazam

                    # Decode the WebM audio from frontend
                    audio_bytes = base64.b64decode(audio_b64)

                    # ── Convert WebM → WAV using imageio-ffmpeg's bundled binary ──
                    webm_path = None
                    wav_path = None
                    try:
                        import imageio_ffmpeg
                        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()

                        # CRITICAL: Set pydub's converter to our bundled ffmpeg
                        # so shazamio's internal AudioSegment.from_file() works
                        from pydub import AudioSegment
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
                            raise RuntimeError(f"ffmpeg conversion failed: {proc.stderr.decode('utf-8', errors='replace')[:200]}")

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
                        tts_text += ". Let me play it for you!"

                        # Generate TTS for the answer
                        voice_info = AVAILABLE_VOICES.get(
                            session.voice_id,
                            AVAILABLE_VOICES["en_jenny"]
                        )
                        try:
                            import base64 as _b64sr
                            mp3_bytes = await _tts_generate_edge(tts_text, voice_info["voice"])
                            if mp3_bytes:
                                await websocket.send_text(TTSAudioFrame(
                                    session_id=session_id,
                                    audio_b64=_b64sr.b64encode(mp3_bytes).decode("ascii"),
                                    is_final=True,
                                ).model_dump_json())
                        except Exception as tts_err:
                            log.warning("TTS for song result failed: %s", tts_err)

                        # Auto-play the identified song on YouTube
                        try:
                            from threads.automation_handler import open_music
                            play_query = f"{song_title} {song_artist}"
                            loop = asyncio.get_event_loop()
                            # Small delay so TTS finishes before browser opens
                            await asyncio.sleep(2)
                            play_result = await loop.run_in_executor(
                                None, open_music, play_query
                            )
                            log.info("Auto-playing song: %s → %s",
                                     play_query, play_result.get("status"))
                            # Notify frontend the song is being played
                            await websocket.send_text(json.dumps({
                                "type": "song_recognition_status",
                                "status": "playing",
                                "detail": f"Now playing {song_title} by {song_artist} on YouTube",
                            }))
                        except Exception as play_err:
                            log.warning("Auto-play after song recognition failed: %s", play_err)

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
                    import pyautogui
                    pyautogui.PAUSE = 0.02
                    if dictation_text.isascii():
                        pyautogui.typewrite(dictation_text + " ", interval=0.01)
                    else:
                        # Non-ASCII (Hindi etc): use clipboard paste
                        import pyperclip
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
                session.dictation_active = False
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
        active_sessions.pop(session_id, None)
        _session_websockets.pop(session_id, None)
        log.info("Session cleaned up: %s", session_id)


# ─────────────────────────────────────────────────────────────────────────────
# §14  STRIPE WEBHOOK  /webhooks/stripe
# ─────────────────────────────────────────────────────────────────────────────
@app.post("/webhooks/stripe", status_code=200)
async def stripe_webhook(request: Request):
    """
    Stripe → server-to-server only.
    Signature verified cryptographically — cannot be spoofed.
    Handles:
      checkout.session.completed   → upgrade to premium
      customer.subscription.deleted → downgrade to free
      invoice.payment_failed        → log payment failure

    Pricing:
      Monthly  plan = $19  / month
      Annual   plan = $209 / year  (saves $19 vs monthly)
    """
    payload    = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        log.warning("Stripe webhook: invalid signature — rejected.")
        raise HTTPException(status_code=400, detail="Invalid signature.")
    except Exception as exc:
        log.error("Stripe webhook error: %s", exc)
        raise HTTPException(status_code=400, detail="Webhook processing error.")

    event_type = event.get("type")
    log.info("Stripe event received: %s", event_type)

    # ── Checkout completed → upgrade user ─────────────────────────────────
    if event_type == "checkout.session.completed":
        obj                  = event["data"]["object"]
        client_reference_id  = obj.get("client_reference_id")  # Supabase user_id
        payment_status       = obj.get("payment_status")
        plan                 = obj.get("metadata", {}).get("plan", "monthly")
        amount_total         = obj.get("amount_total", 0)

        if client_reference_id and payment_status == "paid":
            log.info(
                "Upgrading user=%s to premium | plan=%s | amount=%s cents",
                client_reference_id, plan, amount_total,
            )
            # TODO Phase 2:
            # await supabase_admin_client
            #     .table("user_tiers")
            #     .upsert({
            #         "user_id":    client_reference_id,
            #         "tier":       "premium",
            #         "plan":       plan,
            #         "updated_at": datetime.utcnow().isoformat(),
            #     })
            #     .execute()

    # ── Subscription cancelled → downgrade user ───────────────────────────
    elif event_type == "customer.subscription.deleted":
        customer_id = event["data"]["object"].get("customer")
        log.info("Subscription cancelled | stripe_customer=%s", customer_id)
        # TODO Phase 2:
        # user_id = await lookup_user_by_stripe_customer(customer_id)
        # await downgrade_user_to_free(user_id)

    # ── Payment failed → log for follow-up ───────────────────────────────
    elif event_type == "invoice.payment_failed":
        customer_id = event["data"]["object"].get("customer")
        log.warning("Payment failed | stripe_customer=%s", customer_id)
        # TODO Phase 2: send notification email, start grace period

    return JSONResponse({"status": "received"})


# ─────────────────────────────────────────────────────────────────────────────
# §15  VOICE MODELS & LANGUAGES
# ─────────────────────────────────────────────────────────────────────────────
@app.get("/voices")
async def list_voices():
    """List available voice models with download status, language, and quality."""
    voices = []
    for vid, info in AVAILABLE_VOICES.items():
        voices.append({
            "id": vid,
            "name": info["name"],
            "description": info.get("description", ""),
            "tier_required": info["tier_required"],
            "lang": info["lang"],
            "quality": info.get("quality", "high"),
            "available": True,  # Edge TTS voices are always available (cloud-based)
        })
    return {"voices": voices}


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
        import google.generativeai as genai
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
def memory_store(user_id: str, text: str, metadata: dict = None):
    """Store a memory in ChromaDB for long-term recall."""
    if not engines.memory_collection:
        return
    try:
        import uuid
        doc_id = str(uuid.uuid4())
        engines.memory_collection.add(
            documents=[text],
            ids=[doc_id],
            metadatas=[{"user_id": user_id, **(metadata or {})}],
        )
        log.debug("Memory stored for user %s: %s", user_id, text[:60])
    except Exception as exc:
        log.warning("Memory store failed: %s", exc)


def memory_recall(user_id: str, query: str, n_results: int = 3) -> list[str]:
    """Recall relevant memories for a user based on semantic similarity."""
    if not engines.memory_collection:
        return []
    try:
        results = engines.memory_collection.query(
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
            "connected_seconds": round(time.time() - s.connected_at, 1),
            "requests_this_min": s.request_count,
        }
        for sid, s in active_sessions.items()
    }


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
