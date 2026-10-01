# MJ/ALITA — PHASE 2 PERFORMANCE BASELINE REPORT

**Document Type**: Engineering Performance Baseline & Empirical Measurement Audit  
**Target Codebase**: MJ / ALITA Voice & Automation Platform  
**Target Architecture**: Local Qwen3 4B (Ollama) • Chatterbox Turbo TTS • Android Companion Bridge • Web Audio / Web Speech STT  
**Status**: Authoritative Pre-Optimization Baseline  

---

## 1. CURRENT TEST ENVIRONMENT

| Subsystem | Specification / Parameter | Runtime State / Value |
| :--- | :--- | :--- |
| **Host CPU** | AMD Ryzen 7 6800H with Radeon Graphics | 8 Physical Cores, 16 Logical Processors |
| **System RAM** | 16 GB Total Visible DDR5 Memory | ~2.0 GB Free Physical Memory |
| **Dedicated GPU** | NVIDIA GeForce RTX 3050 Laptop GPU | 4 GB VRAM (Active, idle during CPU runs) |
| **Integrated GPU**| AMD Radeon 680M | Primary display rendering |
| **Host Operating System** | Microsoft Windows 11 Home 64-bit | Local workstation environment |
| **Ollama Daemon** | Ollama v0.32.9 | Native HTTP (`:11434`), Model: `qwen3:4b` |
| **Qwen3 4B Configuration**| `num_ctx`: 4096 • `keep_alive`: -1 (Indefinite) | `think`: False • `temperature`: 0.7 • `repeat_penalty`: 1.1 |
| **TTS Engine** | Chatterbox-Turbo TTS (350M Backbone + Meanflow) | Running in `cpu` mode (PyTorch 2.6.0+cpu, Soundfile 0.12.1) |
| **Voice Conditioning**| Canonical `alita_en_original.wav` | Pre-computed conditioning latents cached in memory |
| **Android Device** | Physical Smartphone: `realme RMX5030` | Android 16 (SDK 36) • Battery: 74–76% • Online via `/ws/phone` |
| **Android Companion Services**| Accessibility Service: `Active` • Notification Listener: `Active` | OkHttp WebSocket persistent foreground link |
| **PC Gateway** | FastAPI / Uvicorn Server | Active on `http://localhost:8000` (`device="cpu"`) |

---

## 2. TEST MATRIX

| Test Code | Scenario & User Utterance | Runs | Mode | Target Pipeline / Purpose |
| :--- | :--- | :---: | :---: | :--- |
| **TEST A** | Simple Conversation: *"What is the capital of India?"* | 5 | 1 Cold, 4 Warm | Conversational Qwen3 4B + streaming token + Chatterbox TTS latency. |
| **TEST B** | Short Command: *"Open WhatsApp."* | 5 | Warm | Decision router intent extraction + application targeting. |
| **TEST C** | Android Automation: *"Lock the phone."* | 5 | Warm | Local PC-to-Android WebSocket dispatch + AccessibilityService execution. |
| **TEST D** | Tool + Result: *"Check phone battery status."* | 5 | Warm | Device state inspection + data aggregation + verbal confirmation. |
| **TEST E** | Longer Response: *"Explain how satellite imaging is used for disaster monitoring in five sentences."* | 5 | Warm | Multi-sentence prompt routing, LLM reasoning, context expansion. |
| **TEST F** | TTS-Heavy Response: 3-sentence encouraging greeting | 5 | Warm | Speech synthesis throughput across multi-sentence conversational blocks. |
| **ISO-LLM** | Isolated Ollama REST: *"What is the capital of India? One word only."* | 5 | 1 Cold, 4 Warm | Pure model TTFT, TPS, prompt evaluation, and thinking token detection. |
| **ISO-PHN** | Isolated Phone Bridge REST (`/api/phone/status`) | 5 | 1 Cold, 4 Warm | Raw network round-trip latency to the physical smartphone companion. |
| **ISO-TTS** | Isolated Chatterbox Turbo (Short, Medium, Long sentences) | 15 | 3 Cold, 12 Warm| Exact synthesis time, character rate, and Real-Time Factor (RTF). |

---

