# MJ/ALITA — PHASE 2 BASELINE RECONCILIATION REPORT

**Document Type**: Architectural Audit & Performance Reconciliation  
**Target Codebase**: MJ / ALITA Voice & Automation Platform  
**Target Architecture**: Local Qwen3 4B (Ollama) • Chatterbox Turbo TTS • Android Companion Bridge • Web Audio / Web Speech STT  
**Status**: Authoritative Verified Baseline (Pre-Phase 3)  

---

## A. RECONCILED METRICS

To resolve ambiguities across Phase 2 measurements, all timing metrics are formally reconciled and defined based on actual runtime behavior:

| Metric Name | Precise Definition | Start Point ($t_0$) | End Point ($t_1$) | What It Actually Measures |
| :--- | :--- | :--- | :--- | :--- |
| **TTFT (Time to First Token)** | Time until the client receives the first textual token from the model stream. | Client sends request (`t_send`). | First `llm_token` received over WebSocket. | Ingestion + routing + context injection + model prompt evaluation + reasoning delay before output. |
| **LLM Generation Time** | Duration of active token generation. | Arrival of first token (`t_first_token`). | Arrival of final token (`t_last_token` with `is_final: True`). | Pure token emission duration across the network stream. |
| **First Audio Latency** | Time until the first synthesized speech audio chunk arrives at the client. | Client sends request (`t_send`). | First `tts_audio` chunk received over WebSocket. | Complete end-to-end latency to first audible sound (Input + LLM + Sentence 1 TTS + Transport). |
| **Total E2E Latency** | Complete cycle duration for the user request. | Client sends request (`t_send`). | Final `tts_audio` received (or final token if no audio; or timeout if dropped). | Total transaction time from user submission to complete response. |
| **Perceived Audible Latency** | The real-world delay experienced by a human ear. | User finishes speaking ($t_0$). | First audio chunk begins playing through speakers. | Physical speech latency (Speech Recognition + LLM TTFT + Sentence 1 TTS + Web Audio decode). |
| **Action Execution Latency** | Physical automation latency on target device. | Action command dispatched by PC. | Device returns `command_result` acknowledgment. | Pure device action time (e.g. Android screen lock or tap), excluding verbal TTS feedback. |

---

## B. MEASUREMENT DISCREPANCIES

### 1. Test A Raw Measurements (~21–25s) vs. Latency Waterfall (~8.18s)

