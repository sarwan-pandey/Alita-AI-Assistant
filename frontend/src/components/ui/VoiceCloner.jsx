/**
 * VoiceCloner — Record/upload voice samples and clone via XTTS v2.
 * Features:
 *   - Record tab with live waveform + countdown timer
 *   - Upload tab with drag & drop
 *   - Progress bar with ETA during cloning
 *   - Minimizable to floating pill for background cloning
 *   - Custom voices list with preview/delete
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useSessionStore } from "../../store/useSessionStore";

const BACKEND = (import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws")
    .replace("ws://", "http://")
    .replace("wss://", "https://")
    .replace("/ws", "");

const STATES = {
    IDLE: "idle",
    RECORDING: "recording",
    UPLOADING: "uploading",
    NAMING: "naming",
    CLONING: "cloning",
    DONE: "done",
    ERROR: "error",
};

export function VoiceCloner({ isOpen, onClose, onVoiceCloned }) {
    const user = useSessionStore((s) => s.user);

    // ── State ─────────────────────────────────────────────────────────────
    const [tab, setTab] = useState("record"); // "record" | "upload"
    const [state, setState] = useState(STATES.IDLE);
    const [minimized, setMinimized] = useState(false);
    const [voiceName, setVoiceName] = useState("");
    const [refText, setRefText] = useState("");
    const [error, setError] = useState("");

    // Recording
    const [recordTime, setRecordTime] = useState(0);
    const [audioBlob, setAudioBlob] = useState(null);
    const [audioUrl, setAudioUrl] = useState(null);
    const mediaRecorderRef = useRef(null);
    const chunksRef = useRef([]);
    const timerRef = useRef(null);
    const canvasRef = useRef(null);
    const analyserRef = useRef(null);
    const animFrameRef = useRef(null);
    const streamRef = useRef(null);

    // Upload
    const [uploadFile, setUploadFile] = useState(null);
    const [dragOver, setDragOver] = useState(false);

    // Cloning progress
    const [uploadId, setUploadId] = useState(null);
    const [cloneId, setCloneId] = useState(null);
    const [progress, setProgress] = useState(0);
    const [step, setStep] = useState("");
    const [eta, setEta] = useState(0);

    // Custom voices
    const [customVoices, setCustomVoices] = useState([]);
    const [previewLoading, setPreviewLoading] = useState(null);

    // ── Fetch custom voices ───────────────────────────────────────────────
    const fetchVoices = useCallback(async () => {
        try {
            const uid = user?.id || "anonymous";
            const res = await fetch(`${BACKEND}/api/voice/custom?user_id=${uid}`);
            if (res.ok) {
                const data = await res.json();
                setCustomVoices(data.voices || []);
            }
        } catch { /* silent */ }
    }, [user]);

    useEffect(() => {
        if (isOpen) fetchVoices();
    }, [isOpen, fetchVoices]);

    // ── Recording ─────────────────────────────────────────────────────────
    const startRecording = useCallback(async () => {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            streamRef.current = stream;

            // Waveform visualizer
            const audioCtx = new AudioContext();
            const source = audioCtx.createMediaStreamSource(stream);
            const analyser = audioCtx.createAnalyser();
            analyser.fftSize = 256;
            source.connect(analyser);
            analyserRef.current = analyser;

            // MediaRecorder
            const recorder = new MediaRecorder(stream, { mimeType: "audio/webm;codecs=opus" });
            chunksRef.current = [];
            recorder.ondataavailable = (e) => {
                if (e.data.size > 0) chunksRef.current.push(e.data);
            };
            recorder.onstop = () => {
                const blob = new Blob(chunksRef.current, { type: "audio/webm" });
                setAudioBlob(blob);
                setAudioUrl(URL.createObjectURL(blob));
                stream.getTracks().forEach((t) => t.stop());
                cancelAnimationFrame(animFrameRef.current);
            };

            mediaRecorderRef.current = recorder;
            recorder.start(250);
            setState(STATES.RECORDING);
            setRecordTime(0);
            setError("");

            // Timer
            timerRef.current = setInterval(() => {
                setRecordTime((t) => {
                    if (t >= 30) {
                        stopRecording();
                        return 30;
                    }
                    return t + 1;
                });
            }, 1000);

            // Draw waveform
            drawWaveform();
        } catch (err) {
            setError("Microphone access denied. Please allow microphone access.");
        }
    }, []);

    const stopRecording = useCallback(() => {
        if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
            mediaRecorderRef.current.stop();
        }
        clearInterval(timerRef.current);
        cancelAnimationFrame(animFrameRef.current);
        setState(STATES.NAMING);
    }, []);

    const resetRecording = useCallback(() => {
        setAudioBlob(null);
        setAudioUrl(null);
        setRecordTime(0);
        setState(STATES.IDLE);
        setVoiceName("");
    }, []);

    // ── Waveform visualization ─────────────────────────────────────────
    const drawWaveform = useCallback(() => {
        const canvas = canvasRef.current;
        const analyser = analyserRef.current;
        if (!canvas || !analyser) return;

        const ctx = canvas.getContext("2d");
        const bufferLength = analyser.frequencyBinCount;
        const dataArray = new Uint8Array(bufferLength);

        const draw = () => {
            animFrameRef.current = requestAnimationFrame(draw);
            analyser.getByteFrequencyData(dataArray);

            ctx.fillStyle = "rgba(10, 10, 30, 0.3)";
            ctx.fillRect(0, 0, canvas.width, canvas.height);

            const barWidth = (canvas.width / bufferLength) * 2.5;
            let x = 0;
            for (let i = 0; i < bufferLength; i++) {
                const v = dataArray[i] / 255;
                const h = v * canvas.height;
                const grad = ctx.createLinearGradient(0, canvas.height - h, 0, canvas.height);
                grad.addColorStop(0, `hsl(${200 + v * 60}, 100%, ${50 + v * 30}%)`);
                grad.addColorStop(1, `hsl(${260 + v * 40}, 80%, 30%)`);
                ctx.fillStyle = grad;
                ctx.fillRect(x, canvas.height - h, barWidth - 1, h);
                x += barWidth;
            }
        };
        draw();
    }, []);

    // ── Upload handlers ────────────────────────────────────────────────
    const handleFileSelect = useCallback((file) => {
        if (!file) return;
        const ext = file.name.split(".").pop().toLowerCase();
        if (!["wav", "mp3", "ogg", "webm", "m4a"].includes(ext)) {
            setError("Unsupported format. Use WAV, MP3, OGG, WebM, or M4A.");
            return;
        }
        if (file.size > 10 * 1024 * 1024) {
            setError("File too large. Max 10MB.");
            return;
        }
        setUploadFile(file);
        setAudioUrl(URL.createObjectURL(file));
        setState(STATES.NAMING);
        setError("");
    }, []);

    // ── Submit (upload/record → server) ────────────────────────────────
    const handleSubmit = useCallback(async () => {
        if (!voiceName.trim()) {
            setError("Please enter a name for your voice.");
            return;
        }

        setState(STATES.UPLOADING);
        setError("");

        try {
            const formData = new FormData();
            formData.append("voice_name", voiceName.trim());
            formData.append("ref_text", refText.trim());
            formData.append("user_id", user?.id || "anonymous");

            let endpoint;
            if (tab === "record" && audioBlob) {
                formData.append("file", audioBlob, "recording.webm");
                endpoint = "/api/voice/record";
            } else if (uploadFile) {
                formData.append("file", uploadFile);
                endpoint = "/api/voice/upload";
            } else {
                setError("No audio to submit.");
                setState(STATES.NAMING);
                return;
            }

            const res = await fetch(`${BACKEND}${endpoint}`, { method: "POST", body: formData });
            const data = await res.json();

            if (!res.ok) {
                throw new Error(data.detail || "Upload failed");
            }

            setUploadId(data.upload_id);

            // Start cloning
            const cloneForm = new FormData();
            cloneForm.append("upload_id", data.upload_id);
            const cloneRes = await fetch(`${BACKEND}/api/voice/clone`, { method: "POST", body: cloneForm });
            const cloneData = await cloneRes.json();

            if (!cloneRes.ok) {
                throw new Error(cloneData.detail || "Clone start failed");
            }

            setCloneId(cloneData.clone_id);
            setState(STATES.CLONING);
            setProgress(0);
        } catch (err) {
            setError(err.message || "Something went wrong.");
            setState(STATES.NAMING);
        }
    }, [voiceName, tab, audioBlob, uploadFile, user]);

    // ── Poll clone progress ────────────────────────────────────────────
    useEffect(() => {
        if (state !== STATES.CLONING || !cloneId) return;

        const interval = setInterval(async () => {
            try {
                const res = await fetch(`${BACKEND}/api/voice/clone/${cloneId}/status`);
                const data = await res.json();

                setProgress(data.progress_pct || 0);
                setStep(data.step || "");
                setEta(data.eta_seconds || 0);

                if (data.status === "completed") {
                    setState(STATES.DONE);
                    clearInterval(interval);
                    fetchVoices();
                    onVoiceCloned?.(data.voice_id);
                } else if (data.status === "failed") {
                    setError(data.error || "Cloning failed.");
                    setState(STATES.ERROR);
                    clearInterval(interval);
                }
            } catch { /* retry */ }
        }, 800);

        return () => clearInterval(interval);
    }, [state, cloneId, fetchVoices, onVoiceCloned]);

    // ── Delete voice ───────────────────────────────────────────────────
    const handleDelete = useCallback(async (voiceId) => {
        try {
            await fetch(`${BACKEND}/api/voice/custom/${voiceId}`, { method: "DELETE" });
            fetchVoices();
        } catch { /* silent */ }
    }, [fetchVoices]);

    // ── Preview voice ──────────────────────────────────────────────────
    const handlePreview = useCallback(async (voiceId) => {
        setPreviewLoading(voiceId);
        try {
            const formData = new FormData();
            formData.append("voice_id", voiceId);
            const res = await fetch(`${BACKEND}/api/voice/preview`, { method: "POST", body: formData });
            if (res.ok) {
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const audio = new Audio(url);
                audio.onended = () => { URL.revokeObjectURL(url); setPreviewLoading(null); };
                audio.play();
            } else {
                setPreviewLoading(null);
            }
        } catch {
            setPreviewLoading(null);
        }
    }, []);

    // ── Cleanup ────────────────────────────────────────────────────────
    useEffect(() => {
        return () => {
            clearInterval(timerRef.current);
            cancelAnimationFrame(animFrameRef.current);
            if (streamRef.current) streamRef.current.getTracks().forEach((t) => t.stop());
        };
    }, []);

    // ── Minimized floating pill ────────────────────────────────────────
    if (minimized && state === STATES.CLONING) {
        return (
            <div className="vc-minimized-pill" onClick={() => setMinimized(false)}>
                <div className="vc-mini-spinner" />
                <span className="vc-mini-text">Cloning {progress}%</span>
                <div className="vc-mini-bar">
                    <div className="vc-mini-bar-fill" style={{ width: `${progress}%` }} />
                </div>
            </div>
        );
    }

    if (!isOpen && state !== STATES.CLONING) return null;

    // ── Full panel ─────────────────────────────────────────────────────
    return (
        <div className="vc-overlay" onClick={(e) => e.target === e.currentTarget && onClose?.()}>
            <div className="vc-panel">
                {/* Header */}
                <div className="vc-header">
                    <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
                        <span style={{ fontSize: "1.5rem" }}>🌊</span>
                        <div>
                            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                <h3 className="vc-title" style={{ margin: 0 }}>F5-TTS Diffusion Voice Studio</h3>
                                <span style={{ fontSize: "0.68rem", padding: "2px 8px", borderRadius: "12px", background: "rgba(56, 189, 248, 0.2)", color: "#38bdf8", border: "1px solid rgba(56, 189, 248, 0.4)", fontWeight: 600 }}>
                                    Flow Matching DiT
                                </span>
                            </div>
                            <p style={{ margin: "2px 0 0", fontSize: "0.75rem", color: "rgba(255,255,255,0.65)" }}>
                                Zero-shot clone any voice with emotional prosody from 3‑15s audio
                            </p>
                        </div>
                    </div>
                    <div className="vc-header-actions">
                        {state === STATES.CLONING && (
                            <button className="vc-minimize-btn" onClick={() => setMinimized(true)} title="Minimize">
                                ─
                            </button>
                        )}
                        <button className="vc-close-btn" onClick={onClose}>✕</button>
                    </div>
                </div>

                {/* Tabs (only show in idle/naming states) */}
                {(state === STATES.IDLE || state === STATES.NAMING) && (
                    <>
                        <div className="vc-tabs">
                            <button
                                className={`vc-tab ${tab === "record" ? "active" : ""}`}
                                onClick={() => { setTab("record"); resetRecording(); setUploadFile(null); }}
                            >
                                🎤 Record Voice
                            </button>
                            <button
                                className={`vc-tab ${tab === "upload" ? "active" : ""}`}
                                onClick={() => { setTab("upload"); resetRecording(); setUploadFile(null); }}
                            >
                                📁 Upload Sample
                            </button>
                        </div>

                        {/* Record Tab */}
                        {tab === "record" && state === STATES.IDLE && (
                            <div className="vc-record-section">
                                <canvas ref={canvasRef} className="vc-waveform" width={400} height={80} />
                                
                                <div style={{
                                    background: "rgba(56, 189, 248, 0.08)",
                                    border: "1px dashed rgba(56, 189, 248, 0.35)",
                                    borderRadius: "8px",
                                    padding: "10px 14px",
                                    fontSize: "0.82rem",
                                    color: "#cbd5e1",
                                    margin: "8px 0 12px",
                                    textAlign: "center",
                                    lineHeight: 1.4
                                }}>
                                    <span style={{ color: "#38bdf8", fontWeight: 600 }}>💡 Read aloud into your mic:</span><br />
                                    <em>"The quick brown fox jumps over the lazy dog, while laughter and warmth fill the quiet evening air."</em>
                                </div>

                                <div className="vc-record-info">
                                    Speak clearly for <strong>5‑15 seconds</strong> in a quiet room
                                </div>
                                <button className="vc-record-btn" onClick={startRecording}>
                                    <span className="vc-record-dot" />
                                    Start Recording
                                </button>
                            </div>
                        )}

                        {/* Recording in progress */}
                        {state === STATES.RECORDING && (
                            <div className="vc-record-section">
                                <canvas ref={canvasRef} className="vc-waveform active" width={400} height={80} />
                                
                                <div style={{
                                    background: "rgba(244, 114, 182, 0.08)",
                                    border: "1px dashed rgba(244, 114, 182, 0.35)",
                                    borderRadius: "8px",
                                    padding: "10px 14px",
                                    fontSize: "0.82rem",
                                    color: "#fbcfe8",
                                    margin: "8px 0 12px",
                                    textAlign: "center",
                                    lineHeight: 1.4
                                }}>
                                    <em>"The quick brown fox jumps over the lazy dog, while laughter and warmth fill the quiet evening air."</em>
                                </div>

                                <div className="vc-timer">
                                    <span className="vc-timer-dot recording" />
                                    {recordTime}s / 30s
                                    {recordTime < 3 && (
                                        <span className="vc-timer-hint"> (min 3s)</span>
                                    )}
                                </div>
                                <button
                                    className="vc-stop-btn"
                                    onClick={stopRecording}
                                    disabled={recordTime < 3}
                                >
                                    ⏹ Stop Recording
                                </button>
                            </div>
                        )}

                        {/* Upload Tab */}
                        {tab === "upload" && state === STATES.IDLE && (
                            <div
                                className={`vc-upload-zone ${dragOver ? "drag-over" : ""}`}
                                onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                                onDragLeave={() => setDragOver(false)}
                                onDrop={(e) => {
                                    e.preventDefault();
                                    setDragOver(false);
                                    handleFileSelect(e.dataTransfer.files[0]);
                                }}
                                onClick={() => document.getElementById("vc-file-input")?.click()}
                            >
                                <input
                                    id="vc-file-input"
                                    type="file"
                                    accept=".wav,.mp3,.ogg,.webm,.m4a"
                                    onChange={(e) => handleFileSelect(e.target.files?.[0])}
                                    hidden
                                />
                                <div className="vc-upload-icon">🌊</div>
                                <div className="vc-upload-text">
                                    Drag & drop a voice sample or <strong>click to browse</strong>
                                </div>
                                <div className="vc-upload-hint">WAV, MP3, WebM • 3‑30 seconds • Max 10MB</div>
                            </div>
                        )}

                        {/* Naming & Reference Transcript step */}
                        {state === STATES.NAMING && (
                            <div className="vc-naming-section">
                                {audioUrl && (
                                    <div className="vc-preview-audio">
                                        <audio controls src={audioUrl} />
                                    </div>
                                )}
                                <div className="vc-name-input-group">
                                    <label className="vc-name-label">Voice Name</label>
                                    <input
                                        type="text"
                                        className="vc-name-input"
                                        placeholder="e.g. My Voice, MJ Custom Warm"
                                        value={voiceName}
                                        onChange={(e) => setVoiceName(e.target.value)}
                                        maxLength={30}
                                        autoFocus
                                    />
                                </div>
                                <div className="vc-name-input-group" style={{ marginTop: "12px" }}>
                                    <label className="vc-name-label" style={{ display: "flex", justifyContent: "space-between" }}>
                                        <span>Reference Transcript</span>
                                        <span style={{ fontSize: "0.7rem", color: "#38bdf8" }}>Optional • boosts F5 fidelity</span>
                                    </label>
                                    <input
                                        type="text"
                                        className="vc-name-input"
                                        placeholder="What was spoken in the audio sample..."
                                        value={refText}
                                        onChange={(e) => setRefText(e.target.value)}
                                        maxLength={200}
                                    />
                                </div>
                                <div className="vc-naming-actions" style={{ marginTop: "16px" }}>
                                    <button className="vc-btn-secondary" onClick={resetRecording}>
                                        ← Re-record
                                    </button>
                                    <button
                                        className="vc-btn-primary"
                                        onClick={handleSubmit}
                                        disabled={!voiceName.trim()}
                                        style={{
                                            background: "linear-gradient(135deg, #0284c7, #9333ea)",
                                            color: "#fff",
                                            fontWeight: 600,
                                        }}
                                    >
                                        🌊 Clone with F5-TTS
                                    </button>
                                </div>
                            </div>
                        )}
                    </>
                )}

                {/* Uploading state */}
                {state === STATES.UPLOADING && (
                    <div className="vc-progress-section">
                        <div className="vc-progress-spinner" />
                        <div className="vc-progress-text">Uploading audio for F5-TTS conditioning...</div>
                    </div>
                )}

                {/* Cloning progress */}
                {state === STATES.CLONING && (
                    <div className="vc-progress-section">
                        <div className="vc-progress-ring">
                            <svg viewBox="0 0 100 100" className="vc-ring-svg">
                                <circle cx="50" cy="50" r="42" className="vc-ring-bg" />
                                <circle
                                    cx="50" cy="50" r="42"
                                    className="vc-ring-fill"
                                    style={{ strokeDashoffset: 264 - (264 * progress) / 100 }}
                                />
                            </svg>
                            <span className="vc-ring-text">{progress}%</span>
                        </div>
                        <div className="vc-progress-step">{step || "Conditioning F5-TTS Flow Matching Diffusion..."}</div>
                        {eta > 0 && (
                            <div className="vc-progress-eta">~{Math.ceil(eta)}s remaining</div>
                        )}
                        <button className="vc-minimize-link" onClick={() => setMinimized(true)}>
                            Minimize & continue using MJ
                        </button>
                    </div>
                )}

                {/* Done */}
                {state === STATES.DONE && (
                    <div className="vc-done-section">
                        <div className="vc-done-icon">🌊</div>
                        <h4 className="vc-done-title">F5-TTS Voice Cloned!</h4>
                        <p className="vc-done-text">
                            <strong>{voiceName}</strong> has been cloned and registered into MJ's voice engine.
                        </p>
                        <div style={{ display: "flex", gap: "10px", justifyContent: "center", marginTop: "12px" }}>
                            <button
                                className="vc-btn-primary"
                                onClick={() => {
                                    if (uploadId) onVoiceCloned?.(uploadId);
                                    resetRecording();
                                    setState(STATES.IDLE);
                                    onClose?.();
                                }}
                                style={{
                                    background: "linear-gradient(135deg, #0284c7, #9333ea)",
                                    color: "#fff",
                                    fontWeight: 600,
                                }}
                            >
                                ✨ Set as Active MJ Voice
                            </button>
                            <button
                                className="vc-btn-secondary"
                                onClick={() => { resetRecording(); setState(STATES.IDLE); onClose?.(); }}
                            >
                                Close
                            </button>
                        </div>
                    </div>
                )}

                {/* Error */}
                {error && (
                    <div className="vc-error">
                        <span>⚠️</span> {error}
                        <button className="vc-error-dismiss" onClick={() => setError("")}>✕</button>
                    </div>
                )}

                {/* Custom voices list */}
                {(state === STATES.IDLE || state === STATES.DONE) && customVoices.length > 0 && (
                    <div className="vc-voices-section">
                        <h4 className="vc-voices-title">Your Cloned F5-TTS Voices</h4>
                        {customVoices.map((v) => (
                            <div key={v.id} className={`vc-voice-item ${v.available ? "" : "pending"}`}>
                                <div className="vc-voice-info">
                                    <span className="vc-voice-icon">🌊</span>
                                    <span className="vc-voice-name">{v.name}</span>
                                    <span className="vc-voice-dur">{v.duration_s}s</span>
                                </div>
                                <div className="vc-voice-actions" style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                                    {v.available && (
                                        <>
                                            <button
                                                className="vc-voice-preview"
                                                onClick={() => handlePreview(v.id)}
                                                disabled={previewLoading === v.id}
                                                title="Preview sample"
                                            >
                                                {previewLoading === v.id ? "⏳" : "▶"}
                                            </button>
                                            <button
                                                className="vc-voice-use-btn"
                                                onClick={() => {
                                                    onVoiceCloned?.(v.id);
                                                    onClose?.();
                                                }}
                                                style={{
                                                    padding: "4px 10px",
                                                    borderRadius: "6px",
                                                    background: "rgba(56, 189, 248, 0.2)",
                                                    color: "#38bdf8",
                                                    border: "1px solid rgba(56, 189, 248, 0.4)",
                                                    fontSize: "0.75rem",
                                                    fontWeight: 600,
                                                    cursor: "pointer",
                                                }}
                                                title="Set this voice as MJ's active voice"
                                            >
                                                ✨ Use Voice
                                            </button>
                                        </>
                                    )}
                                    <button className="vc-voice-delete" onClick={() => handleDelete(v.id)} title="Delete voice">
                                        🗑️
                                    </button>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
