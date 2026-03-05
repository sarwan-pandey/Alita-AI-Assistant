"""
Thread 3: Automation Handler — Full system read/write access.

Capabilities:
  - File operations: create, read, write, delete, list, copy, move
  - Folder operations: create, delete, list, copy, move
  - Clipboard: copy text to clipboard
  - App control: open (with install detection), close
  - System info: battery, disk, RAM, processes
  - Shell commands: run terminal commands
  - URL opening: launch websites
  - Screenshot capture
  - Dictation: type into apps
"""

import os
import subprocess
import platform
import logging
import json
import shutil
import threading
import time as _time_module

log = logging.getLogger("alita.automation")


# ─────────────────────────────────────────────────────────────────────────────
# BACKGROUND TASK MANAGER — Non-blocking concurrent task execution
# ─────────────────────────────────────────────────────────────────────────────

class BackgroundTaskManager:
    """
    Manages background tasks (installs, downloads, etc.) in separate threads.
    The user can keep doing other things while tasks run.
    Each task is isolated — multiple tasks don't interfere with each other.
    """

    def __init__(self):
        self._tasks: dict[str, dict] = {}  # task_id → {status, detail, thread, ...}
        self._lock = threading.Lock()

    def start_task(self, task_id: str, target_fn, args=(), description: str = ""):
        """Start a background task in a new thread."""
        with self._lock:
            if task_id in self._tasks and self._tasks[task_id]["status"] == "running":
                return {"status": "already_running",
                        "detail": f"Task '{task_id}' is already running."}

        def _wrapper():
            try:
                with self._lock:
                    self._tasks[task_id]["status"] = "running"
                result = target_fn(*args)
                with self._lock:
                    self._tasks[task_id]["status"] = "completed"
                    self._tasks[task_id]["result"] = result
                    self._tasks[task_id]["end_time"] = _time_module.time()
            except Exception as e:
                with self._lock:
                    self._tasks[task_id]["status"] = "failed"
                    self._tasks[task_id]["error"] = str(e)
                    self._tasks[task_id]["end_time"] = _time_module.time()

        thread = threading.Thread(target=_wrapper, daemon=True)

        with self._lock:
            self._tasks[task_id] = {
                "status": "starting",
                "description": description,
                "thread": thread,
                "start_time": _time_module.time(),
                "end_time": None,
                "result": None,
                "error": None,
            }

        thread.start()
        return {"status": "started", "task_id": task_id, "detail": description}

    def get_status(self, task_id: str = None) -> dict:
        """Get status of a specific task or all tasks."""
        with self._lock:
            if task_id:
                task = self._tasks.get(task_id)
                if not task:
                    return {"status": "not_found", "detail": f"No task '{task_id}'"}
                elapsed = (_time_module.time() - task["start_time"])
                return {
                    "task_id": task_id,
                    "status": task["status"],
                    "description": task["description"],
                    "elapsed_seconds": round(elapsed),
                    "result": task.get("result"),
                    "error": task.get("error"),
                }
            else:
                # Return all active/recent tasks
                summary = []
                for tid, task in self._tasks.items():
                    elapsed = (_time_module.time() - task["start_time"])
                    if elapsed < 600:  # Only show tasks from last 10 min
                        summary.append({
                            "task_id": tid,
                            "status": task["status"],
                            "description": task["description"],
                            "elapsed_seconds": round(elapsed),
                        })
                return {"status": "success", "tasks": summary}

    def cleanup_old(self):
        """Remove completed tasks older than 10 minutes."""
        with self._lock:
            now = _time_module.time()
            to_remove = [
                tid for tid, t in self._tasks.items()
                if t["end_time"] and (now - t["end_time"]) > 600
            ]
            for tid in to_remove:
                del self._tasks[tid]


# Global task manager instance
_task_manager = BackgroundTaskManager()


def install_app(app_name: str) -> dict:
    """
    Install an application — FULLY AUTOMATIC, non-blocking.
    Runs in a background thread so user can keep doing other things.

    Fallback chain (all automatic via winget):
      1. winget install --name "X" (exact name match)
      2. winget install "X" (general search, winget picks best match)
      3. winget install --source msstore "X" (Microsoft Store only)
      4. Microsoft Store UI (opens Store search — user clicks Install)
      5. Web browser (searches official download page)
    """
    app_lower = app_name.lower().strip()
    task_id = f"install_{app_lower.replace(' ', '_')}"

    _CREATE_NO_WINDOW = subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0

    def _try_winget(args: list, label: str) -> dict | None:
        """Try a winget install command, return result dict or None."""
        try:
            log.info("Trying %s for '%s'...", label, app_name)
            result = subprocess.run(
                args, capture_output=True, text=True, timeout=300,
                creationflags=_CREATE_NO_WINDOW
            )
            stdout = result.stdout or ""
            stderr = result.stderr or ""
            combined = stdout + stderr

            if result.returncode == 0 or "Successfully installed" in combined:
                return {
                    "status": "success", "action": "installed",
                    "app": app_name, "method": label,
                    "detail": f"Successfully installed {app_name}"
                }
            elif "already installed" in combined.lower() or "No applicable" in combined:
                return {
                    "status": "success", "action": "already_installed",
                    "app": app_name,
                    "detail": f"{app_name} is already installed"
                }
            else:
                log.info("%s failed for '%s': %s", label, app_name, combined[:150])
                return None
        except subprocess.TimeoutExpired:
            log.warning("%s timed out for '%s'", label, app_name)
            return None
        except (FileNotFoundError, Exception) as e:
            log.warning("%s error: %s", label, e)
            return None

    def _do_install():
        """The actual install logic — runs in a background thread."""

        # ── Strategy 1: winget install --name "X" (exact name) ────────
        r = _try_winget(
            ["winget", "install", "--name", app_name,
             "--accept-package-agreements", "--accept-source-agreements"],
            "winget --name"
        )
        if r: return r

        # ── Strategy 2: winget install "X" (general query) ────────────
        # winget picks the best match from its full repository
        r = _try_winget(
            ["winget", "install", app_name,
             "--accept-package-agreements", "--accept-source-agreements"],
            "winget general"
        )
        if r: return r

        # ── Strategy 3: winget install from Microsoft Store ───────────
        r = _try_winget(
            ["winget", "install", "--source", "msstore", app_name,
             "--accept-package-agreements", "--accept-source-agreements"],
            "winget msstore"
        )
        if r: return r

        # ── Strategy 4: Open Microsoft Store UI search ────────────────
        # (User needs to click Install, but Store handles download)
        try:
            import urllib.parse
            store_query = urllib.parse.quote_plus(app_name)
            store_url = f"ms-windows-store://search/?query={store_query}"
            subprocess.Popen(["start", "", store_url], shell=True)
            return {
                "status": "store_opened", "action": "store_search",
                "app": app_name, "method": "store_ui",
                "detail": f"Couldn't auto-install {app_name} via winget. "
                          f"Opened Microsoft Store — please click 'Get' or 'Install' to download."
            }
        except Exception:
            pass

        # ── Strategy 5: Web browser search for official download ──────
        try:
            import webbrowser
            import urllib.parse
            search_query = urllib.parse.quote_plus(
                f"{app_name} official download site")
            url = f"https://www.google.com/search?q={search_query}"
            webbrowser.open(url)
            return {
                "status": "web_search", "action": "web_download",
                "app": app_name, "method": "browser",
                "detail": f"{app_name} is not available in winget or Store. "
                          f"Opened browser search — please download from the official site."
            }
        except Exception as e:
            return {"status": "error",
                    "error": f"All install methods failed for {app_name}: {e}"}

    # ── Run in background thread — user can keep doing other things ────
    start_result = _task_manager.start_task(
        task_id=task_id,
        target_fn=_do_install,
        description=f"Installing {app_name}"
    )

    if start_result.get("status") == "already_running":
        return {
            "status": "success",
            "action": "install_in_progress",
            "app": app_name,
            "detail": f"{app_name} installation is already in progress. "
                      f"You can keep doing other things while it installs."
        }

    return {
        "status": "success",
        "action": "install_started",
        "app": app_name,
        "detail": f"Installing {app_name} in the background. You can keep doing "
                  f"other things — say 'install status' to check progress."
    }


