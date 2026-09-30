import os
import sys
import time
import csv
import math
from pathlib import Path

# Force utf-8 stdout/stderr on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import torch
import librosa
import soundfile as sf
import numpy as np
from faster_whisper import WhisperModel
from chatterbox.tts_turbo import ChatterboxTurboTTS

def analyze_audio(wav_path: str):
    y, sr = librosa.load(wav_path, sr=None)
    duration = len(y) / sr
    f0, voiced_flag, voiced_probs = librosa.pyin(
        y, fmin=librosa.note_to_hz('C2'), fmax=librosa.note_to_hz('C7'), sr=sr
    )
    f0_clean = f0[~np.isnan(f0)]
    mean_pitch = float(np.mean(f0_clean)) if len(f0_clean) > 0 else 0.0
    return duration, mean_pitch

def run_turbo_benchmark():
    device = "cpu"
    ckpt_dir = Path("tts_benchmark/chatterbox/models/turbo")
    print(f"Loading official ChatterboxTurboTTS from {ckpt_dir} on {device}...", flush=True)
    model = ChatterboxTurboTTS.from_local(ckpt_dir, device=device)
    print("ChatterboxTurboTTS loaded successfully!", flush=True)

    ref_voice = Path("backend/voices/default/alita_en_original.wav")
    print(f"Conditioning reference voice: {ref_voice} (Female MJ Voice)...", flush=True)
    model.prepare_conditionals(str(ref_voice))
    print("Conditionals prepared successfully!", flush=True)

    output_dir = Path("tts_benchmark/chatterbox/samples/turbo")
    output_dir.mkdir(parents=True, exist_ok=True)

    test_cases = [
        ("T01_Greeting", "Good morning! How can I help you organize your tasks today?"),
        ("T02_System_Status", "All background services are running smoothly, and your CPU utilization is currently at twelve percent."),
        ("T03_Code_Review", "I've reviewed your pull request. The changes look great, but remember to add unit tests for the error handling logic."),
        ("T04_Schedule_Reminder", "You have a team sync scheduled in fifteen minutes. Would you like me to open the meeting link for you?"),
        ("T05_Weather_Info", "The weather forecast today looks clear with a high of seventy-two degrees. Perfect for an afternoon walk."),
        ("T06_Database_Report", "Database migration completed in two point four seconds. Zero tables were locked, and all foreign keys are intact."),
        ("T07_Email_Draft", "I have drafted a quick response to your client confirming the project delivery deadline for Friday morning."),
        ("T08_Deployment_Success", "Your Docker container has been built successfully and deployed to the staging environment."),
        ("T09_Paralinguistic_Laugh", "That's hilarious! [laugh] I really didn't expect that test case to pass on the first try."),
        ("T10_Troubleshooting", "The connection timed out while querying the remote API. Please check your network gateway and proxy settings."),
        ("T11_Long_Explanation", "Here is a breakdown of your memory usage. The frontend development server is using four hundred megabytes, while the vector database process is consuming approximately one point two gigabytes of system RAM."),
        ("T12_Action_Confirmation", "Understood. I will keep monitoring the application logs and notify you immediately if any unexpected exceptions occur."),
    ]

    whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    results = []

    print("\n--- Starting Chatterbox-Turbo English Benchmark ---", flush=True)
    for test_id, text in test_cases:
        print(f"\n[{test_id}] Text: '{text}'", flush=True)

        t0 = time.time()
        wav = model.generate(text=text)
        latency = time.time() - t0

        wav_np = wav.squeeze(0).cpu().numpy()
        out_path = output_dir / f"{test_id}.wav"
        sf.write(str(out_path), wav_np, model.sr)

        duration, mean_pitch = analyze_audio(str(out_path))
        rtf = latency / duration if duration > 0 else 0.0

        segments, info = whisper_model.transcribe(str(out_path))
        transcription = " ".join(s.text for s in segments).strip()

        print(f" -> Duration: {duration:.2f}s | Latency: {latency:.2f}s | RTF: {rtf:.2f}x | Pitch: {mean_pitch:.1f}Hz", flush=True)
        print(f" -> Whisper: '{transcription}'", flush=True)

        results.append({
            "test_id": test_id,
            "exact_input": text,
            "output_wav": str(out_path),
            "duration_s": round(duration, 2),
            "generation_latency_s": round(latency, 2),
            "rtf": round(rtf, 2),
            "mean_pitch_hz": round(mean_pitch, 1),
            "transcription": transcription,
        })

    csv_path = Path("tts_benchmark/results/chatterbox_turbo_benchmark.csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "test_id", "exact_input", "output_wav",
            "duration_s", "generation_latency_s", "rtf", "mean_pitch_hz",
            "transcription"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nAll Chatterbox-Turbo benchmark results saved to {csv_path}", flush=True)

if __name__ == "__main__":
    run_turbo_benchmark()
