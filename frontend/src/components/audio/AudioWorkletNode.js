/**
 * AudioWorkletNode Helper — Utilities for creating and managing offline PCM audio processor worklets.
 */

export async function createOfflineAudioWorklet(audioContext, stream, onChunk) {
  if (!audioContext || !stream) {
    throw new Error("AudioContext and MediaStream are required");
  }

  try {
    await audioContext.audioWorklet.addModule("/offlineAudioProcessor.js");
    const workletNode = new AudioWorkletNode(audioContext, "offline-audio-processor");

    workletNode.port.onmessage = (event) => {
      if (event.data?.type === "pcm_chunk" && event.data.pcm && onChunk) {
        onChunk(event.data.pcm);
      }
    };

    const source = audioContext.createMediaStreamSource(stream);
    source.connect(workletNode);
    workletNode.connect(audioContext.destination);

    return {
      workletNode,
      source,
      setActive: (active) => {
        workletNode.port.postMessage({ type: "set_active", active });
      },
      destroy: () => {
        try {
          source.disconnect();
          workletNode.disconnect();
        } catch (e) {
          console.warn("[AudioWorklet] Disconnect error:", e);
        }
      },
    };
  } catch (err) {
    console.error("[AudioWorklet] Failed to initialize AudioWorkletNode:", err);
    throw err;
  }
}
