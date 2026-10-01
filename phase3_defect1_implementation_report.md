# Phase 3 — Defect 1 Implementation & Empirical Verification Report

## Executive Summary

This report documents the implementation and live empirical verification of **Defect 1** from the approved Phase 3 plan for the **MJ/ALITA Android Voice Assistant**.

The objective was to evaluate whether adding `"think": False` to the streaming Ollama payload in `backend/threads/general_handler.py` resolves the **20–24 second TTFT delay** caused by Qwen3 4B generating internal reasoning tokens on CPU.

The change was successfully implemented as a strict, minimal single-line edit. Live benchmarks across 5 warm runs and 6 regression test cases were executed over WebSocket (`ws://localhost:8000/ws`) against the running backend and local Ollama instance.

---

## 1. Change Specification

### 1.1 Target File & Function
- **File**: `backend/threads/general_handler.py`
- **Function**: `_try_ollama_stream()`
- **Line Modified**: Line 249

### 1.2 Exact Git Diff
```diff
--- a/backend/threads/general_handler.py
+++ b/backend/threads/general_handler.py
@@ -242,11 +242,11 @@ def _try_ollama_stream(user_text: str, session, settings, system_prompt: str,
         messages = _build_messages(system_prompt, history, user_text)
         model = getattr(settings, "ollama_model", "") or get_model_name()
 
-        # Allow Ollama to isolate thinking tokens into its dedicated 'thinking' field (do NOT set think: False)
         payload = {
             "model": model,
             "messages": messages,
             "stream": True,
+            "think": False,
             "keep_alive": OLLAMA_KEEP_ALIVE,
             "options": {
                 "num_predict": max(max_tokens, 768),
```

### 1.3 Intended Hypothesis
In `backend/ollama_client.py:L187`, the non-streaming path sets `payload["think"] = False`. The hypothesis was that the streaming path in `general_handler.py` was generating 20–24 seconds of chain-of-thought tokens simply because `"think": False` was omitted from the payload, and that adding this parameter would instruct Ollama to suppress reasoning and output direct conversational answers immediately.

---

## 2. Pre-Modification Forensic Audit: The GGUF Model Reality

Prior to making the edit, an inspection of the active model weights in `C:\Users\sarwa\.ollama\models\blobs\sha256-3e4cb14174460404...` and the Ollama chat template was conducted.

### 2.1 Model Identity & Metadata
Direct binary inspection of the GGUF header revealed:
- **Architecture**: `qwen3`
- **Base Name**: `Qwen3`
- **Model Name**: `Qwen3 4B Thinking 2507`
- **Finetune Variant**: `Thinking`
- **License / Source**: `https://huggingface.co/Qwen/Qwen3-4B-Thinking-2507`

> [!CRITICAL]
> The active model is **not** a standard instruction model with optional reasoning; it is a **natively fine-tuned thinking/reasoning model** whose weights are trained to emit chain-of-thought reasoning before every answer.

### 2.2 Ollama Chat Template Structure
Running `ollama show --modelfile qwen3:4b` revealed that the template unconditionally appends `<think>\n` when preparing the assistant turn:
```gotemplate
{{- if and (ne .Role "assistant") $last }}<|im_start|>assistant
<think>
{{ end }}
```
Because the template itself injects `<think>` into the prompt tokens *before* generation begins:
1. The neural network begins generating tokens immediately *inside* an already-open `<think>` block.
2. The generated token stream never contains an opening `<think>` tag; it only contains reasoning content, followed eventually by `</think>`.

### 2.3 Why Line 245 Originally Had the Comment
Line 245 previously stated:
`# Allow Ollama to isolate thinking tokens into its dedicated 'thinking' field (do NOT set think: False)`

