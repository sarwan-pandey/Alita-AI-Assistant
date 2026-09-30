"""
Unit Tests for RelationshipManager
"""

import pytest
from engines.relationship_manager import (
    RelationshipManager,
    MOOD_PLAYFUL,
    MOOD_POUTING,
    MOOD_CARING_SCOLDING,
    MOOD_AFFECTIONATE,
)


@pytest.fixture
def manager():
    mgr = RelationshipManager()
    # Reset state for clean testing
    mgr.state["affection_score"] = 80
    mgr.state["current_mood"] = MOOD_PLAYFUL
    mgr.state["lie_count_today"] = 0
    return mgr


def test_record_lie_progression(manager):
    # 1st lie
    st1 = manager.record_lie("study", "Instagram active")
    assert st1["lie_count_today"] == 1
    assert st1["current_mood"] == MOOD_PLAYFUL
    assert st1["affection_score"] == 77

    # 2nd lie -> pouting
    st2 = manager.record_lie("study", "YouTube active")
    assert st2["lie_count_today"] == 2
    assert st2["current_mood"] == MOOD_POUTING
    assert st2["affection_score"] == 72

    # 3rd lie -> caring_scolding
    st3 = manager.record_lie("study", "Game active")
    assert st3["lie_count_today"] == 3
    assert st3["current_mood"] == MOOD_CARING_SCOLDING
    assert st3["affection_score"] == 67


def test_record_truth_boost(manager):
    initial_score = manager.state["affection_score"]
    st = manager.record_truth("study", "VS Code open, phone locked")
    assert st["affection_score"] == initial_score + 3
    assert st["current_mood"] == MOOD_AFFECTIONATE


def test_get_personality_directives(manager):
    directive = manager.get_personality_directives()
    assert "GIRLFRIEND RELATIONSHIP DYNAMICS" in directive
    assert "Sarwan" in directive
