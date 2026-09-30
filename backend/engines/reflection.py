"""
Alita Reflection Guard — Lightweight Self-Correction & Quality Assurance Loop
=============================================================================
Inspects LLM responses before delivery to detect:
1. Empty / zero-length generation
2. False unhelpful refusals / cop-outs ("I don't know", "I cannot", "As an AI")
3. Disproportionately terse answers to comprehensive questions
Triggers an autonomous self-correction turn to refine and complete the answer.
"""

from __future__ import annotations

import inspect
import logging
import re
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("alita.reflection")

COP_OUT_PATTERNS = [
    r"\bi don't know\b",
    r"\bi do not know\b",
    r"\bi'm not sure\b",
    r"\bi am not sure\b",
    r"\bi cannot\b",
    r"\bi can't\b",
    r"\bas an ai\b",
]

_COP_OUT_REGEX = re.compile("|".join(COP_OUT_PATTERNS), re.IGNORECASE)


class ReflectionGuard:
    """
    Evaluates response quality and orchestrates self-correction loops.
    """

    def __init__(
        self,
        llm_fn: Optional[Callable[[List[Dict[str, Any]]], Any]] = None,
        max_retries: int = 2,
    ):
        self.llm_fn = llm_fn
        self.max_retries = max_retries

    def needs_reflection(self, query: str, answer: str) -> bool:
        """
        Fast heuristic checks — evaluates whether the answer warrants a correction pass.
        Zero overhead (no LLM call required).
        """
        if not answer or not answer.strip():
            return True

        ans_clean = answer.strip().lower()

        # Cop-out check
        if _COP_OUT_REGEX.search(ans_clean):
            return True

        q_words = len(query.strip().split())
        a_words = len(ans_clean.split())

        # Long questions with disproportionately terse answers
        if q_words > 20 and a_words < 10:
            return True

        return False

    async def reflect_and_correct(
        self,
        query: str,
        answer: str,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Prompts the model to evaluate and fix its own response.
        """
        if not self.llm_fn:
            return answer

        reflection_prompt = (
            f"Review your answer: '{answer}' for the question: '{query}'. "
            "Is it complete, helpful, and accurate? If it is empty, a refusal, or incomplete, "
            "provide the complete, accurate, direct answer now."
        )

        conv: List[Dict[str, Any]] = list(messages) if messages else [{"role": "user", "content": query}]
        conv.append({"role": "user", "content": reflection_prompt})

        try:
            res = self.llm_fn(conv)
            if inspect.iscoroutine(res):
                res = await res
            return str(res) if res else answer
        except Exception as exc:
            log.warning("Self-correction reflection turn failed: %s", exc)
            return answer

    async def process(
        self,
        query: str,
        answer: str,
        messages: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Full reflection workflow: verifies answer quality and applies up to max_retries corrections.
        """
        current_answer = answer
        for attempt in range(self.max_retries):
            if not self.needs_reflection(query, current_answer):
                return current_answer

            log.info("Reflection triggered for query '%s' (attempt %d/%d)", query[:40], attempt + 1, self.max_retries)
            current_answer = await self.reflect_and_correct(query, current_answer, messages)

        return current_answer


# Global singleton instance
reflection_guard = ReflectionGuard()
