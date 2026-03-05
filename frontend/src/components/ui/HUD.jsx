import { useEmotionStore } from "../../store/useEmotionStore";

const EMOTION_GLYPHS = {
  happy: "◈", sad: "◇", angry: "◆", fear: "◉",
  surprise: "◎", disgust: "◈", neutral: "○",
};

export function HUD({ wsStatus, isListening, isThinking, user, tier, onLogout }) {
  const emotion = useEmotionStore((s) => s.emotion);

  return (
    <div className="hud" role="complementary" aria-label="Status overlay">
      <div className="hud-top-left">
        <span className="hud-brand">Aura</span>
        <div className="hud-ws-status">
          <div className={`hud-ws-dot ${wsStatus}`} />
          <span>{wsStatus === "open" ? "connected" : wsStatus}</span>
        </div>
      </div>

      <div className="hud-top-right">
        <div className={`hud-tier-badge ${tier}`}>
          {tier === "premium" ? "✦ premium" : "free"}
        </div>
        {user?.email && (
          <span style={{
            fontSize: "0.6rem",
            color: "var(--text-dim)",
            letterSpacing: "0.05em",
          }}>
            {user.email.split("@")[0]}
          </span>
        )}
        {onLogout && (
          <button
            className="hud-logout hoverable"
            onClick={onLogout}
            style={{
              background: "none",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "2px",
              color: "rgba(255,255,255,0.35)",
              fontFamily: "'DM Mono', monospace",
              fontSize: "0.5rem",
              letterSpacing: "0.12em",
              textTransform: "uppercase",
              padding: "4px 10px",
              cursor: "none",
              transition: "color 200ms, border-color 200ms",
            }}
          >
            sign out
          </button>
        )}
      </div>

      <div className="hud-center">
        <div className={`hud-listening-ring ${isListening ? "active" : ""} ${isThinking ? "thinking" : ""}`}>
          <div className="hud-listening-dot" />
        </div>
        <div className="hud-emotion-display">
          <span style={{ fontSize: "1.2rem", opacity: 0.6 }}>
            {EMOTION_GLYPHS[emotion?.label] ?? "○"}
          </span>
          <span className="hud-emotion-label">{emotion?.label ?? "neutral"}</span>
        </div>
      </div>
    </div>
  );
}