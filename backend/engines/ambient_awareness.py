"""
Ambient Awareness Engine — Always-On Contextual Intelligence
=============================================================
Maintains continuous, rolling awareness of the user's activity across phone and PC.
Provides natural-language summaries for LLM prompt injection so Alita always knows
what the user is doing, has been doing, and how long they've been doing it — without
the user needing to make any claim.

This is the sensory backbone for the Girlfriend Persona's omniscient awareness.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("alita.ambient_awareness")

try:
    from engines.reality_tracker import reality_tracker
except ImportError:
    from backend.engines.reality_tracker import reality_tracker


# ─────────────────────────────────────────────────────────────────────────────
# ACTIVITY SNAPSHOT — individual point-in-time state capture
# ─────────────────────────────────────────────────────────────────────────────

class ActivitySnapshot:
    """A single point-in-time snapshot of user activity across all devices."""

    __slots__ = (
        "timestamp", "phone_app", "phone_category", "phone_screen_on",
        "phone_package", "pc_app", "pc_category", "pc_title",
    )

    def __init__(
        self,
        timestamp: float,
        phone_app: str,
        phone_category: str,
        phone_screen_on: bool,
        phone_package: str,
        pc_app: str,
        pc_category: str,
        pc_title: str,
    ):
        self.timestamp = timestamp
        self.phone_app = phone_app
        self.phone_category = phone_category
        self.phone_screen_on = phone_screen_on
        self.phone_package = phone_package
        self.pc_app = pc_app
        self.pc_category = pc_category
        self.pc_title = pc_title


# ─────────────────────────────────────────────────────────────────────────────
# APP TRANSITION — records when the user switched between apps
# ─────────────────────────────────────────────────────────────────────────────

class AppTransition:
    """Records a single app switch event."""

    __slots__ = ("timestamp", "source", "from_app", "to_app", "from_category", "to_category", "duration_on_prev")

    def __init__(
        self,
        timestamp: float,
        source: str,       # "phone" or "pc"
        from_app: str,
        to_app: str,
        from_category: str,
        to_category: str,
        duration_on_prev: int,
    ):
        self.timestamp = timestamp
        self.source = source
        self.from_app = from_app
        self.to_app = to_app
        self.from_category = from_category
        self.to_category = to_category
        self.duration_on_prev = duration_on_prev


# ─────────────────────────────────────────────────────────────────────────────
# AMBIENT AWARENESS ENGINE
# ─────────────────────────────────────────────────────────────────────────────

class AmbientAwareness:
    """
    Always-on contextual awareness engine for the Girlfriend Persona.

    Maintains:
      1. Rolling activity log (last 100 snapshots, ~15s intervals)
      2. App transition history (last 50 switches)
      3. Daily usage aggregates per app (total seconds)
      4. Notification digest (recent phone notifications)
      5. Natural-language awareness summary for LLM prompt injection
    """

    _instance: Optional[AmbientAwareness] = None
    _lock = threading.Lock()

    def __new__(cls) -> AmbientAwareness:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(AmbientAwareness, cls).__new__(cls)
                cls._instance._init_state()
            return cls._instance

    def _init_state(self) -> None:
        self._rw_lock = threading.Lock()

        # Rolling activity snapshots (point-in-time captures)
        self.activity_log: deque[ActivitySnapshot] = deque(maxlen=100)

        # App transition events
        self.transitions: deque[AppTransition] = deque(maxlen=50)

        # Daily usage tracking: {app_friendly_name: total_seconds_today}
        self.daily_usage: Dict[str, float] = {}
        self.daily_usage_date: str = self._today_str()

        # Per-category daily totals: {category: total_seconds}
        self.daily_category_totals: Dict[str, float] = {}

        # Last known state for detecting transitions
        self._last_phone_app: str = ""
        self._last_phone_app_cat: str = "NEUTRAL"
        self._last_pc_app: str = ""
        self._last_pc_app_cat: str = "NEUTRAL"
        self._last_phone_start: float = time.time()
        self._last_pc_start: float = time.time()

        # Notification buffer
        self.notification_buffer: deque[Dict[str, Any]] = deque(maxlen=30)

        # Background poller
        self._running = False
        self._poll_thread: Optional[threading.Thread] = None

    @staticmethod
    def _today_str() -> str:
        return str((datetime.now() - timedelta(hours=4)).date())

    # ─────────────────────────────────────────────────────────────────────────
    # BACKGROUND POLLER — captures snapshots every ~12 seconds
    # ─────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the ambient awareness background polling daemon."""
        if self._running:
            return
        self._running = True
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True, name="AmbientAwarenessDaemon"
        )
        self._poll_thread.start()
        log.info("[AmbientAwareness] Background awareness daemon started")

    def stop(self) -> None:
        self._running = False

    def _poll_loop(self) -> None:
        """Main polling loop — captures reality snapshots every ~12 seconds."""
        while self._running:
            try:
                self._capture_snapshot()
            except Exception as exc:
                log.debug(f"[AmbientAwareness] Poll error: {exc}")
            time.sleep(12)

    def _capture_snapshot(self) -> None:
        """Capture current reality state and record it."""
        reality = reality_tracker.get_live_reality()
        now = time.time()

        phone = reality.get("phone", {})
        pc = reality.get("pc", {})

        phone_app = phone.get("name", "Unknown")
        phone_cat = phone.get("category", "NEUTRAL")
        phone_screen = phone.get("screen_on", False)
        phone_pkg = phone.get("package", "")
        pc_app = pc.get("name", "Desktop")
        pc_cat = pc.get("category", "NEUTRAL")
        pc_title = pc.get("title", "")

        snap = ActivitySnapshot(
            timestamp=now,
            phone_app=phone_app,
            phone_category=phone_cat,
            phone_screen_on=phone_screen,
            phone_package=phone_pkg,
            pc_app=pc_app,
            pc_category=pc_cat,
            pc_title=pc_title,
        )

        with self._rw_lock:
            self.activity_log.append(snap)

            # ── Detect app transitions ──
            if phone_app != self._last_phone_app and self._last_phone_app:
                dur = max(0, int(now - self._last_phone_start))
                self.transitions.append(AppTransition(
                    timestamp=now, source="phone",
                    from_app=self._last_phone_app, to_app=phone_app,
                    from_category=self._last_phone_app_cat if hasattr(self, '_last_phone_app_cat') else "NEUTRAL",
                    to_category=phone_cat,
                    duration_on_prev=dur,
                ))
                # Update daily usage for the app we just left
                self._accrue_usage(self._last_phone_app, dur,
                                   getattr(self, '_last_phone_app_cat', "NEUTRAL"))
                self._last_phone_start = now

            self._last_phone_app = phone_app
            self._last_phone_app_cat = phone_cat

            if pc_app != self._last_pc_app and self._last_pc_app:
                dur = max(0, int(now - self._last_pc_start))
                self.transitions.append(AppTransition(
                    timestamp=now, source="pc",
                    from_app=self._last_pc_app, to_app=pc_app,
                    from_category=getattr(self, '_last_pc_app_cat', "NEUTRAL"),
                    to_category=pc_cat,
                    duration_on_prev=dur,
                ))
                self._accrue_usage(self._last_pc_app, dur,
                                   getattr(self, '_last_pc_app_cat', "NEUTRAL"))
                self._last_pc_start = now

            self._last_pc_app = pc_app
            self._last_pc_app_cat = pc_cat

            # Reset daily counters on circadian date rollover
            today = self._today_str()
            if today != self.daily_usage_date:
                self.daily_usage.clear()
                self.daily_category_totals.clear()
                self.daily_usage_date = today

    def _accrue_usage(self, app_name: str, seconds: int, category: str) -> None:
        """Add usage time to daily aggregates (must be called under _rw_lock)."""
        if seconds <= 0 or not app_name:
            return
        self.daily_usage[app_name] = self.daily_usage.get(app_name, 0) + seconds
        self.daily_category_totals[category] = self.daily_category_totals.get(category, 0) + seconds

    # ─────────────────────────────────────────────────────────────────────────
    # NOTIFICATION TRACKING
    # ─────────────────────────────────────────────────────────────────────────

    def record_notification(self, app: str, title: str, text: str, timestamp: float = 0) -> None:
        """Record a phone notification for awareness digest."""
        with self._rw_lock:
            self.notification_buffer.append({
                "app": app,
                "title": title,
                "text": text[:100],  # truncate for privacy
                "timestamp": timestamp or time.time(),
            })

    # ─────────────────────────────────────────────────────────────────────────
    # PUBLIC API — Natural Language Summaries
    # ─────────────────────────────────────────────────────────────────────────

    def get_awareness_summary(self) -> str:
        """
        Build a concise one-liner for LLM prompt injection.
        Describes what the user is doing RIGHT NOW across phone + PC.

        Example: "Sarwan is currently on Instagram (phone, 12 min). PC has VS Code open.
                  Phone screen is on. Today: 2h productive, 45m distraction."
        """
        reality = reality_tracker.get_live_reality()
        phone = reality.get("phone", {})
        pc = reality.get("pc", {})

        parts = []

        # Phone current state
        if phone.get("screen_on") or phone.get("is_screen_on"):
            app = phone.get("name", "Unknown")
            dur = phone.get("duration_formatted", "")
            cat = phone.get("category", "NEUTRAL")
            cat_label = self._category_label(cat)
            parts.append(f"Phone: {app} ({cat_label}, {dur})")
        else:
            parts.append("Phone: screen off/locked")

        # PC current state
        pc_name = pc.get("name", "Desktop")
        pc_dur = pc.get("duration_formatted", "")
        pc_title_short = (pc.get("title", "") or "")[:40]
        if pc_name and pc_name != "Desktop":
            parts.append(f"PC: {pc_name} ({pc_dur})")
        else:
            parts.append("PC: Desktop/idle")

        # Daily category summary
        with self._rw_lock:
            cat_summary = self._format_daily_categories()
        if cat_summary:
            parts.append(f"Today: {cat_summary}")

        # Time of day context
        hour = datetime.now().hour
        if hour >= 1 and hour < 5:
            parts.append("⚠ It's very late at night!")
        elif hour >= 23:
            parts.append("It's late evening")

        return " | ".join(parts)

    def get_activity_journal(self, minutes: int = 30) -> str:
        """
        Natural language summary of what the user has been doing for the last N minutes.
        Used when Alita wants to casually reference recent activity.
        """
        cutoff = time.time() - (minutes * 60)

        with self._rw_lock:
            recent_transitions = [
                t for t in self.transitions if t.timestamp >= cutoff
            ]

        if not recent_transitions:
            # Fall back to current state
            return f"No major app switches in the last {minutes} minutes."

        lines = []
        for t in recent_transitions[-8:]:  # last 8 transitions max
            ts = datetime.fromtimestamp(t.timestamp).strftime("%I:%M %p")
            dur_str = self._format_seconds(t.duration_on_prev)
            lines.append(
                f"• {ts}: {t.source.title()} switched from {t.from_app} ({dur_str}) → {t.to_app}"
            )

        return "Recent activity:\n" + "\n".join(lines)

    def get_daily_usage_stats(self) -> Dict[str, Any]:
        """
        Returns daily usage breakdown by app and category.
        Used by lie detector and proactive agent for evidence.
        """
        # Accrue current session time for active apps
        now = time.time()
        with self._rw_lock:
            # Copy current totals
            usage = dict(self.daily_usage)
            categories = dict(self.daily_category_totals)

            # Add currently running app durations (not yet accrued)
            if self._last_phone_app:
                ongoing_phone = max(0, int(now - self._last_phone_start))
                usage[self._last_phone_app] = usage.get(self._last_phone_app, 0) + ongoing_phone
                cat = getattr(self, '_last_phone_app_cat', "NEUTRAL")
                categories[cat] = categories.get(cat, 0) + ongoing_phone

            if self._last_pc_app:
                ongoing_pc = max(0, int(now - self._last_pc_start))
                usage[self._last_pc_app] = usage.get(self._last_pc_app, 0) + ongoing_pc
                cat = getattr(self, '_last_pc_app_cat', "NEUTRAL")
                categories[cat] = categories.get(cat, 0) + ongoing_pc

        # Sort by usage descending
        sorted_apps = sorted(usage.items(), key=lambda x: x[1], reverse=True)

        return {
            "by_app": {app: self._format_seconds(secs) for app, secs in sorted_apps[:15]},
            "by_app_raw": {app: int(secs) for app, secs in sorted_apps[:15]},
            "by_category": {cat: self._format_seconds(secs) for cat, secs in categories.items()},
            "by_category_raw": {cat: int(secs) for cat, secs in categories.items()},
            "date": self.daily_usage_date,
        }

    def get_notification_digest(self) -> str:
        """
        Returns a natural language summary of recent phone notifications.
        Limited to last 5 notifications for conciseness.
        """
        with self._rw_lock:
            recent = list(self.notification_buffer)[-5:]

        if not recent:
            return ""

        lines = []
        for n in recent:
            ts = datetime.fromtimestamp(n["timestamp"]).strftime("%I:%M %p")
            lines.append(f"• {n['app']}: {n['title']} — {n['text']} ({ts})")

        return "Recent notifications:\n" + "\n".join(lines)

    def get_app_usage_today(self, app_name: str) -> int:
        """Get total seconds spent on a specific app today. Used by lie detector."""
        stats = self.get_daily_usage_stats()
        return stats.get("by_app_raw", {}).get(app_name, 0)

    def get_category_usage_today(self, category: str) -> int:
        """Get total seconds in a category today. Used by proactive agent."""
        stats = self.get_daily_usage_stats()
        return stats.get("by_category_raw", {}).get(category, 0)

    def get_last_transition(self, source: str = "phone") -> Optional[AppTransition]:
        """Get the most recent app transition for a given source."""
        with self._rw_lock:
            for t in reversed(self.transitions):
                if t.source == source:
                    return t
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # FORMATTERS
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _format_seconds(seconds: float) -> str:
        s = int(seconds)
        if s < 60:
            return f"{s}s"
        m = s // 60
        if m < 60:
            return f"{m}m"
        h = m // 60
        rm = m % 60
        return f"{h}h {rm}m"

    def _format_daily_categories(self) -> str:
        """Format daily category totals as a compact string (called under _rw_lock)."""
        now = time.time()
        cats = dict(self.daily_category_totals)

        # Add ongoing durations
        if self._last_phone_app:
            cat = getattr(self, '_last_phone_app_cat', "NEUTRAL")
            cats[cat] = cats.get(cat, 0) + max(0, now - self._last_phone_start)
        if self._last_pc_app:
            cat = getattr(self, '_last_pc_app_cat', "NEUTRAL")
            cats[cat] = cats.get(cat, 0) + max(0, now - self._last_pc_start)

        parts = []
        label_map = {
            "PRODUCTIVE_STUDY": "productive",
            "DISTRACTION_SOCIAL": "distraction",
            "COMMUNICATION": "chatting",
            "IDLE_SLEEP": "idle",
            "NEUTRAL": "other",
        }
        # Only show significant categories (> 1 minute)
        for cat, secs in sorted(cats.items(), key=lambda x: x[1], reverse=True):
            if secs >= 60:
                label = label_map.get(cat, cat.lower())
                parts.append(f"{self._format_seconds(secs)} {label}")

        return ", ".join(parts[:4])

    @staticmethod
    def _category_label(category: str) -> str:
        labels = {
            "PRODUCTIVE_STUDY": "productive",
            "DISTRACTION_SOCIAL": "distraction",
            "COMMUNICATION": "chatting",
            "IDLE_SLEEP": "idle",
            "NEUTRAL": "neutral",
        }
        return labels.get(category, "unknown")


# Global singleton export
ambient_awareness = AmbientAwareness()
