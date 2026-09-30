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
  resolve: {
    // Dedupe three.js — ensures react-globe.gl → globe.gl → three-globe
    // all share the SAME three instance (no duplicate warnings).
    // NOTE: Do NOT use alias: { three: path.resolve(...) } — that breaks
    // subpath exports like three/webgpu and three/tsl.
    dedupe: ["three"],
  },
  optimizeDeps: {
    exclude: [
      "@mediapipe/tasks-vision",
      "onnxruntime-web",
    ], // WASM/ONNX bundles — must not be pre-bundled
  },
  build: {
    target: "esnext",
    sourcemap: false, // Avoid source-map errors from mediapipe
    // SECURITY: Strip all console.* and debugger statements from production
    minify: 'esbuild',
    rollupOptions: {
      output: {
        manualChunks: {
          three: ["three"],
          r3f: ["@react-three/fiber", "@react-three/drei"],
          mediapipe: ["@mediapipe/tasks-vision"],
        },
      },
    },
  },
  esbuild: {
    // Strip console.log/warn/error/debug and debugger from production builds
    drop: process.env.NODE_ENV === 'production' ? ['console', 'debugger'] : [],
  },
});
