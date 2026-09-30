import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import librosa
import numpy as np
from pathlib import Path
from faster_whisper import WhisperModel

def verify():
    samples_dir = Path("tts_benchmark/chatterbox/samples/multilingual")
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    
    test_cases = [
        ("H1", "नमस्ते! मैं एमजे हूँ, आपकी पर्सनल एआई असिस्टेंट।"),
        ("H2", "आज मौसम बहुत अच्छा है, चलिए आज का काम शुरू करते हैं।"),
        ("L1", "Aaj mujhe thoda kaam karna hai aur ek naya project shuru karna hai."),
        ("L2", "Aap kaise hain? Kya hum meeting shuru karein?"),
        ("M1", "Aaj hamara project deployment ke liye ready hai."),
        ("M2", "Server connection check karo aur database logs verify karo."),
        ("E1", "The database query failed because the connection pool timed out."),
    ]
    
    for test_id, original_text in test_cases:
        wav_path = samples_dir / f"{test_id}.wav"
        if not wav_path.exists():
            print(f"Missing {wav_path}")
            continue
            
        y, sr = librosa.load(str(wav_path), sr=None)
        dur = len(y) / sr
        rms = float(np.sqrt(np.mean(y**2)))
        peak = float(np.max(np.abs(y)))
        
        # Pitch analysis
        f0, voiced_flag, voiced_probs = librosa.pyin(
            y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), sr=sr
        )
        f0_clean = f0[~np.isnan(f0)]
        mean_pitch = float(np.mean(f0_clean)) if len(f0_clean) > 0 else 0.0
        pitch_std = float(np.std(f0_clean)) if len(f0_clean) > 0 else 0.0
        
        # Spectral centroids (brightness / robotic metallicness)
        cent = librosa.feature.spectral_centroid(y=y, sr=sr)
        mean_cent = float(np.mean(cent))
        
        # Whisper transcriptions
        seg_auto, info_auto = whisper_model.transcribe(str(wav_path))
        text_auto = " ".join(s.text for s in seg_auto).strip()
        
        seg_hi, _ = whisper_model.transcribe(str(wav_path), language="hi")
        text_hi = " ".join(s.text for s in seg_hi).strip()
        
        print(f"[{test_id}] Original: '{original_text}'")
        print(f"  Duration: {dur:.2f}s | Mean F0: {mean_pitch:.1f}Hz (std: {pitch_std:.1f}Hz) | Centroid: {mean_cent:.0f}Hz")
        print(f"  RMS: {rms:.4f} | Peak: {peak:.4f}")
        print(f"  Whisper Auto ({info_auto.language}): '{text_auto}'")
        print(f"  Whisper Hindi: '{text_hi}'\n")

if __name__ == "__main__":
    verify()
