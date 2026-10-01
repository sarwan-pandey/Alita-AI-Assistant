/**
 * DynamicIsland — Morphing Cinematic Top Capsule
 * ===============================================
 * Adaptive spatial island with 6 fluid states:
 * 1. IDLE: Compact sleek capsule with breathing core & active voice badge.
 * 2. PROACTIVE: Expanded contextual intelligence capsule with quick-action chips.
 * 3. LISTENING: Expanded waveform bars with vocal energy visualizer.
 * 4. THINKING: Morphing quantum pulse with orbital particle shimmer.
 * 5. SPEAKING: Live sentence streamer with audio equalizer.
 * 6. ALERT: Notification/warning card.
 */

import React, { memo, useState, useEffect, useRef } from "react";

export const DynamicIsland = memo(function DynamicIsland({
  isListening = false,
  isThinking = false,
  isSpeaking = false,
  voiceActivity = 0,
  emotion = { label: "neutral", confidence: 0.8 },
  activeVoiceName = "MJ (Chatterbox Turbo)",
  activeVoiceId = "chatterbox_turbo_mj",
  streamingText = "",
  alertMessage = "",
  proactiveSuggestion = null,
  onAcceptProactive = null,
  onDismissProactive = null,
  isOnline = false,
  onIslandClick,
}) {
  const [bars, setBars] = useState(Array(14).fill(0.1));
  const animRef = useRef(null);

  // Audio wave animation for Dynamic Island
  useEffect(() => {
    const animate = () => {
      setBars((prev) =>
        prev.map((_, i) => {
          if (isListening || isSpeaking) {
            const base = voiceActivity * 0.7;
            const wave = Math.sin(Date.now() / 180 + i * 0.6) * 0.35;
            const rand = Math.random() * 0.25;
            return Math.max(0.1, Math.min(1.0, base + wave + rand));
          }
          if (isThinking) {
            return 0.2 + Math.sin(Date.now() / 250 + i * 0.5) * 0.2;
          }
          // Idle breathing
          return 0.08 + Math.sin(Date.now() / 1200 + i * 0.4) * 0.05;
        })
      );
      animRef.current = requestAnimationFrame(animate);
    };
    animRef.current = requestAnimationFrame(animate);
    return () => cancelAnimationFrame(animRef.current);
  }, [isListening, isThinking, isSpeaking, voiceActivity]);

  // Determine current active state
  const state = proactiveSuggestion
    ? "proactive"
    : alertMessage
    ? "alert"
    : isListening
    ? "listening"
    : isThinking
    ? "thinking"
    : isSpeaking
    ? "speaking"
    : "idle";

  // Color mapping based on emotion and state
  const getGlowColor = () => {
    if (state === "proactive") return "rgba(14, 165, 233, 0.5)";
    if (state === "alert") return "rgba(245, 158, 11, 0.4)";
    if (state === "listening") return "rgba(52, 211, 153, 0.45)";
    if (state === "thinking") return "rgba(168, 85, 247, 0.45)";
    if (state === "speaking") return "rgba(56, 189, 248, 0.45)";
    return "rgba(56, 189, 248, 0.15)";
  };

  const getStatusText = () => {
    if (state === "proactive") return proactiveSuggestion.title || "Jarvis Insight";
    if (state === "alert") return alertMessage;
    if (state === "listening") return "Listening…";
    if (state === "thinking") return "Processing…";
    if (state === "speaking") return "MJ Speaking";
    return "NATURAL AUDIO";
  };

  // If in proactive mode, render the interactive autonomous capsule
  if (state === "proactive" && proactiveSuggestion) {
    return (
      <div
        className="dynamic-island-wrapper proactive-mode"
        style={{
          boxShadow: `0 8px 32px -4px ${getGlowColor()}, 0 0 24px 0 ${getGlowColor()}`,
          maxWidth: "640px",
          width: "90%",
        }}
      >
        <div className="dynamic-island-content proactive-content">
          <div className="island-left">
            <div className="island-core-dot proactive">
              <div className="island-core-inner" />
            </div>
            <div className="proactive-text-block">
              <span className="proactive-badge-tag">AUTONOMOUS INSIGHT</span>
              <p className="proactive-message">{proactiveSuggestion.message}</p>
            </div>
          </div>

          <div className="proactive-actions">
            <button
              className="proactive-btn accept"
              onClick={(e) => {
                e.stopPropagation();
                onAcceptProactive?.(proactiveSuggestion);
              }}
            >
              ✓ {proactiveSuggestion.action_label || "Accept"}
            </button>
            <button
              className="proactive-btn dismiss"
              onClick={(e) => {
                e.stopPropagation();
                onDismissProactive?.(proactiveSuggestion);
              }}
            >
              ✕ {proactiveSuggestion.dismiss_label || "Dismiss"}
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div
      className={`dynamic-island-wrapper ${state}`}
      onClick={onIslandClick}
      style={{
        boxShadow: `0 8px 32px -4px ${getGlowColor()}, 0 0 20px 0 ${getGlowColor()}`,
      }}
    >
      <div className="dynamic-island-content">
        {/* Left: Indicator Icon or Core Dot */}
        <div className="island-left">
          <div className={`island-core-dot ${state}`}>
            <div className="island-core-inner" />
          </div>
          <span className="island-title">MJ</span>
        </div>

        {/* Center: Waveform Equalizer or Thinking Spinner */}
        <div className="island-center">
          {state === "thinking" ? (
            <div className="island-thinking-spinner">
              <span className="thinking-dot dot-1" />
              <span className="thinking-dot dot-2" />
              <span className="thinking-dot dot-3" />
            </div>
          ) : (
            <div className="island-wave-bars">
              {bars.map((h, i) => (
                <div
                  key={i}
                  className="island-bar"
                  style={{
                    height: `${Math.max(4, h * 24)}px`,
                    background:
                      state === "listening"
                        ? "#34d399"
                        : state === "speaking"
                        ? "#38bdf8"
                        : "rgba(255, 255, 255, 0.3)",
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {/* Right: State Label & Voice Engine Badge */}
        <div className="island-right">
          <span className="island-status-badge">{getStatusText()}</span>
          <div className={`island-tag ${isOnline ? "online" : "offline"}`}>
            {isOnline ? "ONLINE" : "OFFLINE"}
          </div>
        </div>
      </div>
    </div>
  );
});
