"""
P1 Architecture Verification Test Suite — NVIDIA-First Provider Architecture
============================================================================
Verifies:
  1. Legacy Dependency Audit: Static check proving core MJ pipeline does NOT
     directly import legacy concrete providers (ollama_client, tts_chatterbox_turbo, vision_engine).
  2. Provider Health / Readiness States: AVAILABLE, DEGRADED, UNAVAILABLE.
  3. Primary / Fallback Configuration: Environment overrides and alias resolution.
  4. Removal Simulation: Verifies orchestrator behaves safely when a fallback
     provider is unregistered / unavailable during startup.
  5. Modular Registration: Proves custom/new providers can be registered,
     swapped, and unregistered without any modifications to MJ core.
"""

import ast
import os
import re
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest

# Ensure backend path is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engines.provider_contracts import (
    LLMProviderContract,
    ProviderHealth,
    ProviderStatus,
    TTSProviderContract,
    TTSProviderHealth,
    VisionProviderContract,
    VisionProviderHealth,
)
from engines.provider_orchestrator import ProviderOrchestrator, get_provider_orchestrator
from engines.llm_provider import llm_registry, QwenLocalProvider, NvidiaNIMProvider
from engines.tts_provider import tts_registry, ChatterboxLocalProvider
from engines.vision_provider import vision_registry, MoondreamLocalProvider


# ─────────────────────────────────────────────────────────────────────────────
# 1. LEGACY DEPENDENCY AUDIT (STATIC AST & REGEX SCAN)
# ─────────────────────────────────────────────────────────────────────────────

