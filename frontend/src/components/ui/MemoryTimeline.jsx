/**
 * MemoryTimeline — Interactive SVG/CSS Timeline Visualization
 *
 * Displays conversation history as a flowing timeline with:
 * - Color-coded entries (user = blue, assistant = purple, system = amber)
 * - Emotion indicators on each entry
 * - Time grouping by day
 * - Smooth animations
 */

import { useState } from "react";

const ROLE_COLORS = {
  user:      { bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.35)", dot: "#3b82f6" },
  assistant: { bg: "rgba(168,85,247,0.12)", border: "rgba(168,85,247,0.35)", dot: "#a855f7" },
  system:    { bg: "rgba(245,158,11,0.12)", border: "rgba(245,158,11,0.35)", dot: "#f59e0b" },
};

const EMOTION_EMOJI = {
  neutral: "😐", happy: "😊", sad: "😢", angry: "😠",
  stressed: "😰", curious: "🤔", engaged: "🎯",
  relaxed: "😌", confident: "💪", tired: "😴",
};

function formatTime(ts) {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export function MemoryTimeline({ timeline = [], onClose }) {
  const [filter, setFilter] = useState("all"); // all | user | assistant | system

  const filtered = filter === "all"
    ? timeline
    : timeline.filter((e) => e.role === filter);

  // Group by date
  const grouped = {};
  for (const entry of filtered) {
    const date = new Date(entry.timestamp).toLocaleDateString(undefined, {
      weekday: "short", month: "short", day: "numeric",
    });
    if (!grouped[date]) grouped[date] = [];
    grouped[date].push(entry);
  }

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 300,
      background: "rgba(5,5,15,0.92)",
      backdropFilter: "blur(20px)",
      display: "flex", flexDirection: "column",
      fontFamily: "'Inter', sans-serif",
      animation: "fadeIn 300ms ease",
    }}>
      {/* Header */}
      <div style={{
        padding: "20px 28px",
        borderBottom: "1px solid rgba(255,255,255,0.06)",
        display: "flex", alignItems: "center", justifyContent: "space-between",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          <span style={{ fontSize: "1.2rem" }}>🧠</span>
          <h2 style={{
            margin: 0, fontSize: "0.85rem", fontWeight: 600,
            letterSpacing: "0.12em", textTransform: "uppercase",
            color: "rgba(255,255,255,0.9)",
          }}>
            Memory Timeline
          </h2>
          <span style={{
            fontSize: "0.6rem", color: "rgba(255,255,255,0.35)",
            background: "rgba(255,255,255,0.05)", padding: "2px 8px",
            borderRadius: "4px",
          }}>
            {timeline.length} entries
          </span>
        </div>

        <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
          {["all", "user", "assistant", "system"].map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              style={{
                padding: "4px 10px", fontSize: "0.6rem",
                borderRadius: "4px", cursor: "pointer",
                letterSpacing: "0.1em", textTransform: "uppercase",
                fontFamily: "'Inter', sans-serif", fontWeight: 500,
                border: filter === f ? "1px solid rgba(168,85,247,0.5)" : "1px solid rgba(255,255,255,0.1)",
                background: filter === f ? "rgba(168,85,247,0.15)" : "rgba(255,255,255,0.03)",
                color: filter === f ? "rgba(168,85,247,0.9)" : "rgba(255,255,255,0.5)",
                transition: "all 200ms",
              }}
            >
              {f}
            </button>
          ))}

          <button
            onClick={onClose}
            style={{
              marginLeft: "12px", padding: "4px 12px",
              background: "rgba(255,255,255,0.05)",
              border: "1px solid rgba(255,255,255,0.1)",
              borderRadius: "4px", color: "rgba(255,255,255,0.5)",
              cursor: "pointer", fontSize: "0.75rem",
            }}
          >
            ✕
          </button>
        </div>
      </div>

      {/* Timeline content */}
      <div style={{
        flex: 1, overflowY: "auto", padding: "20px 28px",
      }}>
        {Object.entries(grouped).length === 0 ? (
          <div style={{
            textAlign: "center", color: "rgba(255,255,255,0.3)",
            padding: "60px 0", fontSize: "0.75rem",
          }}>
            No memories yet. Start a conversation!
          </div>
        ) : (
          Object.entries(grouped).map(([date, entries]) => (
            <div key={date} style={{ marginBottom: "24px" }}>
              {/* Date header */}
              <div style={{
                fontSize: "0.6rem", fontWeight: 600,
                letterSpacing: "0.15em", textTransform: "uppercase",
                color: "rgba(255,255,255,0.3)", marginBottom: "12px",
                paddingLeft: "24px",
              }}>
                {date}
              </div>

              {/* Entries */}
              <div style={{ position: "relative", paddingLeft: "24px" }}>
                {/* Vertical line */}
                <div style={{
                  position: "absolute", left: "7px", top: "4px", bottom: "4px",
                  width: "1px", background: "rgba(255,255,255,0.08)",
                }} />

                {entries.map((entry, i) => {
                  const colors = ROLE_COLORS[entry.role] || ROLE_COLORS.system;
                  return (
                    <div
                      key={`${entry.id || entry.timestamp}-${i}`}
                      style={{
                        position: "relative", marginBottom: "8px",
                        padding: "8px 14px",
                        background: colors.bg,
                        border: `1px solid ${colors.border}`,
                        borderRadius: "8px",
                        animation: `slideIn ${200 + i * 30}ms ease`,
                      }}
                    >
                      {/* Dot on timeline */}
                      <div style={{
                        position: "absolute", left: "-21px", top: "12px",
                        width: "8px", height: "8px", borderRadius: "50%",
                        background: colors.dot, boxShadow: `0 0 8px ${colors.dot}40`,
                      }} />

                      <div style={{
                        display: "flex", justifyContent: "space-between",
                        alignItems: "center", marginBottom: "2px",
                      }}>
                        <span style={{
                          fontSize: "0.55rem", fontWeight: 600,
                          letterSpacing: "0.15em", textTransform: "uppercase",
                          color: colors.dot,
                        }}>
                          {entry.role}
                          {entry.emotion && (
                            <span style={{ marginLeft: "6px", fontSize: "0.7rem" }}>
                              {EMOTION_EMOJI[entry.emotion] || ""}
                            </span>
                          )}
                        </span>
                        <span style={{
                          fontSize: "0.5rem", color: "rgba(255,255,255,0.25)",
                        }}>
                          {formatTime(entry.timestamp)}
                        </span>
                      </div>

                      <p style={{
                        margin: 0, fontSize: "0.7rem", lineHeight: 1.5,
                        color: "rgba(255,255,255,0.75)",
                        wordBreak: "break-word",
                      }}>
                        {entry.text}
                      </p>
                    </div>
                  );
                })}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Inline keyframes */}
      <style>{`
        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }
        @keyframes slideIn {
          from { opacity: 0; transform: translateX(-8px); }
          to { opacity: 1; transform: translateX(0); }
        }
      `}</style>
    </div>
  );
}
