/**
 * useNaturalCommandRouter — Multi-language Intent Router
 *
 * Listens to user speech transcripts and maps natural language
 * to feature activations. Supports English, Hindi, and Hinglish.
 *
 * No rigid commands — understands conversational variations:
 *   "check my pulse"   → heart rate
 *   "dil ki dhadkan"   → heart rate
 *   "heartbeat batao"  → heart rate
 *   "haan"             → confirm/accept suggestion
 *   "nahi"             → reject suggestion
 *   "start exercise"   → fitness coach
 *   "squat shuru karo" → fitness coach (squats)
 *
 * Dispatches the appropriate feature events based on intent.
 */

import { useEffect, useRef, useCallback } from "react";
import { useSubscriptionStore, PREMIUM_FEATURES, FEATURE_INFO } from "../store/useSubscriptionStore";

// ─────────────────────────────────────────────────────────────────────────────
// §1  INTENT DEFINITIONS (multi-language keyword groups)
// ─────────────────────────────────────────────────────────────────────────────

const INTENTS = {
  // ── Affirmative / Confirmation ─────────────────────────────────────
  confirm: {
    phrases: [
      // English
      "yes", "yeah", "sure", "okay", "ok", "go ahead", "do it", "start",
      "yep", "yup", "alright", "let's go", "lets go", "please", "confirm",
      "of course", "absolutely", "definitely", "agreed",
      // Hindi
      "haan", "ha", "ji", "ji haan", "theek hai", "theek", "thik hai",
      "sahi hai", "bilkul", "zaroor", "chalo", "kar do", "shuru karo",
      "ho jayega", "ban jayega",
      // Hinglish
      "yes bhai", "haan bhai", "ok done", "chal theek hai",
    ],
    action: "confirm",
  },

  // ── Negative / Rejection ───────────────────────────────────────────
  reject: {
    phrases: [
      "no", "nope", "nah", "not now", "cancel", "stop", "never mind",
      "don't", "dont", "skip",
      "nahi", "na", "mat karo", "nahi chahiye", "rehne do", "band karo",
      "mat", "nahi bhai", "chhodo", "jane do", "ruko",
    ],
    action: "reject",
  },

  // ── Heart Rate ─────────────────────────────────────────────────────
  heart_rate: {
    phrases: [
      "heart rate", "heartbeat", "pulse", "check my pulse", "my heart",
      "heart beat", "bpm", "check pulse", "measure pulse", "vital signs",
      "dil ki dhadkan", "dhadkan", "dil", "pulse check karo",
      "meri heartbeat", "heart rate batao", "pulse batao", "dil ki rate",
    ],
    action: "start_heart_rate",
    premium: true,
  },

  // ── Fitness / Exercise ─────────────────────────────────────────────
  fitness_squats: {
    phrases: [
      "start squats", "do squats", "squat exercise", "squats",
      "count my squats", "track squats",
      "squat karo", "squat shuru karo", "squat count karo",
    ],
    action: "start_exercise",
    params: { exercise: "squats" },
    premium: true,
  },

  fitness_pushups: {
    phrases: [
      "start pushups", "do pushups", "push ups", "pushup",
      "count pushups", "track pushups",
      "pushup karo", "pushup shuru karo",
    ],
    action: "start_exercise",
    params: { exercise: "pushups" },
    premium: true,
  },

  fitness_jumping_jacks: {
    phrases: [
      "jumping jacks", "start jumping jacks", "do jumping jacks",
      "jumping jack karo", "jumping jack shuru karo",
    ],
    action: "start_exercise",
    params: { exercise: "jumping_jacks" },
    premium: true,
  },

  fitness_lunges: {
    phrases: [
      "start lunges", "do lunges", "lunges", "lunge exercise",
      "lunge karo", "lunge shuru karo",
    ],
    action: "start_exercise",
    params: { exercise: "lunges" },
    premium: true,
  },

  fitness_stop: {
    phrases: [
      "stop exercise", "stop counting", "done exercising", "finish workout",
      "exercise band karo", "exercise roko", "ho gaya", "bas",
      "enough", "stop workout",
    ],
    action: "stop_exercise",
    premium: true,
  },

  fitness_general: {
    phrases: [
      "start exercise", "workout", "exercise", "let's exercise",
      "exercise karo", "workout karo", "exercise shuru karo",
      "kasrat karo", "vyayam karo",
    ],
    action: "start_exercise",
    params: { exercise: "squats" },
    premium: true,
  },

  // ── Object Recognition ─────────────────────────────────────────────
  object_recognition: {
    phrases: [
      "what do you see", "what is this", "identify this", "what's this",
      "look at this", "tell me what you see", "recognize this",
      "what am I holding", "what's in front of me", "scan this",
      "yeh kya hai", "kya dikh raha hai", "yeh batao kya hai",
      "dekho yeh kya hai", "pehchano", "identify karo",
      "samne kya hai", "kya hai yeh",
    ],
    action: "identify_object",
    premium: true,
  },

  // ── Screen Reader ──────────────────────────────────────────────────
  screen_reader: {
    phrases: [
      "read my screen", "what's on my screen", "read screen",
      "screen padho", "screen kya hai", "screen batao",
      "screen par kya hai", "screen read karo",
    ],
    action: "read_screen",
    premium: true,
  },

  // ── Sign Language ──────────────────────────────────────────────────
  sign_language: {
    phrases: [
      "sign language", "sign mode", "read my signs", "hand signs",
      "sign language mode", "turn on sign language",
      "sign language chalu karo", "sign padho", "haath ke ishare",
    ],
    action: "enable_sign_language",
    premium: true,
  },

  // ── Voice Enrollment ───────────────────────────────────────────────
  voice_enroll: {
    phrases: [
      "enroll my voice", "remember my voice", "voice enrollment",
      "register my voice", "save my voice", "learn my voice",
      "meri awaaz yaad karo", "awaaz register karo", "voice save karo",
    ],
    action: "enroll_voice",
    premium: true,
  },

  // ── Translation ────────────────────────────────────────────────────
  translate_hindi: {
    phrases: [
      "speak in hindi", "switch to hindi", "hindi mein bolo",
      "hindi mode", "talk in hindi",
      "hindi mein bat karo", "hindi chalu karo",
    ],
    action: "switch_language",
    params: { lang: "hi" },
    premium: true,
  },

  translate_english: {
    phrases: [
      "speak in english", "switch to english", "english mode",
      "english mein bolo", "english chalu karo",
    ],
    action: "switch_language",
    params: { lang: "en" },
    premium: true,
  },

  // ── Memory Timeline ────────────────────────────────────────────────
  memory_timeline: {
    phrases: [
      "show timeline", "memory timeline", "show my history",
      "conversation history", "what did we talk about",
      "timeline dikhao", "history dikhao", "kya baat hui thi",
      "purani baat", "pehle kya hua tha",
    ],
    action: "show_timeline",
  },

  // ── Offline Mode ───────────────────────────────────────────────────
  offline_mode: {
    phrases: [
      "offline mode", "go offline", "work offline", "no internet mode",
      "offline chalo", "bina internet", "offline karo",
    ],
    action: "enable_offline",
    premium: true,
  },

  // ── Pricing / Upgrade ──────────────────────────────────────────────
  show_pricing: {
    phrases: [
      "show pricing", "pricing page", "upgrade", "premium",
      "go premium", "buy premium", "purchase",
      "premium dikhao", "upgrade karo", "premium lena hai",
      "kitna paisa", "price kya hai", "plan dikhao",
    ],
    action: "show_pricing",
  },

  // ── Productivity / Analytics ───────────────────────────────────────
  productivity: {
    phrases: [
      "show productivity", "my stats", "how productive am I",
      "show analytics", "today's stats", "focus time",
      "productivity dikhao", "stats dikhao", "kitna kaam kiya",
      "aaj ka record",
    ],
    action: "show_productivity",
  },

  // ── Breathing / Calm ───────────────────────────────────────────────
  breathing: {
    phrases: [
      "help me relax", "breathing exercise", "calm me down",
      "I'm stressed", "deep breath", "relax karo",
      "tension ho raha hai", "stress ho raha hai", "shant karo",
      "saans ki exercise", "relax", "calm",
    ],
    action: "breathing_exercise",
  },

  // ── Help / What can you do ─────────────────────────────────────────
  help: {
    phrases: [
      "what can you do", "help", "list features", "your abilities",
      "tum kya kar sakte ho", "features batao", "kya kya kar sakte ho",
      "madad karo", "help karo", "abilities batao",
    ],
    action: "show_help",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// §2  FUZZY PHRASE MATCHING
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Fuzzy match: checks if the user's text contains any of the intent phrases.
 * Uses substring matching + word overlap scoring, not exact match.
 * Returns { matched: bool, score: 0-1, phrase: string }
 */
function matchIntent(userText, phrases) {
  const lower = userText.toLowerCase().trim();
  if (!lower) return { matched: false, score: 0, phrase: "" };

  const userWords = new Set(lower.split(/\s+/));

  let bestScore = 0;
  let bestPhrase = "";

  for (const phrase of phrases) {
    const phraseLower = phrase.toLowerCase();

    // Exact substring match (strongest signal)
    if (lower.includes(phraseLower)) {
      const score = phraseLower.length / Math.max(lower.length, 1);
      const adjusted = Math.max(0.7, Math.min(1.0, score + 0.3));
      if (adjusted > bestScore) {
        bestScore = adjusted;
        bestPhrase = phrase;
      }
      continue;
    }

    // Word overlap matching (for reordered/partial phrases)
    const phraseWords = phraseLower.split(/\s+/);
    const overlap = phraseWords.filter((w) => userWords.has(w)).length;
    const overlapRatio = overlap / phraseWords.length;

    if (overlapRatio >= 0.6 && overlap >= 1) {
      const score = overlapRatio * 0.7; // Cap at 0.7 for partial match
      if (score > bestScore) {
        bestScore = score;
        bestPhrase = phrase;
      }
    }
  }

  return {
    matched: bestScore >= 0.5,
    score: bestScore,
    phrase: bestPhrase,
  };
}

// ─────────────────────────────────────────────────────────────────────────────
// §3  THE HOOK
// ─────────────────────────────────────────────────────────────────────────────

export function useNaturalCommandRouter({ enabled = false } = {}) {
  const mountedRef = useRef(true);
  const lastCommandRef = useRef(0);
  const pendingSuggestionRef = useRef(null); // Track what suggestion is waiting for yes/no

  // Handle a detected intent
  const executeIntent = useCallback((intentKey, intent, matchScore) => {
    const now = Date.now();
    if (now - lastCommandRef.current < 2000) return; // 2s cooldown
    lastCommandRef.current = now;

    const action = intent.action;
    const params = intent.params || {};

    // ── Premium gating: if feature is premium and user is free, suggest upgrade
    if (intent.premium) {
      const { isPremium } = useSubscriptionStore.getState();
      if (!isPremium) {
        console.log(
          `[Router] 👑 Premium feature "${intentKey}" requested by free user → suggesting upgrade`,
        );

        // Build premium feature list message
        const featureList = PREMIUM_FEATURES.slice(0, 5)
          .map((k) => FEATURE_INFO[k] ? `${FEATURE_INFO[k].icon} ${FEATURE_INFO[k].name}` : k)
          .join(", ");

        window.dispatchEvent(
          new CustomEvent("Alita:orchestrator_action", {
            detail: {
              actionType: "suggest",
              feature: "premium_upgrade",
              message:
                `👑 "${FEATURE_INFO[intentKey]?.name || intentKey}" is a Premium feature! ` +
                `Upgrade to unlock: ${featureList} and more!`,
              confidence: 0.95,
            },
          }),
        );

        // Also open pricing page
        window.dispatchEvent(new CustomEvent("Alita:show_pricing"));
        return;
      }
    }

    console.log(
      `[Router] 🗣️ Intent: "${intentKey}" → ${action} (score: ${(matchScore * 100).toFixed(0)}%)`,
    );

    switch (action) {
      case "confirm":
        // Accept the most recent orchestrator suggestion
        window.dispatchEvent(
          new CustomEvent("Alita:feature_feedback", {
            detail: { feature: pendingSuggestionRef.current, accepted: true },
          }),
        );
        if (pendingSuggestionRef.current === "fitness_coach") {
          window.dispatchEvent(
            new CustomEvent("Alita:start_exercise", {
              detail: { exercise: "squats" },
            }),
          );
        }
        pendingSuggestionRef.current = null;
        break;

      case "reject":
        window.dispatchEvent(
          new CustomEvent("Alita:feature_feedback", {
            detail: { feature: pendingSuggestionRef.current, accepted: false },
          }),
        );
        pendingSuggestionRef.current = null;
        break;

      case "start_exercise":
        window.dispatchEvent(
          new CustomEvent("Alita:start_exercise", { detail: params }),
        );
        break;

      case "stop_exercise":
        window.dispatchEvent(new CustomEvent("Alita:stop_exercise"));
        break;

      case "identify_object":
        window.dispatchEvent(new CustomEvent("Alita:identify_object"));
        break;

      case "read_screen":
        window.dispatchEvent(new CustomEvent("Alita:read_screen"));
        break;

      case "enroll_voice":
        window.dispatchEvent(new CustomEvent("Alita:enroll_voice"));
        break;

      case "enable_sign_language":
        window.dispatchEvent(
          new CustomEvent("Alita:orchestrator_action", {
            detail: { actionType: "auto_activate", feature: "sign_language" },
          }),
        );
        break;

      case "switch_language":
        window.dispatchEvent(
          new CustomEvent("Alita:switch_language", { detail: params }),
        );
        break;

      case "show_timeline":
        window.dispatchEvent(new CustomEvent("Alita:show_timeline"));
        break;

      case "enable_offline":
        window.dispatchEvent(new CustomEvent("Alita:offline_query", {
          detail: { prompt: "Hello, are you ready?", requestId: "init" },
        }));
        break;

      case "show_productivity":
        window.dispatchEvent(new CustomEvent("Alita:show_productivity"));
        break;

      case "show_pricing":
        window.dispatchEvent(new CustomEvent("Alita:show_pricing"));
        break;

      case "breathing_exercise":
        window.dispatchEvent(
          new CustomEvent("Alita:orchestrator_action", {
            detail: {
              actionType: "auto_activate",
              feature: "breathing_guide",
              message: "🌬️ Let's breathe together. In... and out...",
            },
          }),
        );
        break;

      case "start_heart_rate":
        // Heart rate is always running — just acknowledge
        window.dispatchEvent(
          new CustomEvent("Alita:orchestrator_action", {
            detail: {
              actionType: "auto_activate",
              feature: "heart_rate",
              message: "❤️ Monitoring your heart rate. Please stay still for 10 seconds.",
            },
          }),
        );
        break;

      case "show_help":
        window.dispatchEvent(
          new CustomEvent("Alita:orchestrator_action", {
            detail: {
              actionType: "suggest",
              feature: "help",
              message: "I can: track heart rate ❤️, count exercises 🏋️, read signs 🤟, " +
                "read your screen 📖, detect objects 🔍, translate languages 🌐, " +
                "monitor your focus 🧠, predict what you need 🔮, and much more!",
            },
          }),
        );
        break;

      default:
        break;
    }
  }, []);

  // Track pending suggestions from orchestrator
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { actionType, feature } = e.detail || {};
      if (actionType === "suggest" && feature) {
        pendingSuggestionRef.current = feature;
      }
    };

    window.addEventListener("Alita:orchestrator_action", handler);
    return () => window.removeEventListener("Alita:orchestrator_action", handler);
  }, [enabled]);

  // Main transcript listener
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    const handler = (e) => {
      if (!mountedRef.current) return;

      const text = e.detail?.text || e.detail?.transcript || e.detail;
      if (!text || typeof text !== "string") return;
      if (text.length < 2 || text.length > 200) return; // Skip noise

      // Try to match against all intents
      let bestIntent = null;
      let bestKey = "";
      let bestScore = 0;

      for (const [key, intent] of Object.entries(INTENTS)) {
        const match = matchIntent(text, intent.phrases);
        if (match.matched && match.score > bestScore) {
          bestScore = match.score;
          bestIntent = intent;
          bestKey = key;
        }
      }

      if (bestIntent && bestScore >= 0.5) {
        executeIntent(bestKey, bestIntent, bestScore);
      }
    };

    window.addEventListener("Alita:user_transcript", handler);
    console.log("[Router] ✓ Natural language command router active (EN/HI/Hinglish)");

    return () => {
      mountedRef.current = false;
      window.removeEventListener("Alita:user_transcript", handler);
    };
  }, [enabled, executeIntent]);

  return null;
}
