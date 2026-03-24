// components/hologram/ParticleEffects.jsx
// Emotion-driven particle system — colour/speed/pattern change per emotion
import { useRef, useMemo, useEffect } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

const EMOTION_CONFIGS = {
    neutral:  { color: '#4488ff', speed: 0.3, spread: 1.5, size: 0.02,  pattern: 'float'   },
    happy:    { color: '#ffaa00', speed: 0.6, spread: 2.0, size: 0.025, pattern: 'sparkle' },
    sad:      { color: '#4466aa', speed: 0.15,spread: 1.0, size: 0.015, pattern: 'rain'    },
    loving:   { color: '#ff4488', speed: 0.4, spread: 1.8, size: 0.03,  pattern: 'hearts'  },
    excited:  { color: '#ffdd00', speed: 1.0, spread: 2.5, size: 0.03,  pattern: 'burst'   },
    shy:      { color: '#ff88aa', speed: 0.2, spread: 0.8, size: 0.015, pattern: 'gentle'  },
    flirty:   { color: '#ff66cc', speed: 0.5, spread: 1.5, size: 0.025, pattern: 'spiral'  },
    playful:  { color: '#88ff88', speed: 0.7, spread: 2.0, size: 0.025, pattern: 'bounce'  },
    angry:    { color: '#ff2200', speed: 0.8, spread: 1.5, size: 0.02,  pattern: 'sharp'   },
    caring:   { color: '#88ccff', speed: 0.3, spread: 1.2, size: 0.02,  pattern: 'gentle'  },
};

export function ParticleSystem({ count = 200, emotion = 'neutral' }) {
    const pointsRef = useRef(null);
    const config = EMOTION_CONFIGS[emotion] || EMOTION_CONFIGS.neutral;

    const { positions, velocities, lifetimes } = useMemo(() => {
        const pos  = new Float32Array(count * 3);
        const vel  = new Float32Array(count * 3);
        const life = new Float32Array(count);

        for (let i = 0; i < count; i++) {
            const i3 = i * 3;
            pos[i3]     = (Math.random() - 0.5) * config.spread;
            pos[i3 + 1] = Math.random() * 2.5;
            pos[i3 + 2] = (Math.random() - 0.5) * config.spread;

            vel[i3]     = (Math.random() - 0.5) * 0.01;
            vel[i3 + 1] = Math.random() * 0.01 + 0.005;
            vel[i3 + 2] = (Math.random() - 0.5) * 0.01;

            life[i] = Math.random();
        }
        return { positions: pos, velocities: vel, lifetimes: life };
    }, [count, config.spread]);

    // Update colour when emotion changes
    useEffect(() => {
        if (pointsRef.current) {
            pointsRef.current.material.color.set(config.color);
            pointsRef.current.material.size = config.size;
        }
    }, [emotion, config]);

    useFrame(({ clock }) => {
        if (!pointsRef.current) return;

        const geo     = pointsRef.current.geometry;
        const posArr  = geo.attributes.position.array;
        const time    = clock.getElapsedTime();

        for (let i = 0; i < count; i++) {
            const i3 = i * 3;
            lifetimes[i] += 0.002 * config.speed;

            if (lifetimes[i] > 1) {
                lifetimes[i]    = 0;
                posArr[i3]      = (Math.random() - 0.5) * config.spread;
                posArr[i3 + 1]  = -0.1;
                posArr[i3 + 2]  = (Math.random() - 0.5) * config.spread;
            }

            switch (config.pattern) {
                case 'float':
                    posArr[i3]     += Math.sin(time + i) * 0.001;
                    posArr[i3 + 1] += velocities[i3 + 1] * config.speed;
                    posArr[i3 + 2] += Math.cos(time + i) * 0.001;
                    break;
                case 'sparkle':
                    posArr[i3]     += Math.sin(time * 3 + i * 0.5) * 0.003;
                    posArr[i3 + 1] += velocities[i3 + 1] * config.speed * 1.5;
                    posArr[i3 + 2] += Math.cos(time * 3 + i * 0.5) * 0.003;
                    break;
                case 'spiral': {
                    const angle  = time + i * 0.1;
                    const radius = 0.5 + lifetimes[i] * 0.5;
                    posArr[i3]      = Math.cos(angle) * radius;
                    posArr[i3 + 1] += velocities[i3 + 1] * config.speed;
                    posArr[i3 + 2]  = Math.sin(angle) * radius;
                    break;
                }
                case 'rain':
                    posArr[i3 + 1] -= 0.01 * config.speed;
                    if (posArr[i3 + 1] < -0.1) posArr[i3 + 1] = 2.5;
                    break;
                default:
                    posArr[i3 + 1] += velocities[i3 + 1] * config.speed;
            }
        }

        geo.attributes.position.needsUpdate = true;
    });

    return (
        <points ref={pointsRef}>
            <bufferGeometry>
                <bufferAttribute
                    attach="attributes-position"
                    count={count}
                    array={positions}
                    itemSize={3}
                />
            </bufferGeometry>
            <pointsMaterial
                color={config.color}
                size={config.size}
                transparent
                opacity={0.6}
                blending={THREE.AdditiveBlending}
                depthWrite={false}
                sizeAttenuation
            />
        </points>
    );
}
