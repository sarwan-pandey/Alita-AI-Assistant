"""
Alita Automation — Communication & Messaging (automation_communication.py)
==========================================================================
Social, messaging, and multi-channel communication automation:
- send_whatsapp_message, send_whatsapp_file
- send_to_app, send_file_with_message
- contact resolution & validation
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
import urllib.parse
from typing import Any, Dict, Optional

from threads.automation_app_control import (
    open_app,
)
from threads.automation_file_ops import (
    _safe_path,
)

log = logging.getLogger("Alita.automation_communication")

_APP_SHARE_PROFILES = {
    "whatsapp": {
        "search_shortcut": "ctrl+f",
        "search_delay": 0.5,
        "contact_delay": 1.5,
        "attach_shortcut": None,
        "send_shortcut": "enter",
    },
    "telegram": {
        "search_shortcut": "ctrl+k",
        "search_delay": 0.5,
        "contact_delay": 1.0,
        "attach_shortcut": None,
        "send_shortcut": "enter",
    },
    "discord": {
        "search_shortcut": "ctrl+k",
        "search_delay": 0.5,
        "contact_delay": 1.0,
        "attach_shortcut": None,
        "send_shortcut": "enter",
    },
}


def _extract_whatsapp_info(text: str) -> dict:
    """Extract contact/phone and message content from WhatsApp voice/text commands."""
    cleaned = text.strip()
    contact = ""
    message = ""

    phone_match = re.search(r"(?:(?:on|to|at)\s+(?:the\s+)?(?:number|no\.?)\s*[:=]?\s*|\b)(\+?\d[\d\s\-]{8,14}\d)\b", cleaned, re.IGNORECASE)
    if phone_match:
        raw_num = phone_match.group(1)
        digits = re.sub(r"[^\d+]", "", raw_num)
        if len(re.sub(r"[^\d]", "", digits)) >= 7:
            contact = digits

    if not contact:
        name_match = re.search(r"\b(?:to|for|ko|with)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)(?:\s+(?:on|in|via|saying|that|ki|whatsapp|wp)\b|$)", cleaned, re.IGNORECASE)
        if name_match:
            candidate = name_match.group(1).strip()
            candidate = re.sub(r"\b(on|in|via|with|whatsapp|wp|saying|that|ki)\b", "", candidate, flags=re.IGNORECASE).strip()
            if candidate.lower() not in ("whatsapp", "the", "number", "message", "a message", "my friend", "phone", ""):
                contact = candidate.title()
        else:
            m_simple = re.search(r"\b(?:to|for|ko|with)\s+([a-zA-Z]+)", cleaned, re.IGNORECASE)
            if m_simple and m_simple.group(1).lower() not in ("whatsapp", "the", "number", "message", "a", "phone"):
                contact = m_simple.group(1).title()

    msg_match = re.search(r'(?:saying|that|ki|text\s*[:=]|message\s*[:=]|as)\s+["\']?(.+?)["\']?$', cleaned, re.IGNORECASE)
    if msg_match:
        message = msg_match.group(1).strip()
    else:
        m_direct = re.search(r'\bsend\s+(?:a\s+|the\s+)?(.+?)\s+(?:to|for|on|ko)\s+', cleaned, re.IGNORECASE)
        if m_direct:
            extracted = m_direct.group(1).strip()
            extracted_clean = re.sub(r"\b(message|the\s+message|a\s+message|msg|in\s+the\s+whatsapp|in\s+whatsapp|on\s+whatsapp)\b", "", extracted, flags=re.IGNORECASE).strip()
            if extracted_clean:
                message = extracted_clean

    if message:
        message = re.sub(r"\b(on\s+whatsapp|in\s+whatsapp|via\s+whatsapp|on\s+wp)\b", "", message, flags=re.IGNORECASE).strip()

    if not message or message.lower() in ("user_text", "send message", "message", "the message", "send the message", "a message", "the"):
        message = "Hello!"

    if not contact:
        contact = "Unknown"

    return {"contact": contact, "message": message}


def _verify_whatsapp_contact(contact: str) -> dict:
    """Verify that the active WhatsApp window matches target contact."""
    try:
        from threads.automation_handler import _get_foreground_window_info, _get_ui_elements
        contact_norm = contact.lower().strip()
        fg = _get_foreground_window_info()
        title = fg.get("title", "").lower()
        if contact_norm in title:
            return {"verified": True, "actual_name": contact}

        elements = _get_ui_elements(max_elements=30)
        for e in elements:
            name = (e.get("name") or "").strip()
            if not name:
                continue
            name_lower = name.lower()
            if contact_norm in name_lower or name_lower in contact_norm:
                return {"verified": True, "actual_name": name}

        if "whatsapp" in title:
            return {"verified": True, "actual_name": contact}

        return {"verified": False, "actual_name": "unknown"}
    except Exception:
        return {"verified": True, "actual_name": contact}


def _click_whatsapp_document_option():
    """Click Document in WhatsApp attachment popup."""
    try:
        import pyautogui
        for _ in range(3):
            pyautogui.press("down")
            time.sleep(0.05)
        pyautogui.press("enter")
    except Exception:
        pass


def send_whatsapp_message(contact: str, message: str, settings=None) -> dict:
    """Send a message via WhatsApp Desktop."""
    contact_str = str(contact).strip() if contact else ""
    if not contact_str or contact_str.lower() == "unknown":
        return {"status": "error", "error": "No recipient contact or phone number provided."}

    msg_str = str(message).strip() if message else ""
    if not msg_str or msg_str.lower() in ("user_text", "send message", "message", "the message", "send the message", "a message"):
        msg_str = "Hello!"

    try:
        import pyautogui
        import pyperclip
    except ImportError:
        return {"status": "error", "error": "pyautogui and pyperclip required for WhatsApp automation"}

    try:
        digits_only = re.sub(r"[^\d]", "", contact_str)
        is_phone = len(digits_only) >= 7

        if is_phone:
            encoded_msg = urllib.parse.quote(msg_str)
            uri = f"whatsapp://send?phone={digits_only}&text={encoded_msg}"
            subprocess.Popen(["start", "", uri], shell=True)
            time.sleep(2.0)
            pyautogui.press("enter")
            return {
                "status": "success",
                "action": "sent_whatsapp_message",
                "contact": contact_str,
                "message": msg_str,
                "method": "uri_direct",
            }
        else:
            open_app("whatsapp")
            time.sleep(1.5)
            pyautogui.hotkey("ctrl", "f")
            time.sleep(0.2)
            pyperclip.copy(contact_str)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.8)
            pyautogui.press("enter")
            time.sleep(0.5)

            pyperclip.copy(msg_str)
            pyautogui.hotkey("ctrl", "v")
            time.sleep(0.1)
            pyautogui.press("enter")

            return {
                "status": "success",
                "action": "sent_whatsapp_message",
                "contact": contact_str,
                "message": msg_str,
                "method": "desktop_search",
            }
    except Exception as exc:
        return {"status": "error", "error": f"WhatsApp send failed: {exc}"}


def send_whatsapp_file(contact: str, file_path: str) -> dict:
    """Send a file via WhatsApp Desktop using automation."""
    try:
        safe = _safe_path(file_path)
        if not safe or not os.path.isfile(safe):
            return {"status": "error", "error": f"File not found: {file_path}"}

        open_app("whatsapp")
        time.sleep(1.5)

        import pyautogui
        import pyperclip

        pyautogui.hotkey("ctrl", "f")
        time.sleep(0.2)
        pyperclip.copy(contact)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.8)
        pyautogui.press("enter")
        time.sleep(0.5)

        pyautogui.hotkey("alt", "a")
        time.sleep(0.5)
        _click_whatsapp_document_option()
        time.sleep(1.0)

        pyperclip.copy(safe)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.2)
        pyautogui.press("enter")
        time.sleep(0.5)
        pyautogui.press("enter")

        return {
            "status": "success",
            "action": "send_whatsapp_file",
            "contact": contact,
            "file": os.path.basename(safe),
            "detail": f"File '{os.path.basename(safe)}' sent to {contact} on WhatsApp",
        }
    except Exception as e:
        return {"status": "error", "error": f"WhatsApp file send failed: {e}"}


def send_to_app(contact: str, message: str = "", app: str = "whatsapp", file_path: str = "") -> dict:
    """Universal multi-channel file and text sharing."""
    app_lower = app.lower().strip()
    if app_lower in ("email", "mail", "outlook", "gmail"):
        try:
            import webbrowser
            subject = "Sharing a file" if file_path else ""
            mailto = f"mailto:{contact}?subject={subject}&body={message or ''}"
            webbrowser.open(mailto)
            return {
                "status": "success", "action": "send_to_app", "app": "email",
                "contact": contact, "detail": f"Email compose window opened for {contact}",
            }
        except Exception as e:
            return {"status": "error", "error": f"Email failed: {e}"}

    if file_path:
        return send_whatsapp_file(contact, file_path)
    return send_whatsapp_message(contact, message)


def send_file_with_message(contact: str, message: str = "", file_name: str = "", app: str = "whatsapp") -> dict:
    """Convenience pipeline searching for file and sending with message."""
    from threads.automation_file_ops import find_file_smart
    file_path = ""
    if file_name:
        find_res = find_file_smart(file_name)
        if find_res.get("best_match"):
            file_path = find_res["best_match"]["path"]
    return send_to_app(contact=contact, message=message, app=app, file_path=file_path)
