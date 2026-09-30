/**
 * RealisticFogCanvas — Real-time WebGL Volumetric Cloud & Fog Shader with Mouse Fluid Dynamics
 * ==========================================================================================
 * - Soft, billowing, organic 3D-styled volumetric clouds and rolling fog.
 * - Real-time Mouse Pointer Fluid Vector Reaction (clouds part, swirl, and ripple with cursor).
 * - Full-screen seamless background (no harsh cutouts or dark shadows).
 * - Rock-solid 60FPS GPU performance with ZERO shader recompilations (No flickering).
 */

import React, { memo, useEffect, useRef } from "react";

const VERTEX_SHADER = `
  attribute vec2 position;
  varying vec2 vUv;
  void main() {
    vUv = position * 0.5 + 0.5;
    gl_Position = vec4(position, 0.0, 1.0);
  }
`;

const FRAGMENT_SHADER = `
  precision highp float;
  varying vec2 vUv;
  uniform float u_time;
  uniform vec2 u_resolution;
  uniform vec2 u_mouse;
  uniform float u_mouse_speed;
  uniform float u_voice_intensity;
  uniform float u_speaking;

  // ── 2D Simplex/Perlin Noise Helpers ─────────────────────────────────────
  vec3 mod289(vec3 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec2 mod289(vec2 x) { return x - floor(x * (1.0 / 289.0)) * 289.0; }
  vec3 permute(vec3 x) { return mod289(((x * 34.0) + 1.0) * x); }

  float snoise(vec2 v) {
    const vec4 C = vec4(0.211324865405187,
                        0.366025403784439,
                       -0.577350269189626,
                        0.024390243902439);
    vec2 i  = floor(v + dot(v, C.yy));
    vec2 x0 = v -   i + dot(i, C.xx);
    vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
    vec4 x12 = x0.xyxy + C.xxzz;
    x12.xy -= i1;
    i = mod289(i);
    vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0)) + i.x + vec3(0.0, i1.x, 1.0));
    vec3 m = max(0.5 - vec3(dot(x0, x0), dot(x12.xy, x12.xy), dot(x12.zw, x12.zw)), 0.0);
    m = m * m;
    m = m * m;
    vec3 x = 2.0 * fract(p * C.www) - 1.0;
    vec3 h = abs(x) - 0.5;
    vec3 ox = floor(x + 0.5);
    vec3 a0 = x - ox;
    m *= 1.79284291400159 - 0.85373472095314 * (a0 * a0 + h * h);
    vec3 g;
    g.x  = a0.x  * x0.x  + h.x  * x0.y;
    g.yz = a0.yz * x12.xz + h.yz * x12.yw;
    return 130.0 * dot(m, g);
  }

  // ── Soft Volumetric Cloud fBm (Smooth, billowy octaves) ─────────────────
  float fbm(vec2 p) {
    float total = 0.0;
    float amplitude = 0.55;
    float frequency = 0.85;
    for (int i = 0; i < 5; i++) {
      total += amplitude * snoise(p * frequency);
      frequency *= 1.95;
      amplitude *= 0.5;
    }
    return total;
  }

  void main() {
    vec2 uv = gl_FragCoord.xy / u_resolution.xy;
    float aspect = u_resolution.x / u_resolution.y;
    vec2 p = vec2(uv.x * aspect, uv.y) * 1.1;

    // ── Mouse Pointer Fluid Vector Reaction ───────────────────────────────
    vec2 mouseNorm = vec2(u_mouse.x * aspect, u_mouse.y) * 1.1;
    vec2 mouseDiff = p - mouseNorm;
    float distToMouse = length(mouseDiff);

    // Swirl and push clouds softly with mouse movement
    float mouseForce = exp(-distToMouse * 2.5) * (0.35 + u_mouse_speed * 1.0);
    vec2 swirl = vec2(-mouseDiff.y, mouseDiff.x) * mouseForce * 0.7;
    p += swirl + normalize(mouseDiff + 0.001) * mouseForce * 0.35;

    float t = u_time * 0.025;

    // Soft domain warping for organic drifting cloud plumes
    vec2 q = vec2(fbm(p + vec2(0.0, t * 0.15)), fbm(p + vec2(5.2, 1.3 - t * 0.12)));
    vec2 r = vec2(fbm(p + 2.0 * q + vec2(1.7, 9.2 + t * 0.2)), fbm(p + 2.0 * q + vec2(8.3, 2.8 - t * 0.18)));

    float cloudDensity = fbm(p + 2.4 * r + vec2(t * 0.25, t * 0.08));

    // Normalize density to smooth [0, 1] range
    cloudDensity = clamp((cloudDensity + 0.4) * 0.85, 0.0, 1.0);

    // Soft billowing cloud mask
    float cloudMask = smoothstep(0.1, 0.9, cloudDensity);

    // ── Color Palette: Deep Midnight to Glowing Cyan & Lavender Clouds ──
    vec3 deepSkyColor = vec3(0.024, 0.039, 0.078);       // #060a14
    vec3 deepMistColor = vec3(0.035, 0.09, 0.20);        // Deep sapphire mist
    vec3 cloudCyanHighlight = vec3(0.0, 0.83, 1.0);      // #00d4ff neon cyan
    vec3 cloudPurpleHighlight = vec3(0.72, 0.45, 0.98);  // Lavender / neon purple
    vec3 cloudWhiteWisp = vec3(0.85, 0.94, 1.0);         // Soft ethereal white

    // Multi-spectral atmospheric blending
    vec3 cloudColor = mix(deepMistColor, cloudPurpleHighlight, smoothstep(0.25, 0.65, cloudDensity) * 0.5);
    cloudColor = mix(cloudColor, cloudCyanHighlight, smoothstep(0.45, 0.85, cloudDensity) * 0.65);
    cloudColor = mix(cloudColor, cloudWhiteWisp, smoothstep(0.7, 1.0, cloudDensity) * 0.3);

    // Subtle neon highlight trail following mouse movement
    cloudColor += cloudCyanHighlight * mouseForce * 0.4;

    // AI Speech / Voice illumination
    float illumination = u_speaking * 0.3 + u_voice_intensity * 0.4;
    cloudColor += cloudCyanHighlight * illumination * cloudMask;

    // Final smooth composition
    vec3 finalColor = mix(deepSkyColor, cloudColor, cloudMask * 0.7);

    gl_FragColor = vec4(finalColor, cloudMask * 0.8);
  }
`;

