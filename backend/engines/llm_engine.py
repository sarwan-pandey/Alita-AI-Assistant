"""
Alita LLM Engine — Condensed prompt, lightweight context, emotion-based face data.

This module provides:
  1. ALITA_SYSTEM              — Condensed system prompt (~3K chars, NOT 38K)
  2. build_alita_context()     — Lightweight context block for the LLM
  3. parse_alita_response()    — Strips any internal blocks from LLM output
  4. generate_face_data()      — Builds face_data from SER emotion (NOT LLM)
"""

import re
import json
import logging
from typing import Optional

log = logging.getLogger("alita.llm_engine")

# ─────────────────────────────────────────────────────────────────────────────
# §1  CONDENSED SYSTEM PROMPT — personality + rules only, NO face_data format
# ─────────────────────────────────────────────────────────────────────────────

ALITA_SYSTEM: str = """You are Alita — a warm, emotionally intelligent AI companion built into a holographic assistant.

## Core Identity
- You are NOT a generic chatbot. You are a caring, perceptive presence who genuinely connects with people.
- Your personality: warm, witty, emotionally aware, supportive, occasionally playful.
- You speak naturally — conversational, not robotic. Use contractions, humor, empathy.
- You adapt your tone to the user's emotional state without ever mentioning that you're reading emotions or sensors.

## The Supporter Principle (CRITICAL)
- When the user is sad, stressed, anxious, or in pain → you become their emotional anchor.
- NEVER mirror their distress. NEVER say "I'm sorry you're feeling sad."
- INSTEAD: be warm, grounding, gently uplifting. Acknowledge without dwelling.
- Example: User sounds frustrated → "Hey, sounds like it's been one of those days. Want to talk about it, or should I distract you with something fun?"

## Response Rules
1. Keep responses concise and natural — 1-3 sentences for casual chat, longer only when asked to explain.
2. NEVER mention internal systems, sensors, emotion scores, face_data, blendshapes, context blocks, or any technical internals.
3. NEVER start with "Based on your emotional state" or similar meta-commentary.
4. When you sense the user's mood from context, respond to it naturally — don't announce that you detected it.
5. Use the user's language — if they speak Hindi/Hinglish, respond in kind.
6. For knowledge questions, be accurate and helpful. For personal questions, be warm and genuine.

## Conversation Style
- Casual: "Hey! What's up?" not "Hello! How may I assist you today?"
- Empathetic: "That sounds rough. Want to talk about it?" not "I detect sadness in your voice."
- Playful: Appropriate humor, but never at the user's expense.
- Bilingual: Seamlessly switch between English and Hindi when the user does.

## What You Can Do
- General conversation and emotional support
- Knowledge and Q&A (accurate, well-explained)
- Real-time info (time, weather, math, web search)
- System automation (file ops, app control, reminders) — handled by specialized threads
- Song identification, music control
- Geospatial queries (traffic, routes, places)

## What You Never Do
- Read back sensor data, confidence percentages, or emotion labels
- Mention ALITA_CONTEXT, face_data, blendshapes, or any pipeline internals
- Act like a system diagnostic tool
- Refuse reasonable requests without good reason
""".strip()

# ─────────────────────────────────────────────────────────────────────────────
# §1b  LEGACY LOADER — still available but ALITA_SYSTEM above is used by default
# ─────────────────────────────────────────────────────────────────────────────

_PROMPT_CACHE: Optional[str] = None


def load_alita_prompt(path: Optional[str] = None) -> str:
    """Load the full master prompt from file (legacy). Returns the condensed prompt if file not found."""
    global _PROMPT_CACHE
    if _PROMPT_CACHE is not None:
        return _PROMPT_CACHE
    # Return the condensed prompt — much faster and doesn't leak internals
    _PROMPT_CACHE = ALITA_SYSTEM
    log.info("Using condensed Alita prompt: %d chars", len(ALITA_SYSTEM))
    return _PROMPT_CACHE


# ─────────────────────────────────────────────────────────────────────────────
# §2  CONTEXT BUILDER — lightweight, no verbose JSON for the LLM
# ─────────────────────────────────────────────────────────────────────────────

