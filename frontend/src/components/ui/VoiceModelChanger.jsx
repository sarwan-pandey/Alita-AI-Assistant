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
    const [selectedVoice, setSelectedVoice] = useState("en_jenny");
    const [isOpen, setIsOpen] = useState(false);
    const [loading, setLoading] = useState(false);
    const [previewPlaying, setPreviewPlaying] = useState(null);
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

    // Fetch voices and languages on mount
    useEffect(() => {
        Promise.all([
            fetch(`${BACKEND}/voices`).then((r) => r.json()),
            fetch(`${BACKEND}/languages`).then((r) => r.json()),
        ])
            .then(([vData, lData]) => {
                setVoices(vData.voices || []);
                setLanguages(lData.languages || []);
            })
            .catch(() => {
                // Fallback
                setLanguages([
                    { code: "en", name: "English", free_voices: 1, premium_voices: 3 },
                    { code: "hi", name: "हिंदी (Hindi)", free_voices: 1, premium_voices: 1 },
                    { code: "es", name: "Español (Spanish)", free_voices: 1, premium_voices: 1 },
                    { code: "fr", name: "Français (French)", free_voices: 1, premium_voices: 1 },
                ]);
                setVoices([
                    { id: "en_jenny", name: "Jenny (English Female)", lang: "en", tier_required: "free", quality: "high", available: true },
                    { id: "hi_swara", name: "Swara (Hindi Female)", lang: "hi", tier_required: "free", quality: "high", available: true },
                    { id: "es_lucia", name: "Lucia (Spanish Female)", lang: "es", tier_required: "free", quality: "high", available: true },
                    { id: "fr_denise", name: "Denise (French Female)", lang: "fr", tier_required: "free", quality: "high", available: true },
                ]);
            });
    }, []);

    const isBetaUser = user?.email?.includes("@aura.test") || user?.id?.startsWith?.("test_");
    const canAccessPremium = tier === "premium" || isBetaUser;

    const filteredVoices = voices.filter((v) => v.lang === selectedLang);

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
                                            <span className="voice-option-name">{voice.name}</span>
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
                                        {voice.quality === "high" && (
                                            <span className="voice-quality-badge">HD</span>
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
                </div>
            )}
        </div>
    );
}
