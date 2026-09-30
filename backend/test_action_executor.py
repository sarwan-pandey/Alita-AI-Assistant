"""
test_action_executor.py — Test ActionExecutor closed-loop verification and retry policies
"""

import asyncio
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from engines.action_executor import ActionExecutor, ExecutionOutcome


def test_action_executor_early_polling_success():
    """Test 1: execute_and_verify returns early via polling, proving no fixed sleep."""
    poll_count = 0
    state = {"isScreenOn": True, "isLocked": True}

    async def mock_dispatch(action):
        pass

    async def mock_get_state():
        nonlocal poll_count
        poll_count += 1
        # Flip to unlocked on 2nd poll
        if poll_count >= 2:
            state["isLocked"] = False
        return dict(state)

    executor = ActionExecutor(bridge_dispatch_fn=mock_dispatch)

    start = time.time()
    outcome = asyncio.run(executor.execute_and_verify(
        action={"command": "unlock"},
        expected_state_fn=lambda s: s.get("isLocked") is False,
        get_state_fn=mock_get_state,
        timeout_s=3.0,
        poll_interval_s=0.05,
        max_retries=1,
    ))
    elapsed = time.time() - start

    assert outcome.verified is True
    assert outcome.success is True
    assert elapsed < 1.0, f"Expected sub-second return via polling, took {elapsed:.2f}s"
    assert poll_count >= 2
    print(f"✅ Test 1 Passed: Polling verified in {elapsed:.3f}s with {poll_count} checks")


def test_action_executor_retry_and_failure_reporting():
    """Test 2: Failed action triggers exactly max_retries and returns structured failure with last state."""
    dispatch_attempts = 0
    state = {"isScreenOn": True, "isLocked": True, "currentPackage": "com.android.keyguard"}

    async def mock_dispatch(action):
        nonlocal dispatch_attempts
        dispatch_attempts += 1

    async def mock_get_state():
        return dict(state)

    executor = ActionExecutor(bridge_dispatch_fn=mock_dispatch)

    outcome = asyncio.run(executor.execute_and_verify(
        action={"command": "tap", "x": 100, "y": 200},
        expected_state_fn=lambda s: s.get("isLocked") is False,
        get_state_fn=mock_get_state,
        timeout_s=0.2,
        poll_interval_s=0.05,
        max_retries=2,
    ))

    assert outcome.verified is False
    assert outcome.success is False
    # Initial attempt + 2 retries = 3 attempts total
    assert dispatch_attempts == 3, f"Expected 3 attempts, got {dispatch_attempts}"
    assert outcome.retries_attempted == 2
    assert outcome.post_state.get("currentPackage") == "com.android.keyguard"
    print("✅ Test 2 Passed: Retries executed exactly twice and structured post-state attached")


def test_tricky_already_in_expected_state_short_circuit():
    """Tricky 1: Pre-state check short-circuits execution if already achieved (0 dispatch calls)."""
    dispatched = False
    state = {"isScreenOn": True, "isLocked": False}

    async def mock_dispatch(action):
        nonlocal dispatched
        dispatched = True

    executor = ActionExecutor(bridge_dispatch_fn=mock_dispatch)

    outcome = asyncio.run(executor.execute_and_verify(
        action={"command": "unlock"},
        expected_state_fn=lambda s: s.get("isLocked") is False,
        get_state_fn=lambda: dict(state),
        timeout_s=1.0,
        poll_interval_s=0.05,
    ))

    assert outcome.success is True
    assert outcome.verified is True
    assert dispatched is False, "Should NOT dispatch any command if state is already verified"
    assert outcome.message == "Target state already achieved."
    print("✅ Tricky Test 1 Passed: ActionExecutor short-circuits instantly when state is already achieved")


def test_tricky_interruption_auto_recovery_during_action():
    """Tricky 2: Permission popup appears during action; executor auto-resolves and finishes successfully."""
    dispatched_action = False
    clicked_dialog_button = None

    async def mock_dispatch(action):
        nonlocal clicked_dialog_button, dispatched_action
        if action.get("command") == "click":
            clicked_dialog_button = action.get("target")
        else:
            dispatched_action = True
        return {"success": True}

    async def mock_get_state():
        if clicked_dialog_button:
            # Popup was dismissed, unlocked state now achieved
            return {"isLocked": False, "view_tree": {}}
        elif dispatched_action:
            # Action dispatched, but interrupted by permission popup
            return {
                "isLocked": True,
                "view_tree": {
                    "package": "com.google.android.permissioncontroller",
                    "nodes": [
                        {"text": "Allow Alita to access phone state?", "isClickable": False},
                        {"text": "While using the app", "isClickable": True},
                    ]
                }
            }
        else:
            # Pre-state
            return {"isLocked": True, "view_tree": {}}

    executor = ActionExecutor(bridge_dispatch_fn=mock_dispatch)

    outcome = asyncio.run(executor.execute_and_verify(
        action={"command": "unlock"},
        expected_state_fn=lambda s: s.get("isLocked") is False,
        get_state_fn=mock_get_state,
        timeout_s=0.08,
        poll_interval_s=0.02,
        max_retries=1,
    ))

    assert outcome.success is True
    assert outcome.verified is True
    assert clicked_dialog_button == "While using the app"
    assert outcome.interruption is not None
    assert outcome.interruption.dialog_title == "runtime_permission_while_using"
    print("✅ Tricky Test 2 Passed: ActionExecutor self-healed by auto-dismissing runtime permission mid-flight")


def test_tricky_network_exception_recovery():
    """Tricky 3: Dispatch function raises connection exception on attempt 1, succeeds on retry."""
    attempts = 0
    state = {"isLocked": True}

    async def faulty_dispatch(action):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionResetError("WebSocket frame dropped")
        # Attempt 2 succeeds
        state["isLocked"] = False

    executor = ActionExecutor(bridge_dispatch_fn=faulty_dispatch)

    outcome = asyncio.run(executor.execute_and_verify(
        action={"command": "tap", "x": 100, "y": 100},
        expected_state_fn=lambda s: s.get("isLocked") is False,
        get_state_fn=lambda: dict(state),
        timeout_s=0.1,
        poll_interval_s=0.03,
        max_retries=1,
    ))

    assert outcome.success is True
    assert outcome.verified is True
    assert attempts == 2
    print("✅ Tricky Test 3 Passed: ActionExecutor handled dispatch transport exception and recovered on retry")


if __name__ == "__main__":
    test_action_executor_early_polling_success()
    test_action_executor_retry_and_failure_reporting()
    test_tricky_already_in_expected_state_short_circuit()
    test_tricky_interruption_auto_recovery_during_action()
    test_tricky_network_exception_recovery()
    print("\n🎉 ALL 5 ACTION EXECUTOR TESTS (INCLUDING TRICKY TESTS) PASSED!")
