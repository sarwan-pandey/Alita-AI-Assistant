"""
Voice Management & Cloning Router (Disabled State)
===================================================
Custom voice cloning is currently unavailable.
Chatterbox Multilingual NIM and local Chatterbox Turbo do not support zero-shot
custom voice cloning.

This router preserves the endpoint contracts so future cloning-capable providers
can be integrated behind the TTS Provider Orchestrator without modifying MJ core.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

log = logging.getLogger("alita.voice_clone")

voice_clone_router = APIRouter(prefix="/api/voice", tags=["voice-clone"])

VOICES_DIR = Path(__file__).parent.parent / "voices"
VOICES_CUSTOM_DIR = VOICES_DIR / "custom"
VOICES_CUSTOM_DIR.mkdir(parents=True, exist_ok=True)


async def _resolve_user(request: Request) -> str:
    """Extract authenticated user id or fallback to local user."""
    try:
        from auth_deps import require_auth
        user = await require_auth(request)
        return user.get("user_id", "local_user")
    except Exception:
        return request.query_params.get("user_id") or "local_user"


@voice_clone_router.post("/upload")
async def upload_voice_sample(
    request: Request,
    file: UploadFile = File(...),
    voice_name: str = Form(...),
):
    """Voice sample upload disabled while custom voice cloning is unavailable."""
    raise HTTPException(
        status_code=501,
        detail="Custom voice cloning is unavailable. Preset Chatterbox voices are active.",
    )


@voice_clone_router.post("/record")
async def record_voice_sample(
    request: Request,
    file: UploadFile = File(...),
    voice_name: str = Form(...),
):
    """Voice recording disabled while custom voice cloning is unavailable."""
    raise HTTPException(
        status_code=501,
        detail="Custom voice cloning is unavailable. Preset Chatterbox voices are active.",
    )


@voice_clone_router.post("/clone")
async def start_clone(upload_id: str = Form(...)):
    """Start voice cloning process (disabled)."""
    raise HTTPException(
        status_code=501,
        detail="Custom voice cloning is unavailable. Preset Chatterbox voices are active.",
    )


@voice_clone_router.get("/clone/{clone_id}/status")
async def clone_status(clone_id: str):
    """Check clone status (disabled)."""
    raise HTTPException(
        status_code=501,
        detail="Custom voice cloning is unavailable.",
    )


@voice_clone_router.get("/custom")
async def list_custom_voices(request: Request):
    """List custom voices (returns empty list when voice cloning is disabled)."""
    return {
        "voices": [],
        "available": False,
        "message": "Custom voice cloning is unavailable. Preset Chatterbox voices are active.",
    }


@voice_clone_router.delete("/custom/{voice_id}")
async def delete_custom_voice(voice_id: str, request: Request):
    """Delete a custom voice file if present."""
    user_id = await _resolve_user(request)

    meta_path = VOICES_CUSTOM_DIR / f"{voice_id}.json"
    wav_path = VOICES_CUSTOM_DIR / f"{voice_id}.wav"

    if not meta_path.exists() and not wav_path.exists():
        raise HTTPException(404, "Voice not found")

    meta_path.unlink(missing_ok=True)
    wav_path.unlink(missing_ok=True)

    for raw in VOICES_CUSTOM_DIR.glob(f"{voice_id}_raw*"):
        raw.unlink(missing_ok=True)

    log.info("Custom voice removed: %s (by user=%s)", voice_id, user_id[:8])
    return {"deleted": voice_id}


@voice_clone_router.post("/preview")
async def preview_custom_voice(
    request: Request,
    voice_id: str = Form(...),
    text: str = Form(default="Hello!"),
):
    """Preview custom voice (disabled)."""
    raise HTTPException(
        status_code=501,
        detail="Custom voice cloning is unavailable.",
    )
