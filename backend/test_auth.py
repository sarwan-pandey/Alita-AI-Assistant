"""
test_auth.py — Drop into backend/ folder.
Provides a /auth/test-login endpoint for beta testers.

HOW IT WORKS:
  - Test account password hashes are loaded from environment variables
  - Tester visits the login page, clicks "Beta Access", enters credentials
  - Backend returns a real signed JWT valid for 24 hours
  - JWT is accepted by the main WebSocket auth (same decode_supabase_jwt logic)

SECURITY:
  - Set DISABLE_TEST_AUTH=true in production to completely disable this endpoint
  - Tokens expire after 24 hours
  - Signed with SUPABASE_JWT_SECRET so they pass the same HS256 verification
  - Rate limited: max 5 attempts per IP per minute
  - Password hashes are stored in env vars, NOT in source code

SETUP (one-time):
  1. Pick usernames and passwords for testers
  2. Generate SHA-256 hashes:
     python -c "import hashlib; print(hashlib.sha256(b'YourPassword').hexdigest())"
  3. Set environment variables:
     TEST_USER_BETA01_HASH=<sha256 hash>
     TEST_USER_BETA01_TIER=premium
     TEST_USER_DEMO_HASH=<sha256 hash>
     TEST_USER_DEMO_TIER=free
  4. Share username + original password with tester (NOT the hash)
"""

import os
import time
import hashlib
import secrets
from collections import defaultdict
from typing import Dict

from fastapi import APIRouter, HTTPException, Request, status
from jose import jwt
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────────────────
# TEST USER ACCOUNTS — loaded from environment variables
# Format: TEST_USER_<USERNAME>_HASH = sha256 hex digest of password
#         TEST_USER_<USERNAME>_TIER = "free" or "premium"
#         TEST_USER_<USERNAME>_NAME = display name (optional)
# ─────────────────────────────────────────────────────────────────────────────
def _load_test_users() -> Dict[str, dict]:
    """Load test user accounts from environment variables."""
    users: Dict[str, dict] = {}
    # Scan environment for TEST_USER_*_HASH patterns
    seen_usernames = set()
    for key, value in os.environ.items():
        if key.startswith("TEST_USER_") and key.endswith("_HASH"):
            username = key[10:-5].lower()  # TEST_USER_BETA01_HASH → beta01
            seen_usernames.add(username)
            users[username] = {
                "password_hash": value.strip(),
                "tier": os.getenv(f"TEST_USER_{username.upper()}_TIER", "free"),
                "display_name": os.getenv(f"TEST_USER_{username.upper()}_NAME", f"Tester {username}"),
            }
    return users

TEST_USERS: Dict[str, dict] = _load_test_users()

# ─────────────────────────────────────────────────────────────────────────────
# Rate limiter — simple in-memory (5 attempts per IP per 60 seconds)
# ─────────────────────────────────────────────────────────────────────────────
_attempt_log: dict = defaultdict(list)

def _check_rate_limit(ip: str) -> None:
    now     = time.time()
    window  = 60
    max_att = 5
    # Clean old entries
    _attempt_log[ip] = [t for t in _attempt_log[ip] if now - t < window]
    if len(_attempt_log[ip]) >= max_att:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Wait 60 seconds.",
        )
    _attempt_log[ip].append(now)


# ─────────────────────────────────────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────────────────────────────────────
test_auth_router = APIRouter(prefix="/auth", tags=["test-auth"])


class TestLoginRequest(BaseModel):
    username: str
    password: str


class TestLoginResponse(BaseModel):
    access_token: str
    token_type:   str = "bearer"
    tier:         str
    display_name: str
    expires_in:   int = 86400  # 24 hours


@test_auth_router.post("/test-login", response_model=TestLoginResponse)
async def test_login(body: TestLoginRequest, request: Request):
    """
    Authenticate a beta tester and return a signed JWT.
    The JWT is accepted by the main /ws WebSocket endpoint.
    Disabled when DISABLE_TEST_AUTH=true is set in environment.
    """
    # ── Production kill switch ────────────────────────────────────────
    if os.getenv("DISABLE_TEST_AUTH", "").lower() in ("true", "1", "yes"):
        raise HTTPException(status_code=404, detail="Not found")

    # Get client IP for rate limiting
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    # Normalise username
    username = body.username.strip().lower()

    # Reload users in case env vars changed (hot-reload friendly)
    current_users = _load_test_users() if not TEST_USERS else TEST_USERS

    # Look up user
    user = current_users.get(username)
    if not user:
        # Constant-time compare even for missing user (prevents username enumeration)
        secrets.compare_digest("dummy", "hash")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    # Verify password
    submitted_hash = hashlib.sha256(body.password.encode()).hexdigest()
    if not secrets.compare_digest(submitted_hash, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password.",
        )

    # Import settings from main.py context
    try:
        from main import settings
        jwt_secret = settings.supabase_jwt_secret
    except Exception:
        jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "")
        if not jwt_secret:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Server configuration error.",
            )

    now = int(time.time())

    # Build JWT payload that matches the expected shape in decode_supabase_jwt()
    payload = {
        "sub":          f"test_{username}",          # user_id
        "email":        f"{username}@aura.test",
        "role":         "authenticated",
        "iss":          "https://test.supabase.co",
        "iat":          now,
        "exp":          now + 86400,                 # 24h expiry
        "tier":         user["tier"],
        "is_test_user": True,
    }

    token = jwt.encode(payload, jwt_secret, algorithm="HS256")

    return TestLoginResponse(
        access_token=token,
        tier=user["tier"],
        display_name=user["display_name"],
    )