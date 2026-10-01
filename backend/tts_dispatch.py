"""
MJ TTS Dispatch — Chatterbox Turbo Only
========================================
Single-engine speech synthesis. All text routes to Chatterbox Turbo.
No fallback engines. No language routing.
"""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from core.text_utils import clean_text_for_tts, _clean_text_for_tts

log = logging.getLogger("alita.tts_dispatch")

# Dedicated single-thread executor to prevent CPU starvation and thread pool contention
_tts_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mj_tts")


def get_or_load_turbo_engine():
    """Load or retrieve singleton Chatterbox Turbo engine."""
    from main import engines, settings
    if engines.chatterbox_turbo_engine is None:
        try:
            from engines.resource_guard import resource_guard
            with resource_guard.loading("ChatterboxTurbo", estimated_mb=800):
                from engines.tts_chatterbox_turbo import ChatterboxTurboEngine
                log.info("Loading Chatterbox-Turbo engine on %s...", settings.device)
                engines.chatterbox_turbo_engine = ChatterboxTurboEngine(device=settings.device)
                if engines.chatterbox_turbo_engine.available:
                    log.info("✓ Chatterbox-Turbo engine loaded successfully")
                else:
                    log.error("✗ Chatterbox-Turbo engine failed to initialize")
                    engines.chatterbox_turbo_engine = None
        except Exception as exc:
            log.error("Failed to load Chatterbox-Turbo: %s", exc, exc_info=True)
            engines.chatterbox_turbo_engine = None
    return engines.chatterbox_turbo_engine


def get_or_load_multilingual_engine():
    """Legacy stub — Multilingual engine removed. Returns None."""
    return None


async def _tts_generate(text: str, voice_info: dict, language: str = "en") -> bytes:
    """
    Single-engine TTS dispatcher — Chatterbox Turbo only.
    No fallback. Returns b"" on failure.
    """
    if not text or not text.strip():
        return b""

    from main import engines

    t0 = time.perf_counter()
    voice_id = voice_info.get("id", voice_info.get("name", "chatterbox_turbo_mj"))

    # Clean text (preserve [laugh], [sigh], [cough] — Turbo supports them natively)
    cleaned = _clean_text_for_tts(text, preserve_oral_tags=True)
    if not cleaned or not cleaned.strip():
        return b""

    # Ensure engine is loaded
    engine = engines.chatterbox_turbo_engine
    if engine is None:
        engine = get_or_load_turbo_engine()

    if engine is None or not engine.available:
        log.error("TTS FAILED: Chatterbox-Turbo engine is not available | text='%s'", text[:40])
        return b""

    # Generate speech on isolated thread executor
    loop = asyncio.get_event_loop()
    try:
        wav_bytes = await loop.run_in_executor(
            _tts_executor, engine.generate, cleaned.strip()
        )
        elapsed = time.perf_counter() - t0

        if wav_bytes:
            log.info(
                "TTS OK | engine=chatterbox_turbo | voice=%s | duration=%.3fs | bytes=%d | text='%s'",
                voice_id, elapsed, len(wav_bytes), text[:40]
            )
            return wav_bytes
        else:
            log.error("TTS EMPTY: Chatterbox-Turbo returned empty audio | text='%s'", text[:40])
            return b""

    except Exception as exc:
        log.error("TTS ERROR: Chatterbox-Turbo generation failed: %s | text='%s'", exc, text[:40])
        return b""
