"""
Core Auth Module — Re-exports authentication dependencies and security helpers.
"""

from auth_deps import (
    require_auth,
    require_admin,
    _extract_token,
)

__all__ = [
    "require_auth",
    "require_admin",
    "_extract_token",
]
