"""
Chatterbox English Benchmark (12 Assistant Sentences)
====================================================
Benchmarks ChatterboxTTS conditioned on MJ's female reference voice (alita_en_original.wav).
- Measures inference latency, audio duration, and Real-Time Factor (RTF).
- Saves output WAV files to tts_benchmark/chatterbox/samples/
- Writes CSV metrics to tts_benchmark/results/chatterbox_benchmark.csv
"""

import os
import sys
import time
import csv
from pathlib import Path

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import torch
import soundfile as sf

BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent.parent
SAMPLES_DIR = BENCHMARK_DIR / "samples"
RESULTS_DIR = BENCHMARK_DIR.parent / "results"

# Explicitly use female reference voice
REF_WAV = PROJECT_ROOT / "backend" / "voices" / "default" / "alita_en_original.wav"

SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

SENTENCES = [
    ("S01", "Hello! I am MJ, your personal AI assistant. How can I help you today?"),
    ("S02", "The database query failed because the connection pool timed out after thirty seconds."),
    ("S03", "I completely understand how frustrating that bug can be. Take a deep breath, and let us solve it together."),
    ("S04", "Would you like me to push these changes to staging, or should we run the test suite first?"),
    ("S05", "Yesterday we optimized the audio pipeline, and today our latency is down by forty percent."),
    ("S06", "Got it. I am on it right now."),
    ("S07", "Memory usage peaked at 3.4 gigabytes across 12 worker threads, with an average latency of 85 milliseconds."),
    ("S08", "First, stop the running container. Next, rebuild the Docker image, and finally restart the service."),
    ("S09", "That is actually pretty clever! I probably would not have thought of doing it that way."),
    ("S10", "Warning: CPU utilization has exceeded 90 percent on the primary node."),
    ("S11", "The main problem is the database connection, not the network configuration."),
    ("S12", "Looking at the architecture, separating the English and Hindi synthesis pipelines gives us much better control."),
]


def run_benchmark():
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"=== Initializing ChatterboxTTS on device: {device} ===", flush=True)
    t_load_start = time.perf_counter()

    from chatterbox.tts import ChatterboxTTS

    model = ChatterboxTTS.from_pretrained(device=device)
    load_time = time.perf_counter() - t_load_start
    print(f"[OK] ChatterboxTTS model loaded in {load_time:.2f}s", flush=True)

    print(f"Conditioning on female reference voice: {REF_WAV}", flush=True)
    assert REF_WAV.exists(), f"Reference WAV not found: {REF_WAV}"
    model.prepare_conditionals(str(REF_WAV), exaggeration=0.5)
    print("[OK] Voice conditioning prepared.", flush=True)

    results = []
    csv_file = RESULTS_DIR / "chatterbox_benchmark.csv"

    print(f"\n--- Synthesizing {len(SENTENCES)} Sentences ---", flush=True)
    for sid, text in SENTENCES:
        print(f"\n[{sid}] {text}", flush=True)
        t0 = time.perf_counter()

        wav_tensor = model.generate(
            text,
            repetition_penalty=1.2,
            min_p=0.05,
            top_p=1.0,
            exaggeration=0.5,
            cfg_weight=0.5,
            temperature=0.75,
        )
        gen_time = time.perf_counter() - t0

        wav_np = wav_tensor.squeeze().detach().cpu().numpy()
        sample_rate = model.sr
        audio_dur = len(wav_np) / sample_rate
        rtf = gen_time / audio_dur if audio_dur > 0 else 0

        out_path = SAMPLES_DIR / f"{sid.lower()}.wav"
        sf.write(str(out_path), wav_np, sample_rate, subtype="PCM_16")

        print(f"  -> Audio: {audio_dur:.2f}s | Latency: {gen_time:.2f}s | RTF: {rtf:.2f}x | Saved: {out_path.name}", flush=True)

        results.append({
            "sentence_id": sid,
            "text": text,
            "audio_duration_s": round(audio_dur, 2),
            "generation_time_s": round(gen_time, 2),
            "rtf": round(rtf, 2),
            "sample_rate": sample_rate,
            "device": device,
            "audio_file": str(out_path.relative_to(PROJECT_ROOT)),
        })

    # Write CSV
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "sentence_id", "text", "audio_duration_s", "generation_time_s", "rtf", "sample_rate", "device", "audio_file"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n[DONE] Benchmark complete! Saved {len(results)} audio files and metrics to {csv_file}", flush=True)


if __name__ == "__main__":
    run_benchmark()
