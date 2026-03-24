/**
 * AnimeAvatar — Real-Time Photo Mesh Warping
 *
 * How it works:
 *  1. Loads the avatar photo into an offscreen canvas (source texture)
 *  2. Detects 68 face landmark points using face-api.js (runs once)
 *  3. Builds a Delaunay triangle mesh from those points covering
 *     the entire face + body region
 *  4. Each animation frame:
 *     a. Computes new landmark positions based on the current
 *        emotion/state (morph targets with spring physics)
 *     b. For every triangle: draws the SOURCE triangle pixels onto
 *        the DESTINATION warped position using canvas affine transform
 *  5. The result = actual photo pixels physically moving — not overlays
 *
 * States driven:
 *  - Speaking  → jaw opens (real mouth pixels separate), body bounces
 *  - Listening → head tilts (all face pixels rotate)
 *  - Thinking  → eyes look up-right, brow furrows
 *  - Emotions  → full expression morphs (smile, frown, wide eyes, etc.)
 *  - Idle      → breathing, natural blink, slow sway
 */

import { useEffect, useRef, useCallback, useState } from "react";
import avatarImg from "../../assets/images/avatar.png";

// ─────────────────────────────────────────────────────────────────────────────
// Spring physics for smooth morph blending
// ─────────────────────────────────────────────────────────────────────────────
function makeSpring(stiffness = 0.1, damping = 0.72) {
    let v = 0, x = 0;
    return {
        update(target) {
            v = v * damping + (target - x) * stiffness;
            x += v;
            return x;
        },
        get() { return x; },
        set(val) { x = val; v = 0; },
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Affine transform: maps source triangle → destination triangle
// Canvas 2D ctx.transform(a, b, c, d, e, f) applies:
//   x' = a*x + c*y + e
//   y' = b*x + d*y + f
// We solve: given 3 src→dst point pairs, find [a,b,c,d,e,f]
// ─────────────────────────────────────────────────────────────────────────────
function getAffineTransform(s0, s1, s2, d0, d1, d2) {
    // Build 3x3 system: [s0 s1 s2] -> [d0 d1 d2]
    // Each point: x'=a*x + c*y + e,  y'=b*x + d*y + f
    const [x0, y0] = s0, [x1, y1] = s1, [x2, y2] = s2;
    const [u0, v0] = d0, [u1, v1] = d1, [u2, v2] = d2;

    const det = x0 * (y1 - y2) + x1 * (y2 - y0) + x2 * (y0 - y1);
    if (Math.abs(det) < 0.5) return [1, 0, 0, 1, d0[0] - s0[0], d0[1] - s0[1]];

    const a = ((u0 * (y1 - y2)) + (u1 * (y2 - y0)) + (u2 * (y0 - y1))) / det;
    const c = ((u0 * (x2 - x1)) + (u1 * (x0 - x2)) + (u2 * (x1 - x0))) / det;
    const e = ((u0 * (x1 * y2 - x2 * y1)) + (u1 * (x2 * y0 - x0 * y2)) + (u2 * (x0 * y1 - x1 * y0))) / det;

    const b = ((v0 * (y1 - y2)) + (v1 * (y2 - y0)) + (v2 * (y0 - y1))) / det;
    const d = ((v0 * (x2 - x1)) + (v1 * (x0 - x2)) + (v2 * (x1 - x0))) / det;
    const f = ((v0 * (x1 * y2 - x2 * y1)) + (v1 * (x2 * y0 - x0 * y2)) + (v2 * (x0 * y1 - x1 * y0))) / det;

    return [a, b, c, d, e, f];
}


// ─────────────────────────────────────────────────────────────────────────────
// Draw one warped triangle: clips to dst triangle, applies affine,
// and redraws the full source image (only the clipped triangle shows)
// ─────────────────────────────────────────────────────────────────────────────
function drawWarpedTriangle(ctx, srcCanvas, src, dst) {
    ctx.save();
    // Clip to destination triangle
    ctx.beginPath();
    ctx.moveTo(dst[0][0], dst[0][1]);
    ctx.lineTo(dst[1][0], dst[1][1]);
    ctx.lineTo(dst[2][0], dst[2][1]);
    ctx.closePath();
    ctx.clip();
    // Apply affine transform to map src → dst
    const [a, b, c, d, e, f] = getAffineTransform(src[0], src[1], src[2], dst[0], dst[1], dst[2]);
    ctx.transform(a, b, c, d, e, f);
    ctx.drawImage(srcCanvas, 0, 0);
    ctx.restore();
}

// ─────────────────────────────────────────────────────────────────────────────
// Normalize a landmark from face-api (0-1 relative) to pixel coords
// ─────────────────────────────────────────────────────────────────────────────
function normToImg(landmark, imgW, imgH) {
    return [landmark.x * imgW, landmark.y * imgH];
}

// ─────────────────────────────────────────────────────────────────────────────
// Build triangles from 68 face landmarks + body anchor points
// Returns array of [i, j, k] index triplets
// ─────────────────────────────────────────────────────────────────────────────
function buildTriangles(pts) {
    // face-api gives 68 points in specific order:
    // 0-16: jaw line, 17-21: left brow, 22-26: right brow,
    // 27-35: nose, 36-41: left eye, 42-47: right eye, 48-67: mouth
    // We add extra body/background anchors at indices 68+

    const tris = [];

    // Jaw + body coverage triangles
    // Forehead (brow to image top edge via anchor 68-72)
    tris.push([17, 19, 68], [19, 21, 68], [22, 24, 69], [24, 26, 69]);
    tris.push([17, 21, 70], [21, 22, 70], [22, 26, 71]);
    tris.push([68, 69, 70], [69, 70, 71]);

    // Left brow area
    tris.push([17, 18, 36], [18, 19, 36], [19, 20, 37], [20, 21, 37]);
    tris.push([36, 37, 38], [37, 38, 39]);

    // Right brow area
    tris.push([22, 23, 42], [23, 24, 42], [24, 25, 45], [25, 26, 45]);
    tris.push([42, 43, 44], [44, 45, 46]);

    // Between brows / nose bridge
    tris.push([21, 22, 27], [27, 21, 39], [27, 22, 42]);
    tris.push([27, 28, 29], [27, 39, 28]);

    // Nose area
    tris.push([28, 29, 30], [29, 30, 31], [30, 31, 32], [30, 32, 33], [33, 32, 34], [33, 34, 35]);
    tris.push([31, 32, 48], [35, 32, 54]);

    // Left eye
    tris.push([36, 37, 41], [37, 40, 41], [37, 38, 40], [38, 39, 40]);
    // Right eye
    tris.push([42, 43, 47], [43, 46, 47], [43, 44, 46], [44, 45, 46]);

    // Cheeks (eyes to jaw)
    tris.push([0, 1, 36], [1, 2, 36], [2, 3, 41], [3, 4, 40]); // left cheek
    tris.push([4, 5, 48], [5, 6, 58], [6, 7, 58], [7, 8, 57]); // left jaw
    tris.push([16, 15, 45], [15, 14, 45], [14, 13, 46], [13, 12, 47]); // right cheek
    tris.push([12, 11, 54], [11, 10, 55], [10, 9, 56], [9, 8, 57]); // right jaw

    // Nose to mouth
    tris.push([31, 49, 48], [31, 50, 49], [32, 50, 51], [32, 33, 51]);
    tris.push([33, 52, 51], [33, 53, 52], [35, 53, 54], [35, 54, 55]);
    tris.push([33, 34, 53], [34, 35, 55]);

    // Mouth region
    tris.push([48, 49, 60], [49, 50, 61], [50, 51, 62], [51, 52, 63]);
    tris.push([52, 53, 64], [53, 54, 65], [54, 55, 66], [55, 56, 67]);
    tris.push([56, 57, 67], [57, 58, 66], [58, 59, 65], [59, 60, 64]);
    tris.push([60, 61, 67], [61, 62, 66], [62, 63, 65], [63, 64, 65]);
    tris.push([60, 67, 66], [60, 66, 65], [60, 65, 64]);

    // Between nose and mouth
    tris.push([32, 48, 31], [32, 50, 48], [33, 54, 53]);

    // Jaw coverage
    tris.push([0, 1, 72], [1, 2, 72], [2, 3, 72], [3, 4, 72], [4, 5, 73]);
    tris.push([5, 6, 73], [6, 7, 73], [7, 8, 73], [8, 9, 74]);
    tris.push([9, 10, 74], [10, 11, 74], [11, 12, 74], [12, 13, 75]);
    tris.push([13, 14, 75], [14, 15, 75], [15, 16, 75]);

    tris.push([72, 73, 76], [73, 74, 76], [74, 75, 76], [75, 76, 77]);

    return tris;
}

// ─────────────────────────────────────────────────────────────────────────────
// Emotion → morph target offsets (as % of face bounding box)
// Each entry: { landmark_index: [dx, dy], ... }
// ─────────────────────────────────────────────────────────────────────────────
const MORPH_TARGETS = {
    // Jaw open (speaking): landmarks 6-10 pull down (inner jaw)
    jaw_open: {
        57: [0, 0.12], 58: [-0.02, 0.10], 56: [0.02, 0.10],
        8: [0, 0.06], 7: [-0.01, 0.04], 9: [0.01, 0.04],
        66: [0, 0.08], 65: [0, 0.08], 67: [0, 0.08], 64: [0, 0.08],
    },
    // Smile: mouth corners (48, 54) pull outward+up
    smile: {
        48: [-0.05, -0.03], 54: [0.05, -0.03],
        49: [-0.03, -0.04], 53: [0.03, -0.04],
        61: [-0.02, -0.02], 63: [0.02, -0.02],
    },
    // Frown: mouth corners pull down
    frown: {
        48: [-0.03, 0.04], 54: [0.03, 0.04],
        49: [-0.02, 0.03], 53: [0.02, 0.03],
        61: [-0.01, 0.02], 63: [0.01, 0.02],
    },
    // Brow raise (surprise/fear): brows move up
    brow_up: {
        17: [-0.01, -0.05], 18: [0, -0.06], 19: [0.01, -0.06], 20: [0, -0.06], 21: [0, -0.05],
        22: [0, -0.05], 23: [0, -0.06], 24: [-0.01, -0.06], 25: [0, -0.06], 26: [0.01, -0.05],
    },
    // Brow furrow (angry/thinking): brows move down + inward
    brow_down: {
        17: [0.02, 0.03], 18: [0.01, 0.04], 19: [0, 0.04], 20: [-0.01, 0.04], 21: [-0.02, 0.03],
        22: [0.02, 0.03], 23: [0.01, 0.04], 24: [0, 0.04], 25: [-0.01, 0.04], 26: [-0.02, 0.03],
    },
    // Eye squint (happy/confident)
    eye_squint: {
        37: [0, 0.015], 38: [0, 0.015], 40: [0, -0.010], 41: [0, -0.010],
        43: [0, 0.015], 44: [0, 0.015], 46: [0, -0.010], 47: [0, -0.010],
    },
    // Eye wide (surprise/fear)
    eye_wide: {
        37: [0, -0.02], 38: [0, -0.02], 40: [0, 0.02], 41: [0, 0.02],
        43: [0, -0.02], 44: [0, -0.02], 46: [0, 0.02], 47: [0, 0.02],
    },
    // Blink
    blink: {
        37: [0, 0.025], 38: [0, 0.025], 40: [0, -0.020], 41: [0, -0.020],
        43: [0, 0.025], 44: [0, 0.025], 46: [0, -0.020], 47: [0, -0.020],
    },
    // Head tilt (listening/interested) — shifts left facial half down, right up
    head_tilt_right: {
        0: [-0.02, 0.04], 1: [-0.01, 0.03], 2: [0, 0.02],
        16: [0.02, -0.04], 15: [0.01, -0.03], 14: [0, -0.02],
    },
    // Cheek puff (embarrassed)
    cheek_puff: {
        0: [-0.04, 0], 1: [-0.03, 0], 2: [-0.02, 0],
        16: [0.04, 0], 15: [0.03, 0], 14: [0.02, 0],
        3: [-0.01, 0.01], 13: [0.01, 0.01],
    },
};

// Which morphs to blend per emotional state
const EMOTION_BLEND = {
    neutral: { jaw_open: 0, smile: 0, frown: 0 },
    idle: { jaw_open: 0, smile: 0.08 },
    joy: { smile: 0.85, eye_squint: 0.5, brow_up: 0.2 },
    happy: { smile: 0.85, eye_squint: 0.5, brow_up: 0.2 },
    sad: { frown: 0.7, brow_down: 0.4, eye_squint: 0.2 },
    angry: { frown: 0.6, brow_down: 0.9, eye_wide: 0.1 },
    fear: { eye_wide: 0.9, brow_up: 0.8, jaw_open: 0.25 },
    surprised: { eye_wide: 0.95, brow_up: 0.9, jaw_open: 0.4, smile: 0 },
    disgust: { frown: 0.5, brow_down: 0.5, brow_up: 0 },
    confused: { brow_down: 0.4, head_tilt_right: 0.5, eye_wide: 0.15 },
    embarrassed: { smile: 0.3, cheek_puff: 0.5, eye_squint: 0.3 },
    confident: { smile: 0.5, brow_up: 0.1, eye_squint: 0.2 },
    interested: { smile: 0.35, head_tilt_right: 0.4, brow_up: 0.15 },
    listening: { head_tilt_right: 0.35, smile: 0.1, brow_up: 0.1 },
    thinking: { brow_down: 0.3, eyes_up: 0, eye_squint: 0.1, head_tilt_right: -0.2 },
    speaking: {},  // driven by audio amplitude dynamically
};

// ─────────────────────────────────────────────────────────────────────────────
// Main component
// ─────────────────────────────────────────────────────────────────────────────
export function AnimeAvatar({ isListening, isSpeaking, isThinking, emotion: emotionProp, sendVisionFrame }) {
    const canvasRef = useRef(null);
    const wrapRef = useRef(null);
    const animRef = useRef(null);
    const stateRef = useRef({ isListening, isSpeaking, isThinking, emotion: emotionProp || 'neutral' });
    const meshRef = useRef(null);   // { pts, tris, imgW, imgH, srcCanvas }
    const morphWeights = useRef({});
    const morphSprings = useRef({});
    const audioRef = useRef({ ctx: null, analyser: null, data: null, amp: 0 });
    const timeRef = useRef(0);
    const blinkTimer = useRef(3000 + Math.random() * 4000);
    const blinkAmt = useRef(makeSpring(0.2, 0.65));
    const swayAmt = useRef(makeSpring(0.04, 0.85));
    const breathAmt = useRef(makeSpring(0.03, 0.88));
    const [cameraOn, setCameraOn] = useState(false);
    const videoRef = useRef(null);
    const camStream = useRef(null);
    const loadedRef = useRef(false);

    stateRef.current = { isListening, isSpeaking, isThinking, emotion: emotionProp || 'neutral' };

    // ── Get a spring for each morph key ────────────────────────────────────────
    const getSpring = useCallback((key) => {
        if (!morphSprings.current[key]) {
            morphSprings.current[key] = makeSpring(0.08, 0.74);
        }
        return morphSprings.current[key];
    }, []);

    // ── Init audio analyser ─────────────────────────────────────────────────────
    const initAudio = useCallback(() => {
        if (audioRef.current.ctx) return;
        try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const analyser = ctx.createAnalyser();
            analyser.fftSize = 64;
            analyser.connect(ctx.destination);
            audioRef.current = { ctx, analyser, data: new Uint8Array(analyser.frequencyBinCount), amp: 0 };
        } catch (_) { }
    }, []);

    // ── Camera toggle ───────────────────────────────────────────────────────────
    const toggleCamera = useCallback(async () => {
        if (cameraOn) {
            camStream.current?.getTracks().forEach(t => t.stop());
            camStream.current = null;
            setCameraOn(false);
            return;
        }
        try {
            const s = await navigator.mediaDevices.getUserMedia({ video: { width: 320, height: 240 } });
            camStream.current = s;
            if (videoRef.current) videoRef.current.srcObject = s;
            setCameraOn(true);
            const snap = () => {
                if (!camStream.current) return;
                const c = document.createElement('canvas');
                c.width = 320; c.height = 240;
                c.getContext('2d').drawImage(videoRef.current, 0, 0);
                sendVisionFrame?.({ type: 'vision_frame', image_b64: c.toDataURL('image/jpeg', 0.7).split(',')[1] });
                setTimeout(snap, 5000);
            };
            setTimeout(snap, 1000);
        } catch (_) { }
    }, [cameraOn, sendVisionFrame]);

    // ── Load image + detect face landmarks using face-api.js ───────────────────
    useEffect(() => {
        let cancelled = false;

        const setup = async () => {
            // Dynamically load face-api.js from CDN (no npm install needed)
            if (!window.faceapi) {
                await new Promise((resolve, reject) => {
                    const s = document.createElement('script');
                    s.src = 'https://cdn.jsdelivr.net/npm/face-api.js@0.22.2/dist/face-api.min.js';
                    s.onload = resolve;
                    s.onerror = reject;
                    document.head.appendChild(s);
                });
            }

            // Load the tiny face landmark model — served locally from /public/weights/
            const MODEL_URL = '/weights';
            try {
                await window.faceapi.nets.faceLandmark68TinyNet.loadFromUri(MODEL_URL);
                await window.faceapi.nets.tinyFaceDetector.loadFromUri(MODEL_URL);
            } catch (e) {
                console.warn('[Avatar] Could not load face-api models:', e);
                setupFallbackMesh();
                return;
            }

            if (cancelled) return;

            // Create an Image element for the avatar
            const img = new Image();
            img.crossOrigin = 'anonymous';
            img.src = avatarImg;
            await new Promise((res, rej) => { img.onload = res; img.onerror = rej; });

            if (cancelled) return;

            // Draw image into offscreen source canvas
            const srcCanvas = document.createElement('canvas');
            srcCanvas.width = img.naturalWidth;
            srcCanvas.height = img.naturalHeight;
            srcCanvas.getContext('2d').drawImage(img, 0, 0);

            const imgW = srcCanvas.width;
            const imgH = srcCanvas.height;

            // Detect face landmarks
            let landmarks68 = null;
            try {
                const det = await window.faceapi
                    .detectSingleFace(img, new window.faceapi.TinyFaceDetectorOptions({ scoreThreshold: 0.2 }))
                    .withFaceLandmarks(true);
                if (det) {
                    landmarks68 = det.landmarks.positions; // Array of {x, y}
                }
            } catch (e) {
                console.warn('[Avatar] Face detection failed:', e);
            }

            if (!landmarks68) {
                console.warn('[Avatar] No face detected, using fallback mesh');
                setupFallbackMesh(srcCanvas, imgW, imgH);
                return;
            }

            // Convert to [x, y] arrays normalized to 0-1
            const basePts = landmarks68.map(p => [p.x / imgW, p.y / imgH]);

            // Add extra anchor points for full coverage:
            // 68-71: top of head
            // 72-75: jaw below, 76-77: body area
            const bb = getBoundingBox(basePts);
            const headPad = 0.25; // extra room above detected face
            basePts.push(
                [bb.minX - 0.05, bb.minY - headPad],  // 68 top-left
                [0.5, bb.minY - headPad],   // 69 top-center
                [bb.maxX + 0.05, bb.minY - headPad],   // 70 top-right
                [bb.minX - 0.08, bb.minY - headPad * 0.5], // 71 upper-left extra
                [0, bb.maxY + 0.10],  // 72 bottom-left-jaw
                [0.25, bb.maxY + 0.12],  // 73
                [0.5, bb.maxY + 0.14],  // 74 chin-bottom
                [0.75, bb.maxY + 0.12],  // 75
                [1, bb.maxY + 0.10],  // 76 bottom-right-jaw
                [0.5, 1.0],             // 77 body bottom-center
                [0, 1.0],             // 78 body bottom-left
            );

            const clampPts = basePts.map(([x, y]) => [
                Math.max(-0.1, Math.min(1.1, x)),
                Math.max(-0.1, Math.min(1.2, y)),
            ]);

            const tris = buildTriangles(clampPts);

            if (cancelled) return;
            meshRef.current = { pts: clampPts, basePts: clampPts.map(p => [...p]), tris, imgW, imgH, srcCanvas };
            loadedRef.current = true;
        };

        setup().catch(e => {
            console.error('[Avatar] Setup error:', e);
            setupFallbackMesh();
        });
        return () => { cancelled = true; };
    }, []);

    // ── Fallback: if face-api fails, create a simple grid mesh ─────────────────
    const setupFallbackMesh = useCallback((srcCanvas, imgW, imgH) => {
        const img = new Image();
        img.src = avatarImg;
        img.onload = () => {
            const sc = srcCanvas || document.createElement('canvas');
            if (!srcCanvas) {
                sc.width = img.naturalWidth; sc.height = img.naturalHeight;
                sc.getContext('2d').drawImage(img, 0, 0);
            }
            const W = imgW || sc.width, H = imgH || sc.height;
            // 5×7 grid mesh
            const pts = [];
            const cols = 6, rows = 8;
            for (let r = 0; r <= rows; r++) {
                for (let c = 0; c <= cols; c++) {
                    pts.push([c / cols, r / rows]);
                }
            }
            const tris = [];
            for (let r = 0; r < rows; r++) {
                for (let c = 0; c < cols; c++) {
                    const i = r * (cols + 1) + c;
                    tris.push([i, i + 1, i + cols + 1]);
                    tris.push([i + 1, i + cols + 2, i + cols + 1]);
                }
            }
            meshRef.current = { pts, basePts: pts.map(p => [...p]), tris, imgW: W, imgH: H, srcCanvas: sc };
            loadedRef.current = true;
        };
    }, []);

    // ── Main render loop ────────────────────────────────────────────────────────
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        let lastT = performance.now();

        const render = (now) => {
            const dtMs = Math.min(now - lastT, 50);
            lastT = now;
            timeRef.current += dtMs / 1000;
            const t = timeRef.current;

            const wrap = wrapRef.current;
            if (wrap) {
                const rect = wrap.getBoundingClientRect();
                if (canvas.width !== rect.width || canvas.height !== rect.height) {
                    canvas.width = rect.width;
                    canvas.height = rect.height;
                }
            }

            ctx.clearRect(0, 0, canvas.width, canvas.height);

            // Read audio amplitude
            const au = audioRef.current;
            if (au.analyser && stateRef.current.isSpeaking) {
                au.analyser.getByteFrequencyData(au.data);
                const sum = Array.from(au.data.slice(0, 8)).reduce((a, b) => a + b, 0);
                au.amp = sum / (8 * 255);
            } else {
                au.amp *= 0.9;
            }

            // ── Determine target morphs ─────────────────────────────────────────
            const { isListening, isSpeaking, isThinking, emotion } = stateRef.current;
            let stateKey = emotion in EMOTION_BLEND ? emotion : 'neutral';
            if (isListening && stateKey === 'neutral') stateKey = 'listening';
            if (isThinking && stateKey === 'neutral') stateKey = 'thinking';

            const targets = { ...(EMOTION_BLEND[stateKey] || {}) };
            // Audio-driven jaw
            if (isSpeaking) targets.jaw_open = Math.max(targets.jaw_open || 0, au.amp * 1.2);

            // Blink logic
            blinkTimer.current -= dtMs;
            if (blinkTimer.current <= 0) {
                blinkTimer.current = 2500 + Math.random() * 5000;
                // trigger a blink
                blinkAmt.current.set(1);
            }
            const blinkW = blinkAmt.current.update(0); // spring back to 0
            if (blinkW > 0.01) targets.blink = blinkW;

            // Idle sway (applies as a tiny head-tilt oscillation)
            const sway = Math.sin(t * 0.7) * 0.08;
            swayAmt.current.update(sway);
            const breathAmp = Math.sin(t * 1.2) * 0.03;
            breathAmt.current.update(breathAmp);

            // Update all morph springs
            const allKeys = new Set([
                ...Object.keys(targets),
                ...Object.keys(morphSprings.current),
            ]);
            const weights = {};
            for (const key of allKeys) {
                const sp = getSpring(key);
                weights[key] = sp.update(targets[key] || 0);
            }
            morphWeights.current = weights;

            // ── Warp and render the mesh ─────────────────────────────────────────
            // Still loading — show static image cleanly while face-api initialises
            if (!meshRef.current || !loadedRef.current) {
                // Draw a plain static image in the centre — no triangle gaps
                const tmpImg = new Image();
                tmpImg.src = avatarImg;
                if (tmpImg.complete) {
                    const cW2 = canvas.width, cH2 = canvas.height;
                    const ar2 = tmpImg.naturalWidth / tmpImg.naturalHeight;
                    const dH2 = cH2 * 0.92;
                    const dW2 = dH2 * ar2;
                    ctx.drawImage(tmpImg, (cW2 - dW2) / 2, cH2 * 0.04, dW2, dH2);
                }
                animRef.current = requestAnimationFrame(render);
                return;
            }

            const { pts: basePts, tris, imgW, imgH, srcCanvas } = meshRef.current;
            const cW = canvas.width, cH = canvas.height;

            // Calculate display rect: fit portrait in canvas
            const imgAR = imgW / imgH;
            let drawH = cH * 0.92;
            let drawW = drawH * imgAR;
            if (drawW > cW * 0.88) { drawW = cW * 0.88; drawH = drawW / imgAR; }
            const offsetX = (cW - drawW) / 2;
            const offsetY = cH * 0.04;

            // Global transforms for idle sway & breathing
            const globalTiltX = swayAmt.current.get() * 0.015;  // tiny horizontal sway
            const globalBreath = breathAmt.current.get();         // tiny scale

            // Compute warped landmark positions
            const warpedPts = basePts.map((bp, idx) => {
                let dx = 0, dy = 0;
                for (const [morphKey, weight] of Object.entries(weights)) {
                    if (Math.abs(weight) < 0.001) continue;
                    const morphDelta = MORPH_TARGETS[morphKey];
                    if (!morphDelta) continue;
                    const delta = morphDelta[idx];
                    if (delta) {
                        dx += delta[0] * weight;
                        dy += delta[1] * weight;
                    }
                }
                // Apply idle global sway
                dx += globalTiltX * (bp[1] - 0.5); // more tilt on lower face
                dy += globalBreath * (bp[1] - 0.5);

                // Convert normalized coords to canvas pixel coords
                return [
                    offsetX + (bp[0] + dx) * drawW,
                    offsetY + (bp[1] + dy) * drawH,
                ];
            });

            // Source points in image pixel coords
            const srcPts = basePts.map(([x, y]) => [x * imgW, y * imgH]);

            // Ambient glow behind avatar
            const glowG = ctx.createRadialGradient(cW / 2, cH * 0.5, 0, cW / 2, cH * 0.5, cW * 0.42);
            // Emotion color
            const emoColors = {
                joy: '#ff88cc', happy: '#ff88cc', sad: '#88aaff', angry: '#ff4444',
                fear: '#aaaaff', surprised: '#ffdd88', disgust: '#88cc88',
                confused: '#cc88ff', embarrassed: '#ff99aa', confident: '#ffcc44',
                interested: '#ff88cc', neutral: '#00d4ff', listening: '#00d4ff', thinking: '#cc88ff',
            };
            const eCol = emoColors[stateKey] || '#00d4ff';
            glowG.addColorStop(0, eCol + '18');
            glowG.addColorStop(1, 'transparent');
            ctx.fillStyle = glowG;
            ctx.fillRect(0, 0, cW, cH);

            // Draw each triangle
            for (const [i, j, k] of tris) {
                if (i >= warpedPts.length || j >= warpedPts.length || k >= warpedPts.length) continue;
                drawWarpedTriangle(
                    ctx, srcCanvas,
                    [srcPts[i], srcPts[j], srcPts[k]],
                    [warpedPts[i], warpedPts[j], warpedPts[k]]
                );
            }

            // Speaking pulse ring around avatar
            if (isSpeaking && au.amp > 0.05) {
                const ringR = Math.min(drawW, drawH) * 0.52;
                const pulse = au.amp;
                ctx.save();
                ctx.beginPath();
                ctx.arc(cW / 2, offsetY + drawH * 0.45, ringR + pulse * 30, 0, Math.PI * 2);
                ctx.strokeStyle = eCol + Math.round(40 + pulse * 100).toString(16).padStart(2, '0');
                ctx.lineWidth = 2 + pulse * 4;
                ctx.stroke();
                ctx.restore();
            }

            animRef.current = requestAnimationFrame(render);
        };

        animRef.current = requestAnimationFrame(render);
        return () => {
            if (animRef.current) cancelAnimationFrame(animRef.current);
        };
    }, [getSpring]);

    return (
        <div
            ref={wrapRef}
            className="anime-avatar-wrap"
            id="anime-avatar"
            onClick={initAudio}
        >
            <canvas ref={canvasRef} className="avatar-mesh-canvas" />

            {/* Small camera PiP */}
            {cameraOn && (
                <video
                    ref={videoRef}
                    autoPlay muted playsInline
                    className="avatar-camera-pip"
                />
            )}

            {/* Camera button */}
            <button className="avatar-camera-btn" onClick={toggleCamera} title="Camera context">
                {cameraOn ? '📷 ✕' : '📷'}
            </button>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function getBoundingBox(pts) {
    let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;
    for (const [x, y] of pts) {
        if (x < minX) minX = x; if (x > maxX) maxX = x;
        if (y < minY) minY = y; if (y > maxY) maxY = y;
    }
    return { minX, minY, maxX, maxY };
}
