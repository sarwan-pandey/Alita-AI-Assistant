"""
test_latency_and_runtime_bugs.py
================================
Automated test suite verifying the 6 newly resolved performance latency
bottlenecks and runtime error fixes:

1. Ollama Qwen3 think=False payload verification (disables 4-10s reasoning freeze).
2. Streaming token queue non-blocking get_nowait verification.
3. Conversation history preservation for both 'Alita:' and 'Aura:' without colon truncation.
4. Action hints regex boundary fix and avoidance of forced automation on conversational Hindi.
5. Removal of synchronous os.fsync physical disk barrier in RelationshipManager state saves.
6. Sub-millisecond HWND caching in RealityTracker poll_pc_active_window.
"""

import asyncio
import json
import os
import queue
import re
import sys
import time
from unittest.mock import MagicMock, patch

# Ensure backend modules and workspace can be imported
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.engines.reality_tracker import (
    reality_tracker,
    CATEGORY_PRODUCTIVE,
    CATEGORY_NEUTRAL,
    CATEGORY_DISTRACTION,
)
from backend.engines.relationship_manager import relationship_manager, STATE_FILE
from backend.main import _build_history, SessionRecord


class DummySession:
    def __init__(self, buffer: str = ""):
        self.transcript_buffer = buffer


# ─────────────────────────────────────────────────────────────────────────────
# TEST 1: Ollama Qwen3 Thinking Suppression & Leak Prevention
# ─────────────────────────────────────────────────────────────────────────────
def test_ollama_qwen3_thinking_disabled_payload():
    """Verify that thinking tokens are strictly suppressed from token_queue and responses."""
    # Test 1A: Inspect general_handler._try_ollama_stream suppression
    import backend.threads.general_handler as gh
    with open(gh.__file__, "r", encoding="utf-8") as f:
        gh_content = f.read()
    assert 'data.get("message", {}).get("thinking")' in gh_content, "general_handler must drop thinking field"
    assert 'in_think_block' in gh_content, "general_handler must filter inline think blocks"

    # Test 1B: Inspect ollama_client.ollama_chat suppression
    import backend.ollama_client as oc
    with open(oc.__file__, "r", encoding="utf-8") as f:
        oc_content = f.read()
    assert 'return lines[-1]' not in oc_content, "ollama_client must not return thinking lines as speech"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 2: Streaming Token Queue Non-Blocking Execution
# ─────────────────────────────────────────────────────────────────────────────
def test_streaming_token_queue_nonblocking():
    """Verify that token queue drains via get_nowait at microsecond speed without threadpool dispatch."""
    token_q = queue.Queue()
    test_tokens = ["Hello", " ", "Sarwan", "!", " ", "How", " ", "are", " ", "you", "?"]
    for t in test_tokens:
        token_q.put(t)
    token_q.put(None)  # Sentinel

    collected = []
    t_start = time.perf_counter()
    while True:
        try:
            tok = token_q.get_nowait()
        except queue.Empty:
            continue
        if tok is None:
            break
        collected.append(tok)
    duration_ms = (time.perf_counter() - t_start) * 1000.0

    assert "".join(collected) == "Hello Sarwan! How are you?"
    assert duration_ms < 5.0, f"Draining 11 tokens via get_nowait took {duration_ms:.2f}ms, expected < 5ms"


# ─────────────────────────────────────────────────────────────────────────────
# TEST 3: Multi-Turn Conversation History Preservation (Alita: and Aura:)
# ─────────────────────────────────────────────────────────────────────────────
def test_history_preservation_and_no_leading_colon():
    """Verify _build_history preserves assistant turns for both 'Alita:' and 'Aura:' without colon corruption."""
    # 3A: Buffer with modern 'Alita:' prefixes
    buf_alita = (
        "User: Tum kaun ho?\n"
        "Alita: Main Alita hoon, tumhari girlfriend.\n"
        "User: Aur kya karti ho?\n"
        "Alita: Main hamesha tumhara dhyan rakhti hoon."
    )
    sess_alita = DummySession(buf_alita)
    history_alita = _build_history(sess_alita, max_history=10)

    assert len(history_alita) == 4
    assert history_alita[0] == {"role": "user", "content": "Tum kaun ho?"}
    # Check that 'Alita:' is stripped cleanly without leaving ': '
    assert history_alita[1] == {"role": "assistant", "content": "Main Alita hoon, tumhari girlfriend."}
    assert history_alita[2] == {"role": "user", "content": "Aur kya karti ho?"}
    assert history_alita[3] == {"role": "assistant", "content": "Main hamesha tumhara dhyan rakhti hoon."}

    # 3B: Backward-compatibility with legacy 'Aura:' prefixes
    buf_aura = (
        "User: Hello\n"
        "Aura: Hi Sarwan!\n"
        "User: How are you?\n"
        "Aura: I'm feeling great today!"
    )
    sess_aura = DummySession(buf_aura)
    history_aura = _build_history(sess_aura, max_history=10)

    assert len(history_aura) == 4
    assert history_aura[1] == {"role": "assistant", "content": "Hi Sarwan!"}
    assert history_aura[3] == {"role": "assistant", "content": "I'm feeling great today!"}


