/**
 * sovereignCore.js — Pure Canvas2D rendering engine for The Sovereign entity.
 *
 * Replaces earthSwarm.js. Same interface pattern: init → update → render loop.
 * 7 visual layers drawn back-to-front:
 *   1. Sigil (hexagram floor projection)
 *   2. Column (vertical energy beam)
 *   3. Orbitals (220 particle field, screen blend)
 *   4. Rings (7 sacred geometry rings)
 *   5. Lightning (8 plasma arms)
 *   6. Core (slit-pupil eye)
 *   7. Scan (horizontal surveillance sweep)
 */

import {
  createPerlin,
  createRings,
  createOrbitals,
  createArcs,
  lerpPalette,
} from './sovereignGeometry';

const PALETTE_HOLD_SECONDS = 12;
const PALETTE_BLEND_SECONDS = 3;

// ─────────────────────────────────────────────────────────────────────────────
// §1  INITIALIZATION
// ─────────────────────────────────────────────────────────────────────────────

export function initSovereign(canvas, cssW, cssH) {
  const ctx = canvas.getContext('2d');
  // Use CSS pixel dimensions (not backing store), so geometry is viewport-scaled
  const W = cssW || canvas.width;
  const H = cssH || canvas.height;
  const CX = W / 2;
  const CY = H / 2 - 20; // slightly above center — more imposing

  // Scale factor relative to the original 560×660 design size
  const scale = Math.min(W / 560, H / 660);

  const noise = createPerlin();
  const rings = createRings(scale);
  const orbitals = createOrbitals(scale);
  const arcs = createArcs(scale);

  return {
    ctx, W, H, CX, CY, scale, noise, rings, orbitals, arcs,
    // Palette state
    currentPaletteIdx: 1,     // start on 'void' (cyan)
    nextPaletteIdx: 0,
    paletteBlend: 1.0,        // 1.0 = fully on currentPalette
    paletteTimer: 0,
    // Animation targets driven by ALITA_FACE_DATA
    targetGlowIntensity: 0.5,
    currentGlowIntensity: 0.5,
    targetPulseSpeed: 1.0,
    targetEnergyLevel: 0.5,
    currentEnergyLevel: 0.5,
    targetEyeSlitWidth: 9,
    targetOrbitalSpeed: 1.0,
    targetCoronaScale: 1.0,
    targetSigilScale: 0.9,
    scanY: 0,
    time: 0,
    // Seeded random for lightning jitter (deterministic per frame)
    _rngSeed: 42,
  };
}

// ── Resize (called by SovereignEntity on container resize) ────────────────
export function resizeSovereign(state, cssW, cssH) {
  state.W = cssW;
  state.H = cssH;
  state.CX = cssW / 2;
  state.CY = cssH / 2 - 20;
  state.scale = Math.min(cssW / 560, cssH / 660);
  // Re-generate geometry at new scale
  state.rings = createRings(state.scale);
  state.orbitals = createOrbitals(state.scale);
  state.arcs = createArcs(state.scale);
}

// ─────────────────────────────────────────────────────────────────────────────
// §2  UPDATE FROM ALITA_FACE_DATA
// ─────────────────────────────────────────────────────────────────────────────

