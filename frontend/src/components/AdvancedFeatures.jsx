/**
 * AdvancedFeatures — Orchestrator Component
 *
 * Mounts all 21 advanced feature hooks in a single component.
 * Each hook is independently guarded and fails gracefully.
 * Only this component needs to be added to App.jsx.
 */

import { useRef, useState, useCallback, useEffect } from "react";
import { useHandGestures } from "../hooks/useHandGestures";
import { useObjectRecognition } from "../hooks/useObjectRecognition";
import { useEmotionParticles } from "../hooks/useEmotionParticles";
import { useScreenReader } from "../hooks/useScreenReader";
import { useContextAwareness } from "../hooks/useContextAwareness";
import { useVoiceBiometrics } from "../hooks/useVoiceBiometrics";
import { useTranslation } from "../hooks/useTranslation";
import { usePoseMood } from "../hooks/usePoseMood";
import { useSoundClassification } from "../hooks/useSoundClassification";
import { useMemoryTimeline } from "../hooks/useMemoryTimeline";
import { MemoryTimeline } from "./ui/MemoryTimeline";
import { useHeartRate } from "../hooks/useHeartRate";
import { useSignLanguage } from "../hooks/useSignLanguage";
import { useOfflineLLM } from "../hooks/useOfflineLLM";
import { useFitnessCoach } from "../hooks/useFitnessCoach";
import { useCognitiveOrchestrator } from "../hooks/useCognitiveOrchestrator";
import { usePredictiveIntent } from "../hooks/usePredictiveIntent";
import { useCognitiveLoad } from "../hooks/useCognitiveLoad";
import { useSpatialAudio } from "../hooks/useSpatialAudio";
import { useProductivityAnalytics } from "../hooks/useProductivityAnalytics";
import { useLipReading } from "../hooks/useLipReading";
import { useNaturalCommandRouter } from "../hooks/useNaturalCommandRouter";
import { useSubscriptionStore } from "../store/useSubscriptionStore";
import { PricingPage } from "./ui/PricingPage";

