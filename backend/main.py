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
import re
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
from ws_handler import (
    WsContext,
    dispatch_ws_message,
    handle_speculative_query,
    handle_cancel_speculative,
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
    import warnings as _w
    with _w.catch_warnings():
        _w.simplefilter("ignore", category=FutureWarning)
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
    gemini_model: str        = "gemini-2.5-flash"  # upgraded: better reasoning + vision
    llm_max_tokens: int      = 300      # adaptive per query type
    llm_max_tokens_free: int = 300      # 100% full tokens on free tier
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
    whisper_model_size: str      = "base"

    # ── Rate limiting ─────────────────────────────────────────────────────
    rate_limit_free: int    = 120  # requests per minute (unlimited free tier)
    rate_limit_premium: int = 120

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

    # ── TTS Engine Configuration ──────────────────────────────────────────
    tts_engine_mode: str = "chatterbox_turbo"  # Chatterbox Turbo is the sole TTS engine
    tts_preload_turbo: bool = True
    tts_preload_multilingual: bool = False


settings = Settings()
_all_keys = settings.get_all_gemini_keys()
try:
    from ollama_client import get_model_name, is_ollama_running
    _ollama_model = get_model_name()
    _ollama_status = "online" if is_ollama_running() else "offline"
    log.info("Device: %s | Primary LLM: Ollama %s (%s) | Gemini Fallback Keys: %d loaded",
             settings.device, _ollama_model, _ollama_status, len(_all_keys))
except Exception:
    log.info("Device: %s | Gemini Keys: %d loaded", settings.device, len(_all_keys))


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
from schemas.models import (
    AudioChunk,
    TextMessage,
    LLMReply,
    EmotionUpdate,
    TTSAudioFrame,
    SessionRecord,
    CheckoutRequest,
)


# ─────────────────────────────────────────────────────────────────────────────
# §3  ENGINE REGISTRY
# ─────────────────────────────────────────────────────────────────────────────
class EngineRegistry:
    """Engine Registry — Local Speech & Perception Engine Singletons."""
    llm                      = None
    whisper_model            = None
    whisper_processor        = None     # True sentinel for faster-whisper
    wav2vec2_model           = None
    wav2vec2_processor       = None
    memory_collection        = None     # ChromaDB semantic memory
    chatterbox_turbo_engine  = None     # Chatterbox-Turbo engine (sole TTS)
    EMOTION_LABELS: list[str] = ["neutral", "happy", "angry", "sad"]


# ── Available voice models ──────────────────────────────────────────────────────
AVAILABLE_VOICES = {
    "chatterbox_turbo_mj": {
        "name": "MJ (Chatterbox Turbo)",
        "voice": None,
        "speaker_wav": "voices/default/alita_en_original.wav",
        "engine": "chatterbox_turbo",
        "description": "350M-param neural voice with [laugh], [sigh], [cough] expression tags",
        "tier_required": "free",
        "lang": "en",
        "quality": "ultra",
    },
}

# ── Language display names ──────────────────────────────────────────────────
LANGUAGE_NAMES = {
    "en": "English",
    "hi": "Hinglish / हिंदी",
    "zh": "Chinese",
}

# ── Default voice per language ──────────────────────────────────────────────
_default_active_voice = "chatterbox_turbo_mj"
DEFAULT_VOICE = {
    "en": "chatterbox_turbo_mj",
    "hi": "chatterbox_turbo_mj",
    "zh": "chatterbox_turbo_mj",
}


engines = EngineRegistry()


from tts_dispatch import (
    get_or_load_turbo_engine,
    get_or_load_multilingual_engine,
    _tts_generate,
)


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
    # Primary LLM runs locally via Ollama with optional cloud fallback
    log.info("Primary LLM: Ollama local engine (cloud fallbacks configured)")

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

    _whisper_size = os.getenv("WHISPER_MODEL", "") or getattr(settings, "whisper_model_size", "base") or "base"
    log.info("Loading Whisper %s (multilingual) via faster-whisper…", _whisper_size)
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        compute = "float16" if settings.device == "cuda" else "int8"
        try:
            engines.whisper_model = WhisperModel(
                _whisper_size,
                device=settings.device,
                compute_type=compute,
                download_root="./models/whisper_cache",
            )
        except Exception as inner:
            # int8 can fail on Windows — fall back to float32
            if compute == "int8":
                log.warning("int8 failed (%s), falling back to float32 on CPU…", inner)
                engines.whisper_model = WhisperModel(
                    _whisper_size,
                    device="cpu",
                    compute_type="float32",
                    download_root="./models/whisper_cache",
                )
            else:
                raise
        engines.whisper_processor = True  # type: ignore[assignment]  # sentinel flag for faster-whisper
        log.info("✓ Whisper %s loaded on %s.", _whisper_size, settings.device)
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

    # ── §5d  Chatterbox Turbo — Sole Production Voice Engine ──────────────
    try:
        from engines.resource_guard import resource_guard
        with resource_guard.loading("ChatterboxTurbo", estimated_mb=800):
            from engines.tts_chatterbox_turbo import ChatterboxTurboEngine
            engines.chatterbox_turbo_engine = ChatterboxTurboEngine()
            if engines.chatterbox_turbo_engine.available:
                log.info("✓ Chatterbox-Turbo engine loaded (sole TTS: chatterbox_turbo_mj)")
            else:
                log.error("✗ Chatterbox-Turbo engine failed to initialize")
    except Exception as exc:
        log.error("✗ Failed to load Chatterbox-Turbo: %s", exc, exc_info=True)
        engines.chatterbox_turbo_engine = None

    log.info("Voice engine initialised (Mode: chatterbox_turbo).")


# ─────────────────────────────────────────────────────────────────────────────
# §6  LIFESPAN
# ─────────────────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("=== MJ Assistant Backend starting… ===")

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

    # Start proactive intelligence sentinel daemon & broadcast callback
    try:
        from engines.proactive_agent import proactive_agent
        _main_loop = asyncio.get_running_loop()

        def _broadcast_proactive_suggestion(suggestion: dict):
            for sid, ws in list(_session_websockets.items()):
                try:
                    payload = json.dumps({"type": "proactive_suggestion", **suggestion})
                    asyncio.run_coroutine_threadsafe(ws.send_text(payload), _main_loop)
                except Exception:
                    pass

        proactive_agent.register_broadcast_callback(_broadcast_proactive_suggestion)
        proactive_agent.start()
        log.info("✓ Proactive situational sentinel started.")
    except Exception as exc:
        log.warning("Proactive agent startup notice: %s", exc)

    # Start background reminder checker
    reminder_task = asyncio.create_task(_reminder_checker())

    # Start screen OCR background daemon (Layer 1 of Hybrid Vision Engine)
    # Enables: screen reading, proactive error detection, vision analysis
    # Zero VRAM — runs entirely on CPU via winocr/Tesseract
    try:
        from engines.screen_ocr import screen_ocr
        screen_ocr.start()
        log.info("✓ Screen OCR background daemon started (scan_interval=%.1fs).", screen_ocr.scan_interval)
    except Exception as exc:
        log.warning("Screen OCR startup notice: %s", exc)

    log.info("=== Ready to accept connections. ===")
    yield
    reminder_task.cancel()
    try:
        from engines.proactive_agent import proactive_agent
        proactive_agent.stop()
    except Exception:
        pass
    try:
        from engines.screen_ocr import screen_ocr
        screen_ocr.stop()
    except Exception:
        pass
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
    title="MJ Assistant API",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(test_auth_router)
app.include_router(youtube_router)

from routers.geospatial import geo_router  # type: ignore[import]
app.include_router(geo_router)

from routers.phone_router import phone_router  # type: ignore[import]
app.include_router(phone_router)

from routers.system_router import system_router  # type: ignore[import]
app.include_router(system_router)

from routers.voice_clone import voice_clone_router  # type: ignore[import]
app.include_router(voice_clone_router)

from routers.screen_control import router as screen_router  # type: ignore[import]
app.include_router(screen_router)

from routers.voice_router import voice_router  # type: ignore[import]
app.include_router(voice_router)

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
        if "server" in response.headers:
            del response.headers["server"]
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
    "hey MJ", "hi MJ", "hello MJ",
    "okay MJ", "ok MJ", "yo MJ",
    "hey mj", "hi mj", "hello mj",
    "okay mj", "ok mj", "yo mj",
    "hey Alita", "hi Alita", "hello Alita",
    "okay Alita", "ok Alita", "yo Alita",
    "hey ora", "hi ora", "hello ora",       # common Whisper mishearing
    "hey auro", "hi auro", "hello auro",    # another mishearing
    "hey ara", "hi ara",
    "hey alita", "hi alita", "hello alita",  # lowercase variants
    # Hindi variants
    "namaste MJ", "namaste mj", "namaste Alita", "namaste ora",
    "suno MJ", "suno mj", "suno Alita", "suno ora",
    "MJ suno", "mj suno", "Alita suno",
    "MJ", "mj", "Alita",
]

