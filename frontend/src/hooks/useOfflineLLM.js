/**
 * useOfflineLLM — Browser-based LLM via WebLLM (WebGPU)
 *
 * Runs a small language model entirely in the browser using WebGPU.
 * No server needed — fully offline capable.
 *
 * Uses @mlc-ai/web-llm (loaded dynamically from CDN to avoid npm dep).
 * Falls back gracefully when WebGPU is unavailable.
 *
 * Dispatches: "Alita:offline_reply" CustomEvent
 * Listens:   "Alita:offline_query" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";

// Small model that fits in browser VRAM (~600MB)
const MODEL_ID = "Phi-3.5-mini-instruct-q4f16_1-MLC";
const CDN_URL = "https://cdn.jsdelivr.net/npm/@mlc-ai/web-llm@0.2.73/lib/index.min.js";

export function useOfflineLLM({ enabled = false } = {}) {
  const [status, setStatus] = useState("idle"); // idle | checking | loading | ready | error | unsupported
  const [loadProgress, setLoadProgress] = useState(0);
  const [modelLoaded, setModelLoaded] = useState(false);

  const engineRef = useRef(null);
  const mountedRef = useRef(true);
  const initAttemptedRef = useRef(false);

  // Check WebGPU support
  const checkWebGPU = useCallback(async () => {
    if (!navigator.gpu) return false;
    try {
      const adapter = await navigator.gpu.requestAdapter();
      return !!adapter;
    } catch (_) {
      return false;
    }
  }, []);

  // Load WebLLM engine
  const loadEngine = useCallback(async () => {
    if (engineRef.current) return engineRef.current;
    if (initAttemptedRef.current) return null;
    initAttemptedRef.current = true;

    try {
      setStatus("checking");
      const hasWebGPU = await checkWebGPU();

      if (!hasWebGPU) {
        console.warn("[OfflineLLM] WebGPU not available — offline AI disabled");
        setStatus("unsupported");
        return null;
      }

      setStatus("loading");
      console.log("[OfflineLLM] Loading WebLLM engine…");

      // Dynamically load WebLLM from CDN (avoids npm dependency)
      const webllm = await import(/* @vite-ignore */ CDN_URL);
      const { CreateMLCEngine } = webllm;

      if (!mountedRef.current) return null;

      const engine = await CreateMLCEngine(MODEL_ID, {
        initProgressCallback: (progress) => {
          if (!mountedRef.current) return;
          const pct = Math.round((progress.progress || 0) * 100);
          setLoadProgress(pct);
          if (pct % 20 === 0) {
            console.log(`[OfflineLLM] Loading model: ${pct}%`);
          }
        },
      });

      if (!mountedRef.current) return null;

      engineRef.current = engine;
      setStatus("ready");
      setModelLoaded(true);
      console.log("[OfflineLLM] ✓ Offline AI ready (Phi-3.5-mini in browser!)");

      window.dispatchEvent(
        new CustomEvent("Alita:offline_ready", {
          detail: { model: MODEL_ID },
        }),
      );

      return engine;
    } catch (err) {
      console.warn("[OfflineLLM] Load failed:", err.message);
      setStatus("error");
      initAttemptedRef.current = false;
      return null;
    }
  }, [checkWebGPU]);

  // Generate response
  const generate = useCallback(async (prompt, options = {}) => {
    const engine = engineRef.current || await loadEngine();
    if (!engine) {
      return "Offline AI is not available. WebGPU support is required.";
    }

    try {
      const messages = [
        {
          role: "system",
          content: "You are MJ, a helpful AI assistant. Respond concisely and helpfully.",
        },
        { role: "user", content: prompt },
      ];

      let result = "";

      // Streaming response
      const asyncChunkGenerator = await engine.chat.completions.create({
        messages,
        temperature: options.temperature || 0.7,
        max_tokens: options.maxTokens || 256,
        stream: true,
      });

      for await (const chunk of asyncChunkGenerator) {
        const delta = chunk.choices?.[0]?.delta?.content || "";
        result += delta;

        // Dispatch partial results for streaming UI
        window.dispatchEvent(
          new CustomEvent("Alita:offline_token", {
            detail: { token: delta, partial: result },
          }),
        );
      }

      return result;
    } catch (err) {
      console.warn("[OfflineLLM] Generation error:", err.message);
      return "Sorry, I encountered an error processing your request offline.";
    }
  }, [loadEngine]);

  // Listen for offline query events
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    const handler = async (e) => {
      const { prompt, requestId } = e.detail || {};
      if (!prompt) return;

      console.log("[OfflineLLM] Processing:", prompt.slice(0, 50));

      const reply = await generate(prompt);

      window.dispatchEvent(
        new CustomEvent("Alita:offline_reply", {
          detail: { reply, requestId, prompt },
        }),
      );
    };

    window.addEventListener("Alita:offline_query", handler);

    // Don't auto-load model — wait until first query
    // Just check WebGPU support
    checkWebGPU().then((supported) => {
      if (supported) {
        console.log("[OfflineLLM] ✓ WebGPU available — say 'offline mode' to activate");
        setStatus("idle");
      } else {
        console.log("[OfflineLLM] WebGPU not available — offline AI disabled");
        setStatus("unsupported");
      }
    });

    return () => {
      mountedRef.current = false;
      window.removeEventListener("Alita:offline_query", handler);
    };
  }, [enabled, generate, checkWebGPU]);

  return { status, loadProgress, modelLoaded, generate, loadEngine };
}
