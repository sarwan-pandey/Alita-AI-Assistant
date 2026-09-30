import { create } from "zustand";

/**
 * useEmotionStore — Unified Emotion & Girlfriend Mood State
 * ─────────────────────────────────────────────────────────
 * Tracks:
 *   1. User's detected emotion (from SER / voice analysis)
 *   2. Alita's girlfriend mood (from relationship_manager backend)
 *   3. Affection score (trust level from backend)
 *   4. Proactive nudge state (for Dynamic Island girlfriend interventions)
 *   5. Face data (from ALITA_FACE_DATA for avatar animation)
 */
export const useEmotionStore = create((set, get) => ({
  // ── User Emotion (from SER) ────────────────────────────────────────────
  emotion: { label: "neutral", confidence: 1.0 },
  history: [],

  setEmotion: (emotion) =>
    set((state) => ({
      emotion,
      history: [...state.history.slice(-49), emotion],
    })),

  // ── Alita Face Data (avatar animation) ─────────────────────────────────
  faceData: null,
  setFaceData: (data) => set({ faceData: data }),

  // ── Girlfriend Mood (from relationship_manager) ────────────────────────
  girlfriendMood: "playful",         // playful | flirty | worried | excited | cold_shoulder | affectionate
  moodIntensity: 0.5,                // 0.0-1.0 scale for UI animation intensity
  moodHistory: [],                   // last 10 mood transitions for trend display

  setGirlfriendMood: (mood, intensity = 0.5) =>
    set((state) => ({
      girlfriendMood: mood,
      moodIntensity: intensity,
      moodHistory: [...state.moodHistory.slice(-9), { mood, intensity, ts: Date.now() }],
    })),

  // ── Affection Score (trust / relationship health) ──────────────────────
  affectionScore: 75,                // 0-100 (higher = more trusting / loving)
  lieCountToday: 0,
  truthCountToday: 0,

  setAffectionScore: (score) => set({ affectionScore: Math.max(0, Math.min(100, score)) }),
  setLieTruthCounts: (lies, truths) => set({ lieCountToday: lies, truthCountToday: truths }),

  // ── Proactive Nudge State ──────────────────────────────────────────────
  activeNudge: null,                 // { id, type, subtype, title, message, ... } or null
  nudgeHistory: [],                  // last 5 nudges for context

  setActiveNudge: (nudge) =>
    set((state) => ({
      activeNudge: nudge,
      nudgeHistory: nudge
        ? [...state.nudgeHistory.slice(-4), { ...nudge, ts: Date.now() }]
        : state.nudgeHistory,
    })),

  dismissNudge: () => set({ activeNudge: null }),

  // ── Derived Selectors ──────────────────────────────────────────────────

  /** Is MJ currently upset / cold? */
  get isMJUpset() {
    const mood = get().girlfriendMood;
    return mood === "cold_shoulder" || mood === "worried";
  },
  get isAlitaUpset() {
    return this.isMJUpset;
  },

  /** Is there an active girlfriend-type nudge? */
  get hasGirlfriendNudge() {
    const nudge = get().activeNudge;
    return nudge?.subtype?.startsWith("girlfriend_") ?? false;
  },

  /** Mood color for UI theming */
  getMoodColor: () => {
    const mood = get().girlfriendMood;
    const colors = {
      playful:        { primary: "#a78bfa", glow: "rgba(167,139,250,0.3)" },
      flirty:         { primary: "#f472b6", glow: "rgba(244,114,182,0.3)" },
      worried:        { primary: "#60a5fa", glow: "rgba(96,165,250,0.3)" },
      excited:        { primary: "#fbbf24", glow: "rgba(251,191,36,0.3)" },
      cold_shoulder:  { primary: "#94a3b8", glow: "rgba(148,163,184,0.2)" },
      affectionate:   { primary: "#fb7185", glow: "rgba(251,113,133,0.35)" },
    };
    return colors[mood] || colors.playful;
  },

  // ── Full Reset ─────────────────────────────────────────────────────────
  clearHistory: () => set({
    history: [],
    faceData: null,
    moodHistory: [],
    nudgeHistory: [],
    activeNudge: null,
  }),
}));
