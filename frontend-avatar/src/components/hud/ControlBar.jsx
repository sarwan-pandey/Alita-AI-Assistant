import React, { useState } from 'react';
import { useAvatarStore } from '../../store/avatarStore';
import { audioService } from '../../services/audioService';
import { wsService } from '../../services/websocket';
import { Mic, MicOff, Volume2, VolumeX, Camera, Send, Smile } from 'lucide-react';

export function ControlBar() {
  const [inputText, setInputText] = useState('');
  const isMicActive = useAvatarStore((state) => state.isMicActive);
  const isMuted = useAvatarStore((state) => state.isMuted);
  const cameraMode = useAvatarStore((state) => state.cameraMode);
  const status = useAvatarStore((state) => state.status);
  const setCameraMode = useAvatarStore((state) => state.setCameraMode);
  const setIsMuted = useAvatarStore((state) => state.setIsMuted);
  const setEmotion = useAvatarStore((state) => state.setEmotion);

  const toggleMic = async () => {
    if (isMicActive) {
      audioService.stopMicrophone();
    } else {
      await audioService.startMicrophone();
    }
  };

  const toggleMute = () => {
    setIsMuted(!isMuted);
  };

  const toggleCamera = () => {
    setCameraMode(cameraMode === 'close' ? 'bust' : 'close');
  };

  const handleSend = (e) => {
    e.preventDefault();
    if (!inputText.trim()) return;

    wsService.sendMessage(inputText);
    setInputText('');
  };

  const cycleEmotion = () => {
    const emotions = ['neutral', 'happy', 'attentive', 'thinking', 'concerned'];
    const current = useAvatarStore.getState().emotion;
    const next = emotions[(emotions.indexOf(current) + 1) % emotions.length];
    setEmotion(next);
  };

  const testVoice = () => {
    const phrases = [
      "Hello! I am your real-time 3D living assistant. My mouth and eyes move naturally with my voice!",
      "I am monitoring your system diagnostics and ready to assist you whenever needed.",
      "Notice how my eyes blink and track your cursor smoothly while I speak."
    ];
    const phrase = phrases[Math.floor(Math.random() * phrases.length)];
    useAvatarStore.getState().setAssistantResponse(phrase);
    audioService.speakText(phrase);
  };

  return (
    <div className="dock-wrapper">
      <div className="glass-panel control-bar interactive">
        {/* Mic Toggle Button */}
        <button
          onClick={toggleMic}
          className={`control-btn ${isMicActive ? 'active' : ''} ${status === 'speaking' ? 'speaking' : ''}`}
          title={isMicActive ? 'Mute Microphone' : 'Start Voice Input'}
        >
          {isMicActive ? <Mic size={20} /> : <MicOff size={20} />}
        </button>

        {/* Text Input */}
        <form onSubmit={handleSend} style={{ display: 'flex', flex: 1, gap: '0.5rem', alignItems: 'center' }}>
          <input
            type="text"
            className="text-input-field"
            placeholder="Type a message or speak..."
            value={inputText}
            onChange={(e) => setInputText(e.target.value)}
          />
          <button
            type="submit"
            className="control-btn"
            style={{ width: '38px', height: '38px' }}
            title="Send Message"
          >
            <Send size={16} />
          </button>
        </form>

        {/* Test Speech Quick Button */}
        <button
          onClick={testVoice}
          className="control-btn"
          title="Test Living Speech & Lip-Sync"
          style={{ width: '38px', height: '38px' }}
        >
          <Smile size={18} />
        </button>

        {/* Camera Mode Toggle */}
        <button
          onClick={toggleCamera}
          className={`control-btn ${cameraMode === 'bust' ? 'active' : ''}`}
          title={`Camera View: ${cameraMode === 'close' ? 'Portrait' : 'Full Bust'}`}
          style={{ width: '38px', height: '38px' }}
        >
          <Camera size={18} />
        </button>

        {/* Speaker Mute */}
        <button
          onClick={toggleMute}
          className="control-btn"
          title={isMuted ? 'Unmute Audio' : 'Mute Audio'}
          style={{ width: '38px', height: '38px' }}
        >
          {isMuted ? <VolumeX size={18} /> : <Volume2 size={18} />}
        </button>
      </div>
    </div>
  );
}
