"""
Audio Intelligence — Sound classification, noise suppression, emergency detection.

Three parallel processors for real-time audio analysis:
  1. Noise Suppressor   — Cleans audio for better STT (~5ms, CPU)
  2. Sound Classifier   — YAMNet TFLite for 521 sound categories (~10ms, CPU)
  3. Emergency Detector — Watches classifier output for danger sounds

All processors are NON-BLOCKING — they run in thread executors
and never delay the main speech pipeline.
"""

import os
import time
import logging
import threading
import numpy as np  # type: ignore[import]
from typing import Optional
from collections import deque

log = logging.getLogger("alita.audio_intel")

# ─────────────────────────────────────────────────────────────────────────────
# NOISE SUPPRESSOR — clean audio for better STT
# ─────────────────────────────────────────────────────────────────────────────

_noisereduce = None
_nr_available = None


def _load_noisereduce():
    """Lazy-load noisereduce to avoid import cost at startup."""
    global _noisereduce, _nr_available
    if _nr_available is not None:
        return _nr_available
    try:
        import noisereduce as nr  # type: ignore[import]
        _noisereduce = nr
        _nr_available = True
        log.info("[AudioIntel] noisereduce loaded successfully")
        return True
    except ImportError:
        _nr_available = False
        log.warning("[AudioIntel] noisereduce not installed — noise suppression disabled. "
                    "Install with: pip install noisereduce")
        return False


