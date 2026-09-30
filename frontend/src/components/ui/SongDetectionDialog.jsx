/**
 * SongDetectionDialog — Premium song recognition pop-up
 *
 * Three animated phases:
 *   1. Analyzing  — live audio waveform canvas + progress ring
 *   2. Found      — album artwork, song info, listen link
 *   3. Minimized  — compact pill (auto after 15s, or manual)
 *
 * Error / Not-found states with retry support.
 */

import { useState, useEffect, useRef, useCallback, memo } from "react";

// ── Wave visualizer (Phase 1) ─────────────────────────────────────────────
function useWaveAnimation(canvasRef, active) {
  const rafRef = useRef(null);
  const analyserRef = useRef(null);
  const dataRef = useRef(null);
  const audioCtxRef = useRef(null);
  const streamRef = useRef(null);

  useEffect(() => {
    if (!active || !canvasRef.current) return;

    let cancelled = false;

    const setup = async () => {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true },
        });
        if (cancelled) { stream.getTracks().forEach(t => t.stop()); return; }
        streamRef.current = stream;

        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        audioCtxRef.current = ctx;
        const source = ctx.createMediaStreamSource(stream);
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        analyser.smoothingTimeConstant = 0.75;
        source.connect(analyser);
        analyserRef.current = analyser;
        dataRef.current = new Uint8Array(analyser.frequencyBinCount);

        draw();
      } catch (err) {
        console.warn("[SongDialog] Mic access denied for waveform:", err);
        // Fallback: synthetic wave
        drawSynthetic();
      }
    };

    const draw = () => {
      if (cancelled) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const c = canvas.getContext("2d");
      const W = canvas.width;
      const H = canvas.height;
      const analyser = analyserRef.current;
      const data = dataRef.current;

      analyser.getByteFrequencyData(data);

      c.clearRect(0, 0, W, H);

      const barCount = 64;
      const barW = W / barCount;
      const step = Math.floor(data.length / barCount);

      for (let i = 0; i < barCount; i++) {
        const val = data[i * step] / 255;
        const barH = Math.max(2, val * H * 0.85);
        const x = i * barW;
        const y = (H - barH) / 2;

        // Gradient per bar: cyan → purple
        const hue = 190 + (i / barCount) * 80; // 190 (cyan) → 270 (purple)
        const alpha = 0.4 + val * 0.6;
        c.fillStyle = `hsla(${hue}, 90%, 65%, ${alpha})`;
        c.roundRect?.(x + 1, y, barW - 2, barH, 2);
        c.fill?.();
        // Fallback for browsers without roundRect
        if (!c.roundRect) {
          c.fillRect(x + 1, y, barW - 2, barH);
        }

        // Glow on strong bars
        if (val > 0.6) {
          c.shadowColor = `hsla(${hue}, 90%, 65%, 0.6)`;
          c.shadowBlur = 8;
          c.fillRect(x + 1, y, barW - 2, barH);
          c.shadowBlur = 0;
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    // Fallback synthetic animation if no mic access
    const drawSynthetic = () => {
      if (cancelled) return;
      const canvas = canvasRef.current;
      if (!canvas) return;
      const c = canvas.getContext("2d");
      const W = canvas.width;
      const H = canvas.height;
      const time = Date.now() / 1000;

      c.clearRect(0, 0, W, H);
      const barCount = 64;
      const barW = W / barCount;

      for (let i = 0; i < barCount; i++) {
        const phase = (i / barCount) * Math.PI * 4 + time * 3;
        const val = 0.3 + 0.4 * Math.sin(phase) + 0.15 * Math.sin(phase * 2.7 + time);
        const barH = Math.max(2, Math.abs(val) * H * 0.8);
        const x = i * barW;
        const y = (H - barH) / 2;
        const hue = 190 + (i / barCount) * 80;
        const alpha = 0.35 + Math.abs(val) * 0.5;
        c.fillStyle = `hsla(${hue}, 90%, 65%, ${alpha})`;
        c.fillRect(x + 1, y, barW - 2, barH);
      }

      rafRef.current = requestAnimationFrame(drawSynthetic);
    };

    setup();

    return () => {
      cancelled = true;
      cancelAnimationFrame(rafRef.current);
      streamRef.current?.getTracks().forEach(t => t.stop());
      streamRef.current = null;
      if (audioCtxRef.current?.state !== "closed") {
        audioCtxRef.current?.close().catch(() => {});
      }
      audioCtxRef.current = null;
      analyserRef.current = null;
    };
  }, [active, canvasRef]);
}

