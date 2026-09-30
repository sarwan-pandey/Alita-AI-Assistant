"""
Tier Store — File-backed user tier persistence.

Stores user tiers in data/user_tiers.json with an in-memory cache.
Thread-safe. Auto-creates data directory if missing.

Usage:
    from tier_store import get_tier, set_tier

    tier = get_tier("user-uuid")           # → "free" | "premium"
    set_tier("user-uuid", "premium")       # persists immediately
"""

import json
import logging
import os
import threading
from typing import Any, Optional

log = logging.getLogger("Alita.tier_store")

_DATA_DIR  = os.path.join(os.path.dirname(__file__), "data")
_TIER_FILE = os.path.join(_DATA_DIR, "user_tiers.json")

_lock  = threading.Lock()
_cache: dict[str, dict] = {}   # user_id → {"tier": "free"|"premium", "plan": ..., "updated_at": ...}


def _load() -> None:
    """Load tiers from disk into memory cache."""
    global _cache
    if not os.path.exists(_TIER_FILE):
        _cache = {}
        return
    try:
        with open(_TIER_FILE, "r", encoding="utf-8") as f:
            _cache = json.load(f)
        log.info("Loaded %d user tier(s) from %s", len(_cache), _TIER_FILE)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Failed to load tier store (%s) — starting empty.", exc)
        _cache = {}


def _save() -> None:
    """Persist memory cache to disk. Must be called under _lock."""
    os.makedirs(_DATA_DIR, exist_ok=True)
    try:
        with open(_TIER_FILE, "w", encoding="utf-8") as f:
            json.dump(_cache, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        log.error("Failed to save tier store: %s", exc)


def get_tier(user_id: str) -> str:
    """
    Get the tier for a user.
    Returns "free" if user has no stored tier.
    Test/beta users (user_id starts with "test_") always get "premium".
    """
    if user_id.startswith("test_"):
        return "premium"
    with _lock:
        entry = _cache.get(user_id)
        if entry:
            return entry.get("tier", "free")
    return "free"


def set_tier(
    user_id: str,
    tier: str,
    plan: str = "",
    razorpay_customer_id: str = "",
    subscription_id: str = "",
    **kwargs: Any,
) -> None:
    """
    Set the tier for a user and persist to disk.
    """
    from datetime import datetime, timezone
    with _lock:
        _cache[user_id] = {
            "tier": tier,
            "plan": plan,
            "razorpay_customer_id": razorpay_customer_id or subscription_id,
            "subscription_id": subscription_id or razorpay_customer_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        _save()
    log.info("Tier updated: user=%s → %s (plan=%s)", user_id, tier, plan)


def get_all_tiers() -> dict:
    """Return a copy of all stored tiers (for admin/debug)."""
    with _lock:
        return dict(_cache)


def find_user_by_razorpay_customer(razorpay_customer_id: str) -> str | None:
    """Look up a user_id by their Razorpay customer ID."""
    with _lock:
        for user_id, entry in _cache.items():
            if entry.get("razorpay_customer_id") == razorpay_customer_id:
                return user_id
    return None


# ── Load on import ────────────────────────────────────────────────────────────
_load()
