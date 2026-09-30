"""
Ephemeral Memory Store
======================
Thread-safe, in-memory, time-to-live (TTL) cache for transient conversation turns,
intermediate reasoning state, and active tool context.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


class EphemeralMemoryStore:
    """In-memory key-value cache with automatic TTL expiration."""

    def __init__(self, default_ttl_seconds: float = 300.0) -> None:
        self.default_ttl = default_ttl_seconds
        self._store: Dict[str, Tuple[Any, float]] = {}  # key -> (value, expiry_timestamp)
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, ttl: Optional[float] = None, ttl_seconds: Optional[float] = None) -> None:
        """Store a value with an expiration timestamp."""
        effective_ttl = ttl if ttl is not None else ttl_seconds
        duration = self.default_ttl if effective_ttl is None else effective_ttl
        expiry = time.time() + duration
        with self._lock:
            self._store[key] = (value, expiry)

    def get(self, key: str, default: Any = None) -> Any:
        """Retrieve a value if not expired; otherwise remove it and return default."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return default
            val, expiry = entry
            if time.time() > expiry:
                del self._store[key]
                return default
            return val

    def pop(self, key: str, default: Any = None) -> Any:
        """Retrieve and immediately remove a value."""
        with self._lock:
            entry = self._store.pop(key, None)
            if entry is None:
                return default
            val, expiry = entry
            if time.time() > expiry:
                return default
            return val

    def delete(self, key: str) -> bool:
        """Remove a key if present."""
        with self._lock:
            return self._store.pop(key, None) is not None

    def clear(self) -> None:
        """Flush all entries."""
        with self._lock:
            self._store.clear()

    def prune_expired(self) -> int:
        """Remove all expired entries and return the count removed."""
        now = time.time()
        removed = 0
        with self._lock:
            expired_keys = [k for k, (_, exp) in self._store.items() if now > exp]
            for k in expired_keys:
                del self._store[k]
                removed += 1
        return removed


# Global singleton instance
ephemeral_memory = EphemeralMemoryStore()
