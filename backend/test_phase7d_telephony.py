"""
backend/test_phase7d_telephony.py — Phase 7D Telephony Awareness Unit & Integration Suite
"""

import os
import sys

# Force CPU mode for test runner to preserve active server's CUDA VRAM
os.environ["CUDA_VISIBLE_DEVICES"] = "-1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# Mock tts_dispatch in sys.modules only if not already importable, avoiding test pollution
try:
    import tts_dispatch
except ImportError:
    mock_tts_mod = MagicMock()
    mock_tts_mod._tts_generate = AsyncMock(return_value=b"fake_tts_wav")
    mock_tts_mod.get_or_load_multilingual_engine = lambda: None
    mock_tts_mod.get_or_load_turbo_engine = lambda: None
    sys.modules["tts_dispatch"] = mock_tts_mod

import asyncio
from engines.notification_dispatcher import NotificationDispatcher
from threads.automation_handler import _fast_parse_automation_command, _normalize_automation_action


class TestPhase7DTelephony(unittest.TestCase):
    """Test suite for telephony awareness dispatch, routing, and formatting."""

    def test_intent_matching_call_actions(self):
        # 1. Answer call variations
        for phrase in ["answer", "answer call", "answer the call", "accept the call", "pick up call"]:
            fast = _fast_parse_automation_command(phrase)
            self.assertIsNotNone(fast, f"Fast parse returned None for '{phrase}'")
            self.assertEqual(fast["action"], "phone_answer_call", f"Fast parse failed for '{phrase}'")
            norm = _normalize_automation_action({"action": "phone_answer_call"}, phrase)
            self.assertEqual(norm["action"], "phone_answer_call", f"Failed for '{phrase}'")

        # 2. Reject call variations
        for phrase in ["reject call", "reject the call", "decline call"]:
            fast = _fast_parse_automation_command(phrase)
            self.assertIsNotNone(fast, f"Fast parse returned None for '{phrase}'")
            self.assertEqual(fast["action"], "phone_reject_call", f"Fast parse failed for '{phrase}'")
            norm = _normalize_automation_action({"action": "phone_reject_call"}, phrase)
            self.assertEqual(norm["action"], "phone_reject_call", f"Failed for '{phrase}'")

        # 3. End call variations
        for phrase in ["end call", "hang up", "cut the call", "cut call"]:
            fast = _fast_parse_automation_command(phrase)
            self.assertIsNotNone(fast, f"Fast parse returned None for '{phrase}'")
            self.assertEqual(fast["action"], "phone_end_call", f"Fast parse failed for '{phrase}'")
            norm = _normalize_automation_action({"action": "phone_end_call"}, phrase)
            self.assertEqual(norm["action"], "phone_end_call", f"Failed for '{phrase}'")

        # 4. Outbound call / dial variations via fast-parse and normalizer
        fast_rahul = _fast_parse_automation_command("Call Rahul")
        self.assertIsNotNone(fast_rahul)
        self.assertEqual(fast_rahul["action"], "phone_make_call")
        self.assertEqual(fast_rahul.get("contactName"), "Rahul")

        norm_rahul = _normalize_automation_action({"action": "open_app"}, "Call Rahul")
        self.assertEqual(norm_rahul["action"], "phone_make_call")
        self.assertEqual(norm_rahul.get("contactName"), "Rahul")

        norm_mom = _normalize_automation_action({"action": "open_app"}, "Dial Mom")
        self.assertEqual(norm_mom["action"], "phone_make_call")
        self.assertEqual(norm_mom.get("contactName"), "Mom")

        norm_num = _normalize_automation_action({"action": "open_app"}, "Call +919876543210")
        self.assertEqual(norm_num["action"], "phone_make_call")
        self.assertEqual(norm_num.get("number"), "+919876543210")

    def test_incoming_call_dispatch_and_announcement(self):
        dispatcher = NotificationDispatcher()

        mock_desktop = AsyncMock()
        mock_audio = AsyncMock()
        dispatcher.set_desktop_broadcaster(mock_desktop)
        dispatcher.set_audio_broadcaster(mock_audio)

        # 1. Handle incoming call with known contact
        incoming_event = {
            "type": "incoming_call",
            "event_id": "call_123456",
            "number": "+919876543210",
            "caller": "Rahul",
            "is_known_contact": True,
            "state": "ringing",
            "timestamp": 1791030000000,
        }

        with patch("tts_dispatch._tts_generate", AsyncMock(return_value=b"fake_wav")) as mock_tts:
            call_record = asyncio.run(dispatcher.handle_incoming_call(incoming_event))

            # Verify call record masking
            self.assertEqual(call_record["caller"], "Rahul")
            self.assertEqual(call_record["number"], "+91...3210")  # Masked for privacy
            self.assertEqual(call_record["full_number"], "+919876543210")

            # Verify desktop broadcaster received phone_call_alert
            mock_desktop.assert_called()
            sent_record = mock_desktop.call_args[0][0]
            self.assertEqual(sent_record["type"], "phone_call_alert")
            self.assertEqual(sent_record["caller"], "Rahul")

            # Verify TTS announcement phrased correctly
            mock_tts.assert_called_once()
            spoken_text = mock_tts.call_args[0][0]
            self.assertEqual(spoken_text, "Incoming call from Rahul.")

        # 2. Handle incoming call with private number
        mock_desktop.reset_mock()
        private_event = {
            "type": "incoming_call",
            "event_id": "call_789012",
            "number": "-1",
            "caller": "Private Number",
            "is_private": True,
            "state": "ringing",
            "timestamp": 1791030001000,
        }
        priv_record = asyncio.run(dispatcher.handle_incoming_call(private_event))
        self.assertTrue(priv_record["is_private"])
        self.assertEqual(priv_record["number"], "Private")

        # 3. Handle call state changed to ended
        ended_event = {
            "type": "call_state_changed",
            "event_id": "call_123456",
            "state": "ended",
            "timestamp": 1791030005000,
        }
        asyncio.run(dispatcher.handle_call_state_changed(ended_event))
        dismiss_record = mock_desktop.call_args[0][0]
        self.assertEqual(dismiss_record["type"], "phone_call_dismiss")
        self.assertEqual(dismiss_record["event_id"], "call_123456")

    def test_turn_controller_protection(self):
        dispatcher = NotificationDispatcher()
        mock_desktop = AsyncMock()
        mock_audio = AsyncMock()
        dispatcher.set_desktop_broadcaster(mock_desktop)
        dispatcher.set_audio_broadcaster(mock_audio)
        dispatcher.set_session_provider(lambda: ["test_session_1"])

        # Mock turn_controller so active turn is in flight
        with patch("core.turn_controller.turn_controller.is_active_turn_in_flight", return_value=True):
            with patch("tts_dispatch._tts_generate", AsyncMock(return_value=b"fake_wav")) as mock_tts:
                incoming_event = {
                    "type": "incoming_call",
                    "event_id": "call_active_turn",
                    "number": "+919876543210",
                    "caller": "Test User",
                    "is_known_contact": True,
                    "state": "ringing",
                }
                asyncio.run(dispatcher.handle_incoming_call(incoming_event))
                # Verify TTS announcement was deferred/skipped (turn active)
                mock_tts.assert_not_called()
                # Verify desktop WS was STILL notified (visual alert not blocked)
                mock_desktop.assert_called()


if __name__ == "__main__":
    unittest.main()
