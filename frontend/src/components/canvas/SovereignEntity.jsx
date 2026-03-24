/**
 * SovereignEntity.jsx — React wrapper for The Sovereign Canvas2D entity.
 *
 * Renders at native viewport resolution using devicePixelRatio for crisp
 * HiDPI output. ResizeObserver keeps canvas resolution matched to the
 * actual display size — no more blurry CSS stretching.
 */

import { useEffect, useRef, useCallback } from 'react';
import {
  initSovereign,
  updateFromFaceData,
  startRenderLoop,
  stopRenderLoop,
  resizeSovereign,
} from './sovereignCore';
import { PALETTES, EMOTION_TO_PALETTE } from './sovereignPalettes';

export function SovereignEntity({
  faceData,
  isListening = false,
  isThinking = false,
  isSpeaking = false,
  voiceActivity = 0,
  className,
}) {
  const canvasRef = useRef(null);
  const stateRef = useRef(null);
  const animRef = useRef(null);
  const containerRef = useRef(null);

  // ── Resize canvas to match container at native DPI ──────────────────────
  const handleResize = useCallback(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2); // cap at 2x
    const rect = container.getBoundingClientRect();
    const w = Math.round(rect.width);
    const h = Math.round(rect.height);

    // Only resize if dimensions actually changed (prevents flicker)
    if (canvas.width === w * dpr && canvas.height === h * dpr) return;

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Update internal state dimensions
    if (stateRef.current) {
      resizeSovereign(stateRef.current, w, h);
    }
  }, []);

  // ── Initialize on mount ────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    // Initial sizing
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const rect = container.getBoundingClientRect();
    const w = Math.round(rect.width);
    const h = Math.round(rect.height);

    canvas.width = w * dpr;
    canvas.height = h * dpr;
    canvas.style.width = w + 'px';
    canvas.style.height = h + 'px';

    const ctx = canvas.getContext('2d');
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    stateRef.current = initSovereign(canvas, w, h);
    startRenderLoop(stateRef.current, PALETTES, animRef);

    // Watch for container resizes
    const ro = new ResizeObserver(handleResize);
    ro.observe(container);
    window.addEventListener('resize', handleResize);

    return () => {
      stopRenderLoop(animRef);
      ro.disconnect();
      window.removeEventListener('resize', handleResize);
    };
  }, [handleResize]);

  // ── Update on every new faceData from WebSocket ─────────────────────────
  useEffect(() => {
    if (!stateRef.current || !faceData) return;
    updateFromFaceData(stateRef.current, faceData, PALETTES, EMOTION_TO_PALETTE);
  }, [faceData]);

  // ── React to isListening/isThinking/isSpeaking state changes ────────────
  useEffect(() => {
    if (!stateRef.current) return;
    if (isThinking) {
      stateRef.current.targetGlowIntensity = 0.35;
      stateRef.current.targetPulseSpeed = 1.4;
    } else if (isSpeaking) {
      stateRef.current.targetGlowIntensity = 0.75;
      stateRef.current.targetPulseSpeed = 1.0;
    } else if (isListening) {
      stateRef.current.targetGlowIntensity = 0.55;
      stateRef.current.targetPulseSpeed = 0.7;
    } else {
      stateRef.current.targetGlowIntensity = 0.45;
      stateRef.current.targetPulseSpeed = 0.8;
    }
  }, [isListening, isThinking, isSpeaking]);

  // ── Voice activity drives energy level ──────────────────────────────────
  useEffect(() => {
    if (!stateRef.current) return;
    stateRef.current.targetEnergyLevel = Math.min(1.0, 0.3 + voiceActivity * 0.7);
  }, [voiceActivity]);

  // ── Listen for Alita:face_data custom events (backward compat) ──────────
  useEffect(() => {
    const handler = (e) => {
      if (!stateRef.current || !e.detail) return;
      updateFromFaceData(stateRef.current, e.detail, PALETTES, EMOTION_TO_PALETTE);
    };
    window.addEventListener('Alita:face_data', handler);
    return () => window.removeEventListener('Alita:face_data', handler);
  }, []);

  return (
    <div
      ref={containerRef}
      className={className}
      style={{
        position: 'absolute',
        inset: 0,
        width: '100%',
        height: '100%',
        overflow: 'hidden',
        background: '#000',
      }}
    >
      <canvas
        ref={canvasRef}
        style={{
          display: 'block',
          position: 'absolute',
          top: 0,
          left: 0,
        }}
      />
    </div>
  );
}

export default SovereignEntity;
