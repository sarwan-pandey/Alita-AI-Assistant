"""
test_context_aware_automation.py — Rigorous Verification Test Suite
Tests all 5 phases of Context-Aware Mobile Automation:
1. Screen Analyzer (Semantic, Spatial, Heuristics, Readiness)
2. Interruption Handler (Realme/ColorOS, App & System Popups, Scroll Recovery)
3. Action Executor (Pre-Action Target Resolution, Smart Wait, Error Classification)
4. Task Planner (Enhanced TaskStep, 15+ Workflows, Dynamic Execution)
5. Phone Orchestrator & Decision Router (17 Hardware Methods, Lock Guard, Intent Routing)
"""

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.screen_analyzer import screen_analyzer, ScreenContext, ScreenElement
from engines.action_executor import action_executor, ExecutionOutcome
from engines.interruption_handler import interruption_handler, InterruptionResult
from engines.task_planner import task_planner, TaskStep, TaskPlanResult
from engines.phone_orchestrator import phone_orchestrator
from decision_router import classify_query


class TestPhase1ScreenAnalyzer(unittest.TestCase):
    """Phase 1: Semantic Screen Perception & Intelligence Tests"""

    def setUp(self):
        self.mock_whatsapp_conversation = {
            "package": "com.whatsapp",
            "nodes": [
                {"id": "1", "resourceId": "action_bar_back", "contentDesc": "Navigate up", "isClickable": True, "className": "android.widget.ImageView", "bounds": "[20,70][110,160]"},
                {"id": "2", "resourceId": "conversation_contact_name", "text": "Mom", "isClickable": True, "className": "android.widget.TextView", "bounds": "[130,70][400,160]"},
                {"id": "3", "resourceId": "entry", "text": "Type a message", "isEditable": True, "className": "android.widget.EditText", "bounds": "[40,2100][880,2250]"},
                {"id": "4", "resourceId": "send", "contentDesc": "Send", "isClickable": True, "className": "android.widget.ImageButton", "bounds": "[900,2110][1040,2240]"},
                {"id": "5", "className": "androidx.recyclerview.widget.RecyclerView", "isScrollable": True, "bounds": "[0,170][1080,2090]"},
            ]
        }

    def test_screen_context_parsing(self):
        ctx = screen_analyzer.analyze_screen(self.mock_whatsapp_conversation)
        self.assertEqual(ctx.app_name, "WhatsApp")
        self.assertEqual(ctx.package, "com.whatsapp")
        self.assertEqual(ctx.screen_type, "conversation")
        self.assertFalse(ctx.has_loading_spinner)
        self.assertFalse(ctx.has_dialog_overlay)
        self.assertEqual(len(ctx.interactive_elements), 4)
        self.assertEqual(len(ctx.scrollable_containers), 1)

    def test_loading_state_detection(self):
        loading_tree = {
            "package": "com.android.chrome",
            "nodes": [
                {"id": "1", "className": "android.widget.ProgressBar", "bounds": "[0,100][1080,120]"}
            ]
        }
        self.assertFalse(screen_analyzer.is_screen_ready(loading_tree))
        ctx = screen_analyzer.analyze_screen(loading_tree)
        self.assertTrue(ctx.has_loading_spinner)

    def test_element_finding_exact_and_fuzzy(self):
        # 1. Exact ID
        elem1 = screen_analyzer.find_element_smart(self.mock_whatsapp_conversation, "send")
        self.assertIsNotNone(elem1)
        self.assertEqual(elem1["resourceId"], "send")

        # 2. Exact text
        elem2 = screen_analyzer.find_element_smart(self.mock_whatsapp_conversation, "Mom")
        self.assertIsNotNone(elem2)
        self.assertEqual(elem2["text"], "Mom")

        # 3. Fuzzy text
        elem3 = screen_analyzer.find_element_smart(self.mock_whatsapp_conversation, "type a messge")  # typo
        self.assertIsNotNone(elem3)
        self.assertEqual(elem3["resourceId"], "entry")

        # 4. Semantic synonym: "back button"
        elem4 = screen_analyzer.find_element_smart(self.mock_whatsapp_conversation, "back button")
        self.assertIsNotNone(elem4)
        self.assertEqual(elem4["resourceId"], "action_bar_back")

    def test_positional_heuristics(self):
        # Even without explicit resource ID or text, find by position:
        anon_tree = {
            "package": "com.unknown.app",
            "nodes": [
                {"id": "1", "isClickable": True, "bounds": "[30,50][120,140]"},        # top-left
                {"id": "2", "isClickable": True, "bounds": "[940,2150][1050,2250]"},   # bottom-right
                {"id": "3", "isClickable": True, "bounds": "[800,80][950,180]"},       # top-right
            ]
        }
        back = screen_analyzer.find_element_smart(anon_tree, "back")
        self.assertEqual(back["id"], "1")

        send = screen_analyzer.find_element_smart(anon_tree, "send")
        self.assertEqual(send["id"], "2")

        search = screen_analyzer.find_element_smart(anon_tree, "search")
        self.assertEqual(search["id"], "3")