export const RealisticFogCanvas = memo(function RealisticFogCanvas({
  voiceActivity = 0,
  isSpeaking = false,
}) {
  const canvasRef = useRef(null);
  const mouseRef = useRef({ x: 0.5, y: 0.5, prevX: 0.5, prevY: 0.5, speed: 0 });
  const voiceRef = useRef({ activity: 0, isSpeaking: false });

  // Keep refs in sync with incoming props without re-triggering WebGL initialization
  useEffect(() => {
    voiceRef.current.activity = voiceActivity;
    voiceRef.current.isSpeaking = isSpeaking;
  }, [voiceActivity, isSpeaking]);

  useEffect(() => {
    const handleMouseMove = (e) => {
      const x = e.clientX / window.innerWidth;
      const y = 1.0 - (e.clientY / window.innerHeight);
      const dx = x - mouseRef.current.prevX;
      const dy = y - mouseRef.current.prevY;
      const speed = Math.min(Math.sqrt(dx * dx + dy * dy) * 12.0, 1.0);

      mouseRef.current.x = x;
      mouseRef.current.y = y;
      mouseRef.current.prevX = x;
      mouseRef.current.prevY = y;
      mouseRef.current.speed = speed;
    };

    window.addEventListener("mousemove", handleMouseMove);
    return () => window.removeEventListener("mousemove", handleMouseMove);
  }, []);

  // WebGL Shader lifecycle runs ONCE on mount
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const gl = canvas.getContext("webgl", {
      alpha: true,
      premultipliedAlpha: false,
      antialias: false,
      powerPreference: "high-performance",
    });
    if (!gl) return;

    // Helper: Compile Shader
    const compileShader = (src, type) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, src);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        console.error("Shader error:", gl.getShaderInfoLog(shader));
        gl.deleteShader(shader);
        return null;
      }
      return shader;
    };

    const vert = compileShader(VERTEX_SHADER, gl.VERTEX_SHADER);
    const frag = compileShader(FRAGMENT_SHADER, gl.FRAGMENT_SHADER);
    if (!vert || !frag) return;

    const program = gl.createProgram();
    gl.attachShader(program, vert);
    gl.attachShader(program, frag);
    gl.linkProgram(program);

    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
      console.error("Program error:", gl.getProgramInfoLog(program));
      return;
    }

    gl.useProgram(program);

    // Fullscreen Quad Buffer
    const quadBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, quadBuffer);
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, -1, 1, 1, -1, 1, 1]),
      gl.STATIC_DRAW
    );

    const posAttr = gl.getAttribLocation(program, "position");
    gl.enableVertexAttribArray(posAttr);
    gl.vertexAttribPointer(posAttr, 2, gl.FLOAT, false, 0, 0);

    // Uniform Locations
    const uTime = gl.getUniformLocation(program, "u_time");
    const uResolution = gl.getUniformLocation(program, "u_resolution");
    const uMouse = gl.getUniformLocation(program, "u_mouse");
    const uMouseSpeed = gl.getUniformLocation(program, "u_mouse_speed");
    const uVoiceIntensity = gl.getUniformLocation(program, "u_voice_intensity");
    const uSpeaking = gl.getUniformLocation(program, "u_speaking");

    let animId = null;
    let startTime = performance.now();
    let currentMouse = { x: 0.5, y: 0.5 };
    let currentSpeed = 0;

    const handleResize = () => {
      if (!canvas) return;
      const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = window.innerWidth * dpr;
      canvas.height = window.innerHeight * dpr;
      gl.viewport(0, 0, canvas.width, canvas.height);
    };

    window.addEventListener("resize", handleResize);
    handleResize();

    const render = (now) => {
      const elapsed = (now - startTime) / 1000.0;

      // Smooth lerp mouse position and speed
      currentMouse.x += (mouseRef.current.x - currentMouse.x) * 0.08;
      currentMouse.y += (mouseRef.current.y - currentMouse.y) * 0.08;
      currentSpeed += (mouseRef.current.speed - currentSpeed) * 0.08;
      mouseRef.current.speed *= 0.95;

      gl.uniform1f(uTime, elapsed);
      gl.uniform2f(uResolution, canvas.width, canvas.height);
      gl.uniform2f(uMouse, currentMouse.x, currentMouse.y);
      gl.uniform1f(uMouseSpeed, currentSpeed);
      gl.uniform1f(uVoiceIntensity, voiceRef.current.activity);
      gl.uniform1f(uSpeaking, voiceRef.current.isSpeaking ? 1.0 : 0.0);

      gl.drawArrays(gl.TRIANGLES, 0, 6);
      animId = requestAnimationFrame(render);
    };

    animId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener("resize", handleResize);
      gl.deleteProgram(program);
      gl.deleteShader(vert);
      gl.deleteShader(frag);
    };
  }, []); // Run ONCE on mount

  return (
    <canvas
      ref={canvasRef}
      className="realistic-fog-canvas"
      aria-hidden="true"
      style={{
        position: "fixed",
        inset: 0,
        width: "100vw",
        height: "100vh",
        pointerEvents: "none",
        zIndex: 0,
      }}
    />
  );
});
