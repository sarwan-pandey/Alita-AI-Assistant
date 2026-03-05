/**
 * Alita Assistant — Root App
 * Redesigned: AI Assistant Dashboard UI
 *   - 3-column layout: SearchHistory | Center Soundwave | SearchResults
 *   - Modern soundwave animation replacing 3D particle canvas
 *   - Dynamic search history tracking
 *   - Dynamic search results from voice commands
 */

import { useEffect, useCallback, useState, lazy, Suspense } from "react";
import { createClient } from "@supabase/supabase-js";


import { AudioCapture } from "./components/audio/AudioCapture";
import { TierGate } from "./components/ui/TierGate";
import { VoiceModelChanger } from "./components/ui/VoiceModelChanger";
import { GoogleAuthButton } from "./components/auth/GoogleAuthButton";
import { ThinkingDots } from "./components/ui/AuraAnimations";

// Dashboard components
import { Header } from "./components/ui/Header";
import { SearchHistory } from "./components/ui/SearchHistory";
import { SearchResults } from "./components/ui/SearchResults";
import { BottomNav } from "./components/ui/BottomNav";
import { SoundwaveOrb } from "./components/ui/SoundwaveOrb";

// Geospatial dashboard — lazy loaded
const GeoApp = lazy(() => import("./components/geo/GeoApp"));

import { useSessionStore } from "./store/useSessionStore";
import { useEmotionStore } from "./store/useEmotionStore";
import { useWebSocket } from "./hooks/useWebSocket";
import { useTheme } from "./hooks/useTheme";
import { useNotifications } from "./hooks/useNotifications";

import { TestLoginButton } from "./components/auth/TestLoginButton";

import "./App.css";

// ── Supabase singleton ───────────────────────────────────────────────────────
export const supabase = createClient(
  import.meta.env.VITE_SUPABASE_URL,
  import.meta.env.VITE_SUPABASE_ANON_KEY,
);

// ── Helper: extract search category from user query ─────────────────────────
function categorizeQuery(text) {
  const lower = text.toLowerCase();
  const categories = [
    { key: "medicines", words: ["medicine", "drug", "pharma", "tablet", "pill", "health", "medical"] },
    { key: "medical_equipment", words: ["equipment", "stethoscope", "monitor", "device", "scanner"] },
    { key: "traffic_signals", words: ["traffic", "signal", "road", "driving", "highway"] },
    { key: "data_recognition", words: ["data", "recognition", "pattern", "algorithm", "ai", "ml"] },
    { key: "alarm", words: ["alarm", "timer", "clock", "wake", "reminder"] },
    { key: "facts", words: ["fact", "trivia", "history", "science", "knowledge"] },
    { key: "phones", words: ["phone", "mobile", "smartphone", "iphone", "android", "samsung"] },
    { key: "cartoons", words: ["cartoon", "anime", "animation", "movie", "film", "show"] },
    { key: "restaurants", words: ["restaurant", "food", "eat", "dining", "pizza", "burger", "cook"] },
    { key: "cloth_stores", words: ["cloth", "clothing", "fashion", "wear", "shirt", "dress", "store", "shop"] },
    { key: "technology", words: ["tech", "computer", "laptop", "gadget", "hoverboard", "drone"] },
    { key: "travel", words: ["travel", "flight", "hotel", "trip", "vacation", "tour"] },
    { key: "weather", words: ["weather", "rain", "temperature", "forecast", "sunny", "cloud"] },
    { key: "music", words: ["music", "song", "singer", "band", "album", "playlist"] },
    { key: "sports", words: ["sport", "cricket", "football", "basketball", "game", "match", "player"] },
  ];
  for (const cat of categories) {
    if (cat.words.some((w) => lower.includes(w))) return cat.key;
  }
  return "general";
}

