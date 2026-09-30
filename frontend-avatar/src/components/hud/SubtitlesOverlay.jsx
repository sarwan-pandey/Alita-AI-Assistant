import React from 'react';
import { useAvatarStore } from '../../store/avatarStore';

export function SubtitlesOverlay() {
  const status = useAvatarStore((state) => state.status);
  const transcription = useAvatarStore((state) => state.transcription);
  const assistantResponse = useAvatarStore((state) => state.assistantResponse);

  const displayText = status === 'listening' && transcription
    ? `"${transcription}"`
    : assistantResponse;

  if (!displayText) return null;

  return (
    <div className="glass-panel subtitles-box interactive">
      <p className="subtitles-text">
        {displayText}
      </p>
    </div>
  );
}
