"""
ChatTTS — Conversational Neural Speech Synthesizer for MJ
=========================================================
Ultra-expressive, conversational speech synthesis featuring:
- Natural laughter tags [laugh], giggles, and sighing tags [sigh]
- Conversational prosody, hesitation, and authentic human breathing
- Deterministic female speaker seed for MJ's warm, intimate persona
- Thread-safe in-memory WAV byte stream generation
"""

import io
import os
import time
import logging
import threading
from typing import Optional, List, Dict, Any

import numpy as np
import soundfile as sf
import torch

log = logging.getLogger("alita.chattts")

# MJ's canonical speaker seed — sweet, clear, youthful female conversational timbre
MJ_DEFAULT_SEED = 4220

# ── Dynamic Mood Presets ───────────────────────────────────────────────────────
MOOD_PRESETS: Dict[str, Dict[str, Any]] = {
    "affectionate": {
        "id": "affectionate",
        "name": "Affectionate & Warm",
        "description": "Gentle, warm, and intimate with soft pauses and affectionate sighs",
        "temperature": 0.22,
        "speed": 5,
        "icon": "💖",
    },
    "playful": {
        "id": "playful",
        "name": "Playful & Teasing",
        "description": "Bubbly, dynamic pitch with higher laughter expressiveness and giggles",
        "temperature": 0.38,
        "speed": 5,
        "icon": "✨",
    },
    "soothing": {
        "id": "soothing",
        "name": "Soothing & Tender",
        "description": "Slow, comforting cadence for emotional support and relaxation",
        "temperature": 0.20,
        "speed": 4,
        "icon": "🌙",
    },
    "calm": {
        "id": "calm",
        "name": "Calm & Natural",
        "description": "Balanced, crisp, and conversational everyday tone",
        "temperature": 0.28,
        "speed": 5,
        "icon": "☕",
    },
}


