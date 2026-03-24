/**
 * useSignLanguage — ASL Alphabet Recognition via MediaPipe Hands
 *
 * Recognizes static ASL alphabet letters from hand landmark positions.
 * Uses geometric features (finger extension, angles, distances) —
 * no ML model needed for basic letters.
 *
 * Supported letters: A, B, C, D, E, F, I, L, O, U, V, W, Y
 * (Static hand shapes only — dynamic letters like J, Z excluded)
 *
 * Dispatches: "Alita:sign_detected" CustomEvent
 */

import { useEffect, useRef, useCallback } from "react";

const MP_VERSION = "0.10.14";
const WASM_CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`;
const HAND_MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task";

const DETECTION_COOLDOWN_MS = 600;

// MediaPipe hand landmark indices
const WRIST = 0;
const THUMB_CMC = 1, THUMB_MCP = 2, THUMB_IP = 3, THUMB_TIP = 4;
const INDEX_MCP = 5, INDEX_PIP = 6, INDEX_DIP = 7, INDEX_TIP = 8;
const MIDDLE_MCP = 9, MIDDLE_PIP = 10, MIDDLE_DIP = 11, MIDDLE_TIP = 12;
const RING_MCP = 13, RING_PIP = 14, RING_DIP = 15, RING_TIP = 16;
const PINKY_MCP = 17, PINKY_PIP = 18, PINKY_DIP = 19, PINKY_TIP = 20;

// Helper: distance between two landmarks
function dist(lm, a, b) {
  const dx = lm[a].x - lm[b].x;
  const dy = lm[a].y - lm[b].y;
  return Math.sqrt(dx * dx + dy * dy);
}

// Helper: check if a finger is extended
// A finger is extended if tip is farther from wrist than PIP joint
function isExtended(lm, tipIdx, pipIdx) {
  return dist(lm, WRIST, tipIdx) > dist(lm, WRIST, pipIdx) * 1.1;
}

// Helper: check if finger is curled
function isCurled(lm, tipIdx, mcpIdx) {
  return dist(lm, WRIST, tipIdx) < dist(lm, WRIST, mcpIdx) * 1.05;
}

/**
 * Classify hand shape into ASL letter.
 * Returns { letter, confidence } or null.
 */
function classifyASL(landmarks) {
  if (!landmarks || landmarks.length < 21) return null;

  const lm = landmarks;

  const thumbOut = isExtended(lm, THUMB_TIP, THUMB_IP);
  const indexOut = isExtended(lm, INDEX_TIP, INDEX_PIP);
  const middleOut = isExtended(lm, MIDDLE_TIP, MIDDLE_PIP);
  const ringOut = isExtended(lm, RING_TIP, RING_PIP);
  const pinkyOut = isExtended(lm, PINKY_TIP, PINKY_PIP);

  const indexCurled = isCurled(lm, INDEX_TIP, INDEX_MCP);
  const middleCurled = isCurled(lm, MIDDLE_TIP, MIDDLE_MCP);
  const ringCurled = isCurled(lm, RING_TIP, RING_MCP);
  const pinkyCurled = isCurled(lm, PINKY_TIP, PINKY_MCP);

  // Count extended fingers
  const extendedCount = [indexOut, middleOut, ringOut, pinkyOut].filter(Boolean).length;

  // ── B: All 4 fingers extended, thumb tucked ──
  if (extendedCount === 4 && !thumbOut) {
    return { letter: "B", confidence: 0.8 };
  }

  // ── V: Index + Middle extended, others curled ──
  if (indexOut && middleOut && !ringOut && !pinkyOut) {
    // Check spread between index and middle
    const spread = dist(lm, INDEX_TIP, MIDDLE_TIP);
    if (spread > 0.04) {
      return { letter: "V", confidence: 0.85 };
    }
    // If close together, it's U
    return { letter: "U", confidence: 0.7 };
  }

  // ── W: Index + Middle + Ring extended, pinky curled ──
  if (indexOut && middleOut && ringOut && !pinkyOut) {
    return { letter: "W", confidence: 0.8 };
  }

  // ── I: Only pinky extended ──
  if (!indexOut && !middleOut && !ringOut && pinkyOut) {
    return { letter: "I", confidence: 0.8 };
  }

  // ── Y: Thumb + Pinky extended, others curled ──
  if (thumbOut && !indexOut && !middleOut && !ringOut && pinkyOut) {
    return { letter: "Y", confidence: 0.85 };
  }

  // ── L: Index + Thumb extended, forming L shape ──
  if (thumbOut && indexOut && !middleOut && !ringOut && !pinkyOut) {
    return { letter: "L", confidence: 0.8 };
  }

  // ── D: Index extended, others curled around thumb ──
  if (indexOut && middleCurled && ringCurled && pinkyCurled) {
    return { letter: "D", confidence: 0.7 };
  }

  // ── A: Fist with thumb to side ──
  if (extendedCount === 0 && thumbOut) {
    return { letter: "A", confidence: 0.7 };
  }

  // ── E: All fingers curled, thumb across ──
  if (extendedCount === 0 && !thumbOut) {
    return { letter: "E", confidence: 0.6 };
  }

  // ── F: OK shape — index+thumb touching, others extended ──
  if (middleOut && ringOut && pinkyOut) {
    const thumbIndexDist = dist(lm, THUMB_TIP, INDEX_TIP);
    if (thumbIndexDist < 0.04) {
      return { letter: "F", confidence: 0.75 };
    }
  }

  // ── C: Curved hand — partial curl ──
  if (!indexOut && !middleOut && !ringOut && !pinkyOut && thumbOut) {
    const curvature = dist(lm, THUMB_TIP, PINKY_TIP);
    if (curvature > 0.08) {
      return { letter: "C", confidence: 0.6 };
    }
  }

  // ── O: Thumb + Index forming circle ──
  const thumbIndexDist = dist(lm, THUMB_TIP, INDEX_TIP);
  if (thumbIndexDist < 0.03 && !middleOut && !ringOut && !pinkyOut) {
    return { letter: "O", confidence: 0.65 };
  }

  return null;
}

export function useSignLanguage({ enabled = false, videoRef = null } = {}) {
  const handLandmarkerRef = useRef(null);
  const rafRef = useRef(null);
  const mountedRef = useRef(true);
  const lastDetectionRef = useRef(0);
  const lastLetterRef = useRef("");
  const letterBufferRef = useRef([]);
  const initAttemptedRef = useRef(false);

  const dispatchLetter = useCallback((letter, confidence) => {
    const now = Date.now();
    if (now - lastDetectionRef.current < DETECTION_COOLDOWN_MS) return;

    // Require same letter detected 3 times in a row for stability
    letterBufferRef.current.push(letter);
    if (letterBufferRef.current.length > 5) letterBufferRef.current.shift();

    const recentLetters = letterBufferRef.current.slice(-3);
    const allSame = recentLetters.length >= 3 && recentLetters.every((l) => l === letter);

    if (!allSame) return;

    // Don't re-dispatch same letter
    if (letter === lastLetterRef.current && now - lastDetectionRef.current < 2000) return;

    lastDetectionRef.current = now;
    lastLetterRef.current = letter;

    console.log(`[SignLang] 🤟 Detected: ${letter} (confidence: ${(confidence * 100).toFixed(0)}%)`);

    window.dispatchEvent(
      new CustomEvent("Alita:sign_detected", {
        detail: { letter, confidence, timestamp: now },
      }),
    );
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled || !videoRef) {
      return () => { mountedRef.current = false; };
    }

    if (initAttemptedRef.current) return undefined;
    initAttemptedRef.current = true;

    let cancelled = false;

    async function init() {
      try {
        console.log("[SignLang] Loading MediaPipe HandLandmarker…");

        const vision = await import("@mediapipe/tasks-vision");
        const { HandLandmarker, FilesetResolver } = vision;

        if (cancelled) return;

        const fileset = await FilesetResolver.forVisionTasks(WASM_CDN);

        if (cancelled) return;

        let landmarker;
        try {
          landmarker = await HandLandmarker.createFromOptions(fileset, {
            baseOptions: {
              modelAssetPath: HAND_MODEL_URL,
              delegate: "GPU",
            },
            runningMode: "VIDEO",
            numHands: 1,
            minHandDetectionConfidence: 0.5,
            minHandPresenceConfidence: 0.5,
            minTrackingConfidence: 0.5,
          });
        } catch (_) {
          landmarker = await HandLandmarker.createFromOptions(fileset, {
            baseOptions: {
              modelAssetPath: HAND_MODEL_URL,
              delegate: "CPU",
            },
            runningMode: "VIDEO",
            numHands: 1,
          });
        }

        if (cancelled) {
          landmarker.close();
          return;
        }

        handLandmarkerRef.current = landmarker;
        console.log("[SignLang] ✓ HandLandmarker ready — show ASL signs to camera!");

        // Detection loop
        let lastTime = -1;
        function tick() {
          if (cancelled) return;
          rafRef.current = requestAnimationFrame(tick);

          const video = videoRef?.current;
          if (!video || video.readyState < 2) return;
          if (video.currentTime === lastTime) return;
          lastTime = video.currentTime;

          try {
            const result = handLandmarkerRef.current?.detect(video);
            if (result?.landmarks?.[0]) {
              const classification = classifyASL(result.landmarks[0]);
              if (classification) {
                dispatchLetter(classification.letter, classification.confidence);
              }
            }
          } catch (_) {
            // Frame processing error — skip
          }
        }
        rafRef.current = requestAnimationFrame(tick);
      } catch (err) {
        if (!cancelled) {
          console.warn("[SignLang] Init failed (non-critical):", err.message);
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
        handLandmarkerRef.current?.close();
      } catch (_) {}
      handLandmarkerRef.current = null;
    };
  }, [enabled, videoRef, dispatchLetter]);

  return null;
}