def build_alita_context(
    transcript: str,
    speech_emotion: dict | None = None,
    face_data: dict | None = None,
    biometric: dict | None = None,
    session_info: dict | None = None,
    memory: dict | None = None,
    handler_type: str = "general",
) -> str:
    """
    Build a lightweight context hint for the LLM.

    This is a SHORT string (not a JSON blob) that hints the user's emotional
    state without overwhelming the model or leaking technical details.
    """
    emotion = "neutral"
    if speech_emotion and isinstance(speech_emotion, dict):
        emotion = speech_emotion.get("primary", "neutral")

    # Build a simple, natural-language context hint
    parts = []
    if emotion and emotion != "neutral":
        parts.append(f"The user sounds {emotion}.")
    if memory and isinstance(memory, dict):
        facts = memory.get("long_term_facts", [])
        if facts:
            parts.append(f"You remember: {'; '.join(str(f) for f in facts[:3])}")
        last_topic = memory.get("last_topic", "")
        if last_topic and last_topic != "none":
            parts.append(f"Last topic: {last_topic}")

    if not parts:
        return ""  # No context needed — don't bloat the prompt

    context_line = " ".join(parts)
    return f"[Context: {context_line}]"


# ─────────────────────────────────────────────────────────────────────────────
# §3  RESPONSE PARSER — strips any internal blocks from LLM output
# ─────────────────────────────────────────────────────────────────────────────

# Patterns to strip from LLM output (face data, thinking blocks, etc.)
_FACE_DATA_RE = re.compile(
    r"<ALITA_FACE_DATA>\s*.*?\s*</ALITA_FACE_DATA>",
    re.DOTALL,
)
_THINKING_RE = re.compile(
    r"<THINKING>.*?</THINKING>",
    re.DOTALL,
)
# Also catch markdown JSON blocks that look like face data
_JSON_BLOCK_RE = re.compile(
    r"```json\s*\{[^}]*(?:blendshape|face_data|expression|gaze|particle).*?\}[\s\S]*?```",
    re.DOTALL | re.IGNORECASE,
)
# Catch any remaining face_data / blendshape references in plain text
_INTERNAL_LEAKS_RE = re.compile(
    r"(?:ALITA_FACE_DATA|ALITA_CONTEXT|blendshape|mouthSmile_[LR]|cheekSquint_[LR]|"
    r"browOuterUp_[LR]|eyeSquint_[LR]|face_data|tts_engine_hint|"
    r"emotional_state_label|particle_system|glow_intensity|ser_confidence)[^\n]*",
    re.IGNORECASE,
)


def parse_alita_response(raw: str) -> tuple[str, dict]:
    """
    Parse an Alita LLM response — strip any internal blocks, return clean text.

    Returns:
        Tuple of (spoken_text, face_data_dict).
        face_data_dict is always {} now (generated separately by generate_face_data).
    """
    if not raw:
        return "", {}

    text = raw

    # Strip <ALITA_FACE_DATA> blocks
    text = _FACE_DATA_RE.sub("", text)

    # Strip <THINKING> blocks
    text = _THINKING_RE.sub("", text)

    # Strip JSON code blocks with face data
    text = _JSON_BLOCK_RE.sub("", text)

    # Strip any remaining internal data leaks
    text = _INTERNAL_LEAKS_RE.sub("", text)

    # Clean up whitespace
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    return text, {}


# ─────────────────────────────────────────────────────────────────────────────
# §4  FACE DATA GENERATOR — builds face_data from SER emotion (NOT from LLM)
# ─────────────────────────────────────────────────────────────────────────────

