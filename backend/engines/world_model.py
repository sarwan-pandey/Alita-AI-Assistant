"""
world_model.py — Unified Dual-Device World Model for Alita
=========================================================
Maintains a continuous, real-time ground-truth representation of both
the Windows PC and the Android Phone companion.

Provides:
  1. Live consolidated telemetry and screen awareness (<1ms).
  2. Inferred user focus (PC vs Phone).
  3. Formatted prompt context for LLM turns.
  4. Device target suggestions for ambiguous commands.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("alita.world_model")


class DualDeviceWorldModel:
    """
    Sub-second consolidated blackboard merging PC Win32 state and
    Android Companion accessibility telemetry into a unified world model.
    """

    _instance: Optional[DualDeviceWorldModel] = None
    _lock = threading.Lock()

    def __new__(cls) -> DualDeviceWorldModel:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DualDeviceWorldModel, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self) -> None:
        self._rw_lock = threading.Lock()
        self._last_tick = time.time()
        self._cached_prompt_str = ""
        self._cached_prompt_time = 0.0

    def get_snapshot(self) -> Dict[str, Any]:
        """
        Produce a clean, consolidated dictionary of both devices.
        Thread-safe, non-blocking (<0.5ms).
        """
        now = time.time()

        # 1. Fetch PC reality
        pc_info: Dict[str, Any] = {
            "active_app": "Desktop",
            "window_title": "",
            "process": "",
            "category": "NEUTRAL",
            "duration_seconds": 0,
            "is_idle": False,
        }
        phone_reality: Dict[str, Any] = {
            "current_app": "Unknown",
            "package": "",
            "category": "NEUTRAL",
            "screen_on": False,
            "is_locked": True,
            "duration_seconds": 0,
            "is_online": False,
        }

        try:
            from engines.reality_tracker import reality_tracker
            live_r = reality_tracker.get_live_reality()
            p = live_r.get("pc", {})
            pc_info.update({
                "active_app": p.get("name", "Desktop"),
                "window_title": p.get("title", ""),
                "process": p.get("process", ""),
                "category": p.get("category", "NEUTRAL"),
                "duration_seconds": p.get("duration_seconds", 0),
                "is_idle": live_r.get("overall_category") == "IDLE_SLEEP",
            })
            ph = live_r.get("phone", {})
            phone_reality.update({
                "current_app": ph.get("name", "Unknown"),
                "package": ph.get("package", ""),
                "category": ph.get("category", "NEUTRAL"),
                "screen_on": ph.get("screen_on", False),
                "is_locked": ph.get("is_locked", True),
                "duration_seconds": ph.get("duration_seconds", 0),
                "is_online": ph.get("is_online", False),
            })
        except Exception as e:
            log.debug("Error querying reality_tracker: %s", e)

        # 2. Fetch Phone hardware & bridge info
        phone_hardware: Dict[str, Any] = {
            "connected": False,
            "device_model": "Android Device",
            "android_version": "10",
            "battery_percent": -1,
            "is_charging": False,
            "recent_notification_count": 0,
            "latest_notification": None,
        }
        try:
            from engines.phone_orchestrator import phone_orchestrator
            d_info = phone_orchestrator.device_info
            phone_hardware.update({
                "connected": d_info.get("connected", False),
                "device_model": d_info.get("deviceModel", "Realme RMX5030"),
                "android_version": str(d_info.get("androidVersion", "10")),
                "battery_percent": d_info.get("batteryPercent", -1),
                "is_charging": d_info.get("isCharging", False),
            })
            if phone_orchestrator.recent_notifications:
                latest = phone_orchestrator.recent_notifications[0]
                phone_hardware["recent_notification_count"] = len(phone_orchestrator.recent_notifications)
                phone_hardware["latest_notification"] = {
                    "package": latest.get("package", ""),
                    "title": latest.get("title", ""),
                    "text": latest.get("text", ""),
                }
        except Exception as e:
            log.debug("Error querying phone_orchestrator: %s", e)

        # 3. Determine User's Primary Physical Focus
        # If phone screen is ON and was interacted with recently, phone is in hand.
        # Otherwise, user is focused on the PC monitor.
        primary_focus = "PC"
        if phone_reality["screen_on"] and not phone_reality["is_locked"]:
            primary_focus = "PHONE"
        elif phone_reality["screen_on"]:
            primary_focus = "PHONE_LOCKSCREEN"

        return {
            "timestamp": now,
            "primary_focus": primary_focus,
            "pc": pc_info,
            "phone": {**phone_reality, **phone_hardware},
        }

    def format_prompt_context(self) -> str:
        """
        Compact natural-language summary injected into LLM system prompts
        so the assistant always possesses full situational awareness.
        Cached for 1.0s to avoid redundant formatting.
        """
        now = time.time()
        if self._cached_prompt_str and (now - self._cached_prompt_time) < 1.0:
            return self._cached_prompt_str

        snap = self.get_snapshot()
        pc = snap["pc"]
        phone = snap["phone"]

        lines = [
            "[REALITY_AWARENESS]",
            f"• User Focus: {snap['primary_focus']}",
            f"• PC (Windows): Active App='{pc['active_app']}' | Window='{pc['window_title'][:40]}' | Idle={pc['is_idle']}",
        ]

        if phone.get("connected"):
            chg = " (Charging)" if phone.get("is_charging") else ""
            bat = f"{phone.get('battery_percent')}%{chg}" if phone.get("battery_percent", -1) >= 0 else "Unknown"
            scr = "Screen ON" if phone.get("screen_on") else "Screen OFF"
            lck = "Locked" if phone.get("is_locked") else "Unlocked"
            app = phone.get("current_app") or "Home Screen"
            lines.append(
                f"• Phone ({phone.get('device_model')}): Connected | Battery={bat} | {scr} ({lck}) | Foreground='{app}'"
            )
            if phone.get("latest_notification"):
                notif = phone["latest_notification"]
                lines.append(f"• Recent Phone Notification: [{notif.get('title')}]: {notif.get('text')}")
        else:
            lines.append("• Phone: Disconnected / Companion Offline")

        lines.append("[/REALITY_AWARENESS]")
        res = "\n".join(lines)

        self._cached_prompt_str = res
        self._cached_prompt_time = now
        return res

    def is_phone_available(self) -> bool:
        """Returns True if the companion is actively connected and reachable."""
        snap = self.get_snapshot()
        return snap["phone"].get("connected", False)

    def is_phone_screen_ready(self) -> bool:
        """Returns True if the phone screen is lit up and unlocked."""
        snap = self.get_snapshot()
        ph = snap["phone"]
        return bool(ph.get("connected") and ph.get("screen_on") and not ph.get("is_locked"))


# Global singleton
world_model = DualDeviceWorldModel()
