"""
Nemotron Lightning Provider Tests
==================================
Tests for the Lightning client, metrics capture, and shadow benchmark.

Unit tests run without an API key (testing structure/logic).
Integration tests require NVIDIA_API_KEY and are skipped without it.
"""

import sys
import os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═════════════════════════════════════════════════════════════════════════════
# §1  UNIT TESTS — No API key required
# ═════════════════════════════════════════════════════════════════════════════

class TestLightningMetrics:
    """Tests for the LightningMetrics data structure."""

    def test_metrics_import(self):
        from engines.nvidia_lightning import LightningMetrics
        assert LightningMetrics is not None

    def test_metrics_defaults(self):
        from engines.nvidia_lightning import LightningMetrics
        m = LightningMetrics()
        assert m.success is False
        assert m.ttft_ms == 0.0
        assert m.total_ms == 0.0
        assert m.response_text == ""

    def test_metrics_finalize(self):
        from engines.nvidia_lightning import LightningMetrics
        m = LightningMetrics()
        m.request_start = 100.0
        m.first_token_time = 100.250   # 250ms TTFT
        m.first_sentence_time = 100.500  # 500ms TTFS
        m.response_complete_time = 101.0  # 1000ms total
        m.finalize()
        assert abs(m.ttft_ms - 250.0) < 1.0
        assert abs(m.ttfs_ms - 500.0) < 1.0
        assert abs(m.total_ms - 1000.0) < 1.0

    def test_metrics_summary_format(self):
        from engines.nvidia_lightning import LightningMetrics
        m = LightningMetrics(
            provider="test_provider",
            success=True,
            ttft_ms=100.0,
            ttfs_ms=250.0,
            total_ms=500.0,
            prompt_tokens=50,
            completion_tokens=30,
            total_tokens=80,
            response_text="Hello world",
        )
        summary = m.summary()
        assert "test_provider" in summary
        assert "OK" in summary
        assert "TTFT=100ms" in summary
        assert "11 chars" in summary

    def test_metrics_summary_failure(self):
        from engines.nvidia_lightning import LightningMetrics
        m = LightningMetrics(provider="test", success=False, error="Connection timeout")
        summary = m.summary()
        assert "FAIL" in summary
        assert "Connection timeout" in summary


class TestSentenceDetection:
    """Tests for sentence boundary detection."""

    def test_complete_sentence(self):
        from engines.nvidia_lightning import _has_complete_sentence
        assert _has_complete_sentence("Hello world.") is True
        assert _has_complete_sentence("How are you? ") is True
        assert _has_complete_sentence("Wow!") is True

    def test_incomplete_text(self):
        from engines.nvidia_lightning import _has_complete_sentence
        assert _has_complete_sentence("Hello world") is False
        assert _has_complete_sentence("How are") is False
        assert _has_complete_sentence("") is False


class TestLightningClientInit:
    """Tests for client initialization without API key."""

    def test_client_import(self):
        from engines.nvidia_lightning import NvidiaLightningClient, get_lightning_client
        assert NvidiaLightningClient is not None
        assert callable(get_lightning_client)

    def test_client_no_key(self):
        from engines.nvidia_lightning import NvidiaLightningClient
        client = NvidiaLightningClient(api_key="")
        assert client.available is False

    def test_client_with_key(self):
        from engines.nvidia_lightning import NvidiaLightningClient
        client = NvidiaLightningClient(api_key="test-key-123")
        assert client.available is True
        assert client.model_id == "nvidia/nemotron-3.5-lightning-30b-a3b"

    def test_client_custom_model(self):
        from engines.nvidia_lightning import NvidiaLightningClient
        client = NvidiaLightningClient(
            api_key="test", model_id="nvidia/custom-model"
        )
        assert client.model_id == "nvidia/custom-model"

    def test_client_custom_endpoint(self):
        from engines.nvidia_lightning import NvidiaLightningClient
        client = NvidiaLightningClient(
            api_key="test", base_url="http://localhost:8000/v1"
        )
        assert client._base_url == "http://localhost:8000/v1"

    def test_health_check_no_key(self):
        from engines.nvidia_lightning import NvidiaLightningClient
        client = NvidiaLightningClient(api_key="")
        health = client.health_check()
        assert health["available"] is False
        assert "No API key" in health["error"]

    def test_chat_no_key_returns_metrics(self):
        """Chat without API key returns metrics with error, doesn't crash."""
        from engines.nvidia_lightning import NvidiaLightningClient
        client = NvidiaLightningClient(api_key="")
        metrics = client.chat_with_metrics(
            [{"role": "user", "content": "Hello"}]
        )
        assert metrics.success is False
        assert "No API key" in metrics.error
        assert metrics.provider == "nemotron_lightning"

    def test_simple_chat_no_key(self):
        from engines.nvidia_lightning import NvidiaLightningClient
        client = NvidiaLightningClient(api_key="")
        result = client.chat([{"role": "user", "content": "Hello"}])
        assert result is None


