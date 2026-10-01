import { useCallback, useEffect, useRef, useState } from "react";

const UI_UPDATE_INTERVAL_MS = 60;
const FALLBACK_TICK_MS = 33;

const clamp01 = (value) =>
  Math.max(0, Math.min(1, Number.isFinite(value) ? value : 0));

const SCRIPT_CACHE = new Map();

const loadScriptOnce = (src) => {
  if (SCRIPT_CACHE.has(src)) return SCRIPT_CACHE.get(src);

  const promise = new Promise((resolve, reject) => {
    const existing = document.querySelector(`script[data-vad-src="${src}"]`);
    if (existing) {
      if (existing.getAttribute("data-loaded") === "1") {
        resolve();
        return;
      }
      existing.addEventListener("load", () => resolve(), { once: true });
      existing.addEventListener(
        "error",
        () => reject(new Error(`Failed loading script: ${src}`)),
        { once: true },
      );
      return;
    }

    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.dataset.vadSrc = src;
    script.onload = () => {
      script.setAttribute("data-loaded", "1");
      resolve();
    };
    script.onerror = () => reject(new Error(`Failed loading script: ${src}`));
    document.head.appendChild(script);
  });

  SCRIPT_CACHE.set(src, promise);
  return promise;
};

const loadVadGlobals = async () => {
  await loadScriptOnce("/ort.min.js");
  await loadScriptOnce("/vad.bundle.min.js");

  const vadGlobal = window.vad;
  const MicVAD = vadGlobal?.MicVAD;
  if (!MicVAD?.new) {
    throw new Error("MicVAD global unavailable after loading /vad.bundle.min.js");
  }
  return { MicVAD };
};

const rmsFromFloatFrame = (frame) => {
  if (!frame || frame.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < frame.length; i++) {
    const sample = frame[i];
    sum += sample * sample;
  }
  return Math.sqrt(sum / frame.length);
};

const rmsFromByteData = (data) => {
  if (!data || data.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    const normalized = (data[i] - 128) / 128;
    sum += normalized * normalized;
  }
  return Math.sqrt(sum / data.length);
};

export function useSileroVAD({ enabled = true, speechThreshold = 0.5, onAudioFrame, onSpeechEndAudio } = {}) {
  const [speechProb, setSpeechProb] = useState(0);
  const [isSpeechActive, setIsSpeechActive] = useState(false);

  const speechProbRef = useRef(0);
  const isSpeechActiveRef = useRef(false);
  const rmsRef = useRef(0);
  const isFallbackRmsRef = useRef(false);
  const onAudioFrameRef = useRef(onAudioFrame);
  const onSpeechEndAudioRef = useRef(onSpeechEndAudio);

  useEffect(() => {
    onAudioFrameRef.current = onAudioFrame;
    onSpeechEndAudioRef.current = onSpeechEndAudio;
  });

  const vadRef = useRef(null);
  const fallbackStreamRef = useRef(null);
  const fallbackCtxRef = useRef(null);
  const fallbackAnalyserRef = useRef(null);
  const fallbackIntervalRef = useRef(null);

  const lastUiUpdateTsRef = useRef(0);
  const sileroWarnedRef = useRef(false);

  const updateSpeechState = useCallback(
    (prob, forceUi = false) => {
      const clamped = clamp01(prob);
      const active = clamped >= speechThreshold;
      speechProbRef.current = clamped;
      isSpeechActiveRef.current = active;

      const now = performance.now();
      if (forceUi || now - lastUiUpdateTsRef.current >= UI_UPDATE_INTERVAL_MS) {
        setSpeechProb(clamped);
        setIsSpeechActive(active);
        lastUiUpdateTsRef.current = now;
      }
    },
    [speechThreshold],
  );

  const stopFallbackRms = useCallback(async () => {
    clearInterval(fallbackIntervalRef.current);
    fallbackIntervalRef.current = null;

    try {
      fallbackStreamRef.current?.getTracks().forEach((track) => track.stop());
    } catch (_) {}
    fallbackStreamRef.current = null;

    try {
      if (fallbackCtxRef.current?.state !== "closed") {
        await fallbackCtxRef.current?.close();
      }
    } catch (_) {}

    fallbackCtxRef.current = null;
    fallbackAnalyserRef.current = null;
  }, []);

  const startFallbackRms = useCallback(async () => {
    if (fallbackIntervalRef.current) return;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      fallbackStreamRef.current = stream;

      const audioCtx = new AudioContext();
      fallbackCtxRef.current = audioCtx;

      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 256;
      analyser.smoothingTimeConstant = 0.3;
      source.connect(analyser);
      fallbackAnalyserRef.current = analyser;

      isFallbackRmsRef.current = true;
      console.warn("[VAD] Silero unavailable — using RMS fallback");

      fallbackIntervalRef.current = setInterval(() => {
        if (!fallbackAnalyserRef.current) return;
        const data = new Uint8Array(
          fallbackAnalyserRef.current.frequencyBinCount,
        );
        fallbackAnalyserRef.current.getByteTimeDomainData(data);

        const rms = rmsFromByteData(data);
        rmsRef.current = rms;
        updateSpeechState(rms);
      }, FALLBACK_TICK_MS);
    } catch (err) {
      console.error("[VAD] RMS fallback failed:", err);
    }
  }, [updateSpeechState]);

  useEffect(() => {
    if (!enabled) {
      return undefined;
    }

    let cancelled = false;

    const init = async () => {
      try {
        const { MicVAD } = await loadVadGlobals();

        const vad = await MicVAD.new({
          model: "v5",
          baseAssetPath: "/",
          onnxWASMBasePath: "/",
          startOnLoad: true,
          onSpeechStart: () => {
            if (!cancelled) updateSpeechState(0.99, true);
          },
          onSpeechEnd: (audio) => {
            if (!cancelled) {
              updateSpeechState(0, true);
              if (onSpeechEndAudioRef.current && audio) {
                onSpeechEndAudioRef.current(audio);
              }
            }
          },
          onFrameProcessed: (probabilities, frame) => {
            if (cancelled) return;
            const prob = clamp01(
              probabilities?.isSpeech ?? probabilities?.speech ?? 0,
            );
            rmsRef.current = rmsFromFloatFrame(frame);
            updateSpeechState(prob);
            if (onAudioFrameRef.current && frame) {
              onAudioFrameRef.current(frame, prob);
            }
          },
        });

        if (cancelled) {
          await vad.destroy();
          return;
        }

        vadRef.current = vad;
        isFallbackRmsRef.current = false;
        console.log("[VAD] Silero VAD initialized ✓");
      } catch (err) {
        if (cancelled) return;
        if (!sileroWarnedRef.current) {
          sileroWarnedRef.current = true;
          console.warn("[VAD] Failed to initialize Silero VAD:", err);
        }
        await startFallbackRms();
      }
    };

    void init();

    return () => {
      cancelled = true;

      const cleanup = async () => {
        try {
          if (vadRef.current) {
            await vadRef.current.destroy();
          }
        } catch (_) {}
        vadRef.current = null;

        await stopFallbackRms();
      };

      void cleanup();
    };
  }, [enabled, startFallbackRms, stopFallbackRms, updateSpeechState]);

  const getMicVolume = useCallback(() => rmsRef.current || 0, []);

  return {
    speechProb,
    isSpeechActive,
    speechProbRef,
    isSpeechActiveRef,
    isFallbackRmsRef,
    getMicVolume,
  };
}
