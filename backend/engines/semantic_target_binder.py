"""
semantic_target_binder.py — Semantic Target & Intent Resolver
============================================================
Resolves user instructions into canonical (TargetDevice, Action, TargetApp, CleanQuery)
tuples without brittle preposition regex dependencies.

Solves the "on phone" vs "for the phone" preposition bug once and for all.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Tuple

log = logging.getLogger("alita.semantic_target_binder")


class SemanticTargetBinder:
    """
    Robust entity and slot parser for dual-device (PC & Android Phone) operations.
    """

    # ── Target Device Signals ────────────────────────────────────────────────
    PHONE_EXPLICIT_PATTERNS = [
        # Preposition + Phone / Mobile
        r"\b(?:on|for|in|from|through|via|to|into)\s+(?:the\s+|my\s+|our\s+)?(?:phone|mobile|android|handset|device)\b",
        # Trailing shorthand
        r"\b(?:for\s+phone|on\s+phone|in\s+phone|for\s+mobile|on\s+mobile|in\s+mobile)\b",
        # Hindi / Hinglish locatives
        r"\b(?:phone|mobile)\s*(?:pe|par|pr|me|mein|se|ko)\b",
        # Direct device actions
        r"\b(?:unlock\s+(?:my\s+)?phone|lock\s+(?:my\s+)?phone|phone\s+unlock|phone\s+lock)\b",
        r"\b(?:phone\s+battery|mobile\s+battery|phone\s+screen|mobile\s+screen|phone\s+call)\b",
        r"\b(?:phone\s+companion|android\s+companion)\b",
    ]

    PC_EXPLICIT_PATTERNS = [
        r"\b(?:on|for|in|from|to)\s+(?:the\s+|my\s+)?(?:pc|laptop|computer|desktop|windows|mac)\b",
        r"\b(?:on\s+pc|for\s+pc|in\s+pc|on\s+laptop|for\s+laptop)\b",
        r"\b(?:pc|laptop|computer)\s*(?:pe|par|pr|me|mein)\b",
    ]

    # Apps strictly belonging to mobile environment
    PHONE_EXCLUSIVE_APPS = {
        "dialer": "com.google.android.dialer",
        "phone": "com.google.android.dialer",
        "call": "com.google.android.dialer",
        "camera": "com.google.android.GoogleCamera",
        "selfie": "com.google.android.GoogleCamera",
        "gallery": "com.google.android.apps.photos",
        "photos": "com.google.android.apps.photos",
        "sms": "com.google.android.apps.messaging",
        "messages": "com.google.android.apps.messaging",
        "contacts": "com.google.android.contacts",
    }

    # Apps strictly belonging to PC environment
    PC_EXCLUSIVE_APPS = {
        "vscode": "code.exe",
        "vs code": "code.exe",
        "visual studio": "devenv.exe",
        "terminal": "windowsterminal.exe",
        "powershell": "powershell.exe",
        "cmd": "cmd.exe",
        "command prompt": "cmd.exe",
        "file explorer": "explorer.exe",
        "task manager": "taskmgr.exe",
        "paint": "mspaint.exe",
        "notepad": "notepad.exe",
    }

    # Cross-platform apps
    CROSS_PLATFORM_APPS = {
        "youtube": ("com.google.android.youtube", "https://www.youtube.com"),
        "yt": ("com.google.android.youtube", "https://www.youtube.com"),
        "spotify": ("com.spotify.music", "spotify.exe"),
        "whatsapp": ("com.whatsapp", "whatsapp.exe"),
        "telegram": ("org.telegram.messenger", "telegram.exe"),
        "discord": ("com.discord", "discord.exe"),
        "chrome": ("com.android.chrome", "chrome.exe"),
        "browser": ("com.android.chrome", "chrome.exe"),
        "netflix": ("com.netflix.mediaclient", "https://www.netflix.com"),
    }

    def resolve(
        self,
        text: str,
        world_model_snapshot: Optional[Dict[str, Any]] = None,
        inherited_target: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Parses text into a structured intent resolution:
          - target_device: "phone" | "pc" | "both" | None
          - action: "play_media" | "open_app" | "close_app" | "system_control" | "communicate" | "query" | "general"
          - app: canonical app name or None
          - query: clean search term or payload
          - confidence: 0.0 to 1.0
          - suggested_method: "phone_deep_link" | "phone_task_planner" | "pc_automation" | None
        """
        if not text:
            return {
                "target_device": None,
                "action": "general",
                "app": None,
                "query": "",
                "confidence": 0.0,
                "suggested_method": None,
            }

        text_lower = text.strip().lower()

        # ── Step 1: Detect Explicit Device Mentions ──────────────────────────
        target_device = None
        device_matched_str = ""
        for pat in self.PHONE_EXPLICIT_PATTERNS:
            m = re.search(pat, text_lower)
            if m:
                target_device = "phone"
                device_matched_str = m.group(0)
                break

        if not target_device:
            for pat in self.PC_EXPLICIT_PATTERNS:
                m = re.search(pat, text_lower)
                if m:
                    target_device = "pc"
                    device_matched_str = m.group(0)
                    break

        # Remove the matched device target phrase so its words don't confuse app lookup
        text_for_apps = text_lower
        if device_matched_str:
            text_for_apps = text_for_apps.replace(device_matched_str, " ")

        # ── Step 2: Detect Target App ────────────────────────────────────────
        app = None

        # Check Cross-platform apps FIRST (youtube, spotify, etc.)
        for app_name in self.CROSS_PLATFORM_APPS:
            if re.search(rf"\b{re.escape(app_name)}\b", text_for_apps):
                app = "youtube" if app_name == "yt" else app_name
                break

        # Check PC exclusives
        if not app:
            for app_name in self.PC_EXCLUSIVE_APPS:
                if re.search(rf"\b{re.escape(app_name)}\b", text_for_apps):
                    app = app_name
                    if target_device is None:
                        target_device = "pc"
                    break

        # Check Phone exclusives (dialer, camera, etc.)
        if not app:
            for app_name in self.PHONE_EXCLUSIVE_APPS:
                if re.search(rf"\b{re.escape(app_name)}\b", text_for_apps):
                    app = app_name
                    if target_device is None:
                        target_device = "phone"
                    break

        # ── Step 3: Classify Action ──────────────────────────────────────────
        action = "general"
        if any(w in text_lower for w in ["play", "bajao", "chalao", "song", "music", "gaana", "sangeet", "track", "listen"]):
            action = "play_media"
        elif any(w in text_lower for w in ["open", "launch", "start", "kholo", "khol do", "run"]):
            action = "open_app"
        elif any(w in text_lower for w in ["close", "kill", "quit", "exit", "band karo", "band kar do"]):
            action = "close_app"
        elif any(w in text_lower for w in ["call", "dial", "ring", "phone call", "message", "whatsapp message", "sms"]):
            action = "communicate"
        elif any(w in text_lower for w in ["unlock", "lock", "volume", "brightness", "wifi", "bluetooth", "silent", "vibrate", "screenshot"]):
            action = "system_control"
        elif any(w in text_lower for w in ["battery", "charge", "notifications", "what's on", "read screen", "status"]):
            action = "query"

        # ── Step 4: Contextual Fallback for Target Device ────────────────────
        # If user didn't specify phone or PC, check inherited context, then World Model
        if target_device is None:
            if inherited_target in ("phone", "pc"):
                target_device = inherited_target
            elif action == "communicate" and app in ("dialer", "phone", "sms", "whatsapp"):
                # Communication actions default to phone companion if connected
                target_device = "phone"
            elif action == "system_control" and any(w in text_lower for w in ["screen unlock", "unlock phone", "lock phone", "battery"]):
                target_device = "phone"
            elif world_model_snapshot:
                # If phone screen is lit up and user is holding phone, bias mobile
                phone_st = world_model_snapshot.get("phone", {})
                if phone_st.get("connected") and phone_st.get("screen_on") and not phone_st.get("is_locked"):
                    target_device = "phone"
                else:
                    target_device = "pc"
            else:
                target_device = "pc"  # default workstation

        # ── Step 5: Clean Query Extraction ───────────────────────────────────
        clean = text_lower
        # Strip conversational prefixes
        clean = re.sub(r"^(?:i\s+want\s+you\s+to|please|can\s+you|alita|mj|hey|hello|just)\s+", "", clean, flags=re.IGNORECASE)
        # Strip explicit device phrases
        for pat in self.PHONE_EXPLICIT_PATTERNS + self.PC_EXPLICIT_PATTERNS:
            clean = re.sub(pat, " ", clean)
        # Strip action tokens, apps, and Hindi particles
        clean = re.sub(
            r"\b(play|music|song|songs|track|video|videos|in|on|the|a|an|app|application|and|then|also|kholo|chalao|bajao|open|launch|start|search|for|find|to|pe|par|pr|me|mein|yt|youtube|spotify)\b",
            " ",
            clean
        )
        if app:
            clean = re.sub(rf"\b{re.escape(app)}\b", " ", clean)
        clean = re.sub(r"\s+", " ", clean).strip()

        # Default query if empty
        if not clean and action == "play_media":
            clean = "top trending songs"

        # ── Step 6: Determine Suggested Execution Method ─────────────────────
        suggested_method = None
        if target_device == "phone":
            if action == "play_media" and app == "youtube":
                suggested_method = "phone_deep_link"
            else:
                suggested_method = "phone_task_planner"
        elif target_device == "pc":
            suggested_method = "pc_automation"

        confidence = 0.95 if (target_device and (app or action != "general")) else 0.70

        return {
            "target_device": target_device,
            "action": action,
            "app": app,
            "query": clean,
            "confidence": confidence,
            "suggested_method": suggested_method,
            "raw_text": text,
        }


# Global singleton
semantic_target_binder = SemanticTargetBinder()