export function updateFromFaceData(state, faceData, PALETTES, EMOTION_TO_PALETTE) {
  if (!faceData) return;

  // Map glow_intensity → entity brightness
  if (faceData.particle_system?.glow_intensity !== undefined) {
    state.targetGlowIntensity = faceData.particle_system.glow_intensity;
  }

  // Map pulse_speed → animation tempo
  const speedMap = { slow: 0.6, medium: 1.0, fast: 1.6 };
  if (faceData.particle_system?.pulse_speed) {
    state.targetPulseSpeed = speedMap[faceData.particle_system.pulse_speed] ?? 1.0;
  }

  // Map energy_level → ring rotation speed + lightning intensity
  if (faceData.voice?.energy_level !== undefined) {
    state.targetEnergyLevel = faceData.voice.energy_level;
  }

  // Map emotional_state_label → palette shift
  const emotionLabel = faceData.emotional_state_label;
  const paletteId =
    EMOTION_TO_PALETTE[emotionLabel] ??
    EMOTION_TO_PALETTE[faceData.conversation_phase] ??
    'void';
  const newIdx = PALETTES.findIndex((p) => p.id === paletteId);
  if (newIdx !== -1 && newIdx !== state.currentPaletteIdx) {
    state.nextPaletteIdx = newIdx;
    state.paletteBlend = 0; // start blending toward new palette
  }

  // Map color_temperature → override palette hint
  if (faceData.particle_system?.color_temperature && !emotionLabel) {
    const tempMap = { cool: 'void', warm: 'inferno', neutral: 'omega' };
    const tempPal = tempMap[faceData.particle_system.color_temperature];
    if (tempPal) {
      const tIdx = PALETTES.findIndex((p) => p.id === tempPal);
      if (tIdx !== -1 && tIdx !== state.currentPaletteIdx) {
        state.nextPaletteIdx = tIdx;
        state.paletteBlend = 0;
      }
    }
  }

  // Eye width from blendshapes
  const eyeWide =
    ((faceData.blendshapes?.eyeWide_L ?? 0) +
      (faceData.blendshapes?.eyeWide_R ?? 0)) /
    2;
  state.targetEyeSlitWidth = 9 + eyeWide * 14;

  // Voice pace → orbital speed
  const paceMap = { slow: 0.6, measured: 0.8, normal: 1.0, energised: 1.5 };
  state.targetOrbitalSpeed = paceMap[faceData.voice?.pace] ?? 1.0;

  // Nod → trigger single fast scan sweep
  if (faceData.head_motion?.nod === true) {
    state.scanY = 0;
  }

  // Expression intensity → corona size multiplier
  state.targetCoronaScale =
    0.7 + (faceData.expression?.intensity ?? 0.5) * 0.6;

  // Lean forward → sigil prominence
  state.targetSigilScale = faceData.head_motion?.lean_forward ? 1.1 : 0.9;
}

// ─────────────────────────────────────────────────────────────────────────────
// §3  DRAW FUNCTIONS
// ─────────────────────────────────────────────────────────────────────────────

// Seeded pseudo-random for deterministic lightning jitter per frame
function seededRandom(state) {
  state._rngSeed = (state._rngSeed * 16807 + 0) % 2147483647;
  return state._rngSeed / 2147483647;
}

// ── 3.1 DRAW CORE (slit-pupil eye) ──────────────────────────────────────────
function drawCore(ctx, CX, CY, pal, pulse, time, coronaScale, eyeSlitWidth, s) {
  const scale = coronaScale;
  const S = s || 1; // viewport scale factor

  // a) Outer corona — 12 radial gradient layers
  for (let i = 12; i >= 1; i--) {
    const radius = (20 + i * 22) * scale * S;
    const alpha = 0.06 * (1 - i / 13) * (0.7 + pulse * 0.3);
    const grad = ctx.createRadialGradient(CX, CY, 0, CX, CY, radius);
    grad.addColorStop(0, `rgba(${pal.core},${alpha * 3})`);
    grad.addColorStop(0.3, `rgba(${pal.mid},${alpha * 1.5})`);
    grad.addColorStop(0.7, `rgba(${pal.outer},${alpha * 0.7})`);
    grad.addColorStop(1, 'rgba(0,0,0,0)');
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(CX, CY, radius, 0, Math.PI * 2);
    ctx.fill();
  }

  // b) Iris ring — 12 radial lines
  ctx.save();
  ctx.translate(CX, CY);
  ctx.rotate(time * 0.8);
  const irisInner = 16 * S;
  const irisOuter = (32 + pulse * 8) * S;
  ctx.strokeStyle = `rgba(${pal.core},${0.7 + pulse * 0.3})`;
  ctx.lineWidth = 1.5 * S;
  for (let i = 0; i < 12; i++) {
    const a = (i * Math.PI * 2) / 12;
    ctx.beginPath();
    ctx.moveTo(Math.cos(a) * irisInner, Math.sin(a) * irisInner);
    ctx.lineTo(Math.cos(a) * irisOuter, Math.sin(a) * irisOuter);
    ctx.stroke();
  }
  ctx.restore();

  // c) Slit pupil — vertical diamond bezier
  ctx.save();
  ctx.translate(CX, CY);
  const slitH = (28 + pulse * 10) * S;
  const slitW = (eyeSlitWidth + pulse * 3) * S;
  ctx.beginPath();
  ctx.moveTo(0, -slitH);
  ctx.bezierCurveTo(slitW, -slitH * 0.4, slitW, slitH * 0.4, 0, slitH);
  ctx.bezierCurveTo(-slitW, slitH * 0.4, -slitW, -slitH * 0.4, 0, -slitH);
  const slitGrad = ctx.createRadialGradient(0, 0, 0, 0, 0, slitH);
  slitGrad.addColorStop(0, 'rgba(255,255,255,0.95)');
  slitGrad.addColorStop(0.3, `rgba(${pal.core},0.8)`);
  slitGrad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = slitGrad;
  ctx.fill();

  // Vertical center line
  ctx.beginPath();
  ctx.moveTo(0, -slitH * 0.95);
  ctx.lineTo(0, slitH * 0.95);
  ctx.strokeStyle = `rgba(255,255,255,${0.9 + pulse * 0.1})`;
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.restore();

  // d) White core dot
  const dotR = (4 + pulse * 2) * S;
  ctx.beginPath();
  ctx.arc(CX, CY, dotR, 0, Math.PI * 2);
  ctx.fillStyle = `rgba(255,255,255,${0.95 + pulse * 0.05})`;
  ctx.fill();
  // Sub-dot
  ctx.beginPath();
  ctx.arc(CX, CY, 2.2 * S, 0, Math.PI * 2);
  ctx.fillStyle = 'rgba(255,255,255,0.99)';
  ctx.fill();
}

