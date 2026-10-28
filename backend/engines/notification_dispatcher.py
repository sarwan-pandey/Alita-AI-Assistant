"""
notification_dispatcher.py — Real-Time Phone Notification Dispatcher & State Machine

Coordinates:
1. Normalization & Debouncing (handling Android content + summary pairs, e.g. WhatsApp Business).
2. Privacy-preserving event logging (no message body in INFO logs).
3. Real-time desktop WebSocket broadcasting (`phone_notification_alert`).
4. Voice announcement policy via Chatterbox Turbo (non-disruptive, turn-safe).
5. State transitions: RECEIVED -> DEDUPLICATED -> DISPATCHED -> UI_DELIVERED -> VOICE_ELIGIBLE -> ANNOUNCED.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("alita.notification_dispatcher")

# Recognized communication package display names
PACKAGE_DISPLAY_NAMES = {
    "com.whatsapp.w4b": "WhatsApp Business",
    "com.whatsapp": "WhatsApp",
    "org.telegram.messenger": "Telegram",
    "org.thunderdog.challegram": "Telegram",
    "com.instagram.android": "Instagram",
    "com.google.android.apps.messaging": "Messages",
    "com.discord": "Discord",
    "com.google.android.gm": "Gmail",
}


class NotificationDispatcher:
    """
    Manages real-time normalization, debouncing, desktop alert dispatching,
    and voice announcement policy for incoming phone notifications.
    """

    def __init__(self, debounce_window_s: float = 2.5):
        self.debounce_window_s = debounce_window_s
        # dedup_key -> {"event_id": str, "timestamp": float, "canReply": bool, "key": str, "canonical": dict, "announced": bool}
        self._recent_cache: Dict[str, Dict[str, Any]] = {}
        self._desktop_broadcaster: Optional[Callable[[Dict[str, Any]], Any]] = None
        self._audio_broadcaster: Optional[Callable[[bytes, str], Any]] = None
        self._session_ids_provider: Optional[Callable[[], List[str]]] = None
        self._active_call: Optional[Dict[str, Any]] = None
        self._call_announced_ids: set = set()
        self._lock = asyncio.Lock()

    def set_desktop_broadcaster(self, fn: Callable[[Dict[str, Any]], Any]) -> None:
        """Register the desktop WebSocket broadcaster callback."""
        self._desktop_broadcaster = fn

    def set_audio_broadcaster(self, fn: Callable[[bytes, str], Any]) -> None:
        """Register callback for sending tts_audio chunks to desktop sessions."""
        self._audio_broadcaster = fn

    def set_session_provider(self, fn: Callable[[], List[str]]) -> None:
        """Register provider returning list of active session IDs."""
        self._session_ids_provider = fn

    @property
    def active_call(self) -> Optional[Dict[str, Any]]:
        """Returns the current active incoming or ongoing phone call record."""
        return self._active_call

    def _clean_cache(self, now: float) -> None:
        """Prune cache entries older than 45 seconds."""
        cutoff = now - 45.0
        keys_to_remove = [k for k, v in self._recent_cache.items() if v.get("timestamp", 0) < cutoff]
        for k in keys_to_remove:
            self._recent_cache.pop(k, None)

    def normalize(self, raw_msg: Dict[str, Any]) -> Tuple[str, Optional[Dict[str, Any]]]:
        """
        Normalizes and debounces an incoming raw notification from Android.
        Returns:
            (state, canonical_record)
            If the notification is a redundant summary or duplicate callback, returns (state, None).
        """
        pkg = raw_msg.get("package", "").strip()
        title = raw_msg.get("title", "").strip()
        text = raw_msg.get("text", "").strip()
        raw_key = raw_msg.get("key", "")
        can_reply = bool(raw_msg.get("canReply", False))
        now = time.time()

        if not pkg or (not title and not text):
            return ("INVALID_PAYLOAD", None)

        self._clean_cache(now)
        dedup_key = f"{pkg}::{title}::{text}"

        cached = self._recent_cache.get(dedup_key)
        if cached:
            delta = now - cached.get("timestamp", 0)
            if delta < self.debounce_window_s:
                # Same message arrived within debounce window.
                # Check if this new event has quick-reply capability while the cached one did not
                if can_reply and not cached.get("canReply", False):
                    cached["canReply"] = True
                    cached["key"] = raw_key
                    canonical = cached.get("canonical", {})
                    canonical["canReply"] = True
                    canonical["key"] = raw_key
                    canonical["state"] = "UPGRADED_REPLY"
                    logger.info(
                        "Notification [UPGRADED_REPLY] from %s | sender='%s' | key=%s | canReply=True",
                        pkg,
                        title,
                        (raw_key[:35] + "...") if len(raw_key) > 35 else raw_key,
                    )
                    return ("UPGRADED_REPLY", canonical)
                else:
                    # Duplicate message callback or unhelpful summary update
                    logger.info(
                        "Notification [SUPPRESSED_SUMMARY] from %s | sender='%s' | key=%s | canReply=%s",
                        pkg,
                        title,
                        (raw_key[:35] + "...") if len(raw_key) > 35 else raw_key,
                        can_reply,
                    )
                    return ("SUPPRESSED_SUMMARY", None)

        # Fresh new notification
        event_id = f"notif_{int(now * 1000)}_{uuid.uuid4().hex[:6]}"
        app_name = PACKAGE_DISPLAY_NAMES.get(pkg, pkg.split(".")[-1].capitalize())

        canonical = {
            "type": "phone_notification",
            "event_id": event_id,
            "package": pkg,
            "app_name": app_name,
            "title": title,
            "sender": title,
            "text": text,
            "timestamp": raw_msg.get("timestamp") or int(now * 1000),
            "key": raw_key,
            "canReply": can_reply,
            "state": "DEDUPLICATED",
            "announced": False,
        }

        self._recent_cache[dedup_key] = {
            "event_id": event_id,
            "timestamp": now,
            "canReply": can_reply,
            "key": raw_key,
            "canonical": canonical,
            "announced": False,
        }

        logger.info(
            "Notification [DEDUPLICATED] from %s | sender='%s' | key=%s | canReply=%s",
            pkg,
            title,
            (raw_key[:35] + "...") if len(raw_key) > 35 else raw_key,
            can_reply,
        )
        logger.debug("Notification [DEDUPLICATED] preview body: '%s'", text)

        return ("DEDUPLICATED", canonical)

    async def handle_incoming_notification(self, raw_msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Primary entry point called by phone_router when 'phone_notification' arrives.
        Executes normalization, storage update, desktop dispatch, and voice announcement.
        """
        async with self._lock:
            state, canonical = self.normalize(raw_msg)
            if not canonical or state in ("SUPPRESSED_SUMMARY", "INVALID_PAYLOAD"):
                return None

            from engines.phone_orchestrator import phone_orchestrator

            if state == "UPGRADED_REPLY":
                # Update existing item in phone_orchestrator.recent_notifications
                for item in phone_orchestrator.recent_notifications:
                    if item.get("event_id") == canonical.get("event_id"):
                        item["canReply"] = True
                        item["key"] = canonical.get("key", item.get("key"))
                        break
                return canonical

            # Store new canonical notification in phone_orchestrator
            phone_orchestrator.record_notification(canonical)

        # 1. Desktop UI Alert Dispatch
        await self.dispatch_desktop_alert(canonical)

        # 2. Voice Alert Evaluation
        await self.evaluate_and_announce_voice(canonical)

        return canonical

    async def dispatch_desktop_alert(self, canonical: Dict[str, Any]) -> None:
        """Dispatches phone_notification_alert payload to connected desktop WebSockets."""
        canonical["state"] = "DISPATCHED"

        alert_payload = {
            "type": "phone_notification_alert",
            "event_id": canonical["event_id"],
            "package": canonical["package"],
            "app_name": canonical["app_name"],
            "sender": canonical["sender"],
            "text": canonical["text"],
            "timestamp": canonical["timestamp"],
            "canReply": canonical["canReply"],
        }

        if self._desktop_broadcaster:
            try:
                res = self._desktop_broadcaster(alert_payload)
                if asyncio.iscoroutine(res):
                    await res
                canonical["state"] = "UI_DELIVERED"
                logger.info("Notification [UI_DELIVERED] dispatched to desktop client for event %s", canonical["event_id"])
            except Exception as e:
                logger.warning("Failed to dispatch desktop alert: %s", e)
        else:
            logger.debug("Desktop broadcaster not registered; alert queued in state")

    async def evaluate_and_announce_voice(self, canonical: Dict[str, Any]) -> None:
        """
        Evaluates voice alert policy:
        - Only for WhatsApp Business ('com.whatsapp.w4b').
        - Non-disruptive: checks if active turn is in flight; if yes, skips voice.
        - Safe announcement: speaks sender only ('New WhatsApp message from <sender>.'), never message body.
        - Synthesizes via Chatterbox Turbo TTS.
        """
        pkg = canonical.get("package")
        if pkg != "com.whatsapp.w4b":
            return

        if canonical.get("announced", False):
            return

        # Check if an active conversational turn is in flight across active sessions
        turn_in_flight = False
        try:
            from core.turn_controller import turn_controller
            session_ids = self._session_ids_provider() if self._session_ids_provider else []
            for sid in session_ids:
                if turn_controller.is_active_turn_in_flight(sid):
                    turn_in_flight = True
                    break
        except Exception as e:
            logger.debug("Turn controller check notice: %s", e)

        if turn_in_flight:
            canonical["state"] = "DEFERRED_TURN_ACTIVE"
            logger.info("Notification [DEFERRED_TURN_ACTIVE] voice announcement skipped (user turn active)")
            return

        canonical["state"] = "VOICE_ELIGIBLE"

        # Sanitize sender name (remove emojis and unusual punctuation for clear TTS pronunciation)
        raw_sender = canonical.get("sender", "")
        clean_sender = re.sub(r"[^\w\s\.-]", "", raw_sender).strip()
        if not clean_sender:
            clean_sender = "someone"

        announcement_text = f"New WhatsApp message from {clean_sender}."

        try:
            from tts_dispatch import _tts_generate

            # Generate speech audio via existing Chatterbox Turbo engine
            wav_bytes = await _tts_generate(
                announcement_text,
                voice_info={"id": "chatterbox_turbo_mj"},
                language="en",
            )

            if wav_bytes and self._audio_broadcaster:
                res = self._audio_broadcaster(wav_bytes, announcement_text)
                if asyncio.iscoroutine(res):
                    await res

                canonical["announced"] = True
                canonical["state"] = "ANNOUNCED"
                logger.info(
                    "Notification [ANNOUNCED] voice announcement played for event %s (sender: '%s')",
                    canonical["event_id"],
                    clean_sender,
                )
        except Exception as e:
            logger.warning("Voice announcement failed for event %s: %s", canonical.get("event_id"), e)

    # ── Telephony Awareness (Phase 7D) ─────────────────────────────────────────

    async def handle_incoming_call(self, raw_msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processes real-time incoming call event from Android.
        Normalizes caller ID, deduplicates duplicate callbacks, dispatches URGENT desktop alert,
        and triggers single-engine Chatterbox Turbo voice announcement.
        """
        event_id = raw_msg.get("event_id") or f"call_{int(time.time()*1000)}"
        number = str(raw_msg.get("number", "unknown")).strip()
        caller = str(raw_msg.get("caller", "")).strip() or "Unknown"
        is_known = bool(raw_msg.get("is_known_contact", False))
        is_private = bool(raw_msg.get("is_private", False) or number in ("unknown", "-1", "-2", ""))
        state = raw_msg.get("state", "ringing")
        ts = raw_msg.get("timestamp") or (time.time() * 1000)

        # Mask number for display / privacy if known contact or private
        if is_known and len(number) >= 10:
            masked_number = number[:3] + "..." + number[-4:]
        elif is_private:
            masked_number = "Private"
        else:
            masked_number = number

        call_record = {
            "type": "phone_call_alert",
            "event_id": event_id,
            "caller": caller,
            "number": masked_number,
            "full_number": number,
            "is_known_contact": is_known,
            "is_private": is_private,
            "state": state,
            "priority": "URGENT",
            "timestamp": ts,
        }

        async with self._lock:
            already_active = self._active_call is not None and self._active_call.get("event_id") == event_id
            if already_active:
                logger.info("Call [DEDUPLICATED] incoming_call callback received for active call %s", event_id)
                return call_record

            self._active_call = call_record

        # Privacy-safe log: NEVER log unmasked raw phone numbers at INFO level
        logger.info(
            "Telephony [INCOMING_CALL] caller='%s' | known=%s | private=%s | id=%s",
            caller if is_known else "[UNKNOWN/MASKED]",
            is_known,
            is_private,
            event_id,
        )

        # 1. Desktop UI Alert Dispatch
        if self._desktop_broadcaster:
            try:
                res = self._desktop_broadcaster(call_record)
                if asyncio.iscoroutine(res):
                    await res
                logger.info("Telephony [UI_DELIVERED] call alert dispatched to desktop for event %s", event_id)
            except Exception as e:
                logger.warning("Failed to dispatch desktop call alert: %s", e)

        # 2. Voice Announcement Evaluation
        if event_id not in self._call_announced_ids:
            await self._announce_incoming_call(call_record)

        return call_record

    async def _announce_incoming_call(self, call_record: Dict[str, Any]) -> None:
        """
        Voice announcement for incoming call via canonical Chatterbox Turbo TTS engine.
        Respects active conversational turn protection to avoid corrupting speech recognition.
        """
        event_id = call_record.get("event_id")

        # Check turn in flight
        turn_in_flight = False
        try:
            from core.turn_controller import turn_controller
            session_ids = self._session_ids_provider() if self._session_ids_provider else []
            for sid in session_ids:
                if turn_controller.is_active_turn_in_flight(sid):
                    turn_in_flight = True
                    break
        except Exception as e:
            logger.debug("Turn controller check notice in call announcement: %s", e)

        if turn_in_flight:
            logger.info("Telephony [DEFERRED_TURN_ACTIVE] call announcement skipped (user conversational turn active)")
            return

        is_known = call_record.get("is_known_contact", False)
        is_private = call_record.get("is_private", False)
        raw_caller = call_record.get("caller", "")

        if is_known:
            clean_caller = re.sub(r"[^\w\s\.-]", "", raw_caller).strip() or "a contact"
            announcement_text = f"Incoming call from {clean_caller}."
        elif is_private:
            announcement_text = "Incoming call from a private number."
        else:
            announcement_text = "Incoming call from an unknown number."

        try:
            from tts_dispatch import _tts_generate

            wav_bytes = await _tts_generate(
                announcement_text,
                voice_info={"id": "chatterbox_turbo_mj"},
                language="en",
            )

            if wav_bytes and self._audio_broadcaster:
                res = self._audio_broadcaster(wav_bytes, announcement_text)
                if asyncio.iscoroutine(res):
                    await res

                self._call_announced_ids.add(event_id)
                logger.info(
                    "Telephony [ANNOUNCED] voice alert spoke '%s' for event %s",
                    announcement_text,
                    event_id,
                )
        except Exception as e:
            logger.warning("Voice announcement failed for incoming call %s: %s", event_id, e)

    async def handle_call_state_changed(self, raw_msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processes call state transitions: ACTIVE, ENDED.
        Updates internal active call state and broadcasts state update to desktop client.
        """
        event_id = raw_msg.get("event_id", "")
        new_state = raw_msg.get("state", "").lower()
        ts = raw_msg.get("timestamp") or (time.time() * 1000)

        async with self._lock:
            if new_state == "ended":
                self._active_call = None
                if len(self._call_announced_ids) > 20:
                    self._call_announced_ids.clear()
            elif new_state == "active" and self._active_call:
                self._active_call["state"] = "active"

        logger.info("Telephony [STATE_CHANGED] call %s -> %s", event_id, new_state)

        state_payload = {
            "type": "phone_call_dismiss" if new_state == "ended" else "phone_call_state",
            "event_id": event_id,
            "state": new_state,
            "timestamp": ts,
        }

        if self._desktop_broadcaster:
            try:
                res = self._desktop_broadcaster(state_payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.warning("Failed to dispatch desktop call state change: %s", e)

        return state_payload


# Global singleton dispatcher
notification_dispatcher = NotificationDispatcher(debounce_window_s=2.5)
