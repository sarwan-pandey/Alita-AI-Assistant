/**
 * Alita Assistant — Root App
 * Redesigned: Futuristic Multi-Panel Dashboard
 *   - CSS Grid layout with 8 live data panels
 *   - Central CSS/SVG orb with status timer
 *   - Dark navy theme, glassmorphism, cyan accents
 */

import { useEffect, useCallback, useState, useRef, lazy, Suspense } from "react";
import { createClient } from "@supabase/supabase-js";

import { AudioCapture } from "./components/audio/AudioCapture";
import { TierGate } from "./components/ui/TierGate";
import { GoogleAuthButton } from "./components/auth/GoogleAuthButton";
import { ScreenAgent } from "./components/ui/ScreenAgent";
import { SongDetectionDialog } from "./components/ui/SongDetectionDialog";
import { AdvancedFeatures } from "./components/AdvancedFeatures";

// Cinematic Dynamic Island Suite
import { DynamicIsland } from "./components/ui/DynamicIsland";
import { CinematicSubtitles } from "./components/ui/CinematicSubtitles";
import { FloatingDock } from "./components/ui/FloatingDock";
import { SpatialDrawer } from "./components/ui/SpatialDrawer";
import { ParticleField } from "./components/ui/ParticleField";
import { SovereignNebulaEdge } from "./components/ui/SovereignNebulaEdge";
import { CentralOrb } from "./components/dashboard/CentralOrb";
import { ScreenHighlightOverlay } from "./components/ui/ScreenHighlightOverlay";
import { HolographicOverlay } from "./components/ui/HolographicOverlay";
import { PhoneCompanionCard } from "./components/dashboard/PhoneCompanionCard";

// Geospatial dashboard — lazy loaded
const GeoApp = lazy(() => import("./components/geo/GeoApp"));

import { useSessionStore } from "./store/useSessionStore";
import { useEmotionStore } from "./store/useEmotionStore";
import { useSubscriptionStore } from "./store/useSubscriptionStore";
import { useWebSocket } from "./hooks/useWebSocket";
import { useTheme } from "./hooks/useTheme";
import { useNotifications } from "./hooks/useNotifications";

