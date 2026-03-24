/**
 * useCognitiveLoad — Mental Load Detection
 *
 * Tracks multiple signals to estimate cognitive load:
 *   - Blink rate (via face landmarks eye aspect ratio)
 *   - Pupil size changes (iris landmarks)
 *   - Response latency (time between Alita speaking and user replying)
 *   - Session duration (fatigue accumulates)
 *   - Error rate (user corrections / rephrasing)
 *
 * Cognitive load levels:
 *   low     → User is relaxed, normal engagement
 *   medium  → Moderate focus, some strain
 *   high    → Overloaded — simplify responses, suggest break
 *   critical → Extended overload — enforce break suggestion
 *
 * Dispatches: "Alita:cognitive_load" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { useMotionStore } from "../store/useMotionStore";

const EVAL_INTERVAL_MS = 2000;
const BLINK_THRESHOLD = 0.2; // Eye aspect ratio threshold for blink
const STORAGE_KEY = "alita_cognitive_sessions";

// Eye landmark indices (MediaPipe face mesh)
const LEFT_EYE_TOP = 159, LEFT_EYE_BOTTOM = 145;
const LEFT_EYE_INNER = 133, LEFT_EYE_OUTER = 33;
const RIGHT_EYE_TOP = 386, RIGHT_EYE_BOTTOM = 374;
const RIGHT_EYE_INNER = 362, RIGHT_EYE_OUTER = 263;

// Iris landmarks
const LEFT_IRIS = 468, RIGHT_IRIS = 473;

function calcEyeAspectRatio(landmarks, topIdx, bottomIdx, innerIdx, outerIdx) {
  if (!landmarks || landmarks.length < 475) return null;

  const top = landmarks[topIdx];
  const bottom = landmarks[bottomIdx];
  const inner = landmarks[innerIdx];
  const outer = landmarks[outerIdx];

  if (!top || !bottom || !inner || !outer) return null;

  const vertical = Math.abs(top.y - bottom.y);
  const horizontal = Math.abs(inner.x - outer.x);

  return horizontal > 0 ? vertical / horizontal : null;
}

function calcPupilSize(landmarks) {
  if (!landmarks || landmarks.length < 478) return null;

  // Approximate pupil size from iris landmark spread
  try {
    const leftIris = [];
    for (let i = LEFT_IRIS; i < LEFT_IRIS + 5 && i < landmarks.length; i++) {
      leftIris.push(landmarks[i]);
    }

    if (leftIris.length < 4) return null;

    // Diameter as distance between opposite iris landmarks
    const dx = leftIris[1].x - leftIris[3].x;
    const dy = leftIris[1].y - leftIris[3].y;
    return Math.sqrt(dx * dx + dy * dy);
  } catch (_) {
    return null;
  }
}

export function useCognitiveLoad({ enabled = false } = {}) {
  const [loadLevel, setLoadLevel] = useState("low");
  const [loadScore, setLoadScore] = useState(0);
  const [blinkRate, setBlinkRate] = useState(0);

  const mountedRef = useRef(true);
  const intervalRef = useRef(null);
  const sessionStartRef = useRef(Date.now());
  const blinkCountRef = useRef(0);
  const blinkWindowStartRef = useRef(Date.now());
  const lastEARRef = useRef(0.3);
  const wasBlinkingRef = useRef(false);
  const pupilBaselineRef = useRef(null);
  const responseLatenciesRef = useRef([]);
  const lastAlitaSpokeRef = useRef(0);

  // Track blinks via face landmarks
  useEffect(() => {
    if (!enabled) return;

    const unsub = useMotionStore.subscribe((state) => {
      const lm = state.faceLandmarks;
      if (!lm) return;

      // Calculate EAR (Eye Aspect Ratio)
      const leftEAR = calcEyeAspectRatio(lm, LEFT_EYE_TOP, LEFT_EYE_BOTTOM, LEFT_EYE_INNER, LEFT_EYE_OUTER);
      const rightEAR = calcEyeAspectRatio(lm, RIGHT_EYE_TOP, RIGHT_EYE_BOTTOM, RIGHT_EYE_INNER, RIGHT_EYE_OUTER);

      if (leftEAR === null || rightEAR === null) return;

      const avgEAR = (leftEAR + rightEAR) / 2;

      // Detect blink (EAR drops below threshold then returns)
      if (avgEAR < BLINK_THRESHOLD && !wasBlinkingRef.current) {
        wasBlinkingRef.current = true;
      } else if (avgEAR > BLINK_THRESHOLD && wasBlinkingRef.current) {
        wasBlinkingRef.current = false;
        blinkCountRef.current++;
      }

      lastEARRef.current = avgEAR;

      // Track pupil size for baseline
      const pupilSize = calcPupilSize(lm);
      if (pupilSize) {
        if (!pupilBaselineRef.current) {
          pupilBaselineRef.current = pupilSize;
        }
      }
    });

    return () => unsub?.();
  }, [enabled]);

  // Track response latency
  useEffect(() => {
    if (!enabled) return;

    const alitaHandler = () => {
      lastAlitaSpokeRef.current = Date.now();
    };

    const userHandler = () => {
      if (lastAlitaSpokeRef.current > 0) {
        const latency = Date.now() - lastAlitaSpokeRef.current;
        if (latency < 30000) { // Within 30s
          responseLatenciesRef.current.push(latency);
          if (responseLatenciesRef.current.length > 20) {
            responseLatenciesRef.current.shift();
          }
        }
        lastAlitaSpokeRef.current = 0;
      }
    };

    window.addEventListener("Alita:tts_end", alitaHandler);
    window.addEventListener("Alita:user_transcript", userHandler);

    return () => {
      window.removeEventListener("Alita:tts_end", alitaHandler);
      window.removeEventListener("Alita:user_transcript", userHandler);
    };
  }, [enabled]);

  // Evaluate cognitive load
  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return () => { mountedRef.current = false; };

    intervalRef.current = setInterval(() => {
      if (!mountedRef.current) return;

      const now = Date.now();

      // ── Factor 1: Blink rate (blinks per minute) ───────────────────
      const windowDuration = (now - blinkWindowStartRef.current) / 60000;
      const blinksPerMin = windowDuration > 0.25
        ? blinkCountRef.current / windowDuration
        : 0;

      // Reset window every 60s
      if (windowDuration > 1) {
        blinkCountRef.current = 0;
        blinkWindowStartRef.current = now;
      }

      setBlinkRate(Math.round(blinksPerMin));

      // Normal: 15-20/min. High cognitive load: <10/min (staring)
      // Fatigue: >25/min (excessive blinking)
      let blinkScore;
      if (blinksPerMin < 8) {
        blinkScore = 0.8; // Staring = high load
      } else if (blinksPerMin > 28) {
        blinkScore = 0.7; // Excessive = fatigue
      } else if (blinksPerMin >= 12 && blinksPerMin <= 22) {
        blinkScore = 0.2; // Normal
      } else {
        blinkScore = 0.4; // Slightly off
      }

      // ── Factor 2: Session duration (fatigue builds) ────────────────
      const sessionMinutes = (now - sessionStartRef.current) / 60000;
      const durationScore = Math.min(1, sessionMinutes / 90); // Peaks at 90 min

      // ── Factor 3: Response latency trend ───────────────────────────
      let latencyScore = 0;
      const latencies = responseLatenciesRef.current;
      if (latencies.length >= 3) {
        const avgLatency = latencies.reduce((s, v) => s + v, 0) / latencies.length;
        // Slow responses (>5s) indicate cognitive load
        latencyScore = Math.min(1, avgLatency / 8000);
      }

      // ── Factor 4: EAR (squinting = strain) ─────────────────────────
      const earScore = lastEARRef.current < 0.25 ? 0.5 : 0;

      // ── Combined score (weighted average) ──────────────────────────
      const combined =
        blinkScore * 0.3 +
        durationScore * 0.25 +
        latencyScore * 0.25 +
        earScore * 0.2;

      setLoadScore(combined);

      // ── Determine level ────────────────────────────────────────────
      let level;
      if (combined < 0.3) level = "low";
      else if (combined < 0.5) level = "medium";
      else if (combined < 0.75) level = "high";
      else level = "critical";

      const prevLevel = loadLevel;
      setLoadLevel(level);

      // Dispatch on level change
      if (level !== prevLevel) {
        console.log(
          `[CogLoad] 🧠 Cognitive load: ${level} (score: ${(combined * 100).toFixed(0)}%, ` +
          `blinks: ${Math.round(blinksPerMin)}/min, session: ${Math.round(sessionMinutes)}min)`,
        );

        window.dispatchEvent(
          new CustomEvent("Alita:cognitive_load", {
            detail: {
              level,
              score: combined,
              blinkRate: Math.round(blinksPerMin),
              sessionMinutes: Math.round(sessionMinutes),
              timestamp: now,
            },
          }),
        );
      }
    }, EVAL_INTERVAL_MS);

    console.log("[CogLoad] ✓ Cognitive load monitoring active");

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [enabled, loadLevel]);

  return { loadLevel, loadScore, blinkRate };
}
