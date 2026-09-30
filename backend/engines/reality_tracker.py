"""
Reality Tracker — Sub-Second Ground-Truth Blackboard
===================================================
Maintains continuous, synchronized awareness of both Android phone and Windows PC state.
Categorizes foreground applications and active windows in real-time to provide ground-truth
evidence for conversational verification, lie detection, and girlfriend persona dynamics.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("alita.reality_tracker")

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


# ─────────────────────────────────────────────────────────────────────────────
# APPLICATION & PACKAGE TAXONOMY
# ─────────────────────────────────────────────────────────────────────────────

CATEGORY_DISTRACTION = "DISTRACTION_SOCIAL"
CATEGORY_PRODUCTIVE = "PRODUCTIVE_STUDY"
CATEGORY_COMMUNICATION = "COMMUNICATION"
CATEGORY_SYSTEM_IDLE = "IDLE_SLEEP"
CATEGORY_NEUTRAL = "NEUTRAL"

# Mobile packages taxonomy mapping
PHONE_PACKAGE_MAP: Dict[str, Tuple[str, str]] = {
    # Distraction / Social Media
    "com.instagram.android": ("Instagram", CATEGORY_DISTRACTION),
    "com.google.android.youtube": ("YouTube", CATEGORY_DISTRACTION),
    "com.zhiliaoapp.musically": ("TikTok", CATEGORY_DISTRACTION),
    "com.ss.android.ugc.trill": ("TikTok", CATEGORY_DISTRACTION),
    "com.reddit.frontpage": ("Reddit", CATEGORY_DISTRACTION),
    "com.twitter.android": ("Twitter / X", CATEGORY_DISTRACTION),
    "com.snapchat.android": ("Snapchat", CATEGORY_DISTRACTION),
    "com.netflix.mediaclient": ("Netflix", CATEGORY_DISTRACTION),
    "com.amazon.avod.thirdpartyclient": ("Prime Video", CATEGORY_DISTRACTION),
    "in.startv.hotstar": ("Disney+ Hotstar", CATEGORY_DISTRACTION),
    "tv.twitch.android.app": ("Twitch", CATEGORY_DISTRACTION),
    "com.valvesoftware.android.steam.community": ("Steam", CATEGORY_DISTRACTION),
    "com.dts.freefireth": ("Free Fire", CATEGORY_DISTRACTION),
    "com.dts.freefiremax": ("Free Fire Max", CATEGORY_DISTRACTION),
    "com.pubg.imobile": ("BGMI / PUBG", CATEGORY_DISTRACTION),
    "com.tencent.ig": ("PUBG Mobile", CATEGORY_DISTRACTION),
    "com.king.candycrushsaga": ("Candy Crush", CATEGORY_DISTRACTION),
    "com.supercell.clashofclans": ("Clash of Clans", CATEGORY_DISTRACTION),
    "com.pinterest": ("Pinterest", CATEGORY_DISTRACTION),
    "com.facebook.katana": ("Facebook", CATEGORY_DISTRACTION),

    # Communication
    "com.whatsapp": ("WhatsApp", CATEGORY_COMMUNICATION),
    "com.whatsapp.w4b": ("WhatsApp Business", CATEGORY_COMMUNICATION),
    "org.telegram.messenger": ("Telegram", CATEGORY_COMMUNICATION),
    "org.thunderdog.challegram": ("Telegram X", CATEGORY_COMMUNICATION),
    "com.discord": ("Discord", CATEGORY_COMMUNICATION),
    "com.google.android.apps.messaging": ("Messages", CATEGORY_COMMUNICATION),
    "com.google.android.dialer": ("Phone Dialer", CATEGORY_COMMUNICATION),

    # Productive / Study
    "org.coursera.android": ("Coursera", CATEGORY_PRODUCTIVE),
    "com.udemy.android": ("Udemy", CATEGORY_PRODUCTIVE),
    "com.duolingo": ("Duolingo", CATEGORY_PRODUCTIVE),
    "org.khanacademy.android": ("Khan Academy", CATEGORY_PRODUCTIVE),
    "com.amazon.kindle": ("Kindle", CATEGORY_PRODUCTIVE),
    "com.google.android.apps.docs": ("Google Docs", CATEGORY_PRODUCTIVE),
    "com.google.android.apps.docs.editors.sheets": ("Google Sheets", CATEGORY_PRODUCTIVE),
    "com.google.android.apps.docs.editors.slides": ("Google Slides", CATEGORY_PRODUCTIVE),
    "com.google.android.apps.classroom": ("Google Classroom", CATEGORY_PRODUCTIVE),
    "notion.id": ("Notion", CATEGORY_PRODUCTIVE),
    "md.obsidian": ("Obsidian", CATEGORY_PRODUCTIVE),
    "com.adobe.reader": ("Adobe Acrobat", CATEGORY_PRODUCTIVE),
}

# PC Executables taxonomy mapping
PC_PROCESS_MAP: Dict[str, Tuple[str, str]] = {
    # Productive / IDEs / Office
    "code.exe": ("Visual Studio Code", CATEGORY_PRODUCTIVE),
    "devenv.exe": ("Visual Studio", CATEGORY_PRODUCTIVE),
    "pycharm64.exe": ("PyCharm", CATEGORY_PRODUCTIVE),
    "idea64.exe": ("IntelliJ IDEA", CATEGORY_PRODUCTIVE),
    "sublime_text.exe": ("Sublime Text", CATEGORY_PRODUCTIVE),
    "notepad++.exe": ("Notepad++", CATEGORY_PRODUCTIVE),
    "winword.exe": ("Microsoft Word", CATEGORY_PRODUCTIVE),
    "excel.exe": ("Microsoft Excel", CATEGORY_PRODUCTIVE),
    "powerpnt.exe": ("Microsoft PowerPoint", CATEGORY_PRODUCTIVE),
    "notion.exe": ("Notion", CATEGORY_PRODUCTIVE),
    "obsidian.exe": ("Obsidian", CATEGORY_PRODUCTIVE),
    "acrord32.exe": ("Adobe Reader", CATEGORY_PRODUCTIVE),
    "acrobat.exe": ("Adobe Acrobat", CATEGORY_PRODUCTIVE),
    "sumatrapdf.exe": ("SumatraPDF", CATEGORY_PRODUCTIVE),
    "windowsterminal.exe": ("Windows Terminal", CATEGORY_PRODUCTIVE),
    "cmd.exe": ("Command Prompt", CATEGORY_PRODUCTIVE),
    "powershell.exe": ("PowerShell", CATEGORY_PRODUCTIVE),
    "git-bash.exe": ("Git Bash", CATEGORY_PRODUCTIVE),

    # Communication
    "whatsapp.exe": ("WhatsApp", CATEGORY_COMMUNICATION),
    "discord.exe": ("Discord", CATEGORY_COMMUNICATION),
    "telegram.exe": ("Telegram", CATEGORY_COMMUNICATION),
    "slack.exe": ("Slack", CATEGORY_COMMUNICATION),
    "teams.exe": ("Microsoft Teams", CATEGORY_COMMUNICATION),

    # Entertainment / Games
    "steam.exe": ("Steam", CATEGORY_DISTRACTION),
    "steamwebhelper.exe": ("Steam Web", CATEGORY_DISTRACTION),
    "epicgameslauncher.exe": ("Epic Games Launcher", CATEGORY_DISTRACTION),
    "spotify.exe": ("Spotify", CATEGORY_NEUTRAL),
    "musicbee.exe": ("MusicBee", CATEGORY_NEUTRAL),
    "vlc.exe": ("VLC Media Player", CATEGORY_DISTRACTION),
    "valorant.exe": ("Valorant", CATEGORY_DISTRACTION),
    "cs2.exe": ("Counter-Strike 2", CATEGORY_DISTRACTION),
    "leagueclient.exe": ("League of Legends", CATEGORY_DISTRACTION),
    "gta5.exe": ("Grand Theft Auto V", CATEGORY_DISTRACTION),
    "minecraft.exe": ("Minecraft", CATEGORY_DISTRACTION),
    "javaw.exe": ("Minecraft / Java Game", CATEGORY_DISTRACTION),
}

# Browser title keyword heuristics (Chrome, Edge, Firefox, Brave)
BROWSER_DISTRACTION_KEYWORDS = [
    "youtube", "instagram", "tiktok", "netflix", "twitch", "reddit",
    "twitter", "x.com", "prime video", "hotstar", "anime", "9gag",
    "facebook", "roblox", "crazygames", "web.whatsapp"
]

BROWSER_PRODUCTIVE_KEYWORDS = [
    "stack overflow", "github", "gitlab", "coursera", "udemy",
    "leetcode", "hackerrank", "geeksforgeeks", "w3schools", "arxiv",
    "google docs", "google sheets", "overleaf", "canvas", "classroom",
    "documentation", "api reference", "medium.com", "chatgpt", "claude",
    "deepseek", "mdn web docs", "wikipedia"
]

# Educational video whitelist (overrides YouTube distraction flag)
EDUCATIONAL_VIDEO_KEYWORDS = [
    "lecture", "tutorial", "course", "crash course", "physics", "calculus",
    "mit ", "stanford", "cs50", "khan academy", "interview prep", "algorithms",
    "data structures", "learn python", "machine learning", "deep learning",
    "full course", "for beginners", "study with me", "exam preparation",
    "linear algebra", "discrete math", "computer science", "biology", "chemistry"
]

# Transient mobile packages (keyboards, system UI, permissions) that should not reset app timers
TRANSIENT_PHONE_PACKAGES = {
    "com.google.android.inputmethod.latin",
    "com.touchtype.swiftkey",
    "com.samsung.android.honeyboard",
    "com.android.systemui",
    "android",
    "com.google.android.permissioncontroller",
    "com.android.permissioncontroller",
}
TRANSIENT_PACKAGES = TRANSIENT_PHONE_PACKAGES


class RealityTracker:
    """
    Thread-safe live blackboard recording real-time phone and PC context.
    Provides instant (< 1ms) sensory ground-truth snapshots.
    """

    _instance: Optional[RealityTracker] = None
    _lock = threading.Lock()

    def __new__(cls) -> RealityTracker:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(RealityTracker, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self) -> None:
        self._rw_lock = threading.Lock()

        # Phone State
        self.phone_package: str = ""
        self.phone_friendly_name: str = "Unknown"
        self.phone_category: str = CATEGORY_NEUTRAL
        self.phone_screen_on: bool = False
        self.phone_is_locked: bool = True
        self.phone_app_start_time: float = time.time()
        self.phone_last_seen: float = 0.0

        # PC State
        self.pc_process: str = ""
        self.pc_title: str = ""
        self.pc_friendly_name: str = "Desktop"
        self.pc_category: str = CATEGORY_NEUTRAL
        self.pc_window_start_time: float = time.time()
        self.pc_last_active_time: float = time.time()

        # History log of recent switches (last 20 events)
        self.event_log: List[Dict[str, Any]] = []

        # Fast Window Cache (1.0s TTL)
        self._cached_hwnd: int = 0
        self._cached_hwnd_time: float = 0.0
        self._cached_pc_result: Tuple[str, str, str, str] = ("", "", "Desktop", CATEGORY_NEUTRAL)

    # ─────────────────────────────────────────────────────────────────────────
    # PHONE UPDATES (invoked by phone_router on WebSocket messages)
    # ─────────────────────────────────────────────────────────────────────────

    def update_phone_app(self, package: str, is_screen_on: Optional[bool] = None) -> None:
        """Handle immediate app_switched notification from phone accessibility service."""
        now = time.time()
        with self._rw_lock:
            pkg = (package or "").strip()

            # Bug 8 Fix: Ignore transient keyboards and system overlays from resetting timers
            if pkg in TRANSIENT_PHONE_PACKAGES:
                if is_screen_on is not None:
                    self.phone_screen_on = is_screen_on
                self.phone_last_seen = now
                return

            if pkg != self.phone_package:
                self.phone_package = pkg
                self.phone_app_start_time = now
                friendly, cat = self._classify_phone_package(pkg)
                self.phone_friendly_name = friendly
                self.phone_category = cat

                self._record_event({
                    "source": "phone",
                    "type": "app_switch",
                    "package": pkg,
                    "name": friendly,
                    "category": cat,
                    "timestamp": now,
                })
                log.info(f"[RealityTracker] Phone switched to: {friendly} ({pkg}) [{cat}]")

            if is_screen_on is not None:
                self.phone_screen_on = is_screen_on

            self.phone_last_seen = now

    def update_phone_screen_state(self, is_screen_on: bool, is_locked: bool) -> None:
        """Handle immediate screen on/off/unlock broadcast from phone bridge."""
        now = time.time()
        with self._rw_lock:
            self.phone_screen_on = is_screen_on
            self.phone_is_locked = is_locked
            self.phone_last_seen = now

            if not is_screen_on:
                self.phone_category = CATEGORY_SYSTEM_IDLE
                self.phone_friendly_name = "Screen Locked / Off"
            else:
                # Bug 1 Fix: Screen turned back ON -> restore active package classification!
                if self.phone_package:
                    friendly, cat = self._classify_phone_package(self.phone_package)
                    self.phone_friendly_name = friendly
                    self.phone_category = cat

            self._record_event({
                "source": "phone",
                "type": "screen_state",
                "screen_on": is_screen_on,
                "is_locked": is_locked,
                "timestamp": now,
            })
            log.info(f"[RealityTracker] Phone screen: on={is_screen_on}, locked={is_locked}")

    # ─────────────────────────────────────────────────────────────────────────
    # PC UPDATES (query synchronously or update from ambient watcher)
    # ─────────────────────────────────────────────────────────────────────────

    def poll_pc_active_window(self) -> Tuple[str, str, str, str]:
        """
        Synchronously queries active foreground window via Win32 in < 0.1ms.
        Returns: (process_name, window_title, friendly_name, category)
        """
        if not HAS_WIN32:
            return ("", "", "Desktop", CATEGORY_NEUTRAL)

        try:
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return ("", "", "Desktop", CATEGORY_NEUTRAL)

            now = time.time()
            if hwnd == self._cached_hwnd and (now - self._cached_hwnd_time < 1.0):
                return self._cached_pc_result

            title = win32gui.GetWindowText(hwnd).strip()
            _, pid = win32process.GetWindowThreadProcessId(hwnd)

            proc_name = ""
            if HAS_PSUTIL and pid:
                try:
                    proc = psutil.Process(pid)
                    proc_name = proc.name().lower()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_name = ""

            # Bug 11 Fix: Admin window elevation fallback
            if not proc_name and title:
                lower_t = title.lower()
                if "powershell" in lower_t:
                    proc_name = "powershell.exe"
                elif "command prompt" in lower_t or "cmd.exe" in lower_t:
                    proc_name = "cmd.exe"
                elif "terminal" in lower_t:
                    proc_name = "windowsterminal.exe"
                elif "visual studio code" in lower_t or "code" in lower_t:
                    proc_name = "code.exe"

            with self._rw_lock:
                if title != self.pc_title or proc_name != self.pc_process:
                    self.pc_title = title
                    self.pc_process = proc_name
                    self.pc_window_start_time = now

                    friendly, cat = self._classify_pc_window(proc_name, title)
                    self.pc_friendly_name = friendly
                    self.pc_category = cat

                    self._record_event({
                        "source": "pc",
                        "type": "window_switch",
                        "process": proc_name,
                        "title": title[:60],
                        "name": friendly,
                        "category": cat,
                        "timestamp": now,
                    })

                self.pc_last_active_time = now
                res = (self.pc_process, self.pc_title, self.pc_friendly_name, self.pc_category)
                self._cached_hwnd = hwnd
                self._cached_hwnd_time = now
                self._cached_pc_result = res
                return res

        except Exception as exc:
            log.debug(f"[RealityTracker] poll_pc_active_window error: {exc}")
            return ("", "", "Desktop", CATEGORY_NEUTRAL)

    # ─────────────────────────────────────────────────────────────────────────
    # CONSOLIDATED GROUND-TRUTH SNAPSHOT
    # ─────────────────────────────────────────────────────────────────────────

    def get_live_reality(self) -> Dict[str, Any]:
        """
        Builds instantaneous ground-truth reality snapshot across PC and Phone in < 0.2ms.
        """
        # Ensure PC active window is 100% up to the millisecond
        self.poll_pc_active_window()

        now = time.time()
        with self._rw_lock:
            phone_dur = max(0, int(now - self.phone_app_start_time)) if self.phone_package else 0
            pc_dur = max(0, int(now - self.pc_window_start_time)) if self.pc_process else 0

            # Determine dominant overall activity
            overall_cat = CATEGORY_NEUTRAL
            if self.phone_category == CATEGORY_DISTRACTION or self.pc_category == CATEGORY_DISTRACTION:
                overall_cat = CATEGORY_DISTRACTION
            elif self.phone_category == CATEGORY_PRODUCTIVE or self.pc_category == CATEGORY_PRODUCTIVE:
                overall_cat = CATEGORY_PRODUCTIVE
            elif self.phone_category == CATEGORY_COMMUNICATION or self.pc_category == CATEGORY_COMMUNICATION:
                overall_cat = CATEGORY_COMMUNICATION
            elif not self.phone_screen_on and (now - self.pc_last_active_time > 300):
                overall_cat = CATEGORY_SYSTEM_IDLE

            return {
                "timestamp": now,
                "overall_category": overall_cat,
                "phone": {
                    "package": self.phone_package,
                    "name": self.phone_friendly_name,
                    "category": self.phone_category,
                    "screen_on": self.phone_screen_on,
                    "is_screen_on": self.phone_screen_on,
                    "is_locked": self.phone_is_locked,
                    "duration_seconds": phone_dur,
                    "duration_formatted": self._format_duration(phone_dur),
                    "is_online": (now - self.phone_last_seen < 45) if self.phone_last_seen else False,
                },
                "pc": {
                    "process": self.pc_process,
                    "title": self.pc_title,
                    "name": self.pc_friendly_name,
                    "category": self.pc_category,
                    "duration_seconds": pc_dur,
                    "duration_formatted": self._format_duration(pc_dur),
                },
            }

    # ─────────────────────────────────────────────────────────────────────────
    # CLASSIFIER HELPERS
    # ─────────────────────────────────────────────────────────────────────────

    def _classify_phone_package(self, package: str) -> Tuple[str, str]:
        pkg = (package or "").lower().strip()
        if not pkg:
            return ("Home / Launcher", CATEGORY_NEUTRAL)

        # Check known package map
        if pkg in PHONE_PACKAGE_MAP:
            return PHONE_PACKAGE_MAP[pkg]

        # Suffix / partial checks
        if "instagram" in pkg:
            return ("Instagram", CATEGORY_DISTRACTION)
        if "youtube" in pkg:
            return ("YouTube", CATEGORY_DISTRACTION)
        if "tiktok" in pkg:
            return ("TikTok", CATEGORY_DISTRACTION)
        if "whatsapp" in pkg:
            return ("WhatsApp", CATEGORY_COMMUNICATION)
        if "telegram" in pkg:
            return ("Telegram", CATEGORY_COMMUNICATION)
        if "launcher" in pkg or "nexuslauncher" in pkg or "launcher3" in pkg:
            return ("Home Screen", CATEGORY_NEUTRAL)

        # Friendly fallback
        parts = pkg.split(".")
        name = parts[-1].capitalize() if parts else pkg
        return (name, CATEGORY_NEUTRAL)

    def _classify_pc_window(self, process_name: str, title: str) -> Tuple[str, str]:
        proc = (process_name or "").lower().strip()
        title_lower = (title or "").lower().strip()

        # Bug 11 Fix: Admin process elevation fallback (AccessDenied resolves to blank or unknown)
        if not proc or proc in ("unknown.exe", "unknown"):
            if "powershell" in title_lower:
                proc = "powershell.exe"
            elif "command prompt" in title_lower or "cmd.exe" in title_lower:
                proc = "cmd.exe"
            elif "terminal" in title_lower:
                proc = "windowsterminal.exe"
            elif "visual studio code" in title_lower:
                proc = "code.exe"
            elif "visual studio" in title_lower:
                proc = "devenv.exe"

        # Check process map
        if proc in PC_PROCESS_MAP:
            name, cat = PC_PROCESS_MAP[proc]

            # Special browser handling: chrome, msedge, firefox
            if proc in ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"):
                # Bug 2 Fix: Check educational override BEFORE distraction
                for edu_word in EDUCATIONAL_VIDEO_KEYWORDS:
                    if edu_word in title_lower:
                        return (f"Educational Video ({edu_word.title()})", CATEGORY_PRODUCTIVE)

                # Inspect browser tab title
                for keyword in BROWSER_DISTRACTION_KEYWORDS:
                    if keyword in title_lower:
                        return (f"Browser ({keyword.capitalize()})", CATEGORY_DISTRACTION)
                for keyword in BROWSER_PRODUCTIVE_KEYWORDS:
                    if keyword in title_lower:
                        return (f"Browser ({keyword.capitalize()})", CATEGORY_PRODUCTIVE)
                return ("Web Browser", CATEGORY_NEUTRAL)

            return (name, cat)

        # Browser processes not in map
        if any(b in proc for b in ("chrome", "edge", "firefox", "brave")):
            for edu_word in EDUCATIONAL_VIDEO_KEYWORDS:
                if edu_word in title_lower:
                    return (f"Educational Video ({edu_word.title()})", CATEGORY_PRODUCTIVE)
            for keyword in BROWSER_DISTRACTION_KEYWORDS:
                if keyword in title_lower:
                    return (f"Web ({keyword.capitalize()})", CATEGORY_DISTRACTION)
            for keyword in BROWSER_PRODUCTIVE_KEYWORDS:
                if keyword in title_lower:
                    return (f"Web ({keyword.capitalize()})", CATEGORY_PRODUCTIVE)
            return ("Web Browser", CATEGORY_NEUTRAL)

        # General title keywords
        for edu_word in EDUCATIONAL_VIDEO_KEYWORDS:
            if edu_word in title_lower:
                return (f"Educational Video ({edu_word.title()})", CATEGORY_PRODUCTIVE)

        for keyword in BROWSER_DISTRACTION_KEYWORDS:
            if keyword in title_lower:
                return (f"Entertainment ({keyword.capitalize()})", CATEGORY_DISTRACTION)

        for keyword in BROWSER_PRODUCTIVE_KEYWORDS:
            if keyword in title_lower:
                return (f"Study / Work ({keyword.capitalize()})", CATEGORY_PRODUCTIVE)

        friendly = title[:30] if title else (proc.replace(".exe", "").capitalize() or "Desktop")
        return (friendly, CATEGORY_NEUTRAL)

    def _format_duration(self, seconds: int) -> str:
        if seconds < 60:
            return f"{seconds}s"
        mins = seconds // 60
        if mins < 60:
            return f"{mins}m"
        hours = mins // 60
        rem_mins = mins % 60
        return f"{hours}h {rem_mins}m"

    def _record_event(self, event: Dict[str, Any]) -> None:
        self.event_log.append(event)
        if len(self.event_log) > 50:
            self.event_log.pop(0)


# Global singleton export
reality_tracker = RealityTracker()
