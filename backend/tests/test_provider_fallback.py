"""
Deterministic Provider Fallback Tests (P0)
============================================
Verifies fail-fast, deterministic fallback from NVIDIA candidate providers
to local production baselines:
  - LLM:    NVIDIA Lightning -> local Qwen
  - TTS:    NVIDIA Chatterbox -> local Chatterbox Turbo
  - Vision: Gemma 4 31B -> local Moondream

Guarantees tested:
  1. Fail-fast timeout configuration (no 60-180s hangs)
  2. Primary failure is logged with turn_id
  3. Fallback selection is logged with turn_id
  4. Turn_id / request_id is preserved throughout
  5. Valid result is returned whenever fallback succeeds
  6. NVIDIA credentials are NEVER exposed in logs/errors
  7. Feature flags gate all NVIDIA providers (default: false)
"""

import os
import sys
import time
import logging
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

# Ensure backend path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engines.llm_provider import (
    LLMProvider,
    QwenLocalProvider,
    NvidiaNIMProvider,
    FallbackLLMProvider,
    LLMProviderRegistry,
    sanitize_error as sanitize_llm_error,
)
from engines.tts_provider import (
    TTSProvider,
    ChatterboxLocalProvider,
    ChatterboxNIMProvider,
    FallbackTTSProvider,
    TTSProviderRegistry,
    sanitize_error as sanitize_tts_error,
)
from engines.vision_provider import (
    VisionProvider,
    MoondreamLocalProvider,
    Gemma4VisionProvider,
    FallbackVisionProvider,
    VisionProviderRegistry,
    sanitize_error as sanitize_vision_error,
)


# ═════════════════════════════════════════════════════════════════════════════
# §1  CREDENTIAL SANITIZATION TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestCredentialSanitization:
    """Ensure credentials and tokens are scrubbed from error messages."""

    def test_strip_nvapi_keys(self):
        secret_key = "nvapi-dummyTestKeyForRedactionVerification1234567890"
        error_msg = f"Failed connecting to server with {secret_key}: connection reset"
        sanitized = sanitize_llm_error(error_msg)
        assert secret_key not in sanitized
        assert "nvapi-[REDACTED]" in sanitized

    def test_strip_bearer_tokens(self):
        bearer = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
        error_msg = f"HTTP 401 Unauthorized: Authorization header was {bearer}"
        sanitized = sanitize_tts_error(error_msg)
        assert bearer not in sanitized
        assert "Bearer [REDACTED]" in sanitized

    def test_empty_error_handled(self):
        assert sanitize_vision_error("") == ""
        assert sanitize_vision_error(None) == ""


# ═════════════════════════════════════════════════════════════════════════════
# §2  LLM PROVIDER FALLBACK TESTS (Lightning -> Qwen)
# ═════════════════════════════════════════════════════════════════════════════

