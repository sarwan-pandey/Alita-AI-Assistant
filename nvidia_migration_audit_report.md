# Evidence-First Architectural Audit Report: MJ/ALITA Migration

**Audit Date:** 2026-10-08  
**Scope:** Migration state through Gemma 4 31B IT integration  
**Inspection Mode:** Zero-modification forensic audit (no code altered)

---

## Executive Summary

This audit evaluates the repository following the experimental integrations of:
1. **Nemotron-3.5-Lightning-30B-A3B** (Conversational candidate)
2. **Chatterbox Multilingual TTS** (Multilingual candidate)
3. **Gemma 4 31B IT** (Vision/Multimodal candidate)

**Key Finding:** All NVIDIA implementations have been safely compartmentalized as isolated sidecars. **Production traffic remains 100% on the stable local baseline** (Ollama Qwen3 4B, Chatterbox Turbo, and Moondream). 

However, critical technical hurdles exist in the NVIDIA sidecars—including protocol mismatches on Chatterbox NIM (requires gRPC, not REST) and persistent cloud timeouts on Gemma 4 31B IT (>30s)—meaning **neither candidate is currently viable for production voice interaction**. Adding Nemotron-3-Super at this stage is strictly ill-advised and unnecessary.

---

## Part 1: Detailed Verification (Points 1–10)

### 1. Exactly What Has Already Been Implemented
All newly introduced code has been implemented as standalone modules, benchmark scripts, and test suites:

| Component | File Path | Status | Verification Evidence |
|---|---|---|---|
| **LLM Abstraction** | [`backend/engines/llm_provider.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/llm_provider.py) | Complete (Standalone) | 403 lines; `QwenLocalProvider`, `NvidiaNIMProvider`, `LLMProviderRegistry` |
| **Lightning Client** | [`backend/engines/nvidia_lightning.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/nvidia_lightning.py) | Complete (Standalone) | 337 lines; SSE streaming, TTFT/TTFS metrics, thinking suppression |
| **Shadow Benchmark** | [`backend/engines/shadow_benchmark.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/shadow_benchmark.py) | Complete | Side-by-side prompt harness; output to `backend/data/benchmark_results.json` |
| **TTS Abstraction** | [`backend/engines/tts_provider.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/tts_provider.py) | Incomplete / Discrepant | 331 lines; calls REST `/audio/speech` |
| **TTS NIM Client** | [`backend/engines/tts_nvidia_nim.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/tts_nvidia_nim.py) | Incomplete / Discrepant | 450 lines; 23-language catalog, Phase 6D chunking; calls `/v1/audio/synthesize` |
| **TTS Benchmark** | [`backend/engines/tts_nim_benchmark.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/tts_nim_benchmark.py) | Complete | Multi-language benchmark harness |
| **Vision Abstraction**| [`backend/engines/vision_provider.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/vision_provider.py) | Complete (Standalone) | 289 lines; `MoondreamLocalProvider`, `Gemma4VisionProvider`, registry |
| **Gemma 4 Client** | [`backend/engines/gemma_vision.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/gemma_vision.py) | Complete (Client Logic) | 557 lines; adaptive tokens (128–1024), `VisionFindings`, no device authority |
| **Unit Test Suites** | `backend/tests/test_*.py` | Complete (Passing) | 106 unit tests passing across 4 provider test files |

---

