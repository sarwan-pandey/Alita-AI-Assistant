/**
 * sovereignGeometry.js — Pure math utilities for The Sovereign entity
 * No rendering — just Perlin noise, ring configs, orbital particles, arc configs, palette lerp.
 */

// ── Perlin Noise ──────────────────────────────────────────────────────────────
export function createPerlin() {
  const a = [...Array(256)].map((_, i) => i);
  for (let i = 255; i > 0; i--) {
    const j = 0 | (Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  const p = [...a, ...a];
  const f = (t) => t * t * t * (t * (t * 6 - 15) + 10);
  const lerp = (a, b, t) => a + t * (b - a);
  const g = (h, x, y) => {
    const v = h & 1 ? x : y;
    return h & 2 ? -v : v;
  };
  return (x, y) => {
    const xi = x | 0,
      yi = y | 0,
      xf = x - xi,
      yf = y - yi;
    const u = f(xf),
      v = f(yf),
      X = xi & 255,
      Y = yi & 255;
    return lerp(
      lerp(g(p[p[X] + Y], xf, yf), g(p[p[X + 1] + Y], xf - 1, yf), u),
      lerp(
        g(p[p[X] + Y + 1], xf, yf - 1),
        g(p[p[X + 1] + Y + 1], xf - 1, yf - 1),
        u,
      ),
      v,
    );
  };
}

// ── Ring Configuration ────────────────────────────────────────────────────────
// Returns array of 7 ring objects with sacred geometry parameters
export function createRings(scale = 1) {
  return Array.from({ length: 7 }, (_, i) => ({
    radius: (55 + i * 38) * scale,
    speed: (i % 2 === 0 ? 1 : -1) * (0.004 + i * 0.0018),
    numPoints: 6 + i * 2,
    phase: (i * Math.PI * 2) / 7,
    dashRatio: 0.4 + i * 0.04,
    lineWidth: (0.6 + (7 - i) * 0.15) * Math.max(scale, 0.8),
  }));
}

// ── Orbital Particle Field ────────────────────────────────────────────────────
// Returns array of 220 particle objects across 3 depth layers
export function createOrbitals(scale = 1) {
  return Array.from({ length: 220 }, () => ({
    angle: Math.random() * Math.PI * 2,
    radius: (40 + Math.random() * 220) * scale,
    speed: (Math.random() - 0.5) * 0.025,
    size: (Math.random() * 2.2 + 0.4) * Math.max(scale, 0.7),
    opacity: Math.random() * 0.7 + 0.15,
    noiseOffset: Math.random() * 300,
    layer: 0 | (Math.random() * 3),
    ellipseY: 0.55 + (0 | (Math.random() * 3)) * 0.12,
  }));
}

// ── Lightning Arc Configs ─────────────────────────────────────────────────────
// Returns array of 8 plasma lightning arm configurations
export function createArcs(scale = 1) {
  return Array.from({ length: 8 }, (_, i) => ({
    baseAngle: i * ((Math.PI * 2) / 8) + Math.random() * 0.3,
    length: (90 + Math.random() * 80) * scale,
    phase: Math.random() * Math.PI * 2,
    speed: 0.03 + Math.random() * 0.04,
    segments: 8 + (0 | (Math.random() * 6)),
    branchProbability: 0.4,
  }));
}

// ── Palette Interpolation ─────────────────────────────────────────────────────
// Lerps between two palette objects (core/mid/outer RGB arrays)
export function lerpPalette(a, b, t) {
  const l = (x, y, t) => Math.round(x + t * (y - x));
  return {
    core: [
      l(a.core[0], b.core[0], t),
      l(a.core[1], b.core[1], t),
      l(a.core[2], b.core[2], t),
    ],
    mid: [
      l(a.mid[0], b.mid[0], t),
      l(a.mid[1], b.mid[1], t),
      l(a.mid[2], b.mid[2], t),
    ],
    outer: [
      l(a.outer[0], b.outer[0], t),
      l(a.outer[1], b.outer[1], t),
      l(a.outer[2], b.outer[2], t),
    ],
  };
}
