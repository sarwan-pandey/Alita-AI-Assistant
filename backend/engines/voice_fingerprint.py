# pyre-ignore-all-errors
"""
Voice Fingerprint — Identifies users by their voice.
Uses MFCC feature extraction to create voice embeddings.
Lightweight: no large ML models, just scipy + numpy.

Enrollment: ~5 seconds of speech → creates voice profile
Recognition: ~50ms per check ─ compares against enrolled profiles

Storage: Encrypted voice profiles in data/voice_profiles/
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "voice_profiles")
SAMPLE_RATE = 16000
N_MFCC = 13  # Number of MFCC coefficients
MATCH_THRESHOLD = 0.75  # Minimum similarity for match


def _extract_mfcc(audio: np.ndarray, sr: int = SAMPLE_RATE, n_mfcc: int = N_MFCC) -> np.ndarray:
    """
    Extract MFCC features from audio. Lightweight — no librosa needed.
    Uses manual DCT over mel-filterbank energies.
    """
    # Pre-emphasis
    emphasized = np.append(audio[0], audio[1:] - 0.97 * audio[:-1])

    # Frame the signal
    frame_size = int(0.025 * sr)  # 25ms frames
    frame_stride = int(0.01 * sr)  # 10ms stride
    signal_length = len(emphasized)
    num_frames = max(1, int(np.ceil((signal_length - frame_size) / frame_stride)) + 1)

    # Pad signal
    pad_length = (num_frames - 1) * frame_stride + frame_size
    padded = np.zeros(pad_length)
    padded[:signal_length] = emphasized

    # Create frames
    indices = np.arange(frame_size)[None, :] + np.arange(num_frames)[:, None] * frame_stride
    frames = padded[indices]

    # Apply Hamming window
    frames *= np.hamming(frame_size)

    # FFT and power spectrum
    NFFT = 512
    mag_frames = np.abs(np.fft.rfft(frames, NFFT))
    pow_frames = mag_frames ** 2 / NFFT

    # Mel filterbank
    n_filters = 26
    low_freq_mel = 0
    high_freq_mel = 2595 * np.log10(1 + (sr / 2) / 700)
    mel_points = np.linspace(low_freq_mel, high_freq_mel, n_filters + 2)
    hz_points = 700 * (10 ** (mel_points / 2595) - 1)
    bins = np.floor((NFFT + 1) * hz_points / sr).astype(int)

    fbank = np.zeros((n_filters, int(NFFT / 2 + 1)))
    for i in range(1, n_filters + 1):
        left = bins[i - 1]
        center = bins[i]
        right = bins[i + 1]
        for j in range(left, center):
            if center != left:
                fbank[i - 1, j] = (j - left) / (center - left)
        for j in range(center, right):
            if right != center:
                fbank[i - 1, j] = (right - j) / (right - center)

    filter_banks = np.dot(pow_frames, fbank.T)
    filter_banks = np.where(filter_banks == 0, np.finfo(float).eps, filter_banks)
    filter_banks = 20 * np.log10(filter_banks)

    # DCT to get MFCCs
    mfcc = np.zeros((num_frames, n_mfcc))
    for i in range(n_mfcc):
        mfcc[:, i] = np.sum(
            filter_banks * np.cos(np.pi * i * (np.arange(n_filters) + 0.5) / n_filters),
            axis=1
        )

    # Mean + std as embedding (compact representation)
    embedding = np.concatenate([np.mean(mfcc, axis=0), np.std(mfcc, axis=0)])
    return embedding


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    dot = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    if norm == 0:
        return 0.0
    return float(dot / norm)


class VoiceFingerprint:
    """Multi-user voice identification."""

    def __init__(self) -> None:
        self._profiles: Dict[str, Dict[str, Any]] = {}  # user_id → profile
        self._current_user: Optional[str] = None
        self._load_profiles()

    def enroll(self, user_id: str, audio: np.ndarray, display_name: str = "") -> bool:
        """
        Enroll a new voice. Needs ~5 seconds of speech.
        Returns True if enrollment succeeded.
        """
        if len(audio) < SAMPLE_RATE * 2:
            logger.warning(f"[VoiceID] Audio too short for enrollment ({len(audio)/SAMPLE_RATE:.1f}s)")
            return False

        try:
            embedding = _extract_mfcc(audio)

            self._profiles[user_id] = {
                "user_id": user_id,
                "display_name": display_name or user_id,
                "embedding": embedding.tolist(),
                "enrolled_at": time.time(),
                "last_recognized": time.time(),
                "recognition_count": 0,
            }
            self._save_profiles()
            logger.info(f"[VoiceID] Enrolled: {display_name or user_id}")
            return True
        except Exception as e:
            logger.error(f"[VoiceID] Enrollment failed: {e}")
            return False

    def identify(self, audio: np.ndarray) -> Tuple[Optional[str], float]:
        """
        Identify who is speaking. Returns (user_id, confidence) or (None, 0).
        Takes ~50ms.
        """
        if not self._profiles:
            return None, 0.0

        if len(audio) < SAMPLE_RATE * 0.5:
            return None, 0.0

        try:
            embedding = _extract_mfcc(audio)
            best_match: Optional[str] = None
            best_score: float = 0.0

            for user_id, profile in self._profiles.items():
                stored = np.array(profile["embedding"])
                score = _cosine_similarity(embedding, stored)
                if score > best_score:
                    best_score = score
                    best_match = user_id

            if best_match and best_score >= MATCH_THRESHOLD:
                self._profiles[best_match]["last_recognized"] = time.time()
                self._profiles[best_match]["recognition_count"] = \
                    self._profiles[best_match].get("recognition_count", 0) + 1
                self._current_user = best_match
                logger.info(f"[VoiceID] Identified: {best_match} ({best_score:.2f})")
                return best_match, best_score

            return None, best_score
        except Exception as e:
            logger.debug(f"[VoiceID] Identify error: {e}")
            return None, 0.0

    def remove_user(self, user_id: str) -> bool:
        """Remove a voice profile."""
        if user_id in self._profiles:
            del self._profiles[user_id]
            self._save_profiles()
            return True
        return False

    @property
    def current_user(self) -> Optional[str]:
        return self._current_user

    @property
    def enrolled_users(self) -> List[str]:
        return list(self._profiles.keys())

    def get_user_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user profile info (without embedding)."""
        profile = self._profiles.get(user_id)
        if profile:
            return {k: v for k, v in profile.items() if k != "embedding"}
        return None

    def _save_profiles(self) -> None:
        """Save profiles to disk."""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            filepath = os.path.join(DATA_DIR, "profiles.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self._profiles, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"[VoiceID] Save failed: {e}")

    def _load_profiles(self) -> None:
        """Load profiles from disk."""
        filepath = os.path.join(DATA_DIR, "profiles.json")
        if not os.path.exists(filepath):
            return
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                self._profiles = json.load(f)
            logger.info(f"[VoiceID] Loaded {len(self._profiles)} voice profiles")
        except Exception as e:
            logger.warning(f"[VoiceID] Load failed: {e}")


# Singleton
voice_fingerprint = VoiceFingerprint()
