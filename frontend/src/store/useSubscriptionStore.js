/**
 * useSubscriptionStore — Subscription Tier Management
 *
 * Manages: tier (free/premium), trial state, purchase date.
 * Persisted in localStorage.
 *
 * Rules:
 *   - New users get 7-day premium trial automatically
 *   - After trial, auto-downgrade to free
 *   - If purchased during trial, premium starts from purchase date
 *   - Geospatial (context awareness) always free
 *   - No time limit on usage in any tier
 */

import { create } from "zustand";

const STORAGE_KEY = "alita_subscription";
const TRIAL_DAYS = 7;

// ── Premium feature list ─────────────────────────────────────────────────────
export const PREMIUM_FEATURES = [
  "heart_rate",
  "fitness_coach",
  "predictive_intent",
  "cognitive_load",
  "productivity_analytics",
  "sign_language",
  "lip_reading",
  "spatial_audio",
  "object_recognition",
  "screen_reader",
  "voice_biometrics",
  "translation",
  "offline_llm",
  // ── Alita Intelligence Features ──
  "alita_emotional_ai",
  "xtts_voice_synthesis",
  "multi_llm_racing",
  "holographic_expressions",
  "geospatial_dashboard",
  "song_recognition",
];

// ── Free feature list ────────────────────────────────────────────────────────
export const FREE_FEATURES = [
  "conversation",
  "context_awareness",
  "emotion_particles",
  "hand_gestures",
  "sound_classification",
  "memory_timeline",
  "natural_command_router",
  "cognitive_orchestrator",
  "pose_mood",
];

// ── Feature display info ─────────────────────────────────────────────────────
export const FEATURE_INFO = {
  // Free
  conversation:          { icon: "💬", name: "Core Conversation",      desc: "Unlimited AI conversations" },
  context_awareness:     { icon: "🌍", name: "Geospatial Awareness",   desc: "Time, battery, network, location context" },
  emotion_particles:     { icon: "✨", name: "Emotion Particles",      desc: "Reactive particle visualizations" },
  hand_gestures:         { icon: "🤚", name: "Hand Gesture Control",   desc: "Control with hand gestures" },
  sound_classification:  { icon: "🔊", name: "Sound Classification",   desc: "Ambient sound detection" },
  memory_timeline:       { icon: "📅", name: "Memory Timeline",        desc: "Conversation history timeline" },
  natural_command_router:{ icon: "🗣️", name: "Voice Commands",         desc: "Natural language in EN/HI" },
  cognitive_orchestrator:{ icon: "🧠", name: "Smart Brain",            desc: "Intelligent feature orchestration" },
  pose_mood:             { icon: "😊", name: "Body Mood Detection",    desc: "Mood from body language" },
  // Premium
  heart_rate:            { icon: "❤️", name: "Heart Rate Monitor",     desc: "Pulse via webcam (rPPG)" },
  fitness_coach:         { icon: "🏋️", name: "Fitness Coach",          desc: "Rep counting & form tips" },
  predictive_intent:     { icon: "🔮", name: "Predictive Intent",      desc: "Predicts what you need" },
  cognitive_load:        { icon: "🧠", name: "Cognitive Load Monitor",  desc: "Mental strain detection" },
  productivity_analytics:{ icon: "📊", name: "Productivity Analytics",  desc: "Focus time & mood tracking" },
  sign_language:         { icon: "🤟", name: "Sign Language",           desc: "ASL recognition" },
  lip_reading:           { icon: "👄", name: "Lip Reading",             desc: "Visual speech detection" },
  spatial_audio:         { icon: "🌐", name: "3D Spatial Audio",        desc: "HRTF positional sound" },
  object_recognition:    { icon: "🔍", name: "Object Recognition",     desc: "Identify objects via camera" },
  screen_reader:         { icon: "📖", name: "Screen Reader/OCR",       desc: "Read text on screen" },
  voice_biometrics:      { icon: "🔒", name: "Voice Biometrics",        desc: "Voice-based authentication" },
  translation:           { icon: "🌐", name: "Live Translation",        desc: "Real-time language switching" },
  offline_llm:           { icon: "🧠", name: "Offline AI Brain",        desc: "AI without internet (WebLLM)" },
  // Alita Intelligence
  alita_emotional_ai:    { icon: "💜", name: "Alita Emotional AI",      desc: "7-layer emotional intelligence with Supporter Principle" },
  xtts_voice_synthesis:  { icon: "🎙️", name: "XTTS Voice Synthesis",    desc: "GPU-powered natural voice cloning" },
  multi_llm_racing:      { icon: "⚡", name: "Multi-LLM Racing",        desc: "Groq + NVIDIA + DeepSeek concurrent racing" },
  holographic_expressions:{ icon: "🪬", name: "Holographic Expressions", desc: "Real-time avatar face data from emotion" },
  geospatial_dashboard:  { icon: "🗺️", name: "Geospatial Dashboard",    desc: "TomTom traffic, Mapbox routes, weather" },
  song_recognition:      { icon: "🎵", name: "Song Recognition",        desc: "Identify songs playing around you" },
};

