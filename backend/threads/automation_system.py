"""
Alita Automation — System Control & Administration (automation_system.py)
========================================================================
OS administration, power management, system telemetry, and utilities:
- get_system_info, get_battery, get_running_processes, run_shell_command
- set_brightness, toggle_dark_mode, lock_screen, empty_recycle_bin
- toggle_wifi, toggle_bluetooth, manage_process, network_diagnostics
- manage_scheduled_task, manage_startup_apps, analyze_disk, manage_display
- manage_power_plan, manage_env_var, manage_service, system_power
- reminders, clipboard history, habit tracking, mood journaling
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger("Alita.automation_system")

_SHELL_METACHAR_RE = re.compile(r'[;\x00&|`$(){}\[\]<>!\\\n\r]')

def _sanitize_arg(value: str) -> str:
    """Strip shell metacharacters from user input to prevent injection."""
    if not value:
        return ""
    return _SHELL_METACHAR_RE.sub('', value).strip()


_BLOCKED_COMMANDS = [
    "format", "del ", "rm ", "rmdir", "rd ", "erase",
    "net user", "net localgroup", "net share",
    "reg add", "reg delete", "regedit",
    "powershell -enc", "powershell -e ", "iex", "invoke-expression",
    "certutil", "bitsadmin", "shutdown", "restart", "logoff",
    "schtasks /create", "schtasks /delete",
    "sc create", "sc delete", "sc config",
    "wmic process call", "wmic os call",
    "mklink", "icacls", "takeown", "cacls",
    "bcdedit", "diskpart", "cipher /w",
    "curl", "wget", "invoke-webrequest", "downloadstring",
    "start-process", "new-object",
]

def _is_command_blocked(command: str) -> bool:
    """Check if command matches blocked patterns."""
    cmd_lower = re.sub(r'\s+', ' ', command.lower().strip())
    return any(blocked in cmd_lower for blocked in _BLOCKED_COMMANDS)


def get_system_info() -> dict:
    """Get basic system telemetry: CPU, RAM, OS, Disk."""
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
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_battery() -> dict:
    """Get battery charging status and percentage."""
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
    except Exception as e:
        return {"status": "error", "error": str(e)}


def get_running_processes(limit: int = 15) -> dict:
    """List top running processes by memory consumption."""
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
    except Exception as e:
        return {"status": "error", "error": str(e)}


def run_shell_command(command: str) -> dict:
    """Run a safe shell command."""
    try:
        if _is_command_blocked(command):
            log.warning("[SECURITY] Blocked dangerous command: %s", command[:80])
            return {"status": "error", "error": "This command is not allowed for security reasons."}

        sanitized = _sanitize_arg(command)
        if not sanitized:
            return {"status": "error", "error": "Invalid command."}

        result = subprocess.run(
            sanitized, shell=True, capture_output=True, text=True, timeout=15
        )
        return {
            "status": "success",
            "command": sanitized,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:500] if result.stderr else "",
            "exit_code": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"status": "error", "error": "Command timed out (15s limit)"}
    except Exception:
        return {"status": "error", "error": "Command execution failed."}


def take_screenshot(save_path: str = "") -> dict:
    """Capture full desktop screenshot."""
    try:
        if not save_path:
            save_path = os.path.expanduser("~/Desktop/screenshot.png")
        os.makedirs(os.path.dirname(os.path.abspath(save_path)), exist_ok=True)
        try:
            import mss
            with mss.mss() as sct:
                sct.shot(output=save_path)
            return {"status": "success", "action": "screenshot_saved", "path": save_path}
        except Exception:
            from PIL import ImageGrab
            img = ImageGrab.grab(all_screens=True)
            img.save(save_path)
            return {"status": "success", "action": "screenshot_saved", "path": save_path}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def set_brightness(level: str) -> dict:
    """Set screen brightness percentage."""
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
             f"(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods).WmiSetBrightness(1,{pct})"],
            capture_output=True, timeout=5
        )
        return {"status": "success", "action": "set_brightness", "detail": f"Brightness set to {pct}%"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def toggle_dark_mode() -> dict:
    """Toggle Windows light/dark theme."""
    try:
        ps_cmd = (
            "$path = 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize'; "
            "$val = (Get-ItemProperty -Path $path -Name AppsUseLightTheme).AppsUseLightTheme; "
            "$newVal = if ($val -eq 0) { 1 } else { 0 }; "
            "Set-ItemProperty -Path $path -Name AppsUseLightTheme -Value $newVal; "
            "Set-ItemProperty -Path $path -Name SystemUsesLightTheme -Value $newVal; "
            "if ($newVal -eq 0) { 'dark' } else { 'light' }"
        )
        result = subprocess.run(
            ["powershell", "-Command", ps_cmd],
            capture_output=True, text=True, timeout=5
        )
        mode = result.stdout.strip() or "toggled"
        return {"status": "success", "action": "toggle_dark_mode", "detail": f"Switched to {mode} mode"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def lock_screen() -> dict:
    """Lock the Windows workstation."""
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return {"status": "success", "action": "lock_screen", "detail": "Screen locked"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def empty_recycle_bin() -> dict:
    """Empty the Windows Recycle Bin."""
    try:
        import ctypes
        flags = 7
        result = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
        return {"status": "success", "action": "empty_recycle_bin", "detail": "Recycle bin emptied"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def toggle_wifi(state: str = "toggle") -> dict:
    """Toggle Wi-Fi adapter on/off."""
    try:
        s = state.lower().strip()
        if s in ("on", "enable"):
            cmd = "netsh interface set interface 'Wi-Fi' admin=enabled"
            detail = "Wi-Fi enabled"
        elif s in ("off", "disable"):
            cmd = "netsh interface set interface 'Wi-Fi' admin=disabled"
            detail = "Wi-Fi disabled"
        else:
            cmd = "powershell -Command \"$w = Get-NetAdapter -Name 'Wi-Fi*'; if ($w.Status -eq 'Up') { Disable-NetAdapter -Name $w.Name -Confirm:$false } else { Enable-NetAdapter -Name $w.Name -Confirm:$false }\""
            detail = "Wi-Fi toggled"
        subprocess.run(cmd, shell=True, capture_output=True, timeout=8)
        return {"status": "success", "action": "toggle_wifi", "detail": detail}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def toggle_bluetooth(state: str = "toggle") -> dict:
    """Toggle Bluetooth radio on/off."""
    try:
        s = state.lower().strip()
        ps_cmd = (
            "[Windows.Devices.Radios.Radio,Windows.System.Devices,ContentType=WindowsRuntime] | Out-Null; "
            "$radios = [Windows.Devices.Radios.Radio]::GetRadiosAsync().GetAwaiter().GetResult(); "
            "$bt = $radios | Where-Object { $_.Kind -eq 'Bluetooth' }; "
            "if ($bt) { "
            f"  $target = if ('{s}' -eq 'on') {{ [Windows.Devices.Radios.RadioState]::On }} "
            f"            elseif ('{s}' -eq 'off') {{ [Windows.Devices.Radios.RadioState]::Off }} "
            f"            else {{ if ($bt.State -eq 'On') {{ [Windows.Devices.Radios.RadioState]::Off }} else {{ [Windows.Devices.Radios.RadioState]::On }} }}; "
            "  $bt.SetStateAsync($target).GetAwaiter().GetResult() | Out-Null; "
            "  $target.ToString() "
            "} else { 'No Bluetooth radio found' }"
        )
        res = subprocess.run(["powershell", "-Command", ps_cmd], capture_output=True, text=True, timeout=8)
        return {"status": "success", "action": "toggle_bluetooth", "detail": f"Bluetooth state: {res.stdout.strip()}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def system_power(action: str = "shutdown", delay: int = 0) -> dict:
    """Shutdown, restart, sleep, or hibernate."""
    _CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        act = action.lower().strip()
        if act == "shutdown":
            delay_sec = max(0, delay * 60) if delay > 0 else 30
            subprocess.run(["shutdown", "/s", "/t", str(delay_sec)], capture_output=True, timeout=5, creationflags=_CREATE_NO_WINDOW)
            return {"status": "success", "action": "shutdown", "detail": f"Shutdown in {delay_sec // 60} min."}
        elif act == "restart":
            delay_sec = max(0, delay * 60) if delay > 0 else 30
            subprocess.run(["shutdown", "/r", "/t", str(delay_sec)], capture_output=True, timeout=5, creationflags=_CREATE_NO_WINDOW)
            return {"status": "success", "action": "restart", "detail": f"Restart in {delay_sec // 60} min."}
        elif act == "sleep":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Add-Type -Assembly System.Windows.Forms; [System.Windows.Forms.Application]::SetSuspendState([System.Windows.Forms.PowerState]::Suspend, $false, $false)"],
                capture_output=True, timeout=5
            )
            return {"status": "success", "action": "sleep", "detail": "Entering sleep mode"}
        elif act == "hibernate":
            subprocess.run(["shutdown", "/h"], capture_output=True, timeout=5, creationflags=_CREATE_NO_WINDOW)
            return {"status": "success", "action": "hibernate", "detail": "Entering hibernation"}
        elif act in ("cancel_shutdown", "abort"):
            subprocess.run(["shutdown", "/a"], capture_output=True, timeout=5, creationflags=_CREATE_NO_WINDOW)
            return {"status": "success", "action": "cancel_shutdown", "detail": "Scheduled shutdown aborted"}
        return {"status": "error", "error": f"Unknown power action: {action}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Reminders persistence ──────────────────────────────────────────────────
_REMINDERS_DIR = os.path.join(".", "data", "reminders")

def _load_reminders() -> list:
    os.makedirs(_REMINDERS_DIR, exist_ok=True)
    fpath = os.path.join(_REMINDERS_DIR, "reminders.json")
    if os.path.exists(fpath):
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def _save_reminders(reminders: list):
    os.makedirs(_REMINDERS_DIR, exist_ok=True)
    fpath = os.path.join(_REMINDERS_DIR, "reminders.json")
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(reminders, f, indent=2, ensure_ascii=False)

def set_reminder(text: str, time_str: str = "") -> dict:
    """Set a desktop reminder."""
    try:
        reminders = _load_reminders()
        import uuid
        r_id = f"rem_{str(uuid.uuid4())[:8]}"
        reminders.append({
            "id": r_id, "text": text, "time": time_str,
            "created_at": datetime.now().isoformat(), "active": True,
        })
        _save_reminders(reminders)
        return {"status": "success", "action": "reminder_set", "id": r_id, "text": text, "time": time_str}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def list_reminders() -> dict:
    """Retrieve active reminders."""
    try:
        reminders = _load_reminders()
        active = [r for r in reminders if r.get("active", True)]
        return {"status": "success", "reminders": active, "count": len(active)}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def delete_reminder(reminder_id: str) -> dict:
    """Cancel a reminder."""
    try:
        reminders = _load_reminders()
        reminders = [r for r in reminders if r.get("id") != reminder_id and reminder_id.lower() not in r.get("text", "").lower()]
        _save_reminders(reminders)
        return {"status": "success", "action": "reminder_deleted", "id": reminder_id}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Clipboard history ──────────────────────────────────────────────────────
_CLIPBOARD_HISTORY: List[dict] = []

def _track_clipboard(text: str):
    global _CLIPBOARD_HISTORY
    if not text or not text.strip():
        return
    _CLIPBOARD_HISTORY.insert(0, {"text": text[:200], "timestamp": time.time()})
    _CLIPBOARD_HISTORY = _CLIPBOARD_HISTORY[:25]

def get_clipboard_history(limit: int = 10) -> dict:
    return {"status": "success", "history": _CLIPBOARD_HISTORY[:limit]}


# ── Habit tracker ──────────────────────────────────────────────────────────
_HABIT_LOG = os.path.join(".", "data", "habits.json")

def log_habit(habit_name: str) -> dict:
    try:
        os.makedirs(os.path.dirname(_HABIT_LOG), exist_ok=True)
        data = {}
        if os.path.exists(_HABIT_LOG):
            try:
                data = json.load(open(_HABIT_LOG, "r", encoding="utf-8"))
            except Exception:
                data = {}
        today = datetime.now().strftime("%Y-%m-%d")
        if habit_name not in data:
            data[habit_name] = []
        if today not in data[habit_name]:
            data[habit_name].append(today)
        with open(_HABIT_LOG, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return {"status": "success", "habit": habit_name, "logged_date": today, "streak": len(data[habit_name])}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def get_habit_stats(habit_name: str) -> dict:
    try:
        if not os.path.exists(_HABIT_LOG):
            return {"status": "not_found", "habit": habit_name}
        data = json.load(open(_HABIT_LOG, "r", encoding="utf-8"))
        entries = data.get(habit_name, [])
        return {"status": "success", "habit": habit_name, "total_days": len(entries), "history": entries}
    except Exception as e:
        return {"status": "error", "error": str(e)}


# ── Mood journal ───────────────────────────────────────────────────────────
_MOOD_LOG = os.path.join(".", "data", "mood_journal.json")

def save_mood_entry(mood: str, note: str = "") -> dict:
    try:
        os.makedirs(os.path.dirname(_MOOD_LOG), exist_ok=True)
        entries = []
        if os.path.exists(_MOOD_LOG):
            try:
                entries = json.load(open(_MOOD_LOG, "r", encoding="utf-8"))
            except Exception:
                entries = []
        entry = {"timestamp": datetime.now().isoformat(), "mood": mood, "note": note}
        entries.append(entry)
        with open(_MOOD_LOG, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2)
        return {"status": "success", "entry": entry}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def get_mood_journal(limit: int = 10) -> dict:
    try:
        if not os.path.exists(_MOOD_LOG):
            return {"status": "success", "entries": []}
        entries = json.load(open(_MOOD_LOG, "r", encoding="utf-8"))
        return {"status": "success", "entries": entries[-limit:]}
    except Exception as e:
        return {"status": "error", "error": str(e)}
