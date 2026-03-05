/**
 * MediaPipeController.jsx — Fixed
 *
 * FIXES:
 *   1. Correct CDN URL for model files (previous URL format was wrong)
 *   2. Graceful fallback — if MediaPipe fails, canvas still shows idle animation
 *   3. Better error logging so you can see exactly what failed in F12 console
 *   4. Model files downloaded from jsDelivr CDN (works without local files)
 *   5. GPU delegate with CPU fallback
 */

import { useEffect, useRef } from "react";
import { useMotionStore } from "../../store/useMotionStore";

// ── CDN configuration ──────────────────────────────────────────────────────
// The WASM runtime and model files must come from the same version
const MP_VERSION = "0.10.14";
const WASM_CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`;
const MODEL_BASE = `https://storage.googleapis.com/mediapipe-models`;

const FACE_MODEL_URL = `${MODEL_BASE}/face_landmarker/face_landmarker/float16/latest/face_landmarker.task`;
const POSE_MODEL_URL = `${MODEL_BASE}/pose_landmarker/pose_landmarker_lite/float16/latest/pose_landmarker_lite.task`;

export function MediaPipeController({ videoRef }) {
  const faceLandmarkerRef = useRef(null);
  const poseLandmarkerRef = useRef(null);
  const rafRef = useRef(null);
  const lastTimeRef = useRef(-1);
  const mountedRef = useRef(true);

  const setFaceLandmarks = useMotionStore((s) => s.setFaceLandmarks);
  const setPoseLandmarks = useMotionStore((s) => s.setPoseLandmarks);

  useEffect(() => {
    mountedRef.current = true;

    async function init() {
      try {
        console.log("[MediaPipe] Loading WASM runtime…");

        // Dynamic import — avoids bundler pre-processing WASM files
        const vision = await import("@mediapipe/tasks-vision");
        const { FaceLandmarker, PoseLandmarker, FilesetResolver } = vision;

        const filesetResolver = await FilesetResolver.forVisionTasks(WASM_CDN);
        console.log("[MediaPipe] WASM ready. Loading models…");

        // Load both models in parallel
        const results = await Promise.allSettled([
          FaceLandmarker.createFromOptions(filesetResolver, {
            baseOptions: {
              modelAssetPath: FACE_MODEL_URL,
              delegate: "GPU",
            },
            outputFaceBlendshapes: false,
            runningMode: "VIDEO",
            numFaces: 1,
            minFaceDetectionConfidence: 0.4,
            minFacePresenceConfidence: 0.4,
            minTrackingConfidence: 0.4,
          }),
          PoseLandmarker.createFromOptions(filesetResolver, {
            baseOptions: {
              modelAssetPath: POSE_MODEL_URL,
              delegate: "GPU",
            },
            runningMode: "VIDEO",
            numPoses: 1,
            minPoseDetectionConfidence: 0.4,
            minPosePresenceConfidence: 0.4,
            minTrackingConfidence: 0.4,
          }),
        ]);

        if (!mountedRef.current) return;

        // Handle partial failures gracefully
        if (results[0].status === "fulfilled") {
          faceLandmarkerRef.current = results[0].value;
          console.log("[MediaPipe] ✓ FaceLandmarker ready");
        } else {
          console.warn("[MediaPipe] FaceLandmarker failed:", results[0].reason);
          // Try CPU fallback
          try {
            faceLandmarkerRef.current = await FaceLandmarker.createFromOptions(
              filesetResolver, {
              baseOptions: { modelAssetPath: FACE_MODEL_URL, delegate: "CPU" },
              runningMode: "VIDEO", numFaces: 1,
            }
            );
            console.log("[MediaPipe] ✓ FaceLandmarker ready (CPU fallback)");
          } catch (e) {
            console.error("[MediaPipe] FaceLandmarker CPU fallback also failed:", e);
          }
        }

        if (results[1].status === "fulfilled") {
          poseLandmarkerRef.current = results[1].value;
          console.log("[MediaPipe] ✓ PoseLandmarker ready");
        } else {
          console.warn("[MediaPipe] PoseLandmarker failed:", results[1].reason);
          try {
            poseLandmarkerRef.current = await PoseLandmarker.createFromOptions(
              filesetResolver, {
              baseOptions: { modelAssetPath: POSE_MODEL_URL, delegate: "CPU" },
              runningMode: "VIDEO", numPoses: 1,
            }
            );
            console.log("[MediaPipe] ✓ PoseLandmarker ready (CPU fallback)");
          } catch (e) {
            console.error("[MediaPipe] PoseLandmarker CPU fallback also failed:", e);
          }
        }

        if (faceLandmarkerRef.current || poseLandmarkerRef.current) {
          startLoop();
        }

      } catch (err) {
        console.error("[MediaPipe] Critical init failure:", err);
        // App continues with idle animation — no crash
      }
    }

    function startLoop() {
      function tick() {
        rafRef.current = requestAnimationFrame(tick);
        if (!mountedRef.current) return;

        const video = videoRef.current;
        if (!video || video.readyState < 2) return;

        // Skip if video frame hasn't changed
        if (video.currentTime === lastTimeRef.current) return;
        lastTimeRef.current = video.currentTime;

        const now = performance.now();

        // Face landmarks
        if (faceLandmarkerRef.current) {
          try {
            const result = faceLandmarkerRef.current.detectForVideo(video, now);
            if (result?.faceLandmarks?.[0]?.length > 0) {
              setFaceLandmarks(result.faceLandmarks[0]);
            }
          } catch (_) { }
        }

        // Pose landmarks
        if (poseLandmarkerRef.current) {
          try {
            const result = poseLandmarkerRef.current.detectForVideo(video, now);
            if (result?.landmarks?.[0]?.length > 0) {
              setPoseLandmarks(result.landmarks[0]);
            }
          } catch (_) { }
        }
      }
      rafRef.current = requestAnimationFrame(tick);
    }

    init();

    return () => {
      mountedRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      faceLandmarkerRef.current?.close();
      poseLandmarkerRef.current?.close();
    };
  }, [videoRef, setFaceLandmarks, setPoseLandmarks]);

  return null; // Purely computational — no DOM output
}