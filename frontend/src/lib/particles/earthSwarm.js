import * as THREE from "three";
import { EffectComposer } from "three/examples/jsm/postprocessing/EffectComposer.js";
import { RenderPass } from "three/examples/jsm/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/examples/jsm/postprocessing/UnrealBloomPass.js";

/**
 * ─────────────────────────────────────────────────────────────────────────────
 * ParticlesSwarm — GPU-Accelerated Earth with 7 Advanced Features
 * ─────────────────────────────────────────────────────────────────────────────
 *   1. GPU ShaderMaterial (50K+ particles on GPU — 60fps)
 *   2. Emotion-reactive color palettes (11 states)
 *   3. Audio-reactive displacement (bass/mid/treble)
 *   4. Day/Night cycle with city lights + atmospheric scattering
 *   5. Aurora at poles (thinking state indicator)
 *   6. Mouse/touch gravitational attractors
 *   7. Procedural storms with lightning
 * ─────────────────────────────────────────────────────────────────────────────
 */

// ── Emotion palettes (HSL) matching personality_engine.py ────────────────────
const EMOTION_PALETTES = {
  neutral:     { ocean: [0.58, 0.75, 0.30], land: [0.28, 0.55, 0.42], atmo: [0.60, 0.60, 0.55], accent: [0.55, 0.50, 0.50], bloom: 0.8 },
  happy:       { ocean: [0.15, 0.85, 0.50], land: [0.10, 0.80, 0.55], atmo: [0.12, 0.90, 0.60], accent: [0.08, 0.95, 0.65], bloom: 1.2 },
  sad:         { ocean: [0.62, 0.50, 0.22], land: [0.65, 0.35, 0.30], atmo: [0.68, 0.45, 0.35], accent: [0.70, 0.40, 0.30], bloom: 0.5 },
  angry:       { ocean: [0.00, 0.80, 0.35], land: [0.02, 0.75, 0.40], atmo: [0.98, 0.85, 0.45], accent: [0.05, 0.90, 0.50], bloom: 1.4 },
  fear:        { ocean: [0.75, 0.60, 0.20], land: [0.78, 0.50, 0.28], atmo: [0.80, 0.55, 0.30], accent: [0.82, 0.65, 0.35], bloom: 0.6 },
  depressed:   { ocean: [0.65, 0.30, 0.18], land: [0.70, 0.20, 0.25], atmo: [0.72, 0.25, 0.28], accent: [0.68, 0.30, 0.22], bloom: 0.3 },
  anxious:     { ocean: [0.52, 0.65, 0.28], land: [0.48, 0.55, 0.35], atmo: [0.50, 0.70, 0.40], accent: [0.45, 0.60, 0.38], bloom: 0.7 },
  overwhelmed: { ocean: [0.55, 0.45, 0.25], land: [0.58, 0.40, 0.30], atmo: [0.53, 0.50, 0.35], accent: [0.50, 0.55, 0.32], bloom: 0.5 },
  lonely:      { ocean: [0.63, 0.40, 0.25], land: [0.60, 0.30, 0.32], atmo: [0.58, 0.35, 0.38], accent: [0.55, 0.40, 0.35], bloom: 0.4 },
  grieving:    { ocean: [0.70, 0.25, 0.20], land: [0.72, 0.20, 0.28], atmo: [0.68, 0.30, 0.32], accent: [0.65, 0.25, 0.25], bloom: 0.3 },
  panicked:    { ocean: [0.00, 0.90, 0.40], land: [0.05, 0.85, 0.45], atmo: [0.98, 0.95, 0.50], accent: [0.02, 0.90, 0.55], bloom: 1.6 },
};


