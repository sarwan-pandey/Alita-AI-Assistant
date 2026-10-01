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
import { audioStreamPlayer } from "../../utils/AudioStreamPlayer";

const SAMPLE_RATE = 16000;

// ── Wake Word Normalizer ─────────────────────────────────────────────────────
// STT frequently mishears "Alita" as variations below.
// Only exact known mishearings — no aggressive multi-word patterns.
const WAKE_MISHEARINGS = [
  // MJ mishearings
  /\bm\s*\.?\s*j\b/gi,
  /\bemjay\b/gi,
  /\bem\s+jay\b/gi,
  /\bamjay\b/gi,
  /\bmjay\b/gi,
  // Alita legacy mishearings
  /\blolita\b/gi,
  /\bloleta\b/gi,
  /\blolyta\b/gi,
  /\baletta\b/gi,
  /\baleeta\b/gi,
  /\baleetta\b/gi,
  /\baleta\b/gi,
  /\barita\b/gi,
  /\barida\b/gi,
  /\belita\b/gi,
  /\beleta\b/gi,
  /\belyta\b/gi,
  /\bellita\b/gi,
  /\balitha\b/gi,
  /\balida\b/gi,
  /\baletha\b/gi,
  /\balyda\b/gi,
  /\balitah\b/gi,
  /\balitta\b/gi,
  /\bolita\b/gi,
  /\boleeta\b/gi,
  /\bulita\b/gi,
  /\ba\s+leader\b/gi,
  /\ba\s+letter\b/gi,
  /\ba\s+litre\b/gi,
  /\ba\s+liter\b/gi,
  /\bour\s+leader\b/gi,
  /\bthe\s+leader\b/gi,
  /\ba\s+lita\b/gi,
  /\ba\s*lita\b/gi,
];

