"""
Temporary Diagnostic Instrumentation for Aura / MJ Assistant.
Tracks request lifecycles, latencies, stale requests, and duplicate STT.

DO NOT modify core architectural behavior.
This module is strictly observational.
"""

import io
import time
import wave
import logging
import threading
from typing import Optional, Dict, Any, List

log = logging.getLogger("alita.diagnostics")


def get_audio_duration_from_bytes(audio_bytes: bytes) -> float:
    """Extract audio duration in seconds from WAV bytes, or estimate from MP3."""
    if not audio_bytes:
        return 0.0
    try:
        if audio_bytes.startswith(b"RIFF"):
            with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    return round(frames / rate, 3)
    except Exception:
        pass
    return 0.0


def resolve_tts_engine(text: str, voice_info: Optional[dict] = None, settings_engine_mode: str = "chatterbox") -> str:
    """Resolve which TTS engine will be selected for given text and voice_info."""
    return "chatterbox_turbo"


def is_substantially_identical(text1: str, text2: str) -> bool:
    """Check if two transcripts are identical or substantially similar."""
    t1 = text1.strip().lower()
    t2 = text2.strip().lower()
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    w1 = set(t1.split())
    w2 = set(t2.split())
    if not w1 or not w2:
        return False
    overlap = len(w1 & w2) / max(len(w1), len(w2))
    return overlap >= 0.85


class RequestRecord:
    def __init__(self, request_id: int, session_id: str, transcript: str):
        self.request_id = request_id
        self.session_id = session_id
        self.transcript = transcript
        self.t_stt_received = time.time()
        self.t_req_id_assigned = time.time()
        self.t_llm_start: Optional[float] = None
        self.t_first_token: Optional[float] = None
        self.chunks: Dict[int, Dict[str, Any]] = {}
        self.total_chunks: Optional[int] = None
        self.t_req_complete: Optional[float] = None
        self.is_stale: bool = False


