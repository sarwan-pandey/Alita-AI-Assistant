/**
 * useContextAwareness — Proactive Browser Context Monitoring
 *
 * Monitors device & environment signals and dispatches events when
 * notable changes occur. Zero external dependencies.
 *
 * Signals:
 *   - Battery level & charging state (Battery API)
 *   - Network online/offline (navigator.onLine + Network Information API)
 *   - Time of day (morning/afternoon/evening/night)
 *   - Page visibility (user switched tabs)
 *   - Device memory (navigator.deviceMemory)
 *
 * Dispatches: "Alita:context_update" CustomEvent
 */

import { useEffect, useRef, useCallback } from "react";

const CHECK_INTERVAL_MS = 30000; // Check every 30s

function getTimeOfDay() {
  const hour = new Date().getHours();
  if (hour >= 5 && hour < 12) return "morning";
  if (hour >= 12 && hour < 17) return "afternoon";
  if (hour >= 17 && hour < 21) return "evening";
  return "night";
}

function getGreeting(timeOfDay) {
  switch (timeOfDay) {
    case "morning": return "Good morning! ☀️";
    case "afternoon": return "Good afternoon! 🌤";
    case "evening": return "Good evening! 🌅";
    case "night": return "It's getting late! 🌙";
    default: return "Hello!";
  }
}

export function useContextAwareness({ enabled = false } = {}) {
  const mountedRef = useRef(true);
  const lastContextRef = useRef({
    batteryLevel: null,
    charging: null,
    online: null,
    timeOfDay: null,
    hidden: null,
  });
  const alertedRef = useRef({
    lowBattery: false,
    criticalBattery: false,
    offline: false,
    lateNight: false,
    greeting: false,
  });

  const dispatch = useCallback((type, data) => {
    console.log(`[Context] ${type}:`, data.message || JSON.stringify(data));
    window.dispatchEvent(
      new CustomEvent("Alita:context_update", {
        detail: { type, ...data, timestamp: Date.now() },
      }),
    );
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    let batteryRef = null;
    let intervalId = null;

    async function init() {
      // ── Initial greeting based on time ────────────────────────────
      const timeOfDay = getTimeOfDay();
      if (!alertedRef.current.greeting) {
        alertedRef.current.greeting = true;
        dispatch("greeting", {
          timeOfDay,
          message: getGreeting(timeOfDay),
        });
      }
      lastContextRef.current.timeOfDay = timeOfDay;

      // ── Battery API ──────────────────────────────────────────────
      try {
        if ("getBattery" in navigator) {
          const battery = await navigator.getBattery();
          batteryRef = battery;

          const checkBattery = () => {
            if (!mountedRef.current) return;
            const level = Math.round(battery.level * 100);
            const charging = battery.charging;

            // Low battery alert (< 20%)
            if (level <= 20 && !charging && !alertedRef.current.lowBattery) {
              alertedRef.current.lowBattery = true;
              dispatch("battery_low", {
                level,
                message: `⚡ Battery at ${level}% — consider charging soon`,
              });
            }

            // Critical battery (< 10%)
            if (level <= 10 && !charging && !alertedRef.current.criticalBattery) {
              alertedRef.current.criticalBattery = true;
              dispatch("battery_critical", {
                level,
                message: `🔴 Battery critical at ${level}%! Plug in now`,
              });
            }

            // Reset alerts when charging
            if (charging && lastContextRef.current.charging === false) {
              alertedRef.current.lowBattery = false;
              alertedRef.current.criticalBattery = false;
              dispatch("battery_charging", {
                level,
                message: `🔌 Charging started — battery at ${level}%`,
              });
            }

            lastContextRef.current.batteryLevel = level;
            lastContextRef.current.charging = charging;
          };

          battery.addEventListener("levelchange", checkBattery);
          battery.addEventListener("chargingchange", checkBattery);
          checkBattery();
        }
      } catch (_) {
        // Battery API not available
      }

      // ── Network monitoring ────────────────────────────────────────
      const handleOnline = () => {
        if (!mountedRef.current) return;
        if (alertedRef.current.offline) {
          alertedRef.current.offline = false;
          dispatch("network_restored", {
            message: "📶 Network connection restored",
          });
        }
        lastContextRef.current.online = true;
      };

      const handleOffline = () => {
        if (!mountedRef.current) return;
        alertedRef.current.offline = true;
        dispatch("network_lost", {
          message: "📡 Network connection lost — some features may be limited",
        });
        lastContextRef.current.online = false;
      };

      window.addEventListener("online", handleOnline);
      window.addEventListener("offline", handleOffline);
      lastContextRef.current.online = navigator.onLine;

      // ── Page visibility ───────────────────────────────────────────
      const handleVisibility = () => {
        if (!mountedRef.current) return;
        const hidden = document.hidden;
        if (hidden !== lastContextRef.current.hidden) {
          lastContextRef.current.hidden = hidden;
          dispatch("visibility_change", {
            hidden,
            message: hidden
              ? "User switched away from tab"
              : "User returned to tab",
          });
        }
      };
      document.addEventListener("visibilitychange", handleVisibility);

      // ── Periodic checks ───────────────────────────────────────────
      intervalId = setInterval(() => {
        if (!mountedRef.current) return;

        const newTime = getTimeOfDay();
        if (newTime !== lastContextRef.current.timeOfDay) {
          lastContextRef.current.timeOfDay = newTime;
          dispatch("time_change", {
            timeOfDay: newTime,
            message: getGreeting(newTime),
          });

          // Late night warning
          if (newTime === "night" && !alertedRef.current.lateNight) {
            alertedRef.current.lateNight = true;
            dispatch("late_night", {
              message: "🌙 It's getting late — remember to take breaks!",
            });
          }
          if (newTime === "morning") {
            alertedRef.current.lateNight = false;
          }
        }

        // Network info (if available)
        if ("connection" in navigator) {
          const conn = navigator.connection;
          if (conn?.effectiveType === "2g" || conn?.effectiveType === "slow-2g") {
            dispatch("slow_network", {
              effectiveType: conn.effectiveType,
              message: `🐌 Slow network detected (${conn.effectiveType})`,
            });
          }
        }
      }, CHECK_INTERVAL_MS);

      // Log device info once
      const deviceInfo = {
        memory: navigator.deviceMemory || "unknown",
        cores: navigator.hardwareConcurrency || "unknown",
        platform: navigator.platform,
        online: navigator.onLine,
      };
      console.log("[Context] ✓ Awareness active:", deviceInfo);
    }

    init();

    return () => {
      mountedRef.current = false;
      if (intervalId) clearInterval(intervalId);
      window.removeEventListener("online", () => {});
      window.removeEventListener("offline", () => {});
      document.removeEventListener("visibilitychange", () => {});
    };
  }, [enabled, dispatch]);

  return null;
}
