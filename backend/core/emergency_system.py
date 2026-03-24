"""
Emergency Response System — Auto-record when danger sounds detected.

Manages:
  - Emergency recording storage (video/audio files)
  - Recording metadata (timestamp, detected sound, duration)
  - Admin API for viewing/downloading emergency recordings
  - Cleanup of old recordings
"""

import os
import json
import time
import logging
import uuid
from datetime import datetime
from typing import Optional

log = logging.getLogger("alita.emergency")

# Storage directory for emergency recordings
EMERGENCY_DIR = os.path.join(".", "data", "emergency")
EMERGENCY_META_FILE = os.path.join(EMERGENCY_DIR, "recordings.json")


def _ensure_dir():
    os.makedirs(EMERGENCY_DIR, exist_ok=True)


def start_recording(user_id: str, trigger_sound: str, confidence: float,
                    level: str = "critical") -> dict:
    """
    Register a new emergency recording.
    Returns recording metadata dict with file path for saving chunks.
    """
    _ensure_dir()
    recording_id = str(uuid.uuid4())[:12]  # type: ignore[index]
    timestamp = datetime.now().isoformat()
    filename = f"emergency_{recording_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    meta = {
        "id": recording_id,
        "user_id": user_id,
        "trigger_sound": trigger_sound,
        "trigger_confidence": round(confidence, 2),  # type: ignore[call-overload]
        "level": level,
        "timestamp": timestamp,
        "video_path": os.path.join(EMERGENCY_DIR, f"{filename}.webm"),
        "audio_path": os.path.join(EMERGENCY_DIR, f"{filename}.wav"),
        "status": "recording",
        "duration_seconds": 0,
        "file_size_kb": 0,
    }

    # Save metadata
    recordings = _load_all_recordings()
    recordings.append(meta)
    _save_all_recordings(recordings)

    log.critical(
        "🚨 EMERGENCY RECORDING STARTED: id=%s trigger=%s (%.0f%%) user=%s",
        recording_id, trigger_sound, confidence * 100, user_id
    )
    return meta


def save_recording_chunk(recording_id: str, chunk_data: bytes, is_video: bool = True):
    """Append a recording chunk to the file."""
    recordings = _load_all_recordings()
    recording = next((r for r in recordings if r["id"] == recording_id), None)
    if not recording:
        log.warning("Recording not found: %s", recording_id)
        return

    filepath = recording["video_path"] if is_video else recording["audio_path"]
    try:
        with open(filepath, "ab") as f:
            f.write(chunk_data)
    except Exception as e:
        log.error("Failed to write recording chunk: %s", e)


def stop_recording(recording_id: str) -> Optional[dict]:
    """Mark a recording as complete."""
    recordings = _load_all_recordings()
    recording = None
    for r in recordings:
        if r["id"] == recording_id:
            recording = r
            break

    if not recording:
        return None

    recording["status"] = "completed"  # type: ignore[index]

    # Calculate file size
    for path_key in ("video_path", "audio_path"):
        filepath = recording.get(path_key, "")  # type: ignore[union-attr]
        if filepath and os.path.exists(filepath):
            size_kb = os.path.getsize(filepath) / 1024
            recording["file_size_kb"] = round(size_kb, 1)  # type: ignore[call-overload,index]
            break

    # Calculate duration from start timestamp
    try:
        start = datetime.fromisoformat(recording["timestamp"])  # type: ignore[arg-type]
        recording["duration_seconds"] = round(  # type: ignore[call-overload,index]
            (datetime.now() - start).total_seconds(), 1
        )
    except Exception:
        pass

    _save_all_recordings(recordings)
    log.info(
        "Emergency recording completed: id=%s duration=%.1fs size=%.1fKB",
        recording_id, recording["duration_seconds"], recording["file_size_kb"]  # type: ignore[index]
    )
    return recording


def list_recordings(user_id: Optional[str] = None, limit: int = 50) -> list[dict]:
    """List emergency recordings, optionally filtered by user."""
    recordings = _load_all_recordings()
    if user_id:
        recordings = [r for r in recordings if r.get("user_id") == user_id]
    # Sort by timestamp descending (newest first)
    recordings.sort(key=lambda r: r.get("timestamp", ""), reverse=True)
    return recordings[:limit]  # type: ignore[index]


def get_recording(recording_id: str) -> Optional[dict]:
    """Get a specific recording's metadata."""
    recordings = _load_all_recordings()
    return next((r for r in recordings if r["id"] == recording_id), None)


def delete_recording(recording_id: str) -> bool:
    """Delete a recording and its files."""
    recordings = _load_all_recordings()
    recording = next((r for r in recordings if r["id"] == recording_id), None)
    if not recording:
        return False

    # Delete files
    for path_key in ("video_path", "audio_path"):
        filepath = recording.get(path_key, "")
        if filepath and os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception as e:
                log.warning("Failed to delete %s: %s", filepath, e)

    # Remove from metadata
    recordings = [r for r in recordings if r["id"] != recording_id]
    _save_all_recordings(recordings)
    log.info("Emergency recording deleted: %s", recording_id)
    return True


# ── Internal helpers ──────────────────────────────────────────────────────────

def _load_all_recordings() -> list[dict]:
    _ensure_dir()
    if not os.path.exists(EMERGENCY_META_FILE):
        return []
    try:
        with open(EMERGENCY_META_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_all_recordings(recordings: list[dict]):
    _ensure_dir()
    try:
        with open(EMERGENCY_META_FILE, "w", encoding="utf-8") as f:
            json.dump(recordings, f, indent=2, ensure_ascii=False)
    except Exception as e:
        log.error("Failed to save emergency metadata: %s", e)
