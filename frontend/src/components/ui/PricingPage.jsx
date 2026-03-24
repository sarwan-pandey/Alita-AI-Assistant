/**
 * PricingPage — 3-Tier Pricing Comparison
 *
 * Three cards side-by-side:
 *   1. Free (limited features)
 *   2. Monthly ($99/mo — all features)
 *   3. Yearly ($1100/yr — all features, save 8%)
 *
 * Both paid tiers unlock the exact same full feature set.
 */

import { useState, useEffect } from "react";
import {
  useSubscriptionStore,
  PREMIUM_FEATURES,
  FREE_FEATURES,
  FEATURE_INFO,
} from "../../store/useSubscriptionStore";
import { useSessionStore } from "../../store/useSessionStore";

const MONTHLY_PRICE = 99;
const YEARLY_PRICE = 1100;
const YEARLY_MONTHLY_EQUIV = (YEARLY_PRICE / 12).toFixed(0); // ~$92

export function PricingPage({ onClose }) {
  const {
    tier,
    isPremium,
    isTrialActive,
    trialDaysRemaining,
    purchase,
    purchaseDate,
  } = useSubscriptionStore();

  const [loading, setLoading] = useState("");
  const [error, setError] = useState("");
  const accessToken = useSessionStore((s) => s.accessToken);

  // Check for payment success from URL params
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (params.get("payment") === "success") {
      purchase();
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, [purchase]);

  const handlePurchase = async (plan) => {
    setLoading(plan);
    setError("");

    try {
      const wsUrl = import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws";
      const apiBase = wsUrl
        .replace(/^ws:/, "http:")
        .replace(/^wss:/, "https:")
        .replace(/\/ws$/, "");

      const res = await fetch(`${apiBase}/payments/create-checkout-session`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ plan }),
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

      const options = {
        key: data.razorpay_key_id,
        subscription_id: data.subscription_id,
        name: data.name || "Alita Premium",
        description: data.description,
        handler: function () {
          purchase();
          window.history.replaceState({}, "", window.location.pathname);
        },
        modal: {
          ondismiss: function () {
            setLoading("");
          },
        },
        theme: { color: "#a855f7" },
      };

      const rzp = new window.Razorpay(options);
      rzp.open();
    } catch (err) {
      console.error("Checkout error:", err);
      setError(err.message || "Failed to start checkout. Please try again.");
      setLoading("");
    }
  };

  // ── Render helpers ──────────────────────────────────────────────────────
  const FeatureRow = ({ icon, name, included }) => (
    <li style={S.featureItem}>
      <span style={included ? S.checkGreen : S.checkGray}>
        {included ? "✓" : "—"}
      </span>
      <span style={included ? {} : { opacity: 0.4 }}>
        {icon} {name}
      </span>
    </li>
  );

  const allFeatures = [...FREE_FEATURES, ...PREMIUM_FEATURES];

  return (
    <div style={S.overlay}>
      <div style={S.container}>
        {/* Close */}
        <button onClick={onClose} style={S.closeBtn}>✕</button>

        {/* Header */}
        <div style={S.header}>
          <h1 style={S.title}>
            Choose Your <span style={S.brand}>Alita</span> Plan
          </h1>
          <p style={S.subtitle}>
            {isTrialActive
              ? `🎉 Premium trial active — ${trialDaysRemaining} day${trialDaysRemaining !== 1 ? "s" : ""} remaining`
              : isPremium && purchaseDate
              ? "👑 You're on Premium — all features unlocked"
              : "Unlock every feature with Monthly or Yearly"}
          </p>
        </div>

        {/* ── Three pricing cards ────────────────────────────────────── */}
        <div style={S.cardsRow}>

          {/* ▸ FREE CARD */}
          <div style={S.card}>
            <div style={S.cardInner}>
              <div style={S.cardHead}>
                <div style={S.tierLabel}>Free</div>
                <div style={S.priceRow}>
                  <span style={S.priceBig}>$0</span>
                </div>
                <div style={S.priceNote}>Forever free</div>
              </div>

              <ul style={S.featureList}>
                {allFeatures.map((key) => {
                  const info = FEATURE_INFO[key];
                  if (!info) return null;
                  const isFree = FREE_FEATURES.includes(key);
                  return (
                    <FeatureRow
                      key={key}
                      icon={info.icon}
                      name={info.name}
                      included={isFree}
                    />
                  );
                })}
              </ul>

              {tier === "free" && !isTrialActive ? (
                <div style={S.currentBadge}>Current Plan</div>
              ) : (
                <div style={{ height: 48 }} />
              )}
            </div>
          </div>

          {/* ▸ MONTHLY CARD */}
          <div style={{ ...S.card, ...S.cardHighlight }}>
            <div style={S.cardInner}>
              <div style={S.cardHead}>
                <div style={{ ...S.tierLabel, color: "#a855f7" }}>Monthly</div>
                <div style={S.priceRow}>
                  <span style={{ ...S.priceBig, color: "#a855f7" }}>${MONTHLY_PRICE}</span>
                  <span style={S.pricePer}>/mo</span>
                </div>
                <div style={S.priceNote}>Billed monthly · Cancel anytime</div>
              </div>

              <ul style={S.featureList}>
                {allFeatures.map((key) => {
                  const info = FEATURE_INFO[key];
                  if (!info) return null;
                  return (
                    <FeatureRow
                      key={key}
                      icon={info.icon}
                      name={info.name}
                      included={true}
                    />
                  );
                })}
              </ul>

              {isPremium && purchaseDate ? (
                <div style={S.activeBadge}>👑 Active</div>
              ) : (
                <>
                  {error && loading === "monthly" && (
                    <p style={S.errorText}>{error}</p>
                  )}
                  <button
                    onClick={() => handlePurchase("monthly")}
                    disabled={!!loading}
                    style={{
                      ...S.purchaseBtn,
                      opacity: loading ? 0.6 : 1,
                    }}
                  >
                    {loading === "monthly"
                      ? "Opening checkout…"
                      : `Get Monthly — $${MONTHLY_PRICE}/mo`}
                  </button>
                </>
              )}
            </div>
          </div>

          {/* ▸ YEARLY CARD — Best Value */}
          <div style={{ ...S.card, ...S.cardBestValue }}>
            <div style={S.bestBadge}>🔥 Best Value — Save 8%</div>
            <div style={S.cardInner}>
              <div style={S.cardHead}>
                <div style={{ ...S.tierLabel, color: "#f59e0b" }}>Yearly</div>
                <div style={S.priceRow}>
                  <span style={{ ...S.priceBig, color: "#f59e0b" }}>${YEARLY_MONTHLY_EQUIV}</span>
                  <span style={S.pricePer}>/mo</span>
                </div>
                <div style={S.priceNote}>
                  ${YEARLY_PRICE}/year · Billed annually
                </div>
              </div>

              <ul style={S.featureList}>
                {allFeatures.map((key) => {
                  const info = FEATURE_INFO[key];
                  if (!info) return null;
                  return (
                    <FeatureRow
                      key={key}
                      icon={info.icon}
                      name={info.name}
                      included={true}
                    />
                  );
                })}
              </ul>

              {isPremium && purchaseDate ? (
                <div style={S.activeBadge}>👑 Active</div>
              ) : (
                <>
                  {error && loading === "annual" && (
                    <p style={S.errorText}>{error}</p>
                  )}
                  <button
                    onClick={() => handlePurchase("annual")}
                    disabled={!!loading}
                    style={{
                      ...S.purchaseBtnGold,
                      opacity: loading ? 0.6 : 1,
                    }}
                  >
                    {loading === "annual"
                      ? "Opening checkout…"
                      : `Get Yearly — $${YEARLY_PRICE}/yr`}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>

        {/* ── Feature comparison table ──────────────────────────────── */}
        <div style={S.compSection}>
          <h3 style={S.compTitle}>Full Feature Comparison</h3>
          <div style={S.tableWrap}>
            <table style={S.table}>
              <thead>
                <tr>
                  <th style={S.th}>Feature</th>
                  <th style={{ ...S.th, ...S.thCenter }}>Free</th>
                  <th style={{ ...S.th, ...S.thCenter, color: "#a855f7" }}>Monthly</th>
                  <th style={{ ...S.th, ...S.thCenter, color: "#f59e0b" }}>Yearly</th>
                </tr>
              </thead>
              <tbody>
                {allFeatures.map((key) => {
                  const info = FEATURE_INFO[key];
                  if (!info) return null;
                  const isFree = FREE_FEATURES.includes(key);
                  return (
                    <tr key={key} style={S.tr}>
                      <td style={S.td}>{info.icon} {info.name}</td>
                      <td style={S.tdCenter}>{isFree ? "✅" : "❌"}</td>
                      <td style={S.tdCenter}>✅</td>
                      <td style={S.tdCenter}>✅</td>
                    </tr>
                  );
                })}
                <tr style={S.tr}>
                  <td style={S.td}>⏱️ Unlimited Usage</td>
                  <td style={S.tdCenter}>✅</td>
                  <td style={S.tdCenter}>✅</td>
                  <td style={S.tdCenter}>✅</td>
                </tr>
                <tr style={S.tr}>
                  <td style={S.td}>💰 Price</td>
                  <td style={S.tdCenter}>$0</td>
                  <td style={S.tdCenter}>${MONTHLY_PRICE}/mo</td>
                  <td style={S.tdCenter}>${YEARLY_PRICE}/yr</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        <p style={S.footer}>
          Secure checkout powered by Razorpay · Cancel anytime · No hidden fees
        </p>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// STYLES
// ─────────────────────────────────────────────────────────────────────────────
const font = "'Inter', -apple-system, sans-serif";

const S = {
  overlay: {
    position: "fixed",
    inset: 0,
    zIndex: 9999,
    background: "rgba(0,0,0,0.88)",
    backdropFilter: "blur(24px)",
    display: "flex",
    justifyContent: "center",
    alignItems: "flex-start",
    overflowY: "auto",
    padding: "32px 16px",
  },
  container: {
    maxWidth: "1100px",
    width: "100%",
    position: "relative",
  },
  closeBtn: {
    position: "absolute",
    top: "-4px",
    right: "0",
    background: "none",
    border: "none",
    color: "rgba(255,255,255,0.4)",
    fontSize: "1.4rem",
    cursor: "pointer",
    zIndex: 10,
    padding: "8px",
    transition: "color 0.2s",
  },

  // Header
  header: {
    textAlign: "center",
    marginBottom: "36px",
  },
  title: {
    fontSize: "2.2rem",
    fontWeight: 800,
    color: "rgba(255,255,255,0.95)",
    fontFamily: font,
    margin: 0,
    lineHeight: 1.2,
    letterSpacing: "-0.02em",
  },
  brand: {
    background: "linear-gradient(135deg, #a855f7, #6366f1, #0ea5e9)",
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
  },
  subtitle: {
    fontSize: "1rem",
    color: "rgba(255,255,255,0.5)",
    fontFamily: font,
    marginTop: "10px",
  },

  // Cards row
  cardsRow: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: "16px",
    marginBottom: "48px",
  },
  card: {
    background: "rgba(255,255,255,0.025)",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: "20px",
    padding: "2px",
    position: "relative",
    transition: "transform 0.3s, box-shadow 0.3s",
  },
  cardHighlight: {
    background: "linear-gradient(135deg, rgba(168,85,247,0.1), rgba(99,102,241,0.06))",
    border: "1px solid rgba(168,85,247,0.25)",
    boxShadow: "0 0 40px rgba(168,85,247,0.06)",
    transform: "scale(1.02)",
  },
  cardBestValue: {
    background: "linear-gradient(135deg, rgba(245,158,11,0.08), rgba(234,88,12,0.04))",
    border: "1px solid rgba(245,158,11,0.25)",
    boxShadow: "0 0 40px rgba(245,158,11,0.06)",
  },
  bestBadge: {
    position: "absolute",
    top: "-13px",
    left: "50%",
    transform: "translateX(-50%)",
    background: "linear-gradient(135deg, #f59e0b, #ea580c)",
    color: "#fff",
    fontSize: "0.68rem",
    fontWeight: 700,
    padding: "5px 16px",
    borderRadius: "20px",
    fontFamily: font,
    letterSpacing: "0.04em",
    whiteSpace: "nowrap",
  },
  cardInner: {
    padding: "28px 20px 20px",
    display: "flex",
    flexDirection: "column",
    height: "100%",
  },

  // Card header
  cardHead: {
    textAlign: "center",
    marginBottom: "20px",
    paddingBottom: "16px",
    borderBottom: "1px solid rgba(255,255,255,0.06)",
  },
  tierLabel: {
    fontSize: "0.72rem",
    fontWeight: 700,
    textTransform: "uppercase",
    letterSpacing: "0.14em",
    color: "rgba(255,255,255,0.5)",
    fontFamily: font,
    marginBottom: "8px",
  },
  priceRow: {
    display: "flex",
    justifyContent: "center",
    alignItems: "baseline",
    gap: "2px",
  },
  priceBig: {
    fontSize: "2.6rem",
    fontWeight: 800,
    color: "rgba(255,255,255,0.95)",
    fontFamily: font,
    lineHeight: 1,
  },
  pricePer: {
    fontSize: "0.85rem",
    color: "rgba(255,255,255,0.35)",
    fontFamily: font,
    fontWeight: 400,
  },
  priceNote: {
    fontSize: "0.72rem",
    color: "rgba(255,255,255,0.35)",
    fontFamily: font,
    marginTop: "6px",
  },

  // Feature list
  featureList: {
    listStyle: "none",
    padding: 0,
    margin: "0 0 20px",
    flex: 1,
  },
  featureItem: {
    display: "flex",
    alignItems: "center",
    gap: "8px",
    padding: "5px 0",
    fontSize: "0.78rem",
    color: "rgba(255,255,255,0.75)",
    fontFamily: font,
  },
  checkGreen: {
    color: "rgba(34,197,94,0.9)",
    fontWeight: 700,
    minWidth: "16px",
    fontSize: "0.85rem",
  },
  checkGray: {
    color: "rgba(255,255,255,0.15)",
    fontWeight: 400,
    minWidth: "16px",
    fontSize: "0.85rem",
  },

  // Badges
  currentBadge: {
    textAlign: "center",
    padding: "12px",
    borderRadius: "14px",
    background: "rgba(255,255,255,0.04)",
    color: "rgba(255,255,255,0.4)",
    fontSize: "0.85rem",
    fontFamily: font,
    fontWeight: 600,
  },
  activeBadge: {
    textAlign: "center",
    padding: "12px",
    borderRadius: "14px",
    background: "rgba(168,85,247,0.1)",
    color: "rgba(168,85,247,0.9)",
    fontSize: "0.85rem",
    fontFamily: font,
    fontWeight: 700,
    border: "1px solid rgba(168,85,247,0.2)",
  },

  // Buttons
  purchaseBtn: {
    width: "100%",
    padding: "14px",
    borderRadius: "14px",
    border: "none",
    background: "linear-gradient(135deg, #a855f7, #6366f1)",
    color: "#fff",
    fontSize: "0.92rem",
    fontWeight: 700,
    fontFamily: font,
    cursor: "pointer",
    transition: "all 0.3s",
    boxShadow: "0 4px 24px rgba(168,85,247,0.25)",
    letterSpacing: "0.01em",
  },
  purchaseBtnGold: {
    width: "100%",
    padding: "14px",
    borderRadius: "14px",
    border: "none",
    background: "linear-gradient(135deg, #f59e0b, #ea580c)",
    color: "#fff",
    fontSize: "0.92rem",
    fontWeight: 700,
    fontFamily: font,
    cursor: "pointer",
    transition: "all 0.3s",
    boxShadow: "0 4px 24px rgba(245,158,11,0.25)",
    letterSpacing: "0.01em",
  },
  errorText: {
    color: "#ff6b6b",
    fontSize: "0.72rem",
    textAlign: "center",
    margin: "0 0 8px",
    fontFamily: font,
  },

  // Comparison table
  compSection: {
    marginTop: "8px",
  },
  compTitle: {
    fontSize: "1.15rem",
    fontWeight: 700,
    color: "rgba(255,255,255,0.9)",
    fontFamily: font,
    textAlign: "center",
    marginBottom: "16px",
  },
  tableWrap: {
    overflowX: "auto",
    borderRadius: "16px",
    border: "1px solid rgba(255,255,255,0.07)",
    background: "rgba(255,255,255,0.02)",
  },
  table: {
    width: "100%",
    borderCollapse: "collapse",
    fontFamily: font,
    fontSize: "0.8rem",
  },
  th: {
    padding: "12px 14px",
    textAlign: "left",
    color: "rgba(255,255,255,0.5)",
    fontWeight: 600,
    borderBottom: "1px solid rgba(255,255,255,0.07)",
    fontSize: "0.7rem",
    letterSpacing: "0.1em",
    textTransform: "uppercase",
  },
  thCenter: { textAlign: "center" },
  tr: {
    borderBottom: "1px solid rgba(255,255,255,0.03)",
  },
  td: {
    padding: "9px 14px",
    color: "rgba(255,255,255,0.65)",
  },
  tdCenter: {
    padding: "9px 14px",
    textAlign: "center",
    color: "rgba(255,255,255,0.65)",
  },
  footer: {
    textAlign: "center",
    fontSize: "0.7rem",
    color: "rgba(255,255,255,0.3)",
    fontFamily: font,
    marginTop: "24px",
    paddingBottom: "20px",
  },
};
