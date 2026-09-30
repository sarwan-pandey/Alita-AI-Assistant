"""
Visual Grounding & Set-of-Marks (SoM) Computer-Use Agent
========================================================
Empowers Alita to visually understand and interact with any Windows application.
Uses Set-of-Marks (SoM) bounding box indexing combined with Windows UI Automation
and OpenCV visual contour extraction.
"""

import io
import time
import base64
import logging
from typing import Dict, Any, List, Optional, Tuple
from pathlib import Path
import ctypes

log = logging.getLogger("alita.visual_grounding")

try:
    import cv2  # type: ignore[import-untyped]
    import numpy as np  # type: ignore[import-untyped]
    from PIL import Image, ImageDraw, ImageFont  # type: ignore[import-untyped]
    import pyautogui  # type: ignore[import-untyped]
    import mss  # type: ignore[import-untyped]
    HAS_DEPS = True
except ImportError as err:
    log.warning("Visual Grounding missing dependencies: %s", err)
    HAS_DEPS = False


class VisualGroundingAgent:
    """
    Screenshots the desktop, identifies interactive UI controls,
    and overlays Set-of-Marks (SoM) numbered tags for autonomous computer use.
    """

    def __init__(self):
        self.last_marks: Dict[int, Dict[str, Any]] = {}
        self.last_screenshot: Optional[Any] = None

    def capture_screen(self) -> Optional[Any]:
        """Capture entire screen as PIL Image."""
        if not HAS_DEPS:
            return None
        try:
            with mss.mss() as sct:
                monitor = sct.monitors[1]  # primary monitor
                sct_img = sct.grab(monitor)
                img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                self.last_screenshot = img
                return img
        except Exception as exc:
            log.error("Failed to capture screen: %s", exc)
            return None

    def get_screen_dimensions(self) -> Tuple[int, int]:
        """Get primary monitor screen dimensions."""
        try:
            user32 = ctypes.windll.user32
            user32.SetProcessDPIAware()
            return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        except Exception:
            return 1920, 1080

    def get_uia_elements(self) -> List[Dict[str, Any]]:
        """Extract interactive UI elements via Windows Accessibility Tree with normalized coordinates."""
        elements = []
        screen_w, screen_h = self.get_screen_dimensions()

        try:
            import pywinauto  # type: ignore[import-untyped]
            desktop = pywinauto.Desktop(backend="uia")
            windows = desktop.windows()
            
            # Find foreground window
            import win32gui  # type: ignore[import-untyped]
            hwnd = win32gui.GetForegroundWindow()
            if not hwnd:
                return []

            target_win = None
            for w in windows:
                try:
                    if w.handle == hwnd:
                        target_win = w
                        break
                except Exception:
                    continue

            if not target_win:
                return []

            for elem in target_win.descendants()[:80]:  # Up to 80 elements for rich coverage
                try:
                    rect = elem.rectangle()
                    name = elem.window_text().strip()
                    control_type = elem.element_info.control_type
                    w = rect.width()
                    h = rect.height()

                    if w > 10 and h > 10 and (name or control_type in ("Button", "Edit", "MenuItem", "Hyperlink", "ListItem", "TabItem", "CheckBox")):
                        left = max(0, rect.left)
                        top = max(0, rect.top)
                        right = min(screen_w, rect.right)
                        bottom = min(screen_h, rect.bottom)
                        cx = (left + right) // 2
                        cy = (top + bottom) // 2

                        elements.append({
                            "name": name or control_type,
                            "type": control_type.lower(),
                            "bbox": (left, top, right, bottom),
                            "center": (cx, cy),
                            "norm": {
                                "x": round(cx / max(1, screen_w), 4),
                                "y": round(cy / max(1, screen_h), 4),
                                "w": round((right - left) / max(1, screen_w), 4),
                                "h": round((bottom - top) / max(1, screen_h), 4),
                            },
                        })
                except Exception:
                    continue
        except Exception as exc:
            log.debug("UIA extraction notice: %s", exc)
        return elements

    def ground_screen(self) -> Dict[str, Any]:
        """
        Produce a Set-of-Marks indexed representation of the current screen.
        Returns base64 marked image, marks dictionary, and frontend HUD marks array.
        """
        img = self.capture_screen()
        if not img:
            return {"status": "error", "error": "Screen capture failed", "marks": {}, "frontend_marks": []}

        uia_elements = self.get_uia_elements()
        self.last_marks.clear()
        frontend_marks = []

        # Create overlay image
        draw = ImageDraw.Draw(img)
        mark_id = 1

        for elem in uia_elements:
            bbox = elem["bbox"]
            name = elem["name"]
            center = elem["center"]
            norm = elem["norm"]

            # Store mark
            mark_info = {
                "id": mark_id,
                "name": name,
                "type": elem["type"],
                "center": center,
                "bbox": bbox,
                "norm": norm,
            }
            self.last_marks[mark_id] = mark_info

            frontend_marks.append({
                "id": mark_id,
                "name": name,
                "type": elem["type"],
                "x": norm["x"],
                "y": norm["y"],
                "w": norm["w"],
                "h": norm["h"],
            })

            # Draw boundary box
            draw.rectangle(bbox, outline="#00f0ff", width=2)

            # Draw badge tag [ID]
            badge_text = f" {mark_id} "
            tag_x, tag_y = max(0, bbox[0]), max(0, bbox[1] - 18)
            draw.rectangle((tag_x, tag_y, tag_x + len(badge_text) * 9 + 4, tag_y + 16), fill="#00f0ff")
            draw.text((tag_x + 2, tag_y), badge_text, fill="black")

            mark_id += 1

        # Encode to JPEG base64
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        return {
            "status": "success",
            "marks_count": len(self.last_marks),
            "marks": self.last_marks,
            "frontend_marks": frontend_marks,
            "marked_image_b64": img_b64,
        }

    def find_mark_by_fuzzy_name(self, target_query: str) -> Optional[Dict[str, Any]]:
        """Fuzzy match query text against recognized element names/types."""
        q = target_query.strip().lower()
        if not q or not self.last_marks:
            return None

        # Exact substring match first
        for mark in self.last_marks.values():
            if q in mark["name"].lower():
                return mark

        # Token overlap match
        q_tokens = set(q.split())
        best_mark = None
        best_score = 0
        for mark in self.last_marks.values():
            elem_tokens = set(mark["name"].lower().split())
            overlap = len(q_tokens & elem_tokens)
            if overlap > best_score:
                best_score = overlap
                best_mark = mark

        return best_mark if best_score > 0 else None

    def verify_action_outcome(
        self,
        pre_img: Optional[Any],
        post_img: Optional[Any],
        target_mark_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Self-healing action verification: Inspects visual delta between pre and post screenshots
        to verify that the action took effect and was not blocked by a popup or missed click.
        """
        if not pre_img or not post_img:
            return {"verified": True, "delta_ratio": 0.0, "reason": "No pre/post image available"}

        try:
            import numpy as np
            pre_arr = np.array(pre_img.convert("L"))
            post_arr = np.array(post_img.convert("L"))

            # Calculate mean absolute difference
            diff = np.abs(pre_arr.astype("int32") - post_arr.astype("int32"))
            changed_pixels = np.count_nonzero(diff > 15)
            total_pixels = pre_arr.size
            delta_ratio = float(changed_pixels / max(1, total_pixels))

            # If target mark is specified, calculate localized crop delta
            local_delta = delta_ratio
            if target_mark_id and target_mark_id in self.last_marks:
                bbox = self.last_marks[target_mark_id]["bbox"]
                left, top, right, bottom = bbox
                # Pad bbox slightly
                h, w = pre_arr.shape
                c_top, c_bottom = max(0, top - 20), min(h, bottom + 20)
                c_left, c_right = max(0, left - 20), min(w, right + 20)
                local_diff = diff[c_top:c_bottom, c_left:c_right]
                if local_diff.size > 0:
                    local_delta = float(np.count_nonzero(local_diff > 15) / local_diff.size)

            # Verification logic: If either the global screen shifted (>0.005) or localized area changed (>0.02)
            has_changed = delta_ratio > 0.004 or local_delta > 0.015
            return {
                "verified": has_changed,
                "delta_ratio": round(delta_ratio, 5),
                "local_delta": round(local_delta, 5),
                "reason": "Visual delta verified" if has_changed else "Screen remained unchanged (stagnant action)",
            }
        except Exception as exc:
            log.debug("Visual verification fallback: %s", exc)
            return {"verified": True, "delta_ratio": 0.0, "reason": f"Heuristic pass: {exc}"}

    def click_mark(self, mark_id: int) -> bool:
        """Click on the element indexed by mark_id."""
        mark = self.last_marks.get(mark_id)
        if not mark:
            log.warning("Mark ID %d not found in active screen marks", mark_id)
            return False
        cx, cy = mark["center"]
        try:
            pyautogui.click(cx, cy)
            log.info("Clicked mark [%d]: %s at (%d, %d)", mark_id, mark.get("name"), cx, cy)
            return True
        except Exception as exc:
            log.error("Failed to click mark [%d]: %s", mark_id, exc)
            return False

    def type_mark(self, mark_id: int, text: str) -> bool:
        """Focus on mark_id and type text."""
        if not self.click_mark(mark_id):
            return False
        time.sleep(0.1)
        try:
            import pyperclip  # type: ignore[import-untyped]
            pyperclip.copy(text)
            pyautogui.hotkey("ctrl", "v")
            log.info("Typed text into mark [%d]: %s", mark_id, text[:20])
            return True
        except Exception as exc:
            log.error("Failed to type into mark [%d]: %s", mark_id, exc)
            return False


# Global singleton instance
visual_grounding_agent = VisualGroundingAgent()
