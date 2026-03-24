/**
 * useLipReading — Visual Speech Recognition from Lip Movement
 *
 * Uses MediaPipe face mesh lip landmarks to detect speech patterns
 * even when the microphone is muted or in noisy environments.
 *
 * Algorithm:
 *   1. Track inner lip landmarks (upper/lower lip distance)
 *   2. Detect mouth open/close cycles
 *   3. Measure opening speed + duration patterns
 *   4. Classify: silence / speaking / mouthing words
 *   5. When mic is muted + lip movement detected → alert user
 *
 * Key lip landmarks (MediaPipe face mesh):
 *   Upper inner lip: 13, 14
 *   Lower inner lip: 14, 17 (corrected: 17 is chin area)
 *   Better: 13 (upper lip center), 14 (lower lip center)
 *   Lip corners: 61 (left), 291 (right)
 *
 * Dispatches: "Alita:lip_activity" CustomEvent
 */

import { useEffect, useRef, useState } from "react";
import { useMotionStore } from "../store/useMotionStore";

const ANALYSIS_INTERVAL_MS = 100; // 10Hz tracking
const SPEAKING_THRESHOLD = 0.015; // Mouth opening threshold (normalized)
const SILENCE_DURATION_MS = 800;  // Consider silent after 800ms no movement

// Face mesh lip landmark indices
const UPPER_LIP_CENTER = 13;
const LOWER_LIP_CENTER = 14;
const UPPER_LIP_TOP = 0;      // Top of upper lip
const LIP_LEFT = 61;
const LIP_RIGHT = 291;
const UPPER_OUTER = 37;
const LOWER_OUTER = 84;

// Viseme-like mouth shapes (simplified phoneme groups)
const MOUTH_SHAPES = {
  closed:     { minOpen: 0,     maxOpen: 0.008 },
  slightly:   { minOpen: 0.008, maxOpen: 0.02 },
  medium:     { minOpen: 0.02,  maxOpen: 0.04 },
  wide:       { minOpen: 0.04,  maxOpen: 0.08 },
  very_wide:  { minOpen: 0.08,  maxOpen: 1.0 },
};

function classifyMouthShape(openness) {
  for (const [shape, range] of Object.entries(MOUTH_SHAPES)) {
    if (openness >= range.minOpen && openness < range.maxOpen) {
      return shape;
    }
  }
  return "closed";
}

export function useLipReading({ enabled = false } = {}) {
  const [lipStatus, setLipStatus] = useState("silence"); // silence | speaking | mouthing
  const [mouthOpenness, setMouthOpenness] = useState(0);

  const mountedRef = useRef(true);
  const intervalRef = useRef(null);
  const opennessHistoryRef = useRef([]); // Last N openness values
  const lastSpeakingRef = useRef(0);
  const shapeSequenceRef = useRef([]); // Recent mouth shapes
  const lastDispatchRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    intervalRef.current = setInterval(() => {
      if (!mountedRef.current) return;

      const landmarks = useMotionStore.getState().faceLandmarks;
      if (!landmarks || landmarks.length < 300) return;

      const upperLip = landmarks[UPPER_LIP_CENTER];
      const lowerLip = landmarks[LOWER_LIP_CENTER];
      const lipLeft = landmarks[LIP_LEFT];
      const lipRight = landmarks[LIP_RIGHT];

      if (!upperLip || !lowerLip || !lipLeft || !lipRight) return;

      // Calculate mouth openness (vertical distance / lip width)
      const verticalOpen = Math.abs(lowerLip.y - upperLip.y);
      const lipWidth = Math.abs(lipRight.x - lipLeft.x);
      const normalizedOpenness = lipWidth > 0 ? verticalOpen / lipWidth : 0;

      setMouthOpenness(normalizedOpenness);

      // Track openness history (last 20 readings = 2 seconds)
      opennessHistoryRef.current.push(normalizedOpenness);
      if (opennessHistoryRef.current.length > 20) {
        opennessHistoryRef.current.shift();
      }

      // Track mouth shape sequence
      const shape = classifyMouthShape(normalizedOpenness);
      shapeSequenceRef.current.push(shape);
      if (shapeSequenceRef.current.length > 30) {
        shapeSequenceRef.current.shift();
      }

      // ── Detect speaking vs silence ─────────────────────────────────
      const now = Date.now();
      const history = opennessHistoryRef.current;

      // Calculate variance in openness (speaking = high variance)
      if (history.length >= 5) {
        const mean = history.reduce((s, v) => s + v, 0) / history.length;
        const variance = history.reduce((s, v) => s + (v - mean) ** 2, 0) / history.length;

        // High variance + some openness = speaking/mouthing
        const isMoving = variance > 0.00005;
        const isOpen = normalizedOpenness > SPEAKING_THRESHOLD;

        if (isMoving && isOpen) {
          lastSpeakingRef.current = now;

          const newStatus = "speaking";
          if (lipStatus !== newStatus) {
            setLipStatus(newStatus);
          }
        } else if (isMoving && !isOpen) {
          // Lips moving but not wide open — mouthing
          lastSpeakingRef.current = now;
          if (lipStatus !== "mouthing") {
            setLipStatus("mouthing");
          }
        } else if (now - lastSpeakingRef.current > SILENCE_DURATION_MS) {
          if (lipStatus !== "silence") {
            setLipStatus("silence");
          }
        }
      }

      // ── Dispatch events (debounced) ────────────────────────────────
      const currentStatus = normalizedOpenness > SPEAKING_THRESHOLD &&
        opennessHistoryRef.current.length >= 5 ? "active" : "silent";

      if (now - lastDispatchRef.current > 1000) { // Max 1 event/sec
        lastDispatchRef.current = now;

        // Detect if user is mouthing words while mic might be muted
        const shapes = shapeSequenceRef.current.slice(-15);
        const uniqueShapes = new Set(shapes).size;
        const isMouthing = uniqueShapes >= 3 && shapes.some((s) => s !== "closed");

        if (isMouthing && lipStatus === "speaking") {
          window.dispatchEvent(
            new CustomEvent("Alita:lip_activity", {
              detail: {
                status: lipStatus,
                openness: normalizedOpenness,
                isMouthing: true,
                shapeVariety: uniqueShapes,
                timestamp: now,
              },
            }),
          );
        }
      }
    }, ANALYSIS_INTERVAL_MS);

    console.log("[LipRead] ✓ Lip reading analysis active");

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [enabled, lipStatus]);

  return { lipStatus, mouthOpenness };
}
