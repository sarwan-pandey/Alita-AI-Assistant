/**
 * useHandGestures — MediaPipe Gesture Recognition
 *
 * Recognizes hand gestures via webcam and dispatches events:
 *   - Open_Palm  → pause/resume TTS
 *   - Closed_Fist → stop TTS
 *   - Thumb_Up   → confirmation
 *   - Victory    → next/skip
 *   - Pointing_Up → scroll up
 *
 * Uses @mediapipe/tasks-vision (already installed).
 * Dispatches: window CustomEvent "Alita:gesture"
 */

import { useEffect, useRef, useCallback } from "react";

const MP_VERSION = "0.10.14";
const WASM_CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`;
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/latest/gesture_recognizer.task";

// Cooldown between gesture dispatches (ms)
const GESTURE_COOLDOWN_MS = 800;

// Map MediaPipe gesture names to Alita actions
const GESTURE_ACTION_MAP = {
  Open_Palm: "pause",
  Closed_Fist: "stop",
  Thumb_Up: "confirm",
  Victory: "next",
  Pointing_Up: "scroll_up",
  Thumb_Down: "dismiss",
  ILoveYou: "love",
};

export function useHandGestures({ enabled = false, videoRef = null } = {}) {
  const recognizerRef = useRef(null);
  const rafRef = useRef(null);
  const lastGestureTimeRef = useRef(0);
  const lastGestureNameRef = useRef("");
  const mountedRef = useRef(true);
  const initAttemptedRef = useRef(false);

  const dispatchGesture = useCallback((gestureName, confidence) => {
    const now = Date.now();
    // Cooldown: don't fire same gesture repeatedly
    if (
      now - lastGestureTimeRef.current < GESTURE_COOLDOWN_MS &&
      gestureName === lastGestureNameRef.current
    ) {
      return;
    }
    lastGestureTimeRef.current = now;
    lastGestureNameRef.current = gestureName;

    const action = GESTURE_ACTION_MAP[gestureName];
    if (!action) return;

    console.log(
      `[Gesture] ${gestureName} → ${action} (confidence: ${(confidence * 100).toFixed(0)}%)`,
    );

    window.dispatchEvent(
      new CustomEvent("Alita:gesture", {
        detail: { gesture: gestureName, action, confidence },
      }),
    );

    // Handle immediate actions
    if (action === "stop" || action === "pause") {
      // Stop TTS playback
      try {
        const ttsSource = document.querySelector("audio");
        if (ttsSource) ttsSource.pause();
      } catch (_) {}
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled || !videoRef) {
      return () => {
        mountedRef.current = false;
      };
    }

    // Prevent double init
    if (initAttemptedRef.current) return undefined;
    initAttemptedRef.current = true;

    let cancelled = false;

    async function init() {
      try {
        console.log("[Gesture] Loading MediaPipe GestureRecognizer…");

        const vision = await import("@mediapipe/tasks-vision");
        const { GestureRecognizer, FilesetResolver } = vision;

        if (cancelled) return;

        const fileset = await FilesetResolver.forVisionTasks(WASM_CDN);

        if (cancelled) return;

        let recognizer;
        try {
          recognizer = await GestureRecognizer.createFromOptions(fileset, {
            baseOptions: {
              modelAssetPath: MODEL_URL,
              delegate: "GPU",
            },
            runningMode: "VIDEO",
            numHands: 1,
            minHandDetectionConfidence: 0.5,
            minHandPresenceConfidence: 0.5,
            minTrackingConfidence: 0.5,
          });
        } catch (gpuErr) {
          console.warn("[Gesture] GPU failed, trying CPU:", gpuErr.message);
          recognizer = await GestureRecognizer.createFromOptions(fileset, {
            baseOptions: {
              modelAssetPath: MODEL_URL,
              delegate: "CPU",
            },
            runningMode: "VIDEO",
            numHands: 1,
          });
        }

        if (cancelled) {
          recognizer.close();
          return;
        }

        recognizerRef.current = recognizer;
        console.log("[Gesture] ✓ GestureRecognizer initialized");

        // Start detection loop
        let lastTime = -1;
        function tick() {
          if (cancelled) return;
          rafRef.current = requestAnimationFrame(tick);

          const video = videoRef?.current;
          if (!video || video.readyState < 2) return;
          if (video.currentTime === lastTime) return;
          lastTime = video.currentTime;

          try {
            const result = recognizerRef.current?.recognize(video);
            if (result?.gestures?.[0]?.[0]) {
              const gesture = result.gestures[0][0];
              if (gesture.score > 0.6 && gesture.categoryName !== "None") {
                dispatchGesture(gesture.categoryName, gesture.score);
              }
            }
          } catch (_) {
            // Frame processing error — skip
          }
        }
        rafRef.current = requestAnimationFrame(tick);
      } catch (err) {
        if (!cancelled) {
          console.warn("[Gesture] Init failed (non-critical):", err.message);
        }
      }
    }

    init();

    return () => {
      cancelled = true;
      mountedRef.current = false;
      initAttemptedRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      try {
        recognizerRef.current?.close();
      } catch (_) {}
      recognizerRef.current = null;
    };
  }, [enabled, videoRef, dispatchGesture]);

  return null;
}
