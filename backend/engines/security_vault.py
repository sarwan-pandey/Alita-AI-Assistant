"""
security_vault.py — Sensitive Action Classification & Multi-Turn Confirmation State Tracking

Ensures:
1. Sensitive mobile actions (unlock, messaging, payments, data destruction) trigger security confirmation.
2. Multi-turn confirmation state persists across user turns with a strict 2-minute TTL.
3. Zero plaintext credentials are ever stored, transmitted, logged, or injected into LLM context.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("alita.security_vault")

# Sensitive action categories & pattern definitions
SENSITIVE_PATTERNS = {
    "unlock": [
        r"\bunlock\b.*?\b(phone|screen|device|mobile)\b",
        r"\b(phone|mobile|screen)\b.*?\bunlock\b",
        r"^(unlock|unlock phone|phone unlock)$",
    ],
    "send_message": [
        r"\b(send|text|message)\b.*?\b(whatsapp|telegram|sms|instagram)\b",
        r"\b(whatsapp|telegram)\b.*?\b(send|message)\b",
        r"\bmessage\s+[a-zA-Z0-9_\s]+\s+that\b",
    ],
    "payment": [
        r"\b(pay|transfer|send money|payment|gpay|phonepe|paytm|upi)\b",
        r"\b(send|pay|transfer)\s+(?:rs\.?|inr|rupees?|\d+|one|two|three|four|five|six|seven|eight|nine|ten|twenty|fifty|hundred|thousand)\b",
        r"\b(send|pay|transfer)\s+.+\s+(?:rupees?|rs\.?|paise|bucks)\b",
        r"\b(rupees?|rs\.?|paise)\b.*?\b(bhejo|send|transfer|pay)\b",
        r"\b(bhejo|transfer|pay|send)\b.*?\b(rupees?|rs\.?|paise)\b",
    ],
    "destructive": [
        r"\b(delete|uninstall|wipe|factory reset|clear storage)\b",
    ],
}

AFFIRMATIVE_RESPONSES = {
    "yes", "yeah", "yep", "sure", "proceed", "confirm", "do it",
    "go ahead", "unlock it", "send it", "please do", "ok", "okay",
    "haan", "kardo", "ha", "sahi hai", "bilkul", "approve"
}

NEGATIVE_RESPONSES = {
    "no", "nope", "cancel", "stop", "don't", "abort", "never mind",
    "mat karo", "nahi", "ruk jao", "rehne do", "deny"
}


@dataclass
class SensitiveActionResult:
    is_sensitive: bool
    needs_confirmation: bool
    action_type: str = "none"
    confirmation_prompt: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)


class SecurityVault:
    """
    Manages sensitive action policy enforcement and multi-turn confirmation state.
    """

    CONFIRMATION_TTL_SECONDS = 120.0  # 2 minutes TTL

    def classify_sensitive_action(self, instruction: str) -> Tuple[bool, str]:
        """Check if instruction targets a sensitive mobile operation."""
        inst_lower = instruction.lower().strip()
        for action_type, patterns in SENSITIVE_PATTERNS.items():
            for pat in patterns:
                if re.search(pat, inst_lower):
                    return True, action_type
        return False, "none"

    def check_sensitive_action_intent(
        self,
        instruction: str,
        session_state: Dict[str, Any],
        device_model: str = "Android Device",
    ) -> SensitiveActionResult:
        """
        Evaluate instruction against sensitive action policies and pending confirmations.
        Returns SensitiveActionResult indicating whether to proceed or wait for user confirmation.
        """
        inst_clean = instruction.strip().lower()
        pending = session_state.get("pending_confirmation")
        now = time.time()

        # 1. Check if user is responding to an active pending confirmation
        if pending and isinstance(pending, dict):
            created_at = pending.get("created_at", 0.0)
            if now - created_at <= self.CONFIRMATION_TTL_SECONDS:
                # Active pending confirmation found
                # 1. Check for cancellation / negative refusal FIRST (takes absolute precedence)
                is_negative = any(
                    w == inst_clean or inst_clean.startswith(w + " ") or inst_clean.endswith(" " + w) or f" {w} " in f" {inst_clean} "
                    for w in NEGATIVE_RESPONSES
                )
                if not is_negative and re.search(r"\b(don'?t|do\s+not|never|not|mat\s+karo|mat|nahi|ruk|stop|cancel|abort)\b", inst_clean):
                    is_negative = True

                if is_negative:
                    action_type = pending.get("action_type", "unknown")
                    session_state["pending_confirmation"] = None
                    logger.info(f"User cancelled sensitive action '{action_type}' with refusal: '{inst_clean}'")
                    return SensitiveActionResult(
                        is_sensitive=True,
                        needs_confirmation=False,
                        action_type="cancelled",
                        details={"cancelled": True},
                    )

                # 2. Check for affirmative answer OR repeating the action (only if no negative tokens)
                is_affirmative = (
                    any(w == inst_clean or inst_clean.startswith(w + " ") or inst_clean.endswith(" " + w) or f" {w} " in f" {inst_clean} " for w in AFFIRMATIVE_RESPONSES)
                    or inst_clean == pending.get("instruction", "").strip().lower()
                    or (pending.get("action_type") == "unlock" and any(u in inst_clean for u in ["unlock", "open phone", "open screen", "kholo", "please"]))
                )
                if is_affirmative:
                    action_type = pending.get("action_type", "unknown")
                    orig_instruction = pending.get("instruction", "")
                    # Clear pending confirmation
                    session_state["pending_confirmation"] = None
                    logger.info(f"User confirmed sensitive action '{action_type}' for: '{orig_instruction}'")
                    return SensitiveActionResult(
                        is_sensitive=True,
                        needs_confirmation=False,
                        action_type=action_type,
                        details={"confirmed": True, "original_instruction": orig_instruction},
                    )
            else:
                # Expired
                logger.debug("Pending confirmation expired (> 120s TTL)")
                session_state["pending_confirmation"] = None

        # 2. Check if new instruction is sensitive
        is_sens, action_type = self.classify_sensitive_action(instruction)
        if not is_sens:
            return SensitiveActionResult(is_sensitive=False, needs_confirmation=False)

        # 3. Formulate confirmation prompt according to action type
        payment_detail = ""
        if action_type == "payment":
            clean_inst = re.sub(r'^(?:i\s+want\s+you\s+to|please|can\s+you|mj|alita|hey|hello)\s+', '', instruction.strip(), flags=re.IGNORECASE)
            amt_match = re.search(r"(?:rs\.?|inr|rupees?|₹)\s*(\d+(?:\.\d+)?)|(\d+(?:\.\d+)?)\s*(?:rs\.?|inr|rupees?|₹|bucks)|(?:send|pay|transfer)\s+(\w+)\s+(?:rupees?|rs\.?)", clean_inst, re.IGNORECASE)
            to_match = re.search(r"\bto\s+([a-zA-Z0-9_\s]+?)(?:\s+(?:on|in|via|through|using)\s+(?:gpay|phonepe|paytm|upi)|$)", clean_inst, re.IGNORECASE)
            if not to_match:
                to_match = re.search(r"^([a-zA-Z0-9_\s]+?)\s+ko\b", clean_inst, re.IGNORECASE)
            if amt_match and to_match:
                raw_amt = (amt_match.group(1) or amt_match.group(2) or amt_match.group(3) or "").strip()
                raw_to = to_match.group(1).strip().title()
                if raw_amt and raw_to:
                    payment_detail = f" to send {raw_amt} to {raw_to}"

        prompts = {
            "unlock": f"Are you sure you want me to unlock your {device_model}?",
            "send_message": f"Please confirm: Do you want me to send this message on your {device_model}?",
            "payment": f"Caution: Payment command detected on {device_model}{payment_detail}. Do you authorize proceeding?",
            "destructive": f"Warning: Destructive action detected on {device_model}. Are you sure you want to proceed?",
        }
        prompt = prompts.get(action_type, f"Please confirm: Do you want to execute this action on your {device_model}?")

        # Save pending confirmation in session_state
        session_state["pending_confirmation"] = {
            "action_type": action_type,
            "instruction": instruction,
            "created_at": now,
        }

        return SensitiveActionResult(
            is_sensitive=True,
            needs_confirmation=True,
            action_type=action_type,
            confirmation_prompt=prompt,
            details={"pending": True},
        )

    def clear_confirmation(self, session_state: Dict[str, Any]) -> None:
        """Clear any pending confirmation in session state."""
        session_state["pending_confirmation"] = None


# Singleton instance
security_vault = SecurityVault()
