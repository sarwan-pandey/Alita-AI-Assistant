import React, { useState, useEffect, useRef, useCallback } from "react";
import { CentralOrb } from "../dashboard/CentralOrb";

/**
 * HolographicOverlay.jsx — Pure Borderless 3D Crystal Orb Desktop Overlay
 * ======================================================================
 * 100% Borderless, Frameless, and Boundary-Free.
 * - Zero title bar, zero minimize/maximize/close buttons.
 * - Zero background cards, zero banners, zero subtitle boxes, zero visualizer bars.
 * - Displays ONLY the 3D Möbius Iridescent Crystal Orb floating on the desktop.
 * - Fully activated and listening right from startup.
 * - Drag-to-reposition anywhere across screens.
 * - Click to toggle mic / voice barge-in.
 * - Double-click to expand into the full Sovereign Nebula Command Center.
 */
export function HolographicOverlay({
  onMaximize,
  wsStatus = "open",
  isListening = true,
  isThinking = false,
  isSpeaking = false,
  voiceActivity = 0,
  onToggleMic,
  sendBargeIn,
  contextChips = [],
  onSelectChip,
}) {
  const containerRef = useRef(null);
  const [isHovered, setIsHovered] = useState(false);
  const dragRef = useRef({ isDragging: false, startX: 0, startY: 0, winX: 0, winY: 0 });

  // Handle native window dragging for non-app-region hosts (e.g. browser popups)
  const handleMouseDown = useCallback((e) => {
    // Only drag on primary mouse button
    if (e.button !== 0) return;
    dragRef.current = {
      isDragging: true,
      startX: e.screenX,
      startY: e.screenY,
      winX: window.screenX || 0,
      winY: window.screenY || 0,
    };
  }, []);

  useEffect(() => {
    const handleMouseMove = (e) => {
      if (!dragRef.current.isDragging) return;
      const dx = e.screenX - dragRef.current.startX;
      const dy = e.screenY - dragRef.current.startY;
      try {
        window.moveTo(dragRef.current.winX + dx, dragRef.current.winY + dy);
      } catch (_) {}
    };

    const handleMouseUp = () => {
      dragRef.current.isDragging = false;
    };

    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  }, []);

  const handleOrbClick = (e) => {
    e.stopPropagation();
    if (isSpeaking) {
      sendBargeIn?.();
    } else {
      onToggleMic?.();
    }
  };

  return (
    <div
      ref={containerRef}
      className="pure-crystal-overlay"
      onMouseDown={handleMouseDown}
      onDoubleClick={(e) => {
        e.stopPropagation();
        onMaximize?.();
      }}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      title="MJ AI Assistant • Click to mute/unmute • Double-click to expand • Drag to move"
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 99999,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        background: "transparent",
        backgroundColor: "transparent",
        boxShadow: "none",
        border: "none",
        outline: "none",
        userSelect: "none",
        WebkitUserSelect: "none",
        cursor: "grab",
        WebkitAppRegion: "drag",
        overflow: "hidden",
      }}
    >
      {/* ── ONLY THE 3D MÖBIUS CRYSTAL ORB ── */}
      <div
        onClick={handleOrbClick}
        style={{
          position: "relative",
          width: "380px",
          height: "380px",
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          transition: "transform 350ms cubic-bezier(0.16, 1, 0.3, 1)",
          transform: isHovered ? "scale(1.03)" : "scale(1)",
          cursor: "pointer",
          WebkitAppRegion: "no-drag", // Ensure clicks hit the orb cleanly
        }}
      >
        <CentralOrb
          isListening={isListening}
          isThinking={isThinking}
          isSpeaking={isSpeaking}
          voiceActivity={voiceActivity}
          wsStatus={wsStatus}
          showStatusPill={false}
        />
      </div>

      {/* ── Context-Aware Screen Snapping Chips ── */}
      {contextChips && contextChips.length > 0 && isHovered && (
        <div
          style={{
            position: "absolute",
            bottom: "16px",
            display: "flex",
            gap: "8px",
            flexWrap: "wrap",
            justifyContent: "center",
            maxWidth: "340px",
            zIndex: 100,
            WebkitAppRegion: "no-drag",
            animation: "fadeIn 0.25s ease-out",
          }}
          onClick={(e) => e.stopPropagation()}
        >
          {contextChips.map((chip, idx) => (
            <button
              key={idx}
              onClick={(e) => {
                e.stopPropagation();
                onSelectChip?.(chip);
              }}
              style={{
                background: "rgba(10, 15, 30, 0.85)",
                border: "1px solid rgba(0, 240, 255, 0.4)",
                color: "#e2e8f0",
                padding: "4px 10px",
                borderRadius: "12px",
                fontSize: "11px",
                fontWeight: 500,
                cursor: "pointer",
                backdropFilter: "blur(8px)",
                boxShadow: "0 2px 10px rgba(0,0,0,0.5)",
                transition: "all 0.2s ease",
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.borderColor = "#00f0ff";
                e.currentTarget.style.color = "#00f0ff";
                e.currentTarget.style.transform = "translateY(-1px)";
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.borderColor = "rgba(0, 240, 255, 0.4)";
                e.currentTarget.style.color = "#e2e8f0";
                e.currentTarget.style.transform = "translateY(0)";
              }}
            >
              ✦ {chip}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
