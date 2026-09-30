/**
 * VoiceModelChanger — Language selector + voice model picker.
 * Groups voices by language, shows free/premium tiers.
 * Free users see premium voices but get redirected to purchase on click.
 *
 * Fixes applied:
 *   - speechSynthesis.cancel() on language change
 *   - Re-fetch voices filtered by new language
 *   - Auto-select first voice for new language
 *   - Voice preview button using Web Speech API
 *   - Language indicator showing active language
 */

import { useState, useEffect, useCallback, useRef } from "react";
import { useSessionStore } from "../../store/useSessionStore";
import { VoiceCloner } from "./VoiceCloner";

const BACKEND = (import.meta.env.VITE_WS_BACKEND_URL || "ws://localhost:8000/ws")
    .replace("ws://", "http://")
    .replace("wss://", "https://")
    .replace("/ws", "");

const LANG_FLAGS = {
    en: "🇺🇸",
    hi: "🇮🇳",
    es: "🇪🇸",
    fr: "🇫🇷",
    de: "🇩🇪",
    ja: "🇯🇵",
};

const LANG_NAMES = {
    en: "English",
    hi: "Hindi",
    es: "Spanish",
    fr: "French",
    de: "German",
    ja: "Japanese",
};

// Map language codes to BCP-47 speech synthesis locale codes
const LANG_SPEECH_CODES = {
    en: "en-US",
    hi: "hi-IN",
    es: "es-ES",
    fr: "fr-FR",
    de: "de-DE",
    ja: "ja-JP",
};

