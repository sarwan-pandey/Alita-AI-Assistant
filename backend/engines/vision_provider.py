"""
Vision Provider Abstraction — Unified Multimodal Vision Interface
=================================================================
Provides a common interface for vision/multimodal LLM providers.

IMPORTANT: This module does NOT change production behavior. The active
vision provider is determined by configuration. Current production default
remains the local Moondream model via Ollama.

Supported providers:
  - moondream_local → Ollama local Moondream (current production)
  - gemma_4_31b     → NVIDIA NIM Google Gemma 4 31B IT (multimodal)
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from engines.provider_contracts import (
    ProviderStatus,
    VisionProviderContract,
    VisionProviderHealth,
)

log = logging.getLogger("alita.vision_provider")


# ── Abstract Base Provider ───────────────────────────────────────────────────

class VisionProvider(VisionProviderContract):
    """Abstract base class for vision/multimodal providers, implementing VisionProviderContract."""
    provider_id: str = "unknown"

    @abstractmethod
    def analyze(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Analyze an image (base64 JPEG) with a text prompt.
        If image_b64 is None, may capture screen automatically (provider-dependent).
        Returns analysis text or None on failure.
        """
        ...

    @abstractmethod
    def health_check(self) -> VisionProviderHealth:
        """Check provider availability."""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier string."""
        ...


# ── Moondream Local Provider (Ollama) ────────────────────────────────────────

class MoondreamLocalProvider(VisionProvider):
    """
    Local Moondream vision model via Ollama — current production provider.
    Wraps the existing vision_engine.py without modifying it.
    """

    provider_id = "moondream_local"

    def __init__(self):
        self._health = VisionProviderHealth(provider_id=self.provider_id)

    def analyze(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        try:
            from engines.vision_engine import vision_engine
            if image_b64:
                result = vision_engine.analyze_with_context(prompt, "")
            else:
                result = vision_engine.smart_analyze(prompt)
            if result:
                self._health.record_success()
            return result
        except Exception as exc:
            self._health.record_failure(str(exc))
            log.warning("[moondream_local] Analyze failed: %s", exc)
            return None

    def locate_element(self, target: str) -> Optional[Dict[str, Any]]:
        """Locate screen element coordinates using local vision engine."""
        try:
            from engines.vision_engine import vision_engine
            return vision_engine.locate_element(target)
        except Exception as exc:
            log.debug("[moondream_local] locate_element failed: %s", exc)
            return None

    def analyze_screen(self, prompt: str) -> str:
        """Capture screen and analyze using local vision engine."""
        try:
            from engines.vision_engine import vision_engine
            return vision_engine.analyze_screen(prompt=prompt)
        except Exception as exc:
            log.warning("[moondream_local] analyze_screen failed: %s", exc)
            return ""

    def health_check(self) -> VisionProviderHealth:
        try:
            import httpx
            resp = httpx.get("http://localhost:11434/api/tags", timeout=5.0)
            if resp.status_code == 200:
                tags = resp.json().get("models", [])
                has_moondream = any("moondream" in m.get("name", "") for m in tags)
                self._health.available = has_moondream
                self._health.status = ProviderStatus.AVAILABLE if has_moondream else ProviderStatus.UNAVAILABLE
                self._health.last_error = "" if has_moondream else "Moondream model not loaded"
            else:
                self._health.available = False
                self._health.status = ProviderStatus.UNAVAILABLE
                self._health.last_error = f"Ollama returned {resp.status_code}"
        except Exception as exc:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = str(exc)
        self._health.last_check = time.time()
        return self._health

    def get_model_name(self) -> str:
        return "moondream"


def sanitize_error(error: Any) -> str:
    """Strip API keys and credentials from error strings to prevent leakage."""
    if not error:
        return ""
    import re
    s = str(error)
    s = re.sub(r"nvapi-[A-Za-z0-9_\-]+", "nvapi-[REDACTED]", s)
    s = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    return s


# ── Gemma 4 31B IT Provider (NVIDIA NIM) ─────────────────────────────────────

class Gemma4VisionProvider(VisionProvider):
    """
    NVIDIA NIM Gemma 4 31B IT — multimodal vision model.
    Supports text + image inputs via OpenAI-compatible chat API.

    NOT activated for production traffic. Available for testing and future migration.
    """

    NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"
    MODEL_ID = "google/gemma-4-31b-it"

    provider_id = "gemma_4_31b"

    def __init__(self, api_key: Optional[str] = None, timeout: Optional[float] = None):
        import os
        self._api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY", "").strip()
        self._timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_VISION_TIMEOUT", "5.0"))
        self._client = None
        self._client_lock = threading.Lock()
        self._health = VisionProviderHealth(provider_id=self.provider_id)

    def _get_client(self):
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            if not self._api_key:
                return None
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.NVIDIA_BASE_URL,
                    api_key=self._api_key,
                    timeout=self._timeout,
                )
                log.info("[gemma_4_31b] NVIDIA NIM vision client initialized (timeout=%.1fs)", self._timeout)
                return self._client
            except Exception as exc:
                log.error("[gemma_4_31b] Client init failed: %s", sanitize_error(exc))
                return None

    def analyze(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        client = self._get_client()
        if not client:
            return None

        try:
            # Build multimodal message
            content: list = [{"type": "text", "text": prompt}]
            if image_b64:
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                })

            resp = client.chat.completions.create(
                model=self.MODEL_ID,
                messages=[{"role": "user", "content": content}],
                max_tokens=kwargs.get("max_tokens", 512),
                temperature=kwargs.get("temperature", 0.3),
            )
            text = resp.choices[0].message.content if resp.choices else None
            if text:
                self._health.record_success()
            return text
        except Exception as exc:
            self._health.record_failure(str(exc))
            log.warning("[gemma_4_31b] Analyze failed: %s", sanitize_error(exc))
            return None

    def health_check(self) -> VisionProviderHealth:
        if not self._api_key:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = "No API key configured"
            self._health.last_check = time.time()
            return self._health

        client = self._get_client()
        if not client:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = "Client initialization failed"
            self._health.last_check = time.time()
            return self._health

        try:
            models = client.models.list()
            self._health.available = True
            self._health.status = ProviderStatus.AVAILABLE
            self._health.last_error = ""
        except Exception as exc:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = sanitize_error(exc)
        self._health.last_check = time.time()
        return self._health

    def get_model_name(self) -> str:
        return self.MODEL_ID


# ── Fallback Resilient Vision Provider (P0) ─────────────────────────────────

class FallbackVisionProvider(VisionProvider):
    """
    Resilient Vision Provider: Primary candidate with deterministic failover to local Moondream.

    Guarantees:
      - Fail-fast configurable timeout (default 5.0s via NVIDIA_VISION_TIMEOUT)
      - Strips all API credentials before logging errors
      - Preserves request_id / turn_id throughout the pipeline
      - Logs primary failure and fallback selection clearly
      - Returns valid analysis from local Moondream whenever fallback succeeds
      - Gated by feature flag (ENABLE_NVIDIA_VISION)
    """

    provider_id = "resilient_vision"

    def __init__(
        self,
        primary: Optional[VisionProvider] = None,
        fallback: Optional[VisionProvider] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        import os
        self.primary = primary
        self.fallback = fallback or MoondreamLocalProvider()
        self.timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_VISION_TIMEOUT", "5.0"))
        self.enabled = (
            enabled if enabled is not None
            else os.getenv("ENABLE_NVIDIA_VISION", "false").lower() in ("true", "1", "yes")
        )
        self._health = VisionProviderHealth(provider_id=self.provider_id)

    def analyze(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        turn_id = kwargs.get("turn_id") or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"

        # If feature flag disabled or primary unavailable, route directly to local Moondream
        if not self.enabled or not self.primary:
            log.debug("[Vision] Primary disabled by feature flag (turn_id=%s) -> routing directly to fallback '%s'",
                      turn_id, self.fallback.provider_id)
            return self.fallback.analyze(prompt, image_b64=image_b64, **kwargs)

        primary_failed = False
        error_msg = ""

        try:
            res = self.primary.analyze(prompt, image_b64=image_b64, **kwargs)
            if res:
                self._health.record_success()
                return res
            else:
                primary_failed = True
                error_msg = "Primary returned empty analysis"
        except Exception as exc:
            primary_failed = True
            error_msg = sanitize_error(exc)

        if primary_failed:
            log.warning(
                "[VISION-FALLBACK] Primary '%s' failed (turn_id=%s): %s. Falling back to '%s'",
                self.primary.provider_id, turn_id, error_msg, self.fallback.provider_id
            )
            self._health.record_failure(error_msg)

            fallback_res = self.fallback.analyze(prompt, image_b64=image_b64, **kwargs)
            if fallback_res:
                log.info(
                    "[VISION-FALLBACK] Fallback '%s' succeeded for turn_id=%s (%d chars)",
                    self.fallback.provider_id, turn_id, len(fallback_res)
                )
            return fallback_res

        return None

    def health_check(self) -> VisionProviderHealth:
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

    def get_model_name(self) -> str:
        if self.enabled and self.primary:
            return f"{self.primary.get_model_name()}-resilient->{self.fallback.get_model_name()}"
        return self.fallback.get_model_name()


# ── Vision Provider Registry ────────────────────────────────────────────────

class VisionProviderRegistry:
    """Thread-safe registry of all available vision providers."""

    def __init__(self):
        self._providers: Dict[str, VisionProvider] = {}
        self._lock = threading.Lock()

    def register(self, provider: VisionProvider) -> None:
        with self._lock:
            self._providers[provider.provider_id] = provider
            log.info("Registered vision provider: %s (%s)", provider.provider_id, provider.get_model_name())

    def unregister(self, provider_id: str) -> bool:
        """Unregister a provider by ID. Returns True if removed."""
        with self._lock:
            if provider_id in self._providers:
                del self._providers[provider_id]
                log.info("Unregistered vision provider: %s", provider_id)
                return True
            return False

    def get(self, provider_id: str) -> Optional[VisionProvider]:
        return self._providers.get(provider_id)

    def list_providers(self) -> List[str]:
        return list(self._providers.keys())

    def get_resilient_provider(
        self,
        primary_id: str = "gemma_4_31b",
        fallback_id: str = "moondream_local",
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> FallbackVisionProvider:
        """Create a resilient vision provider wrapping primary and fallback."""
        primary = self.get(primary_id)
        fallback = self.get(fallback_id) or MoondreamLocalProvider()
        return FallbackVisionProvider(primary=primary, fallback=fallback, timeout=timeout, enabled=enabled)

    def analyze_with_fallback(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        primary_id: str = "gemma_4_31b",
        fallback_id: str = "moondream_local",
        **kwargs,
    ) -> Optional[str]:
        """Helper to analyze image with automatic fallback."""
        resilient = self.get_resilient_provider(primary_id=primary_id, fallback_id=fallback_id)
        return resilient.analyze(prompt, image_b64=image_b64, **kwargs)

    def health_check_all(self) -> Dict[str, VisionProviderHealth]:
        results = {}
        for pid, provider in self._providers.items():
            try:
                results[pid] = provider.health_check()
            except Exception as exc:
                results[pid] = VisionProviderHealth(
                    provider_id=pid, available=False, last_error=str(exc)
                )
        return results


# ── Module-level singleton ───────────────────────────────────────────────────

vision_registry = VisionProviderRegistry()


def initialize_vision_providers(nvidia_api_key: str = "") -> VisionProviderRegistry:
    """Initialize all vision providers and register them."""
    moondream = MoondreamLocalProvider()
    vision_registry.register(moondream)

    gemma = Gemma4VisionProvider(api_key=nvidia_api_key)
    vision_registry.register(gemma)

    return vision_registry

