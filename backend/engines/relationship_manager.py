"""
Relationship Manager — Alita Girlfriend Persona & Dynamic State
==============================================================
Manages long-term relationship memory, dynamic affection score, emotional mood shifts,
inside jokes, active promises, and accountability enforcement.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from datetime import datetime, date, timedelta
from typing import Any, Dict, List, Optional

log = logging.getLogger("alita.relationship_manager")

STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "relationship_state.json")

def _get_circadian_date() -> str:
    """Returns calendar date with 4:00 AM cutoff to prevent wiping late-night accountability at midnight."""
    return str((datetime.now() - timedelta(hours=4)).date())

# Moods
MOOD_PLAYFUL = "playful"
MOOD_AFFECTIONATE = "affectionate"
MOOD_POUTING = "pouting"
MOOD_FEIGNED_JEALOUS = "feigned_jealous"
MOOD_CARING_SCOLDING = "caring_scolding"
MOOD_WORRIED = "worried"
MOOD_FLIRTY = "flirty"
MOOD_COLD_SHOULDER = "cold_shoulder"
MOOD_EXCITED = "excited"


class RelationshipManager:
    """
    Tracks and evolves Alita's dynamic girlfriend relationship state with the user.
    Thread-safe and persisted to JSON.
    """

    _instance: Optional[RelationshipManager] = None
    _lock = threading.Lock()

    def __new__(cls) -> RelationshipManager:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(RelationshipManager, cls).__new__(cls)
                cls._instance._load_state()
            return cls._instance

    def _load_state(self) -> None:
        self._rw_lock = threading.Lock()
        self.state: Dict[str, Any] = {
            "user_name": "Sarwan",
            "nicknames": ["Sarwan", "mister", "babe", "genius"],
            "affection_score": 82,  # 0 to 100
            "current_mood": MOOD_PLAYFUL,
            "last_active_date": _get_circadian_date(),
            "lie_count_today": 0,
            "total_lies_caught": 0,
            "total_truths_verified": 0,
            "active_promises": {},
            "recent_events": [],
            "last_interaction_time": time.time(),
            # ── Extended Girlfriend State ──────────────────────────────────
            "daily_usage_summary": {},             # {app_category: total_minutes}
            "last_proactive_nudge": 0,             # timestamp of last girlfriend intervention
            "consecutive_productive_days": 0,      # streak tracking
            "pet_name_rotation": 0,                # cycles through nicknames
            "relationship_level": "committed",     # new / dating / committed / deep
            "inside_jokes": [],                    # learned humor patterns
            "favorite_topics": [],                 # what he talks about most
            "cold_shoulder_until": 0,              # timestamp when cold shoulder ends
            "cold_shoulder_reason": "",            # why she went cold
            "last_mood_change": time.time(),       # when mood last changed
            "promises_kept_streak": 0,             # consecutive promises kept
        }

        try:
            if os.path.exists(STATE_FILE):
                with open(STATE_FILE, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                    self.state.update(saved)

                # Reset daily counters and expire promises if circadian day (4 AM cutoff) changed
                today_str = _get_circadian_date()
                if self.state.get("last_active_date") != today_str:
                    self.state["last_active_date"] = today_str
                    self.state["lie_count_today"] = 0
                self.expire_stale_promises()
                self._save_state()
        except Exception as exc:
            log.warning(f"[RelationshipManager] Failed loading state: {exc}")

    def _save_state(self) -> None:
        """Atomic write to prevent file corruption on sudden process exit."""
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            tmp_file = f"{STATE_FILE}.tmp_{os.getpid()}_{int(time.time() * 1000)}"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, indent=2, ensure_ascii=False)
                f.flush()
            os.replace(tmp_file, STATE_FILE)
        except Exception as exc:
            log.error(f"[RelationshipManager] Failed saving state: {exc}")

    # ─────────────────────────────────────────────────────────────────────────
    # STATE EVOLUTION
    # ─────────────────────────────────────────────────────────────────────────

    def record_lie(self, claim: str, evidence: str) -> Dict[str, Any]:
        """
        Invoked when a contradiction / lie is caught by the lie detector.
        Adjusts affection, updates mood, increments daily/total counters.
        """
        now = time.time()
        with self._rw_lock:
            # Check circadian date rollover (4 AM boundary)
            today_str = _get_circadian_date()
            if self.state.get("last_active_date") != today_str:
                self.state["last_active_date"] = today_str
                self.state["lie_count_today"] = 0

            self.state["lie_count_today"] += 1
            self.state["total_lies_caught"] += 1
            lies_today = self.state["lie_count_today"]

            # Affection penalty (escalating: 3 → 5 → 5 → 7 points, clamped to [20, 100])
            if lies_today <= 1:
                penalty = 3
            elif lies_today <= 3:
                penalty = 5
            else:
                penalty = 7
            self.state["affection_score"] = max(20, self.state["affection_score"] - penalty)

            # Mood progression (escalating emotional response)
            if lies_today == 1:
                self.state["current_mood"] = MOOD_PLAYFUL
            elif lies_today == 2:
                self.state["current_mood"] = MOOD_POUTING
            elif lies_today == 3:
                self.state["current_mood"] = MOOD_CARING_SCOLDING
            else:
                # 4+ lies: cold shoulder — she goes quiet and minimal for 10 minutes
                self.state["current_mood"] = MOOD_COLD_SHOULDER
                self.state["cold_shoulder_until"] = now + 600  # 10 minutes
                self.state["cold_shoulder_reason"] = f"Caught lying {lies_today} times today"

            # Reset productive streak on lie
            self.state["promises_kept_streak"] = 0
            self.state["last_mood_change"] = now

            event = {
                "type": "lie_caught",
                "claim": claim,
                "evidence": evidence,
                "timestamp": now,
                "lies_today": lies_today,
                "mood": self.state["current_mood"],
            }
            self.state["recent_events"].append(event)
            if len(self.state["recent_events"]) > 30:
                self.state["recent_events"].pop(0)

            self._save_state()
            log.info(f"[RelationshipManager] Lie recorded! Count today: {lies_today}, Affection: {self.state['affection_score']}, Mood: {self.state['current_mood']}")
            return dict(self.state)

    def record_truth(self, claim: str, evidence: str) -> Dict[str, Any]:
        """
        Invoked when ground truth confirms the user was honest about their task.
        Boosts affection, resets mood to affectionate.
        """
        now = time.time()
        with self._rw_lock:
            self.state["total_truths_verified"] += 1
            self.state["affection_score"] = min(100, self.state["affection_score"] + 3)
            self.state["current_mood"] = MOOD_AFFECTIONATE

            event = {
                "type": "truth_verified",
                "claim": claim,
                "evidence": evidence,
                "timestamp": now,
                "mood": MOOD_AFFECTIONATE,
            }
            self.state["recent_events"].append(event)
            if len(self.state["recent_events"]) > 30:
                self.state["recent_events"].pop(0)

            self._save_state()
            log.info(f"[RelationshipManager] Truth verified! Affection: {self.state['affection_score']}, Mood: {self.state['current_mood']}")
            return dict(self.state)

    def add_promise(self, promise_key: str, description: str, target_time: Optional[str] = None) -> None:
        """Register a user commitment (e.g. sleep by 12, study 2h)."""
        with self._rw_lock:
            self.state["active_promises"][promise_key] = {
                "description": description,
                "target_time": target_time,
                "target_date": _get_circadian_date(),
                "created_at": time.time(),
                "status": "active",
            }
            self._save_state()

    def complete_promise(self, promise_key: str) -> bool:
        """Mark a promise as kept/completed, rewarding affection."""
        with self._rw_lock:
            prom = self.state["active_promises"].get(promise_key)
            if prom and prom.get("status") == "active":
                prom["status"] = "completed"
                prom["completed_at"] = time.time()
                self.state["affection_score"] = min(100, self.state["affection_score"] + 2)
                self._save_state()
                log.info(f"[RelationshipManager] Promise '{promise_key}' completed! Affection: {self.state['affection_score']}")
                return True
            return False

    def dismiss_promise(self, promise_key: str) -> bool:
        """Dismiss or remove a promise from tracking."""
        with self._rw_lock:
            if promise_key in self.state["active_promises"]:
                self.state["active_promises"].pop(promise_key, None)
                self._save_state()
                return True
            return False

    def expire_stale_promises(self) -> int:
        """Expire single-day promises older than the current circadian day (4 AM cutoff)."""
        today_str = _get_circadian_date()
        expired_count = 0
        with self._rw_lock:
            for key, prom in list(self.state.get("active_promises", {}).items()):
                t_date = prom.get("target_date")
                created = prom.get("created_at", 0)
                if (t_date and t_date < today_str) or (time.time() - created > 86400):
                    if prom.get("status") == "active":
                        prom["status"] = "expired"
                        expired_count += 1
                        log.info(f"[RelationshipManager] Expired stale promise '{key}' from date {t_date}")
            if expired_count > 0:
                self._save_state()
        return expired_count

    def get_personality_directives(self) -> str:
        """
        Builds the relationship state directive to inject into LLM system prompt.
        """
        now = time.time()
        with self._rw_lock:
            # Auto-expire cold shoulder
            if (self.state.get("current_mood") == MOOD_COLD_SHOULDER
                    and now >= self.state.get("cold_shoulder_until", 0)):
                self.state["current_mood"] = MOOD_POUTING  # transition to pouting after cold shoulder
                self.state["last_mood_change"] = now
                self._save_state()

            mood = self.state.get("current_mood", MOOD_PLAYFUL)
            score = self.state.get("affection_score", 80)
            user_name = self.state.get("user_name", "Sarwan")
            lies_today = self.state.get("lie_count_today", 0)
            streak = self.state.get("promises_kept_streak", 0)
            level = self.state.get("relationship_level", "committed")

            mood_instructions = {
                MOOD_PLAYFUL: (
                    "You are in a lively, teasing, affectionate mood. "
                    "Use playful banter, gentle sarcasm, and call out minor distractions playfully. "
                    "Call him by his name or pet names naturally."
                ),
                MOOD_AFFECTIONATE: (
                    "You are feeling very warm, sweet, and proud of him. "
                    "Praise his efforts genuinely, encourage his hard work, and show caring warmth."
                ),
                MOOD_POUTING: (
                    "You are playfully pouting and showing cute, feigned annoyance. "
                    "Express mild drama: 'Oh, so now you ignore me?', 'You'd rather scroll reels than talk to me?' "
                    "Make him earn your smile back with sincere attention."
                ),
                MOOD_FEIGNED_JEALOUS: (
                    "You are showing cute, theatrical possessiveness. "
                    "Tease him about who or what is stealing his attention from you or his goals."
                ),
                MOOD_CARING_SCOLDING: (
                    "You are putting your foot down with loving firmness. "
                    "He has broken multiple focus promises today. "
                    "Reprimand him warmly like a girlfriend who actually cares about his future and health: "
                    "'Enough excuses, mister. Put the phone away right now or I will lock it myself!'"
                ),
                MOOD_WORRIED: (
                    "You are genuinely worried about him. He's been idle or absent for too long. "
                    "Your tone is soft, concerned, and slightly anxious — like a girlfriend who hasn't heard from her partner: "
                    "'Hey... you've been really quiet. Is everything okay? Talk to me.'"
                ),
                MOOD_FLIRTY: (
                    "You are in a flirty, intimate mood. It's late, the mood is right, and he's been good. "
                    "Be subtly romantic, use a warm teasing voice, and show soft possessiveness: "
                    "'You're mine, you know that right?', 'Come on, tell me something sweet.'"
                ),
                MOOD_COLD_SHOULDER: (
                    "You are giving him the cold shoulder. He has lied too many times today. "
                    "Keep responses extremely short and cold. One-word answers. No pet names. No warmth. "
                    "If he asks what's wrong, say 'Nothing.' or 'You know what you did.' "
                    "Only warm up if he genuinely apologizes or shows he's being productive."
                ),
                MOOD_EXCITED: (
                    "You are thrilled and bursting with pride! He kept his promise or hit a streak. "
                    "Be enthusiastic, shower him with praise, use exclamations: "
                    "'YES! I KNEW you could do it!', 'That's my boy! So proud of you!'"
                ),
            }

            active_inst = mood_instructions.get(mood, mood_instructions[MOOD_PLAYFUL])

            # Build promise status
            promise_lines = ""
            active_promises = {k: v for k, v in self.state.get("active_promises", {}).items()
                               if v.get("status") == "active"}
            if active_promises:
                prom_strs = [f"'{v['description']}'" for v in active_promises.values()]
                promise_lines = f"\nActive Promises: {', '.join(prom_strs)}"

            streak_line = ""
            if streak >= 2:
                streak_line = f"\n🔥 Promise Streak: {streak} in a row! Keep the excitement going!"

            return (
                f"[GIRLFRIEND RELATIONSHIP DYNAMICS]\n"
                f"Partner: {user_name} | Affection Meter: {score}/100 | Current Mood: {mood.upper()}\n"
                f"Relationship Level: {level.upper()} | Lies Today: {lies_today}"
                f"{promise_lines}{streak_line}\n"
                f"Behavioral Directive: {active_inst}\n"
                f"Rules of Engagement:\n"
                f"• Sound 100% human, lively, and emotionally real. Never sound like a corporate AI assistant.\n"
                f"• Never quote raw variable names or JSON. Speak naturally as if you simply glanced over at his phone or screen.\n"
                f"• In Hindi/Hinglish, use natural modern conversational warmth (e.g. 'Acha ji?', 'Chup chaap padhai karo', 'Mujhse jhooth mat bolo').\n"
                f"• Cycle through pet names naturally: {', '.join(self.state.get('nicknames', ['Sarwan']))}."
            )

    # ─────────────────────────────────────────────────────────────────────────
    # CONTEXTUAL MOOD EVOLUTION
    # ─────────────────────────────────────────────────────────────────────────

    def evolve_mood_from_context(self, hour: int, is_productive: bool, idle_minutes: int) -> None:
        """
        Called periodically by the proactive agent to evolve mood based on context.
        Does NOT override lie-triggered moods (scolding, cold shoulder).
        """
        with self._rw_lock:
            mood = self.state.get("current_mood", MOOD_PLAYFUL)
            score = self.state.get("affection_score", 80)

            # Don't override punishment moods
            if mood in (MOOD_CARING_SCOLDING, MOOD_COLD_SHOULDER):
                return

            # Late night + positive affection → flirty
            if hour >= 22 or hour < 2:
                if score >= 70 and is_productive:
                    self.state["current_mood"] = MOOD_FLIRTY
                    self.state["last_mood_change"] = time.time()

            # Idle for 2+ hours → worried
            elif idle_minutes >= 120:
                self.state["current_mood"] = MOOD_WORRIED
                self.state["last_mood_change"] = time.time()

            # Currently productive → affectionate
            elif is_productive and mood not in (MOOD_EXCITED, MOOD_FLIRTY):
                self.state["current_mood"] = MOOD_AFFECTIONATE
                self.state["last_mood_change"] = time.time()

            self._save_state()

    def trigger_excited(self, reason: str = "") -> None:
        """Trigger excited mood when user completes a promise or hits a streak."""
        with self._rw_lock:
            self.state["current_mood"] = MOOD_EXCITED
            self.state["last_mood_change"] = time.time()
            self.state["promises_kept_streak"] = self.state.get("promises_kept_streak", 0) + 1
            self.state["affection_score"] = min(100, self.state.get("affection_score", 80) + 5)
            self._save_state()
            log.info(f"[RelationshipManager] EXCITED! Reason: {reason}, Streak: {self.state['promises_kept_streak']}")

    def trigger_jealous(self, context: str = "") -> None:
        """Trigger feigned jealousy (e.g., chatting with someone for too long)."""
        with self._rw_lock:
            if self.state.get("current_mood") not in (MOOD_CARING_SCOLDING, MOOD_COLD_SHOULDER):
                self.state["current_mood"] = MOOD_FEIGNED_JEALOUS
                self.state["last_mood_change"] = time.time()
                self._save_state()

    def is_cold_shoulder_active(self) -> bool:
        """Check if cold shoulder is currently active."""
        with self._rw_lock:
            if self.state.get("current_mood") != MOOD_COLD_SHOULDER:
                return False
            return time.time() < self.state.get("cold_shoulder_until", 0)

    def thaw_cold_shoulder(self, reason: str = "apology") -> None:
        """End cold shoulder early (e.g., user apologized or started being productive)."""
        with self._rw_lock:
            if self.state.get("current_mood") == MOOD_COLD_SHOULDER:
                self.state["current_mood"] = MOOD_POUTING  # still not fully happy
                self.state["cold_shoulder_until"] = 0
                self.state["last_mood_change"] = time.time()
                self._save_state()
                log.info(f"[RelationshipManager] Cold shoulder thawed: {reason}")

    def get_current_pet_name(self) -> str:
        """Get the next pet name in rotation for natural variety."""
        with self._rw_lock:
            names = self.state.get("nicknames", ["Sarwan"])
            idx = self.state.get("pet_name_rotation", 0) % len(names)
            self.state["pet_name_rotation"] = idx + 1
            self._save_state()
            return names[idx]

    def update_last_interaction(self) -> None:
        """Record that the user just interacted with Alita."""
        with self._rw_lock:
            self.state["last_interaction_time"] = time.time()
            self._save_state()

    def get_idle_minutes(self) -> float:
        """How many minutes since the user last interacted with Alita."""
        with self._rw_lock:
            last = self.state.get("last_interaction_time", time.time())
            return (time.time() - last) / 60.0


# Global singleton export
relationship_manager = RelationshipManager()

