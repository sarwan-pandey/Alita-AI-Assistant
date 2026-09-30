"""
interruption_handler.py — Mobile UI Interruption & OEM Popup Detection and Resolution

Detects permission dialogs, OEM battery/autostart popups (Realme/ColorOS), crash/ANR dialogs,
and unexpected package shifts mid-task. Resolves known safe popups automatically and escalates
unrecognized dialogs to the user.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("alita.interruption_handler")

# Known safe dismissal patterns: (package_regex, text_pattern, action_button_text)
KNOWN_SAFE_POPUPS = [
    # Android Runtime Permissions
    {
        "name": "runtime_permission_while_using",
        "package": r"com\.(google\.)?android\.permissioncontroller",
        "text": r"(allow\s+.*?\s+to|permission)",
        "preferred_buttons": ["While using the app", "ALLOW", "Allow", "Only this time"],
    },
    # Realme / ColorOS / Oppo Autostart & Background Prompts
    {
        "name": "coloros_autostart",
        "package": r"com\.coloros\.|com\.oppo\.|com\.heytap\.",
        "text": r"(auto-launch|background running|allow in background)",
        "preferred_buttons": ["Allow", "Turn on", "Keep running"],
    },
    {
        "name": "coloros_battery_warning",
        "package": r"com\.coloros\.|com\.oppo\.",
        "text": r"consuming.*battery",
        "preferred_buttons": ["Allow", "OK", "Ignore"],
    },
    {
        "name": "coloros_running_background",
        "package": r"com\.coloros\.|com\.oppo\.",
        "text": r"running in background",
        "preferred_buttons": ["Allow", "Keep running"],
    },
    {
        "name": "screen_overlay",
        "package": r"com\.android\.settings",
        "text": r"screen overlay",
        "preferred_buttons": ["Open settings", "OK"],
    },
    # Battery Optimization Prompt
    {
        "name": "battery_optimization_ignore",
        "package": r"com\.android\.settings",
        "text": r"(ignore battery optimizations|let app always run in background)",
        "preferred_buttons": ["Allow", "ALLOW", "OK"],
    },
    # Google Play Protect Warning
    {
        "name": "play_protect_warning",
        "package": r"com\.android\.vending",
        "text": r"(unrecognized app|harmful app|blocked by play protect)",
        "preferred_buttons": ["Install anyway", "More details"],
    },
    # App-Specific / Web Prompts
    {
        "name": "cookie_consent",
        "package": r".*",
        "text": r"(cookie|cookies|consent|accept all)",
        "preferred_buttons": ["Accept", "Accept All", "OK", "Got it", "Agree"],
    },
    {
        "name": "rate_app",
        "package": r".*",
        "text": r"(rate|review|enjoy|like this app)",
        "preferred_buttons": ["Not now", "Later", "No thanks", "Maybe later", "Cancel"],
    },
    {
        "name": "update_prompt",
        "package": r".*",
        "text": r"(update available|new version|upgrade)",
        "preferred_buttons": ["Later", "Not now", "Skip", "Remind me later"],
    },
    {
        "name": "login_prompt",
        "package": r".*",
        "text": r"(sign in|log in|create account)",
        "preferred_buttons": ["Skip", "Not now", "Maybe later", "Cancel"],
    },
    # System Warnings
    {
        "name": "low_battery_warning",
        "package": r"com\.android\.",
        "text": r"low battery|battery saver",
        "preferred_buttons": ["OK", "Dismiss"],
    },
    {
        "name": "no_sim_warning",
        "package": r"com\.android\.",
        "text": r"no sim|insert sim",
        "preferred_buttons": ["OK", "Dismiss"],
    },
    {
        "name": "usb_debugging",
        "package": r"com\.android\.",
        "text": r"usb debugging",
        "preferred_buttons": ["OK", "Allow"],
    },
]

# Crash / ANR indicators
CRASH_PATTERNS = [
    r"isn't responding",
    r"keeps stopping",
    r"has stopped",
]


@dataclass
class InterruptionResult:
    is_interrupted: bool
    interruption_type: str = "none"  # "known_popup", "unhandled_popup", "crash_anr", "none"
    dialog_title: str = ""
    suggested_action: str = ""
    auto_resolvable: bool = False
    target_button: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class InterruptionHandler:
    """
    Analyzes view-trees for system dialogs, crashes, and permission popups.
    """

    def detect_interruption(self, screen_tree: Dict[str, Any]) -> InterruptionResult:
        """Inspect a view-tree dump to see if an interrupting dialog is currently active."""
        if not screen_tree or not isinstance(screen_tree, dict):
            return InterruptionResult(is_interrupted=False)

        nodes = screen_tree.get("nodes") or []
        pkg = screen_tree.get("package") or ""

        valid_nodes = [n for n in nodes if isinstance(n, dict)]

        all_text = " ".join([
            (n.get("text") or "") + " " + (n.get("contentDesc") or "")
            for n in valid_nodes
        ]).strip()
        all_text_lower = all_text.lower()

        # 1. Check for Crash / ANR dialogs
        # Only treat as ANR if text matches and it's a modal dialog (low node count or system package)
        for crash_pat in CRASH_PATTERNS:
            if re.search(crash_pat, all_text_lower):
                has_crash_action = any(
                    (n.get("text") or n.get("contentDesc") or "").strip().lower() in ["wait", "close app", "ok", "force close"]
                    for n in valid_nodes
                )
                if has_crash_action or len(valid_nodes) < 15 or pkg in ["android", "com.android.systemui"]:
                    return InterruptionResult(
                        is_interrupted=True,
                        interruption_type="crash_anr",
                        dialog_title="Application crash / Not Responding",
                        suggested_action="App has crashed or stopped responding. Close app or wait.",
                        auto_resolvable=False,
                        details={"all_text": all_text[:200], "package": pkg},
                    )

        # 2. Check against Known Safe Popups
        for popup_rule in KNOWN_SAFE_POPUPS:
            pkg_match = bool(re.search(popup_rule["package"], pkg, re.IGNORECASE)) if pkg else False
            text_match = bool(re.search(popup_rule["text"], all_text, re.IGNORECASE))

            if text_match and (pkg_match or popup_rule["package"] == r".*" or not pkg):
                # Find if any preferred button is present in nodes
                for pref_btn in popup_rule["preferred_buttons"]:
                    for node in valid_nodes:
                        node_text = (node.get("text") or node.get("contentDesc") or "").strip()
                        if node_text.lower() == pref_btn.lower() and node.get("isClickable", False):
                            return InterruptionResult(
                                is_interrupted=True,
                                interruption_type="known_popup",
                                dialog_title=popup_rule["name"],
                                suggested_action=f"Auto-dismiss by clicking '{node_text}'",
                                auto_resolvable=True,
                                target_button=node_text,
                                details={"node": node, "package": pkg},
                            )

        # 3. Check for generic Unhandled System Dialogs
        # If package is permission controller or dialog box with buttons like "Cancel" / "Deny"
        is_dialog_pkg = bool(pkg and any(p in pkg for p in ["permissioncontroller", "dialog", "packageinstaller"]))
        has_dialog_buttons = any(
            (n.get("text") or n.get("contentDesc") or "").strip() in ["Cancel", "Deny", "Don't allow", "Block"]
            for n in valid_nodes
        )

        if is_dialog_pkg or (has_dialog_buttons and len(valid_nodes) < 15):
            return InterruptionResult(
                is_interrupted=True,
                interruption_type="unhandled_popup",
                dialog_title="Unhandled System Dialog",
                suggested_action="Unrecognized dialog appeared. Ask user how to proceed.",
                auto_resolvable=False,
                details={"all_text": all_text[:200], "package": pkg},
            )

        return InterruptionResult(is_interrupted=False)

    async def resolve_known_popup(
        self,
        interruption: InterruptionResult,
        click_fn: Callable[[str], Any],
    ) -> bool:
        """Auto-dismiss a recognized popup using the provided click callback."""
        if not interruption.auto_resolvable or not interruption.target_button:
            return False

        logger.info(f"Auto-dismissing recognized popup via button '{interruption.target_button}'")
        res = click_fn(interruption.target_button)
        import inspect
        if inspect.isawaitable(res):
            res = await res
        if isinstance(res, dict):
            return res.get("success", False)
        return bool(res)

    async def scroll_and_find(
        self,
        find_fn: Callable[[], Any],
        dispatch_fn: Callable[[Dict[str, Any]], Any],
        max_scrolls: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """
        Scrolls down repeatedly to find an element that isn't currently visible on screen.
        Returns the matched element node or None.
        """
        import inspect
        for i in range(max_scrolls + 1):
            res = find_fn()
            if inspect.isawaitable(res):
                res = await res
            if res:
                return res

            if i < max_scrolls:
                logger.info(f"Element not visible on screen, scrolling down (scroll {i + 1}/{max_scrolls})...")
                swipe_action = {
                    "command": "swipe",
                    "startX": 540.0,
                    "startY": 1600.0,
                    "endX": 540.0,
                    "endY": 600.0,
                    "duration": 300,
                }
                disp_res = dispatch_fn(swipe_action)
                if inspect.isawaitable(disp_res):
                    await disp_res
                await asyncio.sleep(0.6)

        return None


# Singleton instance
interruption_handler = InterruptionHandler()
