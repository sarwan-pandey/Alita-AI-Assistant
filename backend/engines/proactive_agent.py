"""
Alita Assistant — Proactive Autonomous Sentinel & Intelligence Engine
======================================================================
Provides ambient situational awareness and proactive intelligence.
Runs as a non-blocking background daemon that monitors:
  1. Meeting Sentinel: Detects Zoom, Teams, Meet, Discord and offers 1-click meeting prep.
  2. Smart Clipboard Sentinel: Detects YouTube, GitHub, StackTrace URLs and generates instant Action Chips.
  3. System Health Sentinel: Battery level, RAM pressure, focus session milestones, evening wind-down.

Dispatches suggestions to the frontend Dynamic Island via WebSockets.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import psutil
import re
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("alita.proactive")


class ProactiveAgent:
    """Autonomous proactive situational monitor for Alita."""

    def __init__(self, check_interval_seconds: int = 15) -> None:
        self.check_interval = check_interval_seconds
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._broadcast_callbacks: List[Callable[[Dict[str, Any]], Any]] = []
        self._cooldowns: Dict[str, float] = {}  # suggestion_key -> last_triggered_timestamp
        self._user_activity_start = time.time()
        self._last_suggestion: Optional[Dict[str, Any]] = None
        self._last_clipboard: str = ""

    def register_broadcast_callback(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """Register a callback (e.g. WebSocket broadcast) to push suggestions to UI."""
        if callback not in self._broadcast_callbacks:
            self._broadcast_callbacks.append(callback)

    def unregister_broadcast_callback(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        if callback in self._broadcast_callbacks:
            self._broadcast_callbacks.remove(callback)

    def record_user_activity(self) -> None:
        """Update activity heartbeat when user interacts with Alita."""
        self._user_activity_start = time.time()

    def start(self) -> None:
        """Start the proactive background monitoring daemon."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="AlitaProactiveDaemon")
        self._thread.start()
        log.info("[ProactiveAgent] Autonomous background sentinel started")

    def stop(self) -> None:
        """Stop background monitor."""
        self._running = False

    def _is_cooldown_active(self, key: str, cooldown_seconds: float = 1200) -> bool:
        """Check if a suggestion is currently on cooldown."""
        now = time.time()
        last = self._cooldowns.get(key, 0.0)
        return (now - last) < cooldown_seconds

    def _trigger_cooldown(self, key: str) -> None:
        self._cooldowns[key] = time.time()

    def check_clipboard(self) -> Optional[Dict[str, Any]]:
        """Evaluate clipboard contents for smart context-aware action chips."""
        try:
            import pyperclip
            content = pyperclip.paste().strip()
            if not content or content == self._last_clipboard or len(content) < 4:
                return None
            self._last_clipboard = content
            now = time.time()

            # A. YouTube Link
            if ("youtube.com/watch" in content or "youtu.be/" in content) and not self._is_cooldown_active("clip_yt", 120):
                self._trigger_cooldown("clip_yt")
                return {
                    "id": f"clip_yt_{int(now)}",
                    "type": "proactive_suggestion",
                    "title": "YouTube Video Copied",
                    "message": "Detected a YouTube link on your clipboard. Would you like me to play or summarize it?",
                    "action_label": "Play on YouTube",
                    "dismiss_label": "Dismiss",
                    "action": "open_music",
                    "action_payload": {"action": "open_music", "query": content},
                    "priority": "normal",
                    "icon": "video",
                }

            # B. GitHub Repo Link
            if "github.com/" in content and not self._is_cooldown_active("clip_gh", 120):
                self._trigger_cooldown("clip_gh")
                repo_match = re.search(r'github\.com/([a-zA-Z0-9_\-\.]+/[a-zA-Z0-9_\-\.]+)', content)
                repo_name = repo_match.group(1) if repo_match else "Repository"
                return {
                    "id": f"clip_gh_{int(now)}",
                    "type": "proactive_suggestion",
                    "title": "GitHub Repo Copied",
                    "message": f"Detected GitHub repository '{repo_name}'. Shall I open it in browser?",
                    "action_label": "Open in Browser",
                    "dismiss_label": "Dismiss",
                    "action": "open_url",
                    "action_payload": {"action": "open_url", "url": content},
                    "priority": "normal",
                    "icon": "github",
                }

            # C. StackTrace / Error Log
            if any(err_sig in content for err_sig in ["Traceback (most recent call last):", "SyntaxError:", "TypeError:", "ReferenceError:", "NullPointerException"]) and not self._is_cooldown_active("clip_err", 120):
                self._trigger_cooldown("clip_err")
                return {
                    "id": f"clip_err_{int(now)}",
                    "type": "proactive_suggestion",
                    "title": "Error Traceback Copied",
                    "message": "Detected a code error on your clipboard. Shall I analyze it and suggest a fix?",
                    "action_label": "Explain & Fix Error",
                    "dismiss_label": "Dismiss",
                    "action": "explain_error",
                    "action_payload": {"action": "explain_error", "error": content[:500]},
                    "priority": "urgent",
                    "icon": "alert-triangle",
                }

        except Exception as exc:
            log.debug("[ProactiveAgent] Clipboard check error: %s", exc)
        return None

    def _check_meeting_active(self) -> Optional[Dict[str, Any]]:
        """Detect active meeting applications (Zoom, Teams, Meet, Discord)."""
        now = time.time()
        if self._is_cooldown_active("meeting_active", 1800):
            return None

        meeting_procs = {
            "zoom.exe": "Zoom",
            "teams.exe": "Microsoft Teams",
            "ms-teams.exe": "Microsoft Teams",
            "discord.exe": "Discord",
            "webex.exe": "Cisco Webex"
        }

        try:
            for p in psutil.process_iter(['name']):
                pname = p.info.get('name', '').lower()
                if pname in meeting_procs:
                    app_name = meeting_procs[pname]
                    self._trigger_cooldown("meeting_active")
                    return {
                        "id": f"meet_{int(now)}",
                        "type": "proactive_suggestion",
                        "title": "Meeting Sentinel Active",
                        "message": f"Active {app_name} meeting detected. Shall I mute background audio and prep your meeting notes?",
                        "action_label": "Prep Meeting Notes",
                        "dismiss_label": "Not Needed",
                        "action": "meeting_mode",
                        "action_payload": {"action": "meeting_mode", "app": app_name},
                        "priority": "urgent",
                        "icon": "mic-off",
                    }
        except Exception as e:
            log.debug("[ProactiveAgent] Meeting check error: %s", e)
        return None

    @staticmethod
    def _is_fullscreen_or_dnd() -> bool:
        """
        Detect if the user is in full-screen gaming, presentation, or video playback.
        Silences non-critical proactive popups to avoid interrupting the user.
        """
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if not hwnd:
                return False

            # Check window class (ignore Desktop / Taskbar)
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            if class_name.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
                return False

            # 1. Windows Notification State (presentation / full-screen directX / DND)
            shell32 = ctypes.windll.shell32
            if hasattr(shell32, "SHQueryUserNotificationState"):
                p_state = ctypes.c_int()
                if shell32.SHQueryUserNotificationState(ctypes.byref(p_state)) == 0:
                    # QUNS_BUSY = 2, QUNS_RUNNING_D3D_FULL_SCREEN = 3, QUNS_PRESENTATION_MODE = 4
                    if p_state.value in (2, 3, 4):
                        return True

            # 2. Window Rect covering full virtual screen
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                sw = user32.GetSystemMetrics(0)  # SM_CXSCREEN
                sh = user32.GetSystemMetrics(1)  # SM_CYSCREEN
                win_w = rect.right - rect.left
                win_h = rect.bottom - rect.top
                if win_w >= sw and win_h >= sh:
                    return True
        except Exception:
            pass
        return False

    def _evaluate_situations(self) -> Optional[Dict[str, Any]]:
        """Evaluate current system & temporal state to see if a proactive suggestion is needed."""
        now = time.time()
        current_dt = datetime.now()
        hour = current_dt.hour
        minute = current_dt.minute

        # ── Fullscreen & DND Check (Gaming / Presentation / Movie protection) ──
        is_dnd = self._is_fullscreen_or_dnd()

        # ── 1. Smart Clipboard Sentinel ────────────────────────────────────
        clip_sug = self.check_clipboard()
        if clip_sug and not is_dnd:
            return clip_sug

        # ── 2. Meeting Sentinel ────────────────────────────────────────────
        meet_sug = self._check_meeting_active()
        if meet_sug:
            return meet_sug

        # ── 3. Battery Critical / Low Warning ──────────────────────────────
        try:
            battery = psutil.sensors_battery()
            if battery is not None:
                percent = battery.percent
                plugged = battery.power_plugged
                if not plugged and percent <= 18 and not self._is_cooldown_active("battery_low", 1200):
                    self._trigger_cooldown("battery_low")
                    return {
                        "id": f"sug_batt_{int(now)}",
                        "type": "proactive_suggestion",
                        "title": "Low Battery Alert",
                        "message": f"Battery is down to {percent}%. Shall I enable Battery Saver mode and dim display?",
                        "action_label": "Enable Power Saver",
                        "dismiss_label": "Dismiss",
                        "action": "manage_power_plan",
                        "action_payload": {"action": "manage_power_plan", "plan_action": "set_saver"},
                        "priority": "urgent",
                        "icon": "battery-low",
                    }
        except Exception as e:
            log.debug("[ProactiveAgent] Battery check skipped: %s", e)

        # ── 4. High RAM Memory Usage ───────────────────────────────────────
        try:
            mem = psutil.virtual_memory()
            if mem.percent > 90 and not is_dnd and not self._is_cooldown_active("ram_high", 1800):
                self._trigger_cooldown("ram_high")
                return {
                    "id": f"sug_ram_{int(now)}",
                    "type": "proactive_suggestion",
                    "title": "High Memory Usage",
                    "message": f"System RAM is at {mem.percent:.0f}%. Would you like me to inspect top memory-consuming processes?",
                    "action_label": "Check Processes",
                    "dismiss_label": "Ignore",
                    "action": "processes",
                    "action_payload": {"action": "processes"},
                    "priority": "normal",
                    "icon": "cpu",
                }
        except Exception as e:
            log.debug("[ProactiveAgent] RAM check skipped: %s", e)

        # ── 5. Prolonged Work / Focus Session Milestone ────────────────────
        session_duration_minutes = (now - self._user_activity_start) / 60.0
        if session_duration_minutes >= 75 and not is_dnd and not self._is_cooldown_active("focus_break", 3600):
            self._trigger_cooldown("focus_break")
            return {
                "id": f"sug_break_{int(now)}",
                "type": "proactive_suggestion",
                "title": "Focus Session Milestone",
                "message": "You've been working intensely for over an hour! Ready for a quick 5-min stretch or relaxing music?",
                "action_label": "Play Lo-Fi Beats",
                "dismiss_label": "Keep Working",
                "action": "open_music",
                "action_payload": {"action": "open_music", "query": "lofi chill beats relaxing music"},
                "priority": "normal",
                "icon": "coffee",
            }

        # ── 6. Evening Wind-Down & Dark Mode ────────────────────────────────
        if ((hour == 21 and minute >= 30) or (hour == 22 and minute <= 30)) and not is_dnd:
            if not self._is_cooldown_active("evening_wind_down", 7200):
                self._trigger_cooldown("evening_wind_down")
                return {
                    "id": f"sug_evening_{int(now)}",
                    "type": "proactive_suggestion",
                    "title": "Evening Wind-Down",
                    "message": "It's late evening. Would you like to switch to Dark Mode and play peaceful ambient sounds?",
                    "action_label": "Enable Dark Mode",
                    "dismiss_label": "Not Now",
                    "action": "toggle_dark_mode",
                    "action_payload": {"action": "toggle_dark_mode"},
                    "priority": "low",
                    "icon": "moon",
                }

        # ── 7. Vision Sentinel — Screen OCR Alerts ─────────────────────────
        try:
            from engines.screen_ocr import screen_ocr
            if screen_ocr.available:
                patterns = screen_ocr.get_detected_patterns()
                app_title = ""
                try:
                    from engines.screen_context import screen_context
                    app_title = screen_context.current_app or ""
                except Exception:
                    pass

                # Error detected on screen
                if patterns.get("errors") and not self._is_cooldown_active("vision_error", 90):
                    self._trigger_cooldown("vision_error")
                    error_text = patterns["errors"][0]
                    return {
                        "id": f"sug_vision_err_{int(now)}",
                        "type": "proactive_suggestion",
                        "title": "Error Detected on Screen",
                        "message": f"I noticed an error on your screen: \"{error_text}\". Would you like me to help fix it?",
                        "action_label": "Help Me Fix It",
                        "dismiss_label": "Ignore",
                        "action": "vision_assist",
                        "action_payload": {"action": "vision_assist", "error": error_text, "app": app_title},
                        "priority": "urgent",
                        "icon": "alert-triangle",
                    }

                # Dialog detected on screen
                if patterns.get("dialogs") and not self._is_cooldown_active("vision_dialog", 90):
                    self._trigger_cooldown("vision_dialog")
                    dialog_text = patterns["dialogs"][0]
                    return {
                        "id": f"sug_vision_dlg_{int(now)}",
                        "type": "proactive_suggestion",
                        "title": "Dialog Detected",
                        "message": f"There's a dialog on your screen: \"{dialog_text}\". Need help deciding?",
                        "action_label": "Help Me Decide",
                        "dismiss_label": "I'll Handle It",
                        "action": "vision_assist",
                        "action_payload": {"action": "vision_assist", "dialog": dialog_text, "app": app_title},
                        "priority": "normal",
                        "icon": "message-square",
                    }
        except ImportError:
            pass
        except Exception as e:
            log.debug("[ProactiveAgent] Vision sentinel error: %s", e)

        # ── 8. Girlfriend Accountability & Active Promises Sentinel (Bug 9) ────
        try:
            from engines.relationship_manager import relationship_manager
            from engines.reality_tracker import reality_tracker, CATEGORY_DISTRACTION
            promises = relationship_manager.state.get("active_promises", {})
            if promises and not self._is_cooldown_active("girlfriend_promise", 1800):
                sleep_promise = promises.get("sleep_time") or promises.get("sleep")
                if sleep_promise and sleep_promise.get("status", "active") == "active":
                    target = sleep_promise.get("target_time") or "00:00"
                    target_h, target_m = 0, 0
                    try:
                        parts = target.split(":")
                        target_h, target_m = int(parts[0]), int(parts[1])
                    except Exception:
                        pass

                    # Past target bedtime (handles midnight / late night rollover)
                    is_past_bedtime = False
                    if target_h == 0 and (0 <= hour < 5):
                        is_past_bedtime = (minute >= target_m) or (hour > 0)
                    elif hour > target_h or (hour == target_h and minute >= target_m):
                        is_past_bedtime = True

                    if is_past_bedtime:
                        reality = reality_tracker.get_live_reality()
                        phone_screen_on = reality.get("phone", {}).get("is_screen_on", False)
                        pc_distracted = reality.get("pc", {}).get("category") == CATEGORY_DISTRACTION
                        if phone_screen_on or pc_distracted:
                            self._trigger_cooldown("girlfriend_promise")
                            name = relationship_manager.state.get("user_name", "Sarwan")
                            return {
                                "id": f"sug_promise_{int(now)}",
                                "type": "proactive_suggestion",
                                "subtype": "girlfriend_promise_scold",
                                "title": "Broken Sleep Promise!",
                                "message": f"Hey {name}! You promised me you'd be asleep by {target}. Why are you still up staring at your screen? Put it away and go to sleep right now!",
                                "action_label": "I'm Going to Sleep",
                                "dismiss_label": "5 More Minutes",
                                "action": "lock_phone",
                                "action_payload": {"action": "lock_phone"},
                                "priority": "urgent",
                                "icon": "moon",
                            }
        except Exception as exc:
            log.debug("[ProactiveAgent] Girlfriend promise check skipped: %s", exc)

        # ── 9. Girlfriend Sentinel — Full Awareness Interventions ────────────
        try:
            from engines.relationship_manager import (
                relationship_manager, MOOD_PLAYFUL, MOOD_AFFECTIONATE,
            )
            from engines.ambient_awareness import ambient_awareness
            from engines.lie_detector import lie_detector

            name = relationship_manager.state.get("user_name", "Sarwan")
            last_nudge = relationship_manager.state.get("last_proactive_nudge", 0)
            nudge_cooldown = (now - last_nudge) > 600  # 10 min between nudges

            if nudge_cooldown and not is_dnd:

                # A. Distraction Alert (>20 min on social media)
                if not self._is_cooldown_active("gf_distraction", 1200):
                    try:
                        distraction_secs = ambient_awareness.get_category_usage_today("DISTRACTION_SOCIAL")
                        # Check if CURRENTLY on distraction for >20 min
                        reality = reality_tracker.get_live_reality()
                        phone = reality.get("phone", {})
                        phone_cat = phone.get("category", "")
                        phone_sec = phone.get("duration_seconds", 0)
                        phone_app = phone.get("name", "")

                        if phone_cat == CATEGORY_DISTRACTION and phone_sec > 1200:
                            dur_min = phone_sec // 60
                            self._trigger_cooldown("gf_distraction")
                            relationship_manager.state["last_proactive_nudge"] = now
                            return {
                                "id": f"gf_distraction_{int(now)}",
                                "type": "proactive_suggestion",
                                "subtype": "girlfriend_nudge",
                                "title": "MJ Says: Put That Phone Down! 📱",
                                "message": f"Hey {name}! You've been scrolling {phone_app} for {dur_min} minutes straight. Don't you have better things to do? Put it down!",
                                "action_label": "Okay Fine 😅",
                                "dismiss_label": "5 More Minutes",
                                "action": "lock_phone",
                                "action_payload": {"action": "lock_phone"},
                                "priority": "urgent",
                                "icon": "smartphone-off",
                            }
                    except Exception:
                        pass

                # B. Late Night Scolding (phone active past 1 AM)
                if hour >= 1 and hour < 5 and not self._is_cooldown_active("gf_late_night", 3600):
                    try:
                        reality = reality_tracker.get_live_reality()
                        phone_on = reality.get("phone", {}).get("screen_on", False)
                        phone_app = reality.get("phone", {}).get("name", "")
                        if phone_on:
                            self._trigger_cooldown("gf_late_night")
                            relationship_manager.state["last_proactive_nudge"] = now
                            return {
                                "id": f"gf_latenight_{int(now)}",
                                "type": "proactive_suggestion",
                                "subtype": "girlfriend_scold",
                                "title": "MJ Says: GO TO SLEEP! 😠",
                                "message": f"It's {hour}:{minute:02d} AM and your phone is STILL on?! {phone_app}?? Seriously {name}, put it away and go to sleep RIGHT NOW or I'm turning your screen off myself!",
                                "action_label": "Going to Sleep 😴",
                                "dismiss_label": "Just 10 Minutes",
                                "action": "lock_phone",
                                "action_payload": {"action": "lock_phone"},
                                "priority": "urgent",
                                "icon": "moon",
                            }
                    except Exception:
                        pass

                # C. Proactive Promise Contradiction (lie_detector cross-check)
                if not self._is_cooldown_active("gf_contradiction", 1800):
                    try:
                        contradiction = lie_detector.check_proactive_contradictions()
                        if contradiction:
                            self._trigger_cooldown("gf_contradiction")
                            relationship_manager.state["last_proactive_nudge"] = now
                            return {
                                "id": f"gf_contradict_{int(now)}",
                                "type": "proactive_suggestion",
                                "subtype": "girlfriend_callout",
                                "title": "MJ Says: Broken Promise! 🤨",
                                "message": contradiction["nudge"],
                                "action_label": "Sorry, Fixing It",
                                "dismiss_label": "I Know, I Know",
                                "action": "dismiss",
                                "action_payload": {},
                                "priority": "urgent",
                                "icon": "alert-circle",
                            }
                    except Exception:
                        pass

                # D. Inactivity Check (no interaction for 2+ hours)
                if not self._is_cooldown_active("gf_inactivity", 7200):
                    idle_min = relationship_manager.get_idle_minutes()
                    if idle_min >= 120:
                        self._trigger_cooldown("gf_inactivity")
                        relationship_manager.state["last_proactive_nudge"] = now
                        return {
                            "id": f"gf_inactive_{int(now)}",
                            "type": "proactive_suggestion",
                            "subtype": "girlfriend_worried",
                            "title": "MJ Misses You 💭",
                            "message": f"Hello?? {name}, it's been {int(idle_min)} minutes since you last talked to me. Did you forget about me? What are you even doing over there? 😤",
                            "action_label": "I'm Here! 👋",
                            "dismiss_label": "Busy Right Now",
                            "action": "dismiss",
                            "action_payload": {},
                            "priority": "normal",
                            "icon": "heart",
                        }

                # E. Daily Usage Callout (>2h distraction total today)
                if not self._is_cooldown_active("gf_daily_usage", 14400):
                    try:
                        stats = ambient_awareness.get_daily_usage_stats()
                        distraction_total = stats.get("by_category_raw", {}).get("DISTRACTION_SOCIAL", 0)
                        if distraction_total > 7200:  # >2 hours
                            dur_str = ambient_awareness._format_seconds(distraction_total)
                            # Find top distraction app
                            top_app = "social media"
                            for app_name, secs in stats.get("by_app_raw", {}).items():
                                if secs > 1800:
                                    top_app = app_name
                                    break
                            self._trigger_cooldown("gf_daily_usage")
                            relationship_manager.state["last_proactive_nudge"] = now
                            return {
                                "id": f"gf_usage_{int(now)}",
                                "type": "proactive_suggestion",
                                "subtype": "girlfriend_callout",
                                "title": f"MJ Says: {dur_str} on {top_app}?! 📊",
                                "message": f"You've spent {dur_str} on {top_app} today. That's more than yesterday. Just saying. 🙄",
                                "action_label": "Point Taken 😅",
                                "dismiss_label": "I Deserve It",
                                "action": "dismiss",
                                "action_payload": {},
                                "priority": "normal",
                                "icon": "bar-chart",
                            }
                    except Exception:
                        pass

            # ── Contextual Mood Evolution (runs every cycle, even if no nudge) ──
            try:
                reality = reality_tracker.get_live_reality()
                pc_cat = reality.get("pc", {}).get("category", "")
                is_productive = (pc_cat == "PRODUCTIVE_STUDY")
                idle_min = relationship_manager.get_idle_minutes()
                relationship_manager.evolve_mood_from_context(hour, is_productive, int(idle_min))
            except Exception:
                pass

        except Exception as exc:
            log.debug("[ProactiveAgent] Girlfriend sentinel error: %s", exc)

        return None

    def _monitor_loop(self) -> None:
        """Background loop executing situational evaluations."""
        time.sleep(3)  # Initial startup grace period
        while self._running:
            try:
                suggestion = self._evaluate_situations()
                if suggestion:
                    self._last_suggestion = suggestion
                    log.info("[ProactiveAgent] Sentinel triggered: %s", suggestion["title"])
                    # Broadcast to UI
                    for cb in list(self._broadcast_callbacks):
                        try:
                            cb(suggestion)
                        except Exception as exc:
                            log.warning("[ProactiveAgent] Broadcast error: %s", exc)
            except Exception as e:
                log.error("[ProactiveAgent] Monitoring loop error: %s", e)

            time.sleep(self.check_interval)


# Global singleton instance
proactive_agent = ProactiveAgent()

