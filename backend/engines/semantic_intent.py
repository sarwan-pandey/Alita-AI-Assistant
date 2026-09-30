# pyre-ignore-all-errors
"""
Semantic Intent Engine — Fast multilingual intent classification

Architecture (V2 — post-audit fix):
  1. KEYWORD classifier is PRIMARY (always works, zero deps, ~0.1ms)
  2. Semantic model is OPTIONAL BOOST (only if numpy is compatible)
  3. Anti-false-positive guards prevent "open question" → open_app
  4. Require BOTH action verb AND target for screen task classification

No cloud API needed. Works in ANY language.
"""

import logging
import time
import re
import numpy as np
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Lazy-load sentence-transformers ──────────────────────────────────────────
_st_model: Any = None
_st_loaded = False


def _load_model() -> Any:
    global _st_model, _st_loaded
    if _st_loaded:
        return _st_model
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-untyped]
        try:
            _st_model = SentenceTransformer('all-MiniLM-L6-v2', local_files_only=True)
        except Exception:
            _st_model = SentenceTransformer('all-MiniLM-L6-v2')
        _st_loaded = True
        logger.info("[SemanticIntent] Model loaded: all-MiniLM-L6-v2")
        return _st_model
    except Exception as e:
        logger.warning(f"[SemanticIntent] Failed to load model: {e}")
        _st_loaded = True  # Don't retry
        return None


# ═════════════════════════════════════════════════════════════════════════════
#  INTENT CATEGORIES
# ═════════════════════════════════════════════════════════════════════════════

INTENT_DB: List[Dict[str, Any]] = [
    # ── OPEN APP ──
    {"intent": "open_app", "phrases": [
        "open notepad", "launch notepad", "start notepad",
        "open word", "launch word", "start microsoft word",
        "open chrome", "launch chrome", "start google chrome",
        "open excel", "launch excel", "start microsoft excel",
        "open powerpoint", "open paint", "open calculator",
        "open vscode", "open vs code", "open file explorer",
        "open spotify", "open discord", "open telegram",
        "open terminal", "open powershell", "open settings",
        "open edge", "launch firefox", "start brave",
        "open slack", "open teams", "open zoom",
        # Hindi/Hinglish
        "notepad kholo", "chrome kholo", "word kholo",
        "excel kholo", "paint kholo", "calculator open karo",
        "notepad open karo", "word open karo",
    ]},

    # ── WRITE/TYPE IN APP ──
    {"intent": "write_in_app", "phrases": [
        "write hello in notepad", "type hello world in notepad",
        "write something in word", "type text in word",
        "write hello in word", "write good morning in notepad",
        "type my name in word", "write a message in notepad",
        "write code in vscode", "type in excel",
        # Hindi/Hinglish
        "notepad mein hello likho", "word mein kuch likho",
        "notepad mein type karo", "word mein likh do",
        "notepad me hello likh do", "word me likho",
    ]},

    # ── COMPOSE (essay, poem, etc.) ──
    {"intent": "compose", "phrases": [
        "write an essay about AI", "compose a poem about nature",
        "write a letter to my teacher", "compose an email about meeting",
        "write a story about adventure", "write an article about technology",
        "write a paragraph about climate change",
        "write essay about artificial intelligence in word",
        "compose poem about love in notepad",
        "write a report about quarterly results",
        # Hindi/Hinglish
        "AI ke baare mein essay likho", "nature par poem likho",
        "ek letter likho teacher ko", "technology par article likho",
    ]},

    # ── SEARCH WEB ──
    {"intent": "search_web", "phrases": [
        "search cats on google", "search for weather",
        "google machine learning", "search youtube for music",
        "look up python tutorial", "find restaurants nearby",
        "search how to cook pasta", "google translate hello",
        # Hindi/Hinglish
        "google par search karo", "youtube par gana search karo",
        "weather search karo", "google karo",
    ]},

    # ── WINDOW MANAGEMENT ──
    {"intent": "window_mgmt", "phrases": [
        "minimize window", "minimize this", "minimize notepad",
        "maximize window", "maximize this", "make fullscreen",
        "close window", "close this", "close notepad",
        "close all windows", "snap left", "snap right",
        "restore window", "switch window", "alt tab",
        # Hindi/Hinglish
        "window band karo", "minimize karo", "maximize karo",
        "close karo", "window chhota karo",
    ]},

    # ── FILE OPS ──
    {"intent": "file_ops", "phrases": [
        "save file", "save this", "save document",
        "new file", "create new file", "new document",
        "open file", "undo", "redo", "copy", "paste", "cut",
        "select all", "print", "print document",
        # Hindi/Hinglish
        "save karo", "file save karo", "naya file banao",
        "undo karo", "copy karo", "paste karo",
    ]},

    # ── NAVIGATION ──
    {"intent": "navigation", "phrases": [
        "scroll down", "scroll up", "next tab", "previous tab",
        "new tab", "close tab", "go to address bar",
        "go back", "go forward", "refresh page",
        "next line", "new line", "new paragraph",
        # Hindi/Hinglish
        "neeche scroll karo", "upar scroll karo",
        "agla tab", "pichla tab", "naya tab",
    ]},

    # ── CLICK/INTERACT ──
    {"intent": "click", "phrases": [
        "click on the button", "click start menu",
        "right click", "double click", "click ok",
        "click cancel", "click yes", "click no",
        "click submit", "click send", "click file menu",
        # Hindi/Hinglish
        "click karo", "button par click karo",
        "right click karo", "double click karo",
    ]},

    # ── SEND/SHARE FILE ──
    {"intent": "send_file", "phrases": [
        "send file to john on whatsapp", "share document on telegram",
        "send my resume on email", "share this file on discord",
        "send photo to mom on whatsapp", "share pdf on telegram",
        "send presentation to team", "share video on whatsapp",
        # Hindi/Hinglish
        "whatsapp pe file bhejo", "telegram pe document bhejo",
        "file bhejo", "photo share karo", "resume bhejo",
    ]},

    # ── CHAT (NOT a screen task) ──
    {"intent": "chat", "phrases": [
        "what is the weather today", "tell me a joke",
        "how are you", "what time is it",
        "explain quantum physics", "who is the president",
        "translate hello to french", "what is machine learning",
        "tell me about yourself", "sing a song",
        "good morning", "thank you", "hello",
        "how does photosynthesis work",
        "what are the benefits of exercise",
        "recommend a good book", "what should I eat",
        "how to open notepad", "can you explain this",
        "what does this mean", "tell me about AI",
        # Hindi/Hinglish
        "mausam kaisa hai", "joke sunao", "kaise ho",
        "time kya hua", "dhanyavaad", "namaste",
        "machine learning kya hai", "apne baare mein batao",
    ]},
]

