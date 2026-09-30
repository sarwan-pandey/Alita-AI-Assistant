"""
test_task_planner.py — Test Multi-Step Task Planning and Step-by-Step Execution
"""

import asyncio
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from engines.action_executor import action_executor
from engines.task_planner import task_planner


def test_task_planner_step_decomposition():
    """Test 7a: Decomposes 'message Rahul on WhatsApp that I am running late' into ordered steps."""
    instr = "message Rahul on WhatsApp that: I am running late"
    steps = task_planner.plan_steps(instr, current_screen_state={})

    assert len(steps) >= 5
    step_names = [s.name for s in steps]
    assert "launch_whatsapp" in step_names
    assert "search_contact" in step_names
    assert "type_contact_name" in step_names
    assert "open_chat" in step_names
    assert "type_message" in step_names
    assert "send_message" in step_names

    # Check that contact name and message are accurately mapped
    type_name_step = next(s for s in steps if s.name == "type_contact_name")
    assert type_name_step.action.get("text") == "Rahul"

    type_msg_step = next(s for s in steps if s.name == "type_message")
    assert type_msg_step.action.get("text") == "I am running late"

    print("✅ Test 7a Passed: Complex instruction decomposed into verified sequence")


def test_task_planner_execution_with_narration():
    """Test 7b: Executes plan with step narration callback and state verification."""
    steps = task_planner.plan_steps("open YouTube", current_screen_state={})
    assert len(steps) == 1
    assert steps[0].action.get("package") == "com.google.android.youtube"

    narrated = []

    async def mock_narrate(text):
        narrated.append(text)

    app_state = {"currentPackage": "com.android.launcher"}

    async def mock_dispatch(act):
        if act.get("command") == "launch_app":
            app_state["currentPackage"] = act.get("package")
        return {"success": True}

    action_executor.set_bridge_dispatcher(mock_dispatch)

    res = asyncio.run(task_planner.execute_plan(
        steps=steps,
        get_state_fn=lambda: dict(app_state),
        narration_callback=mock_narrate,
    ))

    assert res.success is True
    assert res.completed_steps == 1
    assert len(narrated) == 1
    assert "opening youtube" in narrated[0].lower()
    print(f"✅ Test 7b Passed: Step plan verified with live narration: '{narrated[0]}'")


def test_tricky_hindi_hinglish_messaging():
    """Tricky 1: Decomposes Hindi/Hinglish phrasing into structured WhatsApp steps."""
    instr = "whatsapp pe Rohit ko message bhejo ki: main 10 minute me aa raha hu"
    steps = task_planner.plan_steps(instr, current_screen_state={})

    assert len(steps) >= 5
    recip_step = next(s for s in steps if s.name == "type_contact_name")
    assert recip_step.action.get("text") == "Rohit"

    msg_step = next(s for s in steps if s.name == "type_message")
    assert "main 10 minute me aa raha hu" in msg_step.action.get("text")
    print("✅ Tricky Test 1 Passed: Hindi/Hinglish messaging instruction cleanly decomposed")


def test_tricky_skip_launch_if_already_foreground():
    """Tricky 2: Skips redundant app launch if app is already active foreground."""
    instr = "message Priya on WhatsApp that I am outside"
    steps = task_planner.plan_steps(instr, current_screen_state={"currentPackage": "com.whatsapp"})

    step_names = [s.name for s in steps]
    assert "launch_whatsapp" not in step_names, "Should omit launch_whatsapp if WhatsApp is already foreground"
    assert step_names[0] == "search_contact"
    print("✅ Tricky Test 2 Passed: Redundant launch_app skipped when target is already active")


def test_tricky_mid_workflow_failure_halts_immediately():
    """Tricky 3: Mid-plan failure immediately aborts remaining steps to avoid corrupting state."""
    instr = "message Aman on WhatsApp that hello"
    steps = task_planner.plan_steps(instr, current_screen_state={})
    for s in steps:
        s.timeout_s = 0.05

    # Mock dispatch where step 2 (search_contact) fails verification
    async def mock_dispatch(act):
        return {"success": True}

    action_executor.set_bridge_dispatcher(mock_dispatch)

    # State returns wrong package on step 2
    step_calls = 0

    def mock_state():
        nonlocal step_calls
        step_calls += 1
        if step_calls <= 2:
            return {"currentPackage": "com.whatsapp"}
        # Fail step 2
        return {"currentPackage": "com.android.launcher"}

    res = asyncio.run(task_planner.execute_plan(
        steps=steps,
        get_state_fn=mock_state,
    ))

    assert res.success is False
    assert res.completed_steps < len(steps)
    print(f"✅ Tricky Test 3 Passed: Mid-workflow failure halted cleanly at step {res.completed_steps}")


if __name__ == "__main__":
    test_task_planner_step_decomposition()
    test_task_planner_execution_with_narration()
    test_tricky_hindi_hinglish_messaging()
    test_tricky_skip_launch_if_already_foreground()
    test_tricky_mid_workflow_failure_halts_immediately()
    print("\n🎉 ALL 5 TASK PLANNER TESTS (INCLUDING TRICKY TESTS) PASSED!")
