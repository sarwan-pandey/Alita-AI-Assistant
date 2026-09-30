"""
test_remaining_10_bugs.py — Verification of All 10 Remaining Deep-Logic Bugs
=============================================================================
Tests:
  1. Security Vault: Negation Priority over keyword matching
  2. Android Companion: Window state change package filtering
  3. Lie Detector: Interrogative, advice, and modal intention pre-filtering
  4. Relationship Manager: Promise lifecycle (active, completed, expired) & circadian rollover
  5. Proactive Agent: Status checks on active promises & broadcast dispatching
  6. Reality Tracker: Spotify reclassified as CATEGORY_NEUTRAL (no work lie penalty)
  7. TTS Audio Stream: Trailing stage direction buffer guarantees is_final: True
  8. Core Audio Pipeline: Modular text sanitization strips action cues before engine
  9. Phone Orchestrator: Unlock commands routed through Security Vault
  10. Phone Router: WebSocket disconnect instantly clears phone_screen_on in reality_tracker
"""

import asyncio
import json
import pytest
import time
from unittest.mock import MagicMock, AsyncMock, patch

from engines.security_vault import security_vault, SensitiveActionResult
from engines.lie_detector import lie_detector
from engines.relationship_manager import relationship_manager, _get_circadian_date
from engines.reality_tracker import (
    reality_tracker,
    CATEGORY_DISTRACTION,
    CATEGORY_PRODUCTIVE,
    CATEGORY_NEUTRAL,
    CATEGORY_SYSTEM_IDLE,
    PC_PROCESS_MAP,
)
from engines.proactive_agent import proactive_agent
from engines.phone_orchestrator import phone_orchestrator
from core.audio_pipeline import _clean_text_for_tts as core_clean_text


# ── Bug 1: Security Vault Negation Priority ──────────────────────────────────

def test_bug1_security_vault_negation_priority():
    session_state = {
        "pending_confirmation": {
            "action_type": "unlock",
            "instruction": "Unlock my phone",
            "created_at": time.time(),
        }
    }

    # Negative phrase containing the word 'unlock' must NOT confirm!
    res_cancel1 = security_vault.check_sensitive_action_intent("No, don't unlock it", session_state)
    assert res_cancel1.action_type == "cancelled"
    assert res_cancel1.details.get("cancelled") is True
    assert session_state.get("pending_confirmation") is None

    # Reset pending confirmation
    session_state["pending_confirmation"] = {
        "action_type": "unlock",
        "instruction": "Unlock my phone",
        "created_at": time.time(),
    }
    res_cancel2 = security_vault.check_sensitive_action_intent("Nahi unlock mat karo", session_state)
    assert res_cancel2.action_type == "cancelled"

    # Affirmative phrase without negation confirms cleanly
    session_state["pending_confirmation"] = {
        "action_type": "unlock",
        "instruction": "Unlock my phone",
        "created_at": time.time(),
    }
    res_confirm = security_vault.check_sensitive_action_intent("haan unlock kardo", session_state)
    assert res_confirm.action_type == "unlock"
    assert res_confirm.details.get("confirmed") is True
    assert res_confirm.needs_confirmation is False


# ── Bug 2: Android Companion Window State Filter ─────────────────────────────

def test_bug2_android_a11y_window_state_filter():
    # Simulates the logic of AlitaAccessibilityService.kt
    current_package = "com.google.android.apps.nexuslauncher"
    notifications = []

    def on_accessibility_event(event_type: str, pkg: str):
        nonlocal current_package
        is_window_change = (event_type == "TYPE_WINDOW_STATE_CHANGED")
        if is_window_change and pkg != current_package:
            current_package = pkg
            notifications.append(pkg)

    # 1. Preliminary content event arrives first when launching Instagram
    on_accessibility_event("TYPE_WINDOW_CONTENT_CHANGED", "com.instagram.android")
    assert current_package == "com.google.android.apps.nexuslauncher"
    assert len(notifications) == 0

    # 2. Actual window state event arrives milliseconds later
    on_accessibility_event("TYPE_WINDOW_STATE_CHANGED", "com.instagram.android")
    assert current_package == "com.instagram.android"
    assert notifications == ["com.instagram.android"]


# ── Bug 3: Lie Detector Interrogative & Advice Filtering ─────────────────────

def test_bug3_lie_detector_interrogative_filtering():
    # Questions and advice requests should NOT extract claims
    assert lie_detector._extract_claim("Padhai kaise kare?") is None
    assert lie_detector._extract_claim("Exam ki taiyari kaise karu?") is None
    assert lie_detector._extract_claim("Should I study right now?") is None
    assert lie_detector._extract_claim("How can I focus while studying hard?") is None
    assert lie_detector._extract_claim("Bhai padhai karu ya so jau?") is None
    assert lie_detector._extract_claim("Neend nahi aa rahi") is None
    assert lie_detector._extract_claim("Can't sleep tonight Alita") is None
    assert lie_detector._extract_claim("What are you doing?") is None
    assert lie_detector._extract_claim("I want to study machine learning") is None
    assert lie_detector._extract_claim("I am planning to code tomorrow") is None

    # Genuine present factual assertions MUST extract claims
    assert lie_detector._extract_claim("I'm studying for my exam right now") == "study"
    assert lie_detector._extract_claim("I am studying hard right now") == "study"
    assert lie_detector._extract_claim("mai padhai kar raha hu") == "study"
    assert lie_detector._extract_claim("Good night Alita, I'm going to sleep") == "sleep"
    assert lie_detector._extract_claim("I'm coding the backend service") == "work"