// ─────────────────────────────────────────────────────────────────────────────
// VERTEX SHADER — all particle math on GPU
// ─────────────────────────────────────────────────────────────────────────────
const VERT = /* glsl */ `
precision highp float;

attribute float aIndex;
attribute vec3  aRandom;

uniform float uTime, uParticleCount, uActivity, uRadius, uRotSpeed;
uniform vec3  uSunDir;
uniform float uAudioBass, uAudioMid, uAudioTreble;
uniform vec3  uMouseWorld;
uniform float uMouseStrength;
uniform vec3  uStorm0, uStorm1, uStorm2;
uniform float uLightning;
uniform vec3  uOceanHSL, uLandHSL, uAtmoHSL, uAccentHSL;

varying vec3  vColor;
varying float vAlpha, vGlow, vIsAtmo;

float hash(float n) { return fract(sin(n) * 43758.5453123); }
float hash2(vec2 p) { return fract(sin(dot(p, vec2(127.1, 311.7))) * 43758.5453); }

float noise3(vec3 p) {
  return sin(p.x * 8.3 + p.z * 6.1 + uTime * 0.05) * 0.45
       + sin(p.y * 14.7 - p.z * 11.3 + uTime * 0.03) * 0.30
       + cos(p.x * 5.1 + p.z * 9.7 + uTime * 0.07) * 0.20
       + sin(p.y * 20.0 + p.z * 17.0) * 0.05;
}

vec3 hsl2rgb(vec3 c) {
  float h = c.x, s = c.y, l = c.z;
  float C = (1.0 - abs(2.0 * l - 1.0)) * s;
  float X = C * (1.0 - abs(mod(h * 6.0, 2.0) - 1.0));
  float m = l - C * 0.5;
  vec3 rgb;
  float hh = h * 6.0;
  if      (hh < 1.0) rgb = vec3(C, X, 0.0);
  else if (hh < 2.0) rgb = vec3(X, C, 0.0);
  else if (hh < 3.0) rgb = vec3(0.0, C, X);
  else if (hh < 4.0) rgb = vec3(0.0, X, C);
  else if (hh < 5.0) rgb = vec3(X, 0.0, C);
  else               rgb = vec3(C, 0.0, X);
  return rgb + m;
}

void main() {
  float i = aIndex;
  float count = uParticleCount;

  // ── Fibonacci sphere ──────────────────────────────────────────────────
  float phi   = acos(1.0 - 2.0 * (i / count));
  float theta = sqrt(count * 3.14159265) * phi + uTime * uRotSpeed;
  float sPhi = sin(phi), cPhi = cos(phi);
  float sThe = sin(theta), cThe = cos(theta);
  float lat = cPhi, lon = atan(sThe, cThe);

  // ── Terrain ───────────────────────────────────────────────────────────
  float terrain = noise3(vec3(lat, lon, 0.0));
  bool isOcean = terrain < -0.05;
  bool isMtn   = terrain > 0.30;
  bool isPolar = abs(lat) > 0.82;

  float cloudNoise = sin(lat * 12.0 + lon * 9.0 + uTime * 0.12)
                   * cos(lat * 7.0 - lon * 13.0 + uTime * 0.09);
  float cloudThr = 1.0 - (3.7 + uActivity * 1.2) * 0.09;
  bool isCloud = cloudNoise > cloudThr;
  bool isAtmo  = i > count * 0.92;

  // ── Storm spirals ─────────────────────────────────────────────────────
  float stormD = 0.0;
  for (int s = 0; s < 3; s++) {
    vec3 st = (s == 0) ? uStorm0 : (s == 1) ? uStorm1 : uStorm2;
    if (st.z > 0.01 && isCloud) {
      float d = length(vec2(lat - st.x, lon - st.y));
      if (d < 0.4) {
        stormD += sin(d * 15.0 - uTime * 2.0 * st.z) * st.z * (0.4 - d) * 3.0;
      }
    }
  }

  // ── Radii ─────────────────────────────────────────────────────────────
  float R = uRadius;
  float cloudR = R + 1.2 + sin(lon * 5.0 + uTime * 0.1) * 0.4 + stormD;
  float atmoR  = R + 15.0 * (0.8 + sin(lon * 3.0 + lat * 4.0 + uTime * 0.04) * 0.2);
  float landR  = R + max(0.0, terrain) * 3.5;
  float oceanR = R - abs(min(0.0, terrain)) * 5.0;
  float r = isAtmo ? atmoR : (isCloud ? cloudR : (isOcean ? oceanR : landR));

  // ── Audio displacement ────────────────────────────────────────────────
  if (isAtmo)       r += uAudioBass * 8.0 * sin(uTime * 0.5 + phi * 3.0);
  else if (isCloud) r += uAudioTreble * 2.0 * sin(lon * 8.0 + uTime * 3.0);
  else              r += uAudioMid * 1.5 * sin(lat * 12.0 + lon * 8.0 + uTime * 2.0);

  vec3 pos = vec3(sPhi * cThe * r, cPhi * r, sPhi * sThe * r);

  // ── Mouse gravity ────────────────────────────────────────────────────
  if (uMouseStrength > 0.01) {
    vec3 toM = uMouseWorld - pos;
    float md = length(toM);
    float att = min(uMouseStrength * 15.0 / (md * md + 5.0), 3.0);
    pos += normalize(toM) * att;
  }

  // ── Day / Night ──────────────────────────────────────────────────────
  float sunDot = dot(normalize(pos), normalize(uSunDir));
  float dayF = smoothstep(-0.2, 0.3, sunDot);

  // ── Color ────────────────────────────────────────────────────────────
  vec3 hsl;
  float cityLight = 0.0;

  if (isAtmo) {
    hsl = uAtmoHSL;
    hsl.z *= (0.3 + dayF * 0.7);
    float sunset = 1.0 - abs(sunDot);
    if (sunset > 0.7) { hsl.x = mix(hsl.x, 0.05, (sunset - 0.7) * 3.0); hsl.z += 0.15; }
  } else if (isCloud) {
    hsl = vec3(0.0, 0.0, 0.88 * (0.4 + dayF * 0.6));
    hsl.z += uAudioTreble * 0.1;
  } else if (isOcean) {
    hsl = uOceanHSL;
    hsl.z *= (0.2 + dayF * 0.8);
    hsl.z += sin(lon * 20.0 + uTime * 0.5) * 0.03;
  } else {
    if (isPolar) {
      hsl = vec3(0.0, 0.05, 0.92 * (0.3 + dayF * 0.7));
    } else if (isMtn && abs(lat) > 0.3) {
      hsl = vec3(0.0, 0.05, 0.95 * (0.3 + dayF * 0.7));
    } else if (isMtn) {
      hsl = vec3(uLandHSL.x - 0.2, 0.25, 0.38 * (0.3 + dayF * 0.7));
    } else {
      hsl = uLandHSL;
      hsl.z *= (0.25 + dayF * 0.75);
    }
    // City lights at night
    if (dayF < 0.3 && !isPolar) {
      float cn = hash2(vec2(lat * 50.0, lon * 50.0));
      if (cn > 0.82) {
        cityLight = (0.3 - dayF) * 3.0;
        hsl = vec3(0.10, 0.90, 0.70 * cityLight);
      }
    }
  }

  if (uLightning > 0.5 && isCloud) hsl.z = min(hsl.z + 0.5, 1.0);

  vColor  = hsl2rgb(hsl);
  vAlpha  = isAtmo ? (0.08 + uActivity * 0.1 + uAudioBass * 0.05) : (isCloud ? 0.65 : 0.9);
  vGlow   = isAtmo ? 0.5 : (cityLight > 0.1 ? 0.6 : 0.0);
  vIsAtmo = isAtmo ? 1.0 : 0.0;

  vec4 mvPos = modelViewMatrix * vec4(pos, 1.0);
  gl_Position = projectionMatrix * mvPos;

  float ptSz = isAtmo ? 2.0 : (isCloud ? 1.4 : 1.1);
  ptSz += cityLight * 1.0 + uAudioBass * 0.4;
  gl_PointSize = ptSz * (180.0 / -mvPos.z);
}
`;


