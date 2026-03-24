/**
 * ─────────────────────────────────────────────────────────────────────────────
 * ParticlesSwarm — GPU-Accelerated Earth Particle Simulation
 * ─────────────────────────────────────────────────────────────────────────────
 *
 * Features:
 *   1. GPU ShaderMaterial — 50K+ particles, all math on GPU (60fps)
 *   2. Emotion-reactive color palettes — 11 states from personality engine
 *   3. Audio-reactive displacement — bass/mid/treble → visual response
 *   4. Day/Night cycle with city lights + atmospheric scattering
 *   5. Aurora/magnetic field at poles — thinking state indicator
 *   6. Mouse/touch gravitational attractors
 *   7. Procedural weather/storm systems with lightning
 *
 * API:
 *   setRealtimeSignals({ isListening, isThinking, isSpeaking, activity })
 *   setEmotion(label, confidence)
 *   setAudioData(analyserNode)  — pass Web Audio AnalyserNode
 *   resize()
 *   dispose()
 * ─────────────────────────────────────────────────────────────────────────────
 */

import * as THREE from '../frontend/node_modules/three/build/three.module.js';
import { EffectComposer } from '../frontend/node_modules/three/examples/jsm/postprocessing/EffectComposer.js';
import { RenderPass } from '../frontend/node_modules/three/examples/jsm/postprocessing/RenderPass.js';
import { UnrealBloomPass } from '../frontend/node_modules/three/examples/jsm/postprocessing/UnrealBloomPass.js';

// ─────────────────────────────────────────────────────────────────────────────
// EMOTION PALETTES — HSL values matching personality_engine.py states
// Each palette: { ocean, land, atmosphere, cloud, accent, bloomTint }
// ─────────────────────────────────────────────────────────────────────────────
const EMOTION_PALETTES = {
    neutral:     { ocean: [0.58, 0.75, 0.30], land: [0.28, 0.55, 0.42], atmo: [0.60, 0.60, 0.55], accent: [0.55, 0.50, 0.50], bloom: 1.8 },
    happy:       { ocean: [0.15, 0.85, 0.50], land: [0.10, 0.80, 0.55], atmo: [0.12, 0.90, 0.60], accent: [0.08, 0.95, 0.65], bloom: 2.4 },
    sad:         { ocean: [0.62, 0.50, 0.22], land: [0.65, 0.35, 0.30], atmo: [0.68, 0.45, 0.35], accent: [0.70, 0.40, 0.30], bloom: 1.2 },
    angry:       { ocean: [0.00, 0.80, 0.35], land: [0.02, 0.75, 0.40], atmo: [0.98, 0.85, 0.45], accent: [0.05, 0.90, 0.50], bloom: 2.6 },
    fear:        { ocean: [0.75, 0.60, 0.20], land: [0.78, 0.50, 0.28], atmo: [0.80, 0.55, 0.30], accent: [0.82, 0.65, 0.35], bloom: 1.4 },
    depressed:   { ocean: [0.65, 0.30, 0.18], land: [0.70, 0.20, 0.25], atmo: [0.72, 0.25, 0.28], accent: [0.68, 0.30, 0.22], bloom: 0.8 },
    anxious:     { ocean: [0.52, 0.65, 0.28], land: [0.48, 0.55, 0.35], atmo: [0.50, 0.70, 0.40], accent: [0.45, 0.60, 0.38], bloom: 1.6 },
    overwhelmed: { ocean: [0.55, 0.45, 0.25], land: [0.58, 0.40, 0.30], atmo: [0.53, 0.50, 0.35], accent: [0.50, 0.55, 0.32], bloom: 1.3 },
    lonely:      { ocean: [0.63, 0.40, 0.25], land: [0.60, 0.30, 0.32], atmo: [0.58, 0.35, 0.38], accent: [0.55, 0.40, 0.35], bloom: 1.0 },
    grieving:    { ocean: [0.70, 0.25, 0.20], land: [0.72, 0.20, 0.28], atmo: [0.68, 0.30, 0.32], accent: [0.65, 0.25, 0.25], bloom: 0.7 },
    panicked:    { ocean: [0.00, 0.90, 0.40], land: [0.05, 0.85, 0.45], atmo: [0.98, 0.95, 0.50], accent: [0.02, 0.90, 0.55], bloom: 3.0 },
};


