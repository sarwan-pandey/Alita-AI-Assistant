// components/hologram/HologramAvatar.jsx
//
// BRIDGE COMPONENT — translates AURA's isListening / isThinking / isSpeaking
// / emotion props into the AnimationData format expected by HologramScene.
//
// ──────────────────────────────────────────────────────
// TO REVERT TO AnimeAvatar: in App.jsx, simply swap:
//   import { HologramAvatar } from "./components/hologram/HologramAvatar";
//   <HologramAvatar ... />
// back to:
//   import { AnimeAvatar } from "./components/ui/AnimeAvatar";
//   <AnimeAvatar ... />
// ──────────────────────────────────────────────────────

import { useMemo, Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { HologramScene } from './HologramScene';

// Map AURA state → body animation clip name
function getBodyAnim(isListening, isThinking, isSpeaking) {
    if (isSpeaking)  return 'talking';
    if (isListening) return 'listening';
    if (isThinking)  return 'thinking';
    return 'idle';
}

// Map emotion string → rough facial blendshape weights
// (these are additive to the emotion presets inside AvatarModel)
function emotionToFacial(emotion) {
    const map = {
        happy:     { mouthSmileLeft: 0.8, mouthSmileRight: 0.8 },
        sad:       { mouthFrownLeft: 0.6, mouthFrownRight: 0.6 },
        angry:     { browDownLeft: 0.7, browDownRight: 0.7 },
        surprised: { jawOpen: 0.4, eyeWideLeft: 0.7, eyeWideRight: 0.7 },
        excited:   { mouthSmileLeft: 1.0, mouthSmileRight: 1.0 },
        neutral:   {},
    };
    return map[emotion] || {};
}

// Fallback shown while the 3D model is loading
function HologramFallback() {
    return (
        <div style={{
            width: '100%', height: '100%',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            flexDirection: 'column', gap: '12px',
            color: 'rgba(0,212,255,0.6)', fontFamily: "'Inter', sans-serif",
            fontSize: '0.75rem', letterSpacing: '0.15em',
        }}>
            <div style={{
                width: 60, height: 60, borderRadius: '50%',
                border: '2px solid rgba(0,212,255,0.3)',
                borderTopColor: '#00d4ff',
                animation: 'spin 1s linear infinite',
            }} />
            <span>LOADING HOLOGRAM...</span>
            <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
        </div>
    );
}

export function HologramAvatar({ isListening, isThinking, isSpeaking, emotion = 'neutral' }) {
    // Build AnimationData from AURA state on every change
    const animationData = useMemo(() => ({
        facial:   emotionToFacial(emotion),
        lipsync:  [],          // will be populated if/when AURA sends viseme data
        body:     getBodyAnim(isListening, isThinking, isSpeaking),
        emotion:  emotion,
        duration: 1,
    }), [isListening, isThinking, isSpeaking, emotion]);

    return (
        <div
            id="hologram-avatar"
            style={{ width: '100%', height: '100%', position: 'relative' }}
        >
            {/* Loading overlay */}
            <Suspense fallback={<HologramFallback />}>
                {/* State label — matches AURA's existing status text style */}
                <div style={{
                    position: 'absolute', top: 8, left: '50%', transform: 'translateX(-50%)',
                    zIndex: 10, fontSize: '0.6rem', letterSpacing: '0.2em',
                    textTransform: 'uppercase', fontFamily: "'Inter', sans-serif",
                    color: isSpeaking
                        ? 'rgba(245,166,35,0.8)'
                        : isListening
                            ? 'rgba(0,212,255,0.8)'
                            : isThinking
                                ? 'rgba(168,85,247,0.8)'
                                : 'rgba(0,212,255,0.3)',
                    transition: 'color 400ms ease',
                    pointerEvents: 'none',
                }}>
                    {isSpeaking ? '◉ speaking' : isListening ? '◉ listening' : isThinking ? '◉ thinking' : '○ idle'}
                </div>

                <Canvas
                    camera={{ position: [0, 1.2, 2.5], fov: 45 }}
                    gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
                    style={{ background: 'transparent' }}
                    shadows
                >
                    <HologramScene animationData={animationData} />
                </Canvas>
            </Suspense>
        </div>
    );
}
