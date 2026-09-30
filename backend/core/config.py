"""
Core Config Module — Re-exports application settings.
Uses dynamic attribute resolution to prevent circular import crashes during startup.
"""

from __future__ import annotations
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from main import settings as _settings_type, Settings as _Settings_type


def get_settings() -> Any:
    """Safely retrieves the singleton settings instance from main or environment."""
    try:
        import main
        return main.settings
    except ImportError:
        return None


def __getattr__(name: str) -> Any:
    if name in ("settings", "Settings"):
        import main
        return getattr(main, name)
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


__all__ = [
    "settings",
    "Settings",
    "get_settings",
]