# Pre-flatten into parallel lists for vectorized similarity
_ALL_PHRASES: List[str] = []
_ALL_INTENTS: List[str] = []
_EMBEDDINGS: Optional[Any] = None  # numpy array, computed lazily

for _entry in INTENT_DB:
    for _phrase in _entry["phrases"]:
        _ALL_PHRASES.append(_phrase)
        _ALL_INTENTS.append(_entry["intent"])


def _ensure_embeddings() -> bool:
    """Compute embeddings for all action phrases (done once at startup)."""
    global _EMBEDDINGS
    if _EMBEDDINGS is not None:
        return True
    model = _load_model()
    if model is None:
        return False
    try:
        t0 = time.time()
        _EMBEDDINGS = model.encode(_ALL_PHRASES, convert_to_numpy=True, show_progress_bar=False)
        logger.info(f"[SemanticIntent] Computed {len(_ALL_PHRASES)} embeddings in {time.time()-t0:.2f}s")
        return True
    except Exception as e:
        logger.error(f"[SemanticIntent] Embedding error: {e}")
        return False


# ═════════════════════════════════════════════════════════════════════════════
#  INTENT CLASSIFICATION (V2 — robust, false-positive-proof)
# ═════════════════════════════════════════════════════════════════════════════

# Screen-task intents (everything except "chat")
SCREEN_INTENTS = {"open_app", "write_in_app", "compose", "search_web",
                  "window_mgmt", "file_ops", "navigation", "click",
                  "send_file"}

# Confidence threshold for semantic model
CONFIDENCE_THRESHOLD = 0.55


