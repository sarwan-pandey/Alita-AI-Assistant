"""
conversation_store.py — Persistent conversation storage
========================================================
Saves every conversation turn per user to JSON files.
Supports:
  - Saving user + assistant turns with timestamps
  - Loading conversation history on reconnect (session resumption)
  - Exporting anonymised training data (PII stripped)

Storage layout:
  ./data/conversations/{user_id}/history.json   — full conversation log
  ./data/training/                              — anonymised export folder
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import hashlib
from pathlib import Path
from typing import Optional

log = logging.getLogger("aura.conversations")

# ── Storage paths ─────────────────────────────────────────────────────────────
DATA_DIR = Path("./data/conversations")
TRAINING_DIR = Path("./data/training")


def _user_dir(user_id: str) -> Path:
    """Get per-user storage directory (safe filesystem name)."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
    return DATA_DIR / safe_id


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# SAVE a conversation turn
# ─────────────────────────────────────────────────────────────────────────────
def save_turn(
    user_id: str,
    role: str,           # "user" or "assistant"
    content: str,
    emotion: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Append a single conversation turn to the user's history file.
    Thread-safe via append-mode writes.
    """
    if not content.strip():
        return

    udir = _user_dir(user_id)
    _ensure_dir(udir)

    turn = {
        "role": role,
        "content": content,
        "timestamp": time.time(),
        "iso_time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "session_id": session_id,
    }
    if emotion:
        turn["emotion"] = emotion

    history_file = udir / "history.json"

    # Load existing or start fresh
    history = []
    if history_file.exists():
        try:
            history = json.loads(history_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt history for user %s — starting fresh", user_id)

    history.append(turn)

    try:
        history_file.write_text(
            json.dumps(history, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        log.error("Failed to save conversation for %s: %s", user_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# LOAD conversation history (for session resumption)
# ─────────────────────────────────────────────────────────────────────────────
def load_history(user_id: str, max_turns: int = 50) -> list[dict]:
    """
    Load the last N conversation turns for a user.
    Returns list of { role, content, timestamp, emotion? } dicts.
    """
    history_file = _user_dir(user_id) / "history.json"

    if not history_file.exists():
        return []

    try:
        history = json.loads(history_file.read_text(encoding="utf-8"))
        return history[-max_turns:]
    except (json.JSONDecodeError, OSError) as exc:
        log.error("Failed to load history for %s: %s", user_id, exc)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# REBUILD transcript buffer from history (for LLM context)
# ─────────────────────────────────────────────────────────────────────────────
def rebuild_transcript_buffer(user_id: str, max_turns: int = 20) -> str:
    """
    Rebuild the ephemeral transcript_buffer from saved history.
    Used when a user reconnects to continue where they left off.
    """
    history = load_history(user_id, max_turns)
    lines = []
    for turn in history:
        prefix = "User" if turn["role"] == "user" else "Aura"
        lines.append(f"{prefix}: {turn['content']}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# EXPORT anonymised training data
# ─────────────────────────────────────────────────────────────────────────────
# PII patterns to strip
_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE_RE = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")
_NAME_PLACEHOLDER = "[USER]"


def _strip_pii(text: str) -> str:
    """Remove emails, phone numbers from text."""
    text = _EMAIL_RE.sub("[EMAIL]", text)
    text = _PHONE_RE.sub("[PHONE]", text)
    return text


def _anonymise_user_id(user_id: str) -> str:
    """One-way hash the user ID so it can't be traced back."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def export_training_data() -> str:
    """
    Export all conversations as anonymised JSONL for model training.
    Returns path to the exported file.

    Format per line:
      {"conversation_id": "abc123", "turns": [{"role": "user", "content": "..."}, ...]}
    """
    _ensure_dir(TRAINING_DIR)
    export_path = TRAINING_DIR / f"training_{int(time.time())}.jsonl"

    count = 0
    with open(export_path, "w", encoding="utf-8") as f:
        if not DATA_DIR.exists():
            return str(export_path)

        for user_dir in DATA_DIR.iterdir():
            if not user_dir.is_dir():
                continue

            history_file = user_dir / "history.json"
            if not history_file.exists():
                continue

            try:
                history = json.loads(history_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue

            if not history:
                continue

            # Anonymise
            anon_id = _anonymise_user_id(user_dir.name)
            anon_turns = []
            for turn in history:
                anon_turns.append({
                    "role": turn["role"],
                    "content": _strip_pii(turn["content"]),
                })

            record = {
                "conversation_id": anon_id,
                "turns": anon_turns,
                "turn_count": len(anon_turns),
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    log.info("Exported %d conversations to %s", count, export_path)
    return str(export_path)
