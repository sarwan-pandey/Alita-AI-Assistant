"""
Alita Automation — Application & Window Control (automation_app_control.py)
===========================================================================
Desktop window management, app launching, and GUI automation:
- open_app, close_app, open_folder, open_url
- send_keys, click_position, search_in_app, type_in_app, search_web
- fuzzy_match_app, start menu indexing, UWP protocol routing
"""

from __future__ import annotations

import difflib
import logging
import os
import platform
import shutil
import subprocess
import time
import urllib.parse
from typing import Any, Dict, List, Optional

log = logging.getLogger("Alita.automation_app_control")

APP_MAP = {
    # ── Built-in Windows apps ──
    "notepad":        {"exe": "notepad",     "store": None},
    "calculator":     {"exe": "calc",        "store": None},
    "calc":           {"exe": "calc",        "store": None},
    "paint":          {"exe": "mspaint",     "store": None},
    "explorer":       {"exe": "explorer",    "store": None},
    "file explorer":  {"exe": "explorer",    "store": None},
    "terminal":       {"exe": "wt",          "store": "Windows Terminal"},
    "command prompt": {"exe": "cmd",         "store": None},
    "cmd":            {"exe": "cmd",         "store": None},
    "powershell":     {"exe": "powershell",  "store": None},
    "task manager":   {"exe": "taskmgr",     "store": None},
    "settings":       {"exe": "ms-settings:", "store": None},
    "control panel":  {"exe": "control",     "store": None},
    "snipping tool":  {"exe": "snippingtool", "store": "Snipping Tool"},
    "maps":           {"exe": "bingmaps:",   "store": "Windows Maps"},
    "camera":         {"exe": "microsoft.windows.camera:", "store": None},
    "clock":          {"exe": "ms-clock:",   "store": None},
    "photos":         {"exe": "ms-photos:",  "store": None},
    "mail":           {"exe": "outlookmail:", "store": "Mail"},
    "calendar":       {"exe": "outlookcal:", "store": "Calendar"},
    "weather":        {"exe": "bingweather:", "store": "Weather"},
    "store":          {"exe": "ms-windows-store:", "store": None},
    "microsoft store": {"exe": "ms-windows-store:", "store": None},
    "ms store":       {"exe": "ms-windows-store:", "store": None},
    "app store":      {"exe": "ms-windows-store:", "store": None},
    # ── Microsoft Office ──
    "word":           {"exe": "winword",     "store": "Microsoft Word"},
    "excel":          {"exe": "excel",       "store": "Microsoft Excel"},
    "powerpoint":     {"exe": "powerpnt",    "store": "Microsoft PowerPoint"},
    "outlook":        {"exe": "outlook",     "store": "Microsoft Outlook"},
    "teams":          {"exe": "ms-teams",    "store": "Microsoft Teams"},
    "onenote":        {"exe": "onenote",     "store": "OneNote"},
    # ── Browsers ──
    "chrome":         {"exe": "chrome",      "store": "Google Chrome"},
    "google chrome":  {"exe": "chrome",      "store": "Google Chrome"},
    "firefox":        {"exe": "firefox",     "store": "Firefox"},
    "edge":           {"exe": "msedge",      "store": None},
    "brave":          {"exe": "brave",       "store": "Brave Browser"},
    "opera":          {"exe": "opera",       "store": "Opera Browser"},
    # ── Dev Tools ──
    "vscode":         {"exe": "code",        "store": "Visual Studio Code"},
    "vs code":        {"exe": "code",        "store": "Visual Studio Code"},
    "visual studio":  {"exe": "devenv",      "store": "Visual Studio"},
    "git bash":       {"exe": "git-bash",    "store": "Git"},
    "postman":        {"exe": "postman",     "store": "Postman"},
    # ── Communication ──
    "whatsapp":       {"exe": "whatsapp:",   "store": "WhatsApp"},
    "telegram":       {"exe": "telegram",    "store": "Telegram"},
    "discord":        {"exe": "discord",     "store": "Discord"},
    "zoom":           {"exe": "zoom",        "store": "Zoom"},
    "skype":          {"exe": "skype",       "store": "Skype"},
    "slack":          {"exe": "slack",       "store": "Slack"},
    # ── Media ──
    "spotify":        {"exe": "spotify",     "store": "Spotify"},
    "vlc":            {"exe": "vlc",         "store": "VLC"},
    "itunes":         {"exe": "itunes",      "store": "iTunes"},
    # ── Productivity ──
    "notion":         {"exe": "notion",      "store": "Notion"},
    "obs":            {"exe": "obs64",       "store": "OBS Studio"},
    "obs studio":     {"exe": "obs64",       "store": "OBS Studio"},
    # ── Games / Stores ──
    "steam":          {"exe": "steam",       "store": "Steam"},
    "epic games":     {"exe": "EpicGamesLauncher", "store": "Epic Games"},
}