class DiagnosticsTracker:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(DiagnosticsTracker, cls).__new__(cls)
                cls._instance._init()
            return cls._instance

    def _init(self):
        self._seq = 0
        self._seq_lock = threading.Lock()
        self._active_request: Dict[str, int] = {}  # session_id -> active request_id
        self._stt_history: Dict[str, List[tuple]] = {}  # session_id -> [(timestamp, transcript, req_id)]
        self._requests: Dict[int, RequestRecord] = {}
        self._last_audio_end_time: Dict[str, float] = {}  # session_id -> float (wall clock timestamp)

    def next_request_id(self) -> int:
        with self._seq_lock:
            self._seq += 1
            return self._seq

    def get_active_request_id(self, session_id: str) -> Optional[int]:
        try:
            from core.turn_controller import turn_controller
            tid = turn_controller.get_active_turn_id(session_id)
            if tid is not None:
                return tid
        except Exception:
            pass
        return self._active_request.get(session_id)

    # ── 1. STT Final Transcript Received & 2. request_id assigned ────────────
    def on_stt_received(self, session_id: str, transcript: str, req_id: Optional[int] = None) -> int:
        if req_id is None:
            req_id = self.next_request_id()
        now = time.time()
        record = RequestRecord(req_id, session_id, transcript)
        self._requests[req_id] = record

        # Check for duplicate STT
        history = self._stt_history.setdefault(session_id, [])
        for prev_time, prev_text, prev_id in reversed(history):
            dt = now - prev_time
            if dt > 6.0:
                break
            if is_substantially_identical(transcript, prev_text):
                log.warning(
                    "[DIAGNOSTICS] [req=%d] POSSIBLE_DUPLICATE_STT: '%s' matches req=%d ('%s') received %.2fs ago",
                    req_id, transcript, prev_id, prev_text, dt
                )
                break
        history.append((now, transcript, req_id))
        if len(history) > 20:
            self._stt_history[session_id] = history[-20:]

        # Update active request for this session
        old_active = self._active_request.get(session_id)
        self._active_request[session_id] = req_id

        log.info(
            "[DIAGNOSTICS] [req=%d] 1. STT final transcript received: '%s' at %.4f",
            req_id, transcript, now
        )
        log.info(
            "[DIAGNOSTICS] [req=%d] 2. request_id assigned: %d (previous active: %s) at %.4f",
            req_id, req_id, str(old_active), record.t_req_id_assigned
        )
        return req_id

    # ── 3. LLM Request Start ─────────────────────────────────────────────────
    def on_llm_start(self, req_id: int) -> None:
        rec = self._requests.get(req_id)
        if not rec:
            return
        now = time.time()
        rec.t_llm_start = now
        stt_to_llm = now - rec.t_stt_received
        log.info(
            "[DIAGNOSTICS] [req=%d] 3. LLM request start at %.4f | STT -> LLM start latency: %.3fs",
            req_id, now, stt_to_llm
        )

    # ── 4. First LLM Token/Chunk Received ────────────────────────────────────
    def on_first_token(self, req_id: int) -> None:
        rec = self._requests.get(req_id)
        if not rec or rec.t_first_token is not None:
            return
        now = time.time()
        rec.t_first_token = now
        llm_to_token = now - (rec.t_llm_start or rec.t_stt_received)
        log.info(
            "[DIAGNOSTICS] [req=%d] 4. First LLM token received at %.4f | LLM start -> first token latency: %.3fs",
            req_id, now, llm_to_token
        )

    # ── 5. Each Complete TTS Sentence/Chunk Detected ─────────────────────────
    def on_sentence_detected(self, req_id: int, chunk_index: int, text: str) -> None:
        rec = self._requests.get(req_id)
        if not rec:
            return
        now = time.time()
        chunk_data = rec.chunks.setdefault(chunk_index, {})
        chunk_data["chunk_index"] = chunk_index
        chunk_data["text"] = text
        chunk_data["t_sentence_detected"] = now

        llm_to_sent = now - (rec.t_llm_start or rec.t_stt_received)
        log.info(
            "[DIAGNOSTICS] [req=%d] 5. Sentence chunk #%d detected: '%s' at %.4f | LLM start -> sentence latency: %.3fs",
            req_id, chunk_index, text.strip()[:50], now, llm_to_sent
        )

    # ── 6. Audio Queued ──────────────────────────────────────────────────────
    def on_audio_queued(self, req_id: int, chunk_index: int) -> None:
        rec = self._requests.get(req_id)
        if not rec:
            return
        now = time.time()
        chunk_data = rec.chunks.setdefault(chunk_index, {})
        chunk_data["t_audio_queued"] = now
        log.info(
            "[DIAGNOSTICS] [req=%d] 8. Audio queued for chunk #%d at %.4f",
            req_id, chunk_index, now
        )

    # ── 7. TTS Generation Start ──────────────────────────────────────────────
    def on_tts_start(self, req_id: int, chunk_index: int, engine: str) -> None:
        rec = self._requests.get(req_id)
        if not rec:
            return
        now = time.time()
        chunk_data = rec.chunks.setdefault(chunk_index, {})
        chunk_data["engine"] = engine
        chunk_data["t_tts_start"] = now

        sent_detected = chunk_data.get("t_sentence_detected", rec.t_first_token or rec.t_llm_start or now)
        sent_to_tts = now - sent_detected
        log.info(
            "[DIAGNOSTICS] [req=%d] 6. TTS generation start for chunk #%d (engine=%s) at %.4f | sentence -> TTS start latency: %.3fs",
            req_id, chunk_index, engine, now, sent_to_tts
        )

    # ── 8. TTS Generation Completion ─────────────────────────────────────────
    def on_tts_done(self, req_id: int, chunk_index: int, audio_bytes: bytes, session_id: str) -> bool:
        rec = self._requests.get(req_id)
        now = time.time()
        current_active = self.get_active_request_id(session_id)
        is_current = (req_id == current_active)

        if not is_current:
            log.warning(
                "[DIAGNOSTICS] [req=%d] STALE_REQUEST_DISCARDED: request_id=%d != current_active_id=%s during TTS done for chunk #%d",
                req_id, req_id, str(current_active), chunk_index
            )

        if not rec:
            return is_current

        chunk_data = rec.chunks.setdefault(chunk_index, {})
        chunk_data["t_tts_done"] = now
        t_start = chunk_data.get("t_tts_start", now)
        tts_dur = now - t_start
        chunk_data["tts_duration"] = tts_dur
        audio_dur = get_audio_duration_from_bytes(audio_bytes)
        chunk_data["audio_duration"] = audio_dur
        chunk_data["is_current_at_tts_done"] = is_current

        log.info(
            "[DIAGNOSTICS] [req=%d] 7. TTS generation completion for chunk #%d | TTS duration: %.3fs | Audio duration: %.3fs | is_current=%s at %.4f",
            req_id, chunk_index, tts_dur, audio_dur, is_current, now
        )
        return is_current

    # ── 9. WebSocket tts_audio Send ──────────────────────────────────────────
    def on_ws_send(self, req_id: int, chunk_index: int, audio_bytes: bytes, session_id: str) -> None:
        rec = self._requests.get(req_id)
        now = time.time()
        chunk_data = rec.chunks.get(chunk_index, {}) if rec else {}
        chunk_data["t_ws_send"] = now

        t_done = chunk_data.get("t_tts_done", now)
        tts_to_ws = now - t_done

        # Measure inter-sentence audio gap
        last_audio_end = self._last_audio_end_time.get(session_id)
        if last_audio_end is not None and chunk_index > 0:
            inter_sentence_gap = max(0.0, now - last_audio_end)
        else:
            inter_sentence_gap = 0.0

        audio_dur = chunk_data.get("audio_duration") or get_audio_duration_from_bytes(audio_bytes)
        # Advance expected playback end time on the frontend
        # (frontend starts playing at now, finishes at now + audio_dur)
        self._last_audio_end_time[session_id] = now + audio_dur

        log.info(
            "[DIAGNOSTICS] [req=%d] 9. WebSocket tts_audio send for chunk #%d at %.4f | TTS done -> WS send: %.3fs | Inter-sentence audio gap: %.3fs",
            req_id, chunk_index, now, tts_to_ws, inter_sentence_gap
        )

    # ── 10. Request Completion ───────────────────────────────────────────────
    def on_request_complete(self, req_id: int, total_chunks: Optional[int] = None) -> None:
        rec = self._requests.get(req_id)
        if not rec:
            return
        now = time.time()
        rec.t_req_complete = now
        rec.total_chunks = total_chunks if total_chunks is not None else len(rec.chunks)
        total_latency = now - rec.t_stt_received

        log.info(
            "[DIAGNOSTICS] [req=%d] 10. Request complete at %.4f | Total chunks: %d | Total request latency: %.3fs",
            req_id, now, rec.total_chunks, total_latency
        )

        # Print structured latency summary
        self._print_latency_summary(rec)

    def _print_latency_summary(self, rec: RequestRecord) -> None:
        lines = [
            f"=== [DIAGNOSTICS SUMMARY: req={rec.request_id}] ===",
            f"  Transcript: '{rec.transcript}'",
            f"  STT -> LLM Start:         {(rec.t_llm_start - rec.t_stt_received if rec.t_llm_start else 0):.3f}s",
            f"  LLM Start -> First Token: {(rec.t_first_token - rec.t_llm_start if rec.t_first_token and rec.t_llm_start else 0):.3f}s",
        ]
        for idx in sorted(rec.chunks.keys()):
            c = rec.chunks[idx]
            sent_det = c.get("t_sentence_detected")
            tts_start = c.get("t_tts_start")
            tts_done = c.get("t_tts_done")
            ws_send = c.get("t_ws_send")
            lines.append(
                f"  Chunk #{idx} ({c.get('engine', 'unknown')}): text='{c.get('text', '')[:30]}...' | "
                f"SentDet->TTSStart={(tts_start - sent_det if tts_start and sent_det else 0):.3f}s | "
                f"TTSDur={c.get('tts_duration', 0):.3f}s | "
                f"AudioDur={c.get('audio_duration', 0):.3f}s | "
                f"TTSDone->WS={(ws_send - tts_done if ws_send and tts_done else 0):.3f}s | "
                f"is_current={c.get('is_current_at_tts_done', True)}"
            )
        total_dur = (rec.t_req_complete - rec.t_stt_received) if rec.t_req_complete else 0
        lines.append(f"  Total Request Latency:    {total_dur:.3f}s")
        lines.append("==================================================")
        log.info("\n".join(lines))


# Global singleton instance
diagnostics = DiagnosticsTracker()