export function VoiceModelChanger({ sendVoiceChange, onPremiumRequired, externalLang, externalVoiceId, onLanguageChange }) {
    const tier = useSessionStore((s) => s.tier);
    const user = useSessionStore((s) => s.user);
    const [voices, setVoices] = useState([]);
    const [languages, setLanguages] = useState([]);
    const [selectedLang, setSelectedLang] = useState("en");
    const [selectedVoice, setSelectedVoice] = useState(() => {
        const saved = localStorage.getItem("alita_voice_id");
        if (!saved || saved === "chatterbox_mj" || saved === "f5_mj_clone" || saved === "chattts_mj") {
            localStorage.setItem("alita_voice_id", "chatterbox_turbo_mj");
            return "chatterbox_turbo_mj";
        }
        return saved;
    });
    const [isOpen, setIsOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [previewPlaying, setPreviewPlaying] = useState(null);
    const [showCloner, setShowCloner] = useState(false);
    const [activeMood, setActiveMood] = useState("affectionate");
    const [availableMoods, setAvailableMoods] = useState([
        { id: "affectionate", name: "Affectionate & Warm", icon: "💖" },
        { id: "playful", name: "Playful & Teasing", icon: "✨" },
        { id: "soothing", name: "Soothing & Tender", icon: "🌙" },
        { id: "calm", name: "Calm & Natural", icon: "☕" },
    ]);
    const synthVoicesRef = useRef([]);

    // Load browser speech synthesis voices
    useEffect(() => {
        const loadVoices = () => {
            synthVoicesRef.current = window.speechSynthesis?.getVoices() || [];
        };
        loadVoices();
        if (window.speechSynthesis) {
            window.speechSynthesis.onvoiceschanged = loadVoices;
        }
        return () => {
            if (window.speechSynthesis) {
                window.speechSynthesis.onvoiceschanged = null;
            }
        };
    }, []);

    // ── Sync with backend auto-language detection ─────────────────────────
    useEffect(() => {
        if (externalLang && externalLang !== selectedLang) {
            setSelectedLang(externalLang);
        }
    }, [externalLang]);

    useEffect(() => {
        if (externalVoiceId && externalVoiceId !== selectedVoice) {
            setSelectedVoice(externalVoiceId);
        }
    }, [externalVoiceId]);

    // Fetch voices, languages, and mood on mount
    useEffect(() => {
        Promise.all([
            fetch(`${BACKEND}/voices`).then((r) => r.json()).catch(() => ({})),
            fetch(`${BACKEND}/languages`).then((r) => r.json()).catch(() => ({})),
            fetch(`${BACKEND}/api/voice/mood`).then((r) => r.json()).catch(() => ({})),
        ])
            .then(([vData, lData, mData]) => {
                if (vData.voices && Array.isArray(vData.voices) && vData.voices.length > 0) {
                    setVoices(vData.voices);
                }
                if (lData.languages && Array.isArray(lData.languages) && lData.languages.length > 0) {
                    setLanguages(lData.languages);
                }
                if (mData.moods) setAvailableMoods(mData.moods);
                if (mData.active_mood) setActiveMood(mData.active_mood);
            })
            .catch(() => {
                // Fallback: Chatterbox Turbo
                setLanguages([
                    { code: "en", name: "English", free_voices: 1, premium_voices: 0 },
                ]);
                setVoices([
                    {
                        id: "chatterbox_turbo_mj",
                        name: "MJ (Chatterbox Turbo)",
                        lang: "en",
                        tier_required: "free",
                        quality: "ultra",
                        available: true,
                        engine: "chatterbox_turbo",
                        description: "350M-param neural voice with [laugh], [sigh], [cough] expression tags",
                    },
                ]);
            });
    }, []);

    const handleMoodChange = async (moodId) => {
        setActiveMood(moodId);
        try {
            await fetch(`${BACKEND}/api/voice/mood`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ mood: moodId }),
            });
        } catch (err) {
            console.warn("Failed to set active voice mood:", err);
        }
    };

    const isBetaUser = user?.email?.includes("@aura.test") || user?.id?.startsWith?.("test_");
    const canAccessPremium = tier === "premium" || isBetaUser;

    // Filter to show active models
    const filteredVoices = voices.filter(
        (v) =>
            (v.id === "chatterbox_turbo_mj" || v.engine === "chatterbox_turbo") &&
            (v.lang === selectedLang || v.lang === "all" || !v.lang)
    );

    // ── Language switch handler (with speechSynthesis fix) ────────────────
    const handleLangChange = useCallback((langCode) => {
        // Cancel any ongoing speech before switching
        if (window.speechSynthesis) {
            window.speechSynthesis.cancel();
        }

        setSelectedLang(langCode);

        // Notify parent to update STT language immediately
        onLanguageChange?.(langCode);

        // Auto-select first available voice for the new language
        const langVoices = voices.filter((v) => v.lang === langCode);
        const freeVoice = langVoices.find((v) => v.tier_required === "free" && v.available);
        if (freeVoice) {
            setSelectedVoice(freeVoice.id);
            sendVoiceChange?.(freeVoice.id);
        } else if (langVoices.length > 0) {
            setSelectedVoice(langVoices[0].id);
            sendVoiceChange?.(langVoices[0].id);
        }
    }, [voices, sendVoiceChange, onLanguageChange]);

    // ── Voice selection handler ──────────────────────────────────────────
    const handleSelect = useCallback(
        (voiceId) => {
            const voice = voices.find((v) => v.id === voiceId);
            if (!voice) return;

            if (voice.tier_required === "premium" && !canAccessPremium) {
                onPremiumRequired?.();
                return;
            }

            if (!voice.available) return;

            // Cancel current speech before switching voice
            if (window.speechSynthesis) {
                window.speechSynthesis.cancel();
            }

            setLoading(true);
            setSelectedVoice(voiceId);
            sendVoiceChange?.(voiceId);
            setTimeout(() => setLoading(false), 500);
        },
        [voices, canAccessPremium, sendVoiceChange, onPremiumRequired]
    );

    // ── Voice preview ───────────────────────────────────────────────────
    const handlePreview = useCallback((voiceId, e) => {
        e.stopPropagation();

        if (!window.speechSynthesis) return;

        // Stop any current preview
        window.speechSynthesis.cancel();

        if (previewPlaying === voiceId) {
            setPreviewPlaying(null);
            return;
        }

        const voice = voices.find((v) => v.id === voiceId);
        if (!voice) return;

        const langCode = LANG_SPEECH_CODES[voice.lang] || "en-US";
        const sampleTexts = {
            en: "Hello! I am your AI assistant. How can I help you today?",
            hi: "नमस्ते! मैं आपकी AI सहायक हूँ। आज मैं आपकी कैसे मदद कर सकती हूँ?",
            es: "¡Hola! Soy tu asistente de inteligencia artificial.",
            fr: "Bonjour! Je suis votre assistant IA.",
            de: "Hallo! Ich bin Ihr KI-Assistent.",
            ja: "こんにちは！AIアシスタントです。",
        };

        const utterance = new SpeechSynthesisUtterance(sampleTexts[voice.lang] || sampleTexts.en);
        utterance.lang = langCode;

        // Try to find a matching browser voice
        const browserVoices = synthVoicesRef.current;
        const match = browserVoices.find((v) => v.lang.startsWith(voice.lang));
        if (match) utterance.voice = match;

        utterance.rate = 1;
        utterance.pitch = 1;

        setPreviewPlaying(voiceId);
        utterance.onend = () => setPreviewPlaying(null);
        utterance.onerror = () => setPreviewPlaying(null);

        window.speechSynthesis.speak(utterance);
    }, [voices, previewPlaying]);

    const currentVoice = voices.find((v) => v.id === selectedVoice);

    return (
        <div className="voice-changer">
            <button
                className="voice-changer-toggle hoverable"
                onClick={() => setIsOpen(!isOpen)}
                title="Change language & voice"
            >
                <span className="voice-changer-icon">
                    {LANG_FLAGS[selectedLang] || "🌐"}
                </span>
                <span className="voice-changer-current">
                    {currentVoice?.name || "Jenny"}
                </span>
                {/* Language indicator */}
                <span className="lang-indicator">
                    {LANG_NAMES[selectedLang] || selectedLang}
                </span>
                <span className={`voice-changer-arrow ${isOpen ? "open" : ""}`}>▾</span>
            </button>

            {isOpen && (
                <div className="voice-changer-dropdown">
                    <div className="voice-changer-header">
                        <span>Language & Voice</span>
                        <button
                            className="voice-changer-close hoverable"
                            onClick={() => setIsOpen(false)}
                        >
                            ✕
                        </button>
                    </div>

                    {/* Language tabs */}
                    <div className="lang-tabs">
                        {languages.map((lang) => (
                            <button
                                key={lang.code}
                                className={`lang-tab hoverable ${selectedLang === lang.code ? "active" : ""}`}
                                onClick={() => handleLangChange(lang.code)}
                            >
                                <span className="lang-tab-flag">
                                    {LANG_FLAGS[lang.code] || "🌐"}
                                </span>
                                <span className="lang-tab-name">{lang.name}</span>
                            </button>
                        ))}
                    </div>

                    {/* Voice list for selected language */}
                    <div className="voice-list">
                        {filteredVoices.length === 0 && (
                            <div className="voice-empty">No voices available for this language</div>
                        )}
                        {filteredVoices.map((voice) => {
                            const isPremium = voice.tier_required === "premium";
                            const isLocked = isPremium && !canAccessPremium;
                            const isSelected = voice.id === selectedVoice;
                            const isAvailable = voice.available;
                            const isPreviewing = previewPlaying === voice.id;

                            return (
                                <button
                                    key={voice.id}
                                    className={`voice-option hoverable ${isSelected ? "selected" : ""} ${isLocked ? "locked" : ""} ${!isAvailable && !isLocked ? "unavailable" : ""}`}
                                    onClick={() => handleSelect(voice.id)}
                                    disabled={loading}
                                >
                                    <div className="voice-option-left">
                                        <div className="voice-option-info">
                                            <div style={{ display: "flex", alignItems: "center", gap: "6px" }}>
                                                <span className="voice-option-name">{voice.name}</span>
                                                {voice.engine === "chattts" && (
                                                    <span style={{ fontSize: "0.65rem", padding: "1px 6px", borderRadius: "4px", background: "rgba(244, 114, 182, 0.2)", color: "#f472b6", border: "1px solid rgba(244, 114, 182, 0.3)" }}>
                                                        💖 ChatTTS
                                                    </span>
                                                )}
                                                {voice.engine === "f5" && (
                                                    <span style={{ fontSize: "0.65rem", padding: "1px 6px", borderRadius: "4px", background: "rgba(56, 189, 248, 0.2)", color: "#38bdf8", border: "1px solid rgba(56, 189, 248, 0.3)" }}>
                                                        🌊 F5-TTS
                                                    </span>
                                                )}
                                                {voice.engine === "chatterbox" && (
                                                    <span style={{ fontSize: "0.65rem", padding: "1px 6px", borderRadius: "4px", background: "rgba(168, 85, 247, 0.2)", color: "#c084fc", border: "1px solid rgba(168, 85, 247, 0.3)" }}>
                                                        ✨ Chatterbox
                                                    </span>
                                                )}
                                            </div>
                                            <span className="voice-option-desc">
                                                {voice.description}
                                            </span>
                                        </div>
                                    </div>

                                    <div className="voice-option-right">
                                        {/* Preview button */}
                                        {isAvailable && !isLocked && (
                                            <span
                                                role="button"
                                                tabIndex={0}
                                                className={`voice-preview-btn ${isPreviewing ? "playing" : ""}`}
                                                onClick={(e) => handlePreview(voice.id, e)}
                                                title="Preview voice"
                                            >
                                                {isPreviewing ? "◼" : "▶"}
                                            </span>
                                        )}
                                        {voice.quality === "ultra" && (
                                            <span className="voice-quality-badge" style={{ background: "rgba(168, 85, 247, 0.25)", color: "#c084fc", border: "1px solid rgba(168, 85, 247, 0.4)" }}>Studio HD</span>
                                        )}
                                        {isSelected && (
                                            <span className="voice-option-active">●</span>
                                        )}
                                        {isLocked && (
                                            <span className="voice-option-lock">✦ premium</span>
                                        )}
                                        {!isAvailable && !isLocked && (
                                            <span className="voice-option-download">↓</span>
                                        )}
                                    </div>
                                </button>
                            );
                        })}
                    </div>

                    {/* MJ Emotional Mood Selector (Method 3 -> Method 1) */}
                    <div
                        style={{
                            marginTop: "10px",
                            padding: "10px 12px",
                            background: "rgba(244, 114, 182, 0.08)",
                            borderRadius: "10px",
                            border: "1px solid rgba(244, 114, 182, 0.22)",
                        }}
                    >
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "8px" }}>
                            <span style={{ fontSize: "0.75rem", fontWeight: 700, color: "#f472b6", letterSpacing: "0.4px" }}>
                                💖 MJ Emotional Mood
                            </span>
                            <span style={{ fontSize: "0.68rem", color: "rgba(255,255,255,0.55)" }}>
                                Oral Prosody
                            </span>
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "6px" }}>
                            {availableMoods.map((m) => {
                                const isActive = activeMood === m.id;
                                return (
                                    <button
                                        key={m.id}
                                        type="button"
                                        className="hoverable"
                                        onClick={() => handleMoodChange(m.id)}
                                        style={{
                                            display: "flex",
                                            alignItems: "center",
                                            gap: "6px",
                                            padding: "6px 8px",
                                            borderRadius: "7px",
                                            border: isActive ? "1px solid #f472b6" : "1px solid rgba(255,255,255,0.12)",
                                            background: isActive ? "rgba(244, 114, 182, 0.25)" : "rgba(255,255,255,0.04)",
                                            color: isActive ? "#fff" : "rgba(255,255,255,0.8)",
                                            fontSize: "0.73rem",
                                            cursor: "pointer",
                                            transition: "all 0.15s ease",
                                            textAlign: "left",
                                        }}
                                    >
                                        <span style={{ fontSize: "0.85rem" }}>{m.icon || "💖"}</span>
                                        <div style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                                            <div style={{ fontWeight: isActive ? 700 : 500 }}>{m.name.split("&")[0].trim()}</div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </div>

                    {/* F5-TTS Voice Studio trigger */}
                    <button
                        className="vc-clone-trigger hoverable"
                        onClick={() => { setShowCloner(true); setIsOpen(false); }}
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "10px",
                            background: "linear-gradient(135deg, rgba(56, 189, 248, 0.12), rgba(168, 85, 247, 0.15))",
                            border: "1px solid rgba(56, 189, 248, 0.35)",
                            borderRadius: "10px",
                            padding: "10px 14px",
                            marginTop: "8px",
                            cursor: "pointer",
                            width: "100%",
                            textAlign: "left",
                            transition: "all 0.2s ease",
                        }}
                    >
                        <span style={{ fontSize: "1.3rem" }}>🌊</span>
                        <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 600, fontSize: "0.85rem", color: "#38bdf8" }}>
                                F5-TTS Voice Studio
                            </div>
                            <div style={{ fontSize: "0.72rem", color: "rgba(255,255,255,0.65)" }}>
                                Zero-shot clone any voice from 3‑15s audio
                            </div>
                        </div>
                        <span style={{ color: "#38bdf8", fontSize: "0.95rem", fontWeight: "bold" }}>→</span>
                    </button>
                </div>
            )}

            {/* Voice Cloner Modal */}
            <VoiceCloner
                isOpen={showCloner}
                onClose={() => setShowCloner(false)}
                onVoiceCloned={(voiceId) => {
                    sendVoiceChange?.(voiceId);
                }}
            />
        </div>
    );
}
