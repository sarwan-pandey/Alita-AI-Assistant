"""
Provider Contracts — Unified Interface Specifications for MJ/ALITA
===================================================================
Defines the standard abstract contracts, health/readiness states,
and data models that the MJ core depends upon.

Core modules must depend ONLY on these contracts and the provider
orchestrator, never directly on concrete legacy engines.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Generator, List, Optional

log = logging.getLogger("alita.provider_contracts")


# ── Provider Health / Readiness Status ───────────────────────────────────────

class ProviderStatus(str, Enum):
    """
    Standard readiness and operational status for any provider.
    - AVAILABLE: Ready for production traffic; passed readiness checks.
    - DEGRADED: Operational but experiencing elevated latency or partial issues.
    - UNAVAILABLE: Unusable (missing key, broken connection, unready, or offline).
    """
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass
class ProviderHealth:
    """Universal health status tracked across all providers."""
    provider_id: str
    status: ProviderStatus = ProviderStatus.UNAVAILABLE
    available: bool = False
    last_check: float = 0.0
    last_error: str = ""
    consecutive_failures: int = 0
    avg_latency_ms: float = 0.0

    def record_success(self, latency_ms: float = 0.0) -> None:
        self.available = True
        self.status = ProviderStatus.AVAILABLE
        self.consecutive_failures = 0
        self.last_error = ""
        self.last_check = time.time()
        if latency_ms > 0:
            if self.avg_latency_ms == 0:
                self.avg_latency_ms = latency_ms
            else:
                self.avg_latency_ms = 0.7 * self.avg_latency_ms + 0.3 * latency_ms

    def record_failure(self, error: str) -> None:
        self.consecutive_failures += 1
        self.last_error = error
        self.last_check = time.time()
        if self.consecutive_failures >= 3:
            self.available = False
            self.status = ProviderStatus.UNAVAILABLE
        else:
            self.status = ProviderStatus.DEGRADED

    def is_ready(self) -> bool:
        """Provider is considered ready if AVAILABLE or DEGRADED (can still respond)."""
        return self.status in (ProviderStatus.AVAILABLE, ProviderStatus.DEGRADED) and self.available


# Backward compatibility aliases for existing health classes
@dataclass
class TTSProviderHealth(ProviderHealth):
    pass


@dataclass
class VisionProviderHealth(ProviderHealth):
    pass


# ── LLM Provider Contract ────────────────────────────────────────────────────

class LLMProviderContract(ABC):
    """Abstract interface contract for conversational LLM providers."""

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
        """Streaming chat completion. Yields token chunks or returns None on failure."""
        ...

    @abstractmethod
    def health_check(self) -> ProviderHealth:
        """Perform health and readiness check."""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the model identifier string."""
        ...

    def get_status(self) -> ProviderStatus:
        """Return the current readiness status."""
        health = self.health_check()
        return health.status


# ── TTS Provider Contract ────────────────────────────────────────────────────

class TTSProviderContract(ABC):
    """Abstract interface contract for text-to-speech synthesis providers."""

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
        Synthesize text into WAV audio bytes (16-bit PCM).
        Returns valid audio bytes or empty bytes on failure.
        """
        ...

    @abstractmethod
    def health_check(self) -> TTSProviderHealth:
        """Perform health and readiness check."""
        ...

    @abstractmethod
    def get_provider_name(self) -> str:
        """Return human-readable provider name."""
        ...

    @abstractmethod
    def list_voices(self) -> List[Dict[str, Any]]:
        """Return list of supported voice models with metadata."""
        ...

    def get_status(self) -> ProviderStatus:
        """Return current readiness status."""
        health = self.health_check()
        return health.status


# ── Vision Provider Contract ─────────────────────────────────────────────────

class VisionProviderContract(ABC):
    """Abstract interface contract for multimodal vision providers."""

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
        Returns analysis text or None on failure.
        """
        ...

    @abstractmethod
    def health_check(self) -> VisionProviderHealth:
        """Perform health and readiness check."""
        ...

    @abstractmethod
    def get_model_name(self) -> str:
        """Return the vision model identifier string."""
        ...

    def get_status(self) -> ProviderStatus:
        """Return current readiness status."""
        health = self.health_check()
        return health.status
