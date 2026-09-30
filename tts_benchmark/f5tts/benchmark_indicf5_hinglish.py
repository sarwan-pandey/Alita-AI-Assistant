"""
Candidate Benchmark: Saravananravi/indicf5-hinglish
==================================================
Benchmarks Saravananravi/indicf5-hinglish across 5 linguistic categories:
1. Pure Devanagari Hindi
2. Latin-script Hinglish
3. Mixed Hindi-English
4. English technical text
5. Code-switched sentences

Uses the complete IndicF5 2545-token vocabulary (100% character coverage for both
Devanagari script and Latin alphabet).
Preserves every input EXACTLY as written without transliteration or translation.
Saves WAV files to tts_benchmark/f5tts/samples/indicf5_hinglish/
Writes metrics to tts_benchmark/results/indicf5_hinglish_benchmark.csv
"""

import os
import sys
import time
import csv
from pathlib import Path

# Fix Windows console encoding
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

import numpy as np
import torch
import soundfile as sf
from huggingface_hub import hf_hub_download
from safetensors.torch import load_file

from f5_tts.model import CFM, DiT
from f5_tts.infer.utils_infer import (
    infer_process,
    load_vocoder,
    get_tokenizer,
)

BENCHMARK_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BENCHMARK_DIR.parent.parent
SAMPLES_DIR = BENCHMARK_DIR / "samples" / "indicf5_hinglish"
RESULTS_DIR = BENCHMARK_DIR.parent / "results"

REF_WAV_HI = PROJECT_ROOT / "backend" / "voices" / "default" / "alita_hi.wav"
REF_TEXT_HI = "नमस्ते! मैं अलिता हूँ, आपकी पर्सनल एआई असिस्टेंट। मैं आपकी हर तरह से मदद करने के लिए यहाँ हूँ। आप मुझसे कुछ भी पूछ सकते हैं।"

REF_WAV_EN = PROJECT_ROOT / "backend" / "voices" / "default" / "alita_en_original.wav"
REF_TEXT_EN = "Hello, I am Alita, your personal AI assistant. I am here to help you with anything you need. Feel free to ask me questions, have a conversation, or just chat about your day."

SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

# Test items across the 5 mandatory categories (original unmodified text)
TEST_ITEMS = [
    # 1. Pure Devanagari Hindi
    ("H01", "devanagari_hindi", "नमस्ते! मैं एमजे हूँ, आपकी पर्सनल एआई असिस्टेंट। आज मैं आपकी क्या मदद कर सकती हूँ?", "hi"),
    ("H02", "devanagari_hindi", "आज मौसम बहुत अच्छा है, चलिए आज का काम शुरू करते हैं।", "hi"),
    # 2. Latin-script Hinglish
    ("L01", "latin_hinglish", "Aaj mujhe thoda kaam karna hai aur ek naya project shuru karna hai.", "hi"),
    ("L02", "latin_hinglish", "Aap kaise hain? Kya hum meeting shuru karein?", "hi"),
    # 3. Mixed Hindi-English (Code-Switching)
    ("M01", "mixed_hindi_english", "आज हमारा project deployment के लिए ready है.", "hi"),
    ("M02", "mixed_hindi_english", "Server connection check karo aur database logs verify karo.", "hi"),
    # 4. English technical text
    ("E01", "english_technical", "The database query failed because the connection pool timed out after thirty seconds.", "en"),
    ("E02", "english_technical", "Memory usage peaked at 3.4 gigabytes across 12 worker threads.", "en"),
    # 5. Code-switched sentences
    ("C01", "code_switched", "Main kal office jaa raha hoon kyunki presentation delivery scheduled hai.", "hi"),
    ("C02", "code_switched", "Code review complete ho gaya hai, please PR merge kar do.", "hi"),
]


