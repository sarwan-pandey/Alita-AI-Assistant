"""
Unit Tests for LieDetector Engine
"""

import time
import pytest
from engines.reality_tracker import reality_tracker, CATEGORY_DISTRACTION, CATEGORY_PRODUCTIVE
from engines.lie_detector import lie_detector


def test_claim_extraction():
    assert lie_detector._extract_claim("I'm studying for my exam right now") == "study"
    assert lie_detector._extract_claim("mai padhai kar raha hu") == "study"
    assert lie_detector._extract_claim("I am going to sleep good night Alita") == "sleep"
    assert lie_detector._extract_claim("mai so raha hu") == "sleep"
    assert lie_detector._extract_claim("I'm coding the new feature") == "work"
    assert lie_detector._extract_claim("I haven't touched my phone") == "phone_away"
    assert lie_detector._extract_claim("just a quick break for 2 min") == "quick_break"
    assert lie_detector._extract_claim("what is the weather in Delhi") is None


def test_study_claim_caught_lie():
    # Setup phone state: Instagram open and screen on
    reality_tracker.update_phone_app("com.instagram.android", is_screen_on=True)
    reality_tracker.update_phone_screen_state(is_screen_on=True, is_locked=False)

    res = lie_detector.evaluate_user_utterance("I'm studying for my exams right now")
    assert res["detected"] is True
    assert res["is_lie"] is True
    assert "Instagram" in res["evidence"]
    assert "prompt_directive" in res
    assert "GIRLFRIEND REACTION DIRECTIVE" in res["prompt_directive"]


def test_study_claim_verified_truth():
    # Setup phone state: locked and off, PC: VS Code
    reality_tracker.update_phone_app("", is_screen_on=False)
    reality_tracker.update_phone_screen_state(is_screen_on=False, is_locked=True)
    reality_tracker.pc_category = CATEGORY_PRODUCTIVE
    reality_tracker.pc_friendly_name = "Visual Studio Code"

    res = lie_detector.evaluate_user_utterance("I'm studying hard right now")
    assert res["detected"] is True
    assert res["is_lie"] is False
    assert "prompt_directive" in res
    assert "TRUTH CONFIRMED" in res["prompt_directive"]


def test_sleep_claim_caught_lie():
    # Setup phone state: screen is on with YouTube active for 5 minutes (> 240s threshold)
    reality_tracker.update_phone_screen_state(is_screen_on=True, is_locked=False)
    reality_tracker.update_phone_app("com.google.android.youtube", is_screen_on=True)
    reality_tracker.phone_app_start_time = time.time() - 300

    res = lie_detector.evaluate_user_utterance("Good night Alita, I'm going to sleep")
    assert res["detected"] is True
    assert res["is_lie"] is True
    assert "YouTube" in res["evidence"]
