# pyre-ignore-all-errors
"""
Screen Agent V2 — Deterministic Action Scripts + UI Automation
No cloud API needed for screen control. Uses:
  - Semantic intent cache for ~5ms multilingual intent detection
  - UI Automation for direct app control (no pixel clicking)
  - Deterministic action scripts (no LLM planning loop)
  - Groq/Gemini only for text COMPOSITION (optional)
"""

import asyncio
import json
import logging
import os
import time
import threading
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# ── Import our new modules ───────────────────────────────────────────────────
try:
    from engines.semantic_intent import classify_intent as semantic_classify, extract_params, prewarm as _prewarm_intent  # type: ignore[import]
    HAS_SEMANTIC = True
except ImportError:
    HAS_SEMANTIC = False
    logger.warning("[ScreenAgent] semantic_intent not available — using keyword fallback")

try:
    from engines.ui_controller import ui_ctrl, UIController  # type: ignore[import]
    HAS_UI_CTRL = True
except ImportError:
    HAS_UI_CTRL = False
    ui_ctrl = None  # type: ignore[assignment]

try:
    from engines.app_manager import open_app, focus_window, list_windows, get_active_window, find_window  # type: ignore[import]
except ImportError:
    def open_app(name: str) -> dict: return {"ok": False, "title": "", "msg": "N/A"}  # type: ignore[misc]
    def focus_window(title: str) -> bool: return False  # type: ignore[misc]
    def list_windows() -> list: return []  # type: ignore[misc]
    def get_active_window() -> dict: return {"title": "", "left": 0, "top": 0, "width": 0, "height": 0}  # type: ignore[misc]
    def find_window(title: str) -> Optional[dict]: return None  # type: ignore[misc]

# ── Windows High-DPI Awareness Initialization ────────────────────────────────
try:
    import ctypes
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

try:
    import pyautogui  # type: ignore[import-untyped]
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.12
    HAS_PYAUTOGUI = True
except ImportError:
    pyautogui = None
    HAS_PYAUTOGUI = False

# ── Constants ────────────────────────────────────────────────────────────────
MAX_STEPS = 20
ACTION_DELAY = 0.3  # seconds between actions

# ── Text generation (for compose tasks) ──────────────────────────────────────
HAS_OLLAMA = False
try:
    from ollama_client import ollama_chat  # type: ignore[import]
    HAS_OLLAMA = True
except ImportError:
    ollama_chat = None  # type: ignore[assignment]
    HAS_OLLAMA = False


def _build_compose_prompt(topic: str, style: str, max_words: int = 300) -> tuple[str, str]:
    """
    Build a style-aware system + user prompt pair.
    
    The key insight: "Write a application about leave" makes the LLM explain
    HOW to write one. We need to say "Write the actual application letter FOR leave"
    so the LLM produces the document itself.
    """
    # System prompt: forces direct document output
    system = (
        "You are a professional document writer. You produce ONLY the document content itself — "
        "no instructions, no meta-commentary, no markdown formatting, no headers like '# Title'. "
        "Write the actual document as if you are the person writing it. "
        "Output plain text only, ready to be pasted into a text editor."
    )

    # Style-specific user prompts
    STYLE_PROMPTS = {
        "application": (
            f"Write a formal application letter for: {topic}. "
            f"Include a proper salutation (Dear Sir/Madam), state the purpose clearly, "
            f"provide a brief justification, and close with a formal sign-off. "
            f"Under {max_words} words."
        ),
        "letter": (
            f"Write a complete letter about: {topic}. "
            f"Include proper salutation, body paragraphs, and closing. "
            f"Under {max_words} words."
        ),
        "email": (
            f"Write a professional email about: {topic}. "
            f"Include Subject line, greeting, body, and sign-off. "
            f"Under {max_words} words."
        ),
        "essay": (
            f"Write a complete essay on: {topic}. "
            f"Include an introduction, body paragraphs with arguments, and a conclusion. "
            f"Under {max_words} words."
        ),
        "poem": (
            f"Write a poem about: {topic}. Be creative and expressive. "
            f"Under {max_words} words."
        ),
        "story": (
            f"Write a short story about: {topic}. "
            f"Include characters, setting, conflict, and resolution. "
            f"Under {max_words} words."
        ),
        "report": (
            f"Write a formal report on: {topic}. "
            f"Include an executive summary, findings, and recommendations. "
            f"Under {max_words} words."
        ),
        "resume": (
            f"Write a professional resume/CV for: {topic}. "
            f"Include sections for objective, education, experience, and skills. "
            f"Under {max_words} words."
        ),
        "proposal": (
            f"Write a formal proposal for: {topic}. "
            f"Include problem statement, proposed solution, and expected outcomes. "
            f"Under {max_words} words."
        ),
        "complaint": (
            f"Write a formal complaint letter regarding: {topic}. "
            f"State the issue clearly, provide details, and request resolution. "
            f"Under {max_words} words."
        ),
        "notice": (
            f"Write a formal notice about: {topic}. "
            f"Be clear, concise, and authoritative. "
            f"Under {max_words} words."
        ),
        "speech": (
            f"Write a speech about: {topic}. "
            f"Include a strong opening, key points, and a memorable closing. "
            f"Under {max_words} words."
        ),
        "summary": (
            f"Write a comprehensive summary of: {topic}. "
            f"Cover the key points concisely. "
            f"Under {max_words} words."
        ),
        "invitation": (
            f"Write a formal invitation for: {topic}. "
            f"Include event details, date/time placeholder, and RSVP. "
            f"Under {max_words} words."
        ),
        "paragraph": (
            f"Write a detailed paragraph about: {topic}. "
            f"Under {max_words} words."
        ),
        "code": (
            f"Write code for: {topic}. "
            f"Include comments explaining the logic. Output code only."
        ),
        "article": (
            f"Write an article about: {topic}. "
            f"Include an engaging introduction, informative body, and conclusion. "
            f"Under {max_words} words."
        ),
    }

    user_prompt = STYLE_PROMPTS.get(
        style.lower(),
        f"Write a {style} about: {topic}. Produce the actual {style} content directly. "
        f"Do NOT write instructions about how to write one. Under {max_words} words."
    )

    return system, user_prompt


def _generate_text(topic: str, style: str, max_words: int = 300) -> str:
    """Generate text content using local Ollama (Qwen3 4B Q4).
    
    Uses style-aware prompting to produce the actual document, not instructions.
    Falls back to a template if Ollama is unavailable.
    """
    system_prompt, user_prompt = _build_compose_prompt(topic, style, max_words)
    logger.info(f"[ScreenAgent] _generate_text: style='{style}', topic='{topic[:50]}', "
                f"HAS_OLLAMA={HAS_OLLAMA}")
    logger.debug(f"[ScreenAgent] Prompt: {user_prompt[:100]}...")

    # Try Ollama (local Qwen3 4B Q4)
    if HAS_OLLAMA:
        try:
            logger.info("[ScreenAgent] Attempting Ollama generation...")
            text = ollama_chat(
                prompt=user_prompt,
                system=system_prompt,
                max_tokens=max_words * 2,
                temperature=0.7,
            )
            if text:
                text = _clean_llm_output(text)
                if text:
                    logger.info(f"[ScreenAgent] ✓ Generated {len(text)} chars via Ollama")
                    return text
                else:
                    logger.warning("[ScreenAgent] Ollama returned empty text after cleaning")
            else:
                logger.warning("[ScreenAgent] Ollama returned empty text")
        except Exception as e:
            logger.warning(f"[ScreenAgent] Ollama generation failed: {e}")
    else:
        logger.info("[ScreenAgent] ollama_client not available — skipping")

    # Last resort: simple template
    logger.warning("[ScreenAgent] Ollama failed — using template fallback")
    return (
        f"{style.title()}: {topic.title()}\n\n"
        f"This is a placeholder {style} about {topic}. "
        f"No language model was available to generate content. "
        f"Please make sure Ollama is running (ollama serve) with qwen3 4B Q4 pulled."
    )


def _clean_llm_output(text: str) -> str:
    """Remove markdown formatting, headers, and meta-commentary from LLM output."""
    import re
    # Remove markdown headers (# Title, ## Subtitle)
    text = re.sub(r'^#{1,6}\s+.*$', '', text, flags=re.MULTILINE)
    # Remove bold/italic markers
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)
    # Remove markdown bullet markers but keep the text
    text = re.sub(r'^\s*[-*]\s+', '• ', text, flags=re.MULTILINE)
    # Remove code fence markers
    text = re.sub(r'^```\w*\s*$', '', text, flags=re.MULTILINE)
    # Clean up multiple blank lines
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()




# ═════════════════════════════════════════════════════════════════════════════
#  APP MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

def _wait_for_window_ready(app_name: str, max_ms: int = 500, poll_ms: int = 100,
                           stop_event: Optional[threading.Event] = None) -> bool:
    """
    Adaptive polling wait — returns as soon as the window is focused
    instead of always sleeping the full duration. Has a minimum floor of 150ms
    to let Windows finish rendering.

    If stop_event is provided and gets set, returns False immediately
    (allows instant interrupt during waits).

    Returns True if window was detected, False if timed out or stopped.
    """
    min_wait = 0.15  # always wait at least 150ms for UI to settle
    time.sleep(min_wait)
    elapsed_ms = int(min_wait * 1000)

    app_lower = app_name.lower().strip()
    while elapsed_ms < max_ms:
        # ── Check for stop interrupt ──
        if stop_event and stop_event.is_set():
            logger.info("[ScreenAgent] _wait_for_window_ready interrupted by stop")
            return False
        # Check if the target window is now the active window
        try:
            if HAS_UI_CTRL and ui_ctrl:
                if ui_ctrl.is_window_open(app_lower):
                    return True
            for alias in _APP_ALIASES.get(app_lower, [app_lower]):
                if find_window(alias):
                    return True
        except Exception:
            pass
        time.sleep(poll_ms / 1000.0)
        elapsed_ms += poll_ms

    return False

