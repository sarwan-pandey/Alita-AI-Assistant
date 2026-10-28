/**
 * VoiceCloner — Voice Cloning Status Modal
 * =========================================
 * Custom voice cloning is currently unavailable.
 * Chatterbox Multilingual NIM and local Chatterbox Turbo are active for synthesis.
 * This component provides an explicit unavailable state.
 */

import React from "react";

export function VoiceCloner({ isOpen, onClose }) {
    if (!isOpen) return null;

    return (
        <div
            className="vc-overlay"
            onClick={(e) => e.target === e.currentTarget && onClose?.()}
            style={{
                position: "fixed",
                inset: 0,
                background: "rgba(0, 0, 0, 0.75)",
                backdropFilter: "blur(8px)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                zIndex: 1000,
                padding: "20px",
            }}
        >
            <div
                className="vc-panel"
                style={{
                    maxWidth: "460px",
                    width: "100%",
                    background: "#0f172a",
                    border: "1px solid rgba(255, 255, 255, 0.15)",
                    borderRadius: "16px",
                    padding: "32px 24px",
                    textAlign: "center",
                    boxShadow: "0 25px 50px -12px rgba(0, 0, 0, 0.7)",
                }}
            >
                <div style={{ fontSize: "2.8rem", marginBottom: "14px" }}>🎙️</div>
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: "8px", marginBottom: "8px" }}>
                    <h3 style={{ margin: 0, color: "#f87171", fontSize: "1.15rem", fontWeight: 600 }}>
                        Custom Voice Cloning Unavailable
                    </h3>
                </div>
                <p style={{ fontSize: "0.85rem", color: "rgba(255, 255, 255, 0.7)", lineHeight: "1.55", margin: "0 0 24px 0" }}>
                    Custom voice cloning is currently disabled.
                    Preset voices powered by Chatterbox Multilingual NIM and local Chatterbox Turbo are active.
                    Zero-shot custom voice cloning will return when a compatible provider is integrated.
                </p>
                <button
                    onClick={onClose}
                    style={{
                        background: "rgba(255, 255, 255, 0.12)",
                        border: "1px solid rgba(255, 255, 255, 0.25)",
                        color: "#ffffff",
                        padding: "10px 24px",
                        borderRadius: "10px",
                        cursor: "pointer",
                        fontWeight: 600,
                        fontSize: "0.88rem",
                        transition: "all 0.2s ease",
                    }}
                >
                    Close
                </button>
            </div>
        </div>
    );
}