APP_ALIASES = {
    "browser": "chrome", "web browser": "chrome", "internet": "chrome",
    "coding app": "vscode", "code editor": "vscode", "ide": "vscode",
    "text editor": "notepad", "editor": "notepad",
    "music app": "spotify", "music player": "spotify",
    "video player": "vlc", "media player": "vlc",
    "file manager": "explorer", "files": "explorer",
    "messenger": "whatsapp", "chat app": "whatsapp", "messaging": "whatsapp",
    "email": "outlook", "mail app": "outlook",
    "presentation": "powerpoint", "slides": "powerpoint", "ppt": "powerpoint",
    "spreadsheet": "excel", "sheets": "excel",
    "notes": "notepad", "note taking": "notion",
    "video call": "zoom", "meeting app": "zoom", "video meeting": "zoom",
    "screen recorder": "obs", "streaming": "obs", "recording app": "obs",
    "design tool": "figma", "design app": "figma",
    "api testing": "postman", "api tool": "postman",
    "game store": "steam", "games": "steam",
    "voice chat": "discord", "gaming chat": "discord",
    "office": "word", "docs": "word", "document editor": "word",
    "chorme": "chrome", "gogle": "chrome", "crome": "chrome",
    "vscode": "vscode", "visual studio code": "vscode",
    "wp": "whatsapp", "watsapp": "whatsapp", "what'sapp": "whatsapp",
    "tg": "telegram", "telgram": "telegram",
    "yt": "chrome",
    "insta": "chrome", "instagram": "chrome",
}

SHORTHAND_MAP = {
    "yt": "https://youtube.com", "youtube": "https://youtube.com",
    "insta": "https://instagram.com", "ig": "https://instagram.com", "instagram": "https://instagram.com",
    "fb": "https://facebook.com", "facebook": "https://facebook.com",
    "wp": None, "tg": None,
    "linkedin": "https://linkedin.com", "li": "https://linkedin.com",
    "gh": "https://github.com", "github": "https://github.com",
    "twitter": "https://x.com", "x": "https://x.com",
    "reddit": "https://reddit.com",
}

MOOD_MUSIC_MAP = {
    "happy": "upbeat happy feel good songs playlist",
    "sad": "emotional soulful songs for sad mood",
    "angry": "intense rock metal songs for anger",
    "fear": "calming peaceful music for anxiety",
    "surprise": "trending popular songs right now",
    "disgust": "soothing ambient nature sounds",
    "neutral": "top trending songs today",
    "relaxed": "lofi chill beats study music",
    "chill": "lofi chill beats relaxing music",
    "energetic": "workout gym motivation songs",
    "romantic": "romantic love songs bollywood",
    "party": "party dance songs EDM remix",
    "focused": "deep focus study concentration music",
    "nostalgic": "old classic hits nostalgic songs",
    "lonely": "late night alone vibes songs",
    "excited": "hype high energy celebration songs",
}

FOLDER_ALIASES = {
    "downloads": "~/Downloads", "download": "~/Downloads",
    "desktop": "~/Desktop", "documents": "~/Documents", "document": "~/Documents",
    "pictures": "~/Pictures", "photos": "~/Pictures",
    "videos": "~/Videos", "video": "~/Videos",
    "music": "~/Music", "home": "~", "user": "~",
    "recycle bin": "shell:RecycleBinFolder",
}

