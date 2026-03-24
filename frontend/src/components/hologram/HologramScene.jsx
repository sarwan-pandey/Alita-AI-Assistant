// components/hologram/HologramScene.jsx
// Assembles the full 3D holographic scene: avatar + effects + particles
import { useRef } from 'react';
import { Float, ContactShadows, Environment } from '@react-three/drei';
import * as THREE from 'three';
import { AvatarModel } from './AvatarModel';
import { HologramEffects } from './HologramEffects';
import { ParticleSystem } from './ParticleEffects';

export function HologramScene({ animationData }) {
    const groupRef = useRef(null);

    return (
        <>
            {/* ── Lighting ── */}
            <ambientLight intensity={0.3} color="#8888ff" />
            <directionalLight position={[5, 5, 5]} intensity={0.5} color="#ffffff" castShadow />
            <pointLight position={[0, 0, 2]} intensity={0.8} color="#00aaff" distance={5} />
            <spotLight
                position={[0, 3, 0]}
                angle={0.4}
                penumbra={0.5}
                intensity={1}
                color="#4488ff"
                castShadow
            />

            {/* ── Holographic base plate ── */}
            <mesh position={[0, -0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
                <circleGeometry args={[0.8, 64]} />
                <meshBasicMaterial color="#0066ff" transparent opacity={0.3} />
            </mesh>

            {/* ── Floating avatar ── */}
            <Float speed={1.5} rotationIntensity={0.1} floatIntensity={0.2} floatingRange={[0, 0.05]}>
                <group ref={groupRef}>
                    <AvatarModel animationData={animationData} />
                </group>
            </Float>

            {/* ── Hologram FX (scanlines, rings, glow) ── */}
            <HologramEffects />

            {/* ── Ambient particle system (emotion-driven) ── */}
            <ParticleSystem count={200} emotion={animationData?.emotion || 'neutral'} />

            {/* ── Ground shadow ── */}
            <ContactShadows
                position={[0, -0.01, 0]}
                opacity={0.4}
                scale={3}
                blur={2}
                color="#0044ff"
            />

            {/* ── Environment for subtle reflections ── */}
            <Environment preset="night" />
        </>
    );
}
