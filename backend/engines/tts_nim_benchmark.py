"""
TTS Shadow Benchmark — Local Chatterbox vs NVIDIA NIM
======================================================
Side-by-side comparison of local Chatterbox Turbo and NIM Chatterbox Multilingual.
Captures latency, audio size, and quality metrics.

Run:
    cd backend && python -m engines.tts_nim_benchmark

Does NOT modify production TTS behavior.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

log = logging.getLogger("alita.tts_benchmark")


def _safe(text: str) -> str:
    """Strip non-ASCII for safe Windows terminal printing."""
    return text.encode("ascii", errors="replace").decode("ascii")


# ── Test Prompts ─────────────────────────────────────────────────────────────

@dataclass
class TTSPrompt:
    text: str
    language: str
    category: str
    description: str


TEST_PROMPTS: List[TTSPrompt] = [
    # English — short
    TTSPrompt(
        "Hello! How can I help you today?",
        "en", "english_short", "Short English greeting"
    ),
    # English — medium
    TTSPrompt(
        "The weather today is sunny with a high of 32 degrees.",
        "en", "english_medium", "Medium English sentence"
    ),
    # English — longer (will test chunking)
    TTSPrompt(
        "Here are three tips for better sleep. First, keep your room cool. "
        "Second, avoid screens before bed. Third, try a consistent schedule.",
        "en", "english_long", "Multi-sentence English (tests chunking)"
    ),
    # Hindi — short
    TTSPrompt(
        "Namaste! Aaj main aapki kaise madad kar sakti hoon?",
        "hi", "hindi_short", "Short Hindi greeting"
    ),
    # Hindi — medium
    TTSPrompt(
        "Aaj ka mausam bahut accha hai, dhoop khili hui hai.",
        "hi", "hindi_medium", "Medium Hindi sentence"
    ),
    # Spanish
    TTSPrompt(
        "Hola! Como estas? Hoy hace un dia muy bonito.",
        "es", "spanish", "Spanish greeting"
    ),
    # French
    TTSPrompt(
        "Bonjour! Comment allez-vous aujourd'hui?",
        "fr", "french", "French greeting"
    ),
    # Japanese
    TTSPrompt(
        "Konnichiwa! Kyou wa ii tenki desu ne.",
        "ja", "japanese", "Japanese greeting (romanized)"
    ),
]


# ── Local Chatterbox Metrics ─────────────────────────────────────────────────

def _local_tts_with_metrics(text: str, language: str) -> dict:
    """Run local Chatterbox Turbo and capture timing metrics."""
    result = {
        "provider": "chatterbox_local",
        "success": False,
        "total_ms": 0.0,
        "audio_bytes": 0,
        "error": "",
    }

    try:
        from tts_dispatch import get_or_load_turbo_engine
        engine = get_or_load_turbo_engine()
        if engine is None or not engine.available:
            result["error"] = "Engine not available"
            return result

        from core.text_utils import _clean_text_for_tts
        from core.chunk_utils import chunk_text_hard_safety, OPERATIONAL_HARD_LIMIT, ABSOLUTE_SAFETY_LIMIT

        cleaned = _clean_text_for_tts(text, preserve_oral_tags=True)
        if not cleaned or not cleaned.strip():
            result["error"] = "Empty after cleaning"
            return result

        clean_str = cleaned.strip()
        if len(clean_str) <= OPERATIONAL_HARD_LIMIT:
            chunks = [clean_str]
        else:
            chunks = chunk_text_hard_safety(
                clean_str,
                hard_limit=OPERATIONAL_HARD_LIMIT,
                absolute_limit=ABSOLUTE_SAFETY_LIMIT,
            )

        t0 = time.time()

        import numpy as np
        import soundfile as sf

        audio_segments = []
        sr = 24000
        for chunk in chunks:
            wav_bytes = engine.generate(chunk)
            if wav_bytes:
                data, file_sr = sf.read(io.BytesIO(wav_bytes))
                audio_segments.append(data)
                sr = file_sr

        if not audio_segments:
            result["error"] = "Empty audio output"
            return result

        combined = np.concatenate(audio_segments) if len(audio_segments) > 1 else audio_segments[0]
        buf = io.BytesIO()
        sf.write(buf, combined, sr, format="WAV", subtype="PCM_16")
        wav_output = buf.getvalue()

        elapsed = (time.time() - t0) * 1000

        result["success"] = True
        result["total_ms"] = round(elapsed, 1)
        result["audio_bytes"] = len(wav_output)
        result["chunks"] = len(chunks)

    except Exception as exc:
        result["error"] = str(exc)

    return result


# ── NIM TTS Metrics ──────────────────────────────────────────────────────────

async def _nim_tts_with_metrics(text: str, language: str) -> dict:
    """Run NIM Chatterbox Multilingual and capture timing metrics."""
    from engines.tts_nvidia_nim import ChatterboxNIMClient, get_default_voice

    result = {
        "provider": "chatterbox_nim",
        "success": False,
        "total_ms": 0.0,
        "ttfa_ms": 0.0,
        "audio_bytes": 0,
        "voice": "",
        "error": "",
    }

    client = ChatterboxNIMClient()
    if not client.available:
        result["error"] = "NIM endpoint not configured"
        return result

    voice = get_default_voice(language, "Female")
    result["voice"] = voice

    audio, metrics_list = await client.synthesize_chunked(
        text, language=language, voice=voice
    )

    if metrics_list:
        # Aggregate metrics
        total_ms = sum(m.total_ms for m in metrics_list)
        ttfa_ms = metrics_list[0].ttfa_ms if metrics_list[0].success else 0
        all_success = all(m.success for m in metrics_list)
        errors = [m.error for m in metrics_list if m.error]

        result["success"] = all_success and bool(audio)
        result["total_ms"] = round(total_ms, 1)
        result["ttfa_ms"] = round(ttfa_ms, 1)
        result["audio_bytes"] = len(audio) if audio else 0
        result["chunks"] = len(metrics_list)
        if errors:
            result["error"] = "; ".join(errors)
    else:
        result["error"] = "No metrics returned"

    await client.close()
    return result


# ── Benchmark Runner ─────────────────────────────────────────────────────────

async def run_tts_benchmark(
    include_local: bool = True,
    include_nim: bool = True,
    prompts: Optional[List[TTSPrompt]] = None,
) -> List[dict]:
    """
    Run head-to-head TTS benchmark.

    Returns list of result dicts with per-prompt comparison data.
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    if prompts is None:
        prompts = TEST_PROMPTS

    results = []

    print("\n" + "=" * 84)
    print("  TTS BENCHMARK -- Local Chatterbox vs NIM Chatterbox Multilingual")
    print("=" * 84)

    for i, prompt in enumerate(prompts, 1):
        print(f"\n--- Prompt {i}/{len(prompts)}: [{prompt.category}] {_safe(prompt.description)} ---")
        print(f"  Text: \"{_safe(prompt.text[:80])}\"")
        print(f"  Language: {prompt.language}")

        result = {
            "prompt_index": i,
            "category": prompt.category,
            "language": prompt.language,
            "text": prompt.text,
            "text_length": len(prompt.text),
            "local": None,
            "nim": None,
        }

        # Local Chatterbox
        if include_local:
            print("  [Local] Running...", end="", flush=True)
            local_result = _local_tts_with_metrics(prompt.text, prompt.language)
            status = "OK" if local_result["success"] else f"FAIL({local_result['error'][:30]})"
            print(f" {status} | Total={local_result['total_ms']:.0f}ms | Audio={local_result['audio_bytes']}b")
            result["local"] = local_result

        # NIM Chatterbox
        if include_nim:
            print("  [NIM] Running...", end="", flush=True)
            nim_result = await _nim_tts_with_metrics(prompt.text, prompt.language)
            status = "OK" if nim_result["success"] else f"FAIL({nim_result['error'][:30]})"
            print(f" {status} | TTFA={nim_result.get('ttfa_ms', 0):.0f}ms | "
                  f"Total={nim_result['total_ms']:.0f}ms | Audio={nim_result['audio_bytes']}b")
            result["nim"] = nim_result

        results.append(result)

    # Summary table
    _print_summary(results, include_local, include_nim)

    # Save results
    data_dir = Path(__file__).parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    output_file = data_dir / "tts_benchmark_results.json"
    with open(output_file, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_file.resolve()}\n")

    return results


