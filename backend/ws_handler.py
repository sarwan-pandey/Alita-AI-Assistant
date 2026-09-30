"""
Alita WebSocket Message Dispatcher (ws_handler.py)
=================================================
Modular dispatch table for WebSocket control and utility messages:
- Barge-in cancellation
- Speculative query pre-generation
- Voice selection & preference persistence
- Dashboard hardware telemetry
- Screen agent lifecycle & actions
- Dictation & typing automation
- Proactive suggestions acceptance
- Fitness tracking events
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Coroutine, Dict, Optional

log = logging.getLogger("Alita.ws_handler")


@dataclass
class WsContext:
    """Execution context passed to each WebSocket message handler."""
    websocket: Any
    session: Any
    session_id: str
    user_id: str
    tier: str
    active_sessions: Dict[str, Any]
    available_voices: Dict[str, Any]
    default_active_voice: str
    llm_generate_sync: Optional[Callable] = None
    tts_generate: Optional[Callable] = None
    memory_store: Optional[Callable] = None


async def handle_barge_in(msg: dict, ctx: WsContext) -> None:
    """User interrupted Alita mid-turn — cancel pipelines and capture context."""
    partial_response = msg.get("partial_response", "").strip()
    original_query = msg.get("original_query", "").strip()

    ctx.session.pipeline_cancel = True
    ctx.session.barge_in_count = getattr(ctx.session, "barge_in_count", 0) + 1
    if hasattr(ctx.session, "cancel_event") and ctx.session.cancel_event:
        ctx.session.cancel_event.set()

    if partial_response:
        ctx.session.interrupted_response = partial_response
    if original_query:
        ctx.session.interrupted_query = original_query

    try:
        from core.turn_controller import turn_controller
        turn_controller.cancel_active_turn(ctx.session_id, stage="barge_in")
    except Exception as exc:
        log.debug("[%s] Turn controller cancel failed: %s", ctx.session_id, exc)

    log.info(
        "[%s] 🔇 BARGE-IN #%d | interrupted_response=%d chars | original_query='%s'",
        ctx.session_id,
        ctx.session.barge_in_count,
        len(partial_response),
        original_query[:50],
    )


async def handle_speculative_query(msg: dict, ctx: WsContext) -> None:
    """Interim transcript pre-generation to minimize user-perceived latency."""
    spec_text = msg.get("text", "").strip()
    spec_id = msg.get("spec_id", 0)
    if not spec_text:
        return

    from engines.speculative_engine import speculative_manager
    cancel_evt = speculative_manager.start_speculative(ctx.session, spec_id, spec_text)

    # If already satisfied via precomputed greeting fast-path, skip background LLM
    if getattr(ctx.session, "_spec_result", None):
        log.info(
            "[%s] ⚡ Speculative #%d precomputed fast-path hit for: '%s'",
            ctx.session_id, spec_id, spec_text[:50]
        )
        return

    async def _run_speculative(s, text, cancel, sid):
        try:
            loop = asyncio.get_event_loop()
            if ctx.llm_generate_sync:
                tokens, _ = await loop.run_in_executor(
                    None, ctx.llm_generate_sync, s, text
                )
                if cancel.is_set():
                    return
                result = "".join(tokens)
                s._spec_result = result
                s._spec_text = text.lower().strip()
                log.info(
                    "[%s] Speculative #%d cached (%d chars) for: '%s'",
                    ctx.session_id, sid, len(result), text[:50],
                )
        except Exception as e:
            log.warning("[%s] Speculative error: %s", ctx.session_id, e)

    asyncio.create_task(_run_speculative(ctx.session, spec_text, cancel_evt, spec_id))
    log.info("[%s] ⚡ Speculative #%d started: '%s'", ctx.session_id, spec_id, spec_text[:50])


async def handle_cancel_speculative(msg: dict, ctx: WsContext) -> None:
    """Explicitly cancel active speculative background task."""
    from engines.speculative_engine import speculative_manager
    speculative_manager.clear(ctx.session)


async def handle_ping(msg: dict, ctx: WsContext) -> None:
    """WebSocket ping-pong keepalive."""
    await ctx.websocket.send_text(json.dumps({
        "type": "pong",
        "ts": time.time(),
    }))


async def handle_voice_change(msg: dict, ctx: WsContext) -> None:
    """Switch active voice profile and save preference."""
    voice_id = msg.get("voice_id", ctx.default_active_voice)
    voice = ctx.available_voices.get(voice_id)
    if not voice:
        await ctx.websocket.send_text(json.dumps({
            "type": "error",
            "detail": f"Unknown voice: {voice_id}",
        }))
        return

    if voice.get("tier_required") == "premium" and ctx.tier != "premium" and not ctx.user_id.startswith("test_"):
        await ctx.websocket.send_text(json.dumps({
            "type": "voice_change_denied",
            "reason": "premium_required",
            "voice_id": voice_id,
        }))
        return

    ctx.session.voice_id = voice_id
    ctx.session.manual_voice_override = True
    try:
        from engines.user_profile import user_profile
        user_profile.set_preference("selected_voice", voice_id)
    except Exception:
        pass
    log.info("Voice changed to '%s' for session=%s (manual override & persisted)", voice_id, ctx.session_id)

    voice_lang = voice.get("lang", "en")
    stt_lang_map = {"en": "en-IN", "hi": "hi-IN", "es": "es-ES", "fr": "fr-FR", "de": "de-DE", "ja": "ja-JP"}
    await ctx.websocket.send_text(json.dumps({
        "type": "voice_changed",
        "voice_id": voice_id,
        "voice_name": voice.get("name", "Voice"),
        "lang": voice_lang,
        "stt_lang": stt_lang_map.get(str(voice_lang or "en"), "en-IN"),
    }))


async def handle_dashboard_stats(msg: dict, ctx: WsContext) -> None:
    """Telemetry report: CPU, RAM, active sessions, and GPU VRAM if present."""
    try:
        import psutil
        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        stats_payload = {
            "type": "dashboard_stats",
            "cpu_percent": cpu,
            "memory_percent": vm.percent,
            "memory_used_gb": round((vm.total - vm.available) / (1024 ** 3), 2),
            "memory_total_gb": round(vm.total / (1024 ** 3), 2),
            "active_sessions": len(ctx.active_sessions),
            "timestamp": time.time(),
        }
        try:
            import torch
            if torch.cuda.is_available():
                stats_payload["gpu_name"] = torch.cuda.get_device_name(0)
                stats_payload["gpu_vram_allocated_gb"] = round(torch.cuda.memory_allocated(0) / (1024 ** 3), 2)
                stats_payload["gpu_vram_total_gb"] = round(torch.cuda.get_device_properties(0).total_memory / (1024 ** 3), 2)
        except Exception:
            pass
        await ctx.websocket.send_text(json.dumps(stats_payload))
    except Exception as ds_err:
        log.warning("[%s] Dashboard stats error: %s", ctx.session_id, ds_err)


async def handle_language_detected(msg: dict, ctx: WsContext) -> None:
    """Frontend-reported language change."""
    detected_lang = msg.get("language", "en")
    setattr(ctx.session, "detected_language", detected_lang)
    log.info("[%s] Language auto-detected by frontend: %s", ctx.session_id, detected_lang)


async def handle_screen_read(msg: dict, ctx: WsContext) -> None:
    """Screen text / OCR context pushed by client."""
    screen_text = msg.get("text", "")
    setattr(ctx.session, "screen_context", screen_text)
    log.info("[%s] Screen text received: %d chars", ctx.session_id, len(screen_text))
    await ctx.websocket.send_text(json.dumps({
        "type": "screen_read_ack",
        "length": len(screen_text),
    }))


async def handle_start_screen_agent(msg: dict, ctx: WsContext) -> None:
    """Initialize autonomous screen interaction agent."""
    task_id = msg.get("task_id", f"task_{int(time.time())}")
    command = msg.get("command", "")
    log.info("[%s] start_screen_agent received | task=%s | cmd='%s'", ctx.session_id, task_id, command)
    from engines.screen_agent import screen_agent

    def _agent_cb(data: dict):
        try:
            asyncio.create_task(ctx.websocket.send_text(json.dumps({
                "type": "screen_agent_event",
                "task_id": task_id,
                "data": data,
            })))
        except Exception as cb_err:
            log.debug("Screen agent callback send failed: %s", cb_err)

    res = screen_agent.start_task(task_id, command, session=ctx.session, callback=_agent_cb)
    await ctx.websocket.send_text(json.dumps({
        "type": "screen_agent_started",
        "task_id": task_id,
        "result": res,
    }))


async def handle_screen_action(msg: dict, ctx: WsContext) -> None:
    """Execute single screen action via screen agent."""
    action = msg.get("action", "")
    log.info("[%s] screen_action received | action='%s'", ctx.session_id, action)
    from engines.screen_agent import screen_agent
    task_id = f"action_{int(time.time())}"
    res = screen_agent.start_task(task_id, action, session=ctx.session)
    await ctx.websocket.send_text(json.dumps({
        "type": "screen_action_result",
        "task_id": task_id,
        "result": res,
    }))


async def handle_stop_screen_agent(msg: dict, ctx: WsContext) -> None:
    """Stop active screen agent."""
    log.info("[%s] stop_screen_agent received", ctx.session_id)
    from engines.screen_agent import screen_agent
    screen_agent.force_stop()
    await ctx.websocket.send_text(json.dumps({
        "type": "screen_agent_stopped",
        "status": "stopped",
    }))


async def handle_fitness_event(msg: dict, ctx: WsContext) -> None:
    """Fitness coach event handler."""
    msg_type = msg.get("type", "")
    ex_name = msg.get("exercise", "workout")
    reps = msg.get("reps", 0)
    log.info("[%s] Fitness event [%s]: %s (reps: %s)", ctx.session_id, msg_type, ex_name, reps)
    if msg_type == "exercise_completed" and ctx.memory_store:
        ctx.memory_store(ctx.user_id, f"Fitness completed: {ex_name} with {reps} reps")
    await ctx.websocket.send_text(json.dumps({
        "type": "fitness_ack",
        "event": msg_type,
        "exercise": ex_name,
    }))


async def handle_dictate_text(msg: dict, ctx: WsContext) -> None:
    """Types transcribed speech directly into current active Windows input field."""
    dictation_text = msg.get("text", "").strip()
    if not dictation_text:
        return
    try:
        import pyautogui
        pyautogui.PAUSE = 0.02
        if dictation_text.isascii():
            pyautogui.typewrite(dictation_text + " ", interval=0.01)
        else:
            import pyperclip
            pyperclip.copy(dictation_text + " ")
            pyautogui.hotkey("ctrl", "v")
        log.info("Dictation typed: %s", dictation_text[:40])
        await ctx.websocket.send_text(json.dumps({
            "type": "dictation_ack",
            "text": dictation_text,
        }))
    except Exception as e:
        log.warning("Dictation type failed: %s", e)
        await ctx.websocket.send_text(json.dumps({
            "type": "error",
            "detail": f"Typing failed: {e}",
        }))


async def handle_dictation_stop(msg: dict, ctx: WsContext) -> None:
    """Stops continuous dictation mode."""
    ctx.session.dictation_active = False
    log.info("Dictation mode stopped for session=%s", ctx.session_id)
    await ctx.websocket.send_text(json.dumps({
        "type": "dictation_stopped",
    }))


async def handle_proactive_action_accept(msg: dict, ctx: WsContext) -> None:
    """Execute confirmed proactive suggestion from dynamic island / notifications."""
    action_payload = msg.get("action_payload") or {}
    act = action_payload.get("action", "")
    log.info("[%s] Proactive action accepted: %s", ctx.session_id, act)
    try:
        from threads.automation_handler import (
            open_music as _pm_music,
            open_url as _pm_url,
            open_app as _pm_app,
        )
        executed = False
        if act == "open_music":
            _pm_music(action_payload.get("query", ""))
            executed = True
        elif act == "open_url":
            _pm_url(action_payload.get("url", ""))
            executed = True
        elif act == "open_app":
            _pm_app(action_payload.get("app", ""))
            executed = True
        elif ("command" in action_payload or "instruction" in action_payload) and ctx.llm_generate_sync:
            cmd = action_payload.get("command") or action_payload.get("instruction")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, ctx.llm_generate_sync, ctx.session, cmd, None, "automation")
            executed = True

        await ctx.websocket.send_text(json.dumps({
            "type": "proactive_action_executed",
            "action": act,
            "success": executed,
        }))
    except Exception as pa_err:
        log.error("[%s] Proactive action execution error: %s", ctx.session_id, pa_err)
        await ctx.websocket.send_text(json.dumps({
            "type": "error",
            "detail": f"Failed to execute proactive action: {pa_err}",
        }))


DISPATCH_TABLE: Dict[str, Callable[[dict, WsContext], Coroutine[Any, Any, None]]] = {
    "barge_in": handle_barge_in,
    "speculative_query": handle_speculative_query,
    "cancel_speculative": handle_cancel_speculative,
    "ping": handle_ping,
    "voice_change": handle_voice_change,
    "dashboard_stats": handle_dashboard_stats,
    "language_detected": handle_language_detected,
    "screen_read": handle_screen_read,
    "start_screen_agent": handle_start_screen_agent,
    "screen_action": handle_screen_action,
    "stop_screen_agent": handle_stop_screen_agent,
    "exercise_started": handle_fitness_event,
    "exercise_completed": handle_fitness_event,
    "rep_counted": handle_fitness_event,
    "dictate_text": handle_dictate_text,
    "dictation_stop": handle_dictation_stop,
    "proactive_action_accept": handle_proactive_action_accept,
}


async def dispatch_ws_message(msg_type: str, msg: dict, ctx: WsContext) -> bool:
    """
    Dispatch message to registered handler.
    Returns True if handled, False if unknown message type.
    """
    handler = DISPATCH_TABLE.get(msg_type)
    if handler is not None:
        await handler(msg, ctx)
        return True
    return False
