# pyre-ignore-all-errors
"""
Conversational Planner — Breaks abstract goals into executable steps.
Handles high-level instructions like:
  "prepare for my meeting"     → open calendar, draft agenda, open docs
  "set up for coding"          → open vscode, open terminal, open chrome
  "help me write a report"     → open word, compose outline, start writing

Two modes:
  1. Rule-based decomposition for common goals (offline, ~1ms)
  2. LLM fallback for truly novel goals (needs API)
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
#  GOAL TEMPLATES — Rule-based decomposition for common high-level goals
# ═════════════════════════════════════════════════════════════════════════════

GOAL_TEMPLATES: List[Dict[str, Any]] = [
    # ── Work & Meeting ────────────────────────────────────────────────────
    {
        "patterns": [
            r"(?:prepare|get ready|setup|set up)\s+(?:for\s+)?(?:a\s+|my\s+|the\s+)?(?:meeting|call|zoom|teams call)",
            r"(?:meeting|call)\s+(?:ki\s+)?(?:tayyari|preparation)",
        ],
        "name": "prepare_meeting",
        "steps": [
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser for meeting docs"},
            {"action": "open_app", "params": {"app": "word"}, "desc": "Opening Word for notes"},
        ],
        "description": "Preparing workspace for meeting",
    },
    {
        "patterns": [
            r"(?:prepare|get ready)\s+(?:for\s+)?(?:a\s+|my\s+)?presentation",
            r"presentation\s+(?:ki\s+)?(?:tayyari|banao)",
        ],
        "name": "prepare_presentation",
        "steps": [
            {"action": "open_app", "params": {"app": "powerpoint"}, "desc": "Opening PowerPoint"},
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser for research"},
        ],
        "description": "Setting up for presentation work",
    },
    # ── Coding ────────────────────────────────────────────────────────────
    {
        "patterns": [
            r"(?:set ?up|start|prepare|setup)\s+(?:for\s+|my\s+)?(?:coding|programming|development|dev)",
            r"(?:coding|development)\s+(?:ka\s+)?(?:setup|shuru)",
        ],
        "name": "setup_coding",
        "steps": [
            {"action": "open_app", "params": {"app": "vscode"}, "desc": "Opening VS Code"},
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser for docs"},
        ],
        "description": "Setting up coding workspace",
    },
    {
        "patterns": [
            r"(?:set ?up|start|prepare)\s+(?:for\s+)?(?:web\s+)?(?:development|dev)\s+(?:with|using)\s+(\w+)",
        ],
        "name": "setup_webdev",
        "steps": [
            {"action": "open_app", "params": {"app": "vscode"}, "desc": "Opening VS Code"},
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser"},
        ],
        "description": "Setting up web development workspace",
    },
    # ── Writing & Documents ───────────────────────────────────────────────
    {
        "patterns": [
            r"(?:help me |i want to |i need to )?write\s+(?:a\s+)?(?:report|essay|article|paper|document)",
            r"(?:report|essay|article)\s+(?:likh|banao|likho)",
        ],
        "name": "write_document",
        "steps": [
            {"action": "open_app", "params": {"app": "word"}, "desc": "Opening Word"},
            {"action": "compose", "params": {"topic": "__EXTRACT__", "app": "word"}, "desc": "Generating document outline"},
        ],
        "description": "Starting document writing workflow",
    },
    {
        "patterns": [
            r"(?:help me |i want to |i need to )?(?:write|draft|compose)\s+(?:a\s+|an\s+)?(?:email|mail|letter)\s+(?:to\s+)?(.+)?",
            r"(?:email|mail)\s+(?:likh|bhej|likho)\s*(.+)?",
        ],
        "name": "write_email",
        "steps": [
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser for email"},
            {"action": "search_web", "params": {"query": "gmail.com", "app": "chrome"}, "desc": "Going to Gmail"},
        ],
        "description": "Setting up email composition",
    },
    # ── Research ──────────────────────────────────────────────────────────
    {
        "patterns": [
            r"(?:research|study|learn about|find information)\s+(?:about\s+|on\s+)?(.+)",
            r"(.+)\s+(?:ke baare mein|par)\s+(?:research|jaankari|padho)",
        ],
        "name": "research_topic",
        "steps": [
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser"},
            {"action": "search_web", "params": {"query": "__EXTRACT__", "app": "chrome"}, "desc": "Searching for topic"},
            {"action": "open_app", "params": {"app": "notepad"}, "desc": "Opening Notepad for notes"},
        ],
        "description": "Starting research workflow",
    },
    # ── Entertainment ─────────────────────────────────────────────────────
    {
        "patterns": [
            r"(?:play|put on|start)\s+(?:some\s+)?(?:music|songs|gaane|gana)",
            r"(?:music|gaane)\s+(?:chala|bajao|play karo)",
        ],
        "name": "play_music",
        "steps": [
            {"action": "open_app", "params": {"app": "spotify"}, "desc": "Opening Spotify"},
        ],
        "description": "Starting music",
    },
    {
        "patterns": [
            r"(?:play|watch|open)\s+(?:a\s+)?(?:video|movie|film|youtube)",
            r"(?:video|youtube)\s+(?:chala|dikha|play karo)",
        ],
        "name": "watch_video",
        "steps": [
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser"},
            {"action": "search_web", "params": {"query": "youtube.com", "app": "chrome"}, "desc": "Going to YouTube"},
        ],
        "description": "Opening video platform",
    },
    # ── System & Organization ─────────────────────────────────────────────
    {
        "patterns": [
            r"(?:clean ?up|organize|tidy)\s+(?:my\s+)?(?:desktop|files|folders|computer)",
            r"(?:desktop|files)\s+(?:saaf|clean|organize)\s+karo",
        ],
        "name": "cleanup_desktop",
        "steps": [
            {"action": "open_app", "params": {"app": "explorer"}, "desc": "Opening File Explorer"},
        ],
        "description": "Starting desktop cleanup",
    },
    {
        "patterns": [
            r"(?:check|open)\s+(?:my\s+)?(?:downloads|downloaded files)",
        ],
        "name": "check_downloads",
        "steps": [
            {"action": "open_app", "params": {"app": "explorer"}, "desc": "Opening Downloads folder"},
        ],
        "description": "Opening downloads",
    },
    # ── Multi-app workflows ───────────────────────────────────────────────
    {
        "patterns": [
            r"(?:start|begin)\s+(?:my\s+)?(?:work ?day|morning routine|day)",
            r"(?:subah|morning)\s+(?:ka\s+)?(?:routine|kaam)\s+(?:shuru|start)",
        ],
        "name": "start_workday",
        "steps": [
            {"action": "open_app", "params": {"app": "chrome"}, "desc": "Opening browser"},
            {"action": "open_app", "params": {"app": "vscode"}, "desc": "Opening VS Code"},
        ],
        "description": "Setting up your workday",
    },
    {
        "patterns": [
            r"(?:take|create|make)\s+(?:a\s+)?(?:screenshot|snap|screen ?capture)",
            r"screenshot\s+(?:le|lo|lete)",
        ],
        "name": "take_screenshot",
        "steps": [
            {"action": "navigation", "params": {"action": "screenshot"}, "desc": "Taking screenshot"},
        ],
        "description": "Taking a screenshot",
    },
]

# Compile all patterns
for template in GOAL_TEMPLATES:
    template["_compiled"] = [re.compile(p, re.IGNORECASE) for p in template["patterns"]]


class ConversationalPlanner:
    """Breaks high-level goals into executable screen agent steps."""

    def __init__(self) -> None:
        self._last_plan: Optional[Dict[str, Any]] = None

    def plan(self, command: str) -> Optional[Dict[str, Any]]:
        """
        Try to decompose a command into a multi-step plan.
        Returns None if the command is not a high-level goal.
        Returns a plan dict with 'steps', 'name', 'description'.
        """
        command_clean = command.strip()

        # ── Try rule-based decomposition first ───────────────────────────
        plan = self._match_template(command_clean)
        if plan:
            self._last_plan = plan
            logger.info(f"[Planner] Matched template: {plan['name']} ({len(plan['steps'])} steps)")
            return plan

        return None

    def _match_template(self, command: str) -> Optional[Dict[str, Any]]:
        """Match command against goal templates."""
        for template in GOAL_TEMPLATES:
            for compiled in template["_compiled"]:
                match = compiled.search(command)
                if match:
                    # Deep copy steps and fill in extracted values
                    steps = []
                    for step in template["steps"]:
                        s = {
                            "action": step["action"],
                            "params": dict(step["params"]),
                            "desc": step["desc"],
                        }
                        # Replace __EXTRACT__ with captured group
                        for key, val in s["params"].items():
                            if val == "__EXTRACT__":
                                extracted = match.group(1) if match.lastindex and match.lastindex >= 1 else command
                                s["params"][key] = extracted.strip()
                        steps.append(s)

                    return {
                        "name": template["name"],
                        "description": template["description"],
                        "steps": steps,
                        "source": "template",
                    }
        return None

    def is_goal(self, command: str) -> bool:
        """Quick check if this looks like a high-level goal (not a direct command)."""
        goal_indicators = [
            r"(?:prepare|get ready|set ?up|start)\s+(?:for|my)",
            r"(?:help me|i want to|i need to)\s+",
            r"(?:begin|start)\s+(?:my|a)\s+",
            r"(?:let'?s|can you)\s+",
        ]
        cmd_lower = command.lower()
        for pattern in goal_indicators:
            if re.search(pattern, cmd_lower):
                return True
        return False

    def resolve_coreferences(self, text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, bool]:
        """Resolve pronouns ('it', 'that', 'wahi') to concrete active entities."""
        return resolve_coreferences(text, context)

    @property
    def last_plan(self) -> Optional[Dict[str, Any]]:
        return self._last_plan


def resolve_coreferences(text: str, context: Optional[Dict[str, Any]] = None) -> Tuple[str, bool]:
    """
    Resolve conversational pronouns and demonstrative references to concrete entities.
    Examples:
      - 'close it' (VSCode active) -> 'close vscode'
      - 'maximize that' (Chrome active) -> 'maximize chrome'
      - 'wahi open karo' -> 'open {active_app}'
      - 'save this file' -> 'save {current_document}'
    Returns: (resolved_text, was_modified)
    """
    if not text:
        return text, False

    if context is None:
        try:
            from engines.screen_context import screen_context
            context = screen_context.get_full_context()
        except Exception:
            context = {}

    active_app = (context.get("active_app") or "").strip()
    active_doc = (context.get("active_document") or "").strip()

    resolved = text
    modified = False

    # Pronouns referring to active app window
    if active_app:
        app_pronouns = [
            # English Verb-Object
            (r"\b(close|band karo|exit|quit|terminate)\s+(?:it|this|that|that window|wahi|use|yeh)\b", rf"\1 {active_app}"),
            (r"\b(maximize|minimize|restore|focus|switch to)\s+(?:it|this|that|that window|wahi|use)\b", rf"\1 {active_app}"),
            (r"\b(reload|refresh|restart)\s+(?:it|this|that|wahi)\b", rf"\1 {active_app}"),
            (r"\b(open)\s+(?:it|that again|that one|wahi|dobara wahi)\b", rf"\1 {active_app}"),
            # Hindi / Hinglish Object-Verb order (e.g. 'wahi open karo', 'use close karo')
            (r"\b(?:wahi|use|usse|yeh|woh)\s+(open|kholo|band karo|close karo|close|maximize|minimize|chalao|play karo)\b", rf"\1 {active_app}"),
        ]
        for pattern, repl in app_pronouns:
            new_text, count = re.subn(pattern, repl, resolved, flags=re.IGNORECASE)
            if count > 0:
                resolved = new_text
                modified = True
                break

    # Pronouns referring to active document
    if active_doc:
        doc_pronouns = [
            (r"\b(save|format|read|inspect)\s+(?:this|it|the file|that file|document)\b", rf"\1 {active_doc}"),
        ]
        for pattern, repl in doc_pronouns:
            new_text, count = re.subn(pattern, repl, resolved, flags=re.IGNORECASE)
            if count > 0:
                resolved = new_text
                modified = True
                break

    if modified:
        logger.info("[Planner] Coreference resolved: '%s' → '%s'", text, resolved)

    return resolved, modified


# Singleton
conversational_planner = ConversationalPlanner()