APP_SEARCH_SHORTCUTS = {
    "microsoft store": "ctrl+e", "store": "ctrl+e",
    "chrome": "ctrl+l", "google chrome": "ctrl+l",
    "firefox": "ctrl+l", "edge": "ctrl+l", "microsoft edge": "ctrl+l",
    "brave": "ctrl+l", "opera": "ctrl+l",
    "file explorer": "ctrl+e", "explorer": "ctrl+e",
    "settings": "ctrl+e", "ms settings": "ctrl+e",
    "spotify": "ctrl+l", "notepad": "ctrl+h",
    "vscode": "ctrl+shift+p", "vs code": "ctrl+shift+p", "visual studio code": "ctrl+shift+p",
    "outlook": "ctrl+e", "teams": "ctrl+e",
    "discord": "ctrl+k", "telegram": "ctrl+k", "slack": "ctrl+k",
}

_start_menu_cache: Dict[str, str] = {}
_start_menu_cache_time: float = 0.0


def _find_exe_path(exe_name: str) -> Optional[str]:
    """Find executable path via PATH or Windows registry App Paths."""
    found = shutil.which(exe_name)
    if found:
        return found
    if not exe_name.endswith(".exe"):
        found = shutil.which(f"{exe_name}.exe")
        if found:
            return found

    if platform.system() != "Windows":
        return None

    try:
        import winreg
        for exe_try in [exe_name, f"{exe_name}.exe"]:
            try:
                key = winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_try}"
                )
                val, _ = winreg.QueryValueEx(key, None)
                winreg.CloseKey(key)
                if val and os.path.exists(val.strip('"')):
                    return val.strip('"')
            except (FileNotFoundError, OSError):
                pass
    except ImportError:
        pass

    return None


def _is_app_installed(exe_name: str) -> bool:
    """Check if an executable exists on PATH or in registry."""
    return _find_exe_path(exe_name) is not None


def _build_start_menu_cache() -> Dict[str, str]:
    """Build shortcut index for Start Menu."""
    global _start_menu_cache, _start_menu_cache_time
    now = time.time()
    if _start_menu_cache and (now - _start_menu_cache_time) < 300:
        return _start_menu_cache

    cache = {}
    search_dirs = [
        os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                     "Microsoft", "Windows", "Start Menu", "Programs"),
        os.path.join(os.environ.get("APPDATA", ""),
                     "Microsoft", "Windows", "Start Menu", "Programs"),
    ]

    for base_dir in search_dirs:
        if not os.path.isdir(base_dir):
            continue
        for root, dirs, files in os.walk(base_dir):
            for fname in files:
                if fname.lower().endswith(".lnk"):
                    name = fname[:-4].lower()
                    cache[name] = os.path.join(root, fname)

    _start_menu_cache = cache
    _start_menu_cache_time = now
    log.info("Start Menu cache built: %d shortcuts indexed", len(cache))
    return cache


def _search_start_menu(app_name: str) -> Optional[str]:
    """Search Start Menu shortcuts."""
    if platform.system() != "Windows":
        return None

    cache = _build_start_menu_cache()
    query = app_name.lower().strip()

    if query in cache:
        return cache[query]

    candidates = []
    for name, path in cache.items():
        if query in name:
            candidates.append((name, path))

    if candidates:
        candidates.sort(key=lambda x: len(x[0]))
        return candidates[0][1]

    words = query.split()
    for name, path in cache.items():
        if any(name.startswith(w) for w in words if len(w) > 2):
            candidates.append((name, path))

    if candidates:
        candidates.sort(key=lambda x: len(x[0]))
        return candidates[0][1]

    return None


def _verify_app_opened(app_name: str, max_wait_sec: float = 0.8) -> bool:
    """Verify application window appeared."""
    try:
        from engines.screen_context import screen_context
        t_end = time.time() + max_wait_sec
        app_clean = app_name.lower().strip()
        while time.time() < t_end:
            if screen_context.is_app_open(app_clean) or screen_context.is_app_focused(app_clean):
                return True
            time.sleep(0.15)
    except Exception:
        pass
    return False


