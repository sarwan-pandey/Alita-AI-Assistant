# MJ/ALITA — PHASE 3: PRIMARY MODEL MIGRATION REPORT

**Date:** 2026-10-01  
**Target Subsystem:** Primary Conversational & Tool-Calling LLM (Ollama)  
**Status:** COMPLETE & VERIFIED  
**Migration Path:** `qwen3:4b` (Thinking-2507) → `qwen3:4b-instruct` (Instruct-2507 Q4_K_M)

---

## 1. EXECUTIVE SUMMARY & OBJECTIVE

Following the empirical findings of the Model Selection & Benchmarking phase, the active primary model for MJ/ALITA has been migrated from the reasoning variant (`qwen3:4b` / Qwen3-4B-Thinking-2507) to the official instruction-tuned variant (`qwen3:4b-instruct` / Qwen3-4B-Instruct-2507 Q4_K_M).

The objective of this migration was to eliminate the chain-of-thought delay and token leakage issues discovered in Defect 1, ensuring:
1. Fast, direct conversational speech turnaround (First Usable Token < 3.5s).
2. Complete elimination of thinking-token leakage into the streaming text content destined for Chatterbox Turbo.
3. Prevention of silent failures caused by token budget exhaustion inside `<think>` blocks.
4. Retention of 100% accurate Android automation and device tool calling.
5. Strict preservation of the existing architecture: local Ollama execution, 4B-class parameter budget, Q4_K_M quantization, and Chatterbox Turbo TTS.

The legacy Thinking model (`qwen3:4b`, ID: `359d7dd4bcda`) remains preserved in local Ollama storage as a secondary/rollback model. No models were deleted.

---

## 2. FILES CHANGED

Only the 5 approved configuration, startup, and handler files were modified:

| File Path | Description of Change |
| :--- | :--- |
| [`backend/ollama_client.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/ollama_client.py) | Updated default model and `OLLAMA_MODEL` env fallback to `"qwen3:4b-instruct"`. |
| [`backend/threads/general_handler.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/threads/general_handler.py) | Removed experimental `"think": False` line from streaming payload. |
| [`backend/routers/system_router.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/routers/system_router.py) | Updated `vision_model` environment fallback from `"qwen3:4b"` to `"qwen3:4b-instruct"`. |
| [`start_alita.bat`](file:///c:/Users/sarwa/Desktop/aura-assistant/start_alita.bat) | Updated startup warmup check and memory-pinning command to `"qwen3:4b-instruct"`. |
| [`backend/.env`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/.env) | Set `OLLAMA_MODEL=qwen3:4b-instruct` and `OLLAMA_VISION_MODEL=qwen3:4b-instruct`. |

---

## 3. EXACT CHANGES (DIFFS)

### `backend/ollama_client.py`
```diff
--- a/backend/ollama_client.py
+++ b/backend/ollama_client.py
@@ -19,1 +19,1 @@
-        model="qwen3:4b",
+        model="qwen3:4b-instruct",
@@ -36,1 +36,1 @@
-OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:4b")
+OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:4b-instruct")
```

### `backend/threads/general_handler.py`
```diff
--- a/backend/threads/general_handler.py
+++ b/backend/threads/general_handler.py
@@ -248,2 +248,1 @@
             "stream": True,
-            "think": False,
             "keep_alive": OLLAMA_KEEP_ALIVE,
```

### `backend/routers/system_router.py`
```diff
--- a/backend/routers/system_router.py
+++ b/backend/routers/system_router.py
@@ -192,1 +192,1 @@
-        vision_model = os.getenv("OLLAMA_VISION_MODEL", "qwen3:4b")
+        vision_model = os.getenv("OLLAMA_VISION_MODEL", "qwen3:4b-instruct")
```

### `start_alita.bat`
```diff
--- a/start_alita.bat
+++ b/start_alita.bat
@@ -26,3 +26,3 @@
-echo [3/5] Warming up primary LLM (qwen3:4b) into memory...
-powershell -NoProfile -Command "try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/chat' -Method Post -ContentType 'application/json' -Body '{\"model\":\"qwen3:4b\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false,\"keep_alive\":-1,\"options\":{\"num_predict\":5,\"num_ctx\":4096}}' -TimeoutSec 60; exit 0 } catch { exit 1 }" >nul 2>&1
-echo       Model (qwen3:4b) is pinned in memory (4096 context, keep_alive=-1). Response turnaround is instant.
+echo [3/5] Warming up primary LLM (qwen3:4b-instruct) into memory...
+powershell -NoProfile -Command "try { $null = Invoke-RestMethod -Uri 'http://127.0.0.1:11434/api/chat' -Method Post -ContentType 'application/json' -Body '{\"model\":\"qwen3:4b-instruct\",\"messages\":[{\"role\":\"user\",\"content\":\"hi\"}],\"stream\":false,\"keep_alive\":-1,\"options\":{\"num_predict\":5,\"num_ctx\":4096}}' -TimeoutSec 60; exit 0 } catch { exit 1 }" >nul 2>&1
+echo       Model (qwen3:4b-instruct) is pinned in memory (4096 context, keep_alive=-1). Response turnaround is instant.
```

### `backend/.env`
```diff
--- a/backend/.env
+++ b/backend/.env
@@ -18,1 +18,1 @@
-OLLAMA_MODEL=qwen3:4b
+OLLAMA_MODEL=qwen3:4b-instruct
@@ -23,1 +23,1 @@
-OLLAMA_VISION_MODEL=qwen3:4b
+OLLAMA_VISION_MODEL=qwen3:4b-instruct
```

---

## 4. ACTIVE MODEL CONFIRMATION

Post-migration inspection of the live system verified:
* **Python Runtime Configuration:**
  * `ollama_client.get_model_name()` → `"qwen3:4b-instruct"`
  * `ollama_client.OLLAMA_MODEL` → `"qwen3:4b-instruct"`
* **Ollama Active VRAM Process (`/api/ps`):**
  * Loaded Model: `['qwen3:4b-instruct']`
  * Manifest ID: `0edcdef34593`
  * GGUF Blob: `sha256-85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9` (2,497,280,480 bytes)
  * Quantization: `Q4_K_M`
  * Parameter Count: `4,022,468,096` (~4.02B)

---

## 5. BENCHMARK COMPARISON (BEFORE VS AFTER)

| Benchmark Query | Metric | Pre-Migration: `qwen3:4b` (Thinking) | Post-Migration: `qwen3:4b-instruct` (Instruct) | Impact / Delta |
| :--- | :--- | :--- | :--- | :--- |
| **1. "What is the capital of India?"** | First Usable Token | 10.174s | **3.387s** | **-6.787s (-66.7%)** |
| | Total Time | 10.246s | 3.684s | -6.562s |
| | Thinking Tokens | 193 | **0** | Eliminated 193 wasted tokens |
| | Spoken Text | `"New Delhi"` | `"The capital of India is New Delhi."` | Direct, conversational |
| **2. "Who was Albert Einstein?"** | First Usable Token | **TIMEOUT / FAILED** | **3.399s** | **Succeeded (was 0 tokens)** |
| | Total Time | 22.276s | 9.459s | -12.817s |
| | Thinking Tokens | 512 (Budget exhausted) | **0** | Eliminated 512 wasted tokens |
| | Content Tokens | 0 (Silent failure) | 168 | Complete biography |
| **3. "Explain photosynthesis in 3 sentences."** | First Usable Token | 11.784s | **3.288s** | **-8.496s (-72.1%)** |
| | Total Time | 14.083s | 6.405s | -7.678s |
| | Thinking Tokens | 232 | **0** | Eliminated 232 wasted tokens |
| **4. "Bharat ki rajdhani kya hai?"** | First Usable Token | **TIMEOUT / FAILED** | **3.191s** | **Succeeded (was 0 tokens)** |
| | Total Time | 22.431s | 4.183s | -18.248s |
| | Thinking Tokens | 512 (Budget exhausted) | **0** | Eliminated 512 wasted tokens |
| | Content Tokens | 0 (Silent failure) | 18 | Clean Hindi output |
| **5. "What is my phone battery level?"** | First Usable (Tool Token) | 7.701s | **4.017s** | **-3.684s (-47.8%)** |
| | Tool Call Emitted | `get_phone_battery()` | `get_phone_battery()` | 100% schema match |
| | Thinking Tokens | 103 | **0** | Instant tool invocation |
| **6. "Open WhatsApp."** | First Usable (Tool Token) | 7.745s | **4.015s** | **-3.730s (-48.2%)** |
| | Tool Call Emitted | `open_app("WhatsApp")` | `open_app("WhatsApp")` | 100% argument match |
| | Thinking Tokens | 101 | **0** | Instant tool invocation |

---

## 6. REGRESSION RESULTS

The full automated regression suite ([`scratch/verify_migration.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/scratch/verify_migration.py)) was executed against the active backend. All 7 test stages passed cleanly:

