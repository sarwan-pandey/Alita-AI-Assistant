"""
task_planner.py — Multi-Step Autonomous Mobile Task Planner & Dynamic Replanner

Decomposes complex mobile instructions into verified steps, executes them one by one
via action_executor, and dynamically replans the remainder if on-screen reality shifts.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from engines.action_executor import action_executor, ExecutionOutcome
from engines.screen_analyzer import screen_analyzer

logger = logging.getLogger("alita.task_planner")


@dataclass
class TaskStep:
    name: str
    action: Dict[str, Any]
    narration: str
    target_package: Optional[str] = None
    expected_text: Optional[str] = None
    timeout_s: float = 4.0
    pre_condition: Optional[str] = None    # What should be on screen before this step
    find_target: Optional[str] = None       # Smart element search query (e.g. 'Search', 'Send', contact name)
    wait_for_ready: bool = True             # Wait for screen to settle from loading
    scroll_to_find: bool = False            # Scroll down to find target if not visible
    error_recovery: str = "retry"           # "retry" | "scroll_retry" | "back_retry" | "skip" | "abort"
    pre_delay_s: float = 0.0                # Delay in seconds to allow UI rendering before executing action

    def is_satisfied(self, state: Dict[str, Any]) -> bool:
        """Evaluate if step reached its expected state."""
        if not state or not isinstance(state, dict):
            return False

        # Package check
        if self.target_package:
            curr_pkg = state.get("currentPackage") or (state.get("view_tree", {}).get("package") if isinstance(state.get("view_tree"), dict) else "")
            if curr_pkg and self.target_package not in curr_pkg:
                return False

        # On-screen text check
        if self.expected_text:
            tree = state.get("view_tree", {})
            nodes = tree.get("nodes", []) if isinstance(tree, dict) else []
            exp_lower = self.expected_text.lower()
            text_found = any(
                exp_lower in (n.get("text") or "").lower() or
                exp_lower in (n.get("contentDesc") or "").lower()
                for n in nodes
            )
            if not text_found:
                return False

        # Find target check
        if self.find_target:
            tree = state.get("view_tree", {})
            if isinstance(tree, dict) and tree.get("nodes"):
                matched = screen_analyzer.find_element_smart(tree, self.find_target)
                if not matched:
                    return False

        return True


@dataclass
class TaskPlanResult:
    success: bool
    completed_steps: int
    total_steps: int
    narrations: List[str] = field(default_factory=list)
    error: Optional[str] = None
    last_outcome: Optional[ExecutionOutcome] = None


class TaskPlanner:
    """
    Plans and executes multi-step mobile workflows with dynamic on-screen replanning.
    """

    MAX_STEPS_CAP = 12
    MAX_WALL_TIME_SECONDS = 45.0

    WORD_TO_NUM = {
        "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
        "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50,
        "hundred": 100, "thousand": 1000,
    }

    def _parse_currency_amount(self, text: str) -> Optional[float]:
        t = text.lower()
        m = re.search(r'(?:rs\.?|inr|rupees?|₹)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:rs\.?|inr|rupees?|₹|bucks)', t)
        if m:
            val = m.group(1) or m.group(2)
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        m = re.search(r'\b(?:send|pay|transfer)\s+(\d+(?:\.\d+)?)\b', t)
        if m:
            try:
                return float(m.group(1))
            except (ValueError, TypeError):
                pass
        words_pat = '|'.join(self.WORD_TO_NUM.keys())
        m = re.search(r'\b(' + words_pat + r')\s+(?:rupees?|rs\.?|inr|bucks)\b', t)
        if m:
            return float(self.WORD_TO_NUM[m.group(1)])
        m = re.search(r'\b(?:send|pay|transfer)\s+(' + words_pat + r')\b', t)
        if m:
            return float(self.WORD_TO_NUM[m.group(1)])
        return None

    def _parse_payment_recipient(self, text: str) -> Optional[str]:
        t = re.sub(r'^(?:i\s+want\s+you\s+to|please|can\s+you|mj|alita|hey|hello)\s+', '', text.strip(), flags=re.IGNORECASE)
        # 1. Hindi: 'Aditya RM ko ...'
        m = re.search(r'^([a-zA-Z0-9_\s]+?)\s+ko\b', t, re.IGNORECASE)
        if m:
            return m.group(1).strip().title()
        # 2. English: 'to <recipient>'
        m = re.search(r'\bto\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:on|in|via|through|using)\s+(?:gpay|google\s+pay|phonepe|paytm|upi)|$)', t, re.IGNORECASE)
        if m:
            recip = m.group(1).strip()
            recip = re.sub(r'\s+(on|in|via)\s+(my\s+)?phone$', '', recip, flags=re.IGNORECASE).strip()
            return recip.title()
        # 3. 'pay <recipient> <amount>'
        words_pat = '|'.join(self.WORD_TO_NUM.keys())
        m = re.search(r'\bpay\s+([a-zA-Z0-9_\s]+?)\s+(?:\d+|' + words_pat + r')', t, re.IGNORECASE)
        if m:
            return m.group(1).strip().title()
        return None

    def plan_steps(self, instruction: str, current_screen_state: Dict[str, Any]) -> List[TaskStep]:
        """
        Decomposes instruction into an ordered sequence of verified micro-steps.
        Employs fast rule templates for primary actions (messaging, social, app control),
        with view-tree grounded element selection.
        """
        inst_lower = re.sub(r'^(mj|alita|hey mj|hey alita|hello mj|hello alita|ok mj|ok alita|hi mj|hi alita|listen mj|listen alita)\b[,:\s]*', '', instruction.strip().lower()).strip()
        steps: List[TaskStep] = []

        # 1. Screen Unlock
        is_only_unlock = any(w in inst_lower for w in ["unlock", "wake and unlock"]) and not any(
            c in inst_lower for c in [" and ", " then ", " aur ", " phir ", " fir "]
        )
        if is_only_unlock:
            steps.append(TaskStep(
                name="unlock_device",
                action={"command": "unlock"},
                narration="Unlocking screen via on-device secure keystore...",
                timeout_s=4.0,
            ))
            return steps
        elif any(w in inst_lower for w in ["unlock", "wake and unlock"]):
            steps.append(TaskStep(
                name="unlock_device",
                action={"command": "unlock"},
                narration="Unlocking screen via on-device secure keystore...",
                timeout_s=4.0,
            ))

        # ── Call Handling (Answer / Reject) ──────────────────────────────
        if any(w in inst_lower for w in ["answer call", "answer the call", "pick up call", "pick up the phone", "call uthao", "call receive karo", "accept call"]):
            steps.append(TaskStep(
                name="answer_call",
                action={"command": "answer_call"},
                narration="Answering incoming call on your phone...",
                timeout_s=4.0,
            ))
            return steps

        if any(w in inst_lower for w in ["reject call", "reject the call", "decline call", "cut call", "call cut karo", "call kaat do", "call reject karo", "ignore call"]):
            steps.append(TaskStep(
                name="reject_call",
                action={"command": "reject_call"},
                narration="Declining incoming call on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # ── Connectivity & System Toggles ────────────────────────────────
        # WiFi
        if re.search(r"\b(wifi|wi-fi)\b", inst_lower) and any(w in inst_lower for w in ["on", "off", "enable", "disable", "chalu", "band", "toggle", "turn on", "turn off", "connect"]):
            is_on = any(w in inst_lower for w in ["on", "enable", "chalu", "turn on", "connect"])
            is_off = any(w in inst_lower for w in ["off", "disable", "band", "turn off"])
            val = True if is_on and not is_off else (False if is_off else None)
            steps.append(TaskStep(
                name="toggle_wifi",
                action={"command": "toggle_wifi", "enabled": val},
                narration=f"Turning {'on' if val else ('off' if val is False else 'toggling')} WiFi on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # Bluetooth
        if re.search(r"\b(bluetooth|bt)\b", inst_lower) and any(w in inst_lower for w in ["on", "off", "enable", "disable", "chalu", "band", "toggle", "turn on", "turn off", "connect"]):
            is_on = any(w in inst_lower for w in ["on", "enable", "chalu", "turn on", "connect"])
            is_off = any(w in inst_lower for w in ["off", "disable", "band", "turn off"])
            val = True if is_on and not is_off else (False if is_off else None)
            steps.append(TaskStep(
                name="toggle_bluetooth",
                action={"command": "toggle_bluetooth", "enabled": val},
                narration=f"Turning {'on' if val else ('off' if val is False else 'toggling')} Bluetooth on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # Airplane Mode
        if any(w in inst_lower for w in ["airplane mode", "flight mode", "aeroplane mode", "hawa jahaz mode"]):
            steps.append(TaskStep(
                name="toggle_airplane",
                action={"command": "toggle_airplane"},
                narration="Opening Airplane mode settings on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # Mobile Data
        if any(w in inst_lower for w in ["mobile data", "cellular data", "data on", "data off", "net on", "net off"]):
            steps.append(TaskStep(
                name="toggle_mobile_data",
                action={"command": "toggle_mobile_data"},
                narration="Opening mobile network settings on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # Hotspot
        if any(w in inst_lower for w in ["hotspot", "tethering", "personal hotspot"]):
            steps.append(TaskStep(
                name="toggle_hotspot",
                action={"command": "toggle_hotspot"},
                narration="Opening hotspot settings on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # Auto Rotate
        if any(w in inst_lower for w in ["auto rotate", "autorotate", "screen rotation", "auto rotation"]):
            is_on = any(w in inst_lower for w in ["on", "enable", "chalu"])
            is_off = any(w in inst_lower for w in ["off", "disable", "band"])
            val = True if is_on and not is_off else (False if is_off else None)
            steps.append(TaskStep(
                name="toggle_auto_rotate",
                action={"command": "toggle_auto_rotate", "enabled": val},
                narration="Toggling auto screen rotation on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # DND / Silent / Vibrate Mode
        if any(w in inst_lower for w in ["dnd", "do not disturb"]):
            is_off = any(w in inst_lower for w in ["off", "band", "disable"])
            steps.append(TaskStep(
                name="toggle_dnd",
                action={"command": "toggle_dnd", "enabled": not is_off},
                narration=f"{'Disabling' if is_off else 'Enabling'} Do Not Disturb on your phone...",
                timeout_s=4.0,
            ))
            return steps

        if any(w in inst_lower for w in ["silent mode", "phone silent", "phone ko silent", "silent karo"]):
            steps.append(TaskStep(
                name="set_silent_mode",
                action={"command": "set_ringer_mode", "mode": "silent"},
                narration="Setting phone to silent mode...",
                timeout_s=4.0,
            ))
            return steps

        if any(w in inst_lower for w in ["vibrate mode", "vibration mode", "phone vibrate", "vibrate karo"]):
            steps.append(TaskStep(
                name="set_vibrate_mode",
                action={"command": "set_ringer_mode", "mode": "vibrate"},
                narration="Setting phone to vibrate mode...",
                timeout_s=4.0,
            ))
            return steps

        # ── Notification Management ──────────────────────────────────────
        if any(w in inst_lower for w in ["clear notifications", "clear all notifications", "dismiss notifications", "delete notifications", "notifications hatao", "notification saaf"]):
            steps.append(TaskStep(
                name="clear_all_notifications",
                action={"command": "clear_all_notifications"},
                narration="Clearing active notifications on your phone...",
                timeout_s=4.0,
            ))
            return steps

        # ── Open URL / Webpage ───────────────────────────────────────────
        url_match = re.search(r"(?:open|go\s+to|visit|navigate\s+to)\s+(?:website\s+|site\s+|url\s+)?(https?://\S+|[a-zA-Z0-9-]+\.(?:com|org|net|io|dev|in|co|ai|edu)(?:/\S*)?)", inst_lower)
        if url_match:
            raw_url = url_match.group(1).strip()
            if not any(raw_url.lower() == a for a in ["whatsapp", "youtube", "instagram", "spotify", "chrome", "maps", "facebook", "twitter", "reddit"]):
                steps.append(TaskStep(
                    name="open_url",
                    action={"command": "open_url", "url": raw_url},
                    narration=f"Opening {raw_url} on your phone...",
                    timeout_s=5.0,
                ))
                return steps

        # ── Google Maps Navigation ───────────────────────────────────────
        maps_match = re.search(r"(?:navigate|directions?|route)\s+(?:to|for)\s+(.+)", inst_lower) or \
                     re.search(r"(?:how\s+to\s+(?:get|go|reach))\s+(?:to\s+)?(.+)", inst_lower)
        if maps_match:
            dest_raw = instruction[maps_match.start(1):maps_match.end(1)].strip()
            dest_raw = re.sub(r"\s+(on\s+phone|on\s+mobile|in\s+maps)$", "", dest_raw, flags=re.IGNORECASE).strip()
            destination = dest_raw
            steps.append(TaskStep(
                name="navigate_destination",
                action={"command": "launch_app", "package": "com.google.android.apps.maps", "deepLink": f"google.navigation:q={destination}"},
                narration=f"Navigating to {destination} on Google Maps...",
                target_package="com.google.android.apps.maps",
                timeout_s=6.0,
            ))
            return steps

        # ── Photo Capture with Smart Verification ────────────────────────
        if any(w in inst_lower for w in ["take photo", "take a photo", "take picture", "take a picture",
                                          "take selfie", "take a selfie", "photo lo", "selfie lo",
                                          "photo lelo", "selfie lelo", "snap lo", "capture photo", "click a photo"]):
            is_selfie = any(w in inst_lower for w in ["selfie", "front camera"])
            steps.append(TaskStep(
                name="capture_photo",
                action={"command": "capture_photo", "selfie": is_selfie},
                narration=f"Taking {'selfie' if is_selfie else 'photo'} with phone camera...",
                timeout_s=7.0,
            ))
            return steps

        # ── UPI Payment Workflow (Google Pay, PhonePe, Paytm, UPI Intent) ────
        is_payment_cmd = any(w in inst_lower for w in ["pay", "payment", "transfer", "bhejo", "gpay", "phonepe", "paytm", "upi"]) or \
                         any(w in inst_lower for w in ["rupee", "rupees", "rs", "inr", "paise"])
        if is_payment_cmd:
            amt = self._parse_currency_amount(inst_lower)
            recip = self._parse_payment_recipient(instruction)
            if amt and recip:
                app_pkg = None
                app_name = "your UPI app"
                if "gpay" in inst_lower or "google pay" in inst_lower:
                    app_pkg = "com.google.android.apps.nbu.paisa.user"
                    app_name = "Google Pay"
                elif "phonepe" in inst_lower or "phone pe" in inst_lower:
                    app_pkg = "com.phonepe.app"
                    app_name = "PhonePe"
                elif "paytm" in inst_lower:
                    app_pkg = "net.one97.paytm"
                    app_name = "Paytm"

                encoded_pn = urllib.parse.quote(recip)
                amt_str = f"{amt:.2f}"
                upi_uri = f"upi://pay?pn={encoded_pn}&am={amt_str}&cu=INR&tn=Payment"

                steps.append(TaskStep(
                    name="launch_upi_payment",
                    action={
                        "command": "pay_upi",
                        "recipient": recip,
                        "amount": amt,
                        "package": app_pkg,
                        "upi_uri": upi_uri,
                    },
                    narration=f"Setting up Rs. {amt:g} payment to {recip} on {app_name}...",
                    timeout_s=6.0,
                ))
                steps.append(TaskStep(
                    name="prompt_upi_pin",
                    action={"command": "read_screen"},
                    narration=f"I've set up Rs. {amt:g} to {recip}. Please enter your UPI PIN on your phone to finalize.",
                    timeout_s=4.0,
                    error_recovery="skip",
                ))
                return steps

        # ── Spotify Search & Play ────────────────────────────────────────
        spotify_match = re.search(r"(?:play|search)\s+(.+?)\s+(?:on|in)\s+spotify", inst_lower) or \
                        re.search(r"spotify\s+(?:pe|par)\s+(.+?)\s+(?:bajao|chalao|play)", inst_lower)
        if spotify_match:
            spot_query = spotify_match.group(1).strip()
            steps.append(TaskStep(
                name="launch_spotify",
                action={"command": "launch_app", "package": "com.spotify.music"},
                narration="Opening Spotify...",
                target_package="com.spotify.music",
                timeout_s=6.0,
            ))
            steps.append(TaskStep(
                name="tap_spotify_search",
                action={"command": "click", "find_target": "Search"},
                find_target="Search",
                narration="Opening Spotify search...",
                target_package="com.spotify.music",
            ))
            steps.append(TaskStep(
                name="type_spotify_query",
                action={"command": "type", "text": spot_query},
                narration=f"Searching for '{spot_query}' on Spotify...",
                target_package="com.spotify.music",
            ))
            return steps

        # ── Messaging Workflow (WhatsApp, Telegram, Instagram) ───────────
        clean_inst = re.sub(r"\bthat:\s*", "that ", inst_lower)
        clean_inst = re.sub(r"\bwith:\s*", "with ", clean_inst)
        clean_inst = re.sub(r"\bki:\s*", "ki ", clean_inst)

        msg_match = re.search(
            r"(?:send\s+(?:a\s+)?message|message|text|send\s+whatsapp|send\s+telegram)\s+(?:on\s+(?:whatsapp|telegram|instagram)\s+)?(?:to\s+)?(.+?)\s+(?:on\s+(?:whatsapp|telegram|instagram)\s+)?(?:that|with|saying|:)\s*(.+)",
            clean_inst,
            re.IGNORECASE
        )
        if not msg_match:
            msg_match = re.search(
                r"send\s+(?:a\s+)?message\s+on\s+(?:whatsapp|telegram|instagram)\s+to\s+(.+?)\s+(?:that|with|saying|:)\s*(.+)",
                clean_inst,
                re.IGNORECASE
            )
        if not msg_match:
            hindi_match = re.search(
                r"(?:(?:whatsapp|telegram|instagram)\s+(?:pe|par)\s+)?(.+?)\s+ko\s+(?:message|text)\s+(?:bhejo|karo|send\s+karo)\s+(?:ki|that|:)\s*(.+)",
                clean_inst,
                re.IGNORECASE
            )
            if hindi_match:
                msg_match = hindi_match

        if msg_match:
            raw_recip = msg_match.group(1).strip()
            raw_recip = re.sub(r"^(?:(?:send\s+(?:a\s+)?message|message|text)\s+)?(?:on\s+(?:whatsapp|telegram|instagram)\s+)?to\s+", "", raw_recip, flags=re.IGNORECASE).strip()
            raw_recip = re.sub(r"\s+on\s+(?:whatsapp|telegram|instagram)$", "", raw_recip, flags=re.IGNORECASE).strip()
            recipient = raw_recip.title()
            msg_text = instruction[msg_match.start(2):].strip() if msg_match.start(2) < len(instruction) else msg_match.group(2).strip()

            is_telegram = "telegram" in clean_inst
            is_instagram = "instagram" in clean_inst or "insta" in clean_inst

            if is_telegram:
                curr_pkg = current_screen_state.get("currentPackage") or ""
                if curr_pkg != "org.telegram.messenger":
                    steps.append(TaskStep(
                        name="launch_telegram",
                        action={"command": "launch_app", "package": "org.telegram.messenger"},
                        narration=f"Opening Telegram for {recipient}...",
                        target_package="org.telegram.messenger",
                    ))
                steps.append(TaskStep(
                    name="search_contact",
                    action={"command": "click", "find_target": "Search"},
                    find_target="Search",
                    narration=f"Searching for {recipient}...",
                    target_package="org.telegram.messenger",
                ))
                steps.append(TaskStep(
                    name="type_contact_name",
                    action={"command": "type", "text": recipient},
                    narration=f"Typing '{recipient}'...",
                    target_package="org.telegram.messenger",
                ))
                steps.append(TaskStep(
                    name="open_chat",
                    action={"command": "click", "find_target": recipient, "target": recipient},
                    find_target=recipient,
                    scroll_to_find=True,
                    narration=f"Opening chat with {recipient}...",
                    target_package="org.telegram.messenger",
                ))
                steps.append(TaskStep(
                    name="type_message",
                    action={"command": "type", "text": msg_text},
                    narration="Typing message...",
                    target_package="org.telegram.messenger",
                ))
                steps.append(TaskStep(
                    name="send_message",
                    action={"command": "click", "find_target": "Send"},
                    find_target="Send",
                    narration="Sending message...",
                    target_package="org.telegram.messenger",
                ))
                return steps

            elif is_instagram:
                curr_pkg = current_screen_state.get("currentPackage") or ""
                if curr_pkg != "com.instagram.android":
                    steps.append(TaskStep(
                        name="launch_instagram",
                        action={"command": "launch_app", "package": "com.instagram.android"},
                        narration=f"Opening Instagram for {recipient}...",
                        target_package="com.instagram.android",
                    ))
                steps.append(TaskStep(
                    name="open_dms",
                    action={"command": "click", "find_target": "Direct"},
                    find_target="Direct",
                    narration="Opening Instagram Direct Messages...",
                    target_package="com.instagram.android",
                ))
                steps.append(TaskStep(
                    name="search_contact",
                    action={"command": "click", "find_target": "Search"},
                    find_target="Search",
                    narration=f"Searching for {recipient}...",
                    target_package="com.instagram.android",
                ))
                steps.append(TaskStep(
                    name="type_contact_name",
                    action={"command": "type", "text": recipient},
                    narration=f"Typing '{recipient}'...",
                    target_package="com.instagram.android",
                ))
                steps.append(TaskStep(
                    name="open_chat",
                    action={"command": "click", "find_target": recipient, "target": recipient},
                    find_target=recipient,
                    scroll_to_find=True,
                    narration=f"Opening DM with {recipient}...",
                    target_package="com.instagram.android",
                ))
                steps.append(TaskStep(
                    name="type_message",
                    action={"command": "type", "text": msg_text},
                    narration="Typing message...",
                    target_package="com.instagram.android",
                ))
                steps.append(TaskStep(
                    name="send_message",
                    action={"command": "click", "find_target": "Send"},
                    find_target="Send",
                    narration="Sending message...",
                    target_package="com.instagram.android",
                ))
                return steps

            else:
                # WhatsApp (Default)
                curr_pkg = current_screen_state.get("currentPackage") or ""
                if curr_pkg != "com.whatsapp":
                    steps.append(TaskStep(
                        name="launch_whatsapp",
                        action={"command": "launch_app", "package": "com.whatsapp"},
                        narration=f"Opening WhatsApp for {recipient}...",
                        target_package="com.whatsapp",
                    ))

                steps.append(TaskStep(
                    name="search_contact",
                    action={"command": "click", "target": "Search", "resourceId": "menuitem_search", "find_target": "Search"},
                    find_target="Search",
                    narration=f"Searching for {recipient}...",
                    target_package="com.whatsapp",
                ))
                steps.append(TaskStep(
                    name="type_contact_name",
                    action={"command": "type", "target": "search_src_text", "text": recipient},
                    narration=f"Typing '{recipient}' in search...",
                    target_package="com.whatsapp",
                ))
                steps.append(TaskStep(
                    name="open_chat",
                    action={"command": "click", "target": recipient, "find_target": recipient},
                    find_target=recipient,
                    scroll_to_find=True,
                    narration=f"Opening conversation with {recipient}...",
                    target_package="com.whatsapp",
                ))
                steps.append(TaskStep(
                    name="type_message",
                    action={"command": "type", "target": "entry", "text": msg_text},
                    narration="Typing your message...",
                    target_package="com.whatsapp",
                ))
                steps.append(TaskStep(
                    name="send_message",
                    action={"command": "click", "target": "Send", "resourceId": "send", "find_target": "Send"},
                    find_target="Send",
                    narration="Sending message...",
                    target_package="com.whatsapp",
                ))
                return steps

        # 3. Gesture Navigation: Scroll / Swipe
        if any(w in inst_lower for w in ["scroll up", "swipe up", "upar scroll karo", "scroll upar karo"]):
            steps.append(TaskStep(
                name="scroll_up",
                action={"command": "swipe", "startX": 540, "startY": 600, "endX": 540, "endY": 1600, "duration": 350},
                narration="Scrolling up on phone...",
            ))
            return steps

        if any(w in inst_lower for w in ["scroll down", "swipe down", "scroll", "niche scroll karo", "scroll niche karo"]):
            steps.append(TaskStep(
                name="scroll_down",
                action={"command": "swipe", "startX": 540, "startY": 1600, "endX": 540, "endY": 600, "duration": 350},
                narration="Scrolling down on phone...",
            ))
            return steps

        # 4. Social Media Interactions: Like / Double Tap
        if any(w in inst_lower for w in ["like this post", "like the post", "like post", "like this video", "like this", "double tap", "post like karo"]):
            steps.append(TaskStep(
                name="like_post",
                action={"command": "click", "target": "Like", "resourceId": "row_feed_button_like"},
                narration="Liking current post on phone...",
            ))
            return steps

        # 5. Screen Capture / Global Actions
        if any(w in inst_lower for w in ["home screen", "go to home", "go home", "open home", "home page"]):
            steps.append(TaskStep(
                name="nav_home",
                action={"command": "global", "action": "home"},
                narration="Going to home screen on phone...",
            ))
            return steps

        if any(w in inst_lower for w in ["recent apps", "open recent", "open recents", "recent tasks", "recents"]):
            steps.append(TaskStep(
                name="nav_recents",
                action={"command": "global", "action": "recents"},
                narration="Opening recent apps on phone...",
            ))
            return steps

        if any(w in inst_lower for w in ["go back", "press back", "back button", "peeche jao"]):
            steps.append(TaskStep(
                name="nav_back",
                action={"command": "global", "action": "back"},
                narration="Going back on phone...",
            ))
            return steps

        if any(w in inst_lower for w in ["screenshot", "take screenshot", "take a screenshot", "capture screen"]):
            steps.append(TaskStep(
                name="take_screenshot",
                action={"command": "global", "action": "take_screenshot"},
                narration="Capturing phone screenshot...",
            ))
            return steps

        # 6. Instagram Like/Follow Workflow
        if "instagram" in inst_lower or "insta" in inst_lower:
            curr_pkg = current_screen_state.get("currentPackage") or ""
            if "com.instagram.android" not in curr_pkg:
                steps.append(TaskStep(
                    name="launch_instagram",
                    action={"command": "launch_app", "package": "com.instagram.android"},
                    narration="Opening Instagram...",
                    target_package="com.instagram.android",
                ))
            if "like" in inst_lower:
                steps.append(TaskStep(
                    name="like_post",
                    action={"command": "click", "target": "Like", "resourceId": "row_feed_button_like"},
                    narration="Liking post on Instagram...",
                    target_package="com.instagram.android",
                ))
            return steps

        # 6b. SMS / Text Message Workflow
        sms_match = re.search(
            r"(?:send\s+(?:an?\s+)?(?:sms|text)\s+to|sms\s+bhejo|text\s+karo)\s+(.+?)\s+(?:that|with|saying|:)\s*(.+)",
            clean_inst, re.IGNORECASE
        )
        if not sms_match:
            sms_match = re.search(
                r"(.+?)\s+ko\s+(?:sms|text)\s+(?:bhejo|karo|send\s+karo)\s+(?:ki|that|:)\s*(.+)",
                clean_inst, re.IGNORECASE
            )
        if sms_match:
            sms_recip = sms_match.group(1).strip().title()
            sms_text = sms_match.group(2).strip()
            steps.append(TaskStep(
                name="send_sms",
                action={"command": "send_sms", "contactName": sms_recip, "message": sms_text},
                narration=f"Sending SMS to {sms_recip}: '{sms_text[:40]}...'",
                timeout_s=8.0,
            ))
            return steps

        # 6c. Camera / Photo / Selfie Workflow
        if any(w in inst_lower for w in ["take photo", "take a photo", "take picture", "take a picture",
                                          "take selfie", "take a selfie", "photo lo", "selfie lo",
                                          "photo lelo", "selfie lelo", "snap lo", "capture photo"]):
            is_selfie = any(w in inst_lower for w in ["selfie", "front camera"])
            steps.append(TaskStep(
                name="open_camera",
                action={"command": "open_camera", "selfie": is_selfie},
                narration=f"Opening {'front' if is_selfie else 'rear'} camera...",
                timeout_s=5.0,
            ))
            return steps

        # 6d. YouTube Play / Search Workflow (Semantic & Deep-Link Enabled)
        yt_match = re.search(r"(?:play|search)\s+(.+?)\s+(?:on|in)\s+(?:youtube|yt)", inst_lower) or \
                   re.search(r"(?:youtube|yt)\s+(?:pe|par)\s+(.+?)\s+(?:bajao|chalao|play)", inst_lower)
        is_yt = ("youtube" in inst_lower or "yt" in inst_lower) and any(
            w in inst_lower for w in ["play", "search", "find", "chalao", "bajao", "music", "song", "video", "track", "listen"]
        )
        if is_yt or yt_match:
            try:
                from engines.semantic_target_binder import semantic_target_binder
                resolved = semantic_target_binder.resolve(instruction)
                query = resolved.get("query") or "top trending songs"
            except Exception:
                query = yt_match.group(1).strip() if yt_match else "top trending songs"

            # Clean any trailing noise or residual prepositions
            query = re.sub(r'\b(app|application|for the phone|on my phone|for phone|on phone|in mobile|in the youtube|in youtube|on youtube|in yt|on yt)\b', '', query, flags=re.I).strip()
            if not query or query in ("music", "song", "songs", "a", "in", "on"):
                query = "top trending songs"

            import urllib.parse
            deep_link = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"

            steps.append(TaskStep(
                name="launch_youtube_search",
                action={
                    "command": "launch_app",
                    "package": "com.google.android.youtube",
                    "deepLink": deep_link,
                },
                narration=f"Opening YouTube for '{query}' on your phone...",
                target_package="com.google.android.youtube",
                timeout_s=6.0,
            ))
            steps.append(TaskStep(
                name="tap_first_video",
                action={
                    "command": "tap",
                    "target": "first_video",
                    "resourceId": "title",
                    "x": 540.0,
                    "y": 720.0,
                    "duration": 50,
                },
                find_target="video",
                narration="Starting playback on your phone...",
                target_package="com.google.android.youtube",
                timeout_s=4.0,
                pre_delay_s=1.8,
                error_recovery="skip",
            ))
            return steps

        # 7. Comprehensive Android App Launch
        _app_match = re.search(r'\b(open|launch|chalao|kholo|start)\s+(.+)', inst_lower) or \
                     re.search(r'(.+?)\s+(kholo|chalao|open karo)\b', inst_lower)
        if _app_match:
            app_target = _app_match.group(2 if _app_match.lastindex == 2 and _app_match.group(1) in ("open", "launch", "chalao", "kholo", "start") else 1).strip()
            # Strip trailing "on phone", "on my phone", "in mobile"
            app_target = re.sub(r'\s+(on|in)\s+(my\s+)?(phone|mobile|device)$', '', app_target).strip()
            pkg_map = {
                "whatsapp": "com.whatsapp",
                "telegram": "org.telegram.messenger",
                "instagram": "com.instagram.android",
                "insta": "com.instagram.android",
                "youtube": "com.google.android.youtube",
                "yt": "com.google.android.youtube",
                "spotify": "com.spotify.music",
                "chrome": "com.android.chrome",
                "browser": "com.android.chrome",
                "camera": "com.google.android.GoogleCamera",
                "settings": "com.android.settings",
                "maps": "com.google.android.apps.maps",
                "google maps": "com.google.android.apps.maps",
                "snapchat": "com.snapchat.android",
                "twitter": "com.twitter.android",
                "x": "com.twitter.android",
                "facebook": "com.facebook.katana",
                "fb": "com.facebook.katana",
                "tiktok": "com.zhiliaoapp.musically",
                "netflix": "com.netflix.mediaclient",
                "prime": "com.amazon.avod.thirdpartyclient",
                "prime video": "com.amazon.avod.thirdpartyclient",
                "amazon prime": "com.amazon.avod.thirdpartyclient",
                "hotstar": "in.startv.hotstar",
                "disney hotstar": "in.startv.hotstar",
                "reddit": "com.reddit.frontpage",
                "linkedin": "com.linkedin.android",
                "discord": "com.discord",
                "gmail": "com.google.android.gm",
                "mail": "com.google.android.gm",
                "play store": "com.android.vending",
                "gallery": "com.coloros.gallery3d",
                "photos": "com.google.android.apps.photos",
                "google photos": "com.google.android.apps.photos",
                "calculator": "com.coloros.calculator",
                "clock": "com.coloros.alarmclock",
                "alarm": "com.coloros.alarmclock",
                "messages": "com.google.android.apps.messaging",
                "sms": "com.google.android.apps.messaging",
                "dialer": "com.google.android.dialer",
                "phone": "com.google.android.dialer",
                "truecaller": "com.truecaller",
                "paytm": "net.one97.paytm",
                "gpay": "com.google.android.apps.nbu.paisa.user",
                "google pay": "com.google.android.apps.nbu.paisa.user",
                "phonepe": "com.phonepe.app",
                # Extended app catalog
                "uber": "com.ubercab",
                "ola": "com.olacabs.customer",
                "zomato": "com.application.zomato",
                "swiggy": "in.swiggy.android",
                "amazon": "in.amazon.mShop.android.shopping",
                "flipkart": "com.flipkart.android",
                "myntra": "com.myntra.android",
                "slack": "com.Slack",
                "teams": "com.microsoft.teams",
                "microsoft teams": "com.microsoft.teams",
                "zoom": "us.zoom.videomeetings",
                "whatsapp business": "com.whatsapp.w4b",
                "signal": "org.thoughtcrime.securesms",
                "notion": "notion.id",
                "keep": "com.google.android.keep",
                "google keep": "com.google.android.keep",
                "notes": "com.google.android.keep",
                "drive": "com.google.android.apps.docs",
                "google drive": "com.google.android.apps.docs",
                "files": "com.google.android.apps.nbu.files",
                "file manager": "com.coloros.filemanager",
                "jio": "com.jio.myjio",
                "jiocinema": "com.jio.media.ondemand",
                "jio cinema": "com.jio.media.ondemand",
                "youtube music": "com.google.android.apps.youtube.music",
                "yt music": "com.google.android.apps.youtube.music",
                "cred": "com.dreamplug.androidapp",
                "razorpay": "com.razorpay.payments.app",
                "brave": "com.brave.browser",
                "firefox": "org.mozilla.firefox",
                "opera": "com.opera.browser",
                "edge": "com.microsoft.emmx",
                "microsoft edge": "com.microsoft.emmx",
                "outlook": "com.microsoft.office.outlook",
                "whatsapp status": "com.whatsapp",
                "pinterest": "com.pinterest",
                "shazam": "com.shazam.android",
                "sound hound": "com.melodis.midomiMusicIdentifier",
                "spotify": "com.spotify.music",
                "apple music": "com.apple.android.music",
                "wynk": "com.bsbportal.music",
                "gaana": "com.gaana",
                "hungama": "com.hungama.myplay.activity",
            }
            pkg = pkg_map.get(app_target, app_target)
            deeplink_map = {
                "youtube": "vnd.youtube://",
                "whatsapp": "whatsapp://send",
                "instagram": "instagram://app",
                "insta": "instagram://app",
                "spotify": "spotify://",
                "chrome": "googlechrome://",
                "browser": "googlechrome://",
                "maps": "geo:0,0",
                "google maps": "geo:0,0",
                "twitter": "twitter://",
                "x": "twitter://",
                "facebook": "fb://",
                "fb": "fb://",
                "snapchat": "snapchat://",
                "gmail": "googlegmail://",
                "mail": "mailto:",
                "play store": "market://search?q=",
            }
            deep_link = deeplink_map.get(app_target)

            curr_pkg = current_screen_state.get("currentPackage") or ""
            if curr_pkg == pkg:
                steps.append(TaskStep(
                    name=f"already_open_{app_target}",
                    action={"command": "global", "action": "home"},
                    narration=f"{app_target.title()} is already active on your screen.",
                    target_package=pkg,
                ))
            else:
                act = {"command": "launch_app", "package": pkg}
                if deep_link:
                    act["deepLink"] = deep_link
                steps.append(TaskStep(
                    name=f"launch_{app_target}",
                    action=act,
                    narration=f"Opening {app_target.title()}...",
                    target_package=pkg,
                    timeout_s=6.0,
                ))
            return steps

        # 8. Fallback Single Action (Navigation, etc.)
        nav_map = {
            "home": "home", "back": "back", "recents": "recents", "notifications": "notifications"
        }
        for k, v in nav_map.items():
            if k in inst_lower:
                steps.append(TaskStep(
                    name=f"nav_{v}",
                    action={"command": "global", "action": v},
                    narration=f"Navigating {v} on phone...",
                ))
                return steps

        return steps

    async def execute_plan(
        self,
        steps: List[TaskStep],
        get_state_fn: Callable[[], Any],
        read_screen_fn: Optional[Callable[[], Any]] = None,
        narration_callback: Optional[Callable[[str], Any]] = None,
    ) -> TaskPlanResult:
        """
        Executes an ordered step plan with closed-loop verification and dynamic replanning.
        """
        if not steps:
            return TaskPlanResult(success=False, completed_steps=0, total_steps=0, error="No steps to execute.")

        start_time = time.time()
        narrations: List[str] = []
        completed = 0
        skipped = 0
        last_outcome: Optional[ExecutionOutcome] = None

        for idx, step in enumerate(steps):
            if completed >= self.MAX_STEPS_CAP or (time.time() - start_time) > self.MAX_WALL_TIME_SECONDS:
                logger.warning("Task execution hit bounds limit (max steps or timeout).")
                break

            # Narrate step to user
            if narration_callback and step.narration:
                try:
                    cb_res = narration_callback(step.narration)
                    if asyncio.iscoroutine(cb_res):
                        await cb_res
                except Exception as e:
                    logger.debug(f"Narration callback error: {e}")

            narrations.append(step.narration)
            # Allow UI rendering time if pre_delay_s is configured
            if step.pre_delay_s > 0:
                await asyncio.sleep(step.pre_delay_s)

            # Pass context awareness parameters into the action dictionary
            if step.find_target and "find_target" not in step.action:
                step.action["find_target"] = step.find_target
            if step.scroll_to_find and "scroll_to_find" not in step.action:
                step.action["scroll_to_find"] = True

            # Closed-loop expected state predicate
            def _expected(s: Dict[str, Any]) -> bool:
                return step.is_satisfied(s)

            # Execute step through universal action executor
            outcome = await action_executor.execute_and_verify(
                action=step.action,
                expected_state_fn=_expected,
                get_state_fn=get_state_fn,
                read_screen_fn=read_screen_fn,
                timeout_s=step.timeout_s,
                max_retries=1,
            )
            last_outcome = outcome

            if outcome.verified or outcome.success:
                completed += 1
            else:
                # Step failed — Diagnose and decide recovery
                err_diag = outcome.error_type or "FAILED"
                logger.warning(f"Step '{step.name}' failed verification ({err_diag}).")

                # Check if an interruption paused it
                if outcome.interruption and not outcome.interruption.auto_resolvable:
                    return TaskPlanResult(
                        success=False,
                        completed_steps=completed,
                        total_steps=len(steps),
                        narrations=narrations,
                        error=outcome.error or "Task paused due to unhandled on-screen dialog.",
                        last_outcome=outcome,
                    )

                # If step is marked optional / skippable on failure
                if step.error_recovery == "skip":
                    logger.info(f"Step '{step.name}' failed but recovery is 'skip'. Continuing to next step.")
                    skipped += 1
                    continue

                # Abort task with clear diagnosis
                diag_msg = outcome.error or f"Step '{step.name}' failed verification ({err_diag})."
                return TaskPlanResult(
                    success=False,
                    completed_steps=completed,
                    total_steps=len(steps),
                    narrations=narrations,
                    error=diag_msg,
                    last_outcome=outcome,
                )

        return TaskPlanResult(
            success=((completed + skipped) == len(steps)),
            completed_steps=completed,
            total_steps=len(steps),
            narrations=narrations,
            last_outcome=last_outcome,
        )


# Global singleton
task_planner = TaskPlanner()