def suppress_noise(pcm_array: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    """
    Remove background noise from audio while preserving speech.
    Returns cleaned audio. If noisereduce is unavailable, returns original.

    Performance: ~5ms for 1 second of audio on CPU.
    """
    if not _load_noisereduce():
        return pcm_array

    try:
        # Stationary noise reduction — fast, effective for constant background
        assert _noisereduce is not None
        cleaned = _noisereduce.reduce_noise(  # type: ignore[union-attr]
            y=pcm_array,
            sr=sample_rate,
            stationary=True,
            prop_decrease=0.75,  # 75% noise reduction (preserve some naturalness)
            n_fft=512,           # Smaller FFT = faster processing
            hop_length=256,
        )
        return cleaned.astype(np.float32)
    except Exception as e:
        log.warning("[AudioIntel] Noise suppression failed: %s", e)
        return pcm_array


# ─────────────────────────────────────────────────────────────────────────────
# YAMNET SOUND CLASSIFIER — 521 audio event categories
# ─────────────────────────────────────────────────────────────────────────────

_yamnet_model = None
_yamnet_labels = None
_yamnet_available = None
_yamnet_lock = threading.Lock()

# YAMNet model and label file paths
_MODEL_DIR = os.path.join(os.path.dirname(__file__), "..", "models", "yamnet")
_MODEL_PATH = os.path.join(_MODEL_DIR, "yamnet.tflite")
_LABELS_PATH = os.path.join(_MODEL_DIR, "yamnet_labels.txt")


def _ensure_yamnet_model():
    """Download YAMNet TFLite model if not present."""
    os.makedirs(_MODEL_DIR, exist_ok=True)

    if not os.path.exists(_MODEL_PATH):
        log.info("[YAMNet] Downloading TFLite model (~3MB)...")
        try:
            import urllib.request
            model_url = "https://tfhub.dev/google/lite-model/yamnet/tflite/1?lite-format=tflite"
            # Direct download URL for the TFLite model
            alt_url = "https://storage.googleapis.com/tfhub-lite-models/google/lite-model/yamnet/tflite/1.tflite"
            urllib.request.urlretrieve(alt_url, _MODEL_PATH)
            log.info("[YAMNet] Model downloaded to %s", _MODEL_PATH)
        except Exception as e:
            log.error("[YAMNet] Failed to download model: %s", e)
            return False

    if not os.path.exists(_LABELS_PATH):
        log.info("[YAMNet] Downloading label file...")
        try:
            import urllib.request
            labels_url = "https://raw.githubusercontent.com/tensorflow/models/master/research/audioset/yamnet/yamnet_class_map.csv"
            urllib.request.urlretrieve(labels_url, _LABELS_PATH)
            log.info("[YAMNet] Labels downloaded to %s", _LABELS_PATH)
        except Exception as e:
            log.error("[YAMNet] Failed to download labels: %s", e)
            # Create a minimal labels file from known classes
            _create_fallback_labels()

    return os.path.exists(_MODEL_PATH)


def _create_fallback_labels():
    """Create minimal label file with emergency-relevant classes."""
    # These are the most important YAMNet classes (indices from the full 521-class model)
    labels = [
        "Speech", "Child speech", "Conversation", "Narration",
        "Babbling", "Whispering", "Laughter", "Crying", "Screaming",
        "Sigh", "Singing", "Music", "Musical instrument",
        "Dog", "Cat", "Bird", "Alarm", "Siren", "Car horn",
        "Engine", "Train", "Aircraft", "Gunshot", "Explosion",
        "Glass break", "Door", "Knock", "Telephone", "Doorbell",
        "Rain", "Thunder", "Wind", "Water", "Fire",
        "Typing", "Applause", "Crowd", "Silence",
    ]
    with open(_LABELS_PATH, "w") as f:
        for label in labels:
            f.write(f"{label}\n")


def _load_yamnet():
    """Lazy-load YAMNet TFLite model."""
    global _yamnet_model, _yamnet_labels, _yamnet_available

    if _yamnet_available is not None:
        return _yamnet_available

    with _yamnet_lock:
        if _yamnet_available is not None:
            return _yamnet_available

        try:
            # Try tflite_runtime first (smaller install)
            try:
                from tflite_runtime.interpreter import Interpreter  # type: ignore[import]
            except ImportError:
                # Fall back to full TensorFlow
                try:
                    import tensorflow as tf  # type: ignore[import]
                    Interpreter = tf.lite.Interpreter
                except ImportError:
                    log.warning("[YAMNet] Neither tflite-runtime nor tensorflow installed. "
                                "Install with: pip install tflite-runtime")
                    _yamnet_available = False
                    return False

            if not _ensure_yamnet_model():
                _yamnet_available = False
                return False

            # Load model
            interpreter = Interpreter(model_path=_MODEL_PATH)
            interpreter.allocate_tensors()
            _yamnet_model = interpreter

            # Load labels
            _yamnet_labels = []
            if os.path.exists(_LABELS_PATH):
                with open(_LABELS_PATH, "r") as f:
                    content = f.read().strip()
                    # Handle CSV format (display_name is last column)
                    for line in content.split("\n"):
                        if "," in line:
                            parts = line.split(",")
                            _yamnet_labels.append(parts[-1].strip().strip('"'))
                        else:
                            _yamnet_labels.append(line.strip())
                # Remove header if present
                if _yamnet_labels and _yamnet_labels[0].lower() == "display_name":
                    _yamnet_labels = _yamnet_labels[1:]  # type: ignore[index]

            _yamnet_available = True
            log.info("[YAMNet] Loaded: %d classes, model ready", len(_yamnet_labels))
            return True

        except Exception as e:
            log.error("[YAMNet] Failed to load: %s", e)
            _yamnet_available = False
            return False


def classify_sounds(pcm_array: np.ndarray, sample_rate: int = 16000,
                    top_k: int = 5) -> list[dict]:
    """
    Classify audio using YAMNet.
    Returns top-k detected sounds: [{"label": "Music", "confidence": 0.87}, ...]

    Performance: ~10ms for 1 second of audio on CPU.
    """
    if not _load_yamnet():
        return []

    try:
        # YAMNet expects mono float32 at 16kHz
        if pcm_array.dtype != np.float32:
            pcm_array = pcm_array.astype(np.float32)

        # Normalize to [-1, 1]
        max_val = np.abs(pcm_array).max()
        if max_val > 0:
            pcm_array = pcm_array / max_val

        # Resample if needed (YAMNet expects 16kHz)
        if sample_rate != 16000:
            try:
                from scipy import signal  # type: ignore[import]
                num_samples = int(len(pcm_array) * 16000 / sample_rate)
                pcm_array = signal.resample(pcm_array, num_samples).astype(np.float32)
            except ImportError:
                log.warning("[YAMNet] scipy not available for resampling")
                return []

        # Run inference
        assert _yamnet_model is not None
        input_details = _yamnet_model.get_input_details()  # type: ignore[union-attr]
        output_details = _yamnet_model.get_output_details()  # type: ignore[union-attr]

        # Check expected input shape
        input_shape = input_details[0]["shape"]
        expected_len = input_shape[-1] if len(input_shape) > 1 else input_shape[0]

        # Pad or trim to expected length
        if len(pcm_array) < expected_len:
            pcm_array = np.pad(pcm_array, (0, expected_len - len(pcm_array)))
        elif len(pcm_array) > expected_len:
            pcm_array = pcm_array[:expected_len]

        pcm_array = pcm_array.reshape(input_shape)
        _yamnet_model.set_tensor(input_details[0]["index"], pcm_array)  # type: ignore[union-attr]
        _yamnet_model.invoke()  # type: ignore[union-attr]

        # Get scores
        scores = _yamnet_model.get_tensor(output_details[0]["index"])  # type: ignore[union-attr]
        if len(scores.shape) > 1:
            scores = scores.mean(axis=0)  # average over time frames

        # Get top-k
        top_indices = np.argsort(scores)[-top_k:][::-1]
        results = []
        for idx in top_indices:
            if idx < len(_yamnet_labels) and scores[idx] > 0.1:  # type: ignore[arg-type]  # min threshold
                results.append({
                    "label": _yamnet_labels[idx],  # type: ignore[index]
                    "confidence": float(scores[idx]),  # type: ignore[arg-type]
                    "class_id": int(idx),
                })

        return results

    except Exception as e:
        log.warning("[YAMNet] Classification failed: %s", e)
        return []


# ─────────────────────────────────────────────────────────────────────────────
# ENVIRONMENT SUMMARY — human-readable for LLM context
# ─────────────────────────────────────────────────────────────────────────────

# Group YAMNet labels into human-friendly categories
SOUND_CATEGORIES = {
    "music": {"Music", "Singing", "Musical instrument", "Guitar", "Piano",
              "Drum", "Plucked string instrument", "Hip hop music", "Pop music",
              "Rock music", "Electronic music", "Jazz", "Classical music"},
    "people": {"Speech", "Child speech", "Conversation", "Laughter", "Crying",
               "Babbling", "Crowd", "Applause", "Chatter", "Whispering"},
    "animals": {"Dog", "Cat", "Bird", "Bark", "Meow", "Chirp", "Rooster",
                "Insects", "Frog"},
    "alerts": {"Alarm", "Telephone", "Doorbell", "Knock", "Bell",
               "Ringtone", "Buzzer", "Beep"},
    "transport": {"Car horn", "Engine", "Vehicle", "Train", "Aircraft",
                  "Motorcycle", "Bus", "Truck", "Helicopter"},
    "weather": {"Rain", "Thunder", "Wind", "Water"},
    "domestic": {"Typing", "Door", "Dishes", "Cutlery", "Microwave",
                 "Clock", "Keys jangling", "Drawer"},
}


def get_environment_summary(sounds: list[dict], min_confidence: float = 0.3) -> str:
    """
    Convert raw classification results into a natural sentence for the LLM.
    """
    if not sounds:
        return ""

    filtered = [s for s in sounds if s["confidence"] >= min_confidence]
    if not filtered:
        return ""

    # Skip if only speech (that's just the user talking)
    non_speech = [s for s in filtered if s["label"] not in {"Speech", "Conversation", "Narration"}]
    if not non_speech:
        return ""

    labels = [s["label"] for s in non_speech[:3]]  # type: ignore[index]
    return ", ".join(labels)


# ─────────────────────────────────────────────────────────────────────────────
# EMERGENCY DETECTION — watches for danger sounds
# ─────────────────────────────────────────────────────────────────────────────

# Sounds that trigger emergency response
EMERGENCY_SOUNDS = {
    # CRITICAL — auto-record immediately
    "critical": {
        "Gunshot, gunfire": 0.7,
        "Gunshot": 0.7,
        "Explosion": 0.7,
        "Fire alarm": 0.6,
        "Smoke detector": 0.6,
        "Glass break": 0.7,
        "Shatter": 0.7,
    },
    # WARNING — alert user, prepare to record
    "warning": {
        "Screaming": 0.6,
        "Scream": 0.6,
        "Crying, sobbing": 0.6,
        "Crying": 0.6,
        "Siren": 0.5,
        "Car crash": 0.7,
        "Crash": 0.7,
        "Thud": 0.6,
    },
}


class EmergencyDetector:
    """
    Watches for emergency sounds in classifier output.
    Requires 2+ consecutive detections to prevent false positives.
    """

    def __init__(self):
        self.consecutive_detections: dict[str, int] = {}  # sound → count
        self.last_check_time = 0.0
        self.active_emergency: Optional[dict] = None
        self.detection_history: deque = deque(maxlen=50)
        self._lock = threading.Lock()

    def check(self, sounds: list[dict]) -> Optional[dict]:
        """
        Check classifier output for emergency sounds.
        Returns emergency dict if detected, None otherwise.

        Emergency dict: {
            "level": "critical" | "warning",
            "sound": "Gunshot",
            "confidence": 0.85,
            "consecutive": 3,
        }
        """
        with self._lock:
            current_detections = set()

            for sound in sounds:
                label = sound["label"]
                confidence = sound["confidence"]

                # Check critical sounds
                for emergency_label, min_conf in EMERGENCY_SOUNDS.get("critical", {}).items():
                    if label.lower() in emergency_label.lower() or emergency_label.lower() in label.lower():
                        if confidence >= min_conf:
                            current_detections.add(label)
                            self.consecutive_detections[label] = \
                                self.consecutive_detections.get(label, 0) + 1

                            if self.consecutive_detections[label] >= 2:
                                emergency = {
                                    "level": "critical",
                                    "sound": label,
                                    "confidence": confidence,
                                    "consecutive": self.consecutive_detections[label],
                                    "time": time.time(),
                                }
                                self.active_emergency = emergency
                                self.detection_history.append(emergency)
                                log.critical(
                                    "🚨 EMERGENCY DETECTED: %s (%.0f%%, %d consecutive)",
                                    label, confidence * 100,
                                    self.consecutive_detections[label]
                                )
                                return emergency

                # Check warning sounds
                for emergency_label, min_conf in EMERGENCY_SOUNDS.get("warning", {}).items():
                    if label.lower() in emergency_label.lower() or emergency_label.lower() in label.lower():  # type: ignore[union-attr]
                        if confidence >= min_conf:
                            current_detections.add(label)
                            self.consecutive_detections[label] = \
                                self.consecutive_detections.get(label, 0) + 1

                            if self.consecutive_detections[label] >= 3:  # more conservative
                                emergency = {
                                    "level": "warning",
                                    "sound": label,
                                    "confidence": confidence,
                                    "consecutive": self.consecutive_detections[label],
                                    "time": time.time(),
                                }
                                self.active_emergency = emergency
                                self.detection_history.append(emergency)
                                log.warning(
                                    "⚠️ WARNING SOUND: %s (%.0f%%, %d consecutive)",
                                    label, confidence * 100,  # type: ignore[operator]
                                    self.consecutive_detections[label]
                                )
                                return emergency

            # Reset counters for sounds NOT detected this cycle
            for label in list(self.consecutive_detections.keys()):
                if label not in current_detections:
                    self.consecutive_detections[label] = 0

            return None

    def clear_emergency(self):
        """Clear active emergency (user confirmed they're okay)."""
        with self._lock:
            self.active_emergency = None
            self.consecutive_detections.clear()
            log.info("Emergency cleared by user")


# Global emergency detector instance
emergency_detector = EmergencyDetector()


# ─────────────────────────────────────────────────────────────────────────────
# PARALLEL AUDIO PROCESSOR — runs all 3 pipelines without blocking
# ─────────────────────────────────────────────────────────────────────────────

class AudioIntelligenceResult:
    """Result from parallel audio processing."""
    __slots__ = ("clean_audio", "sounds", "emergency", "processing_time_ms")

    def __init__(self):
        self.clean_audio: Optional[np.ndarray] = None
        self.sounds: list[dict] = []
        self.emergency: Optional[dict] = None
        self.processing_time_ms: float = 0.0


def process_audio_chunk(
    pcm_array: np.ndarray,
    sample_rate: int = 16000,
    classify: bool = True,
) -> AudioIntelligenceResult:
    """
    Process an audio chunk through all three pipelines IN PARALLEL:
      1. Noise suppression (for STT)
      2. Sound classification (on raw audio)
      3. Emergency detection (from classifier output)

    This function runs synchronously but can be called from a thread executor.
    Total time: ~15ms CPU (all three run sequentially within the thread,
    but the entire function runs in a separate thread from the main pipeline).
    """
    start = time.perf_counter()
    result = AudioIntelligenceResult()

    # 1. Noise suppression (~5ms)
    result.clean_audio = suppress_noise(pcm_array, sample_rate)

    # 2. Sound classification on RAW audio (~10ms)
    if classify:
        result.sounds = classify_sounds(pcm_array, sample_rate)

        # 3. Emergency check (instant — just checks the classification results)
        if result.sounds:
            result.emergency = emergency_detector.check(result.sounds)

    result.processing_time_ms = (time.perf_counter() - start) * 1000
    return result
