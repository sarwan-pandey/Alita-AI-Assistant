/**
 * WebcamFeed — Mounts a hidden <video> element with the webcam stream.
 * This video is consumed ONLY by MediaPipeController for local WASM inference.
 * It is display:none and its stream is NEVER serialised or sent anywhere.
 */

import { useEffect } from "react";

export function WebcamFeed({ videoRef }) {
  useEffect(() => {
    let stream = null;

    async function startWebcam() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            width: { ideal: 1280 },
            height: { ideal: 720 },
            facingMode: "user",
            frameRate: { ideal: 30 },
          },
          audio: false,    // Audio captured separately by AudioCapture
        });

        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          await videoRef.current.play();
        }
      } catch (err) {
        console.error("[WebcamFeed] getUserMedia failed:", err);
      }
    }

    startWebcam();

    return () => {
      stream?.getTracks().forEach((t) => t.stop());
    };
  }, [videoRef]);

  return (
    <video
      ref={videoRef}
      style={{ display: "none" }}
      playsInline
      muted
      autoPlay
      aria-hidden="true"
    />
  );
}