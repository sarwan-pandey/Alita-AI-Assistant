# pyre-ignore-all-errors
"""
UI Controller — Direct Windows UI Automation
Uses Windows UIA (uiautomation) to interact with app controls directly,
without fragile coordinate-based clicking.
"""

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Optional imports ─────────────────────────────────────────────────────────
try:
    import uiautomation as auto  # type: ignore[import-untyped]
    HAS_UIA = True
except ImportError:
    auto = None
    HAS_UIA = False

try:
    import pyautogui  # type: ignore[import-untyped]
    HAS_PYAUTOGUI = True
except ImportError:
    pyautogui = None
    HAS_PYAUTOGUI = False

try:
    import pyperclip  # type: ignore[import-untyped]
    HAS_PYPERCLIP = True
except ImportError:
    pyperclip = None
    HAS_PYPERCLIP = False


class UIController:
    """Direct Windows UI control via UIA + pyautogui fallback."""

    def __init__(self) -> None:
        self._saved_clipboard: Optional[str] = None

    # ═════════════════════════════════════════════════════════════════════
    #  WINDOW MANAGEMENT
    # ═════════════════════════════════════════════════════════════════════

    def get_focused_window(self) -> Optional[Any]:
        """Get the currently focused window control."""
        if not HAS_UIA:
            return None
        try:
            return auto.GetForegroundControl()
        except Exception:
            return None

    def find_window(self, name: str) -> Optional[Any]:
        """Find a window by partial title match."""
        if not HAS_UIA:
            return None
        name_lower = name.lower()
        try:
            root = auto.GetRootControl()
            for win in root.GetChildren():
                title = getattr(win, 'Name', '') or ''
                if title and name_lower in title.lower():
                    return win
            # Check aliases
            ALIASES: Dict[str, List[str]] = {
                "word": ["word", "document"],
                "notepad": ["notepad"],
                "chrome": ["chrome", "google chrome"],
                "excel": ["excel"],
                "powerpoint": ["powerpoint"],
                "vscode": ["visual studio code"],
            }
            for alias in ALIASES.get(name_lower, []):
                for win in root.GetChildren():
                    title = getattr(win, 'Name', '') or ''
                    if title and alias in title.lower():
                        return win
        except Exception as e:
            logger.warning(f"[UIController] find_window error: {e}")
        return None

    def focus_window(self, name: str) -> bool:
        """Focus a window by name."""
        win = self.find_window(name)
        if win:
            try:
                win.SetFocus()
                time.sleep(0.3)
                return True
            except Exception:
                pass
        # Fallback to pygetwindow
        try:
            from engines.app_manager import focus_window as _fw
            return _fw(name)
        except Exception:
            return False

    def is_window_open(self, name: str) -> bool:
        """Check if a window with the given name exists."""
        return self.find_window(name) is not None

    # ═════════════════════════════════════════════════════════════════════
    #  CONTROL FINDING
    # ═════════════════════════════════════════════════════════════════════

    def find_edit_control(self, window: Optional[Any] = None) -> Optional[Any]:
        """Find the main text editing control in a window."""
        if not HAS_UIA:
            return None
        try:
            win = window or auto.GetForegroundControl()
            if not win:
                return None

            # Search for Document control (Word, etc.)
            doc = win.DocumentControl(searchDepth=8)
            if doc and doc.Name is not None:
                return doc

            # Search for Edit control (Notepad, etc.)
            edit = win.EditControl(searchDepth=8)
            if edit and edit.Name is not None:
                return edit

            # Search for RichEdit
            rich = win.CustomControl(searchDepth=8, ClassName='RichEditD2DPT')
            if rich and rich.Name is not None:
                return rich

        except Exception as e:
            logger.debug(f"[UIController] find_edit_control: {e}")
        return None

    def find_button(self, name: str, window: Optional[Any] = None) -> Optional[Any]:
        """Find a button by name in the current window."""
        if not HAS_UIA:
            return None
        try:
            win = window or auto.GetForegroundControl()
            if not win:
                return None
            btn = win.ButtonControl(Name=name, searchDepth=8)
            if btn and btn.Name:
                return btn
        except Exception:
            pass
        return None

    # ═════════════════════════════════════════════════════════════════════
    #  TEXT INPUT
    # ═════════════════════════════════════════════════════════════════════

    def type_text(self, text: str, use_clipboard: bool = True) -> bool:
        """Type text into the focused control. Uses clipboard paste for reliability."""
        if use_clipboard:
            return self._clipboard_paste(text)
        if HAS_PYAUTOGUI:
            try:
                pyautogui.typewrite(text, interval=0.02) if text.isascii() else self._clipboard_paste(text)
                return True
            except Exception:
                pass
        return False

    def click_control(self, control: Any) -> bool:
        """Click a UIA control."""
        if not control:
            return False
        try:
            control.Click()
            time.sleep(0.2)
            return True
        except Exception:
            # Fallback: get bounding rect and click with pyautogui
            try:
                rect = control.BoundingRectangle
                if rect and HAS_PYAUTOGUI:
                    cx = (rect.left + rect.right) // 2
                    cy = (rect.top + rect.bottom) // 2
                    pyautogui.click(cx, cy)
                    time.sleep(0.2)
                    return True
            except Exception:
                pass
        return False

    def click_center_of_window(self) -> bool:
        """Click the center of the active window as fallback."""
        if not HAS_PYAUTOGUI:
            return False
        try:
            from engines.app_manager import get_active_window
            w = get_active_window()
            cx = w["left"] + w["width"] // 2
            cy = w["top"] + w["height"] // 2
            pyautogui.click(cx, cy)
            return True
        except Exception:
            pyautogui.click(640, 400)
            return True

    def focus_edit_area(self, app_name: str = "") -> bool:
        """Find and focus the editing area of the current app."""
        ctrl = self.find_edit_control()
        if ctrl:
            try:
                ctrl.SetFocus()
                logger.info("[UIController] Focused edit control via UIA")
                return True
            except Exception:
                return self.click_control(ctrl)
        # Fallback: click center
        return self.click_center_of_window()

    def press_key(self, key: str) -> None:
        """Press a single key."""
        if HAS_PYAUTOGUI:
            pyautogui.press(key)

    def hotkey(self, *keys: str) -> None:
        """Press a key combination."""
        if HAS_PYAUTOGUI:
            pyautogui.hotkey(*keys)

    # ═════════════════════════════════════════════════════════════════════
    #  CLIPBOARD
    # ═════════════════════════════════════════════════════════════════════

    def save_clipboard(self) -> None:
        """Save current clipboard content."""
        if HAS_PYPERCLIP:
            try:
                self._saved_clipboard = pyperclip.paste()
            except Exception:
                self._saved_clipboard = None

    def restore_clipboard(self) -> None:
        """Restore saved clipboard content."""
        if HAS_PYPERCLIP and self._saved_clipboard is not None:
            try:
                pyperclip.copy(self._saved_clipboard)
            except Exception:
                pass
            self._saved_clipboard = None

    def _clipboard_paste(self, text: str) -> bool:
        """Copy text to clipboard and paste it."""
        try:
            if HAS_PYPERCLIP:
                pyperclip.copy(text)
            else:
                import subprocess
                p = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
                p.communicate(text.encode('utf-16-le'))
            time.sleep(0.05)
            if HAS_PYAUTOGUI:
                pyautogui.hotkey('ctrl', 'v')
                time.sleep(0.1)
            return True
        except Exception as e:
            logger.error(f"[UIController] clipboard_paste error: {e}")
            return False

    # ═════════════════════════════════════════════════════════════════════
    #  OFFICE SPLASH HANDLER
    # ═════════════════════════════════════════════════════════════════════

    def handle_office_splash(self, app_name: str) -> str:
        """Handle Office apps splash/home screen by clicking 'Blank document'."""
        app_lower = app_name.lower()
        if app_lower not in ("word", "microsoft word", "excel", "microsoft excel",
                             "powerpoint", "microsoft powerpoint"):
            return ""

        time.sleep(1.5)  # Wait for splash to appear

        # Try to find "Blank document" or similar button
        blank_names = ["Blank document", "Blank workbook", "Blank presentation",
                       "New blank document", "Blank"]
        for name in blank_names:
            btn = self.find_button(name)
            if btn:
                self.click_control(btn)
                logger.info(f"[UIController] Clicked '{name}' on Office splash")
                time.sleep(1.0)
                return f"Bypassed splash: clicked '{name}'"

        # Fallback: try Ctrl+N for new document
        if HAS_PYAUTOGUI:
            pyautogui.hotkey('ctrl', 'n')
            time.sleep(1.0)
            logger.info("[UIController] Sent Ctrl+N to bypass Office splash")
            return "Bypassed splash: Ctrl+N"

        return ""


# ── Singleton ────────────────────────────────────────────────────────────────
ui_ctrl = UIController()
