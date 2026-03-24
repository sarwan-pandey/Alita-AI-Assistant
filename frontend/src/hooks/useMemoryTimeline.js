/**
 * useMemoryTimeline — Aggregate conversation data for timeline visualization
 *
 * Collects messages, emotions, and timestamps into a structured timeline.
 * Stores in localStorage for persistence across sessions.
 */

import { useEffect, useRef, useCallback, useState } from "react";

const STORAGE_KEY = "alita_memory_timeline";
const MAX_ENTRIES = 200;

function loadTimeline() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : [];
  } catch (_) {
    return [];
  }
}

function saveTimeline(entries) {
  try {
    // Keep only last MAX_ENTRIES
    const trimmed = entries.slice(-MAX_ENTRIES);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(trimmed));
  } catch (_) {}
}

export function useMemoryTimeline({ enabled = false, messages = [] } = {}) {
  const [timeline, setTimeline] = useState(() => loadTimeline());
  const lastMessageCountRef = useRef(0);
  const mountedRef = useRef(true);

  // Track new messages
  useEffect(() => {
    if (!enabled) return;
    mountedRef.current = true;

    if (messages.length <= lastMessageCountRef.current) return;

    const newMessages = messages.slice(lastMessageCountRef.current);
    lastMessageCountRef.current = messages.length;

    const newEntries = newMessages.map((msg) => ({
      id: msg.id || Date.now() + Math.random(),
      role: msg.role,
      text: (msg.content || "").slice(0, 100), // First 100 chars
      timestamp: msg.id || Date.now(),
      emotion: null,
      category: null,
    }));

    setTimeline((prev) => {
      const updated = [...prev, ...newEntries];
      saveTimeline(updated);
      return updated;
    });
  }, [enabled, messages]);

  // Track emotion changes
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { label, confidence } = e.detail || {};
      if (!label) return;

      // Attach emotion to the most recent timeline entry
      setTimeline((prev) => {
        if (prev.length === 0) return prev;
        const updated = [...prev];
        updated[updated.length - 1] = {
          ...updated[updated.length - 1],
          emotion: label,
          emotionConfidence: confidence,
        };
        saveTimeline(updated);
        return updated;
      });
    };

    // Listen for various events
    window.addEventListener("Alita:body_mood", handler);
    return () => window.removeEventListener("Alita:body_mood", handler);
  }, [enabled]);

  // Track context events
  useEffect(() => {
    if (!enabled) return;

    const handler = (e) => {
      const { type, message } = e.detail || {};
      if (!type) return;

      const entry = {
        id: Date.now() + Math.random(),
        role: "system",
        text: message || type,
        timestamp: Date.now(),
        category: "context",
        contextType: type,
      };

      setTimeline((prev) => {
        const updated = [...prev, entry];
        saveTimeline(updated);
        return updated;
      });
    };

    window.addEventListener("Alita:context_update", handler);
    return () => window.removeEventListener("Alita:context_update", handler);
  }, [enabled]);

  const clearTimeline = useCallback(() => {
    setTimeline([]);
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  // Group timeline by time periods
  const groupedTimeline = timeline.reduce((groups, entry) => {
    const date = new Date(entry.timestamp);
    const key = date.toLocaleDateString();
    if (!groups[key]) groups[key] = [];
    groups[key].push(entry);
    return groups;
  }, {});

  return { timeline, groupedTimeline, clearTimeline };
}