class ChatTTSEngine:
    """
    Thread-safe ChatTTS speech synthesis engine.
    Designed for real-time conversational dialogue with emotional markers.
    """

    def __init__(self, device: Optional[str] = None, seed: int = MJ_DEFAULT_SEED):
        self._lock = threading.Lock()
        self._chat = None
        self._spk_emb = None
        self._seed = seed
        self._initialized = False
        self._sample_rate = 24000

        # Load persisted mood preference
        try:
            from engines.user_profile import user_profile
            saved_mood = user_profile.get_preference("selected_mood", "affectionate")
        except Exception:
            saved_mood = "affectionate"
        self._mood = saved_mood if saved_mood in MOOD_PRESETS else "affectionate"

        # Auto-select device
        if device is None:
            self.device = "cuda" if torch.cuda.is_available() else "cpu"
        else:
            self.device = device

        self._init_model()

    def _init_model(self) -> None:
        """Initialize ChatTTS model and speaker embedding."""
        t0 = time.perf_counter()
        try:
            import ChatTTS
            log.info("Initializing ChatTTS engine on %s...", self.device)
            self._chat = ChatTTS.Chat()
            # source="huggingface" avoids broken rvcmd console panic on Windows
            loaded = self._chat.load(source="huggingface", compile=False, device=self.device)
            if not loaded:
                log.warning("ChatTTS models not yet downloaded or failed to load")
                self._chat = None
                self._initialized = False
                return

            # Generate deterministic speaker embedding for MJ
            torch.manual_seed(self._seed)
            if hasattr(self._chat, "speaker") and hasattr(self._chat, "sample_random_speaker"):
                self._spk_emb = self._chat.sample_random_speaker()
            else:
                self._spk_emb = None

            self._initialized = True
            elapsed = time.perf_counter() - t0
            log.info("✓ ChatTTS engine loaded successfully in %.2fs (device=%s, seed=%d)", elapsed, self.device, self._seed)
        except Exception as exc:
            log.warning("Notice: ChatTTS initialization deferred or unavailable: %s", exc)
            self._chat = None
            self._initialized = False

    def load_model(self) -> bool:
        """Explicitly load the ChatTTS model if not already loaded."""
        if self._initialized and self._chat is not None:
            return True
        with self._lock:
            self._init_model()
            return self.available

    def sample_speaker(self, seed: Optional[int] = None):
        """Sample speaker embedding for voice timbre."""
        if not self.available:
            return None
        target_seed = seed if seed is not None else self._seed
        torch.manual_seed(target_seed)
        if hasattr(self._chat, "sample_random_speaker"):
            return self._chat.sample_random_speaker()
        return None

    @property
    def available(self) -> bool:
        """Returns True if the engine is initialized and ready."""
        return self._initialized and self._chat is not None

    def set_seed(self, seed: int) -> None:
        """Change the speaker seed and re-sample the speaker embedding."""
        with self._lock:
            self._seed = seed
            if self._chat and hasattr(self._chat, "sample_random_speaker"):
                torch.manual_seed(seed)
                self._spk_emb = self._chat.sample_random_speaker()
                log.info("ChatTTS speaker seed updated to %d", seed)

    def set_mood(self, mood_key: str) -> bool:
        """Set the active emotional mood preset (affectionate, playful, soothing, calm)."""
        target = mood_key.lower().strip()
        if target in MOOD_PRESETS:
            self._mood = target
            try:
                from engines.user_profile import user_profile
                user_profile.set_preference("selected_mood", target)
            except Exception as exc:
                log.debug("Notice: user_profile persistence deferred: %s", exc)
            log.info("ChatTTS active mood updated to: %s (%s)", target, MOOD_PRESETS[target]["name"])
            return True
        return False

    def get_mood(self) -> str:
        """Get the active emotional mood preset key."""
        return self._mood

    @classmethod
    def get_available_moods(cls) -> List[Dict[str, Any]]:
        """Get all registered mood presets."""
        return list(MOOD_PRESETS.values())

    def generate(
        self,
        text: str,
        voice: Optional[str] = None,
        language: str = "en",
        temperature: Optional[float] = None,
        speed: Optional[int] = None,
        mood: Optional[str] = None,
    ) -> bytes:
        """
        Synthesize text into WAV bytes with dynamic emotional mood modulation.
        Supports inline emotion tags: [laugh], [sigh], [yawn], [break_0]...[break_7].
        """
        if not text or not text.strip():
            return b""

        if not self.available:
            log.warning("ChatTTS engine requested but not available")
            return b""

        t0 = time.perf_counter()
        clean_text = text.strip()

        # Determine effective emotional mood preset
        active_mood_key = mood.lower().strip() if mood and mood.lower().strip() in MOOD_PRESETS else self._mood
        preset = MOOD_PRESETS.get(active_mood_key, MOOD_PRESETS["affectionate"])

        effective_temp = temperature if temperature is not None else preset["temperature"]
        effective_speed = speed if speed is not None else preset["speed"]
        prompt_directive = f"[speed_{effective_speed}]" if 1 <= effective_speed <= 9 else ""

        with self._lock:
            try:
                import ChatTTS

                params_infer_code = ChatTTS.Chat.InferCodeParams(
                    spk_emb=self._spk_emb,
                    prompt=prompt_directive,
                    temperature=effective_temp,
                )

                # Generate speech
                wavs = self._chat.infer(
                    clean_text,
                    params_infer_code=params_infer_code,
                    use_decoder=True,
                )

                if wavs is None or len(wavs) == 0 or len(wavs[0]) == 0:
                    log.warning("ChatTTS returned empty audio")
                    return b""

                audio_data = wavs[0]
                # Normalize float32 audio
                if isinstance(audio_data, torch.Tensor):
                    audio_data = audio_data.detach().cpu().numpy()

                # Ensure 1D float array
                if audio_data.ndim > 1:
                    audio_data = audio_data.squeeze()

                # Write to WAV buffer
                buffer = io.BytesIO()
                sf.write(buffer, audio_data, self._sample_rate, format="WAV", subtype="PCM_16")
                wav_bytes = buffer.getvalue()

                elapsed_ms = (time.perf_counter() - t0) * 1000
                log.debug(
                    "ChatTTS synthesized %d bytes in %.1fms for '%s'",
                    len(wav_bytes),
                    elapsed_ms,
                    clean_text[:40],
                )
                return wav_bytes

            except Exception as exc:
                log.error("ChatTTS generation failed: %s (text='%s')", exc, clean_text[:40])
                return b""
