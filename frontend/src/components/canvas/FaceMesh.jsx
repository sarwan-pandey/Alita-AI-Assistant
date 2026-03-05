/**
 * FaceMesh.jsx — 3D reactive face mesh driven by MediaPipe 468 landmarks.
 *
 * Features:
 *   - Real-time face mesh from webcam landmarks
 *   - Emotion-driven colour shifts (purple=neutral, green=happy, blue=sad)
 *   - Subtle lip-sync animation during TTS playback
 *   - Holographic wireframe aesthetic with glow
 *   - Smooth interpolation between idle state and tracking state
 */

import { useRef, useMemo, useEffect } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";

import { useMotionStore } from "../../store/useMotionStore";
import { useEmotionStore } from "../../store/useEmotionStore";

// ── Emotion → colour ──────────────────────────────────────────────────────────
const EMOTION_COLORS = {
    happy: new THREE.Color("#a3e635"),
    sad: new THREE.Color("#60a5fa"),
    angry: new THREE.Color("#ef4444"),
    fear: new THREE.Color("#fb923c"),
    surprise: new THREE.Color("#f59e0b"),
    disgust: new THREE.Color("#84cc16"),
    neutral: new THREE.Color("#c084fc"),
};

// ── MediaPipe canonical face-mesh triangulation (selected subset) ─────────────
// Full 468-landmark mesh has ~920 triangles. We use 468 points + key triangles.
// Key face regions: forehead, cheeks, nose, lips, eyes, jawline
function buildFaceTriangulation() {
    // Simplified canonical face-mesh indices for key areas
    // Using Delaunay-style triangulation of MediaPipe face oval + inner features
    const indices = [];

    // Face oval (silhouette) — connect sequential points
    const oval = [
        10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288,
        397, 365, 379, 378, 400, 377, 152, 148, 176, 149, 150, 136,
        172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109, 10,
    ];
    for (let i = 0; i < oval.length - 2; i++) {
        indices.push(oval[i], oval[i + 1], oval[Math.min(i + 2, oval.length - 1)]);
    }

    // Lips (outer)
    const lipsUpper = [61, 185, 40, 39, 37, 0, 267, 269, 270, 409, 291];
    const lipsLower = [61, 146, 91, 181, 84, 17, 314, 405, 321, 375, 291];
    for (let i = 0; i < lipsUpper.length - 1; i++) {
        indices.push(lipsUpper[i], lipsUpper[i + 1], lipsLower[Math.min(i, lipsLower.length - 1)]);
        indices.push(lipsLower[i], lipsLower[i + 1], lipsUpper[Math.min(i + 1, lipsUpper.length - 1)]);
    }

    // Left eye
    const leftEye = [33, 7, 163, 144, 145, 153, 154, 155, 133, 173, 157, 158, 159, 160, 161, 246, 33];
    for (let i = 0; i < leftEye.length - 2; i++) {
        indices.push(leftEye[i], leftEye[i + 1], leftEye[Math.min(i + 2, leftEye.length - 1)]);
    }

    // Right eye
    const rightEye = [362, 382, 381, 380, 374, 373, 390, 249, 263, 466, 388, 387, 386, 385, 384, 398, 362];
    for (let i = 0; i < rightEye.length - 2; i++) {
        indices.push(rightEye[i], rightEye[i + 1], rightEye[Math.min(i + 2, rightEye.length - 1)]);
    }

    // Nose bridge
    const nose = [168, 6, 197, 195, 5, 4, 1, 19, 94, 2, 164];
    for (let i = 0; i < nose.length - 2; i++) {
        indices.push(nose[i], nose[i + 1], nose[Math.min(i + 2, nose.length - 1)]);
    }

    // Fill inner face with radial triangulation from nose tip (4)
    const noseTip = 4;
    const innerRing = [
        33, 133, 362, 263, 61, 291,  // eye corners + lip corners
        10, 152, 234, 454,           // top, chin, sides
        70, 300, 151, 9,             // forehead
    ];
    for (let i = 0; i < innerRing.length - 1; i++) {
        indices.push(noseTip, innerRing[i], innerRing[i + 1]);
    }

    return new Uint16Array(indices);
}

