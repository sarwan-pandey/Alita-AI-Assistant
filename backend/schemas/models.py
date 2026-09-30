"""
Alita Pydantic Models & Request/Response Schemas
================================================
Central data contracts for WebSocket frames, API request bodies,
and session state containers across the Alita assistant platform.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AudioChunk(BaseModel):
    type: str = "audio_chunk"
    session_id: str
    sequence: int
    pcm_float32: List[float]


class TextMessage(BaseModel):
    type: str = "text_message"
    session_id: str
    text: str


class LLMReply(BaseModel):
    type: str = "llm_token"
    session_id: str
    token: str
    is_final: bool = False


class EmotionUpdate(BaseModel):
    type: str = "emotion_update"
    session_id: str
    label: str
    confidence: float


class TTSAudioFrame(BaseModel):
    type: str = "tts_audio"
    session_id: str
    audio_b64: str
    is_final: bool = False


class SessionRecord(BaseModel):
    session_id: str
    user_id: str
    tier: str = "free"
    audio_buffer: list = Field(default_factory=list)
    transcript_buffer: str = ""
    connected_at: float = Field(default_factory=time.time)
    # rate-limit counters
    request_count: int = 0
    window_start: float = Field(default_factory=time.time)
    # voice selection (per session) — defaults to Chatterbox Turbo engine
    voice_id: str = "chatterbox_turbo_mj"
    # True when user manually picked a voice — prevents auto-detect override
    manual_voice_override: bool = False
    # customisable assistant name (user can rename via voice)
    custom_name: str = "MJ"
    greeted: bool = False
    # dictation mode (for typing into apps like notepad)
    dictation_active: bool = False
    dictation_app: str = ""
    # ── Near-sentient personality state ────────────────────────────────────
    current_emotion: str = "neutral"
    emotion_confidence: float = 0.0
    environment_sounds: list = Field(default_factory=list)
    interaction_count: int = 0
    emergency_active: bool = False
    # ── Song memory — persists across conversation turns ───────────────────
    last_identified_song: str = ""
    # ── Barge-in context — remembers what Alita was saying when interrupted ────
    interrupted_response: str = ""
    interrupted_query: str = ""
    barge_in_count: int = 0
    pipeline_cancel: bool = False
    active_pipeline_id: str = ""
    # ── Threading cancel event for instant mid-LLM abort ────────────────────
    cancel_event: Any = Field(default=None)
    # ── Mobile automation multi-turn state ──────────────────────────────────
    pending_confirmation: Optional[Dict[str, Any]] = None
    active_task_plan: Optional[Any] = None

    class Config:
        arbitrary_types_allowed = True

    def __init__(self, **data):
        super().__init__(**data)
        import threading
        if self.cancel_event is None:
            object.__setattr__(self, "cancel_event", threading.Event())


class CheckoutRequest(BaseModel):
    plan: str = "monthly"  # "monthly" | "annual"
