/**
 * CentralOrb — Hyper-Complex 3D Twisted Möbius Wireframe AI Crystal
 * =================================================================
 * High-End 3D Parametric Ribbon Architecture:
 * - Dual interwoven 3D twisting ribbons (Cyan/White Helix & Magenta/Peach Counter-Helix)
 * - 28 longitudinal frequency streamlines + 48 transverse cross-ribs forming a 3D wireframe lattice
 * - Genuine 3D depth rendering: z-scaled perspective projection, front-face specular highlights, back-face depth occlusion
 * - Luminous central plasma energy collision core
 * - Photorealistic crystal glass sphere with refractive caustic highlights & soap-bubble rainbow rim
 */

import React, { memo, useState, useEffect, useRef } from "react";
import { audioStreamPlayer } from "../../utils/AudioStreamPlayer";

export const CentralOrb = memo(function CentralOrb({
  isListening = false,
  isThinking = false,
  isSpeaking = false,
  voiceActivity = 0,
  showStatusPill = true,
  onClick,
}) {
  const canvasRef = useRef(null);
  const [listenTimer, setListenTimer] = useState(0);

  const state = isThinking
    ? "thinking"
    : isSpeaking
    ? "speaking"
    : isListening
    ? "listening"
    : "idle";

  const stateRef = useRef(state);
  const voiceActivityRef = useRef(voiceActivity);

  useEffect(() => {
    stateRef.current = state;
    voiceActivityRef.current = voiceActivity;
  }, [state, voiceActivity]);

  useEffect(() => {
    let interval = null;
    if (isListening) {
      setListenTimer(0);
      interval = setInterval(() => setListenTimer((c) => c + 1), 1000);
    } else {
      setListenTimer(0);
    }
    return () => clearInterval(interval);
  }, [isListening]);

  // ── 60FPS 3D Twisted Möbius Wireframe Loop ────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let animId;
    let t = 0;

    const size = 380;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    canvas.style.width = `${size}px`;
    canvas.style.height = `${size}px`;
    ctx.scale(dpr, dpr);

    const cx = size / 2;
    const cy = size / 2;
    const radius = 132;

    const render = () => {
      t += 0.02;
      const curState = stateRef.current;
      const vAct = voiceActivityRef.current || 0;

      // Real-time audio reactivity from output speech + input mic
      const outVol = audioStreamPlayer.getAudioVolume();
      const freqs = audioStreamPlayer.getAudioFrequencies();
      const dynamicVol = Math.max(vAct, outVol * 1.6);
      const isVoiceActive = dynamicVol > 0.03;

      ctx.clearRect(0, 0, size, size);

      const speed = curState === "thinking"
        ? 0.048
        : isVoiceActive
        ? 0.025 + dynamicVol * 0.04
        : 0.018;

      const waveEnergy = isVoiceActive
        ? 0.95 + dynamicVol * 2.0
        : curState === "speaking" || curState === "listening"
        ? 1.05
        : 0.85;

      // ── 1. Outer Chromatic Dispersion Atmosphere ──────────────────────────
      const outerHalo = ctx.createRadialGradient(cx, cy, radius * 0.75, cx, cy, radius * 1.55);
      const haloOpacity = curState === "speaking" ? 0.4 : curState === "listening" ? 0.3 + vAct * 0.32 : 0.22;
      outerHalo.addColorStop(0, `rgba(168, 85, 247, ${haloOpacity * 0.8})`);
      outerHalo.addColorStop(0.5, `rgba(0, 245, 255, ${haloOpacity * 0.55})`);
      outerHalo.addColorStop(0.85, `rgba(236, 72, 153, ${haloOpacity * 0.3})`);
      outerHalo.addColorStop(1, "rgba(0, 0, 0, 0)");

      ctx.fillStyle = outerHalo;
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 1.55, 0, Math.PI * 2);
      ctx.fill();

      // ── 2. Translucent Crystal Sphere Interior ────────────────────────────
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.clip(); // Keep all 3D ribbons inside crystal bubble

      // Luminous dark crystal background gradient
      const crystalBackdrop = ctx.createRadialGradient(cx, cy - 30, 10, cx, cy, radius);
      crystalBackdrop.addColorStop(0, "rgba(22, 32, 64, 0.4)");
      crystalBackdrop.addColorStop(0.55, "rgba(8, 12, 28, 0.72)");
      crystalBackdrop.addColorStop(1, "rgba(2, 4, 14, 0.92)");
      ctx.fillStyle = crystalBackdrop;
      ctx.fillRect(0, 0, size, size);

      // ── 3. Central Radiant Energy Singularity ─────────────────────────────
      const coreRadiance = ctx.createRadialGradient(cx, cy, 4, cx, cy, radius * 0.65);
      const coreAlpha = 0.32 * waveEnergy;
      coreRadiance.addColorStop(0, `rgba(255, 255, 255, ${coreAlpha * 1.4})`);
      coreRadiance.addColorStop(0.25, `rgba(251, 146, 60, ${coreAlpha * 0.9})`);
      coreRadiance.addColorStop(0.55, `rgba(168, 85, 247, ${coreAlpha * 0.5})`);
      coreRadiance.addColorStop(1, "rgba(0, 0, 0, 0)");
      ctx.fillStyle = coreRadiance;
      ctx.beginPath();
      ctx.arc(cx, cy, radius * 0.65, 0, Math.PI * 2);
      ctx.fill();

      // ── 4. Hyper-Complex 3D Parametric Möbius Ribbon Lattice ──────────────
      ctx.save();
      ctx.globalCompositeOperation = "screen";

      // Mathematical function to compute 3D coordinate along ribbon
      // u: normalized horizontal parameter (-1.0 to 1.0)
      // strandOffset: phase offset between the two helical ribbons
      const compute3DPoint = (u, strandOffset, vOffset) => {
        const span = radius * 0.94;
        const x3d = u * span;
        const envelope = Math.max(0, 1 - Math.pow(u, 2)); // Pinch smoothly at rims

        // Real-time spectral vibration from voice frequency bands
        let freqPerturbation = 0;
        if (freqs && freqs.length > 0) {
          const fBin = Math.min(freqs.length - 1, Math.floor(((u + 1.0) / 2.0) * freqs.length));
          freqPerturbation = (freqs[fBin] / 255) * 14 * Math.sin(u * 14 + t * 3.5);
        }

        // Harmonic dual-frequency wave equations
        const y3d =
          ((Math.sin(t * speed * 52 + u * 3.4 + strandOffset) * 28 +
           Math.cos(t * speed * 36 - u * 2.2 + strandOffset * 0.5) * 16 +
           vOffset * (18 * envelope)) * waveEnergy + freqPerturbation) * envelope;

        // 3D depth z (front/back oscillation)
        const z3d =
          (Math.cos(t * speed * 48 + u * 3.0 + strandOffset) * 45 +
           Math.sin(t * speed * 28 - u * 1.8) * 20) * envelope;

        // Perspective 3D projection
        const fov = 320;
        const scale = fov / (fov + z3d);
        const projX = cx + x3d * scale;
        const projY = cy + y3d * scale;

        return { x: projX, y: projY, z: z3d, scale, envelope };
      };

      // Ribbons to render: Primary Helix (Cyan/Sky) and Secondary Helix (Magenta/Peach)
      const ribbons = [
        {
          strandOffset: 0,
          colorLead: "rgba(0, 245, 255,",
          colorMid: "rgba(56, 189, 248,",
          colorEnd: "rgba(255, 255, 255,",
          numLines: 14,
        },
        {
          strandOffset: Math.PI * 0.85, // Intertwining counter-helix
          colorLead: "rgba(236, 72, 153,",
          colorMid: "rgba(168, 85, 247,",
          colorEnd: "rgba(251, 146, 60,",
          numLines: 14,
        },
      ];

      ribbons.forEach((ribbon) => {
        const uSteps = 36;
        const gridPoints = [];

        // Generate 2D array of projected 3D points for longitudinal streamlines
        for (let l = 0; l < ribbon.numLines; l++) {
          const normL = l / (ribbon.numLines - 1); // -0.5 to 0.5
          const vOff = (normL - 0.5) * 2.0;
          const linePts = [];

          for (let s = 0; s <= uSteps; s++) {
            const u = -1.0 + (s / uSteps) * 2.0;
            const pt = compute3DPoint(u, ribbon.strandOffset, vOff);
            linePts.push(pt);
          }
          gridPoints.push(linePts);
        }

        // Draw Transverse Cross-Ribs (Rungs of the 3D wireframe ribbon)
        const crossStep = 2;
        for (let s = 2; s < uSteps - 2; s += crossStep) {
          const topPt = gridPoints[0][s];
          const botPt = gridPoints[ribbon.numLines - 1][s];
          const avgZ = (topPt.z + botPt.z) / 2;
          const zDepthNorm = Math.max(0.2, Math.min(1.0, (avgZ + 45) / 90)); // 0.2 (back) to 1.0 (front)

          ctx.beginPath();
          ctx.strokeStyle = `${ribbon.colorMid} ${zDepthNorm * 0.45})`;
          ctx.lineWidth = 0.9 * topPt.scale;
          ctx.moveTo(topPt.x, topPt.y);
          ctx.lineTo(botPt.x, botPt.y);
          ctx.stroke();
        }

        // Draw Longitudinal Streamlines with 3D Depth Shading (Zero CPU ShadowBlur)
        gridPoints.forEach((linePts, lIdx) => {
          const normL = lIdx / (ribbon.numLines - 1);
          ctx.beginPath();

          for (let s = 0; s <= uSteps; s++) {
            const pt = linePts[s];
            if (s === 0) {
              ctx.moveTo(pt.x, pt.y);
            } else {
              ctx.lineTo(pt.x, pt.y);
            }
          }

          // Sample midpoint for depth lighting
          const midPt = linePts[Math.floor(uSteps / 2)];
          const zDepthNorm = Math.max(0.25, Math.min(1.0, (midPt.z + 45) / 90));

          let strokeColor;
          if (normL > 0.85) {
            strokeColor = `${ribbon.colorEnd} ${zDepthNorm * 0.95})`; // Specular crest
            ctx.lineWidth = 2.0 * midPt.scale;
          } else if (normL < 0.4) {
            strokeColor = `${ribbon.colorLead} ${zDepthNorm * 0.85})`;
            ctx.lineWidth = 1.4 * midPt.scale;
          } else {
            strokeColor = `${ribbon.colorMid} ${zDepthNorm * 0.75})`;
            ctx.lineWidth = 1.2 * midPt.scale;
          }

          ctx.strokeStyle = strokeColor;
          ctx.stroke();
        });
      });

      ctx.restore(); // end screen composite

      // ── 5. Photorealistic 3D Glass Specular Reflection ────────────────────
      // Curved upper-left softbox Fresnel highlight
      const specHighlight = ctx.createRadialGradient(cx - 38, cy - 44, 3, cx - 28, cy - 34, 82);
      specHighlight.addColorStop(0, "rgba(255, 255, 255, 0.78)");
      specHighlight.addColorStop(0.28, "rgba(255, 255, 255, 0.22)");
      specHighlight.addColorStop(0.8, "rgba(255, 255, 255, 0.04)");
      specHighlight.addColorStop(1, "rgba(255, 255, 255, 0)");
      ctx.fillStyle = specHighlight;
      ctx.beginPath();
      ctx.ellipse(cx - 40, cy - 40, 64, 36, -Math.PI / 4.2, 0, Math.PI * 2);
      ctx.fill();

      // Sharp pinpoint caustic reflection
      ctx.fillStyle = "rgba(255, 255, 255, 0.95)";
      ctx.beginPath();
      ctx.arc(cx - 52, cy - 48, 4.5, 0, Math.PI * 2);
      ctx.fill();

      // Ambient lower-right bounce reflection (warm violet/cyan)
      const bounceReflect = ctx.createRadialGradient(cx + 32, cy + 48, 6, cx + 32, cy + 48, 70);
      bounceReflect.addColorStop(0, "rgba(168, 85, 247, 0.38)");
      bounceReflect.addColorStop(0.55, "rgba(0, 245, 255, 0.16)");
      bounceReflect.addColorStop(1, "rgba(0, 0, 0, 0)");
      ctx.fillStyle = bounceReflect;
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);
      ctx.fill();

      ctx.restore(); // end sphere clip

      // ── 6. Thin-Film Soap-Bubble Iridescent Rainbow Rim ───────────────────
      ctx.save();
      ctx.beginPath();
      ctx.arc(cx, cy, radius, 0, Math.PI * 2);

      const rimGrad = ctx.createConicGradient(t * 0.38, cx, cy);
      rimGrad.addColorStop(0.0, "rgba(0, 245, 255, 0.95)"); // Cyan
      rimGrad.addColorStop(0.22, "rgba(255, 255, 255, 0.98)"); // White specular
      rimGrad.addColorStop(0.45, "rgba(168, 85, 247, 0.92)"); // Violet
      rimGrad.addColorStop(0.7, "rgba(236, 72, 153, 0.9)"); // Pink
      rimGrad.addColorStop(0.88, "rgba(251, 146, 60, 0.88)"); // Peach
      rimGrad.addColorStop(1.0, "rgba(0, 245, 255, 0.95)");

      ctx.strokeStyle = rimGrad;
      ctx.lineWidth = 3.0;
      ctx.shadowColor = "rgba(0, 245, 255, 0.85)";
      ctx.shadowBlur = 22;
      ctx.stroke();
      ctx.restore();

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => cancelAnimationFrame(animId);
  }, []);

  return (
    <div className={`central-nebula-sphere-wrapper state-${state}`} onClick={onClick}>
      {/* 3D Crystal Glass Sphere Canvas */}
      <canvas ref={canvasRef} className="nebula-sphere-canvas" />

      {/* Floating Status Beacon */}
      {showStatusPill && (
        <div className="nebula-status-pill">
          <span className={`status-pill-beacon beacon-${state}`} />
          <span className="status-pill-label">
            {state === "listening"
              ? `LISTENING ${String(Math.floor(listenTimer / 60)).padStart(2, "0")}:${String(listenTimer % 60).padStart(2, "0")}`
              : state.toUpperCase()}
          </span>
        </div>
      )}
    </div>
  );
});