// ── Vertex shader (holographic wireframe with glow) ───────────────────────────
const FACE_VERT = `
  uniform float uTime;
  uniform float uPulse;
  varying vec3 vPosition;
  varying float vEdgeDist;

  void main() {
    vec3 pos = position;
    // Subtle breathing pulse
    pos *= 1.0 + sin(uTime * 1.2) * 0.008 * uPulse;

    vPosition = pos;
    vEdgeDist = length(pos.xy) * 0.5;

    vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mvPos;
  }
`;

const FACE_FRAG = `
  uniform vec3 uColor;
  uniform float uTime;
  uniform float uOpacity;
  varying vec3 vPosition;
  varying float vEdgeDist;

  void main() {
    // Holographic scan-line effect
    float scanline = sin(vPosition.y * 40.0 + uTime * 2.0) * 0.03;

    // Edge glow
    float edge = smoothstep(0.0, 1.5, vEdgeDist);
    float alpha = (0.35 + scanline) * uOpacity * (1.0 - edge * 0.3);

    // Chromatic shimmer
    vec3 col = uColor + vec3(
      sin(uTime * 0.7) * 0.05,
      cos(uTime * 0.9) * 0.04,
      sin(uTime * 1.1) * 0.06
    );

    gl_FragColor = vec4(col * 1.4, alpha);
  }
`;

// ── 3D Face Component ─────────────────────────────────────────────────────────
export function AuraFaceMesh({ isSpeaking = false }) {
    const meshRef = useRef();
    const wireRef = useRef();
    const matRef = useRef();
    const wireMatRef = useRef();
    const clockRef = useRef(new THREE.Clock());

    const faceLandmarks = useMotionStore((s) => s.faceLandmarks);
    const emotion = useEmotionStore((s) => s.emotion);

    const targetColor = useRef(new THREE.Color("#c084fc"));
    const currentColor = useRef(new THREE.Color("#c084fc"));
    const interpRef = useRef(0);

    // Face mesh geometry
    const { geo, indices } = useMemo(() => {
        const g = new THREE.BufferGeometry();
        // 468 landmarks × 3 coords
        const positions = new Float32Array(468 * 3);
        g.setAttribute("position", new THREE.BufferAttribute(positions, 3));

        const idx = buildFaceTriangulation();
        g.setIndex(new THREE.BufferAttribute(idx, 1));
        g.computeVertexNormals();

        return { geo: g, indices: idx };
    }, []);

    // Idle face shape (ellipsoid)
    const idleFace = useMemo(() => {
        const pts = new Float32Array(468 * 3);
        for (let i = 0; i < 468; i++) {
            const angle = (i / 468) * Math.PI * 2;
            const row = Math.floor(i / 20);
            const y = (row / 23 - 0.5) * 2.5;
            const r = Math.sqrt(Math.max(0, 1 - (y / 2.5) ** 2)) * 1.2;
            pts[i * 3] = Math.cos(angle + i * 0.1) * r;
            pts[i * 3 + 1] = y;
            pts[i * 3 + 2] = Math.sin(angle + i * 0.1) * r * 0.3;
        }
        return pts;
    }, []);

    // Shader uniforms
    const uniforms = useMemo(() => ({
        uTime: { value: 0 },
        uColor: { value: new THREE.Color("#c084fc") },
        uOpacity: { value: 0.65 },
        uPulse: { value: 1.0 },
    }), []);

    // Scale + mirror for MediaPipe coords
    const SX = -3.2, SY = -3.2, OX = 1.6, OY = 1.8;

    useFrame((_, delta) => {
        const t = clockRef.current.getElapsedTime();
        uniforms.uTime.value = t;

        // Emotion colour lerp
        if (emotion?.label) {
            targetColor.current.copy(EMOTION_COLORS[emotion.label] || EMOTION_COLORS.neutral);
        }
        currentColor.current.lerp(targetColor.current, delta * 1.5);
        uniforms.uColor.value.copy(currentColor.current);

        // Speaking pulse
        uniforms.uPulse.value = isSpeaking ? 1.0 + Math.sin(t * 8) * 0.15 : 1.0;

        const hasFace = Array.isArray(faceLandmarks) && faceLandmarks.length >= 468;

        // Interpolation
        const targetInterp = hasFace ? 1 : 0;
        interpRef.current += (targetInterp - interpRef.current) * Math.min(delta * 2.0, 1);
        const ip = interpRef.current;

        // Update vertex positions
        const attr = geo.getAttribute("position");
        const arr = attr.array;

        for (let i = 0; i < 468; i++) {
            // Idle position
            const breathe = 1 + Math.sin(t * 0.8 + i * 0.01) * 0.02;
            const ix = idleFace[i * 3] * breathe;
            const iy = idleFace[i * 3 + 1] * breathe;
            const iz = idleFace[i * 3 + 2] * breathe;

            if (hasFace) {
                const lm = faceLandmarks[i];
                const tx = lm.x * SX + OX;
                const ty = lm.y * SY + OY;
                const tz = (lm.z || 0) * 2;

                arr[i * 3] = ix + (tx - ix) * ip;
                arr[i * 3 + 1] = iy + (ty - iy) * ip;
                arr[i * 3 + 2] = iz + (tz - iz) * ip;
            } else {
                arr[i * 3] = ix;
                arr[i * 3 + 1] = iy;
                arr[i * 3 + 2] = iz;
            }
        }
        attr.needsUpdate = true;
        geo.computeVertexNormals();
    });

    return (
        <group>
            {/* Wireframe overlay (the holographic look) */}
            <mesh geometry={geo} ref={wireRef}>
                <shaderMaterial
                    ref={wireMatRef}
                    vertexShader={FACE_VERT}
                    fragmentShader={FACE_FRAG}
                    uniforms={uniforms}
                    transparent
                    wireframe
                    side={THREE.DoubleSide}
                    depthWrite={false}
                    blending={THREE.AdditiveBlending}
                />
            </mesh>

            {/* Subtle solid fill underneath */}
            <mesh geometry={geo} ref={meshRef}>
                <meshBasicMaterial
                    ref={matRef}
                    color={currentColor.current}
                    transparent
                    opacity={0.06}
                    side={THREE.DoubleSide}
                    depthWrite={false}
                    blending={THREE.AdditiveBlending}
                />
            </mesh>

            {/* Glow points at key landmarks */}
            <FaceGlowPoints />
        </group>
    );
}

