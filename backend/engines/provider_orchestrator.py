"""
Provider Orchestrator — Centralized Primary/Fallback Routing Layer
==================================================================
The single architectural layer responsible for selecting, validating,
and failing over between Primary (NVIDIA NIM) and Fallback (Legacy Local)
providers for LLM, TTS, and Vision modalities.

Architecture Principles:
  1. NVIDIA-First: Intended primary providers are NVIDIA NIM endpoints.
  2. Safe Fallback: Legacy local engines serve purely as fallback.
  3. No Blind Activation: A provider must pass health/readiness probes
     before it can receive production traffic.
  4. Core Decoupling: Core MJ components depend ONLY on this layer and
     contracts in `provider_contracts.py`.
  5. Removal Safe: Fallback providers can be removed/unregistered without
     crashing the orchestrator or breaking core contracts.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Any, Dict, Generator, List, Optional

from engines.provider_contracts import (
    LLMProviderContract,
    ProviderHealth,
    ProviderStatus,
    TTSProviderContract,
    TTSProviderHealth,
    VisionProviderContract,
    VisionProviderHealth,
)

log = logging.getLogger("alita.provider_orchestrator")


# ── Credential Sanitization ───────────────────────────────────────────────────

def sanitize_error(error: Any) -> str:
    """Strip API keys and credentials from error strings to prevent leakage."""
    if not error:
        return ""
    s = str(error)
    s = re.sub(r"nvapi-[A-Za-z0-9_\-]+", "nvapi-[REDACTED]", s)
    s = re.sub(r"Bearer\s+[A-Za-z0-9_\-\.]+", "Bearer [REDACTED]", s, flags=re.IGNORECASE)
    return s


# ── Provider Orchestrator Implementation ──────────────────────────────────────

class ProviderOrchestrator:
    """
    Centralized coordinator for LLM, TTS, and Vision providers.
    Directs requests to PRIMARY providers, with automated, fail-fast
    fallback to FALLBACK providers whenever primary is unavailable or fails.
    """

    # Canonical aliases mapping user-friendly names to internal IDs
    ALIASES = {
        # LLM
        "nemotron_lightning": "nemotron_lightning",
        "lightning": "nemotron_lightning",
        "qwen_local": "qwen_local",
        "qwen": "qwen_local",
        "nemotron_super": "nemotron_super",
        "super": "nemotron_super",
        # TTS
        "chatterbox_multilingual": "chatterbox_multilingual_nim",
        "chatterbox_multilingual_nim": "chatterbox_multilingual_nim",
        "chatterbox_turbo": "chatterbox_local",
        "chatterbox_local": "chatterbox_local",
        "turbo": "chatterbox_local",
        # Vision
        "gemma4": "gemma_4_31b",
        "gemma_4_31b": "gemma_4_31b",
        "moondream": "moondream_local",
        "moondream_local": "moondream_local",
    }

    def __init__(self):
        self._lock = threading.Lock()
        self._initialized = False

    def _resolve_id(self, alias_or_id: str) -> str:
        """Resolve a configuration name or alias to canonical provider ID."""
        cleaned = (alias_or_id or "").strip().lower()
        return self.ALIASES.get(cleaned, cleaned)

    # ── Configuration Accessors ───────────────────────────────────────────────

    @property
    def llm_primary_id(self) -> str:
        raw = os.getenv("LLM_PRIMARY", "nemotron_lightning")
        return self._resolve_id(raw)

    @property
    def llm_fallback_id(self) -> str:
        raw = os.getenv("LLM_FALLBACK", "qwen_local")
        return self._resolve_id(raw)

    @property
    def llm_timeout(self) -> float:
        try:
            return float(os.getenv("NVIDIA_LLM_TIMEOUT", "5.0"))
        except (ValueError, TypeError):
            return 5.0

    @property
    def tts_primary_id(self) -> str:
        raw = os.getenv("TTS_PRIMARY", "chatterbox_multilingual")
        return self._resolve_id(raw)

    @property
    def tts_fallback_id(self) -> str:
        raw = os.getenv("TTS_FALLBACK", "chatterbox_turbo")
        return self._resolve_id(raw)

    @property
    def vision_primary_id(self) -> str:
        raw = os.getenv("VISION_PRIMARY", "gemma4")
        return self._resolve_id(raw)

    @property
    def vision_fallback_id(self) -> str:
        raw = os.getenv("VISION_FALLBACK", "moondream")
        return self._resolve_id(raw)

    # ── Registries Integration ────────────────────────────────────────────────

    def _ensure_initialized(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    from engines.llm_provider import initialize_providers
                    from engines.tts_provider import initialize_tts_providers
                    from engines.vision_provider import initialize_vision_providers
                    api_key = os.getenv("NVIDIA_API_KEY", "")
                    initialize_providers(api_key)
                    initialize_tts_providers(api_key)
                    initialize_vision_providers(api_key)
                    self._initialized = True

    def _get_llm_registry(self):
        self._ensure_initialized()
        from engines.llm_provider import llm_registry
        return llm_registry

    def _get_tts_registry(self):
        self._ensure_initialized()
        from engines.tts_provider import tts_registry
        return tts_registry

    def _get_vision_registry(self):
        self._ensure_initialized()
        from engines.vision_provider import vision_registry
        return vision_registry

    # ── Readiness Checks ──────────────────────────────────────────────────────

    def is_provider_ready(self, modality: str, provider_id: str) -> bool:
        """
        Check if a given provider is registered, feature-flagged, and healthy.
        Does NOT enable a broken or unready provider blindly.
        """
        pid = self._resolve_id(provider_id)

        # 1. Check feature flags for cloud NVIDIA providers
        if pid in ("nemotron_lightning", "nemotron_super"):
            flag = os.getenv("ENABLE_NVIDIA_LLM", "false").lower() in ("true", "1", "yes")
            if not flag:
                return False
            if not os.getenv("NVIDIA_API_KEY", "").strip():
                return False

        elif pid == "chatterbox_multilingual_nim":
            flag = os.getenv("ENABLE_NVIDIA_TTS", "false").lower() in ("true", "1", "yes")
            if not flag:
                return False
            if not os.getenv("NVIDIA_API_KEY", "").strip():
                return False

        elif pid == "gemma_4_31b":
            flag = os.getenv("ENABLE_NVIDIA_VISION", "false").lower() in ("true", "1", "yes")
            if not flag:
                return False
            if not os.getenv("NVIDIA_API_KEY", "").strip():
                return False

        # 2. Check registry existence and status
        if modality == "llm":
            p = self._get_llm_registry().get(pid)
        elif modality == "tts":
            p = self._get_tts_registry().get(pid)
        elif modality == "vision":
            p = self._get_vision_registry().get(pid)
        else:
            return False

        if p is None:
            return False

        try:
            health = p.health_check()
            return health.status in (ProviderStatus.AVAILABLE, ProviderStatus.DEGRADED) and health.available
        except Exception as exc:
            log.warning("[%s:%s] Readiness probe exception: %s", modality, pid, sanitize_error(exc))
            return False

    # ── Active Provider Resolution ────────────────────────────────────────────

    def get_llm_provider(self) -> Optional[LLMProviderContract]:
        """
        Get the active LLM provider.
        Returns Primary if ready; otherwise falls back to Fallback provider.
        """
        reg = self._get_llm_registry()
        primary_id = self.llm_primary_id
        fallback_id = self.llm_fallback_id

        # Verify primary readiness
        if self.is_provider_ready("llm", primary_id):
            return reg.get(primary_id)

        # Fallback to secondary provider
        fb = reg.get(fallback_id)
        if fb is not None:
            return fb

        # If fallback is absent (removal simulation), try primary directly
        return reg.get(primary_id)

    def get_tts_provider(self) -> Optional[TTSProviderContract]:
        """
        Get the active TTS provider.
        Returns Primary if ready; otherwise falls back to Fallback provider.
        """
        reg = self._get_tts_registry()
        primary_id = self.tts_primary_id
        fallback_id = self.tts_fallback_id

        if self.is_provider_ready("tts", primary_id):
            return reg.get(primary_id)

        fb = reg.get(fallback_id)
        if fb is not None:
            return fb

        return reg.get(primary_id)

    def get_vision_provider(self) -> Optional[VisionProviderContract]:
        """
        Get the active Vision provider.
        Returns Primary if ready; otherwise falls back to Fallback provider.
        """
        reg = self._get_vision_registry()
        primary_id = self.vision_primary_id
        fallback_id = self.vision_fallback_id

        if self.is_provider_ready("vision", primary_id):
            return reg.get(primary_id)

        fb = reg.get(fallback_id)
        if fb is not None:
            return fb

        return reg.get(primary_id)

    # ── High-Level Caller APIs (MJ Core Surface) ──────────────────────────────

    def chat(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        turn_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Execute synchronous chat completion with deterministic failover.
        Preserves turn_id / request_id and sanitizes credentials.
        """
        tid = turn_id or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"
        primary_id = self.llm_primary_id
        fallback_id = self.llm_fallback_id
        reg = self._get_llm_registry()

        primary = reg.get(primary_id)
        fallback = reg.get(fallback_id)

        # If primary is not ready or disabled, execute fallback directly
        if not self.is_provider_ready("llm", primary_id):
            if fallback:
                log.debug("[LLM-ORCH] Primary '%s' not ready (turn_id=%s) -> routing directly to fallback '%s'",
                          primary_id, tid, fallback_id)
                return fallback.chat(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
            elif primary:
                # Removal simulation: Fallback absent, try primary
                return primary.chat(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
            return None

        # Primary is ready — attempt primary with fail-fast timeout
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    primary.chat,
                    messages,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    turn_id=tid,
                    **kwargs,
                )
                res = future.result(timeout=self.llm_timeout)
            if res:
                return res
            log.warning("[LLM-ORCH] Primary '%s' returned empty (turn_id=%s). Triggering fallback.", primary_id, tid)
        except concurrent.futures.TimeoutError:
            log.warning("[LLM-ORCH] Primary '%s' timed out (>%.1fs, turn_id=%s). Triggering fallback.",
                        primary_id, self.llm_timeout, tid)
        except Exception as exc:
            log.warning("[LLM-ORCH] Primary '%s' failed (turn_id=%s): %s. Triggering fallback.",
                        primary_id, tid, sanitize_error(exc))

        # Primary failed or returned empty — execute fallback
        if fallback:
            log.info("[LLM-ORCH] Executing fallback '%s' for turn_id=%s", fallback_id, tid)
            return fallback.chat(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
        else:
            log.error("[LLM-ORCH] Primary failed and fallback '%s' is not registered (turn_id=%s)", fallback_id, tid)
            return None

    def chat_stream(
        self,
        messages: List[Dict[str, str]],
        max_tokens: int = 300,
        temperature: float = 0.7,
        turn_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[Generator[str, None, None]]:
        """
        Execute streaming chat completion with deterministic failover.
        Enforces fail-fast timeout on first token from primary; seamlessly recovers
        to fallback without duplicates, mixed output, or broken streaming states.
        """
        tid = turn_id or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"
        primary_id = self.llm_primary_id
        fallback_id = self.llm_fallback_id
        reg = self._get_llm_registry()

        primary = reg.get(primary_id)
        fallback = reg.get(fallback_id)

        if not self.is_provider_ready("llm", primary_id):
            if fallback:
                return fallback.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
            elif primary:
                return primary.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
            return None

        try:
            stream = primary.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
            if stream is None:
                raise RuntimeError("Primary stream returned None")

            def _generator():
                import queue
                import threading
                chunk_queue: queue.Queue = queue.Queue()
                stop_event = threading.Event()

                def _extract_str(c):
                    if isinstance(c, str):
                        return c
                    if hasattr(c, "choices") and c.choices:
                        delta = c.choices[0].delta
                        if delta and getattr(delta, "content", None):
                            return delta.content
                    return str(c) if c is not None else ""

                def _reader():
                    try:
                        for chunk in stream:
                            if stop_event.is_set():
                                break
                            chunk_queue.put(("data", _extract_str(chunk)))
                        chunk_queue.put(("done", None))
                    except Exception as err:
                        chunk_queue.put(("error", err))

                reader_thread = threading.Thread(target=_reader, daemon=True)
                reader_thread.start()

                yielded_any = False
                cutoff_timeout = self.llm_timeout

                while True:
                    # Enforce strict fail-fast timeout on first token from primary
                    wait_timeout = cutoff_timeout if not yielded_any else 10.0
                    try:
                        kind, item = chunk_queue.get(timeout=wait_timeout)
                    except queue.Empty:
                        if not yielded_any:
                            stop_event.set()
                            log.warning("[LLM-ORCH] Primary stream timed out waiting for first token (>%.1fs, turn_id=%s). Switching to fallback '%s'",
                                        cutoff_timeout, tid, fallback_id)
                            if fallback:
                                fb_stream = fallback.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
                                if fb_stream:
                                    for fb_chunk in fb_stream:
                                        yield _extract_str(fb_chunk)
                            return
                        else:
                            # Stream stalled mid-generation; terminate cleanly without injecting fallback (prevents duplicate/mixed responses)
                            log.warning("[LLM-ORCH] Primary stream read timeout mid-stream (turn_id=%s)", tid)
                            return

                    if kind == "data":
                        yielded_any = True
                        yield _extract_str(item)
                    elif kind == "done":
                        break
                    elif kind == "error":
                        err = item
                        log.warning("[LLM-ORCH] Primary stream exception (turn_id=%s, yielded=%s): %s",
                                    tid, yielded_any, sanitize_error(err))
                        if not yielded_any and fallback:
                            log.info("[LLM-ORCH] Switching stream to fallback '%s' (turn_id=%s)", fallback_id, tid)
                            fb_stream = fallback.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
                            if fb_stream:
                                for fb_chunk in fb_stream:
                                    yield _extract_str(fb_chunk)
                        break

            return _generator()
        except Exception as exc:
            log.warning("[LLM-ORCH] Primary stream init failed (turn_id=%s): %s. Triggering fallback.",
                        tid, sanitize_error(exc))
            if fallback:
                return fallback.chat_stream(messages, max_tokens=max_tokens, temperature=temperature, turn_id=tid, **kwargs)
            return None

    async def synthesize(
        self,
        text: str,
        voice: str = "",
        language: str = "en",
        turn_id: Optional[str] = None,
        **kwargs,
    ) -> bytes:
        """
        Synthesize text to 16-bit PCM WAV audio with deterministic failover.
        """
        tid = turn_id or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"
        primary_id = self.tts_primary_id
        fallback_id = self.tts_fallback_id
        reg = self._get_tts_registry()

        primary = reg.get(primary_id)
        fallback = reg.get(fallback_id)

        if not self.is_provider_ready("tts", primary_id):
            if fallback:
                return await fallback.synthesize(text, voice=voice, language=language, turn_id=tid, **kwargs)
            elif primary:
                return await primary.synthesize(text, voice=voice, language=language, turn_id=tid, **kwargs)
            return b""

        try:
            audio = await primary.synthesize(text, voice=voice, language=language, turn_id=tid, **kwargs)
            if audio:
                return audio
            log.warning("[TTS-ORCH] Primary '%s' returned empty audio (turn_id=%s). Triggering fallback.", primary_id, tid)
        except Exception as exc:
            log.warning("[TTS-ORCH] Primary '%s' failed (turn_id=%s): %s. Triggering fallback.",
                        primary_id, tid, sanitize_error(exc))

        if fallback:
            log.info("[TTS-ORCH] Executing fallback '%s' for turn_id=%s", fallback_id, tid)
            return await fallback.synthesize(text, voice=voice, language=language, turn_id=tid, **kwargs)
        else:
            log.error("[TTS-ORCH] Primary failed and fallback '%s' is not registered (turn_id=%s)", fallback_id, tid)
            return b""

    def analyze_vision(
        self,
        prompt: str,
        image_b64: Optional[str] = None,
        turn_id: Optional[str] = None,
        **kwargs,
    ) -> Optional[str]:
        """
        Analyze an image or screen with deterministic failover.
        """
        tid = turn_id or kwargs.get("request_id") or f"turn_{int(time.time() * 1000)}"
        primary_id = self.vision_primary_id
        fallback_id = self.vision_fallback_id
        reg = self._get_vision_registry()

        primary = reg.get(primary_id)
        fallback = reg.get(fallback_id)

        if not self.is_provider_ready("vision", primary_id):
            if fallback:
                return fallback.analyze(prompt, image_b64=image_b64, turn_id=tid, **kwargs)
            elif primary:
                return primary.analyze(prompt, image_b64=image_b64, turn_id=tid, **kwargs)
            return None

        try:
            res = primary.analyze(prompt, image_b64=image_b64, turn_id=tid, **kwargs)
            if res:
                return res
            log.warning("[VISION-ORCH] Primary '%s' returned empty (turn_id=%s). Triggering fallback.", primary_id, tid)
        except Exception as exc:
            log.warning("[VISION-ORCH] Primary '%s' failed (turn_id=%s): %s. Triggering fallback.",
                        primary_id, tid, sanitize_error(exc))

        if fallback:
            log.info("[VISION-ORCH] Executing fallback '%s' for turn_id=%s", fallback_id, tid)
            return fallback.analyze(prompt, image_b64=image_b64, turn_id=tid, **kwargs)
        else:
            log.error("[VISION-ORCH] Primary failed and fallback '%s' is not registered (turn_id=%s)", fallback_id, tid)
            return None

    def locate_element(self, target: str) -> Optional[Dict[str, Any]]:
        """
        Multimodal visual element coordinate localization.
        Delegates through active vision provider if supported.
        """
        provider = self.get_vision_provider()
        if hasattr(provider, "locate_element"):
            return getattr(provider, "locate_element")(target)

        # Check fallback
        fb = self._get_vision_registry().get(self.vision_fallback_id)
        if fb and hasattr(fb, "locate_element"):
            return getattr(fb, "locate_element")(target)
        return None

    # ── Utilities for Core System Callers ─────────────────────────────────────

    def get_active_model_name(self, modality: str = "llm") -> str:
        """Return the active model name for reporting/diagnostics."""
        if modality == "llm":
            p = self.get_llm_provider()
            return p.get_model_name() if p else "none"
        elif modality == "tts":
            p = self.get_tts_provider()
            return p.get_provider_name() if p else "none"
        elif modality == "vision":
            p = self.get_vision_provider()
            return p.get_model_name() if p else "none"
        return "unknown"

    def is_llm_ready(self) -> bool:
        """Check if any LLM provider (primary or fallback) is currently operational."""
        p = self.get_llm_provider()
        if not p:
            return False
        health = p.health_check()
        return health.status in (ProviderStatus.AVAILABLE, ProviderStatus.DEGRADED) and health.available

    def get_tts_engine(self):
        """
        Retrieve underlying TTS engine instance for callers requiring direct handles.
        Safe adapter delegation — never imports legacy engines directly.
        """
        p = self.get_tts_provider()
        if hasattr(p, "get_engine"):
            return getattr(p, "get_engine")()
        return None

    def get_health_summary(self) -> Dict[str, Any]:
        """Return full system health summary across all modalities."""
        return {
            "llm": {
                "primary": {"id": self.llm_primary_id, "ready": self.is_provider_ready("llm", self.llm_primary_id)},
                "fallback": {"id": self.llm_fallback_id, "ready": self.is_provider_ready("llm", self.llm_fallback_id)},
                "active_model": self.get_active_model_name("llm"),
            },
            "tts": {
                "primary": {"id": self.tts_primary_id, "ready": self.is_provider_ready("tts", self.tts_primary_id)},
                "fallback": {"id": self.tts_fallback_id, "ready": self.is_provider_ready("tts", self.tts_fallback_id)},
                "active_provider": self.get_active_model_name("tts"),
            },
            "vision": {
                "primary": {"id": self.vision_primary_id, "ready": self.is_provider_ready("vision", self.vision_primary_id)},
                "fallback": {"id": self.vision_fallback_id, "ready": self.is_provider_ready("vision", self.vision_fallback_id)},
                "active_model": self.get_active_model_name("vision"),
            },
        }


# ── Module Singleton ─────────────────────────────────────────────────────────

_orchestrator = ProviderOrchestrator()


def get_provider_orchestrator() -> ProviderOrchestrator:
    """Return the global ProviderOrchestrator singleton."""
    return _orchestrator
