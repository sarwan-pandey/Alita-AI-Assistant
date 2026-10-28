"""
P2 Test Suite — NVIDIA Chatterbox Multilingual Riva gRPC Integration
======================================================================
Verifies:
  1. Riva gRPC Method, Path & Metadata:
     - Endpoints: grpc.nvcf.nvidia.com:443
     - Methods: /nvidia.riva.tts.RivaSpeechSynthesis/Synthesize
                /nvidia.riva.tts.RivaSpeechSynthesis/SynthesizeOnline
     - Function ID: ddacc747-1269-4fab-bfd9-8f593dead106
     - Auth: Bearer token & function-id metadata
  2. Multi-Language & Voice Catalog:
     - English (en / en-US)
     - Hindi (hi / hi-IN)
     - Spanish, French, German, Japanese
  3. Streaming Support:
     - Online chunk delivery & TTFA metrics
  4. Audio Container Compatibility:
     - Raw 16-bit PCM correctly wrapped into RIFF WAV for MJ audio lifecycle
  5. Fallback, Timeout & Error Sanitization:
     - Failover to local Chatterbox Turbo on timeout, 401/invalid creds, or empty audio
     - Credential stripping (nvapi-* / Bearer never exposed in logs)
     - Request ID / Turn ID propagation
  6. Phase 6D Chunk Safety (70-85 target, 90 operational, 100 absolute)
"""

import asyncio
import io
import logging
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engines.provider_contracts import ProviderStatus, TTSProviderHealth
from engines.riva_tts_grpc import (
    DEFAULT_CHATTERBOX_FUNCTION_ID,
    DEFAULT_NVCF_SERVER,
    DEFAULT_SAMPLE_RATE_HZ,
    RivaTTSClient,
    SynthesizeSpeechRequest,
    SynthesizeSpeechResponse,
    pcm_to_wav,
    sanitize_error,
)
from engines.tts_nvidia_nim import (
    VOICE_CATALOG,
    ChatterboxNIMClient,
    TTSNIMMetrics,
    get_default_voice,
    get_locale_for_language,
    normalize_voice_name,
)
from engines.tts_provider import ChatterboxLocalProvider, ChatterboxNIMProvider, FallbackTTSProvider


# ═════════════════════════════════════════════════════════════════════════════
# 1. RIVA GRPC PROTOCOL & METADATA CONTRACT TESTS
# ═════════════════════════════════════════════════════════════════════════════

class TestRivaGRPCProtocol(unittest.TestCase):
    """Verifies that the gRPC client conforms strictly to NVIDIA Riva specification."""

    def test_default_constants(self):
        self.assertEqual(DEFAULT_NVCF_SERVER, "grpc.nvcf.nvidia.com:443")
        self.assertEqual(DEFAULT_CHATTERBOX_FUNCTION_ID, "ddacc747-1269-4fab-bfd9-8f593dead106")
        self.assertEqual(DEFAULT_SAMPLE_RATE_HZ, 24000)

    def test_grpc_method_paths(self):
        client = RivaTTSClient(api_key="nvapi-test", server="test-server:443")
        self.assertEqual(client.METHOD_SYNTHESIZE, "/nvidia.riva.tts.RivaSpeechSynthesis/Synthesize")
        self.assertEqual(client.METHOD_SYNTHESIZE_ONLINE, "/nvidia.riva.tts.RivaSpeechSynthesis/SynthesizeOnline")
        self.assertEqual(client.METHOD_GET_CONFIG, "/nvidia.riva.tts.RivaSpeechSynthesis/GetRivaSynthesisConfig")

    def test_metadata_structure(self):
        client = RivaTTSClient(
            api_key="nvapi-test12345",
            server="grpc.nvcf.nvidia.com:443",
            function_id="test-function-id-99",
        )
        meta = dict(client._build_metadata())
        self.assertEqual(meta["authorization"], "Bearer nvapi-test12345")
        self.assertEqual(meta["function-id"], "test-function-id-99")

    def test_protobuf_request_serialization(self):
        req = SynthesizeSpeechRequest(
            text="Testing serialization",
            language_code="en-US",
            encoding=1,
            sample_rate_hz=24000,
            voice_name="Chatterbox-Multilingual.en-US.Male",
        )
        req.id.value = "turn-req-001"
        data = req.SerializeToString()
        self.assertGreater(len(data), 0)

        # Parse back
        parsed = SynthesizeSpeechRequest()
        parsed.ParseFromString(data)
        self.assertEqual(parsed.text, "Testing serialization")
        self.assertEqual(parsed.language_code, "en-US")
        self.assertEqual(parsed.encoding, 1)
        self.assertEqual(parsed.sample_rate_hz, 24000)
        self.assertEqual(parsed.voice_name, "Chatterbox-Multilingual.en-US.Male")
        self.assertEqual(parsed.id.value, "turn-req-001")


