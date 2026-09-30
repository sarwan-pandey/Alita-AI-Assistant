"""
screen_analyzer.py — Semantic Mobile Screen Understanding Engine

Interprets raw accessibility view-tree dumps into high-level semantic context:
- What app and specific screen is currently displayed?
- What are the primary interactive elements (buttons, inputs, lists)?
- Is the screen in a loading, settling, or error state?
- Where are target elements located semantically (by intent, role, or positional heuristic)?
"""

from __future__ import annotations

import difflib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("alita.screen_analyzer")


@dataclass
class ScreenElement:
    node_id: str
    resource_id: str
    text: str
    content_desc: str
    class_name: str
    package: str
    is_clickable: bool
    is_editable: bool
    is_scrollable: bool
    bounds: Dict[str, int] = field(default_factory=dict)  # {"left": 0, "top": 0, "right": 0, "bottom": 0, "cx": 0, "cy": 0}
    role: str = "generic"  # "button", "input", "text", "list_item", "image", "switch", "tab", "dialog"


@dataclass
class ScreenContext:
    app_name: str
    package: str
    screen_type: str  # "chat_list", "conversation", "search", "settings", "camera", "call", "browser", "home", "dialog", "unknown"
    interactive_elements: List[ScreenElement] = field(default_factory=list)
    text_elements: List[ScreenElement] = field(default_factory=list)
    scrollable_containers: List[ScreenElement] = field(default_factory=list)
    all_text: str = ""
    has_loading_spinner: bool = False
    has_dialog_overlay: bool = False
    keyboard_visible: bool = False
    node_count: int = 0
    raw_tree: Dict[str, Any] = field(default_factory=dict)


