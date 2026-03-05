/**
 * AuraCanvas.jsx — Fixed export + always-visible particles
 * 
 * BLACK SCREEN FIX:
 *   Particles animate from frame 1 — no camera/MediaPipe required.
 *   When face/body detected → particles smoothly flow toward your body.
 */

import { useRef, useMemo, useEffect } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import * as THREE from "three";

import { useMotionStore } from "../../store/useMotionStore";
import { useEmotionStore } from "../../store/useEmotionStore";
import { AuraFaceMesh } from "./FaceMesh";

// ─── Emotion color map ────────────────────────────────────────────────────────
const EMOTION_COLORS = {
  happy: new THREE.Color("#a3e635"),
  sad: new THREE.Color("#60a5fa"),
  angry: new THREE.Color("#ef4444"),
  fear: new THREE.Color("#fb923c"),
  surprise: new THREE.Color("#f59e0b"),
  disgust: new THREE.Color("#84cc16"),
  neutral: new THREE.Color("#c084fc"),
};
function getEmotionColor(label) {
  return EMOTION_COLORS[label] || EMOTION_COLORS.neutral;
}

// ─── Root — pick tier component ───────────────────────────────────────────────
export function AuraCanvas({ tier }) {
  return (
    <>
      <SceneBackground />
      {/* 3D Face Mesh for all tiers */}
      <AuraFaceMesh />
      {/* Premium users get the dense particle backdrop */}
      {tier === "premium" && <DenseField />}
    </>
  );
}

// ── Version without face mesh (face is rendered in separate canvas) ──────────
export function AuraCanvasNoFace({ tier }) {
  return (
    <>
      <SceneBackground />
      {tier === "premium" && <DenseField />}
    </>
  );
}

// ─── Star-field background ────────────────────────────────────────────────────
export function SceneBackground() {
  const { scene } = useThree();

  useEffect(() => {
    scene.background = new THREE.Color(0x050507);
    scene.fog = new THREE.FogExp2(0x050507, 0.04);
    return () => {
      scene.fog = null;
    };
  }, [scene]);

  const positions = useMemo(() => {
    const n = 2000;
    const arr = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      const r = 18 + Math.random() * 22;
      arr[i * 3] = r * Math.sin(phi) * Math.cos(theta);
      arr[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      arr[i * 3 + 2] = r * Math.cos(phi);
    }
    return arr;
  }, []);

  return (
    <points>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          array={positions}
          count={positions.length / 3}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.025}
        color="#8888bb"
        transparent
        opacity={0.28}
        sizeAttenuation
        depthWrite={false}
      />
    </points>
  );
}

// ─── FREE TIER: WireframeHuman ────────────────────────────────────────────────
// Always shows an animated Fibonacci sphere.
// When MediaPipe detects face/body → interpolates toward real landmarks.
const POSE_EDGES = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24],
  [23, 25], [25, 27], [27, 29],
  [24, 26], [26, 28], [28, 30],
];

const N_PARTICLES = 501;

function buildFibSphere(count, radius) {
  const pts = new Float32Array(count * 3);
  const golden = Math.PI * (3 - Math.sqrt(5));
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / (count - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y));
    const t = golden * i;
    const R = radius + (i % 5) * 0.04;
    pts[i * 3] = Math.cos(t) * r * R;
    pts[i * 3 + 1] = y * R;
    pts[i * 3 + 2] = Math.sin(t) * r * R;
  }
  return pts;
}

