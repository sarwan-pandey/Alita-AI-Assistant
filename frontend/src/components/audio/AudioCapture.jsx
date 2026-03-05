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

const SAMPLE_RATE = 16000;

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
}) {
  const [micState, setMicState] = useState("connecting");
  const recognitionRef = useRef(null);
  const ttsPlayingRef = useRef(false);
  const ttsQueueRef = useRef([]);
  const ttsAudioCtxRef = useRef(null);
  const ttsSourceRef = useRef(null);
  const isSpeaking = useRef(false);
  const restartTimeoutRef = useRef(null);
  const lastAlitaTextRef = useRef("");   // what Alita just said (for echo rejection)
  const processingRef = useRef(false);    // prevents double-sends while backend is processing
  const lastSentTextRef = useRef("");     // last text sent to backend (anti-repeat)
  const lastSentTimeRef = useRef(0);      // timestamp of last sent text
  const ttsCooldownRef = useRef(0);       // timestamp when TTS finished (cooldown period)
  const micAnalyserRef = useRef(null);    // WebAudio AnalyserNode on mic stream
  const micStreamRef = useRef(null);      // Raw mic MediaStream for volume detection
  const micAudioCtxRef = useRef(null);    // AudioContext for mic analyser

  // ── Music detection refs ───────────────────────────────────────────────
  const musicVolumeStart = useRef(0);     // timestamp when sustained volume started
  const lastSpeechTime = useRef(Date.now()); // timestamp of last STT result
  const musicDetectedRef = useRef(false);
  const musicCheckIntervalRef = useRef(null);
  const songRecordingRef = useRef(false);  // true when recording for song recognition

  // ── Mic volume analyser (for smart barge-in) ──────────────────────────
  const setupMicAnalyser = useCallback(async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      micStreamRef.current = stream;
      const ctx = new AudioContext();
      micAudioCtxRef.current = ctx;
      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.3;
      source.connect(analyser);
      // DON'T connect to destination — we only want to measure, not play
      micAnalyserRef.current = analyser;
      console.log("[Mic] Volume analyser ready");
    } catch (err) {
      console.warn("[Mic] Could not setup volume analyser:", err);
    }
  }, []);

  const getMicVolume = useCallback(() => {
    if (!micAnalyserRef.current) return 0;
    const data = new Uint8Array(micAnalyserRef.current.frequencyBinCount);
    micAnalyserRef.current.getByteTimeDomainData(data);
    // Compute RMS volume (0 to 1 scale)
    let sum = 0;
    for (let i = 0; i < data.length; i++) {
      const val = (data[i] - 128) / 128; // Normalize to -1..1
      sum += val * val;
    }
    return Math.sqrt(sum / data.length);
  }, []);

  // ── Stop TTS immediately (barge-in) ──────────────────────────────────────
  const stopTTS = useCallback(() => {
    if (!ttsPlayingRef.current && ttsQueueRef.current.length === 0) return;
    console.log("[TTS] Barge-in — user is speaking, stopping Alita");
    try { ttsSourceRef.current?.stop(); } catch (_) { }
    ttsSourceRef.current = null;
    ttsQueueRef.current = [];
    ttsPlayingRef.current = false;
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
        console.log("[TTS] AudioContext created, state:", ttsAudioCtxRef.current.state);
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
          console.log("[TTS] Finished speaking — cooldown active");
          ttsCooldownRef.current = Date.now(); // Start cooldown
          setMicState("active");
          // Clear echo text after cooldown
          setTimeout(() => { lastAlitaTextRef.current = ""; }, 4000);
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
  }, []);

  // ── TTS event listener ──────────────────────────────────────────────────
  useEffect(() => {
    const handler = (e) => {
      const msg = e.detail;
      ttsQueueRef.current.push(msg);
      playNextTTSChunk();
    };
    window.addEventListener("Alita:tts_chunk", handler);
    return () => window.removeEventListener("Alita:tts_chunk", handler);
  }, [playNextTTSChunk]);

  // ── Track what Alita says for echo rejection ───────────────────────────
  useEffect(() => {
    // Listen for LLM tokens to build echo-rejection text
    const tokenHandler = (e) => {
      const msg = e.detail;
      if (msg?.type === "llm_token" && msg.token) {
        lastAlitaTextRef.current += msg.token;
        // Keep only last 200 chars for matching
        if (lastAlitaTextRef.current.length > 200) {
          lastAlitaTextRef.current = lastAlitaTextRef.current.slice(-200);
        }
      }
    };
    window.addEventListener("Alita:llm_token", tokenHandler);
    return () => window.removeEventListener("Alita:llm_token", tokenHandler);
  }, []);

  // ── Restart speech recognition helper ───────────────────────────────────
  const _restartRecognition = useCallback(() => {
    if (!enabled) return;
    clearTimeout(restartTimeoutRef.current);
    restartTimeoutRef.current = setTimeout(() => {
      try {
        recognitionRef.current?.start();
      } catch (e) {
        // Already running — fine
      }
    }, 300);
  }, [enabled]);

  // ── Echo rejection: is this text just Alita's own voice? ───────────────
  const isEcho = useCallback((transcript) => {
    if (!lastAlitaTextRef.current) return false;
    const alitaText = lastAlitaTextRef.current.toLowerCase();
    const userText = transcript.toLowerCase();

    // Check if what the mic heard is a substring of what Alita said
    // (the mic may pick up fragments of TTS output)
    const words = userText.split(/\s+/);
    if (words.length <= 3) {
      // Short phrases: check if ALL words appear in Alita's text
      const matchCount = words.filter(w => alitaText.includes(w)).length;
      if (matchCount >= words.length * 0.7) {
        return true;
      }
    } else {
      // Longer phrases: check if most of the text overlaps
      const matchCount = words.filter(w => alitaText.includes(w)).length;
      if (matchCount >= words.length * 0.5) {
        return true;
      }
    }
    return false;
  }, []);

  // ── Web Speech API Setup ────────────────────────────────────────────────
  const startWebSpeech = useCallback(() => {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn("[STT] Web Speech API not supported");
      return false;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = sttLanguage;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      if (!ttsPlayingRef.current) setMicState("active");
      console.log("[STT] Listening...");
    };

    recognition.onresult = (event) => {
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

      // ── Smart barge-in during TTS (volume-based) ─────────────────────
      // On laptops, the mic picks up Alita's TTS from speakers.
      // We use mic volume to distinguish: user speaking directly into mic
      // is LOUDER than echo from speakers. Only allow barge-in if volume
      // exceeds threshold (0.06 = user is clearly speaking).
      const BARGE_IN_VOLUME = 0.06;
      const ttsCooldownMs = 2000;
      const inCooldown = (Date.now() - ttsCooldownRef.current) < ttsCooldownMs;

      if (ttsPlayingRef.current) {
        const vol = getMicVolume();
        if (vol > BARGE_IN_VOLUME && (interimTranscript.length > 5 || finalTranscript.trim())) {
          // User is actually speaking loudly — barge-in!
          console.log("[BARGE-IN] User speaking (vol=%.3f) — stopping Alita", vol);
          stopTTS();
          ttsCooldownRef.current = 0; // Skip cooldown since user is actively speaking
          // Fall through to process the speech below
        } else {
          // Low volume = just speaker echo — discard
          return;
        }
      } else if (inCooldown) {
        // Short cooldown after TTS ends to let mic settle
        const vol = getMicVolume();
        if (vol <= BARGE_IN_VOLUME) {
          return; // Still just echo residue
        }
        // Volume is high — user is speaking, allow through
        console.log("[STT] Cooldown override — user speaking (vol=%.3f)", vol);
      }

      // Show interim text (visual feedback)
      if (interimTranscript && !ttsPlayingRef.current) {
        onSpeechStart?.();
        isSpeaking.current = true;
      }

      // ── Process final transcript ────────────────────────────────────
      if (finalTranscript.trim()) {
        lastSpeechTime.current = Date.now(); // Update for music detection
        const cleaned = finalTranscript.trim();

        // Skip if still processing previous utterance
        if (processingRef.current) {
          console.log("[STT] Skipped (still processing):", cleaned);
          return;
        }

        // Confidence threshold
        if (bestConfidence > 0 && bestConfidence < 0.4) {
          console.log("[STT] Rejected (low confidence):", cleaned);
          return;
        }

        // Minimum length
        const words = cleaned.split(/\s+/).filter(w => w.length > 0);
        if (words.length < 1 || cleaned.length < 2) return;

        // Noise word filter
        const NOISE_WORDS = new Set([
          "hmm", "hm", "uh", "um", "ah", "oh", "mm", "mhm",
          "huh", "eh", "uhh", "umm", "the", "a", "and", "is", "it",
        ]);
        if (words.length <= 2 && words.every(w => NOISE_WORDS.has(w.toLowerCase()))) {
          console.log("[STT] Rejected (noise):", cleaned);
          return;
        }

        // Echo rejection for final transcript too
        if (isEcho(cleaned)) {
          console.log("[ECHO] Rejected final:", cleaned.slice(0, 40));
          return;
        }

        // Anti-repeat: reject if same/similar text was sent recently
        const now = Date.now();
        const timeSinceLast = now - lastSentTimeRef.current;
        if (timeSinceLast < 10000 && lastSentTextRef.current) {
          const prevWords = lastSentTextRef.current.toLowerCase().split(/\s+/);
          const curWords = cleaned.toLowerCase().split(/\s+/);
          const overlap = curWords.filter(w => prevWords.includes(w)).length;
          const similarity = overlap / Math.max(curWords.length, 1);
          if (similarity > 0.7) {
            console.log("[STT] Rejected (anti-repeat, %.0f%% similar):", similarity * 100, cleaned.slice(0, 40));
            return;
          }
        }

        console.log("[STT] ✓ Accepted:", cleaned);
        isSpeaking.current = false;
        processingRef.current = true;

        // Clear echo text since user is now speaking
        lastAlitaTextRef.current = "";

        // ── DICTATION MODE: route to app instead of chat ────────────
        if (dictationMode) {
          // Check for stop commands
          const lower = cleaned.toLowerCase();
          if (lower.includes("stop dictating") || lower.includes("stop writing") ||
            lower.includes("done writing") || lower.includes("band karo") ||
            lower === "stop" || lower === "done") {
            console.log("[Dictation] Stop command detected");
            onDictationStop?.();
            processingRef.current = false;
            setMicState("active");
            return;
          }
          // Send to backend for typing into app
          console.log("[Dictation] Typing:", cleaned);
          sendDictation?.(cleaned);
          processingRef.current = false;
          setMicState("dictating");
          return;
        }

        // ── NORMAL MODE: send to chat ──────────────────────────────
        onTranscript?.(cleaned);
        onUtteranceCommitted?.(cleaned);
        setMicState("processing");
        lastSentTextRef.current = cleaned;
        lastSentTimeRef.current = Date.now();

        // Allow next utterance after backend has time to respond
        setTimeout(() => {
          processingRef.current = false;
          if (!ttsPlayingRef.current) {
            setMicState("active");
          }
        }, 3000);
      }
    };

    recognition.onerror = (event) => {
      if (event.error === "no-speech" || event.error === "aborted") return;
      console.error("[STT] Error:", event.error);
      if (event.error === "not-allowed") setMicState("error");
    };

    recognition.onend = () => {
      // ALWAYS restart — mic should never stop
      if (enabled) {
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
  }, [enabled, onAudioChunk, onSpeechStart, onUtteranceCommitted, onTranscript, _restartRecognition, isEcho, stopTTS, sttLanguage]);

  // ── Auto-start when enabled ─────────────────────────────────────────────
  useEffect(() => {
    if (enabled) {
      setupMicAnalyser(); // Start volume detection
      const success = startWebSpeech();
      if (!success) setMicState("error");
    }
    return () => {
      clearTimeout(restartTimeoutRef.current);
      try { recognitionRef.current?.stop(); } catch (_) { }
      // Cleanup mic analyser
      try { micStreamRef.current?.getTracks().forEach(t => t.stop()); } catch (_) { }
      try {
        if (micAudioCtxRef.current?.state !== 'closed') {
          micAudioCtxRef.current?.close();
        }
      } catch (_) { }
    };
  }, [enabled, startWebSpeech, setupMicAnalyser]);

  // ── Music / ambient audio detection ─────────────────────────────────────
  useEffect(() => {
    if (!enabled) return;
    const MUSIC_VOLUME_THRESHOLD = 0.04;  // Sustained ambient audio level
    const MUSIC_DURATION_MS = 3000;       // Must persist 3s without speech

    musicCheckIntervalRef.current = setInterval(() => {
      const vol = getMicVolume();
      const now = Date.now();
      const timeSinceSpeech = now - lastSpeechTime.current;

      if (vol > MUSIC_VOLUME_THRESHOLD && timeSinceSpeech > MUSIC_DURATION_MS && !ttsPlayingRef.current) {
        // Sustained audio with no speech for 3s = music
        if (!musicVolumeStart.current) {
          musicVolumeStart.current = now;
        } else if (now - musicVolumeStart.current > MUSIC_DURATION_MS && !musicDetectedRef.current) {
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
    console.log("[STT] Language changed to:", sttLanguage, "— restarting recognition");
    try {
      recognitionRef.current.stop();
    } catch (_) { }
    // Short delay then restart (onend handler will auto-restart)
    clearTimeout(restartTimeoutRef.current);
    restartTimeoutRef.current = setTimeout(() => {
      startWebSpeech();
    }, 500);
  }, [sttLanguage]); // intentionally only depends on sttLanguage

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
        dedicatedStream = await navigator.mediaDevices.getUserMedia({ audio: true });

        // Pick a MIME type the browser actually supports
        const mimeType = MediaRecorder.isTypeSupported("audio/webm;codecs=opus")
          ? "audio/webm;codecs=opus"
          : MediaRecorder.isTypeSupported("audio/webm")
            ? "audio/webm"
            : ""; // let browser pick default

        const mediaRecorder = new MediaRecorder(dedicatedStream, mimeType ? { mimeType } : undefined);
        const chunks = [];

        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) chunks.push(e.data);
        };

        mediaRecorder.onstop = async () => {
          songRecordingRef.current = false;
          setMicState("active");
          // Release the dedicated stream
          dedicatedStream?.getTracks().forEach(t => t.stop());

          const blob = new Blob(chunks, { type: "audio/webm" });

          // Convert to base64
          const reader = new FileReader();
          reader.onload = () => {
            const base64 = reader.result.split(",")[1]; // strip data:audio/webm;base64,
            console.log("[Song] Sending %.1f KB audio for recognition", (base64.length * 3 / 4) / 1024);
            // Dispatch event for App.jsx to send via WebSocket
            window.dispatchEvent(new CustomEvent("Alita:song_audio_ready", {
              detail: { audio_b64: base64 },
            }));
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

    window.addEventListener("Alita:start_song_recognition", handleSongRecognition);
    return () => window.removeEventListener("Alita:start_song_recognition", handleSongRecognition);
  }, [onAudioChunk]);

  // ── Mic status indicator ────────────────────────────────────────────────
  return (
    <div
      onClick={() => {
        if (ttsPlayingRef.current) stopTTS();
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
        pointerEvents: ttsPlayingRef.current ? "auto" : "none",
        cursor: ttsPlayingRef.current ? "pointer" : "default",
        fontFamily: "'DM Mono', monospace",
        fontSize: "0.62rem",
        letterSpacing: "0.15em",
        textTransform: "uppercase",
        color: micState === "active" ? "rgba(163,230,53,0.8)"
          : micState === "speaking" ? "rgba(192,132,252,0.6)"
            : micState === "dictating" ? "rgba(251,191,36,0.8)"
              : micState === "processing" ? "rgba(251,191,36,0.7)"
                : micState === "error" ? "rgba(239,68,68,0.8)"
                  : "rgba(255,255,255,0.2)",
        transition: "color 600ms ease",
      }}
    >
      <div style={{
        width: "6px",
        height: "6px",
        borderRadius: "50%",
        background: micState === "active" ? "#a3e635"
          : micState === "speaking" ? "#c084fc"
            : micState === "dictating" ? "#fbbf24"
              : micState === "processing" ? "#fbbf24"
                : micState === "error" ? "#ef4444"
                  : "rgba(255,255,255,0.2)",
        boxShadow: micState === "active" ? "0 0 8px #a3e635"
          : micState === "speaking" ? "0 0 8px #c084fc"
            : micState === "dictating" ? "0 0 8px #fbbf24"
              : micState === "processing" ? "0 0 8px #fbbf24"
                : "none",
        animation: micState === "active" ? "blink 2s ease-in-out infinite"
          : micState === "speaking" ? "pulse 1.5s ease-in-out infinite"
            : "none",
        transition: "background 600ms ease, box-shadow 600ms ease",
      }} />
      {micState === "active" ? "listening"
        : micState === "speaking" ? "alita is speaking · just talk to interrupt"
          : micState === "dictating" ? `dictating into ${dictationMode?.app || "app"}`
            : micState === "processing" ? "thinking…"
              : micState === "identifying" ? "🎵 listening to the song…"
                : micState === "error" ? "mic blocked"
                  : "connecting…"}
    </div>
  );
}
