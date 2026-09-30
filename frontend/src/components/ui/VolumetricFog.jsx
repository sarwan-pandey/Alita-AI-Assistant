/**
 * VolumetricFog — Ethereal Drifting Cosmic Fog & Volumetric Cloud Layers
 * ======================================================================
 * Renders multiple continuous drifting volumetric cloud banks and misty aurora
 * fog layers using hardware-accelerated SVG turbulence & ambient chromatic glow.
 */

import React, { memo } from "react";

export const VolumetricFog = memo(function VolumetricFog({
  isSpeaking = false,
  isListening = false,
}) {
  return (
    <div
      className={`volumetric-fog-container ${isSpeaking ? "illuminated-speaking" : ""} ${
        isListening ? "illuminated-listening" : ""
      }`}
      aria-hidden="true"
    >
      {/* ── Layer 1: Deep Ambient Mist Cloud (Bottom & Edges) ── */}
      <div className="fog-layer fog-layer-deep" />

      {/* ── Layer 2: Drifting Ethereal Cloud Bank (Left to Right) ── */}
      <div className="fog-layer fog-layer-mid-1" />

      {/* ── Layer 3: Drifting Cosmic Nebula Mist (Right to Left) ── */}
      <div className="fog-layer fog-layer-mid-2" />

      {/* ── Layer 4: Floating Organic Light Cloud Wisps (Top & Center) ── */}
      <div className="fog-layer fog-layer-light" />

      {/* ── Procedural SVG Noise Filter for Organic Fog Texture ── */}
      <svg className="fog-noise-svg" style={{ display: "none" }}>
        <filter id="organic-fog-filter">
          <feTurbulence
            type="fractalNoise"
            baseFrequency="0.012"
            numOctaves="4"
            stitchTiles="stitch"
          />
          <feColorMatrix
            type="matrix"
            values="1 0 0 0 0  0 1 0 0 0  0 0 1 0 0  0 0 0 0.45 0"
          />
        </filter>
      </svg>
    </div>
  );
});
