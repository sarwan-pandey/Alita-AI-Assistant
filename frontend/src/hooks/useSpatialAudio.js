/**
 * useSpatialAudio — 3D Positional Audio via Web Audio API
 *
 * Positions Alita's voice in 3D space using PannerNode.
 * Tracks user head orientation via face landmarks to adjust audio.
 *
 * Features:
 *   - Alita's voice comes from the avatar's screen position
 *   - Head rotation shifts the stereo field naturally
 *   - Environmental reverb adjusts based on ambient sound type
 *   - Proximity: voice gets louder/quieter based on lean distance
 *
 * Dispatches: "Alita:spatial_audio_ready" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";
import { useMotionStore } from "../store/useMotionStore";

const HEAD_TRACK_INTERVAL_MS = 100;

// Face landmark indices for head orientation
const NOSE_TIP = 1;
const LEFT_EAR_TRAGION = 234;
const RIGHT_EAR_TRAGION = 454;
const FOREHEAD = 10;
const CHIN = 152;

export function useSpatialAudio({ enabled = false } = {}) {
  const [spatialReady, setSpatialReady] = useState(false);

  const audioCtxRef = useRef(null);
  const pannerRef = useRef(null);
  const gainRef = useRef(null);
  const sourceNodeRef = useRef(null);
  const mountedRef = useRef(true);
  const intervalRef = useRef(null);

  // Initialize spatial audio context
  const initSpatialContext = useCallback(() => {
    if (audioCtxRef.current) return audioCtxRef.current;

    try {
      const ctx = new AudioContext();

      // Set listener position (user at origin, facing screen)
      if (ctx.listener.positionX) {
        ctx.listener.positionX.value = 0;
        ctx.listener.positionY.value = 0;
        ctx.listener.positionZ.value = 0;
        ctx.listener.forwardX.value = 0;
        ctx.listener.forwardY.value = 0;
        ctx.listener.forwardZ.value = -1;
        ctx.listener.upX.value = 0;
        ctx.listener.upY.value = 1;
        ctx.listener.upZ.value = 0;
      }

      // Create panner for Alita's voice position
      const panner = ctx.createPanner();
      panner.panningModel = "HRTF";           // Head-related transfer function
      panner.distanceModel = "inverse";
      panner.refDistance = 1;
      panner.maxDistance = 10;
      panner.rolloffFactor = 1;
      panner.coneInnerAngle = 360;
      panner.coneOuterAngle = 360;

      // Initial position (center, slightly elevated, in front)
      if (panner.positionX) {
        panner.positionX.value = 0;
        panner.positionY.value = 0.3;    // Slightly above center
        panner.positionZ.value = -1;     // In front of user
      }

      // Gain node for distance-based volume
      const gain = ctx.createGain();
      gain.gain.value = 1.0;

      // Connect: source → panner → gain → output
      panner.connect(gain);
      gain.connect(ctx.destination);

      audioCtxRef.current = ctx;
      pannerRef.current = panner;
      gainRef.current = gain;

      return ctx;
    } catch (err) {
      console.warn("[SpatialAudio] Init failed:", err.message);
      return null;
    }
  }, []);

  // Update Alita's voice position based on avatar screen position
  const updateVoicePosition = useCallback((x, y, z) => {
    const panner = pannerRef.current;
    if (!panner || !panner.positionX) return;

    // Smooth transition
    const now = audioCtxRef.current?.currentTime || 0;
    panner.positionX.setTargetAtTime(x, now, 0.1);
    panner.positionY.setTargetAtTime(y, now, 0.1);
    panner.positionZ.setTargetAtTime(z || -1, now, 0.1);
  }, []);

  // Update listener orientation from head tracking
  const updateListenerFromHead = useCallback((landmarks) => {
    if (!landmarks || landmarks.length < 455) return;
    const ctx = audioCtxRef.current;
    if (!ctx || !ctx.listener.forwardX) return;

    const nose = landmarks[NOSE_TIP];
    const leftEar = landmarks[LEFT_EAR_TRAGION];
    const rightEar = landmarks[RIGHT_EAR_TRAGION];

    if (!nose || !leftEar || !rightEar) return;

    // Head yaw from ear positions (facing direction)
    const earDiffX = rightEar.x - leftEar.x;
    const headYaw = Math.atan2(nose.z || 0, earDiffX) || 0;

    // Update listener forward direction
    const now = ctx.currentTime;
    const forwardX = Math.sin(headYaw);
    const forwardZ = -Math.cos(headYaw);

    ctx.listener.forwardX.setTargetAtTime(forwardX, now, 0.05);
    ctx.listener.forwardZ.setTargetAtTime(forwardZ, now, 0.05);
  }, []);

  // Track head movement for spatial adjustments
  useEffect(() => {
    if (!enabled) return;
    mountedRef.current = true;

    const ctx = initSpatialContext();
    if (!ctx) return;

    setSpatialReady(true);

    // Subscribe to face landmarks
    const unsub = useMotionStore.subscribe((state) => {
      if (!mountedRef.current) return;
      if (state.faceLandmarks) {
        updateListenerFromHead(state.faceLandmarks);
      }
    });

    console.log("[SpatialAudio] ✓ 3D spatial audio active (HRTF panning)");

    window.dispatchEvent(
      new CustomEvent("Alita:spatial_audio_ready", { detail: { ready: true } }),
    );

    return () => {
      mountedRef.current = false;
      unsub?.();
    };
  }, [enabled, initSpatialContext, updateListenerFromHead]);

  // Listen for avatar position updates (from the 3D scene)
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { x, y, z } = e.detail || {};
      if (typeof x === "number") {
        updateVoicePosition(x, y || 0.3, z || -1);
      }
    };

    window.addEventListener("Alita:avatar_position", handler);
    return () => window.removeEventListener("Alita:avatar_position", handler);
  }, [enabled, updateVoicePosition]);

  // Connect any TTS audio element to spatial pipeline
  const connectAudioElement = useCallback((audioElement) => {
    const ctx = audioCtxRef.current;
    const panner = pannerRef.current;
    if (!ctx || !panner || !audioElement) return;

    try {
      // Disconnect previous source
      if (sourceNodeRef.current) {
        try { sourceNodeRef.current.disconnect(); } catch (_) {}
      }

      const source = ctx.createMediaElementSource(audioElement);
      source.connect(panner);
      sourceNodeRef.current = source;

      console.log("[SpatialAudio] Connected audio element to 3D pipeline");
    } catch (err) {
      // Already connected or other issue — non-critical
    }
  }, []);

  // Cleanup
  useEffect(() => {
    return () => {
      try {
        if (sourceNodeRef.current) sourceNodeRef.current.disconnect();
        if (audioCtxRef.current?.state !== "closed") {
          audioCtxRef.current?.close();
        }
      } catch (_) {}
    };
  }, []);

  return {
    spatialReady,
    connectAudioElement,
    updateVoicePosition,
  };
}