# Window title aliases for detection
_APP_ALIASES: Dict[str, List[str]] = {
    "word": ["word", "document", "winword"],
    "microsoft word": ["word", "document"],
    "notepad": ["notepad"],
    "chrome": ["chrome", "google chrome"],
    "excel": ["excel", "book"],
    "powerpoint": ["powerpoint", "presentation"],
    "vscode": ["visual studio code", "code"],
    "vs code": ["visual studio code", "code"],
    "paint": ["paint"],
    "calculator": ["calculator"],
    "explorer": ["explorer", "file explorer"],
}


def _is_app_open(app_name: str) -> bool:
    """Check if an app is already open by checking window titles."""
    app_lower = app_name.lower().strip()
    # Check via ui_controller
    if HAS_UI_CTRL and ui_ctrl:
        if ui_ctrl.is_window_open(app_lower):
            return True
    # Check aliases
    for alias in _APP_ALIASES.get(app_lower, [app_lower]):
        if find_window(alias):
            return True
    return False


def _open_or_focus(app_name: str) -> str:
    """Open an app if not running, or focus it. Returns status message."""
    app_lower = app_name.lower().strip()
    if _is_app_open(app_lower):
        logger.info(f"[ScreenAgent] '{app_name}' already open — focusing")
        focus_window(app_lower)
        # Try aliases for focus
        if not focus_window(app_lower):
            for alias in _APP_ALIASES.get(app_lower, []):
                if focus_window(alias):
                    break
        # Fix #15: Adaptive wait — poll for focus instead of fixed sleep
        _wait_for_window_ready(app_lower, max_ms=500)
        return f"'{app_name}' already open — focused"

    result = open_app(app_name)
    # Longer adaptive wait for app launch
    _wait_for_window_ready(app_lower, max_ms=2000)

    # Handle Office splash screens
    if HAS_UI_CTRL and ui_ctrl:
        splash = ui_ctrl.handle_office_splash(app_lower)
        if splash:
            return f"{result['msg']} + {splash}"
    return result["msg"]


# ═════════════════════════════════════════════════════════════════════════════
#  ACTION EXECUTORS — Deterministic, no LLM needed
# ═════════════════════════════════════════════════════════════════════════════

def _exec_open_app(params: Dict[str, str], notify: Callable) -> str:
    """Execute: open/focus an application."""
    app = params.get("app", "")
    if not app:
        return "No app name specified"
    notify({"action": "open_app", "thought": f"Opening {app}..."})
    return _open_or_focus(app)


def _needs_generation(text: str) -> bool:
    """
    Determine if the user's text is a GENERATION REQUEST or LITERAL TEXT.
    
    LITERAL (just type it):
      - "hello world" → type "hello world"
      - "my name is John" → type "my name is John"
      - "I love coding" → type "I love coding"
    
    GENERATION (use LLM to write it):
      - "an application for leave" → generate a leave application
      - "a letter to my boss" → generate a formal letter
      - "a poem about nature" → generate a poem
      - "about artificial intelligence" → generate content about AI
      - "code for calculator in python" → generate code
    """
    import re
    text_lower = text.lower().strip()

    # Document/content types that ALWAYS mean "generate this"
    DOC_TYPES = re.compile(
        r'\b(application|letter|email|essay|poem|story|article|paragraph|'
        r'report|speech|script|code|program|resume|cv|proposal|'
        r'invitation|notice|complaint|request|memo|summary|review|'
        r'assignment|homework|project|presentation|blog|post|'
        r'biography|autobiography|diary|journal|recipe|tutorial|'
        r'apology|congratulat|thank you letter|cover letter|'
        r'resignation|recommendation|reference|certificate|'
        # Hindi
        r'aavedan|patra|kavita|nibandh|kahani|lekh|prarthna)\b',
        re.IGNORECASE
    )

    # Topic indicators that signal "write ABOUT something"
    TOPIC_INDICATORS = re.compile(
        r'\b(about|regarding|on the topic|for|to my|to the|to a|'
        r'ke baare|ke liye|ke bare|par|ke upar|ke vishay)\b',
        re.IGNORECASE
    )

    # Article + document type = definitely generation
    # "an application", "a letter", "a poem"
    ARTICLE_DOC = re.compile(
        r'\b(an?|the|one|ek)\s+(application|letter|email|essay|poem|story|'
        r'article|paragraph|report|speech|script|code|program|resume|'
        r'proposal|invitation|notice|complaint|request|memo|summary|'
        r'aavedan|patra|kavita|nibandh)\b',
        re.IGNORECASE
    )

    # Strong generation signals
    if ARTICLE_DOC.search(text_lower):
        return True  # "write AN APPLICATION for leave" → generate

    if DOC_TYPES.search(text_lower) and TOPIC_INDICATORS.search(text_lower):
        return True  # "application FOR leave" → generate

    # "about X" pattern at start → generation
    if text_lower.startswith("about ") or text_lower.startswith("regarding "):
        return True

    # Contains "for" + document type → generation
    if DOC_TYPES.search(text_lower) and re.search(r'\bfor\b', text_lower):
        return True

    # Just a document type alone → generation
    # "application for leave" has doc type
    if DOC_TYPES.search(text_lower):
        # But not if it's very short and looks literal like just the word
        words = text_lower.split()
        if len(words) >= 2:
            return True

    # Default: literal text (just type it)
    return False


def _exec_write_in_app(params: Dict[str, str], notify: Callable,
                       stop_event: Optional[threading.Event] = None) -> str:
    """
    Execute: open app → focus edit area → type OR generate text.
    
    Improvements over V1:
      - Stop event checks before every sub-operation
      - 3-tier text input with verification (UIA → clipboard → typewrite)
      - Post-type verification via screen_verifier
      - Increased window timeouts (2000ms for app launch)
      - Real-time progress notifications
    """
    app = params.get("app", "notepad")
    text = params.get("text", "")
    if not text:
        return "No text specified to write"

    def _stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    # ── AGI Decision: Is this literal text or a generation request? ──
    if _needs_generation(text):
        logger.info(f"[ScreenAgent] Smart detect: '{text[:40]}' → GENERATION request")
        compose_params = {
            "app": app,
            "topic": text,
            "style": _detect_style(text),
        }
        return _exec_compose(compose_params, notify, stop_event=stop_event)

    logger.info(f"[ScreenAgent] Smart detect: '{text[:40]}' → LITERAL text")

    # ── Step 1: Open/focus app ────────────────────────────────────────────
    if _stopped():
        return "Stopped before opening app"
    notify({"action": "open_app", "thought": f"Opening {app}..."})
    _open_or_focus(app)
    # Fix #3: Longer wait for write operations — Office apps need 3-5s
    # for splash screens ("Blank document", loading add-ins, etc.)
    _office_apps = {"word", "excel", "powerpoint", "winword", "powerpnt"}
    _wait_ms = 5000 if app.lower() in _office_apps else 3000
    window_ready = _wait_for_window_ready(app, max_ms=_wait_ms, stop_event=stop_event)
    if _stopped():
        return "Stopped while waiting for app"
    if not window_ready:
        logger.warning(f"[ScreenAgent] Window '{app}' not detected after {_wait_ms}ms — proceeding anyway")

    # ── Step 2: Focus editing area ─────────────────────────────────────────
    if _stopped():
        return "Stopped before focusing"
    notify({"action": "focus", "thought": "Focusing editing area..."})
    _focus_edit_area_robust(app)

    # Post-focus stabilization
    time.sleep(0.3)
    if _stopped():
        return "Stopped before typing"

    # ── Step 3: Type text with 3-tier fallback + verification ─────────────
    notify({"action": "type", "thought": f"Typing: {text[:40]}..."})
    typed_ok = False

    # Tier 1: UIA type_text (clipboard-paste, most reliable for Unicode)
    if HAS_UI_CTRL and ui_ctrl and not typed_ok:
        try:
            typed_ok = ui_ctrl.type_text(text, use_clipboard=True)
            if typed_ok:
                logger.info("[ScreenAgent] Text typed via UIA clipboard paste")
        except Exception as e:
            logger.debug(f"[ScreenAgent] UIA type_text failed: {e}")

    # Tier 2: Direct pyperclip + Ctrl+V
    if not typed_ok and HAS_PYAUTOGUI:
        try:
            import pyperclip  # type: ignore[import-untyped]
            pyperclip.copy(text)
            time.sleep(0.05)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.1)
            typed_ok = True
            logger.info("[ScreenAgent] Text typed via direct clipboard paste")
        except Exception as e:
            logger.debug(f"[ScreenAgent] Direct paste failed: {e}")

    # Tier 3: Character-by-character typewrite (ASCII only, slow but reliable)
    if not typed_ok and HAS_PYAUTOGUI and text.isascii():
        try:
            pyautogui.typewrite(text, interval=0.02)
            typed_ok = True
            logger.info("[ScreenAgent] Text typed via typewrite (char-by-char)")
        except Exception as e:
            logger.debug(f"[ScreenAgent] Typewrite failed: {e}")

    if not typed_ok:
        logger.error("[ScreenAgent] All text input methods failed for '%s'", app)
        return f"Failed to type text in {app} — all input methods failed"

    # ── Step 4: Post-type verification ────────────────────────────────────
    # Quick verification: check that the app window is still active
    try:
        if HAS_UI_CTRL and ui_ctrl:
            win = ui_ctrl.get_focused_window()
            if win:
                title = getattr(win, 'Name', '') or ''
                app_lower = app.lower()
                aliases = _APP_ALIASES.get(app_lower, [app_lower])
                is_correct = any(a in title.lower() for a in aliases)
                if is_correct:
                    logger.info(f"[ScreenAgent] ✓ Verified: '{app}' still focused after typing")
                else:
                    logger.warning(f"[ScreenAgent] ✗ Window focus changed: expected '{app}', got '{title[:40]}'")
    except Exception:
        pass

    notify({"action": "complete", "thought": f"✓ Typed {len(text)} chars in {app}"})
    return f"Typed '{text[:40]}' in {app} ({len(text)} chars)"


