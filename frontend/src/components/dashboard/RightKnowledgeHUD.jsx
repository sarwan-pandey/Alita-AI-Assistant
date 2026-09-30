/**
 * RightKnowledgeHUD — Workspace Intelligence & Instant Smart Prompts
 * =================================================================
 * Glassmorphic HUD panel displaying real-time context nodes and
 * interactive smart prompt chips.
 */

import React, { memo } from "react";
import { soundFX } from "../../utils/SoundFX";

export const RightKnowledgeHUD = memo(function RightKnowledgeHUD({
  messages = [],
  onSendPrompt = null,
  onOpenKnowledgeDrawer = null,
}) {
  const handleQuickPrompt = (text) => {
    soundFX.playClick();
    onSendPrompt?.(text);
  };

  return (
    <aside className="cyber-hud-panel right-hud glass-card">
      {/* ── Section 1: Context & Workspace Intelligence ── */}
      <div className="hud-section">
        <div className="hud-section-header">
          <span className="hud-icon">🧠</span>
          <span className="hud-title">WORKSPACE INTELLIGENCE</span>
          <span className="hud-badge online">SYNCED</span>
        </div>

        <div className="memory-stream-card">
          <div className="memory-node active">
            <span className="node-dot cyan" />
            <div className="node-content">
              <span className="node-title">Context & Preferences</span>
              <span className="node-snippet">
                User preferences & workspace profile active
              </span>
            </div>
          </div>

          <div className="memory-node">
            <span className="node-dot purple" />
            <div className="node-content">
              <span className="node-title">Autonomic Intelligence</span>
              <span className="node-snippet">
                Situational awareness & ambient monitoring armed
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Section 2: Smart Command Chips ── */}
      <div className="hud-section">
        <div className="hud-section-header">
          <span className="hud-icon">✨</span>
          <span className="hud-title">QUICK PROMPTS</span>
        </div>

        <div className="quick-prompts-list">
          <button
            className="quick-prompt-btn"
            onClick={() => handleQuickPrompt("What are we working on?")}
          >
            <span>"What are we working on?"</span>
          </button>
          <button
            className="quick-prompt-btn"
            onClick={() => handleQuickPrompt("Play some lofi chill music")}
          >
            <span>"Play some lofi chill music"</span>
          </button>
          <button
            className="quick-prompt-btn"
            onClick={() => handleQuickPrompt("Take a screenshot and summarize my screen")}
          >
            <span>"Summarize what is on my screen"</span>
          </button>
        </div>
      </div>
    </aside>
  );
});
