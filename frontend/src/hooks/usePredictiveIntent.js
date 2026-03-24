/**
 * usePredictiveIntent — Predict What User Will Ask Next
 *
 * Analyzes conversation patterns, time-of-day, day-of-week, and
 * topic history to predict the user's next likely request.
 *
 * Algorithm:
 *   1. Track topics by keyword extraction from user messages
 *   2. Build time-based frequency maps (e.g. "weather" at 8 AM Mon)
 *   3. Apply Markov chains: P(next_topic | current_topic, time, day)
 *   4. Surface predictions as proactive suggestions
 *
 * Dispatches: "Alita:prediction" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";

const STORAGE_KEY = "alita_intent_patterns";
const PREDICTION_INTERVAL_MS = 30000; // Predict every 30s

// Topic keywords — expanded set for common queries
const TOPIC_KEYWORDS = {
  weather:      ["weather", "temperature", "rain", "cold", "hot", "sunny", "forecast"],
  time:         ["time", "clock", "hour", "schedule", "alarm", "timer"],
  music:        ["music", "song", "play", "playlist", "spotify", "album", "artist"],
  news:         ["news", "headline", "latest", "today", "update", "breaking"],
  code:         ["code", "bug", "error", "function", "programming", "debug", "fix"],
  health:       ["health", "exercise", "workout", "calories", "steps", "fitness", "heart"],
  email:        ["email", "mail", "inbox", "message", "send", "reply"],
  search:       ["search", "find", "google", "look up", "what is", "who is"],
  translate:    ["translate", "language", "hindi", "spanish", "french"],
  reminder:     ["remind", "reminder", "forget", "remember", "note", "todo"],
  math:         ["calculate", "math", "sum", "average", "percentage", "convert"],
  general:      ["hello", "hi", "thanks", "help", "how are"],
};

function extractTopics(text) {
  if (!text) return [];
  const lower = text.toLowerCase();
  const found = [];
  for (const [topic, keywords] of Object.entries(TOPIC_KEYWORDS)) {
    if (keywords.some((kw) => lower.includes(kw))) {
      found.push(topic);
    }
  }
  return found.length > 0 ? found : ["general"];
}

function getTimeSlot() {
  const h = new Date().getHours();
  if (h < 6) return "night";
  if (h < 9) return "early_morning";
  if (h < 12) return "morning";
  if (h < 14) return "noon";
  if (h < 17) return "afternoon";
  if (h < 20) return "evening";
  return "night";
}

function getDayType() {
  const day = new Date().getDay();
  return (day === 0 || day === 6) ? "weekend" : "weekday";
}

function loadPatterns() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch (_) {
    return {};
  }
}

function savePatterns(patterns) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(patterns));
  } catch (_) {}
}

export function usePredictiveIntent({ enabled = false, messages = [] } = {}) {
  const [prediction, setPrediction] = useState(null);
  const patternsRef = useRef(loadPatterns());
  const lastMessageCountRef = useRef(0);
  const mountedRef = useRef(true);
  const intervalRef = useRef(null);
  const lastTopicRef = useRef("general");

  // Learn from new messages
  useEffect(() => {
    if (!enabled || messages.length <= lastMessageCountRef.current) return;

    const newMessages = messages.slice(lastMessageCountRef.current);
    lastMessageCountRef.current = messages.length;

    const patterns = patternsRef.current;
    const slot = getTimeSlot();
    const dayType = getDayType();

    for (const msg of newMessages) {
      if (msg.role !== "user") continue;

      const topics = extractTopics(msg.content);
      const contextKey = `${dayType}_${slot}`;

      // Update frequency map: contextKey → { topic: count }
      if (!patterns[contextKey]) patterns[contextKey] = {};
      for (const topic of topics) {
        patterns[contextKey][topic] = (patterns[contextKey][topic] || 0) + 1;
      }

      // Update transition map: lastTopic → { nextTopic: count }
      const transKey = `transition_${lastTopicRef.current}`;
      if (!patterns[transKey]) patterns[transKey] = {};
      for (const topic of topics) {
        patterns[transKey][topic] = (patterns[transKey][topic] || 0) + 1;
      }

      lastTopicRef.current = topics[0];
    }

    patternsRef.current = patterns;
    savePatterns(patterns);
  }, [enabled, messages]);

  // Prediction engine
  const predict = useCallback(() => {
    const patterns = patternsRef.current;
    const slot = getTimeSlot();
    const dayType = getDayType();
    const contextKey = `${dayType}_${slot}`;
    const transKey = `transition_${lastTopicRef.current}`;

    // Score each topic
    const scores = {};

    // Factor 1: Time-based frequency (what do they usually ask now?)
    const timeFreqs = patterns[contextKey] || {};
    const totalTimeFreq = Object.values(timeFreqs).reduce((s, v) => s + v, 0) || 1;
    for (const [topic, count] of Object.entries(timeFreqs)) {
      scores[topic] = (scores[topic] || 0) + (count / totalTimeFreq) * 0.6;
    }

    // Factor 2: Markov transition (what usually follows the current topic?)
    const transFreqs = patterns[transKey] || {};
    const totalTransFreq = Object.values(transFreqs).reduce((s, v) => s + v, 0) || 1;
    for (const [topic, count] of Object.entries(transFreqs)) {
      scores[topic] = (scores[topic] || 0) + (count / totalTransFreq) * 0.4;
    }

    // Find top prediction (excluding "general")
    let bestTopic = null;
    let bestScore = 0;
    for (const [topic, score] of Object.entries(scores)) {
      if (topic !== "general" && score > bestScore) {
        bestTopic = topic;
        bestScore = score;
      }
    }

    if (bestTopic && bestScore > 0.3) {
      const pred = { topic: bestTopic, confidence: bestScore, time: slot, day: dayType };
      setPrediction(pred);

      console.log(
        `[Predict] 🔮 Prediction: "${bestTopic}" (${(bestScore * 100).toFixed(0)}% likely at ${slot} on ${dayType})`,
      );

      window.dispatchEvent(
        new CustomEvent("Alita:prediction", { detail: pred }),
      );
    }
  }, []);

  // Run predictions periodically
  useEffect(() => {
    mountedRef.current = true;
    if (!enabled) return () => { mountedRef.current = false; };

    intervalRef.current = setInterval(() => {
      if (mountedRef.current) predict();
    }, PREDICTION_INTERVAL_MS);

    // Initial prediction after 5s
    const timer = setTimeout(predict, 5000);

    console.log("[Predict] ✓ Predictive intent engine active");

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
      clearTimeout(timer);
    };
  }, [enabled, predict]);

  return { prediction };
}
