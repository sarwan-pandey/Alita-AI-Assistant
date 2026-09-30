import React, { useMemo } from 'react';
import { useAvatarStore } from '../../store/avatarStore';
import { Activity } from 'lucide-react';

export function VoiceActivityCard() {
  const userSpeechVolume = useAvatarStore((state) => state.userSpeechVolume);
  const assistantSpeechVolume = useAvatarStore((state) => state.assistantSpeechVolume);
  const status = useAvatarStore((state) => state.status);

  const activeVolume = Math.max(userSpeechVolume, assistantSpeechVolume);

  // Generate 18 dynamic equalizer bars with procedural heights
  const bars = useMemo(() => Array.from({ length: 18 }), []);

  const isSpeaking = status === 'speaking';
  const isListening = status === 'listening';

  return (
    <div className="glass-panel interactive" style={{ padding: '1.25rem 1.5rem', width: '220px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '1rem' }}>
        <span style={{ fontSize: '0.75rem', fontWeight: 600, letterSpacing: '0.08em', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
          Voice Activity
        </span>
        <Activity size={14} color={isSpeaking ? '#b794f4' : isListening ? '#63b3ed' : '#718096'} />
      </div>

      {/* Dynamic Equalizer Spectrum */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '48px', gap: '3px' }}>
        {bars.map((_, i) => {
          // Bell curve distribution factor from center
          const distFromCenter = Math.abs(i - 8.5) / 8.5;
          const curveFactor = Math.cos(distFromCenter * (Math.PI / 2.2));

          // Base noise + audio driven height
          const minHeight = 12;
          const maxHeight = 46;
          const height = activeVolume > 0.02
            ? minHeight + (maxHeight - minHeight) * curveFactor * activeVolume * (0.6 + ((i * 17) % 10) / 20)
            : minHeight;

          const barColor = isSpeaking
            ? 'linear-gradient(180deg, #b794f4 0%, #805ad5 100%)'
            : isListening
            ? 'linear-gradient(180deg, #63b3ed 0%, #3182ce 100%)'
            : 'rgba(255, 255, 255, 0.15)';

          return (
            <div
              key={i}
              style={{
                flex: 1,
                height: `${height}px`,
                background: barColor,
                borderRadius: '999px',
                transition: 'height 0.08s ease, background 0.3s ease',
                boxShadow: activeVolume > 0.1 ? (isSpeaking ? '0 0 8px rgba(183, 148, 244, 0.4)' : '0 0 8px rgba(99, 179, 237, 0.4)') : 'none',
              }}
            />
          );
        })}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: '0.75rem', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
        <span>{isSpeaking ? 'Alita Output' : isListening ? 'User Input' : 'Silent'}</span>
        <span>{Math.round(activeVolume * 100)}%</span>
      </div>
    </div>
  );
}
