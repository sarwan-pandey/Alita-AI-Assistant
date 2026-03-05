"""
test_auth.py — Drop into backend/ folder.
Provides a /auth/test-login endpoint for beta testers.

HOW IT WORKS:
  - You define test accounts in TEST_USERS dict below (ID + password)
  - Tester visits the login page, clicks "Beta Access", enters credentials
  - Backend returns a real signed JWT valid for 24 hours
  - JWT is accepted by the main WebSocket auth (same decode_supabase_jwt logic)
  - You can grant premium tier to specific testers

SECURITY:
  - Tokens expire after 24 hours
  - Signed with SUPABASE_JWT_SECRET so they pass the same HS256 verification
  - No Supabase or Google account needed
  - Rate limited: max 5 attempts per IP per minute

ADDING TESTERS:
  - Add entries to TEST_USERS below
  - Use strong random passwords (share via WhatsApp/Signal, not email)
  - Set tier to "premium" for premium access testers

HOW TO USE:
  Add this line to main.py imports:
    from test_auth import test_auth_router
  Add this line after app = FastAPI(...):
    app.include_router(test_auth_router)
"""

import time
import hashlib
import secrets
from collections import defaultdict
from typing import Dict

from fastapi import APIRouter, HTTPException, Request, status
from jose import jwt
from pydantic import BaseModel

# ─────────────────────────────────────────────────────────────────────────────
# TEST USER ACCOUNTS
# Format: "username": {"password_hash": sha256(password), "tier": "free"|"premium"}
#
# To add a tester:
#   1. Pick a username (e.g. "tester1") and password (e.g. "Aura#2024!")
#   2. Generate hash: python -c "import hashlib; print(hashlib.sha256(b'Aura#2024!').hexdigest())"
#   3. Add entry below
#   4. Share username + original password with your tester (NOT the hash)
#
# Pre-built test accounts (change passwords before sharing!):
#
#   username: beta01  |  password: AuraBeta@01  |  tier: premium
#   username: beta02  |  password: AuraBeta@02  |  tier: premium
#   username: demo    |  password: AuraDemo#99  |  tier: free
# ─────────────────────────────────────────────────────────────────────────────
TEST_USERS: Dict[str, dict] = {
    "beta01": {
        "password_hash": hashlib.sha256(b"AuraBeta@01").hexdigest(),
        "tier":          "premium",
        "display_name":  "Beta Tester 1",
    },
    "beta02": {
        "password_hash": hashlib.sha256(b"AuraBeta@02").hexdigest(),
        "tier":          "premium",
        "display_name":  "Beta Tester 2",
    },
    "beta03": {
        "password_hash": hashlib.sha256(b"AuraBeta@03").hexdigest(),
        "tier":          "premium",
        "display_name":  "Beta Tester 3",
    },
    "demo": {
        "password_hash": hashlib.sha256(b"AuraDemo#99").hexdigest(),
        "tier":          "free",
        "display_name":  "Demo User",
    },
}

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
    """
    # Get client IP for rate limiting
    ip = request.client.host if request.client else "unknown"
    _check_rate_limit(ip)

    # Normalise username
    username = body.username.strip().lower()

    # Look up user
    user = TEST_USERS.get(username)
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
    # (test_auth.py is imported by main.py so settings is accessible)
    try:
        from main import settings
        jwt_secret = settings.supabase_jwt_secret
    except Exception:
        import os
        jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "placeholder")

    now = int(time.time())

    # Build JWT payload that matches the expected shape in decode_supabase_jwt()
    payload = {
        "sub":          f"test_{username}",          # user_id
        "email":        f"{username}@aura.test",
        "role":         "authenticated",
        "iss":          "https://test.supabase.co",  # iss must contain supabase.co
        "iat":          now,
        "exp":          now + 86400,                 # 24h expiry
        "tier":         user["tier"],                # passed through for convenience
        "is_test_user": True,
    }

    token = jwt.encode(payload, jwt_secret, algorithm="HS256")

    return TestLoginResponse(
        access_token=token,
        tier=user["tier"],
        display_name=user["display_name"],
    )


@test_auth_router.get("/test-users")
async def list_test_users():
    """
    Returns list of test usernames (no passwords/hashes).
    ONLY available in development (set DEBUG=1 in .env).
    """
    import os
    if not os.getenv("DEBUG", ""):
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "users": [
            {"username": u, "tier": v["tier"], "display_name": v["display_name"]}
            for u, v in TEST_USERS.items()
        ]
    }