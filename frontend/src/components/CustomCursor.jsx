/**
 * CustomCursor — Replaces the native OS cursor entirely.
 * Two-layer design:
 *   - Inner dot: follows mouse exactly, instant response
 *   - Outer ring: lags slightly behind for fluid trailing feel
 * Reacts to hoverable elements: ring expands on hover, collapses on click.
 * Emotion-aware: ring color matches current emotion from useEmotionStore.
 */

import { useEffect, useRef, useCallback } from "react";
import { useEmotionStore } from "../store/useEmotionStore";

const EMOTION_COLORS = {
    happy: "#a3e635",
    sad: "#60a5fa",
    angry: "#ef4444",
    fear: "#fb923c",
    surprise: "#f59e0b",
    disgust: "#84cc16",
    neutral: "#c084fc",
};

export function CustomCursor() {
    const dotRef = useRef(null);
    const ringRef = useRef(null);

    // Tracked position refs — avoid re-renders
    const mouse = useRef({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
    const ring = useRef({ x: window.innerWidth / 2, y: window.innerHeight / 2 });
    const rafRef = useRef(null);
    const hovering = useRef(false);
    const clicking = useRef(false);

    const emotion = useEmotionStore((s) => s.emotion);

    // Animate ring toward mouse with lerp
    const animate = useCallback(() => {
        const LERP = 0.12;
        ring.current.x += (mouse.current.x - ring.current.x) * LERP;
        ring.current.y += (mouse.current.y - ring.current.y) * LERP;

        if (dotRef.current) {
            dotRef.current.style.transform =
                `translate(${mouse.current.x}px, ${mouse.current.y}px) translate(-50%, -50%)`;
        }

        if (ringRef.current) {
            ringRef.current.style.transform =
                `translate(${ring.current.x}px, ${ring.current.y}px) translate(-50%, -50%)`;
        }

        rafRef.current = requestAnimationFrame(animate);
    }, []);

    useEffect(() => {
        // Hide native cursor on entire document
        document.documentElement.style.cursor = "none";

        const onMove = (e) => {
            mouse.current.x = e.clientX;
            mouse.current.y = e.clientY;
        };

        const onEnter = (e) => {
            const target = e.target;
            const isHoverable = (
                target.tagName === "BUTTON" ||
                target.tagName === "A" ||
                target.tagName === "INPUT" ||
                target.closest("button") ||
                target.closest("a") ||
                target.classList.contains("hoverable")
            );
            if (isHoverable) {
                hovering.current = true;
                if (ringRef.current) {
                    ringRef.current.style.width = "44px";
                    ringRef.current.style.height = "44px";
                    ringRef.current.style.opacity = "0.6";
                }
                if (dotRef.current) {
                    dotRef.current.style.opacity = "0";
                }
            }
        };

        const onLeave = (e) => {
            hovering.current = false;
            if (ringRef.current) {
                ringRef.current.style.width = "28px";
                ringRef.current.style.height = "28px";
                ringRef.current.style.opacity = "1";
            }
            if (dotRef.current) {
                dotRef.current.style.opacity = "1";
            }
        };

        const onDown = () => {
            clicking.current = true;
            if (ringRef.current) {
                ringRef.current.style.width = "18px";
                ringRef.current.style.height = "18px";
            }
            if (dotRef.current) {
                dotRef.current.style.transform += " scale(1.5)";
            }
        };

        const onUp = () => {
            clicking.current = false;
            if (ringRef.current) {
                ringRef.current.style.width = hovering.current ? "44px" : "28px";
                ringRef.current.style.height = hovering.current ? "44px" : "28px";
            }
        };

        window.addEventListener("mousemove", onMove, { passive: true });
        window.addEventListener("mouseover", onEnter, { passive: true });
        window.addEventListener("mouseout", onLeave, { passive: true });
        window.addEventListener("mousedown", onDown, { passive: true });
        window.addEventListener("mouseup", onUp, { passive: true });

        rafRef.current = requestAnimationFrame(animate);

        return () => {
            document.documentElement.style.cursor = "";
            window.removeEventListener("mousemove", onMove);
            window.removeEventListener("mouseover", onEnter);
            window.removeEventListener("mouseout", onLeave);
            window.removeEventListener("mousedown", onDown);
            window.removeEventListener("mouseup", onUp);
            if (rafRef.current) cancelAnimationFrame(rafRef.current);
        };
    }, [animate]);

    // Update ring color when emotion changes
    useEffect(() => {
        const color = EMOTION_COLORS[emotion?.label] ?? EMOTION_COLORS.neutral;
        if (ringRef.current) {
            ringRef.current.style.borderColor = color;
            ringRef.current.style.boxShadow = `0 0 8px ${color}40`;
        }
        if (dotRef.current) {
            dotRef.current.style.background = color;
        }
    }, [emotion]);

    return (
        <>
            {/* Outer ring — lags behind mouse */}
            <div
                ref={ringRef}
                style={{
                    position: "fixed",
                    top: 0,
                    left: 0,
                    width: "28px",
                    height: "28px",
                    borderRadius: "50%",
                    border: "1px solid #c084fc",
                    boxShadow: "0 0 8px #c084fc40",
                    pointerEvents: "none",
                    zIndex: 99999,
                    transition: "width 200ms ease, height 200ms ease, opacity 200ms ease, border-color 600ms ease, box-shadow 600ms ease",
                    willChange: "transform",
                    mixBlendMode: "screen",
                }}
            />

            {/* Inner dot — exact mouse position */}
            <div
                ref={dotRef}
                style={{
                    position: "fixed",
                    top: 0,
                    left: 0,
                    width: "5px",
                    height: "5px",
                    borderRadius: "50%",
                    background: "#c084fc",
                    pointerEvents: "none",
                    zIndex: 100000,
                    transition: "opacity 150ms ease, background 600ms ease",
                    willChange: "transform",
                }}
            />
        </>
    );
}