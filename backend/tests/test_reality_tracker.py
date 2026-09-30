"""
Unit Tests for RealityTracker Engine
"""

import time
import pytest
from engines.reality_tracker import (
    RealityTracker,
    CATEGORY_DISTRACTION,
    CATEGORY_PRODUCTIVE,
    CATEGORY_COMMUNICATION,
    CATEGORY_SYSTEM_IDLE,
)


@pytest.fixture
def tracker():
    return RealityTracker()


def test_classify_phone_packages(tracker):
    name, cat = tracker._classify_phone_package("com.instagram.android")
    assert name == "Instagram"
    assert cat == CATEGORY_DISTRACTION

    name, cat = tracker._classify_phone_package("com.google.android.youtube")
    assert name == "YouTube"
    assert cat == CATEGORY_DISTRACTION

    name, cat = tracker._classify_phone_package("org.coursera.android")
    assert name == "Coursera"
    assert cat == CATEGORY_PRODUCTIVE

    name, cat = tracker._classify_phone_package("com.whatsapp")
    assert name == "WhatsApp"
    assert cat == CATEGORY_COMMUNICATION


def test_classify_pc_windows(tracker):
    name, cat = tracker._classify_pc_window("code.exe", "test_reality_tracker.py - Alita")
    assert name == "Visual Studio Code"
    assert cat == CATEGORY_PRODUCTIVE

    name, cat = tracker._classify_pc_window("chrome.exe", "YouTube - Lo-Fi Study Beats")
    assert cat == CATEGORY_DISTRACTION

    name, cat = tracker._classify_pc_window("chrome.exe", "Coursera | Deep Learning Specialization")
    assert cat == CATEGORY_PRODUCTIVE

    name, cat = tracker._classify_pc_window("steam.exe", "Steam Store")
    assert cat == CATEGORY_DISTRACTION


def test_update_phone_state_and_snapshot(tracker):
    t0 = time.time()
    tracker.update_phone_app("com.instagram.android", is_screen_on=True)
    tracker.update_phone_screen_state(is_screen_on=True, is_locked=False)

    snapshot = tracker.get_live_reality()
    elapsed_ms = (time.time() - t0) * 1000

    assert snapshot["phone"]["package"] == "com.instagram.android"
    assert snapshot["phone"]["name"] == "Instagram"
    assert snapshot["phone"]["category"] == CATEGORY_DISTRACTION
    assert snapshot["phone"]["screen_on"] is True
    assert snapshot["phone"]["is_locked"] is False
    assert elapsed_ms < 50.0  # Must be fast
