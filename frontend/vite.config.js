import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [
    react(),
    // Suppress missing source-map warnings for @mediapipe/tasks-vision
    {
      name: "suppress-mediapipe-sourcemap-warning",
      enforce: "pre",
      load(id) {
        if (id.includes("@mediapipe/tasks-vision") && id.endsWith(".map")) {
          return "";
        }
      },
    },
  ],
  server: {
    port: 5173,
    headers: {
      // Required for SharedArrayBuffer (AudioWorklet + WASM SIMD)
      "Cross-Origin-Opener-Policy": "same-origin",
      "Cross-Origin-Embedder-Policy": "credentialless",
    },
  },
  optimizeDeps: {
    exclude: ["@mediapipe/tasks-vision"],  // WASM bundle — must not be pre-bundled
  },
  build: {
    target: "esnext",
    sourcemap: false,  // Avoid source-map errors from mediapipe
    rollupOptions: {
      output: {
        manualChunks: {
          "three": ["three"],
          "r3f": ["@react-three/fiber", "@react-three/drei"],
          "mediapipe": ["@mediapipe/tasks-vision"],
        },
      },
    },
  },
});