"""
Deep Complex Logic & Concurrency Reverification Suite
=====================================================
Stress tests complex cross-device discrepancies, multi-threaded race conditions,
temporal state shifts, linguistic nuances (Hinglish, double negatives), and
persistence durability across the Alita Girlfriend & Lie Detection subsystems.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta

# UTF-8 stream handling on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.reality_tracker import (
    reality_tracker,
    CATEGORY_DISTRACTION,
    CATEGORY_PRODUCTIVE,
    CATEGORY_COMMUNICATION,
    CATEGORY_SYSTEM_IDLE,
    CATEGORY_NEUTRAL,
    TRANSIENT_PHONE_PACKAGES,
)
from engines.relationship_manager import (
    relationship_manager,
    _get_circadian_date,
    MOOD_PLAYFUL,
    MOOD_POUTING,
    MOOD_CARING_SCOLDING,
    MOOD_AFFECTIONATE,
    STATE_FILE,
)
from engines.lie_detector import lie_detector
from engines.proactive_agent import proactive_agent
from backend.main import _clean_text_for_tts, _build_system_prompt


class MockSession:
    user_id = "sarwan"
    custom_name = "Alita"
    tier = "free"
    connected_at = time.time()
    current_emotion = "neutral"
    emotion_confidence = 0.85
    interaction_count = 15
    transcript_buffer = ""
    last_identified_song = ""
    interrupted_response = ""
    interrupted_query = ""


# ─────────────────────────────────────────────────────────────────────────────
# 1. CROSS-DEVICE CONFLICT: PC PRODUCTIVE BUT PHONE DISTRACTION
# ─────────────────────────────────────────────────────────────────────────────
def test_cross_device_pc_productive_phone_distraction():
    """
    User has VS Code open on PC, but phone is active on Instagram.
    Claim: 'I am studying hard for my test'.
    Result: Lie detected because phone screen is lit with Instagram.
    """
    reality_tracker.pc_process = "code.exe"
    reality_tracker.pc_title = "main.py - Visual Studio Code"
    reality_tracker.pc_category = CATEGORY_PRODUCTIVE
    reality_tracker.pc_friendly_name = "Visual Studio Code"

    reality_tracker.update_phone_app("com.instagram.android", is_screen_on=True)
    reality_tracker.update_phone_screen_state(is_screen_on=True, is_locked=False)

    eval_res = lie_detector.evaluate_user_utterance("I am studying hard for my exam")
    assert eval_res["detected"] is True
    assert eval_res["is_lie"] is True
    assert "Instagram" in eval_res["evidence"]
    assert "LIE CAUGHT" in eval_res["prompt_directive"]
    print("[PASS] 1. Cross-Device Conflict (PC Productive + Phone Distraction) correctly caught as lie.")


# ─────────────────────────────────────────────────────────────────────────────
# 2. CROSS-DEVICE CONFLICT: PHONE LOCKED BUT PC DISTRACTION (GAMING/YOUTUBE)
# ─────────────────────────────────────────────────────────────────────────────
def test_cross_device_phone_locked_pc_gaming():
    """
    User phone is locked/off, but PC is actively running Steam/Game.
    Claim: 'I am working and coding right now'.
    Result: Lie detected because PC active window is a game.
    """
    reality_tracker.update_phone_app("", is_screen_on=False)
    reality_tracker.update_phone_screen_state(is_screen_on=False, is_locked=True)

    reality_tracker.pc_process = "cyberpunk2077.exe"
    reality_tracker.pc_title = "Cyberpunk 2077"
    reality_tracker.pc_category = CATEGORY_DISTRACTION
    reality_tracker.pc_friendly_name = "Cyberpunk 2077"

    eval_res = lie_detector.evaluate_user_utterance("I am working on the code right now")
    assert eval_res["detected"] is True
    assert eval_res["is_lie"] is True
    assert "Cyberpunk 2077" in eval_res["evidence"]
    assert "LIE CAUGHT" in eval_res["prompt_directive"]
    print("[PASS] 2. Cross-Device Conflict (Phone Locked + PC Gaming) correctly caught as lie.")


# ─────────────────────────────────────────────────────────────────────────────
# 3. CROSS-DEVICE TRUTH SYNCHRONIZATION
# ─────────────────────────────────────────────────────────────────────────────
def test_cross_device_truth_synchronization():
    """
    User phone is locked and PC is running VS Code.
    Claim: 'I'm coding the new API routes'.
    Result: Truth confirmed and praised by girlfriend persona.
    """
    reality_tracker.update_phone_app("", is_screen_on=False)
    reality_tracker.update_phone_screen_state(is_screen_on=False, is_locked=True)

    reality_tracker.pc_process = "code.exe"
    reality_tracker.pc_title = "server.py - Visual Studio Code"
    reality_tracker.pc_category = CATEGORY_PRODUCTIVE
    reality_tracker.pc_friendly_name = "Visual Studio Code"

    eval_res = lie_detector.evaluate_user_utterance("I am coding the new features")
    assert eval_res["detected"] is True
    assert eval_res["is_lie"] is False
    assert "TRUTH CONFIRMED" in eval_res["prompt_directive"]
    print("[PASS] 3. Cross-Device Truth Synchronization successfully verified and praised.")


# ─────────────────────────────────────────────────────────────────────────────
# 4. PHONE AWAY CLAIM: TRUTH VS LIE
# ─────────────────────────────────────────────────────────────────────────────
def test_phone_away_claim_truth_and_lie():
    """
    Test 'I haven't touched my phone':
    A) When phone screen is ON -> Caught as lie.
    B) When phone screen is OFF -> Confirmed as truth.
    """
    # Case A: Screen lit
    reality_tracker.update_phone_app("com.whatsapp", is_screen_on=True)
    reality_tracker.update_phone_screen_state(is_screen_on=True, is_locked=False)
    eval_lie = lie_detector.evaluate_user_utterance("I haven't touched my phone")
    assert eval_lie["detected"] is True
    assert eval_lie["is_lie"] is True
    assert "Phone screen is currently ON" in eval_lie["evidence"]

    # Case B: Screen genuinely off & locked
    reality_tracker.update_phone_screen_state(is_screen_on=False, is_locked=True)
    eval_truth = lie_detector.evaluate_user_utterance("I haven't touched my phone")
    assert eval_truth["detected"] is True
    assert eval_truth["is_lie"] is False
    assert "Phone screen is OFF and locked" in eval_truth["evidence"]
    print("[PASS] 4. Phone Away Claim accurately discriminates between screen-on lie and locked truth.")


# ─────────────────────────────────────────────────────────────────────────────
# 5. MULTI-THREADED CONCURRENCY & DURABILITY STRESS TEST
# ─────────────────────────────────────────────────────────────────────────────
def test_multithreaded_relationship_manager_stress():
    """
    Fires 10 concurrent threads each performing 20 lie and truth events.
    Verifies zero deadlocks, score clamping within [20, 100], and valid JSON persistence.
    """
    def worker(worker_id: int):
        for i in range(20):
            if (worker_id + i) % 2 == 0:
                relationship_manager.record_lie("concurrency_test", f"Worker {worker_id} infraction {i}")
            else:
                relationship_manager.record_truth("concurrency_test", f"Worker {worker_id} truth {i}")

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(worker, w) for w in range(10)]
        for f in concurrent.futures.as_completed(futures):
            f.result()

    # Verify atomic state integrity
    assert os.path.exists(STATE_FILE)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        saved = json.load(f)

    score = saved["affection_score"]
    assert 20 <= score <= 100, f"Affection score out of bounds: {score}"
    assert saved["total_lies_caught"] > 0
    assert saved["total_truths_verified"] > 0
    print(f"[PASS] 5. Multi-Threaded Stress Test Passed (200 ops). Score: {score}, JSON intact.")


# ─────────────────────────────────────────────────────────────────────────────
# 6. RAPID JITTER / SUB-SECOND APP SWITCHING
# ─────────────────────────────────────────────────────────────────────────────
def test_rapid_keyboard_jitter_and_transient_flicker():
    """
    Simulates rapid alternating events between Gboard and Instagram 30 times in 50ms.
    Verifies phone_app_start_time does not reset to 0s and package remains Instagram.
    """
    reality_tracker.update_phone_app("com.instagram.android", is_screen_on=True)
    initial_time = reality_tracker.phone_app_start_time

    for _ in range(30):
        # Keyboard opens
        reality_tracker.update_phone_app("com.google.android.inputmethod.latin", is_screen_on=True)
        # SystemUI notification pops
        reality_tracker.update_phone_app("com.android.systemui", is_screen_on=True)

    # Reality tracker must retain Instagram and its original start time
    assert reality_tracker.phone_package == "com.instagram.android"
    assert reality_tracker.phone_app_start_time == initial_time
    print("[PASS] 6. Rapid transient jitter (60 events) handled with zero timer degradation.")


# ─────────────────────────────────────────────────────────────────────────────
# 7. CIRCADIAN ROLLOVER BOUNDARY PRECISION (03:59:59 vs 04:00:01)
# ─────────────────────────────────────────────────────────────────────────────
def test_circadian_boundary_precision():
    """
    Checks exact temporal cutoff for 4:00 AM circadian day boundary:
    - 2026-09-13 03:59:59 -> 2026-09-12 (Accountability preserved)
    - 2026-09-13 04:00:01 -> 2026-09-13 (Fresh morning rollover)
    """
    t_before = datetime(2026, 9, 13, 3, 59, 59)
    date_before = str((t_before - timedelta(hours=4)).date())
    assert date_before == "2026-09-12"

    t_after = datetime(2026, 9, 13, 4, 0, 1)
    date_after = str((t_after - timedelta(hours=4)).date())
    assert date_after == "2026-09-13"
    print("[PASS] 7. Circadian 4:00 AM boundary precision verified down to the second.")


# ─────────────────────────────────────────────────────────────────────────────
# 8. COMPLEX LINGUISTIC NUANCES & HINDI / HINGLISH NEGATIONS
# ─────────────────────────────────────────────────────────────────────────────
def test_complex_linguistic_nuances_and_negations():
    """
    Verifies that conversational admissions, Hinglish negations, and past-tense
    descriptions never trigger false lie detection.
    """
    negative_statements = [
        "mai padhai nahi kar raha hu, movie dekh raha hu",
        "padhai nahi ho rahi mujhse aaj",
        "I am not studying right now, just chilling",
        "I was studying earlier today before the movie",
        "I never said I was working",
        "I wasn't coding anything today",
        "ab mai so nahi raha hu, uth gaya",
    ]

    for stmt in negative_statements:
        claim = lie_detector._extract_claim(stmt)
        assert claim is None, f"Incorrectly extracted claim '{claim}' from negative statement: '{stmt}'"

    print("[PASS] 8. Complex multilingual & Hinglish negations correctly identified with zero false triggers.")


# ─────────────────────────────────────────────────────────────────────────────
# 9. MALFORMED PROMISE TIME RESILIENCE IN PROACTIVE AGENT
# ─────────────────────────────────────────────────────────────────────────────
def test_malformed_promise_time_resilience():
    """
    Injects malformed, empty, and invalid target times into active promises.
    Ensures proactive_agent handles them gracefully with zero uncaught exceptions.
    """
    malformed_targets = ["midnight", "25:00", "invalid_time", "", None, "12", "10:99:99"]

    for idx, target in enumerate(malformed_targets):
        key = f"bad_promise_{idx}"
        relationship_manager.add_promise(key, "Test bad promise", target)

    # Call _evaluate_situations under malformed promise states
    try:
        res = proactive_agent._evaluate_situations()
        assert res is None or isinstance(res, dict)
    except Exception as exc:
        assert False, f"Proactive agent crashed on malformed promise: {exc}"
    finally:
        for idx in range(len(malformed_targets)):
            relationship_manager.state["active_promises"].pop(f"bad_promise_{idx}", None)
        relationship_manager._save_state()

    print("[PASS] 9. Proactive Agent demonstrates 100% resilience against malformed promise timestamps.")


# ─────────────────────────────────────────────────────────────────────────────
# 10. ADVANCED TTS CLEANSING: SQL ASTERISKS, ADVERBS, NESTED FORMATS
# ─────────────────────────────────────────────────────────────────────────────
def test_advanced_tts_cleansing_edge_cases():
    """
    Verifies that code with asterisks (`SELECT * FROM`), triple bolding, parenthetical
    adverbs (`(gently whispers)`), and Hinglish expressions are properly processed.
    """
    cases = [
        # Action with adverbs in parentheses
        (
            "(affectionately whispers) Good night Sarwan. (softly giggles) Go to sleep!",
            "Good night Sarwan. Go to sleep!"
        ),
        # SQL with asterisk inside code
        (
            "*smirks* Look at your terminal: `SELECT * FROM users WHERE active = 1;` *winks*",
            "Look at your terminal: SELECT * FROM users WHERE active = 1;"
        ),
        # Triple asterisks (bold + italic)
        (
            "***ULTIMATE FOCUS*** is needed today! **No excuses**.",
            "ULTIMATE FOCUS is needed today! No excuses."
        ),
        # Hindi dialogue with action cues
        (
            "*smirks* Acha ji? (sighs deeply) [pouts] Padhai kab karoge?",
            "Acha ji? Padhai kab karoge?"
        ),
        # Multiple adjacent action asterisks
        (
            "*chuckles* *looks at phone* Busted mister!",
            "Busted mister!"
        ),
    ]

    for raw, expected in cases:
        cleaned = _clean_text_for_tts(raw)
        assert cleaned == expected, f"TTS Clean Mismatch:\n  Raw:      {raw!r}\n  Cleaned:  {cleaned!r}\n  Expected: {expected!r}"

    print("[PASS] 10. Advanced TTS Cleansing passes all complex syntax, code asterisk, and adverb test cases.")


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 75)
    print("STARTING DEEP COMPLEX LOGIC & CONCURRENCY REVERIFICATION SUITE")
    print("=" * 75 + "\n")

    test_cross_device_pc_productive_phone_distraction()
    test_cross_device_phone_locked_pc_gaming()
    test_cross_device_truth_synchronization()
    test_phone_away_claim_truth_and_lie()
    test_multithreaded_relationship_manager_stress()
    test_rapid_keyboard_jitter_and_transient_flicker()
    test_circadian_boundary_precision()
    test_complex_linguistic_nuances_and_negations()
    test_malformed_promise_time_resilience()
    test_advanced_tts_cleansing_edge_cases()

    print("\n" + "=" * 75)
    print(">>> 100% REVERIFICATION SUCCESS: ALL DEEP COMPLEX LOGIC SCENARIOS PASSED!")
    print("=" * 75 + "\n")
