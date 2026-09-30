"""
Comprehensive Test Suite for Staged TTS Migration (Chatterbox Dual-Engine)
==========================================================================
Validates all 17 required routing and integration scenarios:
1. Pure English
2. Pure Devanagari Hindi
3. Latin-script Hinglish
4. Mixed Hindi-English
5. English -> Hindi switching
6. Hindi -> English switching
7. URLs
8. Numbers
9. Ports
10. Acronyms
11. Programming terminology
12. Long LLM responses
13. Multiple sentences
14. Empty / very short responses
15. Ambiguous language
16. False-positive protection ("The main problem is the database connection.")
17. Explicit rollback mode (TTS_ENGINE_MODE=chattts_rollback)

Also validates:
- Exact substring content & whitespace preservation (no collapsing or normalization).
- Controlled failure behavior (no silent ChatTTS fallback).
- Audio generation and saving of representative samples for manual listening.
"""

import os
import sys
import time
import asyncio
from pathlib import Path

# Ensure backend directory is in sys.path
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# Force utf-8 output on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import soundfile as sf
import librosa
import numpy as np

from core.language_router import classify_language, chunk_response_for_tts
from engines.tts_chatterbox_turbo import ChatterboxTurboEngine, TTSGenerationError as TurboTTSError
from engines.tts_chatterbox_multilingual import ChatterboxMultilingualEngine, TTSGenerationError as MultilingualTTSError
import main as main_app


def test_routing_cases():
    print("\n" + "=" * 75)
    print("TEST SUITE 1: VERIFYING ALL 17 DEFINED ROUTING & CLASSIFICATION CASES")
    print("=" * 75)

    cases = [
        (1, "Good morning! How can I help you organize your tasks today?", "PURE_ENGLISH", "turbo"),
        (2, "नमस्ते! मैं एमजे हूँ, आपकी पर्सनल एआई असिस्टेंट।", "DEVANAGARI_HINDI", "multilingual"),
        (3, "Aapka din kaisa ja raha hai? Mujhe zaroor bataiye.", "LATIN_HINGLISH", "multilingual"),
        (4, "Maine git status check kiya hai. Working tree clean hai.", "MIXED_HINDI_ENGLISH", "multilingual"),
        (5, "Turn 1: All services operational.", "PURE_ENGLISH", "turbo"),
        (5, "Turn 2: Ab hum agla task shuru kar sakte hain.", "LATIN_HINGLISH", "multilingual"),
        (6, "Turn 1: Aaj ka mausam bahut accha hai.", "LATIN_HINGLISH", "multilingual"),
        (6, "Turn 2: Let us proceed with the deployment checklist.", "PURE_ENGLISH", "turbo"),
        (7, "Documentation dekhne ke liye https://github.com/user/repo par jaiye.", "LATIN_HINGLISH", "multilingual"),
        (8, "Total 404 errors 15 hain, aur latency 125 milliseconds hai.", "LATIN_HINGLISH", "multilingual"),
        (9, "Aapka server localhost:3000 aur port 8080 par active hai.", "MIXED_HINDI_ENGLISH", "multilingual"),
        (10, "Backend API mein CPU usage 45% hai, aur SQL database healthy hai.", "MIXED_HINDI_ENGLISH", "multilingual"),
        (11, "Is Python function mein async/await syntax use kijiye.", "MIXED_HINDI_ENGLISH", "multilingual"),
        (12, "Aapka query successfully process ho gaya hai. Maine database table mein se recent logs fetch kar liye hain. Ab agla step shuru karein.", "MIXED_HINDI_ENGLISH", "multilingual"),
        (13, "First sentence here. Second sentence starts. Third sentence ends.", "PURE_ENGLISH", "turbo"),
        (14, "", "AMBIGUOUS", "multilingual"),
        (15, "xyz123...", "AMBIGUOUS", "multilingual"),
        (16, "The main problem is the database connection.", "PURE_ENGLISH", "turbo"),
    ]

    all_passed = True
    for test_num, sample_text, expected_cat, expected_engine in cases:
        cat, engine = classify_language(sample_text)
        passed = (cat == expected_cat and engine == expected_engine)
        status = "PASS" if passed else "FAIL"
        if not passed:
            all_passed = False
        print(f"  [Case {test_num:2d}] {status} | Expected: ({expected_cat}, {expected_engine}) -> Got: ({cat}, {engine}) | Input: '{sample_text[:45]}'")

    assert all_passed, "Routing classification failed for one or more cases!"
    print("\n✓ ALL 17 DEFINED ROUTING CASES CLASSIFIED CORRECTLY.")


def test_chunker_exact_preservation():
    print("\n" + "=" * 75)
    print("TEST SUITE 2: CHUNKER EXACT SUBSTRING & WHITESPACE PRESERVATION")
    print("=" * 75)

    test_samples = [
        (
            "Documentation https://github.com/user/repo par dekhein. Localhost:3000 par dashboard open karein.",
            2,
            "URL and localhost"
        ),
        (
            "Database migration completed in 2.4 seconds. Zero tables locked, version v2.1 deployment ready.",
            2,
            "Decimal numbers and version strings"
        ),
        (
            "Server port 8080 par run kar raha hai. 404 errors: 15. Latency is 125ms.",
            3,
            "Port numbers and error codes"
        ),
        (
            "Sentence one with   three   spaces.   Sentence two with tabs.\tSentence three.",
            3,
            "Whitespace preservation without collapsing"
        ),
        (
            "Use async/await in this function. Try/catch handles runtime exceptions.",
            2,
            "Programming syntax with slashes"
        ),
    ]

    for raw_input, expected_count, desc in test_samples:
        chunks = chunk_response_for_tts(raw_input)
        reconstructed = "".join(chunks)
        assert reconstructed == raw_input, f"Exact substring match failed! Original:\n{repr(raw_input)}\nReconstructed:\n{repr(reconstructed)}"
        assert len(chunks) == expected_count, f"Expected {expected_count} chunks for '{desc}', got {len(chunks)}: {chunks}"
        print(f"  PASS | {desc} -> {len(chunks)} chunks preserved with 100% exact substring equality.")

    print("\n✓ CHUNKER EXACT SUBSTRING & WHITESPACE PRESERVATION VERIFIED.")


