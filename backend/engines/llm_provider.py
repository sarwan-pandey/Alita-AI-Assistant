"""
LLM Provider Abstraction — Unified Multi-Model Interface
=========================================================
Provides a common interface for all LLM providers so that production code
can route between providers without changing call sites.

IMPORTANT: This module does NOT change production behavior. The active
provider is determined by configuration. Current production default
remains "qwen_local" (Ollama Qwen3 4B).

Supported providers:
  - qwen_local      → Ollama local (current production)
  - nemotron_lightning → NVIDIA NIM Nemotron-3.5-Lightning-30B-A3B
  - nemotron_super    → NVIDIA NIM Nemotron-3-Super-120B-A12B
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional

from engines.provider_contracts import (
    LLMProviderContract,
    ProviderHealth,
    ProviderStatus,
)

log = logging.getLogger("alita.llm_provider")


# ── Abstract Base Provider ───────────────────────────────────────────────────

class LLMProvider(LLMProviderContract):
    """Abstract base class for LLM providers, implementing LLMProviderContract."""
    provider_id: str = "unknown"

    @abstractmethod
    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[str]:
        """Synchronous chat completion. Returns response text or None on failure."""
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[Generator[str, None, None]]:
        """Streaming chat completion. Returns a generator of text chunks or None."""
        ...

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Check provider availability. Returns ProviderHealth."""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier string."""
        ...


# ── Qwen Local Provider (Ollama) ─────────────────────────────────────────────

class QwenLocalProvider(LLMProvider):
    """
    Local Qwen3 4B via Ollama — current production provider.
    Wraps the existing ollama_client module without modifying it.
    """

    provider_id = "qwen_local"

    def __init__(self):
        self._health = ProviderHealth(provider_id=self.provider_id)

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[str]:
        t0 = time.perf_counter()
        try:
            from ollama_client import ollama_chat_messages, get_model_name
            result = ollama_chat_messages(
                messages=messages,
                model=kwargs.get("model") or get_model_name(),
                max_tokens=max_tokens,
                temperature=temperature,
            )
            latency = (time.perf_counter() - t0) * 1000
            if result:
                self._health.record_success(latency)
                return result
            else:
                self._health.record_failure("Empty response from Ollama")
                return None
        except Exception as exc:
            self._health.record_failure(str(exc))
            log.warning("[qwen_local] Chat failed: %s", exc)
            return None

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[Generator[str, None, None]]:
        try:
            from ollama_client import ollama_chat
            stream = ollama_chat(
                prompt="",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
            )
            if stream is None:
                return None

            def _gen():
                for chunk in stream:
                    if hasattr(chunk, "choices") and chunk.choices:
                        delta = chunk.choices[0].delta
                        if delta and getattr(delta, "content", None):
                            yield delta.content
                    elif isinstance(chunk, str):
                        yield chunk

            return _gen()
        except Exception as exc:
            self._health.record_failure(str(exc))
            log.warning("[qwen_local] Stream failed: %s", exc)
            return None

    def health_check(self) -> ProviderHealth:
        try:
            from ollama_client import is_ollama_running, get_model_name
            if is_ollama_running():
                self._health.available = True
                self._health.status = ProviderStatus.AVAILABLE
                self._health.last_check = time.time()
                self._health.last_error = ""
            else:
                self._health.available = False
                self._health.status = ProviderStatus.UNAVAILABLE
                self._health.last_error = "Ollama not running"
                self._health.last_check = time.time()
        except Exception as exc:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = str(exc)
            self._health.last_check = time.time()
        return self._health

    def get_model_name(self) -> str:
        try:
            from ollama_client import get_model_name as _get
            return _get()
        except Exception:
            return "qwen3:4b-instruct"


# ── Credential Sanitization Helper ───────────────────────────────────────────

def sanitize_error(error: Any) -> str:
    """Strip API keys and credentials from error strings to prevent leakage."""
    if not error:
        return ""
    s = str(error)
    s = re.sub(r"nvapi-[A-Za-z0-9_\-]+", "nvapi-[REDACTED]", s)
    s = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    return s


# ── NVIDIA NIM Provider (Nemotron Lightning / Super) ─────────────────────────

class NvidiaNIMProvider(LLMProvider):
    """
    NVIDIA NIM cloud LLM provider — OpenAI-compatible API.
    Supports both Nemotron-3.5-Lightning-30B-A3B and Nemotron-3-Super-120B-A12B.

    NOT activated for production traffic. Available for testing and future migration.
    """

    NVIDIA_BASE_URL = "https://integrate.api.nvidia.com/v1"

    def __init__(
        self,
        provider_id: str,
        model_id: str,
        api_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ):
        self.provider_id = provider_id
        self._model_id = model_id
        self._api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY", "").strip()
        self._timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_LLM_TIMEOUT", "5.0"))
        self._client = None
        self._client_lock = threading.Lock()
        self._health = ProviderHealth(provider_id=provider_id)

    def _get_client(self):
        """Lazy-initialize the OpenAI client for NVIDIA NIM with fail-fast timeout."""
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            if not self._api_key:
                log.debug("[%s] No API key configured — provider disabled", self.provider_id)
                return None
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self.NVIDIA_BASE_URL,
                    api_key=self._api_key,
                    timeout=self._timeout,
                    max_retries=0,
                )
                log.info("[%s] NVIDIA NIM client initialized → %s (timeout=%.1fs, max_retries=0)", self.provider_id, self._model_id, self._timeout)
                return self._client
            except Exception as exc:
                log.error("[%s] Client init failed: %s", self.provider_id, sanitize_error(exc))
                return None

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[str]:
        client = self._get_client()
        if not client:
            return None

        t0 = time.perf_counter()
        try:
            extra_body = kwargs.get("extra_body", {})
            resp = client.chat.completions.create(
                model=self._model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                extra_body=extra_body,
            )
            latency = (time.perf_counter() - t0) * 1000
            text = resp.choices[0].message.content if resp.choices else None
            if text:
                self._health.record_success(latency)
                log.info("[%s] Response: %d chars in %.0fms", self.provider_id, len(text), latency)
                return text
            else:
                self._health.record_failure("Empty response")
                return None
        except Exception as exc:
            self._health.record_failure(str(exc))
            log.warning("[%s] Chat failed: %s", self.provider_id, exc)
            return None

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[Generator[str, None, None]]:
        client = self._get_client()
        if not client:
            return None

        try:
            extra_body = kwargs.get("extra_body", {})
            stream = client.chat.completions.create(
                model=self._model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                extra_body=extra_body,
            )

            def _gen():
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        yield chunk.choices[0].delta.content

            return _gen()
        except Exception as exc:
            self._health.record_failure(str(exc))
            log.warning("[%s] Stream failed: %s", self.provider_id, exc)
            return None

    def health_check(self) -> ProviderHealth:
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
            # Lightweight probe: list models (no inference cost)
            models = client.models.list()
            self._health.available = True
            self._health.status = ProviderStatus.AVAILABLE
            self._health.last_error = ""
            self._health.last_check = time.time()
        except Exception as exc:
            self._health.available = False
            self._health.status = ProviderStatus.UNAVAILABLE
            self._health.last_error = str(exc)
            self._health.last_check = time.time()

        return self._health

    def get_model_name(self) -> str:
        return self._model_id


# ── Fallback Resilient LLM Provider (P0) ────────────────────────────────────

class FallbackLLMProvider(LLMProvider):
    """
    Resilient LLM Provider: Primary candidate with deterministic failover to local Qwen.

    Guarantees:
      - Fail-fast configurable timeout (default 5.0s via NVIDIA_LLM_TIMEOUT)
      - Strips all API credentials before logging errors
      - Preserves request_id / turn_id throughout the pipeline
      - Logs primary failure and fallback selection clearly
      - Returns valid response whenever fallback succeeds
      - Gated by feature flag (ENABLE_NVIDIA_LLM)
    """

    provider_id = "resilient_llm"

    def __init__(
        self,
        primary: Optional[LLMProvider] = None,
        fallback: Optional[LLMProvider] = None,
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        self.primary = primary
        self.fallback = fallback or QwenLocalProvider()
        self.timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_LLM_TIMEOUT", "5.0"))
        self.enabled = (
            enabled if enabled is not None
            else os.getenv("ENABLE_NVIDIA_LLM", "false").lower() in ("true", "1", "yes")
        )
        self._health = ProviderHealth(provider_id=self.provider_id)

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[str]:
        turn_id = kwargs.get("turn_id") or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"

        # Gated by feature flag: if disabled or no primary configured, route directly to fallback
        if not self.enabled or not self.primary:
            log.debug("[LLM] Primary disabled by feature flag (turn_id=%s) -> routing directly to fallback '%s'",
                      turn_id, self.fallback.provider_id)
            return self.fallback.chat(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)

        t0 = time.perf_counter()
        primary_failed = False
        error_msg = ""

        try:
            res = self.primary.chat(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)
            if res:
                self._health.record_success((time.perf_counter() - t0) * 1000)
                return res
            else:
                primary_failed = True
                error_msg = "Primary returned empty response"
        except Exception as exc:
            primary_failed = True
            error_msg = sanitize_error(exc)

        if primary_failed:
            log.warning(
                "[LLM-FALLBACK] Primary '%s' failed (turn_id=%s): %s. Falling back to '%s'",
                self.primary.provider_id, turn_id, error_msg, self.fallback.provider_id
            )
            self._health.record_failure(error_msg)

            fallback_res = self.fallback.chat(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)
            if fallback_res:
                log.info(
                    "[LLM-FALLBACK] Fallback '%s' succeeded for turn_id=%s (%d chars)",
                    self.fallback.provider_id, turn_id, len(fallback_res)
                )
            return fallback_res

        return None

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        **kwargs,
    ) -> Optional[Generator[str, None, None]]:
        turn_id = kwargs.get("turn_id") or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"

        if not self.enabled or not self.primary:
            log.debug("[LLM] Primary disabled by feature flag (turn_id=%s) -> stream directly via fallback '%s'",
                      turn_id, self.fallback.provider_id)
            return self.fallback.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)

        try:
            stream = self.primary.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)
            if stream is None:
                raise RuntimeError("Primary stream returned None")

            def _generator():
                yielded_any = False
                try:
                    for chunk in stream:
                        yielded_any = True
                        yield chunk
                except Exception as exc:
                    error_msg = sanitize_error(exc)
                    log.warning("[LLM-FALLBACK] Primary stream error (turn_id=%s, yielded=%s): %s",
                                turn_id, yielded_any, error_msg)
                    if not yielded_any:
                        log.info("[LLM-FALLBACK] Switching stream to fallback '%s' (turn_id=%s)",
                                 self.fallback.provider_id, turn_id)
                        fb_stream = self.fallback.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)
                        if fb_stream:
                            for chunk in fb_stream:
                                yield chunk

            return _generator()
        except Exception as exc:
            error_msg = sanitize_error(exc)
            log.warning("[LLM-FALLBACK] Primary stream init failed (turn_id=%s): %s. Falling back to '%s'",
                        turn_id, error_msg, self.fallback.provider_id)
            return self.fallback.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, **kwargs)

    def health_check(self) -> ProviderHealth:
        # Fallback is available if either primary or fallback is available
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


# ── Provider Registry ────────────────────────────────────────────────────────

class LLMProviderRegistry:
    """
    Thread-safe registry of all available LLM providers.
    Does NOT select a provider automatically — callers must explicitly
    request a provider by ID or resilient routing.
    """

    def __init__(self):
        self._providers: Dict[str, LLMProvider] = {}
        self._lock = threading.Lock()

    def register(self, provider: LLMProvider) -> None:
        """Register a provider. Overwrites if ID already exists."""
        with self._lock:
            self._providers[provider.provider_id] = provider
            log.info("Registered LLM provider: %s (%s)", provider.provider_id, provider.get_model_name())

    def unregister(self, provider_id: str) -> bool:
        """Unregister a provider by ID. Returns True if removed."""
        with self._lock:
            if provider_id in self._providers:
                del self._providers[provider_id]
                log.info("Unregistered LLM provider: %s", provider_id)
                return True
            return False

    def get(self, provider_id: str) -> Optional[LLMProvider]:
        """Get a provider by ID. Returns None if not registered."""
        return self._providers.get(provider_id)

    def list_providers(self) -> List[str]:
        """List all registered provider IDs."""
        return list(self._providers.keys())

    def get_resilient_provider(
        self,
        primary_id: str = "nemotron_lightning",
        fallback_id: str = "qwen_local",
        timeout: Optional[float] = None,
        enabled: Optional[bool] = None,
    ) -> FallbackLLMProvider:
        """Create a resilient provider wrapping primary and fallback."""
        primary = self.get(primary_id)
        fallback = self.get(fallback_id) or QwenLocalProvider()
        return FallbackLLMProvider(primary=primary, fallback=fallback, timeout=timeout, enabled=enabled)

    def chat_with_fallback(
        self,
        messages: List[Dict[str, str]],
        primary_id: str = "nemotron_lightning",
        fallback_id: str = "qwen_local",
        **kwargs,
    ) -> Optional[str]:
        """Helper to execute chat with automatic fallback."""
        resilient = self.get_resilient_provider(primary_id=primary_id, fallback_id=fallback_id)
        return resilient.chat(messages, **kwargs)

    def health_check_all(self) -> Dict[str, ProviderHealth]:
        """Run health checks on all registered providers."""
        results = {}
        for pid, provider in self._providers.items():
            try:
                results[pid] = provider.health_check()
            except Exception as exc:
                results[pid] = ProviderHealth(
                    provider_id=pid, available=False, last_error=str(exc)
                )
        return results


# ── Module-level singleton ───────────────────────────────────────────────────

llm_registry = LLMProviderRegistry()


def initialize_providers(nvidia_api_key: str = "") -> LLMProviderRegistry:
    """
    Initialize all LLM providers and register them.
    Called once during application startup.

    Current production provider (qwen_local) is always registered.
    NVIDIA providers are registered but only usable if API key is configured.
    """
    # Always register the local Qwen provider (current production)
    qwen = QwenLocalProvider()
    llm_registry.register(qwen)

    key = nvidia_api_key or os.getenv("NVIDIA_API_KEY", "")
    # Register NVIDIA NIM providers (dormant unless API key provided)
    lightning = NvidiaNIMProvider(
        provider_id="nemotron_lightning",
        model_id="nvidia/nemotron-3.5-lightning-30b-a3b",
        api_key=key,
    )
    llm_registry.register(lightning)

    super_provider = NvidiaNIMProvider(
        provider_id="nemotron_super",
        model_id="nvidia/nemotron-3-super-120b-a12b",
        api_key=nvidia_api_key,
    )
    llm_registry.register(super_provider)

    return llm_registry

