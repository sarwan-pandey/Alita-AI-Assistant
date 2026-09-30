# pyre-ignore-all-errors
"""
User Profile — Learns user preferences over time.
Tracks: preferred apps, language, common tasks, time patterns.
Persisted to disk. 100% local, no API.
"""

import json
import logging
import os
import time
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

PROFILE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "user_profile.json")


class UserProfile:
    """Learns and stores user preferences."""

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {
            "preferred_apps": {},        # app → usage count
            "preferred_language": "en",  # en / hi / mixed
            "language_stats": {},        # language → count
            "common_tasks": {},          # task_type → count
            "time_patterns": {},         # hour → task count
            "app_pairs": {},             # "app1→app2" → count (frequent sequences)
            "custom_preferences": {},    # user-set preferences
            "total_interactions": 0,
            "created_at": time.time(),
            "last_updated": time.time(),
        }
        self._load()

    def record_app_use(self, app: str) -> None:
        """Record that user used an app."""
        app_lower = app.lower()
        apps = self._data.setdefault("preferred_apps", {})
        apps[app_lower] = apps.get(app_lower, 0) + 1
        self._data["total_interactions"] = self._data.get("total_interactions", 0) + 1

        # Record time pattern
        hour = str(time.localtime().tm_hour)
        tp = self._data.setdefault("time_patterns", {})
        tp[hour] = tp.get(hour, 0) + 1

        self._data["last_updated"] = time.time()
        self._save()

    def record_task(self, task_type: str) -> None:
        """Record a task type (open_app, compose, search_web, etc.)."""
        tasks = self._data.setdefault("common_tasks", {})
        tasks[task_type] = tasks.get(task_type, 0) + 1
        self._save()

    def record_language(self, lang: str) -> None:
        """Record detected language."""
        stats = self._data.setdefault("language_stats", {})
        stats[lang] = stats.get(lang, 0) + 1
        # Update preferred language
        if stats:
            preferred = max(stats, key=stats.get)  # type: ignore[arg-type]
            self._data["preferred_language"] = preferred
        self._save()

    def record_app_sequence(self, from_app: str, to_app: str) -> None:
        """Record an app switch sequence."""
        key = f"{from_app.lower()}→{to_app.lower()}"
        pairs = self._data.setdefault("app_pairs", {})
        pairs[key] = pairs.get(key, 0) + 1
        self._save()

    @property
    def preferred_language(self) -> str:
        return self._data.get("preferred_language", "en")

    @property
    def top_apps(self) -> List[str]:
        """Get most-used apps, sorted by usage."""
        apps = self._data.get("preferred_apps", {})
        return sorted(apps, key=apps.get, reverse=True)[:10]  # type: ignore[arg-type]

    @property
    def top_tasks(self) -> List[str]:
        """Get most common task types."""
        tasks = self._data.get("common_tasks", {})
        return sorted(tasks, key=tasks.get, reverse=True)[:10]  # type: ignore[arg-type]

    def get_frequent_sequences(self, min_count: int = 3) -> List[Dict[str, Any]]:
        """Get frequently used app sequences (for proactive suggestions)."""
        pairs = self._data.get("app_pairs", {})
        results = []
        for key, count in pairs.items():
            if count >= min_count:
                parts = key.split("→")
                if len(parts) == 2:
                    results.append({
                        "from": parts[0], "to": parts[1], "count": count
                    })
        return sorted(results, key=lambda x: -x["count"])

    def get_active_hours(self) -> List[int]:
        """Get hours when user is most active."""
        tp = self._data.get("time_patterns", {})
        if not tp:
            return list(range(9, 18))  # Default: 9 AM - 6 PM
        return sorted(tp, key=tp.get, reverse=True)[:5]  # type: ignore[arg-type]

    def get_summary(self) -> Dict[str, Any]:
        """Get profile summary."""
        return {
            "total_interactions": self._data.get("total_interactions", 0),
            "preferred_language": self.preferred_language,
            "top_apps": self.top_apps[:5],
            "top_tasks": self.top_tasks[:5],
            "active_hours": self.get_active_hours(),
            "frequent_sequences": self.get_frequent_sequences()[:3],
        }

    def get_preference(self, key: str, default: Any = None) -> Any:
        """Get a custom preference value."""
        return self._data.get("custom_preferences", {}).get(key, default)

    def set_preference(self, key: str, value: Any) -> None:
        """Set a custom preference value and persist."""
        prefs = self._data.setdefault("custom_preferences", {})
        prefs[key] = value
        self._data["last_updated"] = time.time()
        self._save()

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(PROFILE_FILE), exist_ok=True)
            with open(PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.debug(f"[UserProfile] Save failed: {e}")

    def _load(self) -> None:
        try:
            if os.path.exists(PROFILE_FILE):
                with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self._data.update(saved)
                logger.info(f"[UserProfile] Loaded ({self._data.get('total_interactions', 0)} interactions)")
        except Exception as e:
            logger.debug(f"[UserProfile] Load failed: {e}")


# Singleton
user_profile = UserProfile()