// ─────────────────────────────────────────────────────────────────────────────
// VERTEX SHADER — All particle math on GPU
// ─────────────────────────────────────────────────────────────────────────────
const VERTEX_SHADER = /* glsl */ `
precision highp float;

// Per-particle attributes
attribute float aIndex;
attribute vec3  aRandom;

// Uniforms — updated each frame
uniform float uTime;
uniform float uParticleCount;
uniform float uActivity;
uniform float uRadius;
uniform float uRotSpeed;

// Day/Night
uniform vec3  uSunDir;

// Audio reactivity
uniform float uAudioBass;
uniform float uAudioMid;
uniform float uAudioTreble;

// Mouse interaction
uniform vec3  uMouseWorld;
uniform float uMouseStrength;

// Storms (3 storm centers: xyz = lat/lon/intensity)
uniform vec3  uStorm0;
uniform vec3  uStorm1;
uniform vec3  uStorm2;
uniform float uLightning;

// Emotion palette (interpolated on CPU, sent as uniforms)
uniform vec3  uOceanHSL;
uniform vec3  uLandHSL;
uniform vec3  uAtmoHSL;
uniform vec3  uAccentHSL;

// Varyings → fragment shader
varying vec3  vColor;
varying float vAlpha;
varying float vGlow;
varying float vIsAtmo;

// ── Pseudo-random hash ──────────────────────────────────────────────────
float hash(float n) { return fract(sin(n) * 43758.5453123); }
float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

// ── Simple noise (sine-based, fast) ─────────────────────────────────────
float noise3(vec3 p) {
    return sin(p.x * 8.3 + p.z * 6.1 + uTime * 0.05) * 0.45
         + sin(p.y * 14.7 - p.z * 11.3 + uTime * 0.03) * 0.30
         + cos(p.x * 5.1 + p.z * 9.7 + uTime * 0.07) * 0.20
         + sin(p.y * 20.0 + p.z * 17.0) * 0.05;
}

// ── HSL to RGB conversion ───────────────────────────────────────────────
vec3 hsl2rgb(vec3 hsl) {
    float h = hsl.x, s = hsl.y, l = hsl.z;
    float c = (1.0 - abs(2.0 * l - 1.0)) * s;
    float x = c * (1.0 - abs(mod(h * 6.0, 2.0) - 1.0));
    float m = l - c * 0.5;
    vec3 rgb;
    float hh = h * 6.0;
    if      (hh < 1.0) rgb = vec3(c, x, 0.0);
    else if (hh < 2.0) rgb = vec3(x, c, 0.0);
    else if (hh < 3.0) rgb = vec3(0.0, c, x);
    else if (hh < 4.0) rgb = vec3(0.0, x, c);
    else if (hh < 5.0) rgb = vec3(x, 0.0, c);
    else               rgb = vec3(c, 0.0, x);
    return rgb + m;
}

void main() {
    float i = aIndex;
    float count = uParticleCount;

    // ── Fibonacci sphere distribution ───────────────────────────────────
    float phi   = acos(1.0 - 2.0 * (i / count));
    float theta = sqrt(count * 3.14159265) * phi + uTime * uRotSpeed;

    float sinPhi   = sin(phi);
    float cosPhi   = cos(phi);
    float sinTheta = sin(theta);
    float cosTheta = cos(theta);

    float lat = cosPhi;
    float lon = atan(sinTheta, cosTheta);

    // ── Terrain noise ───────────────────────────────────────────────────
    vec3 noisePos = vec3(lat, lon, 0.0);
    float terrain = noise3(noisePos);

    bool isOcean    = terrain < -0.05;
    bool isMountain = terrain > 0.30;
    bool isPolar    = abs(lat) > 0.82;

    // ── Cloud / atmosphere classification ───────────────────────────────
    float cloudNoise = sin(lat * 12.0 + lon * 9.0 + uTime * 0.12) *
                       cos(lat * 7.0  - lon * 13.0 + uTime * 0.09);
    float cloudThreshold = 1.0 - (3.7 + uActivity * 1.2) * 0.09;
    bool isCloud = cloudNoise > cloudThreshold;
    bool isAtmo  = i > count * 0.92;

    // ── Storm spiral displacement ───────────────────────────────────────
    float stormDisplacement = 0.0;
    for (int s = 0; s < 3; s++) {
        vec3 storm = (s == 0) ? uStorm0 : (s == 1) ? uStorm1 : uStorm2;
        float sLat = storm.x;
        float sLon = storm.y;
        float sInt = storm.z;
        if (sInt > 0.01) {
            float dLat = lat - sLat;
            float dLon = lon - sLon;
            float dist = sqrt(dLat * dLat + dLon * dLon);
            float stormRadius = 0.4;
            if (dist < stormRadius && isCloud) {
                // Spiral rotation
                float spiralAngle = dist * 15.0 - uTime * 2.0 * sInt;
                float spiralOffset = sin(spiralAngle) * sInt * (stormRadius - dist) * 3.0;
                stormDisplacement += spiralOffset;
            }
        }
    }

    // ── Compute radii ───────────────────────────────────────────────────
    float cloudR = uRadius + 1.2 + sin(lon * 5.0 + uTime * 0.1) * 0.4 + stormDisplacement;
    float atmoR  = uRadius + 15.0 * (0.8 + sin(lon * 3.0 + lat * 4.0 + uTime * 0.04) * 0.2);
    float landR  = uRadius + max(0.0, terrain) * 3.5;
    float oceanR = uRadius - abs(min(0.0, terrain)) * 5.0;

    float r = isAtmo ? atmoR : (isCloud ? cloudR : (isOcean ? oceanR : landR));

    // ── Audio-reactive displacement ─────────────────────────────────────
    // Bass → atmosphere breathes, Mid → surface ripple, Treble → cloud shimmer
    if (isAtmo) {
        r += uAudioBass * 8.0 * sin(uTime * 0.5 + phi * 3.0);
    } else if (isCloud) {
        r += uAudioTreble * 2.0 * sin(lon * 8.0 + uTime * 3.0);
    } else {
        r += uAudioMid * 1.5 * sin(lat * 12.0 + lon * 8.0 + uTime * 2.0);
    }

    // ── Base position ───────────────────────────────────────────────────
    vec3 pos = vec3(
        sinPhi * cosTheta * r,
        cosPhi * r,
        sinPhi * sinTheta * r
    );

    // ── Mouse gravitational attractor ───────────────────────────────────
    if (uMouseStrength > 0.01) {
        vec3 toMouse = uMouseWorld - pos;
        float mouseDist = length(toMouse);
        float attraction = uMouseStrength * 15.0 / (mouseDist * mouseDist + 5.0);
        attraction = min(attraction, 3.0); // Clamp to prevent particles from tunneling
        pos += normalize(toMouse) * attraction;
    }

    // ── Day/Night factor ────────────────────────────────────────────────
    vec3 normalDir = normalize(pos);
    float sunDot = dot(normalDir, normalize(uSunDir));
    float dayFactor = smoothstep(-0.2, 0.3, sunDot); // 0 = night, 1 = day

    // ── Color computation ───────────────────────────────────────────────
    vec3 baseHSL;
    if (isAtmo) {
        baseHSL = uAtmoHSL;
        baseHSL.z *= (0.3 + dayFactor * 0.7);
        // Atmospheric scattering — edge particles glow cyan/orange at sunset line
        float sunsetFactor = 1.0 - abs(sunDot);
        if (sunsetFactor > 0.7) {
            baseHSL.x = mix(baseHSL.x, 0.05, (sunsetFactor - 0.7) * 3.0); // Orange tint
            baseHSL.z += 0.15;
        }
    } else if (isCloud) {
        baseHSL = vec3(0.0, 0.0, 0.88 * (0.4 + dayFactor * 0.6));
        baseHSL.z += uAudioTreble * 0.1;
    } else if (isOcean) {
        baseHSL = uOceanHSL;
        baseHSL.z *= (0.2 + dayFactor * 0.8);
        // Deep ocean shimmer
        baseHSL.z += sin(lon * 20.0 + uTime * 0.5) * 0.03;
    } else {
        // Land
        if (isPolar) {
            baseHSL = vec3(0.0, 0.05, 0.92 * (0.3 + dayFactor * 0.7));
        } else if (isMountain && abs(lat) > 0.3) {
            // Snow-capped mountains
            baseHSL = vec3(0.0, 0.05, 0.95 * (0.3 + dayFactor * 0.7));
        } else if (isMountain) {
            baseHSL = vec3(uLandHSL.x - 0.2, 0.25, 0.38 * (0.3 + dayFactor * 0.7));
        } else {
            baseHSL = uLandHSL;
            baseHSL.z *= (0.25 + dayFactor * 0.75);
        }
    }

    // ── City lights on night side (land only, not ocean/cloud/atmo) ──────
    float cityLight = 0.0;
    if (!isOcean && !isCloud && !isAtmo && dayFactor < 0.3) {
        float cityNoise = hash2(vec2(lat * 50.0, lon * 50.0));
        if (cityNoise > 0.82 && !isPolar) {
            cityLight = (0.3 - dayFactor) * 3.0; // Brighter as it's darker
            baseHSL = vec3(0.10, 0.90, 0.70 * cityLight); // Warm orange city glow
        }
    }

    // ── Lightning flash ─────────────────────────────────────────────────
    if (uLightning > 0.5 && isCloud) {
        baseHSL.z = min(baseHSL.z + 0.5, 1.0);
    }

    // ── Convert HSL → RGB ───────────────────────────────────────────────
    vColor = hsl2rgb(baseHSL);
    vAlpha = isAtmo ? (0.15 + uActivity * 0.2 + uAudioBass * 0.1) : (isCloud ? 0.75 : 1.0);
    vGlow  = isAtmo ? 1.0 : (cityLight > 0.1 ? 0.8 : 0.0);
    vIsAtmo = isAtmo ? 1.0 : 0.0;

    // ── GL position ─────────────────────────────────────────────────────
    vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mvPos;

    // Point size: atmosphere particles larger, closer = bigger
    float basePtSize = isAtmo ? 3.5 : (isCloud ? 2.2 : 1.8);
    basePtSize += cityLight * 1.5; // City lights glow bigger
    basePtSize += uAudioBass * 0.8; // Audio makes particles bigger
    gl_PointSize = basePtSize * (250.0 / -mvPos.z);
}
`;


