/**
 * useFitnessCoach — Real-time Exercise Tracking via MediaPipe Pose
 *
 * Uses existing pose landmarks to count exercise repetitions and
 * provide form guidance. Tracks exercise history in localStorage.
 *
 * Supported exercises:
 *   - Squats:        hip-knee angle cycle detection
 *   - Pushups:       shoulder-elbow-wrist angle cycle
 *   - Jumping Jacks: arm spread + leg spread cycle
 *   - Lunges:        knee angle asymmetry cycle
 *
 * Dispatches: "Alita:fitness_update" CustomEvent
 * Listens:   "Alita:start_exercise" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { useMotionStore } from "../store/useMotionStore";

const STORAGE_KEY = "alita_fitness_history";
const ANALYSIS_INTERVAL_MS = 100; // 10Hz for smooth counting

// MediaPipe Pose landmark indices
const LEFT_SHOULDER = 11, RIGHT_SHOULDER = 12;
const LEFT_ELBOW = 13, RIGHT_ELBOW = 14;
const LEFT_WRIST = 15, RIGHT_WRIST = 16;
const LEFT_HIP = 23, RIGHT_HIP = 24;
const LEFT_KNEE = 25, RIGHT_KNEE = 26;
const LEFT_ANKLE = 27, RIGHT_ANKLE = 28;

// Calculate angle between three points (in degrees)
function calcAngle(lm, a, b, c) {
  const ba = { x: lm[a].x - lm[b].x, y: lm[a].y - lm[b].y };
  const bc = { x: lm[c].x - lm[b].x, y: lm[c].y - lm[b].y };

  const dot = ba.x * bc.x + ba.y * bc.y;
  const magBA = Math.sqrt(ba.x * ba.x + ba.y * ba.y);
  const magBC = Math.sqrt(bc.x * bc.x + bc.y * bc.y);

  if (magBA === 0 || magBC === 0) return 0;

  const cosAngle = Math.max(-1, Math.min(1, dot / (magBA * magBC)));
  return Math.acos(cosAngle) * (180 / Math.PI);
}

// Distance between two landmarks
function dist2D(lm, a, b) {
  const dx = lm[a].x - lm[b].x;
  const dy = lm[a].y - lm[b].y;
  return Math.sqrt(dx * dx + dy * dy);
}

const EXERCISE_ANALYZERS = {
  squats: {
    name: "Squats",
    emoji: "🏋️",
    analyze(lm) {
      // Track knee angle (hip-knee-ankle)
      const leftAngle = calcAngle(lm, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE);
      const rightAngle = calcAngle(lm, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE);
      const angle = (leftAngle + rightAngle) / 2;

      return {
        angle,
        isDown: angle < 110,   // Below parallel
        isUp: angle > 160,     // Standing
        formTip: angle < 70
          ? "⚠️ Too deep — keep knees safe!"
          : angle > 100 && angle < 130
            ? "✅ Great depth!"
            : null,
      };
    },
  },

  pushups: {
    name: "Push-ups",
    emoji: "💪",
    analyze(lm) {
      // Track elbow angle (shoulder-elbow-wrist)
      const leftAngle = calcAngle(lm, LEFT_SHOULDER, LEFT_ELBOW, LEFT_WRIST);
      const rightAngle = calcAngle(lm, RIGHT_SHOULDER, RIGHT_ELBOW, RIGHT_WRIST);
      const angle = (leftAngle + rightAngle) / 2;

      return {
        angle,
        isDown: angle < 100,   // Arms bent
        isUp: angle > 155,     // Arms extended
        formTip: angle < 60
          ? "⚠️ Go lower — chest to ground!"
          : null,
      };
    },
  },

  jumping_jacks: {
    name: "Jumping Jacks",
    emoji: "⭐",
    analyze(lm) {
      // Track arm spread and leg spread
      const armSpread = dist2D(lm, LEFT_WRIST, RIGHT_WRIST);
      const legSpread = dist2D(lm, LEFT_ANKLE, RIGHT_ANKLE);

      return {
        angle: armSpread * 100 + legSpread * 100, // Combined metric
        isDown: armSpread < 0.3 && legSpread < 0.15,  // Arms down, legs together
        isUp: armSpread > 0.5 && legSpread > 0.2,     // Arms up, legs apart
        formTip: null,
      };
    },
  },

  lunges: {
    name: "Lunges",
    emoji: "🦵",
    analyze(lm) {
      // Track front knee angle
      const leftAngle = calcAngle(lm, LEFT_HIP, LEFT_KNEE, LEFT_ANKLE);
      const rightAngle = calcAngle(lm, RIGHT_HIP, RIGHT_KNEE, RIGHT_ANKLE);

      // The leg with smaller angle is the front leg
      const frontAngle = Math.min(leftAngle, rightAngle);

      return {
        angle: frontAngle,
        isDown: frontAngle < 110,
        isUp: frontAngle > 155,
        formTip: frontAngle < 80
          ? "⚠️ Don't let your knee go past your toes!"
          : frontAngle > 85 && frontAngle < 100
            ? "✅ Perfect 90° angle!"
            : null,
      };
    },
  },
};

function loadHistory() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch (_) {
    return [];
  }
}

function saveHistory(history) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-100)));
  } catch (_) {}
}

export function useFitnessCoach({ enabled = false } = {}) {
  const [activeExercise, setActiveExercise] = useState(null);
  const [repCount, setRepCount] = useState(0);
  const [lastFormTip, setLastFormTip] = useState(null);
  const [history, setHistory] = useState(() => loadHistory());

  const poseLandmarks = useMotionStore((s) => s.poseLandmarks);
  const mountedRef = useRef(true);
  const intervalRef = useRef(null);
  const phaseRef = useRef("up"); // "up" or "down" — for rep counting
  const repCountRef = useRef(0);
  const exerciseStartRef = useRef(null);

  // Start an exercise session
  const startExercise = useCallback((exerciseType) => {
    const analyzer = EXERCISE_ANALYZERS[exerciseType];
    if (!analyzer) {
      console.warn("[Fitness] Unknown exercise:", exerciseType);
      return;
    }

    console.log(`[Fitness] ${analyzer.emoji} Starting ${analyzer.name}!`);
    setActiveExercise(exerciseType);
    setRepCount(0);
    setLastFormTip(null);
    repCountRef.current = 0;
    phaseRef.current = "up";
    exerciseStartRef.current = Date.now();

    window.dispatchEvent(
      new CustomEvent("Alita:fitness_update", {
        detail: {
          type: "exercise_started",
          exercise: exerciseType,
          name: analyzer.name,
          emoji: analyzer.emoji,
        },
      }),
    );
  }, []);

  // Stop exercise and save to history
  const stopExercise = useCallback(() => {
    if (!activeExercise) return;

    const analyzer = EXERCISE_ANALYZERS[activeExercise];
    const duration = Date.now() - (exerciseStartRef.current || Date.now());
    const entry = {
      exercise: activeExercise,
      name: analyzer?.name,
      reps: repCountRef.current,
      duration: Math.round(duration / 1000),
      timestamp: Date.now(),
    };

    const newHistory = [...history, entry];
    setHistory(newHistory);
    saveHistory(newHistory);

    console.log(
      `[Fitness] ✅ ${analyzer?.name} complete: ${repCountRef.current} reps in ${entry.duration}s`,
    );

    window.dispatchEvent(
      new CustomEvent("Alita:fitness_update", {
        detail: {
          type: "exercise_completed",
          ...entry,
        },
      }),
    );

    setActiveExercise(null);
    setRepCount(0);
    setLastFormTip(null);
  }, [activeExercise, history]);

  // Real-time analysis loop
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled || !activeExercise || !poseLandmarks) {
      return () => { mountedRef.current = false; };
    }

    const analyzer = EXERCISE_ANALYZERS[activeExercise];
    if (!analyzer) return undefined;

    intervalRef.current = setInterval(() => {
      if (!mountedRef.current || !poseLandmarks || poseLandmarks.length < 29) return;

      const result = analyzer.analyze(poseLandmarks);

      // Rep counting: detect up→down→up cycle
      if (phaseRef.current === "up" && result.isDown) {
        phaseRef.current = "down";
      } else if (phaseRef.current === "down" && result.isUp) {
        phaseRef.current = "up";
        repCountRef.current++;
        setRepCount(repCountRef.current);

        console.log(`[Fitness] ${analyzer.emoji} Rep #${repCountRef.current}!`);

        window.dispatchEvent(
          new CustomEvent("Alita:fitness_update", {
            detail: {
              type: "rep_counted",
              exercise: activeExercise,
              reps: repCountRef.current,
            },
          }),
        );
      }

      // Form tips
      if (result.formTip) {
        setLastFormTip(result.formTip);
      }
    }, ANALYSIS_INTERVAL_MS);

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [enabled, activeExercise, poseLandmarks]);

  // Listen for start commands
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { exercise } = e.detail || {};
      if (exercise) {
        if (activeExercise) stopExercise();
        startExercise(exercise);
      }
    };

    const stopHandler = () => stopExercise();

    window.addEventListener("Alita:start_exercise", handler);
    window.addEventListener("Alita:stop_exercise", stopHandler);

    console.log("[Fitness] ✓ Coach ready — say 'start squats' to begin!");

    return () => {
      window.removeEventListener("Alita:start_exercise", handler);
      window.removeEventListener("Alita:stop_exercise", stopHandler);
    };
  }, [enabled, activeExercise, startExercise, stopExercise]);

  return {
    activeExercise,
    repCount,
    lastFormTip,
    history,
    startExercise,
    stopExercise,
    availableExercises: Object.keys(EXERCISE_ANALYZERS),
  };
}
