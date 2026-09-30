/**
 * LeftTelemetryHUD — Cybernetic System Vitals, Emotion Radar & Macro Launchpad
 * ============================================================================
 * Glassmorphic HUD displaying real-time cognitive metrics, neural latency,
 * emotional telemetry, and 1-click macro automation triggers.
 */

import React, { memo } from "react";
import { soundFX } from "../../utils/SoundFX";

export const LeftTelemetryHUD = memo(function LeftTelemetryHUD({
  wsStatus = "open",
  emotion = { label: "neutral", confidence: 0.85 },
  tier = "premium",
  onTriggerMacro = null,
}) {
  const handleMacro = (macroName, cmdText) => {
    soundFX.playClick();
    onTriggerMacro?.(cmdText);
  };

  return (
    <aside className="cyber-hud-panel left-hud glass-card">
      {/* ── Section 1: System Vitals & Neural Latency ── */}
      <div className="hud-section">
        <div className="hud-section-header">
          <span className="hud-icon">⚡</span>
          <span className="hud-title">COGNITIVE TELEMETRY</span>
          <span className={`hud-badge ${wsStatus === "open" ? "online" : "offline"}`}>
            {wsStatus === "open" ? "ONLINE" : "OFFLINE"}
          </span>
        </div>

        <div className="telemetry-stat-row">
          <div className="stat-box">
            <span className="stat-label">NEURAL MATRIX</span>
            <span className="stat-val cyan">MJ QUANTUM V3</span>
          </div>
          <div className="stat-box">
            <span className="stat-label">PROCESSING CORE</span>
            <span className="stat-val purple">NEURAL CLUSTER</span>
          </div>
        </div>

        <div className="telemetry-stat-row">
          <div className="stat-box">
            <span className="stat-label">AUDIO ENGINE</span>
            <span className="stat-val green">NATURAL AURA</span>
          </div>
          <div className="stat-box">
            <span className="stat-label">SUBSCRIPTION</span>
            <span className="stat-val gold">{tier.toUpperCase()} EDITION</span>
          </div>
        </div>
      </div>

      {/* ── Section 2: Biometric & Emotion Radar ── */}
      <div className="hud-section">
        <div className="hud-section-header">
          <span className="hud-icon">🧬</span>
          <span className="hud-title">AURA BIOMETRIC RADAR</span>
        </div>

        <div className="emotion-radar-card">
          <div className="emotion-radar-orb">
            <div className={`radar-glow ${emotion?.label || "neutral"}`} />
            <span className="radar-emoji">
              {emotion?.label === "happy" ? "✨" : emotion?.label === "focused" ? "🎯" : emotion?.label === "excited" ? "⚡" : "🌌"}
            </span>
          </div>
          <div className="emotion-meta">
            <span className="emotion-name">{((emotion?.label || "neutral")).toUpperCase()}</span>
            <span className="emotion-desc">
              Confidence: {Math.round((emotion?.confidence || 0.85) * 100)}% • Adaptive Tone Sync
            </span>
          </div>
        </div>
      </div>

      {/* ── Section 3: Macro Automation Launchpad ── */}
      <div className="hud-section">
        <div className="hud-section-header">
          <span className="hud-icon">🚀</span>
          <span className="hud-title">WORKFLOW LAUNCHPAD</span>
        </div>

        <div className="macro-chip-grid">
          <button
            className="macro-chip"
            onClick={() => handleMacro("work_mode", "start work mode")}
          >
            <span className="chip-icon">💼</span>
            <span className="chip-text">Work Mode</span>
          </button>

          <button
            className="macro-chip"
            onClick={() => handleMacro("chill_mode", "chill mode")}
          >
            <span className="chip-icon">🎧</span>
            <span className="chip-text">Chill Mode</span>
          </button>

          <button
            className="macro-chip"
            onClick={() => handleMacro("study_mode", "study mode")}
          >
            <span className="chip-icon">📚</span>
            <span className="chip-text">Deep Study</span>
          </button>

          <button
            className="macro-chip"
            onClick={() => handleMacro("read_screen", "Look at my screen and tell me what you see")}
          >
            <span className="chip-icon">👁️</span>
            <span className="chip-text">Screen Vision</span>
          </button>
        </div>
      </div>
    </aside>
  );
});
