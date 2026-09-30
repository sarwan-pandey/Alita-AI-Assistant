"""
Alita Screen OCR — Layer 1 of the Hybrid Vision Engine
=======================================================
Always-on background OCR + change detection + pattern detection.

Features:
  - In-memory screen capture via MSS (zero disk I/O)
  - Structural similarity change detection (only re-OCR when screen changes)
  - Tesseract OCR for text extraction (~200ms per frame)
  - Pattern detection: errors, dialogs, notifications
  - Rolling context buffer (last 5 snapshots)
  - Proactive alert dispatch when errors/dialogs detected

Zero VRAM — runs entirely on CPU.
"""

import io
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Callable

from PIL import Image, ImageChops, ImageFilter
import mss

log = logging.getLogger("alita.screen_ocr")

# ── OCR Engine auto-detection (winocr primary, Tesseract fallback) ────────────
OCR_ENGINE = None  # "winocr" | "tesseract" | None

# 1. Try winocr (Windows built-in OCR — no external binary needed)
try:
    import winocr
    OCR_ENGINE = "winocr"
    log.info("OCR engine: winocr (Windows built-in OCR)")
except ImportError:
    pass

# 2. Fallback: Tesseract
if not OCR_ENGINE:
    _TESSERACT_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
        os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe"),
    ]
    try:
        import pytesseract
        for _path in _TESSERACT_PATHS:
            if os.path.isfile(_path):
                pytesseract.pytesseract.tesseract_cmd = _path
                OCR_ENGINE = "tesseract"
                log.info("OCR engine: Tesseract at %s", _path)
                break
        if not OCR_ENGINE:
            import shutil
            if shutil.which("tesseract"):
                OCR_ENGINE = "tesseract"
                log.info("OCR engine: Tesseract (from PATH)")
    except ImportError:
        pass

if not OCR_ENGINE:
    log.warning("No OCR engine available — screen text reading disabled")

HAS_OCR = OCR_ENGINE is not None


# ── Error / Dialog / Notification patterns ───────────────────────────────────
ERROR_PATTERNS = [
    re.compile(r"\b(error|exception|failed|failure|fatal|crash|critical)\b", re.I),
    re.compile(r"\b(access\s+denied|permission\s+denied|unauthorized)\b", re.I),
    re.compile(r"\b(not\s+responding|has\s+stopped|stopped\s+working)\b", re.I),
    re.compile(r"\b(traceback|stacktrace|stack\s+trace|unhandled)\b", re.I),
    re.compile(r"\b(blue\s+screen|BSOD|stop\s+code)\b", re.I),
    re.compile(r"\b(could\s+not|cannot|unable\s+to|can't)\s+(find|open|load|connect|start)\b", re.I),
    re.compile(r"\b(404|500|503|timeout|timed?\s+out)\b", re.I),
    re.compile(r"\b(disk\s+full|out\s+of\s+memory|low\s+disk|storage\s+full)\b", re.I),
]

DIALOG_PATTERNS = [
    re.compile(r"\b(save\s+changes|do\s+you\s+want\s+to\s+save)\b", re.I),
    re.compile(r"\b(are\s+you\s+sure|confirm|discard\s+changes)\b", re.I),
    re.compile(r"\b(yes|no|cancel|ok|retry|abort|ignore)\b", re.I),
    re.compile(r"\b(would\s+you\s+like\s+to|do\s+you\s+want)\b", re.I),
    re.compile(r"\b(allow|deny|block|permit)\s+(access|this)?\b", re.I),
]

NOTIFICATION_PATTERNS = [
    re.compile(r"\b(new\s+message|incoming\s+call|missed\s+call)\b", re.I),
    re.compile(r"\b(update\s+available|restart\s+required|reboot\s+needed)\b", re.I),
    re.compile(r"\b(download\s+complete|installation\s+complete)\b", re.I),
    re.compile(r"\b(low\s+battery|battery\s+low|plug\s+in)\b", re.I),
    re.compile(r"\b(reminder|alarm|schedule|meeting\s+in)\b", re.I),
]


