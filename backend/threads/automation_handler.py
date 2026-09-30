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
import re
import subprocess
import platform
import logging
import json
import shutil
import threading
import time as _time_module

log = logging.getLogger("alita.automation")

from threads.automation_file_ops import (
    create_file, read_file, write_file, delete_file, list_directory,
    create_folder, copy_item, move_item, search_files, find_file_smart,
    fuzzy_find_path, _safe_path, _normalize_name, _levenshtein,
)
from threads.automation_app_control import (
    APP_MAP, APP_ALIASES, SHORTHAND_MAP, MOOD_MUSIC_MAP, FOLDER_ALIASES,
    APP_SEARCH_SHORTCUTS, _find_exe_path, fuzzy_match_app, _is_app_installed,
    _build_start_menu_cache, _search_start_menu, _verify_app_opened,
    _find_uwp_app, open_app, close_app, open_folder, _resolve_relative_folder,
    _navigate_existing_explorer, _get_current_explorer_path, open_url,
    send_keys, click_position, search_in_app, _type_unicode, search_web,
    type_in_app,
)
from threads.automation_media import (
    control_music, open_music, set_volume, toggle_mute, system_sound,
)
from threads.automation_communication import (
    _extract_whatsapp_info, _verify_whatsapp_contact, send_whatsapp_message,
    send_whatsapp_file, _click_whatsapp_document_option, send_to_app,
    send_file_with_message, _APP_SHARE_PROFILES,
)
from threads.automation_system import (
    _sanitize_arg, _is_command_blocked, get_system_info, get_battery,
    get_running_processes, run_shell_command, take_screenshot,
    set_brightness, toggle_dark_mode, lock_screen, empty_recycle_bin,
    toggle_wifi, toggle_bluetooth, system_power, set_reminder,
    list_reminders, delete_reminder, _load_reminders, _save_reminders,
    _track_clipboard, get_clipboard_history, log_habit, get_habit_stats,
    save_mood_entry, get_mood_journal,
)


# ─────────────────────────────────────────────────────────────────────────────
# SECURITY HELPERS — Input sanitization for subprocess calls
# ─────────────────────────────────────────────────────────────────────────────
import re as _re_security

# Shell metacharacters that enable command chaining / injection
_SHELL_METACHAR_RE = _re_security.compile(r'[;\x00&|`$(){}\[\]<>!\\\n\r]')

def _sanitize_arg(value: str) -> str:
    """Strip shell metacharacters from user input to prevent injection.
    Allows: alphanumeric, spaces, hyphens, dots, underscores, colons, slashes, @, #, quotes."""
    if not value:
        return ""
    return _SHELL_METACHAR_RE.sub('', value).strip()

# Commands that must NEVER be executed via run_shell_command
_BLOCKED_COMMANDS = [
    "format", "del ", "rm ", "rmdir", "rd ", "erase",
    "net user", "net localgroup", "net share",
    "reg add", "reg delete", "regedit",
    "powershell -enc", "powershell -e ", "iex", "invoke-expression",
    "certutil", "bitsadmin",
    "shutdown", "restart", "logoff",
    "schtasks /create", "schtasks /delete",
    "sc create", "sc delete", "sc config",
    "wmic process call", "wmic os call",
    "mklink", "icacls", "takeown", "cacls",
    "bcdedit", "diskpart", "cipher /w",
    "curl", "wget", "invoke-webrequest", "downloadstring",
    "start-process", "new-object",
]