# ── Anti-false-positive: conversational phrases containing action verbs ──
# These LOOK like commands but are questions/chat
_CONVERSATIONAL_OVERRIDES = re.compile(
    r'(?:^|\b)('
    # Questions about actions (not commands)
    r'how\s+to\s+(open|close|start|write|type|create|delete|send|save|find)'
    r'|can\s+you\s+(open|close|start|explain|tell)'
    r'|what\s+(is|does|happens|should)\s+'
    r'|do\s+you\s+(know|think|like|play|have)'
    # Conversational uses of action verbs
    r'|open\s+(question|mind|heart|book|discussion|ended|source|letter\b(?!\s+to))'
    r'|close\s+(to|friend|call|enough|relationship|attention|minded)'
    r'|start\s+(thinking|feeling|learning|wondering|believing)'
    r'|play\s+(a\s+role|fair|safe|nice|along|dead|hard)'
    # "tell me about X", "explain how" = chat not command
    r'|tell\s+me\s+(about|how|why|what|who|when)'
    r'|explain\s+(how|what|why|the)'
    r'|describe\s+(how|what|the|a)'
    r')\b', re.IGNORECASE
)


def classify_intent(text: str) -> Dict[str, Any]:
    """
    Classify user input into an intent category.
    Returns: {"intent": str, "confidence": float, "is_screen_task": bool}

    Architecture (V2):
      1. Conversational override guard → prevents false positives
      2. Keyword classifier (PRIMARY) → always works, zero deps
      3. Semantic model (OPTIONAL BOOST) → only if numpy works
    """
    text_clean = text.strip()
    if not text_clean:
        return {"intent": "chat", "confidence": 0.0, "is_screen_task": False}

    # ── Guard: Check for conversational false positives FIRST ──
    if _CONVERSATIONAL_OVERRIDES.search(text_clean):
        logger.info(f"[SemanticIntent] Conversational override: '{text_clean[:40]}' → chat")
        return {"intent": "chat", "confidence": 0.85, "is_screen_task": False}

    # ── Primary: Keyword classification (always works, ~0.1ms) ──
    result = _keyword_classify(text_clean)

    # ── Optional: Semantic boost (only if model loaded) ──
    if result["is_screen_task"] and result["confidence"] < 0.75:
        # Low-confidence keyword match — try semantic for confirmation
        if _ensure_embeddings():
            try:
                model = _load_model()
                if model is not None:
                    t0 = time.time()
                    query_emb = model.encode([text_clean], convert_to_numpy=True,
                                            show_progress_bar=False)
                    sims = np.dot(_EMBEDDINGS, query_emb.T).squeeze()
                    best_idx = int(np.argmax(sims))
                    best_score = float(sims[best_idx])
                    best_intent = _ALL_INTENTS[best_idx]
                    elapsed = (time.time() - t0) * 1000

                    if best_score >= CONFIDENCE_THRESHOLD:
                        result = {
                            "intent": best_intent,
                            "confidence": max(result["confidence"], best_score),
                            "is_screen_task": best_intent in SCREEN_INTENTS,
                            "matched_phrase": _ALL_PHRASES[best_idx],
                        }
                        logger.info(f"[SemanticIntent] Semantic boost: '{text_clean[:40]}' → "
                                   f"{best_intent} (score={best_score:.3f}, {elapsed:.1f}ms)")
                    elif best_intent == "chat" and best_score > 0.50:
                        result = {"intent": "chat", "confidence": best_score,
                                  "is_screen_task": False}
                        logger.info(f"[SemanticIntent] Semantic override to chat: "
                                   f"'{text_clean[:40]}' (score={best_score:.3f})")
            except Exception as e:
                logger.debug(f"[SemanticIntent] Semantic boost skipped: {e}")

    logger.info(f"[SemanticIntent] Final: '{text_clean[:40]}' → {result['intent']} "
               f"(conf={result['confidence']:.2f}, screen={result['is_screen_task']})")
    return result


