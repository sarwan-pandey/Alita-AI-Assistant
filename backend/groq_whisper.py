"""
Groq Whisper STT — Accurate speech-to-text via Groq's Whisper API.

Uses the same key rotation pool as the LLM calls (groq_pool.py).
Model: whisper-large-v3-turbo (fastest, most accurate).
Fallback: local faster-whisper medium (when Groq is unavailable).

Usage:
    from groq_whisper import transcribe_audio_b64
    transcript = await transcribe_audio_b64(audio_b64, language="en")
"""

import base64
import io
import logging
import os
import asyncio
import time
import numpy as np
from concurrent.futures import ThreadPoolExecutor

log = logging.getLogger("alita.groq_whisper")

# Dedicated thread pool for blocking API/model calls
_whisper_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="groq-whisper")

# Supported input formats for Groq Whisper
_SUPPORTED_FORMATS = {"flac", "mp3", "mp4", "mpeg", "mpga", "m4a", "ogg", "wav", "webm"}


# ── Local faster-whisper fallback ──────────────────────────────────────────
def _get_local_whisper_model():
    """Get the local faster-whisper model from the engines singleton."""
    try:
        import main as _main  # type: ignore[import]
        model = getattr(_main.engines, 'whisper_model', None)
        if model is not None:
            return model
    except Exception:
        pass
    return None


def _webm_to_pcm(audio_bytes: bytes) -> np.ndarray:
    """Convert WebM/Ogg audio bytes to float32 PCM array for faster-whisper."""
    import subprocess
    import tempfile

    # Write audio to a temp file
    with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
        tmp_in.write(audio_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".webm", ".wav")

    try:
        # Use ffmpeg to convert to 16kHz mono WAV
        result = subprocess.run(
            ["ffmpeg", "-i", tmp_in_path, "-ar", "16000", "-ac", "1",
             "-f", "wav", "-y", tmp_out_path],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            log.warning("[Whisper Local] ffmpeg conversion failed: %s",
                       result.stderr.decode()[:200])
            return np.array([], dtype=np.float32)

        # Read WAV and convert to float32 array
        import wave
        with wave.open(tmp_out_path, 'rb') as wf:
            frames = wf.readframes(wf.getnframes())
            pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            return pcm
    except FileNotFoundError:
        log.warning("[Whisper Local] ffmpeg not found, cannot convert audio")
        return np.array([], dtype=np.float32)
    except Exception as e:
        log.error("[Whisper Local] Audio conversion failed: %s", e)
        return np.array([], dtype=np.float32)
    finally:
        try:
            os.unlink(tmp_in_path)
        except OSError:
            pass
        try:
            os.unlink(tmp_out_path)
        except OSError:
            pass


def _transcribe_local(audio_bytes: bytes, language: str = "en") -> str:
    """Fallback: transcribe using local faster-whisper model."""
    model = _get_local_whisper_model()
    if model is None:
        log.warning("[Whisper Local] No local model available")
        return ""

    start_t = time.time()
    pcm = _webm_to_pcm(audio_bytes)
    if len(pcm) < 1600:  # Less than 0.1s of audio
        log.warning("[Whisper Local] Audio too short after conversion")
        return ""

    try:
        segments, info = model.transcribe(
            pcm,
            beam_size=1,
            vad_filter=True,
            language=language if language != "en-IN" else None,
            vad_parameters=dict(
                min_silence_duration_ms=500,
                speech_pad_ms=150,
            ),
        )
        text = " ".join(seg.text.strip() for seg in segments).strip()
        elapsed = time.time() - start_t
        log.info("[Whisper Local] Transcribed in %.1fs: '%s'", elapsed, text[:80])
        return text
    except Exception as exc:
        log.error("[Whisper Local] Transcription failed: %s", exc)
        return ""


# ── Groq Whisper API (primary) ─────────────────────────────────────────────
def _transcribe_groq(audio_bytes: bytes, language: str = "en", filename: str = "audio.webm") -> str:
    """
    Blocking call to Groq Whisper API. Runs in thread pool.

    Args:
        audio_bytes: Raw audio file bytes (WebM, WAV, etc.)
        language:    ISO language code (e.g. "en", "hi", "es")
        filename:    Filename hint for format detection

    Returns:
        Transcribed text string, or empty string on failure.
    """
    from groq_pool import get_rotator  # type: ignore[import]

    rotator = get_rotator()
    if not rotator.available:
        log.warning("[Whisper Groq] No API keys available — falling back to local")
        return ""

    # Try up to 3 keys (in case of rate limits)
    last_error = None
    for attempt in range(min(3, len(rotator.keys))):
        api_key = rotator.get_key()
        if not api_key:
            break

        try:
            from groq import Groq  # type: ignore[import-untyped]

            client = Groq(api_key=api_key)

            # Groq Whisper API expects a file-like object with a name
            audio_file = io.BytesIO(audio_bytes)
            audio_file.name = filename  # type: ignore[attr-defined]

            transcription = client.audio.transcriptions.create(
                file=audio_file,
                model="whisper-large-v3-turbo",
                language=language,
                response_format="text",
                temperature=0.0,  # Deterministic output
            )

            result = str(transcription).strip()
            if result:
                log.info("[Whisper Groq] Transcribed (%d bytes → %d chars): '%s'",
                         len(audio_bytes), len(result), result[:80])
                return result
            else:
                log.warning("[Whisper Groq] Empty transcription result")
                return ""

        except Exception as exc:
            last_error = exc
            exc_str = str(exc).lower()

            if "rate_limit" in exc_str or "429" in exc_str:
                rotator.mark_rate_limited(api_key, 30)
                log.warning("[Whisper Groq] Key ...%s rate-limited, rotating (attempt %d)",
                           api_key[-8:], attempt + 1)
                continue

            log.error("[Whisper Groq] Failed (attempt %d): %s", attempt + 1, exc)
            break

    if last_error:
        log.error("[Whisper Groq] All attempts failed: %s", last_error)
    return ""


# ── Main entry point ───────────────────────────────────────────────────────
def _transcribe_with_fallback(audio_bytes: bytes, language: str = "en") -> str:
    """
    Try Groq Whisper API first, fall back to local faster-whisper if it fails.
    """
    # Primary: Groq Whisper API (fast, accurate, free)
    result = _transcribe_groq(audio_bytes, language=language)
    if result:
        return result

    # Fallback: local faster-whisper (offline, no rate limits)
    log.info("[Whisper] Groq failed — trying local faster-whisper fallback")
    result = _transcribe_local(audio_bytes, language=language)
    if result:
        return result

    log.warning("[Whisper] Both Groq and local transcription failed")
    return ""


async def transcribe_audio_b64(audio_b64: str, language: str = "en") -> str:
    """
    Async wrapper: decode base64 audio and transcribe.
    Tries Groq Whisper API first, falls back to local faster-whisper.

    Args:
        audio_b64: Base64-encoded audio (WebM from MediaRecorder)
        language:  ISO language code

    Returns:
        Transcribed text, or empty string on failure.
    """
    if not audio_b64:
        return ""

    try:
        audio_bytes = base64.b64decode(audio_b64)
    except Exception as e:
        log.error("[Whisper] Invalid base64 audio: %s", e)
        return ""

    if len(audio_bytes) < 100:
        log.warning("[Whisper] Audio too short (%d bytes), skipping", len(audio_bytes))
        return ""

    log.info("[Whisper] Processing %.1f KB audio...", len(audio_bytes) / 1024)

    # Run in thread pool (both Groq API and local model are blocking)
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        _whisper_pool,
        _transcribe_with_fallback,
        audio_bytes,
        language,
    )

    return result
