import React, { Suspense, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { ContactShadows } from '@react-three/drei';
import * as THREE from 'three';
import { HumanAvatarModel } from './HumanAvatarModel';
import { useAvatarStore } from '../../store/avatarStore';

function CameraRig() {
  const cameraMode = useAvatarStore((state) => state.cameraMode);

  useFrame((state, delta) => {
    // Smooth camera framing transition: close portrait vs bust view
    const targetZ = cameraMode === 'close' ? 0.92 : 1.35;
    const targetY = cameraMode === 'close' ? 0.16 : 0.08;

    state.camera.position.z = THREE.MathUtils.lerp(state.camera.position.z, targetZ, delta * 3);
    state.camera.position.y = THREE.MathUtils.lerp(state.camera.position.y, targetY, delta * 3);
  });

  return null;
}

export function HumanAvatarScene() {
  return (
    <Canvas
      camera={{ position: [0, 0.16, 0.92], fov: 32 }}
      gl={{
        antialias: true,
        toneMapping: THREE.ACESFilmicToneMapping,
        toneMappingExposure: 1.15,
        powerPreference: 'high-performance',
      }}
      style={{ width: '100%', height: '100%' }}
    >
      <CameraRig />

      {/* ── Studio Lighting for Photorealism ── */}
      {/* 1. Ambient Fill */}
      <ambientLight intensity={0.6} color="#2d3748" />

      {/* 2. Key Light (Soft Warm Studio Key) */}
      <directionalLight
        position={[2.0, 3.0, 2.5]}
        intensity={1.6}
        color="#fff5ea"
        castShadow
      />

      {/* 3. Soft Facial Fill & Eye Catchlight */}
      <pointLight
        position={[0, 0.25, 0.85]}
        intensity={0.9}
        color="#fff8f0"
        distance={2.5}
      />

      {/* 4. Cool Soft Fill */}
      <directionalLight
        position={[-2.5, 1.5, 1.5]}
        intensity={0.8}
        color="#dce7f5"
      />

      {/* 5. Rim / Hair Accent Lights */}
      <spotLight
        position={[-1.8, 2.2, -1.5]}
        intensity={2.0}
        color="#9f7aea"
        angle={0.65}
        penumbra={0.8}
      />
      <spotLight
        position={[1.8, 2.0, -1.5]}
        intensity={1.6}
        color="#63b3ed"
        angle={0.65}
        penumbra={0.8}
      />

      {/* ── Ground Soft Contact Shadows ── */}
      <ContactShadows
        position={[0, -0.85, 0]}
        opacity={0.65}
        scale={4}
        blur={2.2}
        color="#08090f"
      />

      {/* ── 3D Human Avatar Model ── */}
      <Suspense fallback={null}>
        <HumanAvatarModel />
      </Suspense>
    </Canvas>
  );
}