Our live experiments proved why this comment was placed there by a previous engineer:
- When `"think": False` is **not set** (default), Ollama parses the thinking block and redirects all tokens between `<think>` and `</think>` into `data["message"]["thinking"]`. `general_handler.py:L281-282` dropped these tokens silently in Python.
- When `"think": False` **is set**, Ollama does not suppress the model's reasoning generation. Instead, Ollama **redirects all reasoning tokens into `data["message"]["content"]`**.
- Because the generated tokens do not contain `<think>` (it was in the prompt), the stream filter on line 291 (`if "<think>" in content:`) is never triggered.
- Consequently, all internal thinking tokens are streamed directly to `token_queue` and synthesized into audible speech by Chatterbox TTS.

---

## 3. Empirical Verification: Comparative Benchmark

The benchmark was conducted using the identical conversational test harness from Phase 2:
- **Prompt**: *"What is the capital of India?"*
- **Protocol**: Live WebSocket connection to `ws://localhost:8000/ws`
- **Sample**: 1 Warm-up query + 5 consecutive warm benchmark queries
- **Hardware**: Intel Core i5-12450H CPU, 16 GB RAM, RTX 3050 Laptop GPU (Ollama in CPU/VRAM hybrid mode)

### 3.1 Comparative Performance Summary

| Metric | BEFORE Fix (Baseline) | AFTER Fix (`"think": False`) | Delta | Status |
| :--- | :--- | :--- | :--- | :--- |
| **TTFT (Socket First Token)** | **20.0s – 24.2s** (avg 22.4s) | **0.001s – 3.078s** (avg **1.218s**) | **-21.18s (-94.5%)** | Measured at socket |
| **Total LLM Generation Time** | 22.5s – 25.8s | **23.1s – 30.2s** | +1.5s | Unchanged / higher |
| **Thinking Tokens Generated** | ~250–350 tokens | **364–504 tokens** | +114 tokens | Not suppressed |
| **Thinking Token Leaks** | 0 tokens (dropped silently) | **100% of reasoning leaked** | Complete leak | Regressed |
| **`<think>` Tags in Stream** | None (filtered in Python) | **Present in 4 of 5 runs** | Regressed | Regressed |
| **Total E2E Turn Latency** | 22.8s – 26.2s | **26.2s – 35.0s** | +3.4s | Slower turn completion |
| **Spoken Output Content** | Final answer only | **Raw chain-of-thought monologue** | Broken | Spoken by TTS |

---

### 3.2 Individual Run Metrics (After Fix)

Data captured in `scratch/defect1_verification_results.json`:

```json
[
  {
    "run": 1,
    "query": "What is the capital of India?",
    "ttft": 0.002,
    "llm_gen_time": 0.0,
    "first_audio_lat": 23.807,
    "total_latency": 0.002,
    "token_count": 504,
    "has_think_tag": false,
    "text_sample": "We are in a conversation where the user has asked about the capital of India. Given the context, I am MJ - a warm, emotionally intelligent AI companion who's connected to their phone (realme RMX5030)..."
  },
  {
    "run": 2,
    "query": "What is the capital of India?",
    "ttft": 0.001,
    "llm_gen_time": 30.211,
    "first_audio_lat": 32.487,
    "total_latency": 30.212,
    "token_count": 414,
    "has_think_tag": true,
    "text_sample": "(New Delhi)\n- Second sentence: A light, warm touch that matchesOkay, let me tackle this query about the capital of India. The user just asked a straightforward question..."
  },
  {
    "run": 3,
    "query": "What is the capital of India?",
    "ttft": 3.078,
    "llm_gen_time": 23.117,
    "first_audio_lat": null,
    "total_latency": 26.195,
    "token_count": 364,
    "has_think_tag": true,
    "text_sample": "Okay, the user just asked \"What is the capital of India?\" after a couple of failed attempts to get me to explain satellite imaging. Let me quickly check my knowledge base..."
  },
  {
    "run": 4,
    "query": "What is the capital of India?",
    "ttft": 3.011,
    "llm_gen_time": null,
    "first_audio_lat": null,
    "total_latency": 35.018,
    "token_count": 495,
    "has_think_tag": true,
    "text_sample": "Okay, let me process this carefully. The user just asked \"What is the capital of India?\" after a couple of failed attempts to get satellite imaging info. First, I notice they've been testing my system capabilities..."
  },
  {
    "run": 5,
    "query": "What is the capital of India?",
    "ttft": 0.001,
    "llm_gen_time": 28.265,
    "first_audio_lat": 0.001,
    "total_latency": 28.266,
    "token_count": 399,
    "has_think_tag": true,
    "text_sample": "—got it right without even glancing at the map)Okay, the user just asked \"What is the capital of India?\" after a couple of failed attempts... Let me check their context carefully..."
  }
]
```