def _print_summary(
    results: List[dict],
    include_local: bool,
    include_nim: bool,
) -> None:
    """Print formatted comparison summary."""
    print("\n" + "=" * 84)
    print("  TTS BENCHMARK RESULTS SUMMARY")
    print("=" * 84)

    if include_local and include_nim:
        print(f"\n  {'#':<3} {'Category':<20} {'Lang':<6} "
              f"{'Local ms':>10} {'NIM ms':>10} {'NIM TTFA':>10} {'Winner':>10}")
        print("  " + "-" * 72)
    else:
        header_provider = "Local ms" if include_local else "NIM ms"
        print(f"\n  {'#':<3} {'Category':<20} {'Lang':<6} {header_provider:>10} {'Status':>10}")
        print("  " + "-" * 52)

    local_times = []
    nim_times = []
    local_wins = 0
    nim_wins = 0

    for r in results:
        idx = r["prompt_index"]
        cat = r["category"][:18]
        lang = r["language"]

        local_ms = r.get("local", {}).get("total_ms", 0) if r.get("local") else 0
        nim_ms = r.get("nim", {}).get("total_ms", 0) if r.get("nim") else 0
        nim_ttfa = r.get("nim", {}).get("ttfa_ms", 0) if r.get("nim") else 0

        local_ok = r.get("local", {}).get("success", False) if r.get("local") else False
        nim_ok = r.get("nim", {}).get("success", False) if r.get("nim") else False

        if include_local and include_nim:
            local_str = f"{local_ms:.0f}ms" if local_ok else "FAIL"
            nim_str = f"{nim_ms:.0f}ms" if nim_ok else "FAIL"
            ttfa_str = f"{nim_ttfa:.0f}ms" if nim_ok else "-"

            if local_ok and nim_ok:
                winner = "Local" if local_ms < nim_ms else "NIM"
                if local_ms < nim_ms:
                    local_wins += 1
                else:
                    nim_wins += 1
                local_times.append(local_ms)
                nim_times.append(nim_ms)
            elif local_ok:
                winner = "Local"
                local_wins += 1
                local_times.append(local_ms)
            elif nim_ok:
                winner = "NIM"
                nim_wins += 1
                nim_times.append(nim_ms)
            else:
                winner = "-"

            print(f"  {idx:<3} {cat:<20} {lang:<6} {local_str:>10} {nim_str:>10} {ttfa_str:>10} {winner:>10}")
        else:
            ms = local_ms if include_local else nim_ms
            ok = local_ok if include_local else nim_ok
            status_str = f"{ms:.0f}ms" if ok else "FAIL"
            status = "OK" if ok else "FAIL"
            print(f"  {idx:<3} {cat:<20} {lang:<6} {status_str:>10} {status:>10}")

    if include_local and local_times:
        avg = sum(local_times) / len(local_times)
        print(f"\n  Local Average: {avg:.0f}ms")
    if include_nim and nim_times:
        avg = sum(nim_times) / len(nim_times)
        print(f"  NIM Average:   {avg:.0f}ms")
    if include_local and include_nim:
        print(f"  Wins: Local={local_wins}  NIM={nim_wins}")

    print("=" * 84)


# ── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Initializing TTS benchmark...")
    results = asyncio.run(run_tts_benchmark())
