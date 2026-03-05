import { create } from "zustand";

export const useMotionStore = create((set) => ({
  faceLandmarks: null,
  poseLandmarks: null,
  blendShapes: null,

  setFaceLandmarks: (faceLandmarks) => set({ faceLandmarks }),
  setPoseLandmarks: (poseLandmarks) => set({ poseLandmarks }),
  setBlendShapes: (blendShapes) => set({ blendShapes }),
  clearLandmarks: () => set({ faceLandmarks: null, poseLandmarks: null }),
}));