// ─────────────────────────────────────────────────────────────────────────────
// FRAGMENT SHADER
// ─────────────────────────────────────────────────────────────────────────────
const FRAG = /* glsl */ `
precision highp float;
varying vec3 vColor; varying float vAlpha, vGlow, vIsAtmo;

void main() {
  vec2 c = gl_PointCoord - vec2(0.5);
  float d = length(c);
  if (d > 0.5) discard;
  float a = vAlpha * smoothstep(0.5, 0.2, d);
  if (vGlow  > 0.1) a *= (1.0 + vGlow * 0.8 * smoothstep(0.5, 0.0, d));
  if (vIsAtmo > 0.5) a *= smoothstep(0.5, 0.0, d) * 0.35;
  gl_FragColor = vec4(vColor, a);
}
`;


// ─────────────────────────────────────────────────────────────────────────────
// AURORA SHADERS — polar ribbons during thinking
// ─────────────────────────────────────────────────────────────────────────────
const AURORA_VERT = /* glsl */ `
precision highp float;
attribute float aIndex;
uniform float uTime, uIntensity, uRadius;
varying vec3 vColor; varying float vAlpha;

float hash(float n) { return fract(sin(n) * 43758.5453); }
vec3 hsl2rgb(vec3 c) {
  float C = (1.0 - abs(2.0 * c.z - 1.0)) * c.y;
  float X = C * (1.0 - abs(mod(c.x * 6.0, 2.0) - 1.0));
  float m = c.z - C * 0.5;
  vec3 rgb; float h = c.x * 6.0;
  if (h<1.0) rgb=vec3(C,X,0); else if (h<2.0) rgb=vec3(X,C,0);
  else if (h<3.0) rgb=vec3(0,C,X); else if (h<4.0) rgb=vec3(0,X,C);
  else if (h<5.0) rgb=vec3(X,0,C); else rgb=vec3(C,0,X);
  return rgb + m;
}
void main() {
  float i = aIndex, total = 3000.0;
  float pole = (i < total * 0.5) ? 1.0 : -1.0;
  float li = mod(i, total * 0.5);
  float ang = (li / (total * 0.5)) * 6.28318 * 3.0;
  float rr = uRadius + 16.0 + sin(ang * 2.0 + uTime * 1.5) * 4.0;
  float w1 = sin(ang * 5.0 + uTime * 2.0 + li * 0.02) * 5.0;
  float w2 = cos(ang * 3.0 + uTime * 1.2) * 3.0;
  float po = 0.75 + hash(i * 7.13) * 0.15;
  float phi = acos(pole * po);
  vec3 pos = vec3(sin(phi)*cos(ang)*rr, cos(phi)*rr + w1 + w2, sin(phi)*sin(ang)*rr);
  float hue = 0.33 + sin(ang*2.0+uTime*0.5)*0.15 + hash(i*3.7)*0.1;
  vColor = hsl2rgb(vec3(hue, 0.7+hash(i*11.3)*0.3, 0.4+sin(ang*7.0+uTime*3.0)*0.2+hash(i*5.1)*0.1));
  vAlpha = uIntensity * (0.3 + sin(ang*4.0+uTime*2.5)*0.2) * smoothstep(0.0, 0.3, uIntensity);
  vec4 mv = modelViewMatrix * vec4(pos, 1.0);
  gl_Position = projectionMatrix * mv;
  gl_PointSize = (3.0 + sin(uTime*3.0+i*0.1)*1.5) * uIntensity * (200.0 / -mv.z);
}
`;

