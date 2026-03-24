/**
 * useParticleStore — Zustand store for emotion-driven particle parameters
 *
 * EarthParticleAvatar reads from this store to adjust visual appearance.
 * useEmotionParticles writes to it based on detected emotions.
 */

import { create } from "zustand";

export const useParticleStore = create((set) => ({
  params: {
    primaryColor: [0.3, 0.5, 1.0],
    secondaryColor: [0.4, 0.6, 0.9],
    speed: 0.3,
    spread: 1.0,
    intensity: 0.5,
    turbulence: 0.1,
    particleSize: 1.0,
  },
  setParams: (newParams) => set({ params: newParams }),
}));
