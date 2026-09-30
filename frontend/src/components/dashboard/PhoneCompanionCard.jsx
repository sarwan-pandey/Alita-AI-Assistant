/**
 * PhoneCompanionCard — Alita Autonomous Mobile Companion HUD Card
 * =================================================================
 * Provides real-time smartphone telemetry, battery status, screen state,
 * incoming notification stream with zero-screen RemoteInput instant replies,
 * and 1-click autonomous mobile automation triggers.
 */

import React, { useState, useEffect, useCallback, memo } from "react";
import { soundFX } from "../../utils/SoundFX";

const API_BASE = "http://localhost:8000";

export const PhoneCompanionCard = memo(function PhoneCompanionCard({
  isOpen = true,
  onClose = null,
  onNotificationArrived = null,
}) {
  const [phoneStatus, setPhoneStatus] = useState({
    status: "offline",
    device: {
      deviceModel: "Android Companion",
      batteryPercent: -1,
      isCharging: false,
      isScreenOn: false,
      accessibilityActive: false,
      notificationListenerActive: false,
      currentPackage: "",
    },
    recentNotifications: [],
  });

  const [loading, setLoading] = useState(false);
  const [replyInput, setReplyInput] = useState({});
  const [customCommand, setCustomCommand] = useState("");
  const [feedback, setFeedback] = useState(null);

  // ── Fetch Status from Backend ──
  const fetchStatus = useCallback(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/phone/status`);
      if (res.ok) {
        const data = await res.json();
        setPhoneStatus(data);
      }
    } catch (_) {
      // Backend may be starting or offline
    }
  }, []);

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [fetchStatus]);

  // ── Action Handlers ──
  const handleExecuteTask = async (instruction) => {
    soundFX.playClick();
    setLoading(true);
    setFeedback(`Executing: "${instruction}"...`);
    try {
      const res = await fetch(`${API_BASE}/api/phone/execute-task`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ instruction }),
      });
      const data = await res.json();
      if (data.success) {
        setFeedback(`✓ Success: ${data.method || data.action || "Executed"}`);
      } else {
        setFeedback(`⚠️ ${data.error || "Execution failed"}`);
      }
    } catch (err) {
      setFeedback(`❌ Error: ${err.message}`);
    } finally {
      setLoading(false);
      setTimeout(() => setFeedback(null), 4000);
      fetchStatus();
    }
  };

  const handleQuickReply = async (notifKey, text) => {
    if (!text || !text.trim()) return;
    soundFX.playClick();
    setLoading(true);
    setFeedback("Sending Zero-Screen RemoteInput Reply...");
    try {
      const res = await fetch(`${API_BASE}/api/phone/reply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ notificationKey: notifKey, text }),
      });
      const data = await res.json();
      if (data.success) {
        setFeedback("✓ Zero-Screen message dispatched!");
        setReplyInput((prev) => ({ ...prev, [notifKey]: "" }));
      } else {
        setFeedback("⚠️ Failed to dispatch direct reply.");
      }
    } catch (err) {
      setFeedback(`❌ ${err.message}`);
    } finally {
      setLoading(false);
      setTimeout(() => setFeedback(null), 3000);
      fetchStatus();
    }
  };

  const isOnline = phoneStatus.status === "online" && phoneStatus.device?.connected;
  const dev = phoneStatus.device || {};

  return (
    <div className="phone-companion-card glass-card">
      {/* ── Header ── */}
      <div className="phone-card-header">
        <div className="phone-title-group">
          <span className="phone-icon">📱</span>
          <div>
            <h4 className="phone-title">MOBILE COMPANION</h4>
            <span className="phone-device-name">
              {dev.deviceModel || "Android Device"}
            </span>
          </div>
        </div>

        <div className="phone-badges">
          <span className={`phone-status-pill ${isOnline ? "online" : "offline"}`}>
            {isOnline ? "SYNCED" : "OFFLINE"}
          </span>
          {onClose && (
            <button className="phone-close-btn" onClick={onClose}>
              ✕
            </button>
          )}
        </div>
      </div>

      {/* ── Telemetry Row ── */}
      <div className="phone-vitals-row">
        {/* Battery Indicator */}
        <div className="vital-item">
          <span className="vital-label">BATTERY</span>
          <div className="vital-val-group">
            <span className={`vital-val ${dev.batteryPercent <= 20 ? "low" : "normal"}`}>
              {dev.batteryPercent >= 0 ? `${dev.batteryPercent}%` : "--"}
            </span>
            {dev.isCharging && <span className="charging-icon">⚡</span>}
          </div>
        </div>

        {/* Accessibility Status */}
        <div className="vital-item">
          <span className="vital-label">AUTOMATION</span>
          <span className={`vital-val ${dev.accessibilityActive ? "active" : "inactive"}`}>
            {dev.accessibilityActive ? "READY" : "INACTIVE"}
          </span>
        </div>

        {/* Screen Lock Status */}
        <div className="vital-item">
          <span className="vital-label">DISPLAY</span>
          <span className="vital-val">
            {dev.isScreenOn ? "AWAKE" : "LOCKED / SLEEP"}
          </span>
        </div>
      </div>

      {/* ── Quick Mobile Actions ── */}
      <div className="phone-action-chips">
        <button
          className="phone-chip"
          disabled={!isOnline || loading}
          onClick={() => handleExecuteTask("Unlock my phone")}
        >
          <span>🔓</span>
          <span>Unlock Screen</span>
        </button>

        <button
          className="phone-chip"
          disabled={!isOnline || loading}
          onClick={() => handleExecuteTask("Go to home screen")}
        >
          <span>🏠</span>
          <span>Home</span>
        </button>

        <button
          className="phone-chip"
          disabled={!isOnline || loading}
          onClick={() => handleExecuteTask("Pull down notifications")}
        >
          <span>🔔</span>
          <span>Notifications</span>
        </button>

        <button
          className="phone-chip"
          disabled={!isOnline || loading}
          onClick={() => handleExecuteTask("Open WhatsApp")}
        >
          <span>💬</span>
          <span>WhatsApp</span>
        </button>

        <button
          className="phone-chip"
          disabled={!isOnline || loading}
          onClick={() => handleExecuteTask("Open Instagram and like post")}
        >
          <span>❤️</span>
          <span>Insta Like</span>
        </button>
      </div>

      {/* ── Natural Instruction Input ── */}
      <div className="phone-input-row">
        <input
          type="text"
          className="phone-text-input"
          placeholder="e.g. Message Mom on WhatsApp that I will be late"
          value={customCommand}
          onChange={(e) => setCustomCommand(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && customCommand.trim()) {
              handleExecuteTask(customCommand.trim());
              setCustomCommand("");
            }
          }}
          disabled={!isOnline || loading}
        />
        <button
          className="phone-send-btn"
          disabled={!isOnline || loading || !customCommand.trim()}
          onClick={() => {
            handleExecuteTask(customCommand.trim());
            setCustomCommand("");
          }}
        >
          ⚡ Send
        </button>
      </div>

      {/* Feedback Banner */}
      {feedback && <div className="phone-feedback-banner">{feedback}</div>}

      {/* ── Incoming Notifications Stream ── */}
      <div className="phone-notifications-container">
        <div className="notif-header">
          <span>INTERCEPTED NOTIFICATIONS</span>
          <span className="notif-count">
            {phoneStatus.recentNotifications?.length || 0}
          </span>
        </div>

        {(!phoneStatus.recentNotifications || phoneStatus.recentNotifications.length === 0) ? (
          <div className="empty-notifs">No active notifications intercepted</div>
        ) : (
          <div className="notif-list">
            {phoneStatus.recentNotifications.slice(0, 4).map((n, i) => (
              <div key={n.key || i} className="notif-item">
                <div className="notif-top">
                  <span className="notif-sender">{n.title || "Unknown Sender"}</span>
                  <span className="notif-pkg">
                    {(n.package || "").replace("com.", "")}
                  </span>
                </div>
                <div className="notif-body">{n.text}</div>

                {n.canReply && (
                  <div className="notif-reply-box">
                    <input
                      type="text"
                      className="notif-reply-input"
                      placeholder="Quick reply..."
                      value={replyInput[n.key] || ""}
                      onChange={(e) =>
                        setReplyInput({ ...replyInput, [n.key]: e.target.value })
                      }
                      onKeyDown={(e) => {
                        if (e.key === "Enter") {
                          handleQuickReply(n.key, replyInput[n.key]);
                        }
                      }}
                    />
                    <button
                      className="notif-reply-btn"
                      disabled={loading || !replyInput[n.key]?.trim()}
                      onClick={() => handleQuickReply(n.key, replyInput[n.key])}
                    >
                      Reply
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
});
