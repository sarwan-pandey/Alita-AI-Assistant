"""
Core Session Manager — Thread-safe session lifecycle and active WebSocket management.
"""

import time
import asyncio
import logging
import threading
from typing import Dict, Any, Optional, List, Tuple
from pydantic import BaseModel, Field  # type: ignore[import-untyped]

log = logging.getLogger("alita.session_manager")


class SessionRecord(BaseModel):
    session_id: str
    user_id: str
    tier: str              = "free"
    audio_buffer: list     = Field(default_factory=list)
    transcript_buffer: str = ""
    connected_at: float    = Field(default_factory=time.time)
    # rate-limit counters
    request_count: int     = 0
    window_start: float    = Field(default_factory=time.time)
    # voice selection (per session) — default to conversational Chatterbox Turbo engine
    voice_id: str          = "chatterbox_turbo_mj"
    # True when user manually picked a voice — prevents auto-detect override
    manual_voice_override: bool = False
    # customisable assistant name (user can rename via voice)
    custom_name: str       = "MJ"
    greeted: bool          = False
    # dictation mode (for typing into apps like notepad)
    dictation_active: bool = False
    dictation_app: str     = ""
    # ── Near-sentient personality state ────────────────────────────────────
    current_emotion: str         = "neutral"
    emotion_confidence: float    = 0.0
    environment_sounds: list     = Field(default_factory=list)
    interaction_count: int       = 0
    emergency_active: bool       = False
    # ── Song memory — persists across conversation turns ───────────────────
    last_identified_song: str    = ""
    # ── Barge-in context — remembers what Alita was saying when interrupted ────
    interrupted_response: str    = ""
    interrupted_query: str       = ""
    barge_in_count: int          = 0
    pipeline_cancel: bool        = False
    active_pipeline_id: str      = ""
    # ── Threading cancel event for instant mid-LLM abort ────────────────────
    cancel_event: Any            = Field(default=None)
    # ── Mobile automation multi-turn state ──────────────────────────────────
    pending_confirmation: Optional[Dict[str, Any]] = None
    active_task_plan: Optional[Any]                = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        if self.cancel_event is None:
            object.__setattr__(self, 'cancel_event', threading.Event())


class SessionManager:
    """Manages active sessions and websockets with thread safety."""

    def __init__(self):
        self._sessions: Dict[str, SessionRecord] = {}
        self._websockets: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def get_session(self, session_id: str) -> Optional[SessionRecord]:
        with self._lock:
            return self._sessions.get(session_id)

    def register_session(self, session_id: str, record: SessionRecord, websocket: Any):
        with self._lock:
            self._sessions[session_id] = record
            self._websockets[session_id] = websocket

    def remove_session(self, session_id: str):
        with self._lock:
            self._sessions.pop(session_id, None)
            self._websockets.pop(session_id, None)

    def cleanup_stale_user_sessions(self, user_id: str) -> List[Tuple[str, Any]]:
        """Identify and cleanly remove all existing active sessions for the user."""
        stale_list = []
        with self._lock:
            for sid, s in list(self._sessions.items()):
                if s.user_id == user_id and sid in self._websockets:
                    ws = self._websockets.pop(sid, None)
                    self._sessions.pop(sid, None)
                    stale_list.append((sid, ws))
        return stale_list

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._sessions)


# Global singleton instance
session_manager = SessionManager()
