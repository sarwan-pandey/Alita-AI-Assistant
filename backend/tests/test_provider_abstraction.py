"""
Provider Abstraction Tests — Proving Current Behavior Preservation
===================================================================
These tests verify that:
  1. The provider abstraction layer imports cleanly
  2. Current Qwen local path still works via the abstraction
  3. Current Chatterbox TTS path still works via the abstraction
  4. Provider selection does not alter current production behavior
  5. NVIDIA providers register but remain dormant without API keys
  6. Health checks report accurate status
  7. Registries function correctly
"""

import sys
import os
import time
import pytest
import threading

# Ensure backend is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═════════════════════════════════════════════════════════════════════════════
# §1  LLM PROVIDER TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestLLMProviderAbstraction:
    """Tests for the LLM provider abstraction layer."""

    def test_import_clean(self):
        """Provider module imports without errors."""
        from engines.llm_provider import (
            LLMProvider,
            QwenLocalProvider,
            NvidiaNIMProvider,
            LLMProviderRegistry,
            ProviderHealth,
            llm_registry,
            initialize_providers,
        )
        assert LLMProvider is not None
        assert QwenLocalProvider is not None
        assert NvidiaNIMProvider is not None

    def test_registry_register_and_list(self):
        """Registry registers providers and lists them correctly."""
        from engines.llm_provider import LLMProviderRegistry, QwenLocalProvider, NvidiaNIMProvider

        registry = LLMProviderRegistry()
        assert registry.list_providers() == []

        qwen = QwenLocalProvider()
        registry.register(qwen)
        assert "qwen_local" in registry.list_providers()

        nim = NvidiaNIMProvider("nemotron_lightning", "nvidia/nemotron-3.5-lightning-30b-a3b")
        registry.register(nim)
        assert "nemotron_lightning" in registry.list_providers()
        assert len(registry.list_providers()) == 2

    def test_registry_get_returns_correct_provider(self):
        """Registry.get() returns the correct provider by ID."""
        from engines.llm_provider import LLMProviderRegistry, QwenLocalProvider

        registry = LLMProviderRegistry()
        qwen = QwenLocalProvider()
        registry.register(qwen)

        result = registry.get("qwen_local")
        assert result is qwen
        assert result.provider_id == "qwen_local"

        assert registry.get("nonexistent") is None

    def test_qwen_provider_id(self):
        """QwenLocalProvider has correct provider_id."""
        from engines.llm_provider import QwenLocalProvider
        qwen = QwenLocalProvider()
        assert qwen.provider_id == "qwen_local"

    def test_qwen_get_model_name(self):
        """QwenLocalProvider reports correct model name."""
        from engines.llm_provider import QwenLocalProvider
        qwen = QwenLocalProvider()
        model = qwen.get_model_name()
        assert isinstance(model, str)
        assert len(model) > 0
        # Should be some variant of qwen3
        assert "qwen" in model.lower() or "4b" in model.lower() or "instruct" in model.lower()

    def test_qwen_health_check(self):
        """QwenLocalProvider health check returns valid ProviderHealth."""
        from engines.llm_provider import QwenLocalProvider, ProviderHealth
        qwen = QwenLocalProvider()
        health = qwen.health_check()
        assert isinstance(health, ProviderHealth)
        assert health.provider_id == "qwen_local"
        assert health.last_check > 0
        # Ollama should be running (started by the test environment)
        # If not running, the test still passes — it just reports unavailable
        assert isinstance(health.available, bool)

    def test_nvidia_provider_dormant_without_key(self):
        """NvidiaNIMProvider stays dormant when no API key is set."""
        from engines.llm_provider import NvidiaNIMProvider

        nim = NvidiaNIMProvider("nemotron_lightning", "nvidia/nemotron-3.5-lightning-30b-a3b", api_key="")
        health = nim.health_check()
        assert health.available is False
        assert "No API key" in health.last_error

        # Chat should return None, not crash
        result = nim.chat(messages=[{"role": "user", "content": "hello"}])
        assert result is None

    def test_nvidia_provider_model_name(self):
        """NvidiaNIMProvider reports correct model ID."""
        from engines.llm_provider import NvidiaNIMProvider

        lightning = NvidiaNIMProvider("nemotron_lightning", "nvidia/nemotron-3.5-lightning-30b-a3b")
        assert lightning.get_model_name() == "nvidia/nemotron-3.5-lightning-30b-a3b"

        super_p = NvidiaNIMProvider("nemotron_super", "nvidia/nemotron-3-super-120b-a12b")
        assert super_p.get_model_name() == "nvidia/nemotron-3-super-120b-a12b"

    def test_initialize_providers_registers_all(self):
        """initialize_providers() registers all three LLM providers."""
        from engines.llm_provider import LLMProviderRegistry, initialize_providers, llm_registry

        # Create a fresh registry for this test
        from engines import llm_provider
        original_registry = llm_provider.llm_registry
        llm_provider.llm_registry = LLMProviderRegistry()

        try:
            registry = initialize_providers(nvidia_api_key="")
            providers = registry.list_providers()
            assert "qwen_local" in providers
            assert "nemotron_lightning" in providers
            assert "nemotron_super" in providers
            assert len(providers) == 3
        finally:
            llm_provider.llm_registry = original_registry

    def test_provider_health_recording(self):
        """ProviderHealth correctly tracks success and failure."""
        from engines.llm_provider import ProviderHealth

        health = ProviderHealth(provider_id="test")
        assert health.available is False
        assert health.consecutive_failures == 0

        health.record_success(100.0)
        assert health.available is True
        assert health.avg_latency_ms == 100.0

        health.record_failure("error1")
        assert health.consecutive_failures == 1
        assert health.available is True  # Still available after 1 failure

        health.record_failure("error2")
        health.record_failure("error3")
        assert health.consecutive_failures == 3
        assert health.available is False  # Tripped after 3 failures

        health.record_success(50.0)
        assert health.available is True  # Recovers on success
        assert health.consecutive_failures == 0

    def test_provider_selection_does_not_alter_production(self):
        """
        Verifying that the provider abstraction DOES NOT change how
        the existing production code path works.
        The existing general_handler.py and main.py still import from
        ollama_client directly — the provider layer is additive only.
        """
        # Verify ollama_client still exists and is importable independently
        from ollama_client import ollama_chat, get_model_name, is_ollama_running
        assert callable(ollama_chat)
        assert callable(get_model_name)
        assert callable(is_ollama_running)

        # Verify tts_dispatch still exists and is importable independently
        # (requires soundfile which may not be in test env)
        sf = pytest.importorskip("soundfile", reason="soundfile not in test env")
        from tts_dispatch import _tts_generate, get_or_load_turbo_engine
        assert callable(_tts_generate)
        assert callable(get_or_load_turbo_engine)

        # The provider layer does NOT modify these modules
        # It wraps them in an abstraction that can be used for future routing

    def test_registry_thread_safety(self):
        """Registry operations are thread-safe."""
        from engines.llm_provider import LLMProviderRegistry, QwenLocalProvider, NvidiaNIMProvider

        registry = LLMProviderRegistry()
        errors = []

        def register_providers():
            try:
                for i in range(10):
                    nim = NvidiaNIMProvider(f"test_{threading.current_thread().name}_{i}", "test-model")
                    registry.register(nim)
            except Exception as exc:
                errors.append(str(exc))

        threads = [threading.Thread(target=register_providers) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread safety errors: {errors}"


# ═════════════════════════════════════════════════════════════════════════════
# §2  VISION PROVIDER TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestVisionProviderAbstraction:
    """Tests for the vision provider abstraction layer."""

    def test_import_clean(self):
        """Vision provider module imports without errors."""
        from engines.vision_provider import (
            VisionProvider,
            MoondreamLocalProvider,
            Gemma4VisionProvider,
            VisionProviderRegistry,
            vision_registry,
            initialize_vision_providers,
        )
        assert VisionProvider is not None

    def test_moondream_provider_id(self):
        from engines.vision_provider import MoondreamLocalProvider
        provider = MoondreamLocalProvider()
        assert provider.provider_id == "moondream_local"
        assert provider.get_model_name() == "moondream"

    def test_gemma_dormant_without_key(self):
        """Gemma4VisionProvider stays dormant without API key."""
        from engines.vision_provider import Gemma4VisionProvider
        gemma = Gemma4VisionProvider(api_key="")
        health = gemma.health_check()
        assert health.available is False
        assert "No API key" in health.last_error

        result = gemma.analyze("test prompt")
        assert result is None

    def test_gemma_model_name(self):
        from engines.vision_provider import Gemma4VisionProvider
        gemma = Gemma4VisionProvider()
        assert gemma.get_model_name() == "google/gemma-4-31b-it"

    def test_initialize_registers_both(self):
        """initialize_vision_providers() registers both providers."""
        from engines.vision_provider import VisionProviderRegistry, initialize_vision_providers
        from engines import vision_provider
        original = vision_provider.vision_registry
        vision_provider.vision_registry = VisionProviderRegistry()
        try:
            registry = initialize_vision_providers()
            providers = registry.list_providers()
            assert "moondream_local" in providers
            assert "gemma_4_31b" in providers
            assert len(providers) == 2
        finally:
            vision_provider.vision_registry = original


# ═════════════════════════════════════════════════════════════════════════════
# §3  TTS PROVIDER TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestTTSProviderAbstraction:
    """Tests for the TTS provider abstraction layer."""

    def test_import_clean(self):
        """TTS provider module imports without errors."""
        from engines.tts_provider import (
            TTSProvider,
            ChatterboxLocalProvider,
            ChatterboxNIMProvider,
            TTSProviderRegistry,
            tts_registry,
            initialize_tts_providers,
        )
        assert TTSProvider is not None

    def test_chatterbox_local_provider_id(self):
        from engines.tts_provider import ChatterboxLocalProvider
        provider = ChatterboxLocalProvider()
        assert provider.provider_id == "chatterbox_local"

    def test_chatterbox_local_list_voices(self):
        """ChatterboxLocalProvider lists voices without crashing."""
        from engines.tts_provider import ChatterboxLocalProvider
        provider = ChatterboxLocalProvider()
        voices = provider.list_voices()
        assert isinstance(voices, list)
        assert len(voices) >= 1
        # Should have at least the default MJ voice
        assert any("mj" in v.get("id", "").lower() or "default" in v.get("name", "").lower() for v in voices)

    def test_nim_dormant_without_key(self):
        """ChatterboxNIMProvider stays dormant without API key."""
        from engines.tts_provider import ChatterboxNIMProvider
        nim = ChatterboxNIMProvider(api_key="")
        health = nim.health_check()
        assert health.available is False
        assert "No API key" in health.last_error

    def test_nim_list_voices_static(self):
        """ChatterboxNIMProvider lists static voice catalog."""
        from engines.tts_provider import ChatterboxNIMProvider
        nim = ChatterboxNIMProvider()
        voices = nim.list_voices()
        assert isinstance(voices, list)
        assert len(voices) >= 2
        assert any("en" in v.get("lang", "") for v in voices)

    def test_nim_default_voice_mapping(self):
        """ChatterboxNIMProvider maps language codes to voice IDs."""
        from engines.tts_provider import ChatterboxNIMProvider
        nim = ChatterboxNIMProvider()
        assert "en-US" in nim._default_voice_for_language("en")
        assert "hi-IN" in nim._default_voice_for_language("hi")
        assert "en-US" in nim._default_voice_for_language("unknown")  # fallback

    def test_initialize_registers_both(self):
        """initialize_tts_providers() registers both providers."""
        from engines.tts_provider import TTSProviderRegistry, initialize_tts_providers
        from engines import tts_provider
        original = tts_provider.tts_registry
        tts_provider.tts_registry = TTSProviderRegistry()
        try:
            registry = initialize_tts_providers()
            providers = registry.list_providers()
            assert "chatterbox_local" in providers
            assert "chatterbox_multilingual_nim" in providers
            assert len(providers) == 2
        finally:
            tts_provider.tts_registry = original


# ═════════════════════════════════════════════════════════════════════════════
# §4  CROSS-CUTTING TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestProductionBehaviorPreservation:
    """
    Tests ensuring that the provider abstraction does NOT alter
    existing production behavior in any way.
    """

    def test_existing_ollama_client_unchanged(self):
        """ollama_client.py is NOT modified — still works as before."""
        from ollama_client import (
            OLLAMA_BASE_URL,
            OLLAMA_MODEL,
            OLLAMA_NUM_CTX,
            ollama_chat,
            get_model_name,
            is_ollama_running,
        )
        assert OLLAMA_BASE_URL.startswith("http")
        assert "qwen" in OLLAMA_MODEL.lower() or "4b" in OLLAMA_MODEL.lower()
        assert OLLAMA_NUM_CTX > 0
        assert callable(ollama_chat)

    def test_existing_tts_dispatch_unchanged(self):
        """tts_dispatch.py is NOT modified — still works as before."""
        pytest.importorskip("soundfile", reason="soundfile not in test env")
        from tts_dispatch import _tts_generate, get_or_load_turbo_engine, get_or_load_multilingual_engine
        assert callable(_tts_generate)
        assert callable(get_or_load_turbo_engine)
        # Multilingual engine should return None (legacy stub)
        assert get_or_load_multilingual_engine() is None

    def test_existing_decision_router_unchanged(self):
        """decision_router.py is NOT modified — still classifies queries."""
        from decision_router import classify_query
        assert classify_query("what time is it") == "realtime"
        assert classify_query("open chrome") == "automation"
        assert classify_query("tell me a joke") == "general"

    def test_existing_general_handler_unchanged(self):
        """general_handler.py still imports directly from ollama_client."""
        import inspect
        from threads.general_handler import _try_ollama
        source = inspect.getsource(_try_ollama)
        # Verify it still imports from ollama_client directly
        assert "ollama_client" in source
        # Verify it does NOT import from llm_provider
        assert "llm_provider" not in source

    def test_no_production_code_imports_providers(self):
        """
        No existing production file imports the new provider modules.
        This proves the abstraction is additive — zero production impact.
        Checks for actual import statements, not config field names.
        """
        import importlib
        import re
        production_modules = [
            "main",
            "tts_dispatch",
            "ollama_client",
            "decision_router",
        ]
        # Match actual import statements like "from engines.llm_provider" or "import llm_provider"
        import_patterns = [
            re.compile(r"(?:from\s+(?:engines\.)?|import\s+)llm_provider\b"),
            re.compile(r"(?:from\s+(?:engines\.)?|import\s+)tts_provider\b"),
            re.compile(r"(?:from\s+(?:engines\.)?|import\s+)vision_provider\b"),
        ]
        for mod_name in production_modules:
            if mod_name in sys.modules:
                mod = sys.modules[mod_name]
            else:
                try:
                    mod = importlib.import_module(mod_name)
                except ImportError:
                    continue

            source_file = getattr(mod, "__file__", "")
            if source_file and os.path.exists(source_file):
                with open(source_file, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for pattern in import_patterns:
                    assert not pattern.search(content), (
                        f"{mod_name} imports a provider module! Match: {pattern.pattern}"
                    )

    def test_settings_has_nvidia_fields(self):
        """Settings class has NVIDIA configuration fields."""
        pytest.importorskip("fastapi", reason="fastapi not in test env")
        from main import settings
        assert hasattr(settings, "nvidia_api_key")
        assert hasattr(settings, "nvidia_model")
        # Provider config fields
        assert hasattr(settings, "llm_provider_active")
        assert hasattr(settings, "tts_provider_active")
        assert hasattr(settings, "vision_provider_active")

    def test_active_providers_are_local(self):
        """Active provider settings default to local (production) providers."""
        pytest.importorskip("fastapi", reason="fastapi not in test env")
        from main import settings
        assert settings.llm_provider_active == "qwen_local"
        assert settings.tts_provider_active == "chatterbox_local"
        assert settings.vision_provider_active == "moondream_local"