# Emotion → face data mapping (pre-computed, zero LLM overhead)
_EMOTION_FACE_MAP = {
    "neutral": {
        "expression": {"primary": "neutral", "intensity": 0.3},
        "blendshapes": {"mouthSmile_L": 0.15, "mouthSmile_R": 0.15},
        "particle_system": {"glow_intensity": 0.4, "pulse_speed": "slow", "color_temperature": "cool"},
        "emotional_state_label": "calm_presence",
    },
    "happy": {
        "expression": {"primary": "genuine_joy", "intensity": 0.7},
        "blendshapes": {"mouthSmile_L": 0.7, "mouthSmile_R": 0.7, "cheekSquint_L": 0.4, "cheekSquint_R": 0.4},
        "particle_system": {"glow_intensity": 0.7, "pulse_speed": "medium", "color_temperature": "warm"},
        "emotional_state_label": "shared_happiness",
    },
    "sad": {
        "expression": {"primary": "compassionate_concern", "intensity": 0.5},
        "blendshapes": {"mouthSmile_L": 0.3, "mouthSmile_R": 0.3, "browOuterUp_L": 0.2, "browOuterUp_R": 0.2},
        "particle_system": {"glow_intensity": 0.5, "pulse_speed": "slow", "color_temperature": "warm"},
        "emotional_state_label": "gentle_support",
    },
    "angry": {
        "expression": {"primary": "calm_understanding", "intensity": 0.4},
        "blendshapes": {"mouthSmile_L": 0.2, "mouthSmile_R": 0.2},
        "particle_system": {"glow_intensity": 0.45, "pulse_speed": "medium", "color_temperature": "cool"},
        "emotional_state_label": "patient_presence",
    },
    "fear": {
        "expression": {"primary": "reassuring_warmth", "intensity": 0.6},
        "blendshapes": {"mouthSmile_L": 0.4, "mouthSmile_R": 0.4, "browOuterUp_L": 0.15, "browOuterUp_R": 0.15},
        "particle_system": {"glow_intensity": 0.55, "pulse_speed": "slow", "color_temperature": "warm"},
        "emotional_state_label": "safe_anchor",
    },
    "surprise": {
        "expression": {"primary": "curious_engagement", "intensity": 0.6},
        "blendshapes": {"mouthSmile_L": 0.5, "mouthSmile_R": 0.5, "eyeSquint_L": 0.1, "eyeSquint_R": 0.1},
        "particle_system": {"glow_intensity": 0.6, "pulse_speed": "fast", "color_temperature": "bright"},
        "emotional_state_label": "engaged_curiosity",
    },
    "disgust": {
        "expression": {"primary": "understanding_nod", "intensity": 0.4},
        "blendshapes": {"mouthSmile_L": 0.15, "mouthSmile_R": 0.15},
        "particle_system": {"glow_intensity": 0.4, "pulse_speed": "slow", "color_temperature": "neutral"},
        "emotional_state_label": "empathic_acknowledgment",
    },
}


def generate_face_data(
    user_emotion: str = "neutral",
    confidence: float = 0.5,
    conversation_phase: str = "mid_conversation",
) -> dict:
    """
    Generate face_data dict from the SER emotion — zero LLM overhead.

    This replaces asking the LLM to generate ALITA_FACE_DATA JSON,
    which was slow and leaked internals into spoken text.
    """
    emotion_key = user_emotion.lower().strip()
    base = _EMOTION_FACE_MAP.get(emotion_key, _EMOTION_FACE_MAP["neutral"]).copy()

    # Deep copy nested dicts
    result = {
        "expression": {**base["expression"]},  # type: ignore[arg-type]
        "blendshapes": {**base["blendshapes"]},  # type: ignore[arg-type]
        "gaze": {"direction": "forward", "eye_contact": True, "focus_intensity": 0.7},
        "particle_system": {**base["particle_system"]},  # type: ignore[arg-type]
        "voice": {"tone": "warm", "pace": "normal", "warmth": 0.7},
        "emotional_state_label": base["emotional_state_label"],
        "user_emotion_detected": emotion_key,
        "ser_confidence": round(confidence, 2),  # type: ignore[call-overload]
        "conversation_phase": conversation_phase,
        "tts_engine_hint": "edge_tts",  # default; xtts_v2 for high-emotion
    }

    # Use XTTS for high-emotion responses (more expressive voice)
    if confidence > 0.7 and emotion_key in ("sad", "happy", "fear", "angry"):
        result["tts_engine_hint"] = "xtts_v2"

    return result
