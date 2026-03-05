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
                    background: "none",
                    border: "1px solid rgba(255,255,255,0.08)",
                    borderRadius: "2px",
                    color: "rgba(255,255,255,0.3)",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.6rem",
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    padding: "8px 16px",
                    cursor: "none",
                    width: "100%",
                    transition: "color 200ms, border-color 200ms",
                }}
                onMouseEnter={(e) => {
                    e.currentTarget.style.color = "rgba(255,255,255,0.55)";
                    e.currentTarget.style.borderColor = "rgba(255,255,255,0.2)";
                }}
                onMouseLeave={(e) => {
                    e.currentTarget.style.color = "rgba(255,255,255,0.3)";
                    e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
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
                    color: "rgba(255,255,255,0.4)",
                }}>
                    Beta Access
                </span>
                <button
                    onClick={() => { setOpen(false); setError(""); }}
                    style={{
                        background: "none",
                        border: "none",
                        color: "rgba(255,255,255,0.25)",
                        cursor: "none",
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
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "2px",
                    color: "rgba(255,255,255,0.85)",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.75rem",
                    letterSpacing: "0.04em",
                    padding: "10px 14px",
                    outline: "none",
                    width: "100%",
                    transition: "border-color 200ms",
                    boxSizing: "border-box",
                    cursor: "text",
                }}
                onFocus={(e) => e.target.style.borderColor = "rgba(192,132,252,0.5)"}
                onBlur={(e) => e.target.style.borderColor = "rgba(255,255,255,0.1)"}
            />

            {/* Password */}
            <input
                type="password"
                placeholder="Password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                onKeyDown={handleKey}
                style={{
                    background: "rgba(255,255,255,0.03)",
                    border: "1px solid rgba(255,255,255,0.1)",
                    borderRadius: "2px",
                    color: "rgba(255,255,255,0.85)",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.75rem",
                    letterSpacing: "0.04em",
                    padding: "10px 14px",
                    outline: "none",
                    width: "100%",
                    transition: "border-color 200ms",
                    boxSizing: "border-box",
                    cursor: "text",
                }}
                onFocus={(e) => e.target.style.borderColor = "rgba(192,132,252,0.5)"}
                onBlur={(e) => e.target.style.borderColor = "rgba(255,255,255,0.1)"}
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
                    background: loading ? "rgba(192,132,252,0.05)" : "rgba(192,132,252,0.1)",
                    border: "1px solid rgba(192,132,252,0.35)",
                    borderRadius: "2px",
                    color: loading ? "rgba(192,132,252,0.4)" : "#c084fc",
                    fontFamily: "'DM Mono', monospace",
                    fontSize: "0.65rem",
                    letterSpacing: "0.15em",
                    textTransform: "uppercase",
                    padding: "11px 24px",
                    cursor: loading ? "not-allowed" : "none",
                    width: "100%",
                    transition: "all 200ms",
                }}
            >
                {loading ? "Authenticating…" : "Enter →"}
            </button>
        </div>
    );
}