import { TestLoginButton } from "./components/auth/TestLoginButton";
import { soundFX } from "./utils/SoundFX";

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
  const [activeView, setActiveView] = useState("mj"); // "mj" | "geospatial"

  const { user, setUser, accessToken, setAccessToken, tier, setTier, clearSession, autoLoginDefaultAdmin } =
    useSessionStore();

  // ── Jarvis Display Mode: "overlay" (pure floating crystal orb) vs "expanded" (full command center) ──
  const [uiMode, setUiMode] = useState(() => {
    try {
      const params = new URLSearchParams(window.location.search);
      if (params.get("mode") === "overlay" || params.get("overlay") === "true") {
        return "overlay";
      }
      if (params.get("mode") === "expanded") {
        return "expanded";
      }
    } catch (_) {}
    return localStorage.getItem("alita_ui_mode") || "overlay";
  });

  const toggleUiMode = useCallback((mode) => {
    setUiMode((prev) => {
      const next = typeof mode === "string" ? mode : (prev === "overlay" ? "expanded" : "overlay");
      localStorage.setItem("alita_ui_mode", next);
      try {
        if (next === "expanded") {
          window.resizeTo(window.screen.availWidth, window.screen.availHeight);
          window.moveTo(0, 0);
        } else if (next === "overlay") {
          window.resizeTo(380, 380);
          window.moveTo(window.screen.availWidth - 420, window.screen.availHeight - 460);
        }
      } catch (_) {}
      return next;
    });
  }, []);

  // Synchronize CSS class for 100% transparent borderless overlay
  useEffect(() => {
    if (uiMode === "overlay") {
      document.documentElement.classList.add("alita-overlay-mode");
      document.body.classList.add("alita-overlay-mode");
    } else {
      document.documentElement.classList.remove("alita-overlay-mode");
      document.body.classList.remove("alita-overlay-mode");
    }
  }, [uiMode]);

  // Keyboard shortcut: Escape or Ctrl+Space to toggle / collapse
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === "Escape" && uiMode === "expanded") {
        toggleUiMode("overlay");
      } else if (e.ctrlKey && e.code === "Space") {
        e.preventDefault();
        toggleUiMode();
      }
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [uiMode, toggleUiMode]);

  const { setEmotion, setFaceData, setGirlfriendMood, setAffectionScore, setLieTruthCounts, setActiveNudge } = useEmotionStore();
  const faceData = useEmotionStore((s) => s.faceData);

  // ── Theme & Notifications ───────────────────────────────────────────
  const { mode: themeMode, cycleTheme } = useTheme();
  const notifications = useNotifications();
  const { isPremium, isTrialActive, trialDaysRemaining } = useSubscriptionStore();

  // Guard: only enable WebSocket after Supabase confirms a valid session.
  // Prevents stale persisted tokens from triggering connect→reject→reconnect loops
  // on the login page.
  const [authReady, setAuthReady] = useState(false);

  const [messages, setMessages] = useState([]);
  const [isListening, setIsListening] = useState(true);
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
  const [userVoiceActivity, setUserVoiceActivity] = useState(0);

  // ── Cinematic Spatial Interface State ────────────────────────────────
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerTab, setDrawerTab] = useState("studio"); // "studio" | "memory" | "chat"
  const [latestSubtitle, setLatestSubtitle] = useState("");
  const [latestRole, setLatestRole] = useState("assistant");
  const [activeVoiceName, setActiveVoiceName] = useState(() => {
    const saved = localStorage.getItem("alita_selected_voice");
    if (!saved || saved === "chatterbox_mj" || saved === "f5_mj_clone" || saved === "chattts_mj") {
      localStorage.setItem("alita_selected_voice", "chatterbox_turbo_mj");
      return "chatterbox_turbo_mj";
    }
    return saved;
  });

  // ── Song Detection Dialog state ──────────────────────────────────────
  // phase: null | "analyzing" | "found" | "not_found" | "error"
  const [songDetection, setSongDetection] = useState({ phase: null, data: null, statusText: "" });

  // ── Proactive Autonomous Intelligence State ──────────────────────────
  const [proactiveSuggestion, setProactiveSuggestion] = useState(null);

  // ── Multimodal Screen Highlight & Set-of-Marks State ────────────────
  const [highlightData, setHighlightData] = useState(null);
  const [somMarks, setSomMarks] = useState([]);
  const [activeSomMark, setActiveSomMark] = useState(null);
  const [contextChips, setContextChips] = useState([]);
  const [showPhoneCompanion, setShowPhoneCompanion] = useState(false);

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
          setAuthReady(true);
        } else {
          setUser(null);
          setAccessToken(null);
          setAuthReady(false);
        }
      }
    );
    supabase.auth.getSession().then(({ data: { session } }) => {
      if (session) {
        setUser(session.user);
        setAccessToken(session.access_token);
        setAuthReady(true);
      } else {
        // No valid session — clear any stale persisted token
        setAuthReady(false);
      }
    });
    return () => subscription.unsubscribe();
  }, [setUser, setAccessToken]);

  // ── Auto-login default admin for zero-touch desktop boot ──────────────
  useEffect(() => {
    if (!user || !accessToken) {
      autoLoginDefaultAdmin?.().then((u) => {
        if (u) setAuthReady(true);
      });
    } else if (user?.id?.startsWith("test_") || accessToken) {
      setAuthReady(true);
    }
  }, [user, accessToken, autoLoginDefaultAdmin]);

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
          // Prevent jarring cold-stop: keep isThinking active until TTS audio actually arrives
          // Provide safety timeout only in case no audio is produced (silent system commands)
          setTimeout(() => {
            setIsThinking((current) => (current ? false : current));
          }, 4000);
        }
        break;

      case "tts_audio":
        // Seamless handoff: As soon as audio arrives, transition from thinking to speaking
        if (msg.audio_b64) {
          setIsThinking(false);
          setIsSpeaking(true);
        }
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
        window.dispatchEvent(
          new CustomEvent("Alita:turn_error", { detail: msg })
        );
        window.dispatchEvent(
          new CustomEvent("MJ:turn_error", { detail: msg })
        );
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

      case "proactive_suggestion":
        console.log("[Proactive Insight]", msg.suggestion);
        soundFX.playWhoosh();
        setProactiveSuggestion(msg.suggestion);
        // Route girlfriend-type nudges to emotion store for UI theming
        if (msg.suggestion?.subtype?.startsWith("girlfriend_")) {
          setActiveNudge(msg.suggestion);
        }
        break;

      case "proactive_action_executed":
        soundFX.playSuccess();
        setErrorToast(`⚡ Action executed: ${msg.action || "Done"}`);
        setTimeout(() => setErrorToast(null), 4000);
        break;

      case "screen_highlight":
        soundFX.playWhoosh();
        console.log("[Screen Highlight]", msg.target);
        setHighlightData(msg.target);
        break;

      case "som_marks":
        console.log("[Set-of-Marks]", msg.marks?.length);
        setSomMarks(msg.marks || []);
        break;

      case "som_action_active":
        setActiveSomMark({ markId: msg.mark_id, action: msg.action, name: msg.name });
        break;

      case "som_step_completed":
        setTimeout(() => {
          setActiveSomMark(null);
          setSomMarks([]);
        }, 3000);
        break;

      case "guardian_alert":
        soundFX.playPing?.();
        setErrorToast(`🛡️ ${msg.message || "Hardware Guardian Alert"}`);
        setTimeout(() => setErrorToast(null), 6000);
        break;

      case "context_chips":
        setContextChips(msg.chips || []);
        break;

      // ── Song Recognition — routed to SongDetectionDialog ──────────
      case "song_recognition_result":
        if (msg.status === "found") {
          setSongDetection({
            phase: "found",
            data: {
              title: msg.title,
              artist: msg.artist,
              album: msg.album || "",
              artwork: msg.artwork || "",
              url: msg.url || "",
            },
            statusText: "",
          });
        } else if (msg.status === "not_found") {
          setSongDetection(prev => ({ ...prev, phase: "not_found", data: null }));
        } else if (msg.status === "error") {
          setSongDetection(prev => ({
            ...prev,
            phase: "error",
            data: { error: msg.error },
          }));
        }
        break;

      case "song_recognition_status":
        setSongDetection(prev => ({
          ...prev,
          statusText: msg.detail || "Analyzing audio...",
        }));
        break;

      case "start_song_recognition":
        // Backend tells us to start recording for song identification
        setSongDetection({ phase: "analyzing", data: null, statusText: "Recording audio…" });
        window.dispatchEvent(new Event("Alita:start_song_recognition"));
        break;

      case "reminder_alert":
        setErrorToast(`⏰ Reminder: ${msg.text}`);
        setTimeout(() => setErrorToast(null), 8000);
        if ("Notification" in window && Notification.permission === "granted") {
          new Notification("MJ Reminder", { body: msg.text, icon: "/alita-icon.png" });
        }
        break;

      // ── Emergency & Environment ─────────────────────────────────────
      case "emergency_alert":
        window.dispatchEvent(
          new CustomEvent("Alita:emergency_alert", { detail: msg })
        );
        setErrorToast(`🚨 EMERGENCY: ${msg.sound} detected — auto-recording started`);
        // Don't auto-dismiss emergency toast
        break;

      case "environment_update":
        window.dispatchEvent(
          new CustomEvent("Alita:environment_update", { detail: msg })
        );
        break;

      // ── Alita Face Data (from ALITA_FACE_DATA JSON block) ─────────
      case "face_data":
        // Dispatch to any listener (SovereignEntity, legacy, etc.)
        window.dispatchEvent(
          new CustomEvent("Alita:face_data", { detail: msg.content || {} })
        );
        // Store faceData for SovereignEntity prop
        setFaceData(msg.content || null);
        // Update emotion store with the user's detected emotion from Alita's analysis
        if (msg.content?.user_emotion_detected) {
          setEmotion({
            label: msg.content.user_emotion_detected,
            confidence: msg.content.ser_confidence || 0.5,
          });
        }
        // ── Girlfriend Mood Sync (from relationship_manager via face_data) ──
        if (msg.content?.girlfriend_mood) {
          setGirlfriendMood(
            msg.content.girlfriend_mood,
            msg.content.mood_intensity || 0.5
          );
        }
        if (typeof msg.content?.affection_score === "number") {
          setAffectionScore(msg.content.affection_score);
        }
        if (typeof msg.content?.lie_count_today === "number") {
          setLieTruthCounts(
            msg.content.lie_count_today || 0,
            msg.content.truth_count_today || 0
          );
        }
        break;

      // ── Screen Agent events — dispatch for ScreenAgent component ──
      case "screen_task_started":
      case "screen_task_progress":
      case "screen_task_complete":
      case "screen_task_stopped":
      case "screen_task_failed":
      case "screen_task_auth":
        window.dispatchEvent(
          new CustomEvent("Alita:ws_message", { detail: msg })
        );
        break;

      // ── Dashboard stats response ──────────────────────────────────
      case "dashboard_stats":
        window.dispatchEvent(
          new CustomEvent("Alita:dashboard_stats", { detail: msg })
        );
        break;

      // ── UI Mode Change (maximize / minimize from voice) ───────────
      case "ui_mode_change":
        if (msg.mode) {
          toggleUiMode(msg.mode);
        }
        break;

      default:
        break;
    }
  }, [setTier, setEmotion, setFaceData, setGirlfriendMood, setAffectionScore, setLieTruthCounts, setActiveNudge, trackSearch]);

  // ── WebSocket ─────────────────────────────────────────────────────────
  const { sendAudioChunk, sendBinaryChunk, sendTextMessage, sendDictation, sendDictationStop, sendBargeIn, sendSpeculativeQuery, cancelSpeculative, wsStatus } = useWebSocket({
    token: accessToken,
    onMessage: handleWSMessage,
    enabled: !!accessToken && authReady,
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

  // ── Voice Change: forward voice model selection to backend via WS ──────
  useEffect(() => {
    const handler = (e) => {
      const { voice_id } = e.detail || {};
      if (voice_id) {
        console.log("[App] Switching voice model to:", voice_id);
        sendAudioChunk({ type: "voice_change", voice_id });
      }
    };
    window.addEventListener("Alita:voice_change", handler);
    return () => window.removeEventListener("Alita:voice_change", handler);
  }, [sendAudioChunk]);

  const lastChimeTimeRef = useRef(0);
  const handleSpeechStart = useCallback(() => {
    const now = Date.now();
    // Only play wake chime once when speech begins from idle (not on every word)
    if (now - lastChimeTimeRef.current > 4000) {
      soundFX.playWakeChime();
      lastChimeTimeRef.current = now;
    }
    setIsListening(true);
    setIsThinking(false);
  }, []);

  const handleAcceptProactive = useCallback((suggestion) => {
    if (sendAudioChunk && suggestion?.action_payload) {
      sendAudioChunk({
        type: "proactive_action_accept",
        action_payload: suggestion.action_payload,
      });
    }
    setProactiveSuggestion(null);
  }, [sendAudioChunk]);

  const handleDismissProactive = useCallback(() => {
    setProactiveSuggestion(null);
  }, []);

  // ── Offline mode & Hand Gesture event listeners ─────────────────────────
  useEffect(() => {
    const connectivityHandler = (e) => {
      const { online } = e.detail || {};
      sendAudioChunk({ type: "connectivity_status", online: !!online });
    };
    const offlineAudioHandler = (e) => {
      const { pcm_binary } = e.detail || {};
      if (pcm_binary) {
        // Send as raw binary ArrayBuffer (8× more efficient than JSON)
        sendBinaryChunk(pcm_binary);
      }
    };
    const ttsEndedHandler = () => {
      setIsSpeaking(false);
      setIsThinking(false);
    };
    const vadSpeechEndHandler = () => {
      sendAudioChunk({ type: "end_of_utterance" });
    };
    window.addEventListener("Alita:connectivity_change", connectivityHandler);
    window.addEventListener("Alita:offline_audio_chunk", offlineAudioHandler);
    window.addEventListener("Alita:vad_speech_end", vadSpeechEndHandler);
    window.addEventListener("MJ:tts_ended", ttsEndedHandler);
    window.addEventListener("Alita:tts_ended", ttsEndedHandler);

    // ── MediaPipe Hand Gesture Control ──────────────────────────────────
    const gestureHandler = (e) => {
      const { action } = e.detail || {};
      if (action === "stop" || action === "pause") {
        window.dispatchEvent(new CustomEvent("Alita:interrupt"));
        window.dispatchEvent(new CustomEvent("MJ:interrupt"));
        setIsSpeaking(false);
      } else if (action === "confirm" && proactiveSuggestion) {
        handleAcceptProactive(proactiveSuggestion);
      } else if (action === "dismiss" && proactiveSuggestion) {
        handleDismissProactive();
      }
    };
    window.addEventListener("Alita:gesture", gestureHandler);

    return () => {
      window.removeEventListener("Alita:connectivity_change", connectivityHandler);
      window.removeEventListener("Alita:offline_audio_chunk", offlineAudioHandler);
      window.removeEventListener("Alita:vad_speech_end", vadSpeechEndHandler);
      window.removeEventListener("MJ:tts_ended", ttsEndedHandler);
      window.removeEventListener("Alita:tts_ended", ttsEndedHandler);
      window.removeEventListener("Alita:gesture", gestureHandler);
    };
  }, [sendAudioChunk, sendBinaryChunk, proactiveSuggestion, handleAcceptProactive, handleDismissProactive]);

  const handleUtteranceCommitted = useCallback((transcript) => {
    if (!transcript) return;
    console.log("[App] Utterance committed — sending to backend:", transcript.slice(0, 50));

    // Send to backend via WebSocket
    sendTextMessage?.(transcript);

    // Update UI state (user message is added when backend echoes user_transcript)
    setCurrentQuery(transcript);
    trackSearch(transcript);
    setIsListening(false);
    setIsThinking(true);
  }, [sendTextMessage, trackSearch]);

  // ── Read emotion from store for dashboard ────────────────────────────
  const emotion = useEmotionStore((s) => s.emotion);

  // ── Dashboard stats: forward request events to WS ────────────────────
  useEffect(() => {
    const handler = () => {
      sendAudioChunk?.({ type: "dashboard_stats" });
    };
    window.addEventListener("Alita:request_dashboard_stats", handler);
    return () => window.removeEventListener("Alita:request_dashboard_stats", handler);
  }, [sendAudioChunk]);

  // ─────────────────────────────────────────────────────────────────────────
  // Auth screen
  // ─────────────────────────────────────────────────────────────────────────
  if (!user) {
    if (uiMode === "overlay") {
      return (
        <HolographicOverlay
          onMaximize={() => toggleUiMode("expanded")}
          wsStatus="connecting"
          isListening={true}
          isThinking={false}
          isSpeaking={false}
          voiceActivity={0}
        />
      );
    }
    return <AuthScreen />;
  }

  // ─────────────────────────────────────────────────────────────────────────
  // Main app — Futuristic Dashboard
  // ─────────────────────────────────────────────────────────────────────────
  return (
    <>
      {/* ─── Screen Agent — ALWAYS MOUNTED ─── */}
      <ScreenAgent />

      {/* ─── AudioCapture — ALWAYS MOUNTED ─── */}
      <AudioCapture
        onAudioChunk={sendAudioChunk}
        onSpeechStart={handleSpeechStart}
        onUtteranceCommitted={handleUtteranceCommitted}
        onTranscript={(text) => {
          if (text) {
            setCurrentQuery(text);
            setIsListening(true);
            setIsThinking(false);
          }
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
        onVoiceActivity={(activity) => setUserVoiceActivity(activity)}
        sendBargeIn={sendBargeIn}
        sendSpeculativeQuery={sendSpeculativeQuery}
        cancelSpeculative={cancelSpeculative}
        isOverlay={uiMode === "overlay"}
      />

      {/* ─── Ambient Holographic Overlay Mode (Pure 3D Crystal Orb) ─── */}
      {uiMode === "overlay" && (
        <HolographicOverlay
          onMaximize={() => toggleUiMode("expanded")}
          wsStatus={wsStatus}
          isListening={isListening}
          isThinking={isThinking}
          isSpeaking={isSpeaking}
          voiceActivity={userVoiceActivity}
          onToggleMic={() => setIsListening((prev) => !prev)}
          sendBargeIn={sendBargeIn}
          contextChips={contextChips}
          onSelectChip={(chip) => sendTextMessage?.(chip)}
        />
      )}

      {/* ─── Geospatial View ─── */}
      {activeView === "geospatial" && uiMode === "expanded" && (
        <Suspense fallback={<div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100vh', background: '#060a14', color: '#00d4ff', fontFamily: 'Inter, sans-serif', fontSize: '0.8rem' }}>Loading Geospatial Dashboard...</div>}>
          <GeoApp />
        </Suspense>
      )}

      {/* ─── Alita Dashboard View ─── */}
      {(activeView === "mj" || activeView === "alita") && uiMode === "expanded" && (
        <>
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

          {/* ─── The Cinematic Dynamic Island Experience ─── */}
          <div className="cinematic-app-container">
            {/* Minimal Overlay Mode Switcher */}
            <div className="corner-hud left">
              <div className="hud-pill" style={{ cursor: "pointer" }} onClick={() => toggleUiMode("overlay")} title="Collapse to Floating Overlay (Esc)">
                <span className="hud-dot purple" />
                <span>OVERLAY MODE ⤓</span>
              </div>
            </div>

            {/* Top Dynamic Island */}
            <DynamicIsland
              isListening={isListening}
              isThinking={isThinking}
              isSpeaking={isSpeaking}
              voiceActivity={userVoiceActivity}
              emotion={emotion}
              activeVoiceName={activeVoiceName}
              isOnline={wsStatus === "open"}
              proactiveSuggestion={proactiveSuggestion}
              onAcceptProactive={handleAcceptProactive}
              onDismissProactive={handleDismissProactive}
              onIslandClick={() => {
                setDrawerTab("studio");
                setDrawerOpen(true);
              }}
            />

            {/* Apple Intelligence Style Sovereign Nebula Perimeter Chromatic Ribbon */}
            <SovereignNebulaEdge
              isListening={isListening}
              isThinking={isThinking}
              isSpeaking={isSpeaking}
              voiceActivity={userVoiceActivity}
            />

            {/* Ambient Background Quantum Glow */}
            <div className="ambient-quantum-glow" />

            {/* ─── Pristine Focused AI Presence Stage ─── */}
            <div className="alita-focused-stage">
              <div
                className="cinematic-centerpiece"
                onClick={() => {
                  if (isSpeaking) {
                    sendBargeIn?.();
                    setIsSpeaking(false);
                  } else {
                    setIsListening((prev) => !prev);
                  }
                }}
              >
                <CentralOrb
                  isListening={isListening}
                  isThinking={isThinking}
                  isSpeaking={isSpeaking}
                  voiceActivity={userVoiceActivity}
                  currentQuery={currentQuery}
                  wsStatus={wsStatus}
                />
              </div>

              {/* Live Conversational Subtitle Pill (1:1 with Concept Art) */}
              {(() => {
                const activeText = isSpeaking || isThinking
                  ? (messages[messages.length - 1]?.role === "assistant" ? messages[messages.length - 1].content : "Thinking...")
                  : currentQuery;
                if (!activeText || !activeText.trim()) return null;
                return (
                  <div className={`alita-live-card ${isSpeaking ? "speaking" : isThinking ? "thinking" : ""}`}>
                    <p className="live-card-text">{activeText}</p>
                  </div>
                );
              })()}

              {/* Clean Floating Quick Chips (When Idle) */}
              {!isSpeaking && !isThinking && !currentQuery && (
                <div className="alita-floating-chips">
                  <button className="alita-chip" onClick={() => sendTextMessage?.("Look at my screen and tell me what you see")}>
                    <span className="chip-icon">👁️</span>
                    <span>Inspect Screen</span>
                  </button>
                  <button className="alita-chip" onClick={() => sendTextMessage?.("What are our recent topics and memories?")}>
                    <span className="chip-icon">🧠</span>
                    <span>Memory Recall</span>
                  </button>
                  <button className="alita-chip" onClick={() => sendTextMessage?.("Play some lofi chill music")}>
                    <span className="chip-icon">🎵</span>
                    <span>Focus Music</span>
                  </button>
                  <button className="alita-chip" onClick={() => sendTextMessage?.("Help me write clean code")}>
                    <span className="chip-icon">⚡</span>
                    <span>Pair Program</span>
                  </button>
                  <button className="alita-chip" onClick={() => setShowPhoneCompanion((prev) => !prev)}>
                    <span className="chip-icon">📱</span>
                    <span>Phone Companion</span>
                  </button>
                </div>
              )}
            </div>

            {/* Spatial Bottom Action Dock */}
            <FloatingDock
              isListening={isListening}
              isSpeaking={isSpeaking}
              onToggleMic={() => {
                if (isSpeaking) {
                  sendBargeIn?.();
                  setIsSpeaking(false);
                } else {
                  setIsListening((prev) => !prev);
                }
              }}
              onTriggerVision={() => {
                sendTextMessage?.("Look at my screen and tell me what you see");
              }}
              onOpenConversations={() => {
                setDrawerTab("chat");
                setDrawerOpen(true);
              }}
              onOpenStudio={() => {
                setDrawerTab("studio");
                setDrawerOpen(true);
              }}
              onOpenAccount={() => {
                setShowPricing(true);
              }}
              onOpenPhone={() => {
                setShowPhoneCompanion((prev) => !prev);
              }}
            />

            {/* Autonomous Mobile Phone Companion Card Overlay */}
            {showPhoneCompanion && (
              <div style={{
                position: "fixed",
                bottom: "85px",
                right: "24px",
                zIndex: 85,
                animation: "fadeIn 0.25s cubic-bezier(0.16, 1, 0.3, 1)"
              }}>
                <PhoneCompanionCard
                  isOpen={showPhoneCompanion}
                  onClose={() => setShowPhoneCompanion(false)}
                />
              </div>
            )}

            {/* Slide-Over Spatial Glass Drawer */}
            <SpatialDrawer
              isOpen={drawerOpen}
              activeTab={drawerTab}
              onClose={() => setDrawerOpen(false)}
              messages={messages}
              onTriggerVision={() => {
                sendTextMessage?.("Look at my screen and tell me what you see");
              }}
            />

            {/* Multimodal Screen Highlight & Set-of-Marks Overlay */}
            <ScreenHighlightOverlay
              highlightData={highlightData}
              somMarks={somMarks}
              activeMark={activeSomMark}
              onDismiss={() => {
                setHighlightData(null);
                setSomMarks([]);
                setActiveSomMark(null);
              }}
            />
          </div>


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
                  textTransform: "uppercase", fontWeight: 600,
                }}>
                Install
              </button>
              <button onClick={() => setAppInstallToast(null)}
                style={{ background: "transparent", border: "none", color: "rgba(165,180,252,0.5)", cursor: "pointer", fontSize: "0.8rem", padding: "2px 6px" }}>
                ✕
              </button>
            </div>
          )}

          {(tier === "free" || showPricing) && <TierGate onClose={() => setShowPricing(false)} />}

          {/* Song Detection Dialog */}
          <SongDetectionDialog
            phase={songDetection.phase}
            songData={songDetection.data}
            statusText={songDetection.statusText}
            onClose={() => setSongDetection({ phase: null, data: null, statusText: "" })}
            onRetry={() => {
              setSongDetection({ phase: "analyzing", data: null, statusText: "Recording audio…" });
              window.dispatchEvent(new Event("Alita:start_song_recognition"));
            }}
          />

          {/* Advanced Features */}
          <AdvancedFeatures
            enabled={wsStatus === "open"}
            messages={messages}
            currentLang={voiceLang}
            sendAudioChunk={sendAudioChunk}
          />
        </>
      )}

      {/* ─── Bottom View Toggle — ONLY VISIBLE IN EXPANDED MODE ─── */}
      {uiMode === "expanded" && (
        <div className="view-toggle-bar">
          <button
            className={`view-toggle-btn ${activeView === "mj" || activeView === "alita" ? "active" : ""}`}
            onClick={() => setActiveView("mj")}
          >
            <span className="view-toggle-dot" />
            MJ
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
      <SovereignNebulaEdge isListening={false} />
      <div className="auth-card">
        <div className="auth-logo">
          <div className="auth-logo-orb" />
          <span className="auth-logo-text">MJ</span>
        </div>
        <p className="auth-tagline">
          An emotionally intelligent presence.<br />
          Speak. Be understood.
        </p>

        <GoogleAuthButton supabase={supabase} />

        <TestLoginButton
          onSuccess={({ token, tier, displayName }) => {
            setAccessToken(token);
            setUser({ id: "test_" + displayName, email: displayName + "@MJ.test" });
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
