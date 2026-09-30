import os
import sys
import numpy as np
import soundfile as sf
import librosa
from faster_whisper import WhisperModel

sys.stdout.reconfigure(encoding='utf-8')

whisper = WhisperModel('tiny', device='cpu', compute_type='float32')
samples_dir = 'tts_benchmark/chatterbox/samples'
files = sorted([f for f in os.listdir(samples_dir) if f.startswith('s') and f.endswith('.wav')])

print(f"=== Auditory & Intelligibility Evaluation of {len(files)} Chatterbox WAVs ===")
for f in files:
    p = os.path.join(samples_dir, f)
    y, sr = librosa.load(p, sr=24000)
    dur = len(y) / sr
    f0, vf, _ = librosa.pyin(y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'))
    f0_clean = f0[vf]
    mean_f0 = float(np.mean(f0_clean)) if len(f0_clean) > 0 else 0.0
    
    segments, _ = whisper.transcribe(p)
    text = ' '.join(s.text for s in segments).strip()
    
    gender = "Female" if mean_f0 > 165 else "Male"
    print(f"[{f}] Dur: {dur:.2f}s | Mean F0: {mean_f0:.1f} Hz ({gender})")
    print(f"  Transcription: \"{text}\"")
