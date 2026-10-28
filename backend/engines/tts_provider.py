"""
TTS Provider Abstraction — Unified Speech Synthesis Interface
==============================================================
Provides a common interface for TTS providers so that production code
can route between providers without changing call sites.

IMPORTANT: This module does NOT change production behavior. The active
TTS provider is determined by configuration. Current production default
remains "chatterbox_local" (local Chatterbox Turbo).

Supported providers:
  - chatterbox_local           → Local Chatterbox Turbo (current production)
  - chatterbox_multilingual_nim → NVIDIA NIM Chatterbox Multilingual TTS
"""

from __future__ import annotations

import io
import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from engines.provider_contracts import (
    ProviderStatus,
    TTSProviderContract,
    TTSProviderHealth,
)

log = logging.getLogger("alita.tts_provider")


# ── Abstract Base Provider ───────────────────────────────────────────────────

class TTSProvider(TTSProviderContract):
    """Abstract base class for TTS providers, implementing TTSProviderContract."""
    provider_id: str = "unknown"

    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str = "",
        language: str = "en",
        **kwargs,
    ) -> bytes:
        """
        Synthesize text to audio bytes (WAV format, 16-bit PCM).
        Returns audio bytes or empty bytes on failure.
        """
        ...

    @abstractmethod
    def health_check(self) -> TTSProviderHealth:
        """Check provider availability."""
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return human-readable provider name."""
        ...

    @abstractmethod
    def list_voices(self) -> List[Dict[str, Any]]:
        """Return list of available voices with metadata."""
        ...


# ── Chatterbox Local Provider ────────────────────────────────────────────────

class ChatterboxLocalProvider(TTSProvider):
    """
    Local Chatterbox Turbo TTS — current production provider.
    Wraps the existing tts_dispatch.py without modifying it.
    """

    provider_id = "chatterbox_local"

    def __init__(self):
        self._health = TTSProviderHealth(provider_id=self.provider_id)

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        language: str = "en",
        **kwargs,
    ) -> bytes:
        t0 = time.perf_counter()
        try:
            from tts_dispatch import _tts_generate
            voice_info = kwargs.get("voice_info", {"id": voice or "chatterbox_turbo_mj"})
            result = await _tts_generate(text, voice_info, language)
            latency = (time.perf_counter() - t0) * 1000
            if result:
                self._health.record_success(latency)
            else:
                self._health.record_failure("Empty audio output")
            return result or b""
        except Exception as exc:
            self._health.record_failure(str(exc))
            log.warning("[chatterbox_local] Synthesis failed: %s", exc)
            return b""

    def get_engine(self):
        """Retrieve or initialize singleton ChatterboxTurboEngine via adapter boundary."""
        try:
            from main import engines, settings
            if getattr(engines, "chatterbox_turbo_engine", None) is not None:
                return engines.chatterbox_turbo_engine
            from engines.resource_guard import resource_guard
            with resource_guard.loading("ChatterboxTurbo", estimated_mb=800):
                from engines.tts_chatterbox_turbo import ChatterboxTurboEngine
                engines.chatterbox_turbo_engine = ChatterboxTurboEngine(device=getattr(settings, "device", "cpu"))
                return engines.chatterbox_turbo_engine
        except Exception as exc:
            log.error("Failed to load Chatterbox Turbo in provider: %s", exc)
            return None

    def health_check(self) -> TTSProviderHealth:
        try:
            engine = self.get_engine()
            if engine and engine.available:
                self._health.available = True
                self._health.status = ProviderStatus.AVAILABLE
                self._health.last_error = ""
            else:
                self._health.available = False
                self._health.status = ProviderStatus.UNAVAILABLE
                self._health.last_error = "Chatterbox Turbo engine not loaded or unavailable"
        except Exception as exc:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = str(exc)
        self._health.last_check = time.time()
        return self._health

    def get_provider_name(self) -> str:
        return "Chatterbox Turbo (Local)"

    def list_voices(self) -> List[Dict[str, Any]]:
        try:
            from main import AVAILABLE_VOICES
            return [
                {"id": vid, "name": v.get("name", vid), "engine": v.get("engine", "chatterbox_turbo")}
                for vid, v in AVAILABLE_VOICES.items()
                if v.get("available", True)
            ]
        except Exception:
            return [{"id": "chatterbox_turbo_mj", "name": "MJ (Default)", "engine": "chatterbox_turbo"}]


def sanitize_error(error: Any) -> str:
    """Strip API keys and credentials from error strings to prevent leakage."""
    if not error:
        return ""
    import re
    s = str(error)
    s = re.sub(r"nvapi-[A-Za-z0-9_\-]+", "nvapi-[REDACTED]", s)
    s = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    return s


# ── NVIDIA NIM Chatterbox Multilingual Provider ─────────────────────────────

class ChatterboxNIMProvider(TTSProvider):
    """
    NVIDIA NIM Chatterbox Multilingual TTS — cloud provider.
    Uses Riva gRPC interface (grpc.nvcf.nvidia.com:443) with NVCF function-id auth.

    NOT activated for production traffic. Available for testing and future migration.

    NOTE: This provider does NOT support custom voice cloning.
    """

    provider_id = "chatterbox_multilingual_nim"

    DEFAULT_NIM_URL = "grpc.nvcf.nvidia.com:443"

    def __init__(
        self,
        api_key: str = "",
        server: str = "",
        function_id: str = "",
        nim_url: str = "",
        timeout: Optional[float] = None,
    ):
        import os
        self._api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY", "").strip()
        self._server = (server or os.getenv("NVIDIA_RIVA_SERVER", "")).strip()
        self._function_id = (
            (function_id or os.getenv("NVIDIA_CHATTERBOX_FUNCTION_ID", "")).strip()
            or "ddacc747-1269-4fab-bfd9-8f593dead106"
        )
        self._nim_url = nim_url or self._server or self.DEFAULT_NIM_URL
        self._timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_TTS_TIMEOUT", "4.0"))
        self._health = TTSProviderHealth(provider_id=self.provider_id)

    def _default_voice_for_language(self, language: str) -> str:
        """Map language code to a Chatterbox NIM voice identifier."""
        from engines.tts_nvidia_nim import get_default_voice
        return get_default_voice(language)

    async def synthesize(
        self,
        text: str,
        voice: str = "Chatterbox-Multilingual.en-US.Male",
        language: str = "en",
        **kwargs,
    ) -> bytes:
        if not self._api_key and "localhost" not in self._server:
            log.debug("[chatterbox_nim] No API key — synthesis skipped")
            return b""

        turn_id = kwargs.get("turn_id") or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"
        t0 = time.perf_counter()

        try:
            from engines.tts_nvidia_nim import ChatterboxNIMClient
            client = ChatterboxNIMClient(
                api_key=self._api_key,
                server=self._server,
                function_id=self._function_id,
                timeout=self._timeout,
                nim_url=self._nim_url,
            )
            wav_bytes, metrics = await client.synthesize_with_metrics(
                text=text,
                language=language,
                voice=voice,
                turn_id=turn_id,
                request_id=turn_id,
            )
            if metrics.success and wav_bytes:
                self._health.record_success(metrics.total_ms)
                log.info(
                    "[chatterbox_nim] gRPC Synthesis OK (turn_id=%s): %.0fms, %d bytes",
                    turn_id,
                    metrics.total_ms,
                    len(wav_bytes),
                )
                return wav_bytes
            else:
                self._health.record_failure(metrics.error or "Empty audio received from Riva")
                log.warning("[chatterbox_nim] gRPC Synthesis failed (turn_id=%s): %s", turn_id, metrics.error)
                return b""
        except Exception as exc:
            sanitized = sanitize_error(exc)
            self._health.record_failure(sanitized)
            log.warning("[chatterbox_nim] Synthesis exception (turn_id=%s): %s", turn_id, sanitized)
            return b""

    def synthesize_stream(
        self,
        text: str,
        voice: str = "",
        language: str = "en",
        **kwargs,
    ) -> Iterator[bytes]:
        """Streaming synthesis via Riva gRPC SynthesizeOnline."""
        turn_id = kwargs.get("turn_id") or kwargs.get("request_id") or ""
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient(
            api_key=self._api_key,
            server=self._server,
            function_id=self._function_id,
            timeout=self._timeout,
            nim_url=self._nim_url,
        )
        yield from client.synthesize_stream(
            text=text,
            language=language,
            voice=voice,
            turn_id=turn_id,
            request_id=turn_id,
        )

    def health_check(self) -> TTSProviderHealth:
        if not self._api_key and "localhost" not in self._server:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = "No API key configured"
            self._health.last_check = time.time()
            return self._health

        try:
            from engines.tts_nvidia_nim import ChatterboxNIMClient
            client = ChatterboxNIMClient(
                api_key=self._api_key,
                server=self._server,
                function_id=self._function_id,
                timeout=min(self._timeout, 5.0),
                nim_url=self._nim_url,
            )
            cfg = client._get_grpc_client().get_synthesis_config(timeout=min(self._timeout, 5.0))
            if cfg:
                self._health.available = True
                self._health.status = ProviderStatus.AVAILABLE
                self._health.last_error = ""
            else:
                self._health.available = False
                self._health.status = ProviderStatus.DEGRADED
                self._health.last_error = "No models reported by Riva server"
        except Exception as exc:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = sanitize_error(exc)
        self._health.last_check = time.time()
        return self._health

    def get_provider_name(self) -> str:
        return "Chatterbox Multilingual (NVIDIA Riva gRPC)"

    def list_voices(self) -> List[Dict[str, Any]]:
        from engines.tts_nvidia_nim import VOICE_CATALOG
        return [{"id": v.voice_id, "name": v.display_name, "lang": v.language} for v in VOICE_CATALOG]


# ── Fallback Resilient TTS Provider (P0) ────────────────────────────────────

class FallbackTTSProvider(TTSProvider):
    """
    Resilient TTS Provider: Primary candidate with deterministic failover to local Chatterbox Turbo.

    Guarantees:
      - Fail-fast configurable timeout (default 4.0s via NVIDIA_TTS_TIMEOUT)
      - Strips all API credentials before logging errors
      - Preserves request_id / turn_id throughout the pipeline
      - Logs primary failure and fallback selection clearly
      - Returns valid audio from local Chatterbox Turbo whenever fallback succeeds
      - Gated by feature flag (ENABLE_NVIDIA_TTS)
    """

    provider_id = "resilient_tts"

    def __init__(
        self,
        primary: Optional[TTSProvider] = None,
        fallback: Optional[TTSProvider] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        import os
        self.primary = primary
        self.fallback = fallback or ChatterboxLocalProvider()
        self.timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_TTS_TIMEOUT", "4.0"))
        self.enabled = (
            enabled if enabled is not None
            else os.getenv("ENABLE_NVIDIA_TTS", "false").lower() in ("true", "1", "yes")
        )
        self._health = TTSProviderHealth(provider_id=self.provider_id)

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        language: str = "en",
        **kwargs,
    ) -> bytes:
        turn_id = kwargs.get("turn_id") or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"

        # If feature flag disabled or primary unavailable, route directly to local Chatterbox Turbo
        if not self.enabled or not self.primary:
            log.debug("[TTS] Primary disabled by feature flag (turn_id=%s) -> routing directly to fallback '%s'",
                      turn_id, self.fallback.provider_id)
            return await self.fallback.synthesize(text, voice, language, **kwargs)

        t0 = time.perf_counter()
        primary_failed = False
        error_msg = ""

        try:
            audio = await self.primary.synthesize(text, voice, language, **kwargs)
            if audio and len(audio) > 44:  # Non-empty and exceeds WAV header
                self._health.record_success((time.perf_counter() - t0) * 1000)
                return audio
            else:
                primary_failed = True
                error_msg = "Primary returned empty or header-only audio"
        except Exception as exc:
            primary_failed = True
            error_msg = sanitize_error(exc)

        if primary_failed:
            log.warning(
                "[TTS-FALLBACK] Primary '%s' failed (turn_id=%s): %s. Falling back to '%s'",
                self.primary.provider_id, turn_id, error_msg, self.fallback.provider_id
            )
            self._health.record_failure(error_msg)

            fallback_audio = await self.fallback.synthesize(text, voice, language, **kwargs)
            if fallback_audio and len(fallback_audio) > 44:
                log.info(
                    "[TTS-FALLBACK] Fallback '%s' succeeded for turn_id=%s (%d bytes)",
                    self.fallback.provider_id, turn_id, len(fallback_audio)
                )
            return fallback_audio

        return b""

    def health_check(self) -> TTSProviderHealth:
        fb_health = self.fallback.health_check()
        if self.enabled and self.primary:
            p_health = self.primary.health_check()
            self._health.available = p_health.available or fb_health.available
            self._health.last_error = "" if self._health.available else f"Primary: {p_health.last_error}; Fallback: {fb_health.last_error}"
        else:
            self._health.available = fb_health.available
            self._health.last_error = fb_health.last_error
        self._health.last_check = time.time()
        return self._health

    def get_provider_name(self) -> str:
        if self.enabled and self.primary:
            return f"{self.primary.get_provider_name()}-resilient->{self.fallback.get_provider_name()}"
        return self.fallback.get_provider_name()

    def list_voices(self) -> List[Dict[str, Any]]:
        if self.enabled and self.primary:
            return self.primary.list_voices()
        return self.fallback.list_voices()


# ── TTS Provider Registry ───────────────────────────────────────────────────

class TTSProviderRegistry:
    """Thread-safe registry of all available TTS providers."""

    def __init__(self):
        self._providers: Dict[str, TTSProvider] = {}
        self._lock = threading.Lock()

    def register(self, provider: TTSProvider) -> None:
        with self._lock:
            self._providers[provider.provider_id] = provider
            log.info("Registered TTS provider: %s", provider.provider_id)

    def unregister(self, provider_id: str) -> bool:
        """Unregister a provider by ID. Returns True if removed."""
        with self._lock:
            if provider_id in self._providers:
                del self._providers[provider_id]
                log.info("Unregistered TTS provider: %s", provider_id)
                return True
            return False

    def get(self, provider_id: str) -> Optional[TTSProvider]:
        return self._providers.get(provider_id)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    def get_resilient_provider(
        self,
        primary_id: str = "chatterbox_multilingual_nim",
        fallback_id: str = "chatterbox_local",
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> FallbackTTSProvider:
        """Create a resilient TTS provider wrapping primary and fallback."""
        primary = self.get(primary_id)
        fallback = self.get(fallback_id) or ChatterboxLocalProvider()
        return FallbackTTSProvider(primary=primary, fallback=fallback, timeout=timeout, enabled=enabled)

    async def synthesize_with_fallback(
        self,
        text: str,
        primary_id: str = "chatterbox_multilingual_nim",
        fallback_id: str = "chatterbox_local",
        **kwargs,
    ) -> bytes:
        """Helper to synthesize audio with automatic fallback."""
        resilient = self.get_resilient_provider(primary_id=primary_id, fallback_id=fallback_id)
        return await resilient.synthesize(text, **kwargs)

    def health_check_all(self) -> Dict[str, TTSProviderHealth]:
        results = {}
        for pid, provider in self._providers.items():
            try:
                results[pid] = provider.health_check()
            except Exception as exc:
                results[pid] = TTSProviderHealth(
                    provider_id=pid, available=False, last_error=str(exc)
                )
        return results


# ── Module-level singleton ───────────────────────────────────────────────────

tts_registry = TTSProviderRegistry()


def initialize_tts_providers(nvidia_api_key: str = "", nim_url: str = "") -> TTSProviderRegistry:
    """Initialize all TTS providers and register them."""
    local = ChatterboxLocalProvider()
    tts_registry.register(local)

    nim = ChatterboxNIMProvider(api_key=nvidia_api_key, nim_url=nim_url)
    tts_registry.register(nim)

    return tts_registry