# ═════════════════════════════════════════════════════════════════════════════
# 2. AUDIO WRAPPING & CHUNK SAFETY
# ═════════════════════════════════════════════════════════════════════════════

class TestAudioWrappingAndChunkSafety(unittest.TestCase):
    """Verifies 16-bit PCM wrapping to RIFF WAV and Phase 6D chunk limits."""

    def test_pcm_to_wav_conversion(self):
        # 48000 bytes = 24000 samples of 16-bit audio = 1.0 second at 24kHz
        fake_pcm = b"\x00\x00" * 24000
        wav = pcm_to_wav(fake_pcm, sample_rate=24000)

        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertEqual(len(wav), 44 + len(fake_pcm))

        # Check soundfile can parse it
        data, sr = sf.read(io.BytesIO(wav))
        self.assertEqual(sr, 24000)
        self.assertEqual(len(data), 24000)

    def test_pcm_to_wav_idempotent(self):
        already_wav = b"RIFF" + b"\x00" * 50
        res = pcm_to_wav(already_wav)
        self.assertEqual(res, already_wav)

    def test_chunk_safety_preservation(self):
        from core.chunk_utils import (
            ABSOLUTE_SAFETY_LIMIT,
            OPERATIONAL_HARD_LIMIT,
            chunk_text_hard_safety,
        )
        long_paragraph = (
            "NVIDIA Chatterbox Multilingual provides high quality synthesized audio "
            "across twenty-three languages when conditioned on proper language tags."
        ) * 3

        chunks = chunk_text_hard_safety(
            long_paragraph,
            hard_limit=OPERATIONAL_HARD_LIMIT,
            absolute_limit=ABSOLUTE_SAFETY_LIMIT,
        )
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk), ABSOLUTE_SAFETY_LIMIT)


# ═════════════════════════════════════════════════════════════════════════════
# 3. CATALOG & VOICE RESOLUTION
# ═════════════════════════════════════════════════════════════════════════════

class TestVoiceAndLanguageCatalog(unittest.TestCase):
    """Verifies language code to locale and subvoice resolution."""

    def test_english_resolution(self):
        self.assertEqual(get_locale_for_language("en"), "en-US")
        voice = get_default_voice("en")
        self.assertEqual(voice, "Chatterbox-Multilingual.en-US.Male")

    def test_hindi_resolution(self):
        self.assertEqual(get_locale_for_language("hi"), "hi-IN")
        voice = get_default_voice("hi")
        self.assertEqual(voice, "Chatterbox-Multilingual.hi-IN.Male")

    def test_multilingual_locales(self):
        test_langs = [("es", "es-ES"), ("fr", "fr-FR"), ("de", "de-DE"), ("ja", "ja-JP"), ("ko", "ko-KR"), ("zh", "zh-CN")]
        for lang, expected_loc in test_langs:
            self.assertEqual(get_locale_for_language(lang), expected_loc)
            voice = get_default_voice(lang)
            self.assertIn(expected_loc, voice)
            self.assertTrue(voice.endswith(".Male"))

    def test_voice_name_normalization(self):
        # Maps requested female voice to official server male subvoice
        normalized = normalize_voice_name("Chatterbox-Multilingual.en-US.Female", "en")
        self.assertEqual(normalized, "Chatterbox-Multilingual.en-US.Male")

        # Preserves correct subvoice
        self.assertEqual(
            normalize_voice_name("Chatterbox-Multilingual.hi-IN.Male", "hi"),
            "Chatterbox-Multilingual.hi-IN.Male",
        )


# ═════════════════════════════════════════════════════════════════════════════
# 4. DETERMINISTIC FALLBACK & CREDENTIAL SANITIZATION
# ═════════════════════════════════════════════════════════════════════════════

