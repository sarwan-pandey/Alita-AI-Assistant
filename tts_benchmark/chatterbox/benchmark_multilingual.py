import os
import sys
import time
import csv
from pathlib import Path

# Force utf-8 stdout/stderr on Windows to handle Devanagari characters
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Prevent pkuseg from triggering slow/hanging Chinese segmenter downloads
sys.modules['spacy_pkuseg'] = None

import torch
import librosa
import soundfile as sf
import numpy as np
from safetensors.torch import load_file as load_safetensors

from chatterbox.mtl_tts import ChatterboxMultilingualTTS, Conditionals
from chatterbox.models.t3 import T3
from chatterbox.models.t3.modules.t3_config import T3Config
from chatterbox.models.s3gen import S3Gen
from chatterbox.models.voice_encoder import VoiceEncoder
from chatterbox.models.tokenizers import MTLTokenizer
from faster_whisper import WhisperModel

def load_multilingual_model(device: str = "cpu") -> ChatterboxMultilingualTTS:
    print(f"Loading Chatterbox Multilingual V3 on {device}...", flush=True)
    models_dir = Path("tts_benchmark/chatterbox/models/multilingual_v3")
    t3_path = models_dir / "t3_mtl23ls_v3.safetensors"
    
    # Locate cached companion files
    hf_cache = Path(os.path.expanduser("~/.cache/huggingface/hub"))
    cb_snap = hf_cache / "models--ResembleAI--chatterbox/snapshots/5bb1f6ee58e50c3b8d408bc82a6d3740c2db6e18"
    hi_snap = hf_cache / "models--ResembleAI--Chatterbox-Multilingual-hi/snapshots/82ca71273cc2a9ab19efdf8315f865c1a5af0ee7"
    
    ve_path = cb_snap / "ve.safetensors"
    s3gen_path = cb_snap / "s3gen.safetensors"
    tok_path = hi_snap / "grapheme_mtl_merged_expanded_v1.json"
    
    print(f" - T3 Checkpoint: {t3_path}", flush=True)
    print(f" - S3Gen Checkpoint: {s3gen_path}", flush=True)
    print(f" - VoiceEncoder: {ve_path}", flush=True)
    print(f" - MTL Tokenizer: {tok_path}", flush=True)
    
    # 1. Voice Encoder
    ve = VoiceEncoder()
    ve.load_state_dict(load_safetensors(ve_path))
    ve.to(device).eval()
    
    # 2. T3 Multilingual
    t3_cfg = T3Config.multilingual()
    t3 = T3(t3_cfg)
    t3_state = load_safetensors(t3_path)
    if "model" in t3_state.keys():
        t3_state = t3_state["model"][0]
    t3.load_state_dict(t3_state)
    t3.to(device).eval()
    
    # 3. S3Gen
    s3gen = S3Gen()
    s3gen.load_state_dict(load_safetensors(s3gen_path), strict=False)
    s3gen.to(device).eval()
    
    # 4. MTL Tokenizer
    tokenizer = MTLTokenizer(str(tok_path))
    
    model = ChatterboxMultilingualTTS(t3, s3gen, ve, tokenizer, device)
    print("Chatterbox Multilingual V3 model loaded successfully.", flush=True)
    return model

def analyze_audio(wav_path: str):
    y, sr = librosa.load(wav_path, sr=None)
    duration = len(y) / sr
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), sr=sr
    )
    f0_clean = f0[~np.isnan(f0)]
    mean_pitch = float(np.mean(f0_clean)) if len(f0_clean) > 0 else 0.0
    return duration, mean_pitch

def run_benchmark():
    device = "cpu"
    model = load_multilingual_model(device=device)
    
    ref_voice = Path("backend/voices/default/alita_en_original.wav")
    print(f"Conditioning reference voice: {ref_voice} (Female MJ Assistant voice)", flush=True)
    model.prepare_conditionals(str(ref_voice), exaggeration=0.5)
    
    output_dir = Path("tts_benchmark/chatterbox/samples/multilingual")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    test_cases = [
        ("H1", "नमस्ते! मैं एमजे हूँ, आपकी पर्सनल एआई असिस्टेंट।", "hi"),
        ("H2", "आज मौसम बहुत अच्छा है, चलिए आज का काम शुरू करते हैं।", "hi"),
        ("L1", "Aaj mujhe thoda kaam karna hai aur ek naya project shuru karna hai.", "hi"),
        ("L2", "Aap kaise hain? Kya hum meeting shuru karein?", "hi"),
        ("M1", "Aaj hamara project deployment ke liye ready hai.", "hi"),
        ("M2", "Server connection check karo aur database logs verify karo.", "hi"),
        ("E1", "The database query failed because the connection pool timed out.", "en"),
    ]
    
    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    
    results = []
    
    print("\n--- Starting Multilingual Benchmark ---", flush=True)
    for test_id, text, lang_id in test_cases:
        print(f"\n[{test_id}] Text: '{text}' (lang={lang_id})", flush=True)
        
        # Generation with timing
        t0 = time.time()
        wav = model.generate(
            text=text,
            language_id=lang_id,
            exaggeration=0.5,
            cfg_weight=0.5,
            temperature=0.8,
            repetition_penalty=2.0
        )
        latency = time.time() - t0
        
        # Save output WAV
        wav_np = wav.squeeze(0).cpu().numpy()
        out_path = output_dir / f"{test_id}.wav"
        sf.write(str(out_path), wav_np, model.sr)
        
        # Analyze audio
        duration, mean_pitch = analyze_audio(str(out_path))
        rtf = latency / duration if duration > 0 else 0.0
        
        # Transcribe with Whisper
        segments, info = whisper_model.transcribe(str(out_path))
        transcription = " ".join(s.text for s in segments).strip()
        detected_lang = info.language
        
        print(f" -> Duration: {duration:.2f}s | Latency: {latency:.2f}s | RTF: {rtf:.2f}x | Pitch: {mean_pitch:.1f}Hz", flush=True)
        print(f" -> Whisper ({detected_lang}): '{transcription}'", flush=True)
        
        results.append({
            "test_id": test_id,
            "exact_input": text,
            "language_id": lang_id,
            "output_wav": str(out_path),
            "duration_s": round(duration, 2),
            "generation_latency_s": round(latency, 2),
            "rtf": round(rtf, 2),
            "mean_pitch_hz": round(mean_pitch, 1),
            "detected_lang": detected_lang,
            "transcription": transcription,
        })
        
    # Save results to CSV
    csv_path = Path("tts_benchmark/results/chatterbox_multilingual_benchmark.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "test_id", "exact_input", "language_id", "output_wav",
            "duration_s", "generation_latency_s", "rtf", "mean_pitch_hz",
            "detected_lang", "transcription"
        ])
        writer.writeheader()
        writer.writerows(results)
        
    print(f"\nAll benchmark results saved to {csv_path}", flush=True)

if __name__ == "__main__":
    run_benchmark()
