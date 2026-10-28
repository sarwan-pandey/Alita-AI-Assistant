"""
NVIDIA Nemotron-3.5-Lightning-30B-A3B — Streaming Provider with Metrics
========================================================================
Production-grade streaming LLM client for the NVIDIA NIM Lightning model.

Features:
  - OpenAI-compatible streaming via SSE
  - Detailed latency metrics: request start, first token, first sentence, completion
  - Token count capture (prompt + completion)
  - Reasoning mode control (disabled by default for fast voice)
  - Configurable model ID and endpoint
  - Thread-safe singleton client
  - No device execution authority — text generation only

This module is used in SHADOW/BENCHMARK mode. It does NOT route production
traffic. Production traffic remains on Qwen local via ollama_client.py.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional, Tuple

log = logging.getLogger("alita.nvidia_lightning")


# ── Metrics Capture ──────────────────────────────────────────────────────────

@dataclass
class LightningMetrics:
    """Detailed timing and token metrics for a single Lightning request."""

    # Timing (seconds since epoch or relative)
    request_start: float = 0.0
    first_token_time: float = 0.0
    first_sentence_time: float = 0.0
    response_complete_time: float = 0.0

    # Derived latencies (milliseconds)
    ttft_ms: float = 0.0        # Time to first token
    ttfs_ms: float = 0.0        # Time to first sentence
    total_ms: float = 0.0       # Total request duration

    # Token counts
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    # Content
    response_text: str = ""
    prompt_preview: str = ""     # First 80 chars of user message

    # Status
    success: bool = False
    error: str = ""
    model_id: str = ""
    provider: str = ""
    reasoning_enabled: bool = False

    def finalize(self) -> None:
        """Compute derived latency fields after all timestamps are set."""
        if self.first_token_time and self.request_start:
            self.ttft_ms = (self.first_token_time - self.request_start) * 1000
        if self.first_sentence_time and self.request_start:
            self.ttfs_ms = (self.first_sentence_time - self.request_start) * 1000
        if self.response_complete_time and self.request_start:
            self.total_ms = (self.response_complete_time - self.request_start) * 1000

    def summary(self) -> str:
        """One-line summary for logging."""
        status = "OK" if self.success else f"FAIL({self.error[:40]})"
        return (
            f"[{self.provider}] {status} | "
            f"TTFT={self.ttft_ms:.0f}ms | TTFS={self.ttfs_ms:.0f}ms | "
            f"Total={self.total_ms:.0f}ms | "
            f"Tokens={self.prompt_tokens}+{self.completion_tokens}={self.total_tokens} | "
            f"Response={len(self.response_text)} chars"
        )


# ── Sentence Detection ──────────────────────────────────────────────────────

_SENTENCE_END = re.compile(r'[.!?]\s|[.!?]$')

# Pattern to strip leaked thinking/reasoning preambles from model output
_THINKING_PREAMBLE = re.compile(
    r"^(?:Here'?s\s+(?:a|my)\s+thinking\s+process:?\s*\n+"
    r"|Let\s+me\s+think.*?\n+"
    r"|<think>[\s\S]*?</think>\s*"
    r")",
    re.IGNORECASE | re.DOTALL,
)


def _has_complete_sentence(text: str) -> bool:
    """Check if accumulated text contains at least one complete sentence."""
    return bool(_SENTENCE_END.search(text))


# ── Lightning Client ─────────────────────────────────────────────────────────

class NvidiaLightningClient:
    """
    Streaming client for Nemotron-3.5-Lightning-30B-A3B via NVIDIA NIM API.

    Usage:
        client = NvidiaLightningClient(api_key="nvapi-xxx")
        metrics = client.chat_with_metrics(messages, max_tokens=300)
        print(metrics.summary())
    """

    DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
    DEFAULT_MODEL_ID = "nvidia/nemotron-3.5-lightning-30b-a3b"

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: str = "",
        model_id: str = "",
        timeout: Optional[float] = None,
    ):
        # None = "use env var", "" = "explicitly no key"
        self._api_key = api_key if api_key is not None else os.getenv("NVIDIA_API_KEY", "")
        self._base_url = base_url or os.getenv("NVIDIA_LIGHTNING_URL", self.DEFAULT_BASE_URL)
        self._model_id = model_id or os.getenv("NVIDIA_LIGHTNING_MODEL", self.DEFAULT_MODEL_ID)
        self._timeout = timeout if timeout is not None else float(os.getenv("NVIDIA_LLM_TIMEOUT", "5.0"))
        self._client = None
        self._client_lock = threading.Lock()

    def _get_client(self):
        """Lazy-init OpenAI-compatible client with fail-fast timeout."""
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            if not self._api_key:
                log.debug("[lightning] No NVIDIA_API_KEY — client disabled")
                return None
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    base_url=self._base_url,
                    api_key=self._api_key,
                    timeout=self._timeout,
                    max_retries=0,
                )
                log.info("[lightning] Client initialized → %s (%s, timeout=%.1fs, max_retries=0)", self._base_url, self._model_id, self._timeout)
                return self._client
            except Exception as exc:
                log.error("[lightning] Client init failed: %s", exc)
                return None

    @property
    def available(self) -> bool:
        """Check if the client can be initialized (has API key)."""
        return bool(self._api_key)

    @property
    def model_id(self) -> str:
        return self._model_id

    # ── Streaming Chat with Metrics ──────────────────────────────────────

    def chat_with_metrics(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.6,
        enable_reasoning: bool = False,
        timeout: float = 30.0,
    ) -> LightningMetrics:
        """
        Stream a chat completion and capture detailed timing metrics.

        Args:
            messages: OpenAI-format messages list
            max_tokens: Maximum response tokens
            temperature: Generation temperature
            enable_reasoning: If True, enables chain-of-thought mode (slower)
            timeout: Request timeout in seconds

        Returns:
            LightningMetrics with all timing and content data
        """
        metrics = LightningMetrics(
            provider="nemotron_lightning",
            model_id=self._model_id,
            reasoning_enabled=enable_reasoning,
        )

        # Capture prompt preview
        for msg in reversed(messages):
            if msg.get("role") == "user":
                metrics.prompt_preview = msg.get("content", "")[:80]
                break

        client = self._get_client()
        if not client:
            metrics.error = "No API key configured or client init failed"
            metrics.response_complete_time = time.time()
            metrics.finalize()
            return metrics

        metrics.request_start = time.time()

        try:
            # Build extra_body for reasoning control
            # Explicitly disable thinking for fast voice responses
            extra_body: Dict[str, Any] = {
                "chat_template_kwargs": {
                    "enable_thinking": enable_reasoning,
                },
            }

            stream = client.chat.completions.create(
                model=self._model_id,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
                stream=True,
                stream_options={"include_usage": True},
                extra_body=extra_body,
            )

            accumulated = []
            first_token_captured = False
            first_sentence_captured = False
            accumulated_text = ""

            for chunk in stream:
                # Capture usage from the final chunk
                if hasattr(chunk, "usage") and chunk.usage:
                    metrics.prompt_tokens = chunk.usage.prompt_tokens or 0
                    metrics.completion_tokens = chunk.usage.completion_tokens or 0
                    metrics.total_tokens = chunk.usage.total_tokens or 0

                if not chunk.choices:
                    continue

                delta = chunk.choices[0].delta
                if not delta or not delta.content:
                    continue

                token_text = delta.content

                # First token timing
                if not first_token_captured:
                    metrics.first_token_time = time.time()
                    first_token_captured = True

                accumulated.append(token_text)
                accumulated_text += token_text

                # First complete sentence timing
                if not first_sentence_captured and _has_complete_sentence(accumulated_text):
                    metrics.first_sentence_time = time.time()
                    first_sentence_captured = True

            raw_text = accumulated_text.strip()

            # Strip any leaked thinking/reasoning preambles
            if not enable_reasoning:
                raw_text = _THINKING_PREAMBLE.sub("", raw_text).strip()
                # Also strip inline <think> tags
                raw_text = re.sub(r"<think>[\s\S]*?</think>", "", raw_text, flags=re.DOTALL).strip()

            metrics.response_text = raw_text
            metrics.response_complete_time = time.time()
            metrics.success = bool(metrics.response_text)

            if not metrics.success:
                metrics.error = "Empty response (possibly all thinking tokens)"

        except Exception as exc:
            metrics.error = str(exc)
            metrics.response_complete_time = time.time()
            log.warning("[lightning] Streaming failed: %s", exc)

        metrics.finalize()
        return metrics

    # ── Non-streaming Chat (simple) ──────────────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.6,
    ) -> Optional[str]:
        """Simple non-streaming chat. Returns text or None."""
        metrics = self.chat_with_metrics(messages, max_tokens, temperature)
        return metrics.response_text if metrics.success else None

    # ── Health Check ─────────────────────────────────────────────────────

    def health_check(self) -> Dict[str, Any]:
        """Quick health probe."""
        if not self._api_key:
            return {"available": False, "error": "No API key configured"}

        client = self._get_client()
        if not client:
            return {"available": False, "error": "Client init failed"}

        try:
            models = client.models.list()
            model_ids = [m.id for m in models.data] if hasattr(models, "data") else []
            return {
                "available": True,
                "model": self._model_id,
                "endpoint": self._base_url,
                "models_accessible": len(model_ids),
            }
        except Exception as exc:
            return {"available": False, "error": str(exc)}


# ── Module-level singleton ───────────────────────────────────────────────────

_lightning_client: Optional[NvidiaLightningClient] = None
_lightning_lock = threading.Lock()


def get_lightning_client() -> NvidiaLightningClient:
    """Get or create the singleton Lightning client."""
    global _lightning_client
    if _lightning_client is not None:
        return _lightning_client
    with _lightning_lock:
        if _lightning_client is not None:
            return _lightning_client
        _lightning_client = NvidiaLightningClient()
        return _lightning_client