// ─────────────────────────────────────────────────────────────────────────────
// FRAGMENT SHADER — Per-pixel particle rendering
// ─────────────────────────────────────────────────────────────────────────────
const FRAGMENT_SHADER = /* glsl */ `
precision highp float;

varying vec3  vColor;
varying float vAlpha;
varying float vGlow;
varying float vIsAtmo;

void main() {
    // Circular soft particle shape
    vec2 center = gl_PointCoord - vec2(0.5);
    float dist = length(center);

    if (dist > 0.5) discard; // Clip to circle

    // Soft edge falloff
    float alpha = vAlpha * smoothstep(0.5, 0.15, dist);

    // Glow effect for city lights and atmosphere
    if (vGlow > 0.1) {
        alpha *= (1.0 + vGlow * 2.0 * smoothstep(0.5, 0.0, dist));
    }

    // Atmosphere: very soft, wide glow
    if (vIsAtmo > 0.5) {
        alpha *= smoothstep(0.5, 0.0, dist) * 0.6;
    }

    gl_FragColor = vec4(vColor, alpha);
}
`;


// ─────────────────────────────────────────────────────────────────────────────
// AURORA VERTEX SHADER — Polar particle ribbons
// ─────────────────────────────────────────────────────────────────────────────
const AURORA_VERTEX = /* glsl */ `
precision highp float;

attribute float aIndex;

uniform float uTime;
uniform float uIntensity;
uniform float uRadius;

varying vec3  vColor;
varying float vAlpha;

float hash(float n) { return fract(sin(n) * 43758.5453); }

vec3 hsl2rgb(vec3 hsl) {
    float h = hsl.x, s = hsl.y, l = hsl.z;
    float c = (1.0 - abs(2.0 * l - 1.0)) * s;
    float x = c * (1.0 - abs(mod(h * 6.0, 2.0) - 1.0));
    float m = l - c * 0.5;
    vec3 rgb;
    float hh = h * 6.0;
    if      (hh < 1.0) rgb = vec3(c, x, 0.0);
    else if (hh < 2.0) rgb = vec3(x, c, 0.0);
    else if (hh < 3.0) rgb = vec3(0.0, c, x);
    else if (hh < 4.0) rgb = vec3(0.0, x, c);
    else if (hh < 5.0) rgb = vec3(x, 0.0, c);
    else               rgb = vec3(c, 0.0, x);
    return rgb + m;
}

void main() {
    float i = aIndex;
    float total = 3000.0;

    // Half at north pole, half at south pole
    float pole = (i < total * 0.5) ? 1.0 : -1.0;
    float localI = mod(i, total * 0.5);

    // Ribbon ring around pole
    float angle = (localI / (total * 0.5)) * 6.28318 * 3.0; // 3 loops
    float ringRadius = uRadius + 16.0 + sin(angle * 2.0 + uTime * 1.5) * 4.0;

    // Wave animation (curtain effect)
    float wave = sin(angle * 5.0 + uTime * 2.0 + localI * 0.02) * 5.0;
    float wave2 = cos(angle * 3.0 + uTime * 1.2) * 3.0;

    // Position in ring
    float polarOffset = 0.75 + hash(i * 7.13) * 0.15; // 75-90 degrees from equator
    float phi = acos(pole * polarOffset);

    float x = sin(phi) * cos(angle) * ringRadius;
    float y = cos(phi) * ringRadius + wave + wave2;
    float z = sin(phi) * sin(angle) * ringRadius;

    vec3 pos = vec3(x, y, z);

    // Aurora colors: green, cyan, pink, purple
    float hue = 0.33 + sin(angle * 2.0 + uTime * 0.5) * 0.15
              + hash(i * 3.7) * 0.1;
    float sat = 0.7 + hash(i * 11.3) * 0.3;
    float lit = 0.4 + sin(angle * 7.0 + uTime * 3.0) * 0.2
              + hash(i * 5.1) * 0.1;

    vColor = hsl2rgb(vec3(hue, sat, lit));
    vAlpha = uIntensity * (0.3 + sin(angle * 4.0 + uTime * 2.5) * 0.2)
           * smoothstep(0.0, 0.3, uIntensity);

    vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
    gl_Position = projectionMatrix * mvPos;
    gl_PointSize = (3.0 + sin(uTime * 3.0 + i * 0.1) * 1.5) * uIntensity * (200.0 / -mvPos.z);
}
`;