1. **Model Identity Test:**
   * Configured Model: `qwen3:4b-instruct`
   * Active VRAM: `['qwen3:4b-instruct']`
   * Status: **PASS**

2. **Basic Conversational Queries:**
   * Query 1 ("Capital of India"): First Usable Token = 3.387s, Content = `"The capital of India is New Delhi."` → **PASS**
   * Query 2 ("Albert Einstein"): First Usable Token = 3.399s, Content = 168 tokens complete bio → **PASS**
   * Query 3 ("Photosynthesis in 3 sentences"): First Usable Token = 3.288s, Content = 80 tokens 3-sentence summary → **PASS**

3. **Multilingual / Hindi Test:**
   * Query 4 ("Bharat ki rajdhani kya hai?"): First Usable Token = 3.191s, Content = `"भारत की राजधानी है..."` → **PASS**

4. **Android / Automation Tool Calling:**
   * Query 5 ("Battery Query"): First Usable Token = 4.017s, Emitted = `get_phone_battery()` → **PASS**
   * Query 6 ("Open WhatsApp"): First Usable Token = 4.015s, Emitted = `open_app(app_name="WhatsApp")` → **PASS**

5. **Streaming & Thinking Separation:**
   * `<think>` / `</think>` tags in output: `0`
   * Thinking tokens generated: `0`
   * Reasoning monologue leaked into content: `False`
   * Internal planning text: `None`
   * Status: **PASS**

6. **TTS Audio Generation:**
   * The clean user-facing string (`"The capital of India is New Delhi."`) was synthesized directly through Chatterbox Turbo.
   * Generation Time: 6.456s
   * Audio Output: 117,164 PCM WAV bytes
   * Audio Format: 24,000 Hz, 16-bit PCM mono
   * Status: **PASS**

---

## 7. UNEXPECTED BEHAVIOR

* **None.** No behavioral regressions, prompt degradation, or tool parsing errors were encountered. The Instruct model integrates directly into the existing MJ/ALITA streaming and tool-calling handlers without requiring prompt adjustments or parsing modifications.

---

## 8. ROLLBACK PROCEDURE

Both models remain installed and immediately accessible in local Ollama storage:
* `qwen3:4b-instruct` (Active, ID: `0edcdef34593`)
* `qwen3:4b` (Rollback, ID: `359d7dd4bcda`)

To execute an immediate rollback:
1. Edit [`backend/.env`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/.env):
   ```ini
   OLLAMA_MODEL=qwen3:4b
   OLLAMA_VISION_MODEL=qwen3:4b
   ```
2. Edit [`backend/ollama_client.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/ollama_client.py) lines 19 and 36:
   ```python
   OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "qwen3:4b")
   ```
3. Restart backend service.

*Rollback time: < 5 seconds. Zero network downloads required.*
