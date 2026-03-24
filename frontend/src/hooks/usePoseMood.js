/**
 * usePoseMood — Body Language → Mood Detection
 *
 * Reads pose landmarks from useMotionStore (populated by MediaPipeController)
 * and infers mood from body language:
 *   - Upright + shoulders aligned → engaged/confident
 *   - Slouching (shoulder drop) → tired/bored
 *   - Head tilt → curious/interested
 *   - Shoulders raised → stressed/tense
 *   - Leaning forward → attentive
 *   - Leaning back → relaxed/disengaged
 *
 * Dispatches: "Alita:body_mood" CustomEvent
 */

import { useEffect, useRef } from "react";
import { useMotionStore } from "../store/useMotionStore";

const ANALYSIS_INTERVAL_MS = 2000; // Analyze every 2s
const SMOOTHING_SAMPLES = 5; // Average over last 5 readings

// MediaPipe Pose landmark indices
const NOSE = 0;
const LEFT_SHOULDER = 11;
const RIGHT_SHOULDER = 12;
const LEFT_EAR = 7;
const RIGHT_EAR = 8;
const LEFT_HIP = 23;
const RIGHT_HIP = 24;

function analyzePose(landmarks) {
  if (!landmarks || landmarks.length < 25) return null;

  const nose = landmarks[NOSE];
  const lShoulder = landmarks[LEFT_SHOULDER];
  const rShoulder = landmarks[RIGHT_SHOULDER];
  const lEar = landmarks[LEFT_EAR];
  const rEar = landmarks[RIGHT_EAR];
  const lHip = landmarks[LEFT_HIP];
  const rHip = landmarks[RIGHT_HIP];

  // Calculate metrics
  const shoulderMidY = (lShoulder.y + rShoulder.y) / 2;
  const hipMidY = (lHip.y + rHip.y) / 2;
  const shoulderMidX = (lShoulder.x + rShoulder.x) / 2;

  // 1. Posture: distance between shoulders and hips (normalized)
  const torsoLength = Math.abs(hipMidY - shoulderMidY);

  // 2. Shoulder asymmetry (tilt)
  const shoulderTilt = Math.abs(lShoulder.y - rShoulder.y);

  // 3. Head tilt (ear asymmetry)
  const headTilt = Math.abs(lEar.y - rEar.y);

  // 4. Forward lean (nose x relative to shoulder midpoint)
  const forwardLean = nose.y - shoulderMidY; // Negative = leaning forward

  // 5. Head height relative to shoulders
  const headDrop = nose.y - shoulderMidY;

  // Determine mood
  let mood = "neutral";
  let confidence = 0.5;

  if (torsoLength < 0.15) {
    // Very compressed torso = slouching
    mood = "tired";
    confidence = 0.7;
  } else if (shoulderTilt > 0.04) {
    // Uneven shoulders = stressed/uncomfortable
    mood = "stressed";
    confidence = 0.6 + Math.min(shoulderTilt * 5, 0.3);
  } else if (headTilt > 0.03) {
    // Head tilted = curious/thinking
    mood = "curious";
    confidence = 0.6 + Math.min(headTilt * 5, 0.3);
  } else if (headDrop < -0.05) {
    // Head well above shoulders and leaning forward = attentive
    mood = "engaged";
    confidence = 0.75;
  } else if (forwardLean > 0.08) {
    // Leaning back = relaxed
    mood = "relaxed";
    confidence = 0.6;
  } else if (torsoLength > 0.25) {
    // Tall upright posture = confident
    mood = "confident";
    confidence = 0.7;
  }

  return { mood, confidence, metrics: { torsoLength, shoulderTilt, headTilt, forwardLean } };
}

export function usePoseMood({ enabled = false } = {}) {
  const poseLandmarks = useMotionStore((s) => s.poseLandmarks);
  const mountedRef = useRef(true);
  const historyRef = useRef([]);
  const lastMoodRef = useRef("neutral");
  const intervalRef = useRef(null);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    intervalRef.current = setInterval(() => {
      if (!mountedRef.current || !poseLandmarks) return;

      const analysis = analyzePose(poseLandmarks);
      if (!analysis) return;

      // Smooth: keep last N samples and pick most common mood
      historyRef.current.push(analysis.mood);
      if (historyRef.current.length > SMOOTHING_SAMPLES) {
        historyRef.current.shift();
      }

      // Mode (most frequent) of recent readings
      const counts = {};
      for (const m of historyRef.current) {
        counts[m] = (counts[m] || 0) + 1;
      }
      const smoothedMood = Object.entries(counts).sort((a, b) => b[1] - a[1])[0][0];

      // Only dispatch if mood changed
      if (smoothedMood !== lastMoodRef.current) {
        lastMoodRef.current = smoothedMood;

        console.log(
          `[PoseMood] Body language: ${smoothedMood} (confidence: ${(analysis.confidence * 100).toFixed(0)}%)`,
        );

        window.dispatchEvent(
          new CustomEvent("Alita:body_mood", {
            detail: {
              mood: smoothedMood,
              confidence: analysis.confidence,
              metrics: analysis.metrics,
            },
          }),
        );
      }
    }, ANALYSIS_INTERVAL_MS);

    console.log("[PoseMood] ✓ Body language analysis active");

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [enabled, poseLandmarks]);

  return null;
}