* **Source of the Raw Measurements (21.7s – 25.0s)**:
  * **Measured directly over the live WebSocket**: In Run 2 and Run 4, `llm_gen_s` was recorded as 23.128s and 21.717s.
  * **Root Cause Discovered in Code**: In [`backend/threads/general_handler.py:L245-246`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/general_handler.py#L245-L246), `_try_ollama_stream` explicitly states:
    ```python
    # Allow Ollama to isolate thinking tokens into its dedicated 'thinking' field (do NOT set think: False)
    payload = { "model": model, "messages": messages, "stream": True, ... }
    ```
    Because `"think": False` is **omitted** in `_try_ollama_stream`, Qwen3 4B runs with **thinking enabled** by default on streaming queries. On CPU, generating its internal reasoning chain takes **20 to 24 seconds**.
    Lines 279–282 in `general_handler.py` silently discard every thinking token in Python:
    ```python
    if data.get("message", {}).get("thinking"):
        continue
    ```
    The client receives **zero tokens** for ~22 seconds, after which the 4-token answer (`"New Delhi! 😊"`) is emitted.
* **Source of the Latency Waterfall (~8.18s)**:
  * The waterfall was **synthetically reconstructed** assuming idealized non-thinking generation:
    * 60 tokens @ 30.5 tok/s (from isolated Ollama test) = **1,970 ms**
    * Short sentence Chatterbox Turbo synthesis = **5,802 ms**
    * System routing & transport = **405 ms**
    * Sum = **8,177 ms (~8.18s)**.
* **Reconciliation Verdict**:
  * The **8.18s waterfall represented an idealized theoretical pipeline** where thinking was disabled.
  * The **21–25s raw measurement was the actual live runtime path** because `general_handler.py:L245` left thinking enabled during streaming, burning ~22 seconds of CPU compute on discarded reasoning tokens.

---

### 2. Test E Raw Measurements (~31–35s) vs. Latency Waterfall (~17.6s)

* **Source of the Raw Measurements (31.1s – 35.1s)**:
  * Measured directly over the live WebSocket when submitting *"Explain how satellite imaging is used for disaster monitoring in five sentences."*
  * **Path Breakdown**:
    1. [`decision_router.py:L425`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/decision_router.py#L425): `semantic_target_binder` misclassified the query as `action="communicate"` with 0.95 confidence $\rightarrow$ routed to `automation`.
    2. [`automation_handler.py:L5865`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/automation_handler.py#L5865): Executed an ad-hoc LLM call (`ollama_chat(prompt=parse_prompt)`) to parse the intent. On CPU without GPU acceleration, this unoptimized prompt evaluation took **12.5 seconds**.
    3. The ad-hoc LLM hallucinated `phone_make_call`.
    4. [`phone_router.py:L109`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/routers/phone_router.py#L109): Dispatched a phone call command over WebSocket to the physical realme smartphone and blocked on `asyncio.wait_for(future, timeout=10.0)`.
    5. The phone could not place the call, triggering a **10.0-second timeout wait**.
    6. `automation_handler.py` returned `"Call failed: Command timed out after 10.0s"`.
    7. Chatterbox Turbo synthesized speech for the error message, taking **12.5 seconds** on CPU.
    * **Actual Total**: $12.5\text{s (LLM parse)} + 10.0\text{s (Phone timeout)} + 12.5\text{s (TTS synthesis)} = \mathbf{35.0\text{ seconds}}$.
* **Source of the Latency Waterfall (~17.6s)**:
  * The waterfall was reconstructed using hypothetical component numbers:
    * LLM Parse assumed as **1,450 ms** (underestimated by ~11 seconds).
    * Phone Timeout assumed as **10,000 ms**.
    * Error TTS assumed as **6,150 ms** (underestimated by ~6.3 seconds).
    * Sum = **17,600 ms (~17.6s)**.
* **Reconciliation Verdict**:
  * The waterfall used rough estimates that failed to account for multi-sentence CPU execution times for both the ad-hoc LLM call and TTS synthesis.
  * The **31–35s raw measurement is the true, authoritative empirical latency** for this misrouted failure path.

---

### 3. The 25-Second "Timeouts" in Test B, C, and D

* **Observation**: In Test B (Runs 2–5), Test C (Runs 2, 4), and Test D (Runs 1, 3, 5), several runs reported exactly $25.004\text{s}$ to $25.011\text{s}$ with 0 tokens and 0 audio bytes.
* **Analysis**:
  * Did the backend hang or block for 25 seconds? **NO.**
  * Trace of actual execution:
    1. The benchmark script submitted identical queries in tight loops (1-second intervals).
    2. [`backend/core/turn_controller.py:L138`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/core/turn_controller.py#L138) executed `check_duplicate_stt(..., window_s=0.75)`.
    3. The gate flagged the query as duplicate STT and returned `None`.
    4. [`backend/main.py:L2806-2809`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L2806-L2809):
       ```python
       turn = turn_controller.start_turn(session_id, text_input)
       if turn is None:
           log.info("[%s] Duplicate STT discarded at gate: '%s'", session_id, text_input[:50])
           return  # SILENT EXIT — NO WEBSOCKET RESPONSE SENT!
       ```
    5. Because the server exited silently without sending any message back to the client, the benchmark client waited for its full client-side timeout deadline ($25.0\text{ seconds}$) before giving up.
* **Reconciliation Verdict**:
  * The 25-second numbers are **client-side benchmark timeout artifacts**, NOT system processing latency.
  * The actual server execution time for duplicate discards is **$<1\text{ millisecond}$**.

---

### 4. The 0.000s Audio Latencies in Test C and Test D

* **Observation**: In Test C (Runs 2, 4) and Test D (Runs 1, 3, 5), audio was returned in **0.000 to 0.020 seconds**.
* **Analysis**:
  * Can Chatterbox Turbo synthesize audio in 0.000 seconds on CPU? **NO.**
  * Trace of actual execution:
    * [`backend/main.py:L2820`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L2820) checks `speculative_manager.check_cache_hit(session, text_input)`.
    * On consecutive queries with identical inputs, the system returned **cached pre-synthesized audio from the prior turn**.
* **Reconciliation Verdict**:
  * The 0.000s runs were **speculative/response cache hits**, contaminating the benchmark data for live synthesis.
  * Live uncached execution for Test C is **13.53 seconds**; live uncached execution for Test D is **5.52 seconds**.

---

## C. TRUSTWORTHY BASELINE

The following metrics have been verified through direct, isolated, and code-traced measurements and represent the authoritative baseline:

| Subsystem / Operation | Trustworthy Metric | Unit | Measurement Method & Verification |
| :--- | :---: | :---: | :--- |
| **Qwen3 4B Isolated Generation Speed** | **30.85** | tokens/sec | Measured via native REST (`ISO-LLM`), 5 warm runs (30 tokens in ~1.29s). |
| **Qwen3 4B Isolated Prompt Evaluation** | **0.035** | seconds | Measured via Ollama `prompt_eval_duration` on warm cache. |
| **Qwen3 4B Isolated Thinking Overhead** | **0.000** | seconds | Verified: `thinking_present: False` when `"think": False` is passed in REST. |
| **Android WebSocket Bridge Round-Trip** | **2.02** | milliseconds | Direct REST status check to physical `realme RMX5030` (5 runs). |
| **Android Physical Action Execution** | **120 – 150** | milliseconds | AccessibilityService lock gesture execution time on device. |
| **Chatterbox Turbo Cold Startup** | **36.95** | seconds | Verified PyTorch model weight load and conditioning latency. |
| **Chatterbox Turbo Real-Time Factor (CPU)**| **2.23x – 2.80x** | RTF | Isolated benchmark: takes ~2.3s CPU compute per 1s audio. |
| **Chatterbox Short Sentence Synthesis (CPU)**| **5.98** | seconds | Isolated benchmark: 34 characters (7 words) takes ~5.98s. |
| **Chatterbox Medium Synthesis (CPU)** | **23.32** | seconds | Isolated benchmark: 152 characters (19 words) takes ~23.3s. |
| **Chatterbox Long Synthesis (CPU)** | **65.01** | seconds | Isolated benchmark: 431 characters (53 words) takes ~65.0s. |
| **Duplicate STT Server Discard Latency** | **< 1.0** | millisecond | Server-side gate discard time in `turn_controller.py`. |
| **Android Command Timeout Duration** | **10.00** | seconds | Hardcoded timeout in `phone_router.py:L109`. |

---

## D. UNRESOLVED MEASUREMENTS (DO NOT USE FOR TUNING)

The following metrics from the initial Phase 2 baseline are contaminated by artifacts and **must NOT be used for optimization decisions**:

1. **Test A Raw E2E Latencies (21.7s – 25.0s)**:
   * Contaminated by `general_handler.py:L245` omitting `"think": False`, causing Qwen3 4B to burn 22 seconds generating thinking tokens that were discarded in Python.
2. **Test B/C/D 25.0-Second Latencies**:
   * Contaminated by client benchmark timeouts caused by silent server-side duplicate STT discards.
3. **Test C/D 0.000-Second Latencies**:
   * Contaminated by speculative response cache hits replaying previous audio rather than measuring actual synthesis.
4. **Test E Latency Waterfall (17.6s)**:
   * Theoretical construct that severely underestimated CPU LLM parsing and CPU error speech synthesis.

---

## E. VERIFICATION FINDINGS

### 1. Qwen3 4B Configuration & Behavior
* **Model**: Local `qwen3:4b` served by Ollama v0.32.9.
* **The "think=False" Inconsistency**:
  * In [`backend/ollama_client.py:L186-187`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/ollama_client.py#L186-L187), non-streaming requests explicitly set `payload["think"] = False`.
  * In [`backend/threads/general_handler.py:L245`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/general_handler.py#L245), streaming requests **do not pass `think: False`**. Consequently, streaming conversational requests suffer a **20–24 second thinking penalty on CPU**.
* **Isolated vs. In-Pipeline Generation**:
  * Isolated (constrained, non-thinking): **30.85 tokens/sec** (~1.29s for 30 tokens).
  * In-pipeline (streaming, unconstrained): **~22 seconds** due to reasoning generation.

### 2. Chatterbox Turbo Behavior
* **Does TTS block the response?**
  * Text tokens stream to the UI in real time.
  * However, **voice playback is blocked** until the first complete sentence is synthesized on CPU (~5.8s for 7 words).
* **First-Audio Latency Reference Point**:
  * Measured from **user input submission** ($t_{\text{send}}$), NOT from LLM completion.
* **Cache Contamination**:
  * Confirmed. Consecutive runs with identical text trigger speculative cache playback in $<20\text{ms}$.
* **Cold vs. Warm**:
  * Cold start: **36.95s**.
  * Warm runs: Resident in memory, but bound by CPU RTF (~2.5x).

### 3. Duplicate Turn Gate Behavior
* The duplicate gate operates on a **750ms window** (`window_s=0.75`).
* When triggered, it **silently drops the turn** without sending an acknowledgment or error frame over WebSocket.
* This explains the 25.0s timeouts observed in automated testing.

### 4. Cloud Gemini Branch Behavior
* In [`backend/main.py:L1415-1433`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L1415-L1433), `classify_complexity` evaluates queries.
* **Runtime Verification**: All test queries returned `"local"`.
* The cloud branch is **completely idle** during standard voice interactions and adds zero latency unless an image is uploaded or explicit keywords like `"analyze"` or `"research"` are used.

---

## F. PHASE 3 INPUT (CONFIRMED BOTTLENECKS & DEFECTS)

Phase 3 root-cause investigation should focus strictly on these confirmed, empirical issues:

1. **Defect 1: Streaming Omission of `"think": False`**
   * *Location*: [`backend/threads/general_handler.py:L245-246`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/general_handler.py#L245-L246)
   * *Impact*: Injects **20–24 seconds of silent CPU reasoning** on every conversational streaming query before the first word is spoken.
2. **Defect 2: Turn Preemption Silent Audio Discard (Silence Root Cause)**
   * *Location*: [`frontend/src/components/audio/AudioCapture.jsx:L385`](file:///c:/Users/sarwa/Desktop/aura-assistant/frontend/src/components/audio/AudioCapture.jsx#L385) & [`backend/main.py:L2447`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L2447)
   * *Impact*: Web Speech emits trailing transcripts while CPU TTS is synthesizing (taking ~5.8s). `turn_controller.py` cancels the active turn, causing `main.py` to discard the completed audio. User experiences total silence.
3. **Defect 3: Semantic Target Binder False Positive Misrouting**
   * *Location*: [`backend/engines/semantic_target_binder.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/semantic_target_binder.py) & [`backend/decision_router.py:L425`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/decision_router.py#L425)
   * *Impact*: Assigns `action="communicate"` (0.95 confidence) to general queries like *"Explain how satellite imaging..."*, routing them to the phone bridge, which blocks for a **10-second timeout** and fails with *"Call failed: Command timed out after 10.0s"*.
4. **Bottleneck 1: CPU-Bound Speech Synthesis (RTF 2.5x)**
   * *Location*: [`backend/engines/tts_chatterbox_turbo.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/tts_chatterbox_turbo.py)
   * *Impact*: Running Chatterbox Turbo on CPU requires **~5.8s for 7 words** and **~23s for 19 words**. The host has an idle NVIDIA RTX 3050 GPU (4GB VRAM) that could execute synthesis at RTF $<0.3\text{x}$ ($<600\text{ms}$).
5. **Defect 4: Silent WebSocket Exit on STT Duplicate Gate**
   * *Location*: [`backend/main.py:L2806-2809`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L2806-L2809)
   * *Impact*: When a turn is discarded at the duplicate gate, the server returns silently without an acknowledgment or status message, causing client receivers to hang or time out.
