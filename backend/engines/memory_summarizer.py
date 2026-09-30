"""
Alita Memory Summarizer — Conversation Consolidation & Knowledge Distillation
=============================================================================
Periodically condenses batches of conversational turns into compact, deduplicated
personal facts. Preserves named entities (people, places, preferences) while preventing
token context bloat. Integrates with the Knowledge Graph and persists summaries to disk.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("alita.summarizer")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DEFAULT_STORAGE = os.path.join(_BACKEND_DIR, "data", "memory_summaries.json")


class MemorySummarizer:
    """
    Tracks conversational volume per user and distills historical dialogue
    into permanent, structured facts.
    """

    def __init__(
        self,
        episodic_memory: Any = None,
        knowledge_graph: Any = None,
        llm_fn: Optional[Callable[[str], Any]] = None,
        threshold: int = 15,
        storage_path: Optional[str] = None,
    ):
        self.episodic_memory = episodic_memory
        self.knowledge_graph = knowledge_graph
        self.llm_fn = llm_fn
        self.threshold = threshold
        self.storage_path = storage_path or _DEFAULT_STORAGE
        self._unsummarized: Dict[str, List[str]] = defaultdict(list)
        self._summaries: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._load()

    def _load(self) -> None:
        """Load persistent summaries from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    for uid, slist in data.items():
                        self._summaries[uid] = slist
                log.info("Loaded summaries for %d users from %s", len(self._summaries), self.storage_path)
            except Exception as exc:
                log.warning("Could not load summaries: %s", exc)

    def _save(self) -> None:
        """Persist summaries to disk."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.storage_path)), exist_ok=True)
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(dict(self._summaries), f, indent=2, ensure_ascii=False)
        except Exception as exc:
            log.warning("Could not persist summaries: %s", exc)

    def record_interaction(self, user_id: str, text: str) -> None:
        """Record an ongoing user interaction for batch summarization."""
        clean = text.strip()
        if clean:
            self._unsummarized[user_id].append(clean)

    def get_unsummarized_count(self, user_id: str) -> int:
        """Returns the number of conversation turns waiting to be summarized."""
        return len(self._unsummarized.get(user_id, []))

    def get_stored_summaries(self, user_id: str) -> List[Dict[str, Any]]:
        """Retrieve historical summaries for a specific user."""
        return list(self._summaries.get(user_id, []))

    def _deduplicate_facts(self, raw_text: str) -> List[str]:
        """
        Parses multi-line text, cleans bullet markers, and deduplicates
        facts case-insensitively while preserving natural capitalization.
        """
        lines = [line.strip() for line in raw_text.splitlines() if line.strip()]
        unique_facts: List[str] = []
        seen_keys: set[str] = set()

        for line in lines:
            cleaned = re.sub(r"^[\s*•\-#\d.)]+", "", line).strip()
            if not cleaned or len(cleaned) < 3:
                continue
            norm_key = cleaned.lower()
            if norm_key not in seen_keys:
                seen_keys.add(norm_key)
                unique_facts.append(cleaned)

        return unique_facts

    async def maybe_summarize(self, user_id: str) -> Optional[Dict[str, Any]]:
        """
        Evaluates unsummarized conversation history. If count >= threshold,
        generates a condensed summary, deduplicates facts, writes to knowledge
        graph and disk, and resets counter.
        """
        count = self.get_unsummarized_count(user_id)
        if count < self.threshold:
            return None

        interactions = list(self._unsummarized[user_id])
        joined_convo = "\n".join(f"- {turn}" for turn in interactions)

        prompt = (
            f"Summarize these {len(interactions)} recent conversations into concise, verified key facts about the user.\n"
            "Preserve exact names, places, relations, and preferences (e.g., 'Priya', 'Google').\n"
            "Return each fact on a separate bullet point:\n\n"
            f"{joined_convo}"
        )

        raw_summary = ""
        if self.llm_fn:
            try:
                res = self.llm_fn(prompt)
                if inspect.iscoroutine(res):
                    raw_summary = await res
                else:
                    raw_summary = str(res)
            except Exception as exc:
                log.warning("LLM summarization failed: %s", exc)

        if not raw_summary:
            # Fallback simple extractive summarization
            raw_summary = "\n".join(f"- {t}" for t in interactions[:5])

        deduped_facts = self._deduplicate_facts(raw_summary)

        # Distill facts into Knowledge Graph if available
        if self.knowledge_graph:
            for fact in deduped_facts:
                try:
                    self.knowledge_graph.extract_and_store(fact, user_id=user_id)
                except Exception as kg_err:
                    log.debug("Failed to store distilled fact in KG: %s", kg_err)

        record = {
            "summary_text": raw_summary,
            "facts": deduped_facts,
            "turns_summarized": len(interactions),
            "timestamp": time.time(),
        }

        self._summaries[user_id].append(record)
        self._save()
        self._unsummarized[user_id].clear()

        log.info("Summarized %d turns for user '%s' into %d key facts", len(interactions), user_id, len(deduped_facts))
        return record


# Global singleton instance
memory_summarizer = MemorySummarizer()
