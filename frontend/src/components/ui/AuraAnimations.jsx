/**
 * AuraAnimations — Lottie-powered micro-animations.
 *
 * Provides reusable animated components:
 *   - ThinkingDots: pulsing dots while Alita is processing
 *   - WaveformAnimation: audio waveform visualization
 *   - SuccessCheck: celebration checkmark
 *
 * Uses simple CSS animations as Lottie JSON fallback (no external files needed).
 */

import { useEffect, useState } from "react";
import { motion, AnimatePresence } from "framer-motion";

// ── Thinking Dots — shown while Alita processes ────────────────────────────
export function ThinkingDots({ visible = false }) {
    if (!visible) return null;

    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            style={{
                display: "flex",
                gap: "6px",
                padding: "12px 20px",
                alignItems: "center",
            }}
        >
            {[0, 1, 2].map((i) => (
                <motion.div
                    key={i}
                    animate={{
                        scale: [1, 1.4, 1],
                        opacity: [0.4, 1, 0.4],
                    }}
                    transition={{
                        duration: 1.2,
                        repeat: Infinity,
                        delay: i * 0.2,
                        ease: "easeInOut",
                    }}
                    style={{
                        width: "6px",
                        height: "6px",
                        borderRadius: "50%",
                        background: "linear-gradient(135deg, #c084fc, #818cf8)",
                    }}
                />
            ))}
            <motion.span
                animate={{ opacity: [0.3, 0.7, 0.3] }}
                transition={{ duration: 2, repeat: Infinity }}
                style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.55rem",
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    color: "rgba(192,132,252,0.6)",
                    marginLeft: "8px",
                }}
            >
                thinking
            </motion.span>
        </motion.div>
    );
}

// ── Waveform — audio visualization ────────────────────────────────────────
export function WaveformAnimation({ active = false }) {
    if (!active) return null;

    return (
        <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            style={{
                display: "flex",
                gap: "3px",
                alignItems: "center",
                height: "24px",
            }}
        >
            {Array.from({ length: 5 }).map((_, i) => (
                <motion.div
                    key={i}
                    animate={{
                        scaleY: [0.3, 1, 0.3],
                    }}
                    transition={{
                        duration: 0.6 + i * 0.1,
                        repeat: Infinity,
                        ease: "easeInOut",
                        delay: i * 0.08,
                    }}
                    style={{
                        width: "3px",
                        height: "20px",
                        borderRadius: "2px",
                        background: `linear-gradient(to top, rgba(163,230,53,0.3), rgba(163,230,53,0.9))`,
                        transformOrigin: "center",
                    }}
                />
            ))}
        </motion.div>
    );
}

// ── Success Checkmark — celebration animation ─────────────────────────────
export function SuccessCheck({ show = false, onComplete }) {
    if (!show) return null;

    return (
        <motion.div
            initial={{ scale: 0, rotate: -180 }}
            animate={{ scale: 1, rotate: 0 }}
            exit={{ scale: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 200, damping: 12 }}
            onAnimationComplete={onComplete}
            style={{
                width: "40px",
                height: "40px",
                borderRadius: "50%",
                background: "linear-gradient(135deg, #34d399, #10b981)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                boxShadow: "0 0 20px rgba(52,211,153,0.4)",
            }}
        >
            <motion.svg
                initial={{ pathLength: 0 }}
                animate={{ pathLength: 1 }}
                transition={{ duration: 0.4, delay: 0.2 }}
                width="20"
                height="20"
                viewBox="0 0 20 20"
                fill="none"
                stroke="white"
                strokeWidth="2.5"
                strokeLinecap="round"
                strokeLinejoin="round"
            >
                <motion.path d="M4 10l4 4 8-8" />
            </motion.svg>
        </motion.div>
    );
}

// ── Pulse Ring — status indicator animation ───────────────────────────────
export function PulseRing({ color = "#c084fc", size = 12 }) {
    return (
        <div style={{ position: "relative", width: size, height: size }}>
            <motion.div
                animate={{
                    scale: [1, 2, 1],
                    opacity: [0.6, 0, 0.6],
                }}
                transition={{
                    duration: 2,
                    repeat: Infinity,
                    ease: "easeOut",
                }}
                style={{
                    position: "absolute",
                    inset: 0,
                    borderRadius: "50%",
                    border: `1px solid ${color}`,
                }}
            />
            <div
                style={{
                    width: "100%",
                    height: "100%",
                    borderRadius: "50%",
                    background: color,
                }}
            />
        </div>
    );
}

