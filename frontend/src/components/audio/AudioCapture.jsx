/**
 * AudioCapture — Natural voice conversation with automatic barge-in.
 *
 * KEY DESIGN: The mic NEVER stops listening. Even while Alita is speaking,
 * the Web Speech API runs. If the user starts talking, Alita stops
 * immediately — just like a real conversation. No buttons needed.
 *
 * Echo rejection: We track what Alita just said and ignore any speech
 * that matches it (prevents the mic from picking up TTS audio).
 *
 * Flow:
 *   1. Component mounts → starts Web Speech API (always-on)
 *   2. User speaks → sends text to backend
 *   3. Alita responds → TTS plays, but mic stays active
 *   4. User speaks during TTS → TTS stops, new speech processed
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { useSileroVAD } from "../../hooks/useSileroVAD";

const SAMPLE_RATE = 16000;

// ── Wake Word Normalizer ─────────────────────────────────────────────────────
// STT frequently mishears "Alita" as variations below.
// Only exact known mishearings — no aggressive multi-word patterns.
const ALITA_MISHEARINGS = [
  /\baletta\b/gi,
  /\baleeta\b/gi,
  /\baleta\b/gi,
  /\barita\b/gi,
  /\belita\b/gi,
  /\balitha\b/gi,
  /\balida\b/gi,
  /\baletha\b/gi,
  /\balyda\b/gi,
  /\balitah\b/gi,
  /\beleta\b/gi,
  /\balitta\b/gi,
];

function normalizeWakeWord(text) {
  let result = text;
  for (const pattern of ALITA_MISHEARINGS) {
    result = result.replace(pattern, "Alita");
  }
  // Compound mishearings (only with greeting prefix to avoid false positives)
  result = result.replace(/\b(hello|hey|hi)\s+later\b/gi, "$1 Alita");
  result = result.replace(/\b(hello|hey|hi)\s+a\s+lita\b/gi, "$1 Alita");
  return result;
}

export function AudioCapture({
  onAudioChunk,
  onSpeechStart,
  onUtteranceCommitted,
  onTranscript,
  enabled,
  sttLanguage = "en-IN",
  dictationMode,
  sendDictation,
  onDictationStop,
  onMusicDetected,
  onVoiceActivity,
  sendBargeIn,
  sendSpeculativeQuery,
  cancelSpeculative,
}) {
  const [micState, setMicState] = useState("connecting");
  const recognitionRef = useRef(null);
  const ttsPlayingRef = useRef(false);
  const ttsQueueRef = useRef([]);
  const ttsAudioCtxRef = useRef(null);
  const ttsSourceRef = useRef(null);
  const isSpeaking = useRef(false);
  const restartTimeoutRef = useRef(null);
  const lastAlitaTextRef = useRef(""); // what Alita just said (for echo rejection)
  const processingRef = useRef(false); // prevents double-sends while backend is processing
  const lastSentTextRef = useRef(""); // last text sent to backend (anti-repeat)
  const lastSentTimeRef = useRef(0); // timestamp of last sent text
  const ttsCooldownRef = useRef(0); // timestamp when TTS finished (cooldown period)
  const networkRetryCountRef = useRef(0); // STT network error retry counter
  const networkRetryTimerRef = useRef(null); // STT network error retry timer
  const recognitionIdRef = useRef(0); // Increments each time a new SpeechRecognition is created
  // — stale instances check this to avoid restart loops
  const ttsEndTimeRef = useRef(0); // timestamp when TTS finished (for echo gate)
  const appliedLanguageRef = useRef((sttLanguage || "en-IN").toLowerCase());

  // ── Barge-in context tracking ─────────────────────────────────────────
  const accumulatedResponseRef = useRef(""); // Alita's full response text so far
  const lastUserQueryRef = useRef(""); // the user's query that triggered current response
  const sendBargeInRef = useRef(sendBargeIn);

  // ── Music detection refs ───────────────────────────────────────────────
  const musicVolumeStart = useRef(0); // timestamp when sustained volume started
  const lastSpeechTime = useRef(Date.now()); // timestamp of last STT result
  const musicDetectedRef = useRef(false);
  const musicCheckIntervalRef = useRef(null);
  const songRecordingRef = useRef(false); // true when recording for song recognition

  // ── Speculative response refs ─────────────────────────────────────────
  const lastSpecTextRef = useRef(""); // last interim text we sent as speculative
  const specDebounceRef = useRef(null); // debounce timer
  const sendSpecRef = useRef(sendSpeculativeQuery);
  const cancelSpecRef = useRef(cancelSpeculative);

  // ── Emergency recording refs ──────────────────────────────────────────
  const emergencyRecordingRef = useRef(false);
  const emergencyRecorderRef = useRef(null);
  const emergencyStreamRef = useRef(null);
  const [emergencyActive, setEmergencyActive] = useState(false);
  const [emergencySound, setEmergencySound] = useState("");

  // ── Environment sounds ────────────────────────────────────────────────
  const [environmentSounds, setEnvironmentSounds] = useState([]);

  // ── Stable refs for callback props (prevents startWebSpeech from being recreated) ──
  const onSpeechStartRef = useRef(onSpeechStart);
  const onTranscriptRef = useRef(onTranscript);
  const onUtteranceCommittedRef = useRef(onUtteranceCommitted);
  const sendDictationRef = useRef(sendDictation);
  const onDictationStopRef = useRef(onDictationStop);
  const dictationModeRef = useRef(dictationMode);
  const sttLanguageRef = useRef(sttLanguage);
  const enabledRef = useRef(enabled);

  useEffect(() => {
    onSpeechStartRef.current = onSpeechStart;
    onTranscriptRef.current = onTranscript;
    onUtteranceCommittedRef.current = onUtteranceCommitted;
    sendDictationRef.current = sendDictation;
    onDictationStopRef.current = onDictationStop;
    dictationModeRef.current = dictationMode;
    sttLanguageRef.current = sttLanguage;
    enabledRef.current = enabled;
    sendBargeInRef.current = sendBargeIn;
    sendSpecRef.current = sendSpeculativeQuery;
    cancelSpecRef.current = cancelSpeculative;
  });

  const { speechProbRef, isFallbackRmsRef, getMicVolume } = useSileroVAD({
    enabled,
  });

  useEffect(() => {
    if (!enabled) {
      onVoiceActivity?.(0);
      return;
    }

    const timer = setInterval(() => {
      const prob = Math.max(0, Math.min(1, speechProbRef.current || 0));
      const rms = Math.max(0, Math.min(1, getMicVolume() * 8));
      const activity = Math.max(prob, rms * 0.7);
      onVoiceActivity?.(activity);
    }, 90);

    return () => {
      clearInterval(timer);
      onVoiceActivity?.(0);
    };
  }, [enabled, getMicVolume, onVoiceActivity, speechProbRef]);

  // ── Stop TTS immediately (barge-in) ──────────────────────────────────────
  const stopTTS = useCallback(() => {
    if (!ttsPlayingRef.current && ttsQueueRef.current.length === 0) return;

    // ── Send barge-in context to backend ────────────────────────────────
    const partialResponse = accumulatedResponseRef.current || "";
    const originalQuery = lastUserQueryRef.current || "";
    if (partialResponse || originalQuery) {
      console.log(
        `[BARGE-IN] Sending context: response=${partialResponse.length} chars, query='${originalQuery.slice(0, 40)}'`
      );
      sendBargeInRef.current?.(partialResponse, originalQuery);
    }

    console.log("[TTS] Barge-in — user is speaking, stopping Alita");
    try {
      ttsSourceRef.current?.stop();
    } catch (_) {}
    ttsSourceRef.current = null;
    ttsQueueRef.current = [];
    ttsPlayingRef.current = false;
    processingRef.current = false; // CRITICAL: allow new speech immediately after barge-in
    setMicState("active");
  }, []);

  // ── TTS Playback (MP3 from Edge TTS) ────────────────────────────────────
  const playNextTTSChunk = useCallback(async () => {
    if (ttsPlayingRef.current || ttsQueueRef.current.length === 0) return;
    ttsPlayingRef.current = true;
    setMicState("speaking");

    // DON'T stop speech recognition — keep mic alive for barge-in!

    const chunk = ttsQueueRef.current.shift();

    try {
      if (!ttsAudioCtxRef.current) {
        ttsAudioCtxRef.current = new AudioContext();
        console.log(
          "[TTS] AudioContext created, state:",
          ttsAudioCtxRef.current.state,
        );
      }
      const ctx = ttsAudioCtxRef.current;

      if (ctx.state === "suspended") {
        await ctx.resume();
      }

      const b64 = chunk.audio_b64;
      if (!b64) {
        ttsPlayingRef.current = false;
        setMicState("active");
        return;
      }

      const binary = atob(b64);
      const bytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

      const audioBuffer = await ctx.decodeAudioData(bytes.buffer.slice(0));

      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(ctx.destination);
      ttsSourceRef.current = source;

      source.onended = () => {
        clearTimeout(ttsTimeout);
        ttsPlayingRef.current = false;
        ttsSourceRef.current = null;
        if (ttsQueueRef.current.length > 0) {
          playNextTTSChunk();
        } else {
          // ── Energy-adaptive echo gate ──────────────────────────────────
          // Sample mic RMS right now (while TTS echo is still in the air).
          // This baseline tells us how loud the bleed is on this specific setup.
          // If it's near-zero → AEC/headphones are handling it → 0ms gate.
          // If elevated → short energy-decay gate kicks in (max 300ms).
          const echoBaseline = getMicVolume();
          ttsEndTimeRef.current = Date.now();
          ttsCooldownRef.current = Date.now(); // keep for barge-in compatibility
          console.log(
            `[TTS] Ended — echo baseline RMS=${echoBaseline.toFixed(4)}`,
          );
          setMicState("active");
          processingRef.current = false; // CRITICAL: always unlock after TTS finishes
          // Release echo text memory quickly so user speech isn't blocked
          setTimeout(() => {
            lastAlitaTextRef.current = "";
            // Clear barge-in response tracking — this response cycle is complete
            accumulatedResponseRef.current = "";
          }, 800);
        }
      };

      const ttsTimeout = setTimeout(() => {
        ttsPlayingRef.current = false;
        ttsSourceRef.current = null;
        setMicState("active");
      }, 30000);

      source.start();
      console.log("[TTS] Playing (%.1fs)", audioBuffer.duration);
    } catch (err) {
      console.error("[TTS] Playback error:", err);
      ttsPlayingRef.current = false;
      ttsSourceRef.current = null;
      setMicState("active");
    }
  }, [getMicVolume]);

  // ── TTS event listener (sentence-level streaming support) ─────────────
  useEffect(() => {
    const handler = (e) => {
      const msg = e.detail;

      // Final TTS marker with empty audio — just signals end of stream
      if (msg.is_final && !msg.audio_b64) {
        return;
      }

      // Sentence-indexed chunks: insert in sorted order so sentences
      // play in sequence even if TTS completes out of order
      if (msg.sentence_idx !== undefined) {
        const q = ttsQueueRef.current;
        // Find insertion point to maintain sentence order
        let insertAt = q.length;
        for (let i = q.length - 1; i >= 0; i--) {
          if (q[i].sentence_idx !== undefined && q[i].sentence_idx > msg.sentence_idx) {
            insertAt = i;
          } else {
            break;
          }
        }
        q.splice(insertAt, 0, msg);
      } else {
        ttsQueueRef.current.push(msg);
      }

      playNextTTSChunk();
    };
    window.addEventListener("Alita:tts_chunk", handler);
    return () => window.removeEventListener("Alita:tts_chunk", handler);
  }, [playNextTTSChunk]);

  // ── Track what Alita says for echo rejection + barge-in context ─────────
  useEffect(() => {
    // Listen for LLM tokens to build echo-rejection text AND barge-in response tracking
    const tokenHandler = (e) => {
      const msg = e.detail;
      if (msg?.type === "llm_token" && msg.token) {
        lastAlitaTextRef.current += msg.token;
        // Keep only last 200 chars for echo matching
        if (lastAlitaTextRef.current.length > 200) {
          lastAlitaTextRef.current = lastAlitaTextRef.current.slice(-200);
        }
        // Accumulate full response for barge-in context
        accumulatedResponseRef.current += msg.token;

        // When the response is final, we can stop accumulating
        if (msg.is_final) {
          // Keep the accumulated response until TTS finishes
          // (it will be cleared when TTS queue empties)
        }
      }
    };
    window.addEventListener("Alita:llm_token", tokenHandler);
    return () => window.removeEventListener("Alita:llm_token", tokenHandler);
  }, []);

  // ── Restart speech recognition helper ───────────────────────────────────
  const _restartRecognition = useCallback(() => {
    if (!enabledRef.current) return;
    clearTimeout(restartTimeoutRef.current);
    restartTimeoutRef.current = setTimeout(() => {
      try {
        recognitionRef.current?.start();
      } catch (e) {
        // Already running — fine
      }
    }, 300);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Echo rejection: is this text just Alita's own voice? ───────────────
  const isEcho = useCallback((transcript) => {
    if (!lastAlitaTextRef.current) return false;

    // Skip echo check if TTS ended more than 2s ago — user is truly speaking
    const msSinceTTS = Date.now() - (ttsEndTimeRef.current || 0);
    if (msSinceTTS > 2000) return false;

    const alitaText = lastAlitaTextRef.current.toLowerCase();
    const userText = transcript.toLowerCase();

    // Check if what the mic heard is a substring of what Alita said
    const words = userText.split(/\s+/);
    if (words.length <= 3) {
      // Short phrases: very strict — 85% of words must match Alita's text
      const matchCount = words.filter((w) => alitaText.includes(w)).length;
      if (matchCount >= words.length * 0.85) {
        return true;
      }
    } else {
      // Longer phrases: 65% overlap required
      const matchCount = words.filter((w) => alitaText.includes(w)).length;
      if (matchCount >= words.length * 0.65) {
        return true;
      }
    }
    return false;
  }, []);

  // ── Web Speech API Setup ────────────────────────────────────────────────
  // NOTE: This callback is intentionally stabilized — it reads props via refs
  // so its identity doesn't change. This prevents the auto-start useEffect
  // from re-firing and creating duplicate recognition instances.
  const startWebSpeech = useCallback(() => {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn("[STT] Web Speech API not supported");
      return false;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = sttLanguageRef.current;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      if (!ttsPlayingRef.current) setMicState("active");
      console.log("[STT] Listening...");
    };

    recognition.onresult = (event) => {
      // Any successful result means the network is back — reset retry counter
      networkRetryCountRef.current = 0;
      clearTimeout(networkRetryTimerRef.current);

      let finalTranscript = "";
      let interimTranscript = "";
      let bestConfidence = 0;

      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (result.isFinal) {
          finalTranscript += result[0].transcript;
          bestConfidence = Math.max(bestConfidence, result[0].confidence || 0);
        } else {
          interimTranscript += result[0].transcript;
        }
      }

      // ── UNIVERSAL BARGE-IN ─────────────────────────────────────────────
      if (ttsPlayingRef.current) {
        // Accept BOTH final and interim transcripts for barge-in.
        // Interim: only if 4+ words (avoids single-word false positives)
        const bargeText = finalTranscript.trim() || interimTranscript.trim();
        const isInterim = !finalTranscript.trim() && !!interimTranscript.trim();
        const wordCount = bargeText.split(/\s+/).length;

        if (bargeText && (!isInterim || wordCount >= 4)) {
          const speechProb = speechProbRef.current;
          const rmsVol = getMicVolume();
          const looksLikeEcho = isEcho(bargeText);
          // Lowered thresholds for more responsive interruption
          const bargeInThreshold = isFallbackRmsRef.current ? 0.03 : 0.35;
          if (speechProb > bargeInThreshold && !looksLikeEcho) {
            console.log(
              `[BARGE-IN] Interrupting Alita (${isInterim ? 'interim' : 'final'}, speechProb=${speechProb.toFixed(3)}, rms=${rmsVol.toFixed(3)}): "${bargeText.slice(0, 60)}"`,
            );
            stopTTS();
            ttsCooldownRef.current = 0;
            // If this was interim, let the final transcript flow through
            // by NOT returning — it will be processed below
            if (isInterim) return;
          } else {
            if (looksLikeEcho) {
              console.log(
                "[BARGE-IN] Ignored echo:",
                bargeText.slice(0, 40),
              );
            } else {
              console.log(
                `[BARGE-IN] Ignored low-confidence speech (speechProb=${speechProb.toFixed(3)}, rms=${rmsVol.toFixed(3)})`,
              );
            }
            return;
          }
        } else {
          return;
        }
      }

      // ── ENERGY-ADAPTIVE ECHO GATE ────────────────────────────────────
      const ECHO_GATE_MAX_MS = 300;
      const timeSinceTTS = Date.now() - ttsEndTimeRef.current;
      const withinGateWindow =
        ttsEndTimeRef.current > 0 && timeSinceTTS < ECHO_GATE_MAX_MS;

      if (withinGateWindow) {
        const speechProb = speechProbRef.current;
        const currentVol = getMicVolume();
        const elevatedSpeechThreshold = isFallbackRmsRef.current ? 0.04 : 0.4;
        const energyStillElevated = speechProb > elevatedSpeechThreshold;
        const textIsEcho = isEcho(
          (finalTranscript || interimTranscript).trim(),
        );

        if (energyStillElevated && textIsEcho) {
          console.log(
            `[ECHO-GATE] Blocked echo (${timeSinceTTS}ms, speechProb=${speechProb.toFixed(4)}, rms=${currentVol.toFixed(4)})`,
          );
          return;
        }
        if (!energyStillElevated) {
          console.log(
            `[ECHO-GATE] Energy cleared in ${timeSinceTTS}ms — accepting`,
          );
          ttsEndTimeRef.current = 0;
        }
      }

      // Show interim text (visual feedback) + speculative response
      if (interimTranscript && !ttsPlayingRef.current) {
        onSpeechStartRef.current?.();
        isSpeaking.current = true;

        // ── SPECULATIVE PRE-GENERATION ─────────────────────────────────
        // Send interim transcript to backend when it's substantial enough
        // so the LLM can start generating before the user finishes speaking.
        const interimWords = interimTranscript.trim().split(/\s+/);
        if (interimWords.length >= 4 && !dictationModeRef.current) {
          const interimNorm = interimTranscript.trim().toLowerCase();
          // Only send if significantly different from last speculative query
          if (interimNorm !== lastSpecTextRef.current) {
            lastSpecTextRef.current = interimNorm;
            clearTimeout(specDebounceRef.current);
            specDebounceRef.current = setTimeout(() => {
              sendSpecRef.current?.(interimTranscript.trim());
            }, 300); // debounce 300ms to avoid flooding
          }
        }
      }

      // ── Process final transcript ────────────────────────────────────
      if (finalTranscript.trim()) {
        lastSpeechTime.current = Date.now();
        const cleaned = normalizeWakeWord(finalTranscript.trim());

        // Short dedup guard: prevent the SAME utterance from being sent twice
        // within a 2s window (STT often fires multiple finals for one phrase).
        // This replaces the old processingRef gate which blocked ALL speech.
        const now_dedup = Date.now();
        if (now_dedup - lastSentTimeRef.current < 2000 && lastSentTextRef.current) {
          const prevW = lastSentTextRef.current.toLowerCase().split(/\s+/);
          const curW = cleaned.toLowerCase().split(/\s+/);
          const ol = curW.filter(w => prevW.includes(w)).length / Math.max(curW.length, 1);
          if (ol > 0.85) {
            console.log("[STT] Dedup: too similar to last send (%.0f%%, %dms ago)", ol * 100, now_dedup - lastSentTimeRef.current);
            return;
          }
        }

        if (bestConfidence > 0 && bestConfidence < 0.4) {
          console.log("[STT] Rejected (low confidence):", cleaned);
          return;
        }

        const words = cleaned.split(/\s+/).filter((w) => w.length > 0);
        if (words.length < 1 || cleaned.length < 2) return;

        const NOISE_WORDS = new Set([
          "hmm",
          "hm",
          "uh",
          "um",
          "ah",
          "oh",
          "mm",
          "mhm",
          "huh",
          "eh",
          "uhh",
          "umm",
          "the",
          "a",
          "and",
          "is",
          "it",
        ]);
        if (
          words.length <= 2 &&
          words.every((w) => NOISE_WORDS.has(w.toLowerCase()))
        ) {
          console.log("[STT] Rejected (noise):", cleaned);
          return;
        }

        if (isEcho(cleaned)) {
          console.log("[ECHO] Rejected final:", cleaned.slice(0, 40));
          return;
        }

        const now = Date.now();
        const timeSinceLast = now - lastSentTimeRef.current;
        if (timeSinceLast < 30000 && lastSentTextRef.current) {
          const prevWords = lastSentTextRef.current.toLowerCase().split(/\s+/);
          const curWords = cleaned.toLowerCase().split(/\s+/);
          const overlap = curWords.filter((w) => prevWords.includes(w)).length;
          const similarity = overlap / Math.max(curWords.length, 1);
          if (similarity > 0.5) {
            console.log(
              "[STT] Rejected (anti-repeat, %.0f%% similar, %ds ago):",
              similarity * 100,
              (timeSinceLast / 1000).toFixed(0),
              cleaned.slice(0, 40),
            );
            return;
          }
        }

        console.log("[STT] ✓ Accepted:", cleaned);
        isSpeaking.current = false;
        lastAlitaTextRef.current = "";

        // Cancel any pending speculative query — the real query is being sent
        clearTimeout(specDebounceRef.current);
        cancelSpecRef.current?.();
        lastSpecTextRef.current = "";

        // Track the user's query for barge-in context
        lastUserQueryRef.current = cleaned;

        // ── DICTATION MODE: route to app instead of chat ────────────
        if (dictationModeRef.current) {
          const lower = cleaned.toLowerCase();
          if (
            lower.includes("stop dictating") ||
            lower.includes("stop writing") ||
            lower.includes("done writing") ||
            lower.includes("band karo") ||
            lower === "stop" ||
            lower === "done"
          ) {
            console.log("[Dictation] Stop command detected");
            onDictationStopRef.current?.();
            processingRef.current = false;
            setMicState("active");
            return;
          }
          console.log("[Dictation] Typing:", cleaned);
          sendDictationRef.current?.(cleaned);
          processingRef.current = false;
          setMicState("dictating");
          return;
        }

        // ── NORMAL MODE: send to chat ──────────────────────────────
        onTranscriptRef.current?.(cleaned);
        onUtteranceCommittedRef.current?.(cleaned);
        setMicState("processing");
        lastSentTextRef.current = cleaned;
        lastSentTimeRef.current = Date.now();

        // Brief visual "processing" state (600ms), then back to active
        setTimeout(() => {
          if (!ttsPlayingRef.current) {
            setMicState("active");
          }
        }, 600);
      }
    };

    recognition.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;

      if (event.error === "network") {
        const MAX_RETRIES = 3;
        const retryCount = networkRetryCountRef.current;
        if (retryCount < MAX_RETRIES) {
          networkRetryCountRef.current = retryCount + 1;
          const delayMs = 1000 * Math.pow(2, retryCount);
          console.warn(
            `[STT] Network error — retrying in ${delayMs}ms (attempt ${retryCount + 1}/${MAX_RETRIES})`,
          );
          clearTimeout(networkRetryTimerRef.current);
          networkRetryTimerRef.current = setTimeout(() => {
            if (enabledRef.current) {
              _restartRecognition();
            }
          }, delayMs);
        } else {
          console.error(
            "[STT] Network error — max retries reached, mic degraded",
          );
          networkRetryCountRef.current = 0;
          setMicState("error");
        }
        return;
      }

      console.error("[STT] Error:", event.error);
      if (event.error === "not-allowed") setMicState("error");
    };

    const myId = ++recognitionIdRef.current;

    recognition.onend = () => {
      if (myId !== recognitionIdRef.current) {
        console.log("[STT] Stale instance ended — suppressing restart");
        return;
      }
      if (enabledRef.current) {
        _restartRecognition();
      }
    };

    recognitionRef.current = recognition;

    try {
      recognition.start();
      return true;
    } catch (e) {
      console.error("[STT] Failed to start:", e);
      return false;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [_restartRecognition, isEcho, stopTTS, getMicVolume, isFallbackRmsRef, speechProbRef]);

  // ── Auto-start when enabled ─────────────────────────────────────────────
  // startWebSpeech is now stable (no prop deps), so this only fires when
  // `enabled` truly changes — no more spurious restarts.
  useEffect(() => {
    if (enabled) {
      const success = startWebSpeech();
      if (!success) setMicState("error");
    }
    return () => {
      clearTimeout(restartTimeoutRef.current);
      try {
        recognitionRef.current?.stop();
      } catch (_) {}
    };
  }, [enabled, startWebSpeech]);

  // ── Music / ambient audio detection ─────────────────────────────────────
  useEffect(() => {
    if (!enabled) return;
    const MUSIC_VOLUME_THRESHOLD = 0.04; // Sustained ambient audio level
    const MUSIC_DURATION_MS = 3000; // Must persist 3s without speech

    musicCheckIntervalRef.current = setInterval(() => {
      const vol = getMicVolume();
      const now = Date.now();
      const timeSinceSpeech = now - lastSpeechTime.current;

      if (
        vol > MUSIC_VOLUME_THRESHOLD &&
        timeSinceSpeech > MUSIC_DURATION_MS &&
        !ttsPlayingRef.current
      ) {
        if (!musicVolumeStart.current) {
          musicVolumeStart.current = now;
        } else if (
          now - musicVolumeStart.current > MUSIC_DURATION_MS &&
          !musicDetectedRef.current
        ) {
          musicDetectedRef.current = true;
          onMusicDetected?.(true);
          console.log("[Music] Background music/audio detected (vol=%.3f)", vol);
        }
      } else {
        musicVolumeStart.current = 0;
        if (musicDetectedRef.current) {
          musicDetectedRef.current = false;
          onMusicDetected?.(false);
        }
      }
    }, 500);

    return () => clearInterval(musicCheckIntervalRef.current);
  }, [enabled, getMicVolume, onMusicDetected]);

  // ── Restart recognition when STT language changes ─────────────────────
  useEffect(() => {
    if (!enabled || !recognitionRef.current) return;

    const nextLanguage = (sttLanguage || "en-IN").toLowerCase();
    if (nextLanguage === appliedLanguageRef.current) return;

    appliedLanguageRef.current = nextLanguage;
    recognitionRef.current.lang = sttLanguage;

    console.log("[STT] Language changed to:", sttLanguage, "— restarting recognition");
    try {
      recognitionRef.current.stop();
    } catch (_) {}
    // Let onend + instance guard handle the restart (prevents duplicate starts).
  }, [enabled, sttLanguage]);

  // ── Seamless Connectivity Detection & Offline PCM Streaming ─────────────
  // Uses AudioWorklet (not deprecated ScriptProcessorNode) for PCM extraction.
  // Sends binary Float32Array instead of JSON arrays (8× less bandwidth).
  // Pre-warms at startup for zero-lag online↔offline switching.
  const offlineStreamRef = useRef(null);
  const offlineCtxRef = useRef(null);
  const offlineWorkletRef = useRef(null); // AudioWorkletNode
  const offlineActiveRef = useRef(false);
  const connectivityDebounceRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;

    const preWarmPCMStream = async () => {
      if (offlineCtxRef.current) return; // already warmed

      try {
        // Get mic stream early — getUserMedia is the slow part (~200-500ms)
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { sampleRate: 16000, channelCount: 1, echoCancellation: true },
        });
        offlineStreamRef.current = stream;

        const ctx = new AudioContext({ sampleRate: 16000 });
        offlineCtxRef.current = ctx;

        // Register the AudioWorklet module
        try {
          await ctx.audioWorklet.addModule("/offlineAudioProcessor.js");
          const workletNode = new AudioWorkletNode(ctx, "offline-audio-processor");
          offlineWorkletRef.current = workletNode;

          // Listen for PCM chunks from the worklet (runs in separate thread)
          workletNode.port.onmessage = (e) => {
            if (e.data.type === "pcm_chunk" && e.data.pcm) {
              // Dispatch binary Float32Array (not JSON — 8× smaller)
              window.dispatchEvent(
                new CustomEvent("Alita:offline_audio_chunk", {
                  detail: { pcm_binary: e.data.pcm.buffer }, // ArrayBuffer
                })
              );
            }
          };

          const source = ctx.createMediaStreamSource(stream);
          source.connect(workletNode);
          workletNode.connect(ctx.destination);
          console.log("[OFFLINE] AudioWorklet pre-warmed (zero-lag switching ready)");
        } catch (workletErr) {
          // Fallback to ScriptProcessorNode if AudioWorklet not supported
          console.warn("[OFFLINE] AudioWorklet not available, using ScriptProcessor fallback:", workletErr);
          const source = ctx.createMediaStreamSource(stream);
          const processor = ctx.createScriptProcessor(4096, 1, 1);
          offlineWorkletRef.current = processor;

          processor.onaudioprocess = (e) => {
            if (!offlineActiveRef.current) return;
            const inputData = e.inputBuffer.getChannelData(0);
            window.dispatchEvent(
              new CustomEvent("Alita:offline_audio_chunk", {
                detail: { pcm_binary: inputData.buffer.slice(0) }, // copy ArrayBuffer
              })
            );
          };

          source.connect(processor);
          processor.connect(ctx.destination);
          console.log("[OFFLINE] ScriptProcessor fallback pre-warmed");
        }

        // Suspend immediately if online — save CPU until needed
        if (navigator.onLine) {
          await ctx.suspend();
        }
      } catch (err) {
        console.error("[OFFLINE] Failed to pre-warm PCM stream:", err);
      }
    };

    preWarmPCMStream();

    const sendConnectivity = (online) => {
      window.dispatchEvent(
        new CustomEvent("Alita:connectivity_change", {
          detail: { online },
        })
      );
    };

    const activateOffline = async () => {
      offlineActiveRef.current = true;
      // Tell worklet to start sending chunks
      if (offlineWorkletRef.current?.port) {
        offlineWorkletRef.current.port.postMessage({ type: "set_active", active: true });
      }
      if (offlineCtxRef.current?.state === "suspended") {
        await offlineCtxRef.current.resume();
      }
      console.log("[Connectivity] ⚡ OFFLINE mode ACTIVE — PCM streaming to Whisper");
    };

    const deactivateOffline = async () => {
      offlineActiveRef.current = false;
      // Tell worklet to stop sending chunks
      if (offlineWorkletRef.current?.port) {
        offlineWorkletRef.current.port.postMessage({ type: "set_active", active: false });
      }
      if (offlineCtxRef.current?.state === "running") {
        await offlineCtxRef.current.suspend();
      }
      console.log("[Connectivity] ⚡ ONLINE mode ACTIVE — Web Speech API STT");
    };

    // Debounced connectivity handlers
    const handleOnline = () => {
      clearTimeout(connectivityDebounceRef.current);
      connectivityDebounceRef.current = setTimeout(() => {
        console.log("[Connectivity] Back ONLINE");
        sendConnectivity(true);
        deactivateOffline();
      }, 500);
    };

    const handleOffline = () => {
      clearTimeout(connectivityDebounceRef.current);
      connectivityDebounceRef.current = setTimeout(() => {
        console.log("[Connectivity] Gone OFFLINE");
        sendConnectivity(false);
        activateOffline();
      }, 200);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    if (!navigator.onLine) {
      sendConnectivity(false);
      activateOffline();
    }

    return () => {
      clearTimeout(connectivityDebounceRef.current);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      offlineActiveRef.current = false;
      if (offlineWorkletRef.current?.port) {
        offlineWorkletRef.current.port.postMessage({ type: "set_active", active: false });
      }
      try {
        offlineWorkletRef.current?.disconnect();
        offlineStreamRef.current?.getTracks().forEach((t) => t.stop());
        if (offlineCtxRef.current?.state !== "closed") {
          offlineCtxRef.current?.close();
        }
      } catch (_) {}
      offlineStreamRef.current = null;
      offlineCtxRef.current = null;
      offlineWorkletRef.current = null;
    };
  }, [enabled]);

  // ── Notification API permission ─────────────────────────────────────────
  useEffect(() => {
    if ("Notification" in window && Notification.permission === "default") {
      Notification.requestPermission();
    }
  }, []);

  // ── Keyboard shortcut: Escape to interrupt TTS (still available) ────────
  useEffect(() => {
    const handleKey = (e) => {
      if (e.code === "Escape" && ttsPlayingRef.current) {
        e.preventDefault();
        stopTTS();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [stopTTS]);

  // ── Song Recognition: Record mic audio for identification ──────────────
  useEffect(() => {
    const handleSongRecognition = async () => {
      if (songRecordingRef.current) return; // Already recording
      songRecordingRef.current = true;
      setMicState("identifying");
      console.log("[Song] Starting 8-second recording for song recognition...");

      let dedicatedStream = null;
      try {
        // Always get a FRESH stream — reusing the analyser stream causes
        // "NotSupportedError" because it's already wired to an AudioContext node.
        dedicatedStream = await navigator.mediaDevices.getUserMedia({
          audio: true,
        });

        // Pick a MIME type the browser actually supports
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : MediaRecorder.isTypeSupported("audio/webm")
            ? "audio/webm"
            : ""; // let browser pick default

        const mediaRecorder = new MediaRecorder(
          dedicatedStream,
          mimeType ? { mimeType } : undefined,
        );
        const chunks = [];

        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) chunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
          songRecordingRef.current = false;
          setMicState("active");
          // Release the dedicated stream
          dedicatedStream?.getTracks().forEach((t) => t.stop());

          const blob = new Blob(chunks, { type: "audio/webm" });

          // Convert to base64
          const reader = new FileReader();
          reader.onload = () => {
            const base64 = reader.result.split(",")[1]; // strip data:audio/webm;base64,
            console.log(
              "[Song] Sending %.1f KB audio for recognition",
              (base64.length * 3) / 4 / 1024,
            );
            // Dispatch event for App.jsx to send via WebSocket
            window.dispatchEvent(
              new CustomEvent("Alita:song_audio_ready", {
                detail: { audio_b64: base64 },
              }),
            );
          };
          reader.readAsDataURL(blob);
        };

        mediaRecorder.start();

        // Record for 8 seconds
        setTimeout(() => {
          if (mediaRecorder.state === "recording") {
            mediaRecorder.stop();
            console.log("[Song] Recording complete (8s)");
          }
        }, 8000);
      } catch (err) {
        console.error("[Song] Recording failed:", err);
        songRecordingRef.current = false;
        setMicState("active");
      }
    };

    window.addEventListener(
      "Alita:start_song_recognition",
      handleSongRecognition,
    );
    return () =>
      window.removeEventListener(
        "Alita:start_song_recognition",
        handleSongRecognition,
      );
  }, []);

  // ── Emergency auto-recording (triggered by backend) ─────────────────────
  useEffect(() => {
    const handleEmergencyAlert = async (e) => {
      const { sound, confidence, level } = e.detail || {};
      if (emergencyRecordingRef.current) return; // Already recording

      console.log(
        `[EMERGENCY] 🚨 ${sound} detected (${(confidence * 100).toFixed(0)}%) — level: ${level}`,
      );
      setEmergencyActive(true);
      setEmergencySound(sound || "Unknown");
      emergencyRecordingRef.current = true;

      try {
        // Try webcam + audio first, fall back to audio only
        let stream;
        try {
          stream = await navigator.mediaDevices.getUserMedia({
            video: true,
            audio: true,
          });
          console.log("[EMERGENCY] Recording with webcam + audio");
        } catch {
          try {
            stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            console.log("[EMERGENCY] Recording audio only (no webcam)");
          } catch (err) {
            console.error("[EMERGENCY] Cannot access mic/cam:", err);
            emergencyRecordingRef.current = false;
            setEmergencyActive(false);
            return;
          }
        }

        emergencyStreamRef.current = stream;
        const mimeType = MediaRecorder.isTypeSupported(
          "video/webm;codecs=vp9,opus",
        )
          ? "video/webm;codecs=vp9,opus"
          : MediaRecorder.isTypeSupported("video/webm")
            ? "video/webm"
            : MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
              ? "audio/webm;codecs=opus"
              : "";

        const recorder = new MediaRecorder(
          stream,
          mimeType ? { mimeType } : undefined,
        );
        const chunks = [];

        recorder.ondataavailable = (ev) => {
          if (ev.data.size > 0) chunks.push(ev.data);
        };

        recorder.onstop = () => {
          console.log("[EMERGENCY] Recording stopped, saving...");
          emergencyRecordingRef.current = false;
          stream.getTracks().forEach((t) => t.stop());
          emergencyStreamRef.current = null;

          // Save recording as blob and dispatch for backend upload
          const blob = new Blob(chunks, { type: mimeType || "video/webm" });
          const reader = new FileReader();
          reader.onload = () => {
            const base64 = reader.result.split(",")[1];
            window.dispatchEvent(
              new CustomEvent("Alita:emergency_recording_ready", {
                detail: {
                  audio_b64: base64,
                  sound,
                  confidence,
                  duration_seconds: 120,
                },
              }),
            );
          };
          reader.readAsDataURL(blob);
          setEmergencyActive(false);
        };

        emergencyRecorderRef.current = recorder;
        recorder.start(5000); // Record in 5-second chunks

        // Auto-stop after 2 minutes
        setTimeout(() => {
          if (recorder.state === "recording") {
            recorder.stop();
            console.log("[EMERGENCY] Auto-stopped after 2 minutes");
          }
        }, 120000);
      } catch (err) {
        console.error("[EMERGENCY] Recording failed:", err);
        emergencyRecordingRef.current = false;
        setEmergencyActive(false);
      }
    };

    // Stop emergency recording handler
    const handleEmergencyStop = () => {
      if (emergencyRecorderRef.current?.state === "recording") {
        emergencyRecorderRef.current.stop();
        console.log("[EMERGENCY] Stopped by user");
      }
      setEmergencyActive(false);
    };

    window.addEventListener("Alita:emergency_alert", handleEmergencyAlert);
    window.addEventListener("Alita:emergency_stop", handleEmergencyStop);
    return () => {
      window.removeEventListener("Alita:emergency_alert", handleEmergencyAlert);
      window.removeEventListener("Alita:emergency_stop", handleEmergencyStop);
    };
  }, []);

  // ── Environment sounds handler ──────────────────────────────────────────
  useEffect(() => {
    const handleEnvironmentUpdate = (e) => {
      const sounds = e.detail?.sounds || [];
      setEnvironmentSounds(sounds);
      // Auto-clear after 10 seconds if no update
      setTimeout(() => setEnvironmentSounds([]), 10000);
    };
    window.addEventListener(
      "Alita:environment_update",
      handleEnvironmentUpdate,
    );
    return () =>
      window.removeEventListener(
        "Alita:environment_update",
        handleEnvironmentUpdate,
      );
  }, []);
  // ── Mic status indicator ────────────────────────────────────────────────
  const isEmergency = emergencyActive;
  const statusColor = isEmergency
    ? "rgba(239,68,68,1)"
    : micState === "active"
      ? "rgba(163,230,53,0.8)"
      : micState === "speaking"
        ? "rgba(192,132,252,0.6)"
        : micState === "dictating"
          ? "rgba(251,191,36,0.8)"
          : micState === "processing"
            ? "rgba(251,191,36,0.7)"
            : micState === "error"
              ? "rgba(239,68,68,0.8)"
              : "rgba(255,255,255,0.2)";

  const dotColor = isEmergency
    ? "#ef4444"
    : micState === "active"
      ? "#a3e635"
      : micState === "speaking"
        ? "#c084fc"
        : micState === "dictating"
          ? "#fbbf24"
          : micState === "processing"
            ? "#fbbf24"
            : micState === "error"
              ? "#ef4444"
              : "rgba(255,255,255,0.2)";

  const statusText = isEmergency
    ? `🚨 EMERGENCY — ${emergencySound} detected · recording...`
    : micState === "active"
      ? "listening"
      : micState === "speaking"
        ? "alita is speaking · say 'stop' or press Esc"
        : micState === "dictating"
          ? `dictating into ${dictationMode?.app || "app"}`
          : micState === "processing"
            ? "thinking…"
            : micState === "identifying"
              ? "🎵 listening to the song…"
              : micState === "error"
                ? "mic blocked"
                : "connecting…";

  // Sound emoji mapping
  const soundEmoji = {
    Music: "🎵",
    Singing: "🎤",
    Dog: "🐕",
    Cat: "🐱",
    Bird: "🐦",
    Rain: "🌧️",
    Thunder: "⛈️",
    Wind: "💨",
    "Car horn": "🚗",
    Siren: "🚨",
    Alarm: "🔔",
    Doorbell: "🔔",
    Typing: "⌨️",
    Laughter: "😂",
  };

  return (
    <>
      {/* Emergency border overlay */}
      {isEmergency && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            border: "3px solid #ef4444",
            borderRadius: "0",
            pointerEvents: "none",
            zIndex: 9999,
            animation: "emergencyPulse 1s ease-in-out infinite",
          }}
        />
      )}

      {/* Environment sounds indicator */}
      {environmentSounds.length > 0 && !isEmergency && (
        <div
          style={{
            position: "fixed",
            bottom: "56px",
            left: "50%",
            transform: "translateX(-50%)",
            zIndex: 19,
            display: "flex",
            gap: "8px",
            fontFamily: "'DM Mono', monospace",
            fontSize: "0.55rem",
            color: "rgba(255,255,255,0.5)",
            letterSpacing: "0.1em",
          }}
        >
          {environmentSounds.map((s, i) => (
            <span
              key={i}
              style={{
                background: "rgba(255,255,255,0.05)",
                padding: "2px 8px",
                borderRadius: "10px",
                border: "1px solid rgba(255,255,255,0.08)",
              }}
            >
              {soundEmoji[s.label] || "🔊"} {s.label}
            </span>
          ))}
        </div>
      )}

      {/* Main status bar */}
      <div
        onClick={() => {
          if (ttsPlayingRef.current) stopTTS();
          if (isEmergency) {
            window.dispatchEvent(new CustomEvent("Alita:emergency_stop"));
          }
        }}
        style={{
          position: "fixed",
          bottom: "32px",
          left: "50%",
          transform: "translateX(-50%)",
          zIndex: 20,
          display: "flex",
          alignItems: "center",
          gap: "10px",
          pointerEvents: ttsPlayingRef.current || isEmergency ? "auto" : "none",
          cursor: ttsPlayingRef.current || isEmergency ? "pointer" : "default",
          fontFamily: "'DM Mono', monospace",
          fontSize: "0.62rem",
          letterSpacing: "0.15em",
          textTransform: "uppercase",
          color: statusColor,
          transition: "color 600ms ease",
        }}
      >
        <div
          style={{
            width: isEmergency ? "8px" : "6px",
            height: isEmergency ? "8px" : "6px",
            borderRadius: "50%",
            background: dotColor,
            boxShadow: isEmergency
              ? "0 0 12px #ef4444, 0 0 24px rgba(239,68,68,0.4)"
              : micState === "active"
                ? "0 0 8px #a3e635"
                : micState === "speaking"
                  ? "0 0 8px #c084fc"
                  : micState === "dictating"
                    ? "0 0 8px #fbbf24"
                    : micState === "processing"
                      ? "0 0 8px #fbbf24"
                      : "none",
            animation: isEmergency
              ? "emergencyPulse 0.5s ease-in-out infinite"
              : micState === "active"
                ? "blink 2s ease-in-out infinite"
                : micState === "speaking"
                  ? "pulse 1.5s ease-in-out infinite"
                  : "none",
            transition: "background 600ms ease, box-shadow 600ms ease",
          }}
        />
        {statusText}
      </div>

      {/* Emergency pulse CSS animation */}
      <style>{`
        @keyframes emergencyPulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.3; }
        }
      `}</style>
    </>
  );
}
