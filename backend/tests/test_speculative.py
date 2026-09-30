"""Unit tests for Gap 9: Speculative Query Optimization.
Tests precomputed greeting cache, similarity matching, cancellation, and latency savings.
"""

import time
import pytest
from unittest.mock import MagicMock


def test_greeting_cache_hit():
    from engines.speculative_engine import get_precomputed_greeting
    
    assert get_precomputed_greeting("hello") is not None
    assert get_precomputed_greeting("Hi there!") is not None
    assert get_precomputed_greeting("good morning") is not None
    assert get_precomputed_greeting("hey alita") is not None
    assert get_precomputed_greeting("namaste") is not None


def test_greeting_cache_miss():
    from engines.speculative_engine import get_precomputed_greeting
    
    assert get_precomputed_greeting("what is the weather in Delhi?") is None
    assert get_precomputed_greeting("open chrome and search google") is None
    assert get_precomputed_greeting("") is None


def test_similarity_high_overlap():
    from engines.speculative_engine import compute_query_similarity, is_speculative_cache_hit
    
    sim = compute_query_similarity("what is the capital of france", "what's the capital of france")
    assert sim >= 0.8, f"Expected similarity >= 0.8, got {sim}"
    assert is_speculative_cache_hit("what is the capital of france", "what's the capital of france", threshold=0.8) is True


def test_similarity_low_overlap():
    from engines.speculative_engine import compute_query_similarity, is_speculative_cache_hit
    
    sim = compute_query_similarity("what is the weather in Tokyo", "play some relaxing jazz music")
    assert sim < 0.5, f"Expected similarity < 0.5, got {sim}"
    assert is_speculative_cache_hit("what is the weather in Tokyo", "play some relaxing jazz music", threshold=0.8) is False


def test_speculative_state_tracking_and_latency():
    from engines.speculative_engine import SpeculativeManager
    
    mgr = SpeculativeManager()
    session = MagicMock()
    session._spec_result = None
    session._spec_text = None
    session._spec_start_time = None
    session._spec_cancel = None

    # Start speculative query
    cancel_evt = mgr.start_speculative(session, spec_id=1, spec_text="hello")
    assert not cancel_evt.is_set()
    assert session._spec_id == 1
    # "hello" should immediately be satisfied via precomputed greeting
    assert session._spec_result is not None
    assert session._spec_text == "hello"

    # Verify latency calculation
    time.sleep(0.02)
    hit, result, latency_saved = mgr.check_cache_hit(session, "hello")
    assert hit is True
    assert result == session._spec_result
    assert latency_saved >= 0.01