class TestFallbackAndResilience(unittest.TestCase):
    """Verifies that failure/timeout triggers fallback to local Turbo without leaking keys."""

    def test_sanitization_removes_keys(self):
        err = "RpcError: 401 Unauthorized for Bearer nvapi-secret_key_1234567890abcdef"
        sanitized = sanitize_error(err)
        self.assertNotIn("nvapi-secret_key_1234567890abcdef", sanitized)
        self.assertIn("Bearer [REDACTED]", sanitized)

    def test_timeout_fallback_to_turbo(self):
        mock_nim = AsyncMock()
        mock_nim.provider_id = "chatterbox_multilingual_nim"
        mock_nim.synthesize.side_effect = TimeoutError("Deadline exceeded nvapi-token999")

        mock_turbo = AsyncMock()
        mock_turbo.provider_id = "chatterbox_local"
        mock_turbo.synthesize.return_value = b"RIFF" + b"\x00" * 50

        provider = FallbackTTSProvider(primary=mock_nim, fallback=mock_turbo, enabled=True, timeout=2.0)
        res = asyncio.run(provider.synthesize("Hello world", turn_id="turn_fallback_01"))

        self.assertEqual(res, b"RIFF" + b"\x00" * 50)
        mock_nim.synthesize.assert_called_once()
        mock_turbo.synthesize.assert_called_once()
        # Verify provider status tracked failure
        self.assertEqual(provider._health.status, ProviderStatus.DEGRADED)
        self.assertNotIn("nvapi-token999", provider._health.last_error)

    def test_empty_response_fallback_to_turbo(self):
        mock_nim = AsyncMock()
        mock_nim.provider_id = "chatterbox_multilingual_nim"
        mock_nim.synthesize.return_value = b""  # Empty audio

        mock_turbo = AsyncMock()
        mock_turbo.provider_id = "chatterbox_local"
        mock_turbo.synthesize.return_value = b"RIFF" + b"\x00" * 50

        provider = FallbackTTSProvider(primary=mock_nim, fallback=mock_turbo, enabled=True)
        res = asyncio.run(provider.synthesize("Empty test", turn_id="turn_fallback_02"))

        self.assertEqual(res, b"RIFF" + b"\x00" * 50)
        mock_turbo.synthesize.assert_called_once()

    def test_turn_id_preserved_through_call(self):
        mock_nim = AsyncMock()
        mock_nim.provider_id = "chatterbox_multilingual_nim"
        mock_nim.synthesize.return_value = b"RIFF" + b"\x00" * 50

        provider = FallbackTTSProvider(primary=mock_nim, enabled=True)
        asyncio.run(provider.synthesize("Turn test", turn_id="preserve_turn_xyz"))

        _, kwargs = mock_nim.synthesize.call_args
        self.assertEqual(kwargs.get("turn_id"), "preserve_turn_xyz")

    def test_invalid_credentials_fallback_to_turbo(self):
        mock_nim = AsyncMock()
        mock_nim.provider_id = "chatterbox_multilingual_nim"
        mock_nim.synthesize.side_effect = RuntimeError("RpcError: 401 UNAUTHENTICATED Bearer nvapi-badkey123")

        mock_turbo = AsyncMock()
        mock_turbo.provider_id = "chatterbox_local"
        mock_turbo.synthesize.return_value = b"RIFF" + b"\x00" * 50

        provider = FallbackTTSProvider(primary=mock_nim, fallback=mock_turbo, enabled=True)
        res = asyncio.run(provider.synthesize("Invalid creds test", turn_id="turn_bad_creds"))

        self.assertEqual(res, b"RIFF" + b"\x00" * 50)
        mock_turbo.synthesize.assert_called_once()
        self.assertNotIn("nvapi-badkey123", provider._health.last_error)
        self.assertIn("Bearer [REDACTED]", provider._health.last_error)


# ═════════════════════════════════════════════════════════════════════════════
# 5. LIVE NVIDIA RIVA GRPC SYNTHESIS (SKIPPED IF NO API KEY)
# ═════════════════════════════════════════════════════════════════════════════

