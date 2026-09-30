"""
Core Audio Pipeline — ChatTTS/F5-TTS Dispatch, Instant Backchanneling & Speech Rate Adaptation
==============================================================================================
Routes speech generation between ChatTTS (conversational neural) and F5-TTS (diffusion voice clone).
Provides instant micro-filler caching (<50ms) and dynamic rate adjustment based on user cadence.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("alita.audio_pipeline")

# ── Instant Thinking Backchannels & Audio Cache ───────────────────────────
_FILLER_PHRASES: Dict[str, List[str]] = {
    "en": [
        "Hmm, let me look into that...",
        "Got it, checking that now...",
        "Let me see...",
        "Looking into that for you...",
    ],
    "hi": [
        "Haan, ek second dekh rahi hoon...",
        "Theek hai, abhi batati hoon...",
        "Achha, dekh rahi hoon...",
    ],
}

_FILLER_AUDIO_CACHE: Dict[Tuple[str, str], bytes] = {}
_ACTIVE_SYNTHESIS_TASKS: Dict[str, asyncio.Task] = {}


def calculate_speech_rate(user_transcript: str, audio_duration_s: float) -> float:
    """
    Dynamically estimates user speaking cadence (words per second).
    Returns speed multiplier: 1.15x for fast/urgent requests, 1.0x for standard.
    """
    if not user_transcript or audio_duration_s <= 0.2:
        return 1.0

    words = len(user_transcript.strip().split())
    wps = words / max(0.5, audio_duration_s)

    if wps > 3.2:
        return 1.15
    elif wps < 1.8:
        return 0.95
    return 1.0
from core.text_utils import clean_text_for_tts, _clean_text_for_tts, preprocess_text_for_tts


async def tts_generate(
    text: str,
    voice_info: Dict[str, Any],
    language: str = "en",
    speed: float = 1.0,
    engines_container: Optional[Any] = None,
) -> bytes:
    """
    Core TTS generation entrypoint — delegates directly to the primary _tts_generate dispatcher.
    """
    if not text or not text.strip():
        return b""
    try:
        import main as _main_mod
        return await _main_mod._tts_generate(text, voice_info, language)
    except Exception as exc:
        log.exception("audio_pipeline.tts_generate delegation failed: %s", exc)
        return b""


async def get_or_synthesize_filler(
    filler_text: str,
    voice_info: Dict[str, Any],
    language: str,
    engines_container: Optional[Any] = None,
) -> bytes:
    """Retrieve pre-warmed audio filler or synthesize in <80ms."""
    voice_name = voice_info.get("name", voice_info.get("engine", "default"))
    key = (voice_name, filler_text)
    if key in _FILLER_AUDIO_CACHE:
        return _FILLER_AUDIO_CACHE[key]

    audio_bytes = await tts_generate(filler_text, voice_info, language, engines_container=engines_container)
    if audio_bytes:
        _FILLER_AUDIO_CACHE[key] = audio_bytes
    return audio_bytes


def cancel_active_synthesis(session_id: str) -> bool:
    """Abort any in-flight synthesis task for this session."""
    task = _ACTIVE_SYNTHESIS_TASKS.pop(session_id, None)
    if task and not task.done():
        task.cancel()
        log.info("[AudioPipeline] Cancelled in-flight synthesis for session: %s", session_id)
        return True
    return False


# Backward compatibility aliases
_get_or_synthesize_filler = get_or_synthesize_filler
_tts_generate = tts_generate
