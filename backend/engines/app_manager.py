"""
App Manager — Windows Application Management
Opens, lists, focuses, and switches between desktop applications.
Uses pygetwindow + subprocess for cross-app window management.
"""

import subprocess
import time
import logging
from typing import Any, Dict, List, Optional

try:
    import pygetwindow as gw  # type: ignore[import-untyped]
    HAS_GW = True
except ImportError:
    gw = None  # type: ignore[assignment]
    HAS_GW = False

try:
    import pyautogui  # type: ignore[import-untyped]
    pyautogui.FAILSAFE = True  # Move mouse to corner to abort
    pyautogui.PAUSE = 0.1
except ImportError:
    pyautogui = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ── Common app name → executable mapping ─────────────────────────────────────
APP_REGISTRY: Dict[str, str] = {
    # Browsers
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "microsoft edge": "msedge.exe",
    "brave": "brave.exe",
    "opera": "opera.exe",
    # Office
    "word": "WINWORD.EXE",
    "microsoft word": "WINWORD.EXE",
    "excel": "EXCEL.EXE",
    "microsoft excel": "EXCEL.EXE",
    "powerpoint": "POWERPNT.EXE",
    "outlook": "OUTLOOK.EXE",
    "onenote": "ONENOTE.EXE",
    # System
    "notepad": "notepad.exe",
    "calculator": "calc.exe",
    "calc": "calc.exe",
    "paint": "mspaint.exe",
    "explorer": "explorer.exe",
    "file explorer": "explorer.exe",
    "files": "explorer.exe",
    "task manager": "taskmgr.exe",
    "settings": "ms-settings:",
    "control panel": "control.exe",
    "cmd": "cmd.exe",
    "command prompt": "cmd.exe",
    "powershell": "powershell.exe",
    "terminal": "wt.exe",
    "windows terminal": "wt.exe",
    # Dev
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "visual studio code": "Code.exe",
    "visual studio": "devenv.exe",
    # Media
    "spotify": "Spotify.exe",
    "vlc": "vlc.exe",
    "photos": "Microsoft.Photos.exe",
    # Communication
    "teams": "Teams.exe",
    "microsoft teams": "Teams.exe",
    "discord": "Discord.exe",
    "slack": "slack.exe",
    "telegram": "Telegram.exe",
    "whatsapp": "WhatsApp.exe",
    "zoom": "Zoom.exe",
    # Creative
    "photoshop": "Photoshop.exe",
    "illustrator": "Illustrator.exe",
    "figma": "Figma.exe",
    "blender": "blender.exe",
}


def open_app(name: str) -> Dict[str, Any]:
    """Launch an application by name. Returns {ok, title, msg}."""
    name_lower = name.lower().strip()
    exe: Optional[str] = APP_REGISTRY.get(name_lower)

    if exe is None:
        # Try fuzzy match
        for key, val in APP_REGISTRY.items():
            if name_lower in key or key in name_lower:
                exe = val
                break

    if exe is None:
        # Last resort: try running the name directly (user might say the exe name)
        exe = name_lower if name_lower.endswith(".exe") else f"{name_lower}.exe"

    try:
        if exe.startswith("ms-"):
            # Windows URI scheme (Settings etc.)
            subprocess.Popen(["start", exe], shell=True)
        else:
            subprocess.Popen([exe], shell=True)
        logger.info(f"[AppManager] Launched: {exe}")
        time.sleep(1.5)  # Give app time to open

        # Try to find the new window
        windows = list_windows()
        for w in windows:
            if name_lower in w["title"].lower() or exe.lower().replace(".exe", "") in w["title"].lower():
                return {"ok": True, "title": w["title"], "msg": f"Opened {name}"}

        return {"ok": True, "title": name, "msg": f"Launched {exe} (window may still be loading)"}
    except Exception as e:
        logger.error(f"[AppManager] Failed to open {exe}: {e}")
        return {"ok": False, "title": "", "msg": f"Failed to open {name}: {str(e)}"}


def list_windows() -> List[Dict[str, Any]]:
    """List all visible windows. Returns [{title, left, top, width, height}]."""
    if not HAS_GW or gw is None:
        return []

    windows: List[Dict[str, Any]] = []
    try:
        for w in gw.getAllWindows():
            if w.title and w.title.strip() and w.visible and w.width > 50 and w.height > 50:
                windows.append({
                    "title": w.title,
                    "left": w.left,
                    "top": w.top,
                    "width": w.width,
                    "height": w.height,
                })
    except Exception as e:
        logger.error(f"[AppManager] list_windows error: {e}")

    return windows


def focus_window(title: str) -> bool:
    """Bring a window to front by title (partial match)."""
    if not HAS_GW or gw is None:
        return False

    title_lower = title.lower()
    try:
        for w in gw.getAllWindows():
            if w.title and title_lower in w.title.lower():
                try:
                    if w.isMinimized:
                        w.restore()
                    w.activate()
                    time.sleep(0.3)
                    logger.info(f"[AppManager] Focused: {w.title}")
                    return True
                except Exception:
                    pass
        return False
    except Exception as e:
        logger.error(f"[AppManager] focus_window error: {e}")
        return False


def find_window(partial_title: str) -> Optional[Dict[str, Any]]:
    """Find a window by partial title match."""
    partial_lower = partial_title.lower()
    for w in list_windows():
        if partial_lower in w["title"].lower():
            return w
    return None


def get_active_window() -> Dict[str, Any]:
    """Get info about the currently focused window using win32gui with fallback."""
    # Attempt 1: Win32 API
    try:
        import win32gui
        hwnd = win32gui.GetForegroundWindow()
        if hwnd:
            title = win32gui.GetWindowText(hwnd).strip()
            if title and title != "Program Manager":
                rect = win32gui.GetWindowRect(hwnd)
                return {
                    "title": title,
                    "left": rect[0],
                    "top": rect[1],
                    "width": rect[2] - rect[0],
                    "height": rect[3] - rect[1],
                }
    except Exception:
        pass

    # Attempt 2: PyGetWindow
    if HAS_GW and gw is not None:
        try:
            active = gw.getActiveWindow()
            if active and getattr(active, "title", "").strip():
                return {
                    "title": active.title.strip(),
                    "left": active.left,
                    "top": active.top,
                    "width": active.width,
                    "height": active.height,
                }
        except Exception as e:
            logger.debug(f"[AppManager] getActiveWindow notice: {e}")

    return {"title": "", "left": 0, "top": 0, "width": 0, "height": 0}
