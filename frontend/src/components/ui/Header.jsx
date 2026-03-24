/**
 * Header — Dashboard top bar.
 *   - "AI Assistance" branding
 *   - User avatar + name
 *   - Notification bell with badge + dropdown panel
 *   - Theme toggle (dark/light/auto cycle)
 *   - PREMIUM / FREE badge
 *   - Logout button
 */

import { useState, useRef, useEffect } from "react";

const THEME_ICONS = {
    dark: "🌙",
    light: "☀️",
    auto: "🖥️",
};

const THEME_LABELS = {
    dark: "Dark",
    light: "Light",
    auto: "Auto",
};

const PREMIUM_FEATURE_COUNT = 13;

export function Header({ user, tier, onLogout, theme, onThemeCycle, notifications, isTrialActive, trialDaysRemaining, isPremium, onShowPricing }) {
    const displayName = user?.email?.split("@")[0] || user?.id || "User";
    const initials = displayName.slice(0, 2).toUpperCase();

    const [notifOpen, setNotifOpen] = useState(false);
    const notifRef = useRef(null);

    // Close notification panel on outside click
    useEffect(() => {
        const handle = (e) => {
            if (notifRef.current && !notifRef.current.contains(e.target)) {
                setNotifOpen(false);
            }
        };
        document.addEventListener("mousedown", handle);
        return () => document.removeEventListener("mousedown", handle);
    }, []);

    const handleBellClick = () => {
        setNotifOpen((prev) => !prev);
        if (!notifOpen) {
            notifications?.markAllRead?.();
        }
    };

    return (
        <header className="dash-header" id="dashboard-header">
            {/* Left: Brand + User */}
            <div className="dash-header-left">
                <div className="dash-brand">
                    <span className="dash-brand-ai">AI </span>
                    <span className="dash-brand-name">Assistance</span>
                </div>
                <div className="dash-header-divider" />
                <div className="dash-header-user">
                    <div className="dash-header-avatar">{initials}</div>
                    <span className="dash-header-username">{displayName}</span>
                </div>
            </div>

            {/* Center: Upsell / Trial CTA (clickable, opens pricing) */}
            {onShowPricing && !isPremium && (
                <button
                    className="header-upsell-btn"
                    onClick={onShowPricing}
                    id="header-upsell"
                >
                    {isTrialActive ? (
                        <>
                            <span className="upsell-gem">✨</span>
                            <span>Unlock {PREMIUM_FEATURE_COUNT} Premium Features</span>
                            <span className="upsell-trial-badge">{trialDaysRemaining}d trial</span>
                        </>
                    ) : (
                        <>
                            <span className="upsell-gem">💎</span>
                            <span>Unlock {PREMIUM_FEATURE_COUNT} Premium Features</span>
                        </>
                    )}
                </button>
            )}

            {/* Right: Controls */}
            <div className="dash-header-right">
                {/* Notification bell */}
                <div className="notif-wrapper" ref={notifRef}>
                    <button
                        className="dash-header-icon-btn notif-bell-btn"
                        onClick={handleBellClick}
                        title="Notifications"
                        id="notif-bell"
                    >
                        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
                            <path d="M13.73 21a2 2 0 0 1-3.46 0" />
                        </svg>
                        {notifications?.unreadCount > 0 && (
                            <span className="notif-badge">{notifications.unreadCount > 9 ? "9+" : notifications.unreadCount}</span>
                        )}
                    </button>

                    {/* Notification dropdown panel */}
                    {notifOpen && (
                        <div className="notif-panel" id="notif-panel">
                            <div className="notif-panel-header">
                                <span>Notifications</span>
                                <div className="notif-panel-actions">
                                    {notifications?.notifications?.length > 0 && (
                                        <button className="notif-clear-btn" onClick={() => notifications?.clearAll?.()}>
                                            Clear All
                                        </button>
                                    )}
                                </div>
                            </div>
                            <div className="notif-panel-body">
                                {(!notifications?.notifications || notifications.notifications.length === 0) ? (
                                    <div className="notif-empty">No notifications yet</div>
                                ) : (
                                    [...notifications.notifications].reverse().slice(0, 20).map((n) => (
                                        <div className={`notif-item ${n.read ? "" : "unread"}`} key={n.id}>
                                            <div className="notif-item-header">
                                                <span className="notif-item-title">{n.title}</span>
                                                <button className="notif-dismiss" onClick={(e) => {
                                                    e.stopPropagation();
                                                    notifications?.dismiss?.(n.id);
                                                }}>×</button>
                                            </div>
                                            <p className="notif-item-body">{n.body}</p>
                                            <span className="notif-item-time">
                                                {formatTimeAgo(n.time)}
                                            </span>
                                        </div>
                                    ))
                                )}
                            </div>
                        </div>
                    )}
                </div>

                {/* Theme toggle */}
                <button
                    className="dash-header-icon-btn theme-toggle-btn"
                    onClick={onThemeCycle}
                    title={`Theme: ${THEME_LABELS[theme?.mode] || "Dark"}`}
                    id="theme-toggle"
                >
                    <span style={{ fontSize: "1rem" }}>
                        {THEME_ICONS[theme?.mode] || "🌙"}
                    </span>
                </button>

                {/* Tier badge — now shows PREMIUM / TRIAL / FREE */}
                <div
                    className={`dash-premium-badge ${isPremium ? "" : isTrialActive ? "trial" : "free"}`}
                    onClick={onShowPricing}
                    style={{ cursor: onShowPricing ? "pointer" : "default" }}
                    title={isPremium ? "Premium active" : isTrialActive ? `Trial: ${trialDaysRemaining} days remaining` : "Free plan — click to upgrade"}
                >
                    <span className="dash-premium-gem">{isPremium ? "💎" : isTrialActive ? "✨" : "◇"}</span>
                    <span>{isPremium ? "PREMIUM" : isTrialActive ? `TRIAL ${trialDaysRemaining}d` : "FREE"}</span>
                </div>

                {/* Logout */}
                <button
                    className="dash-header-icon-btn dash-logout-btn"
                    onClick={onLogout}
                    title="Sign Out"
                    id="logout-btn"
                >
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                        <polyline points="16 17 21 12 16 7" />
                        <line x1="21" y1="12" x2="9" y2="12" />
                    </svg>
                </button>
            </div>
        </header>
    );
}

function formatTimeAgo(timestamp) {
    const seconds = Math.floor((Date.now() - timestamp) / 1000);
    if (seconds < 60) return "just now";
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}m ago`;
    const hours = Math.floor(minutes / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
}
