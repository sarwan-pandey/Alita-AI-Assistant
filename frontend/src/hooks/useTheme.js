/**
 * useTheme — Dark / Light / Auto theme manager.
 *
 * Three modes:
 *   - "dark"  → force dark theme
 *   - "light" → force light theme
 *   - "auto"  → follow system preference via matchMedia
 *
 * Persists choice to localStorage.
 * Applies `data-theme` attribute on <html> element.
 */

import { useState, useEffect, useCallback } from "react";

const STORAGE_KEY = "alita-theme-preference";

export function useTheme() {
    const [mode, setMode] = useState(() => {
        try {
            return localStorage.getItem(STORAGE_KEY) || "dark";
        } catch {
            return "dark";
        }
    });

    const [resolved, setResolved] = useState("dark");

    // Resolve the actual theme (handling "auto" mode)
    const resolveTheme = useCallback((m) => {
        if (m === "auto") {
            return window.matchMedia("(prefers-color-scheme: dark)").matches
                ? "dark"
                : "light";
        }
        return m;
    }, []);

    // Apply theme to DOM
    const applyTheme = useCallback((theme) => {
        document.documentElement.setAttribute("data-theme", theme);
        setResolved(theme);
    }, []);

    // On mode change
    useEffect(() => {
        try {
            localStorage.setItem(STORAGE_KEY, mode);
        } catch { }

        applyTheme(resolveTheme(mode));

        // Listen for system preference changes (only matters in auto mode)
        if (mode === "auto") {
            const mql = window.matchMedia("(prefers-color-scheme: dark)");
            const handler = (e) => applyTheme(e.matches ? "dark" : "light");
            mql.addEventListener("change", handler);
            return () => mql.removeEventListener("change", handler);
        }
    }, [mode, applyTheme, resolveTheme]);

    // Cycle: dark → light → auto → dark
    const cycleTheme = useCallback(() => {
        setMode((prev) => {
            if (prev === "dark") return "light";
            if (prev === "light") return "auto";
            return "dark";
        });
    }, []);

    return { mode, resolved, setMode, cycleTheme };
}
