import React, { useRef, useEffect, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import { useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { useAvatarStore } from '../../store/avatarStore';

// Emotion blendshape profiles
const EMOTION_MAP = {
  neutral:   { mouthSmileLeft: 0.1, mouthSmileRight: 0.1 },
  happy:     { mouthSmileLeft: 0.65, mouthSmileRight: 0.65, cheekSquintLeft: 0.35, cheekSquintRight: 0.35 },
  attentive: { eyeWideLeft: 0.25, eyeWideRight: 0.25, browInnerUp: 0.15, mouthSmileLeft: 0.2, mouthSmileRight: 0.2 },
  thinking:  { browInnerUp: 0.45, eyeLookUpLeft: 0.2, eyeLookUpRight: 0.2, mouthFrownLeft: 0.1, mouthFrownRight: 0.1 },
  surprised: { jawOpen: 0.35, eyeWideLeft: 0.6, eyeWideRight: 0.6, browInnerUp: 0.5 },
  concerned: { browDownLeft: 0.3, browDownRight: 0.3, mouthFrownLeft: 0.25, mouthFrownRight: 0.25 }
};

export function HumanAvatarModel() {
  const groupRef = useRef();
  const { scene } = useGLTF('/models/avatar.glb');

  // Clone scene so materials and morph targets are independent
  const clonedScene = useMemo(() => scene.clone(true), [scene]);

  const morphMeshes = useRef([]);
  const blinkState = useRef({
    nextBlink: performance.now() + 2500,
    isBlinking: false,
    blinkStart: 0,
    blinkDuration: 180,
  });

  const saccadeState = useRef({
    nextSaccade: performance.now() + 600,
    targetX: 0,
    targetY: 0,
    currentX: 0,
    currentY: 0,
  });

  // Auto-frame, normalize scale, and remove stray Blender cubes
  useEffect(() => {
    // 1. Remove background Cube or stray export helpers
    const toRemove = [];
    clonedScene.traverse((child) => {
      if (child.name && (child.name.includes('Cube') || child.name.includes('export'))) {
        toRemove.push(child);
      }
    });
    toRemove.forEach((c) => c.parent?.remove(c));

    // 2. Compute true bounding box and auto-fit to portrait view
    const box = new THREE.Box3().setFromObject(clonedScene);
    const size = new THREE.Vector3();
    const center = new THREE.Vector3();
    box.getSize(size);
    box.getCenter(center);

    const maxDim = Math.max(size.x, size.y, size.z);
    if (maxDim > 0) {
      const targetHeight = 1.55;
      const normScale = targetHeight / maxDim;
      clonedScene.scale.set(normScale, normScale, normScale);

      // Re-center with new scale
      const scaledBox = new THREE.Box3().setFromObject(clonedScene);
      const scaledCenter = new THREE.Vector3();
      scaledBox.getCenter(scaledCenter);

      clonedScene.position.x = -scaledCenter.x;
      clonedScene.position.y = -scaledCenter.y - 0.52; // Perfectly centers head, face, and upper bust
      clonedScene.position.z = -scaledCenter.z;
    }

    // 3. Apply procedural photorealistic skin, eye, and luxury suit materials with smooth normals
    const meshes = [];
    clonedScene.traverse((child) => {
      if (child.isMesh) {
        child.castShadow = true;
        child.receiveShadow = true;

        // Ensure silky smooth organic surface curvature instead of flat faceted polygons
        if (child.geometry) {
          child.geometry.computeVertexNormals();
        }

        if (child.morphTargetDictionary) {
          meshes.push(child);
        }

        const nameLower = (child.name || '').toLowerCase();

        if (nameLower.includes('traje')) {
          // Hide outstretched horizontal T-pose arm suit geometry
          child.visible = false;
          return;
        }

        // High-end procedural shading based on anatomical mesh parts
        if (nameLower.includes('cabeza') || nameLower.includes('head') || nameLower.includes('face')) {
          // Living human facial skin: warm melanin tone with soft specular sheen
          child.material = new THREE.MeshStandardMaterial({
            color: new THREE.Color('#f0c4b2'),
            roughness: 0.48,
            metalness: 0.02,
            flatShading: false,
            envMapIntensity: 1.0,
          });
        } else if (nameLower.includes('cuerpo') || nameLower.includes('body')) {
          // Living human neck and body skin
          child.material = new THREE.MeshStandardMaterial({
            color: new THREE.Color('#ecc0ad'),
            roughness: 0.52,
            metalness: 0.02,
            flatShading: false,
            envMapIntensity: 0.9,
          });
        } else if (nameLower.includes('traje') || nameLower.includes('suit') || nameLower.includes('cloth')) {
          // Luxury dark cybernetic assistant uniform with subtle cyan trim
          child.material = new THREE.MeshStandardMaterial({
            color: new THREE.Color('#141724'),
            roughness: 0.32,
            metalness: 0.28,
            flatShading: false,
            envMapIntensity: 1.2,
          });
        } else if (nameLower.includes('eye') || nameLower.includes('cornea')) {
          // Glistening wet cornea
          child.material = new THREE.MeshStandardMaterial({
            color: new THREE.Color('#2b6cb0'),
            roughness: 0.05,
            metalness: 0.0,
            flatShading: false,
            envMapIntensity: 2.0,
          });
        } else {
          // Hair or remaining accessories
          child.material = new THREE.MeshStandardMaterial({
            color: new THREE.Color('#2d3748'),
            roughness: 0.65,
            metalness: 0.1,
            flatShading: false,
          });
        }
      }
    });
    morphMeshes.current = meshes;
  }, [clonedScene]);

  useFrame((state, delta) => {
    const now = performance.now();
    const time = state.clock.getElapsedTime();
    const pointer = state.pointer; // [-1, 1] normalized mouse position

    const { status, emotion, currentViseme } = useAvatarStore.getState();

    // ──────────────────────────────────────────────────────────
    // 1. BIOLOGICAL BREATHING CYCLE
    // ──────────────────────────────────────────────────────────
    if (groupRef.current) {
      const breathFreq = status === 'thinking' ? 1.2 : 1.5;
      const breathSin = Math.sin(time * breathFreq);
      groupRef.current.position.y = 0.05 + breathSin * 0.008;
      groupRef.current.rotation.x = breathSin * 0.006; // subtle chest pitch
    }

    // ──────────────────────────────────────────────────────────
    // 2. SMOOTH CURSOR GAZE & HEAD TRACKING
    // ──────────────────────────────────────────────────────────
    if (groupRef.current) {
      const targetYaw = THREE.MathUtils.clamp(pointer.x * 0.22, -0.28, 0.28);
      const targetPitch = THREE.MathUtils.clamp(-pointer.y * 0.14, -0.2, 0.18);
      const targetRoll = pointer.x * -0.05;

      // Attentive slight tilt when listening
      const listeningTilt = status === 'listening' ? 0.06 : 0;

      groupRef.current.rotation.y = THREE.MathUtils.lerp(groupRef.current.rotation.y, targetYaw, delta * 4);
      groupRef.current.rotation.x = THREE.MathUtils.lerp(groupRef.current.rotation.x, targetPitch, delta * 4);
      groupRef.current.rotation.z = THREE.MathUtils.lerp(groupRef.current.rotation.z, targetRoll + listeningTilt, delta * 3);
    }

    // ──────────────────────────────────────────────────────────
    // 3. ORGANIC ASYMMETRIC EYE BLINKING
    // ──────────────────────────────────────────────────────────
    let blinkWeight = 0;
    const b = blinkState.current;
    if (!b.isBlinking && now >= b.nextBlink) {
      b.isBlinking = true;
      b.blinkStart = now;
      b.blinkDuration = 160 + Math.random() * 60;
    }

    if (b.isBlinking) {
      const elapsed = now - b.blinkStart;
      const progress = elapsed / b.blinkDuration;
      if (progress >= 1.0) {
        b.isBlinking = false;
        b.nextBlink = now + 2000 + Math.random() * 3200; // Random interval between 2.0s and 5.2s
      } else {
        // Asymmetric blink: 35% time fast snap shut, 65% time natural release
        if (progress < 0.35) {
          blinkWeight = Math.sin((progress / 0.35) * (Math.PI / 2));
        } else {
          blinkWeight = Math.cos(((progress - 0.35) / 0.65) * (Math.PI / 2));
        }
      }
    }

    // ──────────────────────────────────────────────────────────
    // 4. OCULAR MICRO-SACCADES (Living Eye Jitters)
    // ──────────────────────────────────────────────────────────
    const s = saccadeState.current;
    if (now >= s.nextSaccade) {
      s.nextSaccade = now + 400 + Math.random() * 1200;
      s.targetX = (Math.random() - 0.5) * 0.06;
      s.targetY = (Math.random() - 0.5) * 0.04;
    }
    s.currentX = THREE.MathUtils.lerp(s.currentX, s.targetX, delta * 12);
    s.currentY = THREE.MathUtils.lerp(s.currentY, s.targetY, delta * 12);

    // ──────────────────────────────────────────────────────────
    // 5. BLENDSHAPE APPLICATION (Lip-Sync + Emotion + Gaze)
    // ──────────────────────────────────────────────────────────
    const activeEmotionPresets = EMOTION_MAP[emotion] || EMOTION_MAP.neutral;

    morphMeshes.current.forEach((mesh) => {
      const dict = mesh.morphTargetDictionary;
      const influences = mesh.morphTargetInfluences;
      if (!dict || !influences) return;

      const setMorph = (name, targetValue, speed = 10) => {
        if (name in dict) {
          const idx = dict[name];
          const cur = influences[idx] || 0;
          influences[idx] = THREE.MathUtils.lerp(cur, targetValue, delta * speed);
        }
      };

      // Blinks
      setMorph('eyeBlinkLeft', blinkWeight, 25);
      setMorph('eyeBlinkRight', blinkWeight, 25);

      // Saccades
      setMorph('eyeLookInLeft', Math.max(0, s.currentX), 15);
      setMorph('eyeLookOutLeft', Math.max(0, -s.currentX), 15);
      setMorph('eyeLookUpLeft', Math.max(0, s.currentY), 15);
      setMorph('eyeLookDownLeft', Math.max(0, -s.currentY), 15);

      setMorph('eyeLookInRight', Math.max(0, -s.currentX), 15);
      setMorph('eyeLookOutRight', Math.max(0, s.currentX), 15);
      setMorph('eyeLookUpRight', Math.max(0, s.currentY), 15);
      setMorph('eyeLookDownRight', Math.max(0, -s.currentY), 15);

      // Emotion Presets
      Object.entries(activeEmotionPresets).forEach(([morphName, val]) => {
        setMorph(morphName, val, 6);
      });

      // Real-time Audio Visemes (Lip-Sync)
      if (currentViseme) {
        setMorph('jawOpen', currentViseme.jawOpen || 0, 24);
        setMorph('mouthOpen', (currentViseme.jawOpen || 0) * 0.8, 24);
        setMorph('mouthFunnel', currentViseme.mouthFunnel || 0, 20);
        setMorph('mouthSmileLeft', Math.max(activeEmotionPresets.mouthSmileLeft || 0, currentViseme.mouthSmile || 0), 16);
        setMorph('mouthSmileRight', Math.max(activeEmotionPresets.mouthSmileRight || 0, currentViseme.mouthSmile || 0), 16);
      } else {
        // Return lips to rest
        setMorph('jawOpen', 0, 14);
        setMorph('mouthOpen', 0, 14);
        setMorph('mouthFunnel', 0, 14);
      }
    });
  });

  return (
    <group ref={groupRef} position={[0, 0.05, 0]} scale={1.2}>
      <primitive object={clonedScene} />
    </group>
  );
}

useGLTF.preload('/models/avatar.glb');
