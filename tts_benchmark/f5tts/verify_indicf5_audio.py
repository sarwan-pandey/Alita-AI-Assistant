import os
import sys
import numpy as np
import soundfile as sf
import librosa
from faster_whisper import WhisperModel

sys.stdout.reconfigure(encoding='utf-8')

whisper = WhisperModel('tiny', device='cpu', compute_type='float32')
samples_dir = 'tts_benchmark/f5tts/samples/indicf5_hinglish'
files = sorted([f for f in os.listdir(samples_dir) if f.endswith('.wav')])

print(f"=== Auditory & Intelligibility Evaluation of {len(files)} IndicF5-Hinglish WAVs ===")
for f in files:
    p = os.path.join(samples_dir, f)
    y, sr = librosa.load(p, sr=24000)
    dur = len(y) / sr
    f0, vf, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))
    f0_clean = f0[vf]
    mean_f0 = float(np.mean(f0_clean)) if len(f0_clean) > 0 else 0.0
    
    # Transcribe without forcing language so whisper detects what language was spoken
    segments, info = whisper.transcribe(p)
    text = ' '.join(s.text for s in segments).strip()
    
    gender = "Female" if mean_f0 > 165 else "Male"
    print(f"\n[{f}] Dur: {dur:.2f}s | Mean F0: {mean_f0:.1f} Hz ({gender}) | Detected: {info.language}")
    print(f"  Transcription: \"{text}\"")
