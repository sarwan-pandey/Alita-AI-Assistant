"""
WhisperStreamProcessor — Offline streaming STT using faster-whisper.

Designed for barge-in support when the user is offline (no Web Speech API).
Accumulates PCM audio chunks, detects speech boundaries using energy-based VAD,
and transcribes complete utterances using the already-loaded faster-whisper model.

Architecture:
  ┌─────────────┐     ┌─────────────┐     ┌──────────────┐
  │ PCM chunks  │ ──▶ │ Ring Buffer │ ──▶ │ VAD + Whisper │ ──▶ transcript
  │ (from WS)   │     │ (30s window) │     │ (on endpoint) │
  └─────────────┘     └─────────────┘     └──────────────┘

Usage:
    processor = WhisperStreamProcessor(whisper_model)
    processor.feed(pcm_chunk)         # call repeatedly with audio
    result = processor.poll()          # returns transcript or None
    processor.reset()                  # clear buffers for new utterance
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from typing import Optional

import numpy as np  # type: ignore[import]

try:
    import onnxruntime as ort  # type: ignore[import]
    _ONNX_AVAILABLE = True
except ImportError:
    _ONNX_AVAILABLE = False

log = logging.getLogger("whisper_stream")

# ── Configuration ─────────────────────────────────────────────────────────────
SAMPLE_RATE = 16000                   # 16 kHz mono
RING_BUFFER_SECONDS = 30              # max audio history
RING_BUFFER_SAMPLES = SAMPLE_RATE * RING_BUFFER_SECONDS

# Energy-based VAD thresholds (used as pre-filter for Silero)
SPEECH_RMS_THRESHOLD = 0.012          # RMS above this → run Silero check
SILENCE_RMS_THRESHOLD = 0.006         # RMS below this = definitely silence
SPEECH_MIN_DURATION_MS = 250          # ignore speech shorter than this
SILENCE_ENDPOINT_MS = 600             # silence duration to trigger endpoint
PRE_SPEECH_PADDING_MS = 300           # include audio before speech onset
SILERO_SPEECH_THRESHOLD = 0.5         # Silero probability: > this = speech


class WhisperStreamProcessor:
    """
    Accumulates streaming PCM audio, detects speech endpoints using
    energy-based VAD, and transcribes using faster-whisper.

    Thread-safe: feed() can be called from any thread/coroutine.
    poll() returns a transcript when a complete utterance is detected.
    """

    def __init__(self, whisper_model, sample_rate: int = SAMPLE_RATE):
        self.whisper_model = whisper_model
        self.sample_rate = sample_rate

        # Ring buffer for audio data
        self._buffer: deque[np.ndarray] = deque()
        self._buffer_samples = 0
        self._lock = threading.Lock()

        # VAD state
        self._speech_active = False
        self._speech_start_time: float = 0.0
        self._last_speech_time: float = 0.0
        self._silence_start_time: float = 0.0

        # Result queue
        self._pending_transcript: Optional[str] = None
        self._transcribing = False

        # Frame tracking for RMS calculation
        self._frame_size = int(sample_rate * 0.03)  # 30ms frames
        self._rms_history: deque[float] = deque(maxlen=20)  # ~600ms of RMS values

        # ── Silero ONNX VAD (neural, more accurate than RMS) ──────────────
        self._silero_session = None
        self._silero_h = None  # hidden state
        self._silero_c = None  # cell state
        if _ONNX_AVAILABLE:
            try:
                import importlib.resources
                import pathlib
                # Look for Silero model in faster-whisper assets (already bundled)
                vad_paths = [
                    pathlib.Path(__file__).parent.parent / "venv" / "Lib" / "site-packages" / "faster_whisper" / "assets" / "silero_vad.onnx",
                    pathlib.Path(__file__).parent / "silero_vad.onnx",
                ]
                vad_path = None
                for p in vad_paths:
                    if p.exists():
                        vad_path = str(p)
                        break
                if vad_path:
                    opts = ort.SessionOptions()
                    opts.inter_op_num_threads = 1
                    opts.intra_op_num_threads = 1
                    self._silero_session = ort.InferenceSession(vad_path, sess_options=opts)
                    # Initialize hidden states (Silero v5: 2×1×64)
                    self._silero_h = np.zeros((2, 1, 64), dtype=np.float32)
                    self._silero_c = np.zeros((2, 1, 64), dtype=np.float32)
                    log.info("[WhisperStream] Silero ONNX VAD loaded from %s", vad_path)
                else:
                    log.warning("[WhisperStream] Silero ONNX file not found — falling back to RMS VAD")
            except Exception as exc:
                log.warning("[WhisperStream] Silero VAD init failed (RMS fallback): %s", exc)

        log.info("[WhisperStream] Initialized (sample_rate=%d, buffer=%ds, silero=%s)",
                 sample_rate, RING_BUFFER_SECONDS, self._silero_session is not None)

    def feed(self, pcm_chunk: np.ndarray) -> None:
        """
        Feed a PCM audio chunk (float32, mono, 16kHz).
        Thread-safe. Can be called from WebSocket handler.
        """
        if pcm_chunk is None or len(pcm_chunk) == 0:
            return

        # Ensure float32
        if pcm_chunk.dtype != np.float32:
            pcm_chunk = pcm_chunk.astype(np.float32)

        with self._lock:
            self._buffer.append(pcm_chunk)
            self._buffer_samples += len(pcm_chunk)

            # Trim ring buffer if too long
            while self._buffer_samples > RING_BUFFER_SAMPLES and len(self._buffer) > 1:
                removed = self._buffer.popleft()
                self._buffer_samples -= len(removed)

        # Run VAD on this chunk
        self._process_vad(pcm_chunk)

    def _process_vad(self, chunk: np.ndarray) -> None:
        """Voice Activity Detection: Silero (primary) + RMS (pre-filter/fallback)."""
        # Calculate RMS energy
        rms = float(np.sqrt(np.mean(chunk ** 2))) if len(chunk) > 0 else 0.0
        self._rms_history.append(rms)
        now = time.time()

        # ── Get speech probability ────────────────────────────────────────
        speech_prob = 0.0
        if self._silero_session is not None and rms > SILENCE_RMS_THRESHOLD * 0.5:
            # Only run Silero if RMS is above absolute silence (saves CPU)
            speech_prob = self._silero_infer(chunk)
            is_speech = speech_prob > SILERO_SPEECH_THRESHOLD
            is_silence = speech_prob < (SILERO_SPEECH_THRESHOLD * 0.5)
        else:
            # Fallback to RMS-only VAD
            is_speech = rms > SPEECH_RMS_THRESHOLD
            is_silence = rms < SILENCE_RMS_THRESHOLD

        if not self._speech_active:
            if is_speech:
                # Require sustained speech (not just a click)
                recent_rms = list(self._rms_history)[-3:]  # type: ignore[index]
                if len(recent_rms) >= 2 and sum(1 for r in recent_rms if r > SPEECH_RMS_THRESHOLD) >= 2:
                    self._speech_active = True
                    self._speech_start_time = now
                    self._last_speech_time = now
                    self._silence_start_time = 0.0
                    log.debug("[WhisperStream] Speech onset (RMS=%.4f, silero=%.3f)", rms, speech_prob)
        else:
            if not is_silence:
                self._last_speech_time = now
                self._silence_start_time = 0.0
            else:
                if self._silence_start_time == 0.0:
                    self._silence_start_time = now
                else:
                    silence_duration_ms = (now - self._silence_start_time) * 1000
                    speech_duration_ms = (self._last_speech_time - self._speech_start_time) * 1000

                    if (silence_duration_ms >= SILENCE_ENDPOINT_MS and
                            speech_duration_ms >= SPEECH_MIN_DURATION_MS):
                        log.info("[WhisperStream] Endpoint: speech=%.0fms, silence=%.0fms",
                                 speech_duration_ms, silence_duration_ms)
                        self._trigger_transcription()

    def _silero_infer(self, chunk: np.ndarray) -> float:
        """Run Silero ONNX inference on a chunk. Returns speech probability [0,1]."""
        try:
            # Silero expects 512-sample chunks at 16kHz
            # Process the last 512 samples
            if len(chunk) < 512:
                chunk = np.pad(chunk, (512 - len(chunk), 0), mode='constant')
            audio = chunk[-512:].reshape(1, -1).astype(np.float32)
            sr = np.array([self.sample_rate], dtype=np.int64)

            ort_inputs = {
                'input': audio,
                'sr': sr,
                'h': self._silero_h,
                'c': self._silero_c,
            }
            out, hn, cn = self._silero_session.run(None, ort_inputs)
            self._silero_h = hn
            self._silero_c = cn
            return float(out[0][0])
        except Exception:
            return 0.0

    def _trigger_transcription(self) -> None:
        """Extract speech segment and transcribe it."""
        if self._transcribing:
            return

        self._transcribing = True
        self._speech_active = False

        # Extract audio from buffer
        with self._lock:
            if not self._buffer:
                self._transcribing = False
                return

            audio = np.concatenate(self._buffer)
            # Clear buffer for next utterance
            self._buffer.clear()
            self._buffer_samples = 0

        # Transcribe (this runs synchronously — caller should use executor)
        try:
            transcript = self._transcribe(audio)
            if transcript and transcript.strip():
                self._pending_transcript = transcript.strip()
                log.info("[WhisperStream] Transcribed: '%s'", transcript[:60])  # type: ignore[index]
            else:
                log.debug("[WhisperStream] Empty transcription result")
        except Exception as exc:
            log.error("[WhisperStream] Transcription error: %s", exc)
        finally:
            self._transcribing = False
            self._rms_history.clear()

    def _transcribe(self, audio: np.ndarray) -> str:
        """Run faster-whisper transcription on audio segment."""
        if self.whisper_model is None:
            log.warning("[WhisperStream] No Whisper model loaded")
            return ""

        try:
            segments, info = self.whisper_model.transcribe(
                audio,
                beam_size=1,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=200,
                    speech_pad_ms=50,
                ),
            )
            text = " ".join(seg.text.strip() for seg in segments).strip()
            lang = getattr(info, 'language', 'en') or 'en'
            log.debug("[WhisperStream] STT: lang=%s text='%s'", lang, text)
            return text
        except Exception as exc:
            log.error("[WhisperStream] Whisper error: %s", exc)
            return ""

    def poll(self) -> Optional[str]:
        """
        Check if a complete utterance has been transcribed.
        Returns the transcript string, or None if nothing is ready.
        Non-blocking.
        """
        result = self._pending_transcript
        if result is not None:
            self._pending_transcript = None
        return result

    def reset(self) -> None:
        """Clear all buffers and state. Use when starting a new conversation."""
        with self._lock:
            self._buffer.clear()
            self._buffer_samples = 0

        self._speech_active = False
        self._speech_start_time = 0.0
        self._last_speech_time = 0.0
        self._silence_start_time = 0.0
        self._pending_transcript = None
        self._transcribing = False
        self._rms_history.clear()
        log.info("[WhisperStream] Reset")

    @property
    def is_speech_active(self) -> bool:
        """Whether speech is currently being detected."""
        return self._speech_active

    @property
    def is_transcribing(self) -> bool:
        """Whether a transcription is currently in progress."""
        return self._transcribing

    def get_rms(self) -> float:
        """Get the most recent RMS energy level."""
        return self._rms_history[-1] if self._rms_history else 0.0