class TestLiveRivaGRPCSynthesis(unittest.TestCase):
    """
    Live verification of NVIDIA Chatterbox Multilingual via Riva gRPC.
    Requires valid NVIDIA_API_KEY in environment or .env.
    """

    @classmethod
    def setUpClass(cls):
        cls.api_key = os.getenv("NVIDIA_API_KEY", "").strip()
        if not cls.api_key:
            # Try reading from .env
            env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
            if os.path.exists(env_path):
                with open(env_path, "r") as f:
                    for line in f:
                        if line.startswith("NVIDIA_API_KEY="):
                            cls.api_key = line.strip().split("=", 1)[1].strip()
                            break

    def setUp(self):
        if not self.api_key:
            self.skipTest("NVIDIA_API_KEY not configured — skipping live gRPC test")
        # Gentle pacing for NVCF cloud rate limit
        time.sleep(1.0)

    def test_live_english_synthesis(self):
        client = ChatterboxNIMClient(api_key=self.api_key)
        t0 = time.perf_counter()
        wav, metrics = asyncio.run(
            client.synthesize_with_metrics(
                "Hello, this is NVIDIA Chatterbox Multilingual speech synthesis.",
                language="en",
                turn_id="live_test_en",
            )
        )
        if not metrics.success and "rate limit" in metrics.error.lower():
            self.skipTest(f"NVCF cloud rate limit reached: {metrics.error}")
        self.assertTrue(metrics.success, f"Failed: {metrics.error}")
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertGreater(len(wav), 1000)
        self.assertGreater(metrics.total_ms, 0)
        print(f"\n[LIVE TEST] English: {len(wav)} bytes in {metrics.total_ms:.1f}ms (TTFA={metrics.ttfa_ms:.1f}ms)")

    def test_live_hindi_synthesis(self):
        client = ChatterboxNIMClient(api_key=self.api_key)
        for attempt in range(2):
            wav, metrics = asyncio.run(
                client.synthesize_with_metrics(
                    "नमस्ते, अलिता आवाज़ सहायक में आपका स्वागत है।",
                    language="hi",
                    turn_id="live_test_hi",
                )
            )
            if metrics.success:
                break
            if "rate limit" in metrics.error.lower():
                time.sleep(2.0)
            else:
                break

        if not metrics.success and "rate limit" in metrics.error.lower():
            self.skipTest(f"NVCF cloud rate limit reached: {metrics.error}")
        self.assertTrue(metrics.success, f"Failed: {metrics.error}")
        self.assertTrue(wav.startswith(b"RIFF"))
        self.assertGreater(len(wav), 1000)
        print(f"\n[LIVE TEST] Hindi: {len(wav)} bytes in {metrics.total_ms:.1f}ms (TTFA={metrics.ttfa_ms:.1f}ms)")

    def test_live_additional_languages(self):
        """Test at least 3 additional languages as required by P2."""
        client = ChatterboxNIMClient(api_key=self.api_key)
        additional_languages = [
            ("es", "Hola, soy el asistente de voz."),
            ("fr", "Bonjour, je suis l'assistant vocal."),
            ("de", "Hallo, ich bin der Sprachassistent."),
        ]
        for lang, text in additional_languages:
            time.sleep(1.0)
            wav, metrics = asyncio.run(
                client.synthesize_with_metrics(
                    text,
                    language=lang,
                    turn_id=f"live_test_{lang}",
                )
            )
            if not metrics.success and "rate limit" in metrics.error.lower():
                self.skipTest(f"NVCF cloud rate limit reached: {metrics.error}")
            self.assertTrue(metrics.success, f"Failed for {lang}: {metrics.error}")
            self.assertTrue(wav.startswith(b"RIFF"))
            self.assertGreater(len(wav), 1000)
            print(f"\n[LIVE TEST] {lang.upper()}: {len(wav)} bytes in {metrics.total_ms:.1f}ms")

    def test_live_streaming_online(self):
        """Test SynthesizeOnline streaming chunks."""
        client = ChatterboxNIMClient(api_key=self.api_key)
        t0 = time.perf_counter()
        chunks = []
        try:
            for chunk in client.synthesize_stream("Real-time streaming test for speech synthesis.", language="en"):
                chunks.append(chunk)
        except Exception as exc:
            if "rate limit" in str(exc).lower():
                self.skipTest(f"NVCF cloud rate limit reached on streaming: {exc}")
            raise

        self.assertGreater(len(chunks), 0)
        total_pcm = b"".join(chunks)
        total_ms = (time.perf_counter() - t0) * 1000
        self.assertGreater(len(total_pcm), 1000)
        print(f"\n[LIVE TEST] Streaming: {len(chunks)} chunks, {len(total_pcm)} bytes in {total_ms:.1f}ms")


if __name__ == "__main__":
    unittest.main()
