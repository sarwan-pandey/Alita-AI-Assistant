import React from 'react';
import { useAvatarStore } from '../../store/avatarStore';
import { Sparkles, Brain, Volume2, Mic } from 'lucide-react';

export function AssistantStatusCard() {
  const status = useAvatarStore((state) => state.status);
  const latencyMs = useAvatarStore((state) => state.latencyMs);

  const config = {
    idle: {
      label: 'STANDBY',
      color: '#a0aec0',
      glow: 'rgba(160, 174, 192, 0.2)',
      icon: Sparkles,
      dashOffset: 120,
    },
    listening: {
      label: 'LISTENING',
      color: '#63b3ed',
      glow: 'rgba(99, 179, 237, 0.4)',
      icon: Mic,
      dashOffset: 60,
    },
    thinking: {
      label: 'THINKING',
      color: '#f6ad55',
      glow: 'rgba(246, 173, 85, 0.4)',
      icon: Brain,
      dashOffset: 20,
    },
    speaking: {
      label: 'SPEAKING',
      color: '#b794f4',
      glow: 'rgba(183, 148, 244, 0.5)',
      icon: Volume2,
      dashOffset: 0,
    },
  }[status] || {
    label: 'STANDBY',
    color: '#a0aec0',
    glow: 'rgba(160, 174, 192, 0.2)',
    icon: Sparkles,
    dashOffset: 120,
  };

  const Icon = config.icon;

  return (
    <div className="glass-panel interactive" style={{ padding: '1.25rem 1.5rem', width: '220px' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '0.75rem' }}>
        <span style={{ fontSize: '0.75rem', fontWeight: 600, letterSpacing: '0.08em', color: 'var(--text-secondary)', textTransform: 'uppercase' }}>
          Assistant Status
        </span>
        <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>{latencyMs}ms</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', position: 'relative', margin: '0.5rem 0' }}>
        {/* Glowing Radial SVG Ring */}
        <svg width="84" height="84" viewBox="0 0 100 100" style={{ transform: 'rotate(-90deg)' }}>
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="transparent"
            stroke="rgba(255, 255, 255, 0.08)"
            strokeWidth="6"
          />
          <circle
            cx="50"
            cy="50"
            r="40"
            fill="transparent"
            stroke={config.color}
            strokeWidth="6"
            strokeDasharray="251.2"
            strokeDashoffset={config.dashOffset}
            strokeLinecap="round"
            style={{
              transition: 'all 0.5s ease',
              filter: `drop-shadow(0 0 6px ${config.color})`,
            }}
          />
        </svg>

        {/* Center Icon */}
        <div
          style={{
            position: 'absolute',
            top: '50%',
            left: '50%',
            transform: 'translate(-50%, -50%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '42px',
            height: '42px',
            borderRadius: '50%',
            background: 'rgba(0, 0, 0, 0.3)',
            boxShadow: `0 0 16px ${config.glow}`,
          }}
        >
          <Icon size={20} color={config.color} />
        </div>
      </div>

      <div style={{ textAlign: 'center', marginTop: '0.5rem' }}>
        <span
          style={{
            fontFamily: 'var(--font-heading)',
            fontSize: '0.85rem',
            fontWeight: 700,
            letterSpacing: '0.1em',
            color: config.color,
            textShadow: `0 0 12px ${config.glow}`,
          }}
        >
          {config.label}
        </span>
      </div>
    </div>
  );
}