def _detect_style(text: str) -> str:
    """Detect the writing style from the text content."""
    import re
    text_lower = text.lower()
    STYLE_MAP = [
        (r'\b(application|aavedan)\b', "application"),
        (r'\b(letter|patra)\b', "letter"),
        (r'\b(email|mail)\b', "email"),
        (r'\b(essay|nibandh)\b', "essay"),
        (r'\b(poem|kavita)\b', "poem"),
        (r'\b(story|kahani)\b', "story"),
        (r'\b(article|lekh)\b', "article"),
        (r'\b(report)\b', "report"),
        (r'\b(code|program|script)\b', "code"),
        (r'\b(resume|cv)\b', "resume"),
        (r'\b(speech)\b', "speech"),
        (r'\b(proposal)\b', "proposal"),
        (r'\b(summary)\b', "summary"),
        (r'\b(review)\b', "review"),
        (r'\b(blog|post)\b', "blog post"),
        (r'\b(invitation)\b', "invitation"),
        (r'\b(notice)\b', "notice"),
        (r'\b(complaint)\b', "complaint"),
        (r'\b(paragraph)\b', "paragraph"),
    ]
    for pattern, style in STYLE_MAP:
        if re.search(pattern, text_lower):
            return style
    return "content"  # Generic fallback


def _focus_edit_area_robust(app_name: str) -> bool:
    """
    Focus the editing area of the active window with 4-tier fallback.
    Called before typing/pasting content. Returns True if focus was achieved.

    Fix #3: Added Office splash screen bypass (Tier 0).
    When Word/Excel/PowerPoint opens, they show a splash screen with
    template options. We need to dismiss it before trying to focus.

    Tier 0: Office splash screen bypass (Escape + wait)
    Tier 1: UIA SetFocus on edit control (most reliable)
    Tier 2: Visual UI coordinate detection
    Tier 3: Click center of window (last resort)
    """
    focused = False
    app_lower = app_name.lower().strip()

    # ── Tier 0: Office splash screen bypass ───────────────────────────
    # Word/Excel/PowerPoint show a splash with "Blank document" etc.
    # Escape dismisses it, or we wait for it to auto-close.
    _office_apps = {"word", "excel", "powerpoint", "winword", "powerpnt"}
    if app_lower in _office_apps and HAS_PYAUTOGUI:
        try:
            # Check if the current window title suggests a splash screen
            w = get_active_window()
            title = w.get("title", "").lower()
            # Splash screens often have titles like "Word", "Start",
            # or no document name yet
            is_splash = (
                title in ("word", "excel", "powerpoint", "")
                or "start" in title
                or "recent" in title
                or not any(ext in title for ext in [".doc", ".xls", ".ppt", "document", "book", "presentation", "untitled"])
            )
            if is_splash:
                logger.info(f"[ScreenAgent] Office splash detected (title='{title}') — sending Escape")
                pyautogui.press('escape')
                time.sleep(1.0)  # Wait for new blank document to load
                # After Escape, focus may need a click
                try:
                    w2 = get_active_window()
                    if w2.get("width", 0) > 0:
                        cx = w2["left"] + w2["width"] // 2
                        cy = w2["top"] + w2["height"] // 2
                        pyautogui.click(cx, cy)
                        time.sleep(0.3)
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"[ScreenAgent] Office splash check error: {e}")

    # Tier 1: UIA direct focus
    if HAS_UI_CTRL and ui_ctrl:
        try:
            focused = ui_ctrl.focus_edit_area(app_name)
            if focused:
                logger.info("[ScreenAgent] Edit area focused via UIA")
                return True
        except Exception as e:
            logger.debug(f"[ScreenAgent] UIA focus_edit_area failed: {e}")

    # Tier 2: Visual UI
    if not focused and HAS_VISUAL_UI and visual_ui:
        try:
            coords = visual_ui.get_editing_area()
            if coords and HAS_PYAUTOGUI:
                pyautogui.click(*coords)
                focused = True
                logger.info(f"[ScreenAgent] Visual UI: clicked editing area at {coords}")
                return True
        except Exception:
            pass

    # Tier 3: Click center of active window
    if not focused:
        try:
            w = get_active_window()
            if HAS_PYAUTOGUI and w.get("width", 0) > 0:
                cx = w["left"] + w["width"] // 2
                cy = w["top"] + w["height"] // 2
                pyautogui.click(cx, cy)
                logger.info(f"[ScreenAgent] Focused via center click at ({cx}, {cy})")
                focused = True
        except Exception as e:
            logger.warning(f"[ScreenAgent] Center click failed: {e}")

    if not focused:
        logger.warning("[ScreenAgent] All focus methods failed for '%s'", app_name)
    return focused


def _exec_compose(params: Dict[str, str], notify: Callable,
                  stop_event: Optional[threading.Event] = None) -> str:
    """Execute: open app → focus → generate text → paste.
    
    Now includes stop checks, longer timeouts, and paste verification.
    """
    app = params.get("app", "notepad")
    topic = params.get("topic", "")
    style = params.get("style", "essay")
    if not topic:
        # Safety net: if topic extraction failed upstream, use style as topic hint
        # e.g. style="application" → topic="application" → generates a generic application
        if style and style != "essay" and style != "content":
            topic = style
            logger.warning(f"[ScreenAgent] Compose: no topic — falling back to style '{style}' as topic")
        else:
            logger.error("[ScreenAgent] Compose: no topic and no usable style fallback")
            return "No topic specified"

    def _stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    # Step 1: Open/focus app
    if _stopped():
        return "Stopped before opening app"
    notify({"action": "open_app", "thought": f"Opening {app}..."})
    _open_or_focus(app)
    _wait_for_window_ready(app, max_ms=3000, stop_event=stop_event)
    if _stopped():
        return "Stopped while waiting for app"

    # Step 2: Focus editing area (first focus — before generation)
    if _stopped():
        return "Stopped before focusing"
    notify({"action": "focus", "thought": "Focusing editing area..."})
    _focus_edit_area_robust(app)
    time.sleep(0.3)  # Post-focus stabilization

    # Step 3: Generate content
    if _stopped():
        return "Stopped before generating content"
    notify({"action": "compose", "thought": f"✍️ Writing {style} about '{topic[:30]}'..."})
    logger.info(f"[ScreenAgent] Generating text: topic='{topic[:50]}', style='{style}'")
    text = _generate_text(topic, style)
    logger.info(f"[ScreenAgent] Generated {len(text)} chars (starts: '{text[:60]}…')")
    if _stopped():
        return "Stopped after content generation"
    if not text or len(text.strip()) < 5:
        logger.error("[ScreenAgent] Generated text is empty or too short")
        return f"Failed to generate {style} about '{topic[:30]}' — LLM returned empty text"

    # ── Step 3.5: RE-FOCUS edit area before paste ────────────────────────
    # The LLM API call takes 300ms–2s. During that time focus may drift
    # (Windows notifications, user click, antivirus popup, etc.).
    # Re-focus is CRITICAL for reliable paste.
    logger.info("[ScreenAgent] Re-focusing edit area after text generation...")
    _focus_edit_area_robust(app)
    time.sleep(0.2)  # Settle after re-focus

    # Step 4: Paste with 3-tier fallback
    notify({"action": "paste", "thought": f"Pasting {len(text)} chars..."})
    pasted_ok = False

    # Tier 1: UIA clipboard paste
    if HAS_UI_CTRL and ui_ctrl:
        try:
            pasted_ok = ui_ctrl.type_text(text, use_clipboard=True)
            if pasted_ok:
                logger.info("[ScreenAgent] ✓ Pasted via UIA clipboard")
        except Exception as e:
            logger.warning(f"[ScreenAgent] UIA paste failed: {e}")

    # Tier 2: Direct clipboard paste
    if not pasted_ok and HAS_PYAUTOGUI:
        try:
            import pyperclip  # type: ignore[import-untyped]
            pyperclip.copy(text)
            time.sleep(0.1)
            pyautogui.hotkey('ctrl', 'v')
            time.sleep(0.2)
            pasted_ok = True
            logger.info("[ScreenAgent] ✓ Pasted via direct clipboard")
        except Exception as e:
            logger.warning(f"[ScreenAgent] Direct paste failed: {e}")

    # Tier 3: Typewrite (ASCII only)
    if not pasted_ok and HAS_PYAUTOGUI and text.isascii():
        try:
            if len(text) > 500:
                logger.warning("[ScreenAgent] Typewrite fallback truncating %d chars to 500", len(text))
            pyautogui.typewrite(text[:500], interval=0.01)
            pasted_ok = True
            logger.info("[ScreenAgent] ✓ Pasted via typewrite")
        except Exception as e:
            logger.warning(f"[ScreenAgent] Typewrite failed: {e}")

    if not pasted_ok:
        logger.error("[ScreenAgent] All paste methods failed for compose in '%s'", app)
        return f"Generated {style} ({len(text)} chars) but failed to paste in {app}"

    # Step 5: Post-paste verification
    try:
        if HAS_UI_CTRL and ui_ctrl:
            win = ui_ctrl.get_focused_window()
            if win:
                title = getattr(win, 'Name', '') or ''
                app_lower = app.lower()
                aliases = _APP_ALIASES.get(app_lower, [app_lower])
                is_correct = any(a in title.lower() for a in aliases)
                if is_correct:
                    logger.info(f"[ScreenAgent] ✓ Verified: compose pasted in '{app}'")
                else:
                    logger.warning(f"[ScreenAgent] ✗ Window changed during paste: got '{title[:40]}'")
    except Exception:
        pass

    notify({"action": "complete", "thought": f"✓ Composed {style} ({len(text)} chars) in {app}"})
    return f"Composed {style} about '{topic[:30]}' in {app} ({len(text)} chars)"


