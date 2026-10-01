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

      // 4003 = auth rejected, 4001 = session replaced — don't retry in infinite loop
      if (e.code === 4003 || e.code === 4001) {
        console.warn(`[WS] Connection closed with code ${e.code} — stopping retry loop.`);
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
      if (wsRef.current) {
        const socket = wsRef.current;
        if (socket.readyState === WebSocket.CONNECTING) {
          socket.onopen = () => {
            try { socket.close(); } catch (_) {}
          };
          socket.onmessage = null;
          socket.onerror = null;
          socket.onclose = null;
        } else if (socket.readyState === WebSocket.OPEN) {
          try {
            socket.close();
          } catch (_) {}
        }
      }
    };
  }, [token, enabled, connect]);

  const sendAudioChunk = useCallback((chunkData) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify(chunkData));
  }, []);

  // Send raw binary data (ArrayBuffer) — 8× more efficient for PCM audio
  const sendBinaryChunk = useCallback((arrayBuffer) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(arrayBuffer);
  }, []);

  const sendTextMessage = useCallback((text) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) {
      console.warn("[WS] sendTextMessage blocked — WS not open. State:", wsRef.current?.readyState);
      return;
    }
    console.log("[WS] Sending text_message:", text.slice(0, 50));
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

  const sendBargeIn = useCallback((partialResponse, originalQuery) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    console.log("[WS] Sending barge_in: partial=%d chars, query='%s'",
      (partialResponse || "").length, (originalQuery || "").slice(0, 40));
    wsRef.current.send(JSON.stringify({
      type: "barge_in",
      partial_response: partialResponse || "",
      original_query: originalQuery || "",
    }));
  }, []);

  // ── Speculative pre-generation ─────────────────────────────────────────
  // Sends interim transcript to backend so it can START generating a response
  // before the user finishes speaking. If the final transcript matches,
  // the response is already partially/fully cached → near-instant reply.
  const speculativeIdRef = useRef(0);

  const sendSpeculativeQuery = useCallback((interimText) => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    const specId = ++speculativeIdRef.current;
    console.log("[WS] Speculative query #%d: '%s'", specId, interimText.slice(0, 60));
    wsRef.current.send(JSON.stringify({
      type: "speculative_query",
      text: interimText,
      spec_id: specId,
    }));
  }, []);

  const cancelSpeculative = useCallback(() => {
    if (wsRef.current?.readyState !== WebSocket.OPEN) return;
    wsRef.current.send(JSON.stringify({
      type: "cancel_speculative",
    }));
  }, []);

  return { sendAudioChunk, sendBinaryChunk, sendTextMessage, sendDictation, sendDictationStop, sendBargeIn, sendSpeculativeQuery, cancelSpeculative, wsStatus };
}