export function AdvancedFeatures({
  enabled = true,
  videoRef = null,
  messages = [],
  currentLang = "en",
  sendMessage = null,
  sendAudioChunk = null,
}) {
  const [showTimeline, setShowTimeline] = useState(false);
  const [showPricing, setShowPricing] = useState(false);

  // Subscription state
  const { isPremium, isTrialActive, trialDaysRemaining, refresh: refreshSub } =
    useSubscriptionStore();

  // Refresh subscription every 60s (check trial expiry)
  useEffect(() => {
    const interval = setInterval(refreshSub, 60000);
    return () => clearInterval(interval);
  }, [refreshSub]);

  // Listen for pricing page request
  useEffect(() => {
    const handler = () => setShowPricing(true);
    window.addEventListener("Alita:show_pricing", handler);
    return () => window.removeEventListener("Alita:show_pricing", handler);
  }, []);

  // ── Feature 1: Hand Gesture Control ─────────────────────────────────
  useHandGestures({
    enabled: enabled && !!videoRef,
    videoRef,
  });

  // ── FREE: Object/Scene Recognition ──────────────────────────────────
  // (gated to premium)
  useObjectRecognition({
    enabled: enabled && isPremium,
    videoRef,
  });

  // ── Feature 3: Emotion-Reactive Particles ───────────────────────────
  useEmotionParticles({
    enabled,
  });

  // ── PREMIUM: Smart Screen Reader ────────────────────────────────────
  useScreenReader({
    enabled: enabled && isPremium,
    sendMessage: sendAudioChunk,
  });

  // ── Feature 5: Proactive Context Awareness ──────────────────────────
  useContextAwareness({
    enabled,
  });

  // ── PREMIUM: Voice Biometric Authentication ─────────────────────────
  const { enrolled: voiceEnrolled, verified: voiceVerified } =
    useVoiceBiometrics({ enabled: enabled && isPremium });

  // ── PREMIUM: Real-time Language Translation ─────────────────────────
  useTranslation({
    enabled: enabled && isPremium,
    currentLang,
    sendMessage: sendAudioChunk,
  });

  // ── Feature 8: Pose-based Mood Detection ────────────────────────────
  usePoseMood({
    enabled,
  });

  // ── Feature 9: Ambient Sound Classification ─────────────────────────
  useSoundClassification({
    enabled,
  });

  // ── Feature 10: Memory Timeline ─────────────────────────────────────
  const { timeline, clearTimeline } = useMemoryTimeline({
    enabled,
    messages,
  });

  // ── PREMIUM: Heart Rate via Webcam (rPPG) ──────────────────────────
  const { bpm, quality: hrQuality } = useHeartRate({
    enabled: enabled && isPremium && !!videoRef,
    videoRef,
  });

  // ── PREMIUM: Sign Language Recognition ──────────────────────────────
  useSignLanguage({
    enabled: enabled && isPremium && !!videoRef,
    videoRef,
  });

  // ── PREMIUM: Offline AI Brain (WebLLM) ──────────────────────────────
  const { status: llmStatus, modelLoaded: offlineReady } = useOfflineLLM({
    enabled: enabled && isPremium,
  });

  // ── PREMIUM: Real-time Fitness Coach ────────────────────────────────
  const { activeExercise, repCount, lastFormTip } = useFitnessCoach({
    enabled: enabled && isPremium,
  });

  // ── BRAIN: Cognitive Orchestrator (fuses all signals) ───────────────
  const { userState, confidence: brainConfidence } = useCognitiveOrchestrator({
    enabled,
  });

  // ── PREMIUM: Predictive Intent Engine ───────────────────────────────
  const { prediction } = usePredictiveIntent({
    enabled: enabled && isPremium,
    messages,
  });

  // ── PREMIUM: Cognitive Load Monitor ─────────────────────────────────
  const { loadLevel, blinkRate } = useCognitiveLoad({
    enabled: enabled && isPremium,
  });

  // ── PREMIUM: Spatial Audio / 3D Sound ───────────────────────────────
  useSpatialAudio({
    enabled: enabled && isPremium,
  });

  // ── PREMIUM: Productivity Analytics ─────────────────────────────────
  const { todayStats } = useProductivityAnalytics({
    enabled: enabled && isPremium,
    messages,
  });

  // ── PREMIUM: Lip Reading (Visual Speech) ────────────────────────────
  const { lipStatus } = useLipReading({
    enabled: enabled && isPremium,
  });

  // ── Feature 20: Natural Language Command Router ─────────────────────
  useNaturalCommandRouter({
    enabled,
  });

  // ── Gesture handler: Show timeline on "love" gesture ────────────────
  const handleGesture = useCallback((e) => {
    const { action } = e.detail || {};
    if (action === "love") {
      setShowTimeline(true);
    }
  }, []);

  // Listen for gesture events
  useEffect(() => {
    window.addEventListener("Alita:gesture", handleGesture);
    return () => window.removeEventListener("Alita:gesture", handleGesture);
  }, [handleGesture]);

  return (
    <>
      {/* Timeline toggle button */}
      <button
        onClick={() => setShowTimeline(!showTimeline)}
        title="Memory Timeline"
        style={{
          position: "fixed",
          bottom: "75px",
          right: "16px",
          zIndex: 200,
          width: "36px",
          height: "36px",
          borderRadius: "50%",
          background: "rgba(168,85,247,0.12)",
          border: "1px solid rgba(168,85,247,0.3)",
          color: "rgba(168,85,247,0.8)",
          fontSize: "1rem",
          cursor: "pointer",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          backdropFilter: "blur(8px)",
          transition: "all 200ms",
          boxShadow: "0 4px 16px rgba(168,85,247,0.1)",
        }}
        onMouseEnter={(e) => {
          e.target.style.background = "rgba(168,85,247,0.25)";
          e.target.style.transform = "scale(1.1)";
        }}
        onMouseLeave={(e) => {
          e.target.style.background = "rgba(168,85,247,0.12)";
          e.target.style.transform = "scale(1)";
        }}
      >
        🧠
      </button>

      {/* Voice biometric indicator */}
      {voiceEnrolled && (
        <div
          title={voiceVerified ? "Voice verified ✓" : "Voice not verified"}
          style={{
            position: "fixed",
            bottom: "120px",
            right: "20px",
            zIndex: 200,
            width: "10px",
            height: "10px",
            borderRadius: "50%",
            background: voiceVerified
              ? "rgba(34,197,94,0.8)"
              : "rgba(239,68,68,0.6)",
            boxShadow: voiceVerified
              ? "0 0 8px rgba(34,197,94,0.4)"
              : "0 0 8px rgba(239,68,68,0.3)",
            transition: "all 500ms",
          }}
        />
      )}

      {/* Heart rate indicator */}
      {bpm && hrQuality === "good" && (
        <div
          title={`Heart Rate: ${bpm} BPM`}
          style={{
            position: "fixed",
            bottom: "165px",
            right: "12px",
            zIndex: 200,
            padding: "4px 10px",
            borderRadius: "12px",
            background: "rgba(239,68,68,0.1)",
            border: "1px solid rgba(239,68,68,0.3)",
            color: "rgba(239,68,68,0.9)",
            fontSize: "0.6rem",
            fontFamily: "'Inter', sans-serif",
            fontWeight: 600,
            letterSpacing: "0.05em",
            display: "flex",
            alignItems: "center",
            gap: "4px",
            backdropFilter: "blur(8px)",
            animation: "pulse 1s ease-in-out infinite",
          }}
        >
          <span style={{ fontSize: "0.7rem" }}>❤️</span> {bpm}
        </div>
      )}

      {/* Fitness HUD */}
      {activeExercise && (
        <div
          style={{
            position: "fixed",
            top: "80px",
            right: "16px",
            zIndex: 200,
            padding: "12px 18px",
            borderRadius: "12px",
            background: "rgba(34,197,94,0.1)",
            border: "1px solid rgba(34,197,94,0.3)",
            backdropFilter: "blur(12px)",
            fontFamily: "'Inter', sans-serif",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: "1.8rem", fontWeight: 700, color: "rgba(34,197,94,0.95)" }}>
            {repCount}
          </div>
          <div style={{ fontSize: "0.55rem", letterSpacing: "0.15em", textTransform: "uppercase", color: "rgba(34,197,94,0.7)" }}>
            {activeExercise} reps
          </div>
          {lastFormTip && (
            <div style={{ fontSize: "0.55rem", color: "rgba(251,191,36,0.9)", marginTop: "4px" }}>
              {lastFormTip}
            </div>
          )}
        </div>
      )}

      {/* Offline LLM status */}
      {llmStatus === "loading" && (
        <div
          style={{
            position: "fixed",
            bottom: "165px",
            left: "16px",
            zIndex: 200,
            padding: "4px 10px",
            borderRadius: "8px",
            background: "rgba(168,85,247,0.1)",
            border: "1px solid rgba(168,85,247,0.3)",
            color: "rgba(168,85,247,0.8)",
            fontSize: "0.55rem",
            fontFamily: "'Inter', sans-serif",
            backdropFilter: "blur(8px)",
          }}
        >
          🧠 Loading offline AI…
        </div>
      )}

      {/* Memory Timeline overlay */}
      {showTimeline && (
        <MemoryTimeline
          timeline={timeline}
          onClose={() => setShowTimeline(false)}
        />
      )}

      {/* Pricing Page overlay */}
      {showPricing && (
        <PricingPage onClose={() => setShowPricing(false)} />
      )}

      {/* Trial / upgrade CTA moved to Header component */}

      {/* Inline animation for heart rate */}
      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.6; }
        }
      `}</style>
    </>
  );
}
