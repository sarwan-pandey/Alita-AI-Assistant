"""
End-to-End Simulation of Girlfriend Lie Detector Loop in Alita
"""

import time
from engines.reality_tracker import reality_tracker, CATEGORY_PRODUCTIVE
from engines.relationship_manager import relationship_manager
from engines.lie_detector import lie_detector


class MockSession:
    user_id = "sarwan"
    custom_name = "Alita"
    tier = "free"
    connected_at = time.time()
    current_emotion = "neutral"
    emotion_confidence = 0.8
    interaction_count = 5


def test_full_girlfriend_prompt_injection():
    try:
        from main import _build_system_prompt
    except ImportError:
        from backend.main import _build_system_prompt

    session = MockSession()

    # Step 1: User switches to Instagram on phone
    reality_tracker.update_phone_app("com.instagram.android", is_screen_on=True)
    reality_tracker.update_phone_screen_state(is_screen_on=True, is_locked=False)

    # Step 2: User says "I am studying for my exam"
    user_text = "I am studying for my exam right now"
    system_prompt = _build_system_prompt(session, user_text=user_text)

    # Step 3: Verify that system prompt has the Lie Detector directive and Girlfriend instructions
    assert "[GROUND TRUTH REALITY VERIFICATION" in system_prompt
    assert "LIE CAUGHT" in system_prompt
    assert "Instagram" in system_prompt
    assert "GIRLFRIEND RELATIONSHIP DYNAMICS" in system_prompt
    assert "Sarwan" in system_prompt


def test_full_girlfriend_truth_injection():
    try:
        from main import _build_system_prompt
    except ImportError:
        from backend.main import _build_system_prompt

    session = MockSession()

    # Step 1: User locks phone and opens VS Code
    reality_tracker.update_phone_app("", is_screen_on=False)
    reality_tracker.update_phone_screen_state(is_screen_on=False, is_locked=True)
    reality_tracker.pc_category = CATEGORY_PRODUCTIVE
    reality_tracker.pc_friendly_name = "Visual Studio Code"

    # Step 2: User says "I am studying"
    user_text = "I am studying for my exam right now"
    system_prompt = _build_system_prompt(session, user_text=user_text)

    # Step 3: Verify that system prompt has Truth confirmation directive
    assert "[GROUND TRUTH REALITY VERIFICATION" in system_prompt
    assert "TRUTH CONFIRMED" in system_prompt
    assert "Praise him warmly and lovingly" in system_prompt
