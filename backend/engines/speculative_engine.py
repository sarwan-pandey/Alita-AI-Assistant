"""Speculative Query Optimization Engine (Gap 9).
Provides ultra-low-latency response caching, partial-transcript matching,
precomputed greeting fast-paths, and speculative inference management.
"""

import re
import time
import difflib
import logging
import asyncio
from typing import Optional, Tuple, Dict

log = logging.getLogger("speculative_engine")

# ── Precomputed Conversational Greetings (0ms inference) ─────────────────────
PRECOMPUTED_GREETINGS: Dict[str, str] = {
    "hello": "Hello! How can I help you today?",
    "hi": "Hi there! What's on your mind?",
    "hey": "Hey! How can I assist you?",
    "good morning": "Good morning! Hope you're having a wonderful day. How can I help?",
    "good afternoon": "Good afternoon! How can I assist you today?",
    "good evening": "Good evening! What can I help you with tonight?",
    "namaste": "Namaste! How may I assist you today?",
    "what's up": "Not much, ready to assist! What do you need?",
    "sup": "Ready and listening! How can I help?",
}

_CLEAN_RE = re.compile(r"[^\w\s]")


def _normalize(text: str) -> str:
    """Normalize text by lowercasing, stripping punctuation, and extra whitespace."""
    if not text:
        return ""
    cleaned = _CLEAN_RE.sub(" ", text.lower())
    return " ".join(cleaned.split())


def get_precomputed_greeting(text: str) -> Optional[str]:
    """Check if the input matches a common greeting, returning an instant response."""
    norm = _normalize(text)
    if not norm:
        return None

    # Direct match
    if norm in PRECOMPUTED_GREETINGS:
        return PRECOMPUTED_GREETINGS[norm]

    # Prefix match (e.g. "hey alita", "hi there", "hello assistant")
    for greeting, response in PRECOMPUTED_GREETINGS.items():
        if norm == greeting or norm.startswith(f"{greeting} ") or norm.endswith(f" {greeting}"):
            return response

    return None


def compute_query_similarity(query_a: str, query_b: str) -> float:
    """Compute semantic and syntactic similarity between speculative and final queries."""
    norm_a = _normalize(query_a)
    norm_b = _normalize(query_b)

    if not norm_a or not norm_b:
        return 0.0

    if norm_a == norm_b:
        return 1.0

    # 1. SequenceMatcher ratio (handles typos and minor grammatical differences)
    seq_ratio = difflib.SequenceMatcher(None, norm_a, norm_b).ratio()

    # 2. Token overlap (handles word insertions or reorderings)
    words_a = set(norm_a.split())
    words_b = set(norm_b.split())
    intersection = words_a & words_b

    jaccard = len(intersection) / max(len(words_a | words_b), 1)
    
    # 3. Subset coverage (speculative query is often a prefix of final transcript)
    subset_ratio = len(intersection) / max(min(len(words_a), len(words_b)), 1)

    # If shorter string is almost entirely inside longer string and length ratio is close
    len_ratio = min(len(norm_a), len(norm_b)) / max(len(norm_a), len(norm_b))
    prefix_score = subset_ratio * len_ratio

    return max(seq_ratio, jaccard, prefix_score)


def is_speculative_cache_hit(cached_query: str, final_query: str, threshold: float = 0.8) -> bool:
    """Determine if cached speculative result is sufficiently similar to the final query."""
    return compute_query_similarity(cached_query, final_query) >= threshold


class SpeculativeManager:
    """Manages speculative query generation, caching, and evaluation."""

    def __init__(self, default_threshold: float = 0.8):
        self.default_threshold = default_threshold

    def start_speculative(
        self,
        session,
        spec_id: int,
        spec_text: str,
        cancel_event: Optional[asyncio.Event] = None
    ) -> asyncio.Event:
        """Register and initiate speculative processing for a session."""
        # Cancel any previous speculative job
        if hasattr(session, "_spec_cancel") and session._spec_cancel:
            session._spec_cancel.set()

        cancel = cancel_event or asyncio.Event()
        session._spec_cancel = cancel
        session._spec_id = spec_id
        session._spec_text = spec_text.strip().lower()
        session._spec_start_time = time.time()

        # Check instant precomputed greeting fast-path
        greeting_resp = get_precomputed_greeting(spec_text)
        if greeting_resp:
            session._spec_result = greeting_resp
            log.info(
                "⚡ Speculative #%d instant precomputed greeting hit for: '%s'",
                spec_id, spec_text[:40]
            )
        else:
            session._spec_result = None

        return cancel

    def check_cache_hit(
        self,
        session,
        final_query: str,
        threshold: Optional[float] = None
    ) -> Tuple[bool, Optional[str], float]:
        """Check if speculative result matches final query, returning (hit, result, latency_saved)."""
        thresh = threshold or self.default_threshold
        cached_result = getattr(session, "_spec_result", None)
        cached_text = getattr(session, "_spec_text", "")
        start_time = getattr(session, "_spec_start_time", 0.0)

        if not cached_result or not cached_text:
            return (False, None, 0.0)

        sim = compute_query_similarity(cached_text, final_query)
        if sim >= thresh:
            latency_saved = max(0.0, time.time() - start_time) if start_time > 0 else 0.0
            log.info(
                "⚡ Speculative hit (%.1f%% match) for '%s' (saved ~%.2fs)",
                sim * 100, final_query[:40], latency_saved
            )
            return (True, cached_result, latency_saved)

        return (False, None, 0.0)

    def clear(self, session) -> None:
        """Clear speculative state on session."""
        if hasattr(session, "_spec_cancel") and session._spec_cancel:
            session._spec_cancel.set()
        session._spec_result = None
        session._spec_text = ""
        session._spec_start_time = 0.0


# Singleton instance
speculative_manager = SpeculativeManager()
