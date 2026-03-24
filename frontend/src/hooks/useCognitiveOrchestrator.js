/**
 * useCognitiveOrchestrator — The Central Brain
 *
 * Fuses ALL sensor signals into intelligent automatic decisions.
 * Uses 5 AI techniques:
 *
 *   1. Bayesian Scoring    — Probabilistic intent inference
 *   2. Finite State Machine — Clear user state transitions
 *   3. Fuzzy Logic          — Soft thresholds (no binary cutoffs)
 *   4. Temporal Patterns    — Sequence analysis over time
 *   5. Self-Learning        — Adapts thresholds from user behaviour
 *
 * Dispatches: "Alita:orchestrator_action" CustomEvent
 *             "Alita:state_change" CustomEvent
 */

import { useEffect, useRef, useCallback, useState } from "react";

// ─────────────────────────────────────────────────────────────────────────────
// §1  CONSTANTS
// ─────────────────────────────────────────────────────────────────────────────
const TICK_INTERVAL_MS = 500;          // Evaluate every 500ms
const STORAGE_KEY = "alita_brain_weights";
const TEMPORAL_WINDOW_MS = 3000;       // Look at last 3 seconds of signals
const LEARNING_RATE = 0.05;            // How fast weights adapt

// ── User States (FSM) ────────────────────────────────────────────────────────
const STATE = {
  IDLE:          "idle",
  CONVERSATION:  "conversation",
  LISTENING:     "listening",
  EXERCISE:      "exercise",
  SIGNING:       "signing",
  READING:       "reading",
  SLEEPING:      "sleeping",
  STRESSED:      "stressed",
  FOCUSED:       "focused",
};

// ── Feature Activation Levels ────────────────────────────────────────────────
// Level 0: Always auto (no confirmation)
// Level 1: Auto if confident (silent activation)
// Level 2: Observe + suggest (confirm before action)
// Level 3: Explicit only (never auto-activate)
const ACTIVATION_LEVEL = {
  context_awareness:     0,  // Battery, time, network — always active
  emotion_particles:     0,  // Visual only — no harm
  heart_rate:            0,  // Passive measurement
  pose_mood:             0,  // Passive observation
  sound_classification:  0,  // Passive listening
  cognitive_load:        0,  // Passive monitoring
  lip_reading:           0,  // Passive face analysis
  productivity:          0,  // Passive tracking
  spatial_audio:         0,  // Audio processing
  predictive_intent:     0,  // Background pattern analysis
  translation:           1,  // Auto-switch if confident
  gesture_control:       1,  // Only on deliberate gesture
  object_recognition:    2,  // Suggest when user seems to want it
  fitness_coach:         2,  // Suggest, don't auto-start
  sign_language:         2,  // Suggest if appropriate
  screen_reader:         3,  // Explicit only (privacy)
  voice_biometrics:      3,  // Explicit only (enrollment)
  offline_llm:           3,  // Explicit only (big download)
  memory_timeline:       3,  // Explicit only (UI)
};

