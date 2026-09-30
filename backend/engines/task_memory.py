"""
Task Memory — Save and retrieve task execution history for replay.
"""

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MEMORY_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "task_history")


class TaskMemory:
    """Save and retrieve task history for replay / 'do that again'."""

    def __init__(self) -> None:
        os.makedirs(MEMORY_DIR, exist_ok=True)

    def save(self, task_id: str, command: str, history: List[Dict[str, Any]]) -> None:
        """Save a completed task."""
        record = {
            "task_id": task_id,
            "command": command.strip(),
            "steps": len(history),
            "history": history[-30:],  # type: ignore[index]
            "timestamp": time.time(),
        }
        try:
            path = os.path.join(MEMORY_DIR, f"{task_id}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            logger.info(f"[TaskMemory] Saved: {path}")
        except Exception as e:
            logger.warning(f"[TaskMemory] Save error: {e}")

    def find_similar(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Fuzzy-match past tasks by command description."""
        results = []
        query_lower = query.lower().strip()
        try:
            for fname in os.listdir(MEMORY_DIR):
                if not fname.endswith(".json"):
                    continue
                path = os.path.join(MEMORY_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    record = json.load(f)
                cmd = record.get("command", "").lower()
                # Simple word overlap scoring
                q_words = set(query_lower.split())
                c_words = set(cmd.split())
                overlap = len(q_words & c_words)
                if overlap > 0:
                    results.append({"score": overlap, **record})
            results.sort(key=lambda x: x["score"], reverse=True)
            return results[:limit]  # type: ignore[index]
        except Exception as e:
            logger.warning(f"[TaskMemory] Search error: {e}")
            return []

    def get_last(self) -> Optional[Dict[str, Any]]:
        """Get the most recent task."""
        try:
            files = [f for f in os.listdir(MEMORY_DIR) if f.endswith(".json")]
            if not files:
                return None
            files.sort(key=lambda f: os.path.getmtime(os.path.join(MEMORY_DIR, f)), reverse=True)
            with open(os.path.join(MEMORY_DIR, files[0]), "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def list_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """List recent tasks."""
        try:
            files = [f for f in os.listdir(MEMORY_DIR) if f.endswith(".json")]
            files.sort(key=lambda f: os.path.getmtime(os.path.join(MEMORY_DIR, f)), reverse=True)
            tasks = []
            for fname in files[:limit]:  # type: ignore[index]
                with open(os.path.join(MEMORY_DIR, fname), "r", encoding="utf-8") as f:
                    rec = json.load(f)
                    tasks.append({"task_id": rec["task_id"], "command": rec["command"],
                                  "steps": rec["steps"], "timestamp": rec.get("timestamp", 0)})
            return tasks
        except Exception:
            return []


# Singleton
task_memory = TaskMemory()
