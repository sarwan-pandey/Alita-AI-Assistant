import { useAvatarStore } from '../store/avatarStore';

class AudioService {
  constructor() {
    this.audioCtx = null;
    this.micStream = null;
    this.micAnalyser = null;
    this.ttsAnalyser = null;
    this.activeSource = null;
    this.animFrame = null;
  }

  ensureContext() {
    if (!this.audioCtx) {
      const AudioContextClass = window.AudioContext || window.webkitAudioContext;
      this.audioCtx = new AudioContextClass();
    }
    if (this.audioCtx.state === 'suspended') {
      this.audioCtx.resume();
    }
  }

  async startMicrophone() {
    try {
      this.ensureContext();
      this.micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
      const source = this.audioCtx.createMediaStreamSource(this.micStream);
      this.micAnalyser = this.audioCtx.createAnalyser();
      this.micAnalyser.fftSize = 256;
      this.micAnalyser.smoothingTimeConstant = 0.5;
      source.connect(this.micAnalyser);

      useAvatarStore.getState().setIsMicActive(true);
      this.startAnalysisLoop();
      return true;
    } catch (err) {
      console.warn('Microphone access denied or error:', err);
      useAvatarStore.getState().setIsMicActive(false);
      return false;
    }
  }

  stopMicrophone() {
    if (this.micStream) {
      this.micStream.getTracks().forEach((t) => t.stop());
      this.micStream = null;
    }
    useAvatarStore.getState().setIsMicActive(false);
    useAvatarStore.getState().setUserSpeechVolume(0);
  }

  startAnalysisLoop() {
    if (this.animFrame) cancelAnimationFrame(this.animFrame);

    const micBuffer = new Uint8Array(128);
    const ttsBuffer = new Uint8Array(128);

    const loop = () => {
      // 1. Analyze Microphone if active
      if (this.micAnalyser) {
        this.micAnalyser.getByteFrequencyData(micBuffer);
        let sum = 0;
        for (let i = 0; i < micBuffer.length; i++) sum += micBuffer[i];
        const avg = sum / micBuffer.length;
        const normalized = Math.min(1, avg / 128);
        useAvatarStore.getState().setUserSpeechVolume(normalized);

        // Auto transition status if user is speaking above threshold
        if (normalized > 0.25 && useAvatarStore.getState().status === 'idle') {
          useAvatarStore.getState().setStatus('listening');
        }
      }

      // 2. Analyze TTS Audio for Lip-Sync
      if (this.ttsAnalyser) {
        this.ttsAnalyser.getByteFrequencyData(ttsBuffer);
        
        // Low frequencies (100-500 Hz): Vowel energy (jaw drop)
        let lowSum = 0;
        for (let i = 2; i < 16; i++) lowSum += ttsBuffer[i];
        const lowEnergy = Math.min(1, (lowSum / 14) / 180);

        // Mid-High frequencies (1-3 kHz): Consonants / spread
        let midSum = 0;
        for (let i = 16; i < 60; i++) midSum += ttsBuffer[i];
        const midEnergy = Math.min(1, (midSum / 44) / 160);

        const overallVolume = Math.max(lowEnergy, midEnergy);
        useAvatarStore.getState().setAssistantSpeechVolume(overallVolume);

        if (overallVolume > 0.05) {
          useAvatarStore.getState().setCurrentViseme({
            jawOpen: lowEnergy,
            mouthFunnel: midEnergy * 0.7,
            mouthSmile: Math.max(0, midEnergy - lowEnergy * 0.5),
          });
        } else {
          useAvatarStore.getState().setCurrentViseme(null);
        }
      }

      this.animFrame = requestAnimationFrame(loop);
    };

    loop();
  }

  async playAudioBuffer(arrayBuffer) {
    this.ensureContext();
    try {
      const audioBuffer = await this.audioCtx.decodeAudioData(arrayBuffer.slice(0));
      if (this.activeSource) {
        try { this.activeSource.stop(); } catch (_) {}
      }

      this.activeSource = this.audioCtx.createBufferSource();
      this.activeSource.buffer = audioBuffer;

      this.ttsAnalyser = this.audioCtx.createAnalyser();
      this.ttsAnalyser.fftSize = 256;
      this.ttsAnalyser.smoothingTimeConstant = 0.4;

      this.activeSource.connect(this.ttsAnalyser);
      this.ttsAnalyser.connect(this.audioCtx.destination);

      useAvatarStore.getState().setStatus('speaking');
      useAvatarStore.getState().setEmotion('happy');

      this.activeSource.onended = () => {
        useAvatarStore.getState().setStatus('idle');
        useAvatarStore.getState().setEmotion('neutral');
        useAvatarStore.getState().setAssistantSpeechVolume(0);
        useAvatarStore.getState().setCurrentViseme(null);
        this.activeSource = null;
        this.ttsAnalyser = null;
      };

      this.activeSource.start();
    } catch (err) {
      console.error('Error decoding/playing audio buffer:', err);
      useAvatarStore.getState().setStatus('idle');
    }
  }

  // Synthesize speech via backend API or play mock speech for testing
  async speakText(text) {
    try {
      useAvatarStore.getState().setStatus('thinking');
      useAvatarStore.getState().setEmotion('thinking');

      const response = await fetch('/api/voice/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text })
      });

      if (response.ok) {
        const arrayBuffer = await response.arrayBuffer();
        await this.playAudioBuffer(arrayBuffer);
      } else {
        // Fallback to browser SpeechSynthesis if backend audio endpoint returns non-200
        this.speakBrowserFallback(text);
      }
    } catch (err) {
      console.warn('Backend TTS failed, using browser synthesis fallback:', err);
      this.speakBrowserFallback(text);
    }
  }

  speakBrowserFallback(text) {
    if (!window.speechSynthesis) return;
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 1.05;
    utterance.pitch = 1.1;

    useAvatarStore.getState().setStatus('speaking');
    useAvatarStore.getState().setEmotion('happy');

    // Simulate viseme flutter during browser speech
    const interval = setInterval(() => {
      if (window.speechSynthesis.speaking) {
        const randVolume = 0.3 + Math.random() * 0.6;
        useAvatarStore.getState().setAssistantSpeechVolume(randVolume);
        useAvatarStore.getState().setCurrentViseme({
          jawOpen: randVolume * 0.9,
          mouthFunnel: Math.random() * 0.5,
          mouthSmile: Math.random() * 0.4,
        });
      }
    }, 80);

    utterance.onend = () => {
      clearInterval(interval);
      useAvatarStore.getState().setStatus('idle');
      useAvatarStore.getState().setEmotion('neutral');
      useAvatarStore.getState().setAssistantSpeechVolume(0);
      useAvatarStore.getState().setCurrentViseme(null);
    };

    window.speechSynthesis.speak(utterance);
  }
}

export const audioService = new AudioService();