class TestLLMFallback:
    """Verifies LLM fallback to Qwen on error/timeout/feature flag."""

    def test_feature_flag_disabled_routes_directly_to_qwen(self):
        """When ENABLE_NVIDIA_LLM is false, calls go directly to Qwen."""
        mock_lightning = MagicMock(spec=LLMProvider)
        mock_lightning.provider_id = "nemotron_lightning"

        mock_qwen = MagicMock(spec=LLMProvider)
        mock_qwen.provider_id = "qwen_local"
        mock_qwen.chat.return_value = "Hello from local Qwen"

        provider = FallbackLLMProvider(
            primary=mock_lightning,
            fallback=mock_qwen,
            enabled=False,  # Feature flag disabled
        )

        res = provider.chat([{"role": "user", "content": "hi"}], turn_id="turn_test_01")
        assert res == "Hello from local Qwen"
        mock_lightning.chat.assert_not_called()
        mock_qwen.chat.assert_called_once()

    def test_primary_timeout_falls_back_to_qwen(self, caplog):
        """When primary raises timeout, falls back to Qwen and logs turn_id."""
        mock_lightning = MagicMock(spec=LLMProvider)
        mock_lightning.provider_id = "nemotron_lightning"
        mock_lightning.chat.side_effect = TimeoutError("Request timed out after 5.0s with nvapi-secret1234567")

        mock_qwen = MagicMock(spec=LLMProvider)
        mock_qwen.provider_id = "qwen_local"
        mock_qwen.chat.return_value = "Recovered via Qwen"

        provider = FallbackLLMProvider(
            primary=mock_lightning,
            fallback=mock_qwen,
            enabled=True,
            timeout=5.0,
        )

        with caplog.at_level(logging.WARNING):
            res = provider.chat([{"role": "user", "content": "test"}], turn_id="turn_12345")

        assert res == "Recovered via Qwen"
        mock_lightning.chat.assert_called_once()
        mock_qwen.chat.assert_called_once()

        # Check log output
        log_text = caplog.text
        assert "LLM-FALLBACK" in log_text
        assert "turn_12345" in log_text
        assert "nemotron_lightning" in log_text
        assert "qwen_local" in log_text
        # Credentials must NOT be in log
        assert "nvapi-secret1234567" not in log_text
        assert "nvapi-[REDACTED]" in log_text

    def test_primary_empty_response_falls_back_to_qwen(self):
        """When primary returns empty text, falls back to Qwen."""
        mock_lightning = MagicMock(spec=LLMProvider)
        mock_lightning.provider_id = "nemotron_lightning"
        mock_lightning.chat.return_value = ""

        mock_qwen = MagicMock(spec=LLMProvider)
        mock_qwen.provider_id = "qwen_local"
        mock_qwen.chat.return_value = "Fallback Qwen response"

        provider = FallbackLLMProvider(
            primary=mock_lightning,
            fallback=mock_qwen,
            enabled=True,
        )

        res = provider.chat([{"role": "user", "content": "test"}], turn_id="turn_empty")
        assert res == "Fallback Qwen response"

    def test_streaming_fallback_on_init_failure(self):
        """When primary stream fails on init, yields from fallback stream."""
        mock_lightning = MagicMock(spec=LLMProvider)
        mock_lightning.provider_id = "nemotron_lightning"
        mock_lightning.chat_stream.side_effect = ConnectionError("Connection refused")

        mock_qwen = MagicMock(spec=LLMProvider)
        mock_qwen.provider_id = "qwen_local"
        mock_qwen.chat_stream.return_value = iter(["Qwen ", "stream ", "chunk"])

        provider = FallbackLLMProvider(
            primary=mock_lightning,
            fallback=mock_qwen,
            enabled=True,
        )

        chunks = list(provider.chat_stream([{"role": "user", "content": "hi"}], turn_id="stream_01"))
        assert chunks == ["Qwen ", "stream ", "chunk"]


# ═════════════════════════════════════════════════════════════════════════════
# §3  TTS PROVIDER FALLBACK TESTS (NIM -> Chatterbox Turbo)
# ═════════════════════════════════════════════════════════════════════════════

class TestTTSFallback:
    """Verifies TTS fallback to local Chatterbox Turbo."""

    def test_feature_flag_disabled_routes_directly_to_turbo(self):
        import asyncio
        mock_nim = AsyncMock(spec=TTSProvider)
        mock_nim.provider_id = "chatterbox_multilingual_nim"

        mock_turbo = AsyncMock(spec=TTSProvider)
        mock_turbo.provider_id = "chatterbox_local"
        mock_turbo.synthesize.return_value = b"RIFF" + b"\x00" * 50  # Valid dummy WAV

        provider = FallbackTTSProvider(
            primary=mock_nim,
            fallback=mock_turbo,
            enabled=False,
        )

        res = asyncio.run(provider.synthesize("Hello world", turn_id="turn_tts_01"))
        assert len(res) > 44
        mock_nim.synthesize.assert_not_called()
        mock_turbo.synthesize.assert_called_once()

    def test_nim_error_falls_back_to_turbo(self, caplog):
        import asyncio
        mock_nim = AsyncMock(spec=TTSProvider)
        mock_nim.provider_id = "chatterbox_multilingual_nim"
        mock_nim.synthesize.side_effect = RuntimeError("503 Service Unavailable nvapi-key999")

        mock_turbo = AsyncMock(spec=TTSProvider)
        mock_turbo.provider_id = "chatterbox_local"
        mock_turbo.synthesize.return_value = b"RIFF" + b"\x00" * 50

        provider = FallbackTTSProvider(
            primary=mock_nim,
            fallback=mock_turbo,
            enabled=True,
            timeout=4.0,
        )

        with caplog.at_level(logging.WARNING):
            res = asyncio.run(provider.synthesize("Speak this text", turn_id="turn_tts_fail"))

        assert len(res) > 44
        assert "TTS-FALLBACK" in caplog.text
        assert "turn_tts_fail" in caplog.text
        assert "nvapi-key999" not in caplog.text
        assert "nvapi-[REDACTED]" in caplog.text

    def test_nim_empty_audio_falls_back_to_turbo(self):
        import asyncio
        mock_nim = AsyncMock(spec=TTSProvider)
        mock_nim.provider_id = "chatterbox_multilingual_nim"
        mock_nim.synthesize.return_value = b""  # Empty output

        mock_turbo = AsyncMock(spec=TTSProvider)
        mock_turbo.provider_id = "chatterbox_local"
        mock_turbo.synthesize.return_value = b"RIFF" + b"\x00" * 50

        provider = FallbackTTSProvider(
            primary=mock_nim,
            fallback=mock_turbo,
            enabled=True,
        )

        res = asyncio.run(provider.synthesize("Speak", turn_id="turn_empty_audio"))
        assert len(res) > 44
        mock_turbo.synthesize.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# §4  VISION PROVIDER FALLBACK TESTS (Gemma 4 -> Moondream)
