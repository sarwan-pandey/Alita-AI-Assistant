"""
Smoke test for Chatterbox Turbo-only migration.
This test should FAIL before migration and PASS after.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_only_turbo_in_available_voices():
    """AVAILABLE_VOICES must contain exactly one voice: chatterbox_turbo_mj."""
    from main import AVAILABLE_VOICES
    assert "chatterbox_turbo_mj" in AVAILABLE_VOICES, "chatterbox_turbo_mj missing"
    assert "chattts_mj" not in AVAILABLE_VOICES, "chattts_mj should be removed"
    assert "f5_mj_clone" not in AVAILABLE_VOICES, "f5_mj_clone should be removed"
    assert "chatterbox_mj" not in AVAILABLE_VOICES, "chatterbox_mj should be removed"
    print("[PASS] Only chatterbox_turbo_mj in AVAILABLE_VOICES")


def test_default_voice_is_turbo():
    """DEFAULT_VOICE must point to chatterbox_turbo_mj for all languages."""
    from main import DEFAULT_VOICE, _default_active_voice
    assert _default_active_voice == "chatterbox_turbo_mj"
    for lang, voice_id in DEFAULT_VOICE.items():
        assert voice_id == "chatterbox_turbo_mj", f"DEFAULT_VOICE[{lang}] = {voice_id}"
    print("[PASS] DEFAULT_VOICE all point to chatterbox_turbo_mj")


def test_engine_registry_has_turbo_slot():
    """EngineRegistry must have chatterbox_turbo_engine attribute."""
    from main import EngineRegistry
    reg = EngineRegistry()
    assert hasattr(reg, "chatterbox_turbo_engine"), "Missing chatterbox_turbo_engine"
    print("[PASS] EngineRegistry has chatterbox_turbo_engine")


def test_no_chattts_in_registry():
    """EngineRegistry must NOT have chattts_engine."""
    from main import EngineRegistry
    reg = EngineRegistry()
    assert not hasattr(reg, "chattts_engine"), "chattts_engine should be removed"
    print("[PASS] No chattts_engine in EngineRegistry")


def test_no_f5_in_registry():
    """EngineRegistry must NOT have f5_engine."""
    from main import EngineRegistry
    reg = EngineRegistry()
    assert not hasattr(reg, "f5_engine"), "f5_engine should be removed"
    print("[PASS] No f5_engine in EngineRegistry")


def test_tts_dispatch_imports():
    """tts_dispatch must export _tts_generate and get_or_load_turbo_engine."""
    from tts_dispatch import _tts_generate, get_or_load_turbo_engine
    assert callable(_tts_generate)
    assert callable(get_or_load_turbo_engine)
    print("[PASS] tts_dispatch exports correct functions")


if __name__ == "__main__":
    test_only_turbo_in_available_voices()
    test_default_voice_is_turbo()
    test_engine_registry_has_turbo_slot()
    test_no_chattts_in_registry()
    test_no_f5_in_registry()
    test_tts_dispatch_imports()
    print("\n[SUCCESS] ALL SMOKE TESTS PASSED")