export function WireframeHuman() {
  const geoRef = useRef();
  const matRef = useRef();
  const poseLineRef = useRef();
  const clockRef = useRef(new THREE.Clock());

  const faceLandmarks = useMotionStore((s) => s.faceLandmarks);
  const poseLandmarks = useMotionStore((s) => s.poseLandmarks);
  const emotion = useEmotionStore((s) => s.emotion);

  const targetColor = useRef(new THREE.Color("#c084fc"));
  const currentColor = useRef(new THREE.Color("#c084fc"));
  const interp = useRef(0);

  const fibSphere = useMemo(() => buildFibSphere(N_PARTICLES, 1.6), []);
  const lerpedPos = useRef(new Float32Array(N_PARTICLES * 3));
  const trackingPos = useRef(new Float32Array(N_PARTICLES * 3));

  const poseLineArr = useMemo(
    () => new Float32Array(POSE_EDGES.length * 2 * 3),
    []
  );

  const SX = -3.0, SY = -3.0, OX = 1.5, OY = 1.8;

  useFrame((_, delta) => {
    const t = clockRef.current.getElapsedTime();

    // Emotion color
    if (emotion?.label) targetColor.current.copy(getEmotionColor(emotion.label));
    currentColor.current.lerp(targetColor.current, delta * 1.5);
    if (matRef.current) matRef.current.color.copy(currentColor.current);

    const hasFace = Array.isArray(faceLandmarks) && faceLandmarks.length > 10;
    const hasPose = Array.isArray(poseLandmarks) && poseLandmarks.length > 10;
    const hasAny = hasFace || hasPose;

    // Build tracking positions from landmarks
    if (hasFace) {
      for (let i = 0; i < 468 && i < N_PARTICLES; i++) {
        const lm = faceLandmarks[Math.min(i, faceLandmarks.length - 1)];
        trackingPos.current[i * 3] = lm.x * SX + OX;
        trackingPos.current[i * 3 + 1] = lm.y * SY + OY;
        trackingPos.current[i * 3 + 2] = (lm.z || 0) * 2;
      }
    }
    if (hasPose) {
      for (let i = 0; i < 33; i++) {
        const idx = 468 + i;
        if (idx >= N_PARTICLES) break;
        const lm = poseLandmarks[Math.min(i, poseLandmarks.length - 1)];
        trackingPos.current[idx * 3] = lm.x * SX + OX;
        trackingPos.current[idx * 3 + 1] = lm.y * SY + OY;
        trackingPos.current[idx * 3 + 2] = (lm.z || 0) * 2;
      }
    }

    // Lerp interp value
    const targetInterp = hasAny ? 1 : 0;
    interp.current = interp.current + (targetInterp - interp.current) * Math.min(delta * 1.5, 1);
    const ip = interp.current;

    // Animate Fibonacci sphere (idle)
    const breathe = 1 + Math.sin(t * 0.8) * 0.06;
    const spin = t * 0.1;
    const cosS = Math.cos(spin);
    const sinS = Math.sin(spin);

    for (let i = 0; i < N_PARTICLES; i++) {
      const sx = fibSphere[i * 3];
      const sy = fibSphere[i * 3 + 1];
      const sz = fibSphere[i * 3 + 2];
      // Rotate around Y
      const ix = (cosS * sx - sinS * sz) * breathe;
      const iy = sy * breathe;
      const iz = (sinS * sx + cosS * sz) * breathe;

      const tx = trackingPos.current[i * 3];
      const ty = trackingPos.current[i * 3 + 1];
      const tz = trackingPos.current[i * 3 + 2];

      lerpedPos.current[i * 3] = ix + (tx - ix) * ip;
      lerpedPos.current[i * 3 + 1] = iy + (ty - iy) * ip;
      lerpedPos.current[i * 3 + 2] = iz + (tz - iz) * ip;
    }

    if (geoRef.current) {
      const attr = geoRef.current.attributes.position;
      attr.array.set(lerpedPos.current);
      attr.needsUpdate = true;
    }

    // Pose lines
    if (hasPose && poseLineRef.current) {
      for (let e = 0; e < POSE_EDGES.length; e++) {
        const [a, b] = POSE_EDGES[e];
        const la = poseLandmarks[Math.min(a, poseLandmarks.length - 1)];
        const lb = poseLandmarks[Math.min(b, poseLandmarks.length - 1)];
        poseLineArr[e * 6] = la.x * SX + OX;
        poseLineArr[e * 6 + 1] = la.y * SY + OY;
        poseLineArr[e * 6 + 2] = (la.z || 0) * 2;
        poseLineArr[e * 6 + 3] = lb.x * SX + OX;
        poseLineArr[e * 6 + 4] = lb.y * SY + OY;
        poseLineArr[e * 6 + 5] = (lb.z || 0) * 2;
      }
      const pattr = poseLineRef.current.geometry.attributes.position;
      pattr.array.set(poseLineArr);
      pattr.needsUpdate = true;
    }
  });

  return (
    <group>
      <points>
        <bufferGeometry ref={geoRef}>
          <bufferAttribute
            attach="attributes-position"
            array={new Float32Array(N_PARTICLES * 3)}
            count={N_PARTICLES}
            itemSize={3}
          />
        </bufferGeometry>
        <pointsMaterial
          ref={matRef}
          size={0.018}
          color="#c084fc"
          transparent
          opacity={0.9}
          sizeAttenuation
          depthWrite={false}
          blending={THREE.AdditiveBlending}
        />
      </points>

      <lineSegments ref={poseLineRef}>
        <bufferGeometry>
          <bufferAttribute
            attach="attributes-position"
            array={poseLineArr}
            count={POSE_EDGES.length * 2}
            itemSize={3}
          />
        </bufferGeometry>
        <lineBasicMaterial
          color="#38bdf8"
          transparent
          opacity={0.35}
          depthWrite={false}
        />
      </lineSegments>
    </group>
  );
}

