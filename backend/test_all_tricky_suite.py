"""
test_all_tricky_suite.py — Master Runner for All Tricky Edge-Case & Perception Tests
"""

import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import test_action_executor
import test_screen_reading
import test_interruption_handler
import test_task_planner
import test_security_vault
import test_credential_security


def run_master_tricky_suite():
    print("\n" + "=" * 65)
    print("      🚀 EXECUTING ALITA PHONE AUTOMATION TRICKY TEST SUITE")
    print("=" * 65 + "\n")

    tests = [
        # Interruption Handler (10 tests)
        ("Interruption: Standard Permission Auto-Dismissal", test_interruption_handler.test_known_popup_auto_dismissal),
        ("Interruption: Unrecognized Dialog Pauses Task", test_interruption_handler.test_unrecognized_dialog_surfaced_without_guessing),
        ("Interruption: Realme/ColorOS OEM Popup Resiliency", test_interruption_handler.test_tricky_coloros_realme_oem_popup),
        ("Interruption: Chat Screen Keyword False-Positive Immunity", test_interruption_handler.test_tricky_false_positive_prevention_on_normal_chat),
        ("Interruption: System ANR Crash Alert Isolation", test_interruption_handler.test_tricky_system_anr_crash_dialog),
        ("Interruption: Article Discussing Crashes (ANR Immunity)", test_interruption_handler.test_tricky_article_reading_crash_text_not_anr),
        ("Interruption: Accessible Button ContentDescription Match", test_interruption_handler.test_tricky_content_description_only_button),
        ("Interruption: Disabled Button Fallback Selection", test_interruption_handler.test_tricky_disabled_button_fallback),
        ("Interruption: Malformed/Dirty View-Tree Crash-Proofing", test_interruption_handler.test_tricky_malformed_and_dirty_tree_resilience),
        ("Interruption: Play Protect Warning Sideload Target", test_interruption_handler.test_tricky_play_protect_blocked_dialog),

        # Action Executor (5 tests)
        ("Executor: 150ms Early Polling Verification", test_action_executor.test_action_executor_early_polling_success),
        ("Executor: Exact Max Retries & State Reporting", test_action_executor.test_action_executor_retry_and_failure_reporting),
        ("Executor: Already In Target State Short-Circuiting", test_action_executor.test_tricky_already_in_expected_state_short_circuit),
        ("Executor: Interruption Self-Healing Mid-Flight", test_action_executor.test_tricky_interruption_auto_recovery_during_action),
        ("Executor: Network Transport Exception Recovery", test_action_executor.test_tricky_network_exception_recovery),

        # Screen Perception (5 tests)
        ("Perception: View-Tree Node Extraction & Bounds", test_screen_reading.test_screen_reading_node_extraction),
        ("Perception: Sparse Tree Automatic Fallback", test_screen_reading.test_screen_reading_fallback),
        ("Perception: Fuzzy Node Search with Clickable Filter", test_screen_reading.test_tricky_fuzzy_search_content_desc_and_clickable_filter),
        ("Perception: Disconnected Device Safe Degradation", test_screen_reading.test_tricky_disconnected_device_safety),
        ("Perception: Malformed Tree Resilience", test_screen_reading.test_tricky_malformed_nodes_resilience),

        # Task Planner (5 tests)
        ("Planner: Complex Step Decomposition", test_task_planner.test_task_planner_step_decomposition),
        ("Planner: Verified Step Execution with Live Narration", test_task_planner.test_task_planner_execution_with_narration),
        ("Planner: Hindi/Hinglish Messaging Phrasing", test_task_planner.test_tricky_hindi_hinglish_messaging),
        ("Planner: Skip Redundant Launch If Foreground", test_task_planner.test_tricky_skip_launch_if_already_foreground),
        ("Planner: Mid-Workflow Failure Immediate Halt", test_task_planner.test_tricky_mid_workflow_failure_halts_immediately),

        # Security Vault (4 tests)
        ("Vault: Multi-Turn Lifecycle & 120s TTL", test_security_vault.test_sensitive_action_confirmation_lifecycle),
        ("Vault: Hindi Affirmative/Negative Phrasing", test_security_vault.test_tricky_hindi_affirmative_and_negative_matching),
        ("Vault: Substring False-Trigger Immunity ('yesterday')", test_security_vault.test_tricky_unrelated_query_no_accidental_confirmation),
        ("Vault: Payment & Destructive Warning Escalation", test_security_vault.test_tricky_destructive_and_payment_action_warning),

        # Credential Security (2 tests)
        ("Security: Zero Plaintext Credentials in Backend Code", test_credential_security.test_no_plaintext_credentials_in_backend_code),
        ("Security: Clean Keyguard Unlock Payload", test_credential_security.test_unlock_command_payload_has_no_credential),
    ]

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            test_fn()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"❌ FAILED: {name} — {e}")

    print("\n" + "=" * 65)
    print(f"  🏁 RESULTS: {passed}/{len(tests)} PASSED | {failed} FAILED")
    print("=" * 65 + "\n")

    if failed > 0:
        sys.exit(1)
    else:
        print("🌟 ALL 31 EMPIRICAL TRICKY & CLOSED-LOOP TESTS PASSED SUCCESSFULLY!\n")


if __name__ == "__main__":
    run_master_tricky_suite()
