"""
test_security_vault.py — Test Security Vault Confirmation State Persistence and Multi-Turn TTL
"""

import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from engines.security_vault import security_vault


def test_sensitive_action_confirmation_lifecycle():
    """Test 10: Full confirmation lifecycle across user turns."""
    session_state = {}

    # Turn 1: User requests sensitive action ("Unlock my phone")
    res1 = security_vault.check_sensitive_action_intent(
        instruction="Unlock my phone",
        session_state=session_state,
        device_model="Realme RMX5030",
    )
    assert res1.is_sensitive is True
    assert res1.needs_confirmation is True
    assert "Realme RMX5030" in (res1.confirmation_prompt or "")
    assert session_state.get("pending_confirmation") is not None
    assert session_state["pending_confirmation"]["action_type"] == "unlock"

    # Turn 2: User affirmatively confirms ("yes proceed")
    res2 = security_vault.check_sensitive_action_intent(
        instruction="yes proceed",
        session_state=session_state,
        device_model="Realme RMX5030",
    )
    assert res2.is_sensitive is True
    assert res2.needs_confirmation is False
    assert res2.details.get("confirmed") is True
    assert session_state.get("pending_confirmation") is None  # Cleared after confirmation

    # Turn 3: User cancels another sensitive action ("Send message to John", then "cancel")
    res3 = security_vault.check_sensitive_action_intent(
        instruction="Send message to John on WhatsApp that I am delayed",
        session_state=session_state,
        device_model="Realme RMX5030",
    )
    assert res3.needs_confirmation is True
    assert session_state.get("pending_confirmation") is not None

    res4 = security_vault.check_sensitive_action_intent(
        instruction="cancel",
        session_state=session_state,
        device_model="Realme RMX5030",
    )
    assert res4.action_type == "cancelled"
    assert res4.details.get("cancelled") is True
    assert session_state.get("pending_confirmation") is None

    # Turn 4: Confirmation TTL expiration (> 120s)
    security_vault.check_sensitive_action_intent(
        instruction="Unlock my phone",
        session_state=session_state,
    )
    assert session_state.get("pending_confirmation") is not None
    # Artificially age the timestamp by 125 seconds
    session_state["pending_confirmation"]["created_at"] = time.time() - 125.0

    # User answers "yes" after expiration -> treated as fresh non-sensitive chat, pending cleared
    res5 = security_vault.check_sensitive_action_intent(
        instruction="yes",
        session_state=session_state,
    )
    assert res5.needs_confirmation is False
    assert res5.is_sensitive is False
    assert session_state.get("pending_confirmation") is None

    print("✅ Test 10 Passed: Security Vault multi-turn confirmation lifecycle & TTL expiration verified")


def test_tricky_hindi_affirmative_and_negative_matching():
    """Tricky 1: Hindi/Hinglish confirmations ('haan bhai' / 'nahi rehne do') recognized."""
    session = {}

    # Setup pending unlock
    security_vault.check_sensitive_action_intent("Unlock my phone", session)
    assert session.get("pending_confirmation") is not None

    # Confirm with Hindi affirmative: "haan kardo"
    res = security_vault.check_sensitive_action_intent("haan kardo", session)
    assert res.is_sensitive is True
    assert res.details.get("confirmed") is True
    assert session.get("pending_confirmation") is None

    # Setup pending message
    security_vault.check_sensitive_action_intent("Send message on WhatsApp to Rahul", session)
    assert session.get("pending_confirmation") is not None

    # Cancel with Hindi negative: "nahi rehne do"
    res_cancel = security_vault.check_sensitive_action_intent("nahi rehne do", session)
    assert res_cancel.action_type == "cancelled"
    assert res_cancel.details.get("cancelled") is True
    assert session.get("pending_confirmation") is None
    print("✅ Tricky Test 1 Passed: Hindi affirmative and cancellation phrases cleanly parsed")


def test_tricky_unrelated_query_no_accidental_confirmation():
    """Tricky 2: Unrelated query containing 'yes' substring (e.g. 'yesterday') does NOT trigger confirmation."""
    session = {}
    security_vault.check_sensitive_action_intent("Unlock my phone", session)
    assert session.get("pending_confirmation") is not None

    # User says "yesterday was sunny" (starts with yesterday, NOT "yes ")
    res = security_vault.check_sensitive_action_intent("yesterday was sunny in Delhi", session)
    assert res.details.get("confirmed") is not True
    assert res.is_sensitive is False
    print("✅ Tricky Test 2 Passed: Substring words like 'yesterday' immune to false affirmative triggers")


def test_tricky_destructive_and_payment_action_warning():
    """Tricky 3: Destructive and payment actions trigger specialized high-severity warnings."""
    res_pay = security_vault.check_sensitive_action_intent(
        "pay 500 rupees via GPay",
        session_state={},
        device_model="Realme",
    )
    assert res_pay.is_sensitive is True
    assert res_pay.action_type == "payment"
    assert "Payment command detected" in res_pay.confirmation_prompt

    res_wipe = security_vault.check_sensitive_action_intent(
        "factory reset my phone and wipe storage",
        session_state={},
        device_model="Realme",
    )
    assert res_wipe.is_sensitive is True
    assert res_wipe.action_type == "destructive"
    assert "Destructive action detected" in res_wipe.confirmation_prompt
    print("✅ Tricky Test 3 Passed: Payment & destructive operations trigger high-severity prompts")


if __name__ == "__main__":
    test_sensitive_action_confirmation_lifecycle()
    test_tricky_hindi_affirmative_and_negative_matching()
    test_tricky_unrelated_query_no_accidental_confirmation()
    test_tricky_destructive_and_payment_action_warning()
    print("\n🎉 ALL 4 SECURITY VAULT TESTS (INCLUDING TRICKY TESTS) PASSED!")