// ─── PREMIUM TIER: DenseField ─────────────────────────────────────────────────
// 8000 particles using ShaderMaterial.
// GLSL stored as plain strings (no tagged template issues).
const N_DENSE = 8000;

const VERT = [
  "uniform float uTime;",
  "uniform float uInterp;",
  "uniform vec3  uColor;",
  "uniform float uIntensity;",
  "attribute vec3  aTarget;",
  "attribute float aPhase;",
  "attribute float aSpeed;",
  "varying float vAlpha;",
  "varying vec3  vCol;",
  "varying float vGlow;",
  "void main() {",
  "  float t = uTime * aSpeed + aPhase;",
  "  vec3 idle = position;",
  // Organic flowing movement
  "  idle.x += sin(t * 1.3 + aPhase) * 0.07 + cos(t * 0.4) * 0.03;",
  "  idle.y += cos(t * 0.9 + aPhase * 1.2) * 0.06 + sin(t * 0.5) * 0.02;",
  "  idle.z += sin(t * 1.1 + aPhase * 0.8) * 0.05;",
  // Breathing effect
  "  float breathe = 1.0 + sin(uTime * 0.7) * 0.05;",
  "  idle *= breathe;",
  "  vec3 world = mix(idle, aTarget, uInterp);",
  "  float dist = length(world);",
  // Holographic shimmer — chromatic shift based on position
  "  float holo = sin(world.x * 10.0 + uTime * 2.0) * 0.5 + 0.5;",
  "  vec3 holoColor = mix(vec3(0.5, 0.3, 1.0), vec3(0.3, 1.0, 0.9), holo);",
  "  holoColor = mix(holoColor, vec3(1.0, 0.4, 0.8), sin(world.y * 8.0 + uTime) * 0.3 + 0.2);",
  "  vCol = mix(holoColor, uColor, uInterp * 0.7);",
  // Energy pulse ring
  "  float ring = abs(sin(dist * 5.0 - uTime * 1.5)) * 0.3;",
  "  vGlow = ring;",
  "  vAlpha = clamp(1.0 - dist * 0.1, 0.08, 1.0) * uIntensity + ring;",
  // Larger particles with pulsing size
  "  vec4 mvPos = modelViewMatrix * vec4(world, 1.0);",
  "  gl_PointSize = clamp(4.0 / -mvPos.z * (1.0 + 0.4 * sin(t * 2.0) + ring), 1.0, 9.0);",
  "  gl_Position  = projectionMatrix * mvPos;",
  "}",
].join("\n");

const FRAG = [
  "varying float vAlpha;",
  "varying vec3  vCol;",
  "varying float vGlow;",
  "void main() {",
  "  vec2 uv = gl_PointCoord - 0.5;",
  "  float d = dot(uv, uv);",
  "  if (d > 0.25) discard;",
  // Soft radial gradient with holographic glow
  "  float core = exp(-d * 12.0);",
  "  float halo = exp(-d * 4.0) * 0.5;",
  "  float a = (core + halo + vGlow * 0.5) * vAlpha;",
  // Bloom-like color boost
  "  vec3 finalCol = vCol * (1.5 + vGlow * 2.0);",
  "  gl_FragColor = vec4(finalCol, a);",
  "}",
].join("\n");