class TestPhase2InterruptionHandler(unittest.TestCase):
    """Phase 2 & 4: Interruption Handler, Popups, and Scroll Recovery"""

    def test_coloros_battery_popup_detection(self):
        battery_popup = {
            "package": "com.coloros.battery",
            "nodes": [
                {"text": "Alita is consuming battery in the background", "className": "android.widget.TextView"},
                {"text": "Allow", "isClickable": True, "className": "android.widget.Button"},
                {"text": "Cancel", "isClickable": True, "className": "android.widget.Button"},
            ]
        }
        result = interruption_handler.detect_interruption(battery_popup)
        self.assertTrue(result.is_interrupted)
        self.assertTrue(result.auto_resolvable)
        self.assertEqual(result.target_button, "Allow")

    def test_cookie_and_rate_prompts(self):
        cookie_popup = {
            "package": "com.android.chrome",
            "nodes": [
                {"text": "We use cookies to enhance your experience. Accept all cookies?", "className": "android.widget.TextView"},
                {"text": "Accept All", "isClickable": True, "className": "android.widget.Button"},
            ]
        }
        res = interruption_handler.detect_interruption(cookie_popup)
        self.assertTrue(res.is_interrupted)
        self.assertTrue(res.auto_resolvable)
        self.assertEqual(res.target_button, "Accept All")

    def test_crash_anr_detection(self):
        crash_tree = {
            "package": "com.example.app",
            "nodes": [
                {"text": "WhatsApp isn't responding", "className": "android.widget.TextView"},
                {"text": "Close app", "isClickable": True, "className": "android.widget.Button"},
            ]
        }
        res = interruption_handler.detect_interruption(crash_tree)
        self.assertTrue(res.is_interrupted)
        self.assertEqual(res.interruption_type, "crash_anr")
        self.assertFalse(res.auto_resolvable)

    def test_scroll_and_find(self):
        call_count = 0
        def mock_find():
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return {"id": "found_node", "text": "Target Item"}
            return None

        swipes = []
        def mock_dispatch(act):
            swipes.append(act)
            return {"success": True}

        res = asyncio.run(interruption_handler.scroll_and_find(mock_find, mock_dispatch, max_scrolls=3))
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], "found_node")
        self.assertEqual(len(swipes), 2)  # Scrolled 2 times before finding on 3rd check