// ── State Transition Rules ───────────────────────────────────────────────────
// Each rule: [fromState, conditions, toState, minConfidence]
const TRANSITION_RULES = [
  // IDLE → other states
  { from: STATE.IDLE, to: STATE.CONVERSATION,  signal: "speaking",        minConf: 0.6 },
  { from: STATE.IDLE, to: STATE.EXERCISE,      signal: "exercise_pose",   minConf: 0.7 },
  { from: STATE.IDLE, to: STATE.SIGNING,       signal: "sign_detected",   minConf: 0.7 },
  { from: STATE.IDLE, to: STATE.SLEEPING,      signal: "drowsy",          minConf: 0.8 },
  { from: STATE.IDLE, to: STATE.FOCUSED,       signal: "focused_posture", minConf: 0.6 },

  // CONVERSATION → other states
  { from: STATE.CONVERSATION, to: STATE.IDLE,        signal: "silence",          minConf: 0.7 },
  { from: STATE.CONVERSATION, to: STATE.STRESSED,    signal: "stress_detected",  minConf: 0.7 },
  { from: STATE.CONVERSATION, to: STATE.EXERCISE,    signal: "exercise_pose",    minConf: 0.8 },

  // EXERCISE → other states
  { from: STATE.EXERCISE, to: STATE.IDLE,         signal: "standing_still",   minConf: 0.7 },
  { from: STATE.EXERCISE, to: STATE.CONVERSATION, signal: "speaking",         minConf: 0.6 },

  // SIGNING → other states
  { from: STATE.SIGNING, to: STATE.IDLE,         signal: "no_hands",         minConf: 0.6 },
  { from: STATE.SIGNING, to: STATE.CONVERSATION, signal: "speaking",         minConf: 0.5 },

  // STRESSED → other states
  { from: STATE.STRESSED, to: STATE.IDLE,         signal: "relaxed",          minConf: 0.6 },
  { from: STATE.STRESSED, to: STATE.CONVERSATION, signal: "speaking",         minConf: 0.5 },

  // SLEEPING → other states
  { from: STATE.SLEEPING, to: STATE.IDLE,         signal: "alert",            minConf: 0.6 },

  // FOCUSED → other states
  { from: STATE.FOCUSED, to: STATE.IDLE,          signal: "distracted",       minConf: 0.5 },
  { from: STATE.FOCUSED, to: STATE.CONVERSATION,  signal: "speaking",         minConf: 0.5 },

  // Any state → back to IDLE after long inactivity
  { from: "*", to: STATE.IDLE, signal: "long_idle", minConf: 0.9 },
];

// ─────────────────────────────────────────────────────────────────────────────
// §2  FUZZY LOGIC HELPERS
// ─────────────────────────────────────────────────────────────────────────────

/** Fuzzy membership: ramps from 0 at `low` to 1 at `high` */
function fuzzyRamp(value, low, high) {
  if (value <= low) return 0;
  if (value >= high) return 1;
  return (value - low) / (high - low);
}

/** Fuzzy reverse: 1 at low, 0 at high */
function fuzzyRampDown(value, low, high) {
  return 1 - fuzzyRamp(value, low, high);
}

/** Combine fuzzy values with AND (minimum) */
function fuzzyAnd(...values) {
  return Math.min(...values);
}

/** Combine fuzzy values with OR (maximum) */
function fuzzyOr(...values) {
  return Math.max(...values);
}

// ─────────────────────────────────────────────────────────────────────────────
// §3  BAYESIAN SIGNAL SCORING
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Compute a Bayesian-style posterior probability for an intent.
 * Each evidence factor multiplies/divides the prior odds.
 *
 * factors: [{ present: bool, likelihoodRatio: number }]
 * e.g. { present: true, likelihoodRatio: 3.0 } means
 *      "3x more likely if this factor is present"
 */
function bayesianScore(prior, factors) {
  let odds = prior / (1 - prior + 0.001);

  for (const f of factors) {
    if (f.present) {
      odds *= f.likelihoodRatio;
    } else {
      // Absence of expected evidence reduces probability
      odds *= (1 / Math.sqrt(f.likelihoodRatio));
    }
  }

  // Convert odds back to probability
  return odds / (1 + odds);
}

// ─────────────────────────────────────────────────────────────────────────────
// §4  SELF-LEARNING WEIGHT STORAGE
// ─────────────────────────────────────────────────────────────────────────────

function loadWeights() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return stored ? JSON.parse(stored) : {};
  } catch (_) {
    return {};
  }
}

function saveWeights(weights) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(weights));
  } catch (_) {}
}

// ─────────────────────────────────────────────────────────────────────────────
// §5  THE HOOK
// ─────────────────────────────────────────────────────────────────────────────