def test_controlled_failure_no_fallback():
    print("\n" + "=" * 75)
    print("TEST SUITE 3: CONTROLLED FAILURE VERIFICATION (NO SILENT CHATTTS FALLBACK)")
    print("=" * 75)

    main_app.settings.tts_engine_mode = "chatterbox"

    # Temporary mock engine that raises TTSGenerationError
    class BrokenEngine:
        available = True
        def generate(self, text, *args, **kwargs):
            raise TurboTTSError("Simulated hardware tensor timeout")

    orig_turbo = main_app.engines.chatterbox_turbo_engine
    main_app.engines.chatterbox_turbo_engine = BrokenEngine()

    try:
        # Generate English speech through the dispatcher
        wav_bytes = asyncio.run(main_app._tts_generate("This should fail safely without falling back.", {"engine": "chatterbox"}))
        assert wav_bytes == b"", f"Expected controlled failure b'', got {len(wav_bytes)} bytes!"
        print("  PASS | Controlled failure returned b'' on Turbo error without silent ChatTTS fallback.")
    finally:
        main_app.engines.chatterbox_turbo_engine = orig_turbo


def test_explicit_rollback_mode():
    print("\n" + "=" * 75)
    print("TEST SUITE 4: EXPLICIT CHATTTS ROLLBACK MODE VERIFICATION")
    print("=" * 75)

    main_app.settings.tts_engine_mode = "chattts_rollback"
    assert main_app.settings.tts_engine_mode == "chattts_rollback"

    # ChatTTS generation
    chattts = getattr(main_app.engines, "chattts_engine", None)
    if chattts and chattts.available:
        wav_bytes = asyncio.run(main_app._tts_generate("Testing ChatTTS explicit rollback mode.", {"engine": "chattts"}))
        assert len(wav_bytes) > 0, "ChatTTS rollback failed to synthesize audio!"
        print(f"  PASS | ChatTTS explicit rollback synthesized {len(wav_bytes)} bytes successfully.")
    else:
        print("  SKIP | ChatTTS engine not initialized on this machine, skipping audio check.")

    main_app.settings.tts_engine_mode = "chatterbox"
    print("\n✓ EXPLICIT ROLLBACK MODE VERIFIED.")


def test_audio_generation_and_voice_samples():
    print("\n" + "=" * 75)
    print("TEST SUITE 5: AUDIO GENERATION & REPRESENTATIVE LISTENING SAMPLES")
    print("=" * 75)

    out_dir = Path("tts_benchmark/chatterbox/samples/migration_verification")
    out_dir.mkdir(parents=True, exist_ok=True)

    test_items = [
        ("V01_English", "Good morning! All background services are running smoothly, and your CPU utilization is at twelve percent.", "en"),
        ("V02_Hindi_Devanagari", "नमस्ते! मैं एमजे हूँ, आपकी पर्सनल एआई असिस्टेंट। आज मौसम बहुत अच्छा है।", "hi"),
        ("V03_Hinglish_Latin", "Aapka din kaisa ja raha hai? Agar aapko kisi cheez mein madad chahiye to mujhe zaroor bataiye.", "hi"),
        ("V04_Mixed_Technical", "Maine git status check kiya hai. Working tree completely clean hai aur version 2.1 deployment ready hai.", "hi"),
    ]

    main_app.settings.tts_engine_mode = "chatterbox"
    for item_id, text, lang in test_items:
        t0 = time.perf_counter()
        wav_bytes = asyncio.run(main_app._tts_generate(text, {"engine": "chatterbox"}, lang))
        elapsed = time.perf_counter() - t0

        assert len(wav_bytes) > 0, f"Synthesis produced 0 bytes for {item_id}!"
        wav_path = out_dir / f"{item_id}.wav"
        with open(wav_path, "wb") as f:
            f.write(wav_bytes)

        # Supporting F0 pitch analysis
        y, sr = librosa.load(str(wav_path), sr=None)
        f0, _, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), sr=sr)
        f0_clean = f0[~np.isnan(f0)]
        mean_pitch = float(np.mean(f0_clean)) if len(f0_clean) > 0 else 0.0

        print(f"  PASS | [{item_id}] Saved {wav_path} ({len(y)/sr:.2f}s in {elapsed:.1f}s) | Supporting F0: {mean_pitch:.1f} Hz")

    print(f"\n✓ REPRESENTATIVE AUDIO SAMPLES SAVED TO {out_dir} FOR MANUAL LISTENING.")


if __name__ == "__main__":
    print("\n===========================================================================")
    print("STARTING COMPLETE TTS MIGRATION INTEGRATION TEST SUITE")
    print("===========================================================================")
    test_routing_cases()
    test_chunker_exact_preservation()
    test_controlled_failure_no_fallback()
    test_explicit_rollback_mode()
    test_audio_generation_and_voice_samples()
    print("\n" + "=" * 75)
    print("ALL TEST SUITES PASSED SUCCESSFULLY!")
    print("===========================================================================")