def _keyword_classify(text: str) -> Dict[str, Any]:
    """
    Robust intent classification using keyword patterns.

    Key design: Require BOTH action verb AND known target to classify
    as screen task. This prevents false positives like:
      "open question" → chat (not open_app)
      "start thinking" → chat (not open_app)
      "close to my heart" → chat (not window_mgmt)
    """
    text_lower = text.lower().strip()

    # ── Mobile Phone Companion Intents ─────────────────────────────────
    if re.search(r'\b(unlock|open)\s+(my\s+)?(phone|screen|device|mobile)\b', text_lower) or \
       re.search(r'\b(phone|mobile|screen)\s+(unlock|kholo|open)\b', text_lower) or \
       text_lower in ("unlock", "unlock phone", "unlock screen", "phone unlock"):
        return {"intent": "phone_unlock", "confidence": 0.95, "is_screen_task": False, "is_phone_task": True}

    if re.search(r'\b(lock)\s+(my\s+)?(phone|screen|device|mobile)\b', text_lower) or \
       re.search(r'\b(phone|mobile)\s+lock\b', text_lower):
        return {"intent": "phone_lock", "confidence": 0.95, "is_screen_task": False, "is_phone_task": True}

    if re.search(r'\b(phone|mobile)\s+(battery|charge|charging|status)\b', text_lower) or \
       re.search(r'\b(battery|charge)\s+(of\s+)?(my\s+)?(phone|mobile)\b', text_lower):
        return {"intent": "phone_battery", "confidence": 0.95, "is_screen_task": False, "is_phone_task": True}

    # ── HIGHEST priority: standalone window management verbs ──────────
    # "minimize", "maximize", "fullscreen" are ALWAYS window_mgmt
    WINDOW_VERBS = r'^\s*(minimize|maximize|fullscreen|full screen)\s*$'
    if re.search(WINDOW_VERBS, text_lower):
        return {"intent": "window_mgmt", "confidence": 0.90, "is_screen_task": True}

    # ── Window mgmt with target: "minimize chrome", "close the window" ─
    WINDOW_WITH_TARGET = r'\b(minimize|maximize|close)\s+(this|the\s+)?(window|tab|app|\w+)\b'
    if re.search(WINDOW_WITH_TARGET, text_lower):
        # But exclude "close to", "close friend" etc.
        if not re.search(r'\bclose\s+(to|friend|enough|relationship|attention|call|by|at)\b', text_lower):
            return {"intent": "window_mgmt", "confidence": 0.85, "is_screen_task": True}

    # ── HIGH confidence: action verb + KNOWN app name ──────────────────
    ACTION_VERBS = (r'\b(open|launch|start|close|write|type|'
                    r'compose|kholo|band karo|likho|type karo|open karo|likh do)\b')
    APP_NAMES = (r'\b(notepad|chrome|firefox|edge|excel|word|powerpoint|spotify|'
                 r'vscode|vs code|calculator|paint|terminal|explorer|settings|'
                 r'discord|telegram|whatsapp|teams|slack|zoom|brave|opera|vlc|'
                 r'blender|figma|postman|obs|notion|skype|steam)\b')

    has_verb = bool(re.search(ACTION_VERBS, text_lower))
    has_app = bool(re.search(APP_NAMES, text_lower))

    # ── Send/share file patterns ──────────────────────────────────────
    if re.search(r'\b(send|share|bhejo|forward)\s+.*(file|document|photo|image|video|'
                 r'pdf|resume|report|presentation)', text_lower):
        return {"intent": "send_file", "confidence": 0.90, "is_screen_task": True}

    # ── Level 2 Workflows (check BEFORE compose to avoid conflicts) ───
    # Blog creation
    if re.search(r'\b(create|write|make|publish|generate)\s+.*(blog|blog\s+post|article)\b',
                 text_lower):
        return {"intent": "create_blog", "confidence": 0.90, "is_screen_task": True}
    if re.search(r'\b(blog|article)\s+(likhna|likho|banao|bana\s+do|publish\s+karo)\b',
                 text_lower):
        return {"intent": "create_blog", "confidence": 0.90, "is_screen_task": True}

    # YouTube Shorts creation
    if re.search(r'\b(create|make|generate)\s+.*(short|shorts|reel|reels)\b', text_lower):
        return {"intent": "create_short", "confidence": 0.90, "is_screen_task": True}
    if re.search(r'\b(upload|post)\s+.*(youtube|yt|short|shorts)\b', text_lower):
        return {"intent": "create_short", "confidence": 0.85, "is_screen_task": True}
    if re.search(r'\b(short\s+form\s+video|youtube\s+short)\b', text_lower):
        return {"intent": "create_short", "confidence": 0.85, "is_screen_task": True}

    # ── Verb + known app = definite screen task ───────────────────────
    if has_verb and has_app:
        if re.search(r'\b(write|type|compose|likho|likh)\b', text_lower):
            if re.search(r'\b(essay|poem|letter|email|story|article|paragraph|'
                         r'report|application|resume|proposal|summary|complaint|'
                         r'notice|invitation|speech|script|blog)\b', text_lower):
                intent = "compose"
            else:
                intent = "write_in_app"
        elif re.search(r'\b(close|band karo)\b', text_lower):
            intent = "window_mgmt"
        elif re.search(r'\b(minimize|maximize)\b', text_lower):
            intent = "window_mgmt"
        else:
            intent = "open_app"
        return {"intent": intent, "confidence": 0.90, "is_screen_task": True}

    # ── MEDIUM: Verb + no known app → only if short (likely command) ──
    if has_verb and not has_app:
        words = text_lower.split()
        if len(words) <= 6:
            if re.search(r'\b(write|type|compose|likho|likh)\b', text_lower):
                if re.search(r'\b(essay|poem|letter|email|story|article|paragraph|'
                             r'report|application)\b', text_lower):
                    return {"intent": "compose", "confidence": 0.75, "is_screen_task": True}
                return {"intent": "write_in_app", "confidence": 0.60, "is_screen_task": True}
            return {"intent": "open_app", "confidence": 0.55, "is_screen_task": True}
        # Long text with action verb → probably conversation
        return {"intent": "chat", "confidence": 0.60, "is_screen_task": False}

    # ── File/system operations (no app needed) ────────────────────────
    if re.search(r'\b(save|undo|redo|select all|screenshot)\b', text_lower):
        return {"intent": "file_ops", "confidence": 0.80, "is_screen_task": True}

    # ── Navigation (no app needed) ────────────────────────────────────
    if re.search(r'\b(scroll\s+(up|down)|next\s+tab|previous\s+tab|new\s+tab|'
                 r'close\s+tab|refresh|address\s+bar)\b', text_lower):
        return {"intent": "navigation", "confidence": 0.80, "is_screen_task": True}

    # ── Search with target ────────────────────────────────────────────
    if re.search(r'\b(search|google|search karo|dhundho)\s+.+\b', text_lower):
        if re.search(r'\b(on|in|for|karo)\b', text_lower):
            return {"intent": "search_web", "confidence": 0.75, "is_screen_task": True}

    # ── Click patterns ───────────────────────────────────────────────
    if re.search(r'\b(click|right\s+click|double\s+click)\s+(on\s+)?(the\s+)?',
                 text_lower):
        return {"intent": "click", "confidence": 0.70, "is_screen_task": True}

    # ── Default: chat ─────────────────────────────────────────────────
    return {"intent": "chat", "confidence": 0.75, "is_screen_task": False}


