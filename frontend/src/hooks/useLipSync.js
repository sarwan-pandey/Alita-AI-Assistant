// hooks/useLipSync.js
// Adapted from AI face project — drives real-time viseme interpolation
import { useState, useEffect, useRef } from 'react';

export function useLipSync(visemeSequence) {
    const [currentViseme, setCurrentViseme] = useState(null);
    const startTimeRef = useRef(0);
    const indexRef = useRef(0);
    const animFrameRef = useRef(0);

    useEffect(() => {
        if (!visemeSequence || !visemeSequence.length) {
            setCurrentViseme(null);
            return;
        }

        startTimeRef.current = performance.now();
        indexRef.current = 0;

        const animate = () => {
            const elapsed = (performance.now() - startTimeRef.current) / 1000;

            // Advance index to current viseme based on elapsed time
            while (
                indexRef.current < visemeSequence.length - 1 &&
                visemeSequence[indexRef.current + 1].time <= elapsed
            ) {
                indexRef.current++;
            }

            if (indexRef.current < visemeSequence.length) {
                const current = visemeSequence[indexRef.current];
                const next = visemeSequence[indexRef.current + 1];

                if (next) {
                    const segDuration = next.time - current.time;
                    const segProgress = segDuration > 0 ? (elapsed - current.time) / segDuration : 1;
                    const smooth = Math.min(1, Math.max(0, Number.isFinite(segProgress) ? segProgress : 0));

                    setCurrentViseme({
                        viseme: smooth < 0.5 ? current.viseme : next.viseme,
                        weight: current.weight * (1 - smooth) + next.weight * smooth,
                        time: elapsed,
                    });
                } else {
                    setCurrentViseme(current);
                }

                animFrameRef.current = requestAnimationFrame(animate);
            } else {
                setCurrentViseme(null);
            }
        };

        animFrameRef.current = requestAnimationFrame(animate);

        return () => {
            cancelAnimationFrame(animFrameRef.current);
        };
    }, [visemeSequence]);

    return { currentViseme };
}