def _find_uwp_app(app_name: str) -> Optional[str]:
    """Search for UWP package family name."""
    if platform.system() != "Windows":
        return None

    try:
        import re
        sanitized = re.sub(r'[^a-zA-Z0-9\s.\-]', '', app_name).strip()
        if not sanitized:
            return None

        ps_script = (
            f"Get-AppxPackage -Name '*{sanitized}*' "
            f"| Select-Object -First 1 -ExpandProperty PackageFamilyName"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            capture_output=True, text=True, timeout=3
        )
        family_name = result.stdout.strip()
        if family_name and not family_name.startswith("Get-AppxPackage"):
            return f"shell:AppsFolder\\{family_name}!App"
    except (subprocess.TimeoutExpired, Exception):
        pass

    return None


def fuzzy_match_app(query: str) -> Optional[str]:
    """Resolve natural language user prompt to APP_MAP key."""
    query_lower = query.lower().strip()

    if query_lower in APP_MAP:
        return query_lower

    if query_lower in APP_ALIASES:
        return APP_ALIASES[query_lower]

    for alias, app in APP_ALIASES.items():
        if alias in query_lower:
            return app

    for app_key in APP_MAP:
        if app_key in query_lower:
            return app_key

    for app_key in APP_MAP:
        if query_lower in app_key:
            return app_key

    all_names = list(APP_MAP.keys()) + list(APP_ALIASES.keys())
    matches = difflib.get_close_matches(query_lower, all_names, n=1, cutoff=0.7)
    if matches:
        match = matches[0]
        if match in APP_MAP:
            return match
        if match in APP_ALIASES:
            return APP_ALIASES[match]

    return None


