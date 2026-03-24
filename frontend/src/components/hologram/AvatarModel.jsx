// components/hologram/AvatarModel.jsx
// 3D avatar loader with blendshape/morph-target support and real-time lip-sync.
// Requires avatar.glb in /public/models/avatar.glb
import { useRef, useEffect, useMemo, Suspense } from 'react';
import { useFrame } from '@react-three/fiber';
import { useGLTF, useAnimations } from '@react-three/drei';
import * as THREE from 'three';
import { useLipSync } from '../../hooks/useLipSync';

// ARKit viseme → blendshape mapping
const VISEME_MAP = {
    aa:  ['mouthOpen', 'jawOpen'],
    E:   ['mouthSmileLeft', 'mouthSmileRight'],
    I:   ['mouthSmileLeft', 'mouthSmileRight', 'mouthStretchLeft'],
    O:   ['mouthFunnel', 'mouthPucker'],
    U:   ['mouthPucker', 'mouthFunnel'],
    PP:  ['mouthPressLeft', 'mouthPressRight', 'mouthClose'],
    FF:  ['mouthFunnel', 'mouthUpperUpLeft'],
    TH:  ['tongueOut', 'jawOpen'],
    DD:  ['jawOpen', 'mouthClose'],
    SS:  ['mouthSmileLeft', 'mouthSmileRight', 'mouthStretchLeft'],
    CH:  ['mouthShrugUpper', 'mouthFunnel'],
    RR:  ['mouthRollLower', 'mouthPucker'],
    nn:  ['mouthClose', 'jawOpen'],
    kk:  ['jawOpen', 'mouthOpen'],
    sil: [],
};

// Emotion → blendshape preset
const EMOTION_BLENDSHAPES = {
    neutral:  {},
    happy:    { mouthSmileLeft: 0.8, mouthSmileRight: 0.8, cheekSquintLeft: 0.3, cheekSquintRight: 0.3 },
    sad:      { mouthFrownLeft: 0.7, mouthFrownRight: 0.7, browInnerUp: 0.5 },
    angry:    { browDownLeft: 0.8, browDownRight: 0.8, noseSneerLeft: 0.4, noseSneerRight: 0.4 },
    surprised:{ jawOpen: 0.5, eyeWideLeft: 0.8, eyeWideRight: 0.8, browInnerUp: 0.7 },
    excited:  { mouthSmileLeft: 1.0, mouthSmileRight: 1.0, eyeWideLeft: 0.5, eyeWideRight: 0.5 },
    loving:   { mouthSmileLeft: 0.6, mouthSmileRight: 0.6, cheekPuff: 0.3 },
    thinking: { browInnerUp: 0.3, eyeLookUpLeft: 0.2, eyeLookUpRight: 0.2 },
    shy:      { mouthSmileLeft: 0.4, mouthSmileRight: 0.4, cheekSquintLeft: 0.5, cheekSquintRight: 0.5 },
};

function AvatarModelInner({ animationData }) {
    const group = useRef(null);
    const { scene, animations } = useGLTF('/models/avatar.glb');
    const { actions } = useAnimations(animations, group);

    // Clone scene to allow independent manipulation
    const clonedScene = useMemo(() => scene.clone(true), [scene]);

    const morphMesh      = useRef(null);
    const currentWeights = useRef({});
    const targetWeights  = useRef({});

    const { currentViseme } = useLipSync(animationData?.lipsync || []);

    // Find the morph-target mesh on mount
    useEffect(() => {
        clonedScene.traverse((child) => {
            if (child.isMesh && child.morphTargetDictionary) {
                morphMesh.current = child;
                Object.keys(child.morphTargetDictionary).forEach((key) => {
                    currentWeights.current[key] = 0;
                    targetWeights.current[key]  = 0;
                });
            }
        });
    }, [clonedScene]);

    // Update blendshapes from emotion
    useEffect(() => {
        if (!morphMesh.current) return;

        // Reset all targets
        Object.keys(targetWeights.current).forEach((k) => {
            targetWeights.current[k] = 0;
        });

        // Apply emotion preset
        const emotion = animationData?.emotion || 'neutral';
        const preset  = EMOTION_BLENDSHAPES[emotion] || {};
        Object.entries(preset).forEach(([key, val]) => {
            if (key in targetWeights.current) targetWeights.current[key] = val;
        });

        // Apply any explicit facial data from animationData
        if (animationData?.facial) {
            Object.entries(animationData.facial).forEach(([key, val]) => {
                if (key in targetWeights.current) targetWeights.current[key] = val;
            });
        }
    }, [animationData?.emotion, animationData?.facial]);

    // Play body animation
    useEffect(() => {
        if (!animationData?.body || !actions) return;
        const animName = animationData.body;
        if (actions[animName]) {
            Object.values(actions).forEach((a) => {
                if (a && a.isRunning()) a.fadeOut(0.5);
            });
            actions[animName]?.reset().fadeIn(0.5).play();
        }
    }, [animationData?.body, actions]);

    // Per-frame: lerp blendshapes + lip-sync + micro-movements
    useFrame((_, delta) => {
        if (!morphMesh.current?.morphTargetDictionary) return;

        const morphMeshNode  = morphMesh.current;
        const dict       = morphMeshNode.morphTargetDictionary;
        const influences = morphMeshNode.morphTargetInfluences;

        // Merge live lip-sync visemes into targets
        if (currentViseme) {
            const shapes = VISEME_MAP[currentViseme.viseme] || [];
            shapes.forEach((name) => {
                if (name in dict) {
                    targetWeights.current[name] = Math.max(
                        targetWeights.current[name] || 0,
                        currentViseme.weight * 0.8
                    );
                }
            });
        }

        // Smooth lerp for every blendshape
        const lerpSpeed = 8;
        Object.keys(dict).forEach((name) => {
            const idx     = dict[name];
            const target  = targetWeights.current[name] || 0;
            const current = currentWeights.current[name] || 0;
            const next    = THREE.MathUtils.lerp(current, target, lerpSpeed * delta);
            currentWeights.current[name] = next;
            influences[idx]              = next;
        });

        // Subtle breathing
        const breathe = Math.sin(Date.now() * 0.002) * 0.015;
        if (morphMeshNode.parent) morphMeshNode.parent.position.y = breathe;

        // Eye micro-saccades
        const eyeX = Math.sin(Date.now() * 0.001) * 0.05;
        const eyeY = Math.cos(Date.now() * 0.0013) * 0.03;
        if ('eyeLookInLeft' in dict) {
            influences[dict['eyeLookInLeft']]   += Math.max(0,  eyeX);
            influences[dict['eyeLookOutLeft']]  += Math.max(0, -eyeX);
            influences[dict['eyeLookUpLeft']]   += Math.max(0,  eyeY);
            influences[dict['eyeLookDownLeft']] += Math.max(0, -eyeY);
        }

        // Random blink every ~4 s
        const blinkCycle = ((Date.now() % 4000) / 4000);
        if (blinkCycle > 0.95 && 'eyeBlinkLeft' in dict) {
            const w = Math.sin(((blinkCycle - 0.95) / 0.05) * Math.PI);
            influences[dict['eyeBlinkLeft']]  = w;
            influences[dict['eyeBlinkRight']] = w;
        }
    });

    return (
        <group ref={group} position={[0, -0.8, 0]} scale={1}>
            <primitive object={clonedScene} />
        </group>
    );
}

export function AvatarModel({ animationData }) {
    return (
        <Suspense fallback={null}>
            <AvatarModelInner animationData={animationData} />
        </Suspense>
    );
}

useGLTF.preload('/models/avatar.glb');