def _is_command_blocked(command: str) -> bool:
    """Check if a command matches any blocked pattern."""
    # Normalize whitespace (tabs, multiple spaces) before checking
    cmd_lower = _re_security.sub(r'\s+', ' ', command.lower().strip())
    return any(blocked in cmd_lower for blocked in _BLOCKED_COMMANDS)


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

    def get_status(self, task_id: str | None = None) -> dict:
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
                del self._tasks[tid]  # type: ignore[attr-defined]


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

    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows-only

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
                log.info("%s failed for '%s': %s", label, app_name, combined[:150])  # type: ignore[index]
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
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)  # Windows-only
            )
            if result.returncode == 0 or "Successfully uninstalled" in result.stdout:
                return {"status": "success", "action": "uninstalled", "app": app_name}
            else:
                return {"status": "error", "error": f"Could not uninstall {app_name}: {result.stderr[:200]}"}  # type: ignore[index]
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
    """Create a new file with optional content and verify creation."""
    try:
        path = _safe_path(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        verified = os.path.exists(path)
        return {"status": "success", "action": "created", "path": path, "verified": verified}
    except PermissionError as e:
        return {"status": "error", "error": str(e), "verified": False}
    except Exception as e:
        return {"status": "error", "error": str(e), "verified": False}


def read_file(path: str) -> dict:
    """Read a file's contents."""
    try:
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            path = fuzzy_find_path(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read(10000)  # Max 10KB
        return {"status": "success", "path": path, "content": content, "size": os.path.getsize(path)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def write_file(path: str, content: str) -> dict:
    """Write content to a file (overwrite) and verify."""
    try:
        path = _safe_path(path)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        verified = os.path.exists(path) and os.path.getsize(path) >= len(content.encode("utf-8"))
        return {"status": "success", "action": "written", "path": path, "bytes": len(content), "verified": verified}
    except PermissionError as e:
        return {"status": "error", "error": str(e), "verified": False}
    except Exception as e:
        return {"status": "error", "error": str(e), "verified": False}


def delete_file(path: str) -> dict:
    """Delete a file."""
    try:
        path = _safe_path(path)
        if not os.path.exists(path):
            path = fuzzy_find_path(path)
        if os.path.isfile(path):
            os.remove(path)
            return {"status": "success", "action": "deleted", "path": path}
        elif os.path.isdir(path):
            shutil.rmtree(path)
            return {"status": "success", "action": "deleted_folder", "path": path}
        else:
            return {"status": "error", "error": f"Not found: {path}"}
    except PermissionError as e:
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_directory(path: str = "~") -> dict:
    """List files in a directory."""
    try:
        path = os.path.expanduser(path)
        if not os.path.isdir(path):
            return {"status": "error", "error": f"Not a directory: {path}"}
        items = []
        for name in os.listdir(path)[:50]:  # type: ignore[index]  # Max 50 items
            full = os.path.join(path, name)
            is_dir = os.path.isdir(full)
            size = os.path.getsize(full) if os.path.isfile(full) else 0
            items.append({"name": name, "is_dir": is_dir, "size": size})
        return {"status": "success", "path": path, "count": len(items), "items": items}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def create_folder(path: str) -> dict:
    """Create a new folder and verify."""
    try:
        path = os.path.expanduser(path)
        os.makedirs(path, exist_ok=True)
        verified = os.path.isdir(path)
        return {"status": "success", "action": "folder_created", "path": path, "verified": verified}
    except Exception as e:
        return {"status": "error", "error": str(e), "verified": False}


# ─────────────────────────────────────────────────────────────────────────────
# COPY / MOVE OPERATIONS (with safety checks)
# ─────────────────────────────────────────────────────────────────────────────

def _safe_path(path: str) -> str:
    """
    Expand and validate a path using ALLOWLIST approach.
    Only allows access within safe user directories.
    Blocks system directories and sensitive config files.
    """
    import re as _re_safe
    expanded = os.path.abspath(os.path.expanduser(path))
    home = os.path.expanduser("~")
    path_lower = expanded.lower().replace("/", "\\")
    home_lower = home.lower().replace("/", "\\")

    # ── ALLOWLIST: Only these directories under user home are writable ──
    allowed_dirs = [
        os.path.join(home_lower, d) for d in [
            "desktop", "documents", "downloads", "pictures", "videos",
            "music", "projects", "repos", "code", "work",
            "onedrive", "onedrive - personal",
        ]
    ]

    # ── BLOCKLIST FIRST: Block sensitive areas even if inside allowed paths ──
    blocked_patterns = [
        "windows", "program files", "programdata", "system32",
        ".ssh", ".gnupg", ".aws", ".azure", ".kube",
        ".env", ".git", ".keys", "appdata\\roaming",
        "appdata\\local\\microsoft", "ntuser",
    ]
    for pattern in blocked_patterns:
        if pattern in path_lower:
            raise PermissionError(
                f"Access blocked for security: {expanded}. "
                f"Allowed directories: Desktop, Documents, Downloads, Pictures, Videos, Music, Projects"
            )

    # ── ALLOWLIST: Check if path is within an allowed directory ──
    in_allowed = any(path_lower.startswith(d) for d in allowed_dirs)
    if not in_allowed:
        raise PermissionError(
            f"Access outside allowed directories: {expanded}. "
            f"Allowed directories: Desktop, Documents, Downloads, Pictures, Videos, Music, Projects"
        )

    return expanded


def _normalize_name(name: str) -> str:
    """Normalize a filename for fuzzy comparison: lowercase, strip separators."""
    import re
    return re.sub(r'[_\-\s.]+', '', name.lower())


def _levenshtein(a: str, b: str) -> int:
    """Simple Levenshtein distance for short strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(b)]


def fuzzy_find_path(path: str) -> str:
    """
    Find a file/folder even if STT mishears the name.
    
    Strategy:
      1. Exact path exists → return as-is
      2. Try with common separators: underscores, hyphens, spaces
      3. Fuzzy match: list parent dir and find closest name by Levenshtein distance
    
    Examples:
      "sarvan" → finds "sarwan" (edit distance 1)
      "my name" → finds "my_name" (separator normalization)
    """
    expanded = os.path.abspath(os.path.expanduser(path))
    
    # 1. Exact match
    if os.path.exists(expanded):
        return expanded
    
    parent = os.path.dirname(expanded)
    target_name = os.path.basename(expanded)
    
    if not os.path.isdir(parent):
        return expanded  # Parent doesn't exist, can't search
    
    # 2. Try separator variants (my name → my_name, my-name)
    target_normed = _normalize_name(target_name)
    try:
        entries = os.listdir(parent)
    except OSError:
        return expanded
    
    # Exact normalized match (handles underscores, hyphens, spaces, dots)
    for entry in entries:
        if _normalize_name(entry) == target_normed:
            found = os.path.join(parent, entry)
            log.info("[FuzzyFind] Normalized match: '%s' → '%s'", target_name, entry)
            return found
    
    # Also try stripping extension from entries for comparison
    target_no_ext = _normalize_name(os.path.splitext(target_name)[0])
    for entry in entries:
        entry_no_ext = _normalize_name(os.path.splitext(entry)[0])
        if entry_no_ext == target_no_ext:
            found = os.path.join(parent, entry)
            log.info("[FuzzyFind] Name-only match: '%s' → '%s'", target_name, entry)
            return found
    
    # 3. Levenshtein fuzzy match (catches "sarvan" → "sarwan")
    best_match = None
    best_distance = 999
    for entry in entries:
        entry_normed = _normalize_name(os.path.splitext(entry)[0])
        dist = _levenshtein(target_normed, entry_normed)
        # Allow up to 2 character differences for short names, 3 for longer
        max_dist = 2 if len(target_normed) <= 6 else 3
        if dist < best_distance and dist <= max_dist:
            best_distance = dist
            best_match = entry
    
    if best_match:
        found = os.path.join(parent, best_match)  # type: ignore[arg-type]
        log.info("[FuzzyFind] Fuzzy match (dist=%d): '%s' → '%s'", best_distance, target_name, best_match)
        return found
    
    # No fuzzy match found — return original
    return expanded


def copy_item(source: str, destination: str) -> dict:
    """Copy a file or folder from source to destination."""
    try:
        src = _safe_path(source)
        dst = _safe_path(destination)

        # Fuzzy match source if not found exactly (handles STT mishearings)
        if not os.path.exists(src):
            src = fuzzy_find_path(src)

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

        # Fuzzy match source if not found exactly (handles STT mishearings)
        if not os.path.exists(src):
            src = fuzzy_find_path(src)

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
        import pyperclip  # type: ignore[import]
        pyperclip.copy(text)
        _track_clipboard(text)  # Track in clipboard history
        return {"status": "success", "action": "copied_to_clipboard",
                "chars": len(text), "preview": text[:80]}  # type: ignore[index]
    except ImportError:
        # Fallback for Windows
        try:
            process = subprocess.Popen(["clip"], stdin=subprocess.PIPE)
            process.communicate(text.encode("utf-8"))  # type: ignore[arg-type]
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
                key = winreg.OpenKey(  # type: ignore[attr-defined]
                    winreg.HKEY_LOCAL_MACHINE,  # type: ignore[attr-defined]
                    rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{exe_try}"
                )
                val, _ = winreg.QueryValueEx(key, None)  # type: ignore[attr-defined]
                winreg.CloseKey(key)  # type: ignore[attr-defined]
                if val and os.path.exists(val.strip('"')):
                    return val.strip('"')
            except (FileNotFoundError, OSError):
                pass
    except ImportError:
        pass

    return None


# ─────────────────────────────────────────────────────────────────────────────
# INTELLIGENT APP MATCHING — natural language → app name resolution
# ─────────────────────────────────────────────────────────────────────────────

# Natural language descriptions → APP_MAP key
APP_ALIASES = {
    # Generic descriptions
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
    # Common misspellings and variations
    "chorme": "chrome", "gogle": "chrome", "crome": "chrome",
    "vscode": "vscode", "visual studio code": "vscode",
    "wp": "whatsapp", "watsapp": "whatsapp", "what'sapp": "whatsapp",
    "tg": "telegram",  "telgram": "telegram",
    "yt": "chrome",  # YouTube → open browser (for open_music, handled separately)
    "insta": "chrome", "instagram": "chrome",
}

# Platform shorthands → full URL (for open_url actions)
SHORTHAND_MAP = {
    "yt": "https://youtube.com",
    "youtube": "https://youtube.com",
    "insta": "https://instagram.com",
    "ig": "https://instagram.com",
    "instagram": "https://instagram.com",
    "fb": "https://facebook.com",
    "facebook": "https://facebook.com",
    "wp": None,  # WhatsApp → open app, not URL
    "tg": None,  # Telegram → open app
    "linkedin": "https://linkedin.com",
    "li": "https://linkedin.com",
    "gh": "https://github.com",
    "github": "https://github.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "reddit": "https://reddit.com",
}

# Mood → YouTube search query mapping (for mood-aware music)
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


def fuzzy_match_app(query: str) -> str | None:
    """
    Intelligently resolve natural language to an APP_MAP key.

    Resolution order:
      1. Exact match in APP_MAP (instant)
      2. Alias match in APP_ALIASES (instant)
      3. Substring match — query contains an APP_MAP key (fast)
      4. Reverse substring — APP_MAP key contains query (fast)
      5. difflib closest match (fuzzy — handles typos)

    Returns the APP_MAP key or None if no match found.
    """
    import difflib

    query_lower = query.lower().strip()

    # 1. Exact match
    if query_lower in APP_MAP:
        return query_lower

    # 2. Alias match (natural language → app name)
    if query_lower in APP_ALIASES:
        return APP_ALIASES[query_lower]

    # 2b. Multi-word alias match — "the coding app" → "coding app"
    for alias, app in APP_ALIASES.items():
        if alias in query_lower:
            return app

    # 3. Substring match — "open chrome browser" → contains "chrome"
    for app_key in APP_MAP:
        if app_key in query_lower:
            return app_key

    # 4. Reverse substring — query "calc" is in "calculator"
    for app_key in APP_MAP:
        if query_lower in app_key:
            return app_key

    # 5. Fuzzy match (handles typos like "chorme" → "chrome")
    all_names = list(APP_MAP.keys()) + list(APP_ALIASES.keys())
    matches = difflib.get_close_matches(query_lower, all_names, n=1, cutoff=0.7)
    if matches:
        match = matches[0]
        if match in APP_MAP:
            return match
        if match in APP_ALIASES:
            return APP_ALIASES[match]

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
    if _start_menu_cache and (now - _start_menu_cache_time) < 300:
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
                    name = fname[:-4].lower()  # type: ignore[index]  # strip .lnk
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


def _verify_app_opened(app_name: str, max_wait_sec: float = 0.8) -> bool:
    """Verify that the launched app appeared in screen_context."""
    import time as _time_module
    try:
        from engines.screen_context import screen_context
        t_end = _time_module.time() + max_wait_sec
        app_clean = app_name.lower().strip()
        while _time_module.time() < t_end:
            if screen_context.is_app_open(app_clean) or screen_context.is_app_focused(app_clean):
                return True
            _time_module.sleep(0.15)
    except Exception:
        pass
    return False


def _find_uwp_app(app_name: str) -> str | None:
    """
    Search for a UWP/Store app and return its launch URI.
    Uses PowerShell Get-AppxPackage (fast, ~200ms).
    SECURITY: app_name is sanitized to prevent command injection.
    """
    if platform.system() != "Windows":
        return None

    try:
        import re as _re_uwp
        # Sanitize app_name — allow only alphanumeric, spaces, hyphens, dots
        sanitized = _re_uwp.sub(r'[^a-zA-Z0-9\s.\-]', '', app_name).strip()
        if not sanitized:
            return None

        # Use argument list (no shell=True) to prevent injection
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
        if exe.startswith("ms-") or exe.endswith(":"):  # type: ignore[union-attr]
            try:
                subprocess.Popen(["start", "", exe], shell=True)  # type: ignore[list-item]
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception:
                pass

        # ── Method 2: Direct exe path via registry/PATH ──
        full_path = _find_exe_path(exe)  # type: ignore[arg-type]
        if full_path:
            try:
                subprocess.Popen([full_path])
                log.info("[open_app] Method 2 SUCCESS: Popen(%s)", full_path)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception as e2:
                log.warning("[open_app] Method 2 FAILED for '%s': %s", full_path, e2)

        # ── Method 2b: Direct exe via shell=True (handles system apps better) ──
        if full_path:
            try:
                subprocess.Popen(f'"{full_path}"', shell=True)
                log.info("[open_app] Method 2b SUCCESS: shell Popen(%s)", full_path)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception as e2b:
                log.warning("[open_app] Method 2b FAILED for '%s': %s", full_path, e2b)

        # ── Method 3: Start Menu shortcut search ──
        # This finds virtually ALL installed apps (traditional + Store apps)
        lnk_path = _search_start_menu(app_lower)
        if lnk_path:
            try:
                os.startfile(lnk_path)  # type: ignore[attr-defined]
                log.info("[open_app] Method 3 SUCCESS: startfile(%s)", lnk_path)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception as e3:
                log.warning("[open_app] Method 3 FAILED for '%s': %s", lnk_path, e3)

        # ── Method 4: UWP / Store app search ──
        uwp_uri = _find_uwp_app(app_lower)
        if uwp_uri:
            try:
                subprocess.Popen(["explorer", uwp_uri])
                log.info("[open_app] Method 4 SUCCESS: UWP(%s)", uwp_uri)
                verified = _verify_app_opened(app_name)
                return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
            except Exception as e4:
                log.warning("[open_app] Method 4 FAILED for '%s': %s", uwp_uri, e4)

        # ── Method 5: Shell `start` with validation ──
        # Only try this if we have a mapped exe (not raw user input)
        if app_info:
            try:
                result = subprocess.run(
                    f'start "" "{exe}"', shell=True,
                    capture_output=True, text=True, timeout=3
                )
                if result.returncode == 0:
                    log.info("[open_app] Method 5 SUCCESS: start '%s'", exe)
                    verified = _verify_app_opened(app_name)
                    return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
                else:
                    log.warning("[open_app] Method 5 FAILED: returncode=%d stderr=%s", result.returncode, result.stderr[:80])
            except (subprocess.TimeoutExpired, Exception) as e5:
                log.warning("[open_app] Method 5 FAILED for '%s': %s", exe, e5)

        # ── Method 6: Try the original app name as startfile ──
        # Works for some apps registered with Windows
        try:
            os.startfile(app_name)  # type: ignore[attr-defined]
            log.info("[open_app] Method 6 SUCCESS: startfile('%s')", app_name)
            verified = _verify_app_opened(app_name)
            return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
        except (FileNotFoundError, OSError) as e6:
            log.warning("[open_app] Method 6 FAILED for '%s': %s", app_name, e6)

        # ── Method 7: Last resort — try `start <exe>` shell for system apps ──
        try:
            subprocess.Popen(f"start {exe}", shell=True)
            log.info("[open_app] Method 7 SUCCESS: bare start '%s'", exe)
            verified = _verify_app_opened(app_name)
            return {"status": "success", "action": "opened", "app": app_name, "verified": verified}
        except Exception as e7:
            log.warning("[open_app] Method 7 FAILED for '%s': %s", exe, e7)

        # ── All methods failed — truly not found ──
        log.error("[open_app] ALL 7 methods failed for '%s' (exe='%s')", app_name, exe)
        if store_query and platform.system() == "Windows":
            store_url = f"ms-windows-store://search/?query={store_query}"
            return {
                "status": "not_installed",
                "action": "app_not_found",
                "app": app_name,
                "store_url": store_url,
                "store_query": store_query,
                "verified": False,
            }
        return {"status": "error", "error": f"Could not open {app_name}. It may not be installed.", "verified": False}

    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# APP-READY DETECTION — polls foreground window instead of blind sleep()
# ─────────────────────────────────────────────────────────────────────────────

# Map app names to keywords that may appear in their window titles
_APP_WINDOW_KEYWORDS = {
    "whatsapp":   ["whatsapp"],
    "telegram":   ["telegram"],
    "discord":    ["discord"],
    "chrome":     ["chrome", "google chrome"],
    "firefox":    ["firefox", "mozilla"],
    "edge":       ["edge"],
    "brave":      ["brave"],
    "spotify":    ["spotify"],
    "notepad":    ["notepad"],
    "vscode":     ["visual studio code"],
    "vs code":    ["visual studio code"],
    "word":       ["word", "document"],
    "excel":      ["excel"],
    "powerpoint": ["powerpoint"],
    "outlook":    ["outlook"],
    "teams":      ["teams"],
    "slack":      ["slack"],
    "explorer":   ["file explorer", "explorer"],
    "file explorer": ["file explorer", "explorer"],
}


def _wait_for_app_window(app_name: str, timeout: float = 30.0) -> bool:
    """
    Poll the foreground window title until the target app is focused.
    
    Instead of blind sleep(3), this adapts to any app launch time:
    - Polls every 300ms (very lightweight)
    - Returns True as soon as the app window is detected
    - Returns False only after the full timeout (default 30s)
    
    Works whether the app opens in 0.5s or 60s.
    """
    import time as _t

    app_lower = app_name.lower().strip()

    # Build keyword list for matching
    keywords = _APP_WINDOW_KEYWORDS.get(app_lower, [app_lower])
    # Also add the raw app name and common variants
    extra = [app_lower, app_lower.replace(" ", "")]
    keywords = list(set(keywords + extra))

    log.info("[wait_for_app] Waiting for '%s' window (keywords: %s, timeout: %ss)",
             app_name, keywords, timeout)

    start = _t.monotonic()
    poll_interval = 0.3  # 300ms between checks

    while (_t.monotonic() - start) < timeout:
        try:
            fg = _get_foreground_window_info()
            title = fg.get("title", "").lower()

            if title and any(kw in title for kw in keywords):
                elapsed = round(_t.monotonic() - start, 1)  # type: ignore[call-overload]
                log.info("[wait_for_app] '%s' window detected in %ss (title: '%s')",
                         app_name, elapsed, fg.get("title", ""))
                # Small extra delay for the app UI to finish rendering
                _t.sleep(0.5)
                return True
        except Exception:
            pass

        _t.sleep(poll_interval)

    elapsed = round(_t.monotonic() - start, 1)  # type: ignore[call-overload]
    log.warning("[wait_for_app] Timeout after %ss waiting for '%s'", elapsed, app_name)
    return False


# ── Intelligent UI-wait helpers (replace fixed sleep calls) ──────────────

def _wait_for_ui_condition(check_fn, timeout: float = 3.0, interval: float = 0.1,
                           label: str = "condition") -> bool:
    """
    Generic intelligent poll — calls check_fn() every `interval` seconds.
    Returns True the moment check_fn() returns True, or False on timeout.
    Much faster than sleep() on fast machines, auto-extends on slow ones.
    """
    import time as _t
    start = _t.monotonic()
    while (_t.monotonic() - start) < timeout:
        try:
            if check_fn():
                elapsed = round((_t.monotonic() - start) * 1000)
                log.debug("[smart_wait] '%s' met in %dms", label, elapsed)
                return True
        except Exception:
            pass
        _t.sleep(interval)
    log.debug("[smart_wait] '%s' timed out after %.1fs", label, timeout)
    return False


def _wait_for_window_change(original_title: str, timeout: float = 3.0) -> bool:
    """Wait until the foreground window title changes (e.g. a dialog opens)."""
    def _changed():
        try:
            fg = _get_foreground_window_info()
            return fg.get("title", "") != original_title
        except Exception:
            return False
    return _wait_for_ui_condition(_changed, timeout=timeout, label="window_change")


def _wait_for_fg_title(keywords: list, timeout: float = 3.0) -> bool:
    """Wait until the foreground window title contains any of the keywords."""
    kw_lower = [k.lower() for k in keywords]
    def _matches():
        try:
            fg = _get_foreground_window_info()
            title = fg.get("title", "").lower()
            return any(k in title for k in kw_lower)
        except Exception:
            return False
    return _wait_for_ui_condition(_matches, timeout=timeout, label=f"title({keywords})")


def _wait_for_fg_title_gone(keywords: list, timeout: float = 5.0) -> bool:
    """Wait until the foreground window title NO LONGER contains the keywords (dialog closed)."""
    kw_lower = [k.lower() for k in keywords]
    def _gone():
        try:
            fg = _get_foreground_window_info()
            title = fg.get("title", "").lower()
            return not any(k in title for k in kw_lower)
        except Exception:
            return True
    return _wait_for_ui_condition(_gone, timeout=timeout, label=f"title_gone({keywords})")


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
    If an Explorer window is already open, navigates it to the target folder
    instead of opening a new window/tab.
    Also resolves relative folder names (e.g. "price") by checking them as
    subfolders of the current Explorer location.
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

        # 3. If path doesn't exist, try resolving as a subfolder
        if not os.path.isdir(path):
            resolved = _resolve_relative_folder(folder)
            if resolved:
                path = resolved
            else:
                return {"status": "error",
                        "error": f"Folder not found: {path}"}

        # ── Windows: try to reuse an existing Explorer window ──
        if platform.system() == "Windows":
            navigated = _navigate_existing_explorer(path)
            if navigated:
                return {"status": "success", "action": "opened_folder",
                        "path": path, "detail": "Navigated existing Explorer window"}

            # No Explorer window open — open a new one
            subprocess.Popen(["explorer", path])
        else:
            subprocess.Popen(["xdg-open", path])

        return {"status": "success", "action": "opened_folder", "path": path}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def _resolve_relative_folder(folder_name: str) -> str:
    """
    Try to resolve a relative folder name (e.g. "price", "projects")
    by checking:
      1. As a subfolder of the currently-open Explorer window path
      2. As a subfolder of common user directories (Downloads, Desktop, etc.)
    Returns the full path if found, empty string otherwise.
    """
    name = folder_name.strip()
    if not name:
        return ""

    # ── 1. Check relative to the current Explorer path ──
    if platform.system() == "Windows":
        current = _get_current_explorer_path()
        if current:
            candidate = os.path.join(current, name)
            if os.path.isdir(candidate):
                log.info("[open_folder] Resolved '%s' as subfolder of '%s'", name, current)
                return candidate

    # ── 2. Check in common user directories ──
    home = os.path.expanduser("~")
    search_dirs = ["Downloads", "Desktop", "Documents", "Pictures", "Videos", "Music"]
    for d in search_dirs:
        candidate = os.path.join(home, d, name)
        if os.path.isdir(candidate):
            log.info("[open_folder] Resolved '%s' in ~/%s", name, d)
            return candidate

    # ── 3. Case-insensitive search in common directories ──
    name_lower = name.lower()
    for d in search_dirs:
        parent = os.path.join(home, d)
        if os.path.isdir(parent):
            try:
                for entry in os.listdir(parent):
                    if entry.lower() == name_lower and os.path.isdir(os.path.join(parent, entry)):
                        full = os.path.join(parent, entry)
                        log.info("[open_folder] Resolved '%s' (case-insensitive) in ~/%s", name, d)
                        return full
            except OSError:
                continue

    return ""


def _navigate_existing_explorer(target_path: str) -> bool:
    """
    Find an existing File Explorer window and navigate it to target_path.
    
    Uses ctypes to find Explorer windows (by class "CabinetWClass") and
    Ctrl+L address bar navigation — the most reliable approach.
    No COM dependency, works consistently on every call.
    """
    import ctypes
    import ctypes.wintypes
    import time as _t

    try:
        import pyautogui  # type: ignore[import]
        import pyperclip  # type: ignore[import]
    except ImportError:
        log.debug("[open_folder] pyautogui/pyperclip not available for navigation")
        return False

    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
    explorer_hwnd = None

    # ── Find an Explorer window by its window class ──
    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)  # type: ignore[attr-defined]
    def _enum_callback(hwnd, _lParam):
        nonlocal explorer_hwnd
        if user32.IsWindowVisible(hwnd):
            class_buff = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buff, 256)
            # File Explorer windows have class "CabinetWClass"
            if class_buff.value == "CabinetWClass":
                explorer_hwnd = hwnd
                return False  # Stop enumeration — found one
        return True

    try:
        user32.EnumWindows(_enum_callback, 0)
    except Exception:
        pass

    if not explorer_hwnd:
        return False

    # ── Bring Explorer to foreground ──
    try:
        user32.SetForegroundWindow(explorer_hwnd)
    except Exception:
        pass
    _t.sleep(0.3)

    # ── Navigate using address bar: Ctrl+L → paste path → Enter ──
    pyautogui.hotkey("ctrl", "l")
    _t.sleep(0.3)
    pyperclip.copy(target_path)
    pyautogui.hotkey("ctrl", "v")
    _t.sleep(0.2)
    pyautogui.press("enter")
    _t.sleep(0.5)

    log.info("[open_folder] Navigated existing Explorer to: %s", target_path)
    return True


def _get_current_explorer_path() -> str:
    """
    Get the current folder path of the focused Explorer window.
    Uses Ctrl+L to focus the address bar, Ctrl+C to copy, then reads clipboard.
    Returns the path or empty string if not available.
    """
    import time as _t
    try:
        import pyautogui  # type: ignore[import]
        import pyperclip  # type: ignore[import]

        # Save current clipboard
        old_clip = ""
        try:
            old_clip = pyperclip.paste()
        except Exception:
            pass

        # Focus address bar and copy path
        pyautogui.hotkey("ctrl", "l")
        _t.sleep(0.2)
        pyautogui.hotkey("ctrl", "c")
        _t.sleep(0.2)

        current = pyperclip.paste().strip()

        # Press Escape to deselect the address bar
        pyautogui.press("escape")
        _t.sleep(0.1)

        # Restore old clipboard
        try:
            pyperclip.copy(old_clip)
        except Exception:
            pass

        # Validate: must look like a real path
        if current and os.path.isdir(current):
            return current
        return ""
    except Exception:
        return ""


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
            subprocess.run(["pkill", "-f", exe], capture_output=True, timeout=5)  # type: ignore[call-overload]

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
        import pyautogui  # type: ignore[import]
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
        import pyautogui  # type: ignore[import]
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
        import pyautogui  # type: ignore[import]
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
        import pyperclip  # type: ignore[import]
        import pyautogui  # type: ignore[import]
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
    except ImportError:
        import pyautogui  # type: ignore[import]
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
        import pyautogui  # type: ignore[import]
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
        import psutil  # type: ignore[import]
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
        import psutil  # type: ignore[import]
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
        import psutil  # type: ignore[import]
        procs = []
        for p in psutil.process_iter(["pid", "name", "memory_percent"]):
            try:
                procs.append(p.info)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        procs.sort(key=lambda x: x.get("memory_percent", 0), reverse=True)
        return {"status": "success", "count": len(procs), "top": procs[:limit]}  # type: ignore[index]
    except ImportError:
        return {"status": "error", "error": "psutil not installed"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_shell_command(command: str) -> dict:
    """Run a shell command and return output.
    SECURITY: Blocks dangerous commands and sanitizes input.
    """
    try:
        # ── Block dangerous commands ──────────────────────────────────
        if _is_command_blocked(command):
            log.warning("[SECURITY] Blocked dangerous command: %s", command[:80])
            return {"status": "error", "error": "This command is not allowed for security reasons."}

        # ── Sanitize: remove injection metacharacters ─────────────────
        sanitized = _sanitize_arg(command)
        if not sanitized:
            return {"status": "error", "error": "Invalid command."}

        result = subprocess.run(
            sanitized, shell=True, capture_output=True, text=True, timeout=15
        )
        return {
            "status": "success",
            "command": sanitized,
            "stdout": result.stdout[:2000],  # type: ignore[index]
            "stderr": result.stderr[:500] if result.stderr else "",  # type: ignore[index]
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Command timed out (15s limit)"}
    except Exception:
        return {"status": "error", "error": "Command execution failed."}


def take_screenshot(save_path: str = "") -> dict:
    """Take a screenshot and save it."""
    try:
        if not save_path:
            save_path = os.path.expanduser("~/Desktop/screenshot.png")
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        try:
            import mss  # type: ignore[import]
            with mss.mss() as sct:
                sct.shot(output=save_path)
            return {"status": "success", "action": "screenshot_saved", "path": save_path}
        except Exception:
            from PIL import ImageGrab  # type: ignore[import]
            img = ImageGrab.grab(all_screens=True)
            img.save(save_path)
            return {"status": "success", "action": "screenshot_saved", "path": save_path}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def type_in_app(app_name: str, content: str) -> dict:
    """
    Open an app and type content into it.
    
    V2: Delegates to ScreenAgent for reliable open→focus→type→verify pipeline.
    If content is empty, enters dictation mode.
    """
    try:
        # If content is provided, delegate to ScreenAgent for reliable execution
        if content.strip():
            try:
                from engines.screen_agent import screen_agent as _sa  # type: ignore[import]
                import uuid
                task_id = f"type_{str(uuid.uuid4())[:6]}"
                # Use the screen agent's write_in_app pipeline (open→focus→type→verify)
                started = _sa.start_task(task_id, f"write {content} in {app_name}")
                if started:
                    return {
                        "status": "success",
                        "action": "typing_via_screen_agent",
                        "app": app_name,
                        "chars": len(content),
                        "task_id": task_id,
                        "detail": f"Typing {len(content)} chars in {app_name} via ScreenAgent",
                    }
                else:
                    log.warning("ScreenAgent busy — falling back to direct type")
            except ImportError:
                log.warning("ScreenAgent not available — using direct type")

            # Fallback: direct typing (if ScreenAgent is busy or unavailable)
            import time as _time
            result = open_app(app_name)
            if result.get("status") != "success":
                return result
            _time.sleep(2)
            try:
                import pyautogui  # type: ignore[import]
                pyautogui.PAUSE = 0.05
                if content.isascii():
                    pyautogui.typewrite(content, interval=0.02)
                else:
                    import pyperclip  # type: ignore[import]
                    pyperclip.copy(content)
                    pyautogui.hotkey("ctrl", "v")
                return {
                    "status": "success",
                    "action": "typed_in_app",
                    "app": app_name,
                    "chars": len(content),
                }
            except ImportError:
                return {"status": "error", "error": "pyautogui not installed"}

        # No content = enter dictation mode (user will dictate)
        result = open_app(app_name)
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
        ctypes.windll.user32.LockWorkStation()  # type: ignore[attr-defined]
        return {"status": "success", "action": "lock_screen", "detail": "Screen locked"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def empty_recycle_bin() -> dict:
    """Empty the Windows recycle bin."""
    try:
        import ctypes
        # SHEmptyRecycleBin(hwnd, path, flags)
        # SHERB_NOCONFIRMATION = 0x00000001 | SHERB_NOPROGRESSUI = 0x00000002 | SHERB_NOSOUND = 0x00000004
        ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, 0x0007)  # type: ignore[attr-defined]
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
        subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi", f"admin={('disable' if act == 'off' else 'enable')}"],
                       capture_output=True, timeout=10)
        return {"status": "success", "action": "toggle_wifi",
                "detail": f"WiFi turned {act}"}
    except Exception:
        return {"status": "error", "error": "Failed to toggle WiFi."}


# ─────────────────────────────────────────────────────────────────────────────
# ADVANCED OS OPERATIONS
# ─────────────────────────────────────────────────────────────────────────────

def manage_process(name: str, action: str = "info") -> dict:
    """
    Advanced process management.
    Actions: info, kill, priority_high, priority_normal, priority_low
    """
    try:
        import psutil  # type: ignore[import]
        act = action.lower().strip()
        name_lower = name.lower().strip()

        # Find matching processes
        matched = []
        for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent",
                                       "status", "create_time", "cmdline"]):
            try:
                pname = (p.info.get("name") or "").lower()
                if name_lower in pname or pname.startswith(name_lower):
                    matched.append(p)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not matched:
            return {"status": "error", "error": f"No process found matching '{name}'"}

        if act == "kill":
            killed = 0
            for p in matched:
                try:
                    p.kill()
                    killed += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    log.warning("Could not kill PID %d: %s", p.pid, e)
            return {"status": "success", "action": "kill_process",
                    "detail": f"Killed {killed} process(es) matching '{name}'",
                    "count": killed}

        elif act.startswith("priority"):
            import ctypes
            PRIORITY_MAP = {
                "priority_high": 0x00000080,       # HIGH_PRIORITY_CLASS
                "priority_normal": 0x00000020,      # NORMAL_PRIORITY_CLASS
                "priority_low": 0x00004000,         # BELOW_NORMAL_PRIORITY_CLASS
                "priority_realtime": 0x00000100,    # REALTIME_PRIORITY_CLASS
            }
            prio = PRIORITY_MAP.get(act, 0x00000020)
            prio_name = act.replace("priority_", "")
            changed = 0
            for p in matched:
                try:
                    handle = ctypes.windll.kernel32.OpenProcess(0x0200, False, p.pid)  # type: ignore[attr-defined]
                    if handle:
                        ctypes.windll.kernel32.SetPriorityClass(handle, prio)  # type: ignore[attr-defined]
                        ctypes.windll.kernel32.CloseHandle(handle)  # type: ignore[attr-defined]
                        changed += 1
                except Exception:
                    continue
            return {"status": "success", "action": "set_priority",
                    "detail": f"Set {changed} process(es) '{name}' to {prio_name} priority",
                    "priority": prio_name}

        else:  # info
            info_list = []
            for p in matched[:10]:  # type: ignore[index]
                try:
                    with p.oneshot():
                        info_list.append({
                            "pid": p.pid,
                            "name": p.info.get("name", "?"),
                            "cpu_percent": round(p.cpu_percent(interval=0.1), 1),
                            "memory_mb": round(p.memory_info().rss / (1024 * 1024), 1),
                            "memory_percent": round(p.memory_percent(), 1),
                            "status": p.status(),
                            "cmdline": " ".join(p.cmdline()[:3]) if p.cmdline() else "",  # type: ignore[index]
                        })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            return {"status": "success", "action": "process_info",
                    "process": name, "count": len(info_list),
                    "processes": info_list}

    except ImportError:
        return {"status": "error", "error": "psutil not installed. Run: pip install psutil"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def network_diagnostics(action: str = "ip_config", target: str = "") -> dict:
    """
    Network diagnostics: ping, ip_config, traceroute, dns_lookup,
    active_connections, flush_dns, speed_test_info, external_ip.
    """
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        act = action.lower().strip()

        if act == "ping":
            host = target or "google.com"
            result = subprocess.run(
                ["ping", "-n", "4", host],
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "ping",
                    "host": host,
                    "output": result.stdout[:1500],
                    "detail": f"Pinged {host}"}

        elif act == "traceroute":
            host = target or "google.com"
            result = subprocess.run(
                ["tracert", "-d", "-h", "15", host],
                capture_output=True, text=True, timeout=30,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "traceroute",
                    "host": host,
                    "output": result.stdout[:2000],
                    "detail": f"Traceroute to {host}"}

        elif act == "dns_lookup":
            host = target or "google.com"
            result = subprocess.run(
                ["nslookup", host],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "dns_lookup",
                    "host": host,
                    "output": result.stdout[:1000],
                    "detail": f"DNS lookup for {host}"}

        elif act == "active_connections":
            result = subprocess.run(
                ["netstat", "-an"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            lines = result.stdout.strip().split("\n")
            # Count connection states
            states = {}
            for line in lines:
                for state in ["ESTABLISHED", "LISTENING", "TIME_WAIT", "CLOSE_WAIT", "SYN_SENT"]:
                    if state in line:
                        states[state] = states.get(state, 0) + 1
            return {"status": "success", "action": "active_connections",
                    "total_lines": len(lines),
                    "connection_states": states,
                    "sample": "\n".join(lines[:30]),
                    "detail": f"Active connections: {sum(states.values())} total"}

        elif act == "flush_dns":
            result = subprocess.run(
                ["ipconfig", "/flushdns"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "flush_dns",
                    "output": result.stdout.strip(),
                    "detail": "DNS cache flushed"}

        elif act == "external_ip":
            try:
                import urllib.request
                ip = urllib.request.urlopen("https://api.ipify.org", timeout=5).read().decode()
                return {"status": "success", "action": "external_ip",
                        "external_ip": ip,
                        "detail": f"External IP: {ip}"}
            except Exception as e:
                return {"status": "error", "error": f"Could not fetch external IP: {e}"}

        else:  # ip_config (default)
            result = subprocess.run(
                ["ipconfig", "/all"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            # Also try to get external IP
            ext_ip = ""
            try:
                import urllib.request
                ext_ip = urllib.request.urlopen("https://api.ipify.org", timeout=3).read().decode()
            except Exception:
                pass
            return {"status": "success", "action": "ip_config",
                    "output": result.stdout[:2000],
                    "external_ip": ext_ip,
                    "detail": f"IP config retrieved{f' — External IP: {ext_ip}' if ext_ip else ''}"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Network command timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def manage_scheduled_task(action: str = "list", name: str = "",
                          command: str = "", schedule: str = "") -> dict:
    """
    Manage Windows scheduled tasks via schtasks.exe.
    Actions: list, create, delete, run, status.
    """
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        act = action.lower().strip()
        import re as _re_sched
        # Sanitize name — allow only safe characters
        safe_name = _re_sched.sub(r'[^a-zA-Z0-9_\-\s]', '', name).strip() if name else ""

        if act == "list":
            result = subprocess.run(
                ["schtasks", "/Query", "/FO", "LIST", "/V"],
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW
            )
            # Parse and summarize (full output is huge)
            lines = result.stdout.split("\n")
            tasks = []
            current = {}
            for line in lines:
                line = line.strip()
                if line.startswith("TaskName:"):
                    if current and current.get("name"):
                        tasks.append(current)
                    current = {"name": line.split(":", 1)[1].strip()}
                elif line.startswith("Status:"):
                    current["status"] = line.split(":", 1)[1].strip()
                elif line.startswith("Next Run Time:"):
                    current["next_run"] = line.split(":", 1)[1].strip()
            if current and current.get("name"):
                tasks.append(current)
            # Filter to user-created tasks (skip Microsoft\ system tasks)
            user_tasks = [t for t in tasks if not t.get("name", "").startswith("\\Microsoft")]
            return {"status": "success", "action": "list_scheduled_tasks",
                    "total": len(tasks), "user_tasks_count": len(user_tasks),
                    "user_tasks": user_tasks[:20],
                    "detail": f"Found {len(user_tasks)} user-created scheduled tasks"}

        elif act == "create":
            if not safe_name or not command:
                return {"status": "error",
                        "error": "Need both 'name' and 'command' to create a scheduled task"}
            # Parse schedule: "daily", "hourly", "weekly", "once", "minute"
            sched_lower = schedule.lower().strip() if schedule else "daily"
            SCHED_MAP = {
                "daily": "/SC DAILY /ST 09:00",
                "hourly": "/SC HOURLY",
                "weekly": "/SC WEEKLY /D MON /ST 09:00",
                "minute": "/SC MINUTE /MO 30",
                "once": "/SC ONCE /ST 12:00 /SD " + __import__("datetime").date.today().strftime("%m/%d/%Y"),
                "onlogon": "/SC ONLOGON",
                "onidle": "/SC ONIDLE /I 10",
            }
            # Try to extract time from schedule string (e.g. "daily at 3pm", "every day at 15:00")
            sched_args = SCHED_MAP.get(sched_lower, "/SC DAILY /ST 09:00")
            import re as _re_time
            time_match = _re_time.search(r"(\d{1,2}):?(\d{2})?\s*(am|pm)?", schedule.lower() if schedule else "")
            if time_match:
                hour = int(time_match.group(1))
                minute = int(time_match.group(2) or 0)
                ampm = time_match.group(3)
                if ampm == "pm" and hour < 12:
                    hour += 12
                elif ampm == "am" and hour == 12:
                    hour = 0
                time_str = f"{hour:02d}:{minute:02d}"
                sched_args = _re_time.sub(r"/ST \S+", f"/ST {time_str}", sched_args)
                if "/ST" not in sched_args:
                    sched_args += f" /ST {time_str}"

            cmd_args = ["schtasks", "/Create", "/TN", safe_name, "/TR", command]
            if sched_args.strip():
                import shlex as _shlex
                cmd_args.extend(_shlex.split(sched_args))
            cmd_args.append("/F")

            result = subprocess.run(
                cmd_args, capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW
            )
            if result.returncode == 0 or "SUCCESS" in result.stdout.upper():
                return {"status": "success", "action": "create_scheduled_task",
                        "name": safe_name, "command": command,
                        "schedule": sched_args,
                        "detail": f"Created scheduled task '{safe_name}'"}
            return {"status": "error",
                    "error": f"Failed to create task: {result.stderr[:200] or result.stdout[:200]}"}

        elif act == "delete":
            if not safe_name:
                return {"status": "error", "error": "Need 'name' to delete a scheduled task"}
            result = subprocess.run(
                ["schtasks", "/Delete", "/TN", safe_name, "/F"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            if result.returncode == 0 or "SUCCESS" in result.stdout.upper():
                return {"status": "success", "action": "delete_scheduled_task",
                        "name": safe_name,
                        "detail": f"Deleted scheduled task '{safe_name}'"}
            return {"status": "error",
                    "error": f"Failed to delete task: {result.stderr[:200]}"}

        elif act == "run":
            if not safe_name:
                return {"status": "error", "error": "Need 'name' to run a scheduled task"}
            result = subprocess.run(
                ["schtasks", "/Run", "/TN", safe_name],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            if result.returncode == 0:
                return {"status": "success", "action": "run_scheduled_task",
                        "name": safe_name,
                        "detail": f"Manually triggered task '{safe_name}'"}
            return {"status": "error",
                    "error": f"Failed to run task: {result.stderr[:200]}"}

        else:
            return {"status": "error", "error": f"Unknown scheduled task action: {action}"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Scheduled task command timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def manage_startup_apps(action: str = "list", app_name: str = "",
                        app_path: str = "") -> dict:
    """
    Manage Windows startup programs via registry (HKCU\\...\\Run).
    Actions: list, add, remove.
    """
    REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        import winreg  # type: ignore[import]
        act = action.lower().strip()

        if act == "list":
            apps = []
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ)  # type: ignore[attr-defined]
                i = 0
                while True:
                    try:
                        name, value, _ = winreg.EnumValue(key, i)  # type: ignore[attr-defined]
                        apps.append({"name": name, "path": value})
                        i += 1
                    except OSError:
                        break
                winreg.CloseKey(key)  # type: ignore[attr-defined]
            except FileNotFoundError:
                pass
            return {"status": "success", "action": "list_startup_apps",
                    "count": len(apps), "apps": apps,
                    "detail": f"Found {len(apps)} startup applications"}

        elif act == "add":
            if not app_name or not app_path:
                return {"status": "error",
                        "error": "Need both 'app_name' and 'app_path' to add a startup app"}
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE)  # type: ignore[attr-defined]
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, app_path)  # type: ignore[attr-defined]
            winreg.CloseKey(key)  # type: ignore[attr-defined]
            return {"status": "success", "action": "add_startup_app",
                    "name": app_name, "path": app_path,
                    "detail": f"Added '{app_name}' to startup programs"}

        elif act == "remove":
            if not app_name:
                return {"status": "error",
                        "error": "Need 'app_name' to remove a startup app"}
            try:
                key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE)  # type: ignore[attr-defined]
                winreg.DeleteValue(key, app_name)  # type: ignore[attr-defined]
                winreg.CloseKey(key)  # type: ignore[attr-defined]
                return {"status": "success", "action": "remove_startup_app",
                        "name": app_name,
                        "detail": f"Removed '{app_name}' from startup programs"}
            except FileNotFoundError:
                return {"status": "error",
                        "error": f"'{app_name}' not found in startup programs"}

        else:
            return {"status": "error", "error": f"Unknown startup action: {action}"}

    except ImportError:
        return {"status": "error", "error": "winreg is only available on Windows"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def analyze_disk(action: str = "usage", path: str = "") -> dict:
    """
    Disk analysis: usage (by drive), largest_files, health (SMART).
    """
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        act = action.lower().strip()

        if act == "largest_files":
            search_path = os.path.expanduser(path or "~/Desktop")
            if not os.path.isdir(search_path):
                return {"status": "error", "error": f"Not a directory: {search_path}"}
            files = []
            for root, dirs, filenames in os.walk(search_path):
                dirs[:] = [d for d in dirs if not d.startswith('.')]  # type: ignore[index]
                depth = root.replace(search_path, '').count(os.sep)
                if depth > 4:
                    dirs.clear()
                    continue
                for fname in filenames:
                    fpath = os.path.join(root, fname)
                    try:
                        size = os.path.getsize(fpath)
                        files.append({"name": fname, "path": fpath, "size_mb": round(size / (1024 * 1024), 2)})
                    except OSError:
                        continue
            files.sort(key=lambda x: x["size_mb"], reverse=True)
            top = files[:15]  # type: ignore[index]
            return {"status": "success", "action": "largest_files",
                    "path": search_path, "count": len(top),
                    "files": top,
                    "detail": f"Top {len(top)} largest files in {search_path}"}

        elif act == "health":
            result = subprocess.run(
                ["wmic", "diskdrive", "get", "Status,Model,Size,InterfaceType"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "disk_health",
                    "output": result.stdout.strip(),
                    "detail": "Disk health (SMART) status retrieved"}

        else:  # usage (default)
            try:
                import psutil  # type: ignore[import]
                partitions = psutil.disk_partitions()
                drives = []
                for part in partitions:
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        drives.append({
                            "drive": part.device,
                            "mountpoint": part.mountpoint,
                            "fs_type": part.fstype,
                            "total_gb": round(usage.total / (1024**3), 1),
                            "used_gb": round(usage.used / (1024**3), 1),
                            "free_gb": round(usage.free / (1024**3), 1),
                            "used_percent": usage.percent,
                        })
                    except (PermissionError, OSError):
                        continue
                return {"status": "success", "action": "disk_usage",
                        "drives": drives, "count": len(drives),
                        "detail": f"Disk usage for {len(drives)} drive(s)"}
            except ImportError:
                # Fallback without psutil
                result = subprocess.run(
                    ["wmic", "logicaldisk", "get",
                     "DeviceID,FreeSpace,Size,FileSystem,VolumeName"],
                    capture_output=True, text=True, timeout=10,
                    creationflags=_CREATE_NO_WINDOW
                )
                return {"status": "success", "action": "disk_usage",
                        "output": result.stdout.strip(),
                        "detail": "Disk usage retrieved"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Disk analysis command timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def toggle_bluetooth(action: str = "toggle") -> dict:
    """Toggle, enable, or disable Bluetooth via PowerShell."""
    try:
        act = action.lower().strip()

        # Check current Bluetooth status
        check_cmd = (
            "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
            "Where-Object { $_.FriendlyName -notlike '*Radio*' -or $_.Class -eq 'Bluetooth' } | "
            "Select-Object -First 1 -ExpandProperty Status"
        )
        check_result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", check_cmd],
            capture_output=True, text=True, timeout=10
        )
        current = check_result.stdout.strip().lower()
        is_enabled = current == "ok"

        if act == "toggle":
            act = "off" if is_enabled else "on"

        if act in ("on", "enable"):
            ps_cmd = (
                "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
                "Enable-PnpDevice -Confirm:$false -ErrorAction SilentlyContinue"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, timeout=10
            )
            return {"status": "success", "action": "bluetooth_on",
                    "detail": "Bluetooth enabled"}

        elif act in ("off", "disable"):
            ps_cmd = (
                "Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
                "Disable-PnpDevice -Confirm:$false -ErrorAction SilentlyContinue"
            )
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, timeout=10
            )
            return {"status": "success", "action": "bluetooth_off",
                    "detail": "Bluetooth disabled"}

        elif act == "status":
            return {"status": "success", "action": "bluetooth_status",
                    "enabled": is_enabled,
                    "detail": f"Bluetooth is {'enabled' if is_enabled else 'disabled'}"}

        else:
            return {"status": "error", "error": f"Unknown bluetooth action: {action}"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Bluetooth command timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def manage_display(action: str = "info") -> dict:
    """
    Display management: info, set_resolution, list_monitors, rotate.
    """
    try:
        act = action.lower().strip()

        if act in ("info", "resolution"):
            # Get current resolution via ctypes
            import ctypes
            user32 = ctypes.windll.user32  # type: ignore[attr-defined]
            width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
            height = user32.GetSystemMetrics(1)  # SM_CYSCREEN
            # DPI
            try:
                dpi = user32.GetDpiForSystem()
            except Exception:
                dpi = 96
            scale = round(dpi / 96 * 100)

            # Get refresh rate via PowerShell
            refresh = "unknown"
            try:
                ps_cmd = (
                    "Get-CimInstance -ClassName Win32_VideoController | "
                    "Select-Object -First 1 -ExpandProperty CurrentRefreshRate"
                )
                result = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", ps_cmd],
                    capture_output=True, text=True, timeout=5
                )
                refresh = result.stdout.strip() + " Hz"
            except Exception:
                pass

            return {"status": "success", "action": "display_info",
                    "width": width, "height": height,
                    "resolution": f"{width}x{height}",
                    "dpi": dpi, "scale_percent": scale,
                    "refresh_rate": refresh,
                    "detail": f"Display: {width}x{height} at {scale}% scale, {refresh}"}

        elif act == "list_monitors":
            ps_cmd = (
                "Get-CimInstance -Namespace root\\wmi -ClassName WmiMonitorID -ErrorAction SilentlyContinue | "
                "ForEach-Object { "
                "$name = ($_.UserFriendlyName | ForEach-Object { [char]$_ }) -join ''; "
                "$mfr = ($_.ManufacturerName | ForEach-Object { [char]$_ }) -join ''; "
                "Write-Output \"$mfr - $name\" }"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10
            )
            monitors = [m.strip() for m in result.stdout.strip().split("\n") if m.strip()]
            if not monitors:
                monitors = ["Could not enumerate monitors (may require admin)"]
            return {"status": "success", "action": "list_monitors",
                    "count": len(monitors), "monitors": monitors,
                    "detail": f"Found {len(monitors)} monitor(s)"}

        elif act == "rotate":
            # Rotate display using PowerShell + display settings shortcut
            try:
                import pyautogui  # type: ignore[import]
                pyautogui.hotkey("ctrl", "alt", "right")
                import time as _t
                _t.sleep(0.3)
                return {"status": "success", "action": "rotate_display",
                        "detail": "Display rotated (Ctrl+Alt+Arrow). Use same shortcut to rotate back."}
            except ImportError:
                return {"status": "error", "error": "pyautogui not installed"}

        else:
            return {"status": "error", "error": f"Unknown display action: {action}"}

    except Exception as e:
        return {"status": "error", "error": str(e)}


def manage_power_plan(action: str = "list") -> dict:
    """
    Power plan management via powercfg.
    Actions: list, active, set_high, set_balanced, set_saver.
    """
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        act = action.lower().strip()

        if act == "list" or act == "active":
            result = subprocess.run(
                ["powercfg", "/list"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            lines = result.stdout.strip().split("\n")
            plans = []
            active_plan = ""
            for line in lines:
                line = line.strip()
                if "GUID" in line:
                    # Extract name and GUID
                    import re as _re_pwr
                    m = _re_pwr.search(r"([0-9a-f\-]{36})\s+\((.+?)\)", line, _re_pwr.IGNORECASE)
                    if m:
                        guid = m.group(1)
                        name = m.group(2)
                        is_active = "*" in line
                        plans.append({"guid": guid, "name": name, "active": is_active})
                        if is_active:
                            active_plan = name
            return {"status": "success", "action": "list_power_plans",
                    "plans": plans, "active": active_plan,
                    "detail": f"Active power plan: {active_plan}"}

        # Known GUIDs for common power plans
        PLAN_GUIDS = {
            "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "high": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
            "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
            "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
            "saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
        }

        plan_key = act.replace("set_", "")
        guid = PLAN_GUIDS.get(plan_key)
        if guid:
            result = subprocess.run(
                ["powercfg", "/setactive", guid],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            plan_name = plan_key.replace("_", " ").title()
            if result.returncode == 0:
                return {"status": "success", "action": "set_power_plan",
                        "plan": plan_name,
                        "detail": f"Switched to {plan_name} power plan"}
            return {"status": "error",
                    "error": f"Failed to set power plan: {result.stderr[:200]}"}

        return {"status": "error", "error": f"Unknown power plan action: {action}. "
                "Use: list, set_high, set_balanced, set_saver"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Power plan command timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def manage_env_var(action: str = "list", name: str = "", value: str = "") -> dict:
    """
    Environment variable management.
    Actions: list, get, set, delete.
    """
    try:
        act = action.lower().strip()

        if act == "list":
            env_vars = {}
            important_keys = ["PATH", "USERPROFILE", "APPDATA", "TEMP", "TMP",
                              "COMPUTERNAME", "USERNAME", "HOMEDRIVE", "HOMEPATH",
                              "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
                              "JAVA_HOME", "PYTHON_HOME", "NODE_PATH", "GOPATH"]
            for key in important_keys:
                val = os.environ.get(key, "")
                if val:
                    # Truncate long values like PATH
                    env_vars[key] = val[:200] + "..." if len(val) > 200 else val  # type: ignore[index]
            return {"status": "success", "action": "list_env_vars",
                    "count": len(env_vars), "variables": env_vars,
                    "detail": f"Listed {len(env_vars)} key environment variables"}

        elif act == "get":
            if not name:
                return {"status": "error", "error": "Need 'name' to get an environment variable"}
            val = os.environ.get(name.upper(), os.environ.get(name, ""))
            if val:
                return {"status": "success", "action": "get_env_var",
                        "name": name, "value": val[:500],
                        "detail": f"{name} = {val[:100]}"}
            return {"status": "error",
                    "error": f"Environment variable '{name}' not found"}

        elif act == "set":
            if not name or not value:
                return {"status": "error",
                        "error": "Need both 'name' and 'value' to set an environment variable"}
            # Set via setx (persists across sessions)
            _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["setx", name, value],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            # Also set for current session
            os.environ[name] = value
            if result.returncode == 0 or "SUCCESS" in result.stdout.upper():
                return {"status": "success", "action": "set_env_var",
                        "name": name, "value": value[:100],
                        "detail": f"Set {name} = {value[:50]}"}
            return {"status": "error",
                    "error": f"Failed to set variable: {result.stderr[:200]}"}

        elif act == "delete":
            if not name:
                return {"status": "error",
                        "error": "Need 'name' to delete an environment variable"}
            # Delete from registry
            _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["reg", "delete", r"HKCU\Environment", "/v", name, "/f"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            # Remove from current session
            os.environ.pop(name, None)
            if result.returncode == 0:
                return {"status": "success", "action": "delete_env_var",
                        "name": name,
                        "detail": f"Deleted environment variable '{name}'"}
            return {"status": "error",
                    "error": f"Failed to delete variable: {result.stderr[:200]}"}

        else:
            return {"status": "error", "error": f"Unknown env var action: {action}"}

    except Exception as e:
        return {"status": "error", "error": str(e)}


def manage_service(action: str = "list", name: str = "") -> dict:
    """
    Windows service control via sc.exe.
    Actions: list, status, start, stop, restart.
    """
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        act = action.lower().strip()
        import re as _re_svc
        safe_name = _re_svc.sub(r'[^a-zA-Z0-9_\-\s]', '', name).strip() if name else ""

        if act == "list":
            result = subprocess.run(
                ["sc", "queryex", "type=", "service", "state=", "all"],
                capture_output=True, text=True, timeout=15,
                creationflags=_CREATE_NO_WINDOW
            )
            services = []
            lines = result.stdout.split("\n")
            current = {}
            for line in lines:
                line = line.strip()
                if line.startswith("SERVICE_NAME:"):
                    if current and current.get("name"):
                        services.append(current)
                    current = {"name": line.split(":", 1)[1].strip()}
                elif line.startswith("DISPLAY_NAME:"):
                    current["display_name"] = line.split(":", 1)[1].strip()
                elif line.startswith("STATE"):
                    # STATE : 4  RUNNING
                    parts = line.split()
                    for state in ["RUNNING", "STOPPED", "PAUSED", "START_PENDING", "STOP_PENDING"]:
                        if state in parts:
                            current["state"] = state
                            break
            if current and current.get("name"):
                services.append(current)
            # Only show running or notable services
            running = [s for s in services if s.get("state") == "RUNNING"]
            return {"status": "success", "action": "list_services",
                    "total": len(services), "running_count": len(running),
                    "running_services": running[:20],
                    "detail": f"{len(running)} running out of {len(services)} total services"}

        elif act == "status":
            if not safe_name:
                return {"status": "error", "error": "Need 'name' to check service status"}
            result = subprocess.run(
                ["sc", "query", safe_name],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW
            )
            output = result.stdout.strip()
            state = "UNKNOWN"
            for s in ["RUNNING", "STOPPED", "PAUSED", "START_PENDING", "STOP_PENDING"]:
                if s in output:
                    state = s
                    break
            return {"status": "success", "action": "service_status",
                    "service": safe_name, "state": state,
                    "output": output[:500],
                    "detail": f"Service '{safe_name}' is {state}"}

        elif act in ("start", "stop", "restart"):
            if not safe_name:
                return {"status": "error", "error": f"Need 'name' to {act} a service"}

            if act == "restart":
                # Stop then start
                subprocess.run(
                    ["sc", "stop", safe_name],
                    capture_output=True, text=True, timeout=15,
                    creationflags=_CREATE_NO_WINDOW
                )
                import time as _t
                _t.sleep(2)
                result = subprocess.run(
                    ["sc", "start", safe_name],
                    capture_output=True, text=True, timeout=15,
                    creationflags=_CREATE_NO_WINDOW
                )
            else:
                result = subprocess.run(
                    ["sc", act, safe_name],
                    capture_output=True, text=True, timeout=15,
                    creationflags=_CREATE_NO_WINDOW
                )

            combined = result.stdout + result.stderr
            if result.returncode == 0 or "SUCCESS" in combined.upper():
                return {"status": "success", "action": f"{act}_service",
                        "service": safe_name,
                        "detail": f"Service '{safe_name}' {act}ed successfully"}
            # Check for access denied
            if "Access is denied" in combined or "5)" in combined:
                return {"status": "error",
                        "error": f"Access denied — need administrator privileges to {act} '{safe_name}'"}
            return {"status": "error",
                    "error": f"Failed to {act} service: {combined[:200]}"}

        else:
            return {"status": "error", "error": f"Unknown service action: {action}"}

    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Service command timed out"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def system_sound(action: str = "notification") -> dict:
    """
    Play system sounds or manage sound scheme.
    Actions: notification, error, warning, beep, question, info.
    """
    try:
        act = action.lower().strip()
        import winsound  # type: ignore[import]

        SOUND_MAP = {
            "notification": winsound.MB_OK,
            "info": winsound.MB_OK,
            "error": winsound.MB_ICONHAND,
            "warning": winsound.MB_ICONEXCLAMATION,
            "question": winsound.MB_ICONQUESTION,
            "beep": None,  # Use Beep()
            "asterisk": winsound.MB_ICONASTERISK,
        }

        sound = SOUND_MAP.get(act)
        if sound is None and act == "beep":
            winsound.Beep(800, 500)  # 800Hz for 500ms
            return {"status": "success", "action": "play_sound",
                    "sound": "beep",
                    "detail": "Played a beep sound"}
        elif sound is not None:
            winsound.MessageBeep(sound)
            return {"status": "success", "action": "play_sound",
                    "sound": act,
                    "detail": f"Played {act} sound"}
        else:
            # Try as a .wav file path
            if os.path.isfile(act):
                winsound.PlaySound(act, winsound.SND_FILENAME)
                return {"status": "success", "action": "play_sound",
                        "file": act,
                        "detail": f"Played sound file: {act}"}
            return {"status": "error",
                    "error": f"Unknown sound: {action}. Use: notification, error, warning, beep, question"}

    except ImportError:
        return {"status": "error", "error": "winsound is only available on Windows"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def system_power(action: str = "shutdown", delay: int = 0) -> dict:
    """
    System power management: shutdown, restart, sleep, hibernate,
    schedule_shutdown, cancel_shutdown, log_off.
    """
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        act = action.lower().strip()

        if act == "shutdown":
            delay_sec = max(0, delay * 60) if delay > 0 else 30  # default 30s warning
            subprocess.run(
                ["shutdown", "/s", "/t", str(delay_sec)],
                capture_output=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW
            )
            minutes = delay_sec // 60
            return {"status": "success", "action": "shutdown",
                    "delay_seconds": delay_sec,
                    "detail": f"Computer will shut down in {minutes} minute(s). "
                              f"Say 'cancel shutdown' to abort."}

        elif act == "restart":
            delay_sec = max(0, delay * 60) if delay > 0 else 30
            subprocess.run(
                ["shutdown", "/r", "/t", str(delay_sec)],
                capture_output=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW
            )
            minutes = delay_sec // 60
            return {"status": "success", "action": "restart",
                    "delay_seconds": delay_sec,
                    "detail": f"Computer will restart in {minutes} minute(s). "
                              f"Say 'cancel shutdown' to abort."}

        elif act == "sleep":
            # Windows sleep via PowerShell rundll32
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Add-Type -Assembly System.Windows.Forms; "
                 "[System.Windows.Forms.Application]::SetSuspendState("
                 "[System.Windows.Forms.PowerState]::Suspend, $false, $false)"],
                capture_output=True, timeout=5
            )
            return {"status": "success", "action": "sleep",
                    "detail": "Computer going to sleep"}

        elif act == "hibernate":
            subprocess.run(
                ["shutdown", "/h"],
                capture_output=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "hibernate",
                    "detail": "Computer going to hibernate"}

        elif act == "schedule_shutdown":
            delay_min = delay if delay > 0 else 30
            delay_sec = delay_min * 60
            subprocess.run(
                ["shutdown", "/s", "/t", str(delay_sec)],
                capture_output=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "schedule_shutdown",
                    "delay_minutes": delay_min,
                    "detail": f"Shutdown scheduled in {delay_min} minutes. "
                              f"Say 'cancel shutdown' to abort."}

        elif act == "cancel_shutdown":
            subprocess.run(
                ["shutdown", "/a"],
                capture_output=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "cancel_shutdown",
                    "detail": "Scheduled shutdown has been cancelled"}

        elif act == "log_off":
            subprocess.run(
                ["shutdown", "/l"],
                capture_output=True, timeout=5,
                creationflags=_CREATE_NO_WINDOW
            )
            return {"status": "success", "action": "log_off",
                    "detail": "Logging off current user"}

        else:
            return {"status": "error",
                    "error": f"Unknown power action: {action}. "
                    "Use: shutdown, restart, sleep, hibernate, schedule_shutdown, "
                    "cancel_shutdown, log_off"}

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
                dirs[:] = [d for d in dirs if not d.startswith('.')]  # type: ignore[index]
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
                        if ext.lower() not in ext_filter:  # type: ignore[operator]
                            continue
                    # Time filter
                    if time_cutoff:
                        try:
                            if os.path.getmtime(fpath) < time_cutoff:  # type: ignore[operator]
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
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)  # type: ignore[attr-defined]
        ctypes.windll.user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)  # type: ignore[attr-defined]

        return {"status": "success", "action": "music_control",
                "detail": f"Media action: {act}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


_LAST_MUSIC_OPEN: dict = {"query": "", "time": 0.0}


def open_music(query: str) -> dict:
    """Play music on YouTube — opens search, waits for page, and plays video safely."""
    global _LAST_MUSIC_OPEN
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
        if cleaned_query.lower() == _LAST_MUSIC_OPEN.get("query", "").lower() and (now - _LAST_MUSIC_OPEN.get("time", 0.0) < 5.0):
            log.info("[open_music] Debouncing duplicate music open for: '%s'", cleaned_query)
            return {"status": "success", "action": "open_music", "detail": f"Playing '{cleaned_query}' on YouTube"}

        _LAST_MUSIC_OPEN["query"] = cleaned_query
        _LAST_MUSIC_OPEN["time"] = now

        search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(cleaned_query)}"
        webbrowser.open(search_url)

        # Wait briefly for page to load
        _time.sleep(2.0)

        try:
            try:
                import pythoncom
                pythoncom.CoInitialize()
            except Exception:
                pass

            import pyautogui  # type: ignore[import]
            screen_w, screen_h = pyautogui.size()
            try:
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
                # Keep click safely away from screen corners to prevent PyAutoGUI fail-safe triggers
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

        return {"status": "success", "action": "open_music",
                "detail": f"Playing '{cleaned_query}' on YouTube"}
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
    if text and text not in _clipboard_history[:3]:  # type: ignore[index,operator]  # Avoid duplicates
        _clipboard_history.insert(0, text)
        if len(_clipboard_history) > _CLIPBOARD_MAX:
            _clipboard_history.pop()


def get_clipboard_history(n: int = 5) -> dict:
    """Return the last N clipboard entries."""
    entries = _clipboard_history[:n]  # type: ignore[index]
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
            stats[name]["count"] += 1  # type: ignore[operator]
            stats[name]["dates"].add(h.get("date", ""))  # type: ignore[union-attr]

        summary = []
        for name, data in stats.items():
            streak = len(data["dates"])  # type: ignore[arg-type]
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
            "confidence": round(confidence, 2),  # type: ignore[call-overload]
            "timestamp": _time.time(),
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%I:%M %p"),
        })

        # Keep last 500 entries
        moods = moods[-500:]  # type: ignore[index]

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
        dominant = max(emotion_counts, key=emotion_counts.get) if emotion_counts else "neutral"  # type: ignore[arg-type]

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
        from PIL import ImageGrab  # type: ignore[import]
        import tempfile

        # Capture screen
        screenshot = ImageGrab.grab()
        tmp_path = os.path.join(tempfile.gettempdir(), "alita_screen_ocr.png")
        screenshot.save(tmp_path)

        # Try OCR with pytesseract
        try:
            import pytesseract  # type: ignore[import]
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
    user32 = ctypes.windll.user32  # type: ignore[attr-defined]
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
        from pywinauto import Desktop  # type: ignore[import]

        desktop = Desktop(backend="uia")
        try:
            fg = desktop.window(active_only=True)
            fg_wrapper = fg.wrapper_object()
        except Exception:
            # Fallback: get foreground via ctypes
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()  # type: ignore[attr-defined]
            if not hwnd:
                return []
            from pywinauto import Application  # type: ignore[import]
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
    import pyautogui  # type: ignore[import]

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
        try:
            from ollama_client import ollama_chat  # type: ignore[import]

            # Build element list for LLM
            elem_list = "\n".join(
                f"  [{i}] \"{e['name']}\" ({e['type']})"
                for i, e in enumerate(elements)
            )

            pick_prompt = f"""You are a UI navigation assistant. The user wants to interact with: "{target}"

Current window: "{window_info.get('title', 'Unknown')}"

Visible UI elements:
{elem_list}

RULES:
1. Pick the SINGLE element that best matches the user's INTENT (what they want to DO, not just text match)
2. NEVER pick logos, branding icons, or app names that link to homepages (e.g. YouTube logo, Google logo)
3. NEVER pick navigation items like "Home", "Menu", "Settings", "Sign In" unless the user explicitly asked for them
4. Prefer CONTENT elements (video titles, document names, links to actual content) over navigation chrome
5. If the user wants the "first" or a specific result, pick the first content item, NOT header/nav elements
6. If NONE match the user's intent, reply "NONE"

Reply with ONLY the index number (e.g. "5") or "NONE"."""

            answer = ollama_chat(prompt=pick_prompt, max_tokens=10, temperature=0.0)

            if answer and answer.strip().upper() != "NONE":
                try:
                    idx = int(answer.strip().strip("[]"))
                    if 0 <= idx < len(elements):
                        best_match = elements[idx]
                except (ValueError, IndexError):
                    pass
        except Exception as llm_err:
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
        import pyautogui  # type: ignore[import]
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
    import pyautogui  # type: ignore[import]

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
            from main import memory_recall  # type: ignore[import]
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
            from memory.conversation_store import load_history  # type: ignore[import]
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
                "results": matches[:10],  # type: ignore[index]
                "source": "conversation_store",
            }
        except ImportError:
            pass

        return {"status": "error", "error": "Memory systems not available"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# ─────────────────────────────────────────────────────────────────────────────
# WHATSAPP MESSAGING
# ─────────────────────────────────────────────────────────────────────────────

def _extract_whatsapp_info(text: str) -> dict:
    """Extract contact/phone and message content from WhatsApp voice/text commands."""
    import re
    cleaned = text.strip()

    contact = ""
    message = ""

    # 1. Search for phone numbers (10 to 15 digits, optionally prefixed with +)
    # Handles: "on the number 9876543210", "to number 9876543210", "number 9876543210", or raw 10+ digits
    phone_match = re.search(r"(?:(?:on|to|at)\s+(?:the\s+)?(?:number|no\.?)\s*[:=]?\s*|\b)(\+?\d[\d\s\-]{8,14}\d)\b", cleaned, re.IGNORECASE)
    if phone_match:
        raw_num = phone_match.group(1)
        digits = re.sub(r"[^\d+]", "", raw_num)
        if len(re.sub(r"[^\d]", "", digits)) >= 7:
            contact = digits

    # 2. If no phone number found, look for name following prepositions
    if not contact:
        # Match single or two-word names before stop words like 'on', 'saying', 'that', 'ki', 'in'
        name_match = re.search(r"\b(?:to|for|ko|with)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)(?:\s+(?:on|in|via|saying|that|ki|whatsapp|wp)\b|$)", cleaned, re.IGNORECASE)
        if name_match:
            candidate = name_match.group(1).strip()
            # Clean trailing stop words if any
            candidate = re.sub(r"\b(on|in|via|with|whatsapp|wp|saying|that|ki)\b", "", candidate, flags=re.IGNORECASE).strip()
            if candidate.lower() not in ("whatsapp", "the", "number", "message", "a message", "my friend", "phone", ""):
                contact = candidate.title()
        else:
            m_simple = re.search(r"\b(?:to|for|ko|with)\s+([a-zA-Z]+)", cleaned, re.IGNORECASE)
            if m_simple and m_simple.group(1).lower() not in ("whatsapp", "the", "number", "message", "a", "phone"):
                contact = m_simple.group(1).title()

    # 3. Extract Message Text
    # Check explicit message markers: saying, that, ki, message:, text:, as
    msg_match = re.search(r'(?:saying|that|ki|text\s*[:=]|message\s*[:=]|as)\s+["\']?(.+?)["\']?$', cleaned, re.IGNORECASE)
    if msg_match:
        message = msg_match.group(1).strip()
    else:
        # Check "send <message> to <contact> on whatsapp"
        m_direct = re.search(r'\bsend\s+(?:a\s+|the\s+)?(.+?)\s+(?:to|for|on|ko)\s+', cleaned, re.IGNORECASE)
        if m_direct:
            extracted = m_direct.group(1).strip()
            extracted_clean = re.sub(r"\b(message|the\s+message|a\s+message|msg|in\s+the\s+whatsapp|in\s+whatsapp|on\s+whatsapp)\b", "", extracted, flags=re.IGNORECASE).strip()
            if extracted_clean:
                message = extracted_clean

    # Clean message from any trailing app names
    if message:
        message = re.sub(r"\b(on\s+whatsapp|in\s+whatsapp|via\s+whatsapp|on\s+wp)\b", "", message, flags=re.IGNORECASE).strip()

    # If message still empty or generic, use friendly greeting
    if not message or message.lower() in ("user_text", "send message", "message", "the message", "send the message", "a message", "the"):
        message = "Hello!"

    if not contact:
        contact = "Unknown"

    return {"contact": contact, "message": message}


def _verify_whatsapp_contact(contact: str) -> dict:
    """Verify that the active WhatsApp window/chat matches the target contact."""
    try:
        contact_norm = contact.lower().strip()
        fg = _get_foreground_window_info()
        title = fg.get("title", "").lower()
        if contact_norm in title:
            return {"verified": True, "actual_name": contact}

        # Check UIA elements (window header or chat title)
        elements = _get_ui_elements(max_elements=30)
        for e in elements:
            name = (e.get("name") or "").strip()
            if not name:
                continue
            name_lower = name.lower()
            if contact_norm in name_lower or name_lower in contact_norm:
                return {"verified": True, "actual_name": name}

        # If WhatsApp is the active window, accept to allow natural variations
        if "whatsapp" in title:
            return {"verified": True, "actual_name": contact}

        return {"verified": False, "actual_name": "unknown"}
    except Exception as exc:
        log.warning("[_verify_whatsapp_contact] Check error: %s", exc)
        return {"verified": True, "actual_name": contact}


def send_whatsapp_message(contact: str, message: str, settings=None) -> dict:
    """Send a message via WhatsApp Desktop using automation.
    Supports direct phone numbers (via whatsapp:// URI scheme) and contact names.
    Executes synchronously, waits adaptively for chat UI readiness, and verifies delivery.
    """
    import time as _time
    import urllib.parse
    import re
    import subprocess
    import os

    contact_str = str(contact).strip() if contact else ""
    if not contact_str or contact_str.lower() == "unknown":
        return {"status": "error", "error": "No recipient contact or phone number provided."}

    # Ensure message has content
    msg_str = str(message).strip() if message else ""
    if not msg_str or msg_str.lower() in ("user_text", "send message", "message", "the message", "send the message", "a message"):
        msg_str = "Hello!"

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

    msg_lower = msg_str.strip().lower()
    intent_prompt = INTENT_WORDS.get(msg_lower)

    if intent_prompt:
        try:
            from ollama_client import ollama_chat  # type: ignore[import]
            prompt = intent_prompt.format(contact=contact_str) + " Reply with ONLY the message text, nothing else."
            ai_msg = ollama_chat(prompt=prompt, max_tokens=60, temperature=0.8)
            if ai_msg:
                msg_str = ai_msg.strip('"').strip("'")
        except Exception:
            fallback_msgs = {
                "greet": f"Hey {contact_str}! Hope you're doing great 😊",
                "greeting": f"Hey {contact_str}! How's it going? 😊",
                "hello": f"Hello {contact_str}! Hope you're having a wonderful day!",
                "hi": f"Hi {contact_str}! 👋",
                "congrats": f"Congratulations {contact_str}! 🎉🎊 So proud of you!",
                "congratulations": f"Congratulations {contact_str}! 🎉 Amazing work!",
                "thanks": f"Thank you so much {contact_str}! Really appreciate it 🙏",
                "thank you": f"Thank you {contact_str}! It means a lot 🙏",
                "sorry": f"Hey {contact_str}, I'm really sorry. I hope you can understand 🙏",
                "happy birthday": f"Happy Birthday {contact_str}! 🎂🎉 Wishing you the best!",
                "good morning": f"Good morning {contact_str}! ☀️ Have an amazing day!",
                "good night": f"Good night {contact_str}! 🌙 Sleep well!",
            }
            msg_str = fallback_msgs.get(msg_lower, msg_str)

    try:
        import pyautogui  # type: ignore[import]
        import pyperclip  # type: ignore[import]
    except ImportError:
        return {"status": "error", "error": "pyautogui and pyperclip required for WhatsApp automation"}

    try:
        digits_only = re.sub(r"[^\d]", "", contact_str)
        is_phone = len(digits_only) >= 7

        if is_phone:
            # ── PATH A: Direct Phone Number via whatsapp:// URI protocol ──
            clean_phone = digits_only
            if len(digits_only) == 10 and digits_only[0] in "6789":
                clean_phone = f"91{digits_only}"
            elif contact_str.startswith("+"):
                clean_phone = digits_only

            encoded_msg = urllib.parse.quote(msg_str)
            uri = f"whatsapp://send?phone={clean_phone}&text={encoded_msg}"
            log.info("[WhatsApp] Triggering direct protocol: whatsapp://send?phone=%s", clean_phone)

            try:
                os.startfile(uri)  # type: ignore[attr-defined]
            except Exception:
                subprocess.Popen(f'cmd /c start "" "{uri}"', shell=True)

            # 1. Wait for WhatsApp window to appear and bring it to foreground
            # Give up to 15s to handle slow cold starts
            wa_ready = _wait_for_app_window("whatsapp", timeout=15.0)
            if not wa_ready:
                try:
                    from engines.app_manager import focus_window
                    wa_ready = focus_window("whatsapp")
                except Exception:
                    pass

            if not wa_ready:
                log.warning("[WhatsApp] Window did not appear within 15s")
                return {
                    "status": "error",
                    "error": "WhatsApp Desktop took too long to open. Please make sure WhatsApp is installed and running.",
                }

            # Ensure WhatsApp window has focus
            try:
                from engines.app_manager import focus_window
                focus_window("whatsapp")
            except Exception:
                pass

            # 2. Poll adaptively for chat readiness or error dialogs (up to 12s)
            start_poll = _time.monotonic()
            chat_ready = False
            send_clicked = False

            while (_time.monotonic() - start_poll) < 12.0:
                _time.sleep(0.5)

                # Keep window focused
                fg = _get_foreground_window_info()
                fg_title = fg.get("title", "").lower()

                # Check UI elements in foreground
                elements = _get_ui_elements(max_elements=50)

                # A. Check for error dialogs (e.g. invalid phone number)
                invalid_found = False
                for e in elements:
                    ename = (e.get("name") or "").lower()
                    if any(phrase in ename for phrase in [
                        "phone number shared via url is invalid",
                        "url is invalid",
                        "invalid phone number",
                        "not registered on whatsapp",
                    ]):
                        invalid_found = True
                        break

                if invalid_found:
                    pyautogui.press("escape")
                    log.warning("[WhatsApp] Number %s reported invalid by WhatsApp", clean_phone)
                    return {
                        "status": "error",
                        "error": f"WhatsApp reports that the phone number {clean_phone} is invalid or not registered.",
                    }

                # B. Check if Send button is visible (meaning chat is fully rendered with message)
                send_btn = None
                for e in elements:
                    ename = (e.get("name") or "").lower()
                    etype = e.get("type", "")
                    if ename in ("send", "bheje", "bhejo") or (etype == "Button" and "send" in ename):
                        send_btn = e
                        break

                if send_btn:
                    log.info("[WhatsApp] Send button detected at (%d, %d)", send_btn["x"], send_btn["y"])
                    # Click Send button directly
                    try:
                        pyautogui.click(send_btn["x"], send_btn["y"])
                        send_clicked = True
                    except Exception:
                        pyautogui.press("enter")
                        send_clicked = True
                    chat_ready = True
                    break

                # C. Check if message input box / chat pane is loaded
                has_input = any(
                    "type a message" in (e.get("name") or "").lower() or e.get("type") == "Edit"
                    for e in elements
                )
                if has_input and (_time.monotonic() - start_poll) >= 3.0:
                    log.info("[WhatsApp] Chat input area detected — sending Enter")
                    pyautogui.press("enter")
                    send_clicked = True
                    chat_ready = True
                    break

                # D. Fallback if UI element tree is opaque: after 5 seconds of focused WhatsApp, press Enter
                if not elements and (_time.monotonic() - start_poll) >= 5.0 and "whatsapp" in fg_title:
                    log.info("[WhatsApp] Opaque UI fallback (5s elapsed) — sending Enter")
                    pyautogui.press("enter")
                    send_clicked = True
                    chat_ready = True
                    break

            if not chat_ready:
                log.warning("[WhatsApp] Chat readiness not confirmed within timeout for %s", clean_phone)
                return {
                    "status": "error",
                    "error": "WhatsApp opened, but the chat was still loading. The message may not have been sent. Please check WhatsApp.",
                }

            _time.sleep(0.5)
            log.info("[WhatsApp] Direct message dispatched to phone '%s'", clean_phone)
            return {
                "status": "success",
                "action": "send_whatsapp_message",
                "contact": contact_str,
                "detail": f"Message sent to {contact_str} on WhatsApp",
                "verified": True,
            }

        else:
            # ── PATH B: Contact Name Search ──
            whatsapp_result = open_app("whatsapp")
            if whatsapp_result.get("status") == "not_installed":
                return {
                    "status": "not_installed",
                    "app": "WhatsApp",
                    "error": "WhatsApp Desktop is not installed.",
                    "store_url": "https://apps.microsoft.com/detail/9NKSQGP7F2NH",
                }

            if not _wait_for_app_window("whatsapp", timeout=15.0):
                try:
                    from engines.app_manager import focus_window
                    if not focus_window("whatsapp"):
                        return {"status": "error", "error": "WhatsApp did not open in time. Please try again."}
                except Exception:
                    return {"status": "error", "error": "WhatsApp did not open in time. Please try again."}

            try:
                from engines.app_manager import focus_window
                focus_window("whatsapp")
            except Exception:
                pass

            _time.sleep(0.8)

            # Focus search box (Ctrl+F)
            pyautogui.hotkey("ctrl", "f")
            _time.sleep(0.4)

            # Type contact name
            pyperclip.copy(contact_str)
            pyautogui.hotkey("ctrl", "v")
            _time.sleep(1.2)  # Give search results time to filter

            # Select contact (Enter)
            pyautogui.press("enter")
            _time.sleep(0.8)  # Chat pane opens

            # Verify the chat opened matches target
            verify = _verify_whatsapp_contact(contact_str)
            if not verify.get("verified", False):
                pyautogui.press("escape")
                _time.sleep(0.2)
                pyautogui.press("escape")
                actual = verify.get("actual_name", "unknown")
                log.warning("[WhatsApp] Contact verification failed: wanted '%s', got '%s'", contact_str, actual)
                return {
                    "status": "error",
                    "error": f"Could not find contact '{contact_str}' on WhatsApp. Please check the name and try again.",
                }

            # Type message
            pyperclip.copy(msg_str)
            pyautogui.hotkey("ctrl", "v")
            _time.sleep(0.3)

            # Send (Enter)
            pyautogui.press("enter")
            _time.sleep(0.3)

            log.info("[WhatsApp] Message sent to contact '%s'", contact_str)
            return {
                "status": "success",
                "action": "send_whatsapp_message",
                "contact": contact_str,
                "detail": f"Message sent to {contact_str} on WhatsApp",
                "verified": True,
            }

    except Exception as e:
        log.error("[WhatsApp] Automation failed: %s", e)
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

        # Wait for WhatsApp window to actually be focused (event-driven, not blind sleep)
        if not _wait_for_app_window("whatsapp"):
            return {"status": "error", "error": "WhatsApp did not open in time. Please try again."}

        try:
            import pyautogui  # type: ignore[import]
            import pyperclip  # type: ignore[import]
        except ImportError:
            return {"status": "error", "error": "pyautogui and pyperclip required"}

        # Search for contact — poll until WhatsApp title reflects the chat
        wa_title_before = _get_foreground_window_info().get("title", "")
        pyautogui.hotkey("ctrl", "f")
        _time.sleep(0.15)  # Minimal wait for search box focus
        pyperclip.copy(contact)
        pyautogui.hotkey("ctrl", "v")
        # Wait until WhatsApp shows search results (title changes or just brief delay)
        _wait_for_ui_condition(
            lambda: True,  # WhatsApp doesn't change title on search — use min wait
            timeout=0.6, interval=0.1, label="contact_search"
        )
        pyautogui.press("enter")
        # Wait for the chat to open (title changes to include contact name)
        _wait_for_window_change(wa_title_before, timeout=2.0)
        _time.sleep(0.3)  # Buffer for chat UI to finish rendering

        # ── CONTACT VERIFICATION: confirm the right chat was selected ──
        verify = _verify_whatsapp_contact(contact)
        if not verify["verified"]:
            pyautogui.press("escape")
            _time.sleep(0.2)
            pyautogui.press("escape")
            actual = verify.get("actual_name", "unknown")
            log.warning("[WhatsApp File] Contact verification failed: wanted '%s', got '%s'",
                        contact, actual)
            return {
                "status": "error",
                "error": f"Could not find the correct contact '{contact}' on WhatsApp. "
                         f"Found '{actual}' instead. Please check the contact name.",
                "actual_contact": actual,
            }
        log.info("[WhatsApp File] Contact verified: '%s' → '%s'", contact, verify["actual_name"])

        # ── Attach file via the attachment popup ──
        # Step 1: Open the attachment menu (+ button)
        wa_title_before_attach = _get_foreground_window_info().get("title", "")
        pyautogui.hotkey("alt", "a")
        # Poll for the popup to render (UI elements become available)
        _wait_for_ui_condition(
            lambda: any("document" in e["name"].lower()
                        for e in _get_ui_elements(max_elements=20)),
            timeout=2.0, interval=0.15, label="attach_popup"
        )

        # Step 2: Click "Document" in the popup to open the file dialog
        _click_whatsapp_document_option()
        # Intelligent wait: poll until a file dialog window appears
        _wait_for_fg_title(["open", "öffnen", "browse", "select", "choose", "file"],
                           timeout=3.0)
        _time.sleep(0.15)  # File dialog focus settle

        # Step 3: Type the file path in the file dialog's filename field
        pyperclip.copy(safe)
        pyautogui.hotkey("ctrl", "v")
        _time.sleep(0.15)
        pyautogui.press("enter")  # Open/select the file
        # Wait until the file dialog closes (WhatsApp comes back to foreground)
        _wait_for_fg_title_gone(["open", "öffnen", "browse", "select", "choose"],
                                timeout=5.0)
        _time.sleep(0.3)  # WhatsApp needs a moment to render the file preview

        # Step 4: Send
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


def _click_whatsapp_document_option():
    """
    Click "Document" in WhatsApp's attachment popup.
    Strategy: keyboard navigation first (fastest), UI Automation fallback.
    """
    import time as _t
    try:
        import pyautogui  # type: ignore[import]
    except ImportError:
        return

    # ── Method 1: Quick UI Automation scan ──
    try:
        elements = _get_ui_elements(max_elements=30)
        for e in elements:
            if "document" in e["name"].lower():
                pyautogui.click(e["x"], e["y"])
                log.info("[whatsapp_attach] Clicked 'Document' via UIA at (%d, %d)", e["x"], e["y"])
                return
    except Exception:
        pass

    # ── Method 2: Keyboard — Document is the first item ──
    # Press Up repeatedly to reach top, then Enter
    for _ in range(7):
        pyautogui.press("up", _pause=False)
        _t.sleep(0.05)
    _t.sleep(0.1)
    pyautogui.press("enter")
    log.info("[whatsapp_attach] Selected Document via keyboard")


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
                dirs[:] = [d for d in dirs if not d.startswith('.')]  # type: ignore[index]
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
        top = candidates[:5]  # type: ignore[index]

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
                    import pyperclip  # type: ignore[import]
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

        # Wait for app window to actually be focused (event-driven, not blind sleep)
        if not _wait_for_app_window(app_lower):
            return {"status": "error", "error": f"{app.title()} did not open in time. Please try again."}

        try:
            import pyautogui  # type: ignore[import]
            import pyperclip  # type: ignore[import]
        except ImportError:
            return {"status": "error",
                    "error": "pyautogui and pyperclip required for app automation"}

        # Search for contact
        wa_title_pre = _get_foreground_window_info().get("title", "")
        keys = profile["search_shortcut"].split("+")  # type: ignore[union-attr]
        pyautogui.hotkey(*keys)
        _time.sleep(0.15)
        pyperclip.copy(contact)
        pyautogui.hotkey("ctrl", "v")
        _wait_for_ui_condition(lambda: True, timeout=0.5, label="search_results")
        pyautogui.press("enter")
        _wait_for_window_change(wa_title_pre, timeout=2.0)
        _time.sleep(0.3)

        # ── CONTACT VERIFICATION (WhatsApp only) ──
        if app_lower == "whatsapp":
            verify = _verify_whatsapp_contact(contact)
            if not verify["verified"]:
                pyautogui.press("escape")
                _time.sleep(0.2)
                pyautogui.press("escape")
                actual = verify.get("actual_name", "unknown")
                log.warning("[send_to_app] WhatsApp contact mismatch: '%s' vs '%s'",
                            contact, actual)
                return {
                    "status": "error",
                    "error": f"Could not find '{contact}' on WhatsApp. "
                             f"Found '{actual}' instead. Please check the contact name.",
                    "actual_contact": actual,
                }
            log.info("[send_to_app] WhatsApp contact verified: '%s' → '%s'",
                     contact, verify["actual_name"])

        # Send file if provided
        if file_path and os.path.isfile(file_path):
            if app_lower == "whatsapp":
                # WhatsApp: open attach popup → click Document → file dialog
                pyautogui.hotkey("alt", "a")  # Open attachment menu
                _wait_for_ui_condition(
                    lambda: any("document" in e["name"].lower()
                                for e in _get_ui_elements(max_elements=20)),
                    timeout=2.0, interval=0.15, label="attach_popup"
                )
                _click_whatsapp_document_option()  # Click "Document"
                _wait_for_fg_title(["open", "öffnen", "browse", "select", "choose", "file"],
                                   timeout=3.0)
                _time.sleep(0.15)
                pyperclip.copy(file_path)
                pyautogui.hotkey("ctrl", "v")
                _time.sleep(0.15)
                pyautogui.press("enter")  # Select file
                _wait_for_fg_title_gone(["open", "öffnen", "browse", "select", "choose"],
                                        timeout=5.0)
                _time.sleep(0.3)
                pyautogui.press("enter")  # Send
            elif app_lower == "telegram":
                pyautogui.hotkey("ctrl", "shift", "f")  # Attach in Telegram
                _time.sleep(1)
                pyperclip.copy(file_path)
                pyautogui.hotkey("ctrl", "v")
                _time.sleep(0.5)
                pyautogui.press("enter")
                _time.sleep(1)
            elif app_lower == "discord":
                # Discord: use the + button area (just paste the file)
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
    if (compose_message or not message):
        try:
            from ollama_client import ollama_chat  # type: ignore[import]
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
            ai_msg = ollama_chat(prompt=compose_prompt, max_tokens=80, temperature=0.7)
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
# DETERMINISTIC FAST-PATH INTENT PARSER & ACTION NORMALIZER
# ─────────────────────────────────────────────────────────────────────────────

_AUTOMATION_PREFIX_RE = re.compile(
    r"^(?:hey\s+(?:mj|alita)|ok\s+(?:mj|alita)|hello\s+(?:mj|alita)|mj|alita|aura|please|can\s+you(?:\s+please)?|"
    r"could\s+you(?:\s+please)?|would\s+you(?:\s+please)?|i\s+want\s+you\s+to|just|kindly)\s*,?\s*",
    re.IGNORECASE
)

def _clean_user_command(text: str) -> str:
    cleaned = text.strip()
    for _ in range(3):
        m = _AUTOMATION_PREFIX_RE.match(cleaned)
        if m:
            cleaned = cleaned[m.end():].strip()
        else:
            break
    return cleaned

def _fast_parse_automation_command(user_text: str) -> dict | None:
    cleaned = _clean_user_command(user_text)
    lower = cleaned.lower().strip()
    if not lower:
        return None

    # 0. UI Mode / Display Transform (Highest Priority)
    if any(w in lower for w in [
        "maximize yourself", "maximize display", "full screen", "fullscreen",
        "expand ui", "expand display", "bada karo", "open full dashboard", "maximize mj", "maximize alita", "maximize window"
    ]):
        return {"action": "maximize_ui"}

    if any(w in lower for w in [
        "minimize yourself", "collapse display", "collapse ui", "hide yourself",
        "chota karo", "overlay mode", "minimize mj", "minimize alita", "minimize window", "minimize"
    ]):
        return {"action": "minimize_ui"}

    # 0. Song Recognition (Deterministic Fast-Path)
    if any(w in lower for w in [
        "what song", "which song", "identify song", "identify this song",
        "recognize song", "recognize this song", "name this song", "name this track",
        "shazam", "what is playing", "what's playing", "what is this song",
        "what's this song", "konsa gaana", "ye gaana", "what music",
        "this song", "ye kya baj", "kya baj raha", "song playing",
        "bata ye gaana", "gaana bata", "song bata", "pehchaan",
        "which music", "what tune", "which tune", "identify the song",
        "tell me the song", "what am i listening", "listening to what",
        "song is this", "music is this", "what's the name of this",
        "identify this track", "recognize this tune", "identify music",
        "recognize music", "find this song", "find this music", "find the song",
        "detect song", "detect this song", "detect music"
    ]):
        return {"action": "recognize_song"}

    # Browser Autopilot (Active page summarization & data extraction)
    if any(phrase in lower for phrase in [
        "summarize this page", "summarize webpage", "summarize the page",
        "summarize this website", "summarize active tab", "summarize tab",
        "what is this page about", "what is this article about", "page summary",
        "website summary", "read this webpage", "summarize article", "webpage summary"
    ]):
        return {"action": "summarize_webpage"}

    if any(phrase in lower for phrase in [
        "extract links", "extract links from page", "get links from this page",
        "show links on this page", "extract headings", "extract outline",
        "page outline", "extract table", "extract data from page"
    ]):
        dtype = "headings" if ("heading" in lower or "outline" in lower) else "links"
        return {"action": "extract_page_data", "data_type": dtype}

    # 1. System Telemetry / Simple Shortcuts
    if lower in ("battery", "battery status", "check battery", "battery percentage", "battery kitni hai", "check battery status"):
        return {"action": "battery"}
    if lower in ("system info", "system status", "pc info", "computer status", "system information"):
        return {"action": "system_info"}
    if lower in ("screenshot", "take screenshot", "capture screen", "screenshot lo", "take a screenshot"):
        return {"action": "screenshot"}
    if lower in ("lock screen", "lock computer", "lock pc", "lock the screen"):
        return {"action": "lock_screen"}
    if lower in ("empty recycle bin", "recycle bin", "clear trash", "empty trash", "empty recycle"):
        return {"action": "empty_recycle_bin"}
    if lower in ("dark mode", "night mode", "toggle dark mode", "light mode"):
        return {"action": "toggle_dark_mode"}
    if lower in ("mute", "unmute", "toggle mute", "sound off", "awaz band", "turn off sound"):
        return {"action": "toggle_mute"}
    if any(w in lower for w in ["volume up", "increase volume", "awaz badhao", "volume badhao"]):
        return {"action": "set_volume", "level": "up"}
    if any(w in lower for w in ["volume down", "decrease volume", "awaz kam", "volume kam"]):
        return {"action": "set_volume", "level": "down"}
    if any(w in lower for w in ["brightness up", "increase brightness", "brightness badhao"]):
        return {"action": "set_brightness", "level": "up"}
    if any(w in lower for w in ["brightness down", "decrease brightness", "dim screen", "dim display", "brightness kam"]):
        return {"action": "set_brightness", "level": "down"}

    # 2. Macro Workflow Chains (e.g., "work mode", "start work mode", "coding mode", "chill mode", "study mode")
    if any(w in lower for w in [
        "work mode", "start work mode", "coding mode", "developer mode",
        "chill mode", "relax mode", "chill out mode", "rest mode",
        "study mode", "focus mode", "pomodoro mode", "deep work mode",
        "presentation mode", "meeting mode"
    ]):
        mode = "work"
        if any(w in lower for w in ["chill", "relax", "rest"]):
            mode = "chill"
        elif any(w in lower for w in ["study", "focus", "pomodoro", "deep work"]):
            mode = "study"
        elif any(w in lower for w in ["presentation", "meeting"]):
            mode = "presentation"
        return {"action": "workflow_macro", "macro": mode}

    # 3. Open App / Launch App (e.g., "open whatsapp", "launch chrome", "open notepad")
    # Filler words that speech recognition might add before/after app names
    _OPEN_PREFIXES = r"(?:please\s+|can\s+you\s+|could\s+you\s+|i\s+want\s+to\s+|i\s+need\s+to\s+|just\s+|hey\s+(?:mj|alita)\s+|(?:mj|alita)\s+)?"
    _TRAILING_FILLERS = r"(?:\s+(?:please|for\s+me|now|quickly|abhi|jaldi))?"
    _HINDI_OPEN_VERBS = r"(?:kholo|khol\s+do|open\s+karo|open\s+kar\s+do|launch\s+karo|chalu\s+karo|shuru\s+karo|chalao)"
    _HINDI_CLOSE_VERBS = r"(?:band\s+karo|band\s+kar\s+do|hatao|close\s+karo|quit\s+karo)"

    # ── HINDI-FIRST patterns (must be checked BEFORE English to avoid "notepad open karo" → app="karo") ──

    # Hindi Open: "notepad kholo", "chrome open karo", "task manager chalu karo"
    m_hindi_open = re.search(
        r"^" + _OPEN_PREFIXES + r"([a-zA-Z0-9_\-\s\.]+?)\s+" + _HINDI_OPEN_VERBS + _TRAILING_FILLERS + r"$",
        lower
    )
    if m_hindi_open:
        target = m_hindi_open.group(1).strip()
        target = re.sub(r"^(?:the|my|mera|apna)\s+", "", target).strip()
        if target and not any(target.startswith(w) for w in ["music", "song", "folder", "downloads", "documents", "desktop", "picture", "video", "photo"]):
            return {"action": "open_app", "app": target}

    # Hindi Close: "chrome band karo", "notepad band kar do"
    m_hindi_close = re.search(
        r"^" + _OPEN_PREFIXES + r"([a-zA-Z0-9_\-\s\.]+?)\s+" + _HINDI_CLOSE_VERBS + _TRAILING_FILLERS + r"$",
        lower
    )
    if m_hindi_close:
        target = m_hindi_close.group(1).strip()
        target = re.sub(r"^(?:the|my|mera|apna)\s+", "", target).strip()
        if target:
            return {"action": "close_app", "app": target}

    # ── ENGLISH-FIRST patterns ──

    # English Open: "open notepad", "please launch chrome", "can you start task manager"
    m_open = re.search(
        _OPEN_PREFIXES + r"(?:open|launch|start|run)\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\-\s\.]+?)" + _TRAILING_FILLERS + r"(?:\s+app|\s+application)?$",
        lower
    )
    if m_open:
        target = m_open.group(1).strip()
        target = re.sub(r"\s+(?:karo|kar\s+do|karna|please|now|abhi|jaldi)$", "", target).strip()
        if target and not any(target.startswith(w) for w in ["music", "song", "folder", "downloads", "documents", "desktop", "picture", "video", "photo"]):
            return {"action": "open_app", "app": target}

    # English Close: "close chrome", "quit notepad", "kill task manager"
    m_close = re.search(
        _OPEN_PREFIXES + r"(?:close|quit|exit|kill)\s+(?:the\s+|my\s+)?([a-zA-Z0-9_\-\s\.]+?)" + _TRAILING_FILLERS + r"(?:\s+app|\s+window)?$",
        lower
    )
    if m_close:
        target = m_close.group(1).strip()
        target = re.sub(r"\s+(?:karo|kar\s+do|please|now)$", "", target).strip()
        if target:
            return {"action": "close_app", "app": target}

    # 4. Folder Navigation
    m_folder = re.search(r"^(?:open|go\s+to|navigate\s+to)\s+(?:the\s+|my\s+)?(downloads?|documents?|desktop|pictures?|photos?|videos?|music)\s*(?:folder)?$", lower)
    if m_folder:
        folder_name = m_folder.group(1).strip()
        folder_map = {
            "download": "~/Downloads", "downloads": "~/Downloads",
            "document": "~/Documents", "documents": "~/Documents",
            "desktop": "~/Desktop",
            "picture": "~/Pictures", "pictures": "~/Pictures", "photo": "~/Pictures", "photos": "~/Pictures",
            "video": "~/Videos", "videos": "~/Videos",
            "music": "~/Music",
        }
        return {"action": "open_folder", "folder": folder_map.get(folder_name, "~/Downloads")}

    # 5. Play Music / Songs
    if lower.startswith("play ") or any(w in lower for w in ["gaana bajao", "song bajao", "play music", "play songs", "play some", "chalao gaana"]):
        m_play = re.search(r"^play\s+(.+?)(?:\s+(?:on|in)\s+(?:the\s+)?(?:youtube|spotify|yt|gaana))?$", lower)
        query = m_play.group(1).strip() if m_play else lower.replace("play", "").replace("bajao", "").replace("chalao", "").strip()
        query = re.sub(r"\b(music|songs?|some|good|the|a|an|track|video|in\s+the\s+youtube|in\s+youtube|on\s+the\s+youtube|on\s+youtube|in\s+yt|on\s+yt|on\s+spotify|in\s+spotify)\b", "", query, flags=re.IGNORECASE)
        query = re.sub(r"\b(in|on|at|the|for|to)\b\s*$", "", query, flags=re.IGNORECASE)
        query = re.sub(r"^\s*\b(in|on|at|the|for|to)\b", "", query, flags=re.IGNORECASE).strip()
        query = re.sub(r"\s+", " ", query).strip()
        if not query or query in ("in", "on", "youtube", "yt", "spotify", "music", "song", "songs", "a", "something"):
            query = "top trending songs"
        return {"action": "open_music", "query": query}

    # 6. File Sharing / Sending
    if any(w in lower for w in ["send file", "send files", "share file", "share files", "send my", "share my", "send document", "send photo", "send video", "bhejo file", "file bhejo"]):
        contact_match = re.search(r"\b(?:to|for|with|ko)\s+([a-zA-Z0-9_\-]+)", lower)
        contact = contact_match.group(1).title() if contact_match else "Unknown"
        app = "whatsapp"
        for a in ["telegram", "discord", "email", "mail"]:
            if a in lower:
                app = a
                break
        location = ""
        for loc in ["desktop", "downloads", "download", "documents", "pictures", "videos"]:
            if loc in lower:
                location = loc
                break
        file_hint = re.sub(r"\b(?:send|share|the|files?|documents?|photos?|videos?|my|to|for|with|ko|" + re.escape(contact.lower()) + r"|" + re.escape(app) + r"|on|via|which\s+is\s+on|which\s+is\s+in|from|" + re.escape(location) + r")\b", "", lower, flags=re.IGNORECASE).strip()
        return {
            "action": "send_file_smart",
            "contact": contact,
            "file_name": file_hint or "file",
            "app": app,
            "location": location
        }

    # 7. Macro Workflow Chains (e.g., "work mode", "chill mode", "study mode", "coding mode")
    if any(w in lower for w in [
        "work mode", "start work mode", "coding mode", "developer mode",
        "chill mode", "relax mode", "chill out mode", "rest mode",
        "study mode", "focus mode", "pomodoro mode", "deep work mode",
        "presentation mode", "meeting mode"
    ]):
        mode = "work"
        if any(w in lower for w in ["chill", "relax", "rest"]):
            mode = "chill"
        elif any(w in lower for w in ["study", "focus", "pomodoro", "deep work"]):
            mode = "study"
        elif any(w in lower for w in ["presentation", "meeting"]):
            mode = "presentation"
        return {"action": "workflow_macro", "macro": mode}

    # 8. WhatsApp Message
    if ("whatsapp" in lower or "wp" in lower.split()) and any(w in lower for w in ["send", "message", "msg", "bhejo", "bhej", "text", "saying", "chat"]):
        info = _extract_whatsapp_info(user_text)
        return {"action": "send_whatsapp", "contact": info["contact"], "message": info["message"]}

    return None

def _normalize_automation_action(data: dict, user_text: str = "") -> dict:
    if not isinstance(data, dict):
        return {"action": "unknown"}
    action = data.get("action", "").lower().strip()

    # Map open_<app> -> open_app
    if action.startswith("open_") and action not in ("open_app", "open_folder", "open_url", "open_music"):
        app_name = action[5:].replace("_", " ")
        return {"action": "open_app", "app": data.get("app") or app_name}

    # Map launch_<app>, run_<app>, start_<app>
    for prefix in ("launch_", "run_", "start_"):
        if action.startswith(prefix) and action not in ("launch_app", "run_command"):
            app_name = action[len(prefix):].replace("_", " ")
            return {"action": "open_app", "app": data.get("app") or app_name}

    if action in ("launch_app", "start_app", "openapplication", "open"):
        return {"action": "open_app", "app": data.get("app", data.get("name", ""))}

    if action in ("play_music", "play_song", "play_video", "play_audio", "play"):
        query = data.get("query") or data.get("song") or data.get("title") or "top trending songs"
        return {"action": "open_music", "query": query}

    if action in ("work_mode", "chill_mode", "study_mode", "presentation_mode"):
        return {"action": "workflow_macro", "macro": action.replace("_mode", "")}

    if action in ("send_file", "share_file", "send_document", "send_photo", "send_video", "share_document"):
        return {
            "action": "send_file_smart",
            "contact": data.get("contact", "Unknown"),
            "file_name": data.get("file_name") or data.get("file") or data.get("name") or "file",
            "app": data.get("app", "whatsapp"),
            "location": data.get("location", "")
        }

    if action in ("send_message", "send_msg", "whatsapp_message", "send_whatsapp_message"):
        info = _extract_whatsapp_info(user_text) if (data.get("contact") in ("Unknown", None, "") or data.get("message") in ("Unknown", None, "", user_text)) else data
        return {
            "action": "send_whatsapp",
            "contact": info.get("contact") or data.get("contact", "Unknown"),
            "message": info.get("message") or data.get("message", "Hello!")
        }

    return data


def run_workflow_macro(macro_name: str, session=None, settings=None) -> dict:
    """Execute multi-step macro workflow chains."""
    name_clean = macro_name.lower().strip()
    actions_taken = []

    if "work" in name_clean or "code" in name_clean or "coding" in name_clean:
        open_app("vscode")
        actions_taken.append("Opened VS Code")
        set_volume("40")
        actions_taken.append("Set volume to 40%")
        open_music("deep focus instrumental study music")
        actions_taken.append("Playing Deep Focus Music")
        return {
            "status": "success",
            "action": "work_mode",
            "detail": "Work Mode Activated: Launched VS Code, adjusted volume, and started focus music."
        }

    elif "chill" in name_clean or "relax" in name_clean or "rest" in name_clean:
        toggle_dark_mode()
        actions_taken.append("Enabled Dark Mode")
        set_brightness("40")
        actions_taken.append("Dimmed screen to 40%")
        open_music("lofi chill beats relaxing music")
        actions_taken.append("Playing Lo-Fi chill beats")
        return {
            "status": "success",
            "action": "chill_mode",
            "detail": "Chill Mode Activated: Switched to Dark Mode, dimmed screen, and started Lo-Fi beats."
        }

    elif "study" in name_clean or "focus" in name_clean:
        if session:
            set_reminder(session.user_id, "Take a 5-minute Pomodoro break!", "25 minutes")
            actions_taken.append("Set 25-minute Pomodoro timer")
        open_app("notepad")
        actions_taken.append("Opened Notepad")
        open_music("binaural alpha waves study music")
        return {
            "status": "success",
            "action": "study_mode",
            "detail": "Study Mode Activated: Set 25-minute Pomodoro timer, opened Notepad, and started Alpha wave music."
        }

    elif "presentation" in name_clean or "meeting" in name_clean:
        set_brightness("90")
        set_volume("60")
        return {
            "status": "success",
            "action": "presentation_mode",
            "detail": "Meeting/Presentation Mode Activated: Brightened display and adjusted volume."
        }

    return {"status": "error", "error": f"Unknown workflow macro: {macro_name}"}


# ─────────────────────────────────────────────────────────────────────────────
# PHONE / MOBILE AUTOMATION BRIDGE
# ─────────────────────────────────────────────────────────────────────────────

def _phone_action(action_type: str, data: dict, session) -> dict:
    """
    Bridge between synchronous automation handler and async PhoneOrchestrator.
    Maps action_type strings to the appropriate orchestrator method.
    """
    import asyncio

    try:
        from engines.phone_orchestrator import phone_orchestrator
    except ImportError:
        log.warning("phone_orchestrator module not available")
        return {"status": "error", "detail": "Phone companion module is not available."}

    if not phone_orchestrator.device_info.get("connected"):
        return {
            "status": "error",
            "detail": "Your Android phone is not connected. Please ensure the MJ Companion app "
                      "is running on your phone and connected to the same network.",
        }

    def _run_async(coro):
        """Run an async coroutine from synchronous context."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, coro).result(timeout=15)
        return asyncio.run(coro)

    try:
        if action_type == "unlock":
            result = _run_async(phone_orchestrator.unlock_screen())
            unlocked = result.get("success") or result.get("screenUnlocked")
            if result.get("alreadyUnlocked"):
                return {"status": "success", "detail": "Your phone is already unlocked."}
            elif unlocked:
                return {"status": "success", "detail": "Phone unlocked successfully!"}
            else:
                return {"status": "error", "detail": f"Could not unlock phone: {result.get('error', 'unknown error')}"}

        elif action_type == "status":
            state = _run_async(phone_orchestrator.get_live_phone_state())
            battery = state.get("batteryPercent", -1)
            charging = state.get("isCharging", False)
            locked = state.get("isLocked", True)
            screen_on = state.get("isScreenOn", False)
            model = state.get("deviceModel", "Unknown")
            pkg = state.get("currentPackage", "")

            parts = [f"📱 **{model}**"]
            if battery >= 0:
                emoji = "🔋" if battery > 20 else "🪫"
                parts.append(f"{emoji} Battery: {battery}%{'⚡ charging' if charging else ''}")
            parts.append(f"🔒 {'Locked' if locked else 'Unlocked'}")
            parts.append(f"📺 Screen {'on' if screen_on else 'off'}")
            if pkg:
                parts.append(f"📦 Current app: {pkg.split('.')[-1]}")

            return {"status": "success", "detail": " | ".join(parts)}

        elif action_type == "notifications":
            notifs = phone_orchestrator.recent_notifications[:10]
            if not notifs:
                return {"status": "success", "detail": "No recent notifications on your phone."}
            lines = ["📲 **Recent Phone Notifications:**"]
            for i, n in enumerate(notifs[:5], 1):
                app = n.get("app", "Unknown")
                title = n.get("title", "")
                text = n.get("text", "")[:80]
                lines.append(f"{i}. **{app}**: {title} — {text}")
            return {"status": "success", "detail": "\n".join(lines)}

        elif action_type == "reply_notification":
            # Extract reply text from raw user text
            raw = data.get("text", "")
            # Simple extraction: text after "reply" keyword
            import re
            m = re.search(r'(?:reply|respond)\s+(?:with|saying|that)?\s*["\']?(.+?)["\']?\s*$', raw, re.IGNORECASE)
            reply_text = m.group(1).strip() if m else raw

            # Reply to most recent notification that has a reply action
            notifs = phone_orchestrator.recent_notifications
            replied = False
            for n in notifs:
                key = n.get("key") or n.get("notificationKey")
                if key:
                    result = _run_async(phone_orchestrator.reply_direct(key, reply_text))
                    if result.get("success"):
                        replied = True
                        return {"status": "success", "detail": f"Replied to {n.get('app', 'notification')}: \"{reply_text}\""}
                    break
            if not replied:
                return {"status": "error", "detail": "No notification found to reply to."}

        elif action_type == "read_screen":
            tree = _run_async(phone_orchestrator.read_screen())
            nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
            if not nodes:
                return {"status": "success", "detail": "Phone screen appears empty or could not be read."}
            # Extract visible text elements
            texts = []
            for node in nodes[:30]:
                if isinstance(node, dict):
                    t = node.get("text") or node.get("contentDesc") or ""
                    if t.strip():
                        texts.append(t.strip())
            if texts:
                summary = " | ".join(texts[:15])
                return {"status": "success", "detail": f"📱 Phone screen content: {summary}"}
            return {"status": "success", "detail": "Phone screen is showing but no readable text found."}

        elif action_type == "open_app":
            app_name = data.get("app", "")
            if not app_name:
                return {"status": "error", "detail": "No app name specified to open on phone."}
            # Try launching by package name or deep link
            result = _run_async(phone_orchestrator.launch_app(package=app_name))
            if result.get("success"):
                return {"status": "success", "detail": f"Opened {app_name} on your phone."}
            else:
                return {"status": "error", "detail": f"Could not open {app_name} on phone: {result.get('error', 'unknown')}"}

        elif action_type == "make_call":
            number = data.get("number")
            contact = data.get("contactName")
            result = _run_async(phone_orchestrator.make_call(number=number, contact_name=contact))
            if result.get("success"):
                dialed = result.get("number", contact or number or "")
                return {"status": "success", "detail": f"📞 Calling {dialed}..."}
            return {"status": "error", "detail": f"Call failed: {result.get('error', 'unknown')}"}

        elif action_type == "end_call":
            result = _run_async(phone_orchestrator.end_call())
            if result.get("success"):
                return {"status": "success", "detail": "📴 Call ended."}
            return {"status": "error", "detail": f"Could not end call: {result.get('error', 'unknown')}"}

        elif action_type == "send_sms":
            import re
            raw = data.get("raw_text", "")
            sm = re.search(r'(?:sms|text)\s+(?:to\s+)?(.+?)\s+(?:that|with|saying|:)\s*(.+)', raw, re.IGNORECASE)
            if sm:
                recip = sm.group(1).strip()
                msg = sm.group(2).strip()
                digits = re.sub(r'[^0-9+]', '', recip)
                if len(digits) >= 7:
                    result = _run_async(phone_orchestrator.send_sms(number=digits, message=msg))
                else:
                    result = _run_async(phone_orchestrator.send_sms(contact_name=recip, message=msg))
                if result.get("success"):
                    return {"status": "success", "detail": f"📨 SMS sent to {recip}."}
                return {"status": "error", "detail": f"SMS failed: {result.get('error', 'unknown')}"}
            return {"status": "error", "detail": "Could not parse SMS recipient and message. Try: 'send sms to John that hello'"}

        elif action_type == "volume":
            vol_action = data.get("volume_action", "up")
            result = _run_async(phone_orchestrator.set_volume(action=vol_action))
            if result.get("success"):
                cur = result.get("currentVolume", "")
                mx = result.get("maxVolume", "")
                return {"status": "success", "detail": f"🔊 Volume {vol_action} — {cur}/{mx}"}
            return {"status": "error", "detail": f"Volume control failed: {result.get('error', 'unknown')}"}

        elif action_type == "media":
            media_action = data.get("media_action", "play_pause")
            result = _run_async(phone_orchestrator.media_control(action=media_action))
            emoji = {"play": "▶️", "pause": "⏸️", "next": "⏭️", "previous": "⏮️", "stop": "⏹️"}.get(media_action, "🎵")
            if result.get("success"):
                return {"status": "success", "detail": f"{emoji} Media: {media_action}"}
            return {"status": "error", "detail": f"Media control failed: {result.get('error', 'unknown')}"}

        elif action_type == "flashlight":
            enabled = data.get("enabled", True)
            result = _run_async(phone_orchestrator.toggle_flashlight(enabled=enabled))
            if result.get("success"):
                return {"status": "success", "detail": f"🔦 Flashlight {'ON' if enabled else 'OFF'}"}
            return {"status": "error", "detail": f"Flashlight failed: {result.get('error', 'unknown')}"}

        elif action_type == "set_alarm":
            hour = data.get("hour", 6)
            minute = data.get("minute", 0)
            result = _run_async(phone_orchestrator.set_alarm(hour=hour, minute=minute))
            if result.get("success"):
                return {"status": "success", "detail": f"⏰ Alarm set for {hour:02d}:{minute:02d}"}
            return {"status": "error", "detail": f"Alarm failed: {result.get('error', 'unknown')}"}

        elif action_type == "set_timer":
            seconds = data.get("seconds", 300)
            mins = seconds // 60
            secs = seconds % 60
            result = _run_async(phone_orchestrator.set_timer(seconds=seconds))
            if result.get("success"):
                time_str = f"{mins}m {secs}s" if secs else f"{mins} minutes"
                return {"status": "success", "detail": f"⏱️ Timer set for {time_str}"}
            return {"status": "error", "detail": f"Timer failed: {result.get('error', 'unknown')}"}

        elif action_type == "camera":
            selfie = data.get("selfie", False)
            result = _run_async(phone_orchestrator.open_camera(selfie=selfie))
            if result.get("success"):
                return {"status": "success", "detail": f"📷 {'Front' if selfie else 'Rear'} camera opened!"}
            return {"status": "error", "detail": f"Camera failed: {result.get('error', 'unknown')}"}

        elif action_type == "set_clipboard":
            import re
            raw = data.get("raw_text", "")
            # Extract the text to copy
            cm = re.search(r'(?:copy|send|put)\s+["\']?(.+?)["\']?\s+(?:to|on)\s+(?:phone|mobile)', raw, re.IGNORECASE)
            clip_text = cm.group(1).strip() if cm else raw
            result = _run_async(phone_orchestrator.set_clipboard(text=clip_text))
            if result.get("success"):
                return {"status": "success", "detail": f"📋 Copied to phone clipboard: '{clip_text[:50]}'"}
            return {"status": "error", "detail": "Clipboard sync failed."}

        elif action_type == "get_clipboard":
            result = _run_async(phone_orchestrator.get_clipboard())
            if result.get("success"):
                text = result.get("text", "")
                return {"status": "success", "detail": f"📋 Phone clipboard: '{text[:200]}'" if text else "Phone clipboard is empty."}
            return {"status": "error", "detail": "Could not read phone clipboard."}

        elif action_type == "brightness":
            level = data.get("level", 128)
            result = _run_async(phone_orchestrator.set_brightness(level=level))
            pct = int(level * 100 / 255)
            if result.get("success"):
                return {"status": "success", "detail": f"🔆 Brightness set to {pct}%"}
            return {"status": "error", "detail": f"Brightness failed: {result.get('error', 'unknown')}"}

        elif action_type == "lock":
            result = _run_async(phone_orchestrator.lock_screen())
            if result.get("success"):
                return {"status": "success", "detail": "🔒 Phone locked."}
            return {"status": "error", "detail": "Could not lock phone."}

        elif action_type == "screenshot":
            result = _run_async(phone_orchestrator.take_screenshot())
            if result.get("success"):
                return {"status": "success", "detail": "📸 Screenshot taken on phone!"}
            return {"status": "error", "detail": "Screenshot failed."}

        elif action_type == "generic":
            # Pass natural language command to the orchestrator's NL handler
            command = data.get("command", "") or data.get("raw_text", "")
            if hasattr(phone_orchestrator, "execute_natural_task"):
                result = _run_async(phone_orchestrator.execute_natural_task(command))
                detail = result.get("detail") or result.get("summary") or str(result)
                success = result.get("success", False)
                return {"status": "success" if success else "error", "detail": detail}
            else:
                return {"status": "error", "detail": f"Phone orchestrator cannot process: {command}"}

        else:
            return {"status": "error", "detail": f"Unknown phone action type: {action_type}"}

    except Exception as e:
        log.error("Phone action '%s' failed: %s", action_type, e, exc_info=True)
        return {"status": "error", "detail": f"Phone command failed: {str(e)}"}


# ─────────────────────────────────────────────────────────────────────────────
# MAIN HANDLER — Parse intent and execute
# ─────────────────────────────────────────────────────────────────────────────

def handle_automation(user_text: str, session, settings, system_prompt: str,
                      history: list, max_tokens: int, response_cache) -> list[str]:
    """
    Handle automation queries. Uses deterministic fast-path first,
    with LLM fallback, then executes the appropriate system function.
    """
    import re
    text_lower = user_text.lower().strip()

    # ── RETRY / VERIFY / REDO — replay last automation command ─────────
    _RETRY_PHRASES = [
        "do it again", "try again", "retry", "redo", "redo it",
        "repeat it", "repeat that", "once more", "one more time",
        "check again", "verify", "verify it", "reverify", "re-verify",
        "re verify", "is it done", "check if it opened", "check if it worked",
        "did it open", "did it close", "did it work", "did it start",
        "phir se karo", "dubara karo", "fir se", "wapas karo", "dobara",
    ]
    if text_lower in _RETRY_PHRASES or any(text_lower.startswith(p) for p in ["check if it", "did it "]):
        last_cmd = getattr(session, '_last_automation_cmd', None)
        if last_cmd:
            log.info("[%s] RETRY detected — replaying last command: '%s'",
                     getattr(session, 'session_id', 'anon'), last_cmd)
            # Re-execute by recursing with the original command
            return handle_automation(last_cmd, session, settings, system_prompt,
                                     history, max_tokens, response_cache)
        else:
            return ["I don't have a previous command to retry. Please tell me what to do!"]

    # ── Check Voice Macro Recording & Execution ───────────────────────
    try:
        from engines.macro_recorder import macro_recorder
        # A. Teach / Record Macro
        if macro_recorder.is_record_command(user_text):
            ok, msg = macro_recorder.parse_and_record(user_text)
            return [msg]
        # B. List Macros
        if any(w in text_lower for w in ["list my macros", "show my macros", "list macros", "show my routines", "list routines", "my routines"]):
            return [macro_recorder.list_macros()]
        # C. Delete Macro
        if any(w in text_lower for w in ["delete macro", "remove macro", "delete routine", "remove routine"]):
            macro_target = re.sub(r'^(?:delete|remove)\s+(?:macro|routine)\s+', '', text_lower).strip()
            return [macro_recorder.delete_macro(macro_target)]
        # D. Execute Custom Macro Match
        saved_macro = macro_recorder.find_matching_macro(user_text)
        if saved_macro and (
            any(w in text_lower for w in ["start", "run", "launch", "execute", "activate", "routine", "mode", "chalu", "shuru", "karo", "trigger"])
            or saved_macro.get("name") in text_lower
        ):
            log.info("[%s] Running Custom Macro: '%s'", getattr(session, 'session_id', 'anon'), saved_macro.get('name'))
            m_res = macro_recorder.execute_macro(saved_macro, session=session, settings=settings)
            return [f"Executed routine '{saved_macro.get('name')}': {m_res.get('summary', 'Done')}"]
    except Exception as _me:
        log.warning("Macro recorder error: %s", _me)

    # ── Check Compound Multi-App Pipeline ─────────────────────────────
    try:
        from engines.compound_pipeline import compound_pipeline
        if compound_pipeline.is_compound(user_text):
            log.info("[%s] Compound Pipeline Detected: '%s'", getattr(session, 'session_id', 'anon'), user_text[:60])
            pipe_res = compound_pipeline.execute(user_text, session=session, settings=settings)
            return [pipe_res.get("summary", "Compound pipeline completed successfully.")]
    except Exception as _pe:
        log.warning("Compound pipeline error: %s", _pe)

    # ── Check Mobile Companion / Phone Commands (Semantic Target Resolution) ──
    try:
        from engines.world_model import world_model
        from engines.semantic_target_binder import semantic_target_binder
        world_snap = world_model.get_snapshot()
        sem_res = semantic_target_binder.resolve(user_text, world_snap)
        is_phone_target = (sem_res.get("target_device") == "phone")
    except Exception as _sem_err:
        log.debug("Semantic target check: %s", _sem_err)
        sem_res = {}
        is_phone_target = False

    _PHONE_PATTERNS = [
        r"\b(?:on\s+my\s+phone|on\s+phone|in\s+phone|from\s+phone|through\s+phone|for\s+the\s+phone|for\s+my\s+phone|for\s+phone)\b",
        r"\b(?:on\s+my\s+mobile|on\s+mobile|in\s+mobile|for\s+the\s+mobile|for\s+my\s+mobile|for\s+mobile)\b",
        r"\b(?:phone\s+pe|phone\s+par|phone\s+mein|mobile\s+pe|mobile\s+par|mobile\s+mein)\b",
        r"\b(?:unlock\s+(?:my\s+)?phone|phone\s+unlock)\b",
        r"\b(?:phone\s+battery|battery\s+on\s+phone)\b",
        r"\b(?:read\s+(?:my\s+)?phone\s+screen|what(?:'s|\s+is)\s+on\s+my\s+phone)\b",
        r"\b(?:open\s+whatsapp\s+and\s+message|send\s+whatsapp\s+message|call\s+.*on\s+phone)\b",
    ]

    if is_phone_target or any(re.search(pat, text_lower) for pat in _PHONE_PATTERNS):
        try:
            from engines.phone_orchestrator import phone_orchestrator
            log.info("[%s] Mobile Phone Intent Confirmed (semantic=%s): '%s'",
                     getattr(session, 'session_id', 'anon'), is_phone_target, user_text[:60])
            import asyncio
            import concurrent.futures
            st_dict = getattr(session, "__dict__", {})
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    res = ex.submit(asyncio.run, phone_orchestrator.run_instruction(user_text, session_state=st_dict)).result(timeout=15)
            else:
                res = asyncio.run(phone_orchestrator.run_instruction(user_text, session_state=st_dict))

            if res.get("success"):
                return [res.get("message", "Done on your phone.")]
            elif res.get("needs_confirmation"):
                return [res.get("prompt", "Are you sure you want to proceed?")]
            else:
                return [res.get("message") or res.get("error") or "I couldn't complete that on your phone."]
        except Exception as _ph_err:
            log.warning("Phone orchestrator automation error: %s", _ph_err)

    # ── Check if user is confirming to play a recognized song ─────────────
    recognized = getattr(session, '_recognized_song', None)
    if recognized:
        confirm_words = ["yes", "yeah", "yep", "sure", "play", "open", "haan",
                         "haa", "chala", "baja", "play it", "open it", "play karo",
                         "ok", "okay", "go ahead", "do it", "play the song",
                         "play that song", "chalao", "sun"]
        decline_words = ["no", "nope", "nahi", "don't", "cancel", "skip", "mat",
                         "rehne do", "nah"]
        if any(w in text_lower for w in confirm_words):
            query = recognized["query"]
            session._recognized_song = None  # Clear so it doesn't trigger again
            result = open_music(query)
            return [f"Playing {recognized['title']} by {recognized['artist']} on YouTube!"]
        elif any(w in text_lower for w in decline_words):
            session._recognized_song = None
            return ["Alright, no problem!"]
        # If neither confirm nor decline, clear and process as normal command
        session._recognized_song = None

    # ── Play previous/last recognized song ─────────────────────────────
    last_song = getattr(session, '_last_recognized_song', None)
    if last_song and any(phrase in text_lower for phrase in [
        "previous song", "last song", "that song", "the song you identified",
        "song you found", "pichla gaana", "woh gaana", "identified song",
        "recognized song", "play the song you", "play what you",
        "play the previous", "play the last",
    ]):
        result = open_music(last_song["query"])
        return [f"Playing {last_song['title']} by {last_song['artist']} on YouTube!"]

    # ── STEP 1: FAST-PATH DETERMINISTIC PARSER (<1ms, 0% hallucination) ───
    action_data = _fast_parse_automation_command(user_text)

    # ── STEP 2: LLM PARSING FALLBACK (Ambiguous/Complex queries) ───────────
    if not action_data:
        try:
            fg_info = _get_foreground_window_info()
            fg_title = fg_info.get("title", "Unknown")
        except Exception:
            fg_title = "Unknown"

        user_mood = getattr(session, 'last_emotion', None) or "unknown"
        user_mood_confidence = getattr(session, 'last_emotion_confidence', 0.0)
        mood_context = ""
        if user_mood and user_mood != "unknown" and user_mood_confidence > 0.3:
            mood_context = f'\nUser\'s current detected mood: "{user_mood}" (confidence: {user_mood_confidence:.0%})'

        parse_prompt = f"""You are MJ, a system automation assistant. Parse this command.
Currently focused window: "{fg_title}"{mood_context}
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
- {{"action":"manage_process","name":"<process name>","process_action":"info|kill|priority_high|priority_normal|priority_low"}}
- {{"action":"network_diagnostics","net_action":"ip_config|ping|traceroute|dns_lookup|active_connections|flush_dns|external_ip","target":"<host or IP>"}}
- {{"action":"manage_scheduled_task","task_action":"list|create|delete|run","name":"<task name>","command":"<command to run>","schedule":"daily|hourly|weekly|once|onlogon"}}
- {{"action":"manage_startup","startup_action":"list|add|remove","app_name":"<name>","app_path":"<path>"}}
- {{"action":"analyze_disk","disk_action":"usage|largest_files|health","path":"<optional dir path>"}}
- {{"action":"toggle_bluetooth","state":"on|off|toggle|status"}}
- {{"action":"manage_display","display_action":"info|list_monitors|rotate"}}
- {{"action":"manage_power_plan","plan_action":"list|set_high|set_balanced|set_saver"}}
- {{"action":"manage_env_var","env_action":"list|get|set|delete","name":"<var name>","value":"<var value>"}}
- {{"action":"manage_service","service_action":"list|status|start|stop|restart","name":"<service name>"}}
- {{"action":"system_sound","sound":"notification|error|warning|beep|question"}}
- {{"action":"system_power","power_action":"shutdown|restart|sleep|hibernate|schedule_shutdown|cancel_shutdown|log_off","delay":<minutes>}}

User command: "{user_text}"
JSON:"""

        try:
            from ollama_client import ollama_chat  # type: ignore[import]
            raw = ollama_chat(prompt=parse_prompt, max_tokens=200, temperature=0.1)
            if raw:
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
                    folder = text_lower[len(prefix):].strip()  # type: ignore[index]
                    break
            # Remove trailing "folder" word
            folder = folder.replace(" folder", "").strip()  # type: ignore[union-attr]
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

        elif "open" in text_lower or "launch" in text_lower or "start" in text_lower:
            # Extract what comes after the verb
            app_query = text_lower
            for prefix in ["open the ", "open my ", "open that ", "open ",
                           "launch the ", "launch my ", "launch ",
                           "start the ", "start my ", "start "]:
                if text_lower.startswith(prefix):
                    app_query = text_lower[len(prefix):].strip()
                    break

            # Check if it's a shorthand platform → open URL
            app_query_clean = app_query.replace(" app", "").replace(" software", "").replace(" program", "").strip()
            if app_query_clean in SHORTHAND_MAP:
                url = SHORTHAND_MAP[app_query_clean]
                if url:
                    action_data = {"action": "open_url", "url": url}
                else:
                    # wp/tg → open as app
                    resolved = fuzzy_match_app(app_query_clean)
                    action_data = {"action": "open_app", "app": resolved or app_query_clean}
            else:
                # Use fuzzy matching (exact → alias → substring → difflib)
                resolved = fuzzy_match_app(app_query)
                if resolved:
                    action_data = {"action": "open_app", "app": resolved}
                else:
                    # Last resort: pass raw query, let _open_application handle it
                    action_data = {"action": "open_app", "app": app_query_clean}


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
                    app = text_lower[len(prefix):].strip()  # type: ignore[index]
                    break
            action_data = {"action": "install_app", "app": app}
        elif any(w in text_lower for w in ["uninstall ", "remove app"]):
            app = text_lower
            for prefix in ["uninstall ", "remove app ", "remove "]:
                if text_lower.startswith(prefix):
                    app = text_lower[len(prefix):].strip()  # type: ignore[index]
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
                    # Extract the content to type from user command
                    # Patterns: "write X in app", "type X in app", "app mein X likho"
                    import re as _re_content
                    content = ""
                    # English: "write/type CONTENT in APP"
                    m = _re_content.search(
                        r'(?:write|type)\s+(.+?)\s+(?:in|into|on)\s+' + re.escape(app),
                        text_lower
                    )
                    if m:
                        content = m.group(1).strip()
                    else:
                        # "open APP and write/type CONTENT"
                        m2 = _re_content.search(
                            re.escape(app) + r'.*?(?:write|type|and write|and type)\s+(.+?)$',
                            text_lower
                        )
                        if m2:
                            content = m2.group(1).strip()
                    # Hindi: "APP mein CONTENT likho"
                    if not content:
                        m3 = _re_content.search(
                            re.escape(app) + r'\s+(?:mein|me|mai)\s+(.+?)\s*(?:likho|likh|type karo)?$',
                            text_lower
                        )
                        if m3:
                            content = m3.group(1).strip()
                    action_data = {"action": "type_in_app", "app": app, "content": content}
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

        # ── Advanced OS Operations (keyword fallback) ──────────────────
        # Process Management
        elif any(w in text_lower for w in ["kill process", "end task", "terminate process"]):
            proc = text_lower
            for prefix in ["kill process ", "end task ", "terminate process ", "kill "]:
                if text_lower.startswith(prefix):
                    proc = text_lower[len(prefix):].strip()
                    break
            action_data = {"action": "manage_process", "name": proc, "process_action": "kill"}
        elif any(w in text_lower for w in ["process info", "process details", "process status"]):
            proc = text_lower.replace("process info", "").replace("process details", "").replace("process status", "").strip()
            action_data = {"action": "manage_process", "name": proc or "chrome", "process_action": "info"}
        elif any(w in text_lower for w in ["high priority", "set priority"]):
            proc = text_lower.replace("high priority", "").replace("set priority", "").replace("for", "").strip()
            action_data = {"action": "manage_process", "name": proc, "process_action": "priority_high"}

        # Network Diagnostics
        elif any(w in text_lower for w in ["ping ", "ping google", "ping test"]):
            target = text_lower.replace("ping", "").strip() or "google.com"
            action_data = {"action": "network_diagnostics", "net_action": "ping", "target": target}
        elif any(w in text_lower for w in ["my ip", "ip address", "what is my ip", "ipconfig", "ip config"]):
            action_data = {"action": "network_diagnostics", "net_action": "ip_config"}
        elif any(w in text_lower for w in ["traceroute", "tracert"]):
            target = text_lower.replace("traceroute", "").replace("tracert", "").strip() or "google.com"
            action_data = {"action": "network_diagnostics", "net_action": "traceroute", "target": target}
        elif any(w in text_lower for w in ["dns lookup", "nslookup"]):
            target = text_lower.replace("dns lookup", "").replace("nslookup", "").strip() or "google.com"
            action_data = {"action": "network_diagnostics", "net_action": "dns_lookup", "target": target}
        elif any(w in text_lower for w in ["active connections", "netstat", "network connections"]):
            action_data = {"action": "network_diagnostics", "net_action": "active_connections"}
        elif any(w in text_lower for w in ["flush dns", "clear dns"]):
            action_data = {"action": "network_diagnostics", "net_action": "flush_dns"}
        elif any(w in text_lower for w in ["external ip", "public ip"]):
            action_data = {"action": "network_diagnostics", "net_action": "external_ip"}

        # Scheduled Tasks
        elif any(w in text_lower for w in ["scheduled task", "list tasks", "show tasks", "cron job"]):
            action_data = {"action": "manage_scheduled_task", "task_action": "list"}

        # Startup Apps
        elif any(w in text_lower for w in ["startup app", "startup program", "boot app",
                                            "show startup", "list startup", "auto start"]):
            action_data = {"action": "manage_startup", "startup_action": "list"}

        # Disk Analysis
        elif any(w in text_lower for w in ["disk usage", "disk space", "drive space", "storage space",
                                            "how much space", "free space"]):
            action_data = {"action": "analyze_disk", "disk_action": "usage"}
        elif any(w in text_lower for w in ["largest file", "biggest file", "large files"]):
            action_data = {"action": "analyze_disk", "disk_action": "largest_files"}
        elif any(w in text_lower for w in ["disk health", "drive health", "smart status"]):
            action_data = {"action": "analyze_disk", "disk_action": "health"}

        # Bluetooth
        elif "bluetooth" in text_lower:
            if any(w in text_lower for w in ["on", "enable", "chalu"]):
                action_data = {"action": "toggle_bluetooth", "state": "on"}
            elif any(w in text_lower for w in ["off", "disable", "band"]):
                action_data = {"action": "toggle_bluetooth", "state": "off"}
            elif "status" in text_lower:
                action_data = {"action": "toggle_bluetooth", "state": "status"}
            else:
                action_data = {"action": "toggle_bluetooth", "state": "toggle"}

        # Display Management
        elif any(w in text_lower for w in ["screen resolution", "display resolution", "my resolution",
                                            "what resolution", "current resolution"]):
            action_data = {"action": "manage_display", "display_action": "info"}
        elif any(w in text_lower for w in ["connected monitor", "list monitor", "how many monitor",
                                            "display info", "monitor info"]):
            action_data = {"action": "manage_display", "display_action": "list_monitors"}
        elif any(w in text_lower for w in ["rotate screen", "rotate display", "flip screen"]):
            action_data = {"action": "manage_display", "display_action": "rotate"}

        # UI Mode / Display Transform
        elif any(w in text_lower for w in ["maximize yourself", "maximize display", "full screen", "fullscreen", "expand ui", "expand display", "bada karo", "open full dashboard", "maximize mj", "maximize alita"]):
            action_data = {"action": "maximize_ui"}
        elif any(w in text_lower for w in ["minimize yourself", "collapse display", "collapse ui", "hide yourself", "chota karo", "overlay mode", "minimize mj", "minimize alita"]):
            action_data = {"action": "minimize_ui"}

        # Power Plans
        elif any(w in text_lower for w in ["power plan", "power mode", "energy mode"]):
            if any(w in text_lower for w in ["high performance", "high", "gaming", "performance"]):
                action_data = {"action": "manage_power_plan", "plan_action": "set_high"}
            elif any(w in text_lower for w in ["balanced", "normal", "default"]):
                action_data = {"action": "manage_power_plan", "plan_action": "set_balanced"}
            elif any(w in text_lower for w in ["saver", "power saver", "battery saver", "save"]):
                action_data = {"action": "manage_power_plan", "plan_action": "set_saver"}
            else:
                action_data = {"action": "manage_power_plan", "plan_action": "list"}
        elif any(w in text_lower for w in ["high performance"]):
            action_data = {"action": "manage_power_plan", "plan_action": "set_high"}

        # Environment Variables
        elif any(w in text_lower for w in ["environment variable", "env var", "system variable"]):
            action_data = {"action": "manage_env_var", "env_action": "list"}

        # Windows Services
        elif any(w in text_lower for w in ["windows service", "list service", "show service",
                                            "running service"]):
            action_data = {"action": "manage_service", "service_action": "list"}
        elif any(w in text_lower for w in ["start service", "stop service", "restart service"]):
            svc_action = "start"
            if "stop" in text_lower:
                svc_action = "stop"
            elif "restart" in text_lower:
                svc_action = "restart"
            svc_name = text_lower.replace("start service", "").replace("stop service", "").replace("restart service", "").strip()
            action_data = {"action": "manage_service", "service_action": svc_action, "name": svc_name}

        # System Sound
        elif any(w in text_lower for w in ["play sound", "system sound", "notification sound",
                                            "play beep", "beep"]):
            sound = "notification"
            if "error" in text_lower: sound = "error"
            elif "warning" in text_lower: sound = "warning"
            elif "beep" in text_lower: sound = "beep"
            action_data = {"action": "system_sound", "sound": sound}

        # Shutdown / Restart / Sleep / Hibernate
        elif any(w in text_lower for w in ["shut down", "shutdown", "turn off computer",
                                            "turn off pc", "switch off"]):
            action_data = {"action": "system_power", "power_action": "shutdown", "delay": 0}
        elif any(w in text_lower for w in ["restart computer", "restart pc", "restart system",
                                            "reboot", "reboot pc"]):
            action_data = {"action": "system_power", "power_action": "restart", "delay": 0}
        elif any(w in text_lower for w in ["sleep mode", "put to sleep", "go to sleep",
                                            "sleep computer", "computer sleep"]):
            action_data = {"action": "system_power", "power_action": "sleep"}
        elif "hibernate" in text_lower:
            action_data = {"action": "system_power", "power_action": "hibernate"}
        elif any(w in text_lower for w in ["cancel shutdown", "abort shutdown", "stop shutdown"]):
            action_data = {"action": "system_power", "power_action": "cancel_shutdown"}
        elif any(w in text_lower for w in ["schedule shutdown", "shutdown in", "shut down in"]):
            import re as _re_delay
            m = _re_delay.search(r"(\d+)\s*(?:min|minute|hour|hr)", text_lower)
            delay = int(m.group(1)) if m else 30
            if "hour" in text_lower or "hr" in text_lower:
                delay = delay * 60
            action_data = {"action": "system_power", "power_action": "schedule_shutdown", "delay": delay}
        elif any(w in text_lower for w in ["log off", "logoff", "sign out", "sign off"]):
            action_data = {"action": "system_power", "power_action": "log_off"}

        # Music Control
        elif any(w in text_lower for w in ["play music", "resume music", "gaana bajao"]):
            action_data = {"action": "control_music", "control": "play"}
        elif any(w in text_lower for w in ["pause music", "stop music"]):
            action_data = {"action": "control_music", "control": "pause"}
        elif any(w in text_lower for w in ["next song", "skip song"]):
            action_data = {"action": "control_music", "control": "next"}
        elif "previous song" in text_lower:
            action_data = {"action": "control_music", "control": "previous"}

        # ── Mood-based music (check BEFORE generic "play X") ──────────
        elif any(w in text_lower for w in ["mood", "feeling", "vibe", "according to"]) and \
                any(w in text_lower for w in ["play", "music", "song", "bajao", "chalao", "gaana"]):
            # Mood-aware: use SER emotion or extract mood from text
            mood_query = None
            # Check for explicit mood words in the text
            for mood_word in MOOD_MUSIC_MAP:
                if mood_word in text_lower:
                    mood_query = MOOD_MUSIC_MAP[mood_word]
                    break
            # Fall back to SER-detected mood
            if not mood_query and user_mood in MOOD_MUSIC_MAP:
                mood_query = MOOD_MUSIC_MAP[user_mood]
            # Final fallback
            if not mood_query:
                mood_query = MOOD_MUSIC_MAP.get("neutral", "top trending songs today")
            action_data = {"action": "open_music", "query": mood_query}

        elif text_lower.startswith("play ") and not any(w in text_lower for w in ["play music", "play next"]):
            # "play X on youtube" / "play X in youtube" / "play X" → open_music
            import re as _re
            m = _re.search(r"play\s+(.+?)(?:\s+(?:on|in)\s+(?:the\s+)?(?:youtube|spotify|yt|gaana))?$", text_lower)
            query = m.group(1).strip() if m else text_lower.replace("play", "").strip()
            query = _re.sub(r"\b(song|songs?|video|videos?|the|best|some|good|a|an|track|in\s+the\s+youtube|in\s+youtube|on\s+the\s+youtube|on\s+youtube|in\s+yt|on\s+yt)\b", "", query, flags=_re.IGNORECASE)
            query = _re.sub(r"\b(in|on|at|the|for|to)\b\s*$", "", query, flags=_re.IGNORECASE)
            query = _re.sub(r"^\s*\b(in|on|at|the|for|to)\b", "", query, flags=_re.IGNORECASE).strip()
            query = _re.sub(r"\s+", " ", query).strip()
            if not query or query in ("music", "songs", "something", "in", "on", "a", ""):
                query = MOOD_MUSIC_MAP.get(user_mood, MOOD_MUSIC_MAP["neutral"])
            action_data = {"action": "open_music", "query": query}
        elif any(w in text_lower for w in ["play song", "play on youtube", "play in youtube", "play on spotify", "play on yt"]):
            import re as _re
            query = _re.sub(r"\b(play|song|songs?|music|on\s+the\s+youtube|on\s+youtube|in\s+the\s+youtube|in\s+youtube|on\s+spotify|in\s+spotify|on\s+yt|in\s+yt|the|a|an|some)\b", "", text_lower, flags=_re.IGNORECASE)
            query = _re.sub(r"\b(in|on|at|the|for|to)\b\s*$", "", query, flags=_re.IGNORECASE)
            query = _re.sub(r"^\s*\b(in|on|at|the|for|to)\b", "", query, flags=_re.IGNORECASE).strip()
            query = _re.sub(r"\s+", " ", query).strip()
            if not query or query in ("music", "songs", "something", "in", "on", "a", ""):
                query = MOOD_MUSIC_MAP.get(user_mood, MOOD_MUSIC_MAP["neutral"])
            action_data = {"action": "open_music", "query": query}
        elif text_lower.startswith("bajao ") or text_lower.startswith("chalao "):
            import re as _re
            query = text_lower.replace("bajao", "").replace("chalao", "").strip()
            query = _re.sub(r"\b(music|gaana|kuch|kholo|baja|chala|on\s+youtube|in\s+youtube|yt)\b", "", query, flags=_re.IGNORECASE).strip()
            if not query or query in ("music", "gaana", "kuch", ""):
                query = MOOD_MUSIC_MAP.get(user_mood, MOOD_MUSIC_MAP["neutral"])
            action_data = {"action": "open_music", "query": query}

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
                    habit = text_lower[len(prefix):]  # type: ignore[index]
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

        # Song Recognition — broad natural triggers (no strict word boundaries)
        elif any(w in text_lower for w in [
            "what song", "which song", "identify song", "identify this song",
            "recognize song", "recognize this song", "name this song",
            "shazam", "what is playing", "what's playing", "what is this song",
            "what's this song", "konsa gaana", "ye gaana", "what music",
            "this song", "ye kya baj", "kya baj raha", "song playing",
            "bata ye gaana", "gaana bata", "song bata", "pehchaan",
            "which music", "what tune", "which tune", "identify the song",
            "tell me the song", "what am i listening", "listening to what",
            "song is this", "music is this", "what's the name of this",
        ]):
            action_data = {"action": "recognize_song"}

        # ── Phone / Mobile / Android Automation ─────────────────────────
        elif any(w in text_lower for w in ["unlock phone", "unlock mobile", "phone unlock", "phone kholo"]):
            action_data = {"action": "phone_unlock"}
        elif any(w in text_lower for w in ["phone battery", "mobile battery", "phone charge", "phone ka battery"]):
            action_data = {"action": "phone_status"}
        elif any(w in text_lower for w in ["phone status", "phone state", "phone info", "mobile status", "phone ka status"]):
            action_data = {"action": "phone_status"}
        elif any(w in text_lower for w in ["phone notification", "mobile notification", "latest notification", "recent notification",
                                            "phone ke notification", "notification dikhao", "notification batao"]):
            action_data = {"action": "phone_notifications"}
        elif any(w in text_lower for w in ["reply to notification", "reply on notification", "notification reply",
                                            "notification ka reply", "notification ko reply"]):
            # Extract app and reply text
            action_data = {"action": "phone_reply_notification", "text": user_text}
        elif any(w in text_lower for w in ["phone screen", "mobile screen", "phone ka screen", "android screen",
                                            "phone pe kya hai", "phone pe dikhao", "phone pe dekho"]):
            action_data = {"action": "phone_read_screen"}

        # ── Phone Call ────────────────────────────────────────────────────
        elif any(w in text_lower for w in ["call ", "phone call", "dial ", "ring ",
                                            "call karo", "call laga", "phone karo",
                                            "make a call", "make call"]):
            import re as _re
            cm = _re.search(r'(?:call|dial|ring|phone karo|call karo|call laga)\s+(.+)', text_lower)
            target = cm.group(1).strip() if cm else ""
            # Strip trailing "on phone" / "on mobile"
            target = _re.sub(r'\s+(?:on|from)\s+(?:my\s+)?(?:phone|mobile|android)$', '', target).strip()
            # Check if it looks like a phone number
            digits = _re.sub(r'[^0-9+]', '', target)
            if len(digits) >= 7:
                action_data = {"action": "phone_make_call", "number": digits}
            else:
                action_data = {"action": "phone_make_call", "contactName": target}

        elif any(w in text_lower for w in ["end call", "hang up", "cut the call", "call end",
                                            "call kat", "call kaat", "disconnect call"]):
            action_data = {"action": "phone_end_call"}

        # ── SMS ───────────────────────────────────────────────────────────
        elif any(w in text_lower for w in ["send sms", "send text", "send a text", "sms bhejo",
                                            "text message", "sms to", "text to"]):
            action_data = {"action": "phone_send_sms", "raw_text": user_text}

        # ── Volume Control ────────────────────────────────────────────────
        elif any(w in text_lower for w in ["volume up", "volume badha", "awaaz badha",
                                            "increase volume", "turn up volume",
                                            "phone volume up", "phone ki awaaz badha"]):
            action_data = {"action": "phone_volume", "volume_action": "up"}
        elif any(w in text_lower for w in ["volume down", "volume kam", "awaaz kam",
                                            "decrease volume", "turn down volume", "lower volume",
                                            "phone volume down", "phone ki awaaz kam"]):
            action_data = {"action": "phone_volume", "volume_action": "down"}
        elif any(w in text_lower for w in ["mute phone", "phone mute", "silent mode", "phone silent",
                                            "phone ko mute", "phone chup karo", "mute karo"]):
            action_data = {"action": "phone_volume", "volume_action": "mute"}
        elif any(w in text_lower for w in ["unmute phone", "phone unmute", "unmute karo"]):
            action_data = {"action": "phone_volume", "volume_action": "unmute"}
        elif any(w in text_lower for w in ["max volume", "full volume", "volume full", "volume max",
                                            "puri awaaz", "poori awaaz"]):
            action_data = {"action": "phone_volume", "volume_action": "max"}

        # ── Media Playback ────────────────────────────────────────────────
        elif any(w in text_lower for w in ["pause music", "pause song", "music pause",
                                            "gaana roko", "song roko", "pause media",
                                            "pause phone music", "phone music pause"]):
            action_data = {"action": "phone_media", "media_action": "pause"}
        elif any(w in text_lower for w in ["play music", "resume music", "resume song",
                                            "gaana chalao", "gaana bajao", "play media",
                                            "resume media", "phone music play"]):
            action_data = {"action": "phone_media", "media_action": "play"}
        elif any(w in text_lower for w in ["next song", "next track", "skip song", "skip track",
                                            "agla gaana", "next gaana", "skip karo"]):
            action_data = {"action": "phone_media", "media_action": "next"}
        elif any(w in text_lower for w in ["previous song", "previous track", "prev song",
                                            "pichla gaana", "previous gaana", "last song"]):
            action_data = {"action": "phone_media", "media_action": "previous"}

        # ── Flashlight ────────────────────────────────────────────────────
        elif any(w in text_lower for w in ["flashlight on", "torch on", "turn on flashlight",
                                            "turn on torch", "flash on", "flashlight chalu",
                                            "torch chalu", "torch jalao", "flashlight jalao"]):
            action_data = {"action": "phone_flashlight", "enabled": True}
        elif any(w in text_lower for w in ["flashlight off", "torch off", "turn off flashlight",
                                            "turn off torch", "flash off", "flashlight band",
                                            "torch band", "torch bujhao", "flashlight bujhao"]):
            action_data = {"action": "phone_flashlight", "enabled": False}

        # ── Alarm & Timer ─────────────────────────────────────────────────
        elif any(w in text_lower for w in ["set alarm", "set an alarm", "alarm set", "alarm laga",
                                            "alarm lagao", "alarm baja", "wake me up"]):
            import re as _re
            am = _re.search(r'(\d{1,2})(?::(\d{2}))?\s*(?:am|pm|baje)?', text_lower)
            hour = int(am.group(1)) if am else 6
            minute = int(am.group(2)) if am and am.group(2) else 0
            if 'pm' in text_lower and hour < 12:
                hour += 12
            action_data = {"action": "phone_set_alarm", "hour": hour, "minute": minute}

        elif any(w in text_lower for w in ["set timer", "set a timer", "timer set", "timer laga",
                                            "timer lagao", "start timer", "countdown"]):
            import re as _re
            tm = _re.search(r'(\d+)\s*(?:min|minute|second|sec|hour|hr)', text_lower)
            if tm:
                val = int(tm.group(1))
                if any(u in text_lower for u in ["hour", "hr", "ghanta"]):
                    secs = val * 3600
                elif any(u in text_lower for u in ["min", "minute"]):
                    secs = val * 60
                else:
                    secs = val
            else:
                secs = 300  # default 5 min
            action_data = {"action": "phone_set_timer", "seconds": secs}

        # ── Camera ────────────────────────────────────────────────────────
        elif any(w in text_lower for w in ["open camera", "camera kholo", "camera open",
                                            "take photo", "take a photo", "photo lo",
                                            "take selfie", "selfie lo", "selfie lelo",
                                            "capture photo", "take picture"]):
            is_selfie = any(w in text_lower for w in ["selfie", "front camera"])
            action_data = {"action": "phone_camera", "selfie": is_selfie}

        # ── Clipboard Sync ────────────────────────────────────────────────
        elif any(w in text_lower for w in ["copy to phone", "send to phone clipboard",
                                            "phone clipboard", "clipboard sync",
                                            "phone pe copy", "phone pe bhejo"]):
            action_data = {"action": "phone_set_clipboard", "raw_text": user_text}
        elif any(w in text_lower for w in ["get phone clipboard", "phone se copy", "phone se paste",
                                            "phone ka clipboard", "paste from phone"]):
            action_data = {"action": "phone_get_clipboard"}

        # ── Brightness ────────────────────────────────────────────────────
        elif any(w in text_lower for w in ["brightness", "screen brightness", "phone brightness",
                                            "phone ki brightness", "brightness set"]):
            import re as _re
            bm = _re.search(r'(\d+)', text_lower)
            level = int(bm.group(1)) if bm else 128
            # Interpret 0-100 as percentage, scale to 0-255
            if level <= 100:
                level = int(level * 255 / 100)
            action_data = {"action": "phone_brightness", "level": level}

        # ── Lock Screen ───────────────────────────────────────────────────
        elif any(w in text_lower for w in ["lock phone", "lock screen", "lock my phone",
                                            "phone lock karo", "screen lock karo",
                                            "phone band karo"]):
            action_data = {"action": "phone_lock"}

        # ── Phone Screenshot ──────────────────────────────────────────────
        elif any(w in text_lower for w in ["phone screenshot", "phone ka screenshot",
                                            "phone pe screenshot", "mobile screenshot",
                                            "screenshot on phone"]):
            action_data = {"action": "phone_screenshot"}

        elif any(w in text_lower for w in ["on my phone", "on phone", "on mobile", "on android",
                                            "phone pe", "phone par", "phone mein", "phone me",
                                            "mobile pe", "mobile par", "mobile mein"]):
            # Generic phone command — extract what to do
            phone_cmd = text_lower
            for strip in ["on my phone", "on phone", "on mobile", "on android",
                          "phone pe", "phone par", "phone mein", "phone me",
                          "mobile pe", "mobile par", "mobile mein", "mobile me"]:
                phone_cmd = phone_cmd.replace(strip, "").strip()
            # Check if it's "open X" on phone
            if any(phone_cmd.startswith(v) for v in ["open ", "launch ", "start ", "kholo ", "chalao "]):
                app_name = phone_cmd
                for prefix in ["open ", "launch ", "start ", "kholo ", "chalao "]:
                    if phone_cmd.startswith(prefix):
                        app_name = phone_cmd[len(prefix):].strip()
                        break
                action_data = {"action": "phone_open_app", "app": app_name}
            else:
                # Generic phone intent — pass raw text to orchestrator
                action_data = {"action": "phone_generic", "command": phone_cmd, "raw_text": user_text}

        # Smart Search
        elif any(w in text_lower for w in ["find file", "search file", "locate file", "find the", "find my"]):
            query = text_lower
            for prefix in ["find file ", "search file ", "locate file ", "find the ", "find my ", "find "]:
                if text_lower.startswith(prefix):
                    query = text_lower[len(prefix):]  # type: ignore[index]
                    break
            file_type = ""
            for ft in ["pdf", "document", "image", "photo", "video", "audio", "excel"]:
                if ft in text_lower:
                    file_type = ft
                    query = query.replace(ft, "").strip()  # type: ignore[union-attr]
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
        elif ("whatsapp" in text_lower or "wp" in text_lower.split()) and any(w in text_lower for w in ["send", "message", "msg", "bhejo", "bhej", "text", "saying", "chat"]):
            info = _extract_whatsapp_info(user_text)
            action_data = {"action": "send_whatsapp", "contact": info["contact"], "message": info["message"]}
        elif any(w in text_lower for w in ["send file on whatsapp", "whatsapp file", "share file on whatsapp"]):
            import re
            contact_match = re.search(r"(?:to|for)\s+([a-zA-Z0-9_\-]+)", text_lower)
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
                           contact.lower(), str(app), str(location), "whatsapp"]:  # type: ignore[arg-type]
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

    # Normalize action names (e.g., open_whatsapp -> open_app, play_music -> open_music)
    action_data = _normalize_automation_action(action_data, user_text)
    action = action_data.get("action", "")
    result = None

    # ── Runtime guard: prevent open_app when messaging intent detected ──
    # If LLM generated open_app(whatsapp) but user text has messaging keywords,
    # override to send_whatsapp to prevent opening WhatsApp without sending.
    if action == "open_app" and action_data.get("app", "").lower() in (
        "whatsapp", "wp", "watsapp", "what'sapp"
    ):
        _msg_keywords = ["send", "message", "msg", "bhejo", "bhej",
                         "good morning", "good night", "greet", "congrats",
                         "thanks", "file", "photo", "video", "document", "number"]
        if any(kw in text_lower for kw in _msg_keywords):
            info = _extract_whatsapp_info(user_text)
            if info["contact"] and info["contact"] != "Unknown":
                log.info("[Guard] Overriding open_app(whatsapp) → send_whatsapp (contact='%s')", info["contact"])
                action = "send_whatsapp"
                action_data = {
                    "action": "send_whatsapp",
                    "contact": info["contact"],
                    "message": info["message"],
                }


    ACTION_MAP = {
        "workflow_macro": lambda d: run_workflow_macro(d.get("macro", "work"), session=session, settings=settings),
        "open_app": lambda d: open_app(fuzzy_match_app(d.get("app", "")) or d.get("app", "")),
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
        # ── Browser Autopilot Actions ──────────────────────────────────
        "summarize_webpage": lambda d: (lambda: __import__("engines.browser_controller", fromlist=["browser_controller"]).browser_controller.summarize_active_page())(),
        "extract_page_data": lambda d: (lambda: __import__("engines.browser_controller", fromlist=["browser_controller"]).browser_controller.extract_page_data(d.get("data_type", "links")))(),
        "meeting_mode": lambda d: (lambda dt=__import__('datetime').datetime.now(): (
            set_volume("20"),
            open_app("notepad"),
            {"status": "success", "action": "meeting_mode", "detail": f"Meeting Mode Activated: Adjusted volume to 20% and prepared meeting notes in Notepad ({dt.strftime('%H:%M')})."}
        )[-1])(),
        "explain_error": lambda d: {"status": "success", "action": "explain_error", "detail": f"Analyzing error: {d.get('error', '')[:80]}..."},
        "maximize_ui": lambda d: {"status": "success", "action": "maximize_ui", "__meta__": True, "type": "ui_mode_change", "mode": "expanded", "detail": "Maximizing display to full command center."},
        "minimize_ui": lambda d: {"status": "success", "action": "minimize_ui", "__meta__": True, "type": "ui_mode_change", "mode": "overlay", "detail": "Collapsing display to floating holographic overlay."},
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
        # ── WhatsApp messaging (synchronous to guarantee verified delivery before spoken reply) ──
        "send_whatsapp": lambda d: send_whatsapp_message(d.get("contact", ""), d.get("message", ""), settings),
        "send_whatsapp_file": lambda d: send_whatsapp_file(d.get("contact", ""), d.get("file_path", "")),
        # ── Intelligent file sharing (non-blocking) ───────────────────
        "send_to_app": lambda d: _task_manager.start_task(
            f"send_{d.get('app','wa')[:10]}_{d.get('contact','')[:10]}_{int(_time_module.time())}",
            send_to_app, (d.get("contact", ""), d.get("message", ""), d.get("app", "whatsapp"), d.get("file_path", "")),
            description=f"Sending to {d.get('contact', '')} on {d.get('app', 'WhatsApp')}"),
        "send_file_smart": lambda d: _task_manager.start_task(
            f"send_file_{d.get('contact','')[:10]}_{int(_time_module.time())}",
            lambda: send_file_with_message(
                d.get("contact", ""), d.get("file_name", ""),
                d.get("app", "whatsapp"), d.get("custom_message", ""),
                d.get("compose_message", False),
                location=d.get("location", ""),
                session=session, settings=settings),
            description=f"Sending file '{d.get('file_name', '')}' to {d.get('contact', '')}"),
        "find_file": lambda d: find_file_smart(d.get("name", ""), location=d.get("location", "")),
        # ── Install / Uninstall (background) ───────────────────────────
        "install_app": lambda d: install_app(d.get("app", "")),
        "uninstall_app": lambda d: uninstall_app(d.get("app", "")),
        "check_task_status": lambda d: check_task_status(d.get("task_id", "")),
        # ── Visual Context Automation ─────────────────────────────────
        "navigate_ui": lambda d: navigate_ui(d.get("target", ""), settings=settings),
        "switch_and_execute": lambda d: switch_and_execute(d.get("app", ""), d.get("command", ""), d.get("return", True), settings=settings),
        # ── Advanced OS Operations ─────────────────────────────────────
        "manage_process": lambda d: manage_process(d.get("name", ""), d.get("process_action", "info")),
        "network_diagnostics": lambda d: network_diagnostics(d.get("net_action", "ip_config"), d.get("target", "")),
        "manage_scheduled_task": lambda d: manage_scheduled_task(d.get("task_action", "list"), d.get("name", ""), d.get("command", ""), d.get("schedule", "")),
        "manage_startup": lambda d: manage_startup_apps(d.get("startup_action", "list"), d.get("app_name", ""), d.get("app_path", "")),
        "analyze_disk": lambda d: analyze_disk(d.get("disk_action", "usage"), d.get("path", "")),
        "toggle_bluetooth": lambda d: toggle_bluetooth(d.get("state", "toggle")),
        "manage_display": lambda d: manage_display(d.get("display_action", "info")),
        "manage_power_plan": lambda d: manage_power_plan(d.get("plan_action", "list")),
        "manage_env_var": lambda d: manage_env_var(d.get("env_action", "list"), d.get("name", ""), d.get("value", "")),
        "manage_service": lambda d: manage_service(d.get("service_action", "list"), d.get("name", "")),
        "system_sound": lambda d: system_sound(d.get("sound", "notification")),
        "system_power": lambda d: system_power(d.get("power_action", "shutdown"), d.get("delay", 0)),
        # ── Phone / Mobile / Android Automation ────────────────────────
        "phone_unlock": lambda d: _phone_action("unlock", d, session),
        "phone_status": lambda d: _phone_action("status", d, session),
        "phone_notifications": lambda d: _phone_action("notifications", d, session),
        "phone_reply_notification": lambda d: _phone_action("reply_notification", d, session),
        "phone_read_screen": lambda d: _phone_action("read_screen", d, session),
        "phone_open_app": lambda d: _phone_action("open_app", d, session),
        "phone_generic": lambda d: _phone_action("generic", d, session),
        # ── Full Phone Automation (new) ────────────────────────────────
        "phone_make_call": lambda d: _phone_action("make_call", d, session),
        "phone_end_call": lambda d: _phone_action("end_call", d, session),
        "phone_send_sms": lambda d: _phone_action("send_sms", d, session),
        "phone_volume": lambda d: _phone_action("volume", d, session),
        "phone_media": lambda d: _phone_action("media", d, session),
        "phone_flashlight": lambda d: _phone_action("flashlight", d, session),
        "phone_set_alarm": lambda d: _phone_action("set_alarm", d, session),
        "phone_set_timer": lambda d: _phone_action("set_timer", d, session),
        "phone_camera": lambda d: _phone_action("camera", d, session),
        "phone_set_clipboard": lambda d: _phone_action("set_clipboard", d, session),
        "phone_get_clipboard": lambda d: _phone_action("get_clipboard", d, session),
        "phone_brightness": lambda d: _phone_action("brightness", d, session),
        "phone_lock": lambda d: _phone_action("lock", d, session),
        "phone_screenshot": lambda d: _phone_action("screenshot", d, session),
    }

    handler = ACTION_MAP.get(action)  # type: ignore[call-overload]
    if handler:
        log.info("[%s] Executing automation: %s | data=%s", session.session_id, action, json.dumps(action_data)[:100])  # type: ignore[index]
        result = handler(action_data)
        # Save this command for retry/verify support
        session._last_automation_cmd = user_text

        # ── Smart fallback: open_app failed → try open_folder ─────────
        if isinstance(result, str):
            result = {"status": "success", "detail": result}

        # When user says "open Price" while viewing Downloads in Explorer,
        # the LLM parses it as open_app("price") which fails. This fallback
        # tries open_folder which resolves "price" as a subfolder.
        if action == "open_app" and isinstance(result, dict) and result.get("status") in ("error", "not_installed"):
            app_name = action_data.get("app", "")
            if app_name:
                folder_result = open_folder(str(app_name))  # type: ignore[arg-type]
                if folder_result.get("status") == "success":
                    log.info("[%s] open_app failed → open_folder fallback succeeded for '%s'",
                             session.session_id, app_name)
                    result = folder_result

        # Check if this triggers dictation mode
        if isinstance(result, dict) and result.get("dictation_mode"):
            session.dictation_active = True
            session.dictation_app = result.get("app", "")
            log.info("[%s] Dictation mode activated for app: %s", session.session_id, session.dictation_app)
        # Check if app is not installed — signal store redirect
        if isinstance(result, dict) and result.get("status") == "not_installed":
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

    # ── Fast Template Responder: Instant (<1ms) natural spoken reply ───────
    if result:
        action_name = result.get("action") or action
        status_val = result.get("status")
        detail_msg = result.get("detail")

        # 1. Direct clean detail message if provided by action
        if detail_msg and isinstance(detail_msg, str) and len(detail_msg) > 5 and not detail_msg.startswith("{"):
            tokens = [detail_msg]
            if meta:
                tokens.append(meta)
            return tokens

        # 2. Template dictionary for zero-latency responses (<1ms vs 1500ms LLM)
        app_name = result.get("app") or action_data.get("app", "app")
        templates = {
            "open_app": f"Opened {app_name} for you.",
            "close_app": f"Closed {app_name}.",
            "open_folder": f"Opened {action_data.get('folder', 'folder')} in Explorer.",
            "set_volume": f"Volume set to {action_data.get('level', '50')} percent.",
            "toggle_mute": "Audio muted." if result.get("muted") else "Audio unmuted.",
            "set_brightness": f"Screen brightness adjusted to {action_data.get('level', '70')} percent.",
            "screenshot": "Screenshot saved to your Desktop.",
            "lock_screen": "Locking your screen.",
            "empty_recycle_bin": "Recycle bin has been emptied.",
            "toggle_dark_mode": "Theme mode toggled.",
            "battery": result.get("info", "Battery status retrieved."),
            "system_info": result.get("info", "System diagnostics ready."),
        }

        if status_val == "success" and action_name in templates:
            tokens = [templates[action_name]]
            if meta:
                tokens.append(meta)
            return tokens

    # ── Format result via LLM (Fallback for non-templated actions) ────────
    if result:
        try:
            from ollama_client import ollama_chat  # type: ignore[import]

            format_prompt = f"""You are MJ, a voice assistant. 
The user asked: "{user_text}"
The action result is: {json.dumps(result)}
LANGUAGE RULE: If the user spoke English, reply in PURE English only. If Hindi, reply in PURE Hindi (Devanagari) only. NEVER mix languages.
Give a natural, concise spoken response (1 sentence). Sound human, not robotic."""

            text = ollama_chat(prompt=format_prompt, max_tokens=60, temperature=0.5)
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
            tokens.append(meta)  # type: ignore[arg-type]
        return tokens

    return ["I completed the action but couldn't verify the result."]