function DenseField() {
  const emotion = useEmotionStore((s) => s.emotion);
  const faceLandmarks = useMotionStore((s) => s.faceLandmarks);
  const poseLandmarks = useMotionStore((s) => s.poseLandmarks);

  const clockRef = useRef(new THREE.Clock());
  const targetColor = useRef(new THREE.Color("#c084fc"));
  const currentColor = useRef(new THREE.Color("#c084fc"));
  const currentInterp = useRef(0);

  const SX = -3.0, SY = -3.0, OX = 1.5, OY = 1.8;

  const { geo, uniforms } = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const pos = new Float32Array(N_DENSE * 3);
    const targets = new Float32Array(N_DENSE * 3);
    const phases = new Float32Array(N_DENSE);
    const speeds = new Float32Array(N_DENSE);
    const golden = Math.PI * (3 - Math.sqrt(5));

    for (let i = 0; i < N_DENSE; i++) {
      const y = 1 - (i / (N_DENSE - 1)) * 2;
      const r = Math.sqrt(Math.max(0, 1 - y * y));
      const t = golden * i;
      const R = 1.6 + Math.random() * 0.7;
      pos[i * 3] = Math.cos(t) * r * R;
      pos[i * 3 + 1] = y * R;
      pos[i * 3 + 2] = Math.sin(t) * r * R;
      targets[i * 3] = pos[i * 3];
      targets[i * 3 + 1] = pos[i * 3 + 1];
      targets[i * 3 + 2] = pos[i * 3 + 2];
      phases[i] = Math.random() * Math.PI * 2;
      speeds[i] = 0.25 + Math.random() * 0.45;
    }

    g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    g.setAttribute("aTarget", new THREE.BufferAttribute(targets, 3));
    g.setAttribute("aPhase", new THREE.BufferAttribute(phases, 1));
    g.setAttribute("aSpeed", new THREE.BufferAttribute(speeds, 1));

    const u = {
      uTime: { value: 0 },
      uInterp: { value: 0 },
      uColor: { value: new THREE.Color("#c084fc") },
      uIntensity: { value: 1 },
    };

    return { geo: g, uniforms: u };
  }, []);

  useFrame((_, delta) => {
    const t = clockRef.current.getElapsedTime();

    if (emotion?.label) targetColor.current.copy(getEmotionColor(emotion.label));
    currentColor.current.lerp(targetColor.current, delta * 1.2);
    uniforms.uColor.value.copy(currentColor.current);
    uniforms.uTime.value = t;
    uniforms.uIntensity.value = 0.85 + Math.sin(t * 0.6) * 0.15;

    const hasFace = Array.isArray(faceLandmarks) && faceLandmarks.length > 10;
    const hasPose = Array.isArray(poseLandmarks) && poseLandmarks.length > 10;
    const hasAny = hasFace || hasPose;

    currentInterp.current = currentInterp.current + ((hasAny ? 0.88 : 0) - currentInterp.current) * Math.min(delta * 1.5, 1);
    uniforms.uInterp.value = currentInterp.current;

    if (hasAny) {
      const attr = geo.getAttribute("aTarget");
      const arr = attr.array;
      const lms = [];
      if (hasFace) lms.push(...faceLandmarks);
      if (hasPose) lms.push(...poseLandmarks);
      for (let i = 0; i < N_DENSE; i++) {
        const lm = lms[i % lms.length];
        arr[i * 3] = lm.x * SX + OX + (Math.random() - 0.5) * 0.05;
        arr[i * 3 + 1] = lm.y * SY + OY + (Math.random() - 0.5) * 0.05;
        arr[i * 3 + 2] = (lm.z || 0) * 2;
      }
      attr.needsUpdate = true;
    }
  });

  return (
    <points geometry={geo} frustumCulled={false}>
      <shaderMaterial
        vertexShader={VERT}
        fragmentShader={FRAG}
        uniforms={uniforms}
        transparent
        depthWrite={false}
        blending={THREE.AdditiveBlending}
      />
    </points>
  );
}
