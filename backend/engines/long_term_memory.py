# pyre-ignore-all-errors
"""
Long-Term Memory — Remembers information across sessions and restarts.
Stores: user-told facts, conversation summaries, preferences, reminders.
Encrypted at rest with Fernet (machine-local key).
100% local, no API.

Usage:
  "Remember my WiFi password is hello123"
  → Stored encrypted: {"fact": "WiFi password is hello123", "category": "credential"}

  "What's my WiFi password?"
  → Retrieved: "Your WiFi password is hello123"
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ── Encryption (Fernet — symmetric, local key) ──────────────────────────────
try:
    from cryptography.fernet import Fernet  # type: ignore[import-untyped]
    HAS_CRYPTO = True
except ImportError:
    HAS_CRYPTO = False
    logger.info("[LongTermMemory] cryptography not installed — using plaintext (install with: pip install cryptography)")

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
MEMORY_FILE = os.path.join(DATA_DIR, "long_term_memory.enc")
KEY_FILE = os.path.join(DATA_DIR, ".memory_key")


def _get_or_create_key() -> bytes:
    """Get or create encryption key (machine-local)."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(KEY_FILE):
        with open(KEY_FILE, "rb") as f:
            return f.read()
    key = Fernet.generate_key() if HAS_CRYPTO else b"plaintext-mode"
    with open(KEY_FILE, "wb") as f:
        f.write(key)
    return key


# ── Memory Categories ────────────────────────────────────────────────────────
CATEGORIES = {
    "credential": ["password", "pin", "key", "token", "secret", "login", "username"],
    "personal": ["name", "birthday", "age", "address", "phone", "email", "number"],
    "preference": ["prefer", "like", "favorite", "favourite", "want", "love", "hate"],
    "fact": ["is", "are", "was", "were", "means"],
    "reminder": ["remind", "remember to", "don't forget", "yaad"],
    "work": ["meeting", "deadline", "project", "task", "boss", "office", "client"],
}


def _detect_category(text: str) -> str:
    """Detect memory category from text."""
    text_lower = text.lower()
    for category, keywords in CATEGORIES.items():
        for kw in keywords:
            if kw in text_lower:
                return category
    return "general"


# ── Remember/Recall Patterns ────────────────────────────────────────────────
import re

REMEMBER_PATTERNS = [
    re.compile(r"(?:remember|yaad rakh|yaad rakho|note down|note that|save that|store that)\s+(?:that\s+)?(.+)", re.I),
    re.compile(r"(?:remember)\s+(?:that\s+)?(?:my\s+)(.+?\s+(?:is|are|hai|hain)\s+.+)", re.I),
]

RECALL_PATTERNS = [
    re.compile(r"(?:what(?:'s| is| was))\s+my\s+(.+?)(?:\?|$)", re.I),
    re.compile(r"(?:do you (?:remember|know)|recall|tell me)\s+(?:my\s+)?(.+?)(?:\?|$)", re.I),
    re.compile(r"(?:kya hai mera|mera|meri)\s+(.+?)(?:\?|$)", re.I),
]

FORGET_PATTERNS = [
    re.compile(r"(?:forget|delete|remove|erase)\s+(?:that\s+)?(?:my\s+)?(.+?)(?:\?|$)", re.I),
    re.compile(r"(?:bhul ja|hata de|mita de)\s+(.+?)(?:\?|$)", re.I),
]