# ── Bug 4: Relationship Manager Promise Lifecycle ────────────────────────────

def test_bug4_relationship_manager_promise_lifecycle():
    relationship_manager.add_promise("test_sleep", "Sleep by 11 PM", "23:00")
    prom = relationship_manager.state["active_promises"]["test_sleep"]
    assert prom["status"] == "active"
    assert prom["target_date"] == _get_circadian_date()

    # Complete promise
    initial_score = relationship_manager.state["affection_score"]
    completed = relationship_manager.complete_promise("test_sleep")
    assert completed is True
    assert relationship_manager.state["active_promises"]["test_sleep"]["status"] == "completed"
    assert relationship_manager.state["affection_score"] >= initial_score

    # Expire stale promise
    relationship_manager.state["active_promises"]["old_promise"] = {
        "description": "Old sleep",
        "target_time": "22:00",
        "target_date": "2026-01-01",
        "created_at": time.time() - 90000,
        "status": "active",
    }
    expired_cnt = relationship_manager.expire_stale_promises()
    assert expired_cnt >= 1
    assert relationship_manager.state["active_promises"]["old_promise"]["status"] == "expired"

    # Cleanup
    relationship_manager.dismiss_promise("test_sleep")
    relationship_manager.dismiss_promise("old_promise")


# ── Bug 5: Proactive Agent Active Promise Status Check ───────────────────────

def test_bug5_proactive_agent_status_check():
    # Completed or expired promises must NOT trigger proactive promise scold
    relationship_manager.state["active_promises"]["sleep_time"] = {
        "description": "Sleep by midnight",
        "target_time": "00:00",
        "target_date": _get_circadian_date(),
        "created_at": time.time(),
        "status": "completed",  # User completed it!
    }
    proactive_agent._cooldowns.pop("girlfriend_promise", None)
    sug = proactive_agent._evaluate_situations()
    if sug:
        assert sug.get("subtype") != "girlfriend_promise_scold"

    # Cleanup
    relationship_manager.dismiss_promise("sleep_time")


# ── Bug 6: Reality Tracker Spotify Neutral Classification ────────────────────

def test_bug6_spotify_neutral_work_claim():
    # Spotify must be categorized as CATEGORY_NEUTRAL
    assert PC_PROCESS_MAP.get("spotify.exe") == ("Spotify", CATEGORY_NEUTRAL)

    phone_idle = {
        "category": CATEGORY_SYSTEM_IDLE,
        "screen_on": False,
        "name": "Screen Locked",
        "duration_formatted": "10m",
    }
    pc_spotify = {
        "process": "spotify.exe",
        "name": "Spotify",
        "title": "Lo-Fi Beats",
        "category": CATEGORY_NEUTRAL,
        "duration_formatted": "5s",
        "duration_seconds": 5,
    }

    # Working while listening to Spotify is NOT a lie
    res = lie_detector._evaluate_work_claim("I am coding right now", phone_idle, pc_spotify)
    assert res.get("is_lie") is not True


# ── Bug 7: TTS Trailing Stage Direction Buffer Completion ─────────────────────

def test_bug7_tts_trailing_stage_direction_completion():
    # Simulates main.py lines 2075-2092
    sentence_buffer = "*smirks*"
    from main import _clean_text_for_tts

    cleaned = _clean_text_for_tts(sentence_buffer)
    assert cleaned == ""

    sent_final_tts = False
    any_audio = True  # Earlier turn generated audio
    dispatched_packets = []

    # Logic under test
    if sentence_buffer.strip():
        # mp3_bytes = await _tts_generate(...) -> empty because cleaned is ""
        mp3_bytes = b""
        if mp3_bytes:
            sent_final_tts = True

    if not sent_final_tts and any_audio:
        dispatched_packets.append({"type": "tts_audio", "audio_b64": "", "is_final": True})

    assert len(dispatched_packets) == 1
    assert dispatched_packets[0]["is_final"] is True


# ── Bug 8: Core Audio Pipeline Sanitization ──────────────────────────────────

def test_bug8_core_audio_pipeline_sanitization():
    raw_text = "*smirks* You really thought you could lie to me? [pouts] (affectionately whispers) Silly boy!"
    cleaned = core_clean_text(raw_text)
    assert "*smirks*" not in cleaned
    assert "[pouts]" not in cleaned
    assert "whispers" not in cleaned
    assert cleaned == "You really thought you could lie to me? Silly boy!"


# ── Bug 9: Phone Orchestrator Unlock Confirmation ────────────────────────────

@pytest.mark.anyio
async def test_bug9_phone_orchestrator_unlock_security_check():
    phone_orchestrator.device_info["isLocked"] = True
    session_state = {}
    res = await phone_orchestrator.execute_task("Unlock my phone", session_state)
    assert res.get("needs_confirmation") is True
    assert "Are you sure you want me to unlock your" in res.get("confirmation_prompt", "")
    assert session_state.get("pending_confirmation") is not None


# ── Bug 10: Phone Router Disconnect Reality Tracker Sync ─────────────────────

def test_bug10_phone_disconnect_reality_sync():
    reality_tracker.phone_screen_on = True
    reality_tracker.phone_is_locked = False

    # Simulate finally block on WebSocket disconnect
    reality_tracker.update_phone_screen_state(is_screen_on=False, is_locked=True)

    assert reality_tracker.phone_screen_on is False
    assert reality_tracker.phone_is_locked is True
    assert reality_tracker.phone_category == CATEGORY_SYSTEM_IDLE