class ScreenAnalyzer:
    """
    Interprets raw Android accessibility view trees with human-like spatial and semantic reasoning.
    """

    # Common package to human app name mapping
    KNOWN_PACKAGES = {
        "com.whatsapp": "WhatsApp",
        "com.whatsapp.w4b": "WhatsApp Business",
        "org.telegram.messenger": "Telegram",
        "org.thunderdog.challegram": "Telegram X",
        "com.instagram.android": "Instagram",
        "com.google.android.youtube": "YouTube",
        "com.spotify.music": "Spotify",
        "com.google.android.apps.messaging": "Messages",
        "com.google.android.dialer": "Phone",
        "com.android.dialer": "Phone",
        "com.google.android.apps.maps": "Google Maps",
        "com.android.chrome": "Chrome",
        "com.google.android.gm": "Gmail",
        "com.android.settings": "Settings",
        "com.coloros.alarmclock": "Clock",
        "com.google.android.deskclock": "Clock",
        "com.oppo.camera": "Camera",
        "com.android.camera": "Camera",
        "com.coloros.gallery3d": "Photos",
        "com.google.android.apps.photos": "Google Photos",
        "com.android.systemui": "System UI",
    }

    # Loading indicator signatures
    LOADING_CLASSES = {"android.widget.ProgressBar", "android.widget.ProgressDialog"}
    LOADING_TEXT_PATTERNS = [
        r"\bloading\b",
        r"\bplease wait\b",
        r"\bconnecting\b",
        r"\bfetching\b",
        r"\bbuffering\b",
        r"\bsearching\b",
    ]

    def analyze_screen(self, view_tree: Dict[str, Any]) -> ScreenContext:
        """Parse raw view-tree dump into a structured semantic ScreenContext."""
        if not view_tree or not isinstance(view_tree, dict):
            return ScreenContext(
                app_name="Unknown",
                package="",
                screen_type="unknown",
                raw_tree={},
            )

        pkg = view_tree.get("package") or ""
        app_name = self.KNOWN_PACKAGES.get(pkg, pkg.split(".")[-1].capitalize() if pkg else "Unknown")
        nodes = view_tree.get("nodes") or []
        valid_nodes = [n for n in nodes if isinstance(n, dict)]

        elements: List[ScreenElement] = []
        interactive_elements: List[ScreenElement] = []
        text_elements: List[ScreenElement] = []
        scrollables: List[ScreenElement] = []
        all_texts: List[str] = []

        has_spinner = False
        keyboard_visible = False
        has_dialog = False

        for n in valid_nodes:
            cls = n.get("className") or ""
            text = (n.get("text") or "").strip()
            desc = (n.get("contentDesc") or "").strip()
            res_id = n.get("resourceId") or ""
            is_clickable = bool(n.get("isClickable"))
            is_editable = bool(n.get("isEditable") or "EditText" in cls)
            is_scrollable = bool(n.get("isScrollable") or "ScrollView" in cls or "RecyclerView" in cls or "ListView" in cls)

            bounds_dict = self._parse_bounds(n.get("bounds"))
            role = self._determine_role(cls, is_clickable, is_editable, is_scrollable, text, desc, res_id)

            elem = ScreenElement(
                node_id=str(n.get("id") or ""),
                resource_id=res_id,
                text=text,
                content_desc=desc,
                class_name=cls,
                package=pkg,
                is_clickable=is_clickable,
                is_editable=is_editable,
                is_scrollable=is_scrollable,
                bounds=bounds_dict,
                role=role,
            )
            elements.append(elem)

            if text:
                all_texts.append(text)
            if desc and desc != text:
                all_texts.append(desc)

            if is_clickable or is_editable or role == "button" or role == "input":
                interactive_elements.append(elem)

            if text or desc:
                text_elements.append(elem)

            if is_scrollable:
                scrollables.append(elem)

            if cls in self.LOADING_CLASSES:
                has_spinner = True
            if "inputmethod" in cls.lower() or "keyboard" in cls.lower() or "LatinIME" in cls:
                keyboard_visible = True
            if "dialog" in cls.lower() or "popup" in cls.lower():
                has_dialog = True

        combined_text = " ".join(all_texts)

        # Check loading patterns if no explicit spinner widget found
        if not has_spinner:
            comb_lower = combined_text.lower()
            for pat in self.LOADING_TEXT_PATTERNS:
                if re.search(pat, comb_lower):
                    has_spinner = True
                    break

        screen_type = self.detect_screen_type(view_tree, pkg, combined_text, interactive_elements)

        return ScreenContext(
            app_name=app_name,
            package=pkg,
            screen_type=screen_type,
            interactive_elements=interactive_elements,
            text_elements=text_elements,
            scrollable_containers=scrollables,
            all_text=combined_text,
            has_loading_spinner=has_spinner,
            has_dialog_overlay=has_dialog,
            keyboard_visible=keyboard_visible,
            node_count=len(valid_nodes),
            raw_tree=view_tree,
        )

    def detect_screen_type(
        self,
        tree: Dict[str, Any],
        package: str,
        all_text: Optional[str] = None,
        interactive: Optional[List[ScreenElement]] = None,
    ) -> str:
        """Classify the current screen into high-level categories based on package and UI hints."""
        if not all_text:
            nodes = tree.get("nodes") or []
            all_text = " ".join([(n.get("text") or "") + " " + (n.get("contentDesc") or "") for n in nodes if isinstance(n, dict)])
        txt_lower = all_text.lower()

        # WhatsApp specific
        if "whatsapp" in package.lower():
            if any(w in txt_lower for w in ["type a message", "online", "typing..."]) or ("message" in txt_lower and "send" in txt_lower):
                return "conversation"
            if any(w in txt_lower for w in ["chats", "status", "calls", "new chat"]):
                return "chat_list"
            if "search" in txt_lower and len(txt_lower) < 150 and not ("send" in txt_lower or "type a message" in txt_lower):
                return "search_results"

        # YouTube specific
        if "youtube" in package.lower():
            if any(w in txt_lower for w in ["subscribe", "views", "comments", "like", "share"]) and ("replay" in txt_lower or "pause" in txt_lower or "play" in txt_lower):
                return "video_playing"
            if "search" in txt_lower and "results" in txt_lower:
                return "search_results"

        # Phone / Dialer
        if "dialer" in package.lower() or "telecom" in package.lower():
            if any(w in txt_lower for w in ["incoming call", "calling...", "on hold", "end call", "mute", "speaker"]):
                return "call"
            if any(w in txt_lower for w in ["keypad", "favorites", "recents", "contacts"]):
                return "dialer_home"

        # Camera
        if "camera" in package.lower():
            return "camera"

        # Generic patterns
        if "settings" in package.lower():
            return "settings"
        if any(w in txt_lower for w in ["search", "find", "explore"]) and len(txt_lower) < 200:
            return "search"
        if any(w in txt_lower for w in ["allow", "deny", "permission", "cancel", "ok"]):
            # If node count is small, likely a dialog
            nodes = tree.get("nodes") or []
            if len(nodes) < 20:
                return "dialog"

        return "generic"

    def is_screen_ready(self, tree: Dict[str, Any]) -> bool:
        """Determines if the screen is stable and not actively loading or animating."""
        if not tree or not isinstance(tree, dict):
            return False

        nodes = tree.get("nodes") or []
        if not nodes:
            return False

        # Look for active progress bars
        for n in nodes:
            if not isinstance(n, dict):
                continue
            cls = n.get("className") or ""
            if cls in self.LOADING_CLASSES:
                return False

        return True

    def find_element_smart(
        self,
        tree: Dict[str, Any],
        intent: str,
        preferred_role: Optional[str] = None,
        fuzzy_threshold: float = 0.65,
    ) -> Optional[Dict[str, Any]]:
        """
        Locates an element using human-like semantic scanning:
        1. Exact resourceId match
        2. Exact text / content description match
        3. Fuzzy text match (difflib ratio >= threshold)
        4. Intent synonym / role match (e.g. 'send' matches send icon, paper plane, button next to input)
        5. Positional heuristics (e.g. back button -> top-left, send button -> bottom-right)
        """
        if not tree or not isinstance(tree, dict):
            return None

        nodes = tree.get("nodes") or []
        valid_nodes = [n for n in nodes if isinstance(n, dict)]
        if not valid_nodes:
            return None

        intent_lower = intent.strip().lower()

        # Strategy 1: Exact Resource ID match
        for n in valid_nodes:
            res_id = (n.get("resourceId") or "").lower()
            if intent_lower in res_id or (res_id and res_id.endswith(intent_lower)):
                logger.info(f"Smart find: Resource ID match for '{intent}' -> {res_id}")
                return n

        # Strategy 2: Exact Text or ContentDesc match
        for n in valid_nodes:
            txt = (n.get("text") or "").strip().lower()
            desc = (n.get("contentDesc") or "").strip().lower()
            if intent_lower == txt or intent_lower == desc:
                logger.info(f"Smart find: Exact text match for '{intent}' -> txt='{txt}', desc='{desc}'")
                return n

        # Strategy 3: Intent Keyword containment (word-boundary)
        for n in valid_nodes:
            txt = (n.get("text") or "").strip().lower()
            desc = (n.get("contentDesc") or "").strip().lower()
            if (intent_lower in txt and len(txt) <= len(intent_lower) + 15) or \
               (intent_lower in desc and len(desc) <= len(intent_lower) + 15):
                logger.info(f"Smart find: Substring containment match for '{intent}'")
                return n

        # Strategy 4: Fuzzy Text Matching
        best_match = None
        best_ratio = 0.0

        for n in valid_nodes:
            txt = (n.get("text") or "").strip().lower()
            desc = (n.get("contentDesc") or "").strip().lower()
            candidate = txt if txt else desc
            if not candidate:
                continue

            ratio = difflib.SequenceMatcher(None, intent_lower, candidate).ratio()
            # Also check partial ratio for token overlap
            tokens_intent = set(intent_lower.split())
            tokens_cand = set(candidate.split())
            if tokens_intent and tokens_cand:
                overlap = len(tokens_intent.intersection(tokens_cand)) / len(tokens_intent)
                ratio = max(ratio, overlap)

            if ratio > best_ratio and ratio >= fuzzy_threshold:
                best_ratio = ratio
                best_match = n

        if best_match and best_ratio >= fuzzy_threshold:
            logger.info(f"Smart find: Fuzzy text match for '{intent}' (ratio {best_ratio:.2f})")
            return best_match

        # Strategy 5: Semantic Role & Synonym Matching
        synonym_match = self._match_semantic_intent(valid_nodes, intent_lower)
        if synonym_match:
            logger.info(f"Smart find: Semantic synonym match for '{intent}'")
            return synonym_match

        # Strategy 6: Positional Heuristics
        pos_match = self._match_positional_heuristic(valid_nodes, intent_lower)
        if pos_match:
            logger.info(f"Smart find: Positional heuristic match for '{intent}'")
            return pos_match

        return None

    def get_scrollable_areas(self, tree: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Returns all scrollable containers in the view tree."""
        if not tree or not isinstance(tree, dict):
            return []
        nodes = tree.get("nodes") or []
        res = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            cls = n.get("className") or ""
            if n.get("isScrollable") or "ScrollView" in cls or "RecyclerView" in cls or "ListView" in cls:
                res.append(n)
        return res

    def extract_visible_text(self, tree: Dict[str, Any]) -> str:
        """Returns all human-readable visible text on screen."""
        if not tree or not isinstance(tree, dict):
            return ""
        nodes = tree.get("nodes") or []
        texts = []
        for n in nodes:
            if not isinstance(n, dict):
                continue
            t = (n.get("text") or "").strip()
            d = (n.get("contentDesc") or "").strip()
            if t:
                texts.append(t)
            elif d:
                texts.append(d)
        return " | ".join(texts)

    # ── Internal Helpers ────────────────────────────────────────────────────────

    def _determine_role(
        self,
        cls: str,
        is_clickable: bool,
        is_editable: bool,
        is_scrollable: bool,
        text: str,
        desc: str,
        res_id: str,
    ) -> str:
        if is_editable or "EditText" in cls:
            return "input"
        if "Button" in cls or (is_clickable and not is_scrollable):
            return "button"
        if is_scrollable or "RecyclerView" in cls or "ListView" in cls or "ScrollView" in cls:
            return "scrollable"
        if "CheckBox" in cls or "Switch" in cls:
            return "toggle"
        if "ImageView" in cls:
            return "image"
        if "TextView" in cls and text:
            return "text"
        return "generic"

    def _parse_bounds(self, bounds_val: Any) -> Dict[str, int]:
        """Parses bounds string '[l,t][r,b]' or dict into {left, top, right, bottom, cx, cy}."""
        if isinstance(bounds_val, dict):
            cx = bounds_val.get("cx") or (bounds_val.get("left", 0) + bounds_val.get("right", 0)) // 2
            cy = bounds_val.get("cy") or (bounds_val.get("top", 0) + bounds_val.get("bottom", 0)) // 2
            return {
                "left": bounds_val.get("left", 0),
                "top": bounds_val.get("top", 0),
                "right": bounds_val.get("right", 0),
                "bottom": bounds_val.get("bottom", 0),
                "cx": cx,
                "cy": cy,
            }

        if isinstance(bounds_val, str) and "[" in bounds_val:
            m = re.findall(r"\[(\d+),(\d+)\]", bounds_val)
            if len(m) == 2:
                l, t = int(m[0][0]), int(m[0][1])
                r, b = int(m[1][0]), int(m[1][1])
                return {
                    "left": l, "top": t, "right": r, "bottom": b,
                    "cx": (l + r) // 2, "cy": (t + b) // 2
                }

        return {"left": 0, "top": 0, "right": 0, "bottom": 0, "cx": 0, "cy": 0}

    def _match_semantic_intent(self, nodes: List[Dict[str, Any]], intent: str) -> Optional[Dict[str, Any]]:
        """Maps common action intents to synonyms and typical component identifiers."""
        # 1. "send" / "submit"
        if intent in ["send", "send button", "submit", "bhejo"]:
            for n in nodes:
                desc = (n.get("contentDesc") or "").lower()
                res = (n.get("resourceId") or "").lower()
                txt = (n.get("text") or "").lower()
                if any(k in desc for k in ["send", "submit", "deliver"]) or \
                   any(k in res for k in ["send", "btn_send", "send_button"]) or \
                   txt in ["send", "go", "submit"]:
                    return n

        # 2. "search" / "find"
        if intent in ["search", "search button", "search bar", "magnifier", "dhundo"]:
            for n in nodes:
                desc = (n.get("contentDesc") or "").lower()
                res = (n.get("resourceId") or "").lower()
                txt = (n.get("text") or "").lower()
                if any(k in desc for k in ["search", "find", "query"]) or \
                   any(k in res for k in ["search", "menu_search", "search_bar"]) or \
                   txt in ["search", "search...", "find"]:
                    return n

        # 3. "shutter" / "take photo" / "capture"
        if intent in ["shutter", "take photo", "click photo", "camera button", "photo button"]:
            for n in nodes:
                desc = (n.get("contentDesc") or "").lower()
                res = (n.get("resourceId") or "").lower()
                if any(k in desc for k in ["shutter", "take photo", "capture"]) or \
                   any(k in res for k in ["shutter", "btn_camera", "capture_button"]):
                    return n

        # 4. "back" / "navigate up" / "close"
        if intent in ["back", "back button", "close", "piche"]:
            for n in nodes:
                desc = (n.get("contentDesc") or "").lower()
                res = (n.get("resourceId") or "").lower()
                if any(k in desc for k in ["back", "navigate up", "close", "dismiss"]) or \
                   any(k in res for k in ["action_bar_back", "btn_back", "close_button", "up"]):
                    return n

        return None

    def _match_positional_heuristic(self, nodes: List[Dict[str, Any]], intent: str) -> Optional[Dict[str, Any]]:
        """Human-like spatial heuristics based on common screen layout conventions."""
        clickable_nodes = [n for n in nodes if n.get("isClickable")]
        if not clickable_nodes:
            return None

        # "back button" -> top-left clickable
        if intent in ["back", "back button", "piche"]:
            best = None
            min_dist = float("inf")
            for n in clickable_nodes:
                b = self._parse_bounds(n.get("bounds"))
                if b["top"] < 400 and b["left"] < 300:
                    dist = b["left"] + b["top"]
                    if dist < min_dist:
                        min_dist = dist
                        best = n
            if best:
                return best

        # "send button" -> bottom-right clickable
        if intent in ["send", "send button", "bhejo"]:
            best = None
            max_coord = -1
            for n in clickable_nodes:
                b = self._parse_bounds(n.get("bounds"))
                if b["top"] > 1200 and b["left"] > 600:
                    coord = b["cx"] + b["cy"]
                    if coord > max_coord:
                        max_coord = coord
                        best = n
            if best:
                return best

        # "search button" / "top right icon"
        if intent in ["search", "search icon"]:
            for n in clickable_nodes:
                b = self._parse_bounds(n.get("bounds"))
                if b["top"] < 400 and b["left"] > 700:
                    return n

        return None


# Global singleton
screen_analyzer = ScreenAnalyzer()
