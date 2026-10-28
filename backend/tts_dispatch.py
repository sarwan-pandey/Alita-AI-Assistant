"""
MJ TTS Dispatch — Chatterbox Turbo Only
========================================
Single-engine speech synthesis. All text routes to Chatterbox Turbo.
No fallback engines. No language routing.
"""

from __future__ import annotations

import io
import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import soundfile as sf

from core.text_utils import clean_text_for_tts, _clean_text_for_tts
from core.chunk_utils import chunk_text_hard_safety, OPERATIONAL_HARD_LIMIT, ABSOLUTE_SAFETY_LIMIT

log = logging.getLogger("alita.tts_dispatch")

# Dedicated single-thread executor to prevent CPU starvation and thread pool contention
_tts_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mj_tts")


def get_or_load_turbo_engine():
    """Load or retrieve singleton Chatterbox Turbo engine via provider orchestrator."""
    from engines.provider_orchestrator import get_provider_orchestrator
    return get_provider_orchestrator().get_tts_engine()


def get_or_load_multilingual_engine():
    """Legacy stub — Multilingual engine removed. Returns None."""
    return None


async def _tts_generate(text: str, voice_info: dict, language: str = "en") -> bytes:
    """
    Single-engine TTS dispatcher — Chatterbox Turbo only.
    Enforces Phase 6D chunk safety: guarantees NO synthesis chunk > 90 characters.
    Transparently synthesizes and combines multi-chunk inputs into seamless 16-bit PCM WAV.
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

    # Check if primary TTS provider (Chatterbox Multilingual) via provider orchestrator is enabled and ready
    try:
        from engines.provider_orchestrator import get_provider_orchestrator
        orch = get_provider_orchestrator()
        if orch.is_provider_ready("tts", "chatterbox_multilingual"):
            primary_wav = await orch.synthesize(clean_str, voice=voice_id, language=language)
            if primary_wav and len(primary_wav) > 44:
                return primary_wav
    except Exception as orch_err:
        log.warning("[tts_dispatch] Orchestrator synthesis error: %s. Falling back to local engine.", orch_err)

    # Ensure engine is loaded
    engine = engines.chatterbox_turbo_engine
    if engine is None:
        engine = get_or_load_turbo_engine()

    if engine is None or not engine.available:
        log.error("TTS FAILED: Chatterbox-Turbo engine is not available | text='%s'", text[:40])
        return b""

    clean_str = cleaned.strip()
    loop = asyncio.get_event_loop()

    # Enforce Phase 6D hard chunking: if text exceeds operational limit, slice into safe sub-chunks
    if len(clean_str) <= OPERATIONAL_HARD_LIMIT:
        chunks = [clean_str]
    else:
        chunks = chunk_text_hard_safety(
            clean_str,
            hard_limit=OPERATIONAL_HARD_LIMIT,
            absolute_limit=ABSOLUTE_SAFETY_LIMIT,
        )

    try:
        if len(chunks) == 1:
            wav_bytes = await loop.run_in_executor(
                _tts_executor, engine.generate, chunks[0]
            )
        else:
            # Sequential synthesis with zero-crash buffer concatenation
            audio_segments = []
            sr = getattr(engine, "_sample_rate", 24000)
            for c_idx, chunk_item in enumerate(chunks):
                c_bytes = await loop.run_in_executor(
                    _tts_executor, engine.generate, chunk_item
                )
                if c_bytes:
                    data, file_sr = sf.read(io.BytesIO(c_bytes))
                    audio_segments.append(data)
                    sr = file_sr

            if not audio_segments:
                log.error("TTS EMPTY: Chatterbox-Turbo multi-chunk generated no audio | chunks=%d", len(chunks))
                return b""

            combined = np.concatenate(audio_segments)
            buf = io.BytesIO()
            sf.write(buf, combined, sr, format="WAV", subtype="PCM_16")
            wav_bytes = buf.getvalue()

        elapsed = time.perf_counter() - t0

        if wav_bytes:
            log.info(
                "TTS OK | engine=chatterbox_turbo | chunks=%d | voice=%s | duration=%.3fs | bytes=%d | text='%s'",
                len(chunks), voice_id, elapsed, len(wav_bytes), text[:40]
            )
            return wav_bytes
        else:
            log.error("TTS EMPTY: Chatterbox-Turbo returned empty audio | text='%s'", text[:40])
            return b""

    except Exception as exc:
        log.error("TTS ERROR: Chatterbox-Turbo generation failed: %s | text='%s'", exc, text[:40])
        return b""
