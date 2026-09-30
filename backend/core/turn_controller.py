"""
Active Turn Controller for Aura / MJ Assistant
==============================================
Provides centralized per-session active turn management, cooperative
cancellation propagation, duplicate STT gating, and stale result protection.

Invariants:
- Monotonically increasing turn_id / request_id sequence.
- Exactly one active turn per session at any point in time.
- Cooperative cancellation via threading.Event (never forcibly aborts running
  PyTorch/C++ inference in the threadpool).
- Synchronous model calls are allowed to return naturally; results are checked
  immediately after return and discarded if stale.
- Duplicate STT transcripts within 500-750ms are discarded before creating a turn.
- Exact raw user text is preserved with zero alteration.
"""

import time
import re
import logging
import threading
from typing import Optional, Dict, Any, Tuple, List

log = logging.getLogger("alita.turn")

# Pattern for conservative normalization for duplicate detection only
_RE_PUNCT_TAIL = re.compile(r'[\.\?\!\,\;\:\s]+$')
_RE_MULTI_SPACE = re.compile(r'\s+')


def normalize_for_duplicate_check(text: str) -> str:
    """
    Conservative normalization used STRICTLY for duplicate detection.
    Does NOT modify the text passed to the LLM or TTS engines.
    """
    if not text:
        return ""
    t = text.strip().lower()
    t = _RE_PUNCT_TAIL.sub('', t)
    t = _RE_MULTI_SPACE.sub(' ', t)
    return t


class TurnRecord:
    """Represents a single user turn lifecycle."""

    def __init__(self, turn_id: int, request_id: int, session_id: str, transcript: str):
        self.turn_id: int = turn_id
        self.request_id: int = request_id
        self.session_id: str = session_id
        self.transcript: str = transcript  # Exact raw text preserved
        self.cancel_event: threading.Event = threading.Event()
        self.start_time: float = time.time()
        self.is_cancelled: bool = False
        self.is_completed: bool = False
        self.lock = threading.Lock()

    def cancel(self, stage: str = "unknown") -> None:
        """Cooperatively signal cancellation."""
        with self.lock:
            if not self.is_cancelled:
                self.is_cancelled = True
                self.cancel_event.set()
                now = time.time()
                log.info(
                    "[TURN] TURN_CANCELLED | req_id=%d | turn_id=%d | time=%.4f | stage=%s",
                    self.request_id, self.turn_id, now, stage
                )

    def is_active(self) -> bool:
        """
        Check if this turn is still the active turn for its session
        and has not been cancelled.
        """
        if self.is_cancelled or self.cancel_event.is_set():
            return False
        return turn_controller.is_turn_active(self.session_id, self.turn_id)


