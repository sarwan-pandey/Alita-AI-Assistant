import { create } from 'zustand';

export const useAvatarStore = create((set) => ({
  status: 'idle', // 'idle' | 'listening' | 'thinking' | 'speaking'
  emotion: 'neutral',
  userSpeechVolume: 0,
  assistantSpeechVolume: 0,
  currentViseme: null,
  transcription: '',
  assistantResponse: 'Hello! I am Alita. How can I assist you today?',
  isMicActive: false,
  isMuted: false,
  cameraMode: 'close', // 'close' | 'bust'
  latencyMs: 145,
  isConnected: false,

  setStatus: (status) => set({ status }),
  setEmotion: (emotion) => set({ emotion }),
  setUserSpeechVolume: (userSpeechVolume) => set({ userSpeechVolume }),
  setAssistantSpeechVolume: (assistantSpeechVolume) => set({ assistantSpeechVolume }),
  setCurrentViseme: (currentViseme) => set({ currentViseme }),
  setTranscription: (transcription) => set({ transcription }),
  setAssistantResponse: (assistantResponse) => set({ assistantResponse }),
  setIsMicActive: (isMicActive) => set({ isMicActive }),
  setIsMuted: (isMuted) => set({ isMuted }),
  setCameraMode: (cameraMode) => set({ cameraMode }),
  setLatencyMs: (latencyMs) => set({ latencyMs }),
  setIsConnected: (isConnected) => set({ isConnected }),
}));