const AURORA_FRAG = /* glsl */ `
precision highp float;
varying vec3 vColor; varying float vAlpha;
void main() {
  float d = length(gl_PointCoord - vec2(0.5));
  if (d > 0.5) discard;
  gl_FragColor = vec4(vColor, vAlpha * smoothstep(0.5, 0.0, d) * 0.7);
}
`;


// ─────────────────────────────────────────────────────────────────────────────
// MAIN CLASS
// ─────────────────────────────────────────────────────────────────────────────
export class ParticlesSwarm {
  constructor(container, count = 50000) {
    if (!container) throw new Error("ParticlesSwarm requires a valid container element");

    this.count = Math.max(5000, Math.floor(count));
    this.container = container;
    this.disposed = false;
    this.paused = false;
    this.animationFrameId = null;

    // ── State ────────────────────────────────────────────────────────────
    this.activity = 0;
    this.smoothedActivity = 0;
    this.isListening = false;
    this.isThinking = false;
    this.isSpeaking = false;

    // Emotion
    this.currentPalette = { ...EMOTION_PALETTES.neutral };
    this.targetPalette  = { ...EMOTION_PALETTES.neutral };

    // Audio
    this.analyserNode = null;
    this.audioData = new Uint8Array(128);
    this.audioBass = 0; this.audioMid = 0; this.audioTreble = 0;

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
    this.lightningTimer = 0; this.lightningFlash = 0;
    this.sunAngle = 0;

    // FPS throttle
    this.maxFps = 60;
    this.frameInterval = 1000 / this.maxFps;
    this.lastFrameAt = 0;

    // ── Three.js ─────────────────────────────────────────────────────────
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(60, 1, 0.1, 2000);
    this.camera.position.set(0, 0, 120);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.container.appendChild(this.renderer.domElement);

    this.composer = new EffectComposer(this.renderer);
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloomPass = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.8, 0.3, 0.75);
    this.composer.addPass(this.bloomPass);

