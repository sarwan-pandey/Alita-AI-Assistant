/**
 * useSoundClassification — Ambient Sound Detection
 *
 * Uses Web Audio API AnalyserNode for frequency-domain analysis.
 * Classifies ambient sounds based on spectral patterns:
 *   - Music:   harmonic peaks, sustained energy 200-4000Hz
 *   - Typing:  short transient bursts in 2000-8000Hz
 *   - Traffic: low-frequency rumble (50-500Hz)
 *   - Speech:  formant frequencies (300-3000Hz)
 *   - Silence: overall energy below threshold
 *
 * Dispatches: "Alita:ambient_sound" CustomEvent
 */

import { useEffect, useRef, useCallback } from "react";

const FFT_SIZE = 2048;
const ANALYSIS_INTERVAL_MS = 1500;

// Frequency ranges (bin indices depend on sample rate)
function getFreqBinIndex(freq, sampleRate, fftSize) {
  return Math.round((freq * fftSize) / sampleRate);
}

function classifySound(frequencyData, sampleRate) {
  const binCount = frequencyData.length;

  // Calculate energy in different frequency bands
  const lowStart = getFreqBinIndex(50, sampleRate, FFT_SIZE * 2);
  const lowEnd = getFreqBinIndex(500, sampleRate, FFT_SIZE * 2);
  const midStart = getFreqBinIndex(500, sampleRate, FFT_SIZE * 2);
  const midEnd = getFreqBinIndex(4000, sampleRate, FFT_SIZE * 2);
  const highStart = getFreqBinIndex(4000, sampleRate, FFT_SIZE * 2);
  const highEnd = Math.min(getFreqBinIndex(12000, sampleRate, FFT_SIZE * 2), binCount - 1);

  let lowEnergy = 0;
  let midEnergy = 0;
  let highEnergy = 0;
  let totalEnergy = 0;

  for (let i = 0; i < binCount; i++) {
    const val = frequencyData[i];
    // Convert from dB to linear
    const linear = Math.pow(10, Math.max(val, -100) / 20);
    totalEnergy += linear;

    if (i >= lowStart && i <= lowEnd) lowEnergy += linear;
    if (i >= midStart && i <= midEnd) midEnergy += linear;
    if (i >= highStart && i <= highEnd) highEnergy += linear;
  }

  // Normalize
  totalEnergy /= binCount;

  if (totalEnergy < 0.0005) {
    return { label: "silence", confidence: 0.9 };
  }

  // Ratios
  const lowRatio = lowEnergy / (totalEnergy * binCount + 0.001);
  const midRatio = midEnergy / (totalEnergy * binCount + 0.001);
  const highRatio = highEnergy / (totalEnergy * binCount + 0.001);

  // Check for harmonicity (music indicator)
  let harmonicScore = 0;
  for (let i = 2; i < binCount / 4; i++) {
    const fundamental = frequencyData[i];
    // Check if 2nd and 3rd harmonics exist
    if (i * 2 < binCount && i * 3 < binCount) {
      const h2 = frequencyData[i * 2];
      const h3 = frequencyData[i * 3];
      if (fundamental > -40 && h2 > -60 && h3 > -70) {
        harmonicScore++;
      }
    }
  }

  // Classify based on spectral shape
  if (harmonicScore > 15 && midRatio > 0.3) {
    return { label: "music", confidence: 0.7 + Math.min(harmonicScore / 50, 0.25) };
  }

  if (highRatio > 0.4 && totalEnergy > 0.002) {
    // Short high-frequency transients
    return { label: "typing", confidence: 0.6 };
  }

  if (lowRatio > 0.5 && midRatio < 0.2) {
    return { label: "traffic", confidence: 0.6 };
  }

  if (midRatio > 0.3 && lowRatio > 0.1 && highRatio < 0.3) {
    return { label: "speech", confidence: 0.5 };
  }

  return { label: "ambient", confidence: 0.4 };
}

export function useSoundClassification({ enabled = false } = {}) {
  const mountedRef = useRef(true);
  const audioCtxRef = useRef(null);
  const analyserRef = useRef(null);
  const streamRef = useRef(null);
  const intervalRef = useRef(null);
  const lastLabelRef = useRef("silence");
  const stableLabelCountRef = useRef(0);

  const cleanup = useCallback(() => {
    if (intervalRef.current) clearInterval(intervalRef.current);
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
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => {
        mountedRef.current = false;
        cleanup();
      };
    }

    let started = false;

    async function init() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        streamRef.current = stream;

        const ctx = new AudioContext();
        audioCtxRef.current = ctx;

        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = FFT_SIZE;
        analyser.smoothingTimeConstant = 0.7;
        source.connect(analyser);
        analyserRef.current = analyser;
        started = true;

        console.log("[SoundClass] ✓ Ambient sound classification active");

        intervalRef.current = setInterval(() => {
          if (!mountedRef.current || !analyserRef.current) return;

          const data = new Float32Array(analyserRef.current.frequencyBinCount);
          analyserRef.current.getFloatFrequencyData(data);

          const result = classifySound(data, ctx.sampleRate);

          // Require 2 consistent readings before dispatching (debounce)
          if (result.label === lastLabelRef.current) {
            stableLabelCountRef.current++;
          } else {
            stableLabelCountRef.current = 1;
            lastLabelRef.current = result.label;
          }

          if (stableLabelCountRef.current === 2 && result.label !== "silence") {
            console.log(
              `[SoundClass] Detected: ${result.label} (${(result.confidence * 100).toFixed(0)}%)`,
            );

            window.dispatchEvent(
              new CustomEvent("Alita:ambient_sound", {
                detail: {
                  label: result.label,
                  confidence: result.confidence,
                  timestamp: Date.now(),
                },
              }),
            );
          }
        }, ANALYSIS_INTERVAL_MS);
      } catch (err) {
        console.warn("[SoundClass] Init failed:", err.message);
      }
    }

    init();

    return () => {
      mountedRef.current = false;
      cleanup();
    };
  }, [enabled, cleanup]);

  return null;
}
