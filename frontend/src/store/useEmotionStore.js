import { create } from "zustand";

export const useEmotionStore = create((set) => ({
  emotion: { label: "neutral", confidence: 1.0 },
  history: [],
  faceData: null,

  setEmotion: (emotion) =>
    set((state) => ({
      emotion,
      history: [...state.history.slice(-9), emotion],
    })),

  setFaceData: (data) => set({ faceData: data }),

  clearHistory: () => set({ history: [], faceData: null }),
}));