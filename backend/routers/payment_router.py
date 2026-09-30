"""
Payment & Subscription Router — Razorpay Checkout & Webhooks
============================================================
Handles /payments/create-checkout-session, /payments/status, and /webhooks/razorpay.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

log = logging.getLogger("alita.payment_router")

payment_router = APIRouter(tags=["Payments"])


class CheckoutRequest(BaseModel):
    plan: str = "monthly"  # "monthly" | "annual"


@payment_router.post("/payments/create-checkout-session")
async def create_checkout_session(req: CheckoutRequest, request: Request):
    """
    Create a Razorpay subscription and return checkout data.
    Requires Authorization: Bearer <JWT> header.
    """
    from auth_deps import require_auth
    user = await require_auth(request)
    user_id = user["user_id"]

    import main
    settings = getattr(main, "settings", None)
    razorpay_client = getattr(main, "razorpay_client", None)

    if req.plan not in ("monthly", "annual"):
        raise HTTPException(status_code=400, detail="Plan must be 'monthly' or 'annual'.")

    if not razorpay_client:
        raise HTTPException(
            status_code=500,
            detail="Razorpay not configured. Set RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET in .env."
        )

    plan_id = (
        settings.razorpay_plan_monthly if req.plan == "monthly"
        else settings.razorpay_plan_annual
    )

    if not plan_id:
        raise HTTPException(
            status_code=500,
            detail=f"Razorpay Plan ID for '{req.plan}' not configured."
        )

    try:
        subscription = razorpay_client.subscription.create({
            "plan_id": plan_id,
            "total_count": 12 if req.plan == "monthly" else 1,
            "quantity": 1,
            "notes": {
                "user_id": user_id,
                "plan": req.plan,
            },
        })
        log.info("Razorpay subscription created: user=%s plan=%s sub_id=%s",
                 user_id, req.plan, subscription.get("id"))
        return JSONResponse({
            "subscription_id": subscription.get("id"),
            "razorpay_key_id": settings.razorpay_key_id,
            "plan": req.plan,
            "amount": 9900 if req.plan == "monthly" else 110000,
            "currency": "USD",
            "name": "MJ Premium",
            "description": f"MJ Premium — {'Monthly' if req.plan == 'monthly' else 'Annual'} Subscription",
        })
    except Exception as exc:
        log.error("Razorpay subscription error: %s", exc)
        raise HTTPException(status_code=502, detail=f"Razorpay error: {str(exc)}")


@payment_router.get("/payments/status")
async def payment_status(request: Request):
    """Check current subscription tier for authenticated user."""
    from auth_deps import require_auth
    user = await require_auth(request)
    return {
        "user_id": user["user_id"],
        "tier": user.get("tier", "free"),
    }


@payment_router.post("/webhooks/razorpay", status_code=200)
async def razorpay_webhook(request: Request):
    """Cryptographically verified webhook handler for Razorpay subscription events."""
    from tier_store import set_tier as _set_tier
    import main
    settings = getattr(main, "settings", None)
    razorpay_client = getattr(main, "razorpay_client", None)

    payload = await request.body()
    sig_header = request.headers.get("x-razorpay-signature", "")

    try:
        if razorpay_client and settings.razorpay_webhook_secret:
            razorpay_client.utility.verify_webhook_signature(
                payload.decode("utf-8"), sig_header, settings.razorpay_webhook_secret
            )
    except Exception as exc:
        log.warning("Razorpay webhook invalid signature: %s", exc)
        raise HTTPException(status_code=400, detail="Invalid signature.")

    body = json.loads(payload)
    event_type = body.get("event", "")
    log.info("Razorpay event received: %s", event_type)

    entity = body.get("payload", {}).get("subscription", {}).get("entity", {})

    if event_type in ("subscription.activated", "subscription.charged"):
        user_id = entity.get("notes", {}).get("user_id", "")
        plan = entity.get("notes", {}).get("plan", "monthly")
        if user_id:
            log.info("Upgrading user=%s to premium | plan=%s", user_id, plan)
            _set_tier(user_id=user_id, tier="premium", plan=plan, subscription_id=entity.get("id", ""))
    elif event_type in ("subscription.cancelled", "subscription.completed"):
        user_id = entity.get("notes", {}).get("user_id", "")
        if user_id:
            log.info("Downgrading user=%s to free", user_id)
            _set_tier(user_id=user_id, tier="free", plan="free", subscription_id="")

    return {"status": "ok"}
