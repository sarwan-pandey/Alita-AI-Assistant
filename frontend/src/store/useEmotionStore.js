import { create } from "zustand";

export const useEmotionStore = create((set) => ({
  emotion: { label: "neutral", confidence: 1.0 },
  history: [],

  setEmotion: (emotion) =>
    set((state) => ({
      emotion,
      history: [...state.history.slice(-9), emotion],
    })),

  clearHistory: () => set({ history: [] }),
}));