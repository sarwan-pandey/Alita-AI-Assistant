/**
 * TierGate — Premium upgrade CTA with pricing modal.
 * Shows $19/month or $209/year options.
 * Yearly saves $19 vs monthly ($228 - $209 = $19 savings).
 */

import { useState } from "react";
import { useSessionStore } from "../../store/useSessionStore";

export function TierGate() {
  const user = useSessionStore((s) => s.user);
  const [showModal, setShowModal] = useState(false);
  const [selected, setSelected] = useState("annual"); // "monthly" | "annual"

  const handleUpgrade = () => {
    const plan = selected === "monthly" ? "monthly" : "annual";
    const params = new URLSearchParams({
      client_reference_id: user?.id ?? "",
      plan,
    });
    // Replace with your actual Stripe Payment Links
    const stripeLinks = {
      monthly: "https://buy.stripe.com/YOUR_MONTHLY_LINK",
      annual: "https://buy.stripe.com/YOUR_ANNUAL_LINK",
    };
    window.open(`${stripeLinks[selected]}?${params}`, "_blank");
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
              <h2 className="pricing-title">Aura Premium</h2>
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
                  <span className="pricing-number">19</span>
                  <span className="pricing-per">/mo</span>
                </div>
                <p className="pricing-billed">Billed monthly</p>
              </div>

              {/* Annual */}
              <div
                className={`pricing-card hoverable ${selected === "annual" ? "selected" : ""}`}
                onClick={() => setSelected("annual")}
              >
                <div className="pricing-badge">SAVE $19</div>
                <div className="pricing-card-header">
                  <span className="pricing-period">Annual</span>
                  {selected === "annual" && (
                    <span className="pricing-selected-dot">●</span>
                  )}
                </div>
                <div className="pricing-amount">
                  <span className="pricing-currency">$</span>
                  <span className="pricing-number">209</span>
                  <span className="pricing-per">/yr</span>
                </div>
                <p className="pricing-billed">
                  $17.42/mo · Billed annually
                </p>
              </div>
            </div>

            {/* Feature List */}
            <ul className="pricing-features">
              <li><span className="feat-icon">◈</span> Geospatial Intelligence Dashboard</li>
              <li><span className="feat-icon">◈</span> 10,000+ GPU particle figure</li>
              <li><span className="feat-icon">◈</span> Persistent memory across sessions</li>
              <li><span className="feat-icon">◈</span> Domain LoRAs — Medical &amp; Fitness</li>
              <li><span className="feat-icon">◈</span> Zero-shot voice cloning</li>
              <li><span className="feat-icon">◈</span> Bluetooth HRV biometric sync</li>
            </ul>

            {/* CTA */}
            <button
              className="pricing-cta hoverable"
              onClick={handleUpgrade}
            >
              Continue with {selected === "monthly" ? "$19 / month" : "$209 / year"}
              <span className="pricing-cta-arrow">→</span>
            </button>

            <p className="pricing-footer">
              Cancel anytime · Secure checkout via Stripe
            </p>
          </div>
        </div>
      )}
    </>
  );
}