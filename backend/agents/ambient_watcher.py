"""
Ambient Intelligence Watcher
============================
Low-overhead background perception agent that watches active window context
and emits proactive suggestions through Alita's Dynamic Island.
"""

import time
import re
import logging
import threading
from typing import Optional, Dict, Any, Callable

log = logging.getLogger("alita.ambient_watcher")

try:
    import win32gui  # type: ignore[import-untyped]
    import win32process  # type: ignore[import-untyped]
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

try:
    import psutil  # type: ignore[import-untyped]
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class AmbientWatcher:
    """
    Passively observes active desktop application context and extracts high-value
    events (compile errors, traceback in logs, documentation reading) along with
    hardware guardian telemetry (CPU, RAM, Battery) to protect system responsiveness.
    """

    def __init__(self, callback: Optional[Callable[[Dict[str, Any]], None]] = None):
        self.callback = callback
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._last_window_title = ""
        self._last_suggestion_time = 0.0
        self._last_guardian_time = 0.0

    def start(self):
        """Start ambient context watcher in background thread."""
        if self._running or not HAS_WIN32:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="ambient-watcher")
        self._thread.start()
        log.info("✓ Ambient Intelligence Watcher & Hardware Guardian running in background")

    def stop(self):
        """Stop watcher thread."""
        self._running = False

    def _get_active_window(self) -> Dict[str, str]:
        if not HAS_WIN32:
            return {}
        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return {}
            title = win32gui.GetWindowText(hwnd).strip()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            return {"title": title, "hwnd": str(hwnd), "pid": str(pid)}
        except Exception:
            return {}

    def get_hardware_telemetry(self) -> Dict[str, Any]:
        """Collects instantaneous hardware vitals."""
        if not HAS_PSUTIL:
            return {"status": "unavailable"}
        try:
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory()
            battery = None
            try:
                b = psutil.sensors_battery()
                if b:
                    battery = {"percent": b.percent, "plugged": b.power_plugged}
            except Exception:
                pass

            return {
                "status": "ok",
                "cpu_percent": cpu,
                "ram_percent": mem.percent,
                "ram_used_gb": round(mem.used / (1024 ** 3), 2),
                "ram_total_gb": round(mem.total / (1024 ** 3), 2),
                "battery": battery,
            }
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    def _watch_loop(self):
        while self._running:
            time.sleep(5.0)  # Check every 5 seconds
            now = time.time()

            # ── 1. Hardware Guardian Telemetry Check ──────────────────
            if HAS_PSUTIL and (now - self._last_guardian_time > 45):
                try:
                    telemetry = self.get_hardware_telemetry()
                    if telemetry.get("status") == "ok":
                        cpu = telemetry.get("cpu_percent", 0)
                        ram = telemetry.get("ram_percent", 0)
                        battery = telemetry.get("battery")

                        alert = None
                        if cpu > 90.0:
                            alert = {
                                "type": "guardian_alert",
                                "severity": "warning",
                                "metric": "cpu",
                                "value": cpu,
                                "message": f"Critical CPU Spike ({cpu:.1f}%) detected",
                                "action_label": "Optimize Load",
                            }
                        elif ram > 88.0:
                            alert = {
                                "type": "guardian_alert",
                                "severity": "warning",
                                "metric": "ram",
                                "value": ram,
                                "message": f"High Memory Pressure ({ram:.1f}% used) detected",
                                "action_label": "Clean Cache",
                            }
                        elif battery and not battery.get("plugged") and battery.get("percent", 100) < 18:
                            alert = {
                                "type": "guardian_alert",
                                "severity": "warning",
                                "metric": "battery",
                                "value": battery.get("percent"),
                                "message": f"Low Battery ({battery.get('percent')}%) — plug in power",
                                "action_label": "Battery Saver",
                            }

                        if alert:
                            self._last_guardian_time = now
                            if self.callback:
                                self.callback(alert)
                except Exception as exc:
                    log.debug("Guardian telemetry check error: %s", exc)

            # ── 2. Active Window Context Observation ─────────────────
            try:
                win_info = self._get_active_window()
                title = win_info.get("title", "")
                if not title or title == self._last_window_title:
                    continue

                self._last_window_title = title

                # Rate-limit suggestions to at most once every 90 seconds
                if now - self._last_suggestion_time < 90:
                    continue

                # Pattern: Terminal or command prompt showing error keywords in title
                lower_title = title.lower()
                if any(err_term in lower_title for err_term in ("error", "failed", "exception", "traceback")):
                    suggestion = {
                        "type": "proactive_suggestion",
                        "title": "Build Error Detected",
                        "summary": f"Detected error in active window '{title[:35]}…'",
                        "action_label": "Ask Alita to Debug",
                        "dismiss_label": "Ignore",
                        "query": f"I got an error in {title}. Can you inspect and help me debug it?",
                    }
                    self._last_suggestion_time = now
                    if self.callback:
                        self.callback(suggestion)

            except Exception as exc:
                log.debug("Ambient watcher loop error: %s", exc)


# Global singleton instance
ambient_watcher = AmbientWatcher()