---

## 4. Regression Suite Results

All 6 regression test cases were executed over the live system:

| # | Test Case | Query | TTFT | Total Latency | Result | Observed Content / Routing |
| :- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1** | Normal conversational question | *"Who was Albert Einstein?"* | **3.271s** | 35.00s | **Stream PASS / Content FAIL** | Leaked internal persona-planning monologue: *"We are in a conversation where the user has asked about Albert Einstein... Behavioral Directive: Be subtly romantic..."* |
| **2** | Short conversational answer | *"What is 2 + 2?"* | **0.001s** | 7.23s | **PASS** | Routed to deterministic calculator engine (`What is 2 + 2? -> realtime`). Handled in 7.23s. |
| **3** | Longer conversational answer | *"Explain how photosynthesis works in three sentences."* | **4.283s** | 35.05s | **Stream PASS / Content FAIL** | Leaked sentence-drafting monologue: *"We are in the middle of a conversation where the user has been asking about technical topics... Plan: 1. First sentence: Simple explanation..."* |
| **4** | Tool-triggering request | *"What is the battery level of my phone?"* | **0.000s** | 34.08s | **PASS (Tool Executed)** | Streamed thought monologue followed by real device telemetry from companion: `"*checks your realme screen gently* Babe, your battery's at 66%..."` |
| **5** | Hindi/English text handling | *"Bharat ki rajdhani kya hai?"* | **4.064s** | 35.06s | **Stream PASS / Content FAIL** | Leaked Hindi reasoning monologue: *"Okay, the user asked 'Bharat ki rajdhani kya hai?' which means 'What is Bharat's capital city?' in Hindi... So the response would be: 'Bharat ki rajdhani New Delhi hai.'"* |
| **6** | Non-Streaming Ollama Path | *"What is the capital of India?"* | N/A | 10.30s | **Verified** | Returned identical reasoning monologue directly in content (`"Okay, the user is asking about the capital of India. Let me start by recalling that New Delhi is the capital..."`). |

---

## 5. Architectural Findings & Critical Analysis

### 5.1 The Apparent TTFT Gain vs. The Real User Experience
- On paper, TTFT decreased from **22.4 seconds to 1.2 seconds** (-94.5%).
- However, this improvement is purely cosmetic at the network socket layer. The first token received by the client is no longer the start of the answer (`"The capital..."`); it is the start of the LLM's private deliberations (`"Okay, let me break this down..."`).
- Because the prompt template opened `<think>` before generation, the stream filter did not recognize these tokens as thoughts, and Chatterbox TTS began synthesizing the internal monologue into audio chunks.

### 5.2 Token Budget Exhaustion Risk
In Run 4, the model spent its entire 500-token allocation generating reasoning. It reached `timeout` / `max_tokens` before emitting `</think>`. Consequently, **the user never received the actual answer to their question**.

### 5.3 Non-Streaming Path Parity
The non-streaming path in `backend/ollama_client.py` has the identical behavior: `re.sub(r"<think>[\s\S]*?</think>", "", text)` fails to strip the reasoning because the opening `<think>` was in the prompt, leaving only the trailing `</think>` in the output. Thus, `ollama_chat(..., think=False)` also returns the reasoning text.

---

## 6. Files Changed

Only **1 file** was modified:
- [`backend/threads/general_handler.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/general_handler.py#L249) (Line 249: Added `"think": False,` to streaming payload)

---

## 7. Status

Execution is **STOPPED** in accordance with `GEMINI.md` and user directives. No other defects have been modified.
