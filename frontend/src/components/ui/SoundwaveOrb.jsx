/**
 * SoundwaveOrb — Modern soundwave animation with glowing orb.
 * Pure Canvas2D — no Three.js dependency.
 *
 * Features:
 *   - Glowing cyan orb with radial gradient
 *   - Animated soundwave bars that react to listening/thinking state
 *   - Particle field floating around the orb
 *   - Rotating arc accents
 *   - Smooth transitions between idle, listening, and thinking states
 */

import { useEffect, useRef, useCallback } from "react";

export function SoundwaveOrb({ isListening, isThinking, isSpeaking }) {
    const canvasRef = useRef(null);
    const animRef = useRef(null);
    const particlesRef = useRef([]);
    const timeRef = useRef(0);
    const stateRef = useRef({ isListening: false, isThinking: false, isSpeaking: false });

    // Keep state ref in sync (avoids effect re-runs)
    stateRef.current.isListening = isListening;
    stateRef.current.isThinking = isThinking;
    stateRef.current.isSpeaking = isSpeaking;

    const initParticles = useCallback((w, h) => {
        const pts = [];
        for (let i = 0; i < 80; i++) {
            pts.push({
                x: Math.random() * w,
                y: Math.random() * h,
                size: Math.random() * 2 + 0.5,
                vx: (Math.random() - 0.5) * 0.3,
                vy: (Math.random() - 0.5) * 0.3,
                opacity: Math.random() * 0.4 + 0.1,
                hue: Math.random() * 40 + 180,
            });
        }
        particlesRef.current = pts;
    }, []);

    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        const ctx = canvas.getContext("2d");
        let w = 0, h = 0, dpr = 1;

        const resize = () => {
            const rect = canvas.parentElement.getBoundingClientRect();
            dpr = window.devicePixelRatio || 1;
            w = rect.width;
            h = rect.height;
            canvas.width = w * dpr;
            canvas.height = h * dpr;
            canvas.style.width = w + "px";
            canvas.style.height = h + "px";
            // Reset transform before scaling to avoid accumulation
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            initParticles(w, h);
        };

        resize();
        window.addEventListener("resize", resize);

        const draw = () => {
            timeRef.current += 0.016;
            const t = timeRef.current;
            const { isListening: listening, isThinking: thinking, isSpeaking: speaking } = stateRef.current;

            // Reset transform each frame
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, w, h);

            const cx = w / 2;
            const cy = h * 0.42;
            const orbR = Math.min(w, h) * 0.22;

            // ── Particles ──
            particlesRef.current.forEach((p) => {
                p.x += p.vx;
                p.y += p.vy;
                if (p.x < 0) p.x = w;
                if (p.x > w) p.x = 0;
                if (p.y < 0) p.y = h;
                if (p.y > h) p.y = 0;

                const dx = p.x - cx;
                const dy = p.y - cy;
                const dist = Math.sqrt(dx * dx + dy * dy);
                const inf = Math.max(0, 1 - dist / (orbR * 3));

                ctx.beginPath();
                ctx.arc(p.x, p.y, p.size * (1 + inf * 0.5), 0, Math.PI * 2);
                ctx.fillStyle = `hsla(${p.hue}, 80%, 65%, ${p.opacity * (1 + inf * 2)})`;
                ctx.fill();
            });

            // ── Outer glow ──
            const glow = ctx.createRadialGradient(cx, cy, orbR * 0.5, cx, cy, orbR * 2);
            glow.addColorStop(0, "rgba(0, 180, 255, 0.08)");
            glow.addColorStop(0.5, "rgba(0, 150, 255, 0.03)");
            glow.addColorStop(1, "rgba(0, 120, 255, 0)");
            ctx.beginPath();
            ctx.arc(cx, cy, orbR * 2, 0, Math.PI * 2);
            ctx.fillStyle = glow;
            ctx.fill();

            // ── Orb ring ──
            const pulse = speaking ? Math.sin(t * 4) * 5 : listening ? Math.sin(t * 3) * 4 : thinking ? Math.sin(t * 5) * 2 : Math.sin(t * 1.5) * 1;
            const rR = orbR + pulse;

            // Outer ring glow
            ctx.beginPath();
            ctx.arc(cx, cy, rR + 6, 0, Math.PI * 2);
            ctx.strokeStyle = "rgba(0, 212, 255, 0.12)";
            ctx.lineWidth = 12;
            ctx.stroke();

            // Main ring
            ctx.beginPath();
            ctx.arc(cx, cy, rR, 0, Math.PI * 2);
            const rg = ctx.createLinearGradient(cx - rR, cy, cx + rR, cy);
            rg.addColorStop(0, "rgba(0, 200, 255, 0.7)");
            rg.addColorStop(0.5, "rgba(0, 150, 255, 0.5)");
            rg.addColorStop(1, "rgba(0, 200, 255, 0.7)");
            ctx.strokeStyle = rg;
            ctx.lineWidth = 2;
            ctx.stroke();

            // Inner ring
            ctx.beginPath();
            ctx.arc(cx, cy, rR - 3, 0, Math.PI * 2);
            ctx.strokeStyle = "rgba(0, 212, 255, 0.08)";
            ctx.lineWidth = 1;
            ctx.stroke();

            // ── Orb fill ──
            const fill = ctx.createRadialGradient(cx, cy - orbR * 0.3, 0, cx, cy, rR);
            fill.addColorStop(0, "rgba(15, 25, 50, 0.6)");
            fill.addColorStop(0.7, "rgba(8, 15, 35, 0.8)");
            fill.addColorStop(1, "rgba(5, 10, 25, 0.9)");
            ctx.beginPath();
            ctx.arc(cx, cy, rR - 2, 0, Math.PI * 2);
            ctx.fillStyle = fill;
            ctx.fill();

            // ── Flowing wave curves (replaces bars) ──
            let intensity = 0.15;
            if (speaking) intensity = 0.6;
            else if (listening) intensity = 0.75;
            else if (thinking) intensity = 0.45;

            // Clip waves inside the orb
            ctx.save();
            ctx.beginPath();
            ctx.arc(cx, cy, rR - 3, 0, Math.PI * 2);
            ctx.clip();

            // Draw 3 layered sine waves
            const waveConfigs = [
                { freq: 2.5, amp: 0.35, speed: 2.0, phase: 0, hue: 195, alpha: 0.7, width: 2.5 },
                { freq: 3.5, amp: 0.25, speed: 3.0, phase: 1.2, hue: 205, alpha: 0.5, width: 2.0 },
                { freq: 5.0, amp: 0.18, speed: 4.5, phase: 2.5, hue: 180, alpha: 0.35, width: 1.5 },
            ];

            for (const wave of waveConfigs) {
                ctx.beginPath();
                const waveStartX = cx - orbR * 0.9;
                const waveEndX = cx + orbR * 0.9;
                const steps = 120;
                const dx = (waveEndX - waveStartX) / steps;

                for (let s = 0; s <= steps; s++) {
                    const px = waveStartX + s * dx;
                    const normX = (px - cx) / orbR; // -1 to 1

                    // Envelope: fade at edges (circular clip shape)
                    const edgeDist = Math.max(0, 1 - normX * normX);
                    const envelope = Math.sqrt(edgeDist);

                    // Combined sine for organic motion
                    const baseY = Math.sin(normX * Math.PI * wave.freq + t * wave.speed + wave.phase) * wave.amp;
                    const detail = Math.sin(normX * Math.PI * 7 + t * 6 + wave.phase * 2) * 0.06;

                    // Extra motion when listening — faster jitter
                    let listeningBoost = 0;
                    if (listening) {
                        listeningBoost = Math.sin(t * 10 + normX * 9) * 0.12 * envelope;
                    }

                    const py = cy + (baseY + detail + listeningBoost) * orbR * intensity * envelope;

                    if (s === 0) ctx.moveTo(px, py);
                    else ctx.lineTo(px, py);
                }

                // Gradient stroke
                const grad = ctx.createLinearGradient(waveStartX, cy, waveEndX, cy);
                grad.addColorStop(0, `hsla(${wave.hue}, 80%, 65%, 0)`);
                grad.addColorStop(0.2, `hsla(${wave.hue}, 80%, 65%, ${wave.alpha * intensity * 2})`);
                grad.addColorStop(0.5, `hsla(${wave.hue}, 85%, 70%, ${wave.alpha * intensity * 2.5})`);
                grad.addColorStop(0.8, `hsla(${wave.hue}, 80%, 65%, ${wave.alpha * intensity * 2})`);
                grad.addColorStop(1, `hsla(${wave.hue}, 80%, 65%, 0)`);
                ctx.strokeStyle = grad;
                ctx.lineWidth = wave.width;
                ctx.stroke();

                // Mirror wave below center
                ctx.beginPath();
                for (let s = 0; s <= steps; s++) {
                    const px = waveStartX + s * dx;
                    const normX = (px - cx) / orbR;
                    const edgeDist = Math.max(0, 1 - normX * normX);
                    const envelope = Math.sqrt(edgeDist);
                    const baseY = Math.sin(normX * Math.PI * wave.freq + t * wave.speed + wave.phase) * wave.amp;
                    const detail = Math.sin(normX * Math.PI * 7 + t * 6 + wave.phase * 2) * 0.06;
                    let listeningBoost = 0;
                    if (listening) listeningBoost = Math.sin(t * 10 + normX * 9) * 0.12 * envelope;
                    const py = cy - (baseY + detail + listeningBoost) * orbR * intensity * envelope * 0.6;
                    if (s === 0) ctx.moveTo(px, py);
                    else ctx.lineTo(px, py);
                }
                const mirrorGrad = ctx.createLinearGradient(waveStartX, cy, waveEndX, cy);
                mirrorGrad.addColorStop(0, `hsla(${wave.hue + 15}, 70%, 50%, 0)`);
                mirrorGrad.addColorStop(0.3, `hsla(${wave.hue + 15}, 70%, 50%, ${wave.alpha * intensity * 0.8})`);
                mirrorGrad.addColorStop(0.7, `hsla(${wave.hue + 15}, 70%, 50%, ${wave.alpha * intensity * 0.8})`);
                mirrorGrad.addColorStop(1, `hsla(${wave.hue + 15}, 70%, 50%, 0)`);
                ctx.strokeStyle = mirrorGrad;
                ctx.lineWidth = wave.width * 0.7;
                ctx.stroke();
            }
            ctx.restore();

            // ── Center glow ──
            const dg = ctx.createRadialGradient(cx, cy, 0, cx, cy, 20);
            dg.addColorStop(0, "rgba(0, 212, 255, 0.15)");
            dg.addColorStop(1, "rgba(0, 212, 255, 0)");
            ctx.beginPath();
            ctx.arc(cx, cy, 20, 0, Math.PI * 2);
            ctx.fillStyle = dg;
            ctx.fill();

            // ── Speaking pulse ring ──
            if (speaking) {
                const sp = Math.sin(t * 3) * 0.5 + 0.5; // 0..1 pulse
                const spR = rR + 10 + sp * 8;
                ctx.beginPath();
                ctx.arc(cx, cy, spR, 0, Math.PI * 2);
                ctx.strokeStyle = `rgba(245, 166, 35, ${0.15 + sp * 0.2})`;
                ctx.lineWidth = 2 + sp * 2;
                ctx.stroke();

                // Secondary ring
                const sp2 = Math.sin(t * 2 + 1) * 0.5 + 0.5;
                ctx.beginPath();
                ctx.arc(cx, cy, rR + 22 + sp2 * 6, 0, Math.PI * 2);
                ctx.strokeStyle = `rgba(245, 166, 35, ${0.06 + sp2 * 0.08})`;
                ctx.lineWidth = 1;
                ctx.stroke();
            }

            // ── Rotating arcs ──
            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate(t * 0.3);
            ctx.beginPath();
            ctx.arc(0, 0, rR + 16, 0, Math.PI * 0.4);
            ctx.strokeStyle = "rgba(0, 212, 255, 0.15)";
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(0, 0, rR + 16, Math.PI, Math.PI * 1.3);
            ctx.strokeStyle = "rgba(0, 180, 255, 0.1)";
            ctx.lineWidth = 1.5;
            ctx.stroke();
            ctx.restore();

            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate(-t * 0.2);
            ctx.beginPath();
            ctx.arc(0, 0, rR + 24, Math.PI * 0.6, Math.PI * 0.9);
            ctx.strokeStyle = "rgba(100, 200, 255, 0.08)";
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.beginPath();
            ctx.arc(0, 0, rR + 24, Math.PI * 1.6, Math.PI * 1.9);
            ctx.strokeStyle = "rgba(100, 200, 255, 0.08)";
            ctx.lineWidth = 1;
            ctx.stroke();
            ctx.restore();

            animRef.current = requestAnimationFrame(draw);
        };

        animRef.current = requestAnimationFrame(draw);

        return () => {
            window.removeEventListener("resize", resize);
            if (animRef.current) cancelAnimationFrame(animRef.current);
        };
    }, [initParticles]);

    return (
        <div className="soundwave-orb-container" id="soundwave-orb">
            <canvas ref={canvasRef} className="soundwave-canvas" />
        </div>
    );
}
