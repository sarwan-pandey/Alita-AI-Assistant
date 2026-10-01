"""
System & Diagnostics Router — Health, Telemetry, Sessions, Emergency, Vision & History
=======================================================================================
Handles /health, /sessions, /emergency/recordings, /conversations/history, and /api/vision.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
import httpx

log = logging.getLogger("alita.system_router")

system_router = APIRouter(tags=["System"])


class VisionRequest(BaseModel):
    image_b64: str
    prompt: str = "What do you see in this image? Describe it in detail."


@system_router.get("/health")
@system_router.get("/api/health")
@system_router.get("/api/v1/health")
async def health_check():
    """System health check and engine availability matrix."""
    import main
    settings = getattr(main, "settings", None)
    active_sessions = getattr(main, "active_sessions", {})
    engines = getattr(main, "engines", None)
    jwks_keys = getattr(main, "_jwks_keys", {})

    vram_info = {}
    try:
        import torch
        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated(0) / (1024 ** 3)
            reserved = torch.cuda.memory_reserved(0) / (1024 ** 3)
            vram_info = {
                "allocated_gb": round(allocated, 3),
                "reserved_gb": round(reserved, 3),
                "device_name": torch.cuda.get_device_name(0),
            }
    except Exception:
        pass

    # Detect active LLM engine dynamically
    llm_info = "ollama"
    try:
        from ollama_client import is_ollama_running, get_model_name
        model_name = get_model_name()
        if is_ollama_running():
            llm_info = f"ollama ({model_name})"
        elif getattr(settings, "get_all_gemini_keys", None) and settings.get_all_gemini_keys():
            llm_info = f"gemini ({getattr(settings, 'gemini_model', 'gemini-2.0-flash')})"
        elif getattr(settings, "get_all_groq_keys", None) and settings.get_all_groq_keys():
            llm_info = f"groq ({getattr(settings, 'groq_model', 'llama-3.3-70b-versatile')})"
        else:
            llm_info = f"ollama ({model_name}) [waiting for serve]"
    except Exception:
        llm_info = "ollama"

    return {
        "status": "ok",
        "device": getattr(settings, "device", "cpu"),
        "active_sessions": len(active_sessions),
        "engines": {
            "llm": llm_info,
            "whisper": getattr(engines, "whisper_model", None) is not None,
            "wav2vec2": getattr(engines, "wav2vec2_model", None) is not None,
            "memory": getattr(engines, "memory_collection", None) is not None,
            "chatterbox_turbo": getattr(engines, "chatterbox_turbo_engine", None) is not None and engines.chatterbox_turbo_engine.available,
        },
        "security": {
            "jwks_loaded": len(jwks_keys) > 0,
            "jwks_key_count": len(jwks_keys),
        },
        "vram": vram_info,
    }


@system_router.get("/sessions")
async def list_sessions(request: Request):
    """Admin-only: list active sessions. Requires X-Admin-Secret header."""
    from auth_deps import require_admin
    await require_admin(request)

    import main
    active_sessions = getattr(main, "active_sessions", {})

    return {
        sid: {
            "user_id": s.user_id,
            "tier": s.tier,
            "connected_seconds": round(time.time() - s.connected_at, 1),
            "requests_this_min": s.request_count,
            "current_emotion": getattr(s, "current_emotion", "neutral"),
            "interaction_count": getattr(s, "interaction_count", 0),
            "emergency_active": getattr(s, "emergency_active", False),
        }
        for sid, s in active_sessions.items()
    }


@system_router.get("/emergency/recordings")
async def list_emergency_recordings(request: Request, limit: int = 50):
    """Admin-only: list all emergency recordings."""
    from auth_deps import require_admin
    await require_admin(request)
    try:
        from core.emergency_system import list_recordings
        recordings = list_recordings(limit=limit)
        return {"recordings": recordings, "count": len(recordings)}
    except ImportError:
        return {"recordings": [], "count": 0, "error": "emergency_system not available"}


@system_router.get("/emergency/recordings/{recording_id}")
async def get_emergency_recording(recording_id: str, request: Request):
    """Admin-only: get a specific emergency recording."""
    from auth_deps import require_admin
    await require_admin(request)
    try:
        from core.emergency_system import get_recording
        recording = get_recording(recording_id)
        if not recording:
            raise HTTPException(status_code=404, detail="Recording not found")
        return recording
    except ImportError:
        raise HTTPException(status_code=501, detail="Emergency system not available")


@system_router.delete("/emergency/recordings/{recording_id}")
async def delete_emergency_recording(recording_id: str, request: Request):
    """Admin-only: delete an emergency recording."""
    from auth_deps import require_admin
    await require_admin(request)
    try:
        from core.emergency_system import delete_recording
        success = delete_recording(recording_id)
        if not success:
            raise HTTPException(status_code=404, detail="Recording not found")
        return {"status": "deleted", "id": recording_id}
    except ImportError:
        raise HTTPException(status_code=501, detail="Emergency system not available")


@system_router.get("/conversations/history")
async def get_conversation_history(request: Request, limit: int = 50):
    """REST endpoint to load conversation history for a user."""
    from auth_deps import require_auth
    claims = await require_auth(request)
    from memory.conversation_store import load_history

    user_id = claims["user_id"]
    history = load_history(user_id, max_turns=limit)
    return {
        "user_id": user_id,
        "turns": history,
        "count": len(history),
    }


@system_router.post("/admin/export-training-data")
async def export_training_endpoint(request: Request):
    """Export all conversations as anonymised JSONL for model training."""
    from auth_deps import require_admin
    await require_admin(request)
    from memory.conversation_store import export_training_data

    export_path = export_training_data()
    return {
        "status": "exported",
        "path": export_path,
        "note": "Data is anonymised — user IDs hashed, PII stripped.",
    }


@system_router.post("/api/vision")
async def local_vision(req: VisionRequest, request: Request):
    """Analyze an image using local LLaVA model via Ollama."""
    from auth_deps import require_auth
    await require_auth(request)

    try:
        from ollama_client import OLLAMA_NATIVE_URL
        vision_model = os.getenv("OLLAMA_VISION_MODEL", "qwen3:4b-instruct")

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{OLLAMA_NATIVE_URL}/api/chat",
                json={
                    "model": vision_model,
                    "messages": [{
                        "role": "user",
                        "content": req.prompt,
                        "images": [req.image_b64],
                    }],
                    "stream": False,
                    "options": {"num_predict": 500},
                },
            )
            resp.raise_for_status()
            data = resp.json()
            description = data.get("message", {}).get("content", "")

        if not description:
            raise HTTPException(status_code=500, detail="Vision model returned empty response")

        return {"description": description}

    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Ollama not running. Start with: ollama serve")
    except Exception as exc:
        log.error("Vision API error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