# Single-word triggers (user might just say "hey" or "hello" to activate)
WAKE_SINGLE_WORDS = {"hey", "hi", "hello", "MJ", "mj", "emjay", "Alita", "alita", "ora", "auro", "aur", "ara", "namaste", "suno"}


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
    aura_variants = {"MJ", "mj", "emjay", "Alita", "alita", "aur", "ora", "auro", "aurah", "ara", "arra", "aora", "aleeta", "alitta"}
    return word in aura_variants



def _strip_wake_word(transcript: str, custom_name: str = "MJ") -> tuple[bool, str]:
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
    if cn and cn not in ("mj", "alita"):
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
                custom_name=session.custom_name or "MJ",
                memory_context=memory_context,
                user_text=user_text,
            )
            log.debug("Using personality_engine prompt (Alita master prompt not loaded)")

        except Exception as exc:
            # ── Fallback 2: basic inline prompt ───────────────────────────
            log.warning("Personality engine error, using basic fallback: %s", exc)
            name = session.custom_name or "MJ"
            system_prompt = (
                f"You are {name}, an emotionally intelligent AI voice assistant. "
                "You sound like a real human friend — warm, witty, and natural. "
                "You have FULL SYSTEM CONTROL — you can open apps, create files, "
                "control the system, and perform any automation task. "
                "NEVER say 'I can\'t access your computer' or 'I\'m just an AI'. "
                "Reply in the user's language. Be fast, be human, be helpful."
            )

    # ── Dynamic context additions (applied to all prompt sources) ─────────
    # Full persistent memory and domain expertise unlocked for free tier
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

    # ── Ground Truth Lie Detection & Verification ──────────────────────────
    if user_text:
        try:
            from engines.lie_detector import lie_detector
            eval_res = lie_detector.evaluate_user_utterance(user_text)
            if eval_res.get("detected") and eval_res.get("prompt_directive"):
                system_prompt += f"\n\n{eval_res['prompt_directive']}"
        except Exception as exc:
            log.warning("Lie detector prompt integration error: %s", exc)

    # ── Girlfriend Relationship Dynamics ────────────────────────────────────
    # Bug 5 Fix: Deduplication guard to ensure directive is added exactly once
    if "[GIRLFRIEND RELATIONSHIP DYNAMICS]" not in system_prompt:
        try:
            from engines.relationship_manager import relationship_manager
            rel_prompt = relationship_manager.get_personality_directives()
            if rel_prompt:
                system_prompt += f"\n\n{rel_prompt}"
        except Exception as exc:
            log.warning("Relationship manager prompt integration error: %s", exc)

    # ── Ambient Awareness — always-on contextual intelligence ───────────────
    if "[AMBIENT AWARENESS]" not in system_prompt:
        try:
            from engines.ambient_awareness import ambient_awareness
            awareness_ctx = ambient_awareness.get_awareness_summary()
            if awareness_ctx:
                system_prompt += (
                    f"\n\n[AMBIENT AWARENESS]\n{awareness_ctx}\n"
                    "Use this knowledge naturally — reference what he's doing, how long he's been on an app, "
                    "or what he was doing before. Never say 'according to my sensors' or 'data shows'. "
                    "Speak as if you simply glanced over at his screen."
                )
        except Exception as exc:
            log.warning("Ambient awareness prompt integration error: %s", exc)

    # ── Knowledge Graph — multi-hop relational facts ──────────────────────────
    if "[KNOWLEDGE GRAPH" not in system_prompt:
        try:
            from engines.knowledge_graph import knowledge_graph
            kg_context = knowledge_graph.get_relevant_context(user_text, user_id=session.user_id)
            if kg_context:
                system_prompt += f"\n\n{kg_context}"
        except Exception as exc:
            log.warning("Knowledge graph prompt integration error: %s", exc)

    # ── Connected Mobile Companion Telemetry ───────────────────────────────
    if "[CONNECTED MOBILE COMPANION TELEMETRY]" not in system_prompt:
        try:
            from engines.phone_orchestrator import phone_orchestrator
            phone_telemetry = phone_orchestrator.get_prompt_telemetry_summary()
            if phone_telemetry:
                system_prompt += (
                    f"\n\n[CONNECTED MOBILE COMPANION TELEMETRY]\n{phone_telemetry}\n"
                    "You have live awareness of this smartphone. Answer questions about battery, screen, "
                    "visible apps, or notifications using this data naturally."
                )
        except Exception as exc:
            log.warning("Phone telemetry prompt integration error: %s", exc)

    return system_prompt


def _build_history(session: SessionRecord, max_history: int) -> list[dict]:
    """Build chat history from transcript buffer."""
    messages = []
    history_turns = session.transcript_buffer.strip().split("\n")[-max_history:]  # type: ignore[misc]
    for turn in history_turns:
        if turn.startswith("User:"):
            messages.append({"role": "user", "content": turn[len("User:"):].strip()})
        elif turn.startswith("MJ:"):
            messages.append({"role": "assistant", "content": turn[len("MJ:"):].strip()})
        elif turn.startswith("Alita:"):
            messages.append({"role": "assistant", "content": turn[len("Alita:"):].strip()})
        elif turn.startswith("Aura:"):
            messages.append({"role": "assistant", "content": turn[len("Aura:"):].strip()})
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


