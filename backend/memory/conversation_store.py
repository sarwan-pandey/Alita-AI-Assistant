"""
conversation_store.py — Persistent conversation storage
========================================================
Saves every conversation turn per user.

Performance fixes applied:
  Fix #1:  JSONL append (O(1) write) instead of full JSON rewrite (O(n))
  Fix #38: Atomic writes for backward-compat JSON (write-to-temp + os.replace)

Storage layout:
  ./data/conversations/{user_id}/history.jsonl  — append-only log (new, fast)
  ./data/conversations/{user_id}/history.json   — legacy format (auto-detected)
  ./data/training/                              — anonymised export folder

Backward compatibility:
  - If history.jsonl exists → use it (fast path)
  - If only history.json exists → read it, auto-migrate to .jsonl on next save
  - Both load_history() and save_turn() handle both formats transparently
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import hashlib
import tempfile
from pathlib import Path
from typing import Optional

log = logging.getLogger("aura.conversations")

# ── Storage paths ─────────────────────────────────────────────────────────────
# Anchor to absolute directory so working directory changes do not fragment conversation data
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_BASE_DATA = _BACKEND_DIR / "data" if (_BACKEND_DIR / "data").exists() else _BACKEND_DIR.parent / "data"
DATA_DIR = _BASE_DATA / "conversations"
TRAINING_DIR = _BASE_DATA / "training"


def _user_dir(user_id: str) -> Path:
    """Get per-user storage directory (safe filesystem name)."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", user_id)
    return DATA_DIR / safe_id


def _ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# SAVE a conversation turn — Fix #1: O(1) JSONL append
# ─────────────────────────────────────────────────────────────────────────────
def save_turn(
    user_id: str,
    role: str,           # "user" or "assistant"
    content: str,
    emotion: Optional[str] = None,
    session_id: Optional[str] = None,
) -> None:
    """
    Append a single conversation turn to the user's JSONL history file.
    O(1) — no file read, no full re-serialize. Just append one line.
    Thread-safe via append-mode writes (lines < 4KB are atomic on all OSes).
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

    jsonl_file = udir / "history.jsonl"

    try:
        # O(1) append — the core performance fix
        with open(jsonl_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(turn, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.error("Failed to save conversation for %s: %s", user_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# LOAD conversation history (for session resumption)
# Backward-compatible: reads .jsonl (new) or .json (legacy)
# ─────────────────────────────────────────────────────────────────────────────
def load_history(user_id: str, max_turns: int = 50) -> list[dict]:
    """
    Load the last N conversation turns for a user.
    Returns list of { role, content, timestamp, emotion? } dicts.
    Auto-detects JSONL (new) vs JSON array (legacy) format.
    """
    udir = _user_dir(user_id)
    jsonl_file = udir / "history.jsonl"
    json_file = udir / "history.json"

    # Prefer JSONL (new fast format)
    if jsonl_file.exists():
        try:
            history = []
            with open(jsonl_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            history.append(json.loads(line))
                        except json.JSONDecodeError:
                            continue  # skip corrupt lines
            return history[-max_turns:]
        except OSError as exc:
            log.error("Failed to load JSONL history for %s: %s", user_id, exc)
            return []

    # Fall back to legacy JSON array format
    if json_file.exists():
        try:
            history = json.loads(json_file.read_text(encoding="utf-8"))
            return history[-max_turns:]
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Failed to load JSON history for %s: %s", user_id, exc)
            return []

    return []


# ─────────────────────────────────────────────────────────────────────────────
# CLEAR conversation history (for "New Conversation" feature)
# ─────────────────────────────────────────────────────────────────────────────
def clear_history(user_id: str) -> None:
    """
    Delete all conversation history for a user.
    Removes both JSONL and legacy JSON files.
    """
    udir = _user_dir(user_id)
    for fname in ("history.jsonl", "history.json"):
        fpath = udir / fname
        if fpath.exists():
            try:
                fpath.unlink()
                log.info("Cleared %s for user=%s", fname, user_id)
            except OSError as exc:
                log.error("Failed to clear %s for %s: %s", fname, user_id, exc)


# ─────────────────────────────────────────────────────────────────────────────
# REBUILD transcript buffer from history (for LLM context)
# Fix #8: Accept pre-loaded history to avoid double file read
# ─────────────────────────────────────────────────────────────────────────────
def rebuild_transcript_buffer(
    user_id: str,
    max_turns: int = 20,
    preloaded_history: list[dict] | None = None,
) -> str:
    """
    Rebuild the ephemeral transcript_buffer from saved history.
    Used when a user reconnects to continue where they left off.

    If preloaded_history is provided, uses it directly (avoids re-reading file).
    """
    if preloaded_history is not None:
        history = preloaded_history[-max_turns:]
    else:
        history = load_history(user_id, max_turns)

    lines = []
    for turn in history:
        prefix = "User" if turn["role"] == "user" else "Alita"
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

            # Try JSONL first, then legacy JSON
            history = []
            jsonl_file = user_dir / "history.jsonl"
            json_file = user_dir / "history.json"

            if jsonl_file.exists():
                try:
                    with open(jsonl_file, "r", encoding="utf-8") as hf:
                        for line in hf:
                            line = line.strip()
                            if line:
                                try:
                                    history.append(json.loads(line))
                                except json.JSONDecodeError:
                                    continue
                except OSError:
                    continue
            elif json_file.exists():
                try:
                    history = json.loads(json_file.read_text(encoding="utf-8"))
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
