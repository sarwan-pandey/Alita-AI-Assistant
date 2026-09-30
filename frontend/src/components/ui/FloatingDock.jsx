/**
 * FloatingDock — Apple Intelligence / OpenAI Voice Minimalist Pill Dock
 * ======================================================================
 * 1:1 Match for Style 1: "Sovereign Nebula" Concept Art:
 * - Frosted pill buttons with subtle 1px border and soft shadows
 * - [ ⚙️ Settings ] | [ 💬 Conversations ] | [ 🎤 Push-to-Talk / Barge-in ] | [ 👁️ Vision ] | [ 👤 Account ]
 */

import React, { memo } from "react";

export const FloatingDock = memo(function FloatingDock({
  isListening = false,
  isSpeaking = false,
  onToggleMic,
  onTriggerVision,
  onOpenConversations,
  onOpenStudio,
  onOpenAccount,
  onOpenPhone,
}) {
  return (
    <div className="nebula-bottom-dock-container">
      {/* Settings Pill */}
      <button
        className="nebula-dock-pill"
        onClick={onOpenStudio}
        title="Settings & Voice Studio"
      >
        <span className="dock-pill-icon">⚙️</span>
        <span className="dock-pill-label">Settings</span>
      </button>

      {/* Conversations / Chat History Pill */}
      <button
        className="nebula-dock-pill"
        onClick={onOpenConversations}
        title="Conversations & Chat History"
      >
        <span className="dock-pill-icon">💬</span>
        <span className="dock-pill-label">Conversations</span>
      </button>

      {/* Center Hero Mic Pill */}
      <button
        className={`nebula-dock-hero ${isListening ? "listening" : ""} ${isSpeaking ? "speaking" : ""}`}
        onClick={onToggleMic}
        title={
          isSpeaking
            ? "Interrupt MJ (Barge-in)"
            : isListening
            ? "Stop listening"
            : "Start speaking"
        }
      >
        <span className="dock-hero-glow" />
        <span className="dock-hero-icon">
          {isSpeaking ? "🛑" : isListening ? "🔊" : "🎤"}
        </span>
      </button>

      {/* Screen Vision Pill */}
      <button
        className="nebula-dock-pill"
        onClick={onTriggerVision}
        title="Inspect Screen"
      >
        <span className="dock-pill-icon">👁️</span>
        <span className="dock-pill-label">Vision</span>
      </button>

      {/* Mobile Phone Companion Pill */}
      <button
        className="nebula-dock-pill"
        onClick={onOpenPhone}
        title="Phone Companion & Automation"
      >
        <span className="dock-pill-icon">📱</span>
        <span className="dock-pill-label">Phone</span>
      </button>

      {/* Account / Subscription Pill */}
      <button
        className="nebula-dock-pill"
        onClick={onOpenAccount}
        title="Account & Subscription"
      >
        <span className="dock-pill-icon">👤</span>
        <span className="dock-pill-label">Account</span>
      </button>
    </div>
  );
});
