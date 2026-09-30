# pyre-ignore-all-errors
"""
Macro Recorder & Custom Voice Workflow Engine
==============================================
Enables "Teach Alita" — no-code natural voice custom macro creation and replay.
Users can define personal routines on the fly:
  - "Alita, remember this routine as 'morning setup': open Chrome to github.com, open VS Code, and play lofi beats"
  - "Start morning setup" -> Replays the multi-step recipe with voice and UI feedback.
Persists recipes to backend/data/custom_macros.json.
"""

import json
import logging
import os
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("alita.macros")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MACROS_FILE = os.path.join(DATA_DIR, "custom_macros.json")


class MacroRecorder:
    """Manages recording, storing, listing, and executing user-defined voice macros."""

    def __init__(self) -> None:
        self._macros: Dict[str, Dict[str, Any]] = {}
        self._ensure_storage()
        self._load_macros()

    def _ensure_storage(self) -> None:
        os.makedirs(DATA_DIR, exist_ok=True)
        if not os.path.exists(MACROS_FILE):
            with open(MACROS_FILE, "w", encoding="utf-8") as f:
                json.dump({}, f, indent=2)

    def _load_macros(self) -> None:
        try:
            if os.path.exists(MACROS_FILE):
                with open(MACROS_FILE, "r", encoding="utf-8") as f:
                    self._macros = json.load(f)
        except Exception as e:
            logger.error("[MacroRecorder] Failed to load custom macros: %s", e)
            self._macros = {}

    def _save_macros(self) -> None:
        try:
            with open(MACROS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._macros, f, indent=2)
        except Exception as e:
            logger.error("[MacroRecorder] Failed to save custom macros: %s", e)

    def is_record_command(self, text: str) -> bool:
        """Check if user is teaching a new workflow macro."""
        lower = text.lower().strip()
        return bool(re.search(
            r'\b(?:remember\s+(?:this\s+)?(?:routine|macro|workflow)|save\s+(?:macro|routine|workflow)|create\s+(?:macro|routine|workflow)|teach\s+(?:alita|mj))\b',
            lower
        ))

    def parse_and_record(self, text: str) -> Tuple[bool, str]:
        """Parse natural language command into a saved macro recipe."""
        lower = text.lower().strip()

        # Extract macro name: "as 'morning launch': <steps>" or "macro <name>: <steps>"
        name_match = re.search(r'(?:as|name|named|called)\s+[\'"]?([a-zA-Z0-9_\s\-]+?)[\'"]?\s*[:\-\—\,]\s*(.+)$', text, re.IGNORECASE)
        if not name_match:
            name_match = re.search(r'(?:routine|macro|workflow)\s+[\'"]?([a-zA-Z0-9_\s\-]+?)[\'"]?\s*[:\-\—\,]\s*(.+)$', text, re.IGNORECASE)

        if not name_match:
            return False, "Could not determine the macro name. Try saying: 'Remember this routine as morning launch: open Chrome, open VS Code, and play focus music'."

        raw_name = name_match.group(1).strip().lower()
        # Clean name
        macro_name = re.sub(r'^(?:for|to|as)\s+', '', raw_name).strip()
        raw_steps_str = name_match.group(2).strip()

        # Split into individual steps
        from engines.compound_pipeline import compound_pipeline
        steps = compound_pipeline.split_steps(raw_steps_str)
        if not steps:
            steps = [raw_steps_str]

        self._macros[macro_name] = {
            "name": macro_name,
            "created_at": time.time(),
            "raw_command": raw_steps_str,
            "steps": steps,
            "steps_count": len(steps)
        }
        self._save_macros()

        logger.info("[MacroRecorder] Saved macro '%s' with %d steps", macro_name, len(steps))
        steps_preview = " -> ".join(f"'{s}'" for s in steps)
        return True, f"Learned new routine '{macro_name}' ({len(steps)} steps: {steps_preview}). You can run it anytime by saying 'Start {macro_name}'."

    def find_matching_macro(self, text: str) -> Optional[Dict[str, Any]]:
        """Check if user is asking to run a custom saved macro."""
        lower = text.lower().strip()
        # Look for "start <name>", "run <name>", "execute <name>", "activate <name>"
        trigger_match = re.search(r'\b(?:start|run|launch|execute|activate|chalu karo|shuru karo)\s+([a-zA-Z0-9_\s\-]+)$', lower)
        candidate = trigger_match.group(1).strip() if trigger_match else lower

        # Exact match
        if candidate in self._macros:
            return self._macros[candidate]

        # Fuzzy / Substring match
        for name, data in self._macros.items():
            if name in lower or candidate in name:
                return data

        return None

    def execute_macro(
        self,
        macro_data: Dict[str, Any],
        session: Optional[Any] = None,
        settings: Optional[Any] = None,
        notify: Optional[Callable[[Dict[str, Any]], None]] = None
    ) -> Dict[str, Any]:
        """Execute the steps of a saved macro via CompoundPipeline."""
        from engines.compound_pipeline import compound_pipeline
        name = macro_data.get("name", "Custom Routine")
        steps = macro_data.get("steps", [])
        compound_cmd = " and then ".join(steps)

        logger.info("[MacroRecorder] Executing macro '%s' (%d steps)", name, len(steps))
        return compound_pipeline.execute(compound_cmd, session=session, settings=settings, notify=notify)

    def list_macros(self) -> str:
        """List all saved user routines."""
        if not self._macros:
            return "You haven't created any custom macros yet. You can create one by saying 'Remember this routine as coding mode: open VS Code, open Chrome, and play lofi beats'."

        lines = ["Your Saved Voice Routines:"]
        for name, data in self._macros.items():
            steps = data.get("steps", [])
            lines.append(f"- {name.title()} ({len(steps)} steps): {' -> '.join(steps[:3])}")
        return "\n".join(lines)

    def delete_macro(self, name: str) -> str:
        """Delete a custom routine."""
        name_clean = name.lower().strip()
        if name_clean in self._macros:
            del self._macros[name_clean]
            self._save_macros()
            return f"Deleted custom macro '{name_clean}'."
        return f"Macro '{name_clean}' not found."


# Singleton instance
macro_recorder = MacroRecorder()