// ── Helpers ──────────────────────────────────────────────────────────────────
function loadState() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored) return JSON.parse(stored);
  } catch (_) {}
  return null;
}

function saveState(state) {
  try {
    const { tier, trialStartDate, purchaseDate } = state;
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ tier, trialStartDate, purchaseDate }));
  } catch (_) {}
}

function daysBetween(start, end) {
  return Math.floor((end - start) / (1000 * 60 * 60 * 24));
}

function computeDerived(state) {
  const now = Date.now();
  const trialStart = state.trialStartDate;
  const trialEnd = trialStart ? trialStart + TRIAL_DAYS * 24 * 60 * 60 * 1000 : 0;
  const isTrialActive = trialStart && now < trialEnd && !state.purchaseDate;
  const trialDaysRemaining = isTrialActive ? Math.max(0, Math.ceil((trialEnd - now) / (1000 * 60 * 60 * 24))) : 0;
  const isPremium = state.tier === "premium" || isTrialActive;

  return {
    isTrialActive: !!isTrialActive,
    trialDaysRemaining,
    isPremium,
    trialEndDate: trialEnd,
  };
}

// ── The Store ────────────────────────────────────────────────────────────────
export const useSubscriptionStore = create((set, get) => {
  // Load or initialize
  const saved = loadState();
  const initial = saved || {
    tier: "free",
    trialStartDate: Date.now(), // Trial starts immediately
    purchaseDate: null,
  };

  // If this is a brand new user, start trial now
  if (!saved) {
    saveState(initial);
  }

  // Auto-check: if trial expired and not purchased, ensure tier is free
  const derived = computeDerived(initial);
  if (!derived.isTrialActive && !initial.purchaseDate && initial.tier !== "free") {
    initial.tier = "free";
    saveState(initial);
  }

  return {
    // Core state
    tier: initial.tier,
    trialStartDate: initial.trialStartDate,
    purchaseDate: initial.purchaseDate,

    // Derived
    ...computeDerived(initial),

    // Check if a specific feature is accessible
    canUseFeature: (featureKey) => {
      const state = get();
      // Free features always accessible
      if (FREE_FEATURES.includes(featureKey)) return true;
      // Premium features: need premium or trial
      return state.isPremium;
    },

    // Purchase premium
    purchase: () => {
      set((s) => {
        const updated = {
          ...s,
          tier: "premium",
          purchaseDate: Date.now(),
        };
        saveState(updated);
        return { ...updated, ...computeDerived(updated) };
      });
    },

    // Cancel / downgrade
    downgrade: () => {
      set((s) => {
        const updated = {
          ...s,
          tier: "free",
          purchaseDate: null,
        };
        saveState(updated);
        return { ...updated, ...computeDerived(updated) };
      });
    },

    // Refresh derived state (call periodically to check trial expiry)
    refresh: () => {
      set((s) => {
        const derived = computeDerived(s);
        // Auto-downgrade if trial expired and not purchased
        if (!derived.isTrialActive && !s.purchaseDate && s.tier !== "free") {
          const updated = { ...s, tier: "free" };
          saveState(updated);
          return { ...updated, ...computeDerived(updated) };
        }
        return derived;
      });
    },
  };
});