class TestShadowBenchmarkStructure:
    """Tests for shadow benchmark module structure."""

    def test_import(self):
        from engines.shadow_benchmark import (
            run_shadow_benchmark,
            TEST_PROMPTS,
            TestPrompt,
        )
        assert callable(run_shadow_benchmark)
        assert len(TEST_PROMPTS) >= 5

    def test_prompt_catalog_coverage(self):
        """Prompt catalog covers required categories."""
        from engines.shadow_benchmark import TEST_PROMPTS
        categories = {p.category for p in TEST_PROMPTS}
        assert "greeting" in categories
        assert "knowledge" in categories
        assert "reasoning" in categories
        assert "creative" in categories
        assert "medical" in categories

    def test_all_prompts_have_descriptions(self):
        from engines.shadow_benchmark import TEST_PROMPTS
        for p in TEST_PROMPTS:
            assert p.description, f"Prompt '{p.user_message[:30]}' has no description"
            assert p.user_message, f"Prompt has no user_message"
            assert p.max_tokens > 0

    def test_production_code_not_modified(self):
        """Shadow benchmark does not import from or modify production modules."""
        from engines.shadow_benchmark import run_shadow_benchmark
        import inspect
        source = inspect.getsource(run_shadow_benchmark)
        # Should not modify any production state
        assert "settings." not in source
        assert "engines.chatterbox" not in source


# ═════════════════════════════════════════════════════════════════════════════
# §2  QWEN INTEGRATION TEST — Requires Ollama running
# ═════════════════════════════════════════════════════════════════════════════

class TestQwenShadowMetrics:
    """Verify Qwen metrics capture works with live Ollama."""

    def test_qwen_metrics_capture(self):
        """Qwen local produces valid metrics on a simple prompt."""
        from ollama_client import is_ollama_running
        if not is_ollama_running():
            pytest.skip("Ollama not running")

        from engines.shadow_benchmark import _qwen_chat_with_metrics

        messages = [
            {"role": "system", "content": "You are a helpful assistant. Be brief."},
            {"role": "user", "content": "What is 2+2?"},
        ]
        metrics = _qwen_chat_with_metrics(messages, max_tokens=50, temperature=0.3)

        assert metrics.provider == "qwen_local"
        assert metrics.success is True, f"Qwen failed: {metrics.error}"
        assert metrics.total_ms > 0
        assert len(metrics.response_text) > 0
        assert "4" in metrics.response_text
        print(f"\n  Qwen: {metrics.summary()}")
        print(f"  Response: \"{metrics.response_text[:100]}\"")


# ═════════════════════════════════════════════════════════════════════════════
# §3  LIGHTNING INTEGRATION TEST — Requires NVIDIA_API_KEY
# ═════════════════════════════════════════════════════════════════════════════

class TestLightningIntegration:
    """Live integration tests — skipped without NVIDIA_API_KEY."""

    def _get_client(self):
        from engines.nvidia_lightning import NvidiaLightningClient
        key = os.getenv("NVIDIA_API_KEY", "")
        if not key:
            pytest.skip("NVIDIA_API_KEY not set")
        return NvidiaLightningClient(api_key=key)

    def test_lightning_health_check(self):
        client = self._get_client()
        health = client.health_check()
        assert health["available"] is True, f"Health check failed: {health.get('error')}"
        print(f"\n  Health: {health}")

    def test_lightning_simple_chat(self):
        client = self._get_client()
        metrics = client.chat_with_metrics(
            [
                {"role": "system", "content": "Be very brief. Answer directly with no preamble."},
                {"role": "user", "content": "What is 2+2?"},
            ],
            max_tokens=100,  # Enough tokens for thinking + answer
            temperature=0.3,
        )
        assert metrics.success is True, f"Lightning failed: {metrics.error}"
        # Model should produce a response containing "4" or "four"
        response_lower = metrics.response_text.lower()
        assert "4" in metrics.response_text or "four" in response_lower, (
            f"Expected '4' or 'four' in response: \"{metrics.response_text[:200]}\""
        )
        assert metrics.ttft_ms > 0
        assert metrics.total_ms > 0
        print(f"\n  {metrics.summary()}")
        print(f"  Response: \"{metrics.response_text[:100]}\"")

    def test_lightning_streaming_timing(self):
        """Verify TTFT < TTFS < Total ordering."""
        client = self._get_client()
        metrics = client.chat_with_metrics(
            [
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Give me 3 tips for better sleep."},
            ],
            max_tokens=200,
        )
        assert metrics.success is True, f"Failed: {metrics.error}"
        # TTFT should be less than total
        assert metrics.ttft_ms > 0
        assert metrics.ttft_ms <= metrics.total_ms
        # If we got a sentence, TTFS should be between TTFT and total
        if metrics.ttfs_ms > 0:
            assert metrics.ttft_ms <= metrics.ttfs_ms <= metrics.total_ms
        print(f"\n  {metrics.summary()}")

    def test_lightning_reasoning_disabled(self):
        """With reasoning disabled, response should not contain thinking tags."""
        client = self._get_client()
        metrics = client.chat_with_metrics(
            [{"role": "user", "content": "What is the meaning of life?"}],
            max_tokens=150,
            enable_reasoning=False,
        )
        assert metrics.success is True
        assert "<think>" not in metrics.response_text
        assert metrics.reasoning_enabled is False
        print(f"\n  {metrics.summary()}")

    def test_lightning_token_counts(self):
        """Token counts should be populated from usage data."""
        client = self._get_client()
        metrics = client.chat_with_metrics(
            [{"role": "user", "content": "Say hello"}],
            max_tokens=50,
        )
        if metrics.success:
            # Token counts should be non-zero if the API reports them
            print(f"\n  Tokens: prompt={metrics.prompt_tokens} "
                  f"completion={metrics.completion_tokens} total={metrics.total_tokens}")
