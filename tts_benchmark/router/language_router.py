"""
TTS Language Router — Chatterbox Turbo Unified Architecture
===========================================================
Unified single-engine router directing all synthesis to 'chatterbox_turbo'.
Chatterbox Turbo (350M neural) serves as the sole voice engine for English,
Hindi, Hinglish, and mixed code-switched audio with full paralinguistic tag
support ([laugh], [sigh], [cough]).
"""

import re
from typing import Literal, Tuple

EngineType = Literal["chatterbox_turbo"]

# 1. Devanagari Unicode Range (Hindi, Marathi, Sanskrit, etc.)
_RE_DEVANAGARI = re.compile(r"[\u0900-\u097F]")

# 2. Strong Hinglish Markers (unambiguous Hindi words in Latin script)
_STRONG_HINGLISH_WORDS = {
    "aap", "aapka", "aapki", "aapke", "aapko", "aapse",
    "main", "hum", "mera", "meri", "mere", "mujhe", "mujhse",
    "tum", "tumhara", "tumhari", "tumhare", "tujhe",
    "kya", "kyun", "kyon", "kaise", "kahan", "kisko", "kisse", "kab",
    "hain", "hoon", "hun", "tha", "thi",
    "hoga", "hogi", "honge", "hona", "hone",
    "karo", "karna", "karenge", "karega", "karegi", "karungi", "karunga",
    "karta", "karti", "karte", "kar", "kiye", "kiya",
    "boliye", "bataiye", "suniye", "dekho", "dekhna", "dekh",
    "raha", "rahi", "rahe", "sakta", "sakti", "sakte",
    "chahiye", "dena", "lena", "diya", "liya", "dijiye", "lijiye",
    "lekin", "magar", "kyunki", "isliye", "agar", "toh", "bhi",
    "aaj", "kal", "parson", "abhi", "phir", "bahut", "thoda",
    "theek", "shuru", "madad", "waqt", "shukriya", "dhanyawad", "namaste",
    "namaskar", "alvida", "zaroor", "bilkul", "matlab", "samjha", "samjhe",
    "achha", "achhi", "achhe", "bura", "buri", "suno", "bolo",
    "haan", "nahi",
}

_CONTEXTUAL_PARTICLES = {
    "ka", "ke", "ki", "ko", "se", "mein", "par", "pe", "aur", "ya"
}

_RE_WORD_SPLIT = re.compile(r"[^\w']+")


def detect_dialect(text: str) -> str:
    """Classifies input into 'devanagari_hindi', 'latin_hinglish', or 'english'."""
    if not text or not text.strip():
        return "english"

    raw = text.strip()
    if _RE_DEVANAGARI.search(raw):
        return "devanagari_hindi"

    words = [w.lower() for w in _RE_WORD_SPLIT.split(raw) if w]
    if not words:
        return "english"

    if any(w in _STRONG_HINGLISH_WORDS for w in words):
        return "latin_hinglish"

    particle_hits = [w for w in words if w in _CONTEXTUAL_PARTICLES]
    if len(particle_hits) >= 2:
        return "latin_hinglish"

    return "english"


def select_tts_engine(text: str) -> EngineType:
    """
    Deterministic router: Chatterbox Turbo is the sole unified TTS engine.
    All text (English, Hindi, Hinglish, mixed) routes directly to 'chatterbox_turbo'.
    """
    return "chatterbox_turbo"