// ── Glow points at key facial landmarks ──────────────────────────────────────
function FaceGlowPoints() {
    const geoRef = useRef();
    const matRef = useRef();
    const clockRef = useRef(new THREE.Clock());

    const faceLandmarks = useMotionStore((s) => s.faceLandmarks);
    const emotion = useEmotionStore((s) => s.emotion);

    const targetColor = useRef(new THREE.Color("#c084fc"));
    const currentColor = useRef(new THREE.Color("#c084fc"));

    // Key landmark indices: eyes, nose, lips, jawline
    const keyIndices = useMemo(() => [
        1, 4, 5, 6,           // nose
        33, 133, 362, 263,     // eye corners
        61, 291,               // lip corners
        10, 152,               // top + chin
        70, 300,               // forehead sides
        234, 454,              // temples
    ], []);

    const N_POINTS = keyIndices.length;
    const SX = -3.2, SY = -3.2, OX = 1.6, OY = 1.8;

    useFrame((_, delta) => {
        const t = clockRef.current.getElapsedTime();

        if (emotion?.label) {
            targetColor.current.copy(EMOTION_COLORS[emotion.label] || EMOTION_COLORS.neutral);
        }
        currentColor.current.lerp(targetColor.current, delta * 1.5);
        if (matRef.current) matRef.current.color.copy(currentColor.current);

        const hasFace = Array.isArray(faceLandmarks) && faceLandmarks.length >= 468;
        if (!hasFace || !geoRef.current) return;

        const attr = geoRef.current.attributes.position;
        const arr = attr.array;

        for (let i = 0; i < N_POINTS; i++) {
            const lm = faceLandmarks[keyIndices[i]];
            arr[i * 3] = lm.x * SX + OX;
            arr[i * 3 + 1] = lm.y * SY + OY;
            arr[i * 3 + 2] = (lm.z || 0) * 2 + 0.05;
        }
        attr.needsUpdate = true;
    });

    return (
        <points>
            <bufferGeometry ref={geoRef}>
                <bufferAttribute
                    attach="attributes-position"
                    array={new Float32Array(N_POINTS * 3)}
                    count={N_POINTS}
                    itemSize={3}
                />
            </bufferGeometry>
            <pointsMaterial
                ref={matRef}
                size={0.04}
                color="#c084fc"
                transparent
                opacity={0.8}
                sizeAttenuation
                depthWrite={false}
                blending={THREE.AdditiveBlending}
            />
        </points>
    );
}