def open_app(app_name: str) -> dict:
    """Open application via protocols, registry/PATH, Start Menu, or UWP."""
    try:
        app_lower = app_name.lower().strip()
        app_info = APP_MAP.get(app_lower)

        if app_info:
            exe = app_info["exe"]
            store_query = app_info.get("store")
        else:
            exe = app_lower
            store_query = app_name

        if exe.startswith("ms-") or exe.endswith(":"):
            try:
                subprocess.Popen(["start", "", exe], shell=True)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception:
                pass

        full_path = _find_exe_path(exe)
        if full_path:
            try:
                subprocess.Popen([full_path])
                log.info("[open_app] Method 2 SUCCESS: Popen(%s)", full_path)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception as e2:
                log.warning("[open_app] Method 2 FAILED for '%s': %s", full_path, e2)

        if full_path:
            try:
                subprocess.Popen(f'"{full_path}"', shell=True)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception:
                pass

        lnk_path = _search_start_menu(app_lower)
        if lnk_path:
            try:
                os.startfile(lnk_path)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception as e3:
                log.warning("[open_app] Method 3 FAILED for '%s': %s", lnk_path, e3)

        uwp_uri = _find_uwp_app(app_lower)
        if uwp_uri:
            try:
                subprocess.Popen(["explorer", uwp_uri])
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception as e4:
                log.warning("[open_app] Method 4 FAILED for '%s': %s", uwp_uri, e4)

        if app_info:
            try:
                result = subprocess.run(
                    f'start "" "{exe}"', shell=True,
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0:
                    verified = _verify_app_opened(app_name)
                    return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception:
                pass

        try:
            os.startfile(app_name)
            verified = _verify_app_opened(app_name)
            return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
        except (FileNotFoundError, OSError):
            pass

        try:
            subprocess.Popen(f"start {exe}", shell=True)
            verified = _verify_app_opened(app_name)
            return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
        except Exception:
            pass

        return {
            "status": "not_installed",
            "app": app_name,
            "store_query": store_query,
            "store_url": f"ms-windows-store://search/?query={urllib.parse.quote(store_query)}" if store_query else None,
            "message": f"{app_name} is not installed on this PC.",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def close_app(app_name: str) -> dict:
    """Close application by executable/process name."""
    try:
        app_lower = app_name.lower().strip()
        app_info = APP_MAP.get(app_lower)
        exe = app_info["exe"] if app_info else app_lower

        if platform.system() == "Windows":
            subprocess.run(["taskkill", "/IM", f"{exe}.exe", "/F"],
                           capture_output=True, timeout=5)
        else:
            subprocess.run(["pkill", "-f", exe], capture_output=True, timeout=5)

        return {"status": "success", "action": "closed", "app": app_name}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _get_current_explorer_path() -> str:
    """Read folder path of focused Explorer window."""
    try:
        import pyautogui
        import pyperclip

        old_clip = ""
        try:
            old_clip = pyperclip.paste()
        except Exception:
            pass

        pyautogui.hotkey("ctrl", "l")
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "c")
        time.sleep(0.2)

        current = pyperclip.paste().strip()
        pyautogui.press("escape")
        time.sleep(0.1)

        try:
            pyperclip.copy(old_clip)
        except Exception:
            pass

        if current and os.path.isdir(current):
            return current
        return ""
    except Exception:
        return ""


def _resolve_relative_folder(folder_name: str) -> str:
    """Resolve subfolder relative to open Explorer or home dirs."""
    name = folder_name.strip()
    if not name:
        return ""

    if platform.system() == "Windows":
        current = _get_current_explorer_path()
        if current:
            candidate = os.path.join(current, name)
            if os.path.isdir(candidate):
                return candidate

    home = os.path.expanduser("~")
    search_dirs = ["Downloads", "Desktop", "Documents", "Pictures", "Videos", "Music"]
    for d in search_dirs:
        candidate = os.path.join(home, d, name)
        if os.path.isdir(candidate):
            return candidate

    name_lower = name.lower()
    for d in search_dirs:
        parent = os.path.join(home, d)
        if os.path.isdir(parent):
            try:
                for entry in os.listdir(parent):
                    if entry.lower() == name_lower and os.path.isdir(os.path.join(parent, entry)):
                        return os.path.join(parent, entry)
            except OSError:
                continue

    return ""


def _navigate_existing_explorer(target_path: str) -> bool:
    """Reuse existing File Explorer window via ctypes address bar interaction."""
    import ctypes
    import ctypes.wintypes

    try:
        import pyautogui
        import pyperclip
    except ImportError:
        return False

    user32 = ctypes.windll.user32
    explorer_hwnd = None

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def _enum_callback(hwnd, _lParam):
        nonlocal explorer_hwnd
        if user32.IsWindowVisible(hwnd):
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            if class_buff.value == "CabinetWClass":
                explorer_hwnd = hwnd
                return False
        return True

    try:
        user32.EnumWindows(_enum_callback, 0)
    except Exception:
        pass

    if not explorer_hwnd:
        return False

    try:
        user32.SetForegroundWindow(explorer_hwnd)
    except Exception:
        pass
    time.sleep(0.3)

    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.3)
    pyperclip.copy(target_path)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.2)
    pyautogui.press("enter")
    time.sleep(0.5)

    return True