// ── 3.2 DRAW RINGS (sacred geometry) ────────────────────────────────────────
function drawRings(ctx, CX, CY, rings, pal, time) {
  for (let ri = 0; ri < rings.length; ri++) {
    const ring = rings[ri];
    const angle = time * ring.speed + ring.phase;
    // Color: inner rings → core, outer → outer
    const t = ri / (rings.length - 1); // 0=inner, 1=outer
    const alpha = 0.15 + (1 - t) * 0.2;
    const colorKey = t < 0.4 ? 'core' : t < 0.7 ? 'mid' : 'outer';

    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(angle);
    ctx.strokeStyle = `rgba(${pal[colorKey]},${alpha})`;
    ctx.lineWidth = ring.lineWidth;
    ctx.beginPath();
    for (let i = 0; i < ring.numPoints; i++) {
      const a1 = (i * (Math.PI * 2)) / ring.numPoints;
      const a2 = ((i + ring.dashRatio) * (Math.PI * 2)) / ring.numPoints;
      ctx.moveTo(
        Math.cos(a1) * ring.radius,
        Math.sin(a1) * ring.radius,
      );
      ctx.lineTo(
        Math.cos(a2) * ring.radius,
        Math.sin(a2) * ring.radius,
      );
    }
    ctx.stroke();

    // Vertex dots on even-indexed rings
    if (ri % 2 === 0) {
      ctx.fillStyle = `rgba(${pal.core},${alpha * 2.5})`;
      for (let i = 0; i < ring.numPoints; i++) {
        const a = (i * (Math.PI * 2)) / ring.numPoints;
        ctx.beginPath();
        ctx.arc(
          Math.cos(a) * ring.radius,
          Math.sin(a) * ring.radius,
          1.5,
          0,
          Math.PI * 2,
        );
        ctx.fill();
      }
    }

    ctx.restore();
  }
}

// ── 3.3 DRAW LIGHTNING (plasma arms) ────────────────────────────────────────
function drawLightning(ctx, CX, CY, arcs, pal, time, pulse, energyLevel, state) {
  for (let ai = 0; ai < arcs.length; ai++) {
    const arc = arcs[ai];
    // Stochastic activation — more energy = more active
    const activation = Math.sin(time * arc.speed * 40 + arc.phase);
    if (activation < 0.2 - energyLevel * 0.3) continue;

    ctx.save();
    ctx.translate(CX, CY);
    ctx.rotate(arc.baseAngle + time * 0.018);

    const segLen = arc.length / arc.segments;
    let x = 30;
    let y = 0;

    // Main bolt
    ctx.beginPath();
    ctx.moveTo(x, y);
    for (let s = 0; s < arc.segments; s++) {
      const jitter =
        (seededRandom(state) - 0.5) * 18 * (1 - s / arc.segments);
      x += segLen + seededRandom(state) * 4;
      y += jitter;
      ctx.lineTo(x, y);
    }
    ctx.strokeStyle = `rgba(${pal.core},${0.4 + pulse * 0.3 + energyLevel * 0.3})`;
    ctx.lineWidth = 1 + pulse;
    ctx.stroke();

    // Branch lightning (40% chance from a random midpoint)
    if (seededRandom(state) < arc.branchProbability) {
      const branchSeg = 1 + (0 | (seededRandom(state) * (arc.segments - 2)));
      let bx = 30 + branchSeg * segLen;
      let by = (seededRandom(state) - 0.5) * 12;
      ctx.beginPath();
      ctx.moveTo(bx, by);
      for (let bs = 0; bs < 3; bs++) {
        bx += segLen * 0.6 + seededRandom(state) * 3;
        by += (seededRandom(state) - 0.5) * 22;
        ctx.lineTo(bx, by);
      }
      ctx.strokeStyle = `rgba(${pal.mid},${0.25 + pulse * 0.15})`;
      ctx.lineWidth = 0.5;
      ctx.stroke();
    }

    ctx.restore();
  }
}

