/**
 * TestLoginButton.jsx
 *
 * Renders a "Beta Access" button on the auth screen.
 * Opens a minimal form where testers enter their ID + password.
 * On success: stores the JWT and tier in session store exactly like Google OAuth.
 *
 * Place this in: frontend/src/components/auth/TestLoginButton.jsx
 *
 * Add to AuthScreen in App.jsx:
 *   import { TestLoginButton } from "./components/auth/TestLoginButton";
 *   ...inside auth-card after GoogleAuthButton:
 *   <TestLoginButton onSuccess={({ token, tier, displayName }) => {
 *     setAccessToken(token);
 *     setUser({ id: "test_" + displayName, email: displayName + "@aura.test" });
 *     setTier(tier);
 *   }} />
 */

import { useState } from "react";

const BACKEND = import.meta.env.VITE_WS_BACKEND_URL
    ? import.meta.env.VITE_WS_BACKEND_URL.replace("ws://", "http://").replace("wss://", "https://").replace("/ws", "")
    : "http://localhost:8000";

export function TestLoginButton({ onSuccess }) {
    const [open, setOpen] = useState(false);
    const [username, setUsername] = useState("");
    const [password, setPassword] = useState("");
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");

    const handleSubmit = async () => {
        if (!username.trim() || !password.trim()) {
            setError("Enter both username and password.");
            return;
        }
        setLoading(true);
        setError("");

        try {
            const resp = await fetch(`${BACKEND}/auth/test-login`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username: username.trim(), password }),
            });

            const data = await resp.json();

            if (!resp.ok) {
                setError(data.detail ?? "Login failed.");
                setLoading(false);
                return;
            }

            onSuccess?.({
                token: data.access_token,
                tier: data.tier,
                displayName: data.display_name,
            });

            setOpen(false);
            setUsername("");
            setPassword("");

        } catch (err) {
            setError("Could not reach backend. Is it running?");
        } finally {
            setLoading(false);
        }
    };

    const handleKey = (e) => {
        if (e.key === "Enter") handleSubmit();
    };

    if (!open) {
        return (
            <button
                className="test-login-toggle hoverable"
                onClick={() => setOpen(true)}
                style={{
                    background: "rgba(12, 18, 35, 0.45)",
                    border: "1px solid rgba(100, 180, 255, 0.12)",
                    borderRadius: "12px",
                    color: "rgba(150, 180, 220, 0.6)",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.6rem",
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    padding: "10px 16px",
                    cursor: "pointer",
                    width: "100%",
                    transition: "all 300ms cubic-bezier(0.16, 1, 0.3, 1)",
                    backdropFilter: "blur(12px)",
                }}
                onMouseEnter={(e) => {
                    e.currentTarget.style.color = "rgba(180, 210, 255, 0.8)";
                    e.currentTarget.style.borderColor = "rgba(100, 180, 255, 0.25)";
                    e.currentTarget.style.background = "rgba(20, 30, 55, 0.55)";
                    e.currentTarget.style.boxShadow = "0 0 20px rgba(80, 160, 240, 0.1)";
                }}
                onMouseLeave={(e) => {
                    e.currentTarget.style.color = "rgba(150, 180, 220, 0.6)";
                    e.currentTarget.style.borderColor = "rgba(100, 180, 255, 0.12)";
                    e.currentTarget.style.background = "rgba(12, 18, 35, 0.45)";
                    e.currentTarget.style.boxShadow = "none";
                }}
            >
                ◈ Beta Access
            </button>
        );
    }

    return (
        <div style={{
            width: "100%",
            display: "flex",
            flexDirection: "column",
            gap: "10px",
        }}>
            {/* Header */}
            <div style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "4px",
            }}>
                <span style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.62rem",
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    color: "rgba(150, 180, 220, 0.5)",
                }}>
                    Beta Access
                </span>
                <button
                    onClick={() => { setOpen(false); setError(""); }}
                    style={{
                        background: "none",
                        border: "none",
                        color: "rgba(150, 180, 220, 0.35)",
                        cursor: "pointer",
                        fontSize: "0.8rem",
                        padding: "2px 6px",
                    }}
                >
                    ✕
                </button>
            </div>

            {/* Username */}
            <input
                type="text"
                placeholder="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                onKeyDown={handleKey}
                autoComplete="off"
                spellCheck={false}
                style={{
                    background: "rgba(12, 18, 35, 0.5)",
                    border: "1px solid rgba(100, 180, 255, 0.12)",
                    borderRadius: "12px",
                    color: "rgba(220, 235, 255, 0.9)",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.75rem",
                    letterSpacing: "0.04em",
                    padding: "12px 16px",
                    outline: "none",
                    width: "100%",
                    transition: "all 300ms cubic-bezier(0.16, 1, 0.3, 1)",
                    boxSizing: "border-box",
                    cursor: "text",
                    backdropFilter: "blur(12px)",
                }}
                onFocus={(e) => {
                    e.target.style.borderColor = "rgba(100, 180, 255, 0.35)";
                    e.target.style.boxShadow = "0 0 20px rgba(80, 160, 240, 0.12)";
                }}
                onBlur={(e) => {
                    e.target.style.borderColor = "rgba(100, 180, 255, 0.12)";
                    e.target.style.boxShadow = "none";
                }}
            />

            {/* Password */}
            <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={handleKey}
                style={{
                    background: "rgba(12, 18, 35, 0.5)",
                    border: "1px solid rgba(100, 180, 255, 0.12)",
                    borderRadius: "12px",
                    color: "rgba(220, 235, 255, 0.9)",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.75rem",
                    letterSpacing: "0.04em",
                    padding: "12px 16px",
                    outline: "none",
                    width: "100%",
                    transition: "all 300ms cubic-bezier(0.16, 1, 0.3, 1)",
                    boxSizing: "border-box",
                    cursor: "text",
                    backdropFilter: "blur(12px)",
                }}
                onFocus={(e) => {
                    e.target.style.borderColor = "rgba(100, 180, 255, 0.35)";
                    e.target.style.boxShadow = "0 0 20px rgba(80, 160, 240, 0.12)";
                }}
                onBlur={(e) => {
                    e.target.style.borderColor = "rgba(100, 180, 255, 0.12)";
                    e.target.style.boxShadow = "none";
                }}
            />

            {/* Error */}
            {error && (
                <p style={{
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.6rem",
                    color: "#ef4444",
                    letterSpacing: "0.04em",
                    margin: 0,
                }}>
                    {error}
                </p>
            )}

            {/* Submit */}
            <button
                onClick={handleSubmit}
                disabled={loading}
                className="hoverable"
                style={{
                    background: loading
                        ? "rgba(100, 160, 240, 0.06)"
                        : "linear-gradient(135deg, rgba(80, 140, 240, 0.15), rgba(60, 120, 220, 0.08))",
                    border: "1px solid rgba(100, 180, 255, 0.25)",
                    borderRadius: "12px",
                    color: loading ? "rgba(100, 180, 255, 0.4)" : "rgba(140, 200, 255, 0.9)",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.65rem",
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    padding: "12px 24px",
                    cursor: loading ? "not-allowed" : "pointer",
                    width: "100%",
                    transition: "all 300ms cubic-bezier(0.16, 1, 0.3, 1)",
                    backdropFilter: "blur(12px)",
                    boxShadow: loading ? "none" : "0 0 20px rgba(80, 160, 240, 0.08)",
                }}
            >
                {loading ? "Authenticating…" : "Enter →"}
            </button>
        </div>
    );
}