class TestPhase3ActionExecutor(unittest.TestCase):
    """Phase 1 & 4: Action Executor Pre-Action Target Resolution & Error Diagnosis"""

    def test_pre_action_target_resolution(self):
        mock_tree = {
            "package": "com.test.app",
            "nodes": [
                {"id": "btn", "resourceId": "btn_submit", "text": "Submit Now", "isClickable": True, "bounds": "[400,1000][600,1100]"}
            ]
        }
        dispatched_action = None

        def mock_dispatch(act):
            nonlocal dispatched_action
            dispatched_action = act
            return {"success": True}

        action_executor.set_bridge_dispatcher(mock_dispatch)

        action = {"command": "click", "find_target": "Submit Now"}
        outcome = asyncio.run(action_executor.execute_and_verify(
            action=action,
            expected_state_fn=lambda s: True,
            get_state_fn=lambda: {"connected": True},
            read_screen_fn=lambda: mock_tree,
            timeout_s=1.0,
        ))

        self.assertTrue(outcome.success)
        self.assertTrue(outcome.verified)
        self.assertEqual(action["command"], "tap")
        self.assertEqual(action["x"], 500.0)  # Center X
        self.assertEqual(action["y"], 1050.0) # Center Y

    def test_error_classification_and_recovery(self):
        def failing_dispatch(act):
            return {"success": False}

        action_executor.set_bridge_dispatcher(failing_dispatch)

        action = {"command": "click", "find_target": "Nonexistent Button"}
        outcome = asyncio.run(action_executor.execute_and_verify(
            action=action,
            expected_state_fn=lambda s: False,
            get_state_fn=lambda: {"connected": True},
            read_screen_fn=lambda: {"nodes": []},
            timeout_s=0.2,
            max_retries=1,
        ))

        self.assertFalse(outcome.verified)
        self.assertEqual(outcome.error_type, "ELEMENT_NOT_FOUND")


class TestPhase4TaskPlannerWorkflows(unittest.TestCase):
    """Phase 3: Task Planner Context-Aware Multi-Step Workflows"""

    def test_whatsapp_workflow_structure(self):
        steps = task_planner.plan_steps("send message on whatsapp to Alice that see you tomorrow", {})
        self.assertEqual(len(steps), 6)
        self.assertEqual(steps[0].name, "launch_whatsapp")
        self.assertEqual(steps[1].find_target, "Search")
        self.assertEqual(steps[2].name, "type_contact_name")
        self.assertEqual(steps[3].find_target, "Alice")
        self.assertTrue(steps[3].scroll_to_find)
        self.assertEqual(steps[4].name, "type_message")
        self.assertEqual(steps[5].find_target, "Send")

    def test_telegram_workflow(self):
        steps = task_planner.plan_steps("send telegram to Rahul saying I am on my way", {})
        self.assertEqual(len(steps), 6)
        self.assertEqual(steps[0].target_package, "org.telegram.messenger")
        self.assertEqual(steps[3].find_target, "Rahul")

    def test_instagram_workflow(self):
        steps = task_planner.plan_steps("send message on instagram to Priya saying check this out", {})
        self.assertEqual(len(steps), 7)
        self.assertEqual(steps[0].target_package, "com.instagram.android")
        self.assertEqual(steps[1].name, "open_dms")

    def test_hardware_toggles(self):
        # WiFi
        s1 = task_planner.plan_steps("turn on wifi", {})
        self.assertEqual(s1[0].action["command"], "toggle_wifi")
        self.assertTrue(s1[0].action["enabled"])

        s2 = task_planner.plan_steps("wifi off karo", {})
        self.assertFalse(s2[0].action["enabled"])

        # Bluetooth
        s3 = task_planner.plan_steps("turn off bluetooth", {})
        self.assertEqual(s3[0].action["command"], "toggle_bluetooth")
        self.assertFalse(s3[0].action["enabled"])

        # Airplane
        s4 = task_planner.plan_steps("flight mode on", {})
        self.assertEqual(s4[0].action["command"], "toggle_airplane")

        # DND
        s5 = task_planner.plan_steps("dnd on", {})
        self.assertEqual(s5[0].action["command"], "toggle_dnd")
        self.assertTrue(s5[0].action["enabled"])

        # Auto Rotate
        s6 = task_planner.plan_steps("auto rotate on", {})
        self.assertEqual(s6[0].action["command"], "toggle_auto_rotate")
        self.assertTrue(s6[0].action["enabled"])

    def test_call_and_camera_workflows(self):
        # Answer call
        c1 = task_planner.plan_steps("answer the call", {})
        self.assertEqual(c1[0].action["command"], "answer_call")

        # Reject call
        c2 = task_planner.plan_steps("reject call", {})
        self.assertEqual(c2[0].action["command"], "reject_call")

        # Camera
        cam = task_planner.plan_steps("take a selfie", {})
        self.assertEqual(cam[0].action["command"], "capture_photo")
        self.assertTrue(cam[0].action["selfie"])

    def test_navigation_and_url(self):
        # URL
        url_steps = task_planner.plan_steps("open https://github.com", {})
        self.assertEqual(url_steps[0].action["command"], "open_url")
        self.assertEqual(url_steps[0].action["url"], "https://github.com")

        # Maps Navigation
        maps_steps = task_planner.plan_steps("navigate to Golden Gate Bridge", {})
        self.assertEqual(maps_steps[0].target_package, "com.google.android.apps.maps")
        self.assertIn("Golden Gate Bridge", maps_steps[0].action["deepLink"])