def _exec_search_web(params: Dict[str, str], notify: Callable) -> str:
    """Execute: open browser → address bar → type query → enter."""
    app = params.get("app", "chrome")
    query = params.get("query", "")
    if not query:
        return "No search query specified"

    notify({"action": "open_app", "thought": f"Opening {app}..."})
    _open_or_focus(app)
    # Fix #31: Adaptive wait instead of fixed 1s sleep
    _wait_for_window_ready(app, max_ms=1500)

    notify({"action": "search", "thought": f"Searching '{query[:30]}'..."})
    if HAS_PYAUTOGUI:
        pyautogui.hotkey('ctrl', 'l')  # Focus address bar
        time.sleep(0.3)
        if HAS_UI_CTRL and ui_ctrl:
            ui_ctrl.type_text(query)
        else:
            import pyperclip  # type: ignore[import-untyped]
            pyperclip.copy(query)
            pyautogui.hotkey('ctrl', 'v')
        time.sleep(0.1)
        pyautogui.press('enter')

    return f"Searched '{query[:30]}' in {app}"


def _exec_window_mgmt(params: Dict[str, str], notify: Callable) -> str:
    """Execute: window management (minimize/maximize/close/snap)."""
    action = params.get("action", "")
    app = params.get("app", "")

    if app:
        focus_window(app)
        time.sleep(0.3)

    if not HAS_PYAUTOGUI:
        return "pyautogui not available"

    notify({"action": "window", "thought": f"Performing {action}..."})
    if action == "minimize":
        pyautogui.hotkey('win', 'down')
    elif action == "maximize":
        pyautogui.hotkey('win', 'up')
    elif action == "close":
        pyautogui.hotkey('alt', 'F4')
    elif action == "snap_left":
        pyautogui.hotkey('win', 'left')
    elif action == "snap_right":
        pyautogui.hotkey('win', 'right')
    else:
        return f"Unknown window action: {action}"

    return f"Window {action} done"


def _exec_file_ops(params: Dict[str, str], notify: Callable) -> str:
    """Execute: file operations (save/undo/copy/paste/etc.)."""
    action = params.get("action", "")
    if not HAS_PYAUTOGUI:
        return "pyautogui not available"

    notify({"action": "file_op", "thought": f"Performing {action}..."})
    shortcuts = {
        "save": ("ctrl", "s"),
        "undo": ("ctrl", "z"),
        "redo": ("ctrl", "y"),
        "copy": ("ctrl", "c"),
        "paste": ("ctrl", "v"),
        "cut": ("ctrl", "x"),
        "select_all": ("ctrl", "a"),
        "new": ("ctrl", "n"),
        "print": ("ctrl", "p"),
    }
    keys = shortcuts.get(action)
    if keys:
        pyautogui.hotkey(*keys)
        return f"Executed {action} (Ctrl+{keys[-1].upper()})"
    return f"Unknown file action: {action}"


def _exec_navigation(params: Dict[str, str], notify: Callable) -> str:
    """Execute: navigation actions (scroll/tabs/etc.)."""
    action = params.get("action", "")
    if not HAS_PYAUTOGUI:
        return "pyautogui not available"

    notify({"action": "navigate", "thought": f"Performing {action}..."})
    if action == "scroll_down":
        pyautogui.scroll(-5)
    elif action == "scroll_up":
        pyautogui.scroll(5)
    elif action == "next_tab":
        pyautogui.hotkey('ctrl', 'tab')
    elif action == "prev_tab":
        pyautogui.hotkey('ctrl', 'shift', 'tab')
    elif action == "new_tab":
        pyautogui.hotkey('ctrl', 't')
    elif action == "close_tab":
        pyautogui.hotkey('ctrl', 'w')
    elif action == "address_bar":
        pyautogui.hotkey('ctrl', 'l')
    elif action == "refresh":
        pyautogui.press('F5')
    else:
        return f"Unknown nav action: {action}"
    return f"Navigation: {action}"


def _exec_click(params: Dict[str, str], notify: Callable) -> str:
    """Execute: click at coordinates, on a UI element, or at current cursor position."""
    if not HAS_PYAUTOGUI:
        return "pyautogui not available"

    x = params.get("x", "")
    y = params.get("y", "")
    target = params.get("target", "").strip()

    if x and y:
        try:
            px, py = int(x), int(y)
            notify({"action": "click", "thought": f"Clicking at ({px}, {py})..."})
            pyautogui.click(px, py)
            return f"Clicked at ({px}, {py})"
        except (ValueError, TypeError):
            return f"Invalid coordinates: ({x}, {y})"

    # If target is "here", "current", "this", or empty, click at current mouse pointer
    if not target or target.lower() in ("here", "current", "this", "mouse", "cursor", "point"):
        cur_pos = pyautogui.position()
        notify({"action": "click", "thought": f"Clicking at current cursor position ({cur_pos.x}, {cur_pos.y})..."})
        pyautogui.click(cur_pos.x, cur_pos.y)
        return f"Clicked at ({cur_pos.x}, {cur_pos.y})"

    notify({"action": "click", "thought": f"Clicking '{target[:30]}'..."})

    # Strategy 1: Windows UI Automation Control Finder
    if HAS_UI_CTRL and ui_ctrl:
        try:
            btn = ui_ctrl.find_button(target)
            if btn:
                if ui_ctrl.click_control(btn):
                    return f"Clicked button '{target[:30]}' via UI Automation"
        except Exception as e:
            logger.debug(f"[ScreenAgent] UIA click failed: {e}")

    # Strategy 2: Visual UI OCR & Contour Detection
    if HAS_VISUAL_UI and visual_ui:
        try:
            coords = visual_ui.find_element(target)
            if coords:
                pyautogui.click(coords[0], coords[1])
                return f"Clicked '{target[:30]}' at ({coords[0]}, {coords[1]})"
        except Exception as e:
            logger.warning(f"[ScreenAgent] Visual click failed: {e}")

    # Strategy 3: Multimodal Vision Engine Coordinate Localization
    try:
        from engines.vision_engine import vision_engine
        loc = vision_engine.locate_element(target)
        if loc and loc.get("found"):
            screen_w, screen_h = pyautogui.size()
            norm_x = loc.get("x", 0.5)
            norm_y = loc.get("y", 0.5)
            px = int(norm_x * screen_w)
            py = int(norm_y * screen_h)
            pyautogui.click(px, py)
            return f"Located and clicked '{target[:30]}' at ({px}, {py})"
    except Exception as e:
        logger.debug(f"[ScreenAgent] Vision localization failed: {e}")

    # Fallback: Click center of active foreground window
    try:
        from engines.app_manager import get_active_window
        w = get_active_window()
        if w and w.get("width", 0) > 0:
            cx = w["left"] + w["width"] // 2
            cy = w["top"] + w["height"] // 2
            pyautogui.click(cx, cy)
            return f"Clicked center of active window '{w.get('title', '')[:30]}' at ({cx}, {cy})"
    except Exception:
        pass

    return f"Could not locate '{target[:30]}' on screen"


# ── Fix #2 & #8: Actual file sending/sharing ─────────────────────────────────

