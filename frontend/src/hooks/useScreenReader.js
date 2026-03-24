/**
 * useScreenReader — Tab Screenshot + Text Extraction
 *
 * Captures the current browser tab via getDisplayMedia and extracts
 * visible text by sending the screenshot to the backend (Gemini vision).
 *
 * Dispatches: "Alita:screen_text" CustomEvent
 * Listens:   "Alita:read_screen" CustomEvent (trigger)
 */

import { useEffect, useRef, useCallback } from "react";

export function useScreenReader({ enabled = false, sendMessage = null } = {}) {
  const mountedRef = useRef(true);
  const sendMessageRef = useRef(sendMessage);

  // Keep ref in sync
  useEffect(() => {
    sendMessageRef.current = sendMessage;
  });

  const captureAndRead = useCallback(async () => {
    let stream = null;
    try {
      console.log("[ScreenReader] Requesting screen capture…");

      // Request screen sharing (user must approve)
      stream = await navigator.mediaDevices.getDisplayMedia({
        video: { mediaSource: "screen" },
        audio: false,
      });

      // Capture a single frame
      const track = stream.getVideoTracks()[0];
      const imageCapture = new ImageCapture(track);
      const bitmap = await imageCapture.grabFrame();

      // Draw to canvas
      const canvas = document.createElement("canvas");
      canvas.width = bitmap.width;
      canvas.height = bitmap.height;
      const ctx = canvas.getContext("2d");
      ctx.drawImage(bitmap, 0, 0);

      // Stop the stream immediately (privacy)
      stream.getTracks().forEach((t) => t.stop());
      stream = null;

      // Convert to base64 (compressed JPEG for smaller payload)
      const dataUrl = canvas.toDataURL("image/jpeg", 0.7);
      const base64 = dataUrl.split(",")[1];

      console.log(
        "[ScreenReader] Captured %.1f KB screenshot",
        (base64.length * 3) / 4 / 1024,
      );

      // Send to backend for Gemini vision analysis
      if (sendMessageRef.current) {
        sendMessageRef.current({
          type: "screen_read",
          image_b64: base64,
          prompt: "Describe what you see on this screen. Read any visible text.",
        });
      }

      // Also dispatch local event with raw data
      window.dispatchEvent(
        new CustomEvent("Alita:screen_captured", {
          detail: { width: bitmap.width, height: bitmap.height },
        }),
      );
    } catch (err) {
      // Stop stream if error occurred after creation
      if (stream) {
        stream.getTracks().forEach((t) => t.stop());
      }

      if (err.name === "NotAllowedError") {
        console.log("[ScreenReader] User denied screen sharing");
      } else {
        console.warn("[ScreenReader] Capture failed:", err.message);
      }

      window.dispatchEvent(
        new CustomEvent("Alita:screen_text", {
          detail: {
            text: "",
            error: err.name === "NotAllowedError"
              ? "Screen sharing was denied"
              : err.message,
          },
        }),
      );
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    const handler = () => captureAndRead();
    window.addEventListener("Alita:read_screen", handler);
    console.log("[ScreenReader] ✓ Ready — say 'read my screen' to activate");

    return () => {
      mountedRef.current = false;
      window.removeEventListener("Alita:read_screen", handler);
    };
  }, [enabled, captureAndRead]);

  return { captureAndRead };
}
