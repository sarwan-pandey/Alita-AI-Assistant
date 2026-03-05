/**
 * useNotifications — Smart notification manager.
 *
 * Features:
 *   - Time-based greetings (Good Morning/Afternoon/Evening)
 *   - Daily productivity/health/tech tips
 *   - Holiday awareness
 *   - Web Notifications API for system-level alerts
 *   - In-app notification history with unread counter
 *   - Persists to localStorage
 */

import { useState, useEffect, useCallback, useRef } from "react";

const STORAGE_KEY = "alita-notifications";
const LAST_GREETING_KEY = "alita-last-greeting";
const LAST_TIP_KEY = "alita-last-tip-time";

const TIPS = [
    "💡 Take a 5-minute break every 25 minutes (Pomodoro technique).",
    "💧 Stay hydrated — drink a glass of water now!",
    "🧘 Deep breaths: 4 counts in, 7 hold, 8 out. Repeat 3 times.",
    "🖥️ Look away from your screen every 20 minutes at something 20 feet away for 20 seconds.",
    "📱 Try putting your phone on Do Not Disturb while working.",
    "🏃 A 10-minute walk boosts creativity for 2 hours.",
    "🎵 Listening to instrumental music can improve focus.",
    "📝 Write down your top 3 priorities for today.",
    "🌙 Blue light filters help you sleep better — enable night mode after 8 PM.",
    "🧠 Teaching someone else what you learned reinforces your memory.",
    "⌨️ Use keyboard shortcuts to save 8 workdays per year!",
    "🍎 An apple gives you more energy than a cup of coffee.",
    "📚 Reading 20 minutes a day exposes you to 1.8M words per year.",
    "🏋 Just 7 minutes of exercise daily can make a huge difference.",
    "💤 Consistent sleep schedule is more important than total hours.",
];

function getGreeting() {
    const hour = new Date().getHours();
    if (hour >= 5 && hour < 12) return { text: "Good Morning! ☀️", icon: "🌅" };
    if (hour >= 12 && hour < 17) return { text: "Good Afternoon! 🌤️", icon: "☀️" };
    if (hour >= 17 && hour < 21) return { text: "Good Evening! 🌇", icon: "🌆" };
    return { text: "Good Night! 🌙", icon: "🌙" };
}

function getHolidayTip() {
    const now = new Date();
    const m = now.getMonth() + 1;
    const d = now.getDate();

    // Basic holiday awareness
    if (m === 1 && d === 1) return "🎉 Happy New Year! Set your goals for the year.";
    if (m === 1 && d === 26) return "🇮🇳 Happy Republic Day!";
    if (m === 8 && d === 15) return "🇮🇳 Happy Independence Day!";
    if (m === 12 && d === 25) return "🎄 Merry Christmas!";
    if (m === 10 && d === 2) return "🕊️ Happy Gandhi Jayanti!";
    if (m === 11 && d === 14) return "🪔 Happy Children's Day!";
    return null;
}

export function useNotifications() {
    const [notifications, setNotifications] = useState(() => {
        try {
            return JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
        } catch {
            return [];
        }
    });

    const [unreadCount, setUnreadCount] = useState(0);
    const tipTimerRef = useRef(null);

    // Persist to localStorage
    useEffect(() => {
        try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(notifications.slice(-50)));
        } catch { }
        setUnreadCount(notifications.filter((n) => !n.read).length);
    }, [notifications]);

    // Add a notification
    const addNotification = useCallback((title, body, type = "info") => {
        const notif = {
            id: Date.now() + Math.random(),
            title,
            body,
            type, // "greeting", "tip", "alert", "info"
            time: Date.now(),
            read: false,
        };

        setNotifications((prev) => [...prev, notif]);

        // Also send system notification if permitted
        if ("Notification" in window && Notification.permission === "granted") {
            try {
                new Notification(title, {
                    body,
                    icon: "/alita-icon.png",
                    silent: type === "tip",
                });
            } catch { }
        }

        return notif;
    }, []);

    // Mark all as read
    const markAllRead = useCallback(() => {
        setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
    }, []);

    // Clear all
    const clearAll = useCallback(() => {
        setNotifications([]);
    }, []);

    // Dismiss one
    const dismiss = useCallback((id) => {
        setNotifications((prev) => prev.filter((n) => n.id !== id));
    }, []);

    // Request permission on mount
    useEffect(() => {
        if ("Notification" in window && Notification.permission === "default") {
            Notification.requestPermission();
        }
    }, []);

    // Time-based greeting (once per session per time-of-day)
    useEffect(() => {
        const greeting = getGreeting();
        const lastGreeting = localStorage.getItem(LAST_GREETING_KEY);
        const today = new Date().toDateString();
        const greetingKey = `${today}-${greeting.text}`;

        if (lastGreeting !== greetingKey) {
            setTimeout(() => {
                addNotification(greeting.text, "How can I help you today?", "greeting");
                localStorage.setItem(LAST_GREETING_KEY, greetingKey);
            }, 2000);
        }

        // Check for holiday
        const holiday = getHolidayTip();
        if (holiday) {
            const holidayKey = `${today}-holiday`;
            if (localStorage.getItem("alita-last-holiday") !== holidayKey) {
                setTimeout(() => {
                    addNotification("Holiday Today!", holiday, "info");
                    localStorage.setItem("alita-last-holiday", holidayKey);
                }, 5000);
            }
        }
    }, [addNotification]);

    // Daily tip every 30 minutes
    useEffect(() => {
        const sendTip = () => {
            const lastTipTime = parseInt(localStorage.getItem(LAST_TIP_KEY) || "0");
            const now = Date.now();
            const THIRTY_MIN = 30 * 60 * 1000;

            if (now - lastTipTime > THIRTY_MIN) {
                const tip = TIPS[Math.floor(Math.random() * TIPS.length)];
                addNotification("Daily Tip", tip, "tip");
                localStorage.setItem(LAST_TIP_KEY, now.toString());
            }
        };

        // Check on mount
        setTimeout(sendTip, 10000);

        // Check every 15 minutes
        tipTimerRef.current = setInterval(sendTip, 15 * 60 * 1000);
        return () => clearInterval(tipTimerRef.current);
    }, [addNotification]);

    return {
        notifications,
        unreadCount,
        addNotification,
        markAllRead,
        clearAll,
        dismiss,
    };
}