function normalizeWakeWord(text) {
  if (!text) return text;
  let result = text;
  for (const pattern of WAKE_MISHEARINGS) {
    result = result.replace(pattern, "MJ");
  }
  // Compound mishearings (with greeting / call prefixes)
  result = result.replace(/\b(hello|hey|hi|ok|okay|listen)\s+(m\s*j|emjay|em\s*jay|mjay|later|leader|letter|litre|liter|lolita|elita|lita|leeta|aleeta|alita)\b/gi, "$1 MJ");
  result = result.replace(/\b(hello|hey|hi|ok|okay|listen)\s+a\s+(leader|letter|litre|liter|lita)\b/gi, "$1 MJ");
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
  isOverlay = false,
}) {
  const [micState, setMicState] = useState("connecting");
  const recognitionRef = useRef(null);
  const ttsPlayingRef = useRef(false);
  const isSpeaking = useRef(false);
  const restartTimeoutRef = useRef(null);
  const lastAlitaTextRef = useRef(""); // what Alita just said (for echo rejection)
  const processingRef = useRef(false); // prevents double-sends while backend is processing
  const processingTimeoutRef = useRef(null); // watchdog timer for in-flight processing state
  const lastSentTextRef = useRef(""); // last text sent to backend (anti-repeat)
  const lastSentTimeRef = useRef(0); // timestamp of last sent text
  // ── AGI: Utterance accumulation (wait for user to finish full instruction) ──
  const accumulatedFinalRef = useRef(""); // accumulates final transcripts (visual only)
  const utteranceTimerRef = useRef(null); // delay timer before sending
  const UTTERANCE_WAIT_MS = 1200; // fallback timer for dictation mode only

  const ttsCooldownRef = useRef(0); // timestamp when TTS finished (cooldown period)
  const networkRetryCountRef = useRef(0); // STT network error retry counter
  const networkRetryTimerRef = useRef(null); // STT network error retry timer
  const recognitionIdRef = useRef(0); // Increments each time a new SpeechRecognition is created
  // — stale instances check this to avoid restart loops
  const ttsEndTimeRef = useRef(0); // timestamp when TTS finished (for echo gate)
  const appliedLanguageRef = useRef((sttLanguage || "en-IN").toLowerCase());
  const userSpeakingRef = useRef(false); // only trigger onSpeechStart on transition from silence
  const bootTimeRef = useRef(Date.now()); // Boot cooldown: ignore STT for first 5s after mount

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

  const handleAudioFrame = useCallback((frame, prob) => {
    // Drop audio chunks during TTS playback or immediately following TTS to reject echo
    if (ttsPlayingRef.current) return;
    // Drop audio chunks while backend is processing committed utterance (rejects trailing silence/noise)
    if (processingRef.current) return;
    const timeSinceTTS = Date.now() - (ttsEndTimeRef.current || 0);
    if (ttsEndTimeRef.current > 0 && timeSinceTTS < 800) return;

    // Send single unified 16kHz Float32Array PCM frame to backend Whisper
    window.dispatchEvent(
      new CustomEvent("Alita:offline_audio_chunk", {
        detail: { pcm_binary: frame.buffer.slice(0) },
      })
    );
  }, []);

  const handleSpeechEndAudio = useCallback((audio) => {
    // Signal backend that VAD detected end of user utterance for instant flush
    window.dispatchEvent(
      new CustomEvent("Alita:vad_speech_end", {
        detail: { length: audio?.length || 0 },
      })
    );
  }, []);

  const { speechProbRef, isFallbackRmsRef, getMicVolume } = useSileroVAD({
    enabled,
    onAudioFrame: handleAudioFrame,
    onSpeechEndAudio: handleSpeechEndAudio,
  });

  // ── Stop TTS immediately (barge-in) ──────────────────────────────────────
  const stopTTS = useCallback(() => {
    audioStreamPlayer.interrupt();
    clearTimeout(processingTimeoutRef.current);
    const wasPlaying = ttsPlayingRef.current;
    const wasProcessing = processingRef.current;
    ttsPlayingRef.current = false;
    processingRef.current = false; // allow new speech immediately
    setMicState("active");

    if (!wasPlaying && !wasProcessing) return;

    // ── Send barge-in context to backend ────────────────────────────────
    const partialResponse = accumulatedResponseRef.current || "";
    const originalQuery = lastUserQueryRef.current || "";
    if (partialResponse || originalQuery) {
      console.log(
        `[BARGE-IN] Sending context: response=${partialResponse.length} chars, query='${originalQuery.slice(0, 40)}'`
      );
      sendBargeInRef.current?.(partialResponse, originalQuery);
    }

    console.log("[TTS] ⚡ Barge-in triggered — user is speaking, stopping MJ");
    onSpeechStartRef.current?.();
  }, []);

  // ── Global interrupt listener ─────────────────────────────────────────────
  useEffect(() => {
    const handleInterrupt = () => {
      stopTTS();
    };
    window.addEventListener("MJ:interrupt", handleInterrupt);
    window.addEventListener("Alita:interrupt", handleInterrupt);
    return () => {
      window.removeEventListener("MJ:interrupt", handleInterrupt);
      window.removeEventListener("Alita:interrupt", handleInterrupt);
    };
  }, [stopTTS]);

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

      // Instant Voice Barge-In: if user speaks while Alita is speaking, stop TTS immediately (<50ms)
      if (ttsPlayingRef.current && (prob > 0.48 || rms > 0.42)) {
        stopTTS();
      }
    }, 45);

    return () => {
      clearInterval(timer);
      onVoiceActivity?.(0);
    };
  }, [enabled, getMicVolume, onVoiceActivity, speechProbRef, stopTTS]);


  // ── TTS event listener (seamless streaming audio queue) ─────────────
  useEffect(() => {
    audioStreamPlayer.options.onStart = () => {
      clearTimeout(processingTimeoutRef.current);
      ttsPlayingRef.current = true;
      setMicState("speaking");
    };
    audioStreamPlayer.options.onEnd = () => {
      clearTimeout(processingTimeoutRef.current);
      ttsPlayingRef.current = false;
      processingRef.current = false;
      setMicState("active");
    };

    const handler = (e) => {
      const msg = e.detail;
      if (msg.is_final && !msg.audio_b64) {
        // Authoritative completion: backend finished synthesis for this turn.
        // If audio is already playing or queued, audioStreamPlayer.options.onEnd will clear processingRef when done.
        // If NO audio was generated (silent response or empty text), clear processing state immediately.
        if (!audioStreamPlayer.isPlaying && audioStreamPlayer.queue.length === 0) {
          clearTimeout(processingTimeoutRef.current);
          processingRef.current = false;
          ttsPlayingRef.current = false;
          setMicState("active");
        }
        return;
      }
      audioStreamPlayer.enqueueChunk(msg);
    };

    const errorHandler = () => {
      clearTimeout(processingTimeoutRef.current);
      processingRef.current = false;
      ttsPlayingRef.current = false;
      setMicState("active");
      audioStreamPlayer.interrupt();
    };

    const discardHandler = (e) => {
      const msg = e.detail;
      // If there is NO active turn in flight on the backend and audio is not playing:
      // immediately reset processing state and disarm watchdog so mic is ready without waiting
      if (!msg?.active_turn_in_flight && !audioStreamPlayer.isPlaying && audioStreamPlayer.queue.length === 0) {
        clearTimeout(processingTimeoutRef.current);
        processingRef.current = false;
        ttsPlayingRef.current = false;
        setMicState("active");
      }
    };

    window.addEventListener("MJ:tts_chunk", handler);
    window.addEventListener("Alita:tts_chunk", handler);
    window.addEventListener("MJ:turn_error", errorHandler);
    window.addEventListener("Alita:turn_error", errorHandler);
    window.addEventListener("MJ:turn_discarded", discardHandler);
    window.addEventListener("Alita:turn_discarded", discardHandler);
    return () => {
      window.removeEventListener("MJ:tts_chunk", handler);
      window.removeEventListener("Alita:tts_chunk", handler);
      window.removeEventListener("MJ:turn_error", errorHandler);
      window.removeEventListener("Alita:turn_error", errorHandler);
      window.removeEventListener("MJ:turn_discarded", discardHandler);
      window.removeEventListener("Alita:turn_discarded", discardHandler);
    };
  }, []);

  // ── Track what MJ says for echo rejection + barge-in context ─────────
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
    window.addEventListener("MJ:llm_token", tokenHandler);
    window.addEventListener("Alita:llm_token", tokenHandler);
    return () => {
      window.removeEventListener("MJ:llm_token", tokenHandler);
      window.removeEventListener("Alita:llm_token", tokenHandler);
    };
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

    // Only check echo while TTS is actively playing or within 1.5s of TTS ending
    // (covers physical room reverb without blocking real user speech 5s later)
    const isCurrentlyPlaying = ttsPlayingRef.current;
    const msSinceTTS = Date.now() - (ttsEndTimeRef.current || 0);
    if (!isCurrentlyPlaying && msSinceTTS > 1500) return false;

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
      // ── Stabilizer: Ignore STT only for first 300ms after mount ──────
      if (Date.now() - bootTimeRef.current < 300) {
        return;
      }

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
          // Barge-in thresholds — raised fallback from 0.03→0.08 to prevent
          // speaker bleed-through from triggering false barge-ins
          const bargeInThreshold = isFallbackRmsRef.current ? 0.08 : 0.35;
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
      // Extended from 300ms to 800ms — speaker resonance can linger in laptop mics
      const ECHO_GATE_MAX_MS = 800;
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

      // If user speaks while TTS is playing, trigger instantaneous barge-in!
      if (ttsPlayingRef.current && (interimTranscript.trim() || finalTranscript.trim())) {
        const candidate = (interimTranscript || finalTranscript).trim();
        if (!isEcho(candidate)) {
          stopTTS();
        }
      }

      // ── IN-FLIGHT TURN / PROCESSING GUARD ──────────────────────────────
      // Prevents trailing recognition events or room noise from preempting the active turn
      // while backend LLM is generating or TTS is synthesizing.
      if (processingRef.current && !ttsPlayingRef.current) {
        const speechProb = speechProbRef.current || 0;
        const candidate = (interimTranscript || finalTranscript).trim();
        const looksLikeEcho = isEcho(candidate);
        const bargeInThreshold = isFallbackRmsRef.current ? 0.08 : 0.38;

        // If user intentionally speaks a command during processing (multi-word phrase or explicit stop/cancel command):
        const isExplicitCommand =
          candidate.split(/\s+/).length >= 2 ||
          /^(stop|cancel|ruko|bas|wait)$/i.test(candidate);

        if (speechProb > bargeInThreshold && !looksLikeEcho && isExplicitCommand) {
          console.log(`[STT] User interrupted during processing: "${candidate.slice(0, 40)}"`);
          stopTTS();
          processingRef.current = false;
        } else {
          // Trailing recognition fragment or ambient noise while waiting for response — ignore!
          if (finalTranscript.trim() || interimTranscript.trim()) {
            console.log(`[STT] Trailing STT discarded while processing: "${candidate.slice(0, 40)}" (speechProb=${speechProb.toFixed(3)})`);
          }
          return;
        }
      }

      // ── Live Streaming Interim Visual Feedback ─────────────────────────
      if (interimTranscript) {
        if (!userSpeakingRef.current) {
          userSpeakingRef.current = true;
          onSpeechStartRef.current?.();
        }
        isSpeaking.current = true;

        // Stream interim text live to UI
        const cleanedInterim = normalizeWakeWord(interimTranscript.trim());
        const fullInterimPreview = (accumulatedFinalRef.current ? accumulatedFinalRef.current + " " : "") + cleanedInterim;
        onTranscriptRef.current?.(fullInterimPreview);

        // ── SPECULATIVE PRE-GENERATION ─────────────────────────────────
        // Send interim transcript to backend when it's substantial enough
        const interimWords = interimTranscript.trim().split(/\s+/);
        if (interimWords.length >= 4 && !dictationModeRef.current) {
          const interimNorm = interimTranscript.trim().toLowerCase();
          if (interimNorm !== lastSpecTextRef.current) {
            lastSpecTextRef.current = interimNorm;
            clearTimeout(specDebounceRef.current);
            specDebounceRef.current = setTimeout(() => {
              sendSpecRef.current?.(cleanedInterim);
            }, 300);
          }
        }
      }

      // ── Process final transcript (AGI: accumulate before sending) ────
      if (finalTranscript.trim()) {
        lastSpeechTime.current = Date.now();
        const cleaned = normalizeWakeWord(finalTranscript.trim());

        if (bestConfidence > 0 && bestConfidence < 0.4) {
          console.log("[STT] Rejected (low confidence):", cleaned);
          return;
        }

        const words = cleaned.split(/\s+/).filter((w) => w.length > 0);
        if (words.length < 1 || cleaned.length < 2) return;

        const NOISE_WORDS = new Set([
          "hmm", "hm", "uh", "um", "ah", "oh", "mm", "mhm",
          "huh", "eh", "uhh", "umm", "the", "a", "and", "is", "it",
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

        // ── HYBRID STT: Accumulate Web Speech text for visual display only ──
        // The actual transcript will come from Groq Whisper via the backend.
        // Web Speech interim/final text is kept for: (a) visual feedback,
        // (b) fallback if Whisper fails, (c) dictation mode.
        if (accumulatedFinalRef.current) {
          accumulatedFinalRef.current += " " + cleaned;
        } else {
          accumulatedFinalRef.current = cleaned;
        }
        console.log("[STT] Accumulated (visual):", accumulatedFinalRef.current);

        if (!userSpeakingRef.current) {
          userSpeakingRef.current = true;
          onSpeechStartRef.current?.();
        }
        isSpeaking.current = true;

        // ── DICTATION MODE: still uses Web Speech text directly ─────
        // (dictation needs instant typing, can't wait for Whisper)
        if (dictationModeRef.current) {
          clearTimeout(utteranceTimerRef.current);
          utteranceTimerRef.current = setTimeout(() => {
            const fullText = (accumulatedFinalRef.current || "").trim();
            accumulatedFinalRef.current = "";
            if (!fullText) return;

            const lower = fullText.toLowerCase();
            if (
              lower.includes("stop dictating") ||
              lower.includes("stop writing") ||
              lower.includes("done writing") ||
              lower.includes("band karo") ||
              lower === "stop" ||
              lower === "done"
            ) {
              onDictationStopRef.current?.();
              processingRef.current = false;
              setMicState("active");
              return;
            }
            sendDictationRef.current?.(fullText);
            processingRef.current = false;
            setMicState("dictating");
          }, UTTERANCE_WAIT_MS);
          return;
        }

        // ── NORMAL MODE: Send Web Speech text DIRECTLY (no audio chunks) ──
        // Web Speech gives us text instantly. Send it to the backend
        // as a text message — no audio recording/encoding/transfer needed.
        clearTimeout(utteranceTimerRef.current);

        // Calculate dynamic silence delay based on prosody, syntax, and sentence completeness
        // Calibrated for natural speech: average conversational pause = 600-800ms
        const calculateDynamicDelay = (text) => {
          if (!text) return 700;
          const trimmed = text.trim();
          const lower = trimmed.toLowerCase();
          const words = lower.split(/\s+/).filter(Boolean);

          // 1. Terminal punctuation (explicit sentence completion)
          if (/[.!?]$/.test(trimmed)) {
            return 350;
          }

          // 2. Fast single/two-word commands & affirmations (200ms fast path)
          const FAST_COMMANDS = new Set([
            "yes", "yeah", "yep", "no", "nope", "stop", "cancel", "pause", "resume",
            "ok", "okay", "mj", "alita", "haan", "nahi", "ruk", "ruko", "theek hai",
            "open chrome", "open notepad", "open vscode", "close this", "maximize",
            "minimize", "mute", "unmute", "next", "previous", "reload", "help",
            "screenshot", "time", "date", "weather", "what time", "play music"
          ]);
          if (words.length <= 2 && FAST_COMMANDS.has(lower)) {
            return 200;
          }

          // 3. Trailing conjunctions / connective particles / thought fillers (1200ms extension)
          const INCOMPLETE_CONNECTORS = new Set([
            // English
            "and", "to", "because", "then", "or", "so", "with", "for", "that", "but",
            "if", "when", "while", "where", "which", "um", "uh", "like", "also", "plus",
            // Hindi / Hinglish
            "ki", "aur", "toh", "lekin", "par", "ya", "kyunki", "phir", "karke", "bhi",
            "wala", "wali", "wale", "ke", "ka", "se", "mein", "pe"
          ]);
          const lastWord = words[words.length - 1];
          if (INCOMPLETE_CONNECTORS.has(lastWord)) {
            return 1200; // Give user ample time to finish thought without cutting off
          }

          // 4. Short complete sentences (3-5 words)
          if (words.length <= 5) {
            return 700;
          }

          // 5. Standard multi-word sentences
          return 900;
        };

        const dynamicDelay = calculateDynamicDelay(accumulatedFinalRef.current);
        console.log(`[STT] Turn-taking timer scheduled (${dynamicDelay}ms): "${(accumulatedFinalRef.current || "").slice(0, 40)}"`);

        // Dynamically scheduled commit timer
        utteranceTimerRef.current = setTimeout(() => {
          const fullText = (accumulatedFinalRef.current || "").trim();
          accumulatedFinalRef.current = "";
          if (!fullText) return;

          // Anti-duplicate: don't resend the same thing within 3s
          const now = Date.now();
          if (
            fullText.toLowerCase() === lastSentTextRef.current.toLowerCase() &&
            now - lastSentTimeRef.current < 3000
          ) {
            console.log("[STT] Skipped duplicate:", fullText.slice(0, 30));
            return;
          }

          lastSentTextRef.current = fullText;
          lastSentTimeRef.current = now;

          console.log("[STT] ⚡ Sending text directly:", fullText.slice(0, 60));

          // Cancel speculative queries
          clearTimeout(specDebounceRef.current);
          cancelSpecRef.current?.();
          lastSpecTextRef.current = "";

          // Send as TEXT directly (not audio!)
          userSpeakingRef.current = false;
          onUtteranceCommittedRef.current?.(fullText);
          processingRef.current = true;
          clearTimeout(processingTimeoutRef.current);
          // Emergency Fallback Watchdog: Only acts as a safety backstop if backend drops connection
          // or fails to emit lifecycle completion/audio events. Normal turns complete via onStart/onEnd
          // or is_final marker. Timeout is set to 60s to safely exceed worst-case CPU synthesis (~43s).
          processingTimeoutRef.current = setTimeout(() => {
            if (processingRef.current) {
              console.warn(
                "[STT] Emergency fallback watchdog triggered: processingRef auto-cleared after 60s (no backend completion/audio event received)"
              );
              processingRef.current = false;
              setMicState("active");
            }
          }, 60000);
          setMicState("processing");

          // Force-restart recognition session to prevent Chrome's ~36s
          // continuous mode hang. onend → _restartRecognition() fires
          // automatically, creating a fresh session in ~300ms.
          try { recognitionRef.current?.stop(); } catch (_) {}
        }, dynamicDelay);
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
  // PRIMARY: Web Speech API (instant text — no audio transfer needed)
  // FALLBACK: VAD + Groq Whisper (only if Web Speech unavailable)
  useEffect(() => {
    if (enabled) {
      const started = startWebSpeech();
      if (started) {
        setMicState("active");
        console.log("[STT] Web Speech API mode — instant text, zero latency");
      } else {
        // Fallback to VAD + Whisper if Web Speech not available
        setMicState("active");
        console.log("[STT] Fallback: Groq Whisper mode — VAD listening");
      }
    } else {
      setMicState("off");
    }
    return () => {
      clearTimeout(restartTimeoutRef.current);
      try {
        recognitionRef.current?.stop();
      } catch (_) {}
    };
  }, [enabled, startWebSpeech]);

  // ── Voice Activity Feedback (Silero VAD) ─────────────────────────────
  // Pure visual presence & speech-start trigger (orb pulse, glow effect).
  // Zero MediaRecorder interference, zero audio chunk uploading.
  useEffect(() => {
    if (!enabled) return;
    const VAD_CHECK_MS = 100;
    const SPEECH_THRESHOLD = 0.35;

    const vadPollTimer = setInterval(() => {
      const prob = speechProbRef.current || 0;
      const isSpeechNow = prob >= SPEECH_THRESHOLD;

      if (isSpeechNow && !userSpeakingRef.current && !ttsPlayingRef.current) {
        userSpeakingRef.current = true;
        onSpeechStartRef.current?.();
      }
    }, VAD_CHECK_MS);

    return () => clearInterval(vadPollTimer);
  }, [enabled, speechProbRef]);

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

  // ── Network Connectivity Detection ──────────────────────────────────────
  const connectivityDebounceRef = useRef(null);

  useEffect(() => {
    if (!enabled) return;

    const sendConnectivity = (online) => {
      window.dispatchEvent(
        new CustomEvent("Alita:connectivity_change", {
          detail: { online },
        })
      );
    };

    // Debounced connectivity handlers
    const handleOnline = () => {
      clearTimeout(connectivityDebounceRef.current);
      connectivityDebounceRef.current = setTimeout(() => {
        console.log("[Connectivity] Back ONLINE");
        sendConnectivity(true);
      }, 500);
    };

    const handleOffline = () => {
      clearTimeout(connectivityDebounceRef.current);
      connectivityDebounceRef.current = setTimeout(() => {
        console.log("[Connectivity] Gone OFFLINE");
        sendConnectivity(false);
      }, 200);
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);

    if (!navigator.onLine) {
      sendConnectivity(false);
    }

    return () => {
      clearTimeout(connectivityDebounceRef.current);
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
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
        ? "MJ is speaking · say 'stop' or press Esc"
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

  // Pure overlay mode: audio capture and STT work 100% in background without any visual DOM artifacts
  if (isOverlay) {
    return null;
  }

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