export function useCognitiveOrchestrator({ enabled = false } = {}) {
  const [userState, setUserState] = useState(STATE.IDLE);
  const [confidence, setConfidence] = useState(1.0);

  const mountedRef = useRef(true);
  const stateRef = useRef(STATE.IDLE);
  const stateStartRef = useRef(Date.now());
  const weightsRef = useRef(loadWeights());
  const intervalRef = useRef(null);

  // ── Signal buffers (temporal patterns) ─────────────────────────────
  const signalHistoryRef = useRef({
    speaking:        [],   // timestamps when speech detected
    silence:         [],   // timestamps of silence
    gesture:         [],   // { timestamp, gesture, confidence }
    sign:            [],   // { timestamp, letter, confidence }
    exercise_pose:   [],   // timestamps when exercise pose detected
    heart_rate:      [],   // { timestamp, bpm }
    body_mood:       [],   // { timestamp, mood }
    ambient_sound:   [],   // { timestamp, label }
    context:         [],   // { timestamp, type }
    face_present:    [],   // timestamps when face detected
    hands_present:   [],   // timestamps when hands detected
    cognitive_load:  [],   // { timestamp, level, score }
    lip_activity:    [],   // { timestamp, status }
    prediction:      [],   // { timestamp, topic }
  });

  // Prune old signal entries (keep only last TEMPORAL_WINDOW * 2)
  const pruneHistory = useCallback(() => {
    const cutoff = Date.now() - TEMPORAL_WINDOW_MS * 2;
    const history = signalHistoryRef.current;
    for (const key of Object.keys(history)) {
      history[key] = history[key].filter((entry) => {
        const ts = typeof entry === "number" ? entry : entry.timestamp;
        return ts > cutoff;
      });
    }
  }, []);

  // ── Signal collectors (listen to all feature events) ───────────────
  useEffect(() => {
    if (!enabled) return;
    mountedRef.current = true;

    const history = signalHistoryRef.current;

    const handlers = {
      // Speech activity
      "Alita:user_transcript": () => {
        history.speaking.push(Date.now());
      },

      // Gesture detection
      "Alita:gesture": (e) => {
        const d = e.detail || {};
        history.gesture.push({
          timestamp: Date.now(),
          gesture: d.gesture,
          confidence: d.confidence || 0,
        });
        history.hands_present.push(Date.now());
      },

      // Sign language
      "Alita:sign_detected": (e) => {
        const d = e.detail || {};
        history.sign.push({
          timestamp: Date.now(),
          letter: d.letter,
          confidence: d.confidence || 0,
        });
        history.hands_present.push(Date.now());
      },

      // Body mood
      "Alita:body_mood": (e) => {
        const d = e.detail || {};
        history.body_mood.push({
          timestamp: Date.now(),
          mood: d.mood,
        });
        history.face_present.push(Date.now());
      },

      // Heart rate
      "Alita:heart_rate": (e) => {
        const d = e.detail || {};
        history.heart_rate.push({
          timestamp: Date.now(),
          bpm: d.bpm,
        });
        history.face_present.push(Date.now());
      },

      // Ambient sound
      "Alita:ambient_sound": (e) => {
        const d = e.detail || {};
        history.ambient_sound.push({
          timestamp: Date.now(),
          label: d.label,
        });
      },

      // Context updates
      "Alita:context_update": (e) => {
        const d = e.detail || {};
        history.context.push({
          timestamp: Date.now(),
          type: d.type,
        });
      },

      // Fitness events
      "Alita:fitness_update": (e) => {
        const d = e.detail || {};
        if (d.type === "rep_counted") {
          history.exercise_pose.push(Date.now());
        }
      },

      // Cognitive load
      "Alita:cognitive_load": (e) => {
        const d = e.detail || {};
        history.cognitive_load.push({
          timestamp: Date.now(),
          level: d.level,
          score: d.score,
        });
      },

      // Lip activity
      "Alita:lip_activity": (e) => {
        const d = e.detail || {};
        history.lip_activity.push({
          timestamp: Date.now(),
          status: d.status,
        });
        if (d.status === "speaking" || d.status === "mouthing") {
          history.face_present.push(Date.now());
        }
      },

      // Predictions
      "Alita:prediction": (e) => {
        const d = e.detail || {};
        history.prediction.push({
          timestamp: Date.now(),
          topic: d.topic,
        });
      },
    };

    // Register all listeners
    for (const [event, handler] of Object.entries(handlers)) {
      window.addEventListener(event, handler);
    }

    return () => {
      mountedRef.current = false;
      for (const [event, handler] of Object.entries(handlers)) {
        window.removeEventListener(event, handler);
      }
    };
  }, [enabled]);

  // ── Temporal analysis helpers ──────────────────────────────────────
  const recentCount = useCallback((signalArray, windowMs = TEMPORAL_WINDOW_MS) => {
    const cutoff = Date.now() - windowMs;
    return signalArray.filter((entry) => {
      const ts = typeof entry === "number" ? entry : entry.timestamp;
      return ts > cutoff;
    }).length;
  }, []);

  const recentMood = useCallback(() => {
    const moods = signalHistoryRef.current.body_mood;
    if (moods.length === 0) return "neutral";
    return moods[moods.length - 1].mood;
  }, []);

  const recentAmbient = useCallback(() => {
    const sounds = signalHistoryRef.current.ambient_sound;
    if (sounds.length === 0) return "silence";
    return sounds[sounds.length - 1].label;
  }, []);

  const recentHeartRate = useCallback(() => {
    const hrs = signalHistoryRef.current.heart_rate;
    if (hrs.length === 0) return null;
    return hrs[hrs.length - 1].bpm;
  }, []);

  // ── Get learned weight adjustment for a feature ────────────────────
  const getWeight = useCallback((feature) => {
    return weightsRef.current[feature] || 1.0;
  }, []);

  // ── Learn from outcome (positive or negative feedback) ─────────────
  const learnOutcome = useCallback((feature, positive) => {
    const weights = weightsRef.current;
    const current = weights[feature] || 1.0;

    if (positive) {
      // User engaged → increase weight (more likely to activate next time)
      weights[feature] = Math.min(2.0, current + LEARNING_RATE);
    } else {
      // User ignored → decrease weight (less likely next time)
      weights[feature] = Math.max(0.3, current - LEARNING_RATE);
    }

    weightsRef.current = weights;
    saveWeights(weights);
  }, []);

  // ─────────────────────────────────────────────────────────────────────
  // §6  MAIN EVALUATION TICK — The core intelligence loop
  // ─────────────────────────────────────────────────────────────────────
  const evaluate = useCallback(() => {
    if (!mountedRef.current) return;

    const now = Date.now();
    const history = signalHistoryRef.current;

    // ── Prune old data ───────────────────────────────────────────────
    pruneHistory();

    // ── Compute signal presence (fuzzy) ──────────────────────────────
    const speakingRecent = recentCount(history.speaking);
    const gestureRecent = recentCount(history.gesture);
    const signRecent = recentCount(history.sign);
    const exerciseRecent = recentCount(history.exercise_pose);
    const faceRecent = recentCount(history.face_present);
    const handsRecent = recentCount(history.hands_present);
    const mood = recentMood();
    const ambient = recentAmbient();
    const heartRate = recentHeartRate();
    const stateAge = now - stateStartRef.current;

    // ── Fuzzy signal memberships ─────────────────────────────────────
    const isSpeaking = fuzzyRamp(speakingRecent, 0, 2);      // 0→0, 2+→1
    const isSilent = fuzzyRampDown(speakingRecent, 0, 1);     // 0→1, 1+→0
    const isGesturing = fuzzyRamp(gestureRecent, 0, 2);
    const isSigning = fuzzyRamp(signRecent, 1, 3);            // Need 2+ signs
    const isExercising = fuzzyRamp(exerciseRecent, 0, 2);
    const hasFace = fuzzyRamp(faceRecent, 0, 1);
    const hasHands = fuzzyRamp(handsRecent, 0, 1);
    const isStressed = (mood === "stressed" || mood === "angry") ? 0.7 : 0;
    const isDrowsy = (mood === "tired" || mood === "sleepy") ? 0.7 : 0;
    const isRelaxed = (mood === "relaxed" || mood === "neutral") ? 0.6 : 0;
    const isFocused = (mood === "engaged" || mood === "focused") ? 0.7 : 0;
    const elevatedHR = heartRate ? fuzzyRamp(heartRate, 90, 120) : 0;
    const longIdle = fuzzyRamp(stateAge, 60000, 120000);      // 1-2 min

    // ── New: Cognitive load + lip reading signals ─────────────────────
    const cogLoadRecent = signalHistoryRef.current.cognitive_load;
    const latestCogLoad = cogLoadRecent.length > 0 ? cogLoadRecent[cogLoadRecent.length - 1] : null;
    const isCogOverloaded = latestCogLoad
      ? fuzzyRamp(latestCogLoad.score || 0, 0.5, 0.8)
      : 0;

    const lipRecent = recentCount(signalHistoryRef.current.lip_activity);
    const isLipMoving = fuzzyRamp(lipRecent, 0, 2);

    // ── State Machine: evaluate transitions ──────────────────────────
    const currentState = stateRef.current;
    let bestTransition = null;
    let bestTransitionConf = 0;

    for (const rule of TRANSITION_RULES) {
      if (rule.from !== "*" && rule.from !== currentState) continue;

      let signalStrength = 0;

      // Map signal names to fuzzy values
      switch (rule.signal) {
        case "speaking":        signalStrength = isSpeaking; break;
        case "silence":         signalStrength = isSilent; break;
        case "exercise_pose":   signalStrength = isExercising; break;
        case "sign_detected":   signalStrength = fuzzyAnd(isSigning, isSilent); break;
        case "stress_detected": signalStrength = fuzzyAnd(isStressed, elevatedHR); break;
        case "drowsy":          signalStrength = isDrowsy; break;
        case "relaxed":         signalStrength = isRelaxed; break;
        case "alert":           signalStrength = fuzzyRampDown(isDrowsy, 0, 0.3); break;
        case "focused_posture": signalStrength = fuzzyAnd(isFocused, hasFace); break;
        case "distracted":      signalStrength = fuzzyRampDown(isFocused, 0, 0.3); break;
        case "no_hands":        signalStrength = fuzzyRampDown(handsRecent, 0, 1); break;
        case "standing_still":  signalStrength = fuzzyAnd(isSilent, fuzzyRampDown(isExercising, 0, 1)); break;
        case "long_idle":       signalStrength = longIdle; break;
        default:                signalStrength = 0;
      }

      // Apply learned weight
      const weight = getWeight(`transition_${rule.from}_${rule.to}`);
      const adjustedStrength = Math.min(1, signalStrength * weight);

      if (adjustedStrength >= rule.minConf && adjustedStrength > bestTransitionConf) {
        bestTransition = rule;
        bestTransitionConf = adjustedStrength;
      }
    }

    // ── Apply best transition ────────────────────────────────────────
    if (bestTransition && bestTransition.to !== currentState) {
      const prevState = currentState;
      stateRef.current = bestTransition.to;
      stateStartRef.current = now;
      setUserState(bestTransition.to);
      setConfidence(bestTransitionConf);

      console.log(
        `[Brain] State: ${prevState} → ${bestTransition.to} ` +
        `(confidence: ${(bestTransitionConf * 100).toFixed(0)}%, ` +
        `signal: ${bestTransition.signal})`,
      );

      window.dispatchEvent(
        new CustomEvent("Alita:state_change", {
          detail: {
            from: prevState,
            to: bestTransition.to,
            confidence: bestTransitionConf,
            signal: bestTransition.signal,
          },
        }),
      );

      // ── State-specific actions ─────────────────────────────────────
      handleStateAction(bestTransition.to, bestTransitionConf);
    }

    // ── Bayesian feature intent scoring (within current state) ───────
    evaluateFeatureIntents(currentState, {
      isSpeaking, isSilent, isGesturing, isSigning,
      isExercising, hasFace, hasHands, isStressed,
      isDrowsy, isFocused, elevatedHR, mood, ambient,
      isCogOverloaded, isLipMoving,
    });

  }, [pruneHistory, recentCount, recentMood, recentAmbient, recentHeartRate, getWeight]);

  // ── State-specific automatic actions ───────────────────────────────
  const handleStateAction = useCallback((state, conf) => {
    switch (state) {
      case STATE.SLEEPING:
        dispatch("suggest", {
          feature: "rest",
          message: "🌙 You seem drowsy. Maybe take a break?",
          priority: "high",
        });
        break;

      case STATE.STRESSED:
        dispatch("auto_activate", {
          feature: "emotion_particles",
          params: { mood: "calming" },
          message: "💙 I notice you seem stressed. Switching to calming mode.",
        });
        break;

      case STATE.EXERCISE:
        dispatch("suggest", {
          feature: "fitness_coach",
          message: "🏋️ Looks like you're exercising. Want me to count reps?",
          priority: "medium",
        });
        break;

      case STATE.SIGNING:
        dispatch("auto_activate", {
          feature: "sign_language",
          message: "🤟 Sign language mode activated",
        });
        break;

      default:
        break;
    }
  }, []);

  // ── Bayesian intent evaluation for each feature ────────────────────
  const evaluateFeatureIntents = useCallback((state, signals) => {
    const {
      isSpeaking, isSilent, isGesturing, isSigning,
      isExercising, hasFace, hasHands, isStressed,
      isDrowsy, isFocused, elevatedHR, mood, ambient,
      isCogOverloaded, isLipMoving,
    } = signals;

    // ── Gesture control intent ───────────────────────────────────────
    if (ACTIVATION_LEVEL.gesture_control <= 1) {
      const gestureIntent = bayesianScore(0.1, [
        { present: isGesturing > 0.5,  likelihoodRatio: 5.0 },   // Gesture detected
        { present: isSilent > 0.5,     likelihoodRatio: 2.0 },   // Silence amplifies
        { present: isSpeaking > 0.5,   likelihoodRatio: 0.2 },   // Speaking suppresses
        { present: hasHands > 0.5,     likelihoodRatio: 1.5 },   // Hands visible
      ]) * getWeight("gesture_control");

      if (gestureIntent > 0.65) {
        // Gesture is legitimate — let it fire (already handled by useHandGestures)
      }
    }

    // ── Sign language intent (only when not speaking) ────────────────
    if (ACTIVATION_LEVEL.sign_language <= 2 && state !== STATE.CONVERSATION) {
      const signIntent = bayesianScore(0.05, [
        { present: isSigning > 0.3,    likelihoodRatio: 8.0 },
        { present: isSilent > 0.7,     likelihoodRatio: 3.0 },
        { present: isSpeaking > 0.3,   likelihoodRatio: 0.1 },   // Strong suppression
        { present: hasHands > 0.5,     likelihoodRatio: 2.0 },
      ]) * getWeight("sign_language");

      if (signIntent > 0.6 && state !== STATE.SIGNING) {
        dispatch("suggest", {
          feature: "sign_language",
          message: "🤟 I see you signing. Want to switch to sign language mode?",
          confidence: signIntent,
        });
      }
    }

    // ── Exercise intent (only from IDLE) ─────────────────────────────
    if (state === STATE.IDLE && isExercising > 0.5) {
      const exerciseIntent = bayesianScore(0.1, [
        { present: isExercising > 0.5,  likelihoodRatio: 6.0 },
        { present: isSilent > 0.5,      likelihoodRatio: 1.5 },
        { present: hasFace > 0.3,       likelihoodRatio: 1.2 },
      ]) * getWeight("fitness_coach");

      if (exerciseIntent > 0.6) {
        dispatch("suggest", {
          feature: "fitness_coach",
          message: "🏋️ Want me to start counting reps?",
          confidence: exerciseIntent,
        });
      }
    }

    // ── Stress intervention (automatic, Level 0) ─────────────────────
    if (isStressed > 0.5 && elevatedHR > 0.3) {
      const stressScore = fuzzyAnd(isStressed, elevatedHR);
      if (stressScore > 0.5) {
        dispatch("auto_activate", {
          feature: "stress_relief",
          message: "Take a deep breath... I'm here with you. 💙",
          confidence: stressScore,
        });
      }
    }

    // ── Drowsiness warning (automatic, Level 0) ─────────────────────
    if (isDrowsy > 0.6) {
      dispatch("auto_activate", {
        feature: "drowsiness_alert",
        message: "😴 You seem drowsy. Consider taking a break!",
        confidence: isDrowsy,
      });
    }

    // ── Ambient sound context ────────────────────────────────────────
    if (ambient === "music" && isSpeaking < 0.3) {
      dispatch("suppress", {
        feature: "stt",
        reason: "music_playing",
      });
    }

    // ── Cognitive load intervention ──────────────────────────────────
    if (isCogOverloaded > 0.6) {
      dispatch("auto_activate", {
        feature: "cognitive_load_alert",
        message: "🧠 Your cognitive load is high. Consider a short break or simpler tasks.",
        confidence: isCogOverloaded,
      });
    }

    // ── Lip reading: detect muted mic scenario ──────────────────────
    if (isLipMoving > 0.5 && isSpeaking < 0.2) {
      // Lips moving but no audio detected → mic might be muted
      dispatch("suggest", {
        feature: "lip_reading",
        message: "👄 I can see your lips moving but can't hear you. Is your mic on?",
        confidence: fuzzyAnd(isLipMoving, fuzzyRampDown(isSpeaking, 0, 0.3)),
      });
    }

    // ── Predicting context-aware suggestions ─────────────────────────
    const predictions = signalHistoryRef.current.prediction;
    if (predictions.length > 0 && state === STATE.IDLE) {
      const latest = predictions[predictions.length - 1];
      const age = Date.now() - latest.timestamp;
      if (age < 60000) { // Within last minute
        dispatch("suggest", {
          feature: "predictive_intent",
          message: `🔮 Based on your patterns, you might want to ask about "${latest.topic}"`,
          confidence: 0.5,
        });
      }
    }

  }, [getWeight]);

  // ── Dispatch orchestrator action ───────────────────────────────────
  const dispatch = useCallback((actionType, data) => {
    // Debounce: don't dispatch same action twice in 5 seconds
    const key = `${actionType}_${data.feature}`;
    const lastDispatch = dispatch._cache?.[key] || 0;
    if (Date.now() - lastDispatch < 5000) return;
    if (!dispatch._cache) dispatch._cache = {};
    dispatch._cache[key] = Date.now();

    console.log(
      `[Brain] ${actionType}: ${data.feature} — ${data.message || ""}`,
    );

    window.dispatchEvent(
      new CustomEvent("Alita:orchestrator_action", {
        detail: {
          actionType,  // "auto_activate" | "suggest" | "suppress"
          ...data,
          timestamp: Date.now(),
          userState: stateRef.current,
        },
      }),
    );
  }, []);

  // ── User feedback handler (for self-learning) ─────────────────────
  useEffect(() => {
    if (!enabled) return;

    const feedbackHandler = (e) => {
      const { feature, accepted } = e.detail || {};
      if (feature) {
        learnOutcome(feature, accepted);
        console.log(
          `[Brain] Learning: ${feature} — ${accepted ? "✓ accepted" : "✗ rejected"}`,
        );
      }
    };

    window.addEventListener("Alita:feature_feedback", feedbackHandler);
    return () => window.removeEventListener("Alita:feature_feedback", feedbackHandler);
  }, [enabled, learnOutcome]);

  // ── Main evaluation loop ───────────────────────────────────────────
  useEffect(() => {
    mountedRef.current = true;

    if (!enabled) {
      return () => { mountedRef.current = false; };
    }

    intervalRef.current = setInterval(evaluate, TICK_INTERVAL_MS);
    console.log("[Brain] ✓ Cognitive Orchestrator active — evaluating every 500ms");

    return () => {
      mountedRef.current = false;
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [enabled, evaluate]);

  return { userState, confidence, learnOutcome };
}