class OCRSnapshot:
    """A single OCR scan result with metadata."""
    __slots__ = ("text", "patterns", "timestamp", "app_title")

    def __init__(self, text: str, patterns: Dict[str, List[str]],
                 timestamp: float, app_title: str = ""):
        self.text = text
        self.patterns = patterns
        self.timestamp = timestamp
        self.app_title = app_title

    def has_errors(self) -> bool:
        return bool(self.patterns.get("errors"))

    def has_dialogs(self) -> bool:
        return bool(self.patterns.get("dialogs"))

    def has_notifications(self) -> bool:
        return bool(self.patterns.get("notifications"))


class ScreenOCR:
    """
    Always-on screen OCR engine with change detection.
    
    Runs a background daemon that:
    1. Captures screen every N seconds
    2. Detects if screen content changed (pixel diff)
    3. If changed → OCR → pattern detection → proactive alerts
    """

    def __init__(self, scan_interval: float = 5.0, change_threshold: float = 0.90):
        self._scan_interval = scan_interval
        self._change_threshold = change_threshold  # SSIM below this = "changed"
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._sct: Optional[mss.mss] = None

        # State
        self._last_screenshot: Optional[Image.Image] = None
        self._last_text: str = ""
        self._last_patterns: Dict[str, List[str]] = {}
        self._context_buffer: List[OCRSnapshot] = []  # rolling last 5
        self._change_count: int = 0
        self._alert_callbacks: List[Callable[[Dict[str, Any]], Any]] = []
        self._alert_cooldowns: Dict[str, float] = {}  # pattern_key → last_alert_time
        self._alert_cooldown_secs: float = 60.0  # 60s between same alert type

    @property
    def available(self) -> bool:
        return HAS_OCR

    @property
    def scan_interval(self) -> float:
        return self._scan_interval

    @property
    def change_count(self) -> int:
        return self._change_count

    def register_alert_callback(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        """Register a callback for proactive vision alerts."""
        if callback not in self._alert_callbacks:
            self._alert_callbacks.append(callback)

    def start(self) -> None:
        """Start the background OCR monitoring daemon."""
        if self._running:
            return
        if not HAS_OCR:
            log.warning("ScreenOCR cannot start — no OCR engine available")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="AlitaScreenOCR")
        self._thread.start()
        log.info("ScreenOCR started (interval=%.1fs, threshold=%.2f)",
                 self._scan_interval, self._change_threshold)

    def stop(self) -> None:
        """Stop the background monitoring."""
        self._running = False
        log.info("ScreenOCR stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_screen_text(self) -> str:
        """Get the latest OCR text (cached, instant)."""
        with self._lock:
            return self._last_text

    def get_detected_patterns(self) -> Dict[str, List[str]]:
        """Get the latest detected patterns (cached, instant)."""
        with self._lock:
            return dict(self._last_patterns)

    def get_context_buffer(self) -> List[Dict[str, Any]]:
        """Get rolling context buffer (last 5 snapshots) as dicts."""
        with self._lock:
            return [
                {
                    "text": s.text[:500],
                    "patterns": s.patterns,
                    "timestamp": s.timestamp,
                    "app_title": s.app_title,
                }
                for s in self._context_buffer
            ]

    def get_summary(self) -> str:
        """Get a human-readable summary of current screen state."""
        with self._lock:
            if not self._last_text:
                return "No OCR data available yet."
            parts = []
            if self._last_patterns.get("errors"):
                parts.append(f"⚠️ Errors detected: {', '.join(self._last_patterns['errors'][:3])}")
            if self._last_patterns.get("dialogs"):
                parts.append(f"💬 Dialog detected: {', '.join(self._last_patterns['dialogs'][:2])}")
            if self._last_patterns.get("notifications"):
                parts.append(f"🔔 Notifications: {', '.join(self._last_patterns['notifications'][:2])}")
            if not parts:
                # Return first meaningful line of OCR text
                lines = [l.strip() for l in self._last_text.split('\n') if l.strip() and len(l.strip()) > 5]
                if lines:
                    parts.append(f"Screen text: \"{lines[0][:100]}\"")
                else:
                    parts.append("Screen appears mostly visual (no significant text detected).")
            return " | ".join(parts)

    def force_scan(self) -> Optional[OCRSnapshot]:
        """Force an immediate OCR scan (blocking). Used for on-demand queries."""
        if not HAS_OCR:
            return None
        try:
            screenshot = self._capture_screen()
            if screenshot is None:
                return None
            text = self._ocr_image(screenshot)
            patterns = self._detect_patterns(text)
            app_title = self._get_active_title()
            snapshot = OCRSnapshot(text, patterns, time.time(), app_title)
            with self._lock:
                self._last_text = text
                self._last_patterns = patterns
                self._last_screenshot = screenshot
            return snapshot
        except Exception as exc:
            log.error("Force scan failed: %s", exc)
            return None

    # ── Background Monitor ────────────────────────────────────────────────────

    def _monitor_loop(self) -> None:
        """Background daemon: capture → diff → OCR → detect → alert."""
        log.info("ScreenOCR monitor loop started")
        while self._running:
            try:
                self._scan_cycle()
            except Exception as exc:
                log.debug("ScreenOCR cycle error: %s", exc)
            time.sleep(self._scan_interval)

    def _scan_cycle(self) -> None:
        """One complete scan cycle."""
        screenshot = self._capture_screen()
        if screenshot is None:
            return

        # Change detection — skip OCR if screen hasn't changed
        if not self._has_changed(screenshot):
            return

        self._change_count += 1
        t0 = time.perf_counter()

        # OCR
        text = self._ocr_image(screenshot)
        if not text.strip():
            return

        # Pattern detection
        patterns = self._detect_patterns(text)
        app_title = self._get_active_title()

        elapsed = (time.perf_counter() - t0) * 1000
        log.debug("ScreenOCR: %d chars in %.1fms (changes=%d)",
                  len(text), elapsed, self._change_count)

        # Update state
        snapshot = OCRSnapshot(text, patterns, time.time(), app_title)
        with self._lock:
            self._last_text = text
            self._last_patterns = patterns
            self._last_screenshot = screenshot
            self._context_buffer.insert(0, snapshot)
            if len(self._context_buffer) > 5:
                self._context_buffer = self._context_buffer[:5]

        # Proactive alerts
        if patterns.get("errors"):
            self._dispatch_alert("error", patterns["errors"], app_title)
        if patterns.get("dialogs"):
            self._dispatch_alert("dialog", patterns["dialogs"], app_title)

    # ── Screen Capture ────────────────────────────────────────────────────────

    def _capture_screen(self, max_dim: int = 1024) -> Optional[Image.Image]:
        """Capture primary monitor in-memory, return PIL Image."""
        try:
            if self._sct is None:
                self._sct = mss.mss()
            monitor = self._sct.monitors[1] if len(self._sct.monitors) > 1 else self._sct.monitors[0]
            sct_img = self._sct.grab(monitor)
            img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

            # Downscale for faster OCR (1024px max dimension)
            if max(img.width, img.height) > max_dim:
                scale = max_dim / float(max(img.width, img.height))
                new_size = (int(img.width * scale), int(img.height * scale))
                img = img.resize(new_size, Image.Resampling.LANCZOS)

            return img
        except Exception as exc:
            log.debug("Screen capture failed: %s", exc)
            return None

    # ── Change Detection ──────────────────────────────────────────────────────

    def _has_changed(self, current: Image.Image) -> bool:
        """
        Lightweight pixel-diff change detection.
        Returns True if screen content has changed significantly.
        """
        if self._last_screenshot is None:
            with self._lock:
                self._last_screenshot = current
            return True  # First capture — always process

        try:
            # Resize both to same small size for fast comparison
            size = (160, 90)  # Tiny — just for diff
            prev_small = self._last_screenshot.resize(size).convert("L")
            curr_small = current.resize(size).convert("L")

            # Compute absolute pixel difference
            diff = ImageChops.difference(prev_small, curr_small)
            # Mean pixel difference (0 = identical, 255 = completely different)
            diff_pixels = list(diff.getdata())
            mean_diff = sum(diff_pixels) / len(diff_pixels) if diff_pixels else 0
            
            # Normalize to 0-1 similarity score
            similarity = 1.0 - (mean_diff / 255.0)

            if similarity < self._change_threshold:
                return True  # Screen changed significantly
            return False

        except Exception:
            return True  # On error, assume changed

    # ── OCR ────────────────────────────────────────────────────────────────────

    def _ocr_image(self, img: Image.Image) -> str:
        """Run OCR on a PIL Image. Uses winocr (Windows built-in) or Tesseract."""
        try:
            if OCR_ENGINE == "winocr":
                return self._ocr_winocr(img)
            elif OCR_ENGINE == "tesseract":
                return self._ocr_tesseract(img)
            return ""
        except Exception as exc:
            log.debug("OCR failed: %s", exc)
            return ""

    @staticmethod
    def _ocr_winocr(img: Image.Image) -> str:
        """Windows built-in OCR via WinRT (zero external dependencies)."""
        try:
            import winocr
            res = winocr.recognize_pil_sync(img, lang="en")
            if isinstance(res, dict):
                text = res.get("text", "")
                if text:
                    return text.strip()
                lines = res.get("lines", [])
                if lines:
                    return "\n".join(l.get("text", "") for l in lines if isinstance(l, dict) and l.get("text")).strip()
            elif hasattr(res, "text"):
                return res.text.strip()
            return str(res).strip() if res else ""
        except Exception as exc:
            log.debug("winocr recognition error: %s", exc)
            return ""

    @staticmethod
    def _ocr_tesseract(img: Image.Image) -> str:
        """Tesseract OCR fallback."""
        gray = img.convert("L")
        sharp = gray.filter(ImageFilter.SHARPEN)
        text = pytesseract.image_to_string(sharp, config="--psm 6")
        return text.strip()

    # ── Pattern Detection ─────────────────────────────────────────────────────

    @staticmethod
    def _detect_patterns(text: str) -> Dict[str, List[str]]:
        """Scan OCR text for error/dialog/notification patterns."""
        if not text:
            return {}

        result: Dict[str, List[str]] = {}

        # Errors
        errors = []
        for pattern in ERROR_PATTERNS:
            matches = pattern.findall(text)
            errors.extend(matches)
        if errors:
            # Deduplicate and limit
            result["errors"] = list(dict.fromkeys(errors))[:5]

        # Dialogs
        dialogs = []
        for pattern in DIALOG_PATTERNS:
            matches = pattern.findall(text)
            dialogs.extend(matches)
        if dialogs:
            result["dialogs"] = list(dict.fromkeys(dialogs))[:3]

        # Notifications
        notifs = []
        for pattern in NOTIFICATION_PATTERNS:
            matches = pattern.findall(text)
            notifs.extend(matches)
        if notifs:
            result["notifications"] = list(dict.fromkeys(notifs))[:3]

        return result

    # ── Active Window Title ───────────────────────────────────────────────────

    @staticmethod
    def _get_active_title() -> str:
        """Get the currently active window title."""
        try:
            from engines.app_manager import get_active_window
            win = get_active_window()
            return win.get("title", "") if win else ""
        except Exception:
            return ""

    # ── Proactive Alert Dispatch ──────────────────────────────────────────────

    def _dispatch_alert(self, alert_type: str, matches: List[str],
                        app_title: str) -> None:
        """Send a proactive alert to registered callbacks (with cooldown)."""
        now = time.time()
        cooldown_key = f"{alert_type}:{app_title}"

        # Cooldown check — don't spam
        last_time = self._alert_cooldowns.get(cooldown_key, 0)
        if now - last_time < self._alert_cooldown_secs:
            return

        self._alert_cooldowns[cooldown_key] = now

        if alert_type == "error":
            message = f"I noticed an error on your screen: \"{matches[0]}\". Want me to help?"
            suggestion_type = "vision_error"
        elif alert_type == "dialog":
            message = f"There's a dialog on your screen asking about \"{matches[0]}\". Need help?"
            suggestion_type = "vision_dialog"
        else:
            message = f"Screen notification: {matches[0]}"
            suggestion_type = "vision_notification"

        alert_data = {
            "type": suggestion_type,
            "message": message,
            "matches": matches[:3],
            "app": app_title,
            "timestamp": now,
        }

        log.info("ScreenOCR ALERT [%s]: %s (app=%s)", alert_type, matches[0], app_title)

        for callback in self._alert_callbacks:
            try:
                callback(alert_data)
            except Exception as exc:
                log.debug("Alert callback failed: %s", exc)


# ── Singleton ─────────────────────────────────────────────────────────────────
screen_ocr = ScreenOCR(scan_interval=5.0, change_threshold=0.90)

