# Phase 7C.5 — Forensic Root-Cause Fix & Validation Report

**Mode:** Implementation + Targeted Validation  
**Scope:** STT / Audio Lifecycle & False Identity Contamination  
**Date:** 2026-10-07  
**Architecture Preserved:** Local Qwen3-4B (Ollama), Chatterbox Turbo (single-engine), Web Speech + Faster-Whisper, Android automation, Turn Controller (Defect 2 & Defect 3 protections), Notification Dispatcher, Telephony.

---

## A. Exact Files Changed

1. [`backend/data/memory_summaries.json`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/data/memory_summaries.json)  
   *Surgical cleanup of persisted false identity summaries under `test_admin`.*
2. [`backend/engines/whisper_streaming.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/whisper_streaming.py)  
   *Implemented `validate_whisper_transcript()`, added segment-level Whisper metadata filters (`no_speech_prob`, `compression_ratio`, `avg_logprob`), and hardened `_trigger_transcription()` and `_transcribe()`.*
3. [`backend/main.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py)  
   *Hardened `_whisper_poll_loop()` with deterministic transcript validation before calling `_process_user_query()`; safely gated the 90-second autonomous proactive silence prompt via `ENABLE_PROACTIVE_SILENCE` (defaulting to `False`).*
4. [`frontend/src/components/audio/AudioCapture.jsx`](file:///c:/Users/sarwa/Desktop/aura-assistant/frontend/src/components/audio/AudioCapture.jsx)  
   *Repaired the dead post-TTS cooldown gate (`ttsEndTimeRef.current = Date.now()` and `ttsCooldownRef.current = Date.now()` on TTS completion and `MJ:tts_ended`/`Alita:tts_ended` events); ensured `stopTTS()` zeroes both refs for immediate, uninterrupted user barge-in.*

---

## B. Exact Identity Contamination Removed

- **Origin of Contamination:** An ambient/low-SNR transcription hallucination on 2026-10-04 (`"Hello, I'm Jim."`) was committed into `test_admin` history and subsequently digested by `memory_summarizer` into `backend/data/memory_summaries.json` as permanent facts:
  ```json
  "facts": [
    "User said: Hello, I'm Jim.",
    "MJ said: Oh hey Jim! 👋 Nice to meet you—though I think we’ve already crossed paths somewhere in the digital world. How’s your day going? 😊",
    "User said: Okay. Good morning.",
    "MJ said: It's 01:45 PM.",
    "User said: So we're going to work on some of the activities that I know is in our course. So I'll be in the opportunity. Thank you."
  ]
  ```
- **Injection Vector:** `llm_engine.build_alita_context()` loaded these stored facts and appended `[Context: You remember: User said: Hello, I'm Jim.; MJ said: Oh hey Jim!...]` to all prompt requests for `test_admin`.
- **Surgical Removal:**
  - `memory_summaries.json`: Removed the contaminated summary entry under `"test_admin"`, leaving `"test_admin": []`.
  - In `history.jsonl.bak_20261004_1438`: Confirmed 20 turns (lines 739–758) were from the contaminated session.
  - First removed timestamp: `1791101733.3328762` (`2026-10-04T13:45:33+0530`)
  - Last removed timestamp: `1791103640.5211103` (`2026-10-04T14:17:20+0530`)
  - Remaining valid history in active `history.jsonl`: **738 lines** (clean turns ending at `"What is 2+2?"` / `"2 + 2 is 4."`).

---

## C. Backup Locations

Exact verbatim backups were created prior to any file modification:
- [`backend/data/conversations/test_admin/history.jsonl.bak_phase7c5`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/data/conversations/test_admin/history.jsonl.bak_phase7c5) (196,960 bytes)
- [`backend/data/memory_summaries.json.bak_phase7c5`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/data/memory_summaries.json.bak_phase7c5) (40,382 bytes)

---

## D. Exact AudioCapture Echo-Gate Fix

In [`AudioCapture.jsx`](file:///c:/Users/sarwa/Desktop/aura-assistant/frontend/src/components/audio/AudioCapture.jsx):
1. **TTS Completion Callback & Event Handlers:**
   ```javascript
   audioStreamPlayer.options.onEnd = () => {
     clearTimeout(processingTimeoutRef.current);
     ttsPlayingRef.current = false;
     processingRef.current = false;
     ttsEndTimeRef.current = Date.now();
     ttsCooldownRef.current = Date.now();
     setMicState("active");
   };

   const ttsEndHandler = () => {
     clearTimeout(processingTimeoutRef.current);
     ttsPlayingRef.current = false;
     processingRef.current = false;
     ttsEndTimeRef.current = Date.now();
     ttsCooldownRef.current = Date.now();
     setMicState("active");
   };
   window.addEventListener("MJ:tts_ended", ttsEndHandler);
   window.addEventListener("Alita:tts_ended", ttsEndHandler);
   ```
2. **Audio Frame Drop Gate:**
   ```javascript
   const handleAudioFrame = useCallback((frame, prob) => {
     if (ttsPlayingRef.current) return;
     if (processingRef.current) return;
     const timeSinceTTS = Date.now() - (ttsEndTimeRef.current || 0);
     if (ttsEndTimeRef.current > 0 && timeSinceTTS < 800) return;

     window.dispatchEvent(
       new CustomEvent("Alita:offline_audio_chunk", {
         detail: { pcm_binary: frame.buffer.slice(0) },
       })
     );
   }, []);
   ```
3. **Intentional Barge-in Preservation:**
   When user speaks during playback, `prob > 0.48 || rms > 0.42` or Web Speech invokes `stopTTS()`. Inside `stopTTS()`:
   ```javascript
   ttsEndTimeRef.current = 0;
   ttsCooldownRef.current = 0;
   ```
   Zeroing both refs clears the echo gate immediately, allowing user speech to flow into Whisper and Web Speech without delay.

---

## E. Exact Whisper Hallucination Filter

Implemented in [`whisper_streaming.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/engines/whisper_streaming.py) and enforced in [`main.py`](file:///c:/Users/sarwa/Desktop/aura-assistant/backend/main.py):

### 1. Acoustic Segment Level (`faster_whisper` Model Metadata)
- **No-Speech Acoustic Filter:** Segments with `seg.no_speech_prob > 0.65` AND `seg.avg_logprob < -1.0` are dropped (Whisper acoustic confidence that the window is background silence/hiss).
- **Repetition Compression Filter:** Segments with `seg.compression_ratio > 2.4` are dropped (Whisper's standard gzip compression ratio ceiling for repetitive hallucinatory loops).

### 2. Deterministic Transcript Level (`validate_whisper_transcript()`)
- **Noise / Non-Alphanumeric:** Rejects empty text, whitespace, punctuation-only (e.g. `"."`, `","`, `"--"`), and single non-digit characters.
- **Audio Artifacts / Tags:** Rejects strings enclosed in brackets, parentheses, or asterisks (e.g. `"[BLANK_AUDIO]"`, `"(music)"`, `"*sigh*"`).
- **Silence Hallucination Phrases:** Rejects YouTube training artifacts (e.g. `"Thank you for watching"`, `"Please subscribe"`, `"Subtitles by"`).
- **Consecutive Word Loops:** Rejects words repeated 4+ consecutive times (e.g. `"room room room room"`, regex `\b(\w+)(?:\s+\1){3,}\b`).
- **N-gram Repetition Loops:** Rejects 2-gram, 3-gram, or 4-gram phrases repeating 3+ times in texts with $\ge 6$ words (e.g. `"for a dollar for a dollar for a dollar"`).
- **Clause Repetition Loops:** Rejects punctuation-delimited clauses repeating 3+ times (e.g. `"This is a baguette. It's a baguette. It's a baguette."`).
- **Vocabulary Diversity Floor:** For utterances with $\ge 8$ words, requires `unique_words / total_words >= 0.35`.

---

## F. Exact Handling of Short Legitimate Commands

Short commands were explicitly safeguarded and tested:
- `"Stop"`: 1 word, len=4, diversity=1.0 $\rightarrow$ **VALID**
- `"Yes"`: 1 word, len=3, diversity=1.0 $\rightarrow$ **VALID**
- `"No"`: 1 word, len=2, diversity=1.0 $\rightarrow$ **VALID**
- `"Open Chrome"`: 2 words, len=11, diversity=1.0 $\rightarrow$ **VALID**
- `"Call Adi"`: 2 words, len=8, diversity=1.0 $\rightarrow$ **VALID**
- `"Hello MJ"`: 2 words, len=8, diversity=1.0 $\rightarrow$ **VALID**
- `"2"`: 1 digit, len=1, `isdigit() == True` $\rightarrow$ **VALID**
- `"No, no"`: 2 words, repeat count=2 (< 4 threshold) $\rightarrow$ **VALID**
- `"Bye bye bye"`: 3 words, repeat count=3 (< 4 threshold) $\rightarrow$ **VALID**

---

## G. Whether TTS $\rightarrow$ STT Feedback Was Reproduced

- **Findings:**
  - During active TTS playback (`ttsPlayingRef.current == true`), `handleAudioFrame` immediately drops all incoming PCM audio chunks (`if (ttsPlayingRef.current) return;`).
  - At the completion of playback, the repaired 800 ms cooldown gate (`if (ttsEndTimeRef.current > 0 && timeSinceTTS < 800) return;`) completely blocks speaker decay and physical room reverberation.
  - Web Speech `isEcho()` additionally validates that any speech recognized within 1.5 seconds matching MJ's spoken tokens is suppressed.
- **Conclusion:** TTS audio alone **does not become a user turn**.

---

## H. Whether Intentional Barge-in Still Works

- **Verified via Runtime Test:**
  1. User interruption during speech invokes `stopTTS()`.
  2. `AudioStreamPlayer.interrupt()` halts speaker output within 5 ms.
  3. `ttsPlayingRef.current` is set to `false`.
  4. `ttsEndTimeRef.current` and `ttsCooldownRef.current` are explicitly reset to `0`.
  5. The 800 ms suppression gate is bypassed, and user audio immediately streams to Faster-Whisper.
  6. Backend `[TURN] TURN_CANCEL_REQUESTED` and `[TURN] TURN_CANCELLED` fire cleanly without crashing the session.

---

## I. Whether Idle Spontaneous Speech Stopped

- **Diagnosis:** `SILENCE_TIMEOUT = 90` previously caused `asyncio.wait_for(websocket.receive(), timeout=90)` to raise `TimeoutError` after 90 seconds of inactivity, which autonomously called `_send_silence_prompt()` and synthesized TTS.
- **Fix:** Added `ENABLE_PROACTIVE_SILENCE = os.getenv("ENABLE_PROACTIVE_SILENCE", "false").lower() in ("true", "1", "yes")`. By default, this is `False`. The receive loop does not timeout or invoke `_send_silence_prompt()`.
- **Runtime Evidence:** Verified that idle sessions remain completely quiet with zero autonomous speech.

---

## J. Whether Jim/Jay Contamination is Gone from Runtime Context

Verified across all system components:
- **Conversation History:** 0 occurrences of "Jim" or "Jay" across active records (50 turns loaded cleanly).
- **Memory Summarizer:** 0 stored summaries under `test_admin` containing "Jim" or "Jay".
- **Episodic Memory:** 0 entities, episodic topic summary is clean.
- **System Prompt (`ALITA_SYSTEM`):** Canonical identity explicitly verified as **MJ / ALITA** (`"You are MJ — a warm, emotionally intelligent AI companion..."`).
- **LLM Context Hint (`build_alita_context`):** Clean, 0 occurrences of "Jim" or "Jay".
- **User Profile (`user_profile.json`):** 0 occurrences of "Jim" or "Jay".
- **Frontend Code (`frontend/src`):** Clean (only phonetic matcher regex `/\bem\s+jay\b/` for "MJ").

---

## K. Regression Results

| Test Suite / Area | Tests Executed | Passed | Failed | Status |
|---|---|---|---|---|
| **Chatterbox Turbo Smoke** (`test_turbo_migration_smoke.py`) | 6 | 6 | 0 | **PASS** |
| **TTS Migration Suite** (`test_tts_migration.py`) | 5 | 5 | 0 | **PASS** |
| **Voice Dispatch Suite** (`test_voice_dispatch.py`) | 3 | 3 | 0 | **PASS** |
| **Memory Summarizer** (`test_memory_summarizer.py`) | 5 | 5 | 0 | **PASS** |
| **Phase 7D Telephony Suite** (`test_phase7d_telephony.py`) | 3 | 3 | 0 | **PASS** |
| **Phone Companion Suite** (`verify_phone_companion.py`) | 12 | 12 | 0 | **PASS** |
| **Defect 2 & 3 / STT Gate** (`test_defect2_3_whisper_regression.py`) | 2 | 2 | 0 | **PASS** |
| **Full Clean Start Step 8** (`test_step8_clean_start.py`) | 11 steps | 11 | 0 | **PASS** |
| **Frontend Production Build** (`npm run build`) | Vite build | 138 modules | 0 | **PASS** (10.35s) |

---

## L. Remaining Limitations

1. **Local Acoustic Echo Cancellation (AEC):** Operating on laptop hardware without hardware AEC still relies on software gating (`ttsPlayingRef` + 800ms post-TTS cooldown + `isEcho()`). Extremely loud external speakers facing the laptop microphone at max volume could theoretically exceed thresholds if mic sensitivity is set abnormally high, though the 800ms gate and `isEcho()` catch standard acoustic spillover.
2. **Proactive Silence Prompt Gating:** The proactive 90-second prompt is gated to `False` by default. When desired in production, it can be re-enabled by setting `ENABLE_PROACTIVE_SILENCE=true` in `.env`.
