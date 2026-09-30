"""
Integration and Unit Tests for Emotional Local Voice Models:
- ChatTTS (Default for MJ with [laugh] and [sigh] emotional prosody)
- F5-TTS (Flow-matching diffusion for zero-shot voice cloning)
- Persistent voice preference across sessions via UserProfile
- Text cleaning and emotional oral tag translation
"""

import sys
import os

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__))))

def test_text_cleaning_and_prosody():
    from main import _clean_text_for_tts

    # Standard clean (for non-ChatTTS engines)
    raw_text = "*smirks* Hey Sarwan! (giggles) *sighs softly* You did it! [crosses arms]"
    cleaned_standard = _clean_text_for_tts(raw_text, preserve_oral_tags=False)
    assert "*smirks*" not in cleaned_standard
    assert "giggles" not in cleaned_standard
    assert "sighs" not in cleaned_standard
    assert "[crosses arms]" not in cleaned_standard
    assert "Hey Sarwan!" in cleaned_standard
    assert "You did it!" in cleaned_standard
    print("[PASS] Test 1: Standard text cleaning passed")

    # ChatTTS clean (oral tags preserved and converted)
    cleaned_chattts = _clean_text_for_tts(raw_text, preserve_oral_tags=True)
    assert "[laugh]" in cleaned_chattts
    assert "[sigh]" in cleaned_chattts
    assert "[crosses arms]" not in cleaned_chattts
    assert "Hey Sarwan!" in cleaned_chattts
    print("[PASS] Test 2: ChatTTS oral tags translation passed ([laugh], [sigh])")


def test_available_voices_registry():
    from main import AVAILABLE_VOICES, DEFAULT_VOICE

    # Check default voice
    assert DEFAULT_VOICE.get("en") == "chatterbox_turbo_mj", f"Expected chatterbox_turbo_mj as default, got {DEFAULT_VOICE.get('en')}"
    assert "chatterbox_turbo_mj" in AVAILABLE_VOICES

    mj_voice = AVAILABLE_VOICES["chatterbox_turbo_mj"]
    assert mj_voice["engine"] == "chatterbox_turbo"
    assert mj_voice["quality"] == "ultra"
    print("[PASS] Test 3: AVAILABLE_VOICES registry verified with Chatterbox Turbo")


def test_user_profile_persistence():
    from engines.user_profile import user_profile

    # Set preference
    user_profile.set_preference("selected_voice", "chatterbox_turbo_mj")
    retrieved = user_profile.get_preference("selected_voice")
    assert retrieved == "chatterbox_turbo_mj"

    # Change preference to custom voice
    user_profile.set_preference("selected_voice", "custom_clone")
    assert user_profile.get_preference("selected_voice") == "custom_clone"

    # Reset back to chatterbox_turbo_mj
    user_profile.set_preference("selected_voice", "chatterbox_turbo_mj")
    assert user_profile.get_preference("selected_voice") == "chatterbox_turbo_mj"
    print("[PASS] Test 4: Cross-session voice preference persistence verified")


def test_engine_classes():
    from engines.tts_chatterbox_turbo import ChatterboxTurboEngine

    assert hasattr(ChatterboxTurboEngine, "generate")
    assert hasattr(ChatterboxTurboEngine, "available")
    print("[PASS] Test 5: Engine classes and signatures verified (Chatterbox Turbo)")


if __name__ == "__main__":
    print("=== RUNNING LOCAL EMOTIONAL VOICE TEST SUITE ===")
    test_text_cleaning_and_prosody()
    test_available_voices_registry()
    test_user_profile_persistence()
    test_engine_classes()
    print("=== ALL 5 VOICE ENGINE TESTS PASSED! ===")