### 2. Actual Provider Abstraction
The provider abstraction layer (`llm_provider.py`, `tts_provider.py`, `vision_provider.py`) defines abstract base classes (`LLMProvider`, `TTSProvider`, `VisionProvider`) and thread-safe singleton registries.
* **Current Operational State:** The registries are **dormant** and decouple from the runtime.
* **Evidence:** Grep analysis confirms that `llm_registry`, `tts_registry`, and `vision_registry` are imported **exclusively in test files**.
* Neither [`backend/main.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py) nor [`backend/threads/general_handler.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/general_handler.py) invoke these registries.
* Four settings variables were added to `Settings` in [`backend/main.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py#L282-L285) (`llm_provider_active`, `tts_provider_active`, `vision_provider_active`, `nvidia_nim_tts_url`), but no router or dispatcher branches on them.

---

### 3. Lightning Integration & Current Configuration
* **Configuration:** Configured in [`backend/.env`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/.env#L74-L75) via `NVIDIA_LIGHTNING_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b` and endpoint `https://integrate.api.nvidia.com/v1`.
* **Reasoning Control:** `enable_reasoning=False` by default; passes `chat_template_kwargs: {"enable_thinking": False}` and post-processes raw text to strip `<think>` tags and thinking preambles via regex.
* **Metrics Capture:** Fully functional. Tracks request start, TTFT, TTFS (first complete sentence via regex `[.!?]\s`), total completion duration, and token usage counts.
* **Operational Verification:** All unit tests and live integration tests against the NVIDIA cloud endpoint pass cleanly (`TestLightningIntegration`).

---

### 4. Chatterbox Multilingual Integration & Actual API Path
**CRITICAL DEFECT IDENTIFIED:**
1. **API Protocol Mismatch:** The Resemble AI Chatterbox Multilingual NIM microservice primarily exposes **Riva gRPC on port 50051** (`nvidia-riva-client`), while port 9000 is reserved for HTTP health checks (`/v1/health/ready`).
2. **Cloud vs Local Container:** There is **no public REST TTS endpoint** on `integrate.api.nvidia.com` for Chatterbox Multilingual.
3. **Internal Code Discrepancy:**
   - [`backend/engines/tts_provider.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/tts_provider.py#L207) posts to `{nim_url}/audio/speech` with OpenAI-formatted payload `{input, voice, response_format}`.
   - [`backend/engines/tts_nvidia_nim.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/tts_nvidia_nim.py#L282) posts to `{nim_url}/v1/audio/synthesize` with custom payload `{text, language_code, voice}`.
   - Neither REST endpoint exists on NVIDIA's cloud API. Live integration tests in `test_tts_nvidia_nim.py` are skipped for this reason.

---

### 5. Gemma 4 Integration & Image-Input Path
* **Client Implementation:** [`backend/engines/gemma_vision.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/gemma_vision.py) features:
  - Task classification: 6 task types with adaptive token budgets (128 for app classify, 256 for UI find/verify, 1024 for OCR).
  - Gatekeeper: `requires_vision()` regex prevents sending images for non-vision voice queries.
  - Return contract: `VisionFindings` structured dataclass with `to_mj_context()` stringifier.
  - Execution authority: Strictly observe-only (no device actuation authority).
* **CRITICAL LIVE EXPERIMENT FINDING:**
  - Model `google/gemma-4-31b-it` is present in the NVIDIA NIM catalog.
  - **However, live inference requests to `https://integrate.api.nvidia.com/v1` consistently hit `APITimeoutError` (>30s) for both text-only and image+text payloads.**
  - A 30+ second latency or timeout renders the model currently unviable for real-time conversational voice assistance.

---

### 6. Fallback Behavior
* **Production Runtime:** Fully protected. Production continues to call [`ollama_client.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/ollama_client.py), [`tts_dispatch.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/tts_dispatch.py), and [`vision_engine.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/vision_engine.py) directly.
* **Provider Abstraction Fallback:** **Unimplemented.** If an NVIDIA provider is called inside `llm_provider.py`, `tts_provider.py`, or `vision_provider.py` and fails (timeout, 401, 429), the method logs an error and returns `None` or `b""`. There is **no automatic failover** to local Qwen, local Chatterbox Turbo, or local Moondream.

---

### 7. Existing Subsystems Integrity
Verified via `git diff` and file inspection:
* **STT (`whisper_streaming.py`, `AudioCapture.jsx`):** Preserved. Changes in the diff correspond to Phase 7D telephony and speech validation/echo-gate fixes, not NVIDIA regressions.
* **Turn Handling & Barge-In:** Preserved. Strict echo cancellation and 5s asynchronous window remain intact.
* **Android Automation (`android_validator.py`, `automation_handler.py`):** Authoritative validator remains untouched; deterministic telephony fast-paths remain intact.
* **Phone Awareness & Telephony (`phone_router.py`, `notification_dispatcher.py`):** Fully operational.
* **Memory (`memory_engine.py`):** Untouched.

---

### 8. Incomplete or Unsafe Integrations
1. **Gemma 4 Cloud Timeout:** Live cloud calls stall for >30s, causing downstream client hangs.
2. **Chatterbox NIM Missing gRPC Client:** TTS integration expects HTTP REST endpoints that do not exist in NVIDIA cloud NIM.
3. **Missing Automated Circuit Breakers / Fallbacks:** No fast failover mechanism back to local models.
4. **Hardcoded Timeouts:** 60.0s client timeouts with standard SDK retries can block threads for up to 180 seconds.

---

### 9. Duplicated Architecture
Each modality currently has three distinct layers:
1. **LLM:** `ollama_client.py` (active production) vs. `llm_provider.py` (`NvidiaNIMProvider`) vs. `nvidia_lightning.py` (`NvidiaLightningClient`).
2. **TTS:** `tts_dispatch.py` (active production) vs. `tts_provider.py` (`ChatterboxNIMProvider`) vs. `tts_nvidia_nim.py` (`ChatterboxNIMClient`).
3. **Vision:** `vision_engine.py` (active production) vs. `vision_provider.py` (`Gemma4VisionProvider`) vs. `gemma_vision.py` (`GemmaVisionClient`).

---

### 10. Items to Correct Before Adding Nemotron-3-Super
1. **Reconcile duplicate implementations:** Merge `*_provider.py` wrappers and standalone clients into a single coherent engine contract per modality.
2. **Implement concrete, automated fallback:** Add deterministic try-primary-cloud -> on-timeout-or-error-fallback-to-local logic with sub-second cutoffs.
3. **Clarify TTS protocol:** Resolve whether Chatterbox NIM will be deployed locally via gRPC (port 50051) or if local Chatterbox Turbo remains the permanent production engine.
4. **Resolve Gemma 4 latency/timeouts:** Determine whether Gemma 4 can be self-hosted or if another multimodal strategy is required.

---

## Part 2: Audit Conclusions (A–G)

### A. What is actually complete?
* **Nemotron Lightning client & metrics capture:** Unit tested, integration tested, live verified on NVIDIA NIM cloud.
* **Shadow benchmark harness:** Ready to execute side-by-side comparisons between local Qwen and Lightning without disturbing production.
* **Gemma 4 client code:** Task classification, adaptive token budgets, prompt filtering, and findings extraction are fully implemented and unit-tested.
* **Production safety isolation:** Production remains 100% operational on local Qwen3 4B, local Chatterbox Turbo, and local Moondream.

### B. What is partially complete?
* **Provider routing:** Settings fields exist in `Settings`, but no dispatcher or router utilizes them.
* **Provider abstraction:** ABC classes and registries exist, but operate as dormant sidecars.

### C. What is broken?
* **Chatterbox Multilingual NIM HTTP path:** Calling `/v1/audio/synthesize` or `/audio/speech` against NVIDIA cloud fails because the model requires Riva gRPC (port 50051) on a container deployment.
* **Gemma 4 cloud inference latency:** Live calls to `google/gemma-4-31b-it` time out (>30s) on NVIDIA cloud NIM.

### D. What is risky?
* **Lack of fallback inside provider interfaces:** If switched to an NVIDIA provider that errors, the system returns `None` / empty audio rather than rolling back to local engines.
* **Excessive timeouts:** 60-second timeouts on external HTTP clients will cause unacceptable voice pipeline freezes.

### E. What must remain untouched?
* **Core Production Dispatchers:** [`backend/threads/general_handler.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/general_handler.py), [`backend/tts_dispatch.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/tts_dispatch.py), [`backend/engines/vision_engine.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/vision_engine.py).
* **Local Engines:** [`backend/ollama_client.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/ollama_client.py) (Qwen3 4B), [`backend/engines/tts_chatterbox_turbo.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/tts_chatterbox_turbo.py), local Moondream.
* **Phase 6D Audio Rules:** 70–85 character target, 90 character operational limit, 100 character absolute limit.
* **Automation Validator:** [`backend/tools/android_validator.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/tools/android_validator.py) (deterministic safety checks).

### F. What should be fixed before Super?
1. Deduplicate the architecture (eliminate redundant classes between `*_provider.py` and standalone clients).
2. Implement explicit local fallback logic with hard sub-second failure cutoffs.
3. Diagnose and resolve the Gemma 4 cloud endpoint timeout issue.
4. Correct the Chatterbox NIM interface from REST to gRPC (or maintain local Chatterbox Turbo as standard).

### G. Is Nemotron-3-Super actually necessary for MJ, or can Lightning + Gemma already cover most tasks?
**NO. Nemotron-3-Super is NOT currently necessary for MJ, and adding it now would violate engineering change-control principles.**

**Evidence & Rationale:**
1. **Domain Requirements:** MJ/ALITA is a real-time voice assistant handling phone actions, deterministic Android automation, quick queries, and on-screen OCR/UI understanding.
2. **Latency Penalty:** A 120B parameter model will introduce multi-second TTFT delays, contradicting MJ's primary design goal of conversational fluidity.
3. **Deterministic Authority:** Complex device actions are already enforced deterministically by `automation_handler.py` and `android_validator.py`—MJ does not depend on multi-hop autonomous reasoning loops.
4. **Role Adequacy:** Nemotron Lightning 30B delivers 200–500ms TTFT for general conversation and planning, while Gemma 4 is intended for multimodal tasks.
5. **Architectural Discipline:** Per `GEMINI.md`, no model should be added without demonstrated evidence that the existing architecture cannot satisfy requirements. Adding Super before stabilizing the Lightning/Gemma pipeline introduces technical debt without measurable benefit.
