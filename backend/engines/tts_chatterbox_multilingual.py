"""
Chatterbox Multilingual V3 Speech Synthesis Engine for MJ (Hindi/Hinglish)
========================================================================
500M-parameter multilingual zero-shot voice cloning engine:
- T3 Multilingual architecture with language_id="hi".
- Supports pure Devanagari Hindi, Latin-script Hinglish, and mixed Hindi-English.
- Conditioned on canonical MJ female reference voice (alita_en_original.wav).
- Generates 16-bit PCM WAV bytes at 24,000 Hz.
- Thread-safe generation with typed TTSGenerationError on failure.
"""

import io
import os
import sys
import time
import logging
import threading
from pathlib import Path
from typing import Optional

# Prevent unnecessary pkuseg Chinese segmenter downloads
if "spacy_pkuseg" not in sys.modules:
    sys.modules["spacy_pkuseg"] = None

import torch
import soundfile as sf
from safetensors.torch import load_file as load_safetensors

log = logging.getLogger("alita.chatterbox_multilingual")

# Canonical paths relative to project root
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_MTL_DIR = _PROJECT_ROOT / "tts_benchmark" / "chatterbox" / "models" / "multilingual_v3"
_DEFAULT_REF_VOICE = _PROJECT_ROOT / "backend" / "voices" / "default" / "alita_en_original.wav"


class TTSGenerationError(Exception):
    """Raised when speech synthesis fails in a TTS engine."""
    pass


class ChatterboxMultilingualEngine:
    """
    Isolated production wrapper for Chatterbox Multilingual V3 TTS.
    Designed for Hindi, Latin Hinglish, and mixed Hindi-English responses.
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

        self.model_dir = Path(model_dir) if model_dir else _DEFAULT_MTL_DIR
        self.ref_voice_path = Path(ref_voice_path) if ref_voice_path else _DEFAULT_REF_VOICE

        # Determine compute device
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self._init_model()

    def _init_model(self) -> None:
        """Load multilingual model weights and pre-compute MJ voice conditioning."""
        t0 = time.perf_counter()
        try:
            t3_path = self.model_dir / "t3_mtl23ls_v3.safetensors"
            s3gen_path = self.model_dir / "s3gen.safetensors"
            ve_path = self.model_dir / "ve.safetensors"
            tok_path = self.model_dir / "grapheme_mtl_merged_expanded_v1.json"

            for required_file in (t3_path, s3gen_path, ve_path, tok_path):
                if not required_file.exists():
                    log.error("Required Chatterbox Multilingual file missing: %s", required_file)
                    return

            if not self.ref_voice_path.exists():
                log.error("Canonical MJ reference voice not found: %s", self.ref_voice_path)
                return

            from chatterbox.mtl_tts import ChatterboxMultilingualTTS
            from chatterbox.models.t3 import T3
            from chatterbox.models.t3.modules.t3_config import T3Config
            from chatterbox.models.s3gen import S3Gen
            from chatterbox.models.voice_encoder import VoiceEncoder
            from chatterbox.models.tokenizers import MTLTokenizer

            log.info("Loading Chatterbox Multilingual V3 from %s on %s...", self.model_dir, self.device)

            # 1. Voice Encoder
            ve = VoiceEncoder()
            ve.load_state_dict(load_safetensors(ve_path))
            ve.to(self.device).eval()

            # 2. T3 Multilingual
            t3_cfg = T3Config.multilingual()
            t3 = T3(t3_cfg)
            t3_state = load_safetensors(t3_path)
            if "model" in t3_state.keys():
                t3_state = t3_state["model"][0]
            t3.load_state_dict(t3_state)
            t3.to(self.device).eval()

            # 3. S3Gen
            s3gen = S3Gen()
            s3gen.load_state_dict(load_safetensors(s3gen_path), strict=False)
            s3gen.to(self.device).eval()

            # 4. Tokenizer & TTS model
            tokenizer = MTLTokenizer(str(tok_path))
            self._model = ChatterboxMultilingualTTS(t3, s3gen, ve, tokenizer, self.device)
            self._sample_rate = getattr(self._model, "sr", 24000)

            # Pre-compute and cache conditioning with canonical female MJ voice
            log.info("Conditioning Chatterbox Multilingual V3 with canonical MJ voice: %s", self.ref_voice_path.name)
            self._model.prepare_conditionals(str(self.ref_voice_path))

            self._initialized = True
            elapsed = time.perf_counter() - t0
            log.info("✓ Chatterbox Multilingual V3 engine loaded and conditioned in %.2fs", elapsed)

        except Exception as exc:
            log.error("Failed to initialize Chatterbox Multilingual engine: %s", exc, exc_info=True)
            self._model = None
            self._initialized = False

    @property
    def available(self) -> bool:
        """Returns True if the engine is initialized and ready for synthesis."""
        return self._initialized and self._model is not None

    def generate(
        self,
        text: str,
        language: str = "hi",
        temperature: float = 0.8,
        repetition_penalty: float = 1.2,
        top_p: float = 0.95,
    ) -> bytes:
        """
        Synthesize Hindi/Hinglish text into 16-bit PCM WAV bytes with language_id="hi".
        Returns b"" for naturally empty input.
        Raises TTSGenerationError when synthesis fails or produces corrupt/empty audio.
        """
        if not text or not text.strip():
            return b""

        if not self.available:
            raise TTSGenerationError("Chatterbox Multilingual engine is not initialized or unavailable")

        clean_text = text.strip()
        t0 = time.perf_counter()

        with self._lock:
            try:
                wav = self._model.generate(
                    text=clean_text,
                    language_id=language or "hi",
                    temperature=temperature,
                    repetition_penalty=repetition_penalty,
                    top_p=top_p,
                )

                if wav is None or (isinstance(wav, torch.Tensor) and wav.numel() == 0):
                    raise TTSGenerationError(f"Chatterbox Multilingual returned empty audio tensor for '{clean_text[:40]}'")

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
                    "Chatterbox Multilingual generated %d bytes in %.1fms for '%s'",
                    len(wav_bytes),
                    elapsed_ms,
                    clean_text[:40],
                )
                return wav_bytes

            except TTSGenerationError:
                raise
            except Exception as exc:
                raise TTSGenerationError(f"Chatterbox Multilingual synthesis failed: {exc}") from exc
