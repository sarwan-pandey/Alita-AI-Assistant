"""
test_interruption_handler.py — Test Interruption and Dialog Detection/Recovery
Comprehensive suite including tricky edge cases, false-positive resistance,
malformed trees, ANRs, and ColorOS/Realme OEM popups.
"""

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from engines.interruption_handler import interruption_handler


def test_known_popup_auto_dismissal():
    """Test 5: Known permission/autostart popup is recognized and auto-dismissable."""
    permission_tree = {
        "package": "com.google.android.permissioncontroller",
        "nodes": [
            {"text": "Allow Alita to access your location?", "isClickable": False},
            {"text": "While using the app", "isClickable": True},
            {"text": "Only this time", "isClickable": True},
            {"text": "Don't allow", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(permission_tree)
    assert res.is_interrupted is True
    assert res.interruption_type == "known_popup"
    assert res.auto_resolvable is True
    assert res.target_button == "While using the app"

    # Test resolution execution
    clicked_button = None

    async def mock_click(btn):
        nonlocal clicked_button
        clicked_button = btn
        return {"success": True}

    resolved = asyncio.run(interruption_handler.resolve_known_popup(res, mock_click))
    assert resolved is True
    assert clicked_button == "While using the app"
    print("✅ Test 5 Passed: Known permission popup detected and auto-dismissed")


def test_unrecognized_dialog_surfaced_without_guessing():
    """Test 6: Unrecognized dialog pauses task and surfaces unhandled_popup."""
    unknown_dialog_tree = {
        "package": "com.unknown.security.prompter",
        "nodes": [
            {"text": "Suspicious Activity Warning", "isClickable": False},
            {"text": "Block Account", "isClickable": True},
            {"text": "Cancel", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(unknown_dialog_tree)
    assert res.is_interrupted is True
    assert res.interruption_type == "unhandled_popup"
    assert res.auto_resolvable is False
    assert "Ask user how to proceed" in res.suggested_action
    print("✅ Test 6 Passed: Unrecognized dialog successfully paused without guessing")


def test_tricky_coloros_realme_oem_popup():
    """Tricky 1: Realme / ColorOS autostart dialog with extra whitespace and uppercase."""
    coloros_tree = {
        "package": "com.coloros.safecenter",
        "nodes": [
            {"text": "Allow Alita to auto-launch in background for continuous assistance?", "isClickable": False},
            {"text": "  TURN ON  ", "isClickable": True},
            {"text": "Cancel", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(coloros_tree)
    assert res.is_interrupted is True
    assert res.interruption_type == "known_popup"
    assert res.auto_resolvable is True
    assert res.target_button.strip().lower() == "turn on"

    # Test with synchronous click callback (ensure no coroutine crash)
    clicked = None

    def sync_click(btn):
        nonlocal clicked
        clicked = btn
        return True

    resolved = asyncio.run(interruption_handler.resolve_known_popup(res, sync_click))
    assert resolved is True
    assert clicked.strip().lower() == "turn on"
    print("✅ Tricky Test 1 Passed: Realme/ColorOS OEM prompt handled with whitespace resilience & sync callback")


def test_tricky_false_positive_prevention_on_normal_chat():
    """Tricky 2: Normal WhatsApp chat screen containing 'allow' and 'cancel' text must NOT be flagged as popup."""
    # Screen with 20 nodes simulating active chat
    chat_tree = {
        "package": "com.whatsapp",
        "nodes": [
            {"text": "WhatsApp", "isClickable": False},
            {"text": "Sarah", "isClickable": True},
            {"text": "Did your manager allow your vacation?", "isClickable": False},
            {"text": "Yes, but I might cancel if it rains", "isClickable": False},
            {"text": "Type a message", "isClickable": True},
            {"text": "Voice message", "isClickable": True},
            {"text": "Attach", "isClickable": True},
            {"text": "Camera", "isClickable": True},
            {"text": "Back", "isClickable": True},
            {"text": "More options", "isClickable": True},
            {"text": "Online", "isClickable": False},
            {"text": "Today", "isClickable": False},
            {"text": "10:30 AM", "isClickable": False},
            {"text": "10:31 AM", "isClickable": False},
            {"text": "Delivered", "isClickable": False},
            {"text": "Read", "isClickable": False},
            {"text": "Call", "isClickable": True},
            {"text": "Video Call", "isClickable": True},
            {"text": "Profile photo", "isClickable": True},
            {"text": "Search in chat", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(chat_tree)
    assert res.is_interrupted is False
    assert res.interruption_type == "none"
    print("✅ Tricky Test 2 Passed: Normal chat screen with conversational keywords immune to false positives")


def test_tricky_system_anr_crash_dialog():
    """Tricky 3: System ANR (App Not Responding) crash alert is properly identified and non-resolvable."""
    anr_tree = {
        "package": "android",
        "nodes": [
            {"text": "System UI isn't responding", "isClickable": False},
            {"text": "Do you want to close it?", "isClickable": False},
            {"text": "Close app", "isClickable": True},
            {"text": "Wait", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(anr_tree)
    assert res.is_interrupted is True
    assert res.interruption_type == "crash_anr"
    assert res.auto_resolvable is False
    assert "Close app or wait" in res.suggested_action
    print("✅ Tricky Test 3 Passed: System ANR crash alert detected and paused safely")


def test_tricky_article_reading_crash_text_not_anr():
    """Tricky 4: Long tech article containing crash words (e.g. 'keeps stopping') must NOT trigger ANR."""
    article_nodes = [{"text": f"Paragraph {i}: The reason old apps keeps stopping is memory fragmentation.", "isClickable": False} for i in range(20)]
    article_tree = {
        "package": "com.android.chrome",
        "nodes": article_nodes
    }

    res = interruption_handler.detect_interruption(article_tree)
    assert res.is_interrupted is False
    assert res.interruption_type == "none"
    print("✅ Tricky Test 4 Passed: Web article discussing app crashes not falsely flagged as ANR")


def test_tricky_content_description_only_button():
    """Tricky 5: Icon button with empty text and target in contentDescription is recognized."""
    desc_tree = {
        "package": "com.google.android.permissioncontroller",
        "nodes": [
            {"text": "Allow Alita to take photos?", "contentDesc": "", "isClickable": False},
            {"text": "", "contentDesc": "While using the app", "isClickable": True},
            {"text": "Don't allow", "contentDesc": "", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(desc_tree)
    assert res.is_interrupted is True
    assert res.interruption_type == "known_popup"
    assert res.auto_resolvable is True
    assert res.target_button == "While using the app"
    print("✅ Tricky Test 5 Passed: Accessible button using contentDescription matched cleanly")


def test_tricky_disabled_button_fallback():
    """Tricky 6: Non-clickable preferred button skipped in favor of clickable secondary option."""
    mixed_tree = {
        "package": "com.google.android.permissioncontroller",
        "nodes": [
            {"text": "Allow Alita to access contacts?", "isClickable": False},
            # "While using the app" is disabled/non-clickable
            {"text": "While using the app", "isClickable": False},
            # "Only this time" is clickable
            {"text": "Only this time", "isClickable": True},
            {"text": "Don't allow", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(mixed_tree)
    assert res.is_interrupted is True
    assert res.interruption_type == "known_popup"
    assert res.auto_resolvable is True
    # Should select "Only this time" because "While using the app" is non-clickable
    assert res.target_button == "Only this time"
    print("✅ Tricky Test 6 Passed: Non-clickable preferred button skipped for clickable fallback")


def test_tricky_malformed_and_dirty_tree_resilience():
    """Tricky 7: Malformed, dirty, None, or empty trees do not crash the engine."""
    assert interruption_handler.detect_interruption(None).is_interrupted is False
    assert interruption_handler.detect_interruption({}).is_interrupted is False
    assert interruption_handler.detect_interruption({"package": None, "nodes": None}).is_interrupted is False
    assert interruption_handler.detect_interruption({
        "package": "com.something",
        "nodes": [None, "invalid_str", 123, {"text": None, "contentDesc": None, "isClickable": None}]
    }).is_interrupted is False
    print("✅ Tricky Test 7 Passed: Engine completely crash-proof against malformed & dirty view-trees")


def test_tricky_play_protect_blocked_dialog():
    """Tricky 8: Google Play Protect sideload warning detected with 'Install anyway' option."""
    play_protect_tree = {
        "package": "com.android.vending",
        "nodes": [
            {"text": "Blocked by Play Protect: Harmful app detected", "isClickable": False},
            {"text": "More details", "isClickable": True},
            {"text": "Install anyway", "isClickable": True},
            {"text": "OK", "isClickable": True},
        ]
    }

    res = interruption_handler.detect_interruption(play_protect_tree)
    assert res.is_interrupted is True
    assert res.interruption_type == "known_popup"
    assert res.auto_resolvable is True
    assert res.target_button == "Install anyway"
    print("✅ Tricky Test 8 Passed: Play Protect warning detected with bypass target")


if __name__ == "__main__":
    test_known_popup_auto_dismissal()
    test_unrecognized_dialog_surfaced_without_guessing()
    test_tricky_coloros_realme_oem_popup()
    test_tricky_false_positive_prevention_on_normal_chat()
    test_tricky_system_anr_crash_dialog()
    test_tricky_article_reading_crash_text_not_anr()
    test_tricky_content_description_only_button()
    test_tricky_disabled_button_fallback()
    test_tricky_malformed_and_dirty_tree_resilience()
    test_tricky_play_protect_blocked_dialog()
    print("\n🎉 ALL 10 TRICKY INTERRUPTION HANDLER TESTS PASSED PERFECTLY!")
