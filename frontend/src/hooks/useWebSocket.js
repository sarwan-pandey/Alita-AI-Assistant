/**
 * useWebSocket — Auto-connects when token is available.
 * Auto-reconnects on disconnect with exponential backoff.
 * Stops reconnecting only on auth rejection (code 4003).
 * Sends keepalive pings every 15s to prevent idle disconnects.
 */

import { useEffect, useRef, useCallback, useState } from "react";

const WS_URL = import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws";
const BACKOFF_MAX = 30000;  // 30 seconds max between retries
const PING_INTERVAL = 15000; // 15 seconds

export function useWebSocket({ token, onMessage, enabled }) {
  const wsRef = useRef(null);
  const backoffRef = useRef(1000);
  const retryTimer = useRef(null);
  const pingTimer = useRef(null);
  const mountedRef = useRef(true);
  const [wsStatus, setWsStatus] = useState("disconnected");

  const connect = useCallback(() => {
    if (!token || !enabled || !mountedRef.current) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    setWsStatus("connecting");

    const ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`);
    wsRef.current = ws;

    ws.onopen = () => {
      if (!mountedRef.current) return;
      console.log("[WS] Connected");
      backoffRef.current = 1000;   // reset backoff on success
      setWsStatus("open");

      // Start keepalive pings
      clearInterval(pingTimer.current);
      pingTimer.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "ping" }));
        }
      }, PING_INTERVAL);
    };

    ws.onmessage = (e) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === "pong") return; // swallow keepalive replies
        onMessage?.(msg);
      } catch (err) {
        console.error("[WS] Parse error:", err);
      }
    };

    ws.onclose = (e) => {
      if (!mountedRef.current) return;
      setWsStatus("closed");
      clearInterval(pingTimer.current);
      console.log("[WS] Closed. Code:", e.code);

      // 4003 = auth rejected — don't retry
      if (e.code === 4003) {
        console.warn("[WS] Auth rejected — not retrying.");
        return;
      }

      // Exponential backoff reconnect
      const delay = Math.min(backoffRef.current, BACKOFF_MAX);
      backoffRef.current = Math.min(backoffRef.current * 2, BACKOFF_MAX);
      console.log(`[WS] Reconnecting in ${delay}ms…`);

      retryTimer.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, delay);
    };

    ws.onerror = (e) => {
      console.error("[WS] Error:", e);
      setWsStatus("error");
    };
  }, [token, enabled, onMessage]);

  // Auto-connect when token becomes available + cleanup on unmount
  useEffect(() => {
    mountedRef.current = true;

    if (token && enabled) {
      connect();
    }

    return () => {
      mountedRef.current = false;
      clearTimeout(retryTimer.current);
      clearInterval(pingTimer.current);
      wsRef.current?.close();
    };
  }, [token, enabled, connect]);

  const sendAudioChunk = useCallback((chunkData) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify(chunkData));
  }, []);

  const sendTextMessage = useCallback((text) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({
      type: "text_message",
      text,
    }));
  }, []);

  const sendDictation = useCallback((text) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({
      type: "dictate_text",
      text,
    }));
  }, []);

  const sendDictationStop = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({
      type: "dictation_stop",
    }));
  }, []);

  return { sendAudioChunk, sendTextMessage, sendDictation, sendDictationStop, wsStatus };
}