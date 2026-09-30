/**
 * SovereignNebulaEdge — Multi-Strand Sinuous 3D Silk Ribbon with Floating Starlets
 * ==============================================================================
 * Hyper-complex Apple Intelligence perimeter light architecture:
 * - 3 intertwined, independent ribbon strands that twist, cross over, and weave in 3D space
 * - Strand A (Cyan/Sky-Blue), Strand B (Hot Magenta/Rose), Strand C (Neon Violet/Golden Peach)
 * - Multi-octave Fourier harmonics creating organic folding layers with highlights & shadows
 * - 40 drifting luminous photon starlets floating along the energy streams
 * - Audio-reactive expansion, turbulence, and speed scaling on vocal activity
 */

import React, { memo, useEffect, useRef } from "react";

export const SovereignNebulaEdge = memo(function SovereignNebulaEdge({
  isListening = false,
  isThinking = false,
  isSpeaking = false,
  voiceActivity = 0,
}) {
  const canvasRef = useRef(null);
  const stateRef = useRef({ isListening, isThinking, isSpeaking, voiceActivity });

  useEffect(() => {
    stateRef.current = { isListening, isThinking, isSpeaking, voiceActivity };
  }, [isListening, isThinking, isSpeaking, voiceActivity]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    let animId;
    let t = 0;

    // Drifting luminous photon particles
    const numParticles = 42;
    const particles = Array.from({ length: numParticles }, (_, i) => ({
      theta: (i / numParticles) * Math.PI * 2,
      speed: 0.0008 + Math.random() * 0.0016,
      size: 1.5 + Math.random() * 2.8,
      strandIdx: i % 3,
      pulseSpeed: 0.03 + Math.random() * 0.04,
      pulsePhase: Math.random() * Math.PI * 2,
    }));

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      canvas.style.width = `${window.innerWidth}px`;
      canvas.style.height = `${window.innerHeight}px`;
      ctx.scale(dpr, dpr);
    };
    resize();
    window.addEventListener("resize", resize);

    const render = () => {
      t += 0.016;
      const { isListening, isThinking, isSpeaking, voiceActivity } = stateRef.current;
      const w = window.innerWidth;
      const h = window.innerHeight;
      const cx = w / 2;
      const cy = h / 2;

      ctx.clearRect(0, 0, w, h);

      const vAct = voiceActivity || 0;
      const speed = isThinking ? 0.042 : isSpeaking || isListening ? 0.024 + vAct * 0.03 : 0.014;
      const energy = isSpeaking || isListening ? 1.0 + vAct * 1.6 : 0.85;

      const numPoints = 140;
      const margin = 40;
      const halfW = cx - margin;
      const halfH = cy - margin;

      // Superellipse base parameterization
      const getBasePoint = (theta) => {
        const cosT = Math.cos(theta);
        const sinT = Math.sin(theta);
        const n = 3.2; // rounded squircle factor
        const x = cx + halfW * Math.sign(cosT) * Math.pow(Math.abs(cosT), 2 / n);
        const y = cy + halfH * Math.sign(sinT) * Math.pow(Math.abs(sinT), 2 / n);
        return { x, y };
      };

      // ── 3 Intertwined Ribbon Strands Definition ───────────────────────────
      const strands = [
        {
          name: "Strand-Alpha (Cyan / Sky)",
          color1: "#00f5ff",
          color2: "#38bdf8",
          highlight: "#ffffff",
          k1: 3, k2: 5, k3: 7,
          phase1: 0, phase2: 1.2,
          speedMult: 1.0,
          amp: 36 * energy,
          width: 32,
        },
        {
          name: "Strand-Beta (Hot Magenta / Rose)",
          color1: "#ec4899",
          color2: "#f43f5e",
          highlight: "#fbcfe8",
          k1: 4, k2: 6, k3: 8,
          phase1: 2.1, phase2: 3.4,
          speedMult: -0.85, // counter-undulation
          amp: 32 * energy,
          width: 28,
        },
        {
          name: "Strand-Gamma (Neon Violet / Peach)",
          color1: "#a855f7",
          color2: "#fb923c",
          highlight: "#fef08a",
          k1: 5, k2: 3, k3: 9,
          phase1: 4.2, phase2: 0.8,
          speedMult: 1.15,
          amp: 30 * energy,
          width: 24,
        },
      ];

      // Calculate path points for all 3 strands
      const strandPaths = strands.map((strand) => {
        const points = [];
        for (let i = 0; i <= numPoints; i++) {
          const theta = (i / numPoints) * Math.PI * 2;
          const base = getBasePoint(theta);

          const nx = (base.x - cx) / halfW;
          const ny = (base.y - cy) / halfH;
          const dist = Math.hypot(nx, ny) || 1;
          const dirX = nx / dist;
          const dirY = ny / dist;

          // Multi-octave Fourier displacement (creates complex twists and folds)
          const w1 = Math.sin(theta * strand.k1 + t * speed * 60 * strand.speedMult + strand.phase1) * strand.amp;
          const w2 = Math.cos(theta * strand.k2 - t * speed * 42 * strand.speedMult + strand.phase2) * (strand.amp * 0.45);
          const w3 = Math.sin(theta * strand.k3 + t * speed * 28) * (strand.amp * 0.22);

          const totalDisp = w1 + w2 + w3;
          points.push({
            x: base.x + dirX * totalDisp,
            y: base.y + dirY * totalDisp,
            theta,
          });
        }
        return points;
      });

      // ── Helper: Draw smooth Bezier path ───────────────────────────────────
      const tracePath = (pts) => {
        ctx.beginPath();
        ctx.moveTo(pts[0].x, pts[0].y);
        for (let i = 1; i < pts.length - 2; i++) {
          const xc = (pts[i].x + pts[i + 1].x) / 2;
          const yc = (pts[i].y + pts[i + 1].y) / 2;
          ctx.quadraticCurveTo(pts[i].x, pts[i].y, xc, yc);
        }
        ctx.quadraticCurveTo(
          pts[pts.length - 2].x,
          pts[pts.length - 2].y,
          pts[pts.length - 1].x,
          pts[pts.length - 1].y
        );
        ctx.closePath();
      };

      ctx.save();
      ctx.globalCompositeOperation = "screen";

      // ── PASS 1: Broad Volumetric Atmosphere (60px blur) ───────────────────
      strandPaths.forEach((pts, idx) => {
        const strand = strands[idx];
        ctx.save();
        ctx.filter = "blur(56px)";
        ctx.globalAlpha = 0.32 * energy;
        tracePath(pts);

        const grad = ctx.createLinearGradient(0, 0, w, h);
        grad.addColorStop(0, strand.color1);
        grad.addColorStop(0.5, strand.color2);
        grad.addColorStop(1, strand.color1);
        ctx.strokeStyle = grad;
        ctx.lineWidth = strand.width * 2.4;
        ctx.stroke();
        ctx.restore();
      });

      // ── PASS 2: Sinuous 3D Silk Body (20px blur) ──────────────────────────
      strandPaths.forEach((pts, idx) => {
        const strand = strands[idx];
        ctx.save();
        ctx.filter = "blur(20px)";
        ctx.globalAlpha = 0.72 * energy;
        tracePath(pts);

        const grad = ctx.createConicGradient(t * 0.3 * (idx % 2 === 0 ? 1 : -1), cx, cy);
        grad.addColorStop(0, strand.color1);
        grad.addColorStop(0.35, strand.color2);
        grad.addColorStop(0.7, strand.color1);
        grad.addColorStop(1, strand.color2);
        ctx.strokeStyle = grad;
        ctx.lineWidth = strand.width;
        ctx.lineJoin = "round";
        ctx.lineCap = "round";
        ctx.stroke();
        ctx.restore();
      });

      // ── PASS 3: Razor Specular Highlights (Hot Core Filaments) ────────────
      strandPaths.forEach((pts, idx) => {
        const strand = strands[idx];
        ctx.save();
        ctx.filter = "blur(3.5px)";
        ctx.globalAlpha = 0.95 * energy;
        tracePath(pts);

        const grad = ctx.createLinearGradient(0, 0, w, h);
        grad.addColorStop(0, strand.highlight);
        grad.addColorStop(0.5, "#ffffff");
        grad.addColorStop(1, strand.highlight);
        ctx.strokeStyle = grad;
        ctx.lineWidth = 2.4;
        ctx.stroke();
        ctx.restore();
      });

      // ── PASS 4: Drifting Luminous Photon Starlets ──────────────────────────
      particles.forEach((p) => {
        p.theta = (p.theta + p.speed * (1 + vAct * 1.5)) % (Math.PI * 2);
        const norm = p.theta / (Math.PI * 2);
        const idx = Math.floor(norm * (numPoints - 1));
        const pts = strandPaths[p.strandIdx];
        if (!pts || !pts[idx]) return;

        const pt = pts[idx];
        const pulse = 0.5 + 0.5 * Math.sin(t * 3 + p.pulsePhase);
        const strand = strands[p.strandIdx];

        ctx.save();
        ctx.filter = "blur(1.5px)";
        ctx.fillStyle = strand.highlight;
        ctx.globalAlpha = 0.85 * pulse * energy;
        ctx.beginPath();
        ctx.arc(pt.x, pt.y, p.size * (0.8 + 0.4 * pulse), 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();
      });

      ctx.restore(); // end screen composite

      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);
    return () => {
      window.removeEventListener("resize", resize);
      cancelAnimationFrame(animId);
    };
  }, []);

  return (
    <div className="sovereign-nebula-organic-frame" aria-hidden="true">
      <canvas ref={canvasRef} className="sovereign-nebula-canvas" />
    </div>
  );
});