// ── 3.4 DRAW ORBITALS (particle field) ──────────────────────────────────────
function drawOrbitals(
  ctx, CX, CY, orbitals, pal, noise, time, glowIntensity, pulseSpeed,
) {
  for (let i = 0; i < orbitals.length; i++) {
    const o = orbitals[i];
    o.angle += o.speed * pulseSpeed;

    const noiseVal = noise(o.noiseOffset + time * 0.08, o.radius * 0.01) * 28;
    const r = o.radius + noiseVal;
    const x = CX + Math.cos(o.angle) * r;
    const y = CY + Math.sin(o.angle) * r * o.ellipseY;

    const colorKey = o.layer === 0 ? 'core' : o.layer === 1 ? 'mid' : 'outer';
    const pulseFactor = Math.sin(time * 1.4 + o.noiseOffset) * 0.4 + 0.6;
    const finalAlpha = o.opacity * pulseFactor * 0.7 * glowIntensity;

    ctx.fillStyle = `rgba(${pal[colorKey]},${finalAlpha})`;
    ctx.shadowColor = `rgba(${pal[colorKey]},${finalAlpha * 0.6})`;
    ctx.shadowBlur = o.size * 4;
    ctx.beginPath();
    ctx.arc(x, y, o.size, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.shadowBlur = 0;
  ctx.shadowColor = 'transparent';
}

// ── 3.5 DRAW SIGIL (hexagram floor projection) ─────────────────────────────
function drawSigil(ctx, CX, CY, pal, time, pulse, sigilScale, S) {
  const vScale = S || 1;
  ctx.save();
  ctx.translate(CX, CY + 195 * vScale);
  const s = (0.9 + pulse * 0.08) * sigilScale;
  ctx.scale(s * vScale, 0.28 * s * vScale); // flatten to floor perspective
  ctx.globalCompositeOperation = 'screen';

  // Layer 1: Outer circle
  ctx.beginPath();
  ctx.arc(0, 0, 145, 0, Math.PI * 2);
  ctx.strokeStyle = `rgba(${pal.outer},${0.14 + pulse * 0.08})`;
  ctx.lineWidth = 0.8;
  ctx.stroke();

  // Layer 2: Hexagram (two overlapping equilateral triangles)
  ctx.rotate(time * 0.12);
  for (let tri = 0; tri < 2; tri++) {
    ctx.beginPath();
    for (let v = 0; v < 3; v++) {
      const a = tri * (Math.PI / 3) + (v * (Math.PI * 2)) / 3;
      const px = Math.cos(a) * 115;
      const py = Math.sin(a) * 115;
      if (v === 0) ctx.moveTo(px, py);
      else ctx.lineTo(px, py);
    }
    ctx.closePath();
    ctx.strokeStyle = `rgba(${pal.mid},${0.2 + pulse * 0.1})`;
    ctx.lineWidth = 0.6;
    ctx.stroke();
  }

  // Layer 3: 8 rune dots
  ctx.fillStyle = `rgba(${pal.core},${0.3 + pulse * 0.15})`;
  for (let d = 0; d < 8; d++) {
    const a = (d * Math.PI * 2) / 8;
    ctx.beginPath();
    ctx.arc(Math.cos(a) * 125, Math.sin(a) * 125, 2.5, 0, Math.PI * 2);
    ctx.fill();
  }

  ctx.restore();
}

// ── 3.6 DRAW COLUMN (vertical energy beam) ──────────────────────────────────
function drawColumn(ctx, CX, CY, pal, time, pulse, S) {
  const vS = S || 1;
  ctx.save();
  ctx.globalCompositeOperation = 'screen';

  // Upward column
  const upGrad = ctx.createLinearGradient(CX, CY - 260 * vS, CX, CY - 50 * vS);
  upGrad.addColorStop(0, 'rgba(0,0,0,0)');
  upGrad.addColorStop(0.5, `rgba(${pal.mid},${0.04 + pulse * 0.04})`);
  upGrad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = upGrad;
  ctx.fillRect(CX - 8 * vS, CY - 260 * vS, 16 * vS, 210 * vS);

  // Downward column
  const dnGrad = ctx.createLinearGradient(CX, CY + 50 * vS, CX, CY + 220 * vS);
  dnGrad.addColorStop(0, 'rgba(0,0,0,0)');
  dnGrad.addColorStop(0.5, `rgba(${pal.outer},${0.05 + pulse * 0.04})`);
  dnGrad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = dnGrad;
  ctx.fillRect(CX - 6 * vS, CY + 50 * vS, 12 * vS, 170 * vS);

  ctx.restore();
}

// ── 3.7 DRAW SCAN LINE (surveillance sweep) ─────────────────────────────────
function drawScan(ctx, W, pal, scanY, pulse) {
  ctx.save();
  ctx.globalCompositeOperation = 'screen';
  const grad = ctx.createLinearGradient(0, scanY - 30, 0, scanY + 30);
  grad.addColorStop(0, 'rgba(0,0,0,0)');
  grad.addColorStop(0.5, `rgba(${pal.core},${0.04 + pulse * 0.03})`);
  grad.addColorStop(1, 'rgba(0,0,0,0)');
  ctx.fillStyle = grad;
  ctx.fillRect(0, scanY - 30, W, 60);
  ctx.restore();
}

// ─────────────────────────────────────────────────────────────────────────────
// §4  MAIN RENDER LOOP
// ─────────────────────────────────────────────────────────────────────────────

export function startRenderLoop(state, PALETTES, animFrameRef) {
  function frame() {
    state.time += 0.007;
    state.paletteTimer += 0.007;
    state.scanY = (state.scanY + 1.2) % state.H;

    // Reset seeded RNG each frame for deterministic lightning
    state._rngSeed = ((state.time * 10000) | 0) % 2147483647 || 1;

    // Smooth lerp toward targets (prevents jarring jumps)
    state.currentGlowIntensity +=
      (state.targetGlowIntensity - state.currentGlowIntensity) * 0.04;
    state.currentEnergyLevel +=
      (state.targetEnergyLevel - state.currentEnergyLevel) * 0.04;

    // Palette auto-cycle + blend
    if (state.paletteTimer > PALETTE_HOLD_SECONDS) {
      state.paletteTimer = 0;
      state.nextPaletteIdx =
        (state.currentPaletteIdx + 1) % PALETTES.length;
      state.paletteBlend = 0;
    }
    if (state.paletteBlend < 1) {
      state.paletteBlend = Math.min(
        1,
        state.paletteBlend + 0.007 / PALETTE_BLEND_SECONDS,
      );
      if (state.paletteBlend >= 1) {
        state.currentPaletteIdx = state.nextPaletteIdx;
      }
    }

    // Get interpolated palette
    const palA = PALETTES[state.currentPaletteIdx];
    const palB = PALETTES[state.nextPaletteIdx];
    const palRaw =
      state.paletteBlend < 1
        ? lerpPalette(palA, palB, state.paletteBlend)
        : palA;
    const pal = {
      core: palRaw.core.join(','),
      mid: palRaw.mid.join(','),
      outer: palRaw.outer.join(','),
    };

    // Pulse — main animation heartbeat
    const pulse =
      Math.sin(state.time * 1.8 * state.targetPulseSpeed) * 0.5 + 0.5;

    // Motion trail — don't clear fully, let old frames bleed
    state.ctx.fillStyle = 'rgba(0,0,0,0.18)';
    state.ctx.fillRect(0, 0, state.W, state.H);

    // Draw order — back to front:
    drawSigil(
      state.ctx, state.CX, state.CY, pal, state.time, pulse,
      state.targetSigilScale, state.scale,
    );
    drawColumn(state.ctx, state.CX, state.CY, pal, state.time, pulse, state.scale);

    state.ctx.save();
    state.ctx.globalCompositeOperation = 'screen';
    drawOrbitals(
      state.ctx, state.CX, state.CY, state.orbitals, pal,
      state.noise, state.time,
      state.currentGlowIntensity, state.targetPulseSpeed,
    );
    state.ctx.restore();

    drawRings(state.ctx, state.CX, state.CY, state.rings, pal, state.time);

    state.ctx.save();
    state.ctx.globalCompositeOperation = 'screen';
    drawLightning(
      state.ctx, state.CX, state.CY, state.arcs, pal,
      state.time, pulse, state.currentEnergyLevel, state,
    );
    state.ctx.restore();

    state.ctx.save();
    state.ctx.globalCompositeOperation = 'screen';
    drawCore(
      state.ctx, state.CX, state.CY, pal, pulse, state.time,
      state.targetCoronaScale, state.targetEyeSlitWidth, state.scale,
    );
    state.ctx.restore();

    drawScan(state.ctx, state.W, pal, state.scanY, pulse);

    animFrameRef.current = requestAnimationFrame(frame);
  }

  animFrameRef.current = requestAnimationFrame(frame);
}

export function stopRenderLoop(animFrameRef) {
  if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current);
}