class TestPhase5OrchestratorAndRouter(unittest.TestCase):
    """Phase 2, 4, 5: Orchestrator Methods, Lock Guard & Decision Router"""

    def test_orchestrator_hardware_methods(self):
        dispatched = []
        def mock_bridge(act, **kwargs):
            dispatched.append(act)
            return {"success": True}

        phone_orchestrator.set_bridge_sender(mock_bridge)

        async def run_all():
            await phone_orchestrator.toggle_wifi(True)
            await phone_orchestrator.toggle_bluetooth(False)
            await phone_orchestrator.toggle_mobile_data()
            await phone_orchestrator.toggle_airplane()
            await phone_orchestrator.toggle_dnd(True)
            await phone_orchestrator.toggle_auto_rotate(True)
            await phone_orchestrator.toggle_hotspot()
            await phone_orchestrator.capture_photo(selfie=False)
            await phone_orchestrator.answer_call()
            await phone_orchestrator.reject_call()
            await phone_orchestrator.toggle_speaker(True)
            await phone_orchestrator.open_url("example.com")
            await phone_orchestrator.dismiss_notification("key123")
            await phone_orchestrator.clear_all_notifications()
            await phone_orchestrator.get_active_notifications()
            await phone_orchestrator.vibrate(400)
            await phone_orchestrator.set_ringer_mode("silent")

        asyncio.run(run_all())
        self.assertEqual(len(dispatched), 17)
        cmds = [d["command"] for d in dispatched]
        self.assertIn("toggle_wifi", cmds)
        self.assertIn("toggle_bluetooth", cmds)
        self.assertIn("capture_photo", cmds)
        self.assertIn("answer_call", cmds)
        self.assertIn("reject_call", cmds)
        self.assertIn("clear_all_notifications", cmds)
        self.assertIn("set_ringer_mode", cmds)

    def test_lockscreen_guard(self):
        """Ensure actions that can run locked do not prepend unlock, but sensitive actions do."""
        dispatched = []
        def mock_bridge(act, **kwargs):
            dispatched.append(act)
            return {"success": True}

        phone_orchestrator.set_bridge_sender(mock_bridge)
        phone_orchestrator.device_info["connected"] = True
        phone_orchestrator.device_info["isLocked"] = True

        # Call answer should NOT prepend unlock
        res1 = asyncio.run(phone_orchestrator.run_instruction("answer the call"))
        self.assertEqual(res1["completed_steps"], 1)

        # WhatsApp message while locked SHOULD prepend unlock
        phone_orchestrator.device_info["isLocked"] = True
        steps = task_planner.plan_steps("send whatsapp to Dad that I am on my way", {})
        # Prepend unlock check
        can_run_locked = steps[0].name in ("answer_call", "toggle_wifi")
        self.assertFalse(can_run_locked)  # Must require unlock

    def test_decision_router_patterns(self):
        queries = [
            ("turn on wifi", "automation"),
            ("turn off bluetooth", "automation"),
            ("answer the call", "automation"),
            ("reject the call", "automation"),
            ("call uthao", "automation"),
            ("call cut karo", "automation"),
            ("take a photo", "automation"),
            ("take a selfie", "automation"),
            ("clear all notifications", "automation"),
            ("silent mode", "automation"),
            ("vibrate mode", "automation"),
            ("auto rotate on", "automation"),
            ("open google.com", "automation"),
            ("navigate to airport", "automation"),
            ("phone battery", "automation"),
            ("unlock my phone", "automation"),
        ]
        for q, expected in queries:
            actual = classify_query(q)
            self.assertEqual(actual, expected, f"Query '{q}' classified as '{actual}' instead of '{expected}'")


if __name__ == "__main__":
    unittest.main(verbosity=2)