class LongTermMemory:
    """Encrypted persistent memory store."""

    def __init__(self) -> None:
        self._memories: List[Dict[str, Any]] = []
        self._fernet: Any = None
        self._init_encryption()
        self._load()

    def _init_encryption(self) -> None:
        """Initialize encryption."""
        if HAS_CRYPTO:
            try:
                key = _get_or_create_key()
                self._fernet = Fernet(key)
            except Exception as e:
                logger.warning(f"[LTM] Encryption init failed: {e}")

    # ── Core API ─────────────────────────────────────────────────────────

    def remember(self, fact: str, category: Optional[str] = None,
                 source: str = "user") -> Dict[str, Any]:
        """Store a fact in long-term memory."""
        if not category:
            category = _detect_category(fact)

        # Check for duplicates (update if exists)
        fact_lower = fact.lower().strip()
        for i, mem in enumerate(self._memories):
            if self._similarity(mem.get("fact", "").lower(), fact_lower) > 0.8:
                # Update existing memory
                self._memories[i]["fact"] = fact
                self._memories[i]["updated_at"] = time.time()
                self._memories[i]["access_count"] = mem.get("access_count", 0) + 1
                self._save()
                logger.info(f"[LTM] Updated: '{fact[:40]}' ({category})")
                return self._memories[i]

        entry = {
            "fact": fact,
            "category": category,
            "source": source,
            "created_at": time.time(),
            "updated_at": time.time(),
            "access_count": 0,
            "tags": self._extract_tags(fact),
        }
        self._memories.append(entry)
        self._save()
        logger.info(f"[LTM] Stored: '{fact[:40]}' ({category})")
        return entry

    def recall(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Search memories by query. Returns best matches."""
        query_lower = query.lower().strip()
        query_words = set(query_lower.split())
        results: List[Tuple[float, Dict[str, Any]]] = []

        for mem in self._memories:
            fact_lower = mem.get("fact", "").lower()
            tags = set(mem.get("tags", []))

            # Score based on word overlap + tag match
            fact_words = set(fact_lower.split())
            word_overlap = len(query_words & fact_words) / max(len(query_words), 1)
            tag_overlap = len(query_words & tags) / max(len(query_words), 1)
            score = word_overlap * 0.6 + tag_overlap * 0.4

            # Boost exact substring match
            if query_lower in fact_lower:
                score += 0.3

            if score > 0.15:
                results.append((score, mem))

        results.sort(key=lambda x: -x[0])
        return [r[1] for r in results[:limit]]

    def forget(self, query: str) -> int:
        """Remove memories matching query. Returns count removed."""
        query_lower = query.lower().strip()
        before = len(self._memories)
        self._memories = [
            m for m in self._memories
            if query_lower not in m.get("fact", "").lower()
        ]
        removed = before - len(self._memories)
        if removed > 0:
            self._save()
            logger.info(f"[LTM] Forgot {removed} memories matching '{query[:30]}'")
        return removed

    def list_all(self, category: Optional[str] = None,
                 limit: int = 20) -> List[Dict[str, Any]]:
        """List all memories, optionally filtered by category."""
        memories = self._memories
        if category:
            memories = [m for m in memories if m.get("category") == category]
        return sorted(memories, key=lambda x: -x.get("updated_at", 0))[:limit]

    @property
    def count(self) -> int:
        return len(self._memories)

    # ── Intent Detection ─────────────────────────────────────────────────

    def is_remember_command(self, text: str) -> Optional[str]:
        """Check if user wants to store something. Returns the fact or None."""
        for pattern in REMEMBER_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1).strip() if match.lastindex and match.lastindex >= 1 else None
        return None

    def is_recall_command(self, text: str) -> Optional[str]:
        """Check if user is asking to recall something. Returns the query or None."""
        for pattern in RECALL_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1).strip() if match.lastindex and match.lastindex >= 1 else None
        return None

    def is_forget_command(self, text: str) -> Optional[str]:
        """Check if user wants to forget something. Returns the query or None."""
        for pattern in FORGET_PATTERNS:
            match = pattern.search(text)
            if match:
                return match.group(1).strip() if match.lastindex and match.lastindex >= 1 else None
        return None

    # ── Helpers ───────────────────────────────────────────────────────────

    def _extract_tags(self, text: str) -> List[str]:
        """Extract searchable tags from text."""
        stop_words = {"is", "are", "was", "were", "my", "the", "a", "an",
                      "that", "this", "it", "for", "to", "in", "on", "at",
                      "hai", "hain", "mera", "meri", "ka", "ki", "ke"}
        words = text.lower().split()
        return [w for w in words if len(w) > 2 and w not in stop_words]

    def _similarity(self, a: str, b: str) -> float:
        """Simple word-overlap similarity."""
        words_a = set(a.split())
        words_b = set(b.split())
        if not words_a or not words_b:
            return 0.0
        overlap = len(words_a & words_b)
        return overlap / max(len(words_a), len(words_b))

    # ── Persistence (encrypted) ──────────────────────────────────────────

    def _save(self) -> None:
        """Save memories (encrypted if available)."""
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            data = json.dumps(self._memories, ensure_ascii=False).encode("utf-8")
            if self._fernet:
                data = self._fernet.encrypt(data)
            with open(MEMORY_FILE, "wb") as f:
                f.write(data)
        except Exception as e:
            logger.warning(f"[LTM] Save failed: {e}")

    def _load(self) -> None:
        """Load memories (decrypt if needed)."""
        if not os.path.exists(MEMORY_FILE):
            return
        try:
            with open(MEMORY_FILE, "rb") as f:
                data = f.read()
            if self._fernet:
                data = self._fernet.decrypt(data)
            self._memories = json.loads(data.decode("utf-8"))
            logger.info(f"[LTM] Loaded {len(self._memories)} memories")
        except Exception as e:
            logger.warning(f"[LTM] Load failed: {e}")
            self._memories = []


# Singleton
long_term_memory = LongTermMemory()