def open_folder(folder: str) -> dict:
    """Open folder in File Explorer or navigate existing Explorer window."""
    try:
        folder_lower = folder.lower().strip()
        path = FOLDER_ALIASES.get(folder_lower)
        if path and not path.startswith("shell:"):
            path = os.path.expanduser(path)
        elif not path:
            path = os.path.expanduser(folder)

        if path.startswith("shell:"):
            subprocess.Popen(["explorer", path])
            return {"status": "success", "action": "opened_folder", "path": path}

        if not os.path.isdir(path):
            resolved = _resolve_relative_folder(folder)
            if resolved:
                path = resolved
            else:
                return {"status": "error", "error": f"Folder not found: {path}"}

        if platform.system() == "Windows":
            navigated = _navigate_existing_explorer(path)
            if navigated:
                return {"status": "success", "action": "opened_folder",
                        "path": path, "detail": "Navigated existing Explorer window"}
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])

        return {"status": "success", "action": "opened_folder", "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def open_url(url: str) -> dict:
    """Open URL in default web browser."""
    try:
        import webbrowser
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return {"status": "success", "action": "opened_url", "url": url}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def send_keys(keys: str) -> dict:
    """Send keyboard shortcuts to active window."""
    try:
        import pyautogui
        pyautogui.PAUSE = 0.05
        keys_lower = keys.lower().strip()

        KEY_ALIASES = {
            "enter": "enter", "return": "enter", "esc": "escape", "escape": "escape",
            "tab": "tab", "space": "space", "spacebar": "space",
            "backspace": "backspace", "delete": "delete", "del": "delete",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "home": "home", "end": "end", "pageup": "pageup", "pagedown": "pagedown",
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4", "f5": "f5",
            "f6": "f6", "f7": "f7", "f8": "f8", "f9": "f9", "f10": "f10",
            "f11": "f11", "f12": "f12", "ctrl": "ctrl", "control": "ctrl",
            "alt": "alt", "shift": "shift", "win": "win", "windows": "win",
        }

        if "+" in keys_lower:
            parts = [KEY_ALIASES.get(k.strip(), k.strip()) for k in keys_lower.split("+")]
            pyautogui.hotkey(*parts)
            return {"status": "success", "action": "send_keys", "detail": f"Pressed {keys}"}

        key = KEY_ALIASES.get(keys_lower, keys_lower)
        pyautogui.press(key)
        return {"status": "success", "action": "send_keys", "detail": f"Pressed {keys}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def click_position(x: int, y: int, button: str = "left") -> dict:
    """Click coordinate position."""
    try:
        import pyautogui
        pyautogui.click(x, y, button=button)
        return {"status": "success", "action": "click", "detail": f"Clicked {button} at ({x}, {y})"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _type_unicode(text: str):
    """Type text handling unicode via clipboard."""
    try:
        import pyperclip
        import pyautogui
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except Exception:
        import pyautogui
        pyautogui.typewrite(text, interval=0.02)


def search_in_app(app_name: str, query: str) -> dict:
    """Focus search bar in app and execute query."""
    try:
        import pyautogui
        app_lower = app_name.lower().strip()
        open_result = open_app(app_name)
        if open_result.get("status") not in ("success",):
            return open_result

        heavy_apps = ["microsoft store", "store", "spotify", "vscode", "teams"]
        wait_time = 4 if app_lower in heavy_apps else 2.5
        time.sleep(wait_time)

        shortcut = APP_SEARCH_SHORTCUTS.get(app_lower, "ctrl+f")
        if "+" in shortcut:
            pyautogui.hotkey(*shortcut.split("+"))
        else:
            pyautogui.press(shortcut)
        time.sleep(0.3)

        _type_unicode(query)
        time.sleep(0.2)
        pyautogui.press("enter")
        return {"status": "success", "action": "searched_in_app", "app": app_name, "query": query}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def search_web(query: str, engine: str = "google") -> dict:
    """Search web via browser navigation."""
    try:
        import webbrowser
        SEARCH_ENGINES = {
            "google": "https://www.google.com/search?q=",
            "bing": "https://www.bing.com/search?q=",
            "youtube": "https://www.youtube.com/results?search_query=",
            "duckduckgo": "https://duckduckgo.com/?q=",
            "github": "https://github.com/search?q=",
            "amazon": "https://www.amazon.com/s?k=",
            "wikipedia": "https://en.wikipedia.org/wiki/Special:Search?search=",
        }
        engine_lower = engine.lower().strip()
        base_url = SEARCH_ENGINES.get(engine_lower, SEARCH_ENGINES["google"])
        url = base_url + urllib.parse.quote_plus(query)
        webbrowser.open(url)
        return {"status": "success", "action": "searched_web", "query": query, "url": url}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def type_in_app(app_name: str, content: str) -> dict:
    """Type content into target app."""
    try:
        if content.strip():
            try:
                from engines.screen_agent import screen_agent as _sa
                import uuid
                task_id = f"type_{str(uuid.uuid4())[:6]}"
                started = _sa.start_task(task_id, f"write {content} in {app_name}")
                if started:
                    return {
                        "status": "success", "action": "typing_via_screen_agent",
                        "app": app_name, "chars": len(content), "task_id": task_id,
                    }
            except Exception:
                pass

            result = open_app(app_name)
            if result.get("status") != "success":
                return result
            time.sleep(2)
            _type_unicode(content)
            return {"status": "success", "action": "typed_in_app", "app": app_name, "chars": len(content)}

        return {"status": "dictation_mode", "app": app_name}
    except Exception as e:
        return {"status": "error", "error": str(e)}