# ═════════════════════════════════════════════════════════════════════════════

class TestVisionFallback:
    """Verifies Vision fallback to local Moondream."""

    def test_feature_flag_disabled_routes_directly_to_moondream(self):
        mock_gemma = MagicMock(spec=VisionProvider)
        mock_gemma.provider_id = "gemma_4_31b"

        mock_moondream = MagicMock(spec=VisionProvider)
        mock_moondream.provider_id = "moondream_local"
        mock_moondream.analyze.return_value = "Local Moondream screen reading"

        provider = FallbackVisionProvider(
            primary=mock_gemma,
            fallback=mock_moondream,
            enabled=False,
        )

        res = provider.analyze("What is on screen?", turn_id="turn_vision_01")
        assert res == "Local Moondream screen reading"
        mock_gemma.analyze.assert_not_called()
        mock_moondream.analyze.assert_called_once()

    def test_gemma_timeout_falls_back_to_moondream(self, caplog):
        """Simulates the 30s cloud timeout, ensuring fail-fast fallback to Moondream."""
        mock_gemma = MagicMock(spec=VisionProvider)
        mock_gemma.provider_id = "gemma_4_31b"
        mock_gemma.analyze.side_effect = TimeoutError("APITimeoutError: Request timed out Bearer token_secret_123")

        mock_moondream = MagicMock(spec=VisionProvider)
        mock_moondream.provider_id = "moondream_local"
        mock_moondream.analyze.return_value = "Moondream detected home screen"

        provider = FallbackVisionProvider(
            primary=mock_gemma,
            fallback=mock_moondream,
            enabled=True,
            timeout=5.0,
        )

        with caplog.at_level(logging.WARNING):
            res = provider.analyze("Describe screen", turn_id="turn_vision_timeout")

        assert res == "Moondream detected home screen"
        assert "VISION-FALLBACK" in caplog.text
        assert "turn_vision_timeout" in caplog.text
        assert "token_secret_123" not in caplog.text
        assert "Bearer [REDACTED]" in caplog.text


# ═════════════════════════════════════════════════════════════════════════════
# §5  SETTINGS AND TIMEOUT CONFIGURATION TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestConfigurationAndDefaults:
    """Verifies settings fields, default values, and timeout boundaries."""

    def test_main_settings_has_p0_fields(self):
        from main import settings
        assert hasattr(settings, "enable_nvidia_llm")
        assert hasattr(settings, "enable_nvidia_tts")
        assert hasattr(settings, "enable_nvidia_vision")
        assert hasattr(settings, "nvidia_llm_timeout")
        assert hasattr(settings, "nvidia_tts_timeout")
        assert hasattr(settings, "nvidia_vision_timeout")

    def test_production_feature_flags_default_false(self):
        """Feature flags MUST default to False to keep production unchanged."""
        from main import settings
        assert settings.enable_nvidia_llm is False
        assert settings.enable_nvidia_tts is False
        assert settings.enable_nvidia_vision is False

    def test_fail_fast_timeouts_bounded(self):
        """Timeouts must be short (<= 5.0s) to prevent pipeline freezes."""
        from main import settings
        assert settings.nvidia_llm_timeout <= 5.0
        assert settings.nvidia_tts_timeout <= 4.0
        assert settings.nvidia_vision_timeout <= 5.0

    def test_registries_register_resilient_providers(self):
        """All registries can create resilient fallback providers."""
        from engines.llm_provider import initialize_providers
        from engines.tts_provider import initialize_tts_providers
        from engines.vision_provider import initialize_vision_providers

        llm_reg = initialize_providers(nvidia_api_key="")
        res_llm = llm_reg.get_resilient_provider()
        assert res_llm.provider_id == "resilient_llm"
        assert res_llm.fallback.provider_id == "qwen_local"

        tts_reg = initialize_tts_providers(nvidia_api_key="", nim_url="")
        res_tts = tts_reg.get_resilient_provider()
        assert res_tts.provider_id == "resilient_tts"
        assert res_tts.fallback.provider_id == "chatterbox_local"

        vision_reg = initialize_vision_providers(nvidia_api_key="")
        res_vis = vision_reg.get_resilient_provider()
        assert res_vis.provider_id == "resilient_vision"
        assert res_vis.fallback.provider_id == "moondream_local"
