/**
 * ScreenHighlightOverlay — Interactive Multimodal Screen Pointer HUD
 * =================================================================
 * Renders high-precision glowing cybernetic bounding boxes, crosshairs,
 * and animated pointer vectors over target screen elements.
 */

import React, { memo, useEffect, useState } from "react";

export const ScreenHighlightOverlay = memo(function ScreenHighlightOverlay({
  highlightData = null,
  somMarks = [],
  activeMark = null,
  onDismiss = null,
}) {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if ((highlightData && highlightData.found) || (somMarks && somMarks.length > 0)) {
      setVisible(true);
      const timer = setTimeout(() => {
        setVisible(false);
        onDismiss?.();
      }, 10000);
      return () => clearTimeout(timer);
    } else {
      setVisible(false);
    }
  }, [highlightData, somMarks, onDismiss]);

  if (!visible) return null;

  return (
    <div
      className="screen-highlight-backdrop"
      style={{
        position: "fixed",
        inset: 0,
        pointerEvents: "none",
        zIndex: 9999,
        background: somMarks.length > 0 ? "rgba(0, 5, 16, 0.25)" : "transparent",
        backdropFilter: somMarks.length > 0 ? "blur(2px)" : "none",
        transition: "all 0.3s cubic-bezier(0.16, 1, 0.3, 1)",
      }}
      onClick={() => {
        setVisible(false);
        onDismiss?.();
      }}
    >
      {/* Legacy / Single Target Reticle */}
      {highlightData && highlightData.found && (
        <div
          className="screen-target-bracket"
          style={{
            left: `${(highlightData.x ?? 0.5) * 100}%`,
            top: `${(highlightData.y ?? 0.45) * 100}%`,
            width: `${Math.max(8, (highlightData.width ?? 0.15) * 100)}%`,
            height: `${Math.max(6, (highlightData.height ?? 0.08) * 100)}%`,
            transform: "translate(-50%, -50%)",
            position: "absolute",
          }}
        >
          <div className="reticle-corner top-left" />
          <div className="reticle-corner top-right" />
          <div className="reticle-corner bottom-left" />
          <div className="reticle-corner bottom-right" />
          <div className="reticle-pulse-box" />
          <div className="reticle-label-pill">
            <span className="reticle-dot" />
            <span className="reticle-text">{highlightData.label || "Target"}</span>
          </div>
        </div>
      )}

      {/* Set-of-Marks (SoM) Numbered Badges & Interactive Targets */}
      {somMarks && somMarks.map((mark) => {
        const isActive = activeMark && activeMark.markId === mark.id;
        const leftPct = (mark.x ?? 0.5) * 100;
        const topPct = (mark.y ?? 0.5) * 100;
        const wPct = Math.max(3, (mark.w ?? 0.05) * 100);
        const hPct = Math.max(2, (mark.h ?? 0.03) * 100);

        return (
          <div
            key={mark.id}
            className={`som-mark-container ${isActive ? "active-action" : ""}`}
            style={{
              position: "absolute",
              left: `${leftPct}%`,
              top: `${topPct}%`,
              width: `${wPct}%`,
              height: `${hPct}%`,
              transform: "translate(-50%, -50%)",
              border: isActive ? "2px solid #00f0ff" : "1px solid rgba(0, 240, 255, 0.4)",
              borderRadius: "6px",
              boxShadow: isActive
                ? "0 0 25px rgba(0, 240, 255, 0.8), inset 0 0 15px rgba(0, 240, 255, 0.3)"
                : "0 0 8px rgba(0, 240, 255, 0.2)",
              pointerEvents: "auto",
              cursor: "pointer",
              transition: "all 0.25s ease",
            }}
          >
            {/* Cyber Badge Tag [ID] */}
            <div
              style={{
                position: "absolute",
                top: "-18px",
                left: "-2px",
                background: isActive ? "#00f0ff" : "rgba(10, 15, 30, 0.9)",
                color: isActive ? "#000" : "#00f0ff",
                border: "1px solid #00f0ff",
                borderRadius: "3px",
                fontSize: "11px",
                fontWeight: "700",
                fontFamily: "monospace",
                padding: "1px 5px",
                display: "flex",
                alignItems: "center",
                gap: "4px",
                whiteSpace: "nowrap",
                zIndex: 10,
              }}
            >
              <span>{mark.id}</span>
              {isActive && (
                <span style={{ fontSize: "9px", opacity: 0.8 }}>
                  ⚡ {activeMark.action || "ACT"}
                </span>
              )}
            </div>

            {/* Element Name Tooltip */}
            {mark.name && (
              <div
                style={{
                  position: "absolute",
                  bottom: "-20px",
                  left: "0",
                  background: "rgba(0, 0, 0, 0.75)",
                  color: "#e2e8f0",
                  fontSize: "10px",
                  padding: "1px 6px",
                  borderRadius: "3px",
                  whiteSpace: "nowrap",
                  maxWidth: "140px",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  pointerEvents: "none",
                }}
              >
                {mark.name}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
});