def load_candidate_model():
    print("=== Loading Saravananravi/indicf5-hinglish with IndicF5 Vocab ===", flush=True)
    t0 = time.perf_counter()

    # Download vocabulary from IndicF5 mirror (contains all Indic + Latin tokens)
    vocab_path = hf_hub_download(repo_id="rsolanki1822/IndicF5-mirror", filename="checkpoints/vocab.txt")
    vocab_char_map, vocab_size = get_tokenizer(vocab_path, "custom")
    print(f"Loaded tokenizer with {vocab_size} tokens (Devanagari + Latin alphabet)", flush=True)

    ckpt_path = hf_hub_download(repo_id="Saravananravi/indicf5-hinglish", filename="model.safetensors")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Loading weights onto {device}...", flush=True)

    backbone = DiT(
        dim=1024,
        depth=22,
        heads=16,
        ff_mult=2,
        text_dim=512,
        conv_layers=4,
        text_num_embeds=vocab_size,
        mel_dim=100,
    )

    model = CFM(
        transformer=backbone,
        mel_spec_kwargs=dict(
            n_fft=1024,
            hop_length=256,
            win_length=1024,
            n_mel_channels=100,
            target_sample_rate=24000,
            mel_spec_type="vocos",
        ),
        odeint_kwargs=dict(method="euler"),
        vocab_char_map=vocab_char_map,
    )

    state_dict = load_file(ckpt_path)
    cleaned = {}
    for k, v in state_dict.items():
        if k.startswith("ema_model."):
            cleaned[k[10:]] = v
        elif k not in ("initted", "step"):
            cleaned[k] = v
    if cleaned:
        state_dict = cleaned

    model.load_state_dict(state_dict, strict=False)
    model = model.to(device)
    model.eval()

    vocoder = load_vocoder(vocoder_name="vocos", is_local=False, device=device)

    print(f"[OK] Model & Vocoder loaded in {time.perf_counter() - t0:.2f}s", flush=True)
    return model, vocoder, device


def run_benchmark():
    model, vocoder, device = load_candidate_model()

    results = []
    csv_file = RESULTS_DIR / "indicf5_hinglish_benchmark.csv"

    print(f"\n--- Benchmarking {len(TEST_ITEMS)} Items ---", flush=True)
    for tid, category, text, ref_lang in TEST_ITEMS:
        print(f"\n[{tid} | {category}] {text}", flush=True)

        ref_wav = str(REF_WAV_EN if ref_lang == "en" else REF_WAV_HI)
        ref_text = REF_TEXT_EN if ref_lang == "en" else REF_TEXT_HI

        # Ensure sentence ending formatting
        if not ref_text.endswith(". ") and not ref_text.endswith("。"):
            ref_text = ref_text.rstrip(".") + ". "

        t0 = time.perf_counter()
        status = "ok"
        error_msg = ""
        audio_dur = 0.0
        gen_time = 0.0
        rtf = 0.0

        try:
            audio_res, sr, _ = infer_process(
                ref_wav,
                ref_text,
                text,
                model,
                vocoder,
                mel_spec_type="vocos",
                speed=1.0,
                device=device,
                nfe_step=16,
                show_info=lambda *a: None,
            )
            gen_time = time.perf_counter() - t0

            if audio_res is not None:
                if isinstance(audio_res, torch.Tensor):
                    audio_res = audio_res.detach().cpu().numpy()
                audio_arr = np.array(audio_res, dtype=np.float32)

                audio_dur = len(audio_arr) / sr
                rtf = gen_time / audio_dur if audio_dur > 0 else 0.0

                out_path = SAMPLES_DIR / f"{tid.lower()}_{category}.wav"
                sf.write(str(out_path), audio_arr, sr, subtype="PCM_16")
                print(f"  -> Audio: {audio_dur:.2f}s | Latency: {gen_time:.2f}s | RTF: {rtf:.2f}x | Saved: {out_path.name}", flush=True)
            else:
                status = "empty_audio"
                print("  -> Warning: model returned empty audio", flush=True)

        except Exception as exc:
            gen_time = time.perf_counter() - t0
            status = "failed"
            error_msg = str(exc)
            print(f"  -> FAILED: {exc}", flush=True)

        results.append({
            "test_id": tid,
            "category": category,
            "text": text,
            "status": status,
            "error": error_msg,
            "audio_duration_s": round(audio_dur, 2),
            "generation_time_s": round(gen_time, 2),
            "rtf": round(rtf, 2),
            "device": device,
            "ref_audio": Path(ref_wav).name,
        })

    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "test_id", "category", "text", "status", "error", "audio_duration_s", "generation_time_s", "rtf", "device", "ref_audio"
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n[DONE] IndicF5-Hinglish benchmark complete! Results saved to {csv_file}", flush=True)


if __name__ == "__main__":
    run_benchmark()