def _llm_generate_sync(session: SessionRecord, user_text: str, cancel_event=None, query_type: Optional[str] = None) -> Tuple[List[str], List[Dict[str, Any]]]:
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
    base_max = settings.llm_max_tokens  # 100% full token headroom for all users
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

    max_history = 15  # Full 15-turn context history for all users

    system_prompt = _build_system_prompt(session, user_text=user_text)
    history = _build_history(session, max_history)

    # ── Classify the query (skip if pre-classified) ───────────────────────
    if not query_type:
        query_type = classify_query(user_text)

    # NOTE: Removed LLM re-classification via Groq. The V2 decision_router
    # regex patterns are accurate enough and the Groq round-trip was adding
    # 500-1200ms latency for zero benefit. If regex says 'general', trust it.

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
            raw = None
            # Gap 2: Smart LLM Routing — route complex queries to Gemini 2.5 Flash, simple to Qwen3 4B Q4
            try:
                from engines.smart_router import classify_complexity
                has_image = bool(getattr(session, "pending_image", None))
                complexity = classify_complexity(user_text, has_image=has_image)
                if complexity == "cloud":
                    gem_key = key_rotator.get_key()
                    if gem_key:
                        import google.generativeai as genai
                        genai.configure(api_key=gem_key)
                        g_model = genai.GenerativeModel(model_name=getattr(settings, "gemini_model", "gemini-2.5-flash"))
                        g_prompt = f"{system_prompt}\n\nUser: {user_text}"
                        g_resp = g_model.generate_content(g_prompt)
                        if g_resp and g_resp.text:
                            log.info("[%s] Gemini Cloud response: %d chars", session.session_id, len(g_resp.text))
                            raw = [g_resp.text]
            except Exception as g_err:
                log.warning("[%s] Cloud routing failed, falling back to local: %s", session.session_id, g_err)
                raw = None

            if raw is None:
                # Local path: Check if general query requires autonomous agentic tool orchestration
                tool_verbs = ("see", "check", "read", "open", "find", "search", "analyze", "look", "screen")
                needs_tools = any(re.search(rf"\b{re.escape(v)}\b", lower) for v in tool_verbs)
                if needs_tools:
                    try:
                        from engines.tool_orchestrator import ToolOrchestrator
                        from ollama_client import ollama_chat_messages, get_model_name

                        async def _orchestrator_llm(messages):
                            model = getattr(settings, "ollama_model", "") or get_model_name()
                            return await asyncio.to_thread(
                                ollama_chat_messages,
                                messages=messages,
                                model=model,
                                max_tokens=max_tokens,
                                temperature=getattr(settings, "llm_temperature", 0.7),
                            )

                        orchestrator = ToolOrchestrator(llm_fn=_orchestrator_llm, max_iterations=5)
                        try:
                            loop = asyncio.get_running_loop()
                        except RuntimeError:
                            loop = None

                        if loop and loop.is_running():
                            import concurrent.futures
                            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                                ans = executor.submit(lambda: asyncio.run(orchestrator.run(user_text, system_prompt, session))).result(timeout=60.0)
                        else:
                            ans = asyncio.run(orchestrator.run(user_text, system_prompt, session))

                        raw = [ans]
                    except Exception as t_exc:
                        log.warning("[%s] Tool orchestration fallback to handle_general: %s", session.session_id, t_exc)
                        raw = handle_general(user_text, session, settings, system_prompt,
                                              history, max_tokens, response_cache,
                                              cancel_event=cancel_event)
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









