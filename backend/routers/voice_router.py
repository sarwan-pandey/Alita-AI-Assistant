"""
Voice Management Router — Model Listing, Uploads, and Voice Clones
==================================================================
Handles /voices, /voices/upload, /voices/{voice_id}, and /languages.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger("alita.voice_router")

voice_router = APIRouter(tags=["Voices"])


def get_voice_context():
    """Retrieve shared voice registries and engine handles from main/core."""
    import main
    return {
        "AVAILABLE_VOICES": getattr(main, "AVAILABLE_VOICES", {}),
        "LANGUAGE_NAMES": getattr(main, "LANGUAGE_NAMES", {}),
        "DEFAULT_VOICE": getattr(main, "DEFAULT_VOICE", {}),
        "engines": getattr(main, "engines", None),
    }


@voice_router.get("/voices")
async def list_voices():
    """List available voice models (exclusively ChatTTS and F5-TTS)."""
    ctx = get_voice_context()
    available_voices = ctx["AVAILABLE_VOICES"]
    engines = ctx["engines"]

    voices = []
    for vid, info in available_voices.items():
        engine_type = info.get("engine", "chattts")
        is_available = True  # Both ChatTTS and F5-TTS are primary supported local engines

        voices.append({
            "id": vid,
            "name": info["name"],
            "description": info.get("description", ""),
            "tier_required": info.get("tier_required", "free"),
            "lang": info.get("lang", "all"),
            "quality": info.get("quality", "ultra"),
            "engine": engine_type,
            "available": is_available,
        })

    return {"voices": voices}


@voice_router.post("/voices/upload")
async def upload_voice(request: Request):
    """Upload a voice sample WAV for voice cloning (deprecated)."""
    raise HTTPException(status_code=501, detail="Voice cloning removed. Using Chatterbox Turbo engine.")


@voice_router.delete("/voices/{voice_id}")
async def delete_voice(voice_id: str, request: Request):
    """Delete a custom cloned voice."""
    from auth_deps import require_auth
    user = await require_auth(request)
    user_id = user["user_id"]

    if not (voice_id.startswith("f5_custom_") or voice_id.startswith("xtts_custom_")):
        raise HTTPException(status_code=400, detail="Can only delete custom voices.")

    ctx = get_voice_context()
    available_voices = ctx["AVAILABLE_VOICES"]

    if voice_id not in available_voices:
        raise HTTPException(status_code=404, detail="Voice not found.")

    voice_info = available_voices[voice_id]
    owner = voice_info.get("owner_id", "")
    if owner and owner != user_id:
        raise HTTPException(status_code=403, detail="You can only delete your own voices.")

    wav_path = voice_info.get("speaker_wav", "")
    if wav_path and os.path.exists(wav_path):
        try:
            os.remove(wav_path)
        except OSError as exc:
            log.warning("Failed to delete voice file: %s", exc)

    del available_voices[voice_id]
    log.info("Custom voice deleted: %s (by user=%s)", voice_id, user_id[:8])
    return {"message": f"Voice '{voice_id}' deleted successfully."}


@voice_router.get("/languages")
async def list_languages():
    """List supported languages with voice counts and defaults."""
    ctx = get_voice_context()
    available_voices = ctx["AVAILABLE_VOICES"]
    language_names = ctx["LANGUAGE_NAMES"]
    default_voice = ctx["DEFAULT_VOICE"]

    langs = []
    for lang_code, lang_name in language_names.items():
        lang_voices = [
            vid for vid, v in available_voices.items() if v.get("lang") == lang_code
        ]
        free_voices = [
            vid for vid in lang_voices
            if available_voices[vid].get("tier_required") == "free"
        ]
        premium_voices = [
            vid for vid in lang_voices
            if available_voices[vid].get("tier_required") == "premium"
        ]
        langs.append({
            "code": lang_code,
            "name": lang_name,
            "default_voice": default_voice.get(lang_code),
            "free_voices": len(free_voices),
            "premium_voices": len(premium_voices),
            "total_voices": len(lang_voices),
        })
    return {"languages": langs}


@voice_router.get("/voices/preference")
async def get_voice_preference():
    """Get the user's persistent voice preference across all sessions."""
    try:
        from engines.user_profile import user_profile
        pref = user_profile.get_preference("selected_voice", "chatterbox_turbo_mj")
        return {"selected_voice": pref}
    except Exception as exc:
        log.warning("Could not read voice preference: %s", exc)
        return {"selected_voice": "chatterbox_turbo_mj"}


@voice_router.post("/voices/preference")
async def set_voice_preference(request: Request):
    """Set the user's persistent voice preference across all sessions."""
    try:
        body = await request.json()
        voice_id = body.get("voice_id")
        if not voice_id:
            raise HTTPException(status_code=400, detail="Missing voice_id in request body")
        from engines.user_profile import user_profile
        user_profile.set_preference("selected_voice", voice_id)
        log.info("Persisted voice preference across all sessions: %s", voice_id)
        return {"status": "success", "selected_voice": voice_id}
    except HTTPException:
        raise
    except Exception as exc:
        log.error("Failed to set voice preference: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))