const AURORA_FRAGMENT = /* glsl */ `
precision highp float;

varying vec3  vColor;
varying float vAlpha;

void main() {
    vec2 center = gl_PointCoord - vec2(0.5);
    float dist = length(center);
    if (dist > 0.5) discard;

    float alpha = vAlpha * smoothstep(0.5, 0.0, dist) * 0.7;
    gl_FragColor = vec4(vColor, alpha);
}
`;


// ─────────────────────────────────────────────────────────────────────────────
// MAIN CLASS
// ─────────────────────────────────────────────────────────────────────────────
export class ParticlesSwarm {
    constructor(container, count = 50000) {
        if (!container) throw new Error('ParticlesSwarm requires a valid container element');

        this.count = count;
        this.container = container;
        this.disposed = false;
        this.animationFrameId = null;

        // ── State ───────────────────────────────────────────────────────────
        this.activity = 0;
        this.smoothedActivity = 0;
        this.isListening = false;
        this.isThinking = false;
        this.isSpeaking = false;

        // Emotion
        this.currentEmotion = 'neutral';
        this.emotionConfidence = 0;
        this.currentPalette = { ...EMOTION_PALETTES.neutral };
        this.targetPalette = { ...EMOTION_PALETTES.neutral };

        // Audio
        this.analyserNode = null;
        this.audioData = new Uint8Array(128);
        this.audioBass = 0;
        this.audioMid = 0;
        this.audioTreble = 0;

        // Mouse
        this.mouse = new THREE.Vector2();
        this.mouseWorld = new THREE.Vector3();
        this.mouseStrength = 0;
        this.raycaster = new THREE.Raycaster();
        this.mouseSphere = new THREE.Sphere(new THREE.Vector3(0, 0, 0), 65);

        // Storms
        this.storms = [
            { lat: 0.3,  lon: 0, intensity: 0, drift: 0.02 },
            { lat: -0.2, lon: 2, intensity: 0, drift: -0.015 },
            { lat: 0.5,  lon: 4, intensity: 0, drift: 0.025 },
        ];
        this.lightningTimer = 0;
        this.lightningFlash = 0;

        // Day/Night — sun orbits slowly
        this.sunAngle = 0;

        // ── Three.js Setup ──────────────────────────────────────────────────
        this.scene = new THREE.Scene();
        this.camera = new THREE.PerspectiveCamera(60, 1, 0.1, 2000);
        this.camera.position.set(0, 0, 120);

        this.renderer = new THREE.WebGLRenderer({
            antialias: true,
            alpha: true,
            powerPreference: 'high-performance',
        });
        this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
        this.container.appendChild(this.renderer.domElement);

        // Post-processing
        this.composer = new EffectComposer(this.renderer);
        this.composer.addPass(new RenderPass(this.scene, this.camera));
        this.bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), 1.8, 0.4, 0.0);
        this.composer.addPass(this.bloomPass);

        // ── Create particle systems ─────────────────────────────────────────
        this._createEarthParticles();
        this._createAuroraParticles();

        // ── Event listeners ─────────────────────────────────────────────────
        this._onMouseMove = this._onMouseMove.bind(this);
        this._onMouseDown = this._onMouseDown.bind(this);
        this._onMouseUp = this._onMouseUp.bind(this);
        this._onMouseLeave = this._onMouseLeave.bind(this);
        this.container.addEventListener('mousemove', this._onMouseMove);
        this.container.addEventListener('mousedown', this._onMouseDown);
        this.container.addEventListener('mouseup', this._onMouseUp);
        this.container.addEventListener('mouseleave', this._onMouseLeave);
        // Touch support
        this.container.addEventListener('touchmove', (e) => {
            e.preventDefault();
            const touch = e.touches[0];
            this._onMouseMove({ clientX: touch.clientX, clientY: touch.clientY });
        }, { passive: false });
        this.container.addEventListener('touchstart', (e) => {
            const touch = e.touches[0];
            this._onMouseDown({ clientX: touch.clientX, clientY: touch.clientY });
        });
        this.container.addEventListener('touchend', () => this._onMouseUp());

        // ── Clock & Start ───────────────────────────────────────────────────
        this.clock = new THREE.Clock();
        this.animate = this.animate.bind(this);
        this.resize();
        this.animate();
    }

    // ─────────────────────────────────────────────────────────────────────────
    // PARTICLE CREATION
    // ─────────────────────────────────────────────────────────────────────────
    _createEarthParticles() {
        const geo = new THREE.BufferGeometry();
        const indices = new Float32Array(this.count);
        const randoms = new Float32Array(this.count * 3);

        for (let i = 0; i < this.count; i++) {
            indices[i] = i;
            randoms[i * 3]     = Math.random();
            randoms[i * 3 + 1] = Math.random();
            randoms[i * 3 + 2] = Math.random();
        }

        // Dummy positions — computed in shader
        const positions = new Float32Array(this.count * 3);
        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geo.setAttribute('aIndex', new THREE.BufferAttribute(indices, 1));
        geo.setAttribute('aRandom', new THREE.BufferAttribute(randoms, 3));

        const palette = EMOTION_PALETTES.neutral;
        this.earthUniforms = {
            uTime:          { value: 0 },
            uParticleCount: { value: this.count },
            uActivity:      { value: 0 },
            uRadius:        { value: 45.7 },
            uRotSpeed:      { value: 0.27 },
            uSunDir:        { value: new THREE.Vector3(1, 0.3, 0.5).normalize() },
            uAudioBass:     { value: 0 },
            uAudioMid:      { value: 0 },
            uAudioTreble:   { value: 0 },
            uMouseWorld:    { value: new THREE.Vector3() },
            uMouseStrength: { value: 0 },
            uStorm0:        { value: new THREE.Vector3(0.3, 0, 0) },
            uStorm1:        { value: new THREE.Vector3(-0.2, 2, 0) },
            uStorm2:        { value: new THREE.Vector3(0.5, 4, 0) },
            uLightning:     { value: 0 },
            uOceanHSL:      { value: new THREE.Vector3(...palette.ocean) },
            uLandHSL:       { value: new THREE.Vector3(...palette.land) },
            uAtmoHSL:       { value: new THREE.Vector3(...palette.atmo) },
            uAccentHSL:     { value: new THREE.Vector3(...palette.accent) },
        };

        this.earthMaterial = new THREE.ShaderMaterial({
            vertexShader:   VERTEX_SHADER,
            fragmentShader: FRAGMENT_SHADER,
            uniforms:       this.earthUniforms,
            transparent:    true,
            depthWrite:     false,
            blending:       THREE.AdditiveBlending,
        });

        this.earthPoints = new THREE.Points(geo, this.earthMaterial);
        this.scene.add(this.earthPoints);
    }

    _createAuroraParticles() {
        const AURORA_COUNT = 3000;
        const geo = new THREE.BufferGeometry();
        const indices = new Float32Array(AURORA_COUNT);
        const positions = new Float32Array(AURORA_COUNT * 3);

        for (let i = 0; i < AURORA_COUNT; i++) {
            indices[i] = i;
        }

        geo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
        geo.setAttribute('aIndex', new THREE.BufferAttribute(indices, 1));

        this.auroraUniforms = {
            uTime:      { value: 0 },
            uIntensity: { value: 0 },
            uRadius:    { value: 45.7 },
        };

        this.auroraMaterial = new THREE.ShaderMaterial({
            vertexShader:   AURORA_VERTEX,
            fragmentShader: AURORA_FRAGMENT,
            uniforms:       this.auroraUniforms,
            transparent:    true,
            depthWrite:     false,
            blending:       THREE.AdditiveBlending,
        });

        this.auroraPoints = new THREE.Points(geo, this.auroraMaterial);
        this.scene.add(this.auroraPoints);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // PUBLIC API
    // ─────────────────────────────────────────────────────────────────────────
    setRealtimeSignals({ isListening, isThinking, isSpeaking, activity } = {}) {
        if (typeof isListening === 'boolean') this.isListening = isListening;
        if (typeof isThinking === 'boolean') this.isThinking = isThinking;
        if (typeof isSpeaking === 'boolean') this.isSpeaking = isSpeaking;
        if (typeof activity === 'number') this.activity = Math.max(0, Math.min(1, activity));
    }

    setEmotion(label, confidence = 1.0) {
        const palette = EMOTION_PALETTES[label] || EMOTION_PALETTES.neutral;
        this.currentEmotion = label;
        this.emotionConfidence = confidence;
        this.targetPalette = { ...palette };
    }

    setAudioData(analyserNode) {
        this.analyserNode = analyserNode;
        if (analyserNode) {
            this.audioData = new Uint8Array(analyserNode.frequencyBinCount || 128);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // MOUSE INTERACTION
    // ─────────────────────────────────────────────────────────────────────────
    _onMouseMove(e) {
        const rect = this.container.getBoundingClientRect();
        this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
        this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

        // Raycast to find world position on sphere
        this.raycaster.setFromCamera(this.mouse, this.camera);
        const ray = this.raycaster.ray;
        const target = new THREE.Vector3();
        if (ray.intersectSphere(this.mouseSphere, target)) {
            this.mouseWorld.copy(target);
            this.mouseStrength = 1.0;
        } else {
            this.mouseStrength = 0;
        }
    }

    _onMouseDown() {
        this.mouseStrength = 3.0; // Strong gravity on click
    }

    _onMouseUp() {
        this.mouseStrength = Math.min(this.mouseStrength, 1.0);
    }

    _onMouseLeave() {
        this.mouseStrength = 0;
    }

    resize() {
        const width = Math.max(1, this.container.clientWidth || 1);
        const height = Math.max(1, this.container.clientHeight || 1);
        this.camera.aspect = width / height;
        this.camera.updateProjectionMatrix();
        this.renderer.setSize(width, height, false);
        this.composer.setSize(width, height);
        this.bloomPass.setSize(width, height);
    }

    // ─────────────────────────────────────────────────────────────────────────
    // ANIMATION LOOP
    // ─────────────────────────────────────────────────────────────────────────
    animate() {
        if (this.disposed) return;
        this.animationFrameId = requestAnimationFrame(this.animate);

        const delta = this.clock.getDelta();
        const elapsed = this.clock.getElapsedTime();

        // ── Activity smoothing ──────────────────────────────────────────────
        const roleBoost = this.isSpeaking ? 0.9 : this.isListening ? 0.55 : this.isThinking ? 0.35 : 0.12;
        const targetActivity = Math.max(roleBoost, this.activity);
        this.smoothedActivity += (targetActivity - this.smoothedActivity) * 0.15;

        const speedMult = 0.75 + this.smoothedActivity * 2.2;
        const time = elapsed * speedMult;

        // ── Audio data processing ───────────────────────────────────────────
        if (this.analyserNode) {
            this.analyserNode.getByteFrequencyData(this.audioData);
            const len = this.audioData.length;
            const third = Math.floor(len / 3);

            let bassSum = 0, midSum = 0, trebSum = 0;
            for (let i = 0; i < third; i++) bassSum += this.audioData[i];
            for (let i = third; i < third * 2; i++) midSum += this.audioData[i];
            for (let i = third * 2; i < len; i++) trebSum += this.audioData[i];

            this.audioBass   += (bassSum / (third * 255) - this.audioBass) * 0.3;
            this.audioMid    += (midSum / (third * 255) - this.audioMid) * 0.3;
            this.audioTreble += (trebSum / ((len - third * 2) * 255) - this.audioTreble) * 0.3;
        } else {
            this.audioBass   *= 0.95;
            this.audioMid    *= 0.95;
            this.audioTreble *= 0.95;
        }

        // ── Emotion palette interpolation ───────────────────────────────────
        const lerpRate = 0.04; // Smooth ~0.5s transition
        this._lerpPalette('ocean', lerpRate);
        this._lerpPalette('land',  lerpRate);
        this._lerpPalette('atmo',  lerpRate);
        this._lerpPalette('accent', lerpRate);

        // Update bloom based on emotion
        const targetBloom = this.targetPalette.bloom || 1.8;
        this.bloomPass.strength += (targetBloom - this.bloomPass.strength) * lerpRate;

        // ── Day/Night cycle — sun orbits ────────────────────────────────────
        this.sunAngle += delta * 0.08; // Full cycle ~78 seconds
        const sunDir = this.earthUniforms.uSunDir.value;
        sunDir.set(
            Math.cos(this.sunAngle),
            Math.sin(this.sunAngle) * 0.3,
            Math.sin(this.sunAngle)
        ).normalize();

        // ── Storm updates ───────────────────────────────────────────────────
        for (let s = 0; s < 3; s++) {
            const storm = this.storms[s];
            storm.lon += storm.drift * delta * 10;

            // Random storm intensity (spawn/fade)
            if (storm.intensity <= 0.01) {
                if (Math.random() < 0.002) {
                    storm.intensity = 0.5 + Math.random() * 0.5;
                    storm.lat = (Math.random() - 0.5) * 1.2;
                    storm.lon = Math.random() * 6.28;
                }
            } else {
                storm.intensity *= 0.999; // Slowly fade
            }
        }

        // Lightning
        this.lightningTimer -= delta;
        if (this.lightningTimer <= 0) {
            const anyStorm = this.storms.some(s => s.intensity > 0.3);
            if (anyStorm && Math.random() < 0.3) {
                this.lightningFlash = 1.0;
                this.lightningTimer = 0.05 + Math.random() * 0.1;
            } else {
                this.lightningFlash = 0;
                this.lightningTimer = 0.5 + Math.random() * 2.0;
            }
        } else {
            this.lightningFlash *= 0.85;
        }

        // ── Mouse smoothing ─────────────────────────────────────────────────
        const currentMouseStrength = this.earthUniforms.uMouseStrength.value;
        this.earthUniforms.uMouseStrength.value +=
            (this.mouseStrength - currentMouseStrength) * 0.15;

        // ── Update earth uniforms ───────────────────────────────────────────
        const eu = this.earthUniforms;
        eu.uTime.value         = time;
        eu.uActivity.value     = this.smoothedActivity;
        eu.uRotSpeed.value     = 0.27 + this.smoothedActivity * 0.6;
        eu.uAudioBass.value    = this.audioBass;
        eu.uAudioMid.value     = this.audioMid;
        eu.uAudioTreble.value  = this.audioTreble;
        eu.uMouseWorld.value.copy(this.mouseWorld);
        eu.uStorm0.value.set(this.storms[0].lat, this.storms[0].lon, this.storms[0].intensity);
        eu.uStorm1.value.set(this.storms[1].lat, this.storms[1].lon, this.storms[1].intensity);
        eu.uStorm2.value.set(this.storms[2].lat, this.storms[2].lon, this.storms[2].intensity);
        eu.uLightning.value    = this.lightningFlash;
        eu.uOceanHSL.value.set(...this.currentPalette.ocean);
        eu.uLandHSL.value.set(...this.currentPalette.land);
        eu.uAtmoHSL.value.set(...this.currentPalette.atmo);
        eu.uAccentHSL.value.set(...this.currentPalette.accent);

        // ── Update aurora uniforms ──────────────────────────────────────────
        const auroraTarget = this.isThinking ? 1.0 : (this.isSpeaking ? 0.4 : 0.0);
        this.auroraUniforms.uTime.value = elapsed;
        this.auroraUniforms.uIntensity.value +=
            (auroraTarget - this.auroraUniforms.uIntensity.value) * 0.08;

        // ── Render ──────────────────────────────────────────────────────────
        this.composer.render();
    }

    // ─────────────────────────────────────────────────────────────────────────
    // HELPERS
    // ─────────────────────────────────────────────────────────────────────────
    _lerpPalette(key, rate) {
        const current = this.currentPalette[key];
        const target = this.targetPalette[key];
        if (!current || !target) return;
        for (let i = 0; i < current.length; i++) {
            current[i] += (target[i] - current[i]) * rate;
        }
    }

    dispose() {
        this.disposed = true;
        if (this.animationFrameId) {
            cancelAnimationFrame(this.animationFrameId);
            this.animationFrameId = null;
        }

        // Remove event listeners
        this.container.removeEventListener('mousemove', this._onMouseMove);
        this.container.removeEventListener('mousedown', this._onMouseDown);
        this.container.removeEventListener('mouseup', this._onMouseUp);
        this.container.removeEventListener('mouseleave', this._onMouseLeave);

        // Dispose Three.js resources
        this.earthPoints.geometry.dispose();
        this.earthMaterial.dispose();
        this.scene.remove(this.earthPoints);

        this.auroraPoints.geometry.dispose();
        this.auroraMaterial.dispose();
        this.scene.remove(this.auroraPoints);

        this.composer?.dispose?.();
        this.renderer.dispose();

        if (this.renderer.domElement?.parentNode === this.container) {
            this.container.removeChild(this.renderer.domElement);
        }
    }
}