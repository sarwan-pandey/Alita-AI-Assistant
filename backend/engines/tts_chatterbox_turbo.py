"""
Chatterbox-Turbo Speech Synthesis Engine for MJ (English)
=========================================================
High-speed, 350M-parameter distilled text-to-speech engine:
- T3 GPT-2 medium backbone + 1-step Meanflow speech decoder.
- Conditioned on canonical MJ female reference voice (alita_en_original.wav).
- Supports native paralinguistic expression tags ([laugh], [sigh], [cough], [chuckle]).
- Generates 16-bit PCM WAV bytes at 24,000 Hz.
- Thread-safe generation with typed TTSGenerationError on failure.
"""

import io
import os
import time
import logging
import threading
from pathlib import Path
from typing import Optional

import torch
import soundfile as sf

log = logging.getLogger("alita.chatterbox_turbo")

# Canonical paths relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_TURBO_DIR = _PROJECT_ROOT / "tts_benchmark" / "chatterbox" / "models" / "turbo"
_DEFAULT_REF_VOICE = _PROJECT_ROOT / "backend" / "voices" / "default" / "alita_en_original.wav"


class TTSGenerationError(Exception):
    """Raised when speech synthesis fails in a TTS engine."""
    pass


class ChatterboxTurboEngine:
    """
    Isolated production wrapper for Chatterbox-Turbo TTS.
    Designed for low-latency English conversational responses.
    """

    def __init__(
        self,
        model_dir: Optional[Path] = None,
        ref_voice_path: Optional[Path] = None,
        device: Optional[str] = None,
    ):
        self._lock = threading.Lock()
        self._model = None
        self._initialized = False
        self._sample_rate = 24000

        self.model_dir = Path(model_dir) if model_dir else _DEFAULT_TURBO_DIR
        self.ref_voice_path = Path(ref_voice_path) if ref_voice_path else _DEFAULT_REF_VOICE

        # Determine compute device
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self._init_model()

    def _init_model(self) -> None:
        """Load model weights and pre-compute MJ voice conditioning."""
        t0 = time.perf_counter()
        try:
            if not self.model_dir.exists():
                log.error("Chatterbox-Turbo directory not found: %s", self.model_dir)
                return

            if not self.ref_voice_path.exists():
                log.error("Canonical MJ reference voice not found: %s", self.ref_voice_path)
                return

            from chatterbox.tts_turbo import ChatterboxTurboTTS

            log.info("Loading Chatterbox-Turbo from %s on %s...", self.model_dir, self.device)
            self._model = ChatterboxTurboTTS.from_local(self.model_dir, device=self.device)
            self._sample_rate = getattr(self._model, "sr", 24000)

            # Pre-compute and cache conditionals once on startup
            log.info("Conditioning Chatterbox-Turbo with canonical MJ voice: %s", self.ref_voice_path.name)
            self._model.prepare_conditionals(str(self.ref_voice_path))

            self._initialized = True
            elapsed = time.perf_counter() - t0
            log.info("✓ Chatterbox-Turbo engine loaded and conditioned in %.2fs", elapsed)

        except Exception as exc:
            log.error("Failed to initialize Chatterbox-Turbo engine: %s", exc, exc_info=True)
            self._model = None
            self._initialized = False

    @property
    def available(self) -> bool:
        """Returns True if the engine is initialized and ready for synthesis."""
        return self._initialized and self._model is not None

    def generate(
        self,
        text: str,
        temperature: float = 0.8,
        repetition_penalty: float = 1.2,
        top_p: float = 0.95,
    ) -> bytes:
        """
        Synthesize English text into 16-bit PCM WAV bytes.
        Returns b"" for naturally empty input.
        Raises TTSGenerationError when synthesis fails or produces corrupt/empty audio.
        """
        if not text or not text.strip():
            return b""

        if not self.available:
            raise TTSGenerationError("Chatterbox-Turbo engine is not initialized or unavailable")

        clean_text = text.strip()
        t0 = time.perf_counter()

        with self._lock:
            try:
                with torch.inference_mode():
                    wav = self._model.generate(
                        text=clean_text,
                        temperature=temperature,
                        repetition_penalty=repetition_penalty,
                        top_p=top_p,
                    )

                if wav is None or (isinstance(wav, torch.Tensor) and wav.numel() == 0):
                    raise TTSGenerationError(f"Chatterbox-Turbo returned empty audio tensor for '{clean_text[:40]}'")

                if isinstance(wav, torch.Tensor):
                    audio_np = wav.squeeze(0).detach().cpu().numpy()
                else:
                    audio_np = wav

                # Format as 16-bit PCM WAV in memory
                buffer = io.BytesIO()
                sf.write(buffer, audio_np, self._sample_rate, format="WAV", subtype="PCM_16")
                wav_bytes = buffer.getvalue()

                if not wav_bytes:
                    raise TTSGenerationError(f"Audio buffer serialization produced 0 bytes for '{clean_text[:40]}'")

                elapsed_ms = (time.perf_counter() - t0) * 1000
                log.debug(
                    "Chatterbox-Turbo generated %d bytes in %.1fms for '%s'",
                    len(wav_bytes),
                    elapsed_ms,
                    clean_text[:40],
                )
                return wav_bytes

            except TTSGenerationError:
                raise
            except Exception as exc:
                raise TTSGenerationError(f"Chatterbox-Turbo synthesis failed: {exc}") from exc
