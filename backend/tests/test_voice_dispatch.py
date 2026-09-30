"""
Test Suite: Voice Engine Dispatch (Chatterbox Turbo Only)
==========================================================
Validates:
1. resolve_tts_engine returns 'chatterbox_turbo'.
2. Mocked _tts_generate invokes Chatterbox-Turbo engine.
3. AVAILABLE_VOICES registry contains chatterbox_turbo_mj.
4. Empty text / failed engine returns b"" cleanly without crash.
"""

import sys
import os
import asyncio
from pathlib import Path

# Ensure backend directory is in sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import main as main_app
from core.diagnostics import resolve_tts_engine


def test_turbo_dispatch_resolution():
    print("\n" + "=" * 75)
    print("TEST SUITE 1: TURBO-ONLY ENGINE RESOLUTION")
    print("=" * 75)

    voice_turbo = main_app.AVAILABLE_VOICES["chatterbox_turbo_mj"]
    diag = resolve_tts_engine("Hello world", voice_turbo, main_app.settings.tts_engine_mode)
    print(f"  resolve_tts_engine returned: {diag}")
    assert diag == "chatterbox_turbo", f"Expected 'chatterbox_turbo', got '{diag}'"
    print("  [PASS] resolve_tts_engine returns chatterbox_turbo")


def test_generation_dispatch_mocked():
    print("\n" + "=" * 75)
    print("TEST SUITE 2: MOCKED TURBO GENERATION DISPATCH")
    print("=" * 75)

    class MockTurboEngine:
        def __init__(self):
            self.available = True
            self.calls = []

        def generate(self, text, *args, **kwargs):
            self.calls.append(text)
            return b"RIFFmockWAVdata"

    mock_turbo = MockTurboEngine()
    orig_turbo = main_app.engines.chatterbox_turbo_engine
    main_app.engines.chatterbox_turbo_engine = mock_turbo

    try:
        voice = main_app.AVAILABLE_VOICES["chatterbox_turbo_mj"]
        audio = asyncio.run(main_app._tts_generate(
            "Hello! [laugh] This is a test of Chatterbox Turbo.",
            voice
        ))
        assert len(mock_turbo.calls) == 1, f"Expected 1 call, got {len(mock_turbo.calls)}"
        assert audio == b"RIFFmockWAVdata", "Expected mock WAV bytes"
        # Check that oral tags [laugh] were preserved
        assert "[laugh]" in mock_turbo.calls[0], "Oral tag [laugh] was not preserved"
        print("  [PASS] Chatterbox-Turbo engine invoked with oral tags preserved")

        # Test empty text handling
        empty_audio = asyncio.run(main_app._tts_generate("   ", voice))
        assert empty_audio == b"", "Empty text should return b''"
        print("  [PASS] Empty text handled safely")

    finally:
        main_app.engines.chatterbox_turbo_engine = orig_turbo


def test_registry_sweep():
    print("\n" + "=" * 75)
    print("TEST SUITE 3: AVAILABLE_VOICES REGISTRY SWEEP")
    print("=" * 75)

    voices = main_app.AVAILABLE_VOICES
    assert len(voices) == 1, f"Expected exactly 1 voice, got {len(voices)}"
    assert "chatterbox_turbo_mj" in voices, "chatterbox_turbo_mj missing"

    vinfo = voices["chatterbox_turbo_mj"]
    speaker_wav = vinfo.get("speaker_wav")
    if speaker_wav:
        wav_path = _BACKEND_DIR / speaker_wav
        exists = wav_path.is_file()
        print(f"  - Speaker WAV Exists: {exists} ({wav_path})")
        assert exists, f"Reference audio not found at {wav_path}!"

    print("  [PASS] AVAILABLE_VOICES registry verified cleanly")


if __name__ == "__main__":
    test_turbo_dispatch_resolution()
    test_generation_dispatch_mocked()
    test_registry_sweep()
    print("\n" + "=" * 75)
    print("[SUCCESS] ALL VOICE DISPATCH TESTS COMPLETED SUCCESSFULLY!")
    print("=" * 75)
