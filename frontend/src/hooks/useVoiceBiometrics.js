/**
 * useVoiceBiometrics — Speaker Voice Fingerprint Authentication
 *
 * Computes a spectral voice fingerprint using Web Audio API FFT analysis.
 * - Enrollment: Records 3s of user speech, computes MFCC-like feature vector,
 *   stores in localStorage.
 * - Verification: Continuously compares incoming speech against enrolled profile
 *   using cosine similarity.
 *
 * Dispatches:
 *   "Alita:voice_verified" — recognized speaker
 *   "Alita:voice_unknown"  — unknown speaker detected
 *   "Alita:voice_enrolled" — enrollment complete
 *
 * Listens:
 *   "Alita:enroll_voice" — start enrollment
 */

import { useEffect, useRef, useCallback, useState } from "react";

const STORAGE_KEY = "alita_voice_profile";
const VERIFY_INTERVAL_MS = 5000; // Check every 5s
const FFT_SIZE = 2048;
const NUM_BINS = 32; // Downsample FFT to 32 frequency bins
const SIMILARITY_THRESHOLD = 0.72; // Cosine similarity threshold

// Cosine similarity between two vectors
function cosineSimilarity(a, b) {
  if (!a || !b || a.length !== b.length) return 0;
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  const denominator = Math.sqrt(normA) * Math.sqrt(normB);
  return denominator === 0 ? 0 : dotProduct / denominator;
}

// Downsample frequency data to fixed-size feature vector
function extractFeatures(frequencyData) {
  const features = new Array(NUM_BINS).fill(0);
  const binSize = Math.floor(frequencyData.length / NUM_BINS);

  for (let i = 0; i < NUM_BINS; i++) {
    let sum = 0;
    for (let j = 0; j < binSize; j++) {
      const val = frequencyData[i * binSize + j];
      sum += val * val;
    }
    // RMS of each bin
    features[i] = Math.sqrt(sum / binSize);
  }

  // Normalize
  const maxVal = Math.max(...features, 0.001);
  return features.map((f) => f / maxVal);
}

export function useVoiceBiometrics({ enabled = false } = {}) {
  const [enrolled, setEnrolled] = useState(false);
  const [verified, setVerified] = useState(false);
  const profileRef = useRef(null);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const streamRef = useRef(null);
  const intervalRef = useRef(null);
  const mountedRef = useRef(true);

  // Load stored profile
  useEffect(() => {
    try {
      const stored = localStorage.getItem(STORAGE_KEY);
      if (stored) {
        profileRef.current = JSON.parse(stored);
        setEnrolled(true);
        console.log("[VoiceBio] ✓ Voice profile loaded from storage");
      }
    } catch (_) {}
  }, []);

  // Start audio analysis
  const startAnalyser = useCallback(async () => {
    if (audioCtxRef.current) return;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const ctx = new AudioContext();
      audioCtxRef.current = ctx;

      const source = ctx.createMediaStreamSource(stream);
      const analyser = ctx.createAnalyser();
      analyser.fftSize = FFT_SIZE;
      analyser.smoothingTimeConstant = 0.8;
      source.connect(analyser);
      analyserRef.current = analyser;
    } catch (err) {
      console.warn("[VoiceBio] Mic access failed:", err.message);
    }
  }, []);

  // Get current voice features
  const getCurrentFeatures = useCallback(() => {
    if (!analyserRef.current) return null;
    const data = new Float32Array(analyserRef.current.frequencyBinCount);
    analyserRef.current.getFloatFrequencyData(data);

    // Convert from dB to linear
    const linear = data.map((db) => Math.pow(10, db / 20));

    // Check if there's actual audio (not silence)
    const energy = linear.reduce((sum, v) => sum + v, 0) / linear.length;
    if (energy < 0.001) return null; // Too quiet

    return extractFeatures(linear);
  }, []);

  // Enrollment handler
  const enrollVoice = useCallback(async () => {
    console.log("[VoiceBio] Starting enrollment — speak for 3 seconds…");
    await startAnalyser();

    // Collect 3 seconds of features and average them
    const samples = [];
    const collectInterval = setInterval(() => {
      const features = getCurrentFeatures();
      if (features) samples.push(features);
    }, 200);

    setTimeout(() => {
      clearInterval(collectInterval);

      if (samples.length < 5) {
        console.warn("[VoiceBio] Not enough speech detected. Try again.");
        return;
      }

      // Average all samples
      const avgProfile = new Array(NUM_BINS).fill(0);
      for (const s of samples) {
        for (let i = 0; i < NUM_BINS; i++) {
          avgProfile[i] += s[i] / samples.length;
        }
      }

      profileRef.current = avgProfile;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(avgProfile));
      setEnrolled(true);

      console.log("[VoiceBio] ✓ Voice enrolled (%d samples)", samples.length);
      window.dispatchEvent(
        new CustomEvent("Alita:voice_enrolled", {
          detail: { samples: samples.length },
        }),
      );
    }, 3000);
  }, [startAnalyser, getCurrentFeatures]);

  // Verification loop
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled || !enrolled || !profileRef.current) {
      return () => { mountedRef.current = false; };
    }

    let started = false;

    const startVerification = async () => {
      await startAnalyser();
      started = true;

      intervalRef.current = setInterval(() => {
        if (!mountedRef.current) return;

        const features = getCurrentFeatures();
        if (!features) return; // No speech right now

        const similarity = cosineSimilarity(features, profileRef.current);

        if (similarity >= SIMILARITY_THRESHOLD) {
          if (!verified) {
            setVerified(true);
            window.dispatchEvent(
              new CustomEvent("Alita:voice_verified", {
                detail: { similarity, threshold: SIMILARITY_THRESHOLD },
              }),
            );
          }
        } else if (similarity > 0.1) {
          // Only flag unknown if there's real speech (not noise)
          setVerified(false);
          window.dispatchEvent(
            new CustomEvent("Alita:voice_unknown", {
              detail: { similarity, threshold: SIMILARITY_THRESHOLD },
            }),
          );
          console.log(
            `[VoiceBio] Unknown speaker (similarity: ${(similarity * 100).toFixed(0)}%)`,
          );
        }
      }, VERIFY_INTERVAL_MS);
    };

    startVerification();

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
      if (started) {
        try {
          streamRef.current?.getTracks().forEach((t) => t.stop());
        } catch (_) {}
        try {
          if (audioCtxRef.current?.state !== "closed") {
            audioCtxRef.current?.close();
          }
        } catch (_) {}
        audioCtxRef.current = null;
        analyserRef.current = null;
        streamRef.current = null;
      }
    };
  }, [enabled, enrolled, verified, startAnalyser, getCurrentFeatures]);

  // Listen for enrollment trigger
  useEffect(() => {
    if (!enabled) return;
    const handler = () => enrollVoice();
    window.addEventListener("Alita:enroll_voice", handler);
    return () => window.removeEventListener("Alita:enroll_voice", handler);
  }, [enabled, enrollVoice]);

  return { enrolled, verified, enrollVoice };
}
