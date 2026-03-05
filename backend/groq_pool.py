"""
Groq API Key Pool — Round-robin rotation with rate-limit awareness.

Shared module importable from main.py and all handler threads
without circular import issues.
"""

import os
import time
import logging

log = logging.getLogger("alita.groq_pool")


class GroqKeyRotator:
    """Rotates between multiple Groq API keys to avoid rate limits (30 RPM each)."""

    def __init__(self, keys: list[str]):
        self.keys = [k for k in keys if k] if keys else []
        self.index = 0
        self._rate_limited: dict[str, float] = {}  # key → cooldown_expires_at

    def get_key(self) -> str:
        """Get the next available Groq API key, skipping rate-limited ones."""
        if not self.keys:
            return ""
        now = time.time()
        for _ in range(len(self.keys)):
            key = self.keys[self.index % len(self.keys)]
            self.index += 1
            # Skip rate-limited keys
            if key in self._rate_limited and self._rate_limited[key] > now:
                continue
            self._rate_limited.pop(key, None)  # expired cooldown
            return key
        # All keys rate-limited — return the least-recently-limited one
        return self.keys[self.index % len(self.keys)]

    def mark_rate_limited(self, key: str, cooldown_seconds: int = 60):
        """Mark a key as rate-limited with a cooldown period."""
        self._rate_limited[key] = time.time() + cooldown_seconds
        log.info("Groq key ...%s rate-limited for %ds", key[-8:], cooldown_seconds)

    @property
    def available(self) -> bool:
        """True if at least one key is configured."""
        return bool(self.keys)


def _load_keys_from_env() -> list[str]:
    """Load all GROQ_API_KEY* from environment."""
    keys = []
    for var in ["GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4"]:
        val = os.environ.get(var, "").strip()
        if val:
            keys.append(val)
    return keys


# Module-level singleton — loaded once on import
_rotator: GroqKeyRotator | None = None


def get_rotator() -> GroqKeyRotator:
    """Get or create the global GroqKeyRotator singleton."""
    global _rotator
    if _rotator is None:
        keys = _load_keys_from_env()
        _rotator = GroqKeyRotator(keys)
        log.info("Groq pool initialized: %d keys loaded", len(keys))
    return _rotator