def _exec_send_file(params: Dict[str, str], notify: Callable,
                    stop_event: Optional[threading.Event] = None) -> str:
    """
    Execute: find file → open target app → attach file.

    Strategy:
      1. Search for the file across common user directories
      2. Copy the file path to clipboard
      3. Open the target messaging app (WhatsApp/Telegram/Discord/Email)
      4. Use the app's attachment shortcut to send the file

    This replaces the old behavior of just typing the filename as text.
    """
    import glob

    file_name = params.get("file_name") or params.get("file") or params.get("path") or ""
    file_type = params.get("file_type", "file")
    target_app = params.get("target_app") or params.get("target") or "whatsapp"
    contact = params.get("contact", "")

    def _stopped() -> bool:
        return stop_event is not None and stop_event.is_set()

    # ── Step 1: Find the file ────────────────────────────────────────────
    notify({"action": "search", "thought": f"🔍 Searching for {file_name or file_type}..."})

    home = os.path.expanduser("~")
    search_dirs = [
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "Pictures"),
        os.path.join(home, "Videos"),
    ]

    # File type → extension mapping
    _ext_map = {
        "pdf": ["*.pdf"],
        "document": ["*.docx", "*.doc", "*.pdf", "*.txt"],
        "photo": ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.gif"],
        "image": ["*.jpg", "*.jpeg", "*.png", "*.bmp", "*.gif"],
        "video": ["*.mp4", "*.avi", "*.mkv", "*.mov"],
        "resume": ["*resume*", "*cv*"],
        "report": ["*report*"],
        "presentation": ["*.pptx", "*.ppt"],
        "file": ["*"],  # Generic
    }
    extensions = _ext_map.get(file_type, ["*"])

    found_file = None

    # If already a valid local file path, use it directly
    if file_name and os.path.isfile(file_name):
        found_file = os.path.abspath(file_name)

    # Search strategy: exact name first, then by type
    if not found_file:
        for search_dir in search_dirs:
            if not os.path.isdir(search_dir):
                continue

            # 1. Try exact filename match
            if file_name:
                for entry in os.listdir(search_dir):
                    entry_lower = entry.lower()
                    name_lower = file_name.lower()
                    if name_lower in entry_lower:
                        found_file = os.path.join(search_dir, entry)
                        break

            # 2. Try extension-based search
            if not found_file:
                for ext_pattern in extensions:
                    matches = glob.glob(os.path.join(search_dir, ext_pattern))
                    if matches:
                        # Sort by modification time (newest first)
                        matches.sort(key=os.path.getmtime, reverse=True)
                        found_file = matches[0]
                        break

            if found_file:
                break

    if not found_file:
        return f"Could not find {file_name or file_type} file in Desktop, Documents, or Downloads"

    if _stopped():
        return "Stopped before opening target app"

    logger.info(f"[ScreenAgent] Found file: {found_file}")
    notify({"action": "found", "thought": f"📄 Found: {os.path.basename(found_file)}"})

    # ── Step 2: Open the target messaging app ────────────────────────────
    notify({"action": "open_app", "thought": f"Opening {target_app}..."})
    _open_or_focus(target_app)
    _wait_for_window_ready(target_app, max_ms=3000, stop_event=stop_event)

    if _stopped():
        return "Stopped while opening target app"

    # ── Step 3: Search for contact if specified ──────────────────────────
    if contact and HAS_PYAUTOGUI:
        time.sleep(0.5)
        # Most messaging apps: Ctrl+K or click search to find contact
        notify({"action": "search_contact", "thought": f"Finding {contact}..."})

        _app_search_shortcuts = {
            "whatsapp": [("ctrl", "f")],    # WhatsApp Desktop search
            "telegram": [("ctrl", "f")],    # Telegram search
            "discord": [("ctrl", "k")],     # Discord quick switcher
            "slack": [("ctrl", "k")],       # Slack quick switcher
        }
        shortcuts = _app_search_shortcuts.get(target_app.lower(), [("ctrl", "f")])
        for keys in shortcuts:
            pyautogui.hotkey(*keys)
            time.sleep(0.5)

        # Type contact name
        try:
            import pyperclip  # type: ignore[import-untyped]
            pyperclip.copy(contact)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.8)
            pyautogui.press("enter")
            time.sleep(0.5)
        except Exception:
            pyautogui.typewrite(contact, interval=0.03)
            time.sleep(0.8)
            pyautogui.press("enter")
            time.sleep(0.5)

    if _stopped():
        return "Stopped before attaching file"

    # ── Step 4: Attach the file ──────────────────────────────────────────
    notify({"action": "attach", "thought": f"📎 Attaching {os.path.basename(found_file)}..."})

    # Copy file path to clipboard for the file dialog
    try:
        import pyperclip  # type: ignore[import-untyped]

        # Strategy A: Use the app's attachment button shortcut
        _attach_shortcuts = {
            "whatsapp": None,       # WhatsApp: click the paperclip icon
            "telegram": None,       # Telegram: click the paperclip icon
            "discord": None,        # Discord: click the + button
            "slack": None,          # Slack: click the + button
            "email": [("ctrl", "shift", "a")],  # Outlook attach
            "mail": [("ctrl", "shift", "a")],
        }

        shortcut = _attach_shortcuts.get(target_app.lower())
        if shortcut:
            pyautogui.hotkey(*shortcut[0])
            time.sleep(1.0)
        else:
            # For WhatsApp/Telegram/Discord: use drag-and-drop via clipboard
            # Copy the file path, then paste it in the message area
            # Most modern apps accept file paths pasted into the chat
            pyperclip.copy(found_file)
            time.sleep(0.2)

            # Try Windows Shell copy-file-to-clipboard approach
            # This puts the actual FILE on the clipboard (not just the path text)
            try:
                import ctypes
                from ctypes import wintypes
                import struct

                # Use PowerShell to copy file to clipboard
                ps_cmd = f'Add-Type -AssemblyName System.Windows.Forms; ' \
                         f'$files = [System.Collections.Specialized.StringCollection]::new(); ' \
                         f'$files.Add("{found_file}"); ' \
                         f'[System.Windows.Forms.Clipboard]::SetFileDropList($files)'
                import subprocess
                subprocess.run(
                    ["powershell", "-Command", ps_cmd],
                    capture_output=True, timeout=5,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                time.sleep(0.3)

                # Now Ctrl+V will paste the FILE (not text)
                pyautogui.hotkey("ctrl", "v")
                time.sleep(1.0)

                # Press Enter to send (works in WhatsApp/Telegram)
                pyautogui.press("enter")
                time.sleep(0.5)

                logger.info(f"[ScreenAgent] File attached via clipboard file-copy: {found_file}")
                notify({"action": "complete",
                        "thought": f"✓ Sent {os.path.basename(found_file)} on {target_app}"})
                return f"Sent '{os.path.basename(found_file)}' on {target_app}"

            except Exception as e:
                logger.warning(f"[ScreenAgent] Clipboard file-copy failed: {e}")

        # Fallback: type the file path and let user know
        pyperclip.copy(found_file)
        pyautogui.hotkey("ctrl", "v")
        notify({"action": "complete",
                "thought": f"📋 File path copied — paste in {target_app}'s file dialog"})
        return f"File path copied to clipboard: {os.path.basename(found_file)} — paste in {target_app}'s attachment dialog"

    except Exception as e:
        logger.error(f"[ScreenAgent] File attach failed: {e}")
        return f"Failed to attach file: {e}"


# ── Level 2 Workflow Executors ────────────────────────────────────────────────

def _exec_create_blog(params: Dict[str, str], notify: Callable,
                      stop_event: Optional[threading.Event] = None) -> str:
    """Execute the blog creation workflow (generate → AI check → publish)."""
    try:
        from engines.workflow_engine import WorkflowEngine
        from engines.workflows.blog_publisher import BlogPublishWorkflow

        workflow = BlogPublishWorkflow()
        engine = WorkflowEngine(notify_fn=notify, stop_event=stop_event)

        # Run the async workflow from sync context
        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(engine.run(workflow, params))
        finally:
            loop.close()

        if result.success:
            url = result.data.get("published_url", "")
            return f"✅ Blog published! {url}"
        else:
            return f"Blog workflow failed: {result.message}"
    except Exception as e:
        logger.error(f"[ScreenAgent] Blog workflow error: {e}")
        return f"Blog creation failed: {e}"


def _exec_create_short(params: Dict[str, str], notify: Callable,
                       stop_event: Optional[threading.Event] = None) -> str:
    """Execute the YouTube Shorts workflow (find → Opus Clip → upload)."""
    try:
        from engines.workflow_engine import WorkflowEngine
        from engines.workflows.youtube_shorts import YouTubeShortsWorkflow

        workflow = YouTubeShortsWorkflow()
        engine = WorkflowEngine(notify_fn=notify, stop_event=stop_event)

        loop = asyncio.new_event_loop()
        try:
            result = loop.run_until_complete(engine.run(workflow, params))
        finally:
            loop.close()

        if result.success:
            url = result.data.get("youtube_url", "")
            return f"✅ Short uploaded to YouTube! {url}"
        else:
            return f"Shorts workflow failed: {result.message}"
    except Exception as e:
        logger.error(f"[ScreenAgent] Shorts workflow error: {e}")
        return f"YouTube short creation failed: {e}"


# ── Action dispatch table ────────────────────────────────────────────────────
ACTION_EXECUTORS: Dict[str, Callable] = {
    "open_app": _exec_open_app,
    "write_in_app": _exec_write_in_app,
    "compose": _exec_compose,
    "search_web": _exec_search_web,
    "window_mgmt": _exec_window_mgmt,
    "file_ops": _exec_file_ops,
    "navigation": _exec_navigation,
    "click": _exec_click,
    "send_file": _exec_send_file,
    # Level 2 workflows
    "create_blog": _exec_create_blog,
    "create_short": _exec_create_short,
}

# ── Lazy Tier Module Loader (saves ~1,500ms startup) ─────────────────────────
# Instead of importing all 15 modules at module level, we load on first use.
_tier_cache: Dict[str, Any] = {}

def _lazy_load(name: str, module_path: str, attr: str):
    """Import a tier module lazily. Returns (obj, True) or (None, False)."""
    key = f"{module_path}.{attr}"
    if key in _tier_cache:
        return _tier_cache[key]
    try:
        import importlib
        mod = importlib.import_module(module_path)
        obj = getattr(mod, attr)
        _tier_cache[key] = (obj, True)
        return (obj, True)
    except (ImportError, AttributeError) as e:
        logger.debug(f"[ScreenAgent] Lazy load {key} skipped: {e}")
        _tier_cache[key] = (None, False)
        return (None, False)

# Tier flags — set True on first successful lazy load
HAS_MEMORY = HAS_VERIFIER = HAS_CLIPBOARD = False
HAS_SCREEN_CTX = HAS_APP_KNOWLEDGE = HAS_USER_PROFILE = False
HAS_FILE_INTEL = HAS_PROACTIVE = False
HAS_LTM = HAS_PLANNER = HAS_VOICE_ID = HAS_SPECULATIVE = HAS_VISUAL_UI = False

# Lazy accessors (cache after first call)
action_memory = None      # type: ignore[assignment]
clipboard_intel = None     # type: ignore[assignment]
screen_context = None      # type: ignore[assignment]
user_profile = None        # type: ignore[assignment]
file_intel = None          # type: ignore[assignment]
proactive_engine = None    # type: ignore[assignment]
long_term_memory = None    # type: ignore[assignment]
conversational_planner = None  # type: ignore[assignment]
voice_fingerprint = None   # type: ignore[assignment]
speculative_executor = None  # type: ignore[assignment]
visual_ui = None           # type: ignore[assignment]

def _init_tier_modules():
    """Load all tier modules (called once on first task start)."""
    global action_memory, clipboard_intel, screen_context, user_profile
    global file_intel, proactive_engine, long_term_memory, conversational_planner
    global voice_fingerprint, speculative_executor, visual_ui
    global HAS_MEMORY, HAS_VERIFIER, HAS_CLIPBOARD, HAS_SCREEN_CTX
    global HAS_APP_KNOWLEDGE, HAS_USER_PROFILE, HAS_FILE_INTEL, HAS_PROACTIVE
    global HAS_LTM, HAS_PLANNER, HAS_VOICE_ID, HAS_SPECULATIVE, HAS_VISUAL_UI

    if _tier_cache.get("_initialized"):
        return  # Already loaded
    _tier_cache["_initialized"] = True
    t0 = time.time()

    # Tier 1
    obj, HAS_MEMORY = _lazy_load("T1", "engines.action_memory", "action_memory")
    if obj: action_memory = obj
    try:
        from engines.screen_verifier import verify_action  # type: ignore[import]
        HAS_VERIFIER = True
        _tier_cache["verify_action"] = verify_action
    except ImportError:
        pass
    obj, HAS_CLIPBOARD = _lazy_load("T1", "engines.clipboard_intel", "clipboard_intel")
    if obj: clipboard_intel = obj

    # Tier 2
    obj, HAS_SCREEN_CTX = _lazy_load("T2", "engines.screen_context", "screen_context")
    if obj: screen_context = obj
    try:
        from engines.app_knowledge import get_shortcut, get_app_info, suggest_shortcut  # type: ignore[import]
        HAS_APP_KNOWLEDGE = True
    except ImportError:
        pass
    obj, HAS_USER_PROFILE = _lazy_load("T2", "engines.user_profile", "user_profile")
    if obj: user_profile = obj
    obj, HAS_FILE_INTEL = _lazy_load("T2", "engines.file_intel", "file_intel")
    if obj: file_intel = obj
    obj, HAS_PROACTIVE = _lazy_load("T2", "engines.proactive_engine", "proactive_engine")
    if obj: proactive_engine = obj

    # Tier 3
    obj, HAS_LTM = _lazy_load("T3", "engines.long_term_memory", "long_term_memory")
    if obj: long_term_memory = obj
    obj, HAS_PLANNER = _lazy_load("T3", "engines.conversational_planner", "conversational_planner")
    if obj: conversational_planner = obj
    obj, HAS_VOICE_ID = _lazy_load("T3", "engines.voice_fingerprint", "voice_fingerprint")
    if obj: voice_fingerprint = obj
    obj, HAS_SPECULATIVE = _lazy_load("T3", "engines.speculative_executor", "speculative_executor")
    if obj: speculative_executor = obj
    obj, HAS_VISUAL_UI = _lazy_load("T3", "engines.visual_ui", "visual_ui")
    if obj: visual_ui = obj

    elapsed = (time.time() - t0) * 1000
    logger.info(f"[ScreenAgent] Tier modules loaded in {elapsed:.0f}ms")

# ═════════════════════════════════════════════════════════════════════════════
#  MULTI-STEP CHAINING — Split compound commands into steps
# ═════════════════════════════════════════════════════════════════════════════

import re as _re_chain

_CHAIN_SPLIT = _re_chain.compile(
    r'\s+(?:and then|and also|and|then|after that|phir|aur phir|aur|uske baad)\s+',
    _re_chain.IGNORECASE
)


def _split_compound_command(command: str) -> List[str]:
    """
    Split compound commands into individual steps.
    "open notepad and write hello and save file"
    → ["open notepad", "write hello", "save file"]

    Fix #33: Protect 'about' content — don't split 'and' within an
    'about...' topic phrase (e.g. "write about cats and dogs" stays intact).
    """
    text = command.strip()

    # Protection: if text contains 'about X and Y' pattern, don't split on
    # the 'and' that's part of the topic. Replace it temporarily.
    import re as _re_about
    # Match 'about <words> and <words>' where 'and' is inside the topic
    _about_protect = _re_about.compile(
        r'(\babout\s+\w+(?:\s+\w+)*)\s+and\s+(\w+(?:\s+\w+)*?)(?=\s+(?:and then|then|after that|phir|aur phir|uske baad)\b|$)',
        _re_about.IGNORECASE
    )
    protected = _about_protect.sub(r'\1 __AND__ \2', text)

    # Only split if chain words exist in the text
    if _CHAIN_SPLIT.search(protected):
        parts = _CHAIN_SPLIT.split(protected)
        # Restore protected 'and' tokens
        steps = [p.strip().replace('__AND__', 'and') for p in parts if p.strip() and len(p.strip()) > 2]
        if len(steps) > 1:
            logger.info(f"[ScreenAgent] Chained {len(steps)} steps: {steps}")
            return steps
    return [text]


# ═════════════════════════════════════════════════════════════════════════════
#  SCREEN AGENT — Main Orchestrator (AGI Tier 1 + Tier 2)
# ═════════════════════════════════════════════════════════════════════════════

class ScreenAgent:
    """
    V2 Screen Agent — Deterministic action scripts + AGI Tier 1 + 2 + 3.
    Tier 1: Self-learning memory, chaining, error recovery, verification, clipboard.
    Tier 2: Screen context, app knowledge, file intel, user profile, proactive.
    Tier 3: Long-term memory, conversational planner, voice ID, speculative, visual UI.
    """

    def __init__(self) -> None:
        self._running: bool = False
        self._stop_event = threading.Event()  # Replaces bool flag for instant cross-thread signaling
        self._current_task_id: Optional[str] = None
        self._task_thread: Optional[threading.Thread] = None
        self._last_command: str = ""
        self._last_start_time: float = 0
        # Note: Tier module services (clipboard, screen context, file intel)
        # are initialized lazily on first task via _init_tier_modules()

    # ── Public API (backward compatible) ─────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def current_task_id(self) -> Optional[str]:
        return self._current_task_id

    @property
    def steps_taken(self) -> int:
        return 0

    def start_task(self, task_id: str, command: str,
                   notify_fn: Optional[Callable[..., Any]] = None) -> bool:
        """Start a screen task. Returns False if already running or cooldown."""
        if self._running:
            return False
        if time.time() - self._last_start_time < 2.0:
            logger.warning("[ScreenAgent] Cooldown — ignoring rapid re-trigger")
            return False

        self._running = True
        self._current_task_id = task_id
        self._last_start_time = time.time()

        self._task_thread = threading.Thread(
            target=self._run_task, args=(task_id, command, notify_fn), daemon=True)
        self._task_thread.start()
        return True

    def stop_task(self) -> None:
        """Request graceful stop — task will halt at next checkpoint."""
        self._stop_event.set()
        logger.info("[ScreenAgent] Stop requested (event set)")

    def force_stop(self) -> None:
        """
        Force-kill the current task immediately:
          1. Set the stop event
          2. Send Escape key to dismiss any modal dialogs
          3. Restore clipboard
          4. Mark task as aborted
        """
        self._stop_event.set()
        logger.warning("[ScreenAgent] FORCE STOP — aborting task '%s'", self._current_task_id)
        # Send Escape to cancel any in-progress dialogs
        try:
            if HAS_PYAUTOGUI:
                pyautogui.press('escape')
        except Exception:
            pass
        # Restore clipboard
        try:
            if HAS_UI_CTRL and ui_ctrl:
                ui_ctrl.restore_clipboard()
        except Exception:
            pass
        # Force-clear running state
        self._running = False
        self._current_task_id = None

    def _check_stop(self) -> bool:
        """Check if stop has been requested. Call before every sub-operation."""
        return self._stop_event.is_set()

    async def classify_intent(self, user_message: str) -> Dict[str, Any]:
        """Classify intent using semantic cache."""
        if HAS_SEMANTIC:
            result = semantic_classify(user_message)
            return {
                "intent": "screen_task" if result["is_screen_task"] else "chat",
                "sub_intent": result["intent"],
                "confidence": result["confidence"],
            }
        return {"intent": "chat"}

    # ── Task Execution (AGI Tier 1 + Tier 2) ────────────────────────────

    def _run_task(self, task_id: str, command: str,
                  notify_fn: Optional[Callable[..., Any]] = None) -> None:
        """Execute a screen task with all AGI features."""
        self._stop_event.clear()  # Reset stop event for this task
        t0 = time.time()

        # ── Initialize tier modules on first task (lazy load) ────────────
        _init_tier_modules()

        logger.info(f"[ScreenAgent] Task '{task_id}': {command}")

        # Save clipboard
        if HAS_UI_CTRL and ui_ctrl:
            ui_ctrl.save_clipboard()

        def notify(data: dict) -> None:
            if notify_fn:
                try:
                    notify_fn({"type": "screen_task_progress", "task_id": task_id,
                               "step": 1, "estimated_total": 3, **data})
                except Exception:
                    pass

        try:
            # ── Tier 3: Long-Term Memory intercept ───────────────────────
            if HAS_LTM and long_term_memory:
                # Check if user wants to remember something
                fact = long_term_memory.is_remember_command(command)
                if fact:
                    entry = long_term_memory.remember(fact)
                    summary = f"Remembered: {fact[:50]} [{entry.get('category', 'general')}]"
                    logger.info(f"[ScreenAgent] LTM STORE: {summary}")
                    if notify_fn:
                        notify_fn({"type": "screen_task_complete", "task_id": task_id,
                                   "steps": 1, "summary": f"🧠 {summary}"})
                    return

                # Check if user wants to recall something
                query = long_term_memory.is_recall_command(command)
                if query:
                    results = long_term_memory.recall(query)
                    if results:
                        facts = "; ".join(r["fact"] for r in results[:3])
                        summary = f"I remember: {facts}"
                    else:
                        summary = f"I don't have any memory about '{query}'"
                    logger.info(f"[ScreenAgent] LTM RECALL: {summary}")
                    if notify_fn:
                        notify_fn({"type": "screen_task_complete", "task_id": task_id,
                                   "steps": 1, "summary": f"🧠 {summary}"})
                    return

                # Check if user wants to forget something
                forget_q = long_term_memory.is_forget_command(command)
                if forget_q:
                    removed = long_term_memory.forget(forget_q)
                    summary = f"Forgot {removed} memories about '{forget_q}'" if removed else f"No memories about '{forget_q}'"
                    logger.info(f"[ScreenAgent] LTM FORGET: {summary}")
                    if notify_fn:
                        notify_fn({"type": "screen_task_complete", "task_id": task_id,
                                   "steps": 1, "summary": f"🧠 {summary}"})
                    return

            # ── Tier 3: Conversational Planning intercept ────────────────
            if HAS_PLANNER and conversational_planner:
                plan = conversational_planner.plan(command)
                if plan:
                    logger.info(f"[ScreenAgent] PLAN: {plan['name']} ({len(plan['steps'])} steps)")
                    if notify_fn:
                        notify_fn({"type": "screen_task_started", "task_id": task_id,
                                   "command": command, "plan": plan["name"],
                                   "total_steps": len(plan["steps"])})

                    all_summaries = []
                    for si, step in enumerate(plan["steps"]):
                        if self._check_stop():
                            break
                        action = step["action"]
                        params = step["params"]
                        desc = step.get("desc", action)
                        logger.info(f"[ScreenAgent] Plan step {si+1}/{len(plan['steps'])}: {desc}")

                        notify({"action": action, "step": si + 1,
                                "estimated_total": len(plan["steps"]),
                                "thought": desc})

                        executor = ACTION_EXECUTORS.get(action)
                        if executor:
                            # Context check: skip if app already focused
                            if action == "open_app" and HAS_SCREEN_CTX and screen_context:
                                app = params.get("app", "")
                                if app and screen_context.is_app_focused(app):
                                    all_summaries.append(f"{app} already open")
                                    continue

                            summary = self._execute_with_recovery(executor, params, notify, action)
                            all_summaries.append(summary)
                        else:
                            all_summaries.append(f"Unknown: {action}")

                        if si < len(plan["steps"]) - 1:
                            time.sleep(0.3)

                    elapsed = (time.time() - t0) * 1000
                    full_summary = f"📋 {plan['description']}: " + " → ".join(all_summaries)
                    logger.info(f"[ScreenAgent] Plan done: {full_summary} ({elapsed:.0f}ms)")
                    if notify_fn:
                        notify_fn({"type": "screen_task_complete", "task_id": task_id,
                                   "steps": len(plan["steps"]),
                                   "summary": f"{full_summary} ({elapsed:.0f}ms)"})
                    self._last_command = command
                    return

            # ── AGI Step 0: Check Self-Learning Memory ───────────────────
            if HAS_MEMORY and action_memory:
                cached = action_memory.lookup(command)
                if cached:
                    intent = cached["intent"]
                    params = cached["params"]
                    logger.info(f"[ScreenAgent] MEMORY HIT: {intent} (skipped classification)")

                    if notify_fn:
                        notify_fn({"type": "screen_task_started", "task_id": task_id,
                                   "command": command, "from_memory": True})

                    executor = ACTION_EXECUTORS.get(intent)
                    if executor:
                        summary = executor(params, notify)
                        elapsed = (time.time() - t0) * 1000
                        logger.info(f"[ScreenAgent] Memory replay done: {summary} ({elapsed:.0f}ms)")
                        if notify_fn:
                            notify_fn({"type": "screen_task_complete", "task_id": task_id,
                                       "steps": 1, "summary": f"⚡ {summary} (from memory, {elapsed:.0f}ms)"})
                        self._last_command = command
                        return

            # ── AGI Step 1: Split compound commands (chaining) ───────────
            steps = _split_compound_command(command)
            total_steps = len(steps)

            if notify_fn:
                notify_fn({"type": "screen_task_started", "task_id": task_id,
                           "command": command, "total_steps": total_steps})

            all_summaries = []
            # ── Fix #4: Carry app context between compound steps ──────
            # When "open Word AND write a letter", step 2 inherits app=word
            _chain_app_context = ""  # Last opened/focused app in this chain

            for step_idx, step_command in enumerate(steps):
                if self._check_stop():
                    logger.info("[ScreenAgent] Stop requested — aborting chain")
                    break

                logger.info(f"[ScreenAgent] Step {step_idx+1}/{total_steps}: {step_command}")

                # ── Classify intent for this step ────────────────────────
                if HAS_SEMANTIC:
                    result = semantic_classify(step_command)
                    intent = result["intent"]
                    confidence = result["confidence"]
                else:
                    from engines.semantic_intent import _keyword_classify
                    result = _keyword_classify(step_command)
                    intent = result["intent"]
                    confidence = result["confidence"]

                if intent == "chat" or not result.get("is_screen_task", False):
                    logger.info(f"[ScreenAgent] Step '{step_command}' = chat, skipping")
                    continue

                # ── Extract parameters ───────────────────────────────
                params = extract_params(step_command, intent)

                # ── Fix #4: Inject app context from previous step ─────
                # If this step has no app but a previous step opened one,
                # inherit it. "open word AND write hello" → write goes to word.
                if _chain_app_context and not params.get("app"):
                    params["app"] = _chain_app_context
                    logger.info(f"[ScreenAgent] Chain context: inherited app='{_chain_app_context}'")

                # Track which app was opened/used in this step
                if params.get("app"):
                    _chain_app_context = params["app"]

                # ── Tier 2: Context-aware optimization ────────────────
                if intent == "open_app" and HAS_SCREEN_CTX and screen_context:
                    app = params.get("app", "")
                    if app and screen_context.is_app_focused(app):
                        logger.info(f"[ScreenAgent] Context: {app} already focused — skipping open")
                        all_summaries.append(f"{app} already focused")
                        continue
                    elif app and screen_context.is_app_open(app):
                        logger.info(f"[ScreenAgent] Context: {app} is open but not focused — focusing")
                        try:
                            focus_window(app)
                            all_summaries.append(f"Focused {app}")
                            if HAS_USER_PROFILE and user_profile:
                                user_profile.record_app_use(app)
                            continue
                        except Exception:
                            pass  # Fall through to normal open

                # ── Execute with error recovery ──────────────────────────
                executor = ACTION_EXECUTORS.get(intent)
                if not executor:
                    all_summaries.append(f"Unknown: {intent}")
                    continue

                notify({"action": intent, "step": step_idx + 1,
                        "estimated_total": total_steps,
                        "thought": f"Step {step_idx+1}: {step_command[:40]}..."})

                summary = self._execute_with_recovery(executor, params, notify, intent)
                all_summaries.append(summary)

                # ── Tier 2: Record in user profile ─────────────────────
                if HAS_USER_PROFILE and user_profile:
                    user_profile.record_task(intent)
                    app = params.get("app", "")
                    if app:
                        user_profile.record_app_use(app)

                # ── AGI: Verify action (background) ──────────────────────
                if HAS_VERIFIER:
                    try:
                        _verify_fn = _tier_cache.get("verify_action")
                        if _verify_fn:
                            ok, verify_msg = _verify_fn(intent, params)
                            if ok:
                                logger.info(f"[ScreenAgent] ✓ Verified: {verify_msg}")
                            else:
                                logger.warning(f"[ScreenAgent] ✗ Verification failed: {verify_msg}")
                    except Exception as ve:
                        logger.debug(f"[ScreenAgent] Verify error: {ve}")

                # ── AGI: Remember action outcome ──────────────────────
                step_success = not (summary.lower().startswith("failed") or "error" in summary.lower())
                if HAS_MEMORY and action_memory:
                    action_memory.remember(step_command, intent, params,
                                          success=step_success,
                                          execution_time_ms=(time.time()-t0)*1000)

                # Brief pause between chain steps
                if step_idx < total_steps - 1:
                    time.sleep(0.3)

            # ── Send completion ──────────────────────────────────────────
            elapsed = (time.time() - t0) * 1000
            full_summary = " → ".join(all_summaries) if all_summaries else "No actions"
            logger.info(f"[ScreenAgent] All steps done: {full_summary} ({elapsed:.0f}ms)")

            if notify_fn:
                notify_fn({"type": "screen_task_complete", "task_id": task_id,
                           "steps": total_steps,
                           "summary": f"{full_summary} ({elapsed:.0f}ms)"})

            self._last_command = command

            # Remember the full compound command too if successful
            if HAS_MEMORY and action_memory and total_steps == 1 and not full_summary.lower().startswith("failed"):
                result = semantic_classify(command) if HAS_SEMANTIC else {"intent": "open_app"}
                params = extract_params(command, result["intent"])
                action_memory.remember(command, result["intent"], params, success=True)

        except Exception as e:
            logger.error(f"[ScreenAgent] Task error: {e}")
            if notify_fn:
                notify_fn({"type": "screen_task_failed", "task_id": task_id,
                           "error": str(e)})
        finally:
            if HAS_UI_CTRL and ui_ctrl:
                ui_ctrl.restore_clipboard()
            self._running = False
            self._stop_event.clear()  # Reset for next task
            self._current_task_id = None

    # ── Error Self-Recovery ──────────────────────────────────────────────

    def _execute_with_recovery(self, executor: Callable, params: Dict[str, str],
                                notify: Callable, intent: str,
                                max_retries: int = 2) -> str:
        """Execute an action with closed-loop visual verification and automatic retry on failure."""
        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                # Pass stop_event to executors that accept it
                import inspect
                sig = inspect.signature(executor)
                def _do_action():
                    if 'stop_event' in sig.parameters:
                        return executor(params, notify, stop_event=self._stop_event)
                    return executor(params, notify)

                # Execute with Visual Verifier Closed Loop
                try:
                    from engines.screen_verifier import visual_verifier
                    ok, summary = visual_verifier.execute_with_self_healing(intent, params, _do_action, notify)
                except Exception:
                    summary = _do_action()

                if ("error" not in summary.lower() and "fail" not in summary.lower()
                        and not summary.lower().startswith("no ")):
                    return summary
                last_error = summary
            except Exception as e:
                last_error = str(e)
                logger.warning(f"[ScreenAgent] Attempt {attempt+1} failed: {e}")

            if attempt < max_retries:
                logger.info(f"[ScreenAgent] Retrying ({attempt+2}/{max_retries+1})...")
                time.sleep(0.4)

                # Recovery strategies
                if intent == "open_app":
                    # Try alternative app names
                    app = params.get("app", "")
                    ALT_NAMES = {
                        "word": "winword", "chrome": "google chrome",
                        "vscode": "code", "explorer": "file explorer",
                    }
                    alt = ALT_NAMES.get(app.lower())
                    if alt:
                        params = {**params, "app": alt}
                        logger.info(f"[ScreenAgent] Recovery: trying alt name '{alt}'")

        return f"Failed after {max_retries+1} attempts: {last_error}"


# ═════════════════════════════════════════════════════════════════════════════
#  TASK MANAGER — Parallel Task Execution
# ═════════════════════════════════════════════════════════════════════════════
MAX_CONCURRENT_TASKS = 3


class TaskManager:
    """Manages multiple ScreenAgent instances for parallel task execution."""

    def __init__(self) -> None:
        self._agents: Dict[str, ScreenAgent] = {}

    def start_task(self, task_id: str, command: str,
                   notify_fn: Optional[Callable[..., Any]] = None) -> bool:
        self._agents = {k: v for k, v in self._agents.items() if v.is_running}
        if len(self._agents) >= MAX_CONCURRENT_TASKS:
            return False
        agent = ScreenAgent()
        self._agents[task_id] = agent
        return agent.start_task(task_id, command, notify_fn)

    def stop_task(self, task_id: str) -> bool:
        agent = self._agents.get(task_id)
        if agent and agent.is_running:
            agent.stop_task()
            return True
        return False

    def stop_all(self) -> None:
        for agent in self._agents.values():
            if agent.is_running:
                agent.stop_task()

    @property
    def running_count(self) -> int:
        return sum(1 for a in self._agents.values() if a.is_running)

    @property
    def is_any_running(self) -> bool:
        return any(a.is_running for a in self._agents.values())

    def get_status(self) -> List[Dict[str, Any]]:
        return [{"task_id": tid, "running": a.is_running, "steps": a.steps_taken}
                for tid, a in self._agents.items()]


# ═════════════════════════════════════════════════════════════════════════════
#  AUTONOMOUS VISUAL SET-OF-MARKS (SoM) TASK EXECUTION
# ═════════════════════════════════════════════════════════════════════════════

try:
    from agents.visual_grounding import visual_grounding_agent
    HAS_VISUAL_GROUNDING = True
except ImportError:
    try:
        import sys
        sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
        from agents.visual_grounding import visual_grounding_agent
        HAS_VISUAL_GROUNDING = True
    except Exception:
        visual_grounding_agent = None
        HAS_VISUAL_GROUNDING = False


def execute_visual_task(
    goal: str,
    max_steps: int = 6,
    notify_fn: Optional[Callable[..., Any]] = None,
) -> Dict[str, Any]:
    """
    Autonomous Set-of-Marks visual loop with self-healing action verification.
    1. Grounds current desktop UI using UIA + SoM tags.
    2. Emits frontend marks array via notify_fn.
    3. Identifies target mark using goal heuristics.
    4. Clicks/types into mark.
    5. Verifies visual outcome (pre/post screenshot diff).
    6. Recovers or completes.
    """
    if not HAS_VISUAL_GROUNDING or not visual_grounding_agent:
        return {"ok": False, "msg": "Visual Grounding agent not available"}

    logger.info("[ScreenAgent] Initiating autonomous visual task: '%s'", goal)
    steps_log = []

    for step in range(1, max_steps + 1):
        # 1. Ground screen
        grounding = visual_grounding_agent.ground_screen()
        if grounding.get("status") != "success":
            return {"ok": False, "msg": f"Grounding failed at step {step}", "steps": steps_log}

        frontend_marks = grounding.get("frontend_marks", [])
        if notify_fn:
            notify_fn({
                "type": "som_marks",
                "step": step,
                "goal": goal,
                "marks": frontend_marks,
            })

        # 2. Heuristic Target Selection
        target_mark = visual_grounding_agent.find_mark_by_fuzzy_name(goal)
        if not target_mark:
            # Try sub-intent terms
            for word in goal.split():
                if len(word) > 3 and word.lower() not in ("open", "click", "play", "type", "with"):
                    target_mark = visual_grounding_agent.find_mark_by_fuzzy_name(word)
                    if target_mark:
                        break

        if not target_mark and frontend_marks:
            # Fallback to first interactive button/item
            target_mark = visual_grounding_agent.last_marks.get(frontend_marks[0]["id"])

        if not target_mark:
            return {"ok": False, "msg": f"No target UI control identified for goal: '{goal}'", "steps": steps_log}

        target_id = target_mark["id"]
        target_name = target_mark["name"]
        logger.info("[ScreenAgent] Step %d: Targeting mark [%d] '%s'", step, target_id, target_name)

        if notify_fn:
            notify_fn({
                "type": "som_action_active",
                "step": step,
                "mark_id": target_id,
                "name": target_name,
                "action": "click",
            })

        pre_screen = visual_grounding_agent.last_screenshot

        # 3. Execute Action
        click_ok = visual_grounding_agent.click_mark(target_id)
        if not click_ok:
            return {"ok": False, "msg": f"Failed to click mark [{target_id}]", "steps": steps_log}

        time.sleep(0.4)  # UI settle time

        # 4. Self-Healing Action Verification
        post_screen = visual_grounding_agent.capture_screen()
        verification = visual_grounding_agent.verify_action_outcome(pre_screen, post_screen, target_id)
        logger.info("[ScreenAgent] Step %d verification: %s", step, verification.get("reason"))

        steps_log.append({
            "step": step,
            "target_mark_id": target_id,
            "target_name": target_name,
            "verification": verification,
        })

        if verification.get("verified", False):
            # Target action succeeded and screen state progressed!
            if notify_fn:
                notify_fn({
                    "type": "som_step_completed",
                    "step": step,
                    "target_id": target_id,
                    "target_name": target_name,
                    "success": True,
                })
            return {
                "ok": True,
                "msg": f"Executed visual task for '{goal}' at mark [{target_id}] ({target_name})",
                "steps": steps_log,
            }
        else:
            # Self-healing attempt: dismiss potential modal popup or retry
            logger.warning("[ScreenAgent] Step %d did not cause state change, trying escape recovery...", step)
            try:
                if HAS_PYAUTOGUI:
                    pyautogui.press("escape")
                    time.sleep(0.2)
            except Exception:
                pass

    return {"ok": True, "msg": f"Completed visual execution sequence for '{goal}'", "steps": steps_log}


# ═════════════════════════════════════════════════════════════════════════════
#  SINGLETONS + PRE-WARM
# ═════════════════════════════════════════════════════════════════════════════

screen_agent = ScreenAgent()
task_manager = TaskManager()

# Pre-warm semantic intent cache in background
if HAS_SEMANTIC:
    _prewarm_intent()

