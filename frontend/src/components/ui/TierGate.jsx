/**
 * TierGate — Premium upgrade CTA with pricing modal.
 * Shows $99/month or $1100/year options.
 * Uses Razorpay Checkout for UPI, Cards, Net Banking, Wallets.
 *
 * Checkout flow:
 *   1. User picks plan → clicks CTA
 *   2. Frontend calls POST /payments/create-checkout-session
 *   3. Backend creates a Razorpay Subscription
 *   4. Frontend opens Razorpay Checkout modal (UPI/Card/NetBanking)
 *   5. Razorpay fires webhook → backend upgrades tier → WS sends tier_updated
 */

import { useState } from "react";
import { useSessionStore } from "../../store/useSessionStore";

export function TierGate() {
  const user = useSessionStore((s) => s.user);
  const accessToken = useSessionStore((s) => s.accessToken);
  const [showModal, setShowModal] = useState(false);
  const [selected, setSelected] = useState("annual"); // "monthly" | "annual"
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const handleUpgrade = async () => {
    setLoading(true);
    setError("");

    try {
      // Derive REST API base URL from the WS URL
      const wsUrl = import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws";
      const apiBase = wsUrl
        .replace(/^ws:/, "http:")
        .replace(/^wss:/, "https:")
        .replace(/\/ws$/, "");

      const res = await fetch(`${apiBase}/payments/create-checkout-session`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ plan: selected }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server error (${res.status})`);
      }

      const data = await res.json();

      // Load Razorpay Checkout script if not already loaded
      if (!window.Razorpay) {
        await new Promise((resolve, reject) => {
          const script = document.createElement("script");
          script.src = "https://checkout.razorpay.com/v1/checkout.js";
          script.onload = resolve;
          script.onerror = () => reject(new Error("Failed to load Razorpay"));
          document.head.appendChild(script);
        });
      }

      // Open Razorpay Checkout modal
      const options = {
        key: data.razorpay_key_id,
        subscription_id: data.subscription_id,
        name: data.name || "Alita Premium",
        description: data.description,
        handler: function () {
          // Payment success — webhook will handle tier upgrade
          window.location.search = "?payment=success";
        },
        modal: {
          ondismiss: function () {
            setLoading(false);
          },
        },
        theme: {
          color: "#a855f7",
        },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (err) {
      console.error("Checkout error:", err);
      setError(err.message || "Failed to start checkout. Please try again.");
      setLoading(false);
    }
  };

  return (
    <>
      {/* CTA Button */}
      <div className="tier-gate">
        <button
          className="tier-gate-btn hoverable"
          onClick={() => setShowModal(true)}
        >
          ✦ Unlock Premium
        </button>
      </div>

      {/* Pricing Modal */}
      {showModal && (
        <div className="pricing-overlay" onClick={() => setShowModal(false)}>
          <div
            className="pricing-modal"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="pricing-header">
              <div className="pricing-orb" />
              <h2 className="pricing-title">Alita Premium</h2>
              <p className="pricing-subtitle">
                Unlock the full emotional intelligence suite
              </p>
              <button
                className="pricing-close hoverable"
                onClick={() => setShowModal(false)}
              >
                ✕
              </button>
            </div>

            {/* Plan Toggle */}
            <div className="pricing-plans">

              {/* Monthly */}
              <div
                className={`pricing-card hoverable ${selected === "monthly" ? "selected" : ""}`}
                onClick={() => setSelected("monthly")}
              >
                <div className="pricing-card-header">
                  <span className="pricing-period">Monthly</span>
                  {selected === "monthly" && (
                    <span className="pricing-selected-dot">●</span>
                  )}
                </div>
                <div className="pricing-amount">
                  <span className="pricing-currency">$</span>
                  <span className="pricing-number">99</span>
                  <span className="pricing-per">/mo</span>
                </div>
                <p className="pricing-billed">Billed monthly</p>
              </div>

              {/* Annual */}
              <div
                className={`pricing-card hoverable ${selected === "annual" ? "selected" : ""}`}
                onClick={() => setSelected("annual")}
              >
                <div className="pricing-badge">BEST VALUE</div>
                <div className="pricing-card-header">
                  <span className="pricing-period">Annual</span>
                  {selected === "annual" && (
                    <span className="pricing-selected-dot">●</span>
                  )}
                </div>
                <div className="pricing-amount">
                  <span className="pricing-currency">$</span>
                  <span className="pricing-number">1100</span>
                  <span className="pricing-per">/yr</span>
                </div>
                <p className="pricing-billed">
                  $91.67/mo · Billed annually
                </p>
              </div>
            </div>

            {/* Feature List */}
            <ul className="pricing-features">
              <li><span className="feat-icon">◈</span> Alita Emotional Intelligence (7-Layer AI)</li>
              <li><span className="feat-icon">◈</span> XTTS v2 Natural Voice Cloning</li>
              <li><span className="feat-icon">◈</span> Multi-LLM Racing (Groq + NVIDIA + DeepSeek)</li>
              <li><span className="feat-icon">◈</span> Holographic Avatar Expressions</li>
              <li><span className="feat-icon">◈</span> Geospatial Intelligence Dashboard</li>
              <li><span className="feat-icon">◈</span> Song Recognition &amp; Music Control</li>
              <li><span className="feat-icon">◈</span> Persistent memory across sessions</li>
              <li><span className="feat-icon">◈</span> Zero-shot voice cloning</li>
              <li><span className="feat-icon">◈</span> Bluetooth HRV biometric sync</li>
              <li><span className="feat-icon">◈</span> + 13 more advanced features</li>
            </ul>

            {/* Error Message */}
            {error && (
              <p style={{
                color: "#ff6b6b",
                fontSize: "0.85rem",
                textAlign: "center",
                margin: "0 0 0.75rem 0",
              }}>
                {error}
              </p>
            )}

            {/* CTA */}
            <button
              className="pricing-cta hoverable"
              onClick={handleUpgrade}
              disabled={loading}
              style={{ opacity: loading ? 0.6 : 1 }}
            >
              {loading
                ? "Redirecting to Stripe…"
                : `Continue with ${selected === "monthly" ? "$99 / month" : "$1100 / year"}`
              }
              {!loading && <span className="pricing-cta-arrow">→</span>}
            </button>

            <p className="pricing-footer">
              Cancel anytime · Secure checkout via Razorpay
            </p>
          </div>
        </div>
      )}
    </>
  );
}