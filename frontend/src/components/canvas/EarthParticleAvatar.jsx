import { useEffect, useRef } from 'react';
import { ParticlesSwarm } from '../../lib/particles/earthSwarm';

/**
 * EarthParticleAvatar — React wrapper for GPU particle Earth
 *
 * Props:
 *   isListening, isThinking, isSpeaking, voiceActivity (existing)
 *   emotion       — string, e.g. 'happy', 'sad', 'depressed' (NEW)
 *   analyserNode  — Web Audio AnalyserNode for audio reactivity (NEW)
 */
export function EarthParticleAvatar({
  isListening,
  isThinking,
  isSpeaking,
  voiceActivity = 0,
  emotion = 'neutral',
  analyserNode = null,
}) {
  const containerRef = useRef(null);
  const swarmRef = useRef(null);

  // ── Initialize particle system ──────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return;

    const cpuHint = navigator.hardwareConcurrency || 4;
    const memoryHint = navigator.deviceMemory || 4;

    // GPU shaders handle 50K easily; scale based on device capability
    let particleCount;
    if (cpuHint >= 8 && memoryHint >= 8) {
      particleCount = 60000;  // High-end devices
    } else if (cpuHint >= 4) {
      particleCount = 40000;  // Mid-range
    } else {
      particleCount = 20000;  // Lower-end (still GPU-accelerated)
    }

    const swarm = new ParticlesSwarm(containerRef.current, particleCount);
    swarmRef.current = swarm;

    const handleResize = () => swarm.resize();
    const handleVisibility = () => swarm.setPaused(document.hidden);

    window.addEventListener('resize', handleResize);
    document.addEventListener('visibilitychange', handleVisibility);
    handleVisibility();

    return () => {
      window.removeEventListener('resize', handleResize);
      document.removeEventListener('visibilitychange', handleVisibility);
      swarm.dispose();
      swarmRef.current = null;
    };
  }, []);

  // ── Update realtime signals ─────────────────────────────────────────────
  useEffect(() => {
    swarmRef.current?.setRealtimeSignals({
      isListening,
      isThinking,
      isSpeaking,
      activity: voiceActivity,
    });
  }, [isListening, isThinking, isSpeaking, voiceActivity]);

  // ── Update emotion ──────────────────────────────────────────────────────
  useEffect(() => {
    swarmRef.current?.setEmotion(emotion);
  }, [emotion]);

  // ── Connect audio analyser ──────────────────────────────────────────────
  useEffect(() => {
    if (analyserNode) {
      swarmRef.current?.setAudioData(analyserNode);
    }
  }, [analyserNode]);

  return (
    <div
      ref={containerRef}
      style={{
        width: '100%',
        height: '100%',
        position: 'relative',
        cursor: 'grab',
      }}
    />
  );
}
