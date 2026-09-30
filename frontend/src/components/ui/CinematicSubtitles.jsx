/**
 * CinematicSubtitles — Floating Kinetic Audio-Synced Subtitles
 * ============================================================
 * Displays streaming words from Alita with glowing highlight
 * and smooth fade-in/fade-out animations.
 */

import React, { memo, useState, useEffect } from "react";

export const CinematicSubtitles = memo(function CinematicSubtitles({
  text = "",
  role = "assistant", // "assistant" | "user"
  isSpeaking = false,
  isThinking = false,
  onDismiss,
}) {
  const [visible, setVisible] = useState(false);
  const [displayText, setDisplayText] = useState("");

  useEffect(() => {
    if (text && text.trim()) {
      setDisplayText(text);
      setVisible(true);
    } else if (!isSpeaking && !isThinking) {
      const timer = setTimeout(() => setVisible(false), 5000);
      return () => clearTimeout(timer);
    }
  }, [text, isSpeaking, isThinking]);

  if (!visible || !displayText) return null;

  return (
    <div className={`cinematic-subtitles-container ${role}`}>
      <div className="subtitles-card">
        <div className="subtitles-header">
          <span className="subtitles-speaker">
            {role === "assistant" ? "✨ MJ" : "👤 YOU"}
          </span>
          <button
            className="subtitles-close-btn"
            onClick={() => setVisible(false)}
            title="Dismiss subtitles"
          >
            ✕
          </button>
        </div>
        <div className="subtitles-body">
          <p className="subtitles-text">{displayText}</p>
        </div>
      </div>
    </div>
  );
});
