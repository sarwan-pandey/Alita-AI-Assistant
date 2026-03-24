/**
 * useEmotionParticles — Wire Emotion State → Particle Visual Parameters
 *
 * Reads from useEmotionStore (already populated by backend SER) and maps
 * emotions to particle visualization parameters. Updates useParticleStore
 * which EarthParticleAvatar reads from.
 *
 * Emotion → Visual mapping:
 *   neutral  → calm blue, slow movement
 *   happy    → vibrant gold/green, fast swirl
 *   sad      → deep blue/purple, slow drip
 *   angry    → intense red/orange, explosive burst
 *   stressed → flickering yellow, erratic
 *   curious  → teal/cyan, expanding rings
 */

import { useEffect, useRef } from "react";
import { useEmotionStore } from "../store/useEmotionStore";
import { useParticleStore } from "../store/useParticleStore";

const EMOTION_PARTICLE_MAP = {
  neutral: {
    primaryColor: [0.3, 0.5, 1.0],    // Calm blue
    secondaryColor: [0.4, 0.6, 0.9],
    speed: 0.3,
    spread: 1.0,
    intensity: 0.5,
    turbulence: 0.1,
    particleSize: 1.0,
  },
  happy: {
    primaryColor: [1.0, 0.85, 0.2],    // Vibrant gold
    secondaryColor: [0.3, 0.9, 0.4],   // Green accent
    speed: 0.8,
    spread: 1.5,
    intensity: 0.9,
    turbulence: 0.3,
    particleSize: 1.3,
  },
  sad: {
    primaryColor: [0.2, 0.2, 0.7],     // Deep blue
    secondaryColor: [0.4, 0.2, 0.6],   // Purple
    speed: 0.15,
    spread: 0.6,
    intensity: 0.3,
    turbulence: 0.05,
    particleSize: 0.8,
  },
  angry: {
    primaryColor: [1.0, 0.2, 0.1],     // Intense red
    secondaryColor: [1.0, 0.5, 0.0],   // Orange
    speed: 1.2,
    spread: 2.0,
    intensity: 1.0,
    turbulence: 0.8,
    particleSize: 1.5,
  },
  stressed: {
    primaryColor: [0.9, 0.8, 0.1],     // Flickering yellow
    secondaryColor: [0.8, 0.3, 0.2],
    speed: 0.6,
    spread: 1.2,
    intensity: 0.7,
    turbulence: 0.6,
    particleSize: 1.1,
  },
  curious: {
    primaryColor: [0.0, 0.8, 0.8],     // Teal/cyan
    secondaryColor: [0.2, 0.6, 1.0],
    speed: 0.5,
    spread: 1.8,
    intensity: 0.6,
    turbulence: 0.2,
    particleSize: 1.2,
  },
  engaged: {
    primaryColor: [0.2, 0.8, 0.5],     // Green/emerald
    secondaryColor: [0.1, 0.6, 0.8],
    speed: 0.5,
    spread: 1.3,
    intensity: 0.7,
    turbulence: 0.15,
    particleSize: 1.1,
  },
  relaxed: {
    primaryColor: [0.3, 0.6, 0.9],     // Soft sky blue
    secondaryColor: [0.5, 0.4, 0.8],   // Lavender
    speed: 0.2,
    spread: 1.0,
    intensity: 0.4,
    turbulence: 0.05,
    particleSize: 0.9,
  },
};

// Smoothly interpolate between two param sets
function lerpParams(from, to, t) {
  const result = {};
  for (const key of Object.keys(to)) {
    if (Array.isArray(to[key])) {
      result[key] = to[key].map((v, i) => from[key][i] + (v - from[key][i]) * t);
    } else {
      result[key] = from[key] + (to[key] - from[key]) * t;
    }
  }
  return result;
}

export function useEmotionParticles({ enabled = false } = {}) {
  const emotion = useEmotionStore((s) => s.emotion);
  const setParticleParams = useParticleStore((s) => s.setParams);
  const currentParamsRef = useRef(EMOTION_PARTICLE_MAP.neutral);
  const animFrameRef = useRef(null);
  const lastEmotionRef = useRef("neutral");

  useEffect(() => {
    if (!enabled) return;

    const targetEmotion = emotion?.label || "neutral";
    if (targetEmotion === lastEmotionRef.current) return;
    lastEmotionRef.current = targetEmotion;

    const targetParams = EMOTION_PARTICLE_MAP[targetEmotion] || EMOTION_PARTICLE_MAP.neutral;
    const fromParams = { ...currentParamsRef.current };
    let t = 0;

    // Cancel any running animation
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);

    // Smooth transition over ~1 second
    function animate() {
      t = Math.min(t + 0.02, 1); // ~50 frames
      const interpolated = lerpParams(fromParams, targetParams, t);
      currentParamsRef.current = interpolated;
      setParticleParams(interpolated);

      if (t < 1) {
        animFrameRef.current = requestAnimationFrame(animate);
      } else {
        console.log(`[EmotionParticles] Transitioned to: ${targetEmotion}`);
      }
    }

    animFrameRef.current = requestAnimationFrame(animate);

    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
    };
  }, [enabled, emotion, setParticleParams]);

  // Also listen for body mood events to create combined mood
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const bodyMood = e.detail?.mood;
      if (!bodyMood) return;

      // Body mood can influence particles as a secondary signal
      const bodyParams = EMOTION_PARTICLE_MAP[bodyMood];
      if (bodyParams && bodyMood !== lastEmotionRef.current) {
        // Blend body mood at 30% weight
        const current = currentParamsRef.current;
        const blended = lerpParams(current, bodyParams, 0.3);
        setParticleParams(blended);
      }
    };

    window.addEventListener("Alita:body_mood", handler);
    console.log("[EmotionParticles] ✓ Emotion → particle mapping active");

    return () => window.removeEventListener("Alita:body_mood", handler);
  }, [enabled, setParticleParams]);

  return null;
}
