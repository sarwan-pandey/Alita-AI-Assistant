/**
 * useProductivityAnalytics — Track Focus, Mood & Habit Patterns
 *
 * Aggregates data over days/weeks to show:
 *   - Daily focus time (time spent in FOCUSED/CONVERSATION states)
 *   - Mood arc throughout the day
 *   - Most active hours
 *   - Topics discussed frequency
 *   - Distraction count
 *   - Session streak (consecutive days of usage)
 *
 * All data stays local (localStorage). Never leaves the device.
 *
 * Dispatches: "Alita:productivity_update" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";

const STORAGE_KEY = "alita_productivity";
const SAVE_INTERVAL_MS = 30000; // Save every 30s
const MAX_DAYS = 90; // Keep 90 days of data

function todayKey() {
  return new Date().toISOString().slice(0, 10); // YYYY-MM-DD
}

function currentHour() {
  return new Date().getHours();
}

function loadData() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch (_) {
    return {};
  }
}

function saveData(data) {
  try {
    // Prune old data (keep last MAX_DAYS)
    const keys = Object.keys(data).sort();
    if (keys.length > MAX_DAYS) {
      for (const key of keys.slice(0, keys.length - MAX_DAYS)) {
        delete data[key];
      }
    }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
  } catch (_) {}
}

function ensureToday(data) {
  const key = todayKey();
  if (!data[key]) {
    data[key] = {
      focusMinutes: 0,
      conversationMinutes: 0,
      distractionCount: 0,
      moodArc: [],           // { hour, mood }
      topicsDiscussed: {},    // { topic: count }
      activeHours: {},        // { hour: minutes }
      sessionStart: Date.now(),
      totalSessionMinutes: 0,
      messageCount: 0,
    };
  }
  return data[key];
}

export function useProductivityAnalytics({ enabled = false, messages = [] } = {}) {
  const [todayStats, setTodayStats] = useState(null);
  const dataRef = useRef(loadData());
  const mountedRef = useRef(true);
  const intervalRef = useRef(null);
  const lastStateRef = useRef("idle");
  const stateStartRef = useRef(Date.now());
  const lastMessageCountRef = useRef(0);

  // Track state changes from orchestrator
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { from, to } = e.detail || {};
      if (!to) return;

      const now = Date.now();
      const duration = (now - stateStartRef.current) / 60000; // minutes

      const today = ensureToday(dataRef.current);
      const hour = currentHour();

      // Accumulate time in previous state
      if (from === "focused" || from === "conversation") {
        today.focusMinutes += duration;
      }
      if (from === "conversation") {
        today.conversationMinutes += duration;
      }

      // Track active hours
      today.activeHours[hour] = (today.activeHours[hour] || 0) + duration;

      // Track distractions
      if (from === "focused" && to !== "conversation") {
        today.distractionCount++;
      }

      lastStateRef.current = to;
      stateStartRef.current = now;
    };

    window.addEventListener("Alita:state_change", handler);
    return () => window.removeEventListener("Alita:state_change", handler);
  }, [enabled]);

  // Track mood changes
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { mood } = e.detail || {};
      if (!mood) return;

      const today = ensureToday(dataRef.current);
      today.moodArc.push({ hour: currentHour(), mood, timestamp: Date.now() });

      // Keep last 100 mood entries per day
      if (today.moodArc.length > 100) today.moodArc.shift();
    };

    window.addEventListener("Alita:body_mood", handler);
    return () => window.removeEventListener("Alita:body_mood", handler);
  }, [enabled]);

  // Track predictions (topics)
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { topic } = e.detail || {};
      if (!topic) return;

      const today = ensureToday(dataRef.current);
      today.topicsDiscussed[topic] = (today.topicsDiscussed[topic] || 0) + 1;
    };

    window.addEventListener("Alita:prediction", handler);
    return () => window.removeEventListener("Alita:prediction", handler);
  }, [enabled]);

  // Track messages
  useEffect(() => {
    if (!enabled || messages.length <= lastMessageCountRef.current) return;

    const today = ensureToday(dataRef.current);
    today.messageCount = messages.length;
    lastMessageCountRef.current = messages.length;
  }, [enabled, messages]);

  // Periodic save + update stats
  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return () => { mountedRef.current = false; };

    const tick = () => {
      if (!mountedRef.current) return;

      const data = dataRef.current;
      const today = ensureToday(data);

      // Update session time
      today.totalSessionMinutes =
        (Date.now() - (today.sessionStart || Date.now())) / 60000;

      saveData(data);
      setTodayStats({ ...today });
    };

    intervalRef.current = setInterval(tick, SAVE_INTERVAL_MS);
    tick(); // Initial

    console.log("[Productivity] ✓ Analytics tracking active");

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
      // Final save
      saveData(dataRef.current);
    };
  }, [enabled]);

  // Compute weekly summary
  const getWeeklySummary = useCallback(() => {
    const data = dataRef.current;
    const days = [];
    const now = new Date();

    for (let i = 6; i >= 0; i--) {
      const d = new Date(now);
      d.setDate(d.getDate() - i);
      const key = d.toISOString().slice(0, 10);
      days.push({
        date: key,
        day: d.toLocaleDateString(undefined, { weekday: "short" }),
        ...(data[key] || {
          focusMinutes: 0,
          conversationMinutes: 0,
          distractionCount: 0,
          messageCount: 0,
        }),
      });
    }

    const totalFocus = days.reduce((s, d) => s + (d.focusMinutes || 0), 0);
    const totalConvo = days.reduce((s, d) => s + (d.conversationMinutes || 0), 0);
    const totalDistractions = days.reduce((s, d) => s + (d.distractionCount || 0), 0);
    const activeDays = days.filter((d) => (d.focusMinutes || 0) > 0).length;

    return {
      days,
      totalFocusMinutes: Math.round(totalFocus),
      totalConversationMinutes: Math.round(totalConvo),
      totalDistractions,
      activeDays,
      streak: activeDays, // Simplified streak
    };
  }, []);

  return { todayStats, getWeeklySummary };
}