# ═════════════════════════════════════════════════════════════════════════════
#  PARAMETER EXTRACTION
# ═════════════════════════════════════════════════════════════════════════════

# Known app names for extraction
_APP_PATTERN = re.compile(
    r'\b(notepad|chrome|google chrome|firefox|edge|excel|word|microsoft word|'
    r'powerpoint|spotify|vscode|vs code|calculator|paint|terminal|'
    r'powershell|explorer|file explorer|settings|discord|telegram|'
    r'whatsapp|teams|slack|zoom|brave|opera|vlc|photos|blender|figma)\b',
    re.IGNORECASE
)

_COMPOSE_STYLES = re.compile(
    r'\b(essay|poem|letter|email|story|article|paragraph|notes?|code|report|song|speech|'
    r'application|resume|cv|proposal|invitation|complaint|notice|summary|review|tutorial|'
    r'memo|blog|post|script|recipe)\b',
    re.IGNORECASE
)


def extract_params(text: str, intent: str) -> Dict[str, str]:
    """Extract action parameters (app name, content, topic, etc.) from text."""
    params: Dict[str, str] = {}
    text_lower = text.lower().strip()

    # Extract app name
    app_match = _APP_PATTERN.search(text_lower)
    if app_match:
        params["app"] = app_match.group(1)

    if intent == "open_app":
        if not params.get("app"):
            # Try to extract app name from end of text
            words = text_lower.split()
            for w in reversed(words):
                if w not in ("open", "launch", "start", "kholo", "karo", "the", "a", "an"):
                    params["app"] = w
                    break

    elif intent == "write_in_app":
        # Extract text to write: "write HELLO in notepad" → text="hello"
        m = re.match(
            r'(?:write|type|compose|likho|likh do|likh)\s+(.+?)\s+(?:in|mein|me|on|into)\s+\w+',
            text_lower)
        if m:
            params["text"] = m.group(1).strip()
        else:
            # "open notepad and write HELLO"
            m2 = re.search(r'(?:write|type|compose|likho|likh)\s+(.+?)$', text_lower)
            if m2:
                params["text"] = m2.group(1).strip()
        if not params.get("app"):
            params["app"] = "notepad"  # Default

    elif intent == "compose":
        # Extract style and topic: "write an essay about AI" → style="essay", topic="AI"
        style_match = _COMPOSE_STYLES.search(text_lower)
        if style_match:
            params["style"] = style_match.group(1)
        # Extract topic
        topic_match = re.search(
            r'(?:about|on|regarding|for|to|ke baare|par|ke upar|ke liye)\s+(.+?)(?:\s+in\s+\w+)?$',
            text_lower)
        if topic_match:
            params["topic"] = topic_match.group(1).strip()

        # Fallback 1: extract everything after the style word
        if not params.get("topic") and style_match:
            remaining = text_lower[style_match.end():].strip()
            remaining = re.sub(r'^(?:for|to|about|on|regarding)\s+', '', remaining).strip()
            remaining = re.sub(r'\s+(?:in|into|on)\s+\w+$', '', remaining).strip()
            if remaining:
                params["topic"] = remaining

        # Fallback 2: use entire text minus action verb as topic
        if not params.get("topic"):
            topic_fb = re.sub(r'^(?:write|compose|type|create|draft)\s+(?:an?\s+)?', '', text_lower).strip()
            topic_fb = re.sub(r'\s+(?:in|into|on)\s+\w+$', '', topic_fb).strip()
            if topic_fb:
                params["topic"] = topic_fb

        if not params.get("app"):
            params["app"] = "notepad"  # Default
        if not params.get("style"):
            params["style"] = "essay"

    elif intent == "search_web":
        m = re.search(r'(?:search|google|look up|find)\s+(?:for\s+)?(.+?)(?:\s+on\s+\w+)?$', text_lower)
        if m:
            params["query"] = m.group(1).strip()
        if not params.get("app"):
            params["app"] = "chrome"

    elif intent == "send_file":
        # Extract: file name, target app, contact
        file_match = re.search(
            r'\b(file|document|photo|image|video|pdf|resume|report|presentation)\b',
            text_lower)
        if file_match:
            params["file_type"] = file_match.group(1)

        # Extract specific filename — capture multi-word names like "6th syllabus"
        name_match = re.search(
            r'(?:send|share|bhejo|forward)\s+(?:my\s+|the\s+|a\s+)?'
            r'(.+?)\s+(?:file|document|photo|image|video|pdf|to\b)',
            text_lower)
        if name_match:
            fname = name_match.group(1).strip()
            # Remove noise words
            fname = re.sub(r'\b(the|my|a|an)\b', '', fname).strip()
            if fname and len(fname) > 1:
                params["file_name"] = fname

        # Extract target app
        target_match = re.search(
            r'(?:on|via|through|pe|par|in)\s+(whatsapp|telegram|discord|email|mail|slack|teams)',
            text_lower)
        if target_match:
            params["target_app"] = target_match.group(1)

        # Extract contact — phone number or name
        # Pattern 1: "to 6206805982 on whatsapp" / "to 6206805982 number on"
        contact_num = re.search(
            r'(?:to|ko)\s+(\d[\d\s]{6,14})\s*(?:number|no|num|on|pe|par|via)',
            text_lower)
        if contact_num:
            params["contact"] = re.sub(r'\s+', '', contact_num.group(1))
        else:
            # Pattern 2: "to [name] on [app]"
            contact_name = re.search(
                r'(?:to|ko)\s+(.+?)\s+(?:on|pe|par|via|number)',
                text_lower)
            if contact_name:
                name = contact_name.group(1).strip()
                # Remove "whatsapp"/"telegram" if accidentally captured
                name = re.sub(r'\b(whatsapp|telegram|discord|email|slack)\b', '', name).strip()
                if name and len(name) > 1:
                    params["contact"] = name

    elif intent == "window_mgmt":
        if re.search(r'\b(minimize)\b', text_lower):
            params["action"] = "minimize"
        elif re.search(r'\b(maximize|fullscreen)\b', text_lower):
            params["action"] = "maximize"
        elif re.search(r'\b(close|band)\b', text_lower):
            params["action"] = "close"
        elif re.search(r'\b(snap left)\b', text_lower):
            params["action"] = "snap_left"
        elif re.search(r'\b(snap right)\b', text_lower):
            params["action"] = "snap_right"

    elif intent == "file_ops":
        if re.search(r'\b(save)\b', text_lower):
            params["action"] = "save"
        elif re.search(r'\b(undo)\b', text_lower):
            params["action"] = "undo"
        elif re.search(r'\b(redo)\b', text_lower):
            params["action"] = "redo"
        elif re.search(r'\b(copy)\b', text_lower):
            params["action"] = "copy"
        elif re.search(r'\b(paste)\b', text_lower):
            params["action"] = "paste"
        elif re.search(r'\b(cut)\b', text_lower):
            params["action"] = "cut"
        elif re.search(r'\b(select all)\b', text_lower):
            params["action"] = "select_all"
        elif re.search(r'\b(new|create)\b', text_lower):
            params["action"] = "new"
        elif re.search(r'\b(print)\b', text_lower):
            params["action"] = "print"

    elif intent == "navigation":
        if re.search(r'\b(scroll down|neeche)\b', text_lower):
            params["action"] = "scroll_down"
        elif re.search(r'\b(scroll up|upar)\b', text_lower):
            params["action"] = "scroll_up"
        elif re.search(r'\b(next tab|agla tab)\b', text_lower):
            params["action"] = "next_tab"
        elif re.search(r'\b(previous tab|pichla tab)\b', text_lower):
            params["action"] = "prev_tab"
        elif re.search(r'\b(new tab|naya tab)\b', text_lower):
            params["action"] = "new_tab"
        elif re.search(r'\b(close tab)\b', text_lower):
            params["action"] = "close_tab"
        elif re.search(r'\b(address bar)\b', text_lower):
            params["action"] = "address_bar"
        elif re.search(r'\b(refresh)\b', text_lower):
            params["action"] = "refresh"

    elif intent == "create_blog":
        # Extract topic — everything after "blog about" / "blog on"
        topic_match = re.search(
            r'(?:blog|article|post)\s+(?:about|on|regarding)\s+(.+?)(?:\s+and\s+publish|\s+on\s+blogger|$)',
            text_lower)
        if topic_match:
            params["topic"] = topic_match.group(1).strip()
        else:
            # Fallback: strip action words
            topic_fb = re.sub(r'^(?:create|write|make|publish|generate)\s+(?:a\s+)?(?:blog\s+(?:post\s+)?)?', '', text_lower).strip()
            topic_fb = re.sub(r'\s+(?:and\s+publish|on\s+blogger).*$', '', topic_fb).strip()
            if topic_fb:
                params["topic"] = topic_fb
        params["platform"] = "blogger"

    elif intent == "create_short":
        # Extract source URL if provided
        url_match = re.search(r'(https?://\S+)', text_lower)
        if url_match:
            params["source_url"] = url_match.group(1)
        # Extract niche/topic
        topic_match = re.search(
            r'(?:short|shorts|reel)\s+(?:about|on|from)\s+(.+?)(?:\s+and\s+upload|\s+on\s+youtube|$)',
            text_lower)
        if topic_match:
            params["topic"] = topic_match.group(1).strip()
            params["niche"] = topic_match.group(1).strip()

    return params


# ═════════════════════════════════════════════════════════════════════════════
#  PRE-WARM (background thread)
# ═════════════════════════════════════════════════════════════════════════════

def prewarm() -> None:
    """Load model and compute embeddings in background."""
    import threading
    def _warm():
        _ensure_embeddings()
    t = threading.Thread(target=_warm, daemon=True)
    t.start()