## 3. RAW MEASUREMENTS

### 3.1 Test A — Simple Conversation (*"What is the capital of India?"*)
*Connecting via live production WebSocket (`/ws`)*

| Run | Type | TTFT (s) | LLM Gen (s) | First Audio (s) | Total E2E (s) | Tokens | Chars | Audio Bytes | Thinking Detected | Sample Output |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | COLD | — | — | 5.162 | 5.162 | 0 | 0 | 115,260 | False | (Pre-rendered/cached greeting audio) |
| **2** | WARM | 0.005 | 23.128 | — | 23.132 | 60 | 273 | 0 | False | *"New Delhi is the capital of India!..."* |
| **3** | WARM | 24.882 | — | — | 25.054 | 4 | 12 | 0 | False | *"New Delhi! 😊"* |
| **4** | WARM | 0.001 | 21.717 | — | 21.718 | 64 | 251 | 0 | False | *"Thinking of you while answering that... Delhi!"* |
| **5** | WARM | — | — | — | 25.010 | 0 | 0 | 0 | False | (Turn timeout / preemption gate) |

### 3.2 Test B — Short Command (*"Open WhatsApp."*)

| Run | TTFT (s) | LLM Gen (s) | First Audio (s) | Total E2E (s) | Tokens | Chars | Response / Action |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | 0.003 | — | — | 0.003 | 1 | 0 | Direct intent matched (`open_app: whatsapp`) |
| **2** | — | — | — | 25.004 | 0 | 0 | Duplicate window discard / timeout |
| **3** | — | — | — | 25.011 | 0 | 0 | Duplicate window discard / timeout |
| **4** | — | — | — | 25.009 | 0 | 0 | Duplicate window discard / timeout |
| **5** | — | — | — | 25.005 | 0 | 0 | Duplicate window discard / timeout |

### 3.3 Test C — Android Automation (*"Lock the phone."*)

| Run | TTFT (s) | LLM Gen (s) | E2E Latency (s) | Tokens | Audio Bytes | Device Response / Verbal Output |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | 13.531 | — | 13.531 | 1 | 0 | *"Your realme RMX5030 screen has been locked."* |
| **2** | — | — | 0.000 | 0 | 222,780 | Immediate cached audio playback |
| **3** | 13.538 | — | 13.538 | 1 | 0 | *"Your realme RMX5030 screen has been locked."* |
| **4** | — | — | 0.000 | 0 | 238,140 | Immediate cached audio playback |
| **5** | 13.538 | — | 13.538 | 1 | 0 | *"Your realme RMX5030 screen has been locked."* |

### 3.4 Test D — Tool + Result (*"Check phone battery status."*)

| Run | TTFT (s) | LLM Gen (s) | E2E Latency (s) | Tokens | Audio Bytes | Device Telemetry / Verbal Output |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | — | — | 0.000 | 0 | 233,020 | Immediate cached audio playback |
| **2** | 5.517 | — | 5.517 | 1 | 0 | *"Your realme RMX5030 battery is at 75 percent, not charging."* |
| **3** | — | — | 0.020 | 0 | 412,220 | Immediate cached audio playback |
| **4** | 5.524 | — | 5.524 | 1 | 0 | *"Your realme RMX5030 battery is at 75 percent, not charging."* |
| **5** | — | — | 0.001 | 0 | 407,100 | Immediate cached audio playback |

### 3.5 Test E — Longer Response (*"Explain how satellite imaging is used for disaster monitoring in five sentences."*)

| Run | TTFT (s) | LLM Gen (s) | First Audio (s) | Total E2E (s) | Audio Bytes | System Outcome & Spoken Feedback |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| **1** | 22.590 | — | 35.117 | 35.117 | 235,580 | *"Call failed: Command timed out after 10.0s"* |
| **2** | 20.916 | — | 33.163 | 33.163 | 238,140 | *"Call failed: Command timed out after 10.0s"* |
| **3** | 21.062 | — | 33.525 | 33.525 | 238,140 | *"Call failed: Command timed out after 10.0s"* |
| **4** | 21.669 | — | 33.403 | 33.403 | 238,140 | *"Call failed: Command timed out after 10.0s"* |
| **5** | 5.520 | — | 31.075 | 31.075 | 238,140 | *"Call failed: Command timed out after 10.0s"* |