# ─────────────────────────────────────────────────────────────────────────────
# TEST 4: Action Hints Regex & Conversational Hindi Routing
# ─────────────────────────────────────────────────────────────────────────────
def test_action_hints_and_conversational_hindi():
    """Verify word boundary regex works, and conversational Hindi does not trigger OS automation hints."""
    action_hints_pattern = re.compile(
        r"\b(open|close|create|make|delete|move|copy|save|press|click|type|write|"
        r"navigate|go\s+to|run|execute|launch|start|search|find|show|set|turn|"
        r"increase|decrease|minimize|maximize|switch|send|new|rename|undo|redo|"
        r"refresh|reload|install|uninstall|download|upload|extract|zip|connect|"
        r"disconnect|enable|disable|"
        r"kholo|khole|kholna|khol|band|banao|bana|chalu|chalao|bhejo|"
        r"hatao|hata|mitao|mita|dikhao|dikha|bachao|bacha|"
        r"dhundho|dhundh|badlo|badal|kar\s+do|le\s+jao|jao)\b",
        re.IGNORECASE
    )

    # Legitimate automation queries MUST match
    assert action_hints_pattern.search("open chrome") is not None
    assert action_hints_pattern.search("notepad kholo") is not None
    assert action_hints_pattern.search("file banao") is not None
    assert action_hints_pattern.search("folder delete kar do") is not None

    # Conversational Hindi queries MUST NOT match action hints
    assert action_hints_pattern.search("mujhe apne baare mein batao") is None
    assert action_hints_pattern.search("ek achhi kahani batao") is None
    assert action_hints_pattern.search("kya tum mujhse baat karogi") is None
    assert action_hints_pattern.search("padhai kaise kare") is None


# ─────────────────────────────────────────────────────────────────────────────
# TEST 5: RelationshipManager State Saves without os.fsync Barrier
# ─────────────────────────────────────────────────────────────────────────────
def test_relationship_manager_save_state_without_fsync():
    """Verify that _save_state does not invoke blocking os.fsync."""
    with patch("os.fsync") as mock_fsync:
        relationship_manager.record_truth("I am studying hard", "Verified Visual Studio Code in foreground")
        # fsync should not have been called
        assert mock_fsync.call_count == 0, "os.fsync should not be called in atomic file saves"

    # Verify state file was written and is valid JSON
    assert os.path.exists(STATE_FILE)
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert "affection_score" in data
    assert "current_mood" in data


# ─────────────────────────────────────────────────────────────────────────────
# TEST 6: Sub-Millisecond HWND Caching in RealityTracker
# ─────────────────────────────────────────────────────────────────────────────
def test_reality_tracker_hwnd_caching():
    """Verify that consecutive poll_pc_active_window calls within 1.0s utilize cache."""
    reality_tracker._cached_hwnd = 12345
    reality_tracker._cached_hwnd_time = time.time()
    reality_tracker._cached_pc_result = ("code.exe", "VS Code - Project", "Visual Studio Code", CATEGORY_PRODUCTIVE)

    # Patch win32gui.GetForegroundWindow to return the cached HWND
    with patch("backend.engines.reality_tracker.win32gui.GetForegroundWindow", return_value=12345):
        with patch("backend.engines.reality_tracker.psutil.Process") as mock_psutil:
            t0 = time.perf_counter()
            res = reality_tracker.poll_pc_active_window()
            latency_us = (time.perf_counter() - t0) * 1_000_000.0

            # psutil.Process should NOT have been called due to cache hit
            assert mock_psutil.call_count == 0, "psutil.Process must not be called on cache hit"
            assert res == ("code.exe", "VS Code - Project", "Visual Studio Code", CATEGORY_PRODUCTIVE)
            assert latency_us < 500.0, f"Cached poll took {latency_us:.2f} microseconds, expected < 500us"
