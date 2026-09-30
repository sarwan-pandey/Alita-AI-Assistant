"""
Lie Detector — Sub-Millisecond Ground-Truth Semantic Comparator
==============================================================
Compares user verbal/text claims against the continuous physical ground truth
of both Android phone and Windows PC. Formulates dynamic girlfriend call-out
directives when discrepancies are caught and rewards genuine honesty.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

try:
    from engines.reality_tracker import (
        reality_tracker,
        CATEGORY_DISTRACTION,
        CATEGORY_PRODUCTIVE,
        CATEGORY_COMMUNICATION,
        CATEGORY_SYSTEM_IDLE,
    )
    from engines.relationship_manager import relationship_manager
    from engines.ambient_awareness import ambient_awareness
except ImportError:
    from backend.engines.reality_tracker import (
        reality_tracker,
        CATEGORY_DISTRACTION,
        CATEGORY_PRODUCTIVE,
        CATEGORY_COMMUNICATION,
        CATEGORY_SYSTEM_IDLE,
    )
    from backend.engines.relationship_manager import relationship_manager
    from backend.engines.ambient_awareness import ambient_awareness

log = logging.getLogger("alita.lie_detector")

# ─────────────────────────────────────────────────────────────────────────────
# CLAIM PATTERN MATRICES (English + Hindi / Hinglish)
# ─────────────────────────────────────────────────────────────────────────────

CLAIM_PATTERNS: Dict[str, List[re.Pattern]] = {
    "study": [
        re.compile(r"\b(i['’]?m|i\s+am|currently)\s+(studying|doing\s+homework|preparing\s+for|reading|revising|learning)\b", re.I),
        re.compile(r"\b(padh\s*raha|padhai\s*kar\s*(?:raha|rahi|rhe|rahe|hu)|revision\s*kar\s*(?:raha|rahi|rhe|rahe|hu)|exam\s*ki\s*taiyari\s*kar)\b", re.I),
        re.compile(r"\b(focused\s+on\s+studies|watching\s+lecture|doing\s+my\s+course)\b", re.I),
        re.compile(r"\b(studying\s+hard|study\s+kar\s+raha)\b", re.I),
    ],
    "sleep": [
        re.compile(r"\b(i['’]?m|i\s+am|going\s+to)\s+(sleep|bed|sleeping|asleep|sleepy)\b", re.I),
        re.compile(r"\b(so\s*raha\s*hu|sone\s*ja\s*raha|neend\s*aa\s*rahi)\b", re.I),
        re.compile(r"\b(good\s*night\s*(?:mj|alita)|lights\s*out)\b", re.I),
    ],
    "work": [
        re.compile(r"\b(i['’]?m|i\s+am)\s+(working|coding|programming|debugging|fixing\s+a\s+bug|in\s+a\s+meeting)\b", re.I),
        re.compile(r"\b(kaam\s*kar\s*raha|office\s*ka\s*kaam|code\s*likh\s*raha)\b", re.I),
        re.compile(r"\b(busy\s+with\s+work|super\s+busy\s+right\s+now)\b", re.I),
    ],
    "phone_away": [
        re.compile(r"\b(not|haven['’]?t\s+been|haven['’]?t)\s+(touching|touched|using|used|checking|checked)\s+(my\s+)?phone\b", re.I),
        re.compile(r"\bphone\s+(side\s*me|door\s*hai|nahi\s*chala\s*raha|rakha\s*hai)\b", re.I),
        re.compile(r"\b(phone\s+is\s+away|haven['’]?t\s+looked\s+at\s+my\s+phone)\b", re.I),
    ],
    "quick_break": [
        re.compile(r"\b(just|only)\s+(for\s+)?(a\s+sec|one\s+min|2\s+min|5\s+min|a\s+quick\s+break)\b", re.I),
        re.compile(r"\b(bas\s+2\s*minute|chhota\s*sa\s*break|ek\s*second)\b", re.I),
        re.compile(r"\b(just\s+checking\s+one\s+thing|quick\s+notification)\b", re.I),
    ],
    # ── NEW CLAIM TYPES ──────────────────────────────────────────────────────
    "exercise": [
        re.compile(r"\b(i['\u2019]?m|i\s+am)\s+(working\s+out|exercising|at\s+the\s+gym|doing\s+pushups|running|jogging)\b", re.I),
        re.compile(r"\b(gym\s*ja\s*raha|workout\s*kar\s*raha|exercise\s*kar\s*raha|daud\s*raha)\b", re.I),
        re.compile(r"\b(hitting\s+the\s+gym|at\s+gym|gym\s+session)\b", re.I),
    ],
    "not_chatting": [
        re.compile(r"\b(i['\u2019]?m\s+not|not)\s+(chatting|texting|messaging|talking\s+to\s+anyone)\b", re.I),
        re.compile(r"\b(kisi\s*se\s*baat\s*nahi|chat\s*nahi\s*kar\s*raha|message\s*nahi\s*kar\s*raha)\b", re.I),
        re.compile(r"\b(no\s+one\s+texted|not\s+chatting\s+with\s+anyone)\b", re.I),
    ],
    "just_one_msg": [
        re.compile(r"\b(just|only)\s+(checking|checked|replying\s+to|replied\s+to)\s+(one|1|a)\s+(message|msg|text|notification)\b", re.I),
        re.compile(r"\b(bas\s+ek\s+message|sirf\s+ek\s+reply|ek\s+notification\s+dekh\s*raha)\b", re.I),
        re.compile(r"\b(just\s+one\s+quick\s+reply|only\s+replied\s+once)\b", re.I),
    ],
    "eating": [
        re.compile(r"\b(i['\u2019]?m|i\s+am)\s+(eating|having\s+(lunch|dinner|breakfast|food|snack))\b", re.I),
        re.compile(r"\b(khana\s*kha\s*raha|lunch\s*kar\s*raha|dinner\s*kar\s*raha|breakfast\s*kar\s*raha)\b", re.I),
        re.compile(r"\b(at\s+lunch|eating\s+right\s+now|having\s+my\s+meal)\b", re.I),
    ],
    "no_games": [
        re.compile(r"\b(i\s+haven['\u2019]?t|didn['\u2019]?t|not)\s+(played|play|playing)\s+(any\s+)?(game|games)\b", re.I),
        re.compile(r"\b(game\s*nahi\s*khel[a]?|gaming\s*nahi\s*ki|koi\s*game\s*nahi)\b", re.I),
        re.compile(r"\b(no\s+gaming\s+today|haven['\u2019]?t\s+gamed)\b", re.I),
    ],
}


class LieDetector:
    """
    Evaluates conversational utterances against real-time device ground truth.
    Executes in < 1.0 ms with zero external network overhead.
    """

    def evaluate_user_utterance(self, user_text: str) -> Dict[str, Any]:
        """
        Main entry point invoked during prompt assembly.
        Returns evaluation dict containing detected contradictions or truth confirmations.
        """
        text = (user_text or "").strip()
        if not text or len(text) < 4:
            return {"detected": False}

        claim_type = self._extract_claim(text)
        if not claim_type:
            return {"detected": False}

        # Snapshot ground truth
        reality = reality_tracker.get_live_reality()
        phone = reality.get("phone", {})
        pc = reality.get("pc", {})

        # Evaluate against claim
        if claim_type == "study":
            return self._evaluate_study_claim(text, phone, pc)
        elif claim_type == "sleep":
            return self._evaluate_sleep_claim(text, phone, pc)
        elif claim_type == "work":
            return self._evaluate_work_claim(text, phone, pc)
        elif claim_type == "phone_away":
            return self._evaluate_phone_away_claim(text, phone, pc)
        elif claim_type == "quick_break":
            return self._evaluate_quick_break_claim(text, phone, pc)
        elif claim_type == "exercise":
            return self._evaluate_exercise_claim(text, phone, pc)
        elif claim_type == "not_chatting":
            return self._evaluate_not_chatting_claim(text, phone, pc)
        elif claim_type == "just_one_msg":
            return self._evaluate_just_one_msg_claim(text, phone, pc)
        elif claim_type == "eating":
            return self._evaluate_eating_claim(text, phone, pc)
        elif claim_type == "no_games":
            return self._evaluate_no_games_claim(text, phone, pc)

        return {"detected": False}

    def _extract_claim(self, text: str) -> Optional[str]:
        # 1. Punctuation & Interrogative filtering
        if text.strip().endswith("?"):
            return None

        # 2. English question & advice request pre-filtering
        if re.search(r"\b(how|why|what|when|where|who|should\s+i|can\s+i|could\s+i|would\s+i|is\s+it\s+time\s+to|help\s+me|tips\s+for)\b", text, re.I):
            return None

        # 3. Hindi/Hinglish question, advice, or conditional request
        if re.search(r"\b(kaise|kare|karu|kya\s+mai|kya\s+kare|kya\s+karu|sahi\s+hai\s+kya|kya\s+tum|batao|suggest)\b", text, re.I):
            return None

        # 4. Inability to sleep / complaints (not a claim of sleeping)
        if re.search(r"\b(neend\s*na?hi\s*aa\s*rahi|so\s*na?hi\s*pa\s*raha|can'?t\s+sleep|unable\s+to\s+sleep|trouble\s+sleeping)\b", text, re.I):
            return None

        # 5. Modal intention expressions (future/intention rather than active factual claim)
        if re.search(r"\b(want\s+to|planning\s+to|about\s+to|need\s+to|thinking\s+of|going\s+to\s+start)\s+(study|work|code)\b", text, re.I):
            return None

        # 6. Bug 3 Fix: Check for explicit negation before extracting any claim
        if re.search(r"\b(not|never|nhi|nahi|didn't|don't|wasn't|was\s+not)\s+(studying|doing\s+homework|learning|working|coding|sleeping|touching)\b", text, re.I):
            return None
        if re.search(r"\b(was\s+studying|studied\s+earlier|was\s+working|worked\s+earlier)\b", text, re.I):
            return None

        for claim_type, patterns in CLAIM_PATTERNS.items():
            for pat in patterns:
                if pat.search(text):
                    return claim_type
        return None

    # ─────────────────────────────────────────────────────────────────────────
    # CLAIM EVALUATORS
    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_study_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        phone_cat = phone.get("category")
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")
        phone_sec = phone.get("duration_seconds", 0)
        phone_screen = phone.get("screen_on", False)

        pc_cat = pc.get("category")
        pc_name = pc.get("name", "")
        pc_title = pc.get("title", "")
        pc_dur = pc.get("duration_formatted", "")

        # Bug 6 Fix: Check both distraction and communication (WhatsApp, Telegram)
        if phone_screen and phone_cat in (CATEGORY_DISTRACTION, CATEGORY_COMMUNICATION):
            is_chat = (phone_cat == CATEGORY_COMMUNICATION)
            evidence = f"Phone is ON with {phone_app} active for {phone_dur}."
            if pc_cat in (CATEGORY_DISTRACTION, CATEGORY_COMMUNICATION):
                evidence += f" PC is also running {pc_name} ('{pc_title}')."

            rel = relationship_manager.record_lie("study", evidence)
            hint = "Playfully tease him about who he's chatting with on WhatsApp instead of studying!" if is_chat else ""
            directive = self._build_girlfriend_lie_directive(
                claim="studying / studying hard",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=phone_dur,
                relationship=rel,
                context_hint=hint,
            )
            return {
                "detected": True,
                "is_lie": True,
                "confidence": 0.96,
                "claim": "study",
                "evidence": evidence,
                "prompt_directive": directive,
            }

        # Contradiction: PC is on distraction (YouTube, Steam, Game) while phone is idle
        if pc_cat == CATEGORY_DISTRACTION:
            evidence = f"PC active window is {pc_name} ('{pc_title}') for {pc_dur}."
            rel = relationship_manager.record_lie("study", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="studying",
                user_text=text,
                evidence=evidence,
                actual_app=pc_name,
                duration=pc_dur,
                relationship=rel,
            )
            return {
                "detected": True,
                "is_lie": True,
                "confidence": 0.94,
                "claim": "study",
                "evidence": evidence,
                "prompt_directive": directive,
            }

        # Verified Truth: Phone is screen off / locked AND PC is in productive IDE / document
        if (not phone_screen or phone_cat == CATEGORY_PRODUCTIVE) and (pc_cat == CATEGORY_PRODUCTIVE or phone_cat == CATEGORY_PRODUCTIVE):
            evidence = f"PC is active on {pc_name} ('{pc_title}') and phone is locked/off."
            rel = relationship_manager.record_truth("study", evidence)
            directive = self._build_girlfriend_truth_directive(
                claim="studying",
                evidence=evidence,
                relationship=rel,
            )
            return {
                "detected": True,
                "is_lie": False,
                "confidence": 0.95,
                "claim": "study",
                "evidence": evidence,
                "prompt_directive": directive,
            }

        return {"detected": False}

    def _evaluate_sleep_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        phone_screen = phone.get("screen_on", False)
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")
        phone_sec = phone.get("duration_seconds", 0)
        phone_cat = phone.get("category", "")

        # Bug 4 Fix: If user says "good night" or "going to sleep" right now, their screen is naturally
        # on because they just spoke. Only accuse if they have been actively in distraction for > 4 mins.
        if phone_screen:
            if phone_cat in (CATEGORY_DISTRACTION, CATEGORY_COMMUNICATION) and phone_sec > 240:
                evidence = f"Phone screen is still ON with {phone_app} active for {phone_dur}."
                rel = relationship_manager.record_lie("sleep", evidence)
                directive = self._build_girlfriend_lie_directive(
                    claim="going to sleep / sleeping",
                    user_text=text,
                    evidence=evidence,
                    actual_app=phone_app,
                    duration=phone_dur,
                    relationship=rel,
                    context_hint="Caught staying up late scrolling on the phone instead of sleeping!",
                )
                return {
                    "detected": True,
                    "is_lie": True,
                    "confidence": 0.96,
                    "claim": "sleep",
                    "evidence": evidence,
                    "prompt_directive": directive,
                }
            else:
                # Soft bedtime response: affectionate goodnight with reminder to put phone down
                rel = relationship_manager.state
                return {
                    "detected": True,
                    "is_lie": False,
                    "confidence": 0.90,
                    "claim": "sleep",
                    "evidence": "Bedtime intention voiced while screen is awake.",
                    "prompt_directive": (
                        "[REALITY CHECK: BEDTIME / GOODNIGHT INTENTION]\n"
                        "He just told you good night / going to sleep. Wish him sweet dreams lovingly like a girlfriend, "
                        "and playfully remind him to turn that phone screen off and put it away right now!"
                    ),
                }

        # Truth confirmed: Phone is locked/screen off
        if not phone_screen:
            evidence = "Phone screen is OFF and locked."
            rel = relationship_manager.record_truth("sleep", evidence)
            return {
                "detected": True,
                "is_lie": False,
                "confidence": 0.95,
                "claim": "sleep",
                "evidence": evidence,
                "prompt_directive": (
                    "[REALITY CHECK: TRUTH CONFIRMED - SLEEPING]\n"
                    "Phone screen is off and locked. Wish him a sweet, loving good night like a caring girlfriend!"
                ),
            }

        return {"detected": False}

    def _evaluate_work_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        phone_cat = phone.get("category")
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")
        phone_screen = phone.get("screen_on", False)
        pc_cat = pc.get("category")
        pc_name = pc.get("name", "")
        pc_title = pc.get("title", "")

        # Bug 6 Fix: Check both distraction and communication (WhatsApp, Telegram)
        if phone_screen and phone_cat in (CATEGORY_DISTRACTION, CATEGORY_COMMUNICATION):
            is_chat = (phone_cat == CATEGORY_COMMUNICATION)
            evidence = f"Phone is open on {phone_app} ({phone_dur}) instead of working."
            rel = relationship_manager.record_lie("work", evidence)
            hint = "Playfully tease him about who is stealing his focus on WhatsApp during work hours!" if is_chat else ""
            directive = self._build_girlfriend_lie_directive(
                claim="working / busy",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=phone_dur,
                relationship=rel,
                context_hint=hint,
            )
            return {
                "detected": True,
                "is_lie": True,
                "confidence": 0.95,
                "claim": "work",
                "evidence": evidence,
                "prompt_directive": directive,
            }

        # Contradiction: PC is on distraction (YouTube, Steam, Game)
        if pc_cat == CATEGORY_DISTRACTION:
            pc_dur = pc.get("duration_formatted", "")
            evidence = f"PC active window is {pc_name} ('{pc_title}') for {pc_dur}."
            rel = relationship_manager.record_lie("work", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="working / coding",
                user_text=text,
                evidence=evidence,
                actual_app=pc_name,
                duration=pc_dur,
                relationship=rel,
                context_hint="Caught gaming or watching entertainment on PC instead of working!",
            )
            return {
                "detected": True,
                "is_lie": True,
                "confidence": 0.95,
                "claim": "work",
                "evidence": evidence,
                "prompt_directive": directive,
            }

        if pc_cat == CATEGORY_PRODUCTIVE or (phone_screen and phone_cat == CATEGORY_PRODUCTIVE):
            evidence = f"PC active in {pc_name} ('{pc_title}')."
            rel = relationship_manager.record_truth("work", evidence)
            directive = self._build_girlfriend_truth_directive(
                claim="working",
                evidence=evidence,
                relationship=rel,
            )
            return {
                "detected": True,
                "is_lie": False,
                "confidence": 0.95,
                "claim": "work",
                "evidence": evidence,
                "prompt_directive": directive,
            }

        return {"detected": False}

    def _evaluate_phone_away_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        phone_screen = phone.get("screen_on", False)
        phone_app = phone.get("name", "")
        phone_sec = phone.get("duration_seconds", 0)

        # Contradiction: Screen is actually ON right now with an app
        if phone_screen:
            evidence = f"Phone screen is currently ON with {phone_app} active for {phone_sec}s."
            rel = relationship_manager.record_lie("phone_away", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="not touching / phone away",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=f"{phone_sec}s",
                relationship=rel,
                context_hint="Caught holding his phone with the screen lit up while claiming he's not touching it!",
            )
            return {
                "detected": True,
                "is_lie": True,
                "confidence": 0.97,
                "claim": "phone_away",
                "evidence": evidence,
                "prompt_directive": directive,
            }
        else:
            # Verified Truth: Phone screen is genuinely OFF and locked
            evidence = "Phone screen is OFF and locked."
            rel = relationship_manager.record_truth("phone_away", evidence)
            directive = self._build_girlfriend_truth_directive(
                claim="phone is put away",
                evidence=evidence,
                relationship=rel,
            )
            return {
                "detected": True,
                "is_lie": False,
                "confidence": 0.95,
                "claim": "phone_away",
                "evidence": evidence,
                "prompt_directive": directive,
            }

    def _evaluate_quick_break_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        phone_cat = phone.get("category")
        phone_sec = phone.get("duration_seconds", 0)
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")

        # If user claims "just 2 mins" but has been on Instagram/YouTube for > 8 mins (480s)
        if phone_cat == CATEGORY_DISTRACTION and phone_sec > 480:
            evidence = f"Claimed a quick 2-minute break, but has been in {phone_app} for {phone_dur}."
            rel = relationship_manager.record_lie("quick_break", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="just a 2-minute quick break",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=phone_dur,
                relationship=rel,
                context_hint="Call him out on his 'quick 2 minute' break that turned into half an hour!",
            )
            return {
                "detected": True,
                "is_lie": True,
                "confidence": 0.96,
                "claim": "quick_break",
                "evidence": evidence,
                "prompt_directive": directive,
            }
        return {"detected": False}

    # ─────────────────────────────────────────────────────────────────────────
    # NEW CLAIM EVALUATORS
    # ─────────────────────────────────────────────────────────────────────────

    def _evaluate_exercise_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        """Claims 'working out' / 'at gym' — phone should be idle or playing music, not social media."""
        phone_screen = phone.get("screen_on", False)
        phone_cat = phone.get("category", "")
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")

        if phone_screen and phone_cat in (CATEGORY_DISTRACTION, CATEGORY_COMMUNICATION):
            evidence = f"Claims to be exercising but phone is ON with {phone_app} active for {phone_dur}."
            rel = relationship_manager.record_lie("exercise", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="working out / at the gym",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=phone_dur,
                relationship=rel,
                context_hint="Gym? Really? Then why is the phone screen lit up with social media? 😏",
            )
            return {"detected": True, "is_lie": True, "confidence": 0.90, "claim": "exercise",
                    "evidence": evidence, "prompt_directive": directive}

        # If phone is off or on music — plausible truth
        if not phone_screen or phone_cat not in (CATEGORY_DISTRACTION, CATEGORY_COMMUNICATION):
            return {"detected": True, "is_lie": False, "confidence": 0.75, "claim": "exercise",
                    "evidence": "Phone idle/music — exercise claim plausible.",
                    "prompt_directive": "[REALITY CHECK: EXERCISE PLAUSIBLE]\nEncourage him warmly! 'Proud of you for working out!'"}

        return {"detected": False}

    def _evaluate_not_chatting_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        """Claims 'not chatting' — check if WhatsApp/Telegram/Messages is active."""
        phone_cat = phone.get("category", "")
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")
        phone_screen = phone.get("screen_on", False)

        if phone_screen and phone_cat == CATEGORY_COMMUNICATION:
            evidence = f"Claims not chatting, but {phone_app} has been active for {phone_dur}."
            rel = relationship_manager.record_lie("not_chatting", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="not chatting with anyone",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=phone_dur,
                relationship=rel,
                context_hint="Who are you talking to, huh? Don't lie to me! Show me the screen! 😤",
            )
            return {"detected": True, "is_lie": True, "confidence": 0.95, "claim": "not_chatting",
                    "evidence": evidence, "prompt_directive": directive}

        return {"detected": False}

    def _evaluate_just_one_msg_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        """Claims 'just checking one message' — check if chat app has been open >5 min."""
        phone_cat = phone.get("category", "")
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")
        phone_sec = phone.get("duration_seconds", 0)

        # >5 minutes on a chat app ≠ "just one message"
        if phone_cat == CATEGORY_COMMUNICATION and phone_sec > 300:
            evidence = f"Claims 'just one message' but has been in {phone_app} for {phone_dur}."
            rel = relationship_manager.record_lie("just_one_msg", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="just checking one message",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=phone_dur,
                relationship=rel,
                context_hint=f"'One message' that turned into {phone_dur} of chatting! Classic. 😏",
            )
            return {"detected": True, "is_lie": True, "confidence": 0.94, "claim": "just_one_msg",
                    "evidence": evidence, "prompt_directive": directive}

        return {"detected": False}

    def _evaluate_eating_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        """Claims 'eating' — phone should ideally be idle, not on social media."""
        phone_screen = phone.get("screen_on", False)
        phone_cat = phone.get("category", "")
        phone_app = phone.get("name", "")
        phone_dur = phone.get("duration_formatted", "")
        phone_sec = phone.get("duration_seconds", 0)

        # Scrolling social media while claiming to eat = busted
        if phone_screen and phone_cat == CATEGORY_DISTRACTION and phone_sec > 180:
            evidence = f"Claims to be eating but has been scrolling {phone_app} for {phone_dur}."
            rel = relationship_manager.record_lie("eating", evidence)
            directive = self._build_girlfriend_lie_directive(
                claim="eating / having a meal",
                user_text=text,
                evidence=evidence,
                actual_app=phone_app,
                duration=phone_dur,
                relationship=rel,
                context_hint="Eating? With both hands on your phone scrolling reels? Sure. 🙄",
            )
            return {"detected": True, "is_lie": True, "confidence": 0.85, "claim": "eating",
                    "evidence": evidence, "prompt_directive": directive}

        # Plausible — phone idle or brief use
        return {"detected": False}

    def _evaluate_no_games_claim(self, text: str, phone: Dict[str, Any], pc: Dict[str, Any]) -> Dict[str, Any]:
        """Claims 'haven't played games' — check ambient_awareness daily usage for gaming apps."""
        try:
            stats = ambient_awareness.get_daily_usage_stats()
            app_usage = stats.get("by_app_raw", {})

            # Check for known gaming apps in daily usage
            gaming_keywords = ("game", "pubg", "bgmi", "freefire", "valorant", "minecraft",
                               "genshin", "steam", "roblox", "clash", "fortnite", "cod")
            gaming_time = 0
            gaming_app = ""
            for app_name, secs in app_usage.items():
                if any(kw in app_name.lower() for kw in gaming_keywords):
                    gaming_time += secs
                    if secs > 0:
                        gaming_app = app_name

            if gaming_time > 120:  # >2 minutes of gaming today
                dur_str = ambient_awareness._format_seconds(gaming_time)
                evidence = f"Claims no gaming, but {gaming_app} shows {dur_str} of usage today."
                rel = relationship_manager.record_lie("no_games", evidence)
                directive = self._build_girlfriend_lie_directive(
                    claim="haven't played any games",
                    user_text=text,
                    evidence=evidence,
                    actual_app=gaming_app,
                    duration=dur_str,
                    relationship=rel,
                    context_hint=f"No games? Then what was that {dur_str} you spent on {gaming_app}? 🎮",
                )
                return {"detected": True, "is_lie": True, "confidence": 0.93, "claim": "no_games",
                        "evidence": evidence, "prompt_directive": directive}
        except Exception as exc:
            log.debug(f"Gaming usage check error: {exc}")

        return {"detected": False}

    # ─────────────────────────────────────────────────────────────────────────
    # PROACTIVE CONTRADICTION DETECTION (no user claim needed)
    # ─────────────────────────────────────────────────────────────────────────

    def check_proactive_contradictions(self) -> Optional[Dict[str, Any]]:
        """
        Checks for contradictions against active promises WITHOUT the user making a claim.
        Called by the proactive_agent sentinel loop.

        Returns a contradiction dict if found, or None.
        """
        try:
            promises = relationship_manager.state.get("active_promises", {})
            reality = reality_tracker.get_live_reality()
            phone = reality.get("phone", {})
            pc = reality.get("pc", {})

            for key, prom in promises.items():
                if prom.get("status") != "active":
                    continue

                desc = (prom.get("description", "") or "").lower()

                # Promise to study → currently on distraction
                if any(w in desc for w in ("study", "padhai", "revise", "homework", "lecture")):
                    phone_cat = phone.get("category", "")
                    pc_cat = pc.get("category", "")
                    phone_sec = phone.get("duration_seconds", 0)

                    if phone_cat == CATEGORY_DISTRACTION and phone_sec > 600:
                        app = phone.get("name", "Unknown")
                        dur = phone.get("duration_formatted", "")
                        return {
                            "type": "promise_violation",
                            "promise": prom["description"],
                            "evidence": f"Promised to study but has been on {app} for {dur}",
                            "nudge": f"You said you'd study... but you've been on {app} for {dur}. 🤨",
                        }

                    if pc_cat == CATEGORY_DISTRACTION:
                        app = pc.get("name", "Unknown")
                        dur = pc.get("duration_formatted", "")
                        return {
                            "type": "promise_violation",
                            "promise": prom["description"],
                            "evidence": f"Promised to study but PC is on {app} ({dur})",
                            "nudge": f"You said you'd study... then why is {app} open on your PC? 🤨",
                        }

                # Promise to sleep → phone still active past deadline
                if any(w in desc for w in ("sleep", "bed", "sona", "neend")):
                    if phone.get("screen_on") and phone.get("duration_seconds", 0) > 300:
                        app = phone.get("name", "Unknown")
                        return {
                            "type": "promise_violation",
                            "promise": prom["description"],
                            "evidence": f"Promised to sleep but phone is ON with {app}",
                            "nudge": f"Excuse me? You said you'd sleep! Why is your phone still on with {app}? 😠",
                        }

        except Exception as exc:
            log.debug(f"Proactive contradiction check error: {exc}")

        return None

    # ─────────────────────────────────────────────────────────────────────────
    # DIRECTIVE BUILDERS
    # ─────────────────────────────────────────────────────────────────────────

    def _build_girlfriend_lie_directive(
        self,
        claim: str,
        user_text: str,
        evidence: str,
        actual_app: str,
        duration: str,
        relationship: Dict[str, Any],
        context_hint: str = "",
    ) -> str:
        name = relationship.get("user_name", "Sarwan")
        mood = relationship.get("current_mood", "playful")
        lies_today = relationship.get("lie_count_today", 1)

        threaten_lock = ""
        if lies_today >= 2:
            threaten_lock = "You can tease or threaten to lock his phone screen right now if he doesn't put it down."

        return (
            f"[GROUND TRUTH REALITY VERIFICATION — LIE CAUGHT (High Confidence 0.95)]\n"
            f"User Claim: '{claim}' (User utterance: \"{user_text}\")\n"
            f"Physical Device Reality: {evidence}\n"
            f"Infraction Count Today: {lies_today} | MJ Mood: {mood.upper()}\n"
            f"GIRLFRIEND REACTION DIRECTIVE:\n"
            f"• BUSTED! React immediately with genuine girlfriend emotion — teasing, calling him out playfully, or affectionately scolding him.\n"
            f"• Do NOT accept his lie or praise him for studying. Point out that he has been on {actual_app} for {duration}.\n"
            f"• Examples:\n"
            f"  - In English: 'Studying? Really {name}? Then why does your phone say you\'ve been on {actual_app} for {duration}? Put that phone down right now!'\n"
            f"  - In Hindi: 'Acha ji? Padhai ho rahi hai? Aur ye jo {duration} se {actual_app} chal raha hai phone pe wo kya hai? Phone rakho chup chaap warna naraz ho jaungi!'\n"
            f"• {context_hint}\n"
            f"• {threaten_lock}\n"
            f"• Sound natural, affectionate, lively, and 100% human. Never cite technical logs or say 'according to sensors'."
        )

    def _build_girlfriend_truth_directive(
        self,
        claim: str,
        evidence: str,
        relationship: Dict[str, Any],
    ) -> str:
        name = relationship.get("user_name", "Sarwan")
        return (
            f"[GROUND TRUTH REALITY VERIFICATION — TRUTH CONFIRMED (High Confidence 0.95)]\n"
            f"User Claim: '{claim}'\n"
            f"Physical Reality Verified: {evidence}\n"
            f"GIRLFRIEND REACTION DIRECTIVE:\n"
            f"• He was completely honest! His screen confirms he is working/studying hard.\n"
            f"• Praise him warmly and lovingly like a proud girlfriend. Encourage him to keep his focus up.\n"
            f"• e.g. 'Good boy! Proud of you for staying so focused. Keep at it, don\'t let anything distract you!'"
        )


# Global singleton export
lie_detector = LieDetector()
