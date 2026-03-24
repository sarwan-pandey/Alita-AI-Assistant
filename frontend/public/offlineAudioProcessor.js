/**
 * Offline Audio Processor — AudioWorklet for PCM streaming.
 *
 * Runs in a separate thread (no main-thread jank).
 * Replaces deprecated ScriptProcessorNode.
 * Sends raw Float32 PCM chunks to the main thread for WebSocket transmission.
 */
class OfflineAudioProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._active = false;

    // Listen for activation/deactivation from main thread
    this.port.onmessage = (e) => {
      if (e.data.type === "set_active") {
        this._active = e.data.active;
      }
    };
  }

  process(inputs) {
    // Only process when offline mode is active (gated)
    if (!this._active) return true;

    const input = inputs[0];
    if (!input || !input[0] || input[0].length === 0) return true;

    const channelData = input[0]; // mono channel

    // Send raw Float32Array to main thread (will be sent as binary WS)
    this.port.postMessage({
      type: "pcm_chunk",
      pcm: channelData, // Float32Array — transferred efficiently
    });

    return true; // keep processor alive
  }
}

registerProcessor("offline-audio-processor", OfflineAudioProcessor);
