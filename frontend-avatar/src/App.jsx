import React, { useEffect, useState } from 'react';
import { HumanAvatarScene } from './components/avatar/HumanAvatarScene';
import { VoiceActivityCard } from './components/hud/VoiceActivityCard';
import { AssistantStatusCard } from './components/hud/AssistantStatusCard';
import { SubtitlesOverlay } from './components/hud/SubtitlesOverlay';
import { ControlBar } from './components/hud/ControlBar';
import { wsService } from './services/websocket';
import { useAvatarStore } from './store/avatarStore';
import { Radio } from 'lucide-react';

export function App() {
  const isConnected = useAvatarStore((state) => state.isConnected);
  const [timeStr, setTimeStr] = useState('');

  useEffect(() => {
    // Connect to Alita backend WebSocket
    wsService.connect();

    // Clock ticker
    const updateTime = () => {
      const d = new Date();
      setTimeStr(d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    };
    updateTime();
    const timer = setInterval(updateTime, 1000);
    return () => clearInterval(timer);
  }, []);

  return (
    <div className="app-container">
      {/* ── Layer 1: 3D Living Human Canvas ── */}
      <div className="canvas-wrapper">
        <HumanAvatarScene />
      </div>

      {/* ── Layer 2: Luxury Glassmorphic HUD ── */}
      <div className="ui-overlay">
        {/* Top Header */}
        <header className="top-nav">
          <div className="glass-panel brand-badge interactive">
            <div className="logo-dot" />
            <span className="brand-title">Alita AI • 3D Human</span>
          </div>

          <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
            <div
              className="glass-panel interactive"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.5rem',
                padding: '0.45rem 0.9rem',
                borderRadius: '9999px',
                fontSize: '0.75rem',
                color: isConnected ? 'var(--color-emerald)' : 'var(--text-muted)',
              }}
            >
              <Radio size={14} />
              <span>{isConnected ? 'Backend Online' : 'Local Standby'}</span>
            </div>

            <div
              className="glass-panel"
              style={{
                padding: '0.45rem 0.9rem',
                borderRadius: '9999px',
                fontSize: '0.75rem',
                color: 'var(--text-secondary)',
                fontWeight: 500,
              }}
            >
              {timeStr}
            </div>
          </div>
        </header>

        {/* Side HUD Cards */}
        <div className="side-cards-container">
          <VoiceActivityCard />
          <AssistantStatusCard />
        </div>

        {/* Bottom Conversation & Control Dock */}
        <footer style={{ display: 'flex', flexDirection: 'column', gap: '1rem', alignItems: 'center', width: '100%' }}>
          <SubtitlesOverlay />
          <ControlBar />
        </footer>
      </div>
    </div>
  );
}

export default App;
