"""
XTTS v2 — Local Neural TTS with Voice Cloning
===============================================
Coqui TTS wrapper for Alita assistant.
- Voice cloning from 6-30s reference audio
- 17 languages including Hindi + English
- GPU-accelerated (RTX 3050 compatible)
- Speaker embedding cache for instant re-use
"""

import io
import os
import time
import logging
import hashlib
from pathlib import Path
from typing import Optional

import numpy as np

log = logging.getLogger("alita.xtts")

# Directory for voice samples
VOICES_DIR = Path(__file__).parent.parent / "voices"
VOICES_DEFAULT_DIR = VOICES_DIR / "default"
VOICES_CUSTOM_DIR = VOICES_DIR / "custom"


class XTTSEngine:
    """
    XTTS v2 voice synthesis engine with speaker embedding caching.
    
    Usage:
        engine = XTTSEngine(device="cuda")
        wav_bytes = engine.generate("Hello world!", "voices/default/alita_en.wav", "en")
    """

    # Supported XTTS language codes
    SUPPORTED_LANGS = {
        "en", "es", "fr", "de", "it", "pt", "pl", "tr", "ru",
        "nl", "cs", "ar", "zh-cn", "ja", "hu", "ko", "hi",
    }

    def __init__(self, device: str = "cuda", model_name: str = "tts_models/multilingual/multi-dataset/xtts_v2"):
        """Load XTTS v2 model onto specified device."""
        self.device = device
        self.model = None
        self._speaker_cache: dict[str, dict] = {}  # wav_hash → conditioning tensors
        self._cache_hits = 0
        self._cache_misses = 0

        try:
            from TTS.api import TTS
            log.info("Loading XTTS v2 model (first run downloads ~1.8GB)...")
            start = time.time()

            self.tts = TTS(model_name=model_name).to(device)
            self.model = self.tts.synthesizer.tts_model if hasattr(self.tts, 'synthesizer') else True

            elapsed = time.time() - start
            log.info("✓ XTTS v2 loaded on %s in %.1fs", device, elapsed)
        except Exception as exc:
            log.error("✗ Failed to load XTTS v2: %s", exc)
            self.tts = None
            self.model = None

    @property
    def available(self) -> bool:
        """True if the model is loaded and ready."""
        return self.tts is not None and self.model is not None

    def _get_wav_hash(self, speaker_wav: str) -> str:
        """Hash the speaker WAV path + modification time for cache key."""
        try:
            stat = os.stat(speaker_wav)
            key = f"{speaker_wav}:{stat.st_mtime}:{stat.st_size}"
            return hashlib.md5(key.encode()).hexdigest()
        except OSError:
            return hashlib.md5(speaker_wav.encode()).hexdigest()

    def _preprocess_wav(self, speaker_wav: str) -> str:
        """
        Auto-preprocess WAV: convert to mono 22050Hz if needed.
        Returns path to the preprocessed file (may be same path if already good).
        """
        try:
            import wave
            with wave.open(speaker_wav, 'rb') as wf:
                channels = wf.getnchannels()
                framerate = wf.getframerate()

            if channels > 1 or framerate != 22050:
                from pydub import AudioSegment
                audio = AudioSegment.from_wav(speaker_wav)
                if channels > 1:
                    audio = audio.set_channels(1)
                    log.info("Auto-converted %s from %dch to mono", Path(speaker_wav).name, channels)
                if framerate != 22050:
                    audio = audio.set_frame_rate(22050)
                    log.info("Auto-resampled %s from %dHz to 22050Hz", Path(speaker_wav).name, framerate)
                audio.export(speaker_wav, format='wav')
        except Exception as exc:
            log.warning("Failed to preprocess WAV %s: %s", speaker_wav, exc)
        return speaker_wav

    def _get_speaker_conditioning(self, speaker_wav: str) -> Optional[dict]:
        """
        Get or compute speaker conditioning (embeddings) from reference audio.
        Cached for fast re-use — first call processes the WAV, subsequent calls
        return instantly.
        """
        if not hasattr(self.tts, 'synthesizer') or not hasattr(self.tts.synthesizer, 'tts_model'):
            return None

        wav_hash = self._get_wav_hash(speaker_wav)

        if wav_hash in self._speaker_cache:
            self._cache_hits += 1
            log.debug("Speaker embedding cache HIT (hits=%d)", self._cache_hits)
            return self._speaker_cache[wav_hash]

        self._cache_misses += 1

        # Auto-preprocess: ensure mono 22050Hz
        speaker_wav = self._preprocess_wav(speaker_wav)
        # Re-hash after preprocessing (file may have changed)
        wav_hash = self._get_wav_hash(speaker_wav)

        try:
            model = self.tts.synthesizer.tts_model
            # Compute speaker latents (gpt_cond_latent + speaker_embedding)
            gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
                audio_path=[speaker_wav]
            )
            conditioning = {
                "gpt_cond_latent": gpt_cond_latent,
                "speaker_embedding": speaker_embedding,
            }
            self._speaker_cache[wav_hash] = conditioning
            log.info("Speaker embedding computed and cached for: %s", Path(speaker_wav).name)
            return conditioning
        except Exception as exc:
            log.error("Failed to compute speaker embedding: %s", exc)
            return None

    def generate(
        self,
        text: str,
        speaker_wav: str,
        language: str = "en",
    ) -> Optional[bytes]:
        """
        Generate speech audio from text using a reference voice.
        
        Args:
            text: Text to synthesize
            speaker_wav: Path to reference WAV file (6-30 seconds)
            language: Language code (en, hi, etc.)
            
        Returns:
            MP3 bytes or None if generation fails
        """
        if not self.available:
            log.warning("XTTS engine not available")
            return None

        if not text or not text.strip():
            return None

        if not os.path.exists(speaker_wav):
            log.warning("Speaker WAV not found: %s", speaker_wav)
            return None

        # Normalize language code
        lang = language.lower().strip()
        if lang not in self.SUPPORTED_LANGS:
            # Map common variants
            lang_map = {"hindi": "hi", "english": "en", "chinese": "zh-cn"}
            lang = lang_map.get(lang, "en")

        try:
            start = time.time()

            # Try cached speaker conditioning for speed
            conditioning = self._get_speaker_conditioning(speaker_wav)

            if conditioning and hasattr(self.tts, 'synthesizer') and hasattr(self.tts.synthesizer, 'tts_model'):
                # Fast path: use pre-computed speaker embeddings
                model = self.tts.synthesizer.tts_model
                wav_array = model.inference(
                    text=text,
                    language=lang,
                    gpt_cond_latent=conditioning["gpt_cond_latent"],
                    speaker_embedding=conditioning["speaker_embedding"],
                )
                # inference returns dict with "wav" key
                if isinstance(wav_array, dict):
                    wav_array = wav_array.get("wav", wav_array)
                
                # Convert tensor to numpy
                if hasattr(wav_array, 'cpu'):
                    wav_array = wav_array.cpu().numpy()
                if hasattr(wav_array, 'squeeze'):
                    wav_array = wav_array.squeeze()
            else:
                # Fallback: use TTS API (re-processes WAV each time)
                wav_array = self.tts.tts(
                    text=text,
                    speaker_wav=speaker_wav,
                    language=lang,
                )

            if wav_array is None or (hasattr(wav_array, '__len__') and len(wav_array) == 0):
                log.warning("XTTS returned empty audio")
                return None

            # Convert numpy WAV to MP3 bytes (matches Edge TTS pipeline)
            mp3_bytes = self._wav_to_mp3(wav_array)

            elapsed = time.time() - start
            log.info("XTTS generated %d bytes MP3 in %.2fs (lang=%s)", len(mp3_bytes), elapsed, lang)
            return mp3_bytes

        except Exception as exc:
            log.error("XTTS generation failed: %s", exc, exc_info=True)
            return None

    def _wav_to_mp3(self, wav_array, sample_rate: int = 24000) -> bytes:
        """Convert numpy WAV array to MP3 bytes using pydub."""
        try:
            from pydub import AudioSegment

            # Ensure float32 → int16
            if isinstance(wav_array, np.ndarray):
                if wav_array.dtype == np.float32 or wav_array.dtype == np.float64:
                    # Normalize to int16 range
                    wav_array = np.clip(wav_array, -1.0, 1.0)
                    wav_array = (wav_array * 32767).astype(np.int16)

                raw_bytes = wav_array.tobytes()
            else:
                raw_bytes = bytes(wav_array)

            # Create AudioSegment from raw PCM
            audio = AudioSegment(
                data=raw_bytes,
                sample_width=2,  # int16 = 2 bytes
                frame_rate=sample_rate,
                channels=1,
            )

            # Export as MP3
            buffer = io.BytesIO()
            audio.export(buffer, format="mp3", bitrate="128k")
            return buffer.getvalue()

        except ImportError:
            # pydub not available — return WAV instead
            log.warning("pydub not available, returning raw WAV bytes")
            import wave
            buffer = io.BytesIO()
            with wave.open(buffer, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(sample_rate)
                if isinstance(wav_array, np.ndarray):
                    if wav_array.dtype != np.int16:
                        wav_array = np.clip(wav_array, -1.0, 1.0)
                        wav_array = (wav_array * 32767).astype(np.int16)
                    wf.writeframes(wav_array.tobytes())
                else:
                    wf.writeframes(bytes(wav_array))
            return buffer.getvalue()

    def preload_voices(self):
        """Pre-compute speaker embeddings for all default voices at startup."""
        if not self.available:
            return

        for wav_dir in [VOICES_DEFAULT_DIR, VOICES_CUSTOM_DIR]:
            if not wav_dir.exists():
                continue
            for wav_file in wav_dir.glob("*.wav"):
                try:
                    self._get_speaker_conditioning(str(wav_file))
                    log.info("Pre-cached voice: %s", wav_file.name)
                except Exception as exc:
                    log.warning("Failed to pre-cache %s: %s", wav_file.name, exc)

    def list_voices(self) -> list[dict]:
        """List all available voice samples (default + custom)."""
        voices = []
        for category, vdir in [("default", VOICES_DEFAULT_DIR), ("custom", VOICES_CUSTOM_DIR)]:
            if not vdir.exists():
                continue
            for wav_file in sorted(vdir.glob("*.wav")):
                stat = wav_file.stat()
                voices.append({
                    "id": wav_file.stem,
                    "name": wav_file.stem.replace("_", " ").title(),
                    "category": category,
                    "path": str(wav_file),
                    "size_kb": round(stat.st_size / 1024, 1),
                    "cached": self._get_wav_hash(str(wav_file)) in self._speaker_cache,
                })
        return voices

    def status(self) -> dict:
        """Engine status for monitoring."""
        return {
            "available": self.available,
            "device": self.device,
            "cached_speakers": len(self._speaker_cache),
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
        }