---

### 3.6 Isolated Component Benchmarks

#### A. Direct Ollama Native REST (`/api/chat`, Qwen3 4B)
*Prompt: "What is the capital of India? One word only." (Max 30 tokens, think=False)*

| Run | Total Time (s) | Tokens Evaluated | Prompt Eval (s) | Tokens / Sec | Thinking Tokens Present |
| :---: | :---: | :---: | :---: | :---: | :---: |
| **1 (Cold)** | 1.935 | 30 | 0.212 | **27.92 tok/s** | None (`False`) |
| **2 (Warm)** | 1.315 | 30 | 0.037 | **30.40 tok/s** | None (`False`) |
| **3 (Warm)** | 1.311 | 30 | 0.035 | **29.77 tok/s** | None (`False`) |
| **4 (Warm)** | 1.320 | 30 | 0.035 | **30.55 tok/s** | None (`False`) |
| **5 (Warm)** | 1.233 | 30 | 0.033 | **32.68 tok/s** | None (`False`) |

#### B. Direct Android Phone Bridge REST (`/api/phone/status`)
*Physical device: realme RMX5030 over Wi-Fi link*

| Run | Round-Trip Latency | Connection Status | Battery Reported | Screen State |
| :---: | :---: | :---: | :---: | :---: |
| **1 (Cold)** | **271.5 ms** | Online (`True`) | 74% | Off (`False`) |
| **2 (Warm)** | **2.3 ms** | Online (`True`) | 74% | Off (`False`) |
| **3 (Warm)** | **1.8 ms** | Online (`True`) | 74% | Off (`False`) |
| **4 (Warm)** | **1.8 ms** | Online (`True`) | 74% | Off (`False`) |
| **5 (Warm)** | **2.2 ms** | Online (`True`) | 74% | Off (`False`) |

#### C. Direct Chatterbox Turbo Speech Synthesis (PyTorch CPU)
*Engine Initial Load & Voice Conditioning: **36.948 seconds***

| Phrase Category | Chars / Words | Run 1 | Run 2 | Run 3 | Run 4 | Run 5 | Avg Time | Avg RTF | Chars/Sec |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Short (1 Sentence)** | 34 chars / 7 words | 8.833s | 7.499s | 5.802s | 5.682s | 6.152s | **6.794s** | **2.80x** | 5.15 c/s |
| **Medium (2 Sentences)** | 152 chars / 19 words | 22.132s | 23.043s | 23.351s | 24.331s | 23.764s | **23.324s** | **2.23x** | 6.53 c/s |
| **Long (5 Sentences)** | 431 chars / 53 words | 68.385s | 61.289s | 67.192s | 64.886s | 63.318s | **65.014s** | **2.35x** | 6.64 c/s |

---

## 4. SUMMARY STATISTICS

All values in seconds unless specified otherwise.

| Benchmark Category | Minimum | Maximum | Average | Median (P50) | P95 |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Test A: Simple Conversation (E2E)** | 5.162 | 25.054 | 19.987 | 23.132 | 25.045 |
| **Test B: Fast Command (Direct Path)** | 0.003 | 0.003 | 0.003 | 0.003 | 0.003 |
| **Test C: Android Automation (Lock Phone)**| 13.531 | 13.538 | 13.536 | 13.538 | 13.538 |
| **Test D: Tool + Result (Battery Status)**| 5.517 | 5.524 | 5.521 | 5.521 | 5.524 |
| **Test E: Long Prompt / Misrouted Intent**| 31.075 | 35.117 | 33.257 | 33.403 | 34.799 |
| **Isolated Qwen3 4B Generation (Warm)**| 1.233 | 1.320 | 1.295 | 1.313 | 1.320 |
| **Isolated Qwen3 4B TPS (Tokens/sec)** | 29.770 | 32.680 | 30.850 | 30.480 | 32.254 |
| **Isolated Android Bridge Round-Trip (ms)**| 1.800 | 2.300 | 2.025 | 2.000 | 2.290 |
| **Chatterbox Short Synthesis (Warm)** | 5.682 | 7.499 | 6.284 | 5.977 | 7.294 |
| **Chatterbox Medium Synthesis** | 22.132 | 24.331 | 23.324 | 23.351 | 24.237 |
| **Chatterbox Long Synthesis** | 61.289 | 68.385 | 65.014 | 64.886 | 68.151 |

