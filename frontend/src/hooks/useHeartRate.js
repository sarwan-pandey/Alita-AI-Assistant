/**
 * useHeartRate — Remote Photoplethysmography (rPPG)
 *
 * Estimates heart rate from webcam by detecting micro-color-changes
 * in facial skin caused by blood flow. Uses MediaPipe face landmarks
 * to isolate the forehead region.
 *
 * Algorithm:
 *   1. Extract forehead ROI using face landmarks
 *   2. Average green channel intensity (hemoglobin absorbs green light)
 *   3. Collect 10 seconds of samples (~300 at 30fps)
 *   4. Apply bandpass filter (40-180 BPM → 0.67-3.0 Hz)
 *   5. Find dominant frequency via autocorrelation
 *   6. Convert to BPM
 *
 * Dispatches: "Alita:heart_rate" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { useMotionStore } from "../store/useMotionStore";

const SAMPLE_WINDOW_SEC = 10;   // Collect 10s of data
const TARGET_FPS = 30;          // Camera frame rate
const BUFFER_SIZE = SAMPLE_WINDOW_SEC * TARGET_FPS; // ~300 samples
const UPDATE_INTERVAL_MS = 3000; // Update BPM every 3s
const MIN_BPM = 40;
const MAX_BPM = 180;

// Forehead landmark indices (MediaPipe face mesh)
// Using points around the forehead center
const FOREHEAD_LANDMARKS = [10, 67, 69, 104, 108, 151, 297, 299, 333, 337];

/**
 * Simple bandpass filter using moving average subtraction.
 * Removes DC (breathing, movement) and high-freq noise.
 */
function bandpassFilter(signal, lowCutSamples, highCutSamples) {
  const n = signal.length;
  if (n < lowCutSamples) return signal;

  // High-pass: subtract slow moving average (removes DC + breathing)
  const highPassed = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    let count = 0;
    for (let j = Math.max(0, i - lowCutSamples); j <= Math.min(n - 1, i + lowCutSamples); j++) {
      sum += signal[j];
      count++;
    }
    highPassed[i] = signal[i] - sum / count;
  }

  // Low-pass: smooth with shorter window (removes noise)
  const result = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    let sum = 0;
    let count = 0;
    for (let j = Math.max(0, i - highCutSamples); j <= Math.min(n - 1, i + highCutSamples); j++) {
      sum += highPassed[j];
      count++;
    }
    result[i] = sum / count;
  }

  return result;
}

/**
 * Find dominant frequency using autocorrelation.
 * More robust than FFT for short, noisy signals.
 */
function findDominantBPM(signal, fps) {
  const n = signal.length;
  if (n < fps * 2) return null; // Need at least 2 seconds

  // Autocorrelation for lags corresponding to 40-180 BPM
  const minLag = Math.floor(fps * 60 / MAX_BPM); // 180 BPM
  const maxLag = Math.floor(fps * 60 / MIN_BPM);  // 40 BPM

  let bestLag = minLag;
  let bestCorr = -Infinity;

  for (let lag = minLag; lag <= Math.min(maxLag, n / 2); lag++) {
    let corr = 0;
    let count = 0;
    for (let i = 0; i < n - lag; i++) {
      corr += signal[i] * signal[i + lag];
      count++;
    }
    corr /= count;

    if (corr > bestCorr) {
      bestCorr = corr;
      bestLag = lag;
    }
  }

  // Convert lag to BPM
  const bpm = (fps * 60) / bestLag;
  return Math.round(bpm);
}

