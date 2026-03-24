// components/hologram/HologramEffects.jsx
// Scanlines, rotating rings, and base glow — pure Three.js shaders
import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

export function HologramEffects() {
    return (
        <>
            <ScanlineEffect />
            <HologramRings />
            <BaseGlow />
        </>
    );
}

function ScanlineEffect() {
    const meshRef = useRef(null);

    const scanlineMaterial = useMemo(() => {
        return new THREE.ShaderMaterial({
            transparent: true,
            depthWrite: false,
            side: THREE.DoubleSide,
            uniforms: {
                uTime: { value: 0 },
                uColor: { value: new THREE.Color('#00aaff') },
                uOpacity: { value: 0.05 },
            },
            vertexShader: `
                varying vec2 vUv;
                varying vec3 vPosition;
                void main() {
                    vUv = uv;
                    vPosition = position;
                    gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
                }
            `,
            fragmentShader: `
                uniform float uTime;
                uniform vec3 uColor;
                uniform float uOpacity;
                varying vec2 vUv;
                varying vec3 vPosition;

                void main() {
                    // Horizontal scanlines
                    float scanline = sin(vPosition.y * 100.0 + uTime * 2.0) * 0.5 + 0.5;
                    scanline = step(0.8, scanline);

                    // Vertical glitch
                    float glitch = step(0.99, sin(uTime * 10.0 + vPosition.y * 50.0));

                    // Moving scan bar
                    float scanBar = smoothstep(0.0, 0.02,
                        abs(fract(vPosition.y * 0.5 - uTime * 0.3) - 0.5));
                    scanBar = 1.0 - scanBar;

                    float alpha = (scanline * 0.3 + glitch * 0.5 + scanBar * 0.2) * uOpacity;
                    gl_FragColor = vec4(uColor, alpha);
                }
            `,
        });
    }, []);

    useFrame(({ clock }) => {
        scanlineMaterial.uniforms.uTime.value = clock.getElapsedTime();
    });

    return (
        <mesh ref={meshRef} material={scanlineMaterial} position={[0, 0.8, 0]}>
            <cylinderGeometry args={[0.6, 0.6, 2.0, 32, 1, true]} />
        </mesh>
    );
}

function HologramRings() {
    const ringsRef = useRef(null);

    useFrame(({ clock }) => {
        if (!ringsRef.current) return;
        const t = clock.getElapsedTime();

        ringsRef.current.children.forEach((ring, i) => {
            ring.rotation.z = t * (0.2 + i * 0.1);
            ring.position.y = -0.01 + Math.sin(t + i) * 0.02;
            const mat = ring.material;
            if (mat) mat.opacity = 0.1 + Math.sin(t * 2 + i) * 0.05;
        });
    });

    return (
        <group ref={ringsRef} position={[0, 0, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            {[0.5, 0.65, 0.8].map((radius, i) => (
                <mesh key={i}>
                    <ringGeometry args={[radius, radius + 0.01, 64]} />
                    <meshBasicMaterial
                        color="#00aaff"
                        transparent
                        opacity={0.15}
                        side={THREE.DoubleSide}
                    />
                </mesh>
            ))}
        </group>
    );
}

function BaseGlow() {
    const glowRef = useRef(null);

    useFrame(({ clock }) => {
        if (glowRef.current) {
            glowRef.current.material.opacity =
                0.15 + Math.sin(clock.getElapsedTime() * 2) * 0.05;
        }
    });

    return (
        <mesh ref={glowRef} position={[0, 0.01, 0]} rotation={[-Math.PI / 2, 0, 0]}>
            <circleGeometry args={[1.2, 64]} />
            <meshBasicMaterial color="#0044ff" transparent opacity={0.15} />
        </mesh>
    );
}