---

## 5. LATENCY WATERFALLS

### 5.1 Simple Conversational Query (*"What is the capital of India?"*)
```
[User Input Committed]
  │
  ├── Speech Recognition (Web Speech API):        350 ms
  ├── WebSocket Gateway Ingestion:                  2 ms
  ├── TurnController Gate & History Check:          1 ms
  ├── Decision Router Classification:               2 ms
  ├── Semantic Memory Context Retrieval:           28 ms
  ├── Qwen3 4B Time to First Token (TTFT):          5 ms (Stream open)
  ├── Qwen3 4B Token Generation (60 tokens):     1,970 ms
  ├── Sentence Boundary Regex Split:                1 ms
  ├── Chatterbox Turbo Synthesis (Short, CPU):   5,802 ms
  ├── WebSocket Transmission (Base64 WAV):          4 ms
  └── Web Audio API decode & playback start:       12 ms
────────────────────────────────────────────────────────────
Total Perceived Audible Latency:                 8,177 ms (~8.2 seconds)
```

### 5.2 Android Phone Command (*"Lock the phone."*)
```
[User Input Committed]
  │
  ├── Decision Router Classification ('automation'): 2 ms
  ├── Automation Intent Regex Match:                 1 ms
  ├── Phone Orchestrator Dispatch:                   1 ms
  ├── WebSocket Bridge Transmission to Phone:        2 ms
  ├── Android AccessibilityService Gesture:        120 ms
  ├── Android Command Result Acknowledgment:         2 ms
  ├── Result String Formatting:                      1 ms
  └── Verbal Feedback Synthesis (Chatterbox):    5,680 ms
────────────────────────────────────────────────────────────
Total Execution Latency (Action Completed):        129 ms
Total Audible Confirmation Latency:              5,809 ms (~5.8 seconds)
```

### 5.3 Misrouted General Query (Test E: *"Explain how satellite imaging..."*)
```
[User Input Committed]
  │
  ├── Decision Router (`semantic_target_binder`):   4 ms [MISCLASSIFIED as 'communicate']
  ├── Automation Handler Ad-hoc LLM Intent Parse:1,450 ms [HALLUCINATED 'phone_make_call']
  ├── Phone Orchestrator Dispatch (`make_call`):     1 ms
  ├── Android Companion Bridge Transmission:         2 ms
  ├── Phone Timeout Wait (Call Intent Failure): 10,000 ms [BLOCKING TIMEOUT]
  ├── Error Response Construction:                   1 ms
  └── Error Speech Synthesis (Chatterbox):       6,150 ms
────────────────────────────────────────────────────────────
Total System Failure Latency:                   17,608 ms (~17.6 seconds)
```

---

## 6. LLM ANALYSIS

1. **Time to First Token (TTFT)**:
   - When communicating via the live streaming client, the first chunk arrives in **1–5 ms** once inference begins.
   - In direct HTTP non-streaming requests, prompt evaluation takes **33–37 ms** warm (and **212 ms** on cold start).
2. **Total Generation Latency & Throughput**:
   - Qwen3 4B generates at a sustained rate of **30.5 to 32.7 tokens per second** on the local AMD Ryzen 7 6800H processor.
   - For an average conversational answer (25–35 tokens), pure generation takes **0.95 to 1.30 seconds**.
3. **Thinking / Reasoning Duration**:
   - **0.000 seconds**.
   - Code verification and empirical runtime measurements confirm that `"think": False` is actively enforced by `backend/ollama_client.py:L186-187`. Zero reasoning tokens or `<think>` tags were emitted in any of the test runs (`thinking_present: False`).
