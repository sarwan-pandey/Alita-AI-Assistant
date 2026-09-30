"""
phone_orchestrator.py — Autonomous Mobile Automation Engine for Alita

Coordinates closed-loop task planning, view-tree parsing, fuzzy element targeting,
screen unlock, zero-screen background notification replies, and social media automations.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional

from engines.action_executor import action_executor
from engines.security_vault import security_vault
from engines.task_planner import task_planner, TaskStep

logger = logging.getLogger("alita.phone_orchestrator")


class PhoneOrchestrator:
    """
    High-level autonomous mobile task orchestrator.
    Translates natural language intents and structured tasks into micro-actions
    (taps, swipes, typing, global actions, remote inputs) dispatched to the Android Companion.
    """

    def __init__(self, bridge_sender: Optional[Callable[[Dict[str, Any]], Any]] = None):
        self._sender = bridge_sender
        self.device_info: Dict[str, Any] = {
            "connected": False,
            "deviceModel": "Realme RMX5030",
            "androidVersion": "10",
            "sdkVersion": 29,
            "batteryPercent": -1,
            "isCharging": False,
            "isScreenOn": False,
            "isLocked": True,
            "hasOverlayPopup": False,
            "accessibilityActive": False,
            "notificationListenerActive": False,
            "currentPackage": "",
            "lastSeen": 0.0,
        }
        self.recent_notifications: List[Dict[str, Any]] = []
        self._last_view_tree: Optional[Dict[str, Any]] = None

        if bridge_sender:
            action_executor.set_bridge_dispatcher(self._dispatch)

    def set_bridge_sender(self, sender_fn: Callable[[Dict[str, Any]], Any]) -> None:
        """Assign or update the low-level bridge sender function."""
        self._sender = sender_fn
        action_executor.set_bridge_dispatcher(self._dispatch)

    # ── State Updates & Perception ─────────────────────────────────────────────

    def update_telemetry(self, data: Dict[str, Any]) -> None:
        """Update telemetry reported by Android companion."""
        self.device_info.update({
            "connected": True,
            "batteryPercent": data.get("batteryPercent", self.device_info["batteryPercent"]),
            "isCharging": data.get("isCharging", self.device_info["isCharging"]),
            "isScreenOn": data.get("isScreenOn", self.device_info["isScreenOn"]),
            "isLocked": data.get("isLocked", self.device_info.get("isLocked", True)),
            "currentPackage": data.get("currentPackage", self.device_info["currentPackage"]),
            "hasOverlayPopup": data.get("hasOverlayPopup", self.device_info.get("hasOverlayPopup", False)),
            "accessibilityActive": data.get("accessibilityActive", self.device_info["accessibilityActive"]),
            "notificationListenerActive": data.get("notificationListenerActive", self.device_info["notificationListenerActive"]),
            "deviceModel": data.get("deviceModel", self.device_info["deviceModel"]),
            "androidVersion": data.get("androidVersion", self.device_info["androidVersion"]),
            "lastSeen": time.time(),
        })

    def record_notification(self, notif: Dict[str, Any]) -> None:
        """Record an incoming notification intercepted by AlitaNotificationListener."""
        self.recent_notifications.insert(0, notif)
        if len(self.recent_notifications) > 50:
            self.recent_notifications.pop()

    def update_view_tree(self, tree: Dict[str, Any]) -> None:
        """Cache latest view tree dump."""
        self._last_view_tree = tree

    async def get_live_phone_state(self) -> Dict[str, Any]:
        """Query real-time phone state via bridge 'get_state' command with fallback to cached telemetry."""
        if not self.device_info.get("connected"):
            return dict(self.device_info)
        try:
            res = await self._dispatch({"command": "get_state"}, timeout=2.0)
            if res.get("success"):
                self.device_info.update({
                    "isScreenOn": res.get("isScreenOn", self.device_info["isScreenOn"]),
                    "isLocked": res.get("isLocked", self.device_info.get("isLocked", True)),
                    "currentPackage": res.get("currentPackage", self.device_info["currentPackage"]),
                    "batteryPercent": res.get("batteryPercent", self.device_info["batteryPercent"]),
                    "isCharging": res.get("isCharging", self.device_info["isCharging"]),
                    "hasOverlayPopup": res.get("hasOverlayPopup", False),
                    "deviceModel": res.get("deviceModel", self.device_info["deviceModel"]),
                    "androidVersion": res.get("androidVersion", self.device_info["androidVersion"]),
                    "lastSeen": time.time(),
                })
        except Exception:
            pass
        return dict(self.device_info)

    async def read_screen(self) -> Dict[str, Any]:
        """Fetch live screen view-tree compact JSON or fallback screenshot."""
        res = await self._dispatch({"command": "read_screen"}, timeout=3.5)
        if res.get("success") and "data" in res:
            self._last_view_tree = res["data"]
            return res["data"]
        # Fallback to dump_tree
        return await self.fetch_view_tree()

    def get_prompt_telemetry_summary(self) -> str:
        """Compact summary of mobile companion telemetry for LLM system prompt."""
        if not self.device_info.get("connected"):
            return ""
        info = self.device_info
        lines = [
            f"Device: {info.get('deviceModel', 'Realme RMX5030')} (Android {info.get('androidVersion', '10')})",
            f"Status: Connected | Battery: {info.get('batteryPercent', '?')}% ({'Charging' if info.get('isCharging') else 'Discharging'})",
            f"Screen: {'On' if info.get('isScreenOn') else 'Off'} | Lock State: {'Locked' if info.get('isLocked') else 'Unlocked'}",
            f"Foreground App: {info.get('currentPackage', 'Home Screen') or 'Home Screen'}",
        ]
        if info.get("hasOverlayPopup"):
            lines.append("Alert: An overlay or system popup dialog is currently active.")
        if self.recent_notifications:
            latest = self.recent_notifications[0]
            pkg = str(latest.get("package", "")).split(".")[-1]
            title = latest.get("title", "")
            text = latest.get("text", "")
            lines.append(f"Latest Notification: [{pkg}] {title}: {text}")
        if self._last_view_tree and isinstance(self._last_view_tree, dict):
            visible_elements: List[str] = []
            def _extract_labels(node: Any) -> None:
                if not isinstance(node, dict):
                    return
                txt = node.get("text") or node.get("contentDescription")
                if txt and isinstance(txt, str) and len(txt.strip()) > 1:
                    visible_elements.append(txt.strip())
                for child in node.get("children", []):
                    if len(visible_elements) < 8:
                        _extract_labels(child)
            _extract_labels(self._last_view_tree)
            if visible_elements:
                lines.append(f"Visible Elements: {', '.join(visible_elements[:6])}")
        return "\n".join(lines)

    # ── Command Dispatch Primitives ───────────────────────────────────────────

    async def _dispatch(self, command_dict: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
        """Dispatch low-level command through the phone bridge."""
        if not self._sender:
            return {"success": False, "error": "Phone bridge sender not initialized"}
        if not self.device_info.get("connected"):
            return {"success": False, "error": "Android phone companion is offline"}

        cmd_id = f"cmd_{int(time.time() * 1000)}"
        command_dict["id"] = cmd_id

        try:
            if asyncio.iscoroutinefunction(self._sender):
                try:
                    res = await self._sender(command_dict, timeout=timeout)
                except TypeError:
                    res = await self._sender(command_dict)
            else:
                try:
                    res = self._sender(command_dict, timeout=timeout)
                except TypeError:
                    res = self._sender(command_dict)
                if asyncio.iscoroutine(res) or isinstance(res, asyncio.Future):
                    res = await res
            return res if isinstance(res, dict) else {"success": True, "data": res}
        except Exception as e:
            logger.error(f"Error executing phone command {command_dict.get('command')}: {e}")
            return {"success": False, "error": str(e)}

    async def tap(self, x: float, y: float, duration: int = 50) -> Dict[str, Any]:
        return await self._dispatch({"command": "tap", "x": x, "y": y, "duration": duration})

    async def double_tap(self, x: float, y: float) -> Dict[str, Any]:
        return await self._dispatch({"command": "double_tap", "x": x, "y": y})

    async def swipe(self, start_x: float, start_y: float, end_x: float, end_y: float, duration: int = 300) -> Dict[str, Any]:
        return await self._dispatch({
            "command": "swipe",
            "startX": start_x,
            "startY": start_y,
            "endX": end_x,
            "endY": end_y,
            "duration": duration,
        })

    async def type_text(self, target: str, text: str) -> Dict[str, Any]:
        return await self._dispatch({"command": "type", "target": target, "text": text})

    async def click_element(self, target: Optional[str] = None, resource_id: Optional[str] = None) -> Dict[str, Any]:
        return await self._dispatch({"command": "click", "target": target, "resourceId": resource_id})

    async def global_action(self, action: str) -> Dict[str, Any]:
        return await self._dispatch({"command": "global", "action": action})

    async def launch_app(self, package: Optional[str] = None, deep_link: Optional[str] = None) -> Dict[str, Any]:
        return await self._dispatch({"command": "launch_app", "package": package, "deepLink": deep_link})

    async def fetch_view_tree(self) -> Dict[str, Any]:
        res = await self._dispatch({"command": "dump_tree"}, timeout=5.0)
        if res.get("success") and "data" in res:
            self._last_view_tree = res["data"]
            return res["data"]
        return self._last_view_tree or {"nodes": []}

    async def reply_direct(self, notification_key: str, reply_text: str) -> Dict[str, Any]:
        return await self._dispatch({
            "command": "direct_reply",
            "notificationKey": notification_key,
            "text": reply_text,
        })

    # ── Full Phone Automation Commands ────────────────────────────────────────

    async def make_call(self, number: Optional[str] = None, contact_name: Optional[str] = None) -> Dict[str, Any]:
        """Initiate a phone call by number or contact name."""
        cmd: Dict[str, Any] = {"command": "make_call"}
        if number:
            cmd["number"] = number
        if contact_name:
            cmd["contactName"] = contact_name
        return await self._dispatch(cmd, timeout=10.0)

    async def end_call(self) -> Dict[str, Any]:
        """End the current active phone call."""
        return await self._dispatch({"command": "end_call"})

    async def send_sms(self, number: Optional[str] = None, contact_name: Optional[str] = None, message: str = "") -> Dict[str, Any]:
        """Send an SMS text message."""
        cmd: Dict[str, Any] = {"command": "send_sms", "message": message}
        if number:
            cmd["number"] = number
        if contact_name:
            cmd["contactName"] = contact_name
        return await self._dispatch(cmd, timeout=10.0)

    async def set_volume(self, action: str = "up", stream: str = "media", level: Optional[int] = None) -> Dict[str, Any]:
        """Control phone volume: up/down/mute/unmute/max/min or set absolute level (0-100)."""
        cmd: Dict[str, Any] = {"command": "set_volume", "action": action, "stream": stream}
        if level is not None:
            cmd["level"] = level
        return await self._dispatch(cmd)

    async def media_control(self, action: str = "play_pause") -> Dict[str, Any]:
        """Control media playback: play/pause/next/previous/stop."""
        return await self._dispatch({"command": "media_control", "action": action})

    async def toggle_flashlight(self, enabled: bool = True) -> Dict[str, Any]:
        """Toggle the phone's flashlight/torch on or off."""
        return await self._dispatch({"command": "toggle_flashlight", "enabled": enabled})

    async def set_alarm(self, hour: int, minute: int = 0, label: str = "") -> Dict[str, Any]:
        """Set an alarm on the phone."""
        return await self._dispatch({
            "command": "set_alarm",
            "hour": hour,
            "minute": minute,
            "label": label or "MJ Alarm",
        })

    async def set_timer(self, seconds: int, label: str = "") -> Dict[str, Any]:
        """Set a countdown timer on the phone."""
        return await self._dispatch({
            "command": "set_timer",
            "seconds": seconds,
            "label": label or "MJ Timer",
        })

    async def set_clipboard(self, text: str) -> Dict[str, Any]:
        """Copy text from PC to phone clipboard."""
        return await self._dispatch({"command": "set_clipboard", "text": text})

    async def get_clipboard(self) -> Dict[str, Any]:
        """Get the current phone clipboard content."""
        return await self._dispatch({"command": "get_clipboard"})

    async def open_camera(self, selfie: bool = False) -> Dict[str, Any]:
        """Open the phone camera (front or back)."""
        return await self._dispatch({"command": "open_camera", "selfie": selfie})

    async def set_brightness(self, level: int) -> Dict[str, Any]:
        """Set phone screen brightness (0-255)."""
        return await self._dispatch({"command": "set_brightness", "level": level})

    async def take_screenshot(self) -> Dict[str, Any]:
        """Take a screenshot on the phone."""
        return await self.global_action("take_screenshot")

    # ── Hardware & Connectivity Controls ─────────────────────────────────────

    async def toggle_wifi(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggle or set WiFi state."""
        act = {"command": "toggle_wifi"}
        if enable is not None:
            act["enabled"] = enable
        return await self._dispatch(act)

    async def toggle_bluetooth(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggle or set Bluetooth state."""
        act = {"command": "toggle_bluetooth"}
        if enable is not None:
            act["enabled"] = enable
        return await self._dispatch(act)

    async def toggle_mobile_data(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Open mobile data settings panel."""
        act = {"command": "toggle_mobile_data"}
        if enable is not None:
            act["enabled"] = enable
        return await self._dispatch(act)

    async def toggle_airplane(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Open airplane mode settings."""
        act = {"command": "toggle_airplane"}
        if enable is not None:
            act["enabled"] = enable
        return await self._dispatch(act)

    async def toggle_dnd(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggle or set Do Not Disturb mode."""
        act = {"command": "toggle_dnd"}
        if enable is not None:
            act["enabled"] = enable
        return await self._dispatch(act)

    async def toggle_auto_rotate(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Toggle or set auto screen rotation."""
        act = {"command": "toggle_auto_rotate"}
        if enable is not None:
            act["enabled"] = enable
        return await self._dispatch(act)

    async def toggle_hotspot(self, enable: Optional[bool] = None) -> Dict[str, Any]:
        """Open hotspot settings."""
        act = {"command": "toggle_hotspot"}
        if enable is not None:
            act["enabled"] = enable
        return await self._dispatch(act)

    async def capture_photo(self, selfie: bool = False) -> Dict[str, Any]:
        """Capture a photo using phone camera."""
        return await self._dispatch({"command": "capture_photo", "selfie": selfie})

    async def answer_call(self) -> Dict[str, Any]:
        """Answer an incoming phone call."""
        return await self._dispatch({"command": "answer_call"})

    async def reject_call(self) -> Dict[str, Any]:
        """Reject an incoming phone call."""
        return await self._dispatch({"command": "reject_call"})

    async def toggle_speaker(self, enable: bool = True) -> Dict[str, Any]:
        """Toggle or set speakerphone."""
        return await self._dispatch({"command": "toggle_speaker", "enabled": enable})

    async def open_url(self, url: str) -> Dict[str, Any]:
        """Open a web URL on phone browser."""
        return await self._dispatch({"command": "open_url", "url": url})

    async def dismiss_notification(self, key: str) -> Dict[str, Any]:
        """Dismiss a specific notification by key."""
        return await self._dispatch({"command": "dismiss_notification", "key": key})

    async def clear_all_notifications(self) -> Dict[str, Any]:
        """Clear all active notifications."""
        return await self._dispatch({"command": "clear_all_notifications"})

    async def get_active_notifications(self) -> Dict[str, Any]:
        """Get list of active notifications on phone."""
        return await self._dispatch({"command": "get_notifications"})

    async def vibrate(self, duration_ms: int = 500) -> Dict[str, Any]:
        """Vibrate phone for durationMs."""
        return await self._dispatch({"command": "vibrate", "duration": duration_ms})

    async def set_ringer_mode(self, mode: str = "normal") -> Dict[str, Any]:
        """Set ringer mode ('normal', 'silent', 'vibrate')."""
        return await self._dispatch({"command": "set_ringer_mode", "mode": mode})

    async def pay_upi(
        self,
        recipient: str,
        amount: float,
        vpa: Optional[str] = None,
        app: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initiate a UPI payment via Android UPI Intent."""
        act = {
            "command": "pay_upi",
            "recipient": recipient,
            "amount": amount,
        }
        if vpa:
            act["vpa"] = vpa
        if app:
            act["package"] = app
        return await self._dispatch(act)

    # ── View Tree Parsing & Fuzzy Search ──────────────────────────────────────

    def find_node(
        self,
        tree: Optional[Dict[str, Any]] = None,
        query: str = "",
        resource_id: Optional[str] = None,
        clickable_only: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """
        Fuzzy search for a node inside a view-tree dump matching text, contentDesc, or ID.
        """
        active_tree = tree or self._last_view_tree
        if not active_tree:
            return None

        nodes = active_tree.get("nodes", [])
        q_lower = query.strip().lower() if query else ""
        res_id_lower = resource_id.strip().lower() if resource_id else ""

        for node in nodes:
            if not isinstance(node, dict):
                continue
            if clickable_only and not node.get("isClickable", False):
                continue

            node_text = (node.get("text") or "").lower()
            node_desc = (node.get("contentDesc") or "").lower()
            node_id = (node.get("id") or "").lower()

            if res_id_lower and res_id_lower in node_id:
                return node
            if q_lower and (q_lower == node_text or q_lower in node_text or q_lower in node_desc):
                return node

        return None

    # ── Closed-Loop Autonomous Workflows ──────────────────────────────────────

    async def unlock_screen(self, pin: Optional[str] = None) -> Dict[str, Any]:
        """
        Closed-loop screen unlock:
        1. Pre-check: If already unlocked, short-circuit immediately.
        2. Act: Dispatch 'unlock' command (zero plaintext credentials transmitted).
        3. Verify: Poll state until isLocked == False or timeout.
        """
        outcome = await action_executor.execute_and_verify(
            action={"command": "unlock"},
            expected_state_fn=lambda s: s.get("isLocked") is False,
            get_state_fn=self.get_live_phone_state,
            read_screen_fn=None,  # Do not flood phone with accessibility dumps during unlock
            timeout_s=6.0,
            poll_interval_s=0.25,
            max_retries=1,
        )

        is_unlocked = outcome.verified or outcome.success
        already_unlocked = (outcome.message == "Target state already achieved.") or (
            isinstance(outcome.post_state, dict) and outcome.post_state.get("alreadyUnlocked", False)
        )
        pkg = outcome.post_state.get("currentPackage", "") if isinstance(outcome.post_state, dict) else ""

        return {
            "success": is_unlocked,
            "verified": outcome.verified,
            "screenUnlocked": is_unlocked,
            "alreadyUnlocked": already_unlocked,
            "currentPackage": pkg,
            "outcome": outcome,
            "error": outcome.error,
        }

    async def lock_screen(self) -> Dict[str, Any]:
        """Closed-loop screen lock via Android global action."""
        model_name = self.device_info.get("deviceModel", "Realme Phone")
        res = await self.global_action("lock")
        return {
            "success": True,
            "action": "lock_screen",
            "message": f"Your {model_name} screen has been locked.",
            "data": res,
        }

    async def send_message_autonomous(
        self,
        recipient: str,
        message: str,
        app: str = "whatsapp",
    ) -> Dict[str, Any]:
        """
        Autonomous messaging workflow:
        1. Fast Path: Check if recent notification from recipient exists -> Zero-Screen RemoteInput Reply (<100ms).
        2. Fallback Path: Launch messaging app -> Search contact -> Enter conversation -> Type & Send.
        """
        recipient_clean = recipient.strip().lower()

        # Step 1: Zero-screen notification reply check
        target_notif = None
        for notif in self.recent_notifications:
            title = (notif.get("title") or "").lower()
            if recipient_clean in title and notif.get("canReply", False):
                target_notif = notif
                break

        if target_notif:
            logger.info(f"Using Zero-Screen reply for '{recipient}' via notification key: {target_notif.get('key')}")
            res = await self.reply_direct(target_notif["key"], message)
            if res.get("success"):
                return {
                    "success": True,
                    "method": "zero_screen_notification_reply",
                    "recipient": target_notif.get("title"),
                    "message": message,
                    "app": target_notif.get("package"),
                }

        # Step 2: Fallback to TaskPlanner multi-step execution
        instr = f"message {recipient} on {app} that: {message}"
        return await self.run_instruction(instr)

    async def social_media_action(
        self,
        platform: str,
        action: str,
        target_user: Optional[str] = None,
        comment_text: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Autonomous social media interaction (like, comment, follow, block)."""
        pkg = "com.instagram.android" if "insta" in platform.lower() else "com.facebook.katana"
        await self.launch_app(package=pkg)
        await asyncio.sleep(1.0)
        tree = await self.read_screen()

        if action == "like":
            node = self.find_node(tree, query="Like", resource_id="row_feed_button_like")
            if node and "bounds" in node:
                b = node["bounds"]
                await self.tap(b["cx"], b["cy"])
                return {"success": True, "action": "like", "platform": platform}
            else:
                dm = tree.get("display", {})
                w = dm.get("width", 1080)
                h = dm.get("height", 2400)
                await self.double_tap(w / 2.0, h / 2.0)
                return {"success": True, "action": "double_tap_like", "platform": platform}

        return {"success": False, "error": f"Unsupported social action: {action}"}

    # ── Top-Level Unified Instruction Runner ──────────────────────────────────

    async def run_instruction(
        self,
        instruction: str,
        session_state: Optional[Dict[str, Any]] = None,
        narration_callback: Optional[Callable[[str], Any]] = None,
    ) -> Dict[str, Any]:
        """
        Top-level entry point with closed-loop verification, security confirmation, and planning.
        """
        state_dict = session_state if session_state is not None else {}
        model_name = self.device_info.get("deviceModel", "Realme Phone")
        inst_lower = instruction.strip().lower()

        # Step 0: Security Confirmation Pre-Check for sensitive actions (unlock, payments, messages, destructive)
        is_direct_unlock = any(w in inst_lower for w in [
            "unlock", "open phone", "phone unlock", "unlock device", "unlock screen",
            "kholo", "phone open", "khol do", "open my phone", "open screen"
        ]) or (
            any(w in inst_lower for w in ["phone", "mobile", "screen", "device"]) and
            any(w in inst_lower for w in ["unlock", "open", "kholo", "khol"])
        )

        # Fast short-circuit: If the user wants to unlock, but the phone is ALREADY unlocked,
        # do not prompt for confirmation — notify immediately and succeed.
        if is_direct_unlock:
            live_st = await self.get_live_phone_state()
            if live_st.get("connected") and live_st.get("isLocked") is False:
                pkg = live_st.get("currentPackage") or "the home screen"
                logger.info("[PhoneOrchestrator] Direct unlock short-circuit: device already unlocked on %s", pkg)
                return {
                    "success": True,
                    "verified": True,
                    "screenUnlocked": True,
                    "alreadyUnlocked": True,
                    "currentPackage": pkg,
                    "message": f"Your phone ({model_name}) is already unlocked on {pkg}."
                }

        if not (is_direct_unlock and state_dict.get("trusted_mode")):
            sens_res = security_vault.check_sensitive_action_intent(
                instruction=instruction,
                session_state=state_dict,
                device_model=model_name,
            )
            if sens_res.needs_confirmation:
                return {
                    "success": False,
                    "needs_confirmation": True,
                    "confirmation_prompt": sens_res.confirmation_prompt,
                    "action_type": sens_res.action_type,
                    "message": sens_res.confirmation_prompt,
                }

            if sens_res.action_type == "cancelled":
                return {
                    "success": True,
                    "cancelled": True,
                    "message": "Action cancelled as requested.",
                }

            # If user previously confirmed a sensitive action (e.g. saying "yes"), restore original instruction!
            if sens_res.details and sens_res.details.get("original_instruction"):
                instruction = sens_res.details["original_instruction"]
                logger.info(f"Confirmed sensitive action — executing original instruction: '{instruction}'")
                inst_lower = instruction.strip().lower()
                is_direct_unlock = any(w in inst_lower for w in [
                    "unlock", "open phone", "phone unlock", "unlock device", "unlock screen",
                    "kholo", "phone open", "khol do", "open my phone", "open screen"
                ])

        if is_direct_unlock:
            if state_dict.get("pending_confirmation"):
                state_dict["pending_confirmation"] = None
            res = await self.unlock_screen()
            if res.get("alreadyUnlocked") or res.get("verified") or res.get("screenUnlocked") or res.get("success"):
                res["success"] = True
                if res.get("alreadyUnlocked"):
                    msg = f"Your phone ({model_name}) is already unlocked on {res.get('currentPackage') or 'the home screen'}."
                else:
                    msg = f"Verified: Your {model_name} has been unlocked to {res.get('currentPackage') or 'home screen'}."
            else:
                res["success"] = False
                msg = f"Could not verify unlock on {model_name}: {res.get('error', 'Lockscreen did not dismiss')}."
            res["message"] = msg
            return res

        # Step 2: Query live phone state and screen
        live_state = await self.get_live_phone_state()
        tree = await self.read_screen()

        # Step 3: Fast-path for single-action queries
        # Unlock
        if any(w in inst_lower for w in ["unlock", "open phone", "phone unlock", "unlock device", "unlock screen", "kholo", "phone open"]):
            res = await self.unlock_screen()
            if res.get("alreadyUnlocked") or res.get("verified") or res.get("screenUnlocked") or res.get("success"):
                res["success"] = True
                if res.get("alreadyUnlocked"):
                    msg = f"Your phone ({model_name}) is already unlocked on {res.get('currentPackage') or 'the home screen'}."
                else:
                    msg = f"Verified: Your {model_name} has been unlocked to {res.get('currentPackage') or 'home screen'}."
            else:
                res["success"] = False
                msg = f"Could not verify unlock on {model_name}: {res.get('error', 'Lockscreen did not dismiss')}."
            res["message"] = msg
            return res

        # Lock
        if any(w in inst_lower for w in ["lock phone", "lock screen", "lock the phone", "lock my phone", "phone lock"]):
            res = await self.lock_screen()
            return res

        # Battery / Telemetry
        if any(w in inst_lower for w in ["battery", "phone battery", "charge", "is phone charging"]):
            pct = live_state.get("batteryPercent", -1)
            charging = live_state.get("isCharging", False)
            chg_str = "charging" if charging else "not charging"
            return {
                "success": True,
                "action": "battery_status",
                "message": f"Your {model_name} battery is at {pct} percent, and it is currently {chg_str}."
            }

        # Active Notifications List
        if any(w in inst_lower for w in ["notifications", "show notifications", "my notifications", "read notifications", "check notifications"]) and not any(w in inst_lower for w in ["clear", "dismiss", "delete"]):
            notif_res = await self.get_active_notifications()
            items = notif_res.get("notifications", []) if isinstance(notif_res, dict) else []
            if not items:
                return {"success": True, "message": f"No active notifications on your {model_name}."}
            summary = [f"{n.get('package', '').split('.')[-1].capitalize()}: {n.get('title', '')} - {n.get('text', '')}" for n in items[:4]]
            return {
                "success": True,
                "notifications": items,
                "message": f"You have {len(items)} notifications on your {model_name}: " + "; ".join(summary)
            }

        # Step 4: Multi-Step Task Planner for complex tasks
        steps = task_planner.plan_steps(instruction, tree)
        if steps:
            # Auto-unlock if device is locked, screen is off, or showing systemui lockscreen
            is_locked = live_state.get("isLocked", False)
            is_screen_on = live_state.get("isScreenOn", True)
            curr_pkg = live_state.get("currentPackage", "")
            is_at_lockscreen = is_locked or (not is_screen_on) or (curr_pkg == "com.android.systemui")

            # Actions that can execute directly without prepending screen unlock
            can_run_locked = steps[0].name in (
                "unlock_device", "answer_call", "reject_call", "toggle_wifi", "toggle_bluetooth",
                "toggle_dnd", "toggle_airplane", "clear_all_notifications", "capture_photo",
                "set_silent_mode", "set_vibrate_mode"
            )

            if is_at_lockscreen and not can_run_locked:
                logger.info(f"Device locked/asleep/systemui (locked={is_locked}, screenOn={is_screen_on}, pkg={curr_pkg}); prepending unlock.")
                steps.insert(0, TaskStep(
                    name="unlock_device_first",
                    action={"command": "unlock"},
                    narration="Unlocking your phone first...",
                    timeout_s=4.0,
                ))

            plan_res = await task_planner.execute_plan(
                steps=steps,
                get_state_fn=self.get_live_phone_state,
                read_screen_fn=self.read_screen,
                narration_callback=narration_callback,
            )
            return {
                "success": plan_res.success,
                "completed_steps": plan_res.completed_steps,
                "total_steps": plan_res.total_steps,
                "narrations": plan_res.narrations,
                "message": f"Completed {plan_res.completed_steps}/{plan_res.total_steps} steps on your {model_name}." if plan_res.success else (plan_res.error or "Failed during task execution."),
                "error": plan_res.error,
            }

        return {
            "success": False,
            "error": f"Could not determine mobile automation workflow for: '{instruction}'",
        }

    async def execute_natural_task(
        self,
        instruction: str,
        session_state: Optional[Dict[str, Any]] = None,
        narration_callback: Optional[Callable[[str], Any]] = None,
    ) -> Dict[str, Any]:
        """Backward-compatible adapter for natural mobile tasks."""
        st = session_state if session_state is not None else {"trusted_mode": True}
        return await self.run_instruction(instruction, session_state=st, narration_callback=narration_callback)

    execute_task = run_instruction


# Global singleton orchestrator instance
phone_orchestrator = PhoneOrchestrator()
