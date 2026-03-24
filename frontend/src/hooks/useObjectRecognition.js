/**
 * useObjectRecognition — MediaPipe Image Classification
 *
 * On command ("what do you see"), captures the current webcam frame
 * and classifies objects using MediaPipe Image Classifier.
 *
 * Dispatches: "Alita:object_detected" CustomEvent
 * Listens:   "Alita:identify_object" CustomEvent (trigger)
 */

import { useEffect, useRef, useCallback } from "react";

const MP_VERSION = "0.10.14";
const WASM_CDN = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MP_VERSION}/wasm`;
const MODEL_URL =
  "https://storage.googleapis.com/mediapipe-models/image_classifier/efficientnet_lite0/float32/latest/efficientnet_lite0.tflite";

export function useObjectRecognition({ enabled = false, videoRef = null } = {}) {
  const classifierRef = useRef(null);
  const initPromiseRef = useRef(null);
  const mountedRef = useRef(true);

  // Lazy-initialize classifier on first request
  const ensureClassifier = useCallback(async () => {
    if (classifierRef.current) return classifierRef.current;
    if (initPromiseRef.current) return initPromiseRef.current;

    initPromiseRef.current = (async () => {
      try {
        console.log("[ObjectRecog] Loading MediaPipe ImageClassifier…");

        const vision = await import("@mediapipe/tasks-vision");
        const { ImageClassifier, FilesetResolver } = vision;

        const fileset = await FilesetResolver.forVisionTasks(WASM_CDN);

        let classifier;
        try {
          classifier = await ImageClassifier.createFromOptions(fileset, {
            baseOptions: {
              modelAssetPath: MODEL_URL,
              delegate: "GPU",
            },
            runningMode: "IMAGE",
            maxResults: 5,
            scoreThreshold: 0.15,
          });
        } catch (_) {
          classifier = await ImageClassifier.createFromOptions(fileset, {
            baseOptions: {
              modelAssetPath: MODEL_URL,
              delegate: "CPU",
            },
            runningMode: "IMAGE",
            maxResults: 5,
            scoreThreshold: 0.15,
          });
        }

        classifierRef.current = classifier;
        console.log("[ObjectRecog] ✓ ImageClassifier ready");
        return classifier;
      } catch (err) {
        console.warn("[ObjectRecog] Init failed:", err.message);
        initPromiseRef.current = null;
        return null;
      }
    })();

    return initPromiseRef.current;
  }, []);

  // Classify current webcam frame
  const classifyFrame = useCallback(async () => {
    const video = videoRef?.current;
    if (!video || video.readyState < 2) {
      console.warn("[ObjectRecog] No video available");
      return;
    }

    const classifier = await ensureClassifier();
    if (!classifier) return;

    try {
      // Capture frame to canvas for classification
      const canvas = document.createElement("canvas");
      canvas.width = video.videoWidth || 640;
      canvas.height = video.videoHeight || 480;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);

      // Create ImageData for the classifier
      const result = classifier.classify(canvas);

      if (result?.classifications?.[0]?.categories?.length > 0) {
        const objects = result.classifications[0].categories.map((c) => ({
          label: c.categoryName,
          confidence: c.score,
        }));

        console.log("[ObjectRecog] Detected:", objects.map((o) =>
          `${o.label} (${(o.confidence * 100).toFixed(0)}%)`).join(", "));

        window.dispatchEvent(
          new CustomEvent("Alita:object_detected", {
            detail: { objects, timestamp: Date.now() },
          }),
        );
      } else {
        window.dispatchEvent(
          new CustomEvent("Alita:object_detected", {
            detail: { objects: [], timestamp: Date.now() },
          }),
        );
      }
    } catch (err) {
      console.warn("[ObjectRecog] Classification error:", err.message);
    }
  }, [videoRef, ensureClassifier]);

  // Listen for trigger event
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    const handler = () => {
      classifyFrame();
    };

    // Triggered by voice command or button
    window.addEventListener("Alita:identify_object", handler);
    console.log("[ObjectRecog] ✓ Listening for identify commands");

    return () => {
      mountedRef.current = false;
      window.removeEventListener("Alita:identify_object", handler);
      try {
        classifierRef.current?.close();
      } catch (_) {}
      classifierRef.current = null;
      initPromiseRef.current = null;
    };
  }, [enabled, classifyFrame]);

  return { classifyFrame };
}