    // ── Build particle systems ───────────────────────────────────────────
    this._createEarth();
    this._createAurora();

    // ── Mouse/Touch events ───────────────────────────────────────────────
    this._onMove = this._onMove.bind(this);
    this._onDown = () => { this.mouseStrength = 3.0; };
    this._onUp   = () => { this.mouseStrength = Math.min(this.mouseStrength, 1.0); };
    this._onOut  = () => { this.mouseStrength = 0; };
    this.container.addEventListener("mousemove", this._onMove);
    this.container.addEventListener("mousedown", this._onDown);
    this.container.addEventListener("mouseup", this._onUp);
    this.container.addEventListener("mouseleave", this._onOut);
    this.container.addEventListener("touchmove", (e) => {
      e.preventDefault();
      this._onMove({ clientX: e.touches[0].clientX, clientY: e.touches[0].clientY });
    }, { passive: false });
    this.container.addEventListener("touchstart", (e) => {
      this._onMove({ clientX: e.touches[0].clientX, clientY: e.touches[0].clientY });
      this._onDown();
    });
    this.container.addEventListener("touchend", this._onUp);

    // ── Start ────────────────────────────────────────────────────────────
    this.clock = new THREE.Clock();
    this.animate = this.animate.bind(this);
    this.resize();
    this.animate();
  }


  // ═══════════════════════════════════════════════════════════════════════════
  // PARTICLE CREATION
  // ═══════════════════════════════════════════════════════════════════════════
  _createEarth() {
    const geo = new THREE.BufferGeometry();
    const idx = new Float32Array(this.count);
    const rnd = new Float32Array(this.count * 3);
    const pos = new Float32Array(this.count * 3); // dummy, computed in shader

    for (let i = 0; i < this.count; i++) {
      idx[i] = i;
      rnd[i * 3] = Math.random(); rnd[i * 3 + 1] = Math.random(); rnd[i * 3 + 2] = Math.random();
    }

    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("aIndex",   new THREE.BufferAttribute(idx, 1));
    geo.setAttribute("aRandom",  new THREE.BufferAttribute(rnd, 3));

    const p = EMOTION_PALETTES.neutral;
    this.eu = {
      uTime:          { value: 0 },
      uParticleCount: { value: this.count },
      uActivity:      { value: 0 },
      uRadius:        { value: 45.7 },
      uRotSpeed:      { value: 0.27 },
      uSunDir:        { value: new THREE.Vector3(1, 0.3, 0.5).normalize() },
      uAudioBass:     { value: 0 }, uAudioMid: { value: 0 }, uAudioTreble: { value: 0 },
      uMouseWorld:    { value: new THREE.Vector3() },
      uMouseStrength: { value: 0 },
      uStorm0:        { value: new THREE.Vector3(0.3, 0, 0) },
      uStorm1:        { value: new THREE.Vector3(-0.2, 2, 0) },
      uStorm2:        { value: new THREE.Vector3(0.5, 4, 0) },
      uLightning:     { value: 0 },
      uOceanHSL:      { value: new THREE.Vector3(...p.ocean) },
      uLandHSL:       { value: new THREE.Vector3(...p.land) },
      uAtmoHSL:       { value: new THREE.Vector3(...p.atmo) },
      uAccentHSL:     { value: new THREE.Vector3(...p.accent) },
    };

    this.earthMat = new THREE.ShaderMaterial({
      vertexShader: VERT, fragmentShader: FRAG,
      uniforms: this.eu,
      transparent: true, depthWrite: false,
      blending: THREE.NormalBlending,
    });

    this.earthPts = new THREE.Points(geo, this.earthMat);
    this.scene.add(this.earthPts);
  }

  _createAurora() {
    const N = 3000;
    const geo = new THREE.BufferGeometry();
    const idx = new Float32Array(N);
    const pos = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) idx[i] = i;

    geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    geo.setAttribute("aIndex",   new THREE.BufferAttribute(idx, 1));

    this.au = {
      uTime:      { value: 0 },
      uIntensity: { value: 0 },
      uRadius:    { value: 45.7 },
    };

    this.auroraMat = new THREE.ShaderMaterial({
      vertexShader: AURORA_VERT, fragmentShader: AURORA_FRAG,
      uniforms: this.au,
      transparent: true, depthWrite: false,
      blending: THREE.AdditiveBlending,
    });

    this.auroraPts = new THREE.Points(geo, this.auroraMat);
    this.scene.add(this.auroraPts);
  }


  // ═══════════════════════════════════════════════════════════════════════════
  // PUBLIC API
  // ═══════════════════════════════════════════════════════════════════════════
  setRealtimeSignals({ isListening, isThinking, isSpeaking, activity } = {}) {
    if (typeof isListening === "boolean") this.isListening = isListening;
    if (typeof isThinking  === "boolean") this.isThinking  = isThinking;
    if (typeof isSpeaking  === "boolean") this.isSpeaking  = isSpeaking;
    if (typeof activity    === "number")  this.activity = Math.max(0, Math.min(1, activity));
  }

  setEmotion(label, confidence = 1.0) {
    this.targetPalette = { ...(EMOTION_PALETTES[label] || EMOTION_PALETTES.neutral) };
  }

  setAudioData(analyserNode) {
    this.analyserNode = analyserNode;
    if (analyserNode) this.audioData = new Uint8Array(analyserNode.frequencyBinCount || 128);
  }

  setPaused(paused) { this.paused = !!paused; }


  // ═══════════════════════════════════════════════════════════════════════════
  // MOUSE
  // ═══════════════════════════════════════════════════════════════════════════
  _onMove(e) {
    const r = this.container.getBoundingClientRect();
    this.mouse.x = ((e.clientX - r.left) / r.width) * 2 - 1;
    this.mouse.y = -((e.clientY - r.top) / r.height) * 2 + 1;
    this.raycaster.setFromCamera(this.mouse, this.camera);
    const hit = new THREE.Vector3();
    if (this.raycaster.ray.intersectSphere(this.mouseSphere, hit)) {
      this.mouseWorld.copy(hit);
      this.mouseStrength = Math.max(this.mouseStrength, 1.0);
    } else {
      this.mouseStrength = 0;
    }
  }

  resize() {
    const w = Math.max(1, this.container.clientWidth || 1);
    const h = Math.max(1, this.container.clientHeight || 1);
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
    this.composer.setSize(w, h);
    this.bloomPass.setSize(w, h);
  }


  // ═══════════════════════════════════════════════════════════════════════════
  // ANIMATION LOOP
  // ═══════════════════════════════════════════════════════════════════════════
  animate(now = 0) {
    if (this.disposed) return;
    this.animationFrameId = requestAnimationFrame(this.animate);
    if (this.paused) return;
    if (now && this.lastFrameAt && now - this.lastFrameAt < this.frameInterval) return;
    this.lastFrameAt = now;

    const dt = this.clock.getDelta();
    const elapsed = this.clock.getElapsedTime();

    // ── Activity smoothing ──────────────────────────────────────────────
    const boost = this.isSpeaking ? 0.9 : this.isListening ? 0.55 : this.isThinking ? 0.35 : 0.12;
    this.smoothedActivity += (Math.max(boost, this.activity) - this.smoothedActivity) * 0.15;
    const time = elapsed * (0.75 + this.smoothedActivity * 2.2);

    // ── Audio ────────────────────────────────────────────────────────────
    if (this.analyserNode) {
      this.analyserNode.getByteFrequencyData(this.audioData);
      const len = this.audioData.length, t = Math.floor(len / 3);
      let b = 0, m = 0, tr = 0;
      for (let i = 0; i < t; i++) b += this.audioData[i];
      for (let i = t; i < t * 2; i++) m += this.audioData[i];
      for (let i = t * 2; i < len; i++) tr += this.audioData[i];
      this.audioBass   += (b / (t * 255) - this.audioBass) * 0.3;
      this.audioMid    += (m / (t * 255) - this.audioMid) * 0.3;
      this.audioTreble += (tr / ((len - t * 2) * 255) - this.audioTreble) * 0.3;
    } else {
      this.audioBass *= 0.95; this.audioMid *= 0.95; this.audioTreble *= 0.95;
    }

    // ── Emotion palette lerp ────────────────────────────────────────────
    const lr = 0.04;
    for (const k of ["ocean", "land", "atmo", "accent"]) {
      const c = this.currentPalette[k], t2 = this.targetPalette[k];
      if (c && t2) { c[0] += (t2[0]-c[0])*lr; c[1] += (t2[1]-c[1])*lr; c[2] += (t2[2]-c[2])*lr; }
    }
    this.bloomPass.strength += ((this.targetPalette.bloom || 1.8) - this.bloomPass.strength) * lr;

    // ── Day/Night sun ───────────────────────────────────────────────────
    this.sunAngle += dt * 0.08;
    this.eu.uSunDir.value.set(Math.cos(this.sunAngle), Math.sin(this.sunAngle) * 0.3, Math.sin(this.sunAngle)).normalize();

    // ── Storms ──────────────────────────────────────────────────────────
    for (const s of this.storms) {
      s.lon += s.drift * dt * 10;
      if (s.intensity <= 0.01) {
        if (Math.random() < 0.002) { s.intensity = 0.5 + Math.random() * 0.5; s.lat = (Math.random()-0.5)*1.2; s.lon = Math.random()*6.28; }
      } else { s.intensity *= 0.999; }
    }
    this.lightningTimer -= dt;
    if (this.lightningTimer <= 0) {
      if (this.storms.some(s => s.intensity > 0.3) && Math.random() < 0.3) {
        this.lightningFlash = 1.0; this.lightningTimer = 0.05 + Math.random() * 0.1;
      } else { this.lightningFlash = 0; this.lightningTimer = 0.5 + Math.random() * 2.0; }
    } else { this.lightningFlash *= 0.85; }

    // ── Update uniforms ─────────────────────────────────────────────────
    const u = this.eu;
    u.uTime.value = time;
    u.uActivity.value = this.smoothedActivity;
    u.uRotSpeed.value = 0.27 + this.smoothedActivity * 0.6;
    u.uAudioBass.value = this.audioBass;
    u.uAudioMid.value = this.audioMid;
    u.uAudioTreble.value = this.audioTreble;
    u.uMouseWorld.value.copy(this.mouseWorld);
    u.uMouseStrength.value += (this.mouseStrength - u.uMouseStrength.value) * 0.15;
    u.uStorm0.value.set(this.storms[0].lat, this.storms[0].lon, this.storms[0].intensity);
    u.uStorm1.value.set(this.storms[1].lat, this.storms[1].lon, this.storms[1].intensity);
    u.uStorm2.value.set(this.storms[2].lat, this.storms[2].lon, this.storms[2].intensity);
    u.uLightning.value = this.lightningFlash;
    u.uOceanHSL.value.set(...this.currentPalette.ocean);
    u.uLandHSL.value.set(...this.currentPalette.land);
    u.uAtmoHSL.value.set(...this.currentPalette.atmo);
    u.uAccentHSL.value.set(...this.currentPalette.accent);

    // Aurora
    const auroraT = this.isThinking ? 1.0 : (this.isSpeaking ? 0.4 : 0.0);
    this.au.uTime.value = elapsed;
    this.au.uIntensity.value += (auroraT - this.au.uIntensity.value) * 0.08;

    this.composer.render();
  }


  // ═══════════════════════════════════════════════════════════════════════════
  // DISPOSE
  // ═══════════════════════════════════════════════════════════════════════════
  dispose() {
    this.disposed = true;
    if (this.animationFrameId) { cancelAnimationFrame(this.animationFrameId); this.animationFrameId = null; }

    this.container.removeEventListener("mousemove", this._onMove);
    this.container.removeEventListener("mousedown", this._onDown);
    this.container.removeEventListener("mouseup", this._onUp);
    this.container.removeEventListener("mouseleave", this._onOut);

    this.earthPts.geometry.dispose(); this.earthMat.dispose(); this.scene.remove(this.earthPts);
    this.auroraPts.geometry.dispose(); this.auroraMat.dispose(); this.scene.remove(this.auroraPts);
    this.composer?.dispose?.();
    this.renderer.dispose();
    if (this.renderer.domElement?.parentNode === this.container) this.container.removeChild(this.renderer.domElement);
  }
}
