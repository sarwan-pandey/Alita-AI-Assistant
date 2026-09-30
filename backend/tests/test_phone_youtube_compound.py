import pytest
import asyncio
import os
import sys

# Ensure backend root is in python path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from engines.semantic_target_binder import semantic_target_binder
from engines.compound_pipeline import compound_pipeline
from engines.task_planner import task_planner
from engines.phone_orchestrator import phone_orchestrator
from engines.action_executor import action_executor
from threads.automation_handler import _fast_parse_automation_command


def test_compound_device_target_propagation():
    """Verify compound commands maintain device target across split sub-steps."""
    cmd = "I want you to unlock my phone and play a music in the YouTube"
    
    # 1. Full intent binding
    full_bind = semantic_target_binder.resolve(cmd)
    assert full_bind["target_device"] == "phone"
    assert full_bind["action"] == "play_media"
    assert full_bind["query"] == "top trending songs"

    # 2. Split steps
    steps = compound_pipeline.split_steps(cmd)
    assert len(steps) == 2
    assert "unlock my phone" in steps[0]
    assert "play a music in the YouTube" in steps[1]

    # 3. Step 2 inherits phone target
    s2_bind = semantic_target_binder.resolve(steps[1], inherited_target=full_bind["target_device"])
    assert s2_bind["target_device"] == "phone"
    assert s2_bind["query"] == "top trending songs"


def test_task_planner_compound_phone_plan():
    """Verify TaskPlanner plans both unlock and YouTube playback with clean query."""
    cmd = "I want you to unlock my phone and play a music in the YouTube"
    tp_steps = task_planner.plan_steps(cmd, {})
    assert len(tp_steps) >= 3
    assert tp_steps[0].name == "unlock_device"
    assert tp_steps[1].name == "launch_youtube_search"
    assert "top%20trending%20songs" in tp_steps[1].action.get("deepLink", "")
    assert tp_steps[2].name == "tap_first_video"
    assert tp_steps[2].action.get("command") == "tap"


@pytest.mark.anyio
async def test_phone_orchestrator_already_unlocked():
    """Verify phone orchestrator short-circuits with success when already unlocked."""
    phone_orchestrator.device_info["connected"] = True
    phone_orchestrator.device_info["isLocked"] = False
    phone_orchestrator.device_info["currentPackage"] = "com.google.android.apps.nexuslauncher"

    res = await phone_orchestrator.run_instruction("unlock my phone", session_state={})
    assert res.get("success") is True
    assert res.get("alreadyUnlocked") is True
    assert "already unlocked" in res.get("message", "").lower()
    assert res.get("needs_confirmation") is not True


def test_music_query_sanitization():
    """Verify 'play a music in the YouTube' does not extract literal 'in youtube'."""
    parsed = _fast_parse_automation_command("play a music in the YouTube")
    assert parsed["action"] == "open_music"
    assert parsed["query"] == "top trending songs"

    parsed2 = _fast_parse_automation_command("play despacito on youtube")
    assert parsed2["action"] == "open_music"
    assert parsed2["query"] == "despacito"


def test_end_to_end_compound_pipeline_no_pc_tabs():
    """Verify compound pipeline executes on phone bridge and opens 0 PC tabs."""
    cmd = "I want you to unlock my phone and play a music in the YouTube"
    phone_orchestrator.device_info["connected"] = True
    phone_orchestrator.device_info["isLocked"] = False

    dispatched = []
    pc_tabs = []

    async def mock_dispatch(act):
        dispatched.append(act)
        return {"success": True}

    phone_orchestrator.set_bridge_sender(mock_dispatch)
    action_executor.set_bridge_dispatcher(mock_dispatch)

    import webbrowser
    orig_open = webbrowser.open
    def mock_open(url):
        pc_tabs.append(url)
        return True
    webbrowser.open = mock_open

    try:
        pipeline_res = compound_pipeline.execute(cmd)
        assert pipeline_res["status"] == "success"
        assert pipeline_res["steps_count"] == 2
        # Zero PC tabs opened
        assert len(pc_tabs) == 0
        # Dispatched to phone
        assert any(c.get("command") == "launch_app" and c.get("package") == "com.google.android.youtube" for c in dispatched)
        assert any(c.get("command") == "tap" for c in dispatched)
    finally:
        webbrowser.open = orig_open