class TurnController:
    """Singleton controller managing active turns across all sessions."""

    _instance = None
    _singleton_lock = threading.Lock()

    def __new__(cls):
        with cls._singleton_lock:
            if cls._instance is None:
                cls._instance = super(TurnController, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._seq: int = 0
        self._seq_lock = threading.Lock()
        self._active_turns: Dict[str, TurnRecord] = {}  # session_id -> TurnRecord
        self._stt_history: Dict[str, List[Tuple[float, str, int]]] = {}  # session_id -> [(time, norm_text, turn_id)]
        self._state_lock = threading.Lock()

    def next_id(self) -> int:
        """Monotonically increasing atomic sequence."""
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def check_duplicate_stt(self, session_id: str, raw_transcript: str, window_s: float = 0.75) -> Tuple[bool, Optional[int], float]:
        """
        Check if an identical transcript arrived within window_s for the same session.
        Returns: (is_duplicate, previous_turn_id, delta_time)
        """
        norm = normalize_for_duplicate_check(raw_transcript)
        if not norm:
            return False, None, 0.0

        now = time.time()
        with self._state_lock:
            history = self._stt_history.setdefault(session_id, [])
            for prev_time, prev_norm, prev_turn_id in reversed(history):
                dt = now - prev_time
                if dt > window_s * 4.0:  # prune ancient entries
                    break
                if dt <= window_s and norm == prev_norm:
                    log.warning(
                        "[TURN] DUPLICATE_STT_DISCARDED | turn_id=None | time=%.4f | stage=stt_gate | "
                        "transcript='%s' matches turn=%d received %.3fs ago",
                        now, raw_transcript, prev_turn_id, dt
                    )
                    return True, prev_turn_id, dt
        return False, None, 0.0

    def start_turn(self, session_id: str, raw_transcript: str) -> Optional[TurnRecord]:
        """
        Attempt to start a new turn.
        Checks the duplicate STT gate first.
        If accepted, cancels the previous active turn and registers the new turn.
        """
        now = time.time()
        is_dup, prev_id, dt = self.check_duplicate_stt(session_id, raw_transcript, window_s=0.75)
        if is_dup:
            return None

        turn_id = self.next_id()
        request_id = turn_id  # 1:1 monotonic mapping

        with self._state_lock:
            # 1. Cancel previous active turn if one exists
            prev_turn = self._active_turns.get(session_id)
            if prev_turn and not prev_turn.is_cancelled:
                log.info(
                    "[TURN] TURN_CANCEL_REQUESTED | req_id=%d | turn_id=%d | time=%.4f | stage=preempted_by_new_turn",
                    prev_turn.request_id, prev_turn.turn_id, now
                )
                prev_turn.cancel(stage="preempted_by_new_turn")

            # 2. Register STT history for future deduplication
            norm = normalize_for_duplicate_check(raw_transcript)
            hist = self._stt_history.setdefault(session_id, [])
            hist.append((now, norm, turn_id))
            if len(hist) > 30:
                self._stt_history[session_id] = hist[-30:]

            # 3. Create and set new active turn
            new_turn = TurnRecord(turn_id, request_id, session_id, raw_transcript)
            self._active_turns[session_id] = new_turn

        log.info(
            "[TURN] TURN_STARTED | req_id=%d | turn_id=%d | time=%.4f | stage=turn_start | transcript='%s'",
            request_id, turn_id, now, raw_transcript[:60]
        )
        return new_turn

    def get_active_turn(self, session_id: str) -> Optional[TurnRecord]:
        with self._state_lock:
            return self._active_turns.get(session_id)

    def get_active_turn_id(self, session_id: str) -> Optional[int]:
        with self._state_lock:
            turn = self._active_turns.get(session_id)
            return turn.turn_id if turn else None

    def is_turn_active(self, session_id: str, turn_id: int) -> bool:
        with self._state_lock:
            active = self._active_turns.get(session_id)
            if active is None:
                return False
            return (active.turn_id == turn_id) and (not active.is_cancelled)

    def cancel_active_turn(self, session_id: str, stage: str = "explicit") -> None:
        """Cancel active turn for session (e.g. barge-in or disconnect)."""
        with self._state_lock:
            active = self._active_turns.get(session_id)
            if active and not active.is_cancelled:
                now = time.time()
                log.info(
                    "[TURN] TURN_CANCEL_REQUESTED | req_id=%d | turn_id=%d | time=%.4f | stage=%s",
                    active.request_id, active.turn_id, now, stage
                )
                active.cancel(stage=stage)

    def complete_turn(self, session_id: str, turn_id: int, stage: str = "stream_complete") -> None:
        """Mark turn as completed."""
        with self._state_lock:
            active = self._active_turns.get(session_id)
            if active and active.turn_id == turn_id:
                active.is_completed = True
                now = time.time()
                log.info(
                    "[TURN] TURN_COMPLETED | req_id=%d | turn_id=%d | time=%.4f | stage=%s | total_latency=%.3fs",
                    active.request_id, active.turn_id, now, stage, now - active.start_time
                )


# Global singleton instance
turn_controller = TurnController()