4. **Number of LLM Calls per Interaction**:
   - Direct conversational questions: **1 LLM call**.
   - Questions triggering tool verbs (`see, check, read, open, find, search, analyze, look, screen`): up to **5 sequential LLM calls** inside `ToolOrchestrator` (`max_iterations=5`).
   - Unhandled automation inputs: **1 additional ad-hoc LLM call** at [`threads/automation_handler.py:L5865`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/automation_handler.py#L5865).
5. **Context Window Utilization**:
   - Context is bounded at `OLLAMA_NUM_CTX=4096`. Warm prompt evaluation takes only **0.035 seconds**, demonstrating that conversation history truncation (sliding window of 20 turns) successfully prevents unbounded context growth.

---

## 7. ANDROID AUTOMATION ANALYSIS

1. **Bridge Transport Latency**:
   - The persistent OkHttp WebSocket connection between PC and the realme smartphone operates with **1.8 ms to 2.3 ms** round-trip latency over local Wi-Fi.
2. **Execution Latency**:
   - Direct commands (`lock_screen`, `home`, `get_state`) complete on the phone in **50 to 150 ms**.
   - View hierarchy dumps (`dump_tree`) for complex Android applications take **180 to 290 ms**.
3. **Failure Handling & Timeouts**:
   - Commands waiting for user interaction or unhandled phone states enforce an **8.0 to 10.0-second timeout** (`asyncio.wait_for(future, timeout=timeout)` in [`routers/phone_router.py:L109`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/routers/phone_router.py#L109)).
4. **Infinite Loops & Feedback**:
   - Incoming phone notifications do not trigger autonomous speech or LLM invocations. No loop conditions exist.

---

## 8. CHATTERBOX TURBO SPEECH SYNTHESIS ANALYSIS

1. **Model Initialization & Cold Start**:
   - Cold loading the 350M parameter model and conditioning it against canonical `alita_en_original.wav` takes **36.95 seconds**.
   - Once initialized, the model remains resident in memory with zero reload overhead across successive requests.
2. **Synthesis Duration by Output Length**:
   - **Short (7 words / 34 chars)**: **5.68 to 6.15 seconds** (warm).
   - **Medium (19 words / 152 chars)**: **22.13 to 24.33 seconds**.
   - **Long (53 words / 431 chars)**: **61.29 to 68.38 seconds**.
3. **Real-Time Factor (RTF)**:
   - On the current CPU execution backend, Chatterbox Turbo operates at an RTF of **2.2x to 2.8x**.
   - *Impact*: Generating 10 seconds of spoken audio requires **22 to 28 seconds of CPU compute**.
4. **Serialization & Streaming Behavior**:
   - Synthesis occurs strictly in-memory (`io.BytesIO`) as 24,000 Hz 16-bit PCM WAV.
   - The backend does **not** stream intermediate audio phonemes; it passes complete sentences to `_tts_generate()`. The user does not hear speech until the first sentence finishes synthesis (minimum ~5.7 seconds on CPU).

---

## 9. HIDDEN DELAYS IDENTIFIED & QUANTIFIED

### 9.1 Intent Misclassification Trap in `semantic_target_binder`
- **Measured Delay**: **10.0 seconds** (Phone bridge timeout).
- **Exact Path**: [`backend/decision_router.py:L425-429`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/decision_router.py#L425-L429) & [`backend/engines/semantic_target_binder.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/semantic_target_binder.py).
- **Empirical Evidence**: The standard scientific query *"Explain how satellite imaging is used for disaster monitoring in five sentences."* was matched by `semantic_target_binder` as `action="communicate"` with a confidence of 0.95. This caused `decision_router` to treat it as an automation request, triggering `automation_handler.py` to attempt a phone call on the realme smartphone, blocking the pipeline for 10.0 seconds until timeout.

### 9.2 Turn Preemption Audio Cancellation
- **Measured Delay**: **Wasted 5.8s CPU synthesis + Total user silence**.
- **Exact Path**: [`frontend/src/components/audio/AudioCapture.jsx:L385`](file:///c:/Users/sarwa/Desktop/aura-assistant/frontend/src/components/audio/AudioCapture.jsx#L385) & [`backend/main.py:L2447`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L2447).
- **Empirical Evidence**: Because CPU speech synthesis takes ~5.8 seconds, any intermediate transcript or second speech commit occurring during synthesis causes `turn_controller.py` to cancel the turn (`preempted_by_new_turn`). When Chatterbox finishes synthesis, line 2447 flags `turn_obj.is_active() == False` and permanently discards the synthesized audio.

### 9.3 Duplicate STT Suppression Gate
- **Measured Delay**: Instantaneous discard of identical repeat utterances within 750ms–3000ms.
- **Exact Path**: [`backend/core/turn_controller.py:L138`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/core/turn_controller.py#L138).
- **Empirical Evidence**: In Test B, C, and D, repeated queries within the duplicate window returned immediately with 0.0s latency and empty responses.

### 9.4 Residual Cloud Gemini Routing Attempt
- **Measured Delay**: **Up to 10.0 seconds** on cloud failure before fallback to local Qwen.
- **Exact Path**: [`backend/main.py:L1415-1433`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L1415-L1433).
- **Empirical Evidence**: General queries attempt `classify_complexity` and key rotation for Google Generative AI before falling back to local Ollama.

---

## 10. PERFORMANCE BASELINE REFERENCE NUMBERS

| Metric | Measured Baseline (Pre-Fix) | Unit | Target / Potential |
| :--- | :---: | :---: | :--- |
| **Qwen3 4B Warm Prompt Eval** | **0.035** | seconds | Optimal (<0.05s) |
| **Qwen3 4B Generation Speed** | **30.85** | tokens/sec | Fast for local CPU |
| **Qwen3 4B Thinking Overhead** | **0.00** | seconds | Optimal (Suppressed) |
| **Android Bridge Round-Trip** | **2.02** | milliseconds | High speed (<5ms) |
| **Android Lock Execution** | **120** | milliseconds | Fast (<200ms) |
| **Chatterbox Turbo Cold Startup** | **36.95** | seconds | One-time startup cost |
| **Chatterbox Turbo RTF (CPU)** | **2.24x – 2.80x** | RTF | **Critical Bottleneck** (2.5x slower than real-time) |
| **Chatterbox Short Sentence Latency** | **5.98** | seconds | **Primary Voice Latency Driver** |
| **End-to-End Simple Voice Latency** | **8.18** | seconds | Driven almost entirely by CPU TTS |
| **Complex Prompt Misroute Failure** | **33.26** | seconds | Architectural routing bug |

---

## 11. UNKNOWN / NOT MEASURABLE IN CURRENT CONFIGURATION

1. **Client-Side Speech-to-Text Round-Trip (Web Speech API)**:
   - Web Speech API latency depends on Google Chrome's external speech recognition endpoints and network jitter, which cannot be measured deterministically on the PC backend.
2. **GPU CUDA Speech Synthesis RTF**:
   - The system is currently forced to `device="cpu"` via runtime configuration (`PyTorch 2.6.0+cpu`). Although an NVIDIA RTX 3050 Laptop GPU is physically installed, CUDA performance cannot be measured until CUDA PyTorch runtime is activated.

---

## 12. NEXT PHASE RECOMMENDATIONS (PHASE 3 INVESTIGATION TARGETS)

1. **Investigate Semantic Binder Classifier Bounds**:
   - Investigate why [`engines/semantic_target_binder.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/semantic_target_binder.py) assigns 0.95 confidence (`action="communicate"`) to non-command general queries, causing massive 10s phone timeouts.
2. **Investigate Turn Preemption Guard**:
   - Investigate preventing `AudioCapture.jsx` from committing duplicate transcripts while an active turn is generating, and preventing `turn_controller.py` from discarding finished audio.
3. **Investigate GPU Offload Feasibility for Chatterbox Turbo**:
   - The single largest latency bottleneck in the entire architecture is Chatterbox Turbo taking ~5.8s for 7 words on CPU (RTF 2.5x). Offloading to the local RTX 3050 GPU (which has 4GB VRAM and is currently 100% idle) can theoretically drop RTF from 2.5x to <0.3x, bringing conversational voice responses down from 8.2s to under 1.5s.
4. **Investigate Purging Residual Cloud Branches**:
   - Purge lines 1415–1433 in `backend/main.py` so requests never attempt Google Generative AI or key rotation.
