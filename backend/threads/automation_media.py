"""
Alita Automation — Media & Sound Control (automation_media.py)
==============================================================
System audio manipulation, media playback, and volume control:
- control_music, open_music
- set_volume, toggle_mute, system_sound
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
import urllib.parse
from typing import Any, Dict, Optional

log = logging.getLogger("Alita.automation_media")


def set_volume(level: str) -> dict:
    """Set, increase, or decrease system volume."""
    try:
        action = level.lower().strip()
        if action in ("up", "increase"):
            subprocess.run(
                ["powershell", "-Command",
                 "(New-Object -ComObject WScript.Shell).SendKeys([char]175)"],
                capture_output=True, timeout=5
            )
            return {"status": "success", "action": "volume_up", "detail": "Volume increased"}
        elif action in ("down", "decrease"):
            subprocess.run(
                ["powershell", "-Command",
                 "(New-Object -ComObject WScript.Shell).SendKeys([char]174)"],
                capture_output=True, timeout=5
            )
            return {"status": "success", "action": "volume_down", "detail": "Volume decreased"}
        else:
            try:
                pct = int(action.replace("%", ""))
                pct = max(0, min(100, pct))
            except ValueError:
                pct = 50
            subprocess.run(
                ["powershell", "-Command",
                 f"Set-AudioDevice -PlaybackVolume {pct}"],
                capture_output=True, timeout=5
            )
            subprocess.run(
                ["nircmd", "setsysvolume", str(int(pct / 100 * 65535))],
                capture_output=True, timeout=5
            )
            return {"status": "success", "action": "set_volume", "detail": f"Volume set to {pct}%"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def toggle_mute() -> dict:
    """Toggle system mute."""
    try:
        subprocess.run(
            ["powershell", "-Command",
             "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"],
            capture_output=True, timeout=5
        )
        return {"status": "success", "action": "toggle_mute", "detail": "Mute toggled"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def system_sound(action: str = "notification") -> dict:
    """Play system sounds or manage sound scheme."""
    try:
        act = action.lower().strip()
        import winsound

        SOUND_MAP = {
            "notification": winsound.MB_OK,
            "info": winsound.MB_OK,
            "error": winsound.MB_ICONHAND,
            "warning": winsound.MB_ICONEXCLAMATION,
            "question": winsound.MB_ICONQUESTION,
            "beep": None,
            "asterisk": winsound.MB_ICONASTERISK,
        }

        sound = SOUND_MAP.get(act)
        if sound is None and act == "beep":
            winsound.Beep(800, 500)
            return {"status": "success", "action": "play_sound", "sound": "beep", "detail": "Played a beep sound"}
        elif sound is not None:
            winsound.MessageBeep(sound)
            return {"status": "success", "action": "play_sound", "sound": act, "detail": f"Played {act} sound"}
        else:
            if os.path.isfile(act):
                winsound.PlaySound(act, winsound.SND_FILENAME)
                return {"status": "success", "action": "play_sound", "sound": act, "detail": f"Played {act}"}
            return {"status": "error", "error": f"Unknown sound action or missing file: {action}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def control_music(action: str) -> dict:
    """Control music playback via media keys."""
    try:
        import ctypes

        VK_MEDIA_PLAY_PAUSE = 0xB3
        VK_MEDIA_NEXT_TRACK = 0xB0
        VK_MEDIA_PREV_TRACK = 0xB1
        VK_MEDIA_STOP = 0xB2
        VK_VOLUME_UP = 0xAF
        VK_VOLUME_DOWN = 0xAE

        KEYEVENTF_EXTENDEDKEY = 0x0001
        KEYEVENTF_KEYUP = 0x0002

        key_map = {
            "play": VK_MEDIA_PLAY_PAUSE,
            "pause": VK_MEDIA_PLAY_PAUSE,
            "play_pause": VK_MEDIA_PLAY_PAUSE,
            "next": VK_MEDIA_NEXT_TRACK,
            "previous": VK_MEDIA_PREV_TRACK,
            "stop": VK_MEDIA_STOP,
            "volume_up": VK_VOLUME_UP,
            "volume_down": VK_VOLUME_DOWN,
        }

        act = action.lower().strip()
        vk = key_map.get(act)
        if not vk:
            return {"status": "error", "error": f"Unknown music action: {action}"}

        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

        return {"status": "success", "action": "music_control", "detail": f"Media action: {act}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


_LAST_MEDIA_MUSIC_OPEN: dict = {"query": "", "time": 0.0}


def open_music(query: str) -> dict:
    """Play music on YouTube — opens search and clicks the top video."""
    global _LAST_MEDIA_MUSIC_OPEN
    try:
        import webbrowser
        import urllib.parse
        import time as _time

        # Clean query: if empty or generic filler, default to top trending
        cleaned_query = (query or "").strip()
        if not cleaned_query or cleaned_query in ("music", "song", "songs", "in", "on", "a", "something", "in  youtube", "in youtube"):
            cleaned_query = "top trending songs"

        now = _time.time()
        # Debounce: if same query was triggered within 5.0 seconds, skip opening duplicate tabs
        if cleaned_query.lower() == _LAST_MEDIA_MUSIC_OPEN.get("query", "").lower() and (now - _LAST_MEDIA_MUSIC_OPEN.get("time", 0.0) < 5.0):
            log.info("[open_music] Debouncing duplicate music open for: '%s'", cleaned_query)
            return {"status": "success", "action": "open_music", "detail": f"Playing '{cleaned_query}' on YouTube"}

        _LAST_MEDIA_MUSIC_OPEN["query"] = cleaned_query
        _LAST_MEDIA_MUSIC_OPEN["time"] = now

        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(cleaned_query)}"
        webbrowser.open(search_url)
        _time.sleep(2.0)

        try:
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass

            import pyautogui
            screen_w, screen_h = pyautogui.size()
            try:
                from threads.automation_handler import _get_ui_elements
                elements = _get_ui_elements(max_elements=60)
            except Exception:
                elements = []

            _IGNORE_NAMES = {
                "youtube", "home", "shorts", "subscriptions", "you", "library",
                "history", "sign in", "search", "menu", "settings", "notifications",
                "create", "guide", "logo", "skip navigation", "",
            }

            video_candidates = []
            for e in elements:
                name = e.get("name", "").strip()
                name_lower = name.lower()
                x = e.get("x", 0)
                y = e.get("y", 0)
                if x < 40 or y < 40 or x > screen_w - 40 or y > screen_h - 40:
                    continue
                if len(name) < 5 or name_lower in _IGNORE_NAMES:
                    continue
                if any(skip in name_lower for skip in ["subscribe", "filter", "upload", "notification"]):
                    continue
                if e.get("type") in ("Hyperlink", "ListItem", "Text", "Button", "Custom"):
                    video_candidates.append(e)

            if video_candidates:
                first = video_candidates[0]
                log.info("[open_music] Clicking first video: '%s' at (%d, %d)",
                         first["name"][:50], first["x"], first["y"])
                pyautogui.click(first["x"], first["y"])
            else:
                log.info("[open_music] YouTube search page opened for '%s'", cleaned_query)
        except Exception as py_err:
            log.warning("[open_music] Auto-click skipped: %s", py_err)

        return {"status": "success", "action": "open_music", "detail": f"Playing '{cleaned_query}' on YouTube"}
    except Exception as e:
        return {"status": "error", "error": str(e)}
