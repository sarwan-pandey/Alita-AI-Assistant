"""
Alita Core Package
"""

def __getattr__(name: str):
    if name in ("settings", "Settings"):
        from .config import settings, Settings
        return settings if name == "settings" else Settings
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
from .auth import require_auth, require_admin
from .tier import get_tier, set_tier
from .session_manager import SessionRecord, SessionManager, session_manager

__all__ = [
    "settings",
    "Settings",
    "require_auth",
    "require_admin",
    "get_tier",
    "set_tier",
    "SessionRecord",
    "SessionManager",
    "session_manager",
]
