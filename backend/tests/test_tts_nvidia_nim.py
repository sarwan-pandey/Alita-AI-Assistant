"""
NVIDIA NIM Chatterbox Multilingual TTS Tests
==============================================
Unit tests (no NIM required) + integration tests (require running NIM).
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═════════════════════════════════════════════════════════════════════════════
# §1  UNIT TESTS — No NIM required
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceCatalog:
    """Tests for the voice catalog and selection logic."""

    def test_catalog_not_empty(self):
        from engines.tts_nvidia_nim import VOICE_CATALOG
        assert len(VOICE_CATALOG) >= 20

    def test_catalog_has_english(self):
        from engines.tts_nvidia_nim import VOICE_CATALOG
        en_voices = [v for v in VOICE_CATALOG if v.language == "en"]
        assert len(en_voices) >= 2  # Male and Female at minimum

    def test_catalog_has_hindi(self):
        from engines.tts_nvidia_nim import VOICE_CATALOG
        hi_voices = [v for v in VOICE_CATALOG if v.language == "hi"]
        assert len(hi_voices) >= 2

    def test_catalog_languages(self):
        """Catalog covers required languages."""
        from engines.tts_nvidia_nim import VOICE_CATALOG
        languages = {v.language for v in VOICE_CATALOG}
        required = {"en", "hi", "es", "fr", "de", "ja", "ko", "zh", "pt", "ru", "ar"}
        for lang in required:
            assert lang in languages, f"Missing language: {lang}"

    def test_voice_id_format(self):
        """All voice IDs follow the expected naming convention."""
        from engines.tts_nvidia_nim import VOICE_CATALOG
        for v in VOICE_CATALOG:
            assert v.voice_id.startswith("Chatterbox-Multilingual."), f"Bad ID: {v.voice_id}"
            parts = v.voice_id.split(".")
            assert len(parts) == 3, f"Expected 3 parts in {v.voice_id}"
            assert parts[2] in ("Male", "Female"), f"Bad gender in {v.voice_id}"

    def test_default_voice_english(self):
        from engines.tts_nvidia_nim import get_default_voice
        voice = get_default_voice("en", "Female")
        assert "en-US" in voice
        assert "Female" in voice

    def test_default_voice_hindi(self):
        from engines.tts_nvidia_nim import get_default_voice
        voice = get_default_voice("hi", "Male")
        assert "hi-IN" in voice
        assert "Male" in voice

    def test_default_voice_fallback(self):
        """Unknown language falls back to English."""
        from engines.tts_nvidia_nim import get_default_voice
        voice = get_default_voice("xx", "Female")
        assert "en-US" in voice

    def test_locale_mapping(self):
        from engines.tts_nvidia_nim import get_locale_for_language
        assert get_locale_for_language("en") == "en-US"
        assert get_locale_for_language("hi") == "hi-IN"
        assert get_locale_for_language("es") == "es-ES"
        assert get_locale_for_language("xx") == "en-US"  # fallback


class TestMetrics:
    """Tests for TTSNIMMetrics."""

    def test_metrics_defaults(self):
        from engines.tts_nvidia_nim import TTSNIMMetrics
        m = TTSNIMMetrics()
        assert m.success is False
        assert m.total_ms == 0.0
        assert m.error == ""

    def test_metrics_finalize(self):
        from engines.tts_nvidia_nim import TTSNIMMetrics
        m = TTSNIMMetrics()
        m.request_start = 100.0
        m.first_audio_time = 100.5
        m.response_complete_time = 101.0
        m.finalize()
        assert abs(m.ttfa_ms - 500.0) < 1.0
        assert abs(m.total_ms - 1000.0) < 1.0

    def test_metrics_summary(self):
        from engines.tts_nvidia_nim import TTSNIMMetrics
        m = TTSNIMMetrics(
            success=True,
            total_ms=500.0,
            ttfa_ms=200.0,
            audio_bytes=48000,
            language="en",
            voice="test",
            text_length=30,
        )
        s = m.summary()
        assert "nim_tts" in s
        assert "OK" in s
        assert "500ms" in s


class TestClientInit:
    """Tests for NIM TTS client initialization."""

    def test_import(self):
        from engines.tts_nvidia_nim import ChatterboxNIMClient, get_nim_tts_client
        assert ChatterboxNIMClient is not None
        assert callable(get_nim_tts_client)

    def test_client_default_url(self):
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient(api_key="")
        assert "localhost:9000" in client.nim_url

    def test_client_custom_url(self):
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient(nim_url="http://my-nim:9000")
        assert client.nim_url == "http://my-nim:9000"

    def test_client_available(self):
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient(nim_url="http://localhost:9000")
        assert client.available is True


class TestChunkSafety:
    """Tests that chunk safety is preserved in the NIM path."""

    def test_chunk_constants_exist(self):
        from core.chunk_utils import (
            TARGET_MIN_CHARS, TARGET_MAX_CHARS,
            OPERATIONAL_HARD_LIMIT, ABSOLUTE_SAFETY_LIMIT,
        )
        assert TARGET_MIN_CHARS == 70
        assert TARGET_MAX_CHARS == 85
        assert OPERATIONAL_HARD_LIMIT == 90
        assert ABSOLUTE_SAFETY_LIMIT == 100

    def test_chunk_safety_applied(self):
        """Verify chunk_text_hard_safety produces chunks <= ABSOLUTE_SAFETY_LIMIT."""
        from core.chunk_utils import chunk_text_hard_safety, OPERATIONAL_HARD_LIMIT, ABSOLUTE_SAFETY_LIMIT
        long_text = "This is a long sentence that goes well beyond ninety characters. " * 5
        chunks = chunk_text_hard_safety(
            long_text, hard_limit=OPERATIONAL_HARD_LIMIT, absolute_limit=ABSOLUTE_SAFETY_LIMIT
        )
        for chunk in chunks:
            assert len(chunk) <= ABSOLUTE_SAFETY_LIMIT, f"Chunk too long ({len(chunk)}): '{chunk}'"


class TestBenchmarkStructure:
    """Tests for TTS benchmark module structure."""

    def test_import(self):
        from engines.tts_nim_benchmark import run_tts_benchmark, TEST_PROMPTS
        assert callable(run_tts_benchmark)
        assert len(TEST_PROMPTS) >= 5

    def test_prompt_languages(self):
        from engines.tts_nim_benchmark import TEST_PROMPTS
        languages = {p.language for p in TEST_PROMPTS}
        assert "en" in languages
        assert "hi" in languages

    def test_prompts_have_descriptions(self):
        from engines.tts_nim_benchmark import TEST_PROMPTS
        for p in TEST_PROMPTS:
            assert p.description
            assert p.text
            assert p.language


class TestProductionPreservation:
    """Verify production TTS code is NOT modified."""

    def test_tts_dispatch_unchanged(self):
        """tts_dispatch.py does not import NIM module."""
        import inspect
        from tts_dispatch import _tts_generate
        source = inspect.getsource(_tts_generate)
        assert "tts_nvidia_nim" not in source
        assert "ChatterboxNIMClient" not in source

    def test_tts_dispatch_uses_local(self):
        """Production dispatch still routes to Chatterbox Turbo."""
        import inspect
        from tts_dispatch import _tts_generate
        source = inspect.getsource(_tts_generate)
        assert "chatterbox_turbo_engine" in source

    def test_no_production_imports(self):
        """No production code imports the NIM TTS module."""
        import ast
        prod_files = [
            "tts_dispatch.py",
            "general_handler.py",
            "main.py",
        ]
        for fname in prod_files:
            fpath = os.path.join(os.path.dirname(__file__), "..", fname)
            if not os.path.exists(fpath):
                continue
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            assert "tts_nvidia_nim" not in content, f"{fname} imports tts_nvidia_nim!"

    def test_voice_clone_path_intact(self):
        """voice_clone.py still exists and is not modified by NIM integration."""
        clone_path = os.path.join(os.path.dirname(__file__), "..", "routers", "voice_clone.py")
        assert os.path.exists(clone_path), "routers/voice_clone.py is missing!"


# ═════════════════════════════════════════════════════════════════════════════
# §2  INTEGRATION TESTS — Require running NIM
# ═════════════════════════════════════════════════════════════════════════════

class TestNIMIntegration:
    """Live NIM integration tests — skipped if NIM not reachable."""

    @pytest.fixture(autouse=True)
    def _check_nim(self):
        """Skip if NIM endpoint is not reachable."""
        nim_url = os.getenv("NVIDIA_NIM_TTS_URL", "")
        if not nim_url:
            pytest.skip("NVIDIA_NIM_TTS_URL not set")

    @pytest.mark.asyncio
    async def test_nim_health(self):
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient()
        health = await client.health_check()
        assert health["available"] is True, f"Health failed: {health}"
        await client.close()

    @pytest.mark.asyncio
    async def test_nim_synthesize_english(self):
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient()
        audio, metrics = await client.synthesize_with_metrics(
            "Hello world!", language="en"
        )
        assert metrics.success, f"Failed: {metrics.error}"
        assert len(audio) > 44  # More than just WAV header
        assert metrics.total_ms > 0
        print(f"\n  {metrics.summary()}")
        await client.close()

    @pytest.mark.asyncio
    async def test_nim_synthesize_hindi(self):
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient()
        audio, metrics = await client.synthesize_with_metrics(
            "Namaste! Aap kaise hain?", language="hi"
        )
        assert metrics.success, f"Failed: {metrics.error}"
        assert len(audio) > 44
        print(f"\n  {metrics.summary()}")
        await client.close()

    @pytest.mark.asyncio
    async def test_nim_chunked_synthesis(self):
        """Test multi-chunk synthesis with Phase 6D safety."""
        from engines.tts_nvidia_nim import ChatterboxNIMClient
        client = ChatterboxNIMClient()
        long_text = (
            "Here is a longer text that should be split into multiple chunks. "
            "Each chunk should be under ninety characters for safety. "
            "This tests the chunking and audio concatenation pipeline."
        )
        audio, metrics_list = await client.synthesize_chunked(long_text, language="en")
        assert audio, "No audio produced"
        assert len(metrics_list) >= 1
        for m in metrics_list:
            assert m.text_length <= 100, f"Chunk too long: {m.text_length}"
        print(f"\n  Chunks: {len(metrics_list)}, Total audio: {len(audio)} bytes")
        await client.close()