class TestLegacyDependencyAudit(unittest.TestCase):
    """
    Static audit proving that the core MJ pipeline depends ONLY on provider contracts
    and never directly imports legacy concrete engines.
    """

    CORE_PIPELINE_FILES = [
        "main.py",
        "threads/general_handler.py",
        "threads/realtime_handler.py",
        "threads/automation_handler.py",
        "tts_dispatch.py",
        "engines/screen_agent.py",
        "engines/browser_controller.py",
        "routers/system_router.py",
        "routers/geospatial.py",
        "engines/workflows/blog_publisher.py",
        "engines/workflows/youtube_shorts.py",
        "engines/shadow_benchmark.py",
    ]

    FORBIDDEN_LEGACY_MODULES = [
        "ollama_client",
        "tts_chatterbox_turbo",
        "engines.tts_chatterbox_turbo",
        "vision_engine",
        "engines.vision_engine",
    ]

    def test_core_pipeline_files_exist(self):
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        for rel_path in self.CORE_PIPELINE_FILES:
            full_path = os.path.join(backend_dir, rel_path)
            self.assertTrue(os.path.exists(full_path), f"Expected core pipeline file missing: {rel_path}")

    def test_no_direct_legacy_imports_in_core_pipeline(self):
        """
        Parse AST of all core files to verify zero Import or ImportFrom statements
        pointing directly to legacy concrete engines.
        """
        backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        violations = []

        for rel_path in self.CORE_PIPELINE_FILES:
            full_path = os.path.join(backend_dir, rel_path)
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            try:
                tree = ast.parse(content, filename=rel_path)
            except SyntaxError as se:
                self.fail(f"Syntax error in {rel_path}: {se}")

            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in self.FORBIDDEN_LEGACY_MODULES:
                            violations.append(f"{rel_path}:{node.lineno} -> import {alias.name}")
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if mod in self.FORBIDDEN_LEGACY_MODULES:
                        violations.append(f"{rel_path}:{node.lineno} -> from {mod} import ...")

        self.assertEqual(
            violations,
            [],
            f"Core MJ pipeline has forbidden direct legacy imports:\n" + "\n".join(violations)
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. PROVIDER READINESS AND HEALTH STATES
# ─────────────────────────────────────────────────────────────────────────────

class TestProviderHealthAndReadinessStates(unittest.TestCase):
    """
    Verifies the 3-state readiness model: AVAILABLE, DEGRADED, UNAVAILABLE.
    """

    def test_status_enum_values(self):
        self.assertEqual(ProviderStatus.AVAILABLE.value, "AVAILABLE")
        self.assertEqual(ProviderStatus.DEGRADED.value, "DEGRADED")
        self.assertEqual(ProviderStatus.UNAVAILABLE.value, "UNAVAILABLE")

    def test_provider_health_transitions(self):
        health = ProviderHealth(provider_id="test_provider")
        self.assertEqual(health.status, ProviderStatus.UNAVAILABLE)
        self.assertFalse(health.is_ready())

        # Success transition
        health.record_success(latency_ms=120.0)
        self.assertEqual(health.status, ProviderStatus.AVAILABLE)
        self.assertTrue(health.is_ready())
        self.assertEqual(health.avg_latency_ms, 120.0)

        # Failure transitions
        health.record_failure("transient timeout")
        self.assertEqual(health.status, ProviderStatus.DEGRADED)
        self.assertTrue(health.is_ready())  # Degraded can still attempt fallback

        health.record_failure("second timeout")
        self.assertEqual(health.status, ProviderStatus.DEGRADED)

        health.record_failure("third timeout - threshold reached")
        self.assertEqual(health.status, ProviderStatus.UNAVAILABLE)
        self.assertFalse(health.is_ready())

    def test_broken_provider_not_activated_blindly(self):
        """
        A provider that is UNAVAILABLE or disabled must NOT receive production traffic.
        """
        orch = ProviderOrchestrator()
        # With default env flags (ENABLE_NVIDIA_LLM=false), nemotron_lightning is not ready
        self.assertFalse(orch.is_provider_ready("llm", "nemotron_lightning"))
        self.assertFalse(orch.is_provider_ready("tts", "chatterbox_multilingual"))
        self.assertFalse(orch.is_provider_ready("vision", "gemma4"))


# ─────────────────────────────────────────────────────────────────────────────
# 3. PRIMARY / FALLBACK CONFIGURATION AND ROUTING
# ─────────────────────────────────────────────────────────────────────────────

class TestPrimaryFallbackConfiguration(unittest.TestCase):
    """
    Verifies configuration support for LLM, TTS, and Vision primary/fallback pairs.
    """

    def test_default_intended_configuration(self):
        orch = ProviderOrchestrator()
        self.assertEqual(orch.llm_primary_id, "nemotron_lightning")
        self.assertEqual(orch.llm_fallback_id, "qwen_local")
        self.assertEqual(orch.tts_primary_id, "chatterbox_multilingual_nim")
        self.assertEqual(orch.tts_fallback_id, "chatterbox_local")
        self.assertEqual(orch.vision_primary_id, "gemma_4_31b")
        self.assertEqual(orch.vision_fallback_id, "moondream_local")

    def test_alias_resolution(self):
        orch = ProviderOrchestrator()
        self.assertEqual(orch._resolve_id("lightning"), "nemotron_lightning")
        self.assertEqual(orch._resolve_id("qwen"), "qwen_local")
        self.assertEqual(orch._resolve_id("chatterbox_turbo"), "chatterbox_local")
        self.assertEqual(orch._resolve_id("turbo"), "chatterbox_local")
        self.assertEqual(orch._resolve_id("gemma4"), "gemma_4_31b")
        self.assertEqual(orch._resolve_id("moondream"), "moondream_local")

    def test_environment_override_routing(self):
        with patch.dict(os.environ, {
            "LLM_PRIMARY": "qwen_local",
            "LLM_FALLBACK": "nemotron_lightning",
        }):
            orch = ProviderOrchestrator()
            self.assertEqual(orch.llm_primary_id, "qwen_local")
            self.assertEqual(orch.llm_fallback_id, "nemotron_lightning")


# ─────────────────────────────────────────────────────────────────────────────
# 4. REMOVAL SIMULATION (FALLBACK ABSENCE SAFETY)
# ─────────────────────────────────────────────────────────────────────────────

class TestRemovalSimulation(unittest.TestCase):
    """
    Verifies that the provider registry and orchestrator behave safely when
    a fallback provider is unregistered/unavailable during startup.
    Fallback providers must NEVER become hard dependencies of the core.
    """

    def test_unregistered_fallback_provider_handled_gracefully(self):
        orch = get_provider_orchestrator()

        # Temporarily unregister fallback provider
        original_fallback = llm_registry.get("qwen_local") or QwenLocalProvider()
        llm_registry.unregister("qwen_local")
        self.assertIsNone(llm_registry.get("qwen_local"))

        try:
            # Resolving provider when fallback is missing should not crash
            provider = orch.get_llm_provider()
            # If primary is not ready and fallback is None, it should return primary safely or None
            # without raising AttributeError / NameError

            # Chat call when fallback is missing and primary is disabled returns None cleanly
            res = orch.chat(messages=[{"role": "user", "content": "hello"}], turn_id="removal_test_1")
            self.assertIsNone(res)
        finally:
            # Restore fallback provider
            if original_fallback:
                llm_registry.register(original_fallback)
            self.assertIsNotNone(llm_registry.get("qwen_local"))

    def test_tts_unregistered_fallback_handled_gracefully(self):
        orch = get_provider_orchestrator()

        original_fallback = tts_registry.get("chatterbox_local") or ChatterboxLocalProvider()
        tts_registry.unregister("chatterbox_local")
        self.assertIsNone(tts_registry.get("chatterbox_local"))

        try:
            provider = orch.get_tts_provider()
            # Must not crash
        finally:
            if original_fallback:
                tts_registry.register(original_fallback)


# ─────────────────────────────────────────────────────────────────────────────
# 5. MODULAR REGISTRATION
# ─────────────────────────────────────────────────────────────────────────────

class MockCustomLLMProvider(LLMProviderContract):
    """Dummy custom LLM provider for modular registration testing."""
    provider_id = "custom_test_llm"

    def chat(self, messages, max_tokens=300, temperature=0.7, **kwargs):
        return f"custom_response: {messages[-1]['content']}"

    def chat_stream(self, messages, max_tokens=300, temperature=0.7, **kwargs):
        def _g():
            yield "custom_stream"
        return _g()

    def health_check(self):
        return ProviderHealth(provider_id=self.provider_id, available=True, status=ProviderStatus.AVAILABLE)

    def get_model_name(self):
        return "custom-test-v1"


class TestModularRegistration(unittest.TestCase):
    """
    Verifies that a new provider can be added, registered, selected via config,
    and removed without modifying any MJ core code.
    """

    def test_dynamic_provider_lifecycle(self):
        orch = get_provider_orchestrator()
        custom = MockCustomLLMProvider()

        # 1. Register new provider
        llm_registry.register(custom)
        self.assertIn("custom_test_llm", llm_registry.list_providers())
        self.assertEqual(llm_registry.get("custom_test_llm").get_model_name(), "custom-test-v1")

        # 2. Configure as active primary
        with patch.dict(os.environ, {"LLM_PRIMARY": "custom_test_llm", "ENABLE_NVIDIA_LLM": "true"}):
            active_p = orch.get_llm_provider()
            self.assertEqual(active_p.provider_id, "custom_test_llm")

            # 3. Execute chat through core orchestrator
            response = orch.chat(messages=[{"role": "user", "content": "ping"}])
            self.assertEqual(response, "custom_response: ping")

        # 4. Unregister provider
        unregistered = llm_registry.unregister("custom_test_llm")
        self.assertTrue(unregistered)
        self.assertNotIn("custom_test_llm", llm_registry.list_providers())


if __name__ == "__main__":
    unittest.main()
