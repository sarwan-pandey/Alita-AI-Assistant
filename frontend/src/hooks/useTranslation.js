/**
 * useTranslation — Real-time Language Detection & Translation
 *
 * Detects the language of user speech (Hindi vs English) by checking
 * Unicode ranges. When mismatch with current TTS language is detected,
 * notifies the system to translate.
 *
 * Dispatches: "Alita:translation" CustomEvent
 * Listens:   user transcript events
 */

import { useEffect, useRef, useCallback } from "react";

// Hindi/Devanagari Unicode range: U+0900 to U+097F
const DEVANAGARI_RE = /[\u0900-\u097F]/;
const ARABIC_RE = /[\u0600-\u06FF]/;
const CJK_RE = /[\u4E00-\u9FFF\u3040-\u309F\u30A0-\u30FF]/;

// Common Hindi words in Latin script (Hinglish)
const HINGLISH_WORDS = new Set([
  "kya", "hai", "nahi", "mein", "ka", "ki", "ke", "ko", "se", "par",
  "aur", "bhi", "yeh", "woh", "kuch", "bahut", "accha", "theek",
  "kaise", "kaisa", "kahan", "kab", "kyun", "haan", "na", "tum",
  "aap", "hum", "tera", "mera", "uska", "unka", "sab", "log",
  "bhai", "didi", "bolo", "batao", "sunao", "dekho", "chalo",
  "arre", "abhi", "phir", "lekin", "isliye", "waise", "matlab",
]);

function detectLanguage(text) {
  if (!text) return "unknown";

  // Check for non-Latin scripts first
  if (DEVANAGARI_RE.test(text)) return "hi";
  if (ARABIC_RE.test(text)) return "ar";
  if (CJK_RE.test(text)) return "zh";

  // Check for Hinglish (Hindi in Latin script)
  const words = text.toLowerCase().split(/\s+/);
  const hinglishCount = words.filter((w) => HINGLISH_WORDS.has(w)).length;
  const hinglishRatio = hinglishCount / Math.max(words.length, 1);

  if (hinglishRatio > 0.3) return "hi-latin"; // Hinglish
  return "en";
}

export function useTranslation({
  enabled = false,
  currentLang = "en",
  sendMessage = null,
} = {}) {
  const mountedRef = useRef(true);
  const currentLangRef = useRef(currentLang);
  const sendMessageRef = useRef(sendMessage);
  const lastDetectedRef = useRef(null);
  const cooldownRef = useRef(0);

  useEffect(() => {
    currentLangRef.current = currentLang;
    sendMessageRef.current = sendMessage;
  });

  const handleTranscript = useCallback((e) => {
    const text = e.detail?.text || e.detail;
    if (!text || typeof text !== "string") return;

    const now = Date.now();
    if (now - cooldownRef.current < 5000) return; // 5s cooldown

    const detected = detectLanguage(text);
    if (detected === "unknown") return;

    lastDetectedRef.current = detected;

    // Check for language mismatch
    const currentTTSLang = currentLangRef.current;
    const isHindi = detected === "hi" || detected === "hi-latin";
    const isTTSHindi = currentTTSLang === "hi";

    if ((isHindi && !isTTSHindi) || (!isHindi && isTTSHindi)) {
      cooldownRef.current = now;

      const fromLang = isHindi ? "Hindi" : "English";
      const toLang = isTTSHindi ? "Hindi" : "English";

      console.log(
        `[Translation] Detected ${fromLang} speech — TTS is ${toLang}. Suggesting translation.`,
      );

      window.dispatchEvent(
        new CustomEvent("Alita:translation", {
          detail: {
            detectedLang: detected,
            ttsLang: currentTTSLang,
            text,
            suggestion: `User is speaking ${fromLang} but TTS is set to ${toLang}`,
          },
        }),
      );

      // Optionally send to backend for language-aware response
      if (sendMessageRef.current) {
        sendMessageRef.current({
          type: "language_detected",
          detected_lang: detected,
          current_tts_lang: currentTTSLang,
        });
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    // Listen for STT transcript events
    const onTranscript = (e) => {
      if (!mountedRef.current) return;
      const msg = e.detail;
      if (msg?.type === "llm_token" && msg?.token) return; // Skip LLM tokens
      handleTranscript(e);
    };

    window.addEventListener("Alita:user_transcript", onTranscript);
    console.log("[Translation] ✓ Language detection active");

    return () => {
      mountedRef.current = false;
      window.removeEventListener("Alita:user_transcript", onTranscript);
    };
  }, [enabled, handleTranscript]);

  return { detectLanguage };
}
