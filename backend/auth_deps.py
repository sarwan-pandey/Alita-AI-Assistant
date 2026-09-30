"""
auth_deps.py — Reusable FastAPI authentication dependencies
=============================================================
Provides `require_auth()` and `require_admin()` to protect endpoints
against unauthenticated access and IDOR vulnerabilities.

Usage:
    from auth_deps import require_auth, require_admin

    @router.get("/my-data")
    async def my_data(user: dict = Depends(require_auth)):
        user_id = user["user_id"]
        ...

    @router.post("/admin/action")
    async def admin_action(request: Request, _=Depends(require_admin)):
        ...
"""

from __future__ import annotations

import hmac
import logging
from typing import Any, Dict

from fastapi import HTTPException, Request, status  # type: ignore[import-untyped]

log = logging.getLogger("Alita.auth")


def _extract_token(request: Request) -> str:
    """
    Extract JWT token from Authorization header or query param.
    Supports:
      - Authorization: Bearer <token>
      - ?token=<token>
    """
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header.split(" ", 1)[1]

    # Fallback to query param (for GET endpoints)
    token = request.query_params.get("token", "")
    if token:
        return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing authentication. Provide Authorization: Bearer <token> header.",
    )


async def require_auth(request: Request) -> Dict[str, Any]:
    """
    FastAPI dependency — verifies JWT and returns user claims.

    Returns dict with: user_id, email, role

    Usage:
        @router.get("/protected")
        async def endpoint(user: dict = Depends(require_auth)):
            user_id = user["user_id"]
    """
    token = _extract_token(request)

    # Import decode function from main (avoids circular imports)
    from main import decode_supabase_jwt, get_user_tier  # type: ignore[import]

    try:
        claims = decode_supabase_jwt(token)
    except HTTPException:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token.",
        )

    # Add tier to claims for convenience
    claims["tier"] = get_user_tier(claims["user_id"])
    return claims


async def require_admin(request: Request) -> None:
    """
    FastAPI dependency — requires X-Admin-Secret header.

    Usage:
        @router.post("/admin/action")
        async def endpoint(_=Depends(require_admin)):
    """
    from main import settings  # type: ignore[import]

    admin_secret = request.headers.get("X-Admin-Secret", "")
    if not admin_secret or not hmac.compare_digest(admin_secret, settings.admin_secret):
        ip = request.client.host if request.client else "unknown"
        log.warning("Unauthorized admin access attempt from %s", ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden.",
        )
