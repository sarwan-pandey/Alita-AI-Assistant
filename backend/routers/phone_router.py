"""
phone_router.py — FastAPI Router & WebSocket Bridge for Alita Android Companion

Handles:
- Persistent WebSocket connection with Android Companion (`/ws/phone`)
- Command routing & response awaiting
- Device telemetry & status reporting (`/api/phone/status`)
- Direct notification replies (`/api/phone/reply`)
- View-tree extraction & natural mobile instruction execution
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from engines.phone_orchestrator import phone_orchestrator

logger = logging.getLogger("alita.phone_router")

phone_router = APIRouter(tags=["Phone Companion"])


# ── Pydantic Request Models ──────────────────────────────────────────────────

class PhoneCommandRequest(BaseModel):
    command: str = Field(..., description="Action name: tap, double_tap, swipe, type, click, global, unlock_screen, launch_app")
    x: Optional[float] = None
    y: Optional[float] = None
    duration: Optional[int] = 50
    startX: Optional[float] = None
    startY: Optional[float] = None
    endX: Optional[float] = None
    endY: Optional[float] = None
    target: Optional[str] = None
    resourceId: Optional[str] = None
    text: Optional[str] = None
    action: Optional[str] = None
    package: Optional[str] = None
    deepLink: Optional[str] = None
    pin: Optional[str] = None


class NotificationReplyRequest(BaseModel):
    notificationKey: str = Field(..., description="Active notification key identifier")
    text: str = Field(..., description="Text content to reply with")


class NaturalTaskRequest(BaseModel):
    instruction: str = Field(..., description="Natural language mobile instruction, e.g. 'Unlock my phone' or 'Message Mom on WhatsApp'")


# ── Phone Connection Bridge ──────────────────────────────────────────────────

class PhoneBridgeManager:
    """Manages active WebSocket link to the Android companion device."""

    def __init__(self):
        self.active_socket: Optional[WebSocket] = None
        self._pending_commands: Dict[str, asyncio.Future[Dict[str, Any]]] = {}
        self._lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self.active_socket is not None

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self.active_socket = websocket
        phone_orchestrator.device_info["connected"] = True
        logger.info("Android Phone Companion connected via WebSocket.")

    async def disconnect(self) -> None:
        async with self._lock:
            self.active_socket = None
        phone_orchestrator.device_info["connected"] = False
        # Cancel any pending command futures
        for cmd_id, fut in list(self._pending_commands.items()):
            if not fut.done():
                fut.set_exception(ConnectionResetError("Phone companion disconnected"))
        self._pending_commands.clear()
        logger.info("Android Phone Companion disconnected.")

    async def send_command(self, command_dict: Dict[str, Any], timeout: float = 8.0) -> Dict[str, Any]:
        """Dispatches a command to the phone and awaits its command_result."""
        if not self.active_socket:
            return {"success": False, "error": "Phone is not connected"}

        cmd_id = command_dict.get("id") or f"cmd_{int(time.time() * 1000)}"
        command_dict["id"] = cmd_id

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Dict[str, Any]] = loop.create_future()
        self._pending_commands[cmd_id] = future

        try:
            msg_str = json.dumps(command_dict)
            await self.active_socket.send_text(msg_str)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            logger.warning(f"Command {cmd_id} timed out after {timeout}s")
            return {"success": False, "error": f"Command timed out after {timeout}s"}
        except Exception as e:
            logger.error(f"Failed to send command {cmd_id}: {e}")
            return {"success": False, "error": str(e)}
        finally:
            self._pending_commands.pop(cmd_id, None)

    def resolve_command(self, cmd_id: str, result: Dict[str, Any]) -> None:
        """Resolves a pending command future when reply is received."""
        fut = self._pending_commands.get(cmd_id)
        if fut and not fut.done():
            fut.set_result(result)


bridge_manager = PhoneBridgeManager()
phone_orchestrator.set_bridge_sender(bridge_manager.send_command)


# ── WebSocket Bridge Endpoint ────────────────────────────────────────────────

@phone_router.websocket("/ws/phone")
async def phone_websocket_endpoint(websocket: WebSocket):
    """
    Main communication channel between Alita PC backend and Android Companion.
    """
    await bridge_manager.connect(websocket)

    try:
        while True:
            text_data = await websocket.receive_text()
            try:
                msg = json.loads(text_data)
            except json.JSONDecodeError:
                logger.warning(f"Malformed JSON from phone: {text_data[:100]}")
                continue

            msg_type = msg.get("type")

            # 1. Handshake
            if msg_type == "handshake":
                phone_orchestrator.device_info.update({
                    "connected": True,
                    "deviceModel": msg.get("deviceModel", "Android Device"),
                    "androidVersion": msg.get("androidVersion", "Unknown"),
                    "sdkVersion": msg.get("sdkVersion", 0),
                    "accessibilityActive": msg.get("accessibilityActive", False),
                    "notificationListenerActive": msg.get("notificationListenerActive", False),
                    "batteryPercent": msg.get("batteryPercent", -1),
                    "isCharging": msg.get("isCharging", False),
                    "lastSeen": time.time(),
                })
                logger.info(f"Handshake accepted: {phone_orchestrator.device_info['deviceModel']} (Android {phone_orchestrator.device_info['androidVersion']})")

            # 2. Telemetry Update
            elif msg_type == "telemetry":
                phone_orchestrator.update_telemetry(msg)
                try:
                    from engines.reality_tracker import reality_tracker
                    pkg = msg.get("currentPackage", "")
                    scr = msg.get("isScreenOn", True)
                    lck = msg.get("isLocked", False)
                    if pkg:
                        reality_tracker.update_phone_app(pkg, is_screen_on=scr)
                    reality_tracker.update_phone_screen_state(is_screen_on=scr, is_locked=lck)
                except Exception:
                    pass

            # 2b. Instant App Switched Notification (< 5ms)
            elif msg_type == "app_switched":
                pkg = msg.get("package", "")
                scr = msg.get("isScreenOn", True)
                phone_orchestrator.device_info["currentPackage"] = pkg
                phone_orchestrator.device_info["isScreenOn"] = scr
                phone_orchestrator.device_info["lastSeen"] = time.time()
                try:
                    from engines.reality_tracker import reality_tracker
                    reality_tracker.update_phone_app(pkg, is_screen_on=scr)
                except Exception:
                    pass

            # 2c. Instant Screen State Changed Notification (< 5ms)
            elif msg_type == "screen_state":
                scr = msg.get("isScreenOn", True)
                lck = msg.get("isLocked", False)
                phone_orchestrator.device_info["isScreenOn"] = scr
                phone_orchestrator.device_info["isLocked"] = lck
                phone_orchestrator.device_info["lastSeen"] = time.time()
                try:
                    from engines.reality_tracker import reality_tracker
                    reality_tracker.update_phone_screen_state(is_screen_on=scr, is_locked=lck)
                except Exception:
                    pass

            # 3. Phone Notification Intercepted
            elif msg_type == "phone_notification":
                phone_orchestrator.record_notification(msg)
                logger.info(f"Notification from {msg.get('package')}: {msg.get('title')}: {msg.get('text')}")

            # 4. Command Result Reply
            elif msg_type == "command_result":
                cmd_id = msg.get("id")
                if cmd_id:
                    bridge_manager.resolve_command(cmd_id, msg)

            # 5. View Tree Dump Reply
            elif msg_type == "view_tree":
                cmd_id = msg.get("id")
                tree_data = msg.get("data", {})
                phone_orchestrator.update_view_tree(tree_data)
                if cmd_id:
                    bridge_manager.resolve_command(cmd_id, {"success": True, "data": tree_data})

            # 6. Pong Heartbeat
            elif msg_type == "pong":
                cmd_id = msg.get("id")
                if cmd_id:
                    bridge_manager.resolve_command(cmd_id, msg)

            # 7. Status Event
            elif msg_type == "status_event":
                logger.info(f"Phone status event: {msg.get('status')}")

    except WebSocketDisconnect:
        logger.info("Phone companion WebSocket disconnected.")
    except Exception as e:
        logger.error(f"WebSocket error in phone channel: {e}")
    finally:
        try:
            from engines.reality_tracker import reality_tracker
            reality_tracker.update_phone_screen_state(is_screen_on=False, is_locked=True)
        except Exception:
            pass
        await bridge_manager.disconnect()


# ── REST API Endpoints ───────────────────────────────────────────────────────

@phone_router.get("/api/phone/status")
async def get_phone_status():
    """
    Returns live connectivity status, battery %, hardware telemetry, and recent notifications.
    """
    return {
        "status": "online" if bridge_manager.is_connected else "offline",
        "device": phone_orchestrator.device_info,
        "recentNotifications": phone_orchestrator.recent_notifications[:10],
    }


@phone_router.post("/api/phone/command")
async def execute_phone_command(req: PhoneCommandRequest):
    """
    Sends a raw UI automation command (tap, swipe, type, click, global, unlock) to the phone.
    """
    if not bridge_manager.is_connected:
        raise HTTPException(status_code=503, detail="Android companion is offline")

    cmd_payload = req.model_dump(exclude_none=True)
    if req.command == "unlock_screen" and not req.pin:
        cmd_payload["pin"] = getattr(phone_orchestrator, "default_password", None)
    res = await bridge_manager.send_command(cmd_payload, timeout=10.0)
    return res


@phone_router.post("/api/phone/reply")
async def reply_phone_notification(req: NotificationReplyRequest):
    """
    Executes zero-screen instant background reply via Android RemoteInput.
    """
    if not bridge_manager.is_connected:
        raise HTTPException(status_code=503, detail="Android companion is offline")

    res = await phone_orchestrator.reply_direct(req.notificationKey, req.text)
    return res


@phone_router.get("/api/phone/view-tree")
async def get_phone_view_tree():
    """
    Fetches active screen view tree from the phone via AccessibilityService.
    """
    if not bridge_manager.is_connected:
        raise HTTPException(status_code=503, detail="Android companion is offline")

    tree = await phone_orchestrator.fetch_view_tree()
    return {"success": True, "tree": tree}


@phone_router.post("/api/phone/execute-task")
async def execute_natural_mobile_task(req: NaturalTaskRequest):
    """
    Autonomous high-level mobile task planner.
    Parses natural language (e.g. 'Unlock my phone', 'Message Sarah on WhatsApp that I will be late', 'Like post on Instagram')
    and executes self-healing multi-step mobile workflows.
    """
    if not bridge_manager.is_connected:
        raise HTTPException(status_code=503, detail="Android companion is offline")

    res = await phone_orchestrator.execute_natural_task(req.instruction)
    return res


@phone_router.get("/api/phone/download-apk")
@phone_router.get("/download-apk")
async def download_companion_apk():
    """Serves the latest compiled Android companion APK directly for easy phone installation."""
    workspace_root = Path(__file__).resolve().parent.parent.parent
    apk_path = workspace_root / "AlitaCompanion.apk"
    if not apk_path.exists():
        apk_path = workspace_root / "android_companion" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    if not apk_path.exists():
        raise HTTPException(status_code=404, detail="AlitaCompanion.apk not found")
    return FileResponse(
        path=str(apk_path),
        filename="AlitaCompanion.apk",
        media_type="application/vnd.android.package-archive"
    )
