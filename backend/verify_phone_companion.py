"""
verify_phone_companion.py — Comprehensive Test Suite for Alita Phone Companion

Validates:
1. Android companion project structure, manifest, services, and configs.
2. FastAPI phone router routes (/api/phone/* and /ws/phone).
3. Live WebSocket bridge connection, handshake, and telemetry.
4. Intercepted notifications stream and Zero-Screen RemoteInput replies.
5. Bidirectional command execution and future resolution.
6. View-tree parsing and fuzzy element targeting.
7. High-level autonomous mobile workflows (Unlock, WhatsApp, Instagram).
8. Natural language instruction parser and routing.
"""

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path
from typing import Any, Dict

# Ensure backend root is in sys.path
backend_dir = Path(__file__).parent.resolve()
workspace_dir = backend_dir.parent.resolve()
sys.path.insert(0, str(backend_dir))

from starlette.testclient import TestClient


class TestPhoneCompanion(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        from main import app
        cls.app = app
        cls.client = TestClient(app)
        from engines.phone_orchestrator import PhoneOrchestrator, phone_orchestrator
        from routers.phone_router import bridge_manager
        cls.orchestrator = phone_orchestrator
        cls.bridge_manager = bridge_manager

    # ─────────────────────────────────────────────────────────────────────────
    # 1. Android Native Project Structure & Code Verification
    # ─────────────────────────────────────────────────────────────────────────
    def test_01_android_project_files_exist(self):
        android_dir = workspace_dir / "android_companion"
        required_files = [
            android_dir / "settings.gradle.kts",
            android_dir / "build.gradle.kts",
            android_dir / "gradle.properties",
            android_dir / "gradle" / "wrapper" / "gradle-wrapper.properties",
            android_dir / "app" / "build.gradle.kts",
            android_dir / "app" / "src" / "main" / "AndroidManifest.xml",
            android_dir / "app" / "src" / "main" / "res" / "xml" / "accessibility_service_config.xml",
            android_dir / "app" / "src" / "main" / "res" / "values" / "strings.xml",
            android_dir / "app" / "src" / "main" / "res" / "values" / "colors.xml",
            android_dir / "app" / "src" / "main" / "res" / "values" / "themes.xml",
            android_dir / "app" / "src" / "main" / "res" / "layout" / "activity_main.xml",
            android_dir / "app" / "src" / "main" / "res" / "drawable" / "bg_status_pill.xml",
            android_dir / "app" / "src" / "main" / "java" / "ai" / "alita" / "companion" / "AlitaAccessibilityService.kt",
            android_dir / "app" / "src" / "main" / "java" / "ai" / "alita" / "companion" / "AlitaNotificationListener.kt",
            android_dir / "app" / "src" / "main" / "java" / "ai" / "alita" / "companion" / "AlitaPhoneBridgeService.kt",
            android_dir / "app" / "src" / "main" / "java" / "ai" / "alita" / "companion" / "MainActivity.kt",
        ]

        for path in required_files:
            self.assertTrue(path.exists(), f"Missing required Android file: {path}")
            self.assertGreater(path.stat().st_size, 20, f"File appears empty: {path}")

    def test_02_android_manifest_and_permissions(self):
        manifest_path = workspace_dir / "android_companion" / "app" / "src" / "main" / "AndroidManifest.xml"
        content = manifest_path.read_text(encoding="utf-8")

        self.assertIn("android.permission.INTERNET", content)
        self.assertIn("BIND_ACCESSIBILITY_SERVICE", content)
        self.assertIn("BIND_NOTIFICATION_LISTENER_SERVICE", content)
        self.assertIn("AlitaAccessibilityService", content)
        self.assertIn("AlitaNotificationListener", content)
        self.assertIn("AlitaPhoneBridgeService", content)
        self.assertIn("MainActivity", content)
        self.assertIn("FOREGROUND_SERVICE", content)

    def test_03_accessibility_config(self):
        config_path = workspace_dir / "android_companion" / "app" / "src" / "main" / "res" / "xml" / "accessibility_service_config.xml"
        content = config_path.read_text(encoding="utf-8")

        self.assertIn('android:canPerformGestures="true"', content)
        self.assertIn('android:canRetrieveWindowContent="true"', content)
        self.assertIn("flagRetrieveInteractiveWindows", content)

    # ─────────────────────────────────────────────────────────────────────────
    # 2. FastAPI Phone Routes Registration
    # ─────────────────────────────────────────────────────────────────────────
    def test_04_phone_routes_registered_on_fastapi(self):
        paths = set(self.app.openapi().get("paths", {}).keys())
        for r in self.app.routes:
            if hasattr(r, "path") and r.path:
                paths.add(r.path)
            if hasattr(r, "original_router"):
                for sr in getattr(r.original_router, "routes", []):
                    if hasattr(sr, "path"):
                        paths.add(sr.path)
        self.assertIn("/api/phone/status", paths)
        self.assertIn("/api/phone/command", paths)
        self.assertIn("/api/phone/reply", paths)
        self.assertIn("/api/phone/view-tree", paths)
        self.assertIn("/api/phone/execute-task", paths)
        self.assertIn("/ws/phone", paths)

    def test_05_phone_status_initial_offline(self):
        res = self.client.get("/api/phone/status")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("status", data)
        self.assertIn("device", data)
        self.assertIn("recentNotifications", data)

    # ─────────────────────────────────────────────────────────────────────────
    # 3. WebSocket Handshake & Telemetry Simulation
    # ─────────────────────────────────────────────────────────────────────────
    def test_06_websocket_handshake_and_telemetry(self):
        with self.client.websocket_connect("/ws/phone") as ws:
            # 1. Send Handshake
            handshake = {
                "type": "handshake",
                "deviceModel": "Google Pixel 8 Pro",
                "androidVersion": "14",
                "sdkVersion": 34,
                "accessibilityActive": True,
                "notificationListenerActive": True,
                "batteryPercent": 85,
                "isCharging": False,
            }
            ws.send_text(json.dumps(handshake))

            # Query status via REST API
            res = self.client.get("/api/phone/status")
            self.assertEqual(res.status_code, 200)
            status_data = res.json()
            self.assertEqual(status_data["status"], "online")
            self.assertEqual(status_data["device"]["deviceModel"], "Google Pixel 8 Pro")
            self.assertEqual(status_data["device"]["batteryPercent"], 85)
            self.assertTrue(status_data["device"]["accessibilityActive"])

            # 2. Send Telemetry update
            telemetry = {
                "type": "telemetry",
                "batteryPercent": 84,
                "isCharging": True,
                "isScreenOn": True,
                "currentPackage": "com.whatsapp",
                "accessibilityActive": True,
                "notificationListenerActive": True,
            }
            ws.send_text(json.dumps(telemetry))

            res2 = self.client.get("/api/phone/status")
            d2 = res2.json()["device"]
            self.assertEqual(d2["batteryPercent"], 84)
            self.assertTrue(d2["isCharging"])
            self.assertEqual(d2["currentPackage"], "com.whatsapp")

            # 3. Intercept Notification
            notif = {
                "type": "phone_notification",
                "key": "0|com.whatsapp|101|Sarah|10001",
                "package": "com.whatsapp",
                "title": "Sarah",
                "text": "Hey! Are you still joining for the meet?",
                "timestamp": 1725440000000,
                "canReply": True,
            }
            ws.send_text(json.dumps(notif))
            time.sleep(0.05)

            res3 = self.client.get("/api/phone/status")
            notifs = res3.json()["recentNotifications"]
            self.assertTrue(any(n["title"] == "Sarah" for n in notifs))

    # ─────────────────────────────────────────────────────────────────────────
    # 4. Bridge Manager Command Dispatch & Resolution
    # ─────────────────────────────────────────────────────────────────────────
    def test_07_bridge_manager_command_and_future_resolution(self):
        class MockWebSocket:
            def __init__(self, bridge):
                self.bridge = bridge

            async def send_text(self, text: str):
                data = json.loads(text)
                cmd_id = data["id"]
                # Immediately resolve future via bridge
                asyncio.get_event_loop().call_soon(
                    self.bridge.resolve_command,
                    cmd_id,
                    {"type": "command_result", "id": cmd_id, "success": True, "echo": data.get("command")}
                )

        mock_ws = MockWebSocket(self.bridge_manager)
        self.bridge_manager.active_socket = mock_ws
        self.orchestrator.device_info["connected"] = True

        async def run_test():
            result = await self.bridge_manager.send_command({"command": "tap", "x": 100, "y": 200})
            self.assertTrue(result.get("success"))
            self.assertEqual(result.get("echo"), "tap")

        asyncio.run(run_test())

    # ─────────────────────────────────────────────────────────────────────────
    # 5. View-Tree Parsing & Fuzzy Element Matching
    # ─────────────────────────────────────────────────────────────────────────
    def test_08_view_tree_parsing_and_fuzzy_search(self):
        sample_tree = {
            "package": "com.instagram.android",
            "nodeCount": 4,
            "nodes": [
                {
                    "id": "com.instagram.android:id/action_bar_button_back",
                    "text": None,
                    "contentDesc": "Back",
                    "isClickable": True,
                    "bounds": {"left": 20, "top": 40, "right": 80, "bottom": 100, "cx": 50, "cy": 70},
                },
                {
                    "id": "com.instagram.android:id/row_feed_button_like",
                    "text": None,
                    "contentDesc": "Like",
                    "isClickable": True,
                    "bounds": {"left": 40, "top": 600, "right": 100, "bottom": 660, "cx": 70, "cy": 630},
                },
                {
                    "id": "com.instagram.android:id/row_feed_button_comment",
                    "text": None,
                    "contentDesc": "Comment",
                    "isClickable": True,
                    "bounds": {"left": 120, "top": 600, "right": 180, "bottom": 660, "cx": 150, "cy": 630},
                },
                {
                    "id": "com.instagram.android:id/profile_tab",
                    "text": "Profile",
                    "contentDesc": "Profile tab",
                    "isClickable": True,
                    "bounds": {"left": 400, "top": 900, "right": 480, "bottom": 960, "cx": 440, "cy": 930},
                },
            ],
        }

        # Fuzzy match by text
        profile_node = self.orchestrator.find_node(sample_tree, query="Profile")
        self.assertIsNotNone(profile_node)
        self.assertEqual(profile_node["bounds"]["cx"], 440)

        # Fuzzy match by contentDesc
        like_node = self.orchestrator.find_node(sample_tree, query="Like")
        self.assertIsNotNone(like_node)
        self.assertEqual(like_node["bounds"]["cx"], 70)

        # Fuzzy match by resource ID substring
        comment_node = self.orchestrator.find_node(sample_tree, resource_id="button_comment")
        self.assertIsNotNone(comment_node)
        self.assertEqual(comment_node["bounds"]["cx"], 150)

    # ─────────────────────────────────────────────────────────────────────────
    # 6. Autonomous Mobile Workflows (Unlock, WhatsApp, Instagram)
    # ─────────────────────────────────────────────────────────────────────────
    def test_09_autonomous_unlock_workflow(self):
        async def mock_sender(cmd_dict: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
            cmd = cmd_dict.get("command")
            if cmd in ("unlock", "unlock_screen"):
                return {"type": "command_result", "id": cmd_dict.get("id"), "success": True, "verifiedUnlocked": True, "isLocked": False, "currentPackage": "com.google.android.apps.nexuslauncher"}
            elif cmd == "dump_tree":
                return {
                    "success": True,
                    "data": {
                        "package": "com.google.android.apps.nexuslauncher",
                        "nodes": [{"text": "Clock", "bounds": {"cx": 500, "cy": 200}}],
                    },
                }
            elif cmd == "get_state":
                return {"success": True, "isLocked": False, "currentPackage": "com.google.android.apps.nexuslauncher"}
            return {"success": True}

        self.orchestrator.set_bridge_sender(mock_sender)
        self.orchestrator.device_info["connected"] = True

        async def run_unlock():
            res = await self.orchestrator.unlock_screen(pin="1234")
            self.assertTrue(res["success"])
            self.assertTrue(res["screenUnlocked"])
            self.assertIn("nexuslauncher", res["currentPackage"])

        asyncio.run(run_unlock())

    def test_10_zero_screen_message_fast_path(self):
        # Register a notification from Mom
        self.orchestrator.recent_notifications = [
            {
                "key": "notif_whatsapp_mom_99",
                "package": "com.whatsapp",
                "title": "Mom",
                "text": "Are you joining dinner?",
                "canReply": True,
            }
        ]

        dispatched_cmds = []

        async def mock_sender(cmd_dict: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
            dispatched_cmds.append(cmd_dict)
            return {"type": "command_result", "id": cmd_dict["id"], "success": True}

        self.orchestrator.set_bridge_sender(mock_sender)
        self.orchestrator.device_info["connected"] = True

        async def run_msg():
            res = await self.orchestrator.send_message_autonomous("Mom", "Yes, see you in 15 mins!")
            self.assertTrue(res["success"])
            self.assertEqual(res["method"], "zero_screen_notification_reply")
            self.assertEqual(res["recipient"], "Mom")

            # Assert direct_reply command was dispatched with RemoteInput key
            self.assertEqual(len(dispatched_cmds), 1)
            self.assertEqual(dispatched_cmds[0]["command"], "direct_reply")
            self.assertEqual(dispatched_cmds[0]["notificationKey"], "notif_whatsapp_mom_99")
            self.assertEqual(dispatched_cmds[0]["text"], "Yes, see you in 15 mins!")

        asyncio.run(run_msg())

    def test_11_social_media_action_workflow(self):
        dispatched_cmds = []

        async def mock_sender(cmd_dict: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
            dispatched_cmds.append(cmd_dict)
            cmd = cmd_dict.get("command")
            if cmd == "dump_tree":
                return {
                    "success": True,
                    "data": {
                        "package": "com.instagram.android",
                        "nodes": [
                            {
                                "id": "row_feed_button_like",
                                "contentDesc": "Like",
                                "isClickable": True,
                                "bounds": {"cx": 90, "cy": 720},
                            }
                        ],
                    },
                }
            return {"success": True}

        self.orchestrator.set_bridge_sender(mock_sender)
        self.orchestrator.device_info["connected"] = True

        async def run_insta():
            res = await self.orchestrator.social_media_action("instagram", "like")
            self.assertTrue(res["success"])
            self.assertEqual(res["action"], "like")
            # Verify tap at cx: 90, cy: 720 was dispatched
            tap_cmd = next((c for c in dispatched_cmds if c.get("command") == "tap"), None)
            self.assertIsNotNone(tap_cmd)
            self.assertEqual(tap_cmd["x"], 90)
            self.assertEqual(tap_cmd["y"], 720)

        asyncio.run(run_insta())

    def test_12_natural_language_task_parser(self):
        parsed_actions = []

        async def mock_sender(cmd_dict: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
            parsed_actions.append(cmd_dict.get("command"))
            if cmd_dict.get("command") == "dump_tree":
                return {"success": True, "data": {"package": "com.test", "nodes": []}}
            return {"success": True}

        self.orchestrator.set_bridge_sender(mock_sender)
        self.orchestrator.device_info["connected"] = True

        async def run_nlp():
            # 1. Home
            await self.orchestrator.execute_natural_task("Go to home screen")
            self.assertIn("global", parsed_actions)

            # 2. Recents
            await self.orchestrator.execute_natural_task("Open recent apps")
            self.assertIn("global", parsed_actions)

            # 3. Unlock with PIN
            self.orchestrator.device_info["isLocked"] = True
            await self.orchestrator.execute_natural_task("Unlock my phone with pin 9876")
            self.assertTrue("unlock_screen" in parsed_actions or "unlock" in parsed_actions)

            # 4. Launch App
            await self.orchestrator.execute_natural_task("Open Camera")
            self.assertIn("launch_app", parsed_actions)

        asyncio.run(run_nlp())


if __name__ == "__main__":
    unittest.main()
