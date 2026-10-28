"""
Shadow Benchmark — Qwen Local vs Nemotron Lightning Side-by-Side
=================================================================
Runs identical prompts through both providers and captures comparative
timing metrics. Does NOT affect production traffic.

Usage:
    cd backend
    python -m engines.shadow_benchmark

    # Or with custom NVIDIA API key:
    NVIDIA_API_KEY=nvapi-xxx python -m engines.shadow_benchmark

Output: Formatted comparison table + per-prompt metrics.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


def _safe(text: str) -> str:
    """Strip non-ASCII chars for safe terminal printing on Windows cp1252."""
    return text.encode("ascii", errors="replace").decode("ascii")

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(override=True)

from engines.nvidia_lightning import (
    NvidiaLightningClient,
    LightningMetrics,
    get_lightning_client,
)

log = logging.getLogger("alita.shadow_benchmark")

# ── Qwen Local Metrics Capture ──────────────────────────────────────────────

def _qwen_chat_with_metrics(
    messages: list,
    max_tokens: int = 300,
    temperature: float = 0.6,
) -> LightningMetrics:
    """
    Run the same prompt through local Qwen and capture comparable metrics.
    Uses the Qwen provider interface.
    """
    from engines.llm_provider import llm_registry
    qwen = llm_registry.get("qwen_local")
    model_name = qwen.get_model_name() if qwen else "qwen3:4b-instruct"
    health = qwen.health_check() if qwen else None
    is_running = health.available if health else False

    metrics = LightningMetrics(
        provider="qwen_local",
        model_id=model_name,
        reasoning_enabled=False,
    )

    for msg in reversed(messages):
        if msg.get("role") == "user":
            metrics.prompt_preview = msg.get("content", "")[:80]
            break

    if not is_running or not qwen:
        metrics.error = "Ollama not running"
        metrics.response_complete_time = time.time()
        metrics.finalize()
        return metrics

    metrics.request_start = time.time()

    try:
        # Ollama's non-streaming path doesn't give us first-token timing,
        # so TTFT = TTFS = total for non-streaming.
        result = qwen.chat(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        metrics.response_complete_time = time.time()

        if result:
            metrics.response_text = result.strip()
            metrics.success = True
            # For non-streaming, all timings are the same
            metrics.first_token_time = metrics.response_complete_time
            metrics.first_sentence_time = metrics.response_complete_time
            # Approximate token counts (4 chars ≈ 1 token)
            metrics.completion_tokens = max(1, len(metrics.response_text) // 4)
            # Estimate prompt tokens from messages
            prompt_chars = sum(len(m.get("content", "")) for m in messages)
            metrics.prompt_tokens = max(1, prompt_chars // 4)
            metrics.total_tokens = metrics.prompt_tokens + metrics.completion_tokens
        else:
            metrics.error = "Empty response"

    except Exception as exc:
        metrics.error = str(exc)
        metrics.response_complete_time = time.time()

    metrics.finalize()
    return metrics


# ── Test Prompt Catalog ──────────────────────────────────────────────────────

@dataclass
class TestPrompt:
    """A test prompt with category and expected behavior."""
    category: str
    user_message: str
    system_prompt: str = ""
    max_tokens: int = 300
    description: str = ""


# System prompt used for all tests (simplified MJ prompt)
_MJ_SYSTEM = (
    "You are MJ, an emotionally intelligent AI voice assistant. "
    "You sound like a real human friend — warm, witty, and natural. "
    "Keep responses concise and conversational. "
    "Reply in the user's language. Be fast, be human, be helpful."
)

TEST_PROMPTS: List[TestPrompt] = [
    TestPrompt(
        category="greeting",
        user_message="Hello MJ",
        system_prompt=_MJ_SYSTEM,
        max_tokens=100,
        description="Simple greeting — should be fast and short",
    ),
    TestPrompt(
        category="greeting",
        user_message="How are you doing today?",
        system_prompt=_MJ_SYSTEM,
        max_tokens=150,
        description="Casual check-in",
    ),
    TestPrompt(
        category="knowledge",
        user_message="What is the capital of Japan?",
        system_prompt=_MJ_SYSTEM,
        max_tokens=100,
        description="Simple factual knowledge",
    ),
    TestPrompt(
        category="knowledge",
        user_message="Explain photosynthesis in 2 sentences.",
        system_prompt=_MJ_SYSTEM,
        max_tokens=200,
        description="Concise knowledge explanation",
    ),
    TestPrompt(
        category="reasoning",
        user_message="If I have 3 apples and give away 1, then buy 5 more, how many do I have?",
        system_prompt=_MJ_SYSTEM,
        max_tokens=150,
        description="Simple arithmetic reasoning",
    ),
    TestPrompt(
        category="creative",
        user_message="Tell me a short joke about programming.",
        system_prompt=_MJ_SYSTEM,
        max_tokens=200,
        description="Creative/humor generation",
    ),
    TestPrompt(
        category="instruction",
        user_message="Give me 3 tips for better sleep.",
        system_prompt=_MJ_SYSTEM,
        max_tokens=300,
        description="Structured instruction list",
    ),
    TestPrompt(
        category="hindi",
        user_message="Mujhe ek acchi recipe batao biryani ki.",
        system_prompt=_MJ_SYSTEM,
        max_tokens=300,
        description="Hindi language request (bilingual test)",
    ),
    TestPrompt(
        category="medical",
        user_message="I have a mild headache. What are some home remedies?",
        system_prompt=_MJ_SYSTEM + "\n\nThis appears to be a health/medical query. Be accurate, recommend seeing a doctor for serious concerns.",
        max_tokens=300,
        description="Medical query — accuracy matters",
    ),
    TestPrompt(
        category="conversational",
        user_message="I'm feeling a bit bored. What should I do?",
        system_prompt=_MJ_SYSTEM,
        max_tokens=200,
        description="Emotional/conversational support",
    ),
]


# ── Benchmark Runner ─────────────────────────────────────────────────────────

def run_shadow_benchmark(
    prompts: Optional[List[TestPrompt]] = None,
    include_lightning: bool = True,
    include_qwen: bool = True,
) -> List[dict]:
    """
    Run shadow benchmark on all test prompts.
    Returns list of comparison result dicts.
    """
    if prompts is None:
        prompts = TEST_PROMPTS

    lightning = get_lightning_client() if include_lightning else None
    results = []

    print("\n" + "=" * 84)
    print("  SHADOW BENCHMARK -- Qwen Local vs Nemotron Lightning")
    print("=" * 84)

    if lightning and not lightning.available:
        print("\n  [!] NVIDIA_API_KEY not set -- Lightning tests will be skipped")
        print("  Set NVIDIA_API_KEY in .env or environment to enable Lightning benchmarks\n")
        include_lightning = False

    for i, prompt in enumerate(prompts, 1):
        print(f"\n--- Prompt {i}/{len(prompts)}: [{prompt.category}] {_safe(prompt.description)} ---")
        print(f"  User: \"{prompt.user_message}\"")

        messages = []
        if prompt.system_prompt:
            messages.append({"role": "system", "content": prompt.system_prompt})
        messages.append({"role": "user", "content": prompt.user_message})

        result = {
            "prompt_index": i,
            "category": prompt.category,
            "description": prompt.description,
            "user_message": prompt.user_message,
            "qwen": None,
            "lightning": None,
        }

        # ── Qwen Local ──────────────────────────────────────────────────
        if include_qwen:
            print("  [Qwen] Running...", end="", flush=True)
            qwen_metrics = _qwen_chat_with_metrics(
                messages, max_tokens=prompt.max_tokens, temperature=0.6,
            )
            print(f" {qwen_metrics.summary()}")
            if qwen_metrics.success:
                preview = _safe(qwen_metrics.response_text[:120].replace("\n", " "))
                print(f"  [Qwen] Response: \"{preview}...\"" if len(qwen_metrics.response_text) > 120 else f"  [Qwen] Response: \"{preview}\"")
            result["qwen"] = {
                "success": qwen_metrics.success,
                "total_ms": round(qwen_metrics.total_ms, 1),
                "ttft_ms": round(qwen_metrics.ttft_ms, 1),
                "ttfs_ms": round(qwen_metrics.ttfs_ms, 1),
                "tokens": qwen_metrics.total_tokens,
                "completion_tokens": qwen_metrics.completion_tokens,
                "response_length": len(qwen_metrics.response_text),
                "error": qwen_metrics.error,
            }

        # ── Lightning ───────────────────────────────────────────────────
        if include_lightning and lightning:
            print("  [Lightning] Running...", end="", flush=True)
            lightning_metrics = lightning.chat_with_metrics(
                messages,
                max_tokens=prompt.max_tokens,
                temperature=0.6,
                enable_reasoning=False,  # Fast mode for voice
            )
            print(f" {lightning_metrics.summary()}")
            if lightning_metrics.success:
                preview = _safe(lightning_metrics.response_text[:120].replace("\n", " "))
                print(f"  [Lightning] Response: \"{preview}...\"" if len(lightning_metrics.response_text) > 120 else f"  [Lightning] Response: \"{preview}\"")
            result["lightning"] = {
                "success": lightning_metrics.success,
                "total_ms": round(lightning_metrics.total_ms, 1),
                "ttft_ms": round(lightning_metrics.ttft_ms, 1),
                "ttfs_ms": round(lightning_metrics.ttfs_ms, 1),
                "tokens": lightning_metrics.total_tokens,
                "prompt_tokens": lightning_metrics.prompt_tokens,
                "completion_tokens": lightning_metrics.completion_tokens,
                "response_length": len(lightning_metrics.response_text),
                "error": lightning_metrics.error,
            }

        results.append(result)

        # Brief pause between prompts to avoid rate limiting
        time.sleep(0.5)

    # ── Summary Table ────────────────────────────────────────────────────
    _print_summary(results, include_lightning)

    return results


def _print_summary(results: List[dict], include_lightning: bool) -> None:
    """Print formatted comparison summary table."""
    print("\n" + "=" * 84)
    print("  BENCHMARK RESULTS SUMMARY")
    print("=" * 84)

    # Header
    if include_lightning:
        print(f"\n  {'#':<3} {'Category':<15} {'Qwen Total':>12} {'Qwen TTFT':>10} "
              f"{'LN Total':>12} {'LN TTFT':>10} {'LN TTFS':>10} {'Winner':>10}")
        print("  " + "-" * 82)
    else:
        print(f"\n  {'#':<3} {'Category':<15} {'Qwen Total':>12} {'Status':>10}")
        print("  " + "-" * 42)

    qwen_total = 0.0
    ln_total = 0.0
    qwen_wins = 0
    ln_wins = 0

    for r in results:
        q = r.get("qwen", {}) or {}
        l = r.get("lightning", {}) or {}

        q_time = q.get("total_ms", 0) if q.get("success") else -1
        l_time = l.get("total_ms", 0) if l.get("success") else -1

        if include_lightning and l:
            winner = "—"
            if q_time > 0 and l_time > 0:
                if q_time < l_time:
                    winner = "Qwen"
                    qwen_wins += 1
                else:
                    winner = "Lightning"
                    ln_wins += 1
                qwen_total += q_time
                ln_total += l_time

            q_str = f"{q_time:.0f}ms" if q_time > 0 else "FAIL"
            l_str = f"{l_time:.0f}ms" if l_time > 0 else "FAIL"
            l_ttft = f"{l.get('ttft_ms', 0):.0f}ms" if l.get("success") else "—"
            l_ttfs = f"{l.get('ttfs_ms', 0):.0f}ms" if l.get("success") else "—"
            q_ttft = f"{q.get('ttft_ms', 0):.0f}ms" if q.get("success") else "—"

            print(f"  {r['prompt_index']:<3} {r['category']:<15} {q_str:>12} {q_ttft:>10} "
                  f"{l_str:>12} {l_ttft:>10} {l_ttfs:>10} {winner:>10}")
        else:
            q_str = f"{q_time:.0f}ms" if q_time > 0 else "FAIL"
            status = "OK" if q.get("success") else "FAIL"
            print(f"  {r['prompt_index']:<3} {r['category']:<15} {q_str:>12} {status:>10}")

    # Averages
    n = max(1, len(results))
    print()
    if include_lightning and ln_total > 0:
        both_n = qwen_wins + ln_wins
        print(f"  Qwen Average:      {qwen_total / max(1, both_n):.0f}ms")
        print(f"  Lightning Average:  {ln_total / max(1, both_n):.0f}ms")
        print(f"  Wins: Qwen={qwen_wins}  Lightning={ln_wins}")
    print("=" * 90)


# ── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    print("\n  Initializing shadow benchmark...")
    results = run_shadow_benchmark()

    # Save results to JSON
    output_path = Path(__file__).parent.parent / "data" / "benchmark_results.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n  Results saved to: {output_path}")