from core.text_utils import clean_text_for_tts, _clean_text_for_tts, preprocess_text_for_tts
# language_router.classify_language removed — single TTS engine, no routing needed
# Note: _tts_generate, get_or_load_multilingual_engine, and get_or_load_turbo_engine
# have been extracted to tts_dispatch.py and imported above.


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

    # ── DUPLICATE STT GATE & ACTIVE TURN INITIALIZATION ──────────
    from core.turn_controller import turn_controller
    turn = turn_controller.start_turn(session.session_id, transcript)
    if turn is None:
        log.warning("[TURN] DUPLICATE_STT_DISCARDED | session=%s | transcript='%s'",
                    session.session_id, transcript[:50])
        return

    # ── DIAGNOSTICS: 1. STT final transcript & 2. request_id ────────────
    from core.diagnostics import diagnostics, resolve_tts_engine
    req_id = diagnostics.on_stt_received(session.session_id, transcript, req_id=turn.request_id)
    session.cancel_event = turn.cancel_event

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
        voice_id = DEFAULT_VOICE.get(detected_lang, _default_active_voice)
        voice_info = AVAILABLE_VOICES.get(voice_id, AVAILABLE_VOICES[_default_active_voice])
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

    # Resolve voice: user's chosen voice, persistent preference, or auto-detect by language
    if session.voice_id and session.voice_id in AVAILABLE_VOICES:
        voice_info = AVAILABLE_VOICES[session.voice_id]
    else:
        try:
            from engines.user_profile import user_profile
            saved_voice = user_profile.get_preference("selected_voice")
            if saved_voice and saved_voice in AVAILABLE_VOICES:
                session.voice_id = saved_voice
                voice_info = AVAILABLE_VOICES[saved_voice]
            else:
                voice_id = DEFAULT_VOICE.get(detected_lang, _default_active_voice)
                voice_info = AVAILABLE_VOICES.get(voice_id, AVAILABLE_VOICES[_default_active_voice])
        except Exception:
            voice_id = DEFAULT_VOICE.get(detected_lang, _default_active_voice)
            voice_info = AVAILABLE_VOICES.get(voice_id, AVAILABLE_VOICES[_default_active_voice])

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
    diagnostics.on_llm_start(req_id)
    _cancel_ev = getattr(session, 'cancel_event', None)
    llm_tokens, _pipeline_meta = await loop.run_in_executor(
        None, _llm_generate_sync, session, enriched_transcript, _cancel_ev
    )
    diagnostics.on_first_token(req_id)

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

    # ── Inject Girlfriend Mood & Affection into face_data for frontend ────
    if face_data_dict:
        try:
            from engines.relationship_manager import relationship_manager
            rel_state = relationship_manager.state
            face_data_dict["girlfriend_mood"] = rel_state.get("current_mood", "playful")
            face_data_dict["mood_intensity"] = rel_state.get("mood_intensity", 0.5)
            face_data_dict["affection_score"] = rel_state.get("affection_score", 75)
            face_data_dict["lie_count_today"] = rel_state.get("lie_count_today", 0)
            face_data_dict["truth_count_today"] = rel_state.get("truth_count_today", 0)
        except Exception:
            pass

    # Send face_data to frontend avatar
    if face_data_dict:
        try:
            await websocket.send_text(json.dumps({
                "type": "face_data",
                "session_id": session.session_id,
                "content": face_data_dict,
            }))
            log.info("[%s] face_data sent to frontend (%s, mood=%s)",
                     session.session_id,
                     face_data_dict.get('emotional_state_label', 'unknown'),
                     face_data_dict.get('girlfriend_mood', 'unknown'))
        except Exception as exc:
            log.warning("[%s] Failed to send face_data: %s", session.session_id, exc)

    # Save last topic for next turn's context
    session._last_topic = transcript[:80]  # type: ignore[attr-defined]

    # ── TTS Engine Hint: Only override if target engine actually exists in EngineRegistry ──
    tts_hint = face_data_dict.get("tts_engine_hint", "") if face_data_dict else ""
    if tts_hint:
        # Map hint names to engine types registered in EngineRegistry
        _hint_to_engine = {
            "chattts": "chattts",
            "f5": "f5",
            "f5_tts": "f5",
            "xtts_v2": "xtts",
            "edge_tts": "edge",
        }
        target_engine = _hint_to_engine.get(tts_hint)
        # Check if the target engine is actually registered and available
        _engine_attr = f"{target_engine}_engine" if target_engine else ""
        _engine_obj = getattr(engines, _engine_attr, None)
        if _engine_obj is not None and getattr(_engine_obj, "available", False):
            voice_info = dict(voice_info)
            voice_info["engine"] = target_engine
            log.debug("[%s] TTS engine hint applied: %s -> %s", session.session_id, tts_hint, target_engine)
        else:
            log.debug("[%s] TTS engine hint '%s' ignored — engine not available in registry, keeping '%s'",
                      session.session_id, tts_hint, voice_info.get("engine"))

    # ── Chunk-level streaming TTS synthesis for fast Time-To-First-Audio ───────
    from core.language_router import chunk_response_for_tts

    full_response = spoken_text or ""
    if spoken_text:
        # Send full text to frontend for display
        await websocket.send_text(json.dumps({
            "type": "llm_token",
            "session_id": session.session_id,
            "token": spoken_text,
            "is_final": True,
        }))
        await asyncio.sleep(0)

    chunks = chunk_response_for_tts(spoken_text) if spoken_text else []
    any_audio = False

    for idx, chunk in enumerate(chunks):
        # Check for pipeline cancellation between TTS sentences
        if session.pipeline_cancel and session.active_pipeline_id != pipeline_id:
            if full_response.strip():
                session.interrupted_response = full_response.strip()
                session.interrupted_query = transcript
            log.info("[%s] Pipeline %s cancelled mid-TTS. Saved %d chars of partial response.",
                     session.session_id, pipeline_id, len(full_response))
            break

        if not turn.is_active():
            log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | idx=%d | stage=voice_pre_tts",
                        turn.request_id, turn.turn_id, idx)
            break

        is_last = (idx == len(chunks) - 1)
        # DIAGNOSTICS: 5. Sentence detected, 6. TTS start, 8. Audio queued
        diagnostics.on_sentence_detected(req_id, idx, chunk)
        diagnostics.on_audio_queued(req_id, idx)
        _eng_diag = resolve_tts_engine(chunk, voice_info, settings.tts_engine_mode)
        diagnostics.on_tts_start(req_id, idx, _eng_diag)

        # Synthesize chunk (exact substring content and whitespace preserved)
        mp3_bytes = await _tts_generate(chunk, voice_info, detected_lang)

        # DIAGNOSTICS: 7. TTS generation completion
        diagnostics.on_tts_done(req_id, idx, mp3_bytes, session.session_id)

        if not turn.is_active():
            log.warning("[TURN] STALE_TTS_DISCARDED | req_id=%d | turn_id=%d | idx=%d | stage=voice_post_tts",
                        turn.request_id, turn.turn_id, idx)
            break

        if mp3_bytes:
            if not turn.is_active():
                log.warning("[TURN] STALE_AUDIO_DISCARDED | req_id=%d | turn_id=%d | idx=%d | stage=voice_pre_ws_send",
                            turn.request_id, turn.turn_id, idx)
                break
            any_audio = True
            await websocket.send_text(json.dumps({
                "type": "tts_audio",
                "session_id": session.session_id,
                "audio_b64": base64.b64encode(mp3_bytes).decode("ascii"),
                "is_final": is_last,
            }))
            # DIAGNOSTICS: 9. WebSocket tts_audio send
            diagnostics.on_ws_send(req_id, idx, mp3_bytes, session.session_id)

    # DIAGNOSTICS: 10. Request completion
    diagnostics.on_request_complete(req_id, total_chunks=len(chunks))

    if not any_audio and turn.is_active():
        # Send final empty frame to signal TTS complete if no audio was generated
        await websocket.send_text(json.dumps({
            "type": "tts_audio",
            "session_id": session.session_id,
            "audio_b64": "",
            "is_final": True,
        }))

    if not turn.is_active():
        log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=voice_end_stale",
                    turn.request_id, turn.turn_id)
        return

    turn_controller.complete_turn(session.session_id, turn.turn_id, stage="voice_complete")

    session.transcript_buffer += f"\nMJ: {full_response}"

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
            "[%s] TTS returned empty for all sentences — verify ChatTTS/F5-TTS engine availability "
            "and check voice_info engine type (current voice_id=%s).",
            session.session_id,
            session.voice_id or "default",
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
    # Check persistent user profile preference across sessions
    try:
        from engines.user_profile import user_profile
        saved_voice = user_profile.get_preference("selected_voice")
        if saved_voice and saved_voice in AVAILABLE_VOICES:
            session.voice_id = saved_voice
    except Exception:
        pass
    active_sessions[session_id] = session
    _session_websockets[session_id] = websocket  # For reminder background task

    log.info(
        "WS connected | user=%s | tier=%s | session=%s | voice=%s",
        user_id, tier, session_id, session.voice_id,
    )

    # Send session init — tells React which features to unlock
    # SECURITY: Only send tier + features, never internal IDs or secrets
    await websocket.send_text(json.dumps({
        "type":       "session_init",
        "session_id": session_id,
        "tier":       tier,
        "voice_id":   session.voice_id,
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

    # ── §13a  Auto-greeting — Alita speaks first (context-aware) ─────────
    if not session.greeted:
        session.greeted = True
        import base64 as _b64g
        import random as _rng
        from datetime import datetime as _dt_greet

        # ── 1. Gather personalization context (all zero-latency local lookups) ──
        _user_name = "there"
        _last_topic = None
        _is_returning = False

        try:
            from engines.episodic_memory import episodic_memory as _em
            _entities = _em.get_relevant_entities(user_id)
            for _ent in _entities:
                if _ent.get("entity_type") == "identity":
                    _user_name = _ent["entity_value"]
                    break
            _summary = _em.get_last_session_summary(user_id)
            if _summary:
                # Extract first topic (before the | separator), keep it short
                _last_topic = _summary.split("|")[0].strip()[:80]
        except Exception:
            pass  # Episodic memory not available — use defaults

        # ── 2. Detect language from voice preference ──
        _voice_id_greet = session.voice_id or DEFAULT_VOICE.get("en", _default_active_voice)
        _voice_info_greet = AVAILABLE_VOICES.get(_voice_id_greet, AVAILABLE_VOICES[_default_active_voice])
        _greet_lang = _voice_info_greet.get("lang", "en")

        # ── 3. Time-of-day aware greeting prefix ──
        _hour = _dt_greet.now().hour
        if _greet_lang == "hi":
            if _hour < 12:
                _time_greet = "सुप्रभात"
            elif _hour < 17:
                _time_greet = "नमस्ते"
            else:
                _time_greet = "शुभ संध्या"
        else:
            if _hour < 12:
                _time_greet = "Good morning"
            elif _hour < 17:
                _time_greet = "Good afternoon"
            else:
                _time_greet = "Good evening"

        # ── 4. Build contextual greeting (still template-based → zero LLM latency) ──
        if _greet_lang == "hi":
            if _is_returning and _last_topic:
                _greet_templates = [
                    f"{_time_greet}, {_user_name}! वापस आने पर खुशी हुई। पिछली बार हम \"{_last_topic}\" पर बात कर रहे थे — आगे बढ़ें?",
                    f"{_time_greet}, {_user_name}! मैं MJ हूँ। पिछली बार हमने \"{_last_topic}\" discuss किया था। कुछ और मदद चाहिए?",
                ]
            elif _is_returning:
                _greet_templates = [
                    f"{_time_greet}, {_user_name}! फिर से मिलकर अच्छा लगा। बताइए, क्या मदद करूँ?",
                    f"{_time_greet}, {_user_name}! वापस स्वागत है — बोलिए, मैं सुन रही हूँ।",
                ]
            else:
                _greet_templates = [
                    f"{_time_greet}! मैं MJ हूँ, आपकी personal assistant। बताइए, क्या मदद करूँ?",
                    f"{_time_greet}! MJ यहाँ — बोलिए, मैं सुन रही हूँ।",
                ]
        else:
            if _is_returning and _last_topic:
                _greet_templates = [
                    f"{_time_greet}, {_user_name}! Great to see you again. Last time we were discussing \"{_last_topic}\" — want to pick up where we left off?",
                    f"{_time_greet}, {_user_name}! Welcome back. I remember we talked about \"{_last_topic}\". How can I help today?",
                ]
            elif _is_returning:
                _greet_templates = [
                    f"{_time_greet}, {_user_name}! Welcome back — what's on your mind?",
                    f"{_time_greet}, {_user_name}! Good to see you again. How can I help?",
                ]
            else:
                _greet_templates = [
                    f"{_time_greet}! I'm MJ, your personal assistant. How can I help you today?",
                    f"{_time_greet}! MJ here — ready whenever you are.",
                    f"Hey {_user_name}! I'm MJ. What's on your mind?",
                ]

        greeting = _rng.choice(_greet_templates)

        # Send greeting text
        await websocket.send_text(json.dumps({
            "type": "llm_token",
            "session_id": session_id,
            "token": greeting,
            "is_final": True,
        }))

        # ── Send warm greeting face_data alongside the greeting text ──
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
                "tts_engine_hint": "chatterbox",
            },
        }))

        # TTS the greeting (language-aware)
        voice_id = session.voice_id or DEFAULT_VOICE.get(_greet_lang, _default_active_voice)
        voice_info = AVAILABLE_VOICES.get(voice_id, AVAILABLE_VOICES[_default_active_voice])
        mp3_bytes = await _tts_generate(greeting, voice_info, _greet_lang)
        if mp3_bytes:
            await websocket.send_text(json.dumps({
                "type": "tts_audio",
                "session_id": session_id,
                "audio_b64": _b64g.b64encode(mp3_bytes).decode("ascii"),
                "is_final": True,
            }))

        session.transcript_buffer += f"\nMJ: {greeting}"
        log.info("[%s] Auto-greeting sent (context-aware, lang=%s, returning=%s)", session_id, _greet_lang, _is_returning)

    # ── Audio accumulator (no server-side VAD — frontend handles it) ─────
    accumulated_pcm: list[float] = []

    # ── Detect session language for silence prompts ──────────────────────
    _session_voice_id = session.voice_id or DEFAULT_VOICE.get("en", _default_active_voice)
    _session_voice_info = AVAILABLE_VOICES.get(_session_voice_id, AVAILABLE_VOICES[_default_active_voice])
    _session_lang = _session_voice_info.get("lang", "en")

    # ── Message loop (with silence detection) ──────────────────────────────
    import random as _rng_loop
    SILENCE_TIMEOUT = 90  # seconds of silence before proactive prompt
    silence_prompts_en = [
        "Hey, you've been quiet for a while. Everything okay?",
        "Still here! Just let me know if you need anything.",
        "I'm here whenever you're ready to chat.",
    ]
    silence_prompts_hi = [
        "अरे, बहुत देर से चुप हो! सब ठीक है?",
        "मैं यहाँ हूँ, बताओ क्या चल रहा है?",
        "कुछ बोलो ना! मैं सुन रही हूँ।",
    ]
    last_activity = time.time()

    async def _send_silence_prompt():
        """Send a proactive prompt after silence (language-aware)."""
        _prompts = silence_prompts_hi if _session_lang == "hi" else silence_prompts_en
        prompt = _rng_loop.choice(_prompts)
        await websocket.send_text(json.dumps({
            "type": "llm_token",
            "session_id": session_id,
            "token": prompt,
            "is_final": True,
        }))
        # TTS the prompt (language-aware)
        voice_id = session.voice_id or DEFAULT_VOICE.get(_session_lang, _default_active_voice)
        voice_info = AVAILABLE_VOICES.get(voice_id, AVAILABLE_VOICES[_default_active_voice])
        mp3 = await _tts_generate(prompt, voice_info, _session_lang)
        if mp3:
            import base64 as _b64s
            await websocket.send_text(json.dumps({
                "type": "tts_audio",
                "session_id": session_id,
                "audio_b64": _b64s.b64encode(mp3).decode("ascii"),
                "is_final": True,
            }))
        session.transcript_buffer += f"\nMJ: {prompt}"
        log.info("[%s] Silence prompt sent (lang=%s)", session_id, _session_lang)

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

                    # ── Knowledge Graph — passively extract relational facts ──
                    try:
                        from engines.knowledge_graph import knowledge_graph
                        knowledge_graph.extract_and_store(transcript, user_id=user_id)
                    except Exception:
                        pass  # Non-critical — never block pipeline

                    # ── Context injection in offline STT path with decision_router ──
                    from decision_router import classify_query as _offline_classify  # type: ignore[import]
                    offline_qtype = _offline_classify(transcript)
                    log.info("[%s] [OFFLINE-STT] Query classified as: %s", session_id, offline_qtype)

                    from engines.llm_engine import build_alita_context as _offline_ctx, parse_alita_response as _offline_parse, generate_face_data as _offline_face  # type: ignore[import]
                    _offline_alita_ctx = _offline_ctx(transcript=transcript, handler_type=offline_qtype)

                    loop = asyncio.get_event_loop()
                    tokens, ws_meta = await loop.run_in_executor(
                        None, _llm_generate_sync, session, transcript, None, offline_qtype
                    )

                    # Forward any metadata messages (e.g. app not installed, start song recognition)
                    for meta_msg in (ws_meta or []):
                        mt = meta_msg.get("type", "")
                        if mt == "app_not_installed":
                            await websocket.send_text(json.dumps({
                                "type": "app_not_installed",
                                "app": meta_msg.get("app", ""),
                                "store_url": meta_msg.get("store_url", ""),
                            }))
                        elif mt == "start_song_recognition":
                            await websocket.send_text(json.dumps({"type": "start_song_recognition"}))

                    # Clean LLM response (strip any internal data leaks)
                    raw_offline_resp = " ".join(tokens) if tokens else ""
                    spoken_offline, _ = _offline_parse(raw_offline_resp)

                    # Generate face_data from SER emotion (NOT from LLM)
                    _off_emotion = getattr(session, '_last_emotion_label', 'neutral')
                    _off_conf = getattr(session, '_last_emotion_confidence', 0.5)
                    face_offline = _offline_face(user_emotion=_off_emotion, confidence=_off_conf)

                    # Inject girlfriend mood into offline face_data
                    if face_offline:
                        try:
                            from engines.relationship_manager import relationship_manager
                            _rel = relationship_manager.state
                            face_offline["girlfriend_mood"] = _rel.get("current_mood", "playful")
                            face_offline["mood_intensity"] = _rel.get("mood_intensity", 0.5)
                            face_offline["affection_score"] = _rel.get("affection_score", 75)
                            face_offline["lie_count_today"] = _rel.get("lie_count_today", 0)
                            face_offline["truth_count_today"] = _rel.get("truth_count_today", 0)
                        except Exception:
                            pass

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
                        voice_id_off = session.voice_id or DEFAULT_VOICE.get("en", _default_active_voice)
                        voice_info_off = AVAILABLE_VOICES.get(
                            voice_id_off,
                            AVAILABLE_VOICES[_default_active_voice]
                        )
                        # Apply tts_engine_hint from face_data only if engine is available
                        _off_hint = face_offline.get("tts_engine_hint", "") if face_offline else ""
                        if _off_hint:
                            _hint_map = {"chattts": "chattts", "f5": "f5", "f5_tts": "f5", "xtts_v2": "xtts", "edge_tts": "edge"}
                            _target = _hint_map.get(_off_hint)
                            _eng_obj = getattr(engines, f"{_target}_engine", None) if _target else None
                            if _eng_obj is not None and getattr(_eng_obj, "available", False):
                                voice_info_off = dict(voice_info_off)
                                voice_info_off["engine"] = _target
                                log.debug("[%s] Offline TTS hint applied: %s -> %s", session_id, _off_hint, _target)
                            else:
                                log.debug("[%s] Offline TTS hint '%s' ignored — keeping '%s'",
                                          session_id, _off_hint, voice_info_off.get("engine"))
                        detected_lang = _detect_language(transcript)
                        mp3 = await _tts_generate(full_resp, voice_info_off, detected_lang)
                        if mp3:
                            await websocket.send_text(json.dumps({
                                "type": "tts_audio",
                                "session_id": session_id,
                                "audio_b64": _b64off.b64encode(mp3).decode("ascii"),
                                "is_final": True,
                            }))
                        session.transcript_buffer += f"\nMJ: {full_resp}"
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

            # ── Dispatch modular control messages via ws_handler ─────────
            _ws_ctx = WsContext(
                websocket=websocket,
                session=session,
                session_id=session_id,
                user_id=user_id,
                tier=tier,
                active_sessions=active_sessions,
                available_voices=AVAILABLE_VOICES,
                default_active_voice=_default_active_voice,
                llm_generate_sync=_llm_generate_sync,
                tts_generate=_tts_generate,
                memory_store=memory_store,
            )
            if await dispatch_ws_message(msg_type, msg, _ws_ctx):
                continue

            # ── Text message (Web Speech API / keyboard) ──────────────────
            if msg_type == "text_message":
                text_input = msg.get("text", "").strip()
                if not text_input:
                    continue

                # ── DUPLICATE STT GATE & ACTIVE TURN INITIALIZATION ──────────
                from core.turn_controller import turn_controller
                turn = turn_controller.start_turn(session_id, text_input)
                if turn is None:
                    # Duplicate STT within conservative window (500-750ms) — discarded at gate
                    continue

                from core.diagnostics import diagnostics, resolve_tts_engine
                req_id = diagnostics.on_stt_received(session_id, text_input, req_id=turn.request_id)
                session.cancel_event = turn.cancel_event
                session.pipeline_cancel = False
                cmd_id = turn.turn_id

                # ── Check speculative cache first ─────────────────────────
                spec_hit = False
                from engines.speculative_engine import speculative_manager
                has_hit, spec_res, latency_saved = speculative_manager.check_cache_hit(session, text_input)
                if has_hit:
                    spec_hit = True
                    session._spec_result = spec_res
                    log.info(
                        "[%s] ⚡ SPECULATIVE HIT — using cached response (saved ~%.2fs latency)",
                        session_id, latency_saved
                    )

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
                    turn_controller.cancel_active_turn(session_id, stage="rate_limit")
                    continue

                loop = asyncio.get_event_loop()

                # Send user transcript back to frontend for display
                await websocket.send_text(json.dumps({
                    "type": "user_transcript",
                    "text": text_input,
                }))

                # Ensure session has cmd lock for persistence
                if not hasattr(session, '_cmd_lock'):
                    session._cmd_lock = asyncio.Lock()  # type: ignore[assignment]

                async def _handle_text_message(ws, sess, uid, sid, text, is_spec_hit, cid, turn_obj):
                    """Process a text query with progressive sequential TTS and active turn tracking."""
                    await _handle_text_message_inner(ws, sess, uid, sid, text, is_spec_hit, cid, turn_obj)

                async def _handle_text_message_inner(ws, sess, uid, sid, text, is_spec_hit, cid, turn_obj):
                    """Inner text message handler (runs without long-lived turn lock)."""
                    import base64 as _b64t
                    import queue as _queue
                    import re as _re_sent

                    r_id = turn_obj.request_id

                    # Sentence boundary regex — split on . ! ? but skip Dr. vs. etc.
                    _SENT_END = _re_sent.compile(
                        r'(?<![A-Z][a-z])(?<!\d)(?<!\.\.)([.!?])\s+|(\n)'
                    )

                    try:
                        if not turn_obj.is_active():
                            log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=entry",
                                        turn_obj.request_id, turn_obj.turn_id)
                            return

                        loop = asyncio.get_event_loop()
                        log.info("[%s] CMD #%d started: '%s'", sid, cid, text[:60])

                        # ── Resolve voice early ───────────────────────────────
                        detected_lang = _detect_language(text)
                        current_voice_id = sess.voice_id or DEFAULT_VOICE.get(detected_lang, _default_active_voice)
                        current_voice_info = AVAILABLE_VOICES.get(
                            current_voice_id,
                            AVAILABLE_VOICES[_default_active_voice]
                        )
                        current_lang = current_voice_info.get("lang", "en")

                        if not sess.manual_voice_override \
                           and detected_lang != current_lang \
                           and detected_lang in DEFAULT_VOICE:
                            new_voice_id = DEFAULT_VOICE[detected_lang]
                            new_voice_info = AVAILABLE_VOICES.get(new_voice_id, current_voice_info)
                            sess.voice_id = new_voice_id
                            log.info("CMD #%d auto-switched voice: %s → %s",
                                     cid, current_voice_info.get("name"), new_voice_info.get("name"))
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

                            diagnostics.on_llm_start(r_id)
                            diagnostics.on_first_token(r_id)
                            diagnostics.on_sentence_detected(r_id, 0, full_response)
                            diagnostics.on_audio_queued(r_id, 0)
                            _eng_diag = resolve_tts_engine(full_response, voice_info, settings.tts_engine_mode)
                            diagnostics.on_tts_start(r_id, 0, _eng_diag)

                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=spec_pre_send",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            # Send as one token
                            await ws.send_text(json.dumps({
                                "type": "llm_token", "session_id": sid,
                                "token": full_response, "cmd_id": cid, "is_final": True,
                            }))
                            # Single TTS
                            mp3 = await _tts_generate(full_response, voice_info, detected_lang)
                            diagnostics.on_tts_done(r_id, 0, mp3, sid)

                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_TTS_DISCARDED | req_id=%d | turn_id=%d | stage=spec_post_tts",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            if mp3:
                                if not turn_obj.is_active():
                                    log.warning("[TURN] STALE_AUDIO_DISCARDED | req_id=%d | turn_id=%d | stage=spec_pre_ws_send",
                                                turn_obj.request_id, turn_obj.turn_id)
                                    return
                                await ws.send_text(json.dumps({
                                    "type": "tts_audio", "session_id": sid, "cmd_id": cid,
                                    "sentence_idx": 0,
                                    "audio_b64": _b64t.b64encode(mp3).decode("ascii"),
                                    "is_final": True,
                                }))
                                diagnostics.on_ws_send(r_id, 0, mp3, sid)

                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=spec_history_save",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            async with sess._cmd_lock:  # type: ignore[attr-defined]
                                sess.transcript_buffer += f"\nUser: {text}\nMJ: {full_response}"
                                save_turn(user_id=uid, role="user", content=text, session_id=sid)
                                save_turn(user_id=uid, role="assistant", content=full_response, session_id=sid)
                                memory_store(uid, f"User said: {text}")
                                memory_store(uid, f"MJ said: {full_response}")
                                try:
                                    from engines.knowledge_graph import knowledge_graph
                                    knowledge_graph.extract_and_store(text, user_id=uid)
                                except Exception:
                                    pass
                            log.info("[%s] CMD #%d completed (speculative)", sid, cid)
                            turn_controller.complete_turn(sid, turn_obj.turn_id, stage="spec_complete")
                            diagnostics.on_request_complete(r_id, total_chunks=1)
                            return

                        # ── Classify query to decide: stream vs batch ─────────
                        sess._spec_result = None  # type: ignore[assignment]
                        sess._spec_text = ""  # type: ignore[assignment]

                        from decision_router import classify_query  # type: ignore[import]
                        query_type = classify_query(text)

                        # Realtime + automation → batch (short responses)
                        if query_type in ("realtime", "automation"):
                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=batch_pre_llm",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            diagnostics.on_llm_start(r_id)
                            tokens_list, ws_metadata = await loop.run_in_executor(
                                None, _llm_generate_sync, sess, text, turn_obj.cancel_event, query_type
                            )

                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=batch_post_llm",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            diagnostics.on_first_token(r_id)
                            full_response = ""
                            for i, tok in enumerate(tokens_list):
                                if not turn_obj.is_active():
                                    log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=batch_tokens",
                                                turn_obj.request_id, turn_obj.turn_id)
                                    return
                                full_response += tok
                                await ws.send_text(json.dumps({
                                    "type": "llm_token", "session_id": sid,
                                    "token": tok, "cmd_id": cid,
                                    "is_final": (i == len(tokens_list) - 1),
                                }))
                                await asyncio.sleep(0)

                            diagnostics.on_sentence_detected(r_id, 0, full_response)
                            diagnostics.on_audio_queued(r_id, 0)
                            _eng_diag = resolve_tts_engine(full_response, voice_info, settings.tts_engine_mode)
                            diagnostics.on_tts_start(r_id, 0, _eng_diag)

                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=batch_pre_tts",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            # Single TTS for short response
                            mp3 = await _tts_generate(full_response, voice_info, detected_lang)
                            diagnostics.on_tts_done(r_id, 0, mp3, sid)

                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_TTS_DISCARDED | req_id=%d | turn_id=%d | stage=batch_post_tts",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            if mp3:
                                if not turn_obj.is_active():
                                    log.warning("[TURN] STALE_AUDIO_DISCARDED | req_id=%d | turn_id=%d | stage=batch_pre_ws_send",
                                                turn_obj.request_id, turn_obj.turn_id)
                                    return
                                await ws.send_text(json.dumps({
                                    "type": "tts_audio", "session_id": sid, "cmd_id": cid,
                                    "sentence_idx": 0,
                                    "audio_b64": _b64t.b64encode(mp3).decode("ascii"),
                                    "is_final": True,
                                }))
                                diagnostics.on_ws_send(r_id, 0, mp3, sid)

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

                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=batch_history_save",
                                            turn_obj.request_id, turn_obj.turn_id)
                                return

                            async with sess._cmd_lock:  # type: ignore[attr-defined]
                                sess.transcript_buffer += f"\nUser: {text}\nMJ: {full_response}"
                                save_turn(user_id=uid, role="user", content=text, session_id=sid)
                                save_turn(user_id=uid, role="assistant", content=full_response, session_id=sid)
                                memory_store(uid, f"User said: {text}")
                                memory_store(uid, f"MJ said: {full_response}")
                                try:
                                    from engines.knowledge_graph import knowledge_graph
                                    knowledge_graph.extract_and_store(text, user_id=uid)
                                except Exception:
                                    pass

                            if getattr(sess, 'dictation_active', False):
                                await ws.send_text(json.dumps({
                                    "type": "dictation_start",
                                    "app": getattr(sess, 'dictation_app', ''),
                                }))

                            log.info("[%s] CMD #%d completed (batch/%s): %d chars", sid, cid, query_type, len(full_response))
                            turn_controller.complete_turn(sid, turn_obj.turn_id, stage="batch_complete")
                            diagnostics.on_request_complete(r_id, total_chunks=1)
                            return

                        # ──────────────────────────────────────────────────────
                        # GENERAL → TRUE STREAMING + SENTENCE TTS PIPELINE
                        # ──────────────────────────────────────────────────────
                        from threads.general_handler import handle_general_stream  # type: ignore[import]

                        if not turn_obj.is_active():
                            log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=stream_pre_llm",
                                        turn_obj.request_id, turn_obj.turn_id)
                            return

                        diagnostics.on_llm_start(r_id)
                        token_q: _queue.Queue = _queue.Queue()
                        system_prompt = _build_system_prompt(sess, user_text=text)
                        max_history = 15 if sess.tier == "premium" else 5
                        history = _build_history(sess, max_history)

                        # Start LLM streaming in a background thread with cancel_event
                        loop.run_in_executor(
                            None,
                            handle_general_stream,
                            text, sess, settings, system_prompt, history,
                            settings.llm_max_tokens if sess.tier == "premium" else settings.llm_max_tokens_free,
                            response_cache, token_q, turn_obj.cancel_event,
                        )

                        # ── Sentence queue for progressive sequential TTS ─────
                        sentence_q: asyncio.Queue = asyncio.Queue()
                        full_response = ""
                        sentence_buffer = ""
                        sentence_idx = 0

                        async def _process_sequential_tts():
                            """Synthesize sentences sequentially in arrival order without parallel engine contention."""
                            nonlocal sentence_idx
                            while True:
                                if not turn_obj.is_active():
                                    log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=tts_queue_stale",
                                                turn_obj.request_id, turn_obj.turn_id)
                                    break
                                try:
                                    item = await asyncio.wait_for(sentence_q.get(), timeout=0.1)
                                except asyncio.TimeoutError:
                                    continue

                                if item is None:
                                    break

                                s_text, s_idx = item
                                if not turn_obj.is_active():
                                    log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | idx=%d | stage=pre_tts",
                                                turn_obj.request_id, turn_obj.turn_id, s_idx)
                                    break

                                _eng_diag = resolve_tts_engine(s_text, voice_info, settings.tts_engine_mode)
                                diagnostics.on_tts_start(r_id, s_idx, _eng_diag)

                                # Synchronous TTS call in threadpool (returns naturally)
                                mp3 = await _tts_generate(s_text, voice_info, detected_lang)
                                diagnostics.on_tts_done(r_id, s_idx, mp3, sid)

                                if not turn_obj.is_active():
                                    log.warning("[TURN] STALE_TTS_DISCARDED | req_id=%d | turn_id=%d | idx=%d | stage=post_tts",
                                                turn_obj.request_id, turn_obj.turn_id, s_idx)
                                    break

                                if mp3:
                                    if not turn_obj.is_active():
                                        log.warning("[TURN] STALE_AUDIO_DISCARDED | req_id=%d | turn_id=%d | idx=%d | stage=pre_ws_send",
                                                    turn_obj.request_id, turn_obj.turn_id, s_idx)
                                        break
                                    await ws.send_text(json.dumps({
                                        "type": "tts_audio",
                                        "session_id": sid,
                                        "cmd_id": cid,
                                        "sentence_idx": s_idx,
                                        "audio_b64": _b64t.b64encode(mp3).decode("ascii"),
                                        "is_final": False,
                                    }))
                                    diagnostics.on_ws_send(r_id, s_idx, mp3, sid)

                        tts_worker = asyncio.create_task(_process_sequential_tts())

                        while True:
                            if not turn_obj.is_active():
                                log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=stream_tokens_stale",
                                            turn_obj.request_id, turn_obj.turn_id)
                                break

                            # Poll queue — non-blocking get_nowait avoiding threadpool scheduling overhead
                            try:
                                token = token_q.get_nowait()
                            except _queue.Empty:
                                await asyncio.sleep(0.005)
                                continue

                            if token is None:
                                # Stream complete — flush remaining sentence buffer
                                break

                            # Send token to frontend immediately
                            diagnostics.on_first_token(r_id)
                            full_response += token  # type: ignore[operator]
                            sentence_buffer += token  # type: ignore[operator]

                            if turn_obj.is_active():
                                await ws.send_text(json.dumps({
                                    "type": "llm_token",
                                    "session_id": sid,
                                    "token": token,
                                    "cmd_id": cid,
                                    "is_final": False,
                                }))

                            # Check for sentence boundary (require min length to prevent micro-chunk starvation)
                            if _SENT_END.search(sentence_buffer):  # type: ignore[union-attr]
                                parts = _SENT_END.split(sentence_buffer)  # type: ignore[union-attr]
                                complete = ""
                                remainder = ""
                                for j, p in enumerate(parts):
                                    if p is None:
                                        continue
                                    if j < len(parts) - 1:
                                        complete += p  # type: ignore[operator]
                                    else:
                                        remainder = p

                                # Only dispatch early if the complete chunk is substantial enough (>= 45 chars or >= 7 words)
                                # This ensures the synthesized audio is long enough (~3-5s) so the next chunk has time to generate
                                if len(complete.strip()) >= 45 or len(complete.strip().split()) >= 7:
                                    diagnostics.on_sentence_detected(r_id, sentence_idx, complete.strip())
                                    diagnostics.on_audio_queued(r_id, sentence_idx)
                                    await sentence_q.put((complete.strip(), sentence_idx))
                                    sentence_idx += 1
                                    sentence_buffer = remainder

                        # ── Flush final sentence buffer ───────────────────────
                        if sentence_buffer.strip() and turn_obj.is_active():  # type: ignore[union-attr]
                            diagnostics.on_sentence_detected(r_id, sentence_idx, sentence_buffer.strip())
                            diagnostics.on_audio_queued(r_id, sentence_idx)
                            await sentence_q.put((sentence_buffer.strip(), sentence_idx))
                            sentence_idx += 1

                        # Sentinel to signal completion of sentences
                        await sentence_q.put(None)

                        # Send final llm_token marker
                        await ws.send_text(json.dumps({
                            "type": "llm_token",
                            "session_id": sid,
                            "token": "",
                            "cmd_id": cid,
                            "is_final": True,
                        }))

                        # Wait for sequential TTS worker to finish
                        await tts_worker

                        # If turn is no longer active, abort here — no final audio marker, no history save
                        if not turn_obj.is_active():
                            log.warning("[TURN] STALE_RESULT_DISCARDED | req_id=%d | turn_id=%d | stage=stream_end_stale",
                                        turn_obj.request_id, turn_obj.turn_id)
                            return

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
                            sess.transcript_buffer += f"\nUser: {text}\nMJ: {full_response}"
                            save_turn(user_id=uid, role="user", content=text, session_id=sid)
                            save_turn(user_id=uid, role="assistant", content=full_response, session_id=sid)
                            memory_store(uid, f"User said: {text}")
                            memory_store(uid, f"MJ said: {full_response}")
                            try:
                                from engines.knowledge_graph import knowledge_graph
                                knowledge_graph.extract_and_store(text, user_id=uid)
                            except Exception:
                                pass

                        if getattr(sess, 'dictation_active', False):
                            await ws.send_text(json.dumps({
                                "type": "dictation_start",
                                "app": getattr(sess, 'dictation_app', ''),
                            }))

                        log.info("[%s] CMD #%d completed (stream): %d chars, %d sentences",
                                 sid, cid, len(full_response), sentence_idx)
                        turn_controller.complete_turn(sid, turn_obj.turn_id, stage="stream_complete")
                        diagnostics.on_request_complete(r_id, total_chunks=sentence_idx)

                    except Exception as e:
                        log.error("[%s] CMD #%d error: %s", sid, cid, e, exc_info=True)

                asyncio.create_task(
                    _handle_text_message(websocket, session, user_id, session_id, text_input, spec_hit, cmd_id, turn)
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
                        voice_id_sr = getattr(session, "voice_id", None) or _default_active_voice
                        voice_info = AVAILABLE_VOICES.get(
                            voice_id_sr,
                            AVAILABLE_VOICES[_default_active_voice]
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
        from core.turn_controller import turn_controller
        turn_controller.cancel_active_turn(session_id, stage="disconnect")
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

# CheckoutRequest imported from schemas.models


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
            "name": "MJ Premium",
            "description": f"MJ Premium — {'Monthly' if req.plan == 'monthly' else 'Annual'} Subscription",
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
# Voice listing & preferences are routed via voice_router


@app.get("/api/voice/mood")
async def get_voice_mood():
    """Returns available emotional mood presets and the currently active mood."""
    from engines.tts_chattts import MOOD_PRESETS
    from engines.user_profile import user_profile
    active_mood = user_profile.get_preference("selected_mood", "affectionate")
    return {
        "active_mood": active_mood,
        "moods": list(MOOD_PRESETS.values()),
    }


@app.post("/api/voice/mood")
async def set_voice_mood(request: Request):
    """Update the active emotional mood preset for MJ."""
    from engines.tts_chattts import MOOD_PRESETS
    from engines.user_profile import user_profile
    data = await request.json()
    mood_key = data.get("mood", "").lower().strip()
    if mood_key not in MOOD_PRESETS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mood '{mood_key}'. Valid options: {list(MOOD_PRESETS.keys())}",
        )

    user_profile.set_preference("selected_mood", mood_key)

    return {
        "success": True,
        "active_mood": mood_key,
        "preset": MOOD_PRESETS[mood_key],
    }


# Voice uploads, deletion, languages & preferences are routed via voice_router


# ─────────────────────────────────────────────────────────────────────────────
# §16  CHROMADB SEMANTIC MEMORY — Long-term user memory
# ─────────────────────────────────────────────────────────────────────────────
def memory_store(user_id: str, text: str, metadata: Optional[Dict[str, Any]] = None):
    """Store a memory in ChromaDB for long-term recall and record for periodic summarization."""
    # Gap 6: Record interaction for conversation memory summarization
    try:
        from engines.memory_summarizer import memory_summarizer
        from engines.knowledge_graph import knowledge_graph
        memory_summarizer.knowledge_graph = knowledge_graph
        memory_summarizer.record_interaction(user_id, text)
        if memory_summarizer.get_unsummarized_count(user_id) >= memory_summarizer.threshold:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(memory_summarizer.maybe_summarize(user_id))
            except RuntimeError:
                pass
    except Exception as sum_err:
        log.debug("Memory summarizer record failed: %s", sum_err)

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


# ─────────────────────────────────────────────────────────────────────────────
# §16  ADMIN TRAINING EXPORT
# ─────────────────────────────────────────────────────────────────────────────
# /admin/export-training-data is mounted via system_router (routers/system_router.py)


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