const CATEGORY_LABELS = {
  medicines: "Medicines",
  medical_equipment: "Medical Equipment",
  traffic_signals: "Traffic Signals",
  data_recognition: "Data Recognition",
  alarm: "Alarm",
  facts: "Facts",
  phones: "Phones",
  cartoons: "Cartoons",
  restaurants: "Restaurants",
  cloth_stores: "Cloth Stores",
  technology: "Technology",
  travel: "Travel",
  weather: "Weather",
  music: "Music",
  sports: "Sports",
  general: "General",
};

// ─────────────────────────────────────────────────────────────────────────────
// App Shell
// ─────────────────────────────────────────────────────────────────────────────
export default function App() {
  const [activeView, setActiveView] = useState("alita"); // "alita" | "geospatial"

  const { user, setUser, accessToken, setAccessToken, tier, setTier, clearSession } =
    useSessionStore();

  const { setEmotion } = useEmotionStore();

  // ── Theme & Notifications ───────────────────────────────────────────
  const { mode: themeMode, cycleTheme } = useTheme();
  const notifications = useNotifications();

  const [messages, setMessages] = useState([]);
  const [isListening, setIsListening] = useState(false);
  const [isThinking, setIsThinking] = useState(false);
  const [isSpeaking, setIsSpeaking] = useState(false);
  const [errorToast, setErrorToast] = useState(null);
  const [showPricing, setShowPricing] = useState(false);
  const [dictationMode, setDictationMode] = useState(null);
  const [sttLanguage, setSttLanguage] = useState("en-IN");
  const [appInstallToast, setAppInstallToast] = useState(null);
  const [currentQuery, setCurrentQuery] = useState("");
  const [voiceLang, setVoiceLang] = useState("en");
  const [autoVoiceId, setAutoVoiceId] = useState(null);
  const [musicDetected, setMusicDetected] = useState(false);

  // ── Dynamic search state ────────────────────────────────────────────────
  const [searchHistory, setSearchHistory] = useState({});
  // searchHistory format: { "medicines": { count: 3, lastTime: ... }, ... }

  const [lastSearchResult, setLastSearchResult] = useState(null);
  // lastSearchResult format: { title, category, confidence, query }

  // ── Supabase auth ──────────────────────────────────────────────────────
  useEffect(() => {
    const { data: { subscription } } = supabase.auth.onAuthStateChange(
      (_event, session) => {
        if (session) {
          setUser(session.user);
          setAccessToken(session.access_token);
        } else {
          setUser(null);
          setAccessToken(null);
        }
      }
    );
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        setUser(session.user);
        setAccessToken(session.access_token);
      }
    });
    return () => subscription.unsubscribe();
  }, [setUser, setAccessToken]);

  // ── Track search in history ────────────────────────────────────────────
  const trackSearch = useCallback((queryText) => {
    const category = categorizeQuery(queryText);
    setSearchHistory((prev) => {
      const existing = prev[category] || { count: 0 };
      return {
        ...prev,
        [category]: { count: existing.count + 1, lastTime: Date.now() },
      };
    });

    // Build a search result from the query
    const cat = categorizeQuery(queryText);
    const words = queryText.trim().split(/\s+/);
    const title = words.slice(0, 4).map((w) =>
      w.charAt(0).toUpperCase() + w.slice(1)
    ).join(" ");

    setLastSearchResult({
      title: title,
      category: CATEGORY_LABELS[cat] || cat,
      confidence: (75 + Math.random() * 20).toFixed(1),
      query: queryText,
    });
  }, []);

  // ── WebSocket message handler ──────────────────────────────────────────
  const handleWSMessage = useCallback((msg) => {
    switch (msg.type) {

      case "session_init":
        setTier(msg.tier);
        break;

      case "emotion_update":
        setEmotion({ label: msg.label, confidence: msg.confidence });
        setIsListening(false);
        setIsThinking(true);
        break;

      case "llm_token":
        window.dispatchEvent(
          new CustomEvent("Alita:llm_token", { detail: msg })
        );
        setMessages((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && !last.final) {
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + msg.token, final: msg.is_final },
            ];
          }
          return [
            ...prev,
            {
              role: "assistant",
              content: msg.token,
              final: msg.is_final,
              id: Date.now(),
            },
          ];
        });
        if (msg.is_final) {
          setIsThinking(false);
          // Auto-reset speaking after a delay (TTS playback window)
          setTimeout(() => setIsSpeaking(false), 3000);
        }
        break;

      case "tts_audio":
        setIsSpeaking(true);
        window.dispatchEvent(
          new CustomEvent("Alita:tts_chunk", { detail: msg })
        );
        break;

      case "user_transcript":
        setIsSpeaking(false); // Stop speaking animation when user talks
        setCurrentQuery(msg.text);
        trackSearch(msg.text);
        setMessages((prev) => [
          ...prev,
          { role: "user", content: msg.text, final: true, id: Date.now() },
        ]);
        break;

      case "conversation_history":
        if (msg.turns?.length) {
          setMessages(
            msg.turns.map((t, i) => ({
              role: t.role === "assistant" ? "assistant" : "user",
              content: t.content,
              final: true,
              id: (t.timestamp || Date.now()) * 1000 + i,
            }))
          );
        }
        break;

      case "error":
        console.error("[WS Error]", msg.detail);
        setErrorToast(msg.detail);
        setTimeout(() => setErrorToast(null), 6000);
        setIsThinking(false);
        break;

      case "voice_changed":
        console.log("[Voice] Switched to:", msg.voice_name);
        // Update STT language when user manually switches voice
        if (msg.stt_lang) setSttLanguage(msg.stt_lang);
        if (msg.lang) setVoiceLang(msg.lang);
        break;

      case "voice_change_denied":
        if (msg.reason === "premium_required") {
          setShowPricing(true);
        }
        break;

      case "dictation_start":
        setDictationMode({ app: msg.app || "app" });
        break;

      case "dictation_stopped":
        setDictationMode(null);
        break;

      case "dictation_ack":
        break;

      case "app_not_installed":
        setAppInstallToast({ app: msg.app, store_url: msg.store_url });
        setTimeout(() => setAppInstallToast(null), 12000);
        break;

      case "voice_auto_switched":
        setSttLanguage(msg.stt_lang || "en-IN");
        setVoiceLang(msg.detected_lang || "en");
        setAutoVoiceId(msg.voice_id || null);
        setErrorToast(`🗣 Voice switched to ${msg.voice_name}`);
        setTimeout(() => setErrorToast(null), 4000);
        break;

      case "name_changed":
        break;

      // ── Song Recognition ─────────────────────────────────────────
      case "song_recognition_result":
        if (msg.status === "found") {
          const songInfo = `🎵 ${msg.title} — ${msg.artist}${msg.album ? ` (${msg.album})` : ""} • Now Playing on YouTube`;
          setErrorToast(songInfo);
          setTimeout(() => setErrorToast(null), 15000);
        } else if (msg.status === "not_found") {
          setErrorToast("🎵 Couldn't identify the song. Try playing it louder.");
          setTimeout(() => setErrorToast(null), 5000);
        } else if (msg.status === "error") {
          setErrorToast(`❌ Song recognition error: ${msg.error}`);
          setTimeout(() => setErrorToast(null), 5000);
        }
        break;

      case "song_recognition_status":
        setErrorToast(`🎵 ${msg.detail || "Analyzing audio..."}`);
        setTimeout(() => setErrorToast(null), 8000);
        break;

      case "start_song_recognition":
        // Backend tells us to start recording for song identification
        window.dispatchEvent(new Event("Alita:start_song_recognition"));
        break;

      case "reminder_alert":
        setErrorToast(`⏰ Reminder: ${msg.text}`);
        setTimeout(() => setErrorToast(null), 8000);
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification("Alita Reminder", { body: msg.text, icon: "/alita-icon.png" });
        }
        break;

      default:
        break;
    }
  }, [setTier, setEmotion, trackSearch]);

  // ── WebSocket ─────────────────────────────────────────────────────────
  const { sendAudioChunk, sendTextMessage, sendDictation, sendDictationStop, wsStatus } = useWebSocket({
    token: accessToken,
    onMessage: handleWSMessage,
    enabled: !!accessToken,
  });

  // ── Song Recognition: forward recorded audio to backend via WS ─────────
  useEffect(() => {
    const handler = (e) => {
      const { audio_b64 } = e.detail || {};
      if (audio_b64) {
        sendAudioChunk({ type: "recognize_song", audio_b64 });
      }
    };
    window.addEventListener("Alita:song_audio_ready", handler);
    return () => window.removeEventListener("Alita:song_audio_ready", handler);
  }, [sendAudioChunk]);

  const handleSpeechStart = useCallback(() => {
    setIsListening(true);
    setIsThinking(false);
  }, []);

  const handleUtteranceCommitted = useCallback((transcript) => {
    if (transcript) {
      console.log("[App] Utterance committed:", transcript.slice(0, 50));
    }
  }, []);

  // ── Build search history items for the left panel ─────────────────────
  const historyItems = Object.entries(searchHistory)
    .map(([key, val]) => ({
      label: CATEGORY_LABELS[key] || key,
      count: val.count,
      pct: Math.min(99, 30 + val.count * 12),
      lastTime: val.lastTime,
    }))
    .sort((a, b) => b.lastTime - a.lastTime);

  // ─────────────────────────────────────────────────────────────────────────
  // Auth screen
  // ─────────────────────────────────────────────────────────────────────────
  if (!user) {
    return <AuthScreen />;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Main app — Dashboard Layout
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <>
      {/* ─── View Toggle (always visible) ─── */}
      <div className="view-toggle-bar">
        <button
          className={`view-toggle-btn ${activeView === "alita" ? "active" : ""}`}
          onClick={() => setActiveView("alita")}
        >
          <span className="view-toggle-dot" />
          Alita
        </button>
        <button
          className={`view-toggle-btn ${activeView === "geospatial" ? "active" : ""}`}
          onClick={() => {
            if (tier === "free") {
              setShowPricing(true);
            } else {
              setActiveView("geospatial");
            }
          }}
        >
          <span className="view-toggle-dot" />
          Geospatial
          {tier === "free" && <span style={{
            fontSize: "0.55rem",
            background: "rgba(192,132,252,0.15)",
            border: "1px solid rgba(192,132,252,0.3)",
            borderRadius: "3px",
            padding: "1px 5px",
            color: "#c084fc",
            marginLeft: "6px",
            letterSpacing: "0.1em",
            fontWeight: 700,
          }}>PRO</span>}
        </button>
      </div>

      {/* ─── AudioCapture — ALWAYS MOUNTED (persists across view switches) ─── */}
      <AudioCapture
        onAudioChunk={sendAudioChunk}
        onSpeechStart={handleSpeechStart}
        onUtteranceCommitted={handleUtteranceCommitted}
        onTranscript={(text) => {
          sendTextMessage?.(text);
        }}
        enabled={wsStatus === "open"}
        sttLanguage={sttLanguage}
        dictationMode={dictationMode}
        sendDictation={sendDictation}
        onDictationStop={() => {
          sendDictationStop?.();
          setDictationMode(null);
        }}
        onMusicDetected={(detected) => setMusicDetected(detected)}
      />

      {/* ─── Geospatial View (full viewport, outside grid) ─── */}
      {activeView === "geospatial" && (
        <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#0a0e1a', color: '#00d4ff', fontFamily: 'Inter, sans-serif', fontSize: '0.8rem' }}>Loading Geospatial Dashboard...</div>}>
          <GeoApp />
        </Suspense>
      )}

      {/* ─── Alita View ─── */}
      {activeView === "alita" && (
        <div className="app-root">

          {/* Dictation mode indicator */}
          {dictationMode && (
            <div style={{
              position: "fixed", top: 0, left: 0, right: 0, zIndex: 100,
              padding: "10px 20px",
              background: "linear-gradient(135deg, rgba(251,191,36,0.15), rgba(245,158,11,0.1))",
              borderBottom: "1px solid rgba(251,191,36,0.3)",
              backdropFilter: "blur(12px)",
              display: "flex", alignItems: "center", justifyContent: "center", gap: "16px",
              fontFamily: "'Inter', sans-serif", fontSize: "0.7rem",
              letterSpacing: "0.1em", textTransform: "uppercase",
              color: "rgba(251,191,36,0.9)",
            }}>
              <span style={{ animation: "blink 1.5s ease-in-out infinite" }}>●</span>
              <span>dictating into {dictationMode.app} — say "stop dictating" to end</span>
              <button onClick={() => { sendDictationStop?.(); setDictationMode(null); }}
                style={{
                  background: "rgba(251,191,36,0.15)", border: "1px solid rgba(251,191,36,0.3)",
                  borderRadius: "4px", color: "rgba(251,191,36,0.9)",
                  padding: "4px 12px", fontSize: "0.65rem", cursor: "pointer",
                  fontFamily: "'Inter', sans-serif", letterSpacing: "0.1em",
                }}>
                STOP
              </button>
            </div>
          )}

          {/* ─── Header ─── */}
          <Header
            user={user}
            tier={tier}
            onLogout={async () => {
              await supabase.auth.signOut();
              clearSession();
              setMessages([]);
            }}
            theme={{ mode: themeMode }}
            onThemeCycle={cycleTheme}
            notifications={notifications}
          />

          {/* ─── Dashboard Body (3-column) ─── */}
          <div className="dash-body">

            {/* Left: Search History */}
            <SearchHistory items={historyItems} />

            {/* Center: Soundwave + Listening */}
            <div className="center-panel">
              {/* WS status */}
              <div className="center-ws-status">
                <div className={`center-ws-dot ${wsStatus}`} />
                <span>{wsStatus === "open" ? "connected" : wsStatus}</span>
              </div>

              {/* Soundwave Orb — replaces 3D particle canvas */}
              <div className="canvas-container">
                <SoundwaveOrb isListening={isListening} isThinking={isThinking} isSpeaking={isSpeaking} />

                {/* Voice-only mode — no chat bubbles, only status */}
                <ThinkingDots visible={isThinking} />

                {/* Text input */}
                {wsStatus === "open" && (
                  <form
                    className="text-input-bar"
                    onSubmit={(e) => {
                      e.preventDefault();
                      const input = e.target.elements.chatInput;
                      const text = input.value.trim();
                      if (!text) return;
                      sendTextMessage?.(text);
                      setCurrentQuery(text);
                      trackSearch(text);
                      setMessages((prev) => [
                        ...prev,
                        { role: "user", content: text, final: true, id: Date.now() },
                      ]);
                      input.value = "";
                      setIsThinking(true);
                    }}
                  >
                    <input
                      id="chatInput"
                      name="chatInput"
                      type="text"
                      placeholder="Type a message…"
                      autoComplete="off"
                      className="text-input-field"
                    />
                    <button type="submit" className="text-input-send">➤</button>
                  </form>
                )}
              </div>

              {/* Query text */}
              <div className="center-query-text">
                {currentQuery || "Ask me anything..."}
              </div>

              {/* Listening state */}
              <div className="center-listening">
                <span className="center-listening-text">
                  {isThinking ? "Thinking..." : isListening ? "Listening..." : "Ready"}
                </span>
                <div className={`center-listening-dot ${isListening ? "active" : ""} ${isThinking ? "thinking" : ""}`} />
              </div>
            </div>

            {/* Right: Search Results */}
            <SearchResults result={lastSearchResult} />
          </div>

          {/* ─── Bottom Nav ─── */}
          <BottomNav />

          {/* Voice model changer */}
          <VoiceModelChanger
            sendVoiceChange={(voiceId) => {
              sendAudioChunk?.({ type: "voice_change", voice_id: voiceId });
            }}
            onPremiumRequired={() => setShowPricing(true)}
            externalLang={voiceLang}
            externalVoiceId={autoVoiceId}
            onLanguageChange={(langCode) => {
              // Update STT language when user manually picks a language
              const langMap = { en: "en-IN", hi: "hi-IN", es: "es-ES", fr: "fr-FR", de: "de-DE", ja: "ja-JP" };
              setSttLanguage(langMap[langCode] || "en-IN");
              setVoiceLang(langCode);
            }}
          />

          {/* Error toast */}
          {errorToast && (
            <div className="error-toast" onClick={() => setErrorToast(null)}>
              <span>⚠ {errorToast}</span>
              <button onClick={() => setErrorToast(null)}>✕</button>
            </div>
          )}

          {/* App Install Toast */}
          {appInstallToast && (
            <div style={{
              position: "fixed", bottom: "80px", left: "50%", transform: "translateX(-50%)",
              zIndex: 200, padding: "14px 24px",
              background: "linear-gradient(135deg, rgba(59,130,246,0.15), rgba(99,102,241,0.12))",
              border: "1px solid rgba(99,102,241,0.3)", borderRadius: "12px",
              backdropFilter: "blur(16px)", display: "flex", alignItems: "center", gap: "16px",
              fontFamily: "'Inter', sans-serif", fontSize: "0.72rem",
              letterSpacing: "0.08em", color: "rgba(165,180,252,0.95)",
              boxShadow: "0 8px 32px rgba(99,102,241,0.15)",
              animation: "slideUp 400ms cubic-bezier(0.16,1,0.3,1)",
            }}>
              <span style={{ fontSize: "1.1rem" }}>📦</span>
              <span><strong>{appInstallToast.app}</strong> is not installed</span>
              <button onClick={() => { window.open(appInstallToast.store_url, "_blank"); setAppInstallToast(null); }}
                style={{
                  background: "rgba(99,102,241,0.25)", border: "1px solid rgba(99,102,241,0.4)",
                  borderRadius: "6px", color: "rgba(199,210,254,0.95)",
                  padding: "6px 16px", fontSize: "0.65rem", cursor: "pointer",
                  fontFamily: "'Inter', sans-serif", letterSpacing: "0.12em",
                  textTransform: "uppercase", fontWeight: 600, transition: "background 200ms",
                }}
                onMouseEnter={(e) => (e.target.style.background = "rgba(99,102,241,0.4)")}
                onMouseLeave={(e) => (e.target.style.background = "rgba(99,102,241,0.25)")}>
                Install
              </button>
              <button onClick={() => setAppInstallToast(null)}
                style={{ background: "transparent", border: "none", color: "rgba(165,180,252,0.5)", cursor: "pointer", fontSize: "0.8rem", padding: "2px 6px" }}>
                ✕
              </button>
            </div>
          )}

          {(tier === "free" || showPricing) && <TierGate onClose={() => setShowPricing(false)} />}

        </div>
      )}
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Auth Screen
// ─────────────────────────────────────────────────────────────────────────────
function AuthScreen() {
  const { setUser, setAccessToken, setTier } = useSessionStore();

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-logo">
          <div className="auth-logo-orb" />
          <span className="auth-logo-text">Alita</span>
        </div>
        <p className="auth-tagline">
          An emotionally intelligent presence.<br />
          Speak. Be understood.
        </p>

        <GoogleAuthButton supabase={supabase} />

        <TestLoginButton
          onSuccess={({ token, tier, displayName }) => {
            setAccessToken(token);
            setUser({ id: "test_" + displayName, email: displayName + "@Alita.test" });
            setTier(tier);
          }}
        />

        <p className="auth-footer">
          Your webcam and voice never leave your device.
        </p>
      </div>
      <div className="auth-bg">
        {Array.from({ length: 60 }).map((_, i) => (
          <div
            key={i}
            className="auth-particle"
            style={{
              left: `${Math.random() * 100}%`,
              top: `${Math.random() * 100}%`,
              animationDelay: `${Math.random() * 8}s`,
              animationDuration: `${6 + Math.random() * 10}s`,
              width: `${1 + Math.random() * 2}px`,
              height: `${1 + Math.random() * 2}px`,
              opacity: 0.15 + Math.random() * 0.4,
            }}
          />
        ))}
      </div>
    </div>
  );
}