export function useHeartRate({ enabled = false, videoRef = null } = {}) {
  const [bpm, setBpm] = useState(null);
  const [measuring, setMeasuring] = useState(false);
  const [quality, setQuality] = useState("waiting"); // waiting | poor | fair | good

  const mountedRef = useRef(true);
  const canvasRef = useRef(null);
  const greenBufferRef = useRef([]);
  const timestampBufferRef = useRef([]);
  const rafRef = useRef(null);
  const intervalRef = useRef(null);
  const faceLandmarksRef = useRef(null);

  // Listen for face landmarks from MediaPipeController via Zustand store
  useEffect(() => {
    if (!enabled) return;

    const unsub = useMotionStore.subscribe((state) => {
      faceLandmarksRef.current = state.faceLandmarks;
    });

    return () => unsub?.();
  }, [enabled]);

  // Extract green channel from forehead region
  const sampleGreenChannel = useCallback(() => {
    const video = videoRef?.current;
    if (!video || video.readyState < 2) return null;

    const landmarks = faceLandmarksRef.current;
    if (!landmarks || landmarks.length < 340) return null;

    // Create/reuse offscreen canvas
    if (!canvasRef.current) {
      canvasRef.current = document.createElement("canvas");
    }
    const canvas = canvasRef.current;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });

    const vw = video.videoWidth || 640;
    const vh = video.videoHeight || 480;
    canvas.width = vw;
    canvas.height = vh;

    // Draw current frame
    ctx.drawImage(video, 0, 0, vw, vh);

    // Get forehead bounding box from landmarks
    let minX = Infinity, maxX = -Infinity;
    let minY = Infinity, maxY = -Infinity;

    for (const idx of FOREHEAD_LANDMARKS) {
      const lm = landmarks[idx];
      if (!lm) continue;
      const x = lm.x * vw;
      const y = lm.y * vh;
      minX = Math.min(minX, x);
      maxX = Math.max(maxX, x);
      minY = Math.min(minY, y);
      maxY = Math.max(maxY, y);
    }

    // Validate ROI
    const roiW = Math.round(maxX - minX);
    const roiH = Math.round(maxY - minY);
    if (roiW < 10 || roiH < 5) return null;

    // Extract pixel data from forehead region
    try {
      const imageData = ctx.getImageData(
        Math.round(minX),
        Math.round(minY),
        Math.min(roiW, vw - Math.round(minX)),
        Math.min(roiH, vh - Math.round(minY)),
      );
      const pixels = imageData.data;

      // Average green channel
      let greenSum = 0;
      let count = 0;
      for (let i = 1; i < pixels.length; i += 4) {
        greenSum += pixels[i]; // Green channel
        count++;
      }

      return count > 0 ? greenSum / count : null;
    } catch (_) {
      return null;
    }
  }, [videoRef]);

  // Main measurement loop
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled || !videoRef) {
      return () => { mountedRef.current = false; };
    }

    setMeasuring(true);
    setQuality("waiting");
    greenBufferRef.current = [];
    timestampBufferRef.current = [];

    // Sample green channel at ~30fps
    let lastSampleTime = 0;
    const sampleInterval = 1000 / TARGET_FPS;

    function tick() {
      if (!mountedRef.current) return;
      rafRef.current = requestAnimationFrame(tick);

      const now = performance.now();
      if (now - lastSampleTime < sampleInterval) return;
      lastSampleTime = now;

      const greenValue = sampleGreenChannel();
      if (greenValue === null) return;

      greenBufferRef.current.push(greenValue);
      timestampBufferRef.current.push(now);

      // Keep buffer at fixed size
      if (greenBufferRef.current.length > BUFFER_SIZE * 1.5) {
        greenBufferRef.current = greenBufferRef.current.slice(-BUFFER_SIZE);
        timestampBufferRef.current = timestampBufferRef.current.slice(-BUFFER_SIZE);
      }

      // Update quality indicator
      const bufLen = greenBufferRef.current.length;
      if (bufLen < TARGET_FPS * 3) {
        setQuality("waiting");
      } else if (bufLen < BUFFER_SIZE) {
        setQuality("poor");
      } else {
        setQuality("fair");
      }
    }

    rafRef.current = requestAnimationFrame(tick);

    // Compute BPM periodically
    intervalRef.current = setInterval(() => {
      if (!mountedRef.current) return;

      const signal = greenBufferRef.current;
      if (signal.length < TARGET_FPS * 5) return; // Need at least 5s

      // Estimate actual FPS from timestamps
      const timestamps = timestampBufferRef.current;
      const duration = (timestamps[timestamps.length - 1] - timestamps[0]) / 1000;
      const actualFps = timestamps.length / Math.max(duration, 1);

      // Bandpass filter
      const lowCut = Math.round(actualFps / (MIN_BPM / 60)); // Slow breathing removal
      const highCut = Math.max(1, Math.round(actualFps / (MAX_BPM / 60) / 2)); // Noise removal
      const filtered = bandpassFilter(signal, lowCut, highCut);

      // Find dominant frequency
      const estimatedBPM = findDominantBPM(filtered, actualFps);

      if (estimatedBPM && estimatedBPM >= MIN_BPM && estimatedBPM <= MAX_BPM) {
        setBpm(estimatedBPM);
        setQuality("good");

        console.log(`[HeartRate] ❤️ ${estimatedBPM} BPM (${signal.length} samples, ${actualFps.toFixed(0)} fps)`);

        window.dispatchEvent(
          new CustomEvent("Alita:heart_rate", {
            detail: {
              bpm: estimatedBPM,
              quality: "good",
              samples: signal.length,
              timestamp: Date.now(),
            },
          }),
        );
      }
    }, UPDATE_INTERVAL_MS);

    console.log("[HeartRate] ✓ rPPG heart rate monitoring started");

    return () => {
      mountedRef.current = false;
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      if (intervalRef.current) clearInterval(intervalRef.current);
      setMeasuring(false);
    };
  }, [enabled, videoRef, sampleGreenChannel]);

  return { bpm, measuring, quality };
}