// ── Progress Ring (SVG) ───────────────────────────────────────────────────
function ProgressRing({ progress, size = 48, stroke = 3 }) {
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (progress / 100) * circumference;

  return (
    <svg className="song-progress-ring" width={size} height={size}>
      <circle
        cx={size / 2} cy={size / 2} r={radius}
        fill="none"
        stroke="rgba(255,255,255,0.06)"
        strokeWidth={stroke}
      />
      <circle
        cx={size / 2} cy={size / 2} r={radius}
        fill="none"
        stroke="url(#songRingGradient)"
        strokeWidth={stroke}
        strokeLinecap="round"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        style={{ transition: "stroke-dashoffset 300ms ease", transform: "rotate(-90deg)", transformOrigin: "50% 50%" }}
      />
      <defs>
        <linearGradient id="songRingGradient" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" stopColor="#00d4ff" />
          <stop offset="100%" stopColor="#c084fc" />
        </linearGradient>
      </defs>
    </svg>
  );
}

// ── Main Component ────────────────────────────────────────────────────────
function SongDetectionDialogInner({
  phase,       // "analyzing" | "found" | "not_found" | "error" | null
  songData,    // { title, artist, album, artwork, url, error }
  statusText,  // "Analyzing audio..." etc.
  onClose,
  onRetry,
}) {
  const [minimized, setMinimized] = useState(false);
  const [progress, setProgress] = useState(0);
  const [closing, setClosing] = useState(false);
  const canvasRef = useRef(null);
  const autoMinTimerRef = useRef(null);
  const autoCloseTimerRef = useRef(null);

  // Reset minimized when phase changes
  useEffect(() => {
    if (phase === "analyzing") {
      setMinimized(false);
      setProgress(0);
      setClosing(false);
    }
  }, [phase]);

  // Progress animation during analyzing (8-sec recording + ~5-sec processing ≈ 13s total)
  useEffect(() => {
    if (phase !== "analyzing") return;
    const TOTAL_MS = 13000;
    const INTERVAL = 150;
    let elapsed = 0;
    const timer = setInterval(() => {
      elapsed += INTERVAL;
      const pct = Math.min(95, (elapsed / TOTAL_MS) * 100);
      setProgress(pct);
    }, INTERVAL);
    return () => clearInterval(timer);
  }, [phase]);

  // When song found → set progress to 100
  useEffect(() => {
    if (phase === "found") {
      setProgress(100);
    }
  }, [phase]);

  // Auto-minimize 15s after song found
  useEffect(() => {
    clearTimeout(autoMinTimerRef.current);
    clearTimeout(autoCloseTimerRef.current);
    if (phase === "found" && !minimized) {
      autoMinTimerRef.current = setTimeout(() => {
        setMinimized(true);
      }, 15000);
      // Auto-close 30s after minimize
      autoCloseTimerRef.current = setTimeout(() => {
        handleClose();
      }, 45000);
    }
    return () => {
      clearTimeout(autoMinTimerRef.current);
      clearTimeout(autoCloseTimerRef.current);
    };
  }, [phase, minimized]);

  // Waveform animation
  useWaveAnimation(canvasRef, phase === "analyzing");

  const handleClose = useCallback(() => {
    setClosing(true);
    setTimeout(() => {
      onClose?.();
      setClosing(false);
      setMinimized(false);
    }, 350);
  }, [onClose]);

  const handleMinimize = useCallback(() => {
    setMinimized(true);
  }, []);

  const handleExpand = useCallback(() => {
    setMinimized(false);
    // Reset auto-minimize timer
    clearTimeout(autoMinTimerRef.current);
    autoMinTimerRef.current = setTimeout(() => {
      setMinimized(true);
    }, 15000);
  }, []);

  if (!phase) return null;

  // ── Minimized Pill ──────────────────────────────────────────────────────
  if (minimized && phase === "found" && songData) {
    return (
      <div className={`song-minimized-pill ${closing ? "closing" : ""}`} onClick={handleExpand}>
        <div className="song-min-artwork">
          {songData.artwork ? (
            <img src={songData.artwork} alt="" />
          ) : (
            <span className="song-min-note">🎵</span>
          )}
        </div>
        <div className="song-min-info">
          <span className="song-min-title">{songData.title}</span>
          <span className="song-min-artist">{songData.artist}</span>
        </div>
        <button className="song-min-expand" onClick={(e) => { e.stopPropagation(); handleExpand(); }}>
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <polyline points="18 15 12 9 6 15" />
          </svg>
        </button>
        <button className="song-min-close" onClick={(e) => { e.stopPropagation(); handleClose(); }}>✕</button>
      </div>
    );
  }

  // ── Full Dialog ─────────────────────────────────────────────────────────
  return (
    <div className={`song-dialog-overlay ${closing ? "closing" : ""}`} onClick={handleClose}>
      <div className={`song-dialog ${closing ? "closing" : ""}`} onClick={(e) => e.stopPropagation()}>

        {/* Close + Minimize buttons */}
        <div className="song-dialog-controls">
          {phase === "found" && (
            <button className="song-ctrl-btn" onClick={handleMinimize} title="Minimize">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <line x1="5" y1="12" x2="19" y2="12" />
              </svg>
            </button>
          )}
          <button className="song-ctrl-btn" onClick={handleClose} title="Close">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* ─── Phase: Analyzing ─────────────────────────────────────────── */}
        {phase === "analyzing" && (
          <div className="song-analyzing">
            <div className="song-analyzing-header">
              <div className="song-ring-wrap">
                <ProgressRing progress={progress} size={56} stroke={3} />
                <div className="song-ring-icon">🎵</div>
              </div>
              <div className="song-analyzing-text">
                <span className="song-analyzing-title">Listening</span>
                <span className="song-analyzing-sub">
                  {statusText || "Analyzing audio…"}
                </span>
              </div>
            </div>
            <div className="song-wave-wrap">
              <canvas
                ref={canvasRef}
                className="song-wave-canvas"
                width={480}
                height={120}
              />
              <div className="song-wave-glow" />
            </div>
            <div className="song-analyzing-hint">
              Hold your device near the music source
            </div>
          </div>
        )}

        {/* ─── Phase: Found ─────────────────────────────────────────────── */}
        {phase === "found" && songData && (
          <div className="song-found">
            <div className="song-found-badge">
              <div className="song-found-badge-dot" />
              Song Identified
            </div>

            <div className="song-artwork-wrap">
              {songData.artwork ? (
                <img className="song-artwork-img" src={songData.artwork} alt={songData.title} />
              ) : (
                <div className="song-artwork-placeholder">
                  <span>🎵</span>
                </div>
              )}
              <div className="song-artwork-ring" />
              {/* Floating particles */}
              {Array.from({ length: 8 }).map((_, i) => (
                <div
                  key={i}
                  className="song-particle"
                  style={{
                    "--angle": `${(i / 8) * 360}deg`,
                    "--delay": `${i * 0.15}s`,
                    "--size": `${3 + Math.random() * 3}px`,
                  }}
                />
              ))}
            </div>

            <div className="song-info">
              <h3 className="song-title">{songData.title}</h3>
              <p className="song-artist">{songData.artist}</p>
              {songData.album && (
                <p className="song-album">{songData.album}</p>
              )}
            </div>

            {songData.url && (
              <a
                className="song-listen-btn"
                href={songData.url}
                target="_blank"
                rel="noopener noreferrer"
              >
                <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M8 5v14l11-7z" />
                </svg>
                Listen Now
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginLeft: "4px" }}>
                  <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                  <polyline points="15 3 21 3 21 9" />
                  <line x1="10" y1="14" x2="21" y2="3" />
                </svg>
              </a>
            )}

            <div className="song-auto-minimize-hint">
              Auto-minimizing in 15s · click minimize to keep
            </div>
          </div>
        )}

        {/* ─── Phase: Not Found ─────────────────────────────────────────── */}
        {phase === "not_found" && (
          <div className="song-not-found">
            <div className="song-nf-icon">🎵</div>
            <h3 className="song-nf-title">Couldn't Identify</h3>
            <p className="song-nf-desc">
              The song couldn't be recognized. Try playing it louder or moving closer to the speaker.
            </p>
            <button className="song-retry-btn" onClick={onRetry}>
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <polyline points="23 4 23 10 17 10" />
                <path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
              </svg>
              Try Again
            </button>
          </div>
        )}

        {/* ─── Phase: Error ─────────────────────────────────────────────── */}
        {phase === "error" && (
          <div className="song-error">
            <div className="song-err-icon">❌</div>
            <h3 className="song-err-title">Recognition Error</h3>
            <p className="song-err-desc">
              {songData?.error || "Something went wrong. Please try again."}
            </p>
            <button className="song-retry-btn" onClick={onRetry}>
              Try Again
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

export const SongDetectionDialog = memo(SongDetectionDialogInner);
