"""
Unit Tests for TTS Language Router — Chatterbox Turbo
=====================================================
Verifies deterministic routing to Chatterbox Turbo for all linguistic inputs:
English, Devanagari Hindi, Latin-script Hinglish, and mixed code-switching.
"""

import sys
from pathlib import Path

# Add router directory
ROUTER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROUTER_DIR))

from language_router import select_tts_engine, detect_dialect


def test_english_routing():
    english_samples = [
        "Hello, how are you?",
        "Good morning. How can I help you today?",
        "Let me check that for you.",
        "Today I'll help you organize your tasks, answer your questions, and keep track of everything.",
        "I understand. Let me think about that for a moment.",
        "Sure, opening Google Chrome right now.",
        "The current weather in New York is sunny and twenty-five degrees Celsius.",
        "Your reminder has been set for tomorrow morning at nine.",
        "Would you like me to send an email or read your latest notifications?",
        "I am always here to assist you with any questions.",
    ]
    for text in english_samples:
        engine = select_tts_engine(text)
        assert engine == "chatterbox_turbo", f"Expected 'chatterbox_turbo' for '{text}', got '{engine}'"
        assert detect_dialect(text) == "english"
    print("  [PASS] 10/10 Pure English sentences correctly routed to Chatterbox Turbo.")


def test_hindi_devanagari_routing():
    hindi_samples = [
        "नमस्ते, आप कैसे हैं?",
        "आज मौसम बहुत अच्छा है।",
        "नमस्ते, मैं एमजे हूँ। मैं आपकी मदद करने के लिए तैयार हूँ।",
        "आप अपने काम के बारे में मुझे बताइए।",
        "क्या मैं आपकी कोई और सहायता कर सकती हूँ?",
        "कृपया एक क्षण प्रतीक्षा कीजिए।",
        "यह जानकारी आपके लिए उपलब्ध है।",
        "शुभ प्रभात! आपका दिन शुभ हो।",
        "मुझे यह सुनकर बहुत खुशी हुई।",
        "धन्यवाद! फिर मिलेंगे।",
    ]
    for text in hindi_samples:
        engine = select_tts_engine(text)
        assert engine == "chatterbox_turbo", f"Expected 'chatterbox_turbo' for '{text}', got '{engine}'"
        assert detect_dialect(text) == "devanagari_hindi"
    print("  [PASS] 10/10 Devanagari Hindi sentences correctly routed to Chatterbox Turbo.")


def test_hinglish_latin_routing():
    hinglish_samples = [
        "Hello, main aapki help kar sakti hoon.",
        "Aaj hum kya karne wale hain?",
        "Hello, main MJ hoon. Aaj main aapki kis tarah help kar sakti hoon?",
        "Aaj hum apne project ki testing shuru karenge.",
        "Aap mujhe bataiye ki kya problem hai.",
        "Theek hai, main abhi check karti hoon.",
        "Mujhe thoda samay dijiye please.",
        "Kya aapko ye samajh aaya?",
        "Main aapke sare tasks organize kar dungi.",
        "Bahut accha! Sab kuch ready hai.",
    ]
    for text in hinglish_samples:
        engine = select_tts_engine(text)
        assert engine == "chatterbox_turbo", f"Expected 'chatterbox_turbo' for '{text}', got '{engine}'"
        assert detect_dialect(text) == "latin_hinglish"
    print("  [PASS] 10/10 Latin-script Hinglish sentences correctly routed to Chatterbox Turbo.")


def test_mixed_hindi_english_routing():
    mixed_samples = [
        "आज हम आपके project की testing शुरू करेंगे.",
        "Hello! मैं आपकी screen देख सकती हूँ.",
        "कृपया wait करें, data load हो रहा है।",
        "आपका meeting schedule update हो गया है.",
        "Chrome browser open कर दिया गया है।",
        "Kya aapne new feature verify kiya hai?",
        "Please confirm kijiye ki settings save ho gayi hain.",
        "Maine task complete kar diya hai.",
        "Ye process subah start hoga.",
        "Network connection check karke report deti hoon.",
    ]
    for text in mixed_samples:
        engine = select_tts_engine(text)
        assert engine == "chatterbox_turbo", f"Expected 'chatterbox_turbo' for '{text}', got '{engine}'"
    print("  [PASS] 10/10 Mixed Hindi-English sentences correctly routed to Chatterbox Turbo.")


def test_edge_cases():
    edge_cases = [
        ("", "chatterbox_turbo"),  # empty text fallback
        ("   ", "chatterbox_turbo"),  # whitespace fallback
        ("12345 67890", "chatterbox_turbo"),  # digits
        ("OK.", "chatterbox_turbo"),  # short confirmation
        ("Haan.", "chatterbox_turbo"),  # single-word Hindi affirmation
    ]
    for text, expected in edge_cases:
        engine = select_tts_engine(text)
        assert engine == expected, f"Expected '{expected}' for '{text}', got '{engine}'"
    print("  [PASS] 5/5 Edge cases correctly routed to Chatterbox Turbo.")


if __name__ == "__main__":
    print("=======================================================")
    print("RUNNING TTS LANGUAGE ROUTER UNIT TESTS (CHATTERBOX TURBO)")
    print("=======================================================")
    test_english_routing()
    test_hindi_devanagari_routing()
    test_hinglish_latin_routing()
    test_mixed_hindi_english_routing()
    test_edge_cases()
    print("=======================================================")
    print("ALL 45 ROUTER UNIT TESTS PASSED FOR CHATTERBOX TURBO!")
    print("=======================================================")