def uninstall_app(app_name: str) -> dict:
    """Uninstall an application via winget (background thread)."""
    task_id = f"uninstall_{app_name.lower().strip().replace(' ', '_')}"

    def _do_uninstall():
        try:
            result = subprocess.run(
                ["winget", "uninstall", "--name", app_name],
                capture_output=True, text=True, timeout=120,
                creationflags=subprocess.CREATE_NO_WINDOW if platform.system() == "Windows" else 0
            )
            if result.returncode == 0 or "Successfully uninstalled" in result.stdout:
                return {"status": "success", "action": "uninstalled", "app": app_name}
            else:
                return {"status": "error", "error": f"Could not uninstall {app_name}: {result.stderr[:200]}"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    _task_manager.start_task(task_id, _do_uninstall, description=f"Uninstalling {app_name}")
    return {
        "status": "success",
        "action": "uninstall_started",
        "app": app_name,
        "detail": f"Uninstalling {app_name} in the background."
    }


def check_task_status(task_id: str = "") -> dict:
    """Check status of background tasks (installs, downloads, etc.)."""
    _task_manager.cleanup_old()
    return _task_manager.get_status(task_id if task_id else None)


# ─────────────────────────────────────────────────────────────────────────────
# FILE OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def create_file(path: str, content: str = "") -> dict:
    """Create a new file with optional content."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success", "action": "created", "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def read_file(path: str) -> dict:
    """Read a file's contents."""
    try:
        path = os.path.expanduser(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(10000)  # Max 10KB
        return {"status": "success", "path": path, "content": content, "size": os.path.getsize(path)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def write_file(path: str, content: str) -> dict:
    """Write content to a file (overwrite)."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return {"status": "success", "action": "written", "path": path, "bytes": len(content)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def delete_file(path: str) -> dict:
    """Delete a file."""
    try:
        path = os.path.expanduser(path)
        if os.path.isfile(path):
            os.remove(path)
            return {"status": "success", "action": "deleted", "path": path}
        elif os.path.isdir(path):
            shutil.rmtree(path)
            return {"status": "success", "action": "deleted_folder", "path": path}
        else:
            return {"status": "error", "error": f"Not found: {path}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_directory(path: str = "~") -> dict:
    """List files in a directory."""
    try:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return {"status": "error", "error": f"Not a directory: {path}"}
        items = []
        for name in os.listdir(path)[:50]:  # Max 50 items
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            items.append({"name": name, "is_dir": is_dir, "size": size})
        return {"status": "success", "path": path, "count": len(items), "items": items}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def create_folder(path: str) -> dict:
    """Create a new folder."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(path, exist_ok=True)
        return {"status": "success", "action": "folder_created", "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# COPY / MOVE OPERATIONS (with safety checks)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_path(path: str) -> str:
    """Expand and validate a path. Prevent access outside user home."""
    expanded = os.path.abspath(os.path.expanduser(path))
    home = os.path.expanduser("~")
    # Allow access within user home, Desktop, Documents, Downloads, etc.
    # Block system directories like C:\Windows, C:\Program Files
    blocked = ["windows", "program files", "programdata", "system32"]
    path_lower = expanded.lower()
    for b in blocked:
        if b in path_lower and home.lower() not in path_lower:
            raise PermissionError(f"Access to system directory blocked: {expanded}")
    return expanded


def copy_item(source: str, destination: str) -> dict:
    """Copy a file or folder from source to destination."""
    try:
        src = _safe_path(source)
        dst = _safe_path(destination)

        if not os.path.exists(src):
            return {"status": "error", "error": f"Source not found: {src}"}

        # If destination is a directory, put the item inside it
        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))

        if os.path.isfile(src):
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            return {"status": "success", "action": "copied_file",
                    "source": src, "destination": dst,
                    "size": os.path.getsize(dst)}
        elif os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
            return {"status": "success", "action": "copied_folder",
                    "source": src, "destination": dst}
        else:
            return {"status": "error", "error": f"Unknown item type: {src}"}
    except PermissionError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def move_item(source: str, destination: str) -> dict:
    """Move a file or folder from source to destination."""
    try:
        src = _safe_path(source)
        dst = _safe_path(destination)

        if not os.path.exists(src):
            return {"status": "error", "error": f"Source not found: {src}"}

        if os.path.isdir(dst):
            dst = os.path.join(dst, os.path.basename(src))

        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.move(src, dst)
        return {"status": "success", "action": "moved",
                "source": src, "destination": dst}
    except PermissionError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def copy_text_to_clipboard(text: str) -> dict:
    """Copy text to the system clipboard."""
    try:
        import pyperclip
        pyperclip.copy(text)
        _track_clipboard(text)  # Track in clipboard history
        return {"status": "success", "action": "copied_to_clipboard",
                "chars": len(text), "preview": text[:80]}
    except ImportError:
        # Fallback for Windows
        try:
            process = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))
            return {"status": "success", "action": "copied_to_clipboard",
                    "chars": len(text)}
        except Exception as e:
            return {"status": "error", "error": f"Clipboard failed: {e}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# APP CONTROL — Smart launch with install detection
# ─────────────────────────────────────────────────────────────────────────────

# App name → {exe, store_query} mapping (Windows)
# store_query is the Microsoft Store search term (None = built-in app)
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


def _find_exe_path(exe_name: str) -> str | None:
    """
    Find the full path to an executable using FAST methods only:
      1. shutil.which (PATH lookup — instant)
      2. Windows registry App Paths (instant)
    Does NOT scan directories (too slow for real-time voice assistant).
    """
    import shutil as _shutil

    # 1. PATH lookup (instant)
    found = _shutil.which(exe_name)
    if found:
        return found
    if not exe_name.endswith(".exe"):
        found = _shutil.which(f"{exe_name}.exe")
        if found:
            return found

    if platform.system() != "Windows":
        return None

    # 2. Windows Registry — App Paths (instant)
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


# ── Start Menu shortcut search cache ──────────────────────────────────────
_start_menu_cache: dict[str, str] = {}   # lowercase name → .lnk full path
_start_menu_cache_time: float = 0.0


def _build_start_menu_cache() -> dict[str, str]:
    """
    Build a cache of Start Menu shortcuts (.lnk files).
    Covers virtually ALL installed apps (traditional + Store apps).
    Cache is rebuilt at most every 60 seconds.
    """
    global _start_menu_cache, _start_menu_cache_time
    import time as _time
    import glob

    now = _time.time()
    if _start_menu_cache and (now - _start_menu_cache_time) < 60:
        return _start_menu_cache

    cache = {}
    # All Users Start Menu + Current User Start Menu
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
                    name = fname[:-4].lower()  # strip .lnk
                    full_path = os.path.join(root, fname)
                    cache[name] = full_path

    _start_menu_cache = cache
    _start_menu_cache_time = now
    log.info("Start Menu cache built: %d shortcuts indexed", len(cache))
    return cache


def _search_start_menu(app_name: str) -> str | None:
    """
    Search Start Menu shortcuts for an app by name.
    Uses fuzzy matching: exact → contains → word match.
    Returns the .lnk path if found, None otherwise.
    """
    if platform.system() != "Windows":
        return None

    cache = _build_start_menu_cache()
    query = app_name.lower().strip()

    # 1. Exact match
    if query in cache:
        return cache[query]

    # 2. Contains match (e.g. "store" matches "Microsoft Store")
    candidates = []
    for name, path in cache.items():
        if query in name:
            candidates.append((name, path))

    if candidates:
        # Prefer shortest name (most specific match)
        candidates.sort(key=lambda x: len(x[0]))
        return candidates[0][1]

    # 3. Check if any word in query matches start of shortcut name
    words = query.split()
    for name, path in cache.items():
        if any(name.startswith(w) for w in words if len(w) > 2):
            candidates.append((name, path))

    if candidates:
        candidates.sort(key=lambda x: len(x[0]))
        return candidates[0][1]

    return None


def _find_uwp_app(app_name: str) -> str | None:
    """
    Search for a UWP/Store app and return its launch URI.
    Uses PowerShell Get-AppxPackage (fast, ~200ms).
    """
    if platform.system() != "Windows":
        return None

    try:
        # Search installed UWP apps by name
        ps_cmd = (
            f'powershell -NoProfile -Command "'
            f"Get-AppxPackage -Name '*{app_name}*' "
            f"| Select-Object -First 1 -ExpandProperty PackageFamilyName"
            f'"'
        )
        result = subprocess.run(
            ps_cmd, shell=True, capture_output=True, text=True, timeout=3
        )
        family_name = result.stdout.strip()
        if family_name and not family_name.startswith("Get-AppxPackage"):
            # Get the app's launch URI via shell:AppsFolder
            return f"shell:AppsFolder\\{family_name}!App"
    except (subprocess.TimeoutExpired, Exception):
        pass

    return None


def open_app(app_name: str) -> dict:
    """
    Open an application. Tries methods in order of speed & reliability:
      1. Protocol URIs (ms-settings:, whatsapp:, etc.)    — instant
      2. Direct exe path via registry/PATH lookup          — instant
      3. Start Menu shortcut search (.lnk files)           — fast (~50ms)
      4. UWP/Store app search (Get-AppxPackage)            — ~200ms
      5. Shell `start` command with error suppression      — fallback
    Only reports "not installed" if ALL methods fail.
    """
    try:
        app_lower = app_name.lower().strip()
        app_info = APP_MAP.get(app_lower)

        if app_info:
            exe = app_info["exe"]
            store_query = app_info.get("store")
        else:
            exe = app_lower
            store_query = app_name  # Keep original case for store search

        # ── Method 1: Protocol URIs (ms-settings:, bingmaps:, whatsapp:) ──
        if exe.startswith("ms-") or exe.endswith(":"):
            try:
                subprocess.Popen(["start", "", exe], shell=True)
                return {"status": "success", "action": "opened", "app": app_name}
            except Exception:
                pass

        # ── Method 2: Direct exe path via registry/PATH ──
        full_path = _find_exe_path(exe)
        if full_path:
            try:
                subprocess.Popen([full_path])
                return {"status": "success", "action": "opened", "app": app_name}
            except Exception:
                pass

        # ── Method 3: Start Menu shortcut search ──
        # This finds virtually ALL installed apps (traditional + Store apps)
        lnk_path = _search_start_menu(app_lower)
        if lnk_path:
            try:
                os.startfile(lnk_path)
                return {"status": "success", "action": "opened", "app": app_name}
            except Exception:
                pass

        # ── Method 4: UWP / Store app search ──
        uwp_uri = _find_uwp_app(app_lower)
        if uwp_uri:
            try:
                subprocess.Popen(["explorer", uwp_uri])
                return {"status": "success", "action": "opened", "app": app_name}
            except Exception:
                pass

        # ── Method 5: Shell `start` with validation ──
        # Only try this if we have a mapped exe (not raw user input)
        if app_info:
            try:
                result = subprocess.run(
                    f'start "" "{exe}"', shell=True,
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0:
                    return {"status": "success", "action": "opened", "app": app_name}
            except (subprocess.TimeoutExpired, Exception):
                pass

        # ── Method 6: Try the original app name as startfile ──
        # Works for some apps registered with Windows
        try:
            os.startfile(app_name)
            return {"status": "success", "action": "opened", "app": app_name}
        except (FileNotFoundError, OSError):
            pass

        # ── All methods failed — truly not found ──
        if store_query and platform.system() == "Windows":
            store_url = f"ms-windows-store://search/?query={store_query}"
            return {
                "status": "not_installed",
                "action": "app_not_found",
                "app": app_name,
                "store_url": store_url,
                "store_query": store_query,
            }
        return {"status": "error", "error": f"Could not open {app_name}. It may not be installed."}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# Well-known folder aliases → actual paths
FOLDER_ALIASES = {
    "downloads":  "~/Downloads",
    "download":   "~/Downloads",
    "desktop":    "~/Desktop",
    "documents":  "~/Documents",
    "document":   "~/Documents",
    "pictures":   "~/Pictures",
    "photos":     "~/Pictures",
    "videos":     "~/Videos",
    "video":      "~/Videos",
    "music":      "~/Music",
    "home":       "~",
    "user":       "~",
    "recycle bin": "shell:RecycleBinFolder",
}


def open_folder(folder: str) -> dict:
    """
    Open a folder in File Explorer.
    Resolves well-known aliases like 'downloads', 'desktop', etc.
    """
    try:
        folder_lower = folder.lower().strip()

        # 1. Check well-known aliases
        path = FOLDER_ALIASES.get(folder_lower)
        if path and not path.startswith("shell:"):
            path = os.path.expanduser(path)
        elif not path:
            # 2. Try as a literal path
            path = os.path.expanduser(folder)

        # For shell: paths (e.g. Recycle Bin), just launch directly
        if path.startswith("shell:"):
            subprocess.Popen(["explorer", path])
            return {"status": "success", "action": "opened_folder", "path": path}

        if not os.path.isdir(path):
            return {"status": "error",
                    "error": f"Folder not found: {path}"}

        # Open in File Explorer (Windows)
        if platform.system() == "Windows":
            os.startfile(path)
        else:
            subprocess.Popen(["xdg-open", path])

        return {"status": "success", "action": "opened_folder", "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def close_app(app_name: str) -> dict:
    """Close an application by name."""
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


def open_url(url: str) -> dict:
    """Open a URL in the default browser."""
    try:
        import webbrowser
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        webbrowser.open(url)
        return {"status": "success", "action": "opened_url", "url": url}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def send_keys(keys: str) -> dict:
    """
    Send keyboard shortcut(s) to the active application.
    Supports combos like 'ctrl+n', 'ctrl+shift+s', 'alt+f4'
    and single keys like 'enter', 'tab', 'escape', 'f5'.
    Universal — works in ANY app.
    """
    try:
        import pyautogui
        import time as _time
        pyautogui.PAUSE = 0.05

        keys_lower = keys.lower().strip()

        # Map common names to pyautogui key names
        KEY_ALIASES = {
            "enter": "enter", "return": "enter",
            "esc": "escape", "escape": "escape",
            "tab": "tab", "space": "space", "spacebar": "space",
            "backspace": "backspace", "delete": "delete", "del": "delete",
            "up": "up", "down": "down", "left": "left", "right": "right",
            "home": "home", "end": "end",
            "pageup": "pageup", "page up": "pageup",
            "pagedown": "pagedown", "page down": "pagedown",
            "f1": "f1", "f2": "f2", "f3": "f3", "f4": "f4",
            "f5": "f5", "f6": "f6", "f7": "f7", "f8": "f8",
            "f9": "f9", "f10": "f10", "f11": "f11", "f12": "f12",
            "ctrl": "ctrl", "control": "ctrl",
            "alt": "alt", "shift": "shift",
            "win": "win", "windows": "win", "super": "win",
            "printscreen": "printscreen", "prtsc": "printscreen",
        }

        # Handle combos like "ctrl+n", "ctrl+shift+s"
        if "+" in keys_lower:
            parts = [KEY_ALIASES.get(k.strip(), k.strip()) for k in keys_lower.split("+")]
            pyautogui.hotkey(*parts)
            return {"status": "success", "action": "send_keys",
                    "detail": f"Pressed {keys}"}

        # Single key
        key = KEY_ALIASES.get(keys_lower, keys_lower)
        pyautogui.press(key)
        return {"status": "success", "action": "send_keys",
                "detail": f"Pressed {keys}"}

    except ImportError:
        return {"status": "error", "error": "pyautogui not installed. Run: pip install pyautogui"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def click_position(x: int, y: int, button: str = "left") -> dict:
    """Click at a specific screen position."""
    try:
        import pyautogui
        pyautogui.click(x, y, button=button)
        return {"status": "success", "action": "click",
                "detail": f"Clicked {button} at ({x}, {y})"}
    except ImportError:
        return {"status": "error", "error": "pyautogui not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Per-app search shortcut mappings ─────────────────────────────────────
# Maps app names to the keyboard shortcut that focuses their search bar
APP_SEARCH_SHORTCUTS = {
    "microsoft store": "ctrl+e",
    "store":           "ctrl+e",
    "chrome":          "ctrl+l",
    "google chrome":   "ctrl+l",
    "firefox":         "ctrl+l",
    "edge":            "ctrl+l",
    "microsoft edge":  "ctrl+l",
    "brave":           "ctrl+l",
    "opera":           "ctrl+l",
    "file explorer":   "ctrl+e",
    "explorer":        "ctrl+e",
    "settings":        "ctrl+e",
    "ms settings":     "ctrl+e",
    "spotify":         "ctrl+l",
    "notepad":         "ctrl+h",   # Find and replace
    "vscode":          "ctrl+shift+p",
    "vs code":         "ctrl+shift+p",
    "visual studio code": "ctrl+shift+p",
    "outlook":         "ctrl+e",
    "teams":           "ctrl+e",
    "discord":         "ctrl+k",
    "telegram":        "ctrl+k",
    "slack":           "ctrl+k",
}
# Default fallback: try Ctrl+F (universal find), then Ctrl+E
DEFAULT_SEARCH_SHORTCUTS = ["ctrl+e", "ctrl+f"]


def search_in_app(app_name: str, query: str) -> dict:
    """
    Compound action: Opens an app, waits for it to load,
    focuses the search bar, types the query, and presses Enter.
    Works with any app — uses per-app shortcut mappings
    with a universal fallback.
    """
    try:
        import pyautogui
        import time as _time

        app_lower = app_name.lower().strip()

        # ── Step 1: Open the app ──
        open_result = open_app(app_name)
        if open_result.get("status") not in ("success",):
            return open_result  # Propagate error (e.g. not installed)

        # ── Step 2: Wait for app to load ──
        # Longer wait for heavier apps
        heavy_apps = ["microsoft store", "store", "spotify", "vscode",
                      "vs code", "visual studio code", "teams"]
        wait_time = 4 if app_lower in heavy_apps else 2.5
        _time.sleep(wait_time)

        # ── Step 3: Focus the search bar ──
        shortcut = APP_SEARCH_SHORTCUTS.get(app_lower)
        if shortcut:
            send_keys(shortcut)
            _time.sleep(0.5)
        else:
            # Try common search shortcuts
            for sc in DEFAULT_SEARCH_SHORTCUTS:
                send_keys(sc)
                _time.sleep(0.3)
                break  # Just try the first one

        # ── Step 4: Clear any existing text and type query ──
        pyautogui.hotkey("ctrl", "a")
        _time.sleep(0.1)
        pyautogui.typewrite(query, interval=0.02) if query.isascii() else _type_unicode(query)
        _time.sleep(0.3)

        # ── Step 5: Press Enter to search ──
        pyautogui.press("enter")

        return {
            "status": "success",
            "action": "search_in_app",
            "app": app_name,
            "query": query,
            "detail": f"Opened {app_name} and searched for '{query}'"
        }

    except ImportError:
        return {"status": "error", "error": "pyautogui not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _type_unicode(text: str):
    """Type unicode text using clipboard (for non-ASCII chars like Hindi)."""
    try:
        import pyperclip
        import pyautogui
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        import pyautogui
        pyautogui.typewrite(text, interval=0.02)


def search_web(query: str, engine: str = "google") -> dict:
    """
    Search the web — opens browser and goes directly to search results.
    No need to open browser first, type in address bar, etc.
    """
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

        import urllib.parse
        url = base_url + urllib.parse.quote_plus(query)
        webbrowser.open(url)

        return {
            "status": "success",
            "action": "search_web",
            "query": query,
            "engine": engine,
            "url": url,
            "detail": f"Searched for '{query}' on {engine}"
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def search_windows(query: str) -> dict:
    """
    Open Windows Start Menu search and type a query.
    Finds apps, files, settings, etc. through Windows Search.
    """
    try:
        import pyautogui
        import time as _time

        # Press Windows key to open Start Menu search
        pyautogui.press("win")
        _time.sleep(0.8)

        # Type the search query
        if query.isascii():
            pyautogui.typewrite(query, interval=0.03)
        else:
            _type_unicode(query)

        return {
            "status": "success",
            "action": "search_windows",
            "query": query,
            "detail": f"Opened Windows search for '{query}'"
        }
    except ImportError:
        return {"status": "error", "error": "pyautogui not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM INFO
# ─────────────────────────────────────────────────────────────────────────────

def get_system_info() -> dict:
    """Get basic system information."""
    try:
        import psutil
        info = {
            "os": platform.system() + " " + platform.release(),
            "hostname": platform.node(),
            "cpu_percent": psutil.cpu_percent(interval=0.5),
            "ram_total_gb": round(psutil.virtual_memory().total / (1024**3), 1),
            "ram_used_percent": psutil.virtual_memory().percent,
            "disk_total_gb": round(psutil.disk_usage('/').total / (1024**3), 1),
            "disk_used_percent": psutil.disk_usage('/').percent,
        }
        return {"status": "success", **info}
    except ImportError:
        return {"status": "error", "error": "psutil not installed. Run: pip install psutil"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_battery() -> dict:
    """Get battery status."""
    try:
        import psutil
        battery = psutil.sensors_battery()
        if battery:
            return {
                "status": "success",
                "percent": battery.percent,
                "plugged_in": battery.power_plugged,
                "time_left": str(battery.secsleft // 60) + " minutes" if battery.secsleft > 0 else "calculating",
            }
        return {"status": "success", "info": "No battery detected (desktop PC)"}
    except ImportError:
        return {"status": "error", "error": "psutil not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_running_processes(limit: int = 15) -> dict:
    """List top running processes by memory usage."""
    try:
        import psutil
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get("memory_percent", 0), reverse=True)
        return {"status": "success", "count": len(procs), "top": procs[:limit]}
    except ImportError:
        return {"status": "error", "error": "psutil not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_shell_command(command: str) -> dict:
    """Run a shell command and return output."""
    try:
        result = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=15
        )
        return {
            "status": "success",
            "command": command,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500] if result.stderr else "",
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Command timed out (15s limit)"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def take_screenshot(save_path: str = "") -> dict:
    """Take a screenshot and save it."""
    try:
        from PIL import ImageGrab
        if not save_path:
            save_path = os.path.expanduser("~/Desktop/screenshot.png")
        img = ImageGrab.grab()
        img.save(save_path)
        return {"status": "success", "action": "screenshot_saved", "path": save_path}
    except ImportError:
        return {"status": "error", "error": "Pillow not installed. Run: pip install Pillow"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def type_in_app(app_name: str, content: str) -> dict:
    """
    Open an app for dictation / typing.
    If content is provided, types it immediately.
    If content is empty, signals dictation mode (frontend will send speech as dictation).
    """
    try:
        import time as _time

        # 1. Open the app
        result = open_app(app_name)
        if result.get("status") != "success":
            return result

        # 2. Wait for the app to open and gain focus
        _time.sleep(2)

        # 3. If content is provided, type it now
        if content.strip():
            try:
                import pyautogui
                pyautogui.PAUSE = 0.05
                if content.isascii():
                    pyautogui.typewrite(content, interval=0.02)
                else:
                    import pyperclip
                    pyperclip.copy(content)
                    pyautogui.hotkey("ctrl", "v")
                return {
                    "status": "success",
                    "action": "typed_in_app",
                    "app": app_name,
                    "chars": len(content),
                }
            except ImportError:
                return {"status": "error", "error": "pyautogui not installed. Run: pip install pyautogui"}

        # 4. No content = enter dictation mode (user will dictate)
        return {
            "status": "success",
            "action": "dictation_ready",
            "app": app_name,
            "dictation_mode": True,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM SHORTCUTS
# ─────────────────────────────────────────────────────────────────────────────

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
            # Try to set to a specific percentage
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
            # Fallback: use nircmd if available
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


def set_brightness(level: str) -> dict:
    """Set, increase, or decrease screen brightness."""
    try:
        action = level.lower().strip()
        if action in ("up", "increase"):
            pct = 80
        elif action in ("down", "decrease", "dim"):
            pct = 30
        else:
            try:
                pct = int(action.replace("%", ""))
                pct = max(0, min(100, pct))
            except ValueError:
                pct = 70
        subprocess.run(
            ["powershell", "-Command",
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods)"
             f".WmiSetBrightness(1,{pct})"],
            capture_output=True, timeout=5
        )
        return {"status": "success", "action": "set_brightness", "detail": f"Brightness set to {pct}%"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def toggle_dark_mode() -> dict:
    """Toggle Windows dark/light mode."""
    try:
        # Read current mode
        result = subprocess.run(
            ["reg", "query",
             r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
             "/v", "AppsUseLightTheme"],
            capture_output=True, text=True, timeout=5
        )
        # If current is light (1), switch to dark (0); if dark (0), switch to light (1)
        current_light = "0x1" in result.stdout
        new_val = "0" if current_light else "1"
        mode_name = "Dark" if current_light else "Light"

        for key in ["AppsUseLightTheme", "SystemUsesLightTheme"]:
            subprocess.run(
                ["reg", "add",
                 r"HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
                 "/v", key, "/t", "REG_DWORD", "/d", new_val, "/f"],
                capture_output=True, timeout=5
            )
        return {"status": "success", "action": "toggle_dark_mode", "detail": f"Switched to {mode_name} Mode"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def lock_screen() -> dict:
    """Lock the computer screen."""
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return {"status": "success", "action": "lock_screen", "detail": "Screen locked"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def empty_recycle_bin() -> dict:
    """Empty the Windows recycle bin."""
    try:
        import ctypes
        # SHEmptyRecycleBin(hwnd, path, flags)
        # SHERB_NOCONFIRMATION = 0x00000001 | SHERB_NOPROGRESSUI = 0x00000002 | SHERB_NOSOUND = 0x00000004
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x0007)
        return {"status": "success", "action": "empty_recycle_bin", "detail": "Recycle bin emptied"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def toggle_wifi(action: str = "toggle") -> dict:
    """Toggle, enable, or disable WiFi."""
    try:
        act = action.lower().strip()
        if act in ("on", "enable"):
            cmd = 'netsh interface set interface "Wi-Fi" admin=enable'
        elif act in ("off", "disable"):
            cmd = 'netsh interface set interface "Wi-Fi" admin=disable'
        else:
            # Toggle: check current and flip
            result = subprocess.run(
                ["netsh", "interface", "show", "interface", "Wi-Fi"],
                capture_output=True, text=True, timeout=5
            )
            if "Enabled" in result.stdout or "Connected" in result.stdout:
                cmd = 'netsh interface set interface "Wi-Fi" admin=disable'
                act = "off"
            else:
                cmd = 'netsh interface set interface "Wi-Fi" admin=enable'
                act = "on"
        subprocess.run(cmd, shell=True, capture_output=True, timeout=10)
        return {"status": "success", "action": "toggle_wifi",
                "detail": f"WiFi turned {act}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# SMART SEARCH
# ─────────────────────────────────────────────────────────────────────────────

def search_files(query: str, file_type: str = "", days: int = 0) -> dict:
    """Search for files by name, type, and modification time."""
    try:
        import fnmatch
        from datetime import datetime, timedelta

        home = os.path.expanduser("~")
        search_dirs = [
            os.path.join(home, "Desktop"),
            os.path.join(home, "Documents"),
            os.path.join(home, "Downloads"),
            os.path.join(home, "Pictures"),
            os.path.join(home, "Videos"),
        ]

        query_lower = query.lower()
        ext_filter = None
        if file_type:
            ft = file_type.lower().strip(".")
            ext_map = {
                "pdf": [".pdf"], "document": [".doc", ".docx", ".txt", ".rtf"],
                "image": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
                "photo": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"],
                "video": [".mp4", ".avi", ".mkv", ".mov", ".wmv"],
                "audio": [".mp3", ".wav", ".flac", ".aac", ".ogg"],
                "excel": [".xls", ".xlsx", ".csv"],
                "ppt": [".ppt", ".pptx"],
            }
            ext_filter = ext_map.get(ft, [f".{ft}"])

        time_cutoff = None
        if days > 0:
            time_cutoff = (datetime.now() - timedelta(days=days)).timestamp()

        results = []
        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                # Skip hidden/system directories
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                # Limit depth to 3 levels
                depth = root.replace(search_dir, '').count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for fname in files:
                    fpath = os.path.join(root, fname)
                    # Name match
                    if query_lower and query_lower not in fname.lower():
                        continue
                    # Extension filter
                    if ext_filter:
                        _, ext = os.path.splitext(fname)
                        if ext.lower() not in ext_filter:
                            continue
                    # Time filter
                    if time_cutoff:
                        try:
                            if os.path.getmtime(fpath) < time_cutoff:
                                continue
                        except OSError:
                            continue
                    results.append({
                        "name": fname,
                        "path": fpath,
                        "size": os.path.getsize(fpath) if os.path.exists(fpath) else 0,
                    })
                    if len(results) >= 15:
                        break
                if len(results) >= 15:
                    break
            if len(results) >= 15:
                break

        return {
            "status": "success",
            "action": "search_files",
            "query": query,
            "count": len(results),
            "files": results,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# MUSIC CONTROL
# ─────────────────────────────────────────────────────────────────────────────

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

        # Simulate key press
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)

        return {"status": "success", "action": "music_control",
                "detail": f"Media action: {act}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def open_music(query: str) -> dict:
    """Play music on YouTube — opens search, waits, clicks first video result."""
    try:
        import webbrowser
        import urllib.parse
        import time as _time

        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
        webbrowser.open(search_url)

        # Wait for page to load, then click the first video
        _time.sleep(3.5)

        try:
            import pyautogui
            # Tab through YouTube UI to reach first video result and press Enter
            # The first video result is typically reachable after a few Tab presses
            pyautogui.press("tab")
            _time.sleep(0.3)
            pyautogui.press("enter")
        except ImportError:
            pass  # pyautogui not installed — search page is still open

        return {"status": "success", "action": "open_music",
                "detail": f"Playing '{query}' on YouTube"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# SMART REMINDERS
# ─────────────────────────────────────────────────────────────────────────────

_REMINDERS_DIR = os.path.join(".", "data", "reminders")


def _load_reminders(user_id: str) -> list:
    """Load reminders for a user from JSON file."""
    os.makedirs(_REMINDERS_DIR, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)
    path = os.path.join(_REMINDERS_DIR, f"{safe_id}.json")
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return []


def _save_reminders(user_id: str, reminders: list):
    """Save reminders to JSON file."""
    os.makedirs(_REMINDERS_DIR, exist_ok=True)
    safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)
    path = os.path.join(_REMINDERS_DIR, f"{safe_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reminders, f, indent=2, ensure_ascii=False)


def set_reminder(user_id: str, text: str, time_str: str) -> dict:
    """Set a reminder with natural time parsing."""
    import time as _time
    from datetime import datetime, timedelta

    try:
        now = datetime.now()
        remind_at = None
        time_lower = time_str.lower().strip()

        # Parse common time patterns
        if "minute" in time_lower:
            import re
            match = re.search(r"(\d+)", time_lower)
            mins = int(match.group(1)) if match else 5
            remind_at = now + timedelta(minutes=mins)
        elif "hour" in time_lower:
            import re
            match = re.search(r"(\d+)", time_lower)
            hrs = int(match.group(1)) if match else 1
            remind_at = now + timedelta(hours=hrs)
        elif "tomorrow" in time_lower:
            remind_at = now + timedelta(days=1)
            remind_at = remind_at.replace(hour=9, minute=0, second=0)
        else:
            # Try to parse HH:MM or "5pm" style
            import re
            time_match = re.search(r"(\d{1,2}):?(\d{2})?\s*(am|pm)?", time_lower)
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                ampm = time_match.group(3)
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                remind_at = now.replace(hour=hour, minute=minute, second=0)
                if remind_at <= now:
                    remind_at += timedelta(days=1)

        if not remind_at:
            remind_at = now + timedelta(minutes=30)  # Default: 30 min

        reminder = {
            "text": text,
            "set_at": _time.time(),
            "remind_at": remind_at.timestamp(),
            "remind_at_iso": remind_at.strftime("%Y-%m-%d %I:%M %p"),
            "done": False,
        }

        reminders = _load_reminders(user_id)
        reminders.append(reminder)
        _save_reminders(user_id, reminders)

        return {
            "status": "success",
            "action": "set_reminder",
            "text": text,
            "remind_at": reminder["remind_at_iso"],
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_reminders(user_id: str) -> dict:
    """List active reminders for a user."""
    import time as _time
    reminders = _load_reminders(user_id)
    active = [r for r in reminders if not r.get("done", False)]
    return {
        "status": "success",
        "action": "list_reminders",
        "count": len(active),
        "reminders": [
            {"text": r["text"], "remind_at": r.get("remind_at_iso", "unknown")}
            for r in active
        ],
    }


def delete_reminder(user_id: str, index: int = -1) -> dict:
    """Delete a reminder by index (1-based), or last one if index=-1."""
    reminders = _load_reminders(user_id)
    active = [r for r in reminders if not r.get("done", False)]
    if not active:
        return {"status": "error", "error": "No active reminders to delete"}
    try:
        if index == -1:
            idx = len(active) - 1
        else:
            idx = index - 1  # 1-based to 0-based
        if 0 <= idx < len(active):
            deleted = active[idx]
            deleted["done"] = True
            _save_reminders(user_id, reminders)
            return {"status": "success", "action": "delete_reminder",
                    "detail": f"Deleted: {deleted['text']}"}
        return {"status": "error", "error": f"Invalid reminder number: {index}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# CLIPBOARD HISTORY
# ─────────────────────────────────────────────────────────────────────────────

_clipboard_history: list[str] = []
_CLIPBOARD_MAX = 20


def _track_clipboard(text: str):
    """Add an entry to clipboard history (called internally)."""
    if text and text not in _clipboard_history[:3]:  # Avoid duplicates
        _clipboard_history.insert(0, text)
        if len(_clipboard_history) > _CLIPBOARD_MAX:
            _clipboard_history.pop()


def get_clipboard_history(n: int = 5) -> dict:
    """Return the last N clipboard entries."""
    entries = _clipboard_history[:n]
    return {
        "status": "success",
        "action": "clipboard_history",
        "count": len(entries),
        "entries": entries if entries else ["No clipboard history yet."],
    }


# ─────────────────────────────────────────────────────────────────────────────
# HABIT TRACKER
# ─────────────────────────────────────────────────────────────────────────────

_HABITS_DIR = os.path.join(".", "data", "habits")


def log_habit(user_id: str, habit: str) -> dict:
    """Log a habit action (e.g. 'drank water', 'exercised')."""
    import time as _time
    from datetime import datetime
    try:
        os.makedirs(_HABITS_DIR, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)
        path = os.path.join(_HABITS_DIR, f"{safe_id}.json")

        habits = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    habits = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        entry = {
            "habit": habit,
            "timestamp": _time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%I:%M %p"),
        }
        habits.append(entry)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(habits, f, indent=2, ensure_ascii=False)

        # Count today's occurrences
        today = datetime.now().strftime("%Y-%m-%d")
        today_count = sum(1 for h in habits if h.get("date") == today and h.get("habit") == habit)

        return {
            "status": "success",
            "action": "log_habit",
            "habit": habit,
            "today_count": today_count,
            "detail": f"Logged '{habit}' — {today_count} time(s) today",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_habit_stats(user_id: str, days: int = 7) -> dict:
    """Get habit statistics for the last N days."""
    from datetime import datetime, timedelta
    try:
        safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)
        path = os.path.join(_HABITS_DIR, f"{safe_id}.json")

        if not os.path.exists(path):
            return {"status": "success", "action": "habit_stats",
                    "detail": "No habits logged yet. Start by saying something like 'I drank water'."}

        with open(path, "r", encoding="utf-8") as f:
            habits = json.load(f)

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = [h for h in habits if h.get("date", "") >= cutoff]

        # Group by habit name
        stats = {}
        for h in recent:
            name = h.get("habit", "unknown")
            if name not in stats:
                stats[name] = {"count": 0, "dates": set()}
            stats[name]["count"] += 1
            stats[name]["dates"].add(h.get("date", ""))

        summary = []
        for name, data in stats.items():
            streak = len(data["dates"])
            summary.append({
                "habit": name,
                "total": data["count"],
                "active_days": streak,
                "streak": f"{streak}/{days} days",
            })

        return {
            "status": "success",
            "action": "habit_stats",
            "period_days": days,
            "habits": summary,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# MOOD JOURNAL
# ─────────────────────────────────────────────────────────────────────────────

_MOOD_DIR = os.path.join(".", "data", "mood")


def save_mood_entry(user_id: str, emotion: str, confidence: float = 0.0):
    """Auto-save a mood entry (called from SER in main.py)."""
    import time as _time
    from datetime import datetime
    try:
        os.makedirs(_MOOD_DIR, exist_ok=True)
        safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)
        path = os.path.join(_MOOD_DIR, f"{safe_id}.json")

        moods = []
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    moods = json.load(f)
            except (json.JSONDecodeError, OSError):
                pass

        moods.append({
            "emotion": emotion,
            "confidence": round(confidence, 2),
            "timestamp": _time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%I:%M %p"),
        })

        # Keep last 500 entries
        moods = moods[-500:]

        with open(path, "w", encoding="utf-8") as f:
            json.dump(moods, f, indent=2, ensure_ascii=False)
    except Exception:
        pass  # Silent — this is auto-logging


def get_mood_journal(user_id: str, days: int = 7) -> dict:
    """Get mood trends for the last N days."""
    from datetime import datetime, timedelta
    try:
        safe_id = "".join(c if c.isalnum() or c in "_-" else "_" for c in user_id)
        path = os.path.join(_MOOD_DIR, f"{safe_id}.json")

        if not os.path.exists(path):
            return {"status": "success", "action": "mood_journal",
                    "detail": "No mood data yet. I'll start tracking your emotions as we talk!"}

        with open(path, "r", encoding="utf-8") as f:
            moods = json.load(f)

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        recent = [m for m in moods if m.get("date", "") >= cutoff]

        # Count emotions
        emotion_counts = {}
        for m in recent:
            emo = m.get("emotion", "neutral")
            emotion_counts[emo] = emotion_counts.get(emo, 0) + 1

        # Find dominant emotion
        dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"

        return {
            "status": "success",
            "action": "mood_journal",
            "period_days": days,
            "total_entries": len(recent),
            "emotion_breakdown": emotion_counts,
            "dominant_mood": dominant,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# SCREEN READER (OCR)
# ─────────────────────────────────────────────────────────────────────────────

def read_screen() -> dict:
    """Take a screenshot and extract text via OCR."""
    try:
        from PIL import ImageGrab
        import tempfile

        # Capture screen
        screenshot = ImageGrab.grab()
        tmp_path = os.path.join(tempfile.gettempdir(), "alita_screen_ocr.png")
        screenshot.save(tmp_path)

        # Try OCR with pytesseract
        try:
            import pytesseract
            text = pytesseract.image_to_string(screenshot)
            if text.strip():
                # Truncate to avoid overwhelming the LLM
                text = text.strip()[:2000]
                return {
                    "status": "success",
                    "action": "read_screen",
                    "text": text,
                    "detail": f"Extracted {len(text)} characters from screen",
                }
        except ImportError:
            pass

        # Fallback: just report screenshot taken
        return {
            "status": "success",
            "action": "read_screen",
            "text": "(OCR not available — pytesseract not installed. Screenshot saved.)",
            "screenshot_path": tmp_path,
            "detail": "Screenshot captured but OCR is not available. Install pytesseract for text extraction.",
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# VISUAL CONTEXT AUTOMATION (UI Automation API)
# Uses Windows Accessibility Tree — instant, no screenshots needed.
# ─────────────────────────────────────────────────────────────────────────────

def _get_foreground_window_info() -> dict:
    """Get the foreground window handle and title via ctypes."""
    import ctypes
    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return {"hwnd": hwnd, "title": buf.value}


def _get_ui_elements(max_elements: int = 80) -> list[dict]:
    """
    Query the Windows UI Automation accessibility tree for the foreground window.
    Returns a list of clickable/visible UI elements with name, type, and coordinates.
    Runs in ~50–100ms — no screenshots or OCR needed.
    """
    try:
        from pywinauto import Desktop

        desktop = Desktop(backend="uia")
        try:
            fg = desktop.window(active_only=True)
            fg_wrapper = fg.wrapper_object()
        except Exception:
            # Fallback: get foreground via ctypes
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            from pywinauto import Application
            app = Application(backend="uia").connect(handle=hwnd)
            fg_wrapper = app.window(handle=hwnd).wrapper_object()

        elements = []
        # Collect interactive elements from the control tree
        try:
            all_children = fg_wrapper.descendants()
        except Exception:
            all_children = []

        CLICKABLE_TYPES = {
            "Button", "MenuItem", "ListItem", "TreeItem", "TabItem",
            "Hyperlink", "Link", "CheckBox", "RadioButton", "ComboBox",
            "Text", "Edit", "Pane", "Group", "Header", "HeaderItem",
        }

        for child in all_children:
            try:
                ctrl_type = child.element_info.control_type or ""
                name = (child.element_info.name or "").strip()
                if not name or len(name) < 2 or len(name) > 120:
                    continue
                if ctrl_type not in CLICKABLE_TYPES:
                    continue

                # Get bounding rectangle
                rect = child.element_info.rectangle
                if rect.width() < 5 or rect.height() < 5:
                    continue  # Too small / invisible

                cx = rect.left + rect.width() // 2
                cy = rect.top + rect.height() // 2

                elements.append({
                    "name": name,
                    "type": ctrl_type,
                    "x": cx,
                    "y": cy,
                    "w": rect.width(),
                    "h": rect.height(),
                })

                if len(elements) >= max_elements:
                    break
            except Exception:
                continue

        return elements
    except ImportError:
        log.warning("pywinauto not available — cannot enumerate UI elements")
        return []
    except Exception as e:
        log.warning("UI element enumeration failed: %s", e)
        return []


def navigate_ui(target: str, settings=None) -> dict:
    """
    Navigate to a UI element on the current screen using the Windows Accessibility Tree.
    
    1. Enumerates all visible UI elements (~50ms)
    2. Uses LLM to pick the best match for the user's target
    3. Clicks the matched element
    4. Falls back to fuzzy text matching if LLM is unavailable
    5. Scrolls + retries up to 3 times if not found
    """
    import time as _t
    import pyautogui

    target_lower = target.lower().strip()
    if not target_lower:
        return {"status": "error", "error": "No navigation target specified"}

    window_info = _get_foreground_window_info()
    log.info("[navigate_ui] Target: '%s' | Window: '%s'", target, window_info.get("title", "?"))

    for attempt in range(3):
        elements = _get_ui_elements(max_elements=100)

        if not elements:
            if attempt == 0:
                log.warning("[navigate_ui] No UI elements found — trying scroll")
                pyautogui.scroll(-3)
                _t.sleep(0.5)
                continue
            return {
                "status": "error",
                "action": "navigate_ui",
                "error": "Could not read UI elements from the current window. "
                         "The app may not support UI Automation.",
            }

        # ── LLM-based element selection (most accurate) ────────────────
        best_match = None
        if settings and hasattr(settings, "groq_api_key"):
            from groq_pool import get_rotator as _get_groq_rotator
            _groq_key = _get_groq_rotator().get_key()
            if _groq_key:
                try:
                    from groq import Groq
                    client = Groq(api_key=_groq_key)

                    # Build element list for LLM
                    elem_list = "\n".join(
                        f"  [{i}] \"{e['name']}\" ({e['type']})"
                        for i, e in enumerate(elements)
                    )

                    pick_prompt = f"""You are a UI navigation assistant. The user wants to go to: "{target}"

Current window: "{window_info.get('title', 'Unknown')}"

Visible UI elements:
{elem_list}

Pick the SINGLE element that best matches the user's intent.
Reply with ONLY the index number (e.g. "5"). If NONE match, reply "NONE"."""

                    resp = client.chat.completions.create(
                        model=getattr(settings, "groq_model", "llama-3.3-70b-versatile"),
                        messages=[{"role": "user", "content": pick_prompt}],
                        max_tokens=10,
                        temperature=0.0,
                    )
                    answer = resp.choices[0].message.content.strip()

                    if answer.upper() != "NONE":
                        try:
                            idx = int(answer.strip().strip("[]"))
                            if 0 <= idx < len(elements):
                                best_match = elements[idx]
                        except (ValueError, IndexError):
                            pass
                except Exception as llm_err:
                    exc_str = str(llm_err)
                    if "rate_limit" in exc_str.lower() or "429" in exc_str:
                        _get_groq_rotator().mark_rate_limited(_groq_key, 60)
                    log.warning("[navigate_ui] LLM selection failed: %s", llm_err)

        # ── Fallback: fuzzy text matching ──────────────────────────────
        if not best_match:
            from difflib import SequenceMatcher

            scored = []
            for e in elements:
                name_lower = e["name"].lower()
                # Exact match
                if target_lower == name_lower:
                    scored.append((1.0, e))
                # Contains match
                elif target_lower in name_lower or name_lower in target_lower:
                    scored.append((0.8, e))
                else:
                    ratio = SequenceMatcher(None, target_lower, name_lower).ratio()
                    if ratio > 0.45:
                        scored.append((ratio, e))

            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                best_match = scored[0][1]

        # ── Click the element ──────────────────────────────────────────
        if best_match:
            log.info("[navigate_ui] Clicking '%s' (%s) at (%d, %d)",
                     best_match["name"], best_match["type"],
                     best_match["x"], best_match["y"])
            pyautogui.click(best_match["x"], best_match["y"])
            _t.sleep(0.3)

            return {
                "status": "success",
                "action": "navigate_ui",
                "clicked": best_match["name"],
                "element_type": best_match["type"],
                "position": {"x": best_match["x"], "y": best_match["y"]},
                "detail": f"Clicked '{best_match['name']}' ({best_match['type']})",
                "window": window_info.get("title", ""),
            }

        # Not found — scroll down and retry
        log.info("[navigate_ui] Target '%s' not found on attempt %d, scrolling...",
                 target, attempt + 1)
        pyautogui.scroll(-5)
        _t.sleep(0.6)

    # All attempts exhausted — try keyboard search as last resort
    log.info("[navigate_ui] Falling back to keyboard search for '%s'", target)
    try:
        import pyautogui
        # Try Ctrl+F / Ctrl+E to search within the app
        pyautogui.hotkey("ctrl", "f")
        _t.sleep(0.3)
        pyautogui.typewrite(target, interval=0.02) if target.isascii() else _type_unicode(target)
        pyautogui.press("enter")
        _t.sleep(0.3)
        return {
            "status": "success",
            "action": "navigate_ui",
            "detail": f"Could not find '{target}' in UI elements. Used keyboard search as fallback.",
            "method": "keyboard_search",
        }
    except Exception:
        pass

    return {
        "status": "error",
        "action": "navigate_ui",
        "error": f"Could not find '{target}' on the current screen after 3 scroll attempts.",
    }


def switch_and_execute(target_app: str, command: str,
                       return_to_previous: bool = True,
                       settings=None) -> dict:
    """
    Switch to another app, execute a navigation command, then optionally return.
    
    1. Saves the current foreground window
    2. Opens the target app
    3. Waits for it to load
    4. Executes the command (navigate_ui or search)
    5. Optionally switches back to the previous window
    """
    import time as _t
    import pyautogui

    # Save current window
    prev_window = _get_foreground_window_info()
    log.info("[switch_exec] From '%s' → open '%s' → '%s'",
             prev_window.get("title", "?"), target_app, command)

    # Open the target app
    app_result = open_app(target_app)
    if app_result.get("status") == "not_installed":
        return {
            "status": "not_installed",
            "action": "switch_and_execute",
            "app": target_app,
            "error": f"{target_app} is not installed",
            "store_url": app_result.get("store_url", ""),
        }

    # Wait for the app to load
    _t.sleep(1.5)

    # Verify the correct app is now focused — avoid multi-tab confusion
    new_fg = _get_foreground_window_info()
    new_title = new_fg.get("title", "").lower()
    target_lower = target_app.lower().strip()
    # Check if target app name appears in the window title
    if target_lower not in new_title and not any(
        alias in new_title for alias in [target_lower, target_lower.replace(" ", "")]
    ):
        log.warning("[switch_exec] Window '%s' doesn't match '%s', retrying...",
                    new_fg.get("title", "?"), target_app)
        open_app(target_app)
        _t.sleep(1.5)

    # Execute the command in the new app
    cmd_result = navigate_ui(command, settings=settings)

    # Return to previous app if requested
    if return_to_previous:
        _t.sleep(0.5)
        pyautogui.hotkey("alt", "tab")
        _t.sleep(0.3)
        log.info("[switch_exec] Returned to previous window via Alt+Tab")

    return {
        "status": "success",
        "action": "switch_and_execute",
        "app": target_app,
        "command_result": cmd_result,
        "returned": return_to_previous,
        "detail": f"Executed '{command}' in {target_app}"
                  + (f", returned to {prev_window.get('title', 'previous window')}" if return_to_previous else ""),
    }



def recall_conversations(user_id: str, query: str, days: int = 7) -> dict:
    """Search past conversations for relevant context."""
    from datetime import datetime, timedelta
    try:
        # Try semantic recall via ChromaDB first
        try:
            from main import memory_recall
            memories = memory_recall(user_id, query, n_results=5)
            if memories:
                return {
                    "status": "success",
                    "action": "recall_conversations",
                    "query": query,
                    "results": memories,
                    "source": "semantic_memory",
                }
        except ImportError:
            pass

        # Fallback: search conversation_store directly
        try:
            from memory.conversation_store import load_history
            history = load_history(user_id, max_turns=100)

            cutoff = (datetime.now() - timedelta(days=days)).timestamp()
            query_lower = query.lower()

            matches = []
            for turn in history:
                if turn.get("timestamp", 0) < cutoff:
                    continue
                if query_lower in turn.get("content", "").lower():
                    matches.append({
                        "role": turn["role"],
                        "content": turn["content"][:200],
                        "time": turn.get("iso_time", "unknown"),
                    })

            return {
                "status": "success",
                "action": "recall_conversations",
                "query": query,
                "count": len(matches),
                "results": matches[:10],
                "source": "conversation_store",
            }
        except ImportError:
            pass

        return {"status": "error", "error": "Memory systems not available"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP MESSAGING
# ─────────────────────────────────────────────────────────────────────────────

def send_whatsapp_message(contact: str, message: str, settings=None) -> dict:
    """Send a message via WhatsApp Desktop using automation.
    If the message is a short intent-word (greet, hello, congrats, etc.),
    generates a real message using AI instead of sending the literal word.
    """
    import time as _time

    # ── Detect intent-words and generate real messages ─────────────────
    INTENT_WORDS = {
        "greet": "Write a friendly greeting message for {contact}. 1-2 sentences, casual tone with an emoji.",
        "greeting": "Write a friendly greeting message for {contact}. 1-2 sentences, casual tone with an emoji.",
        "hello": "Write a warm hello message for {contact}. 1-2 sentences, friendly.",
        "hi": "Write a warm hello message for {contact}. 1 sentence, casual.",
        "congrats": "Write a congratulations message for {contact}. 1-2 sentences, enthusiastic with emoji.",
        "congratulations": "Write a congratulations message for {contact}. 1-2 sentences, enthusiastic.",
        "thanks": "Write a thank you message for {contact}. 1-2 sentences, genuine.",
        "thank you": "Write a thank you message for {contact}. 1-2 sentences, heartfelt.",
        "sorry": "Write an apology message for {contact}. 1-2 sentences, sincere.",
        "apology": "Write a sincere apology message for {contact}. 1-2 sentences.",
        "miss you": "Write a 'miss you' message for {contact}. 1-2 sentences, warm.",
        "good morning": "Write a good morning message for {contact}. 1-2 sentences, cheerful with emoji.",
        "good night": "Write a good night message for {contact}. 1-2 sentences, warm.",
        "happy birthday": "Write a happy birthday message for {contact}. 2-3 sentences, celebratory with emojis.",
        "get well": "Write a get well soon message for {contact}. 1-2 sentences, caring.",
    }

    msg_lower = message.strip().lower()
    intent_prompt = INTENT_WORDS.get(msg_lower)

    if intent_prompt and settings and hasattr(settings, "groq_api_key"):
        from groq_pool import get_rotator as _get_groq_rotator
        _groq_key = _get_groq_rotator().get_key()
        if _groq_key:
            try:
                from groq import Groq
                client = Groq(api_key=_groq_key)
                prompt = intent_prompt.format(contact=contact) + " Reply with ONLY the message text, nothing else."
                resp = client.chat.completions.create(
                    model=getattr(settings, "groq_model", "llama-3.3-70b-versatile"),
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=60,
                    temperature=0.8,
                )
                ai_msg = resp.choices[0].message.content.strip().strip('"').strip("'")
                if ai_msg:
                    message = ai_msg
            except Exception:
                # Fallback: still generate a basic message
                fallback_msgs = {
                    "greet": f"Hey {contact}! Hope you're doing great 😊",
                    "greeting": f"Hey {contact}! How's it going? 😊",
                    "hello": f"Hello {contact}! Hope you're having a wonderful day!",
                    "hi": f"Hi {contact}! 👋",
                    "congrats": f"Congratulations {contact}! 🎉🎊 So proud of you!",
                    "congratulations": f"Congratulations {contact}! 🎉 Amazing work!",
                    "thanks": f"Thank you so much {contact}! Really appreciate it 🙏",
                    "thank you": f"Thank you {contact}! It means a lot 🙏",
                    "sorry": f"Hey {contact}, I'm really sorry. I hope you can understand 🙏",
                    "happy birthday": f"Happy Birthday {contact}! 🎂🎉 Wishing you the best!",
                    "good morning": f"Good morning {contact}! ☀️ Have an amazing day!",
                    "good night": f"Good night {contact}! 🌙 Sleep well!",
                }
                message = fallback_msgs.get(msg_lower, message)

    try:
        # Check if WhatsApp is installed
        whatsapp_result = open_app("whatsapp")
        if whatsapp_result.get("status") == "not_installed":
            return {
                "status": "not_installed",
                "app": "WhatsApp",
                "error": "WhatsApp Desktop is not installed.",
                "store_url": "https://apps.microsoft.com/detail/9NKSQGP7F2NH",
            }

        _time.sleep(3)  # Wait for WhatsApp to open/focus

        try:
            import pyautogui
            import pyperclip
        except ImportError:
            return {"status": "error", "error": "pyautogui and pyperclip required for WhatsApp automation"}

        # Click search bar (Ctrl+F in WhatsApp Desktop)
        pyautogui.hotkey("ctrl", "f")
        _time.sleep(0.5)

        # Type contact name
        pyperclip.copy(contact)
        pyautogui.hotkey("ctrl", "v")
        _time.sleep(1.5)

        # Press Enter to select the first matching contact
        pyautogui.press("enter")
        _time.sleep(0.5)

        # Type message
        pyperclip.copy(message)
        pyautogui.hotkey("ctrl", "v")
        _time.sleep(0.3)

        # Send (Enter)
        pyautogui.press("enter")

        return {
            "status": "success",
            "action": "send_whatsapp_message",
            "contact": contact,
            "detail": f"Message sent to {contact} on WhatsApp",
        }
    except Exception as e:
        return {"status": "error", "error": f"WhatsApp automation failed: {str(e)}"}


def send_whatsapp_file(contact: str, file_path: str) -> dict:
    """Send a file via WhatsApp Desktop using automation."""
    import time as _time
    try:
        # Validate file exists
        safe = _safe_path(file_path)
        if not safe:
            return {"status": "error", "error": f"Invalid file path: {file_path}"}
        if not os.path.isfile(safe):
            return {"status": "error", "error": f"File not found: {file_path}"}

        # Open WhatsApp
        whatsapp_result = open_app("whatsapp")
        if whatsapp_result.get("status") == "not_installed":
            return {
                "status": "not_installed",
                "app": "WhatsApp",
                "error": "WhatsApp Desktop is not installed.",
                "store_url": "https://apps.microsoft.com/detail/9NKSQGP7F2NH",
            }

        _time.sleep(3)

        try:
            import pyautogui
            import pyperclip
        except ImportError:
            return {"status": "error", "error": "pyautogui and pyperclip required"}

        # Search for contact
        pyautogui.hotkey("ctrl", "f")
        _time.sleep(0.5)
        pyperclip.copy(contact)
        pyautogui.hotkey("ctrl", "v")
        _time.sleep(1.5)
        pyautogui.press("enter")
        _time.sleep(0.5)

        # Open attachment dialog (+ button / paperclip icon)
        # In WhatsApp Desktop, the attach shortcut is typically via clicking the attachment icon
        # We use the keyboard shortcut or fall back to clicking
        pyautogui.hotkey("alt", "a")  # Attach shortcut in some versions
        _time.sleep(1)

        # Type file path in the file dialog
        pyperclip.copy(safe)
        pyautogui.hotkey("ctrl", "v")
        _time.sleep(0.5)
        pyautogui.press("enter")
        _time.sleep(1)

        # Send
        pyautogui.press("enter")

        return {
            "status": "success",
            "action": "send_whatsapp_file",
            "contact": contact,
            "file": os.path.basename(safe),
            "detail": f"File '{os.path.basename(safe)}' sent to {contact} on WhatsApp",
        }
    except Exception as e:
        return {"status": "error", "error": f"WhatsApp file send failed: {str(e)}"}


# ─────────────────────────────────────────────────────────────────────────────
# INTELLIGENT FILE SHARING
# ─────────────────────────────────────────────────────────────────────────────

def find_file_smart(name: str, location: str = "") -> dict:
    """
    Fuzzy file search — finds files by partial name, even without extension.
    Searches Desktop, Documents, Downloads, Pictures, Videos (depth 3).
    Matching priority: exact name → starts-with → contains → fuzzy (difflib).
    If location is provided (e.g. "desktop"), searches ONLY that folder first,
    then falls back to all folders if not found.
    """
    from difflib import SequenceMatcher
    try:
        home = os.path.expanduser("~")
        all_dirs = ["Desktop", "Documents", "Downloads", "Pictures", "Videos"]

        # If location hint provided, search that folder first
        location_map = {
            "desktop": "Desktop", "downloads": "Downloads", "download": "Downloads",
            "documents": "Documents", "document": "Documents", "docs": "Documents",
            "pictures": "Pictures", "photos": "Pictures", "images": "Pictures",
            "videos": "Videos", "video": "Videos", "music": "Music",
        }
        loc_key = location.lower().strip() if location else ""
        if loc_key and loc_key in location_map:
            # Search the hinted location first, then fall back to others
            primary = location_map[loc_key]
            ordered = [primary] + [d for d in all_dirs if d != primary]
        else:
            ordered = all_dirs

        search_dirs = [
            os.path.join(home, d)
            for d in ordered
        ]

        name_lower = name.lower().strip()
        candidates = []

        for search_dir in search_dirs:
            if not os.path.exists(search_dir):
                continue
            for root, dirs, files in os.walk(search_dir):
                dirs[:] = [d for d in dirs if not d.startswith('.')]
                depth = root.replace(search_dir, '').count(os.sep)
                if depth > 3:
                    dirs.clear()
                    continue
                for fname in files:
                    fpath = os.path.join(root, fname)
                    fname_lower = fname.lower()
                    fname_no_ext = os.path.splitext(fname_lower)[0]

                    # Score: 100 = exact, 90 = exact no-ext, 80 = starts-with,
                    #         70 = contains, <70 = fuzzy ratio
                    if fname_lower == name_lower:
                        score = 100
                    elif fname_no_ext == name_lower:
                        score = 90
                    elif fname_no_ext.startswith(name_lower):
                        score = 80
                    elif name_lower in fname_no_ext:
                        score = 70
                    else:
                        ratio = SequenceMatcher(None, name_lower, fname_no_ext).ratio()
                        if ratio >= 0.55:
                            score = int(ratio * 65)
                        else:
                            continue  # Skip low matches

                    candidates.append({
                        "name": fname,
                        "path": fpath,
                        "score": score,
                        "size": os.path.getsize(fpath) if os.path.exists(fpath) else 0,
                    })
                    if len(candidates) >= 50:
                        break
                if len(candidates) >= 50:
                    break
            if len(candidates) >= 50:
                break

        # Sort by score (highest first), then most recent
        candidates.sort(key=lambda c: c["score"], reverse=True)
        top = candidates[:5]

        if not top:
            return {
                "status": "not_found",
                "action": "find_file_smart",
                "query": name,
                "error": f"No file matching '{name}' found. Check the name or location.",
            }

        return {
            "status": "success",
            "action": "find_file_smart",
            "query": name,
            "best_match": top[0],
            "alternatives": top[1:],
            "count": len(top),
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── App-specific automation mappings for contact search + send ────────────
_APP_SHARE_PROFILES = {
    "whatsapp": {
        "search_shortcut": "ctrl+f",
        "search_delay": 0.5,
        "contact_delay": 1.5,
        "attach_shortcut": None,  # Use drag-and-drop / file dialog
        "send_shortcut": "enter",
    },
    "telegram": {
        "search_shortcut": "ctrl+k",
        "search_delay": 0.5,
        "contact_delay": 1.0,
        "attach_shortcut": None,
        "send_shortcut": "enter",
    },
    "discord": {
        "search_shortcut": "ctrl+k",
        "search_delay": 0.5,
        "contact_delay": 1.0,
        "attach_shortcut": None,
        "send_shortcut": "enter",
    },
}


def send_to_app(contact: str, message: str = "",
                app: str = "whatsapp", file_path: str = "") -> dict:
    """
    Universal file/message sharing — sends a message and/or file
    to a contact via WhatsApp, Telegram, Discord, or Email.
    """
    import time as _time
    app_lower = app.lower().strip()

    # ── Email: use mailto: URI ──
    if app_lower in ("email", "mail", "outlook", "gmail"):
        try:
            import webbrowser
            subject = "Sharing a file" if file_path else ""
            mailto = f"mailto:{contact}?subject={subject}&body={message or ''}"
            webbrowser.open(mailto)
            result = {
                "status": "success",
                "action": "send_to_app",
                "app": "email",
                "contact": contact,
                "detail": f"Email compose window opened for {contact}",
            }
            # If there's a file, we can't mailto-attach, so note that
            if file_path:
                result["detail"] += f". Please attach '{os.path.basename(file_path)}' manually."
                result["file_note"] = "Email doesn't support auto-attach. File path copied to clipboard."
                try:
                    import pyperclip
                    pyperclip.copy(file_path)
                except Exception:
                    pass
            return result
        except Exception as e:
            return {"status": "error", "error": f"Email failed: {e}"}

    # ── Messaging apps: WhatsApp, Telegram, Discord ──
    profile = _APP_SHARE_PROFILES.get(app_lower)
    if not profile:
        # Fallback: treat as WhatsApp
        profile = _APP_SHARE_PROFILES["whatsapp"]
        app_lower = "whatsapp"

    try:
        # Open the app
        app_result = open_app(app_lower)
        if app_result.get("status") == "not_installed":
            return {
                "status": "not_installed",
                "app": app.title(),
                "error": f"{app.title()} is not installed.",
                "store_url": app_result.get("store_url", ""),
            }

        _time.sleep(3)

        try:
            import pyautogui
            import pyperclip
        except ImportError:
            return {"status": "error",
                    "error": "pyautogui and pyperclip required for app automation"}

        # Search for contact
        keys = profile["search_shortcut"].split("+")
        pyautogui.hotkey(*keys)
        _time.sleep(profile["search_delay"])
        pyperclip.copy(contact)
        pyautogui.hotkey("ctrl", "v")
        _time.sleep(profile["contact_delay"])
        pyautogui.press("enter")
        _time.sleep(0.5)

        # Send file if provided
        if file_path and os.path.isfile(file_path):
            # Use drag-and-drop simulation via clipboard for file
            # Copy file path to clipboard and use attach shortcut
            if app_lower == "whatsapp":
                pyautogui.hotkey("alt", "a")  # Attach in WhatsApp
            elif app_lower == "telegram":
                pyautogui.hotkey("ctrl", "shift", "f")  # Attach in Telegram
            elif app_lower == "discord":
                # Discord: use the + button area (just paste the file)
                pass

            _time.sleep(1)
            pyperclip.copy(file_path)
            pyautogui.hotkey("ctrl", "v")
            _time.sleep(0.5)
            pyautogui.press("enter")
            _time.sleep(1)

        # Send message if provided
        if message:
            pyperclip.copy(message)
            pyautogui.hotkey("ctrl", "v")
            _time.sleep(0.3)
            pyautogui.press("enter")

        detail = f"{'File and message' if file_path else 'Message'} sent to {contact} on {app.title()}"
        return {
            "status": "success",
            "action": "send_to_app",
            "app": app.title(),
            "contact": contact,
            "file": os.path.basename(file_path) if file_path else None,
            "detail": detail,
        }
    except Exception as e:
        return {"status": "error", "error": f"{app.title()} automation failed: {e}"}


def send_file_with_message(contact: str, file_name: str,
                           app: str = "whatsapp", custom_message: str = "",
                           compose_message: bool = False,
                           location: str = "",
                           session=None, settings=None) -> dict:
    """
    Intelligent file sharing:
      1. Finds the file by fuzzy name match
      2. Optionally generates an AI message about the file
      3. Sends the file + message to the contact via the chosen app
    """
    # Step 1: Find the file
    found = find_file_smart(file_name, location=location)
    if found.get("status") != "success":
        return {
            "status": "error",
            "action": "send_file_with_message",
            "error": f"Could not find file '{file_name}'. {found.get('error', '')}",
        }

    best = found["best_match"]
    file_path = best["path"]
    actual_name = best["name"]

    # Step 2: Generate AI message if requested
    message = custom_message
    if (compose_message or not message) and settings and hasattr(settings, "groq_api_key"):
        from groq_pool import get_rotator as _get_groq_rotator
        _groq_key = _get_groq_rotator().get_key()
        if _groq_key:
            try:
                from groq import Groq
                client = Groq(api_key=_groq_key)
                compose_prompt = (
                    f"Write a short, friendly 1-sentence message to accompany sending "
                    f"the file '{actual_name}' to someone named '{contact}'. "
                    f"Be natural and concise, like a human text message."
                )
                if compose_message:
                    compose_prompt = (
                        f"Write a brief paragraph about the file '{actual_name}' — "
                        f"describe what it likely contains based on its name/type. "
                        f"Keep it under 2 sentences, friendly tone."
                    )
                resp = client.chat.completions.create(
                    model=getattr(settings, "groq_model", "llama-3.3-70b-versatile"),
                    messages=[{"role": "user", "content": compose_prompt}],
                    max_tokens=80,
                    temperature=0.7,
                )
                ai_msg = resp.choices[0].message.content.strip()
                if ai_msg:
                    message = ai_msg
            except Exception:
                # Fallback message
                if not message:
                    ext = os.path.splitext(actual_name)[1].lower()
                    type_label = {
                        ".pdf": "document", ".docx": "document", ".doc": "document",
                        ".xlsx": "spreadsheet", ".pptx": "presentation",
                        ".jpg": "photo", ".png": "image", ".mp4": "video",
                    }.get(ext, "file")
                    message = f"Here's the {type_label} — {actual_name}"

    if not message:
        message = f"Sharing: {actual_name}"

    # Step 3: Send via the chosen app
    result = send_to_app(contact, message, app, file_path)
    result["file_found"] = actual_name
    result["file_path"] = file_path
    return result


# ─────────────────────────────────────────────────────────────────────────────
# MAIN HANDLER — Parse intent and execute
# ─────────────────────────────────────────────────────────────────────────────

def handle_automation(user_text: str, session, settings, system_prompt: str,
                      history: list, max_tokens: int, response_cache) -> list[str]:
    """
    Handle automation queries. Uses LLM to parse the user's intent,
    then executes the appropriate system function.
    """
    import re
    text_lower = user_text.lower().strip()

    # ── Get foreground window context for smarter decisions ───────────────
    try:
        fg_info = _get_foreground_window_info()
        fg_title = fg_info.get("title", "Unknown")
    except Exception:
        fg_title = "Unknown"

    # ── LLM-based intent parsing ──────────────────────────────────────────
    parse_prompt = f"""You are Alita, a system automation assistant. Parse this command.
Currently focused window: "{fg_title}"
Reply with ONLY a JSON object (no markdown, no explanation):

Available actions:
- {{"action":"open_app","app":"<name>"}}
- {{"action":"close_app","app":"<name>"}}
- {{"action":"open_folder","folder":"<name or path>"}}
- {{"action":"open_url","url":"<url>"}}
- {{"action":"create_file","path":"<path>","content":"<text>"}}
- {{"action":"read_file","path":"<path>"}}
- {{"action":"write_file","path":"<path>","content":"<text>"}}
- {{"action":"delete_file","path":"<path>"}}
- {{"action":"list_dir","path":"<path>"}}
- {{"action":"create_folder","path":"<path>"}}
- {{"action":"copy_item","source":"<path>","destination":"<path>"}}
- {{"action":"move_item","source":"<path>","destination":"<path>"}}
- {{"action":"copy_to_clipboard","text":"<text>"}}
- {{"action":"type_in_app","app":"<name>","content":"<text to type>"}}
- {{"action":"send_keys","keys":"<shortcut like ctrl+n, ctrl+s, alt+f4, enter, tab, escape, f5>"}}
- {{"action":"click_position","x":<number>,"y":<number>,"button":"left|right"}}
- {{"action":"battery"}}
- {{"action":"system_info"}}
- {{"action":"processes"}}
- {{"action":"screenshot"}}
- {{"action":"run_command","command":"<shell command>"}}
- {{"action":"set_volume","level":"up|down|<0-100>"}}
- {{"action":"toggle_mute"}}
- {{"action":"set_brightness","level":"up|down|<0-100>"}}
- {{"action":"toggle_dark_mode"}}
- {{"action":"lock_screen"}}
- {{"action":"empty_recycle_bin"}}
- {{"action":"toggle_wifi","state":"on|off|toggle"}}
- {{"action":"search_files","query":"<name>","file_type":"pdf|image|video|document","days":<N>}}
- {{"action":"control_music","control":"play|pause|next|previous|stop"}}
- {{"action":"open_music","query":"<song or artist>"}}
- {{"action":"set_reminder","text":"<what to remind>","time":"<when>"}}
- {{"action":"list_reminders"}}
- {{"action":"delete_reminder","index":<N>}}
- {{"action":"clipboard_history"}}
- {{"action":"log_habit","habit":"<habit name>"}}
- {{"action":"habit_stats"}}
- {{"action":"mood_journal"}}
- {{"action":"read_screen"}}
- {{"action":"recall_memory","query":"<what to remember>"}}
- {{"action":"send_whatsapp","contact":"<name>","message":"<text>"}}
- {{"action":"send_whatsapp_file","contact":"<name>","file_path":"<path>"}}
- {{"action":"send_to_app","contact":"<name>","message":"<text>","app":"whatsapp|telegram|discord|email","file_path":"<optional path>"}}
- {{"action":"send_file_smart","contact":"<name or phone number>","file_name":"<partial name, no extension needed>","app":"whatsapp|telegram|discord|email","compose_message":true|false,"location":"desktop|downloads|documents|pictures|videos|"}}
- {{"action":"find_file","name":"<partial file name>"}}
- {{"action":"search_in_app","app":"<app name>","query":"<search query>"}}
- {{"action":"search_web","query":"<search query>","engine":"google|youtube|bing|github|amazon|wikipedia"}}
- {{"action":"search_windows","query":"<search query>"}}
- {{"action":"install_app","app":"<app name>"}}
- {{"action":"uninstall_app","app":"<app name>"}}
- {{"action":"check_task_status","task_id":"<optional task id>"}}
- {{"action":"recognize_song"}}
- {{"action":"navigate_ui","target":"<element to find and click>"}}
- {{"action":"switch_and_execute","app":"<app name>","command":"<what to do in that app>","return":true|false}}

Default paths: Desktop = "~/Desktop", Downloads = "~/Downloads", Documents = "~/Documents"
For file paths, ALWAYS use full paths with ~/. Example: "create a python file on desktop" → path = "~/Desktop/script.py"
For file creation, infer appropriate extension from context: .txt, .py, .html, .css, .js, .json, .md, .csv, etc.

IMPORTANT rules:
- "write in notepad" / "type in notepad" → use type_in_app with app="notepad"
- "copy file X to Y" / "move file from X to Y" → use copy_item or move_item
- "copy this text" → use copy_to_clipboard
- If user says to JUST open an app, use open_app
- "navigate to downloads" / "go to documents" / "open downloads folder" → open_folder (NOT open_app)
- "open my pictures" / "go to desktop" → open_folder

SEARCH CONTEXT (CRITICAL — pick the right search type):
- "search for X in Microsoft Store" / "find X in Store" → search_in_app (app="Microsoft Store", query="X")
- "search for X in Chrome" / "look up X in browser" → search_in_app (app="chrome", query="X")
- "search for X in Settings" / "find X in settings" → search_in_app (app="settings", query="X")
- "search for X in File Explorer" → search_in_app (app="file explorer", query="X")
- "search for X on YouTube" / "YouTube search X" → search_web (query="X", engine="youtube")
- "search for X on Amazon" → search_web (query="X", engine="amazon")
- "search for X" / "Google X" / "look up X" / "web search X" → search_web (query="X", engine="google")
- "search X on my computer" / "find X on PC" → search_windows (query="X")
- "Windows search X" → search_windows (query="X")
- "find file X" / "search for X.pdf" → search_files (file search, NOT web search)
- RULE: If user says "in <app>" → use search_in_app. If "on <website>" → use search_web. Otherwise → search_web.
- CRITICAL: "search X in Y" where Y is an app like Spotify/Store/Chrome/Settings → ALWAYS use search_in_app, NEVER open_app.
- CRITICAL: Do NOT use open_app when search_in_app is the intent. They are DIFFERENT actions.
- CRITICAL: "play X on YouTube" ≠ "search X on YouTube". Play → open_music. Search → search_web.

INSTALL/UNINSTALL:
- "install Spotify" / "download Discord" / "get VS Code" → install_app (runs in background via winget)
- "uninstall Spotify" / "remove Discord" → uninstall_app
- "install status" / "what's installing" / "check downloads" → check_task_status
- RULE: install_app handles EVERYTHING automatically (winget → Store → web fallback). Just pass the app name.
- "press ctrl+n" / "new file" / "save" / "undo" / "close window" → send_keys
- "press enter" / "press tab" / "press escape" → send_keys
- "new file in notepad" → send_keys with keys="ctrl+n"
- "save the file" → send_keys with keys="ctrl+s"
- "close this" / "close window" → send_keys with keys="alt+f4"
- "undo" → send_keys with keys="ctrl+z"
- "redo" → send_keys with keys="ctrl+y"
- "select all" → send_keys with keys="ctrl+a"
- "refresh" / "reload" → send_keys with keys="f5"
- "fullscreen" → send_keys with keys="f11"
- "minimize" → send_keys with keys="win+down"
- "maximize" → send_keys with keys="win+up"
- "create file X.ext on desktop" → create_file with proper path and extension
PLAY vs SEARCH (CRITICAL — understand the difference):
- "play X on YouTube" / "play X" / "bajao X" → open_music (PLAYS the content — opens YouTube and clicks first result)
- "search X on YouTube" / "YouTube search X" → search_web (ONLY searches — just shows search results)
- "search for X on YouTube" → search_web (ONLY searches)
- RULE: If user says "PLAY", use open_music. If user says "SEARCH" or "look up", use search_web.
- RULE: "play" means AUTO-PLAY the first result. "search" means SHOW results only.
- "play music" / "next song" / "pause" → control_music
- "play <song name>" / "play <artist>" → open_music (query="<song name>")
- "remind me" → set_reminder, "my reminders" → list_reminders
- "I drank water" / "I exercised" → log_habit
- "my mood" / "mood journal" → mood_journal
- "read screen" / "what's on my screen" → read_screen
- "find file" / "search for" → search_files
- "remember when" / "what did we talk about" → recall_memory
- "what song is this" / "identify this song" / "which song is playing" / "shazam" → recognize_song

UI NAVIGATION (CRITICAL — use navigate_ui for IN-APP navigation):
- "go to accounts" / "click on privacy" / "open display settings" / "tap on bluetooth" → navigate_ui (target=element name)
- "go to accounts in settings" → if Settings is already open: navigate_ui. If not: switch_and_execute (app="settings", command="accounts")
- "open Chrome and search weather then come back" → switch_and_execute (app="chrome", command="weather", return=true)
- "switch to notepad and type hello" → switch_and_execute (app="notepad", command="hello", return=false)
- RULE: If user says "go to X" / "click X" / "tap X" / "find X on screen" and an app is ALREADY OPEN → use navigate_ui
- RULE: If user says "open App and do X" or "switch to App and do X" → use switch_and_execute
- RULE: After open_app, if user gives a follow-up like "now go to accounts" → navigate_ui (NOT search_in_app)
- RULE: navigate_ui reads the LIVE screen elements and clicks the best match — it's smarter than search_in_app for UI navigation
- "send message to X on whatsapp" → send_whatsapp with contact and message
- "send greet to X" / "send greeting to X" → send_whatsapp with contact and message (generate a REAL greeting, NOT the literal word)
- "send congrats to X" / "send thanks to X" → send_whatsapp with an appropriate FULL message, not the single word
- RULE: If user says "send greet/greeting/congrats/thanks/hello" → message should be a PROPER sentence like "Hey! How are you? 😊", NOT the word itself
- "send file to X on whatsapp" → send_whatsapp_file

WINDOW AWARENESS (CRITICAL — avoid multi-tab confusion):
- The currently focused window title is provided above. Use it to decide between navigate_ui vs switch_and_execute.
- If user says "go to accounts" and the focused window is "Settings" → navigate_ui (it's already there).
- If user says "go to accounts" but focused window is "Chrome" → switch_and_execute (app="settings", command="accounts").
- If user says "go to X in settings" / "click X in settings" and focused window is NOT Settings → ALWAYS use switch_and_execute.
- RULE: Do NOT assume the right app is focused. CHECK the focused window title.
- RULE: If the command references a specific app by name ("in settings", "in chrome"), ALWAYS use switch_and_execute to guarantee correct focus.
- RULE: If multiple windows/tabs are open, focus on the FOREGROUND window only — ignore background windows.

FILE SHARING (INTELLIGENT — use these for smart sharing):
- "send resume to Rahul on WhatsApp" → send_file_smart (file_name="resume", contact="Rahul", app="whatsapp")
- "send this report to Mom on Telegram" → send_file_smart (file_name="report", contact="Mom", app="telegram")
- "write something about this project and send to Boss" → send_file_smart (compose_message=true)
- "share budget file with John on Discord" → send_file_smart (file_name="budget", contact="John", app="discord")
- "email the presentation to client" → send_file_smart (file_name="presentation", contact="client", app="email")
- "send file to X" (no app mentioned) → default app to whatsapp
- "find my resume" / "find budget file" → find_file (just locate, don't send)
- "send message to X on telegram" → send_to_app (app="telegram")
- "message John on discord" → send_to_app (app="discord")
- RULE: If user mentions a FILE NAME + a CONTACT + an APP → use send_file_smart. If just msg → send_to_app.

FILE SHARING — LOCATION HINTS (extract folder from user's words):
- "send the file which is on desktop with name Pawan to Rahul on WhatsApp" → send_file_smart (file_name="Pawan", contact="Rahul", app="whatsapp", location="desktop")
- "share my resume from downloads to Mom on Telegram" → send_file_smart (file_name="resume", contact="Mom", app="telegram", location="downloads")
- "desktop pe jo Pawan file hai wo WhatsApp pe Rahul ko bhejo" → send_file_smart (file_name="Pawan", contact="Rahul", app="whatsapp", location="desktop")
- "send the Pawan file to 9876543210 on WhatsApp" → send_file_smart (file_name="Pawan", contact="9876543210", app="whatsapp")
- "send this file to Rahul on WhatsApp" → send_file_smart (file_name from context or ask, contact="Rahul", app="whatsapp")
- "send this to Rahul on WhatsApp" → send_file_smart (file_name from context, contact="Rahul", app="whatsapp")
- RULE: "on desktop" / "from desktop" / "which is on desktop" / "desktop pe" → location="desktop"
- RULE: "in downloads" / "from downloads" / "downloads me" → location="downloads"
- RULE: "in documents" / "from documents" → location="documents"
- RULE: Phone numbers (10+ digits) are valid contacts — pass them as-is to "contact"
- RULE: "this file" / "the file" / "ye file" without a clear name → use any file name hint from context, or extract from the sentence
- RULE: "send X to Y on Z" where X=file, Y=person/number, Z=app → send_file_smart
- RULE: "send this to Y on Z" → send_file_smart (try to infer file name from sentence, default to empty string)

User command: "{user_text}"
JSON:"""

    action_data = None

    # Try LLM parsing first
    from groq_pool import get_rotator as _get_groq_rotator
    _groq_key = _get_groq_rotator().get_key()
    if _groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=_groq_key)
            resp = client.chat.completions.create(
                model=settings.groq_model,
                messages=[{"role": "user", "content": parse_prompt}],
                max_tokens=200,
                temperature=0.1,
            )
            raw = resp.choices[0].message.content.strip()
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', raw, re.DOTALL)
            if json_match:
                action_data = json.loads(json_match.group(0))
        except Exception as e:
            log.warning("LLM parse failed: %s", e)

    # ── Fallback: keyword-based parsing ───────────────────────────────────
    if not action_data:
        # Copy/move detection
        if any(w in text_lower for w in ["copy", "move", "paste", "transfer"]):
            # Try to extract source/destination from common patterns
            is_move = "move" in text_lower or "transfer" in text_lower
            if "clipboard" in text_lower or "copy this" in text_lower or "copy text" in text_lower:
                action_data = {"action": "copy_to_clipboard", "text": user_text}
            else:
                # Default: let LLM handle complex paths, fallback to generic
                src, dst = "~/Desktop", "~/Documents"
                if "download" in text_lower:
                    src = "~/Downloads" if "from download" in text_lower else src
                    dst = "~/Downloads" if "to download" in text_lower else dst
                if "document" in text_lower:
                    src = "~/Documents" if "from document" in text_lower else src
                    dst = "~/Documents" if "to document" in text_lower else dst
                if "desktop" in text_lower:
                    src = "~/Desktop" if "from desktop" in text_lower else src
                    dst = "~/Desktop" if "to desktop" in text_lower else dst
                action = "move_item" if is_move else "copy_item"
                action_data = {"action": action, "source": src, "destination": dst}

        # ── Navigate / Go to folder ────────────────────────────────
        elif any(w in text_lower for w in ["navigate to", "go to", "open folder"]):
            # Extract folder name
            folder = text_lower
            for prefix in ["navigate to the ", "navigate to my ", "navigate to ",
                           "go to the ", "go to my ", "go to ",
                           "open folder ", "open the ", "open my "]:
                if text_lower.startswith(prefix):
                    folder = text_lower[len(prefix):].strip()
                    break
            # Remove trailing "folder" word
            folder = folder.replace(" folder", "").strip()
            if folder in FOLDER_ALIASES or os.path.isdir(os.path.expanduser(folder)):
                action_data = {"action": "open_folder", "folder": folder}
            else:
                # Could be "go to settings" (an app), fallback to open_app
                action_data = {"action": "open_app", "app": folder}

        elif "open" in text_lower and any(f in text_lower for f in FOLDER_ALIASES):
            # "open downloads", "open my documents", etc.
            for alias in FOLDER_ALIASES:
                if alias in text_lower:
                    action_data = {"action": "open_folder", "folder": alias}
                    break

        elif "open" in text_lower and any(app in text_lower for app in APP_MAP):
            for app in APP_MAP:
                if app in text_lower:
                    action_data = {"action": "open_app", "app": app}
                    break
        elif "open" in text_lower:
            # Try to extract app name even if not in APP_MAP
            words = text_lower.replace("open", "").strip().split()
            if words:
                app_guess = " ".join(words[:2])  # first 2 words after "open"
                action_data = {"action": "open_app", "app": app_guess}

        # ── In-app search fallback (BEFORE install/other fallbacks) ────────
        elif re.search(r"search\s+(.+?)\s+in\s+(\w[\w\s]*)", text_lower):
            import re as _re
            m = _re.search(r"search\s+(.+?)\s+in\s+(\w[\w\s]*)", text_lower)
            if m:
                query = m.group(1).strip()
                app = m.group(2).strip()
                action_data = {"action": "search_in_app", "app": app, "query": query}
        elif re.search(r"find\s+(.+?)\s+in\s+(\w[\w\s]*)", text_lower):
            import re as _re
            m = _re.search(r"find\s+(.+?)\s+in\s+(\w[\w\s]*)", text_lower)
            if m:
                query = m.group(1).strip()
                app = m.group(2).strip()
                # Don't match "find file" type queries
                if app.lower() not in ("downloads", "documents", "desktop", "my"):
                    action_data = {"action": "search_in_app", "app": app, "query": query}
        # Install / Uninstall / Status
        elif any(w in text_lower for w in ["install ", "download ", "get app"]):
            app = text_lower
            for prefix in ["install ", "download ", "get app ", "get "]:
                if text_lower.startswith(prefix):
                    app = text_lower[len(prefix):].strip()
                    break
            action_data = {"action": "install_app", "app": app}
        elif any(w in text_lower for w in ["uninstall ", "remove app"]):
            app = text_lower
            for prefix in ["uninstall ", "remove app ", "remove "]:
                if text_lower.startswith(prefix):
                    app = text_lower[len(prefix):].strip()
                    break
            action_data = {"action": "uninstall_app", "app": app}
        elif any(w in text_lower for w in ["install status", "what's installing", "check download", "task status"]):
            action_data = {"action": "check_task_status"}

        elif "battery" in text_lower:
            action_data = {"action": "battery"}
        elif "system info" in text_lower or "system status" in text_lower:
            action_data = {"action": "system_info"}
        elif "screenshot" in text_lower:
            action_data = {"action": "screenshot"}
        elif "list files" in text_lower or "show files" in text_lower:
            path = "~/Desktop"
            if "download" in text_lower:
                path = "~/Downloads"
            elif "document" in text_lower:
                path = "~/Documents"
            action_data = {"action": "list_dir", "path": path}
        elif "processes" in text_lower or "task manager" in text_lower:
            action_data = {"action": "processes"}
        elif ("write" in text_lower or "type" in text_lower) and any(app in text_lower for app in APP_MAP):
            for app in APP_MAP:
                if app in text_lower:
                    action_data = {"action": "type_in_app", "app": app, "content": ""}
                    break

        # ── New feature keyword fallbacks ──────────────────────────────
        # System Shortcuts
        elif any(w in text_lower for w in ["volume up", "increase volume"]):
            action_data = {"action": "set_volume", "level": "up"}
        elif any(w in text_lower for w in ["volume down", "decrease volume"]):
            action_data = {"action": "set_volume", "level": "down"}
        elif any(w in text_lower for w in ["mute", "unmute", "sound off", "awaz band"]):
            action_data = {"action": "toggle_mute"}
        elif any(w in text_lower for w in ["brightness", "dim screen"]):
            if "increase" in text_lower or "up" in text_lower:
                action_data = {"action": "set_brightness", "level": "up"}
            elif "decrease" in text_lower or "down" in text_lower or "dim" in text_lower:
                action_data = {"action": "set_brightness", "level": "down"}
            else:
                action_data = {"action": "set_brightness", "level": "70"}
        elif any(w in text_lower for w in ["dark mode", "night mode", "light mode"]):
            action_data = {"action": "toggle_dark_mode"}
        elif any(w in text_lower for w in ["lock screen", "lock computer", "lock pc"]):
            action_data = {"action": "lock_screen"}
        elif any(w in text_lower for w in ["empty recycle", "recycle bin", "clear trash"]):
            action_data = {"action": "empty_recycle_bin"}
        elif "wifi" in text_lower:
            if any(w in text_lower for w in ["on", "enable", "chalu"]):
                action_data = {"action": "toggle_wifi", "state": "on"}
            elif any(w in text_lower for w in ["off", "disable", "band"]):
                action_data = {"action": "toggle_wifi", "state": "off"}
            else:
                action_data = {"action": "toggle_wifi", "state": "toggle"}

        # Music Control
        elif any(w in text_lower for w in ["play music", "resume music", "gaana bajao"]):
            action_data = {"action": "control_music", "control": "play"}
        elif any(w in text_lower for w in ["pause music", "stop music"]):
            action_data = {"action": "control_music", "control": "pause"}
        elif any(w in text_lower for w in ["next song", "skip song"]):
            action_data = {"action": "control_music", "control": "next"}
        elif "previous song" in text_lower:
            action_data = {"action": "control_music", "control": "previous"}
        elif text_lower.startswith("play ") and not any(w in text_lower for w in ["play music", "play next"]):
            # "play X on youtube" / "play X" / "bajao X" → open_music (auto-plays first result)
            import re as _re
            m = _re.search(r"play\s+(.+?)(?:\s+on\s+(?:youtube|spotify|yt))?$", text_lower)
            query = m.group(1).strip() if m else text_lower.replace("play", "").strip()
            for w in ["song", "video", "the"]:
                query = query.replace(w, "").strip()
            action_data = {"action": "open_music", "query": query or "music"}
        elif any(w in text_lower for w in ["play song", "play on youtube", "play on spotify"]):
            query = text_lower.replace("play", "").replace("song", "").replace("on youtube", "").replace("on spotify", "").strip()
            action_data = {"action": "open_music", "query": query or "music"}
        elif text_lower.startswith("bajao ") or text_lower.startswith("chalao "):
            query = text_lower.replace("bajao", "").replace("chalao", "").strip()
            action_data = {"action": "open_music", "query": query or "music"}

        # Smart Reminders
        elif any(w in text_lower for w in ["remind me", "set reminder", "yaad dila", "reminder lagao"]):
            action_data = {"action": "set_reminder", "text": user_text, "time": user_text}
        elif any(w in text_lower for w in ["show reminders", "list reminders", "my reminders"]):
            action_data = {"action": "list_reminders"}
        elif "delete reminder" in text_lower:
            action_data = {"action": "delete_reminder", "index": -1}

        # Clipboard History
        elif any(w in text_lower for w in ["clipboard history", "what did i copy", "last copied", "recent copies", "copied earlier"]):
            action_data = {"action": "clipboard_history"}

        # Habit Tracker
        elif any(w in text_lower for w in ["i drank", "i exercised", "i walked", "i meditated", "i studied", "i read"]):
            # Extract the habit
            habit = text_lower
            for prefix in ["i ", "i've ", "i just "]:
                if text_lower.startswith(prefix):
                    habit = text_lower[len(prefix):]
                    break
            action_data = {"action": "log_habit", "habit": habit}
        elif any(w in text_lower for w in ["my habits", "habit stats", "show streak", "habit tracker"]):
            action_data = {"action": "habit_stats"}

        # Mood Journal
        elif any(w in text_lower for w in ["mood journal", "my mood", "mood history", "mood trend", "my emotions"]):
            action_data = {"action": "mood_journal"}

        # Screen Reader
        elif any(w in text_lower for w in ["read screen", "what's on my screen", "describe screen", "screen reader", "ocr", "screen padho"]):
            action_data = {"action": "read_screen"}

        # Context Memory
        elif any(w in text_lower for w in ["remember when", "what did we talk", "recall", "past conversation", "do you remember", "yaad hai"]):
            action_data = {"action": "recall_memory", "query": user_text}

        # Song Recognition
        elif any(w in text_lower for w in ["what song", "which song", "identify song", "identify this song",
                                            "recognize song", "recognize this song",
                                            "name this song", "shazam", "what is playing", "what's playing",
                                            "konsa gaana", "ye gaana", "what music", "this song"]):
            action_data = {"action": "recognize_song"}

        # Smart Search
        elif any(w in text_lower for w in ["find file", "search file", "locate file", "find the", "find my"]):
            query = text_lower
            for prefix in ["find file ", "search file ", "locate file ", "find the ", "find my ", "find "]:
                if text_lower.startswith(prefix):
                    query = text_lower[len(prefix):]
                    break
            file_type = ""
            for ft in ["pdf", "document", "image", "photo", "video", "audio", "excel"]:
                if ft in text_lower:
                    file_type = ft
                    query = query.replace(ft, "").strip()
                    break
            days = 0
            if "yesterday" in text_lower:
                days = 1
            elif "last week" in text_lower:
                days = 7
            elif "today" in text_lower:
                days = 1
            action_data = {"action": "search_files", "query": query, "file_type": file_type, "days": days}

        # WhatsApp Messaging
        elif any(w in text_lower for w in ["send message on whatsapp", "whatsapp message", "send on whatsapp",
                                            "message on whatsapp", "whatsapp bhejo", "whatsapp pe bhejo"]):
            # Extract contact name and message (best effort)
            import re
            contact_match = re.search(r"(?:to|for)\s+([a-zA-Z]+)", text_lower)
            contact = contact_match.group(1).title() if contact_match else "Unknown"
            message = user_text  # LLM will provide better parsing
            action_data = {"action": "send_whatsapp", "contact": contact, "message": message}
        elif any(w in text_lower for w in ["send file on whatsapp", "whatsapp file", "share file on whatsapp"]):
            import re
            contact_match = re.search(r"(?:to|for)\s+([a-zA-Z]+)", text_lower)
            contact = contact_match.group(1).title() if contact_match else "Unknown"
            action_data = {"action": "send_whatsapp_file", "contact": contact, "file_path": ""}

        # ── Intelligent file sharing across apps ──────────────────────
        elif any(w in text_lower for w in ["send file", "share file", "bhejo file",
                                            "send the file", "share the file",
                                            "send document", "share document",
                                            "send photo", "share photo",
                                            "send video", "share video",
                                            "send this file", "send this to",
                                            "share this with", "send it to",
                                            "file bhejo", "ye file bhejo",
                                            "ye bhejo", "isko bhejo",
                                            "send this on", "share this on"]):
            import re
            # Extract contact — support names and phone numbers
            contact_match = re.search(r"(?:to|for|with|ko)\s+([a-zA-Z]+|\d{10,})", text_lower)
            contact = contact_match.group(1).title() if contact_match else "Unknown"
            # Detect app
            app = "whatsapp"  # default
            for a in ["telegram", "discord", "email", "mail"]:
                if a in text_lower:
                    app = a
                    break
            # Detect location hint
            location = ""
            for loc in ["desktop", "downloads", "download", "documents", "pictures", "videos"]:
                if loc in text_lower:
                    location = loc
                    break
            # Extract file name hint
            file_hint = text_lower
            for strip_w in ["send", "share", "the", "file", "document", "photo", "video",
                           "to", "on", "via", "with", "bhejo", "this", "it", "ye", "isko",
                           "which is", "from", "in", "pe", "ko",
                           contact.lower(), app, location, "whatsapp"]:
                file_hint = file_hint.replace(strip_w, "")
            file_hint = file_hint.strip()
            action_data = {"action": "send_file_smart", "contact": contact,
                          "file_name": file_hint or "file", "app": app,
                          "location": location}

        elif any(w in text_lower for w in ["message on telegram", "send on telegram",
                                            "message on discord", "send on discord",
                                            "telegram message", "discord message"]):
            import re
            contact_match = re.search(r"(?:to|for)\s+([a-zA-Z]+)", text_lower)
            contact = contact_match.group(1).title() if contact_match else "Unknown"
            app = "telegram" if "telegram" in text_lower else "discord"
            action_data = {"action": "send_to_app", "contact": contact,
                          "message": user_text, "app": app}

    # ── Execute the action ────────────────────────────────────────────────
    if not action_data:
        return ["I couldn't understand that automation command. Try saying something like 'Open Chrome' or 'List files on Desktop'."]

    action = action_data.get("action", "")
    result = None

    ACTION_MAP = {
        "open_app": lambda d: open_app(d.get("app", "")),
        "close_app": lambda d: close_app(d.get("app", "")),
        "open_folder": lambda d: open_folder(d.get("folder", "~/Downloads")),
        "open_url": lambda d: open_url(d.get("url", "")),
        "create_file": lambda d: create_file(d.get("path", ""), d.get("content", "")),
        "read_file": lambda d: read_file(d.get("path", "")),
        "write_file": lambda d: write_file(d.get("path", ""), d.get("content", "")),
        "delete_file": lambda d: delete_file(d.get("path", "")),
        "list_dir": lambda d: list_directory(d.get("path", "~")),
        "create_folder": lambda d: create_folder(d.get("path", "")),
        "copy_item": lambda d: copy_item(d.get("source", ""), d.get("destination", "")),
        "move_item": lambda d: move_item(d.get("source", ""), d.get("destination", "")),
        "copy_to_clipboard": lambda d: copy_text_to_clipboard(d.get("text", "")),
        "battery": lambda d: get_battery(),
        "system_info": lambda d: get_system_info(),
        "processes": lambda d: get_running_processes(),
        "screenshot": lambda d: take_screenshot(d.get("path", "")),
        "run_command": lambda d: run_shell_command(d.get("command", "")),
        "type_in_app": lambda d: type_in_app(d.get("app", ""), d.get("content", "")),
        "send_keys": lambda d: send_keys(d.get("keys", "")),
        "click_position": lambda d: click_position(d.get("x", 0), d.get("y", 0), d.get("button", "left")),
        # ── Compound search actions ───────────────────────────────────
        "search_in_app": lambda d: search_in_app(d.get("app", ""), d.get("query", "")),
        "search_web": lambda d: search_web(d.get("query", ""), d.get("engine", "google")),
        "search_windows": lambda d: search_windows(d.get("query", "")),
        # ── New features ──────────────────────────────────────────────
        "set_volume": lambda d: set_volume(d.get("level", "50")),
        "toggle_mute": lambda d: toggle_mute(),
        "set_brightness": lambda d: set_brightness(d.get("level", "70")),
        "toggle_dark_mode": lambda d: toggle_dark_mode(),
        "lock_screen": lambda d: lock_screen(),
        "empty_recycle_bin": lambda d: empty_recycle_bin(),
        "toggle_wifi": lambda d: toggle_wifi(d.get("state", "toggle")),
        "search_files": lambda d: search_files(d.get("query", ""), d.get("file_type", ""), d.get("days", 0)),
        "control_music": lambda d: control_music(d.get("control", "play")),
        "open_music": lambda d: open_music(d.get("query", "music")),
        "set_reminder": lambda d: set_reminder(session.user_id, d.get("text", ""), d.get("time", "30 minutes")),
        "list_reminders": lambda d: list_reminders(session.user_id),
        "delete_reminder": lambda d: delete_reminder(session.user_id, d.get("index", -1)),
        "clipboard_history": lambda d: get_clipboard_history(d.get("count", 5)),
        "log_habit": lambda d: log_habit(session.user_id, d.get("habit", "")),
        "habit_stats": lambda d: get_habit_stats(session.user_id, d.get("days", 7)),
        "mood_journal": lambda d: get_mood_journal(session.user_id, d.get("days", 7)),
        "read_screen": lambda d: read_screen(),
        "recall_memory": lambda d: recall_conversations(session.user_id, d.get("query", ""), d.get("days", 7)),
        "recognize_song": lambda d: {"status": "success", "action": "recognize_song", "_ws_trigger": "start_song_recognition", "detail": "Listening to the song for 8 seconds..."},
        "send_whatsapp": lambda d: send_whatsapp_message(d.get("contact", ""), d.get("message", ""), settings),
        "send_whatsapp_file": lambda d: send_whatsapp_file(d.get("contact", ""), d.get("file_path", "")),
        # ── Intelligent file sharing ───────────────────────────────────
        "send_to_app": lambda d: send_to_app(d.get("contact", ""), d.get("message", ""), d.get("app", "whatsapp"), d.get("file_path", "")),
        "send_file_smart": lambda d: send_file_with_message(d.get("contact", ""), d.get("file_name", ""), d.get("app", "whatsapp"), d.get("custom_message", ""), d.get("compose_message", False), location=d.get("location", ""), session=session, settings=settings),
        "find_file": lambda d: find_file_smart(d.get("name", ""), location=d.get("location", "")),
        # ── Install / Uninstall (background) ───────────────────────────
        "install_app": lambda d: install_app(d.get("app", "")),
        "uninstall_app": lambda d: uninstall_app(d.get("app", "")),
        "check_task_status": lambda d: check_task_status(d.get("task_id", "")),
        # ── Visual Context Automation ─────────────────────────────────
        "navigate_ui": lambda d: navigate_ui(d.get("target", ""), settings=settings),
        "switch_and_execute": lambda d: switch_and_execute(d.get("app", ""), d.get("command", ""), d.get("return", True), settings=settings),
    }

    handler = ACTION_MAP.get(action)
    if handler:
        log.info("[%s] Executing automation: %s | data=%s", session.session_id, action, json.dumps(action_data)[:100])
        result = handler(action_data)
        # Check if this triggers dictation mode
        if result and result.get("dictation_mode"):
            session.dictation_active = True
            session.dictation_app = result.get("app", "")
            log.info("[%s] Dictation mode activated for app: %s", session.session_id, session.dictation_app)
        # Check if app is not installed — signal store redirect
        if result and result.get("status") == "not_installed":
            log.info("[%s] App not installed: %s → store redirect", session.session_id, result.get("app"))
    else:
        return [f"Unknown automation action: {action}"]

    # ── Build metadata for special results (forwarded to frontend) ───────
    meta = None
    if result and result.get("status") == "not_installed":
        meta = {
            "__meta__": True,
            "type": "app_not_installed",
            "app": result.get("app", ""),
            "store_url": result.get("store_url", ""),
        }
    elif result and result.get("_ws_trigger"):
        meta = {
            "__meta__": True,
            "type": result["_ws_trigger"],
        }

    # ── Format result via LLM ─────────────────────────────────────────────
    if result:
        from groq_pool import get_rotator as _get_groq_rotator
        _groq_key = _get_groq_rotator().get_key()
        if _groq_key:
            try:
                from groq import Groq
                client = Groq(api_key=_groq_key)

                format_prompt = f"""You are Alita, a voice assistant. 
The user asked: "{user_text}"
The action result is: {json.dumps(result)}
LANGUAGE RULE: If the user spoke English, reply in PURE English only. If Hindi, reply in PURE Hindi (Devanagari) only. NEVER mix languages.
Give a natural, concise spoken response (1 sentence). Sound human, not robotic."""

                resp = client.chat.completions.create(
                    model=settings.groq_model,
                    messages=[{"role": "user", "content": format_prompt}],
                    max_tokens=60,
                    temperature=0.5,
                )
                text = resp.choices[0].message.content
                if text:
                    tokens = [text]
                    if meta:
                        tokens.append(meta)
                    return tokens
            except Exception:
                pass

    # Fallback: return raw result
    if result:
        status_val = result.get("status", "unknown")
        if status_val == "success":
            tokens = [f"Done! {result.get('action', 'Action')} completed successfully."]
        elif status_val == "not_installed":
            tokens = [f"{result.get('app', 'The app')} is not installed. Would you like to install it from the Microsoft Store?"]
        else:
            tokens = [f"Error: {result.get('error', 'Unknown error')}"]
        if meta:
            tokens.append(meta)
        return tokens

    return ["I completed the action but couldn't verify the result."]
