"""
Unit Tests for ws_handler.py (WebSocket Message Dispatcher)
===========================================================
"""

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from ws_handler import WsContext, dispatch_ws_message, DISPATCH_TABLE


class MockWebSocket:
    def __init__(self):
        self.sent_messages = []

    async def send_text(self, text: str):
        self.sent_messages.append(json.loads(text))


class MockSession:
    def __init__(self):
        self.pipeline_cancel = False
        self.barge_in_count = 0
        self.cancel_event = asyncio.Event()
        self.interrupted_response = ""
        self.interrupted_query = ""
        self.voice_id = None
        self.manual_voice_override = False
        self.dictation_active = True
        self.detected_language = "en"
        self.screen_context = ""


@pytest.fixture
def ws_context():
    ws = MockWebSocket()
    sess = MockSession()
    voices = {
        "chatterbox_mj": {
            "name": "MJ",
            "tier_required": "free",
            "lang": "en",
        },
        "premium_voice": {
            "name": "Premium Voice",
            "tier_required": "premium",
            "lang": "en",
        }
    }
    return WsContext(
        websocket=ws,
        session=sess,
        session_id="test_session_1",
        user_id="user_123",
        tier="free",
        active_sessions={"test_session_1": sess},
        available_voices=voices,
        default_active_voice="chatterbox_mj",
    )


@pytest.mark.anyio
async def test_ping_handler(ws_context):
    msg = {"type": "ping"}
    handled = await dispatch_ws_message("ping", msg, ws_context)
    assert handled is True
    assert len(ws_context.websocket.sent_messages) == 1
    reply = ws_context.websocket.sent_messages[0]
    assert reply["type"] == "pong"
    assert "ts" in reply


@pytest.mark.anyio
async def test_barge_in_handler(ws_context):
    msg = {
        "type": "barge_in",
        "partial_response": "I was about to say...",
        "original_query": "What is the capital?",
    }
    handled = await dispatch_ws_message("barge_in", msg, ws_context)
    assert handled is True
    assert ws_context.session.pipeline_cancel is True
    assert ws_context.session.barge_in_count == 1
    assert ws_context.session.interrupted_response == "I was about to say..."
    assert ws_context.session.interrupted_query == "What is the capital?"
    assert ws_context.session.cancel_event.is_set()


@pytest.mark.anyio
async def test_language_detected_handler(ws_context):
    msg = {"type": "language_detected", "language": "hi"}
    handled = await dispatch_ws_message("language_detected", msg, ws_context)
    assert handled is True
    assert ws_context.session.detected_language == "hi"


@pytest.mark.anyio
async def test_screen_read_handler(ws_context):
    msg = {"type": "screen_read", "text": "Visual Studio Code - main.py"}
    handled = await dispatch_ws_message("screen_read", msg, ws_context)
    assert handled is True
    assert ws_context.session.screen_context == "Visual Studio Code - main.py"
    reply = ws_context.websocket.sent_messages[0]
    assert reply["type"] == "screen_read_ack"
    assert reply["length"] == len("Visual Studio Code - main.py")


@pytest.mark.anyio
async def test_voice_change_free_tier_allowed(ws_context):
    msg = {"type": "voice_change", "voice_id": "chatterbox_mj"}
    handled = await dispatch_ws_message("voice_change", msg, ws_context)
    assert handled is True
    assert ws_context.session.voice_id == "chatterbox_mj"
    reply = ws_context.websocket.sent_messages[0]
    assert reply["type"] == "voice_changed"
    assert reply["voice_id"] == "chatterbox_mj"


@pytest.mark.anyio
async def test_voice_change_premium_denied_for_free(ws_context):
    msg = {"type": "voice_change", "voice_id": "premium_voice"}
    handled = await dispatch_ws_message("voice_change", msg, ws_context)
    assert handled is True
    reply = ws_context.websocket.sent_messages[0]
    assert reply["type"] == "voice_change_denied"
    assert reply["reason"] == "premium_required"


@pytest.mark.anyio
async def test_unknown_message_returns_false(ws_context):
    handled = await dispatch_ws_message("non_existent_type", {}, ws_context)
    assert handled is False
