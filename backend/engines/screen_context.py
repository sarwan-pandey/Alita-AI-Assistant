# pyre-ignore-all-errors
"""
Screen Context — Always knows what's on the user's screen.
Tracks: active window, app name, window title, recent app switches.
Lightweight polling (no OCR by default) — adds negligible CPU.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

try:
    from engines.app_manager import get_active_window, list_windows  # type: ignore[import]
    HAS_APP_MGR = True
except ImportError:
    HAS_APP_MGR = False


# App name normalization
_WINDOW_TO_APP = {
    "notepad": "notepad", "untitled - notepad": "notepad",
    "word": "word", "document": "word",
    "excel": "excel", "book": "excel",
    "powerpoint": "powerpoint", "presentation": "powerpoint",
    "chrome": "chrome", "google chrome": "chrome",
    "firefox": "firefox", "mozilla firefox": "firefox",
    "edge": "edge", "microsoft edge": "edge",
    "code": "vscode", "visual studio code": "vscode",
    "explorer": "explorer", "file explorer": "explorer",
    "cmd": "terminal", "powershell": "terminal", "windows terminal": "terminal",
    "spotify": "spotify", "vlc": "vlc",
    "discord": "discord", "slack": "slack", "teams": "teams",
    "telegram": "telegram", "whatsapp": "whatsapp",
}


def _detect_app_from_title(title: str) -> str:
    """Detect app name from window title."""
    title_lower = title.lower()
    for keyword, app_name in _WINDOW_TO_APP.items():
        if keyword in title_lower:
            return app_name
    # Fallback: use the last part of title (usually app name)
    parts = title.split(" - ")
    if len(parts) > 1:
        return parts[-1].strip().lower()
    return title_lower[:30]


class ScreenContext:
    """Lightweight screen context tracker with document awareness."""

    def __init__(self) -> None:
        self._current_window: Dict[str, Any] = {}
        self._current_app: str = ""
        self._current_title: str = ""
        self._current_document: str = ""  # NEW: extracted document name
        self._app_history: List[Dict[str, Any]] = []  # Last 20 app switches
        self._open_apps: List[str] = []
        self._document_history: List[Dict[str, str]] = []  # Last 10 documents
        self._monitoring: bool = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start_monitoring(self, interval: float = 1.0) -> None:
        """Start background context tracking."""
        if self._monitoring or not HAS_APP_MGR:
            return
        self._monitoring = True
        self._thread = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True)
        self._thread.start()
        logger.info("[ScreenContext] Monitoring started (%.1fs interval)", interval)

    def stop_monitoring(self) -> None:
        self._monitoring = False

    def _monitor_loop(self, interval: float) -> None:
        """Background: poll active window every N seconds."""
        while self._monitoring:
            try:
                self._update_context()
            except Exception as e:
                logger.debug(f"[ScreenContext] Update error: {e}")
            time.sleep(interval)

    @staticmethod
    def _extract_document_name(title: str, app_name: str) -> str:
        """
        Extract the document/file name from a window title.
        
        Examples:
          - "Report.docx - Microsoft Word" → "Report.docx"
          - "Untitled - Notepad" → "Untitled"
          - "Budget.xlsx - Excel" → "Budget.xlsx"
          - "main.py - Visual Studio Code" → "main.py"
          - "Google - Google Chrome" → "" (not a document)
        """
        if not title:
            return ""
        
        # Most apps use " - AppName" format: "Document - App"
        parts = title.split(" - ")
        if len(parts) >= 2:
            candidate = parts[0].strip()
            # Check if it looks like a filename (has extension or is "Untitled" etc.)
            import os
            _, ext = os.path.splitext(candidate)
            if ext:  # Has file extension
                return candidate
            # Common untitled patterns
            untitled = {"untitled", "new", "document", "book", "presentation",
                        "untitled-", "sin título", "शीर्षकहीन"}
            if candidate.lower() in untitled or candidate.lower().startswith("untitled"):
                return candidate
            # For notepad, first part is always the document
            if app_name in ("notepad",):
                return candidate
        
        return ""

    def _update_context(self) -> None:
        """Update current screen context."""
        if not HAS_APP_MGR:
            return

        try:
            win = get_active_window()
            title = win.get("title", "")
            if not title:
                return

            app = _detect_app_from_title(title)
            doc = self._extract_document_name(title, app)

            with self._lock:
                # Detect app switch
                if app != self._current_app and self._current_app:
                    self._app_history.insert(0, {
                        "from_app": self._current_app,
                        "to_app": app,
                        "timestamp": time.time(),
                    })
                    if len(self._app_history) > 20:
                        self._app_history = self._app_history[:20]

                    # Tier 2→3 bridge: feed app switch to user profile
                    try:
                        from engines.user_profile import user_profile  # type: ignore[import]
                        user_profile.record_app_sequence(self._current_app, app)
                    except Exception:
                        pass

                # Track document changes
                if doc and doc != self._current_document:
                    self._document_history.insert(0, {
                        "document": doc,
                        "app": app,
                        "timestamp": str(time.time()),
                    })
                    if len(self._document_history) > 10:
                        self._document_history = self._document_history[:10]
                    logger.debug("[ScreenContext] Document changed: '%s' → '%s'",
                                self._current_document, doc)

                self._current_window = win
                self._current_app = app
                self._current_title = title
                self._current_document = doc

            # Update open apps list (less frequently)
            try:
                windows = list_windows()
                apps = set()
                for w in windows:
                    a = _detect_app_from_title(w.get("title", ""))
                    if a:
                        apps.add(a)
                with self._lock:
                    self._open_apps = sorted(apps)
            except Exception:
                pass

        except Exception:
            pass

    @property
    def current_app(self) -> str:
        """Currently focused app name."""
        with self._lock:
            return self._current_app

    @property
    def current_title(self) -> str:
        """Currently focused window title."""
        with self._lock:
            return self._current_title

    @property
    def current_document(self) -> str:
        """Currently open document/file name (extracted from title)."""
        with self._lock:
            return self._current_document

    @property
    def current_window(self) -> Dict[str, Any]:
        """Full window info (title, position, size)."""
        with self._lock:
            return dict(self._current_window)

    @property
    def open_apps(self) -> List[str]:
        """List of currently open app names."""
        with self._lock:
            return list(self._open_apps)

    def is_app_open(self, app_name: str) -> bool:
        """Check if a specific app is currently open."""
        app_lower = app_name.lower()
        with self._lock:
            return any(app_lower in a for a in self._open_apps)

    def is_app_focused(self, app_name: str) -> bool:
        """Check if a specific app is currently focused."""
        with self._lock:
            return app_name.lower() in self._current_app

    def get_app_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent app switch history."""
        with self._lock:
            return list(self._app_history[:limit])

    def get_document_history(self, limit: int = 10) -> List[Dict[str, str]]:
        """Get recent document history."""
        with self._lock:
            return list(self._document_history[:limit])

    def confirm_context(self, expected_app: str,
                        expected_doc: Optional[str] = None) -> Dict[str, Any]:
        """
        Pre/post-execution context confirmation.
        
        Returns:
            {
                "app_matches": bool,
                "doc_matches": bool (or None if not checked),
                "actual_app": str,
                "actual_doc": str,
                "actual_title": str,
            }
        """
        with self._lock:
            app_matches = expected_app.lower() in self._current_app
            doc_matches = None
            if expected_doc:
                doc_matches = (expected_doc.lower() in self._current_document.lower()
                               if self._current_document else False)
            return {
                "app_matches": app_matches,
                "doc_matches": doc_matches,
                "actual_app": self._current_app,
                "actual_doc": self._current_document,
                "actual_title": self._current_title,
            }

    def get_context_summary(self) -> Dict[str, Any]:
        """Get full context for decision making."""
        with self._lock:
            return {
                "active_app": self._current_app,
                "active_title": self._current_title,
                "active_document": self._current_document,
                "open_apps": list(self._open_apps),
                "recent_switches": len(self._app_history),
                "recent_documents": [d["document"] for d in self._document_history[:5]],
            }

    def get_full_context(self) -> Dict[str, Any]:
        """Get unified context combining window tracking and screen OCR."""
        summary = self.get_context_summary()
        ocr_data = {
            "ocr_available": False,
            "screen_text": "",
            "patterns": {},
            "summary": "",
        }
        try:
            from engines.screen_ocr import screen_ocr
            if screen_ocr.available:
                ocr_data = {
                    "ocr_available": True,
                    "screen_text": screen_ocr.get_screen_text()[:500],
                    "patterns": screen_ocr.get_detected_patterns(),
                    "summary": screen_ocr.get_summary(),
                }
        except Exception:
            pass

        summary["ocr"] = ocr_data
        return summary


# Singleton
screen_context = ScreenContext()

