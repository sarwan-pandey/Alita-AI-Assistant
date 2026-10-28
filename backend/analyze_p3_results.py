import json
from pathlib import Path

path = Path("p3_benchmark_results.json")
data = json.loads(path.read_text(encoding="utf-8"))

print("=" * 110)
print(f"{'#':<3} | {'Category':<32} | {'Q TTFT':<8} | {'Q Total':<8} | {'L TTFT':<8} | {'L Total':<8} | {'Q E2E':<8} | {'L E2E':<8} | {'Advantage'}")
print("=" * 110)

for s in data["scenarios"]:
    qid, cat = s["id"], s["category"]
    q, l = s["qwen"], s["lightning"]
    qttft, qtot, qe2e = q["ttft_ms"], q["total_llm_ms"], q["e2e_first_audio_ms"]
    lttft, ltot, le2e = l["ttft_ms"], l["total_llm_ms"], l["e2e_first_audio_ms"]
    
    if not l["success"]:
        adv = "Qwen (L Failed)"
    elif not q["success"]:
        adv = "Lightning (Q Failed)"
    elif lttft < qttft and le2e < qe2e:
        adv = "Lightning"
    elif qe2e < le2e:
        adv = "Qwen"
    else:
        adv = "Mixed"
        
    print(f"{qid:<3} | {cat:<32} | {qttft:>8.1f} | {qtot:>8.1f} | {lttft:>8.1f} | {ltot:>8.1f} | {qe2e:>8.1f} | {le2e:>8.1f} | {adv}")

print("=" * 110)
print("\nAGGREGATE SUMMARY:")
stats = data["stats"]
for model in ["qwen", "lightning"]:
    m = stats[model]
    print(f"\n--- {model.upper()} ---")
    print(f"  TTFT:           avg={m['ttft']['avg']}ms, p50={m['ttft']['p50']}ms, p95={m['ttft']['p95']}ms, min={m['ttft']['min']}ms, max={m['ttft']['max']}ms")
    print(f"  TTFS (useful):  avg={m['ttfs']['avg']}ms, p50={m['ttfs']['p50']}ms, p95={m['ttfs']['p95']}ms")
    print(f"  Total LLM:      avg={m['total_llm']['avg']}ms, p50={m['total_llm']['p50']}ms, p95={m['total_llm']['p95']}ms")
    print(f"  E2E Audio:      avg={m['e2e_first_audio']['avg']}ms, p50={m['e2e_first_audio']['p50']}ms, p95={m['e2e_first_audio']['p95']}ms")
    print(f"  Cold Start:     TTFT={m['cold_ttft_ms']}ms, Total={m['cold_total_ms']}ms")
    print(f"  Failure Rate:   {m['failure_rate_pct']}%")
    print(f"  Tool Accuracy:  {m['tool_accuracy_pct']}%")
    print(f"  Auto Accuracy:  {m['automation_success_pct']}%")
    print(f"  Answer Acc:     {m['answer_accuracy_pct']}%")

print("\nFALLBACK TESTS:")
for name, res in data["fallback_tests"].items():
    print(f"  {name:<30}: Pass={res.get('pass')}")

print("\n" + "=" * 110)
print("PER-SCENARIO DETAILED RESPONSES & METRICS")
print("=" * 110)
for s in data["scenarios"]:
    qid, cat, prompt = s["id"], s["category"], s["prompt"]
    q, l = s["qwen"], s["lightning"]
    print(f"\n--- Scenario {qid}: {cat} ---")
    safe_prompt = prompt.encode('ascii', errors='replace').decode('ascii')
    print(f"Prompt: {safe_prompt}")
    print(f"  [Qwen]      TTFT={q['ttft_ms']:>6.1f}ms | TTFS={q['ttfs_ms']:>6.1f}ms | Total={q['total_llm_ms']:>6.1f}ms | E2E-Audio={q['e2e_first_audio_ms']:>6.1f}ms | Chars={q['char_length']}")
    print(f"              AnsCorrect={q['answer_correct']} | ToolCorrect={q['tool_correct']} | AutoSuccess={q['automation_success']} | Verbosity={q['unwanted_verbosity']}")
    q_resp = q['response_text'][:140].encode('ascii', errors='replace').decode('ascii')
    l_resp = l['response_text'][:140].encode('ascii', errors='replace').decode('ascii')
    print(f"              Response: {repr(q_resp)}")
    print(f"  [Lightning] TTFT={l['ttft_ms']:>6.1f}ms | TTFS={l['ttfs_ms']:>6.1f}ms | Total={l['total_llm_ms']:>6.1f}ms | E2E-Audio={l['e2e_first_audio_ms']:>6.1f}ms | Chars={l['char_length']}")
    print(f"              AnsCorrect={l['answer_correct']} | ToolCorrect={l['tool_correct']} | AutoSuccess={l['automation_success']} | Verbosity={l['unwanted_verbosity']}")
    print(f"              Response: {repr(l_resp)}")
